#!/usr/bin/env python3
"""开局死锁可达性检查：从开局背包出发做闭包迭代。

和 _startcheck 的区别：
  _startcheck 只看"手搓链能不能通"、"有没有发电"，是静态检查。
  本脚本做真正的可达性闭包：
     背包物品 → 能造什么（手搓/机器，考虑科技锁）
             → 能建什么（建筑物品 + 供电）
             → 能研究什么（科研包 + 前置）
     → 科技解锁更多配方 → 再回到第一步，直到不再变化。
  任何"最终仍不可达"的关键物品/科技就是死锁。

跑法：python tools/_deadlockcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C


def item_name(i) -> str:
    return C.ITEM_NAMES.get(i, f"?{i}")


def reachable() -> dict:
    """闭包迭代，返回最终可达状态。"""
    # 开局背包物品 + 玩家能徒手挖到的所有矿石。
    # 右键挖矿不需要任何建筑（game._remove_or_mine 直接调 grid.mine），
    # 所以三种矿从第 0 秒起就是可达的，不能算进死锁。
    have = set(C.STARTING_ITEMS) | set(C.ORE_TO_ITEM.values())
    techs = set()                                # 已研究科技
    buildings = {C.B_CORE}                       # 能放的建筑（核心开局就有）
    made = set()                                 # 能造出来的物品
    machine_ok = set()                           # 能自动化的配方

    changed = True
    rounds = 0
    while changed:
        changed = False
        rounds += 1

        # --- 1. 能造什么 ---
        # 统一配方（M6.6）：手搓和机器共用同一份配方。
        # 手搓永远可行，只受原料限制；科技锁（RECIPE_TECH）只锁"机器自动化"
        # 这条路径——所以任何原料齐的物品都必然可达，不会再有完美死锁。
        # 机器路径另外需要：科技已解锁 + 那台机器能建出来。
        for rid, (ins, outs, _, allows) in C.RECIPES.items():
            if not all(i in have for i in ins):
                continue
            req = C.RECIPE_TECH.get(rid)
            if bool(allows) and (req is None or req in techs):
                machine_ok.add(rid)
            new = set(outs) - have
            if new:
                have |= new
                made |= set(outs)
                changed = True

        # --- 2. 能建什么 ---
        for btype, item in C.BUILD_ITEM.items():
            if btype in buildings:
                continue
            if item not in have:
                continue
            # 建筑本身也可能受科技锁（TECH_UNLOCK_BUILDING）
            tid = C.TECH_UNLOCK_BUILDING.get(btype)
            if tid is not None and tid not in techs:
                continue
            buildings.add(btype)
            changed = True

        # --- 3. 能研究什么 ---
        # 科研站能吃下的科研包：必须能造 + 能建科研站
        can_lab = C.B_LAB in buildings
        for tech_id, (name, cost, prereqs, desc) in C.TECH_TREE.items():
            if tech_id in techs:
                continue
            if not can_lab:
                continue
            if not all(p in techs for p in prereqs):
                continue
            rid = C.TECH_PACK_RECIPE.get(tech_id)
            r = C.RECIPES.get(rid) if rid else None
            if r is None:
                continue
            if not all(i in have for i in r[1]):
                continue           # 科研包造不出来，研究不了
            techs.add(tech_id)
            changed = True

    return {
        "have": have, "made": made, "buildings": buildings,
        "techs": techs, "rounds": rounds, "machine_ok": machine_ok,
    }


def main():
    ok = True
    st = reachable()
    have, built, techs = st["have"], st["buildings"], st["techs"]
    print(f"闭包迭代 {st['rounds']} 轮")
    print(f"可达物品 {len(have)} 种: "
          f"{[item_name(i) for i in sorted(have)][:20]}...")
    print(f"可建建筑 {len(built)} 种: "
          f"{[C.BUILDING_NAMES.get(b, b) for b in sorted(built)]}")
    print(f"可研究科技 {len(techs)}/{len(C.TECH_TREE)}: {sorted(techs)}")

    # --- 检查 1：所有科技是否都可研究 ---
    unreachable_tech = [t for t in C.TECH_TREE if t not in techs]
    print(f"\n[1] 无法研究的科技: {unreachable_tech if unreachable_tech else '无'}")
    if unreachable_tech:
        print(f"  !! FAIL 这些科技永远研究不了（开局死锁）")
        for t in unreachable_tech:
            name, cost, pre, _ = C.TECH_TREE[t]
            rid = C.TECH_PACK_RECIPE.get(t)
            r = C.RECIPES.get(rid) if rid else None
            miss = [item_name(i) for i in r[0]] if r else ["(无科研包配方)"]
            print(f"       {t}「{name}」需要科研包 {rid}，缺 {miss}")
        ok = False

    # --- 检查 2：所有建筑是否都能造出来 ---
    unbuildable = [b for b in C.BUILD_ITEM if b not in built]
    print(f"[2] 造不出来的建筑: "
          f"{[C.BUILDING_NAMES.get(b, b) for b in unbuildable] if unbuildable else '无'}")
    if unbuildable:
        print("  !! FAIL 这些建筑永不可造")
        ok = False

    # --- 检查 3：科研包本身能不能造 ---
    pack_items = {i for rid in C.TECH_PACK_RECIPE.values()
                  for i in C.RECIPES[rid][1]}
    bad_pack = [item_name(i) for i in pack_items if i not in have]
    print(f"[3] 造不出来的科研包: {bad_pack if bad_pack else '无'}")
    if bad_pack:
        print("  !! FAIL 科研包造不出来，所有科技都要卡死")
        ok = False

    # --- 4. 配方科技锁：现在只锁"机器自动化"，不阻断手搓可达性 ---
    print("[4] 配方科技锁（只锁机器路径，手搓照样能做）:")
    for rid, tid in C.RECIPE_TECH.items():
        outs = [item_name(i) for i in C.RECIPES[rid][1]]
        state = "可自动化" if rid in st["machine_ok"] else "仅手搓（科技未解锁）"
        print(f"       {rid} 产 {outs} 需科技 {tid} → {state}")

    # --- 5. 除科技锁外，所有配方都必须能自动化 ---
    only_hand = [rid for rid in C.RECIPES
                 if rid not in st["machine_ok"]
                 and C.RECIPE_TECH.get(rid) is None]
    print(f"[5] 没有科技锁却无法自动化的配方: "
          f"{only_hand if only_hand else '无'}")
    if only_hand:
        print("  !! FAIL 这些配方又没科技锁又没法自动化，设计漏了")
        ok = False

    # --- 6. 科技锁配方不能构成自动化死锁 ---
    # 规则：被 RECIPE_TECH 锁住的配方，其产物不得出现在「研究该科技所需的
    # 科研包配方」的原料里——否则研究这个科技必须靠它自己锁住的东西，
    # 自动化产线就断了（只能靠手搓硬绕）。
    # M6.16 曾发生过：circuit 被 circuit1 锁，circuit1 吃 science_blue，
    # science_blue 又吃电路板 → 制造台造不了蓝包 → 研究不了电路板科技。
    auto_bad = []
    for rid, tid in C.RECIPE_TECH.items():
        pack_rid = C.TECH_PACK_RECIPE.get(tid)
        if not pack_rid or pack_rid not in C.RECIPES:
            continue
        outs = set(C.RECIPES[rid][1])
        pack_ins = set(C.RECIPES[pack_rid][0])
        hit = outs & pack_ins
        if hit:
            auto_bad.append((rid, tid, pack_rid,
                             [item_name(i) for i in hit]))
    print(f"[6] 科技锁→科研包→被锁配方 自动化环: "
          f"{auto_bad if auto_bad else '无'}")
    if auto_bad:
        print("  !! FAIL 配方被科技锁住，但研究该科技又需要它 → 自动化断链")
        ok = False

    print()
    print("PASS 开局无死锁" if ok else "FAIL 存在开局死锁")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())