"""星际物流（M5b）：发射台 + 运输船 + 发射窗口。

发射台（3×3，网格只记中心格）两种模式：
  supply  — 相邻传送带上的物品被吸进库存；有货 + 窗口开 → 发船
  request — 船卸下来的货往相邻传送带吐（与请求塔同款交换口）
运输船：恒星级舰队（Fleet，sim 持有），跨行星飞：
  docked → outbound（装货飞目标 request 台）→ inbound（返航，剩货带回）
发射窗口：两颗行星的相位差（绕一圈取小角）≤ SHIP_WINDOW_ANGLE 才能发射。
  窗口由公转自然产生，玩家要等/规划——这就是"相位对齐"的核心玩法。
  Fleet.window_wait() 按两颗行星各自角速度解析算出下一次窗口剩余秒数，
  轨道面板据此做预测。

设计铁律（同塔/无人机）：发射台只在中心格写 building；3×3 内全空且不和
其它 3×3 大件重叠才能放；拆台时舰队里的船一并清掉。
"""

from __future__ import annotations

import math

import numpy as np

from .. import config as C

# 3×3 占地相对中心格的偏移
_PAD_OFFSETS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def _wrap180(a: float) -> float:
    """角度差归一到 (-180, 180]。"""
    return ((a + 180.0) % 360.0) - 180.0


def phase_diff(w1, w2) -> float:
    """两颗行星的相位差（度，0~180）。"""
    return abs(_wrap180(w1.planet.angle - w2.planet.angle))


def window_open(w1, w2) -> bool:
    """当前是否在发射窗口内（相位差 ≤ SHIP_WINDOW_ANGLE）。"""
    return phase_diff(w1, w2) <= C.SHIP_WINDOW_ANGLE


def _phase_after(w1, w2, t: float) -> float:
    """t 秒后的相位差（真近点角，走开普勒运动）。"""
    return abs(_wrap180(w1.planet.angle_after(t) - w2.planet.angle_after(t)))


def _rel_rate(w1, w2) -> float:
    """两颗行星的平均相对角速度（度/秒，恒为正；同周期 ≈ 0）。"""
    p1, p2 = w1.planet.period, w2.planet.period
    if p1 <= 0 or p2 <= 0:
        return 0.0
    return abs(360.0 / p1 - 360.0 / p2)


def window_wait(w1, w2) -> float:
    """距离下一次发射窗口开启还要多少秒（当前在窗口内返回 0）。

    M6.31 真实轨道后没有解析解（真近点角随开普勒方程变速），改为按
    "相对平近点角每步 5°"粗扫 + 25 次二分细化。
    同周期（相对角速度 ≈ 0）永远不换窗口：窗口内 0，否则 inf。
    """
    if window_open(w1, w2):
        return 0.0
    rel = _rel_rate(w1, w2)
    if rel < 1e-9:
        return float("inf")
    step = max(0.25, 5.0 / rel)      # 相对平近点角每步 5°
    limit = 1.2 * 360.0 / rel        # 一个会合周期多一点
    t = 0.0
    while t < limit:
        t += step
        if _phase_after(w1, w2, t) <= C.SHIP_WINDOW_ANGLE:
            lo, hi = t - step, t
            for _ in range(25):
                mid = (lo + hi) / 2.0
                if _phase_after(w1, w2, mid) <= C.SHIP_WINDOW_ANGLE:
                    hi = mid
                else:
                    lo = mid
            return max(hi, 0.0)
    return float("inf")


def window_hold(w1, w2) -> float:
    """窗口还能持续多少秒（不在窗口内返回 0）。"""
    if not window_open(w1, w2):
        return 0.0
    rel = _rel_rate(w1, w2)
    if rel < 1e-9:
        return float("inf")
    step = max(0.25, C.SHIP_WINDOW_ANGLE / rel / 4.0)
    t = 0.0
    limit = 4.0 * C.SHIP_WINDOW_ANGLE / rel + 10.0
    while t < limit:
        t += step
        if _phase_after(w1, w2, t) > C.SHIP_WINDOW_ANGLE:
            lo, hi = t - step, t
            for _ in range(25):
                mid = (lo + hi) / 2.0
                if _phase_after(w1, w2, mid) > C.SHIP_WINDOW_ANGLE:
                    hi = mid
                else:
                    lo = mid
            return max(lo, 0.0)
    return 0.0


