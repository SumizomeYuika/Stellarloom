#!/usr/bin/env python3
"""科研包自检：电磁矩阵产线 + 科研站吃包推进科技。

跑法：python tools/_sciencecheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.production import MachineNetwork
from stellarloom.tech import LabNetwork, TechTree
from stellarloom.world import WorldGrid


def main():
    fails = []

    # 1. 电磁矩阵配方存在、是科研站配方、原料都有来源
    r = C.RECIPES.get("science_blue")
    print(f"[1] science_blue 配方: {r}")
    if r is None or r[3] is None or C.B_LAB not in r[3]:
        fails.append("电磁矩阵不是科研站配方")
    for item in r[0]:
        src = [rid for rid, rr in C.RECIPES.items() if item in rr[1]]
        if not src:
            fails.append(f"电磁矩阵原料 {C.ITEM_NAMES.get(item, item)} 无来源")

    # 2. 所有科技都必须有科研包配方映射
    miss = [t for t in C.TECH_TREE if t not in C.TECH_PACK_RECIPE]
    print(f"[2] 缺科研包映射的科技: {miss}")
    if miss:
        fails.append("有科技没配科研包")
    for t, rid in C.TECH_PACK_RECIPE.items():
        if rid not in C.RECIPES:
            fails.append(f"科技 {t} 指向不存在的配方 {rid}")

    # 3. 科研站只收科研包，拒收铁板/矿石
    g = WorldGrid(64, 64)
    g.place(10, 10, C.B_LAB)
    labs = LabNetwork(g)
    tech = TechTree()
    labs.bind(tech)
    labs.sync()
    ok_pack = labs.feed(10, 10, C.I_SCIENCE_BLUE)
    bad_plate = labs.feed(10, 10, C.I_IRON_PLATE)
    bad_ore = labs.feed(10, 10, C.I_IRON_ORE)
    print(f"[3] 喂电磁矩阵={ok_pack} 喂铁板={bad_plate} 喂矿石={bad_ore}")
    if not ok_pack or bad_plate or bad_ore:
        fails.append("科研站收料判定不对")

    # 4. 消耗科研包推进科技，够数就完成
    tech.start("logistics1")
    cost = C.TECH_TREE["logistics1"][1]
    g2 = WorldGrid(64, 64)
    g2.place(20, 20, C.B_LAB)
    labs2 = LabNetwork(g2)
    labs2.bind(tech)
    labs2.sync()
    labs2.labs[(20, 20)]["stored"] = {C.I_SCIENCE_BLUE: cost}
    for _ in range(cost * 2):
        labs2.update(C.LAB_CONSUME_INTERVAL, 1.0)
    print(f"[4] 吃 {cost} 个包后: researched={sorted(tech.researched)} "
          f"current={tech.current} 剩余包="
          f"{labs2.labs[(20, 20)]['stored']}")
    if "logistics1" not in tech.researched:
        fails.append("科研站吃够包没完成科技")
    if labs2.labs[(20, 20)]["stored"]:
        fails.append("研究完成后还在吃包")

    # 5. 没有研究目标时不吃包（避免白烧）
    tech2 = TechTree()
    g3 = WorldGrid(64, 64)
    g3.place(30, 30, C.B_LAB)
    labs3 = LabNetwork(g3)
    labs3.bind(tech2)
    labs3.sync()
    labs3.labs[(30, 30)]["stored"] = {C.I_SCIENCE_BLUE: 5}
    for _ in range(10):
        labs3.update(C.LAB_CONSUME_INTERVAL, 1.0)
    left = labs3.labs[(30, 30)]["stored"].get(C.I_SCIENCE_BLUE, 0)
    print(f"[5] 没研究时吃包后剩余: {left} (期望 5)")
    if left != 5:
        fails.append("没研究目标时仍然烧包")

    # 6. 研究目标完成后能接着研究下一个（前置检查）
    tech2.start("power1")
    ok, why = tech2.can_research("wind1")
    print(f"[6] power1 未完成时能研究 wind1: {ok} ({why})")
    if ok:
        fails.append("前置科技没完成也能研究")
    tech2.add_pack_progress(C.TECH_TREE["power1"][1])
    ok2, _ = tech2.can_research("wind1")
    print(f"[6b] power1 完成后能研究 wind1: {ok2}")
    if not ok2:
        fails.append("前置完成后仍不能研究")

    # 7. 科技不进机器配方列表（手搓/科技门槛检查）
    net = MachineNetwork(WorldGrid(64, 64))
    asm = net and C.RECIPES["science_blue"][3]
    print(f"[7] 电磁矩阵允许建筑: "
          f"{[C.BUILDING_NAMES.get(b, b) for b in asm]}")
    if C.B_LAB not in asm:
        fails.append("电磁矩阵不是科研站造的")

    # 8. 科研站制造模式：喂原料能在够时产出矩阵
    g4 = WorldGrid(64, 64)
    g4.place(40, 40, C.B_LAB)
    labs4 = LabNetwork(g4)
    tech3 = TechTree()
    labs4.bind(tech3)
    labs4.sync()
    labs4.set_mode(40, 40, C.LAB_MODE_PRODUCE)
    labs4.set_recipe(40, 40, "science_blue")
    need = C.RECIPES["science_blue"][0]
    for it, n in need.items():
        labs4.labs[(40, 40)]["inputs"][it] = n
    dur = C.RECIPES["science_blue"][2]
    for _ in range(int(dur / 0.1) + 5):
        labs4.update(0.1, 1.0)
    produced = labs4.labs[(40, 40)]["outputs"].get(C.I_SCIENCE_BLUE, 0)
    print(f"[8] 科研站制造模式产出电磁矩阵: {produced}（期望 >=1）")
    if produced < 1:
        fails.append("科研站制造模式没产出矩阵")

    print()
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        return 1
    print("PASS 科研包体系全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())