#!/usr/bin/env python3
"""存档往返自检：不需要 pygame / display。

构造一个假 Game（只用 numpy 网络层），插几条带子+物品+机器+塔+无人机，
存档 -> 读档 -> 比对。跑法：
    python tools/_savecheck.py
"""

from __future__ import annotations

import os
import sys
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, DroneNetwork, InserterNetwork, TowerNetwork
from stellarloom.production import ChestNetwork, MachineNetwork, MinerNetwork
from stellarloom.save import SaveManager
from stellarloom.save.savefile import SAVE_VERSION
from stellarloom.tech import LabNetwork, TechTree
from stellarloom.world import PlanetOrbit, WorldGrid


class FakePower:
    time = 12.5
    day_length = 120.0


class FakeCamera:
    x = 123.0
    y = 456.0
    zoom = 0.9


class FakeChunks:
    def clear(self):
        pass


class FakeGame:
    def __init__(self):
        self.grid = WorldGrid(64, 64)
        self.belts = BeltNetwork(self.grid)
        self.machines = MachineNetwork(self.grid)
        self.miners = MinerNetwork(self.grid)
        self.chests = ChestNetwork(self.grid)
        self.inserters = InserterNetwork(self.grid, self.belts)
        self.inserters.chests = self.chests
        self.inserters.miners = self.miners
        self.towers = TowerNetwork(self.grid)
        self.drones = DroneNetwork(self.grid)
        self.labs = LabNetwork(self.grid)
        self.tech = TechTree()
        self.labs.bind(self.tech)
        self.inserters.labs = self.labs
        self.power = FakePower()
        self.camera = FakeCamera()
        self.chunks = FakeChunks()
        self.inventory: dict[int, int] = dict(C.STARTING_ITEMS)
        self.planet = PlanetOrbit()
        # 存档 v10：worlds 数组。FakeGame 平铺字段 = 单行星，把自身当 world 0，
        # dump 用 ws.grid / ws.belts / ... 取到的就是同一批对象。
        self.worlds = [self]
        self.world_index = 0


def build_world(g: FakeGame):
    gr = g.grid
    # 一条 8 格向右传送带
    for i in range(8):
        gr.place(10 + i, 20, C.B_BELT, 0)
    # 熔炉 + 制造台 + 科研站
    gr.place(20, 20, C.B_FURNACE, 0)
    gr.place(24, 24, C.B_ASSEMBLER, 0)
    gr.place(28, 28, C.B_LAB, 0)
    # 一座供应塔 + 一座请求塔
    gr.place(40, 40, C.B_TOWER_SUPPLY, 0)
    gr.place(50, 50, C.B_TOWER_REQUEST, 0)
    gr.belts_changed()

    g.belts.rebuild()
    g.machines.sync()
    g.towers.sync(g.drones)
    g.labs.sync()

    # 往带子里塞物品，手动摆浮点位置
    lane = g.belts.lanes[0]
    lane.positions = np.array([0.25, 1.5, 3.75, 6.125], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE, C.I_IRON_PLATE,
                           C.I_CIRCUIT, C.I_IRON_ORE], dtype=np.int32)

    # 机器状态
    m = g.machines.machines[(24, 24)]
    m.set_recipe("gear")
    m.inputs = {C.I_IRON_PLATE: 2}
    m.outputs = {C.I_GEAR: 3}
    m.progress = 0.4

    # 塔库存 + 过滤
    tw_s = g.towers.towers[(40, 40)]
    tw_s.inventory = {C.I_IRON_PLATE: 12}
    tw_s.filter = C.I_IRON_PLATE
    tw_r = g.towers.towers[(50, 50)]
    tw_r.inventory = {C.I_GEAR: 3}

    # 科研站
    g.labs.labs[(28, 28)]["stored"] = {C.I_SCIENCE_BLUE: 5}
    g.labs.labs[(28, 28)]["timer"] = 1.25

    # 一个带过滤的分拣器（只抓铁矿石），用来验证过滤数组存档往返
    if gr.place_overlay(12, 20, C.B_INSERTER, 0):
        gr.set_overlay_filter(12, 20, C.I_IRON_ORE)

    # 箱子 + 采矿机（v6 新增，验证暂存往返）
    gr.place(30, 30, C.B_CHEST, 0)
    ys, xs = np.nonzero(gr.ore > 0)
    if len(xs):
        gr.place(int(xs[0]), int(ys[0]), C.B_MINER, 0)
    g.chests.sync()
    g.miners.sync()
    chest = g.chests.get(30, 30)
    if chest is not None:
        chest.store = {C.I_IRON_PLATE: 7, C.I_GEAR: 2}
    for mn in g.miners.miners.values():
        mn.buffer = {C.I_IRON_ORE: 13}
        break

    # 科技
    g.tech.researched = {"logistics1", "power1"}
    g.tech.current = "circuit1"
    g.tech.progress = 7
    # 背包和科研站喂料
    g.inventory = {C.I_IRON_PLATE: 41, C.I_GEAR: 12, C.I_BELT_ITEM: 7}

    # 无人机改一下电量/位置
    if g.drones.drones:
        d = g.drones.drones[0]
        d.x, d.y, d.energy = 43.5, 41.25, 42.0

    # 行星角度（轨道系统最小版）：非零值，验证存档往返
    g.planet.angle = 137.0
    g.planet.period = 300.0
    g.planet.eccentricity = 0.3