def flight_time(w1, w2) -> float:
    """单程飞行秒数：相位越远越久（0.6×~1.4× 基准）。"""
    d = phase_diff(w1, w2)
    return C.SHIP_FLIGHT_BASE * (0.6 + 0.8 * d / 180.0)


class LaunchPad:
    """发射台：3×3，两种模式，库存与请求/供应方向。"""

    __slots__ = ("x", "y", "mode", "target", "inventory", "ships")

    def __init__(self, x: int, y: int, mode: str):
        self.x = x
        self.y = y
        self.mode = mode                   # "supply" | "request"
        self.target: int | None = None     # 目标行星下标（supply 台用）
        self.inventory: dict[int, int] = {}  # item_id -> count
        self.ships: list = []              # 停靠/归属本台的船（Fleet 填）

    # ---------- 库存 ----------

    def total(self) -> int:
        return sum(self.inventory.values())

    def capacity_left(self, item: int) -> int:
        return C.PAD_STACK - self.inventory.get(item, 0)

    def add_item(self, item: int, count: int) -> int:
        """入库，返回放不下的数量。"""
        put = min(max(self.capacity_left(item), 0), count)
        if put > 0:
            self.inventory[item] = self.inventory.get(item, 0) + put
        return count - put

    def remove_item(self, item: int, count: int) -> int:
        have = self.inventory.get(item, 0)
        take = min(have, count)
        if take > 0:
            self.inventory[item] = have - take
            if self.inventory[item] == 0:
                del self.inventory[item]
        return take

    def accepts(self, item: int) -> bool:
        """request 台收货（M5b 最小版：不过滤，全收）。"""
        return True

    def all_cells(self):
        for dx, dy in _PAD_OFFSETS:
            yield self.x + dx, self.y + dy


class Ship:
    """运输船：恒星级实体，坐标记 (world_index, pad_x, pad_y)。"""

    __slots__ = ("home", "target", "cargo", "state", "t", "dur")

    def __init__(self, home: tuple[int, int, int]):
        self.home = home                   # (world_index, pad_x, pad_y)
        self.target: tuple[int, int, int] | None = None
        self.cargo: dict[int, int] = {}
        self.state = "docked"              # docked / outbound / inbound
        self.t = 0.0                       # 当前航段剩余秒数
        self.dur = 0.0                     # 当前航段总秒数（算进度用）

    # ---------- 展示 ----------

    def progress(self) -> float:
        """本航段进度 0~1（docked = 0）。"""
        if self.dur <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self.t / self.dur))


