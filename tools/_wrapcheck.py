#!/usr/bin/env python3
"""传送带环形卷绕 + 物流塔抓取的边界回归。

两个怀疑点：
  A. 跨越地图边界的 lane（x=510→0），rebuild 后物品会被丢掉，
     因为 _restore_items 用裸坐标算 frac，绕回来变成 >lane.length 被截掉。
  B. 供应塔从相邻带子抓物品时遍历整条 lane，会把还没流到塔旁边的
     上游物品也吸走。

跑法：python tools/_wrapcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, TowerNetwork
from stellarloom.world import WorldGrid


def check_wrap_rebuild() -> bool:
    """跨边界的 lane，rebuild 后物品不能凭空消失。"""
    g = WorldGrid(64, 64)
    cells = []
    # 从 x=60 一路向右铺到 x=3（跨卷绕点）
    x, y = 60, 20
    for _ in range(8):
        g.place(x, y, C.B_BELT, 0)
        cells.append((x, y))
        x = (x + 1) % g.w
    b = BeltNetwork(g)
    lane = b.lanes[0]
    print(f"[A] lane 数={len(b.lanes)} 长度={lane.length} "
          f"头={lane.cells[0]} 尾={lane.cells[-1]}")
    if lane.length != 8:
        print("  !! FAIL 跨边界 lane 长度不对")
        return False
    # 往第 3 格塞物品
    if not b.try_insert(*lane.cells[2], C.I_IRON_ORE):
        print("  !! FAIL 塞不进物品")
        return False
    before = b.item_count
    b.rebuild()
    after = b.item_count
    print(f"[A] rebuild 前物品={before} 后={after}")
    if after != before:
        print("  !! FAIL 跨边界 lane 重建丢物品")
        return False
    return True


def check_tower_pull_position() -> bool:
    """供应塔只能抓塔旁边那一格上的物品，不能吸走整条 lane 的上游物品。"""
    g = WorldGrid(64, 64)
    # 塔中心 (30,30)，3×3 占 (29..31, 29..31)，外圈交换格从 (28..32, ...)
    g.place(30, 30, C.B_TOWER_SUPPLY, 0)
    # 带子：从 x=10 一路向右铺到 x=28（塔左侧外圈格就是带子）
    cells = []
    x, y = 10, 30
    for _ in range(19):
        g.place(x, y, C.B_BELT, 0)
        cells.append((x, y))
        x += 1
    b = BeltNetwork(g)
    tw = TowerNetwork(g)
    tw.sync()

    lane = b.lanes[0]
    # 物品放在 lane 最开头（x=10），离塔交换格 (28,30) 还有 18 格远
    lane.positions = np.array([0.0], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)
    tower = next(iter(tw.towers.values()))
    tw._pull_from_belts(tower, g, b)
    got = tower.inventory.get(C.I_IRON_ORE, 0)
    print(f"[B] 带子贴着塔，物品在 lane 头 (10,30)，距塔 18 格："
          f"塔库存={dict(tower.inventory)} 带子剩余={len(lane.items)}")
    if got != 0:
        print("  !! FAIL 塔把远处上游物品吸走了（应只抓塔旁那一格）")
        return False
    return True


def check_tower_pull_adjacent() -> bool:
    """物品真的流到塔旁边的格子后，塔应该能抓到。"""
    g = WorldGrid(64, 64)
    g.place(30, 30, C.B_TOWER_SUPPLY, 0)
    x, y = 10, 30
    cells = []
    for _ in range(18):
        g.place(x, y, C.B_BELT, 0)
        cells.append((x, y))
        x += 1
    b = BeltNetwork(g)
    tw = TowerNetwork(g)
    tw.sync()
    lane = b.lanes[0]
    # 物品流到 x=27 格（塔外圈格 x=28 的前一格，还在带子上）
    ci = lane.cell_index((27, 30))
    lane.positions = np.array([float(ci) + 0.5], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)
    tower = next(iter(tw.towers.values()))
    # 塔旁边的带子格是 x=28，但带子只铺到 x=27，补一格
    g.place(28, 30, C.B_BELT, 0)
    b.rebuild()
    lane = b.lanes[0]
    ci = lane.cell_index((28, 30))
    lane.positions = np.array([float(ci) + 0.5], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)
    tw._pull_from_belts(tower, g, b)
    got = tower.inventory.get(C.I_IRON_ORE, 0)
    print(f"[C] 物品在塔旁 (28,30)，塔库存={dict(tower.inventory)}")
    if got != 1:
        print("  !! FAIL 物品就在塔旁边却抓不到")
        return False
    return True


def main():
    results = [
        ("跨边界 lane rebuild", check_wrap_rebuild()),
        ("塔不吸远处物品", check_tower_pull_position()),
        ("塔抓相邻格物品", check_tower_pull_adjacent()),
    ]
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 卷绕与物流塔边界全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
