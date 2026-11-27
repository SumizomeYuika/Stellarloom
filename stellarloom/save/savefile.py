"""存档系统：zlib 压缩的 JSON，numpy 数组转 base64 原始字节。

设计要点：
- 传送带物品位置是 float32，必须原样保存，不能转成整数（会丢位置精度）
- 每个字段有版本号，迁移函数留空壳
- 自动存档轮转 3 份

文件格式（.slm）：
    4 字节 magic "SLM1" + zlib 压缩的 UTF-8 JSON
"""

from __future__ import annotations

import base64
import json
import os
import time
import zlib

import numpy as np

from .. import config as C

SAVE_VERSION = 14   # v14（M15d）：players 表（按玩家分背包/手搓）
MAGIC = b"SLM1"
SAVE_SLOT_COUNT = 6  # 多存档（M6.20）：固定 6 个手动槽位


def _fleet_of(game):
    """取恒星级舰队（Game 挂在 sim 上；测试桩可能没有）。"""
    f = getattr(game, "fleet", None)
    if f is not None:
        return f
    sim = getattr(game, "sim", None)
    return getattr(sim, "fleet", None)


def _pad_at(worlds, loc):
    """按 (world_index, x, y) 找发射台（可能已拆 → None）。"""
    if not worlds:
        return None
    wi, px, py = loc
    if not (0 <= wi < len(worlds)):
        return None
    return worlds[wi].pads.pads.get((px, py))


def _name(k) -> str:
    """内部物品数字 id → 存档名字（"stellarloom:iron_ore"）。
    未知（负数伪 id / 未注册）原样返回 str。"""
    try:
        return C.ITEM_REGISTRY.name_of(int(k))
    except Exception:
        return str(k)


def _load_key(k) -> int:
    """存档键（数字字符串 / 名字）→ 内部数字 id。
    数字字符串直通（老档行为不变）；名字查注册表，未知 → -1（汇总显示 '?'）。"""
    s = str(k)
    if s.lstrip("-").isdigit():
        return int(s)
    try:
        return C.ITEM_REGISTRY.id_of(s)
    except Exception:
        return -1


def _arr(a: np.ndarray) -> dict:
    """numpy 数组 -> {dtype, shape, b64}"""
    return {
        "dtype": str(a.dtype),
        "shape": list(a.shape),
        "b64": base64.b64encode(a.tobytes()).decode("ascii"),
    }


def _unarr(d: dict) -> np.ndarray:
    raw = base64.b64decode(d["b64"])
    return np.frombuffer(raw, dtype=np.dtype(d["dtype"])).reshape(d["shape"]).copy()


def _f32_list(a: np.ndarray) -> list:
    return [float(x) for x in a.tolist()]


def _i32_list(a: np.ndarray) -> list:
    return [int(x) for x in a.tolist()]


