#!/usr/bin/env python3
"""开局可行性自检：确认没有任何死锁（M13.2 无电开局版）。

M13.2 设计变更：出生点不再预置核心，开局一点电都没有。
开局路径改为：
    长按采矿（免费） -> 手搓铁板/铜板/磁铁/铜线 -> 手搓电磁矩阵
    -> 科技面板「手动研究」推第一个科技 -> 铺电
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.power import PowerGrid
from stellarloom.tech import TechTree
from stellarloom.world import WorldGrid
from stellarloom.world.planets import PLANETS


def main():
    ok = True
    tech = TechTree()

    # --- 1. 开局无电（设计如此）---
    print("[1] 开局供电：")
    no_core = [p.pid for p in PLANETS if p.has_core]
    print("  预置核心的行星: "
          + (", ".join(no_core) if no_core else "无（开局无电，符合设计）"))
    if no_core:
        print("  !! FAIL 仍有行星预置核心，开局白送电")
        ok = False

    g = WorldGrid(64, 64)
    p = PowerGrid(g)
    p.update(0.016)
    print(f"  纯空网格供电 {p.last_supply:.1f} / 耗电 {p.last_demand:.1f}")
    if p.last_supply > 0.0:
        print("  !! FAIL 空网格居然有电")
        ok = False

    # --- 2. 手搓链：空背包 + 矿石 -> 电磁矩阵 ---
    print("[2] 手搓链（开局唯一科研来源）：")
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

    chain = [
        ("iron_plate", 200), ("copper_plate", 60), ("stone_brick", 20),
        ("gear", 40), ("magnet", 40), ("copper_wire", 40), ("circuit", 8),
        ("science_blue", 40),
    ]
    broke = [rid for rid, times in chain if not craft(rid, times)]
    print(f"  手搓链断点: {broke if broke else '无'}")
    if broke:
        print(f"  !! FAIL 手搓链断在 {broke}")
        ok = False
    packs = bag.get(C.I_SCIENCE_BLUE, 0)
    print(f"  搓出电磁矩阵: {packs} 个")
    if packs <= 0:
        print("  !! FAIL 一个电磁矩阵都搓不出来，科技永远推不动")
        ok = False

    # --- 3. 手动研究能推进第一个科技 ---
    print("[3] 手动研究：")
    inv = dict(bag)
    first = "power1"
    cost = C.TECH_TREE[first][1]
    print(f"  {C.TECH_TREE[first][0]} 需要 {cost} 个包，背包有 {packs} 个")
    if packs < cost:
        print(f"  !! FAIL 包不够（{packs} < {cost}），第一个科技研究不完")
        ok = False
    for _ in range(cost):
        good, msg = tech.manual_research(first, inv)
        if not good:
            print(f"  !! FAIL 手动研究失败: {msg}")
            ok = False
            break
    done = first in tech.researched
    print(f"  {C.TECH_TREE[first][0]} 完成: {done}")
    if not done:
        ok = False
    elif not tech.is_unlocked(C.B_SOLAR):
        print("  !! FAIL 研究完 power1 还是放不下太阳能")
        ok = False

    # --- 4. 科技闭包可达 ---
    print("[4] 科技闭包：")
    have = set(C.STARTING_ITEMS) | set(C.ORE_TO_ITEM.values())
    reach_techs = set()
    reach_buildings = {C.B_CORE}
    for _ in range(50):
        grew = False
        for rid, (ins, outs, _d, _a) in C.RECIPES.items():
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
            for tech_id, (_n, _c, prereqs, _d) in C.TECH_TREE.items():
                if tech_id in reach_techs:
                    continue
                if not all(pp in reach_techs for pp in prereqs):
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
        print("  !! FAIL 这些科技永远研究不了（开局死锁）")
        for t in stuck:
            rid = C.TECH_PACK_RECIPE.get(t)
            r = C.RECIPES.get(rid) if rid else None
            miss = ([C.ITEM_NAMES.get(i, i) for i in r[0]]
                    if r else ["无科研包配方"])
            print(f"       {t} 缺 {miss}")
        ok = False

    # --- 5. 一级包必须能手搓 ---
    print("[5] 手搓黑名单：")
    print(f"  禁搓配方: {sorted(C.HANDCRAFT_BLACKLIST)}")
    if "science_blue" in C.HANDCRAFT_BLACKLIST:
        print("  !! FAIL 电磁矩阵被禁搓，开局无电又搓不了包 = 完美死锁")
        ok = False

    print()
    print("PASS 开局无死锁" if ok else "FAIL 存在死锁")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())