#!/usr/bin/env python3
"""戴森云自检（M4）：太阳帆产线 + 发射器 + 轨道容量 + 发电 + 存档。

跑法：python tools/_dysoncheck.py
不需要 pygame。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.logistics.dyson import DysonNetwork, Emitter
from stellarloom.tech import TechTree
from stellarloom.world import WorldGrid


def item_name(i) -> str:
    return C.ITEM_NAMES.get(i, f"?{i}")


def main():
    fails = []

    # ---------- 1. 配方与物品齐备 ----------
    print("[1] 戴森云相关配方:")
    for rid in ("solar_sail", "emitter", "science_red", "grain"):
        r = C.RECIPES.get(rid)
        if r is None:
            fails.append(f"缺配方 {rid}")
            print(f"    !! {rid} 不存在")
            continue
        ins = " + ".join(f"{item_name(i)}×{n}" for i, n in r[0].items())
        outs = " + ".join(f"{item_name(i)}×{n}" for i, n in r[1].items())
        print(f"    {rid:12s} {ins}  ->  {outs}   {r[2]}s  {r[3]}")
        if not r[3]:
            fails.append(f"{rid} 不能自动化（allows 为空）")
        for item in r[0]:
            # 矿石是徒手/矿机直接挖的，不算"没有来源"
            if item in C.ORE_TO_ITEM.values():
                continue
            if not any(item in rr[1] for rr in C.RECIPES.values()):
                fails.append(f"{rid} 的原料 {item_name(item)} 没有产出来源")
    if C.RECIPES["solar_sail"][1].get(C.I_SOLAR_SAIL, 0) < 2:
        fails.append("太阳帆配方一份料出不到 2 片")

    # ---------- 2. 发射器物品/建筑/科技锁三件套齐 ----------
    print("[2] 建筑 ↔ 物品 ↔ 科技锁:")
    print(f"    B_EMITTER={C.B_EMITTER}  I_EMITTER_ITEM={C.I_EMITTER_ITEM}")
    if C.BUILD_ITEM.get(C.B_EMITTER) != C.I_EMITTER_ITEM:
        fails.append("BUILD_ITEM 没配发射器")
    if "emitter" not in C.RECIPES:
        fails.append("发射器没有配方")
    elif list(C.RECIPES["emitter"][1].keys()) != [C.I_EMITTER_ITEM]:
        fails.append("发射器配方产出的不是发射器物品")
    lock = C.TECH_UNLOCK_BUILDING.get(C.B_EMITTER)
    print(f"    科技锁: {lock}")
    if lock is None:
        fails.append("发射器没有科技锁")
    elif lock not in C.TECH_TREE:
        fails.append(f"发射器的科技锁 {lock} 不在科技树里")
    if C.POWER_USAGE.get(C.B_EMITTER) is None:
        fails.append("发射器没有耗电登记")

    # ---------- 3. 轨道容量 + 发射 ----------
    print("[3] 轨道发射:")
    g = WorldGrid(64, 64)
    dyson = DysonNetwork(g)
    tech = TechTree()
    dyson.bind(tech)

    # 没研究科技时一条轨道都没解锁，打不出去
    n0 = dyson.launch(5)
    print(f"    无科技解锁时发射 {n0} 片（应为 0）")
    if n0 != 0:
        fails.append("没研究 dyson1 就能往轨道打帆")

    # 研究 dyson1 解锁内轨
    tech.researched.add("dyson1")
    print(f"    dyson1 后解锁轨道数: {dyson.unlocked_orbits()}（应为 1）")
    if dyson.unlocked_orbits() != 1:
        fails.append("dyson1 应只解锁内轨")

    cap0 = C.DYSON_ORBIT_CAP[0]
    n1 = dyson.launch(cap0 + 10)
    print(f"    内轨容量 {cap0}，尝试打 {cap0 + 10} 片，实际 {n1}")
    if n1 != cap0:
        fails.append("内轨没有按容量封顶")
    if dyson.total_sails() != cap0:
        fails.append("总帆数不对")

    # 满了之后再打应该 0
    if dyson.launch(1) != 0:
        fails.append("轨道满了还能继续打帆")

    # dyson2 解锁剩余两条
    tech.researched.add("dyson2")
    print(f"    dyson2 后解锁轨道数: {dyson.unlocked_orbits()}（应为 {C.DYSON_ORBITS}）")
    if dyson.unlocked_orbits() != C.DYSON_ORBITS:
        fails.append("dyson2 应解锁全部轨道")
    n2 = dyson.launch(10)
    print(f"    解锁后继续打 10 片，实际 {n2}")
    if n2 != 10:
        fails.append("解锁中轨后打不出去帆")

    # ---------- 4. 发电与效率 ----------
    print("[4] 发电:")
    base_power = dyson.power_output()
    expect = dyson.total_sails() * C.DYSON_SAIL_POWER
    print(f"    {dyson.total_sails()} 帆 -> {base_power:.1f} kW（期望 {expect:.1f}）")
    if abs(base_power - expect) > 1e-6:
        fails.append("发电量与帆数×单帆功率不符")
    tech.researched.add("sail1")
    eff_power = dyson.power_output()
    print(f"    sail1 研究后 -> {eff_power:.1f} kW（期望 {base_power * 1.5:.1f}）")
    if abs(eff_power - base_power * 1.5) > 1e-6:
        fails.append("sail1 效率加成没生效")

    # ---------- 5. 发射器囤帆 + 定时发射 ----------
    print("[5] 发射器:")
    g2 = WorldGrid(64, 64)
    g2.place(30, 30, C.B_EMITTER)
    d2 = DysonNetwork(g2)
    t2 = TechTree()
    t2.researched.add("dyson1")
    d2.bind(t2)
    d2.sync()
    em = d2.get(30, 30)
    if em is None:
        fails.append("发射器 sync 没建出对象")
    else:
        # 拒收非太阳帆
        if em.feed(C.I_IRON_PLATE):
            fails.append("发射器收了铁板")
        n = 0
        while em.feed(C.I_SOLAR_SAIL):
            n += 1
            if n > C.DYSON_EMITTER_STORE_CAP + 2:
                break
        print(f"    喂太阳帆 {n} 片（上限 {C.DYSON_EMITTER_STORE_CAP}）")
        if n != C.DYSON_EMITTER_STORE_CAP:
            fails.append("发射器储存上限不对")
        # 推足够时间让它把帆全部打出去
        total = 0.0
        before = d2.total_sails()
        for _ in range(400):
            d2.update(C.DYSON_LAUNCH_INTERVAL, 1.0)
            total += C.DYSON_LAUNCH_INTERVAL
        after = d2.total_sails()
        launched = after - before
        print(f"    推进 {total:.1f}s 后：轨道 +{launched} 帆，发射器剩 "
              f"{em.total()} 片，累计发射 {em.launched}")
        if launched <= 0:
            fails.append("发射器没有发射")
        if em.total() != 0:
            fails.append("发射器没把帆打完")
        if em.launched != launched:
            fails.append("发射器累计发射数与轨道增量不符")

    # ---------- 6. 存档往返 ----------
    print("[6] 存档往返:")
    d = dyson.dump()
    g3 = WorldGrid(64, 64)
    d3 = DysonNetwork(g3)
    d3.bind(tech)
    d3.load_from(d)
    same = (d3.orbit_count == dyson.orbit_count
            and d3.total_sails() == dyson.total_sails())
    print(f"    帆数 {dyson.orbit_count} -> {d3.orbit_count}  一致={same}")
    if not same:
        fails.append("戴森云存档往返不一致")

    print()
    if fails:
        for f in fails:
            print(f"!! FAIL {f}")
        print("FAIL 戴森云自检未通过")
        return 1
    print("PASS 戴森云自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())