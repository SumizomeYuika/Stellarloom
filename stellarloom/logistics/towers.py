"""物流塔：供应塔存物资，请求塔要物资，无人机在中间飞。

Factorio 式主被动模型：
  supply  — 被动供应塔，从传送带/机器收物品入库
  request — 主动请求塔，向无人机要物品，再往传送带/机器吐

塔占地 3×3，网格里记中心格。物品交换只发生在 3×3 边缘的相邻格。
"""

from __future__ import annotations

import numpy as np

from .. import config as C

# 塔内 3×3 占地相对中心格的偏移
_TOWER_OFFSETS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


class Tower:
    __slots__ = ("x", "y", "mode", "inventory", "filter", "drones")

    def __init__(self, x: int, y: int, mode: str):
        self.x = x
        self.y = y
        self.mode = mode                  # "supply" | "request"
        self.inventory: dict[int, int] = {}  # item_id -> count
        self.filter: int | None = None    # None = 不限物品
        self.drones: list = []            # 由 DroneNetwork 填入

    # ---------- 库存操作 ----------

    def total(self) -> int:
        return sum(self.inventory.values())

    def capacity_left(self, item: int) -> int:
        if self.filter is not None and self.filter != item:
            return 0
        return C.TOWER_STACK - self.inventory.get(item, 0)

    def add_item(self, item: int, count: int) -> int:
        """入库存，返回放不下的数量。"""
        space = self.capacity_left(item)
        put = min(space, count)
        if put > 0:
            self.inventory[item] = self.inventory.get(item, 0) + put
        return count - put

    def remove_item(self, item: int, count: int) -> int:
        """出库存，返回实际拿到的数量。"""
        have = self.inventory.get(item, 0)
        take = min(have, count)
        if take > 0:
            self.inventory[item] = have - take
            if self.inventory[item] == 0:
                del self.inventory[item]
        return take

    def has(self, item: int, count: int = 1) -> bool:
        return self.inventory.get(item, 0) >= count

    def missing_items(self) -> dict[int, int]:
        """请求塔缺口：{item_id: 还缺多少}。供应塔永远返回空。"""
        if self.mode != "request":
            return {}
        # 简化：请求塔只关心过滤物品；没设过滤则每种物品都要补到半满
        if self.filter is not None:
            items = [self.filter]
        else:
            items = list(C.ITEM_COLORS.keys())
        out: dict[int, int] = {}
        for item in items:
            want = C.TOWER_STACK // 2
            have = self.inventory.get(item, 0)
            if have < want:
                out[item] = want - have
        return out

    def accepts(self, item: int) -> bool:
        """供应塔收不收这个物品。"""
        return self.filter is None or self.filter == item

    def all_cells(self):
        for dx, dy in _TOWER_OFFSETS:
            yield self.x + dx, self.y + dy


class TowerNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.towers: dict[tuple[int, int], Tower] = {}  # 中心格 -> Tower
        # 塔 3×3 外圈交换格缓存：(中心x, 中心y) -> [(x, y), ...]
        self._adj_cells: dict[tuple[int, int], list] = {}

    def get_tower(self, x: int, y: int) -> Tower | None:
        """某格是否在某个塔的 3×3 范围内。

        原来是遍历所有塔做 abs 比较（O(塔数)），点击和拆除都走这里。
        改成查 3×3 中心反查表：对给定格，最多只可能落在 9 个候选中心里。
        """
        g = self.grid
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                t = self.towers.get(((x + dx) % g.w, (y + dy) % g.h))
                if t is not None:
                    return t
        return None

    def can_place(self, x: int, y: int) -> bool:
        """3×3 范围内必须全空，且不能和已有塔的 3×3 重叠。

        塔只在中心格写 building，所以光查 3×3 格空不够：
        相邻 2 格处再放一座塔，两边的 3×3 会重叠成一片。
        两座 3×3 塔不重叠的条件是中心切比雪夫距离 >= 3。
        """
        g = self.grid
        for dx, dy in _TOWER_OFFSETS:
            cx, cy = (x + dx) % g.w, (y + dy) % g.h
            if int(g.building[cy, cx]) != C.B_EMPTY:
                return False
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                cx, cy = (x + dx) % g.w, (y + dy) % g.h
                if int(g.building[cy, cx]) in (C.B_TOWER_SUPPLY,
                                               C.B_TOWER_REQUEST):
                    return False
        return True

    def sync(self, drones=None):
        """建筑增删后调用：把网格里的塔映射成 Tower 对象。

        drones: DroneNetwork，传入时会为新塔 spawn 无人机、清理已拆塔的无人机。
        """
        g = self.grid
        # numpy 一次扫出所有塔格，不 Python 双重循环
        mask = (g.building == C.B_TOWER_SUPPLY) | (g.building == C.B_TOWER_REQUEST)
        ys, xs = np.nonzero(mask)
        for cy, cx in zip(ys.tolist(), xs.tolist()):
            b = int(g.building[cy, cx])
            key = (cx, cy)
            if key not in self.towers:
                mode = "supply" if b == C.B_TOWER_SUPPLY else "request"
                t = Tower(cx, cy, mode)
                self.towers[key] = t
                if drones is not None:
                    drones.spawn_for_tower(t)
                    t.drones = [d for d in drones.drones if d.home is t]
        # 删除已拆的
        dead = [k for k, t in self.towers.items()
                if int(g.building[t.y, t.x]) not in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST)]
        for k in dead:
            t = self.towers[k]
            if drones is not None:
                drones.remove_for_tower(t)
            self._adj_cells.pop((t.x, t.y), None)
            del self.towers[k]

    def update(self, dt: float, belts, drones):
        """每帧：
        1. 供应塔从相邻传送带抓物品
        2. 请求塔往相邻传送带吐物品
        3. 0.5 秒一次派无人机
        """
        g = self.grid
        for t in self.towers.values():
            if t.mode == "supply":
                self._pull_from_belts(t, g, belts)
            else:
                self._push_to_belts(t, g, belts)

        # 简单节流：利用帧时间累计，每 0.5 秒派一次
        self._assign_timer = getattr(self, "_assign_timer", 0.0) + dt
        if self._assign_timer >= 0.5:
            self._assign_timer = 0.0
            drones.assign_tasks(list(self.towers.values()))

    def _adjacent_belt_cells(self, t: Tower):
        """塔 3×3 外圈一圈的格子坐标（物品交换口）。

        缓存到塔实例上——这一圈格子对同一座塔永远不变，
        但原来每帧每座塔都重新 yield 16 次，233 座塔 × 16 = 3728 次/帧。
        """
        cached = self._adj_cells.get((t.x, t.y))
        if cached is not None:
            return cached
        g = self.grid
        out = []
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                if max(abs(dx), abs(dy)) != 2:
                    continue
                out.append(((t.x + dx) % g.w, (t.y + dy) % g.h))
        self._adj_cells[(t.x, t.y)] = out
        return out

    def _pull_from_belts(self, t: Tower, g, belts):
        """供应塔：从周围传送带抓物品。"""
        for bx, by in self._adjacent_belt_cells(t):
            if int(g.building[by, bx]) != C.B_BELT:
                continue
            lane_idx = belts.cell_lane.get((bx, by))
            if lane_idx is None:
                continue
            lane = belts.lanes[lane_idx]
            n = len(lane.positions)
            if n == 0:
                continue
            # 只抓“此刻正好流到本格”的物品（位置落在 [ci, ci+1)）。
            # 原来遍历整条 lane，会把上游十几格外的物品隔空吸进塔。
            # positions 有序，用二分定位本格区间，避免逐物品扫（塔多时很慢）。
            ci = lane.cell_index((bx, by))
            if ci < 0:
                continue
            lo = int(np.searchsorted(lane.positions, float(ci), side="left"))
            hi = int(np.searchsorted(lane.positions, float(ci + 1), side="left"))
            for i in range(hi - 1, lo - 1, -1):
                item = int(lane.items[i])
                if not t.accepts(item):
                    continue
                if t.capacity_left(item) <= 0:
                    break
                t.add_item(item, 1)
                lane.items = np.delete(lane.items, i).astype(np.int32)
                lane.positions = np.delete(lane.positions, i).astype(np.float32)
                break

    def _push_to_belts(self, t: Tower, g, belts):
        """请求塔：往周围传送带吐物品。

        原来物品在外层、格子在内层，每件物品都要重扫 16 格并各调一次
        try_insert。改成先找出能塞货的带子格，再按物品往里塞。
        """
        if not t.inventory:
            return
        # 先收集可用的带子格（一次）
        slots = []
        for bx, by in self._adjacent_belt_cells(t):
            if int(g.building[by, bx]) == C.B_BELT:
                slots.append((bx, by))
        if not slots:
            return
        for item, count in list(t.inventory.items()):
            if count <= 0:
                continue
            for bx, by in slots:
                if belts.try_insert(bx, by, item):
                    t.remove_item(item, 1)
                    break

    # ---------- 辅助 ----------

    def count(self) -> int:
        return len(self.towers)