def snapshot(g: FakeGame) -> dict:
    lane = g.belts.lanes[0]
    m = g.machines.machines[(24, 24)]
    tw_s = g.towers.towers[(40, 40)]
    d = g.drones.drones[0] if g.drones.drones else None
    chest = g.chests.get(30, 30)
    mn = next(iter(g.miners.miners.values()), None)
    return {
        "lane_cells": list(lane.cells),
        "lane_positions": [round(float(p), 6) for p in lane.positions],
        "lane_items": [int(i) for i in lane.items],
        "lane_next": int(lane.next_lane),
        "machine_recipe": m.recipe_id,
        "machine_inputs": dict(m.inputs),
        "machine_outputs": dict(m.outputs),
        "machine_progress": round(m.progress, 6),
        "tower_inv": dict(tw_s.inventory),
        "tower_filter": tw_s.filter,
        "lab_stored": dict(g.labs.labs[(28, 28)]["stored"]),
        "lab_timer": round(g.labs.labs[(28, 28)]["timer"], 6),
        "tech_researched": sorted(g.tech.researched),
        "tech_current": g.tech.current,
        "tech_progress": round(g.tech.progress, 6),
        "power_time": round(g.power.time, 6),
        "drones_n": len(g.drones.drones),
        "drone0": (round(d.x, 4), round(d.y, 4), round(d.energy, 4)) if d else None,
        "inventory": dict(g.inventory),
        "chest_store": dict(chest.store) if chest else None,
        "miner_buffer": dict(mn.buffer) if mn else None,
        "miner_n": len(g.miners.miners),
        "chest_n": len(g.chests.chests),
        "ore_sum": int(g.grid.ore.sum()),
        "ore_type_sum": int(g.grid.ore_type.sum()),
        "overlay_filter_sum": int(g.grid.overlay_filter.sum()),
        "planet_angle": round(g.planet.angle, 6),
        "planet_period": round(g.planet.period, 6),
        "planet_ecc": round(g.planet.eccentricity, 6),
    }


