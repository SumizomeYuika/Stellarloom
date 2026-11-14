"""传送带网络：lane 合并 + 批量移动。

核心思路（参考 Factorio 的 transport line）：
- 把连续、同向的传送带格子合并成一条 Lane。
- 一条 Lane 内的物品用两个 numpy 数组表示：类型 + 沿 lane 的浮点位置。
- 移动时对整条 lane 的 positions 数组一次性加速，再用向量化的间距约束
  把挤压向后传递，没有逐格推进。

重建策略：
- 用 numpy 一次性找出所有传送带格（C 层扫描，快），再只在带格上走 lane，
  不再写 Python 双重循环扫全图。
- 重建前把所有物品换算成世界坐标快照，重建后按格子重新挂到新 lane 上，
  所以放置/拆除传送带不会让物品消失。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import config as C


@dataclass
class Lane:
    cells: list[tuple[int, int]]          # 有序格子，0=入口端，-1=出口端
    next_lane: int = -1                    # 下游 lane 下标，-1 = 断头
    positions: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    items: np.ndarray = field(default_factory=lambda: np.empty(0, np.int32))

    @property
    def length(self) -> int:
        return len(self.cells)

    def cell_index(self, cell) -> int:
        """格子在 lane 内的序号，带缓存避免反复 list.index。"""
        m = self.__dict__.get("_idx_map")
        if m is None:
            m = {c: i for i, c in enumerate(self.cells)}
            self.__dict__["_idx_map"] = m
        return m.get(cell, -1)


class BeltNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.lanes: list[Lane] = []
        self.cell_lane: dict[tuple[int, int], int] = {}
        self.rebuild()

    # ---------- 构建 ----------

    def rebuild(self):
        """重建 lane 拓扑，并保留所有在途物品。"""
        self._snapshot = self._snapshot_items()

        self.lanes.clear()
        self.cell_lane.clear()

        g = self.grid
        # numpy 找出所有传送带格，避免 Python 双重循环
        belt_ys, belt_xs = np.nonzero(g.building == C.B_BELT)
        if not len(belt_ys):
            return

        visited = np.zeros((g.h, g.w), dtype=bool)

        # 向量化算出每个带格的上游格，判断它是不是"真入口"：
        # 上游不是带子、或上游方向不同 → 是真入口。
        # 必须从真入口开始 trace：np.nonzero 是行主序，向左/向上的带子
        # 会先扫到出口端，从出口端走一步就出界，会把一条带子切成碎 lane。
        d_self = g.direction[belt_ys, belt_xs]
        dx = np.array(C.DX, dtype=np.int64)[d_self]
        dy = np.array(C.DY, dtype=np.int64)[d_self]
        up_y = (belt_ys - dy) % g.h
        up_x = (belt_xs - dx) % g.w
        is_entry = ((g.building[up_y, up_x] != C.B_BELT)
                    | (g.direction[up_y, up_x] != d_self))

        # 第一轮：只从真入口出发
        for by, bx in zip(belt_ys[is_entry].tolist(),
                          belt_xs[is_entry].tolist()):
            if visited[by, bx]:
                continue
            self._trace_lane(bx, by, visited)

        # 第二轮：剩下的都是首尾相接的闭环（每格都有同向上游，没有入口），
        # 随便挑起点即可。这样每个带格最多访问两次，整体 O(n)。
        for by, bx in zip(belt_ys.tolist(), belt_xs.tolist()):
            if visited[by, bx]:
                continue
            self._trace_lane(bx, by, visited)

        # 建立 lane 间连接
        for lane in self.lanes:
            ex, ey = lane.cells[-1]
            d = int(g.direction[ey, ex])
            nx, ny = g.wrap(ex + C.DX[d], ey + C.DY[d])
            lane.next_lane = self.cell_lane.get((nx, ny), -1)

        self._restore_items(self._snapshot)
        self._snapshot = []

    def validate_links(self) -> None:
        """按当前格子/方向重算 lane 间连接（还 TechDebt #9）。

        读档恢复的 `next_lane` 可能是旧档/手改存档留下的坏下标，直接信它
        会让物品卡在断头或串到别的 lane。这里只重算连接、不动物品位置，
        比整张 `rebuild()` 便宜且不丢浮点精度。
        """
        g = self.grid
        for lane in self.lanes:
            if not lane.cells:
                lane.next_lane = -1
                continue
            ex, ey = lane.cells[-1]
            d = int(g.direction[ey, ex])
            nx, ny = g.wrap(ex + C.DX[d], ey + C.DY[d])
            lane.next_lane = self.cell_lane.get((nx, ny), -1)

    def _trace_lane(self, sx: int, sy: int, visited: np.ndarray):
        g = self.grid
        cells: list[tuple[int, int]] = []
        x, y = sx, sy
        direction = int(g.direction[sy, sx])
        while True:
            x, y = g.wrap(x, y)
            if visited[y, x] or g.building[y, x] != C.B_BELT:
                break
            if int(g.direction[y, x]) != direction:
                break
            visited[y, x] = True
            cells.append((x, y))
            x += C.DX[direction]
            y += C.DY[direction]
        if not cells:
            return
        idx = len(self.lanes)
        self.lanes.append(Lane(cells=cells))
        for c in cells:
            self.cell_lane[c] = idx

    # ---------- 物品快照 / 恢复 ----------

    def _snapshot_items(self) -> list[tuple[float, float, int]]:
        """把在途物品换算成世界格坐标（格中心 = 整数 + 0.5）。"""
        out = []
        for lane in self.lanes:
            if not len(lane.positions):
                continue
            x0, y0 = lane.cells[0]
            d = int(self.grid.direction[lane.cells[0][1], lane.cells[0][0]])
            dx, dy = C.DX[d], C.DY[d]
            for pos, item in zip(lane.positions, lane.items):
                out.append((x0 + dx * float(pos) + 0.5,
                            y0 + dy * float(pos) + 0.5,
                            int(item)))
        return out

    def _restore_items(self, snapshot):
        if not snapshot:
            return
        g = self.grid
        buckets: dict[int, list[tuple[float, int]]] = {}
        for gx, gy, item in snapshot:
            # 按世界坐标精确投影回它所在的 lane，而不是用 int(gx) 猜格子。
            # snapshot 用的是「x0 + dir*pos + 0.5」，所以 pos 要反解：
            #   向右：pos = gx - x0 - 0.5；向左：pos = x0 - gx + 0.5
            #   向下：pos = gy - y0 - 0.5；向上：pos = y0 - gy + 0.5
            placed = False
            for idx, lane in enumerate(self.lanes):
                if not lane.cells:
                    continue
                x0, y0 = lane.cells[0]
                d = int(g.direction[y0, x0])
                if d == 0:
                    if abs(gy - (y0 + 0.5)) > 0.6:
                        continue
                    pos = gx - x0 - 0.5
                elif d == 2:
                    if abs(gy - (y0 + 0.5)) > 0.6:
                        continue
                    pos = x0 - gx + 0.5
                elif d == 1:
                    if abs(gx - (x0 + 0.5)) > 0.6:
                        continue
                    pos = gy - y0 - 0.5
                else:
                    if abs(gx - (x0 + 0.5)) > 0.6:
                        continue
                    pos = y0 - gy + 0.5
                # 落在该 lane 范围内才算（含一点点容差，容纳边界处物品）
                if -0.5 <= pos < lane.length + 0.5:
                    ci = int(max(0.0, min(pos, lane.length - 1e-6)))
                    frac = pos - ci
                    frac = min(max(frac, 0.0), 0.999)
                    buckets.setdefault(idx, []).append((ci + frac, item))
                    placed = True
                    break
            # 找不到归属的（所在带子被拆）就地丢弃，跟旧行为一致

        for idx, entries in buckets.items():
            entries.sort()
            lane = self.lanes[idx]
            lane.positions = np.array([p for p, _ in entries], dtype=np.float32)
            lane.items = np.array([i for _, i in entries], dtype=np.int32)
            # 挤掉超出容量上限的（超长 lane 被截断的极端情况）
            keep = lane.positions < lane.length
            lane.positions = lane.positions[keep]
            lane.items = lane.items[keep]

    # ---------- 物品操作 ----------

    def try_insert(self, x: int, y: int, item_type: int = 1) -> bool:
        """往某格传送带塞物品（采矿机往带上吐）。"""
        cell = (x % self.grid.w, y % self.grid.h)
        idx = self.cell_lane.get(cell)
        if idx is None:
            return False
        lane = self.lanes[idx]
        ci = lane.cell_index(cell)
        if ci < 0:
            return False
        pos = float(ci)
        # 只看目标位置下游方向的最近物品（positions 有序）
        if len(lane.positions):
            j = int(np.searchsorted(lane.positions, pos, side="right"))
            if j < len(lane.positions):
                if lane.positions[j] - pos < C.ITEM_SPACING:
                    return False
            if j > 0 and pos - lane.positions[j - 1] < C.ITEM_SPACING:
                return False
        # searchsorted 找插入点，保持 positions 有序
        i = int(np.searchsorted(lane.positions, pos))
        lane.positions = np.insert(lane.positions, i, pos).astype(np.float32)
        lane.items = np.insert(lane.items, i, item_type).astype(np.int32)
        return True

    def has_space(self, x: int, y: int) -> bool:
        """某格传送带还能不能塞进一个物品（不真的塞）。

        分拣器先用它判断目标带有没有空间，没有就不抓，
        否则会每帧抓了又放不回，把来源带的物品钉住甚至弄丢。
        """
        cell = (x % self.grid.w, y % self.grid.h)
        idx = self.cell_lane.get(cell)
        if idx is None:
            return False
        lane = self.lanes[idx]
        ci = lane.cell_index(cell)
        if ci < 0:
            return False
        pos = float(ci)
        if len(lane.positions):
            j = int(np.searchsorted(lane.positions, pos, side="right"))
            if j < len(lane.positions):
                if lane.positions[j] - pos < C.ITEM_SPACING:
                    return False
            if j > 0 and pos - lane.positions[j - 1] < C.ITEM_SPACING:
                return False
        return True

    def insert_at(self, lane_idx: int, pos: float, item_type: int) -> bool:
        """按绝对位置插入物品（分拣器投递失败原样放回用）。

        该位置刚刚被取出过，槽位一定是空的，不再做间距检查，
        否则浮点位置会跟邻居擦边导致放不回、物品凭空消失。
        """
        if lane_idx < 0 or lane_idx >= len(self.lanes):
            return False
        lane = self.lanes[lane_idx]
        i = int(np.searchsorted(lane.positions, pos))
        lane.positions = np.insert(lane.positions, i, pos).astype(np.float32)
        lane.items = np.insert(lane.items, i, item_type).astype(np.int32)
        return True

    def take_at_end(self, lane_idx: int) -> int | None:
        """取走 lane 出口端的物品，返回物品类型。"""
        lane = self.lanes[lane_idx]
        if not len(lane.positions):
            return None
        i = len(lane.positions) - 1
        if lane.positions[i] < lane.length - C.ITEM_SPACING:
            return None
        item = int(lane.items[i])
        lane.positions = lane.positions[:i]
        lane.items = lane.items[:i]
        return item

    # ---------- 每帧更新 ----------

    def update(self, dt: float):
        speed = C.BELT_SPEED * dt
        spacing = C.ITEM_SPACING
        lanes = self.lanes
        n_lanes = len(lanes)

        for idx in range(n_lanes):
            lane = lanes[idx]
            n = len(lane.positions)
            if n == 0:
                continue

            nxt = lanes[lane.next_lane] if lane.next_lane >= 0 else None
            lane.positions += speed

            # 队首上限：有下游时放到 length（越过即转移），断头时最后物品停在末格中心
            head = float(lane.length) if nxt is not None else float(lane.length - 1)

            # 向量化压缩：pos[i] <= head - spacing*(n-1-i)
            if n > 1:
                limits = head - spacing * np.arange(
                    n - 1, -1, -1, dtype=np.float32)
                np.minimum(lane.positions, limits, out=lane.positions)
            elif lane.positions[0] > head:
                lane.positions[0] = head

            if nxt is None:
                continue

            # 越界物品推给下游
            while len(lane.positions) and lane.positions[-1] >= lane.length:
                if len(nxt.positions) and nxt.positions[0] < spacing:
                    lane.positions[-1] = lane.length - 1e-3
                    break
                overflow = float(lane.positions[-1]) - lane.length
                item = int(lane.items[-1])
                lane.positions = lane.positions[:-1]
                lane.items = lane.items[:-1]
                nxt.positions = np.insert(nxt.positions, 0, overflow).astype(np.float32)
                nxt.items = np.insert(nxt.items, 0, item).astype(np.int32)

    # ---------- 查询 ----------

    def iter_items(self):
        """yield (x_float, y_float, item_type) 世界格坐标。"""
        for lane in self.lanes:
            if not len(lane.positions):
                continue
            x0, y0 = lane.cells[0]
            d = int(self.grid.direction[lane.cells[0][1], lane.cells[0][0]])
            dx, dy = C.DX[d], C.DY[d]
            for pos, item in zip(lane.positions.tolist(), lane.items.tolist()):
                yield (x0 + dx * pos + 0.5, y0 + dy * pos + 0.5, item)

    @property
    def item_count(self) -> int:
        return sum(len(l.positions) for l in self.lanes)