class PadsNetwork:
    """一颗行星上的全部发射台：同步、放置检查、带子收发货。"""

    def __init__(self, grid):
        self.grid = grid
        self.pads: dict[tuple[int, int], LaunchPad] = {}  # 中心格 -> Pad
        self._adj_cells: dict[tuple[int, int], list] = {}

    def get_pad(self, x: int, y: int) -> LaunchPad | None:
        """某格是否落在某个发射台 3×3 内。"""
        g = self.grid
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                p = self.pads.get(((x + dx) % g.w, (y + dy) % g.h))
                if p is not None:
                    return p
        return None

    def can_place(self, x: int, y: int) -> bool:
        """3×3 全空，且不和其它 3×3 大件（塔/发射台/行星引擎）重叠。"""
        g = self.grid
        for dx, dy in _PAD_OFFSETS:
            cx, cy = (x + dx) % g.w, (y + dy) % g.h
            if int(g.building[cy, cx]) != C.B_EMPTY:
                return False
        big = (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST, C.B_LAUNCH_PAD,
               C.B_PLANET_ENGINE)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                cx, cy = (x + dx) % g.w, (y + dy) % g.h
                if int(g.building[cy, cx]) in big:
                    return False
        return True

    def sync(self, fleet: "Fleet | None" = None, world_index: int = 0,
             spawn_ships: bool = True):
        """建筑增删后调用：网格 -> Pad 对象；fleet 传入时管船的增删。"""
        g = self.grid
        mask = g.building == C.B_LAUNCH_PAD
        ys, xs = np.nonzero(mask)
        for cy, cx in zip(ys.tolist(), xs.tolist()):
            key = (cx, cy)
            if key not in self.pads:
                p = LaunchPad(cx, cy, "supply")
                self.pads[key] = p
                if fleet is not None and spawn_ships:
                    fleet.spawn_for_pad(p, world_index)
        dead = [k for k, p in self.pads.items()
                if int(g.building[p.y, p.x]) != C.B_LAUNCH_PAD]
        for k in dead:
            p = self.pads[k]
            if fleet is not None:
                fleet.remove_for_pad(p, world_index)
            self._adj_cells.pop(k, None)
            del self.pads[k]

    # ---------- 带子交换（与 TowerNetwork 同款逻辑） ----------

    def _adjacent_belt_cells(self, p: LaunchPad):
        cached = self._adj_cells.get((p.x, p.y))
        if cached is not None:
            return cached
        g = self.grid
        out = []
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                if max(abs(dx), abs(dy)) != 2:
                    continue
                out.append(((p.x + dx) % g.w, (p.y + dy) % g.h))
        self._adj_cells[(p.x, p.y)] = out
        return out

    def update(self, dt: float, belts):
        """供应台从相邻带子吸货；请求台往相邻带子吐货。"""
        g = self.grid
        for p in self.pads.values():
            if p.mode == "supply":
                self._pull_from_belts(p, g, belts)
            else:
                self._push_to_belts(p, g, belts)

    def _pull_from_belts(self, p: LaunchPad, g, belts):
        for bx, by in self._adjacent_belt_cells(p):
            if int(g.building[by, bx]) != C.B_BELT:
                continue
            lane_idx = belts.cell_lane.get((bx, by))
            if lane_idx is None:
                continue
            lane = belts.lanes[lane_idx]
            if len(lane.positions) == 0:
                continue
            ci = lane.cell_index((bx, by))
            if ci < 0:
                continue
            lo = int(np.searchsorted(lane.positions, float(ci), side="left"))
            hi = int(np.searchsorted(lane.positions, float(ci + 1), side="left"))
            for i in range(hi - 1, lo - 1, -1):
                item = int(lane.items[i])
                if p.capacity_left(item) <= 0:
                    break
                p.add_item(item, 1)
                lane.items = np.delete(lane.items, i).astype(np.int32)
                lane.positions = np.delete(lane.positions, i).astype(np.float32)
                break

    def _push_to_belts(self, p: LaunchPad, g, belts):
        if not p.inventory:
            return
        slots = []
        for bx, by in self._adjacent_belt_cells(p):
            if int(g.building[by, bx]) == C.B_BELT:
                slots.append((bx, by))
        if not slots:
            return
        for item, count in list(p.inventory.items()):
            if count <= 0:
                continue
            for bx, by in slots:
                if belts.try_insert(bx, by, item):
                    p.remove_item(item, 1)
                    break

    def count(self) -> int:
        return len(self.pads)


