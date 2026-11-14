#!/usr/bin/env python3
"""开局可行性自检：确认没有任何死锁。

检查项：
1. 初始能放的建筑里，至少有一台发电
2. 分拣器初始解锁（否则物资链断）
3. 开局供电 > 开局必需耗电
4. 从零开始能推完第一个科技（模拟产能链）
5. 科技闭包可达：从开局背包做闭包迭代，所有科技都必须最终能研究
   （历史上这里出现过完美死锁：circuit 配方被 circuit1 锁，
    而 circuit1 的科研包又要电路板 → 全部 7 个科技都研究不了）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.power import PowerGrid
from stellarloom.tech import TechTree
from stellarloom.world import WorldGrid


def main():
    ok = True

    # --- 1. 初始解锁集合 ---
    tech = TechTree()
    unlocked = [b for b in C.BUILDING_NAMES if tech.is_unlocked(b)]
    print("初始解锁建筑:", [C.BUILDING_NAMES[b] for b in unlocked])

    has_gen = any(b in C.POWER_GEN for b in unlocked)
    print(f"  有发电设备: {has_gen}")
    if not has_gen:
        print("  !! FAIL 开局没有任何发电设备")
        ok = False

    has_inserter = C.B_INSERTER in unlocked
    print(f"  有分拣器: {has_inserter}")
    if not has_inserter:
        print("  !! FAIL 分拣器未初始解锁，物资链断")
        ok = False

    # --- 2. 开局供电 vs 最小产线耗电 ---
    g = WorldGrid(64, 64)
    cx, cy = g.w // 2, g.h // 2
    g.place(cx, cy, C.B_CORE)
    # 最小可运转产线：1 采矿机 + 1 熔炉 + 1 科研站 + 2 分拣器
    g.place(cx + 3, cy, C.B_MINER, 0)
    g.place(cx + 5, cy, C.B_FURNACE, 0)
    g.place(cx + 7, cy, C.B_LAB, 0)
    g.place(cx + 4, cy, C.B_INSERTER, 0)
    g.place(cx + 6, cy, C.B_INSERTER, 0)

    p = PowerGrid(g)
    p.update(0.016)
    print(f"  开局供电 {p.last_supply:.1f} / 最小产线耗电 {p.last_demand:.1f} "
          f"= {p.last_ratio*100:.0f}%")
    if p.last_ratio < 1.0:
        print("  !! FAIL 开局供电不足，采矿产不出东西")
        ok = False

    # --- 3. 夜晚（太阳能归零）也够 ---
    p2 = PowerGrid(g)
    p2.time = p2.day_length * 0.75  # 正午夜
    p2.update(0.016)
    print(f"  夜间供电 {p2.last_supply:.1f} = {p2.last_ratio*100:.0f}%")
    if p2.last_ratio < 1.0:
        print("  !! FAIL 夜间停摆（核心供电不够）")
        ok = False

    # --- 4. 第一个科技消耗下限 vs 可达成 ---
    print("  可研究科技:", [t for t in C.TECH_TREE
                        if tech.can_research(t)[0]])
    min_cost = min(cost for _, cost, _, _ in C.TECH_TREE.values())
    print(f"  最便宜科技 {min_cost} 个电磁矩阵 = "
          f"{int(min_cost * C.LAB_CONSUME_INTERVAL)} 秒（单科研站）")

    # --- 5. 开局手搓链闭环：矿石在手就能一路搓到电磁矩阵原料 ---
    bag = {C.I_IRON_ORE: 400, C.I_COPPER_ORE: 200, C.I_STONE: 100}

    def craft(rid, times=1):
        ins, outs = C.RECIPES[rid][0], C.RECIPES[rid][1]
        for _ in range(times):
            if any(bag.get(i, 0) < n for i, n in ins.items()):
                return False
            for i, n in ins.items():
                left = bag.get(i, 0) - n
                if left > 0:
                    bag[i] = left
                else:
                    bag.pop(i, None)
            for i, n in outs.items():
                bag[i] = bag.get(i, 0) + n
        return True

    # 顺序必须按依赖链：先基础材料，再分拣器（要电路板）、熔炉（要磁铁+石材）
    # M6.16：assembler/lab 改吃铜线（电路板被 circuit1 锁，开局只能手搓/不依赖）
    chain = [
        ("iron_plate", 200), ("copper_plate", 40), ("stone_brick", 20),
        ("gear", 40), ("circuit", 20), ("copper_wire", 8), ("magnet", 20),
        ("belt", 8), ("inserter", 4),
        ("furnace", 1), ("miner", 1), ("assembler", 1),
    ]
    broke = [rid for rid, times in chain if not craft(rid, times)]
    print(f"  手搓链断点: {broke if broke else '无'}")
    if broke:
        print(f"  !! FAIL 手搓链断在 {broke}")
        ok = False

    # 统一配方后：所有配方都能手搓，所有配方都有机器建筑（除非显式只允许手搓）
    all_made = {i for r in C.RECIPES.values() for i in r[1]}
    need_items = {C.I_IRON_PLATE, C.I_GEAR, C.I_BELT_ITEM, C.I_INSERTER_ITEM,
                  C.I_FURNACE_ITEM, C.I_MINER_ITEM, C.I_ASSEMBLER_ITEM}
    missing = need_items - all_made
    print(f"  可产出关键物品: {len(need_items - missing)}/{len(need_items)}"
          + (f" 缺 {missing}" if missing else ""))
    if missing:
        print(f"  !! FAIL 缺关键物品 {missing}")
        ok = False

    no_hand = [C.ITEM_NAMES.get(i, i) for i in need_items if i not in all_made]
    print(f"  开局必需但造不出来的: {no_hand if no_hand else '无'}")
    if no_hand:
        print(f"  !! FAIL 这些开局必需建筑造不出来: {no_hand}")
        ok = False
    # 建筑物品必须都有配方，否则永远造不出来
    orphan = [C.ITEM_NAMES.get(i, i) for i in C.BUILD_ITEM.values()
              if i not in all_made]
    print(f"  没有配方的建筑: {orphan if orphan else '无'}")
    if orphan:
        print(f"  !! FAIL 这些建筑永不可造: {orphan}")
        ok = False

    # --- 6. 科技闭包可达（防完美死锁） ---
    # 统一配方（M6.6）后手搓永远可行，科技锁只锁"机器自动化"路径，
    # 所以任何原料齐的物品都可达。这里仍做闭包迭代，防止配方链本身断开。
    have = set(C.STARTING_ITEMS) | set(C.ORE_TO_ITEM.values())
    reach_techs: set[str] = set()
    reach_buildings = {C.B_CORE}
    for _ in range(50):
        grew = False
        for rid, (ins, outs, _, allows) in C.RECIPES.items():
            if all(i in have for i in ins):
                if set(outs) - have:
                    have |= set(outs)
                    grew = True
        for btype, item in C.BUILD_ITEM.items():
            if btype in reach_buildings or item not in have:
                continue
            tid = C.TECH_UNLOCK_BUILDING.get(btype)
            if tid is not None and tid not in reach_techs:
                continue
            reach_buildings.add(btype)
            grew = True
        if C.B_LAB in reach_buildings:
            for tech_id, (_, _, prereqs, _) in C.TECH_TREE.items():
                if tech_id in reach_techs:
                    continue
                if not all(p in reach_techs for p in prereqs):
                    continue
                rid = C.TECH_PACK_RECIPE.get(tech_id)
                r = C.RECIPES.get(rid) if rid else None
                if r is None or not all(i in have for i in r[1]):
                    continue
                reach_techs.add(tech_id)
                grew = True
        if not grew:
            break

    stuck = [t for t in C.TECH_TREE if t not in reach_techs]
    print(f"  科技可达性: {len(reach_techs)}/{len(C.TECH_TREE)}"
          + (f"  卡死 {stuck}" if stuck else ""))
    if stuck:
        print(f"  !! FAIL 这些科技永远研究不了（开局死锁）")
        for t in stuck:
            rid = C.TECH_PACK_RECIPE.get(t)
            r = C.RECIPES.get(rid) if rid else None
            miss = ([C.ITEM_NAMES.get(i, i) for i in r[0]] if r else ["无科研包配方"])
            print(f"       {t} 缺 {miss}")
        ok = False

    print()
    print("PASS 开局无死锁" if ok else "FAIL 存在死锁")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())