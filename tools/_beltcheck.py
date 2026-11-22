#!/usr/bin/env python3
"""传送带 4 方向 lane 构建 + 物品流动回归。

背景：BeltNetwork.rebuild 用 np.nonzero 按行扫传送带格，
对下/右方向的带子，扫到的第一个格可能是 lane 中段而不是头部。
这个脚本对 4 个方向各建 8 格带子，检查：
  1. lane 数 = 1
  2. lane 长度 = 8
  3. 物品能从第一格流到末端
  4. lane.cells 顺序 = 玩家铺设的顺序

跑法：python tools/_beltcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork
from stellarloom.world import WorldGrid

N = 8


def build(d: int):
    g = WorldGrid(64, 64)
    cells = []
    x, y = 30, 30
    for _ in range(N):
        g.place(x, y, C.B_BELT, d)
        cells.append((x, y))
        x += C.DX[d]
        y += C.DY[d]
    return g, cells


def check_dir(d: int, name: str) -> bool:
    g, cells = build(d)
    b = BeltNetwork(g)
    lengths = [l.length for l in b.lanes]
    print(f"[dir={d} {name}] lane 数={len(b.lanes)} 长度={lengths}")
    if len(b.lanes) != 1:
        print("  !! FAIL 应该只有 1 条 lane")
        return False
    lane = b.lanes[0]
    if lane.length != N:
        print(f"  !! FAIL 长度应为 {N}")
        return False
    if list(lane.cells) != cells:
        print(f"  !! FAIL lane.cells 顺序不对")
        print(f"      期望 {cells}")
        print(f"      实际 {list(lane.cells)}")
        return False

    # 从第一格塞物品，看能否流到末端
    if not b.try_insert(*cells[0], C.I_IRON_ORE):
        print("  !! FAIL 第一格塞不进物品")
        return False
    for _ in range(600):
        b.update(1 / 60)
    if not len(lane.positions):
        print("  !! FAIL 物品凭空消失了")
        return False
    head = float(lane.positions[-1])
    print(f"  流动后 物品数={len(lane.positions)} 队首位置={head:.3f} "
          f"(期望 ~{N - 1})")
    if head < N - 1.5:
        print("  !! FAIL 物品没流到末端")
        return False
    return True


def check_turn() -> bool:
    """拐弯：右 3 格 + 拐角向下 + 下 3 格 → 应该是 2 条 lane，物品能跨 lane 传递。"""
    g = WorldGrid(64, 64)
    for i in range(3):
        g.place(30 + i, 30, C.B_BELT, 0)
    for i in range(4):
        g.place(33, 30 + i, C.B_BELT, 1)
    b = BeltNetwork(g)
    print(f"[拐弯] lane 数={len(b.lanes)} 长度={[l.length for l in b.lanes]} "
          f"next={[l.next_lane for l in b.lanes]}")
    if len(b.lanes) != 2:
        print("  !! FAIL 拐弯处应切成 2 条 lane")
        return False
    # 第一条 lane 的 next 应指向第二条
    src = b.lanes[0]
    if src.next_lane < 0:
        print("  !! FAIL 两条 lane 没连上 next_lane")
        return False
    b.try_insert(30, 30, C.I_IRON_ORE)
    for _ in range(900):
        b.update(1 / 60)
    dst = b.lanes[src.next_lane]
    print(f"  传输后 源lane物品={len(src.positions)} "
          f"下游lane物品={len(dst.positions)}")
    if not len(dst.positions):
        print("  !! FAIL 物品没传到下游 lane")
        return False
    return True


def check_backwards_build() -> bool:
    """反向铺设：先放末端再放头部，lane 仍应按方向正确排序。"""
    g = WorldGrid(64, 64)
    cells = []
    x, y = 30, 30
    for _ in range(N):
        cells.append((x, y))
        x += 1
    # 反序放
    for c in reversed(cells):
        g.place(c[0], c[1], C.B_BELT, 0)
    b = BeltNetwork(g)
    lane = b.lanes[0]
    print(f"[反向铺设] lane.cells 头={lane.cells[0]} 尾={lane.cells[-1]}")
    if lane.cells[0] != cells[0]:
        print(f"  !! FAIL 头部应为 {cells[0]}（物品入口端）")
        return False
    return True


def check_closed_loop() -> bool:
    """横穿整张地图、首尾相接的闭环带子。

    这条没有"真入口"（每格上游都有同向带子），旧的回溯实现会沿反方向
    走满 w*h 次找入口，26 万格时 rebuild 直接爆到 8 秒。这里锁死：
    lane 数必须是 1、长度 = 地图宽、物品能绕一圈不丢。
    """
    g = WorldGrid(64, 64)
    y = 20
    for x in range(g.w):
        g.place(x, y, C.B_BELT, 0)
    import time
    t0 = time.perf_counter()
    b = BeltNetwork(g)
    cost = (time.perf_counter() - t0) * 1000
    print(f"[闭环] lane 数={len(b.lanes)} 长度={[l.length for l in b.lanes]} "
          f"rebuild={cost:.0f}ms")
    if len(b.lanes) != 1 or b.lanes[0].length != g.w:
        print("  !! FAIL 闭环带子没合并成一条 lane")
        return False
    lane = b.lanes[0]
    if lane.next_lane != 0:
        print(f"  !! FAIL 闭环 lane 的 next_lane={lane.next_lane}（应指向自己 0）")
        return False
    b.try_insert(*lane.cells[0], C.I_IRON_ORE)
    for _ in range(2000):
        b.update(1 / 60)
    if b.item_count != 1:
        print(f"  !! FAIL 闭环上物品数={b.item_count}（应一直 1 个）")
        return False
    return True


def check_rebuild_preserves_positions() -> bool:
    """放置新建筑触发 rebuild 时，转角/停住带子上的物品不能跳位、不能挤成一坨。

    回归 bug：`_restore_items` 把格内偏移 frac 硬夹到 [0,1)，
    停住带子末段在上半格的物品 frac 是负的，全被夹成 0 → 位移/重叠。
    """
    g = WorldGrid(64, 64)
    for x in range(10, 15):
        g.place(x, 10, C.B_BELT, 0)          # 水平向右
    for y in range(10, 17):
        g.place(15, y, C.B_BELT, 1)          # 转角向下
    b = BeltNetwork(g)
    for x in range(10, 15):
        b.try_insert(x, 10, C.I_IRON_PLATE)
    for _ in range(360):                      # 6 秒，物品会堆到垂直带末端
        b.update(1 / 60)

    lane0_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (10, 10))
    lane1_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (15, 10))
    before = {
        lane0_i: [round(float(p), 3) for p in b.lanes[lane0_i].positions],
        lane1_i: [round(float(p), 3) for p in b.lanes[lane1_i].positions],
    }
    total_before = b.item_count

    b.rebuild()

    lane0_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (10, 10))
    lane1_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (15, 10))
    after = {
        lane0_i: [round(float(p), 3) for p in b.lanes[lane0_i].positions],
        lane1_i: [round(float(p), 3) for p in b.lanes[lane1_i].positions],
    }
    print(f"[rebuild保位] 水平前={before[lane0_i]} 后={after[lane0_i]}")
    print(f"[rebuild保位] 垂直前={before[lane1_i]} 后={after[lane1_i]} "
          f"物品数={total_before}->{b.item_count}")
    if b.item_count != total_before:
        print("  !! FAIL rebuild 丢了物品")
        return False
    for key in (lane0_i, lane1_i):
        if before[key] != after[key]:
            print(f"  !! FAIL rebuild 后 lane{key} 物品位置变了（跳位/挤坨）")
            return False
    return True



def check_validate_links() -> bool:
    """坏 next_lane（旧档/手改）能被 validate_links 按格子重算回来（#9）。"""
    g = WorldGrid(64, 64)
    for x in range(10, 15):
        g.place(x, 10, C.B_BELT, 0)          # lane A：10..14 向右
    for y in range(10, 14):
        g.place(15, y, C.B_BELT, 1)          # lane B：转角向下，接在 A 后
    b = BeltNetwork(g)
    a_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (10, 10))
    b_i = next(i for i, l in enumerate(b.lanes) if l.cells[0] == (15, 10))
    good = b.lanes[a_i].next_lane
    b.lanes[a_i].next_lane = 999             # 人为打断
    b.lanes[b_i].next_lane = -5
    b.validate_links()
    fixed = (b.lanes[a_i].next_lane == b_i
             and b.lanes[b_i].next_lane == -1)
    print(f"[validate] 坏链接修复：A→{b.lanes[a_i].next_lane}（期望 {b_i}）"
          f" B→{b.lanes[b_i].next_lane}（期望 -1）")
    if not fixed or good != b_i:
        print("  !! FAIL validate_links 没按格子重算")
        return False
    return True


def main():
    results = [
        ("向右", check_dir(0, "右")),
        ("向下", check_dir(1, "下")),
        ("向左", check_dir(2, "左")),
        ("向上", check_dir(3, "上")),
        ("拐弯分 lane", check_turn()),
        ("反向铺设", check_backwards_build()),
        ("闭环整圈", check_closed_loop()),
        ("rebuild 保位不挤坨", check_rebuild_preserves_positions()),
        ("next_lane 校验修复", check_validate_links()),
    ]
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 传送带 4 方向全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())