#!/usr/bin/env python3
"""分拣器叠加层回归测试。

之前分拣器占独立建筑格，插在传送带中间会把 lane 切断，物品全卡在上半段。
改成 overlay 后验证：
  1. 带子中间叠分拣器，lane 仍是一条完整的（不切断）
  2. 物品能一路流到末端
  3. 分拣器仍能把物品从带子搬进机器
  4. 拆带子时叠在上面的分拣器一起消失
  5. 分拣器计入建筑统计（否则不耗电）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, InserterNetwork
from stellarloom.production import MachineNetwork
from stellarloom.world import WorldGrid


def check_lane_intact() -> bool:
    """带子中间叠分拣器，lane 不能被切断。"""
    g = WorldGrid(64, 64)
    for i in range(10):
        g.place(10 + i, 20, C.B_BELT, 0)        # 向右
    for i in (3, 5, 7):
        assert g.place_overlay(10 + i, 20, C.B_INSERTER, 1)

    belts = BeltNetwork(g)
    n = len(belts.lanes)
    length = belts.lanes[0].length if n else 0
    print(f"[1] lane 数={n} 长度={length} (期望 1 / 10)")
    if n != 1 or length != 10:
        print("  !! FAIL 传送带被切断")
        return False

    # 物品能流到末端
    belts.try_insert(10, 20)
    lane = belts.lanes[0]
    for _ in range(600):
        belts.update(1 / 60)
    head = lane.positions[-1] if len(lane.positions) else -1
    print(f"[2] 10 秒后队首位置={head:.2f} (期望 ~{lane.length - 1:.2f})")
    if head < lane.length - 1.0:
        print("  !! FAIL 物品被卡住")
        return False
    return True


def check_belt_to_machine() -> bool:
    """分拣器把带子上的物品搬进熔炉。

    布局（列 20，向下走）：
        (20,10) 带子
        (20,11) 带子  ← 物品在这格
        (20,12) 分拣器，朝下 d=1 → 源=(20,11) 目标=(20,13)
        (20,13) 熔炉
    """
    g = WorldGrid(64, 64)
    g.place(20, 10, C.B_BELT, 1)
    g.place(20, 11, C.B_BELT, 1)
    g.place_overlay(20, 12, C.B_INSERTER, 1)
    g.place(20, 13, C.B_FURNACE, 0)

    belts = BeltNetwork(g)
    mach = MachineNetwork(g)
    mach.sync()
    mach.machines[(20, 13)].set_recipe("iron_plate")  # 空壳机器必须先设配方才收料
    ins = InserterNetwork(g, belts)

    lane = belts.lanes[0]
    lane.positions = np.array([1.5], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)

    before = len(lane.positions)
    ins.update(0.0, mach)
    after = len(lane.positions)
    m = mach.machines[(20, 13)]
    got = m.inputs.get(C.I_IRON_ORE, 0)
    print(f"[3] 带子物品 {before}->{after}，熔炉输入={m.inputs}")
    if after != 0 or got != 1:
        print("  !! FAIL 分拣器没完成搬运")
        return False
    return True


def check_overlay_on_belt_grab() -> bool:
    """分拣器直接叠在带子格上，仍能从背后带子抓货。

    布局（列 20）：
        (20,10) 带子（源）
        (20,11) 带子 + 分拣器叠加，朝下 d=1 → 源=(20,10) 目标=(20,12)
        (20,12) 熔炉
    """
    g = WorldGrid(64, 64)
    g.place(20, 10, C.B_BELT, 1)
    g.place(20, 11, C.B_BELT, 1)
    assert g.place_overlay(20, 11, C.B_INSERTER, 1)
    g.place(20, 12, C.B_FURNACE, 0)

    belts = BeltNetwork(g)
    mach = MachineNetwork(g)
    mach.sync()
    mach.machines[(20, 12)].set_recipe("iron_plate")  # 空壳机器必须先设配方才收料
    ins = InserterNetwork(g, belts)

    lane = belts.lanes[0]
    lane.positions = np.array([0.5], dtype=np.float32)   # (20,10) 格内
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)

    before = len(lane.positions)
    ins.update(0.0, mach)
    after = len(lane.positions)
    got = mach.machines[(20, 12)].inputs.get(C.I_IRON_ORE, 0)
    print(f"[4] 叠带分拣器: 带子 {before}->{after}，熔炉输入="
          f"{mach.machines[(20, 12)].inputs}")
    if after != 0 or got != 1:
        print("  !! FAIL 叠在带子上的分拣器抓不到货")
        return False
    return True


def check_remove_cascade() -> bool:
    g = WorldGrid(64, 64)
    g.place(5, 5, C.B_BELT, 0)
    g.place_overlay(5, 5, C.B_INSERTER, 0)
    g.remove(5, 5)
    left = g.get_overlay(5, 5)
    print(f"[5] 拆带子后 overlay={left} (期望 {C.B_EMPTY})")
    if left != C.B_EMPTY:
        print("  !! FAIL 分拣器悬空残留")
        return False

    n = g.count_building(C.B_INSERTER)
    print(f"[6] count_building(分拣器)={n} (期望 0)")
    if n != 0:
        print("  !! FAIL 计数错误")
        return False
    return True


def check_count_and_power() -> bool:
    g = WorldGrid(64, 64)
    g.place(3, 3, C.B_BELT, 0)
    g.place(3, 4, C.B_BELT, 0)
    g.place_overlay(3, 3, C.B_INSERTER, 0)
    g.place_overlay(3, 4, C.B_INSERTER, 0)
    n = g.count_building(C.B_INSERTER)
    print(f"[7] 两个分拣器 count={n} (期望 2)")
    if n != 2:
        print("  !! FAIL 分拣器没计入建筑统计")
        return False
    return True


def check_filter() -> bool:
    """分拣器过滤：混矿带子上只抓指定品种，别的留给下游。

    布局（列 20，向下走）：
        (20,10) 带子 = 铁矿 + 铜矿 + 石矿
        (20,11) 带子 + 分拣器（过滤=铜矿），朝下 d=1 → 源=(20,10) 目标=(20,12)
        (20,12) 熔炉（铜板配方，只收铜矿）

    期望：只有铜矿被搬走，铁矿/石矿还留在带子上。
    """
    g = WorldGrid(64, 64)
    g.place(20, 10, C.B_BELT, 1)
    g.place(20, 11, C.B_BELT, 1)
    assert g.place_overlay(20, 11, C.B_INSERTER, 1)
    g.set_overlay_filter(20, 11, C.I_COPPER_ORE)
    g.place(20, 12, C.B_FURNACE, 0)

    belts = BeltNetwork(g)
    mach = MachineNetwork(g)
    mach.sync()
    m = mach.machines[(20, 12)]
    m.set_recipe("copper_plate")
    ins = InserterNetwork(g, belts)

    lane = belts.lanes[0]
    lane.positions = np.array([0.2, 0.5, 0.8], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE, C.I_COPPER_ORE, C.I_STONE],
                          dtype=np.int32)

    ins.update(0.0, mach)
    left = sorted(int(i) for i in lane.items)
    got = m.inputs.get(C.I_COPPER_ORE, 0)
    print(f"[8] 混矿带子过滤: 剩余物品={left}，熔炉={dict(m.inputs)}")
    if got != 1:
        print("  !! FAIL 过滤的铜矿没被抓走")
        return False
    if C.I_IRON_ORE not in left or C.I_STONE not in left:
        print("  !! FAIL 非过滤物品被误抓")
        return False
    if C.I_COPPER_ORE in left:
        print("  !! FAIL 铜矿还有残留（应该被抓干净）")
        return False

    # 清掉过滤 → 应该恢复抓任意物品
    g.set_overlay_filter(20, 11, 0)
    ins.cooldowns.clear()
    lane.positions = np.array([0.2], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)
    m.set_recipe("iron_plate")   # 换成收铁矿，避免被目标需求挡住
    ins.update(0.0, mach)
    if m.inputs.get(C.I_IRON_ORE, 0) != 1:
        print("  !! FAIL 清掉过滤后没恢复抓取")
        return False
    print("[9] 清过滤后恢复抓任意物品 OK")
    return True


def check_filter_serialization() -> bool:
    """过滤值随拆带子一起清掉，不会残留在数组里。"""
    g = WorldGrid(32, 32)
    g.place(3, 3, C.B_BELT, 0)
    g.place_overlay(3, 3, C.B_INSERTER, 0)
    g.set_overlay_filter(3, 3, C.I_STONE)
    if g.get_overlay_filter(3, 3) != C.I_STONE:
        print("  !! FAIL 过滤值没设上")
        return False
    g.remove(3, 3)
    f = g.get_overlay_filter(3, 3)
    print(f"[10] 拆带子后过滤值={f} (期望 0)")
    if f != 0:
        print("  !! FAIL 拆带子后过滤值残留")
        return False
    return True


def check_belt_to_belt() -> bool:
    """带子→分拣器→带子：目标带满了不能把来源带钉死，物品一个不能丢。

    回归 M6.13 的 bug：分拣器原来对目标传送带无条件返回"能收"，
    目标带塞满后每帧抓了又放不回，来源带队首被反复拽回格头，整条带子堵死。
    """
    g = WorldGrid(64, 64)
    for x in range(10, 17):                     # 源带向右，分拣器叠在 16 上
        g.place(x, 12, C.B_BELT, 0)
    g.place_overlay(16, 12, C.B_INSERTER, 0)
    for y in range(12, 19):                     # 目标带向下拐弯
        g.place(17, y, C.B_BELT, 1)
    b = BeltNetwork(g)
    ins = InserterNetwork(g, b)
    mn = MachineNetwork(g)

    src_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (10, 12))
    tgt_i = next(i for i, l in enumerate(b.lanes) if l.cells[0][0] >= 17)

    produced = 0
    for _ in range(1800):                       # 30 秒持续供料，目标带会先塞满
        if b.try_insert(10, 12, C.I_IRON_PLATE):
            produced += 1
        b.update(1 / 60)
        ins.update(1 / 60, mn)

    src = b.lanes[src_i]
    tgt = b.lanes[tgt_i]
    lost = produced - b.item_count
    print(f"[11] 供料 {produced}，皮带总物品 {b.item_count}，丢失 {lost}")
    if lost != 0:
        print("  !! FAIL 带子→带子搬运丢了物品")
        return False

    head = float(src.positions.max()) if len(src.positions) else -1.0
    expect = float(src.length)                  # 有下游时队首顶到 length
    print(f"[12] 源带队首={head:.2f} (期望 ~{expect:.2f})，目标带首格物品={len(tgt.positions)}")
    if head < expect - 0.1:
        print("  !! FAIL 来源带被分拣器钉在格头，后面堵死")
        return False

    # 再跑 1 秒，来源带物品位置必须纹丝不动（不能每帧抓了又放回抖动）
    before = [round(float(p), 3) for p in src.positions]
    for _ in range(60):
        b.update(1 / 60)
        ins.update(1 / 60, mn)
    after = [round(float(p), 3) for p in src.positions]
    print(f"[13] 再 1 秒源带物品数 {len(before)}→{len(after)}，抖动量="
          f"{max((abs(a - c) for a, c in zip(before, after)), default=0):.3f}")
    if len(before) != len(after):
        print("  !! FAIL 目标满时来源带物品数量还在变（抓放抖动/丢失）")
        return False
    if before and max(abs(a - c) for a, c in zip(before, after)) > 1e-6:
        print("  !! FAIL 目标满时来源带物品位置还在动（被钉住抖动）")
        return False
    return True



def check_three_part_arm() -> bool:
    """M10：头/连接部/尾三段几何 + 遮挡规则 + 动画状态 + 渲染不崩。"""
    from types import SimpleNamespace

    import pygame

    from stellarloom.core.game import Game
    from stellarloom.render.camera import Camera
    from stellarloom.render.layers import arm_part_hidden, inserter_hand

    src, dst = (0.0, 0.0), (10.0, 4.0)
    p0, ph, p1 = (inserter_hand(src, dst, t) for t in (0.0, 0.5, 1.0))
    print(f"[14] 手部 0/0.5/1 = {p0}/{ph}/{p1}")
    if p0 != src or p1 != dst or abs(ph[0] - 5.0) > 1e-9 or abs(ph[1] - 2.0) > 1e-9:
        print("  !! FAIL 手部插值不对")
        return False
    if inserter_hand(src, dst, 2.0) != dst or inserter_hand(src, dst, -1.0) != src:
        print("  !! FAIL 越界没钳制")
        return False

    hid = (arm_part_hidden(C.B_EMPTY), arm_part_hidden(C.B_BELT),
           arm_part_hidden(C.B_FURNACE), arm_part_hidden(C.B_ASSEMBLER))
    print(f"[15] 遮挡（空/带/熔炉/制造台）= {hid}（期望 False/False/True/True）")
    if hid != (False, False, True, True):
        print("  !! FAIL 机器格没有隐藏头/尾")
        return False

    g = WorldGrid(64, 64)
    g.place(20, 10, C.B_BELT, 1)
    g.place(20, 11, C.B_BELT, 1)
    g.place_overlay(20, 12, C.B_INSERTER, 1)
    g.place(20, 13, C.B_FURNACE, 0)
    belts = BeltNetwork(g)
    mach = MachineNetwork(g)
    mach.sync()
    mach.machines[(20, 13)].set_recipe("iron_plate")
    ins = InserterNetwork(g, belts)
    lane = belts.lanes[0]
    lane.positions = np.array([1.5], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)
    ins.update(0.0, mach)
    key = (20, 12)
    anim = ins.anim.get(key, 0.0)
    carry = ins.carry.get(key)
    print(f"[16] 投递后 anim={anim:.2f} carry={carry}")
    if abs(anim - 2 * C.INSERTER_SWING_TIME) > 1e-9 or carry != C.I_IRON_ORE:
        print("  !! FAIL 投递后没有开始摆动/手上没物品")
        return False
    ins.update(C.INSERTER_SWING_TIME, mach)
    rem = ins.anim.get(key, 0.0)
    phase = 1.0 - abs(rem - C.INSERTER_SWING_TIME) / C.INSERTER_SWING_TIME
    print(f"[17] 半程 rem={rem:.2f} phase={phase:.2f}")
    if abs(phase - 1.0) > 1e-9:
        print("  !! FAIL 半程手没到目标格")
        return False
    ins.update(C.INSERTER_SWING_TIME, mach)
    print(f"[18] 整程后 anim={ins.anim.get(key)} carry={ins.carry.get(key)}")
    if key in ins.anim or key in ins.carry:
        print("  !! FAIL 动画没清干净")
        return False

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((320, 240))
    g2 = WorldGrid(64, 64)
    g2.place(20, 10, C.B_BELT, 1)
    g2.place(20, 11, C.B_BELT, 1)
    g2.place_overlay(20, 12, C.B_INSERTER, 1)
    ins2 = InserterNetwork(g2, BeltNetwork(g2))
    cam = Camera(g2.w * C.TILE, g2.h * C.TILE)
    cam.x, cam.y = 20.5 * C.TILE, 12.5 * C.TILE
    fake = SimpleNamespace(screen=screen, camera=cam, grid=g2)
    fake.sim = SimpleNamespace(inserters=ins2)
    fake._arm_part_hidden = lambda gx, gy: arm_part_hidden(int(g2.get(gx, gy)))
    for zoom in (0.5, 1.0, 2.0):
        cam.zoom = zoom
        screen.fill((0, 0, 0))
        Game._draw_inserters(fake)
    corner = screen.get_at((2, 2))[:3]
    center = screen.get_at((160, 120))[:3]
    print(f"[19] 渲染 zoom=2 角落={corner} 中心={center}")
    pygame.quit()
    if center == corner:
        print("  !! FAIL 臂一个像素都没画出来")
        return False
    return True


def main():
    results = [
        ("lane 不切断 + 物品流通", check_lane_intact()),
        ("带子→分拣器→机器", check_belt_to_machine()),
        ("叠在带子上的分拣器", check_overlay_on_belt_grab()),
        ("拆带子级联删除", check_remove_cascade()),
        ("分拣器计数", check_count_and_power()),
        ("分拣器过滤混矿带", check_filter()),
        ("过滤值随拆除清理", check_filter_serialization()),
        ("带子→分拣器→带子不丢物品", check_belt_to_belt()),
        ("三段机械臂（头/连接部/尾）", check_three_part_arm()),
    ]
    print()
    bad = [name for name, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 分拣器叠加层 + 三段机械臂全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())