def _downgrade(data: dict, ver: int) -> dict:
    """把 v4 存档数据降级成 v1/v2/v3 的形状，用来实测迁移链。"""
    import copy
    d = copy.deepcopy(data)
    # v11（M7）：物品名字键 → 数字键，降级链在纯数字域跑，
    # 迁移升回来时 v10->v11 会自动转回名字，自洽。
    from stellarloom.registry import ITEM_REGISTRY

    def _num(kv):
        out = {}
        for k, v in (kv or {}).items():
            s = str(k)
            try:
                out[ITEM_REGISTRY.id_of(k)] = int(v)
            except Exception:
                out[int(s) if s.lstrip("-").isdigit() else s] = v
        return out

    stats = d.setdefault("stats", {})
    if isinstance(stats.get("inventory"), dict):
        stats["inventory"] = _num(stats["inventory"])
    worlds = d.get("worlds")
    wlist = worlds if isinstance(worlds, list) else [d]
    for wd in wlist:
        for md in wd.get("machines", []):
            md["inputs"] = _num(md.get("inputs"))
            md["outputs"] = _num(md.get("outputs"))
        for md in wd.get("miners", []):
            md["buffer"] = _num(md.get("buffer"))
        for cd in wd.get("chests", []):
            cd["store"] = _num(cd.get("store"))
        for td in wd.get("towers", []):
            td["inventory"] = _num(td.get("inventory"))
            f = td.get("filter")
            if f:
                s = str(f)
                try:
                    td["filter"] = ITEM_REGISTRY.id_of(f)
                except Exception:
                    td["filter"] = int(s) if s.lstrip("-").isdigit() else f
        for ld in wd.get("labs", []):
            if isinstance(ld.get("stored"), dict):
                ld["stored"] = _num(ld.get("stored"))
            ld["inputs"] = _num(ld.get("inputs"))
            ld["outputs"] = _num(ld.get("outputs"))
        for bd in wd.get("belts", []):
            bd["items"] = [
                (ITEM_REGISTRY.id_of(x) if not str(x).lstrip("-").isdigit()
                 else int(x)) for x in bd.get("items", [])]
        for dd in wd.get("drones", []):
            if dd.get("cargo") is not None:
                s = str(dd["cargo"])
                dd["cargo"] = int(s) if s.lstrip("-").isdigit() \
                    else ITEM_REGISTRY.id_of(s)
            if dd.get("task_item") is not None:
                s = str(dd["task_item"])
                dd["task_item"] = int(s) if s.lstrip("-").isdigit() \
                    else ITEM_REGISTRY.id_of(s)
    # v10 结构（worlds 数组）-> 先提回 v9 平铺，再按旧逻辑继续降级
    if "worlds" in d:
        worlds = d.pop("worlds")
        w0 = worlds[0] if worlds else {}
        for k in ("planet", "grid", "belts", "machines", "miners", "chests",
                  "towers", "labs", "drones", "camera", "power"):
            if k in w0:
                d[k] = w0[k]
        d.pop("world_index", None)
    grid = d["grid"]
    # v4 字段：ore_type 数组 + 分拣器过滤数组
    grid.pop("ore_type", None)
    grid.pop("overlay_filter", None)
    # v3 -> v4 的三处：int 背包 / int 科研站 / 有 points
    d["stats"]["inventory"] = int(sum(d["stats"]["inventory"].values()))
    for ld in d["labs"]:
        ld["stored"] = int(sum(ld["stored"].values()))
    d["tech"]["points"] = 42.0
    d["version"] = 3
    # v5 及更早都没有箱子/采矿机暂存表，删掉让迁移补空表
    d.pop("miners", None)
    d.pop("chests", None)
    if ver <= 2:
        # v2 -> v3：机器单值 output
        for md in d["machines"]:
            outs = md.pop("outputs", {})
            total = sum(outs.values())
            md["output"] = (int(next(iter(outs))) if outs and total else None)
        d["version"] = 2
    if ver <= 1:
        # v1 -> v2：没有 overlay，分拣器在 building 里
        grid.pop("overlay", None)
        grid.pop("overlay_dir", None)
        bld = _unarr_local(grid["building"])
        dirc = _unarr_local(grid["direction"])
        # 把两格传送带改成 B_INSERTER，模拟老档里的分拣器
        for (x, y) in ((10, 20), (11, 20)):
            if bld[y, x] == C.B_BELT:
                bld[y, x] = C.B_INSERTER
        grid["building"] = _arr_local(bld)
        grid["direction"] = _arr_local(dirc)
        d["version"] = 1
    return d


