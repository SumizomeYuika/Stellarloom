"""电网（M9 真电网）：按空间连通性分区，产出每个电网的供电比例。

规则：
- 电力相关的建筑（发电/耗电/电力塔）只要**互相在 POWER_LINK_RANGE 格内**
  就连通（塔可接力），连成一个电网；不相连的就是两个电网，互不借电。
- 每个电网独立算 supply/demand → ratio；机器按自己所在电网的 ratio 变速。
- 戴森云与 mod 全局注电按各网需求比例摊派（不会凭空喂给孤岛）。
- 兼容：**全场一根电力塔都没有时退回旧版全球电网**（旧档/开局不至于全停电）。
- 单位：kW；显示自动转 kW/MW。旧 mod 直接 `power.last_supply += x` 的注电
  按 POWER_LEGACY_SCALE 换算成 kW 后摊到各网。
"""

from __future__ import annotations

import math

import numpy as np

from .. import config as C

_MISS = object()


def fmt_power(kw: float) -> str:
    """把 kW 数格式化成人看的单位。"""
    if kw >= 1000.0:
        return f"{kw / 1000.0:.2f} MW"
    if kw >= 10.0:
        return f"{kw:.0f} kW"
    return f"{kw:.1f} kW"


class PowerGrid:
    LINK_RANGE = C.POWER_LINK_RANGE

    def __init__(self, grid):
        self.grid = grid
        self.time = 0.0          # 累计游戏秒
        self.day_length = 120.0  # 一昼夜秒数
        self.dyson = None        # 由 game 注入 DysonNetwork（M4 戴森云供电）
        self.planet = None       # 由 game 注入 PlanetOrbit（轨道系统最小版）
        self.force_ratio: float | None = None  # 测试/调试：强制所有网比例

        # 电网分区缓存
        self._nets: list[dict] = []
        self._cell_net: dict[tuple[int, int], int] = {}
        self._legacy = False     # 没有电力塔 → 退回全球一张网
        self._rev = -1
        self._age = 999.0
        self._display_supply = 0.0
        self.legacy_inject = 0.0  # 旧 mod 注电（kW），每帧清零

        self.last_demand = 0.0
        self.last_ratio = 1.0

    # ---------- 旧 API 兼容：mod 用 last_supply += 注电 ----------

    @property
    def last_supply(self) -> float:
        return self._display_supply

    @last_supply.setter
    def last_supply(self, value: float):
        delta = float(value) - self._display_supply
        if delta > 0.0:
            self.legacy_inject += delta * C.POWER_LEGACY_SCALE

    # ---------- 拓扑 ----------

    def _rate_usage(self, btype: int) -> float:
        r = C.POWER_USAGE.get(btype, 0.0)
        if btype not in C.VANILLA_BUILDING_IDS:
            r *= C.POWER_LEGACY_SCALE   # mod 旧单位换算
        return r

    def _rate_gen(self, btype: int) -> float:
        r = C.POWER_GEN.get(btype, 0.0)
        if btype not in C.VANILLA_BUILDING_IDS:
            r *= C.POWER_LEGACY_SCALE
        return r

    def _collect_nodes(self):
        g = self.grid
        nodes = []
        ys, xs = np.nonzero(g.building)
        for y, x in zip(ys.tolist(), xs.tolist()):
            bt = int(g.building[y, x])
            if bt in C.POWER_GEN or bt in C.POWER_USAGE or bt == C.B_POWER_POLE:
                nodes.append((x, y, bt))
        # 分拣器是叠加层，但一样耗电
        oy, ox = np.nonzero(g.overlay == C.B_INSERTER)
        for y, x in zip(oy.tolist(), ox.tolist()):
            nodes.append((x, y, C.B_INSERTER))
        return nodes

    def _dist(self, x1, y1, x2, y2) -> float:
        w, h = self.grid.w, self.grid.h
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        dx = min(dx, w - dx)
        dy = min(dy, h - dy)
        return (dx * dx + dy * dy) ** 0.5

    def rebuild(self):
        """重建电网分区（建筑变化/定时调用）。"""
        g = self.grid
        nodes = self._collect_nodes()
        self._legacy = not any(bt == C.B_POWER_POLE for _, _, bt in nodes)
        self._nets = []
        self._cell_net = {}
        if not nodes:
            self._rev = getattr(g, "rev", 0)
            self._age = 0.0
            return

        n = len(nodes)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        if self._legacy:
            for i in range(1, n):
                union(0, i)
        else:
            R = max(1.0, self.LINK_RANGE)
            bk = max(1, int(R))
            buckets: dict[tuple[int, int], list[int]] = {}
            keys = []
            for i, (x, y, _bt) in enumerate(nodes):
                key = (x // bk, y // bk)
                keys.append(key)
                buckets.setdefault(key, []).append(i)
            bw = (g.w + bk - 1) // bk
            bh = (g.h + bk - 1) // bk
            for i, (x, y, _bt) in enumerate(nodes):
                bx, by = keys[i]
                for ox in (-1, 0, 1):
                    for oy in (-1, 0, 1):
                        for j in buckets.get(((bx + ox) % bw, (by + oy) % bh), ()):
                            if j <= i:
                                continue
                            x2, y2, _ = nodes[j]
                            if self._dist(x, y, x2, y2) <= R:
                                union(i, j)

        comp: dict[int, int] = {}
        for i, (x, y, bt) in enumerate(nodes):
            root = find(i)
            if root not in comp:
                comp[root] = len(self._nets)
                self._nets.append({"nodes": [], "gen": 0.0, "dem": 0.0,
                                   "ratio": 1.0})
            self._nets[comp[root]]["nodes"].append((x, y, bt))
            self._cell_net[(x, y)] = comp[root]

        self._rev = getattr(g, "rev", 0)
        self._age = 0.0

    # ---------- 每帧 ----------

    def update(self, dt: float):
        self.time += dt
        self._age += dt
        if (getattr(self.grid, "rev", 0) != self._rev or self._age >= 0.5
                or not self._nets):
            self.rebuild()

        daylight = max(0.0, math.sin(2 * math.pi * self.time / self.day_length))
        orbit_factor = (self.planet.solar_factor()
                        if self.planet is not None else 1.0)
        temp_eff = (self.planet.temperature_efficiency()
                    if self.planet is not None else 1.0)
        dyson_total = (self.dyson.power_output()
                       if self.dyson is not None else 0.0)
        global_extra = dyson_total + self.legacy_inject

        total_gen = 0.0
        total_dem = 0.0
        for net in self._nets:
            gen = 0.0
            dem = 0.0
            for _x, _y, bt in net["nodes"]:
                if bt == C.B_POWER_POLE:
                    continue
                if bt in C.POWER_GEN:
                    rate = self._rate_gen(bt)
                    if bt == C.B_SOLAR:
                        rate *= daylight * orbit_factor * temp_eff
                    gen += rate
                elif bt in C.POWER_USAGE:
                    dem += self._rate_usage(bt)
            net["gen"] = gen
            net["dem"] = dem
            total_gen += gen
            total_dem += dem

        # 全局注电（戴森云 / 旧 mod 注电）按需求比例摊到各网
        for net in self._nets:
            extra = 0.0
            if global_extra > 0.0:
                if total_dem > 0.0:
                    extra = global_extra * (net["dem"] / total_dem)
                elif not self._legacy:
                    extra = 0.0   # 没负载的网络不占电
            avail = net["gen"] + extra
            net["ratio"] = (min(1.0, avail / net["dem"])
                            if net["dem"] > 0.0 else 1.0)

        self.last_demand = total_dem
        self._display_supply = total_gen + global_extra
        if total_dem <= 0.0:
            self.last_ratio = 1.0
        else:
            self.last_ratio = min(1.0, self._display_supply / total_dem)
        self.legacy_inject = 0.0

    # ---------- 查询 ----------

    def factor_at(self, x: int, y: int) -> float:
        """该格所在电网的供电比例；不需要电的格子返回 1。"""
        if self.force_ratio is not None:
            return float(self.force_ratio)
        if self._legacy:
            return self.last_ratio
        key = (int(x) % self.grid.w, int(y) % self.grid.h)
        i = self._cell_net.get(key, _MISS)
        if i is _MISS:
            return 1.0
        return self._nets[i]["ratio"]

    @property
    def net_count(self) -> int:
        return max(1, len(self._nets))

    @property
    def speed_factor(self) -> float:
        """全局平均充足率（传送带/采矿等粗粒度用途）。"""
        return self.last_ratio

    @property
    def is_day(self) -> bool:
        return math.sin(2 * math.pi * self.time / self.day_length) > 0

    def status_text(self) -> str:
        pct = self.last_ratio * 100
        warn = " ⚠" if self.last_ratio < 0.99 else ""
        nets = f" · {len(self._nets)} 网" if len(self._nets) > 1 else ""
        return (f"电 {fmt_power(self._display_supply)}/"
                f"{fmt_power(self.last_demand)} ({pct:.0f}%){warn}{nets}")