class SaveManager:
    def __init__(self, save_dir: str | None = None):
        if save_dir is None:
            # 存档放项目根目录下的 saves/
            here = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            save_dir = os.path.join(here, "saves")
        self.dir = save_dir
        os.makedirs(self.dir, exist_ok=True)
        self.last_save_time = 0.0

    # ---------- 序列化 ----------

    def dump(self, game) -> dict:
        """把 Game 的全部状态转成可 JSON 化的 dict。

        v10 结构：
        - 顶层：version / dyson（恒星级，全局）/ tech / stats / worlds / world_index
        - worlds[i]：一颗行星的 planet / grid / belts / machines / miners /
          chests / towers / labs / drones / camera / power
        """
        data = {
            "version": SAVE_VERSION,
            "saved_at": time.time(),
            "worlds": [],
            "world_index": getattr(game, "world_index", 0),
            "dyson": {"orbit_count": [0] * C.DYSON_ORBITS,
                      "orbit_angle": [0.0] * C.DYSON_ORBITS,
                      "emitters": []},
            "tech": {
                "researched": sorted(game.tech.researched),
                "current": game.tech.current,
                "progress": game.tech.progress,
                "queue": list(game.tech.queue),
            },
            "stats": {
                # M7：物品用命名空间名字持久化（"stellarloom:iron_ore"）
                "inventory": {_name(k): v for k, v in game.inventory.items()},
            },
        }

        # v14（M15d）：按玩家分背包。单机只有 players[0]；联机服务端有多个。
        # stats.inventory 保留（= 当前玩家背包，slot_meta/老工具兼容）。
        players = getattr(game, "players", None)
        if players:
            data["players"] = {
                str(pid): {"inventory": {_name(k): v
                                         for k, v in ps.inventory.items()}}
                for pid, ps in sorted(players.items())
            }

        # 兼容没有 worlds 的对象（旧 FakeGame / 测试桩）：平铺字段 = 单行星
        worlds = getattr(game, "worlds", None)
        if worlds is None:
            worlds = [game]

        for ws in worlds:
            g = ws.grid
            wd = {
                "planet": ws.planet.dump(),
                "grid": {
                    "w": g.w,
                    "h": g.h,
                    "building": _arr(g.building),
                    "direction": _arr(g.direction),
                    "overlay": _arr(g.overlay),
                    "overlay_dir": _arr(g.overlay_dir),
                    "overlay_filter": _arr(g.overlay_filter),
                    "ore": _arr(g.ore),
                    "ore_type": _arr(g.ore_type),
                },
                "belts": [],
                "machines": [],
                "miners": [],
                "chests": [],
                "towers": [],
                "pads": [],
                "labs": [],
                "drones": [],
                "camera": {
                    "x": ws.camera.x,
                    "y": ws.camera.y,
                    "zoom": ws.camera.zoom,
                },
                "power": {
                    "time": ws.power.time,
                    "day_length": ws.power.day_length,
                },
            }

            # 传送带：每条 lane 的格子 + 物品浮点位置（物品 id 存名字）
            for lane in ws.belts.lanes:
                wd["belts"].append({
                    "cells": [list(c) for c in lane.cells],
                    "next_lane": int(lane.next_lane),
                    # float32 原样保存，不能取整
                    "positions": _f32_list(lane.positions),
                    "items": [_name(int(x)) for x in lane.items],
                })

            # 机器
            for (mx, my), m in ws.machines.machines.items():
                wd["machines"].append({
                    "x": mx, "y": my,
                    "btype": m.btype,
                    "recipe": m.recipe_id,
                    "inputs": {_name(k): v for k, v in m.inputs.items()},
                    "outputs": {_name(k): v for k, v in m.outputs.items()},
                    "progress": m.progress,
                })

            # 采矿机（含 50 格暂存）
            for (mx, my), mn in ws.miners.miners.items():
                wd["miners"].append({
                    "x": mx, "y": my,
                    "buffer": {_name(k): v for k, v in mn.buffer.items()},
                })

            # 箱子
            for (cx, cy), ch in ws.chests.chests.items():
                wd["chests"].append({
                    "x": cx, "y": cy,
                    "store": {_name(k): v for k, v in ch.store.items()},
                })

            # 塔（含库存与过滤：filter=0 表示不限，保持 0）
            for (tx, ty), t in ws.towers.towers.items():
                wd["towers"].append({
                    "x": tx, "y": ty,
                    "mode": t.mode,
                    "inventory": {_name(k): v for k, v in t.inventory.items()},
                    "filter": (0 if not t.filter else _name(t.filter)),
                })

            # M5b：发射台（库存 + 模式 + 目标行星）
            pads_net = getattr(ws, "pads", None)
            if pads_net is not None:
                for (px, py), pad in pads_net.pads.items():
                    wd["pads"].append({
                        "x": px, "y": py,
                        "mode": pad.mode,
                        "target": pad.target,
                        "inventory": {_name(k): v
                                      for k, v in pad.inventory.items()},
                    })

            # 科研站（research：stored/timer；produce：recipe/inputs/outputs/progress）
            for (lx, ly), lab in ws.labs.labs.items():
                wd["labs"].append({
                    "x": lx, "y": ly,
                    "mode": lab.get("mode", C.LAB_MODE_RESEARCH),
                    "stored": {_name(k): v for k, v in lab["stored"].items()},
                    "timer": lab["timer"],
                    "recipe": lab.get("recipe"),
                    "inputs": {_name(k): v for k, v in lab.get("inputs", {}).items()},
                    "outputs": {_name(k): v for k, v in lab.get("outputs", {}).items()},
                    "progress": lab.get("progress", 0.0),
                })

            # 无人机（cargo / task_item 是物品 id，存名字）
            for d in ws.drones.drones:
                wd["drones"].append({
                    "x": d.x, "y": d.y,
                    "energy": d.energy,
                    "cargo": (None if d.cargo is None
                              else _name(d.cargo)),
                    "state": d.state,
                    "home": [d.home.x, d.home.y] if d.home else None,
                    "target": ([d.target_tower.x, d.target_tower.y]
                               if d.target_tower else None),
                    "deliver": ([d.deliver_tower.x, d.deliver_tower.y]
                                if d.deliver_tower else None),
                    "task_item": (None if d.task_item is None
                                  else _name(d.task_item)),
                    "task_count": d.task_count,
                })

            # 分拣器冷却（M11：读档不再清零，避免读档瞬间多抓一圈）
            wd["inserters"] = [
                {"x": x, "y": y, "cd": round(cd, 3)}
                for (x, y), cd in ws.inserters.cooldowns.items() if cd > 0]

            # 液体（M14）：只存有液体的格（管道/储罐），空管不占存档
            # 测试桩（FakeGame 的世界对象）没有 pipes → 跳过
            pipes = getattr(ws, "pipes", None)
            if pipes is not None:
                wd["pipe_fluid"] = pipes.dump_cells()

            data["worlds"].append(wd)

        # M5b：恒星级舰队（跨行星，顶层存）
        fleet = _fleet_of(game)
        if fleet is not None:
            data["ships"] = []
            for s in fleet.ships:
                data["ships"].append({
                    "home": list(s.home),
                    "target": list(s.target) if s.target else None,
                    "cargo": {_name(k): v for k, v in s.cargo.items()},
                    "state": s.state,
                    "t": s.t,
                    "dur": s.dur,
                })

        # 戴森云（M4，恒星级全局）
        if getattr(game, "dyson", None) is not None:
            data["dyson"] = game.dyson.dump()

        return data

    # ---------- 反序列化 ----------

    def _load_world(self, ws, wd: dict):
        """把存档里一颗行星的数据写回 WorldState（ws）。

        grid / belts / machines / miners / chests / towers / labs / drones /
        camera / power 都在这。dyson / tech / stats 是全局的，不在这里。
        """
        g = ws.grid

        grid = wd.get("grid", {})
        if "building" in grid:
            g.building = _unarr(grid["building"])
            g.direction = _unarr(grid["direction"])
            g.ore = _unarr(grid["ore"])
            # overlay（分拣器叠加层）：v1 老档没有这两个字段，缺失就留空
            if "overlay" in grid:
                g.overlay = _unarr(grid["overlay"])
                g.overlay_dir = _unarr(grid["overlay_dir"])
            else:
                g.overlay = np.zeros((g.h, g.w), dtype=np.int32)
                g.overlay_dir = np.zeros((g.h, g.w), dtype=np.int32)
            # 分拣器过滤：v5 才有，老档全填 0（不限）
            if "overlay_filter" in grid:
                g.overlay_filter = _unarr(grid["overlay_filter"])
            else:
                g.overlay_filter = np.zeros((g.h, g.w), dtype=np.int32)
            # 矿脉类型：v4 才有，老档全填铁矿
            if "ore_type" in grid:
                g.ore_type = _unarr(grid["ore_type"]).astype(np.int8)
            else:
                g.ore_type = np.full((g.h, g.w), C.ORE_IRON, dtype=np.int8)
                g.ore_type[g.ore <= 0] = C.ORE_NONE

        # 行星轨道（v9 才有）：老档没有就给默认角度 0
        ws.planet.load_from(wd.get("planet", {}))

        # 重建传送带 lane（格子拓扑），再挂物品（items 可能存名字）
        ws.belts.lanes.clear()
        ws.belts.cell_lane.clear()
        from ..logistics.belts import Lane
        for bd in wd.get("belts", []):
            cells = [tuple(c) for c in bd["cells"]]
            lane = Lane(cells=cells)
            lane.positions = np.array(bd["positions"], dtype=np.float32)
            lane.items = np.array(
                [_load_key(x) for x in bd.get("items", [])],
                dtype=np.int32)
            idx = len(ws.belts.lanes)
            ws.belts.lanes.append(lane)
            for c in cells:
                ws.belts.cell_lane[c] = idx
        # 恢复 next_lane 连接（M11：按格子方向校验，防旧档/手改档断链）
        ws.belts.validate_links()

        # 机器
        ws.machines.machines.clear()
        ws.machines.sync()
        for md in wd.get("machines", []):
            key = (md["x"], md["y"])
            m = ws.machines.machines.get(key)
            if m is None:
                continue
            # 配方可能是 None（玩家手动清空），必须原样恢复，不能落回默认
            # 旧档（M6.6 之前）用的是 hand_*/mk_* 两套 id，这里翻译成统一 id
            rid = md.get("recipe")
            if rid is not None:
                rid = C.LEGACY_RECIPE_ALIAS.get(rid, rid)
                if rid not in C.RECIPES:
                    rid = None
            m.set_recipe(rid)
            m.inputs = {_load_key(k): v for k, v in md["inputs"].items()}
            m.outputs = {_load_key(k): v
                         for k, v in md.get("outputs", {}).items()}
            m.progress = md["progress"]

        # 采矿机暂存（v6 才有）
        ws.miners.miners.clear()
        ws.miners.sync()
        for md in wd.get("miners", []):
            mn = ws.miners.get(md["x"], md["y"])
            if mn is not None:
                mn.buffer = {_load_key(k): v
                             for k, v in md.get("buffer", {}).items()}

        # 箱子（v6 才有）
        ws.chests.chests.clear()
        ws.chests.sync()
        for cd in wd.get("chests", []):
            ch = ws.chests.get(cd["x"], cd["y"])
            if ch is not None:
                ch.store = {_load_key(k): v
                            for k, v in cd.get("store", {}).items()}

        # 塔
        ws.towers.towers.clear()
        ws.drones.drones.clear()
        ws.towers.sync(ws.drones)
        # sync 会为每座塔自动 spawn 无人机，但存档里有完整无人机列表，
        # 清掉刚 spawn 的，避免读档后无人机翻倍
        ws.drones.drones.clear()
        for td in wd.get("towers", []):
            t = ws.towers.towers.get((td["x"], td["y"]))
            if t is None:
                continue
            t.inventory = {_load_key(k): v
                           for k, v in td["inventory"].items()}
            t.filter = _load_key(td["filter"]) if td.get("filter") else 0

        # 科研站
        ws.labs.sync()
        for ld in wd.get("labs", []):
            lab = ws.labs.labs.get((ld["x"], ld["y"]))
            if lab is not None:
                st = ld.get("stored", {})
                if isinstance(st, dict):
                    lab["stored"] = {_load_key(k): v for k, v in st.items()}
                else:
                    # v3 老档是单个 int（铁板数），转成电磁矩阵
                    lab["stored"] = ({C.LAB_CONSUME_ITEM: int(st)}
                                     if st else {})
                lab["timer"] = ld["timer"]
                # 双模式字段（v8 才有）
                lab["mode"] = ld.get("mode", C.LAB_MODE_RESEARCH)
                rid = ld.get("recipe")
                lab["recipe"] = rid if rid in C.LAB_PRODUCE_RECIPES else None
                lab["inputs"] = {_load_key(k): v for k, v in
                                 ld.get("inputs", {}).items()}
                lab["outputs"] = {_load_key(k): v for k, v in
                                  ld.get("outputs", {}).items()}
                lab["progress"] = ld.get("progress", 0.0)

        # M5b：发射台（直接建对象，不 spawn 船——船在舰队顶层恢复）
        from ..logistics.pads import LaunchPad
        if hasattr(ws, "pads"):
            ws.pads.pads.clear()
            ws.pads._adj_cells.clear()
            for pd in wd.get("pads", []):
                pad = LaunchPad(pd["x"], pd["y"], pd.get("mode", "supply"))
                pad.target = pd.get("target")
                pad.inventory = {_load_key(k): v
                                 for k, v in pd.get("inventory", {}).items()}
                ws.pads.pads[(pad.x, pad.y)] = pad

        # 无人机
        from ..logistics.drones import Drone
        towers_by_pos = ws.towers.towers
        for dd in wd.get("drones", []):
            home_pos = dd.get("home")
            home = towers_by_pos.get(tuple(home_pos)) if home_pos else None
            if home is None:
                continue
            d = Drone(home)
            d.x = dd["x"]
            d.y = dd["y"]
            d.energy = dd["energy"]
            d.cargo = (None if dd.get("cargo") is None
                       else _load_key(dd["cargo"]))
            d.state = dd["state"]
            d.task_item = (None if dd.get("task_item") is None
                           else _load_key(dd["task_item"]))
            d.task_count = dd["task_count"]
            tp = dd.get("target")
            d.target_tower = towers_by_pos.get(tuple(tp)) if tp else None
            dp = dd.get("deliver")
            d.deliver_tower = towers_by_pos.get(tuple(dp)) if dp else None
            ws.drones.drones.append(d)
        # 塔->无人机反查表
        for t in ws.towers.towers.values():
            t.drones = [d for d in ws.drones.drones if d.home is t]

        # 电力 / 相机（每行星独立）
        pw = wd.get("power", {})
        if "time" in pw:
            ws.power.time = pw["time"]
            ws.power.day_length = pw["day_length"]
        cam = wd.get("camera", {})
        if "x" in cam:
            ws.camera.x = cam["x"]
            ws.camera.y = cam["y"]
            ws.camera.zoom = cam["zoom"]

        # 读档覆盖了 overlay 数组，分拣器坐标集合缓存作废
        g.overlay_gen += 1
        ws.inserters.invalidate()
        # M11：恢复分拣器冷却（旧档没有该字段 → 空，等价旧行为）
        ws.inserters.cooldowns.clear()
        for cd in wd.get("inserters", []):
            try:
                ws.inserters.cooldowns[(int(cd["x"]), int(cd["y"]))] = float(
                    cd["cd"])
            except (KeyError, TypeError, ValueError):
                continue

        # M14：恢复管道/储罐里的液体（建筑格子已在上文写回 grid，这里重建成格表再灌）
        pipes = getattr(ws, "pipes", None)
        if pipes is not None:
            pipes.load_cells(wd.get("pipe_fluid"))

    def load_into(self, game, data: dict):
        """把存档数据写回 Game。调用前 game 的各个 network 应已建好。"""
        data = self._migrate(data)
        worlds_data = data.get("worlds") or [{}]
        if not isinstance(worlds_data, list):
            worlds_data = [worlds_data]

        # 确保 Game 有足够多的 WorldState；测试桩（无 _ensure_world）只有 1 个
        if hasattr(game, "_ensure_world"):
            for i in range(len(worlds_data)):
                game._ensure_world(i)
        else:
            if not hasattr(game, "worlds") or len(game.worlds) == 0:
                game.worlds = [game]

        for i, wd in enumerate(worlds_data):
            ws = game.worlds[i]
            self._load_world(ws, wd)

        # 科技（全局）
        tech = data["tech"]
        game.tech.researched = set(tech["researched"])
        game.tech.current = tech["current"]
        game.tech.progress = tech["progress"]
        game.tech.queue = list(tech.get("queue", []))

        # 物品栏（v4 是 dict；v3 及更早是 int 矿石计数，迁移时已转好）
        inv = data["stats"]["inventory"]
        if isinstance(inv, dict):
            items = {_load_key(k): v for k, v in inv.items()}
        else:
            items = dict(C.STARTING_ITEMS)
        # 就地更新，绝不换引用——M6.26：Game/craft 队列在构造时复制了
        # inventory 的引用，换引用会让前端显示旧背包、sim 用新背包
        # （症状：背包显示有 X 个，放置却提示"不够（有 0，要 1）"）
        game.inventory.clear()
        game.inventory.update(items)

        # v14（M15d）：按玩家背包表。老档（迁移后）只有 players["0"] =
        # 旧 stats.inventory；单机档恒只有一个玩家。就地更新背包引用，
        # 保证 PlayerState.craft 绑定的字典不失联。
        pdata = data.get("players")
        if pdata and hasattr(game, "ensure_player"):
            for pid_s, pd in pdata.items():
                ps = game.ensure_player(int(pid_s))
                pitems = {_load_key(k): v
                          for k, v in (pd.get("inventory") or {}).items()}
                ps.inventory.clear()
                ps.inventory.update(pitems)

        # 激活存档记录的行星（真实 Game 才需要；顺带把 dyson.grid 指过去）
        if hasattr(game, "_activate_world"):
            game._activate_world(data.get("world_index", 0))

        # 戴森云（v7 才有，恒星级全局）：先 sync 建出激活世界的发射器，
        # 再灌帆数与储存
        if getattr(game, "dyson", None) is not None:
            game.dyson.sync()
            game.dyson.load_from(data.get("dyson", {}))

        # M5b：恒星级舰队（v12 才有）：清掉自动 spawn 的船，按存档重建
        fleet = _fleet_of(game)
        if fleet is not None:
            from ..logistics.pads import Ship
            for ws in (getattr(game, "worlds", None) or []):
                if hasattr(ws, "pads"):
                    for p in ws.pads.pads.values():
                        p.ships.clear()
            fleet.ships = []
            for sd in data.get("ships", []):
                home = tuple(int(x) for x in sd["home"])
                s = Ship(home)
                s.target = (tuple(int(x) for x in sd["target"])
                            if sd.get("target") else None)
                s.cargo = {_load_key(k): v
                           for k, v in sd.get("cargo", {}).items()}
                s.state = sd.get("state", "docked")
                s.t = float(sd.get("t", 0.0))
                s.dur = float(sd.get("dur", 0.0))
                fleet.ships.append(s)
                pad = _pad_at(game.worlds, home)
                if pad is not None:
                    pad.ships.append(s)

        # 激活世界整体失效重绘（前端视图清缓存；headless 的 Simulation 没有 chunks）
        if hasattr(game, "chunks"):
            game.chunks.clear()
        game.inserters.invalidate()

    def _migrate(self, data: dict) -> dict:
        """版本迁移。"""
        v = data.get("version", 0)
        if v == SAVE_VERSION:
            return data
        if v == 1:
            # v1 -> v2：分拣器从 building 挪到 overlay 数组。
            # 老档里分拣器的格子 building 是 B_INSERTER，需要搬过去，
            # 否则读档后分拣器还在 building 里，会继续切断传送带。
            grid = data["grid"]
            bld = _unarr(grid["building"])
            dirc = _unarr(grid["direction"])
            mask = bld == C.B_INSERTER
            ov = np.zeros_like(bld)
            ovd = np.zeros_like(dirc)
            ov[mask] = C.B_INSERTER
            ovd[mask] = dirc[mask]
            bld[mask] = C.B_EMPTY
            grid["building"] = _arr(bld)
            grid["direction"] = _arr(dirc)
            grid["overlay"] = _arr(ov)
            grid["overlay_dir"] = _arr(ovd)
            data["version"] = 2
            v = 2
        if v == 2:
            # v2 -> v3：机器输出槽从单值 output 变成 outputs dict
            for md in data.get("machines", []):
                if "outputs" not in md:
                    old = md.pop("output", None)
                    md["outputs"] = {} if old is None else {str(old): 1}
            data["version"] = 3
            v = 3
        if v == 3:
            # v3 -> v4：多矿种 + 物品栏 dict + 科研包体系
            grid = data["grid"]
            # 1) ore_type 数组：老档没有，全部当铁矿
            if "ore_type" not in grid:
                ore = _unarr(grid["ore"])
                ot = np.full(ore.shape, C.ORE_IRON, dtype=np.int8)
                ot[ore <= 0] = C.ORE_NONE
                grid["ore_type"] = _arr(ot)
            # 2) 物品栏：老档是 int 矿石数，转成只有铁矿的背包
            stats = data.setdefault("stats", {})
            inv = stats.get("inventory", 0)
            if not isinstance(inv, dict):
                stats["inventory"] = ({str(C.I_IRON_ORE): int(inv)}
                                      if inv else {})
            # 3) 科研站 stored：老档是 int（铁板数），转成电磁矩阵
            for ld in data.get("labs", []):
                st = ld.get("stored", 0)
                if not isinstance(st, dict):
                    ld["stored"] = ({str(C.I_SCIENCE_BLUE): int(st)}
                                    if st else {})
            # 4) 研究点清空（换成科研包体系，旧的 points 没意义了）
            tech = data.get("tech", {})
            tech.pop("points", None)
            data["version"] = 4
            v = 4
        if v == 4:
            # v4 -> v5：分拣器过滤数组（老档全填 0 = 不限）
            grid = data["grid"]
            if "overlay_filter" not in grid:
                ov = _unarr(grid["overlay"]) if "overlay" in grid else None
                shape = ov.shape if ov is not None else (data["grid"]["h"],
                                                         data["grid"]["w"])
                grid["overlay_filter"] = _arr(
                    np.zeros(shape, dtype=np.int32))
            data["version"] = 5
            v = 5
        if v == 5:
            # v5 -> v6：新增箱子 / 采矿机暂存。老档没有这两张表，
            # 补成空表即可（建筑本身存在网格里，读到之后 sync 会重建对象）。
            data.setdefault("miners", [])
            data.setdefault("chests", [])
            data["version"] = 6
            v = 6
        if v == 6:
            # v6 -> v7：M4 戴森云。老档没有发射器、没有轨道帆，
            # 补一个空 dyson 结构即可（发射器建筑在网格里，sync 会重建）。
            if "dyson" not in data:
                data["dyson"] = {
                    "orbit_count": [0] * C.DYSON_ORBITS,
                    "orbit_angle": [0.0] * C.DYSON_ORBITS,
                    "emitters": [],
                }
            data["version"] = 7
            v = 7
        if v == 7:
            # v7 -> v8：科研站双模式（M6.11）。老档科研站一律研究模式，
            # 补上 produce 相关空字段即可（load_into 也有 .get 兜底）。
            for ld in data.get("labs", []):
                ld.setdefault("mode", C.LAB_MODE_RESEARCH)
                ld.setdefault("recipe", None)
                ld.setdefault("inputs", {})
                ld.setdefault("outputs", {})
                ld.setdefault("progress", 0.0)
            data.setdefault("tech", {}).setdefault("queue", [])
            data["version"] = 8
            v = 8
        if v == 8:
            # v8 -> v9：轨道系统最小版。老档没有行星状态，角度从近日点 0° 开始。
            data.setdefault("planet", {
                "angle": 0.0,
                "period": C.PLANET_ORBIT_PERIOD,
                "eccentricity": C.PLANET_ECCENTRICITY,
            })
            data["version"] = 9
            v = 9
        if v == 9:
            # v9 -> v10：星际（多行星）。
            # 平铺结构（grid/belts/.../planet/camera/power）打包成 worlds[0]
            # 主行星；dyson / tech / stats 本来就是恒星级/玩家级，留顶层。
            w0 = {}
            for k in ("planet", "grid", "belts", "machines", "miners",
                      "chests", "towers", "labs", "drones", "camera",
                      "power"):
                if k in data:
                    w0[k] = data.pop(k)
            data.setdefault("worlds", [w0])
            data.setdefault("world_index", 0)
            data["version"] = 10
            v = 10
        if v == 10:
            # v10 -> v11（M7）：物品从数字 id 换成 "命名空间:名字"。
            # 数字查注册表转名字（本进程分配表稳定，原版/兼容段不漂移）；
            # 未知数字保留原样（读取时数字直通，行为与老档一致）。
            def _kv(d):
                return {_name(k): int(v) for k, v in (d or {}).items()}

            stats = data.setdefault("stats", {})
            if isinstance(stats.get("inventory"), dict):
                stats["inventory"] = _kv(stats["inventory"])
            for wd in data.get("worlds", []):
                for md in wd.get("machines", []):
                    md["inputs"] = _kv(md.get("inputs"))
                    md["outputs"] = _kv(md.get("outputs"))
                for md in wd.get("miners", []):
                    md["buffer"] = _kv(md.get("buffer"))
                for cd in wd.get("chests", []):
                    cd["store"] = _kv(cd.get("store"))
                for td in wd.get("towers", []):
                    td["inventory"] = _kv(td.get("inventory"))
                    f = td.get("filter")
                    td["filter"] = 0 if not f else _name(f)
                for ld in wd.get("labs", []):
                    if isinstance(ld.get("stored"), dict):
                        ld["stored"] = _kv(ld.get("stored"))
                    ld["inputs"] = _kv(ld.get("inputs"))
                    ld["outputs"] = _kv(ld.get("outputs"))
                for bd in wd.get("belts", []):
                    bd["items"] = [_name(x) for x in bd.get("items", [])]
                for dd in wd.get("drones", []):
                    if dd.get("cargo") is not None:
                        dd["cargo"] = _name(dd["cargo"])
                    if dd.get("task_item") is not None:
                        dd["task_item"] = _name(dd["task_item"])
            data["version"] = 11
            v = 11
        if v == 11:
            # v11 -> v12（M5b）：发射台（每行星）+ 舰队（顶层）。
            # 老档没有就是空表，读档后玩家重新建/自动配船。
            data.setdefault("ships", [])
            for wd in data.get("worlds", []):
                wd.setdefault("pads", [])
            data["version"] = 12
            v = 12
        if v == 12:
            # v12 -> v13（M14）：管道/储罐里的液体（每行星）。
            # 老档没有管道，所以空表就等价于"一滴液体都没有"。
            for wd in data.get("worlds", []):
                wd.setdefault("pipe_fluid", [])
            data["version"] = 13
            v = 13
        if v == 13:
            # v13 -> v14（M15d）：按玩家分背包。老档只有一个共享背包，
            # 整个装进 players["0"]（本地/单人玩家），行为与旧档一致。
            stats = data.setdefault("stats", {})
            inv = stats.get("inventory")
            data.setdefault("players", {
                "0": {"inventory": inv if isinstance(inv, dict) else {}}})
            data["version"] = 14
            return data
        raise ValueError(f"存档版本 {v} 太旧或不支持（当前 {SAVE_VERSION}）")

    # ---------- 文件读写 ----------

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def save(self, game, name: str = "save.slm") -> str:
        data = self.dump(game)
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        blob = MAGIC + zlib.compress(raw, 6)
        path = self._path(name)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)  # 原子替换，防止写一半崩了毁档
        self.last_save_time = time.time()
        return path

    def load(self, game, name: str = "save.slm") -> bool:
        path = self._path(name)
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            blob = f.read()
        if not blob.startswith(MAGIC):
            raise ValueError("不是有效的 .slm 存档")
        raw = zlib.decompress(blob[len(MAGIC):])
        data = json.loads(raw.decode("utf-8"))
        self.load_into(game, data)
        return True

    def save_auto(self, game) -> str:
        """自动存档轮转：autosave_0/1/2。"""
        for i in range(3):
            name = f"autosave_{i}.slm"
            p = self._path(name)
            if not os.path.exists(p):
                return self.save(game, name)
        # 全存在，找最旧的覆盖
        oldest_i, oldest_t = 0, float("inf")
        for i in range(3):
            p = self._path(f"autosave_{i}.slm")
            t = os.path.getmtime(p)
            if t < oldest_t:
                oldest_t, oldest_i = t, i
        return self.save(game, f"autosave_{oldest_i}.slm")

    def exists(self, name: str = "save.slm") -> bool:
        return os.path.exists(self._path(name))

    def info(self, name: str = "save.slm") -> dict | None:
        path = self._path(name)
        if not os.path.exists(path):
            return None
        return {"path": path, "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path)}

    # ---------- 多存档槽位（M6.20） ----------

    def slot_file(self, i: int) -> str:
        return f"slot_{i + 1}.slm"

    def slot_label(self, i: int) -> str:
        return f"存档 {i + 1}"

    def latest_autosave(self) -> str | None:
        """最新的自动存档文件名，没有就 None。"""
        best = None
        for i in range(3):
            n = f"autosave_{i}.slm"
            if self.exists(n):
                t = self.info(n)["mtime"]
                if best is None or t > best[0]:
                    best = (t, n)
        return best[1] if best else None

    def slot_meta(self, name: str) -> dict | None:
        """读一个存档文件的轻量摘要（不重建游戏）：行星 / 物品 / 版本 / 时间。"""
        path = self._path(name)
        if not os.path.exists(path):
            return None
        meta = {"mtime": os.path.getmtime(path)}
        try:
            with open(path, "rb") as f:
                blob = f.read()
            if not blob.startswith(MAGIC):
                return None
            data = json.loads(zlib.decompress(blob[len(MAGIC):])
                              .decode("utf-8"))
            worlds = data.get("worlds") or []
            wi = data.get("world_index", 0)
            meta["version"] = data.get("version")
            from ..world.planets import PLANETS
            if worlds and wi < len(PLANETS):
                meta["planet"] = PLANETS[wi].name
            else:
                meta["planet"] = None
            meta["items"] = self._total_items(data)
        except Exception:  # noqa: BLE001 半截档/坏档就当"有文件但读不了"
            meta["broken"] = True
        return meta

    @staticmethod
    def _total_items(data: dict) -> int:
        """在地物品总数：全部行星带子上的物品 + 背包。"""
        n = 0
        for wd in data.get("worlds") or []:
            for bd in wd.get("belts", []):
                n += len(bd.get("items", []))
        inv = (data.get("stats") or {}).get("inventory", {})
        if isinstance(inv, dict):
            n += sum(int(v) for v in inv.values())
        else:
            n += int(inv or 0)
        return n

    def slot_list(self) -> list[dict]:
        """6 个槽位的展示信息（一次遍历，面板打开时调用）。"""
        out = []
        for i in range(SAVE_SLOT_COUNT):
            name = self.slot_file(i)
            info = self.info(name)
            m = self.slot_meta(name) if info else None
            out.append({
                "index": i,
                "label": self.slot_label(i),
                "file": name,
                "has": info is not None,
                "mtime": (m or {}).get("mtime") or (info["mtime"]
                                                    if info else None),
                "size": info["size"] if info else None,
                "version": (m or {}).get("version"),
                "planet": (m or {}).get("planet"),
                "items": (m or {}).get("items"),
                "broken": bool((m or {}).get("broken")),
            })
        return out