def _unarr_local(d: dict) -> np.ndarray:
    from stellarloom.save.savefile import _unarr
    return _unarr(d)


def _arr_local(a: np.ndarray) -> dict:
    from stellarloom.save.savefile import _arr
    return _arr(a)


def check_migrations(data: dict, sm: SaveManager) -> int:
    """v1 / v2 / v3 三条老档路径 -> v4 实测。"""
    bad = 0
    for ver in (1, 2, 3):
        old = _downgrade(data, ver)
        g = FakeGame()
        try:
            sm.load_into(g, old)
        except Exception as e:  # noqa: BLE001
            print(f"  !! v{ver}->v{SAVE_VERSION} 迁移抛异常: {type(e).__name__}: {e}")
            bad += 1
            continue
        if old["version"] != SAVE_VERSION:
            print(f"  !! v{ver}->v{SAVE_VERSION} 版本号没升到，实际 {old['version']}")
            bad += 1
        # ore_type 必须补齐，且只在该有矿的格子填了矿
        if int(g.grid.ore_type.sum()) <= 0:
            print(f"  !! v{ver}->v{SAVE_VERSION} ore_type 空")
            bad += 1
        # 背包必须是 dict
        if not isinstance(g.inventory, dict):
            print(f"  !! v{ver}->v{SAVE_VERSION} 背包不是 dict")
            bad += 1
        # 分拣器过滤数组必须补齐且全 0（不限）
        if not hasattr(g.grid, "overlay_filter"):
            print(f"  !! v{ver}->v{SAVE_VERSION} 缺 overlay_filter 数组")
            bad += 1
        elif int(g.grid.overlay_filter.sum()) != 0:
            print(f"  !! v{ver}->v{SAVE_VERSION} 老档过滤值应为全 0，实际和={int(g.grid.overlay_filter.sum())}")
            bad += 1
        # 科研站 stored 必须是 dict
        for lab in g.labs.labs.values():
            if not isinstance(lab["stored"], dict):
                print(f"  !! v{ver}->v{SAVE_VERSION} 科研站 stored 不是 dict")
                bad += 1
                break
        # 机器配方不能丢（v2 的单值 output 必须变成 dict）
        for m in g.machines.machines.values():
            if not isinstance(m.outputs, dict):
                print(f"  !! v{ver}->v{SAVE_VERSION} 机器 outputs 不是 dict")
                bad += 1
                break
        if ver == 1:
            ins = int((g.grid.overlay == C.B_INSERTER).sum())
            if ins != 2:
                print(f"  !! v1->v4 分拣器没搬进 overlay（期望 2，实际 {ins}）")
                bad += 1
            if int((g.grid.building == C.B_INSERTER).sum()) != 0:
                print("  !! v1->v4 building 里还残留分拣器")
                bad += 1
        print(f"  v{ver}->v{SAVE_VERSION} 迁移 OK（ore_type 和={int(g.grid.ore_type.sum())}，"
              f"背包 {dict(list(g.inventory.items())[:3])}）")
    return bad


