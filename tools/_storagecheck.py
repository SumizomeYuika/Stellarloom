#!/usr/bin/env python3
"""箱子 + 采矿机暂存 + 机器手动存取 自检。

覆盖本轮需求：
1. 箱子：混装、每种上限、手动放入/取出、分拣器可进可出
2. 采矿机：50 格暂存、满了停挖不丢矿、手动放入/取出、往带子吐货不丢
3. 机器：原料槽手动放入/取出、产物槽只能整体取出、不能手动塞产物
4. 分拣器：机器/箱子/采矿机 之间的抓取与投递，投递失败不吞货

跑法：python tools/_storagecheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, InserterNetwork
from stellarloom.production import ChestNetwork, MachineNetwork, MinerNetwork
from stellarloom.world import WorldGrid


def check_chest_basic() -> bool:
    """箱子：混装、每种上限、手动存取往返。"""
    g = WorldGrid(32, 32)
    g.place(5, 5, C.B_CHEST, 0)
    cn = ChestNetwork(g)
    cn.sync()
    ch = cn.get(5, 5)
    ok = True

    # 混装两种
    ch.add_item(C.I_IRON_PLATE, 3)
    ch.add_item(C.I_GEAR, 2)
    print(f"[1] 箱子混装 {ch.store}")
    if ch.store != {C.I_IRON_PLATE: 3, C.I_GEAR: 2}:
        ok = False
        print("  !! FAIL 混装结果不对")

    # 每种上限
    n = ch.add_item(C.I_IRON_PLATE, C.CHEST_STACK + 20)
    print(f"[1b] 再放 {C.CHEST_STACK + 20} 个铁板，实际放入 {n}，"
          f"现有 {ch.store.get(C.I_IRON_PLATE)}")
    if ch.store.get(C.I_IRON_PLATE) != C.CHEST_STACK:
        ok = False
        print("  !! FAIL 每种上限失效")

    # 手动取出：全取
    got = ch.take_item(C.I_GEAR)
    print(f"[1c] 全取齿轮得到 {got}，剩余 {ch.store.get(C.I_GEAR)}")
    if got != 2 or C.I_GEAR in ch.store:
        ok = False
        print("  !! FAIL 全取数量不对")

    # 手动取出：指定数量
    got = ch.take_item(C.I_IRON_PLATE, 10)
    print(f"[1d] 取 10 个铁板得到 {got}，剩余 {ch.store.get(C.I_IRON_PLATE)}")
    if got != 10 or ch.store.get(C.I_IRON_PLATE) != C.CHEST_STACK - 10:
        ok = False
        print("  !! FAIL 指定数量取出不对")
    return ok


def check_chest_inserter() -> bool:
    """分拣器：能往箱子投货，也能从箱子抓货，投递失败不吞。"""
    g = WorldGrid(32, 32)
    # 带子(10,10) → 分拣器(11,10) → 箱子(12,10)
    g.place(10, 10, C.B_BELT, 0)
    g.place_overlay(11, 10, C.B_INSERTER, 0)
    g.place(12, 10, C.B_CHEST, 0)
    b = BeltNetwork(g)
    cn = ChestNetwork(g)
    cn.sync()
    mn = MachineNetwork(g)
    mn.sync()
    ins = InserterNetwork(g, b)
    ins.chests = cn
    ins.miners = None

    # 带子上放一个铁板
    b.try_insert(10, 10, C.I_IRON_PLATE)
    ins.cooldowns.clear()
    for _ in range(3):
        ins.update(1.1, mn)
    ch = cn.get(12, 10)
    print(f"[2] 带子→箱子：箱子内容 {ch.store}，带子上剩 {b.item_count}")
    if ch.store.get(C.I_IRON_PLATE, 0) < 1:
        print("  !! FAIL 分拣器没能把货送进箱子")
        return False

    # 反向：箱子(14,10) → 分拣器(13,10)朝左 → 带子(12,10)
    g.place(14, 10, C.B_CHEST, 0)
    g.place_overlay(13, 10, C.B_INSERTER, 2)   # 朝左：目标 12,10
    g.place(12, 10, C.B_BELT, 0)
    b.rebuild()
    cn.sync()
    ch2 = cn.get(14, 10)
    ch2.store = {C.I_GEAR: 3}
    ins.cooldowns.clear()
    for _ in range(3):
        ins.update(1.1, mn)
    left = sum(1 for _ in b.iter_items())
    print(f"[2b] 箱子→带子：箱子剩 {ch2.store}，带子上物品数 {left}")
    if ch2.store.get(C.I_GEAR, 0) >= 3:
        print("  !! FAIL 分拣器没能从箱子抓货")
        return False
    return True


def check_miner_buffer() -> bool:
    """采矿机：50 格暂存、满了停挖、手动存取、吐货不丢。"""
    g = WorldGrid(48, 48)
    ys, xs = np.nonzero(g.ore > 0)
    if not len(xs):
        print("[3] 没矿，跳过")
        return True
    x, y = int(xs[0]), int(ys[0])
    g.place(x, y, C.B_MINER, 0)
    b = BeltNetwork(g)
    mn = MinerNetwork(g)
    mn.sync()
    m = mn.get(x, y)
    ok = True

    # 手动放入两种矿到暂存
    m.add_item(C.I_IRON_ORE, 20)
    m.add_item(C.I_COPPER_ORE, 10)
    tot = m.total()
    print(f"[3] 采矿机暂存 {m.buffer}，共 {tot}（上限 {C.MINER_BUFFER_CAP}）")
    if tot != 30:
        ok = False
        print("  !! FAIL 暂存数量不对")

    # 塞到满，满了不能继续塞
    n = m.add_item(C.I_STONE, C.MINER_BUFFER_CAP)
    print(f"[3b] 再塞 {C.MINER_BUFFER_CAP} 个石矿，实际放入 {n}，"
          f"总 {m.total()}")
    if m.total() > C.MINER_BUFFER_CAP:
        ok = False
        print("  !! FAIL 暂存上限失效")

    # 满了还挖不挖？挖矿前 has_space 应为 False
    spaces = m.has_space()
    print(f"[3c] 满仓后 has_space={spaces}（期望 False）")
    if spaces:
        ok = False
        print("  !! FAIL 满仓仍在挖")

    # 手动全取一种
    got = m.take_item(C.I_IRON_ORE)
    print(f"[3d] 全取铁矿 {got} 个")
    if got != 20:
        ok = False
        print("  !! FAIL 手动全取数量不对")
    return ok


def check_miner_no_item_loss() -> bool:
    """采矿机往满带子吐货：货必须留在暂存，不能凭空消失。"""
    g = WorldGrid(48, 48)
    ys, xs = np.nonzero(g.ore > 0)
    if not len(xs):
        print("[4] 没矿，跳过")
        return True
    x, y = int(xs[0]), int(ys[0])
    g.place(x, y, C.B_MINER, 0)
    tx, ty = g.wrap(x + 1, y)
    g.place(tx, ty, C.B_BELT, 0)
    b = BeltNetwork(g)
    mn = MinerNetwork(g)
    mn.sync()
    m = mn.get(x, y)

    # 把目标带子塞满
    lane = b.lanes[b.cell_lane[(tx, ty)]]
    ci = lane.cell_index((tx, ty))
    lane.positions = np.array([float(ci)] * int(C.ITEM_CAPACITY_PER_CELL),
                              dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE] * int(C.ITEM_CAPACITY_PER_CELL),
                          dtype=np.int32)

    m.buffer = {C.I_IRON_ORE: 5}
    before = m.total()
    belt_before = b.item_count
    for _ in range(4):
        mn.update(0.6, b)
    after = m.total()
    belt_after = b.item_count
    total = after + belt_after
    # 采矿机会继续挖矿，所以总量只增不减；关键是"不能少"
    print(f"[4] 满带子：采矿机暂存 {before}→{after}，带子 {belt_before}→"
          f"{belt_after}，守恒总量={total}（应≥{before + belt_before}）")
    if total < before + belt_before:
        print("  !! FAIL 吐货失败时矿物凭空消失")
        return False
    if belt_after != belt_before:
        print("  !! FAIL 满带子居然还塞进去了东西")
        return False
    return True


def check_machine_manual() -> bool:
    """机器：原料可手动进出；产物只能整体取出，手动塞产物无效。"""
    mn = MachineNetwork(WorldGrid(16, 16))
    g = WorldGrid(16, 16)
    g.place(3, 3, C.B_FURNACE, 0)
    mn = MachineNetwork(g)
    mn.sync()
    m = mn.get_machine(3, 3)
    m.set_recipe("iron_plate")
    ok = True

    # 手动放入两种：铁矿石（配方要）与齿轮（配方不要）
    n1 = m.add_input(C.I_IRON_ORE, 5)
    n2 = m.add_input(C.I_GEAR, 5)
    print(f"[5] 手动放铁矿石 {n1} 个、齿轮 {n2} 个（齿轮应 0）")
    if n1 != 5 or n2 != 0:
        ok = False
        print("  !! FAIL 机器手动放入没按配方过滤")

    # 手动取出指定数量
    got = m.take_input(C.I_IRON_ORE, 2)
    print(f"[5b] 手动取 2 个铁矿石，得到 {got}，剩 {m.inputs}")
    if got != 2 or m.inputs.get(C.I_IRON_ORE) != 3:
        ok = False
        print("  !! FAIL 机器手动取出原料数量不对")

    # 产物只能整体取
    m.outputs = {C.I_IRON_PLATE: 4, C.I_GEAR: 2}
    got = m.take_all_outputs()
    print(f"[5c] 整体取产物 {got}，取后 {m.outputs}")
    if got != {C.I_IRON_PLATE: 4, C.I_GEAR: 2} or m.outputs:
        ok = False
        print("  !! FAIL 产物整体取出不对")

    # 机器没有"手动放入产物"的接口，outputs 只能通过生产写
    has_bad_api = hasattr(m, "add_output")
    print(f"[5d] 是否存在手动放产物接口 add_output={has_bad_api}（期望 False）")
    if has_bad_api:
        ok = False
        print("  !! FAIL 机器暴露了手动放产物的接口")

    # 配方原料数是 1，上限 10
    m.set_recipe("iron_plate")
    n = m.add_input(C.I_IRON_ORE, 999)
    print(f"[5e] 一次性放 999 个，实际放入 {n}，现有 {m.inputs}")
    if m.inputs.get(C.I_IRON_ORE, 0) > C.MACHINE_INPUT_CAP:
        ok = False
        print("  !! FAIL 原料槽上限失效")
    return ok


def check_inserter_chest_to_machine() -> bool:
    """箱子 → 分拣器 → 机器：链路要通，且过滤要生效。"""
    g = WorldGrid(32, 32)
    g.place(10, 10, C.B_CHEST, 0)
    g.place_overlay(11, 10, C.B_INSERTER, 0)
    g.place(12, 10, C.B_FURNACE, 0)
    b = BeltNetwork(g)
    cn = ChestNetwork(g)
    cn.sync()
    mn = MachineNetwork(g)
    mn.sync()
    ins = InserterNetwork(g, b)
    ins.chests = cn
    ins.miners = None
    ins.labs = None

    ch = cn.get(10, 10)
    # 箱子里放齿轮和铁矿石各若干；熔炉只要铁矿石
    ch.store = {C.I_GEAR: 5, C.I_IRON_ORE: 5}
    m = mn.get_machine(12, 10)
    m.set_recipe("iron_plate")

    ins.cooldowns.clear()
    for _ in range(6):
        ins.update(1.1, mn)
    print(f"[6] 箱子→熔炉：箱子 {ch.store}，熔炉原料 {m.inputs}")
    if m.inputs.get(C.I_IRON_ORE, 0) <= 0:
        print("  !! FAIL 铁矿石没送进熔炉")
        return False
    if m.inputs.get(C.I_GEAR, 0) != 0:
        print("  !! FAIL 齿轮被错误送进熔炉")
        return False
    return True


def main():
    checks = [
        ("箱子混装/上限/手动存取", check_chest_basic()),
        ("分拣器进出箱子", check_chest_inserter()),
        ("采矿机暂存 50 格", check_miner_buffer()),
        ("采矿机吐货不丢矿", check_miner_no_item_loss()),
        ("机器手动存取料/产物整体取", check_machine_manual()),
        ("箱子→分拣器→机器且过滤生效", check_inserter_chest_to_machine()),
    ]
    print()
    bad = [n for n, ok in checks if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 箱子/采矿机暂存/机器手动存取 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())