class Fleet:
    """恒星级运输船队：跨行星发射/飞行/卸货/返航。"""

    def __init__(self):
        self.ships: list[Ship] = []
        self._worlds: list = []   # 由 sim 每帧注入（WorldState 列表）

    # ---------- 船的生命周期 ----------

    def spawn_for_pad(self, pad: LaunchPad, world_index: int):
        s = Ship((world_index, pad.x, pad.y))
        self.ships.append(s)
        pad.ships.append(s)

    def remove_for_pad(self, pad: LaunchPad, world_index: int):
        dead = (world_index, pad.x, pad.y)
        self.ships = [s for s in self.ships if s.home != dead]

    # ---------- 更新 ----------

    def update(self, dt: float, worlds: list):
        """推进舰队：docked 尝试发射，outbound/inbound 推进计时。"""
        self._worlds = worlds
        if len(worlds) < 2:
            self._prune(worlds)
            return
        for s in list(self.ships):
            if s.state == "docked":
                self._try_launch(s, worlds)
            elif s.state == "outbound":
                s.t -= dt
                if s.t <= 0:
                    self._arrive(s, worlds)
            elif s.state == "inbound":
                s.t -= dt
                if s.t <= 0:
                    self._dock(s, worlds)
        self._prune(worlds)

    def _pad(self, worlds, loc: tuple[int, int, int] | None):
        if loc is None:
            return None
        wi, px, py = loc
        if not (0 <= wi < len(worlds)):
            return None
        return worlds[wi].pads.pads.get((px, py))

    def _try_launch(self, s: Ship, worlds: list):
        home = self._pad(worlds, s.home)
        if home is None or home.mode != "supply":
            return
        if not home.inventory:
            return
        wi = s.home[0]
        tgt_wi = home.target
        if tgt_wi is None or tgt_wi == wi or not (0 <= tgt_wi < len(worlds)):
            # 没设目标：默认发往下一颗行星（有货就动，减少玩家配置负担）
            tgt_wi = (wi + 1) % len(worlds)
        if tgt_wi == wi:
            return
        if not window_open(worlds[wi], worlds[tgt_wi]):
            return
        # 找目标行星上的 request 台：至少要能给船上的货腾出位置，
        # 否则船白跑一趟（满仓时原地等待，货留在本台）
        tgt_pad = None
        for p in worlds[tgt_wi].pads.pads.values():
            if p.mode != "request":
                continue
            if any(p.capacity_left(item) > 0 for item in home.inventory):
                tgt_pad = p
                break
        if tgt_pad is None:
            return
        # 装货：按库存顺序装到 SHIP_CARGO_CAP
        cargo: dict[int, int] = {}
        left = C.SHIP_CARGO_CAP
        for item, n in sorted(home.inventory.items()):
            if left <= 0:
                break
            take = min(n, left)
            home.remove_item(item, take)
            cargo[item] = cargo.get(item, 0) + take
            left -= take
        if sum(cargo.values()) < C.SHIP_MIN_CARGO:
            # 不够一船：塞回库存，等下一窗口/下一批
            for item, n in cargo.items():
                home.add_item(item, n)
            return
        s.cargo = cargo
        s.target = (tgt_wi, tgt_pad.x, tgt_pad.y)
        s.dur = flight_time(worlds[wi], worlds[tgt_wi])
        s.t = s.dur
        s.state = "outbound"

    def _arrive(self, s: Ship, worlds: list):
        tgt = self._pad(worlds, s.target)
        if tgt is None or tgt.mode != "request":
            s.state = "inbound"   # 目标没了，原路带回
            s.t = s.dur
            return
        for item, n in list(s.cargo.items()):
            left = tgt.add_item(item, n)
            if left <= 0:
                del s.cargo[item]
            else:
                s.cargo[item] = left
        s.state = "inbound"
        s.t = s.dur

    def _dock(self, s: Ship, worlds: list):
        home = self._pad(worlds, s.home)
        if home is not None:
            for item, n in list(s.cargo.items()):
                left = home.add_item(item, n)
                if left <= 0:
                    del s.cargo[item]
                else:
                    s.cargo[item] = left
        s.state = "docked"
        s.target = None
        s.t = 0.0
        s.dur = 0.0

    def _prune(self, worlds: list):
        """清掉母台已被拆的船。"""
        keep = []
        for s in self.ships:
            pad = self._pad(worlds, s.home)
            if pad is not None and pad.mode == "supply":
                keep.append(s)
            else:
                if pad is not None:
                    pad.ships = [x for x in pad.ships if x is not s]
        self.ships = keep

    # ---------- 查询（UI 用） ----------

    def ships_from(self, world_index: int) -> list[Ship]:
        return [s for s in self.ships if s.home[0] == world_index]

    def in_flight(self) -> list[Ship]:
        return [s for s in self.ships if s.state != "docked"]
