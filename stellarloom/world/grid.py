"""环形卷绕世界网格。

所有坐标访问都经过 wrap()，走出边界自动从另一侧回来。
建筑与方向用 numpy int32 数组存储，避免每格一个 Python 对象。
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class WorldGrid:
    def __init__(self, w: int = C.GRID_W, h: int = C.GRID_H, seed: int = 42):
        self.w = w
        self.h = h
        self.rng = np.random.default_rng(seed)

        # 建筑类型（0=空）
        self.building = np.zeros((h, w), dtype=np.int32)
        self.rev = 0                     # 建筑/叠层改动计数（电网等拓扑缓存用）
        # 建筑方向（传送带朝向等），0-3
        self.direction = np.zeros((h, w), dtype=np.int32)
        # 叠加建筑（目前只有分拣器）：可以叠在传送带上，不切断带子
        self.overlay = np.zeros((h, w), dtype=np.int32)
        self.overlay_dir = np.zeros((h, w), dtype=np.int32)
        # 分拣器过滤：0 = 不限，其余 = 只抓这个物品 ID（int32 免得种类不够用）
        self.overlay_filter = np.zeros((h, w), dtype=np.int32)
        # 矿脉储量（0 = 无矿）
        self.ore = np.zeros((h, w), dtype=np.int32)
        # 矿脉类型（0=无，1=铁，2=铜，3=石）
        self.ore_type = np.zeros((h, w), dtype=np.int8)

        # 叠加层代数：place/remove overlay 时 +1，供 InserterNetwork 判断
        # 坐标集合缓存是否过期（不依赖外部回调，谁用都正确）。
        self.overlay_gen = 0

        self._scatter_ore()

    # ---------- 坐标 ----------

    def wrap_x(self, x: int) -> int:
        return x % self.w

    def wrap_y(self, y: int) -> int:
        return y % self.h

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        return x % self.w, y % self.h

    # ---------- 矿脉 ----------

    def _scatter_ore(self, veins: int = 60):
        """随机撒矿脉：铁矿占主区，铜矿在对角区，石矿零散小块。"""
        for _ in range(veins):
            cx = int(self.rng.integers(0, self.w))
            cy = int(self.rng.integers(0, self.h))
            size = int(self.rng.integers(30, 120))
            # 按象限决定矿种：铜在铁矿对角区，石矿零散
            dx = abs(cx - self.w // 2) / (self.w / 2)
            dy = abs(cy - self.h // 2) / (self.h / 2)
            r = (dx + dy) / 2
            if r < 0.35:
                ore_t = C.ORE_IRON
            elif r < 0.65:
                ore_t = self.rng.random()
                ore_t = C.ORE_COPPER if ore_t < 0.7 else C.ORE_STONE
            else:
                ore_t = C.ORE_STONE if self.rng.random() < 0.6 else C.ORE_COPPER
            x, y = cx, cy
            for _ in range(size):
                self.ore[y, x] = int(self.rng.integers(200, 1000))
                self.ore_type[y, x] = ore_t
                # 随机游走一步
                x = (x + int(self.rng.integers(-1, 2))) % self.w
                y = (y + int(self.rng.integers(-1, 2))) % self.h

    def get_ore_type(self, x: int, y: int) -> int:
        return int(self.ore_type[y % self.h, x % self.w])

    def mine(self, x: int, y: int) -> int:
        """挖一格矿，返回物品 ID（0=没挖到）。

        矿脉无限：这里**不递减**储量，矿格永远挖不完。
        `self.ore` 里的数值现在只当"有没有矿"的标记 + 渲染用（存档也保留），
        真正的矿种看 `ore_type`。
        """
        x, y = self.wrap(x, y)
        if self.ore[y, x] > 0:
            ore_t = int(self.ore_type[y, x])
            return C.ORE_TO_ITEM.get(ore_t, C.I_IRON_ORE)
        return 0

    # ---------- 建筑 ----------

    def get(self, x: int, y: int) -> int:
        return int(self.building[y % self.h, x % self.w])

    def can_place(self, x: int, y: int) -> bool:
        """该格能否放建筑：空地，且不在任何物流塔的 3×3 占地内。

        塔只在中心格写 building，其余 8 格是空的，所以必须额外查一遍
        周围 3×3 有没有塔中心，否则传送带/熔炉能直接盖在塔身上。
        """
        if self.get(x, y) != C.B_EMPTY:
            return False
        x, y = self.wrap(x, y)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                cx, cy = (x + dx) % self.w, (y + dy) % self.h
                if int(self.building[cy, cx]) in (C.B_TOWER_SUPPLY,
                                                  C.B_TOWER_REQUEST):
                    return False
        return True

    def get_overlay(self, x: int, y: int) -> int:
        return int(self.overlay[y % self.h, x % self.w])

    def get_overlay_dir(self, x: int, y: int) -> int:
        return int(self.overlay_dir[y % self.h, x % self.w])

    def get_overlay_filter(self, x: int, y: int) -> int:
        """分拣器过滤物品 ID，0 = 不限。"""
        return int(self.overlay_filter[y % self.h, x % self.w])

    def set_overlay_filter(self, x: int, y: int, item: int):
        """设置分拣器过滤物品（0 = 不限）。"""
        x, y = self.wrap(x, y)
        self.overlay_filter[y, x] = item

    def place_overlay(self, x: int, y: int, btype: int, direction: int = 0) -> bool:
        """放叠加建筑（分拣器）。不和 building 冲突，能叠在传送带上。"""
        x, y = self.wrap(x, y)
        if self.overlay[y, x] != C.B_EMPTY:
            return False
        self.overlay[y, x] = btype
        self.overlay_dir[y, x] = direction
        self.overlay_filter[y, x] = 0
        self.overlay_gen += 1
        self.rev += 1
        return True

    def remove_overlay(self, x: int, y: int) -> bool:
        x, y = self.wrap(x, y)
        if self.overlay[y, x] == C.B_EMPTY:
            return False
        self.overlay[y, x] = C.B_EMPTY
        self.overlay_dir[y, x] = 0
        self.overlay_filter[y, x] = 0
        self.overlay_gen += 1
        self.rev += 1
        return True

    def place(self, x: int, y: int, btype: int, direction: int = 0) -> bool:
        if not self.can_place(x, y):
            return False
        x, y = self.wrap(x, y)
        self.building[y, x] = btype
        self.direction[y, x] = direction
        self.rev += 1
        return True

    def remove(self, x: int, y: int) -> bool:
        x, y = self.wrap(x, y)
        if self.building[y, x] in (C.B_EMPTY, C.B_CORE):
            return False
        self.building[y, x] = C.B_EMPTY
        self.direction[y, x] = 0
        self.rev += 1
        # 传送带被拆时，叠在上面的分拣器也一起掉（否则悬空的抓不到东西）
        if self.overlay[y, x] != C.B_EMPTY:
            self.overlay[y, x] = C.B_EMPTY
            self.overlay_dir[y, x] = 0
            self.overlay_filter[y, x] = 0
            self.overlay_gen += 1
            self.rev += 1
        return True

    def count_building(self, btype: int) -> int:
        """统计建筑数量。分拣器是 overlay，走 overlay 数组。"""
        if btype == C.B_INSERTER:
            return int(np.count_nonzero(self.overlay == C.B_INSERTER))
        return int(np.count_nonzero(self.building == btype))

    def belts_changed(self):
        """建筑增删后通知传送带网络重建 lane。由 Game 注入。"""
        if hasattr(self, "on_belts_changed"):
            self.on_belts_changed()