#!/usr/bin/env python3
"""建筑物品化自检：放置扣物品、缺料不能放、拆除返还、开局库存够铺最小产线。

不需要 pygame（直接调 Game 的纯逻辑方法，用假的 Game 也行），
但 _pay_building 在 Game 上，所以这里复制最小实现来验证 config 数据，
另外验证 STARTING_ITEMS 是否够。

跑法：python tools/_buildcostcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C


def main():
    fails = []

    # 1. 每个能放的建筑都必须有对应物品
    missing = [b for b in C.BUILDING_NAMES
               if b != C.B_CORE and b not in C.BUILD_ITEM]
    print(f"[1] 无对应物品的建筑: {missing}")
    if missing:
        fails.append("有建筑没有 BUILD_ITEM 映射")

    # 2. 每个建筑物品都必须能被某个配方造出来（手搓或机器）
    made = set()
    for rid, (ins, outs, dur, allows) in C.RECIPES.items():
        made |= set(outs)
    no_source = [i for i in C.BUILD_ITEM.values() if i not in made]
    print(f"[2] 没有任何配方能造的建筑物: "
          f"{[C.ITEM_NAMES.get(i, i) for i in no_source]}")
    if no_source:
        fails.append("有建筑物造不出来（死锁）")

    # 3. 开局库存必须够：2 采矿机 + 2 熔炉 + 一条 10 格带 + 4 分拣器
    need = {
        C.I_MINER_ITEM: 2,
        C.I_FURNACE_ITEM: 2,
        C.I_BELT_ITEM: 10,
        C.I_INSERTER_ITEM: 4,
    }
    gap = {C.ITEM_NAMES.get(i, i): (C.STARTING_ITEMS.get(i, 0), n)
           for i, n in need.items() if C.STARTING_ITEMS.get(i, 0) < n}
    print(f"[3] 开局库存缺口: {gap}")
    if gap:
        fails.append("开局库存不够铺最小产线")

    # 4. 扣物品 / 返还 逻辑（照抄 Game._pay_building 的语义）
    inv = dict(C.STARTING_ITEMS)

    def count(i):
        return inv.get(i, 0)

    def pay(btype, n=1):
        item = C.BUILD_ITEM.get(btype)
        if item is None:
            return True
        if count(item) < n:
            return False
        left = count(item) - n
        if left > 0:
            inv[item] = left
        else:
            inv.pop(item, None)
        return True

    def refund(btype, n=1):
        item = C.BUILD_ITEM.get(btype)
        if item is not None:
            inv[item] = count(item) + n

    before = count(C.I_BELT_ITEM)
    assert pay(C.B_BELT), "开局应该能放传送带"
    mid = count(C.I_BELT_ITEM)
    refund(C.B_BELT)
    after = count(C.I_BELT_ITEM)
    print(f"[4] 传送带 {before} -> 放 -1 -> {mid} -> 拆 +1 -> {after}")
    if not (mid == before - 1 and after == before):
        fails.append("放置扣料/拆除返还数量不对")

    # 5. 库存清空后不能再放
    inv[C.I_FURNACE_ITEM] = 0
    ok = pay(C.B_FURNACE)
    print(f"[5] 熔炉库存 0 时放置: {ok} (期望 False)")
    if ok:
        fails.append("库存为 0 仍能放置")

    # 6. 统一配方（M6.6）：一个物品只能有一个配方，不存在 hand_*/mk_* 双套。
    #    校验：没有残留的 hand_/mk_ 前缀 id，每个产出物品只由一个配方产出。
    dup_prefix = [rid for rid in C.RECIPES if rid.startswith(("hand_", "mk_"))]
    print(f"[6] 残留的旧式配方 id: {dup_prefix if dup_prefix else '无'}")
    if dup_prefix:
        fails.append(f"还有旧式 hand_/mk_ 配方 id: {dup_prefix}")

    prod_count: dict[int, list[str]] = {}
    for rid, r in C.RECIPES.items():
        for item in r[1]:
            prod_count.setdefault(item, []).append(rid)
    multi = {C.ITEM_NAMES.get(i, i): rids
             for i, rids in prod_count.items() if len(rids) > 1}
    print(f"[6b] 有多个配方的物品: {multi if multi else '无'}")
    if multi:
        fails.append(f"同一物品有多个配方，手搓/机器会分裂: {multi}")

    # 7. 所有配方都必须有能做的机器建筑（= 所有东西都能自动化）
    no_machine = [rid for rid, r in C.RECIPES.items() if not r[3]]
    print(f"[7] 无法自动化的配方: {no_machine if no_machine else '无'}")
    if no_machine:
        fails.append(f"这些配方无法自动化: {no_machine}")

    # 8. 手搓必须比机器慢（成本相同，靠时间拉开差距）
    if C.HAND_CRAFT_TIME_MULT <= 1.0:
        print(f"[8] 手搓耗时倍率 {C.HAND_CRAFT_TIME_MULT} ≤ 1，手搓不会比机器慢")
        fails.append("HAND_CRAFT_TIME_MULT 必须 > 1")
    else:
        print(f"[8] 手搓耗时倍率 {C.HAND_CRAFT_TIME_MULT}× ✓")

    print()
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        return 1
    print("PASS 建筑物品化全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())