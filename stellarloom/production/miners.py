"""采矿机：脚下有矿就挖，挖出来的先放自己暂存格，再往带子上吐。

暂存格设计（本轮新增）：
- 每台采矿机自带 MINER_BUFFER_CAP（50）格的混装暂存
- 挖矿先塞暂存；暂存满了就停止挖掘（不白挖矿、不丢东西）
- 暂存里的矿优先往前方带子吐，吐不出去就继续囤着
- 玩家可以在采矿机面板里手动放入/取出

原来挖出来是直接 try_insert 到带子，带子满了矿就凭空消失，
所以暂存格不只是为了手动存取，也是修掉"矿被吞"这个老问题的关键。
"""

from __future__ import annotations

import numpy as np

from .. import config as C
from . import storage as S


class Miner:
    __slots__ = ("x", "y", "buffer")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.buffer: dict[int, int] = {}

    # ---------- 手动存取（面板用） ----------

    def space(self, item: int) -> int:
        return S.space(self.buffer, item, C.MINER_BUFFER_CAP,
                       C.MINER_BUFFER_CAP)

    def add_item(self, item: int, count: int) -> int:
        return S.add(self.buffer, item, count, C.MINER_BUFFER_CAP,
                     C.MINER_BUFFER_CAP)

    def take_item(self, item: int, count: int | None = None) -> int:
        return S.take(self.buffer, item, count)

    # ---------- 自动侧 ----------

    def has_space(self) -> bool:
        return S.total(self.buffer) < C.MINER_BUFFER_CAP

    def push(self, item: int) -> bool:
        """挖到一个矿：塞暂存。满了返回 False。"""
        return S.add(self.buffer, item, 1, C.MINER_BUFFER_CAP,
                     C.MINER_BUFFER_CAP) > 0

    def total(self) -> int:
        return S.total(self.buffer)


class MinerNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.miners: dict[tuple[int, int], Miner] = {}
        self._acc = 0.0
        self._dirty: list[tuple[int, int]] = []

    def sync(self):
        g = self.grid
        ys, xs = np.nonzero(g.building == C.B_MINER)
        wanted: set[tuple[int, int]] = set()
        for y, x in zip(ys.tolist(), xs.tolist()):
            wanted.add((x, y))
            if (x, y) not in self.miners:
                self.miners[(x, y)] = Miner(x, y)
        for k in [k for k in self.miners if k not in wanted]:
            del self.miners[k]

    def get(self, x: int, y: int) -> Miner | None:
        return self.miners.get((x % self.grid.w, y % self.grid.h))

    def update(self, dt: float, belts):
        """0.5 秒一轮：先吐暂存到带子，再挖新的填暂存。"""
        self._acc += dt
        interval = 0.5
        if self._acc < interval:
            return
        self._acc -= interval

        g = self.grid
        for m in self.miners.values():
            x, y = m.x, m.y
            d = int(g.direction[y, x])
            tx, ty = g.wrap(x + C.DX[d], y + C.DY[d])

            # 1) 先吐暂存：有货先出货，出得去才有地方装新挖的
            if m.buffer:
                for item in list(m.buffer.keys()):
                    while m.buffer.get(item, 0) > 0:
                        if not belts.try_insert(tx, ty, item):
                            break
                        m.take_item(item, 1)
                    break   # 一轮只吐一种，别把暂存同一帧全倒出去

            # 2) 再挖一铲（暂存没满、脚下有矿）
            if g.ore[y, x] > 0 and m.has_space():
                item = g.mine(x, y)
                if item:
                    m.push(item)
                    self._dirty.append((x, y))

    def pop_dirty_cells(self) -> list:
        """挖过的格子，交给 Game 去失效渲染缓存。"""
        cells = self._dirty
        self._dirty = []
        return cells