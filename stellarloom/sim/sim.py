"""Simulation：服务器端核心（M6.24 架构分层）。

服务器端 = 全部游戏逻辑，headless、零 pygame：
- 世界集合（每行星一套网络）、恒星级科技/戴森云、玩家背包、手搓队列；
- step(dt) 推进所有模拟；
- 指令 API（放置/拆除/手搓/切星）——前端把输入翻成指令；
- 事件流（toast/成就/脏格子）——前端帧末拉取渲染。

前端（Game）只做：读 sim 状态渲染，转发输入，展示事件。
"""

from __future__ import annotations

import contextlib

import numpy as np

from .. import config as C
from ..core.worldstate import WorldState
from ..logistics.dyson import DysonNetwork
from ..logistics.pads import Fleet
from ..save import SaveManager
from ..tech import TechTree
from ..world.planets import PLANETS
from .craft_queue import CraftQueue


class Simulation:
    """可运行的游戏内核。不 import pygame，可 headless 推进。"""

    def __init__(self):
        self.tech = TechTree()
        self.dyson = DysonNetwork(None)
        self.dyson.bind(self.tech)
        self.inventory: dict[int, int] = dict(C.STARTING_ITEMS)
        self.saves = SaveManager()

        # 手搓队列（材料排队时即扣，产出按配方时长推进）
        self.craft = CraftQueue(self.inventory)

        # 世界集合：生成全部可殖民行星
        self.worlds: list[WorldState] = []
        self.world_index = 0
        self._belts_dirty = False
        for pdef in PLANETS:
            self._spawn_world(pdef)
        # M5b：恒星级运输船队（跨行星）
        self.fleet = Fleet()
        self.activate_world(0)

        # 事件流：前端帧末 pop_events() 拉取
        self._events: list[tuple] = []
        # 脏格子：本帧内逻辑改动过的格子，前端据此刷新 chunk 缓存
        self._dirty_cells: list[tuple[int, int]] = []
        # M15a：旁路订阅者（联机服务端要和本地渲染同时拿到事件/脏格）
        self._event_sinks: list = []
        self._dirty_sinks: list = []

    # ---------- 世界 ----------

    def _spawn_world(self, pdef):
        ws = WorldState(pdef, self.tech, self.dyson, self._on_belts_changed)
        self.worlds.append(ws)
        return ws

    def ensure_world(self, i: int):
        """要读档的行星不存在就按配置生成（存档可能含 PLANETS 之外更多行星）。"""
        while len(self.worlds) <= i:
            self._spawn_world(PLANETS[len(self.worlds) % len(PLANETS)])

    def activate_world(self, i: int):
        """把第 i 颗行星的组件挂回 sim 同名属性（逻辑侧；渲染侧另由前端同步）。"""
        if not (0 <= i < len(self.worlds)):
            return
        if self._belts_dirty:
            self.belts.rebuild()
            self._belts_dirty = False
        ws = self.worlds[i]
        self.world_index = i
        self.grid = ws.grid
        self.planet = ws.planet
        self.belts = ws.belts
        self.camera = ws.camera
        self.machines = ws.machines
        self.miners = ws.miners
        self.chests = ws.chests
        self.inserters = ws.inserters
        self.power = ws.power
        self.towers = ws.towers
        self.drones = ws.drones
        self.pads = ws.pads
        self.labs = ws.labs
        self.pipes = ws.pipes
        self.dyson.grid = ws.grid

    def switch_planet(self, i: int):
        """切星（轨道面板点击圆点）。"""
        self.activate_world(i)

    @property
    def world(self):
        """当前激活的行星 WorldState。

        注意：Simulation 以前**只有** `worlds` 列表，没有 `world`；
        `sim.world` 会在长按采矿里直接 AttributeError（采矿必定崩）。
        这里是唯一权威入口，别在前端自己拼 self.worlds[self.world_index]。
        """
        return self.worlds[self.world_index]

    def _on_belts_changed(self):
        self._belts_dirty = True

    # ---------- 事件流 ----------

    def emit(self, kind: str, *payload):
        ev = (kind, *payload)
        self._events.append(ev)
        # M15a：除了本地队列，再 fan-out 给订阅者（联机服务端要拿同一份事件，
        # 不能跟渲染抢 pop_events 的唯一消费者地位）
        for sink in self._event_sinks:
            try:
                sink(ev)
            except Exception:
                pass

    def subscribe_events(self, sink):
        """注册事件旁路（网络层用）。返回取消函数。"""
        self._event_sinks.append(sink)
        return lambda: (self._event_sinks.remove(sink)
                        if sink in self._event_sinks else None)

    def pop_events(self) -> list[tuple]:
        """取走并清空事件。事件：(kind, *payload)，kind ∈ {"toast","achievement"}。"""
        out, self._events = self._events, []
        return out

    def take_dirty_cells(self) -> list[tuple[int, int]]:
        """取走并清空本帧脏格子（渲染层刷新 chunk 缓存用）。"""
        out, self._dirty_cells = self._dirty_cells, []
        return out

    def subscribe_dirty(self, sink):
        """注册脏格旁路（M15a：网络层要独立拿到脏格，不能和渲染抢）。"""
        self._dirty_sinks.append(sink)
        return lambda: (self._dirty_sinks.remove(sink)
                        if sink in self._dirty_sinks else None)

    def _mark_dirty(self, gx: int, gy: int):
        self._dirty_cells.append((gx, gy))
        if self._dirty_sinks:
            for sink in self._dirty_sinks:
                try:
                    sink(gx, gy)
                except Exception:
                    pass

    # ---------- M15a：指令层的世界作用域 ----------

    @contextlib.contextmanager
    def with_world(self, index: int):
        """临时切到第 index 颗行星执行一条指令，退出时还原。

        联机时指令带 world_index；`activate_world` 会改一大堆全局态，
        必须包一层再还原，否则服务端处理 A 行星的指令会污染 B 行星。
        """
        if not (0 <= index < len(self.worlds)) or index == self.world_index:
            yield self
            return
        prev = self.world_index
        self.activate_world(index)
        try:
            yield self
        finally:
            self.activate_world(prev)

    # ---------- 推进 ----------

    def step(self, dt: float):
        """推进一个物理帧的全部逻辑（网络/行星/手搓/研究）。暂停由前端控制。"""
        if self._belts_dirty:
            self._belts_dirty = False
            self.belts.rebuild()
            self.machines.sync()
            self.miners.sync()
            self.chests.sync()
            self.towers.sync(self.drones)
            self.pads.sync(self.fleet, self.world_index)
            self.labs.sync()
            self.dyson.sync()
            self.pipes.invalidate()

        prev_researched = set(self.tech.researched)
        self.power.update(dt)
        sf = self.power.speed_factor
        self.belts.update(dt * sf * self.tech.belt_speed_multiplier())
        # M14：液体先均流/泵送，机器再抽料排料（顺序决定"本帧抽到的是本帧的液")
        self.pipes.update(dt, self.power)
        self.machines.update(dt, self.power)
        self.miners.update(dt * sf if sf < 1.0 else dt, self.belts)
        for cx, cy in self.miners.pop_dirty_cells():
            self._mark_dirty(cx, cy)
        self.inserters.update(dt, self.machines)
        self.towers.update(dt, self.belts, self.drones)
        self.pads.update(dt, self.belts)
        self.drones.update(dt)
        self.labs.update(dt, self.power)
        self.dyson.update(dt, self.power)
        # 行星公转（M6.31 真实轨道）：全部行星都走，不管当前在哪颗——
        # 否则切星后相位冻结，星际发射窗口预测会失真。
        for ws in self.worlds:
            ws.planet.update(dt)
        # M5b：恒星级舰队——所有行星的发射台都可能发船，舰队长在 sim 级
        self.fleet.update(dt, self.worlds)

        # 手搓队列：面板关掉也照跑（材料已扣，这里只推进计时和产出）
        prev_job = self.craft.job
        self.craft.update(dt)
        if prev_job is not None and self.craft.job is None:
            r = C.RECIPES.get(prev_job.rid)
            if r is not None:
                nm = " + ".join(C.ITEM_NAMES.get(i, "?") for i in r[1])
                self.emit("toast", f"手搓完成：{nm}", 1.8)

        # 研究完成（含队列自动接续完成的）
        for tid in sorted(self.tech.researched - prev_researched):
            name, _, _, desc = C.TECH_TREE.get(tid, (tid, 0, (), ""))
            self.emit("achievement", f"研究完成：{name}", desc)

    # ---------- 背包 ----------

    def manual_mine(self, gx: int, gy: int, amount: int = 1) -> int:
        """手动采矿：从矿格挖 amount 个进背包，返回实际挖到的个数。

        矿脉无限（grid.mine 不递减），所以这里只判断"是不是矿格"。
        没有电、没有采矿机也能用——这是开局唯一免费的材料来源。
        """
        w = self.world
        if w is None:
            return 0
        got = 0
        for _ in range(max(1, int(amount))):
            item = w.grid.mine(gx, gy)
            if not item:
                break
            self.inventory[item] = self._count(item) + 1
            got += 1
        if got:
            self._mark_dirty(gx, gy)
        return got

    def _count(self, item: int) -> int:
        return self.inventory.get(item, 0)

    def _have_building(self, btype: int) -> int:
        item = C.BUILD_ITEM.get(btype)
        return 0 if item is None else self._count(item)

    def _pay_building(self, btype: int, n: int = 1) -> bool:
        """扣 n 个建筑物品；不够就发提示并返回 False。"""
        item = C.BUILD_ITEM.get(btype)
        if item is None:
            return True
        have = self._count(item)
        if have < n:
            self.emit("toast",
                      f"{C.ITEM_NAMES.get(item, '建筑')} 不够（有 {have}，要 {n}）",
                      2.0)
            return False
        left = have - n
        if left > 0:
            self.inventory[item] = left
        else:
            self.inventory.pop(item, None)
        return True

    def _refund_building(self, btype: int, n: int = 1):
        """拆建筑返还物品（全额返还）。"""
        item = C.BUILD_ITEM.get(btype)
        if item is None:
            return
        self.inventory[item] = self._count(item) + n

    # ---------- 指令：放置 / 拆除 ----------

    def place_building(self, btype: int, gx: int, gy: int,
                       direction: int = 0) -> str:
        """放置一个单格建筑（不含两点式的带/分拣器）。

        返回码："ok" / "locked"（科技未解锁） / "no_place"（格被占）
               / "no_item"（建筑物品不够）。
        成功后相应网络已 sync——前端可直接开面板。
        """
        if not self.tech.is_unlocked(btype):
            return "locked"
        if not self.grid.can_place(gx, gy):
            return "no_place"
        if not self._pay_building(btype):
            return "no_item"
        if not self.grid.place(gx, gy, btype, direction):
            self._refund_building(btype)
            return "no_place"
        self._mark_dirty(gx, gy)
        self.grid.belts_changed()
        # 这些建筑放下后立刻 sync，面板才拿得到实例
        if btype in (C.B_FURNACE, C.B_ASSEMBLER):
            self.machines.sync()
            self.miners.sync()
            self.chests.sync()
        elif btype == C.B_CHEST:
            self.chests.sync()
        elif btype == C.B_MINER:
            self.miners.sync()
        return "ok"

    def place_tower(self, btype: int, gx: int, gy: int,
                    direction: int = 0) -> str:
        """放置 3×3 物流塔（单击放，只记中心格）。"""
        if not self.tech.is_unlocked(btype):
            return "locked"
        if not self.towers.can_place(gx, gy):
            return "no_place"
        if not self._pay_building(btype):
            return "no_item"
        self.grid.place(gx, gy, btype, direction)
        self._mark_dirty(gx, gy)
        self.grid.belts_changed()
        return "ok"

    def place_pad(self, btype: int, gx: int, gy: int,
                  direction: int = 0) -> str:
        """放置 3×3 发射台（M5b，单击放，只记中心格，自动配一条运输船）。"""
        if btype != C.B_LAUNCH_PAD:
            return self.place_tower(btype, gx, gy, direction)
        if not self.tech.is_unlocked(btype):
            return "locked"
        if not self.pads.can_place(gx, gy):
            return "no_place"
        if not self._pay_building(btype):
            return "no_item"
        self.grid.place(gx, gy, btype, direction)
        self.pads.sync(self.fleet, self.world_index)
        self._mark_dirty(gx, gy)
        self.grid.belts_changed()
        return "ok"

    def place_engine(self, gx: int, gy: int, direction: int = 0) -> str:
        """放置 3×3 行星引擎（M6，单击放，只记中心格）。"""
        if not self.tech.is_unlocked(C.B_PLANET_ENGINE):
            return "locked"
        if not self.pads.can_place(gx, gy):
            return "no_place"
        if not self._pay_building(C.B_PLANET_ENGINE):
            return "no_item"
        self.grid.place(gx, gy, C.B_PLANET_ENGINE, direction)
        self._mark_dirty(gx, gy)
        self.grid.belts_changed()
        return "ok"

    # ---------- 行星工程（M6）：调轨道 ----------

    def engine_at(self, gx: int, gy: int) -> tuple[int, int] | None:
        """点中行星引擎 3×3 的任意格 → 返回中心格。"""
        if self.grid.get(gx, gy) == C.B_PLANET_ENGINE:
            return (gx, gy)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if self.grid.get(gx + dx, gy + dy) == C.B_PLANET_ENGINE:
                    return (gx + dx, gy + dy)
        return None

    def has_engine(self) -> bool:
        return self.grid.count_building(C.B_PLANET_ENGINE) > 0

    def engine_powered(self) -> bool:
        """引擎要通电才能变轨：有引擎且它所在电网的供电比例够。"""
        return (self.has_engine()
                and self._engine_factor() >= C.ENGINE_POWER_MIN_RATIO)

    def engine_center(self) -> tuple[int, int] | None:
        """引擎中心格（网格里只存中心）。"""
        ys, xs = np.nonzero(self.grid.building == C.B_PLANET_ENGINE)
        if len(xs) == 0:
            return None
        return (int(xs[0]), int(ys[0]))

    def _engine_factor(self) -> float:
        """引擎中心格所在电网的供电比例（没有引擎返回 0）。"""
        center = self.engine_center()
        if center is None:
            return 0.0
        return self.power.factor_at(center[0], center[1])

    def orbit_base_a(self) -> float:
        """本行星原始半长轴（变轨范围与档位都以它为基准）。"""
        return max(self.worlds[self.world_index].pdef.a_au, 1e-6)

    def orbit_ratio(self) -> float:
        """当前半长轴 / 原始半长轴。"""
        return self.planet.a_au / self.orbit_base_a()

    def set_orbit_a_ratio(self, ratio: float) -> float:
        """把轨道半径设成原始的 ratio 倍（clamp 到 0.6~1.8），返回实际比值。"""
        base = self.orbit_base_a()
        r = max(C.ENGINE_A_MIN_RATIO, min(C.ENGINE_A_MAX_RATIO, float(ratio)))
        if self.engine_powered():
            self.planet.set_semi_major(base * r)
        return self.orbit_ratio()

    def nudge_orbit_a(self, step: float) -> float:
        """面板上点一次「半径 ±」：在当前位置上加减档位。"""
        return self.set_orbit_a_ratio(self.orbit_ratio() + step)

    def shift_orbit_phase(self, delta_deg: float) -> bool:
        """平移轨道相位（度）；没通电不生效。"""
        if not self.engine_powered():
            return False
        self.planet.shift_phase(delta_deg)
        return True

    def set_pad_mode(self, gx: int, gy: int, mode: str) -> bool:
        """切换发射台模式（supply/request）。"""
        pad = self.pads.get_pad(gx, gy)
        if pad is None or mode not in ("supply", "request"):
            return False
        pad.mode = mode
        if mode == "request":
            self.fleet.remove_for_pad(pad, self.world_index)
            pad.ships.clear()
        else:
            self.fleet.spawn_for_pad(pad, self.world_index)
        self._mark_dirty(pad.x, pad.y)
        return True

    def set_pad_target(self, gx: int, gy: int, world_index: int) -> bool:
        """设置发射台的目标行星（供货台用）。"""
        pad = self.pads.get_pad(gx, gy)
        if pad is None:
            return False
        if not (0 <= world_index < len(self.worlds)):
            return False
        pad.target = world_index
        return True

    def lay_belt_line(self, sx: int, sy: int, ex: int, ey: int,
                      last_dir: int = 0) -> bool:
        """从 (sx,sy) 到 (ex,ey) 铺 L 形传送带。中途缺料提前止步。"""
        # 先沿 X 走
        x, y = sx, sy
        while x != ex:
            step_x = 1 if ex > x else -1
            d = 0 if step_x > 0 else 2  # 右 / 左
            if self.grid.can_place(x, y):
                if not self._pay_building(C.B_BELT):
                    self.grid.belts_changed()
                    return False
                self.grid.place(x, y, C.B_BELT, d)
                self._mark_dirty(x, y)
            x += step_x
        # 再沿 Y 走
        while y != ey:
            step_y = 1 if ey > y else -1
            d = 1 if step_y > 0 else 3  # 下 / 上
            if self.grid.can_place(x, y):
                if not self._pay_building(C.B_BELT):
                    self.grid.belts_changed()
                    return False
                self.grid.place(x, y, C.B_BELT, d)
                self._mark_dirty(x, y)
            y += step_y
        # 最后一格
        if self.grid.can_place(ex, ey):
            last_d = last_dir
            if ex != sx:
                last_d = 0 if ex > sx else 2
            elif ey != sy:
                last_d = 1 if ey > sy else 3
            if self._pay_building(C.B_BELT):
                self.grid.place(ex, ey, C.B_BELT, last_d)
                self._mark_dirty(ex, ey)
        self.grid.belts_changed()
        return True

    def place_inserter(self, mx: int, my: int, d: int) -> str:
        """在 (mx,my) 放一个方向 d 的分拣器（overlay）。"""
        if self.grid.get_overlay(mx, my) != C.B_EMPTY:
            return "no_place"
        if not self._pay_building(C.B_INSERTER):
            return "no_item"
        if self.grid.place_overlay(mx, my, C.B_INSERTER, d):
            self._mark_dirty(mx, my)
            return "ok"
        self._refund_building(C.B_INSERTER)
        return "no_place"

    def set_overlay_filter(self, gx: int, gy: int, choice: int):
        """设置分拣器过滤（0=不限，否则物品 id）。"""
        self.grid.set_overlay_filter(gx, gy, choice)
        self._mark_dirty(gx, gy)

    def remove_building(self, gx: int, gy: int) -> tuple[bool, int | None]:
        """拆除格子上的建筑（或分拣器），容器内物品退回背包。

        返回 (拆没拆, 退回的建筑物品 id|None)。点中塔 3×3 → 拆塔中心。
        """
        # M5b：点中发射台 3×3 → 拆台（库存退回背包，船一并撤）
        pad = self.pads.get_pad(gx, gy)
        if pad is not None:
            for item, n in list(pad.inventory.items()):
                if n > 0:
                    self.inventory[item] = self._count(item) + n
            pad.inventory.clear()
            self.fleet.remove_for_pad(pad, self.world_index)
            pad.ships.clear()
            if self.grid.remove(pad.x, pad.y):
                self._refund_building(C.B_LAUNCH_PAD)
                self._mark_dirty(pad.x, pad.y)
                self.grid.belts_changed()
            self.pads.sync(self.fleet, self.world_index)
            return True, None
        # 点中塔的 3×3 范围 → 拆塔中心
        eng = self.engine_at(gx, gy)
        if eng is not None:
            if self.grid.remove(eng[0], eng[1]):
                self._refund_building(C.B_PLANET_ENGINE)
                self._mark_dirty(eng[0], eng[1])
                self.grid.belts_changed()
            return True, None
        tower = self.towers.get_tower(gx, gy)
        if tower is not None:
            self.drones.remove_for_tower(tower)
            if self.grid.remove(tower.x, tower.y):
                self._refund_building(
                    C.B_TOWER_SUPPLY if tower.mode == "supply"
                    else C.B_TOWER_REQUEST)
                self._mark_dirty(tower.x, tower.y)
                self.grid.belts_changed()
            return True, None
        # 先拆叠加层（分拣器），再拆底下的建筑
        if self.grid.get_overlay(gx, gy) != C.B_EMPTY:
            self.grid.remove_overlay(gx, gy)
            self._refund_building(C.B_INSERTER)
            self._mark_dirty(gx, gy)
            return True, C.B_INSERTER
        if self.grid.get(gx, gy) != C.B_EMPTY:
            btype = self.grid.get(gx, gy)
            # 拆带容器的建筑前，把里面存的东西退回背包
            if btype == C.B_CHEST:
                ch = self.chests.get(gx, gy)
                if ch is not None:
                    for item, n in list(ch.store.items()):
                        if n > 0:
                            self.inventory[item] = self._count(item) + n
                    ch.store.clear()
            elif btype == C.B_MINER:
                mn = self.miners.get(gx, gy)
                if mn is not None:
                    for item, n in list(mn.buffer.items()):
                        if n > 0:
                            self.inventory[item] = self._count(item) + n
                    mn.buffer.clear()
            elif btype in (C.B_FURNACE, C.B_ASSEMBLER):
                m = self.machines.get_machine(gx, gy)
                if m is not None:
                    for store in (m.inputs, m.outputs):
                        for item, n in list(store.items()):
                            if n > 0:
                                self.inventory[item] = self._count(item) + n
                        store.clear()
            elif btype == C.B_EMITTER:
                em = self.dyson.get(gx, gy)
                if em is not None:
                    for item, n in list(em.store.items()):
                        if n > 0:
                            self.inventory[item] = self._count(item) + n
                    em.store.clear()
            elif btype in (C.B_FURNACE, C.B_ASSEMBLER):
                pass
            # M14：拆管道/储罐时把里面的液体**先泼给相邻管网**，泼不完才丢，
            # 免得拆一格罐子凭空蒸发 2500 单位
            if btype in C.FLUID_CELL_BUILDINGS:
                self._spill_fluid(gx, gy)
            if self.grid.remove(gx, gy):
                self._refund_building(btype)
                self._mark_dirty(gx, gy)
                self.grid.belts_changed()
                return True, btype
        else:
            item = self.grid.mine(gx, gy)
            if item:
                self.inventory[item] = self._count(item) + 1
                self._mark_dirty(gx, gy)
        return False, None

    # ---------- 液体（M14） ----------

    def _spill_fluid(self, gx: int, gy: int):
        """拆掉液体格前，把里面的液体泼给四邻（泼不完的才丢）。

        没有这一步的话，拆一格满储罐就等于凭空销毁 2500 单位液体。
        """
        try:
            amt = self.pipes.amount_at(gx, gy)
            fid = self.pipes.fid_at(gx, gy)
        except Exception:
            return
        if amt <= C.FLUID_EPS or fid == 0:
            return
        w, h = self.grid.w, self.grid.h
        for d in range(4):
            if amt <= C.FLUID_EPS:
                break
            nx = (gx + C.DX[d]) % w
            ny = (gy + C.DY[d]) % h
            if int(self.grid.building[ny, nx]) in C.FLUID_CELL_BUILDINGS:
                amt -= self.pipes.fill_at(nx, ny, fid, amt)
        # 剩下泼不掉的：直接清零（拆之前先清掉，避免 rebuild 时按坐标搬回来）
        self.pipes.amount_clear(gx, gy)

    def fluid_at(self, gx: int, gy: int) -> tuple[int, float, float]:
        """(液体 id, 液量, 容量)——点击/面板/HUD 用。"""
        return (self.pipes.fid_at(gx, gy), self.pipes.amount_at(gx, gy),
                self.pipes.cap_at(gx, gy))

    # ---------- M15a：面板写入指令（联机前置） ----------
    # 所有"面板改机器/箱子/科研站/塔"的动作都必须走这里：
    # 联机时 UI 只是发指令，服务端才是唯一改状态的地方。
    # 返回码与放置指令同风格："ok" / "no_machine" / "no_item" / "locked" / ...

    def _give_item(self, item: int, n: int) -> int:
        """把 n 个物品塞进背包（n<=0 忽略）。返回实际塞入量。"""
        n = int(n)
        if n <= 0:
            return 0
        self.inventory[item] = self._count(item) + n
        return n

    def _machine_at(self, gx: int, gy: int):
        return self.machines.get_machine(gx, gy)

    def set_machine_recipe(self, gx: int, gy: int, rid: str | None) -> str:
        """给机器设配方（None = 不生产）。科技/机型不匹配会被拒。"""
        m = self._machine_at(gx, gy)
        if m is None:
            return "no_machine"
        if rid is not None:
            if rid not in C.RECIPES:
                return "no_recipe"
            allows = C.RECIPES[rid][3]
            if allows and m.btype not in allows:
                return "no_recipe"
            req = C.RECIPE_TECH.get(rid)
            if req and not self.tech.is_unlocked(req):
                return "locked"
        m.set_recipe(rid)
        self._mark_dirty(gx, gy)
        return "ok"

    def machine_take_input(self, gx: int, gy: int, item: int,
                           count: int | None = None) -> int:
        """从机器原料槽取出到背包，返回实际取出数。"""
        m = self._machine_at(gx, gy)
        if m is None:
            return 0
        n = m.take_input(item, count)
        self._give_item(item, n)
        return n

    def machine_add_input(self, gx: int, gy: int, item: int,
                          count: int | None = None,
                          from_inventory: bool = True) -> int:
        """把背包里的原料放进机器，返回实际放入数（超出配方需求会被拒）。"""
        m = self._machine_at(gx, gy)
        if m is None:
            return 0
        want = self._count(item) if from_inventory else int(count or 0)
        if want <= 0:
            return 0
        n = m.add_input(item, min(want, int(count if count else want)))
        if n <= 0:
            return 0
        if from_inventory:
            left = want - n
            if left > 0:
                self.inventory[item] = left
            else:
                self.inventory.pop(item, None)
        return n

    def machine_take_outputs(self, gx: int, gy: int) -> dict[int, int]:
        """取出机器全部产物到背包，返回 {item: n}。"""
        m = self._machine_at(gx, gy)
        if m is None:
            return {}
        got = m.take_all_outputs()
        for it, n in got.items():
            self._give_item(it, n)
        return got

    # ---------- 箱子 / 采矿机 / 发射器（统一容器指令） ----------

    def container_at(self, gx: int, gy: int):
        """该格上的可搬运容器：(kind, obj)，kind ∈ chest/miner/emitter。

        箱子、采矿机、发射器的背包读写接口同名（add_item/take_item），
        所以面板只要发 container_take/container_put，联机时也只传一种指令。
        """
        ch = self.chests.get(gx, gy)
        if ch is not None:
            return "chest", ch
        mn = self.miners.get(gx, gy)
        if mn is not None:
            return "miner", mn
        em = self.dyson.get(gx, gy)
        if em is not None:
            return "emitter", em
        return None, None

    def chest_take(self, gx: int, gy: int, item: int,
                   count: int | None = None) -> int:
        ch = self.chests.get(gx, gy)
        if ch is None:
            return 0
        n = ch.take_item(item, count)
        self._give_item(item, n)
        return n

    def chest_put(self, gx: int, gy: int, item: int,
                  count: int | None = None) -> int:
        ch = self.chests.get(gx, gy)
        if ch is None:
            return 0
        have = self._count(item)
        if have <= 0:
            return 0
        n = ch.add_item(item, min(have, int(count or have)))
        if n <= 0:
            return 0
        left = have - n
        if left > 0:
            self.inventory[item] = left
        else:
            self.inventory.pop(item, None)
        return n

    def container_take(self, gx: int, gy: int, item: int,
                       count: int | None = None) -> int:
        """从该格容器（箱子/采矿机/发射器）取物品到背包。"""
        _kind, obj = self.container_at(gx, gy)
        if obj is None:
            return 0
        n = obj.take_item(item, count)
        self._give_item(item, n)
        return n

    def container_put(self, gx: int, gy: int, item: int,
                      count: int | None = None) -> int:
        """把背包物品放进该格容器。"""
        _kind, obj = self.container_at(gx, gy)
        if obj is None:
            return 0
        have = self._count(item)
        if have <= 0:
            return 0
        n = obj.add_item(item, min(have, int(count or have)))
        if n <= 0:
            return 0
        left = have - n
        if left > 0:
            self.inventory[item] = left
        else:
            self.inventory.pop(item, None)
        return n

    # ---------- 科研站 ----------

    def lab_exists(self, gx: int, gy: int) -> bool:
        return self.labs.get_lab(gx, gy) is not None

    def lab_set_mode(self, gx: int, gy: int, mode: str) -> str:
        if self.labs.get_lab(gx, gy) is None:
            return "no_lab"
        if mode not in (C.LAB_MODE_RESEARCH, C.LAB_MODE_PRODUCE):
            return "bad_mode"
        self.labs.set_mode(gx, gy, mode)
        self._mark_dirty(gx, gy)
        return "ok"

    def lab_set_recipe(self, gx: int, gy: int, rid: str | None) -> str:
        lab = self.labs.get_lab(gx, gy)
        if lab is None:
            return "no_lab"
        if rid is not None and rid not in C.LAB_PRODUCE_RECIPES:
            return "no_recipe"
        self.labs.set_recipe(gx, gy, rid)
        self._mark_dirty(gx, gy)
        return "ok"

    def lab_take_item(self, gx: int, gy: int, item: int,
                      count: int | None = None) -> int:
        n = self.labs.take_item(gx, gy, item, count)
        self._give_item(item, n)
        return n

    def lab_add_item(self, gx: int, gy: int, item: int,
                     count: int | None = None) -> int:
        have = self._count(item)
        if have <= 0:
            return 0
        n = self.labs.add_item(gx, gy, item, min(have, int(count or have)))
        if n <= 0:
            return 0
        left = have - n
        if left > 0:
            self.inventory[item] = left
        else:
            self.inventory.pop(item, None)
        return n

    def lab_take_outputs(self, gx: int, gy: int) -> dict[int, int]:
        got = self.labs.take_outputs(gx, gy)
        for it, n in got.items():
            self._give_item(it, n)
        return got

    # ---------- 物流塔 ----------

    def set_tower_filter(self, gx: int, gy: int, item: int | None) -> str:
        """设置塔的过滤物品（None = 不过滤）。"""
        t = self.towers.get_tower(gx, gy)
        if t is None:
            return "no_tower"
        t.filter = None if not item else int(item)
        self._mark_dirty(t.x, t.y)
        return "ok"

    # ---------- 指令：手搓 ----------

    def do_craft(self, rid: str, times: int) -> int:
        """把手搓任务排进队列，返回实际排进去的次数（材料不够会少排）。"""
        return self.craft.start(rid, times)

    def manual_research(self, tech_id: str) -> tuple[bool, str]:
        """手动研究：直接吃背包里的科研包，不需要科研站、不需要电。"""
        return self.tech.manual_research(tech_id, self.inventory)

    def start_research(self, tech_id: str) -> tuple[bool, str]:
        """把科技排进研究队列（M15a：科技面板不再直接改 TechTree）。

        用 can_queue 而不是 can_research：允许"前置还在队列里"的预排计划。
        """
        ok, why = self.tech.can_queue(tech_id)
        if not ok:
            return False, why
        self.tech.start(tech_id)
        return True, "已加入研究"

    def cancel_craft(self):
        self.craft.cancel()