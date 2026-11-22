"""箱子：纯存储建筑，不耗电、不生产。

规则（本轮定）：
- 每种物品最多 CHEST_STACK 个（可混装多种）
- 分拣器可以往里放（feed），也可以从里面抓（take）
- 玩家在面板里可以手动放入任意物品、手动取出任意数量
- 箱子没有输入/输出区分，两个方向都通

箱子之所以没有像机器那样区分原料槽/产物槽，是因为箱子本身就是"纯容器"，
玩家往里塞什么就是什么；分拣器抓取时按过滤设置挑货。
"""

from __future__ import annotations

import numpy as np

from .. import config as C
from . import storage as S


class Chest:
    __slots__ = ("x", "y", "store")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.store: dict[int, int] = {}

    # ---------- 容量 ----------

    def space(self, item: int) -> int:
        return S.space(self.store, item, C.CHEST_STACK)

    def total(self) -> int:
        return S.total(self.store)

    # ---------- 自动侧（分拣器） ----------

    def feed(self, item: int) -> bool:
        return S.add(self.store, item, 1, C.CHEST_STACK) > 0

    def peek_item(self, flt: int = 0) -> int | None:
        for item, n in self.store.items():
            if n > 0 and (flt <= 0 or item == flt):
                return item
        return None

    def take_one(self, item: int) -> bool:
        return S.take(self.store, item, 1) > 0

    # ---------- 手动侧（面板） ----------

    def add_item(self, item: int, count: int) -> int:
        return S.add(self.store, item, count, C.CHEST_STACK)

    def take_item(self, item: int, count: int | None = None) -> int:
        """count=None 全取。"""
        return S.take(self.store, item, count)


class ChestNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.chests: dict[tuple[int, int], Chest] = {}

    def sync(self):
        g = self.grid
        ys, xs = np.nonzero(g.building == C.B_CHEST)
        wanted: set[tuple[int, int]] = set()
        for y, x in zip(ys.tolist(), xs.tolist()):
            wanted.add((x, y))
            if (x, y) not in self.chests:
                self.chests[(x, y)] = Chest(x, y)
        for k in [k for k in self.chests if k not in wanted]:
            del self.chests[k]

    def get(self, x: int, y: int) -> Chest | None:
        return self.chests.get((x % self.grid.w, y % self.grid.h))

    def count(self) -> int:
        return len(self.chests)