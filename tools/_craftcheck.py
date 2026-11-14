#!/usr/bin/env python3
"""手搓链自检：从空背包 + 矿石，仅靠手搓能不能搭出最小自动化产线。

M6.6 起手搓和机器共用同一份 RECIPES，区别只有耗时（手搓慢 HAND_CRAFT_TIME_MULT 倍）。
所以这里直接用手搓语义跑一遍完整链，验证成本上和机器完全等价、不会死锁。

验证顺序：矿石 → 铁板 → 齿轮 → 传送带/分拣器/熔炉/采矿机/制造台，
然后（假设有机器）自动化出铁板/铜板/电路板/电磁矩阵，闭环不死锁。

跑法：python tools/_craftcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C


class Inv:
    """最小背包：只做扣料/加料。"""

    def __init__(self, init=None):
        self.d = dict(init or {})

    def count(self, i):
        return self.d.get(i, 0)

    def add(self, i, n=1):
        self.d[i] = self.count(i) + n

    def add_dict(self, m):
        for i, n in m.items():
            self.add(i, n)

    def take(self, m):
        if any(self.count(i) < n for i, n in m.items()):
            return False
        for i, n in m.items():
            left = self.count(i) - n
            if left > 0:
                self.d[i] = left
            else:
                self.d.pop(i, None)
        return True

    def craft(self, rid, times=1):
        """照 Game / CraftPanel 的统一配方语义手搓（成本与机器一致）。"""
        r = C.RECIPES.get(rid)
        if r is None:
            return 0
        ins, outs = r[0], r[1]
        done = 0
        for _ in range(times):
            if not self.take(ins):
                break
            self.add_dict(outs)
            done += 1
        return done


def main():
    fails = []
    inv = Inv()

    # 0. 背包是空的（验证手搓真的从零起步）
    print(f"[0] 起始背包 {inv.d}")

    # 1. 没有任何矿石时手搓铁板必须失败
    got = inv.craft("iron_plate")
    print(f"[1] 空矿石手搓铁板: {got} 次 (期望 0)")
    if got != 0:
        fails.append("没有矿石也能手搓铁板")

    # 2. 采矿 10 铁矿 → 手搓 10 铁板（统一配方：矿1→板1）
    inv.add(C.I_IRON_ORE, 10)
    n = inv.craft("iron_plate", 10)
    print(f"[2] 10 铁矿手搓 {n} 铁板, 背包={inv.d}")
    if n != 10 or inv.count(C.I_IRON_PLATE) != 10:
        fails.append("铁矿 → 铁板 手搓数量不对")

    # 3. 手搓齿轮
    n = inv.craft("gear", 3)
    print(f"[3] 手搓 {n} 齿轮, 铁板剩 {inv.count(C.I_IRON_PLATE)}")
    if n != 3:
        fails.append("铁板 → 齿轮 手搓失败")

    # 4. 手搓传送带 + 分拣器
    #    belt: 铁板2+齿轮1 → 带子3（一份料出 3 个，用户要求）
    #    inserter: 铁板1+电路板1 → 分拣器1
    inv.add(C.I_IRON_ORE, 40)
    inv.craft("iron_plate", 20)
    inv.craft("gear", 6)
    belts = inv.craft("belt", 2)   # 2 次 = 6 个带子
    print(f"[4a] 手搓传送带 2 次 → {inv.count(C.I_BELT_ITEM)} 个带子（期望 6）")
    if belts != 2 or inv.count(C.I_BELT_ITEM) != 6:
        fails.append("传送带一份原料没出 3 个")
    # 分拣器要电路板：走手搓电路板（铁板2+铜板1→电路板2）
    inv.add(C.I_COPPER_ORE, 8)
    inv.craft("copper_plate", 4)
    inv.craft("circuit", 4)     # 4 次 → 8 个电路板
    ins = inv.craft("inserter", 4)
    print(f"[4b] 手搓分拣器 {ins} 个  背包={inv.d}")
    if ins != 4:
        fails.append("手搓分拣器失败")

    # 5. 手搓熔炉
    inv.add(C.I_STONE, 10)
    inv.craft("stone_brick", 5)
    inv.craft("iron_plate", 10)
    inv.craft("magnet", 4)
    fur = inv.craft("furnace")
    print(f"[5] 手搓熔炉 {fur}")
    if fur != 1:
        fails.append("手搓熔炉失败")

    # 6. 手搓采矿机 + 制造台
    #    miner: 铁板4 + 电路板2 + 磁铁2 + 齿轮2
    #    assembler: 铁板4 + 齿轮8 + 电路板4
    inv.add(C.I_IRON_ORE, 400)
    inv.add(C.I_COPPER_ORE, 60)
    inv.add(C.I_STONE, 40)
    inv.craft("iron_plate", 120)
    inv.craft("copper_plate", 30)
    inv.craft("stone_brick", 20)
    inv.craft("gear", 30)
    inv.craft("circuit", 20)
    inv.craft("copper_wire", 10)   # assembler 改吃铜线（M6.16）
    inv.craft("magnet", 10)
    miner = inv.craft("miner")
    asm = inv.craft("assembler")
    print(f"[6] 手搓采矿机 {miner} / 制造台 {asm}")
    if miner != 1 or asm != 1:
        fails.append("手搓采矿机/制造台失败")

    # 7. 关键自动化配方必须存在且都挂在建筑上（统一配方后所有配方都有机器）
    for rid in ("circuit", "science_blue", "copper_wire"):
        r = C.RECIPES.get(rid)
        if r is None:
            fails.append(f"{rid} 配方缺失")
        elif not r[3]:
            fails.append(f"{rid} 没有机器建筑，无法自动化")
        else:
            ins_txt = " + ".join(C.ITEM_NAMES.get(i, "?") for i in r[0])
            out_txt = " + ".join(C.ITEM_NAMES.get(i, "?") for i in r[1])
            print(f"[7] {rid}: {ins_txt} → {out_txt} ({r[2]}s)")

    # 8. 电磁矩阵的原料必须有来源
    sb = C.RECIPES["science_blue"][0]
    for item in sb:
        sources = [rid for rid, r in C.RECIPES.items() if item in r[1]]
        print(f"[8] {C.ITEM_NAMES.get(item, item)} 来源配方: {sources}")
        if not sources:
            fails.append(f"电磁矩阵原料 {C.ITEM_NAMES.get(item, item)} 无来源")

    # 9. 所有东西都能自动化：每个配方都必须有能做的机器建筑
    no_machine = [rid for rid, r in C.RECIPES.items() if not r[3]]
    print(f"[9] 只能手搓、不能自动化的配方: {no_machine if no_machine else '无'}")
    if no_machine:
        fails.append(f"这些配方无法自动化: {no_machine}")

    print()
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        return 1
    print("PASS 手搓链闭环无死锁")
    return 0


if __name__ == "__main__":
    sys.exit(main())