def main():
    tmp_dir = "/tmp/slm_savecheck"
    os.makedirs(tmp_dir, exist_ok=True)
    for f in os.listdir(tmp_dir):
        os.remove(os.path.join(tmp_dir, f))

    a = FakeGame()
    build_world(a)
    a.inserters.cooldowns[(5, 5)] = 0.4      # M11：冷却也要进存档
    before = snapshot(a)

    sm = SaveManager(tmp_dir)
    path = sm.save(a, "t.slm")
    size = os.path.getsize(path)
    print(f"[存档] {path}  {size} 字节")
    bad = 0

    # M7：持久化用命名空间名字（"stellarloom:iron_ore"），不是数字
    nd = sm.dump(a)
    inv_keys = list(nd["stats"]["inventory"])
    named = all(":" in str(k) for k in inv_keys)
    if not named:
        print(f"  !! 存档物品键没名字化: {inv_keys}")
        bad += 1
    else:
        print(f"[M7] 存档物品键名字化 ✓ {sorted({str(k).split(':')[0] for k in inv_keys})} 命名空间")
    # 旧数字档（v10）直接读：数字 1 必须对上铁矿石，往返不丢
    old10 = copy.deepcopy(nd)
    old10["version"] = 10
    old10["stats"]["inventory"] = {"1": 5, "101": 3}
    for wd in old10.get("worlds", []):
        for md in wd.get("machines", []):
            md["inputs"] = {"1": 2}
            md["outputs"] = {"2": 1}
    g_old = FakeGame()
    sm.load_into(g_old, old10)
    if g_old.inventory.get(C.I_IRON_ORE) == 5 \
            and g_old.inventory.get(C.I_BELT_ITEM) == 3:
        print("[M7] 旧数字档兼容 ✓（1→铁矿石 101→传送带）")
    else:
        print(f"  !! 旧数字档兼容失败: {g_old.inventory}")
        bad += 1

    b = FakeGame()
    ok = sm.load(b, "t.slm")
    cd = b.inserters.cooldowns.get((5, 5))
    cd_ok = abs((cd or 0.0) - 0.4) <= 0.05
    if cd_ok:
        print(f"[M11] 分拣器冷却读档恢复 ✓ {cd:.2f}s")
    else:
        print(f"  !! FAIL 分拣器冷却没恢复: {cd}")
    print(f"[读档] {ok}")
    after = snapshot(b)

    bad = 0 if cd_ok else 1
    for k in before:
        if before[k] != after[k]:
            bad += 1
            print(f"  !! {k}: 存={before[k]} 读={after[k]}")
    if bad:
        print(f"\n不一致 {bad} 项 FAIL")
        return 1
    print("\n全部字段一致 PASS")
    print(f"  带子物品浮点位置: {after['lane_positions']}")
    print(f"  无人机: {after['drones_n']} 台, 0号 {after['drone0']}")
    print(f"  科技: {after['tech_researched']} 当前={after['tech_current']}")

    # 自动存档轮转
    for i in range(4):
        sm.save_auto(a)
    autos = sorted(f for f in os.listdir(tmp_dir) if f.startswith("autosave_"))
    print(f"  自动存档文件: {autos}")
    assert len(autos) == 3, "轮转槽位必须是 3"

    # ---------- 多存档槽位（M6.20） ----------
    print("\n[多存档] 槽位独立 + 摘要:")
    slots_bad = 0
    slots = sm.slot_list()
    if len(slots) != 6:
        print(f"  !! 槽位数应为 6，实际 {len(slots)}")
        slots_bad += 1
    # 槽 1 存 A、槽 2 存 B（不同内容），互不影响
    if sm.save(a, sm.slot_file(0)) and sm.save(a, sm.slot_file(1)):
        g1 = FakeGame()
        g2 = FakeGame()
        sm.load(g1, sm.slot_file(0))
        sm.load(g2, sm.slot_file(1))
        s1 = snapshot(g1)
        s2 = snapshot(g2)
        if s1 != before or s2 != before:
            print("  !! 槽里读出的快照与存前不一致")
            slots_bad += 1
    else:
        print("  !! 存槽失败")
        slots_bad += 1
    # 槽独立：存 A 后改 A 再存槽 1，槽 2 内容不变（还是 B）
    a.grid.place(1, 1, C.B_SOLAR, 0)
    a.grid.overlay_gen += 1
    sm.save(a, sm.slot_file(0))
    g1b = FakeGame()
    sm.load(g1b, sm.slot_file(0))
    g2b = FakeGame()
    sm.load(g2b, sm.slot_file(1))
    if int((g1b.grid.building == C.B_SOLAR).sum()) != 1:
        print("  !! 槽1 重存后太阳能没进去")
        slots_bad += 1
    if int((g2b.grid.building == C.B_SOLAR).sum()) != 0:
        print("  !! 槽2 被槽1 污染（多存档隔离失效）")
        slots_bad += 1
    # 摘要
    m0 = sm.slot_meta(sm.slot_file(0))
    if m0 is None or not m0.get("items") or "planet" not in m0:
        print(f"  !! 槽1 摘要异常: {m0}")
        slots_bad += 1
    else:
        print(f"  槽1 摘要: 行星={m0['planet']} 物品={m0['items']} "
              f"v{m0.get('version')}")
    # 空槽读档返回 False 不崩
    sm = SaveManager(tmp_dir)  # 同一目录
    for i in range(3, 6):  # 槽 4-6 应该还没存
        if sm.load(FakeGame(), sm.slot_file(i)):
            print(f"  !! 空槽 {i + 1} 竟然读档成功")
            slots_bad += 1
    # 最新自动存档
    la = sm.latest_autosave()
    if la is None or not la.startswith("autosave_"):
        print(f"  !! latest_autosave 异常: {la}")
        slots_bad += 1
    if slots_bad:
        print(f"\n多存档 {slots_bad} 项 FAIL")
        return 1
    print("  槽位独立 / 摘要 / 空槽 / 自动档 全部 PASS")

    # v1/v2/v3 老档 -> v4 迁移实测
    print(f"\n[迁移链] 老档 -> v{SAVE_VERSION}")
    mbad = check_migrations(sm.dump(a), sm)
    if mbad:
        print(f"\n迁移 {mbad} 项 FAIL")
        return 1
    print("\n迁移链全部 PASS")

    # ---------- v14（M15d）：按玩家分背包 ----------
    print("\n[v14] 按玩家分背包:")
    from stellarloom.sim.sim import Simulation
    pbad = 0
    s = Simulation()
    s.players[0].inventory[C.I_GEAR] = 4          # 本地玩家
    s.ensure_player(1).inventory[C.I_IRON_PLATE] = 9   # 联机玩家 1
    d14 = sm.dump(s)
    if d14.get("version") != SAVE_VERSION:
        print(f"  !! dump 版本不是 {SAVE_VERSION}: {d14.get('version')}")
        pbad += 1
    pl = d14.get("players") or {}
    if pl.get("1", {}).get("inventory", {}).get("stellarloom:iron_plate") != 9:
        print(f"  !! players[1] 没进存档: {pl.keys()}")
        pbad += 1
    s2 = Simulation()
    sm.load_into(s2, d14)
    if s2.players.get(1) is None or s2.players[1].inventory.get(C.I_IRON_PLATE) != 9:
        print(f"  !! 读档后 players[1] 背包错: {s2.players.keys()}")
        pbad += 1
    if s2.players[0].inventory.get(C.I_GEAR) != 4:
        print("  !! 读档后 players[0] 背包错")
        pbad += 1
    # 老档（v13，无 players 表）迁移：共享背包装进 players[0]
    d13 = copy.deepcopy(d14)
    d13.pop("players", None)
    d13["version"] = 13
    want = {_load_key_local(k): v
            for k, v in d13["stats"]["inventory"].items()}
    s3 = Simulation()
    sm.load_into(s3, d13)
    if d13["version"] != SAVE_VERSION:
        print(f"  !! v13 迁移没升到 {SAVE_VERSION}: {d13['version']}")
        pbad += 1
    if dict(s3.players[0].inventory) != want:
        print(f"  !! v13 迁移背包错: {s3.players[0].inventory} != {want}")
        pbad += 1
    if len(s3.players) != 1:
        print(f"  !! 单机档应只有 player 0，实际 {sorted(s3.players)}")
        pbad += 1
    if pbad:
        print(f"\nv14 分背包 {pbad} 项 FAIL")
        return 1
    print("  players 表往返 ✓ v13→v14 迁移 ✓ 单机单玩家 ✓")
    return 0


def _load_key_local(k):
    from stellarloom.save.savefile import _load_key
    return _load_key(k)


if __name__ == "__main__":
    sys.exit(main())
