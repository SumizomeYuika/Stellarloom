#!/usr/bin/env python3
"""塔占地与面板状态残留回归。

两个怀疑点：
  A. 塔占 3×3，但只在中心格写 building，其余 8 格仍是空的，
     别的建筑能盖在塔身上（传送带穿过塔、熔炉压在塔边）。
  B. MachinePanel.show 不清 _recipe_rects，打开新机器时若在 draw 之前
     收到点击，会用上一台机器的配方表设置配方（跨建筑类型误设）。

跑法：python tools/_statecheck.py
"""

from __future__ import annotations

import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.logistics import TowerNetwork
from stellarloom.world import WorldGrid


class _FakeRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    @property
    def left(self): return self.x
    @property
    def top(self): return self.y
    @property
    def right(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h
    @property
    def width(self): return self.w
    @property
    def height(self): return self.h

    def collidepoint(self, pos):
        px, py = pos
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def size(self):
        return (self.w, self.h)

    @size.setter
    def size(self, v):
        self.w, self.h = int(v[0]), int(v[1])

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    @center.setter
    def center(self, v):
        self.x = int(v[0]) - self.w // 2
        self.y = int(v[1]) - self.h // 2


def check_tower_footprint() -> bool:
    """塔的 3×3 占地内不允许再放建筑。"""
    g = WorldGrid(64, 64)
    tw = TowerNetwork(g)
    cx, cy = 30, 30
    if not tw.can_place(cx, cy):
        print("  !! FAIL 空地却判定不能放塔")
        return False
    g.place(cx, cy, C.B_TOWER_SUPPLY, 0)
    # 塔占 (29..31, 29..31)，中心是 (30,30)
    bad = []
    for dx, dy in [(-1, -1), (1, 1), (0, -1), (1, 0)]:
        x, y = cx + dx, cy + dy
        if g.can_place(x, y):
            # 试着真放一个
            if g.place(x, y, C.B_FURNACE, 0):
                bad.append((x, y))
    print(f"[A] 塔 3×3 占地内成功放下的建筑: {bad}")
    if bad:
        print("  !! FAIL 建筑盖在塔身上了")
        return False
    return True


def check_panel_recipe_residue() -> bool:
    """MachinePanel 打开新机器时必须清掉上一台的配方点击区。"""
    pg = mock.MagicMock()
    pg.Rect = _FakeRect
    pg.Surface = mock.MagicMock()
    pg.SRCALPHA = 0
    pg.draw = mock.MagicMock()
    sys.modules.setdefault("pygame", pg)

    from stellarloom.ui.machine_panel import MachinePanel
    from stellarloom.production.machines import Machine

    panel = MachinePanel(mock.MagicMock())
    fur = Machine(10, 10, C.B_FURNACE)
    panel.show(fur, (1280, 720), set())
    # 模拟一次绘制，填满 _recipe_rects
    panel._recipe_rects = [(_FakeRect(100, 100, 200, 22), "magnet")]
    # 换成制造台并 show（不清 _recipe_rects 的旧实现会残留 magnet）
    asm = Machine(20, 20, C.B_ASSEMBLER)
    panel.show(asm, (1280, 720), set())
    leftover = [rid for _, rid in panel._recipe_rects]
    print(f"[B] show 之后残留的配方点击区: {leftover}")
    # 制造台的可用配方里没有 magnet，残留就是 bug
    if "magnet" in leftover:
        print("  !! FAIL 旧机器的配方行残留，可能误设配方")
        return False
    return True


def check_tower_tower_overlap() -> bool:
    """两座塔的 3×3 不能互相重叠。"""
    g = WorldGrid(64, 64)
    tw = TowerNetwork(g)
    g.place(30, 30, C.B_TOWER_SUPPLY, 0)
    # 中心只隔 2 格 → 3×3 会重叠
    ok = tw.can_place(32, 30)
    print(f"[C] 在 (32,30) 紧邻已有塔放第二座塔 → can_place={ok} (期望 False)")
    if ok:
        print("  !! FAIL 两座塔的 3×3 重叠了")
        return False
    return True


def main():
    results = [
        ("塔 3×3 占地不可侵占", check_tower_footprint()),
        ("机器面板点击区不残留", check_panel_recipe_residue()),
        ("塔与塔不重叠", check_tower_tower_overlap()),
    ]
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 状态残留检查全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())