"""液体管网（M14）：**每格独立液量** + 压差限速均流 + 泵单向加压。

为什么不"整段共享"（这是用户 8.1 明确要的）：
- 整段共享 = 液体瞬间均布，长管线没有代价，泵也没用。
- 这里每格自己存液量（管道 100 / 储罐 2500），相邻两格之间**按压差限速**
  互流（每秒最多 PIPE_FLOW_RATE）。于是：
  * 长管线要时间才灌满/排空，压力（液位）是真实的一格格传过去的；
  * 液体只能从高液位流向低液位（没有泵时）；
  * 泵（B_FLUID_PUMP）是**单向加压器**：输入口 = 本格 − 朝向，
    输出口 = 本格 + 朝向，速率上限 PUMP_FLOW_RATE，**不看两边压差**——
    所以能把液体从低液位打到高液位，也能隔着泵把两段管网"加压接力"。

一格只装一种液体：不同液体相邻时**不互流**（要玩家自己分流/抽干）。
同一格里出现两种液体只可能来自"拆管道重建"或"存档注入"，按先到先得保留。

数据结构（稀疏，随 grid.rev 重建，不做 512×512 每帧扫描）：
    cells[i] = (x, y)          cap[i] 容量     amt[i] 液量
    fid[i]  液体 id（0 = 空）   nb[i*4+d] 邻居下标（-1 = 没有）
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class FluidNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.cells: list[tuple[int, int]] = []
        self.index: dict[tuple[int, int], int] = {}
        self.amt = np.zeros(0, np.float32)
        self.fid = np.zeros(0, np.int32)
        self.cap = np.zeros(0, np.float32)
        # nb[i, d] = 第 i 格朝 d 方向的邻居下标（-1 = 不是液体格）
        self.nb = np.zeros((0, 4), np.int32)
        self.pumps: list[tuple[int, int, int]] = []   # (x, y, dir)
        self._rev = -1
        self._pump_dirs = np.zeros(0, np.int32)

        # 统计（HUD / 自检用）
        self.flowed = 0.0        # 上一帧输运总量（单位）
        self.pumped = 0.0        # 上一帧泵输运总量

    # ---------- 拓扑 ----------

    def invalidate(self):
        """建筑变化后调用；下一帧 update/查询时自动重建。"""
        self._rev = -1

    def _snapshot(self) -> dict[tuple[int, int], tuple[int, float]]:
        out = {}
        for i, cell in enumerate(self.cells):
            if self.amt[i] > C.FLUID_EPS:
                out[cell] = (int(self.fid[i]), float(self.amt[i]))
        return out

    def rebuild(self):
        """按当前网格重建格表/邻居表/泵表，保留已有液体（按坐标搬运）。"""
        prev = self._snapshot()
        self.cells = []
        self.index = {}
        self.pumps = []
        g = self.grid
        ys, xs = np.nonzero((g.building == C.B_PIPE)
                            | (g.building == C.B_TANK))
        coords = list(zip(xs.tolist(), ys.tolist()))
        self.cells = coords
        self.index = {c: i for i, c in enumerate(coords)}
        n = len(coords)
        self.amt = np.zeros(n, np.float32)
        self.fid = np.zeros(n, np.int32)
        self.cap = np.zeros(n, np.float32)
        for i, (x, y) in enumerate(coords):
            bt = int(g.building[y % g.h, x % g.w])
            self.cap[i] = (C.TANK_CELL_CAP if bt == C.B_TANK
                           else C.PIPE_CELL_CAP)
            old = prev.get((x, y))
            if old is not None:
                f, a = old
                self.fid[i] = f
                self.amt[i] = min(a, self.cap[i])
        # 邻居表（四邻，环绕世界）
        nb = np.full((n, 4), -1, np.int32)
        w, h = g.w, g.h
        for i, (x, y) in enumerate(coords):
            for d in range(4):
                nx = (x + C.DX[d]) % w
                ny = (y + C.DY[d]) % h
                j = self.index.get((nx, ny))
                if j is not None:
                    nb[i, d] = j
        self.nb = nb
        # 泵表
        pys, pxs = np.nonzero(g.building == C.B_FLUID_PUMP)
        for y, x in zip(pys.tolist(), pxs.tolist()):
            self.pumps.append((x, y, int(g.direction[y, x]) & 3))
        self._pump_dirs = np.array([d for _, _, d in self.pumps], np.int32)
        self._rev = getattr(g, "rev", 0)

    def _ensure(self):
        if getattr(self.grid, "rev", 0) != self._rev:
            self.rebuild()

    # ---------- 每帧 ----------

    def update(self, dt: float, power=None):
        """先均流、再跑泵。power 可为 PowerGrid（按泵所在电网取比例）。"""
        self._ensure()
        if dt <= 0.0 or not len(self.cells):
            self.flowed = 0.0
            self.pumped = 0.0
            return
        self.flowed = self._equalize(dt)
        self.pumped = self._run_pumps(dt, power)
        self._cleanup()

    def _cleanup(self):
        """空格的液体 id 归零（避免"我没有液体但残留类型"挡住别种液体）。"""
        empty = self.amt <= C.FLUID_EPS
        if empty.any():
            self.amt[empty] = 0.0
            self.fid[empty] = 0

    def _equalize(self, dt: float) -> float:
        """相邻格按压差限速互流（同种液体或一侧为空才流）。返回本帧输运量。"""
        amt, cap, fid, nb = self.amt, self.cap, self.fid, self.nb
        maxq = float(C.PIPE_FLOW_RATE) * dt
        if maxq <= 0.0:
            return 0.0
        n = len(self.cells)
        idx = np.arange(n, dtype=np.int32)
        total = 0.0
        for d in range(4):
            j = nb[:, d]
            # 每条无向边只算一次：只处理 i < j 的那一端
            mask = (j >= 0) & (j > idx)
            if not mask.any():
                continue
            i = idx[mask]
            jj = j[mask]
            ai = amt[i]
            aj = amt[jj]
            fi = fid[i]
            fj = fid[jj]
            # 兼容：一侧为空（0）或两侧同种液体；不同种互不流动
            compat = (ai <= C.FLUID_EPS) | (aj <= C.FLUID_EPS) | (fi == fj)
            if not compat.any():
                continue
            i = i[compat]
            jj = jj[compat]
            ai = ai[compat]
            aj = aj[compat]
            ci = cap[i]
            cj = cap[jj]
            diff = ai - aj
            # 压差驱动：一次最多走一半差值（不会来回震荡），再被速率上限钳住
            q = np.clip(diff * 0.5, -maxq, maxq)
            # 不能超过源侧存量
            q = np.where(q > 0.0, np.minimum(q, ai), np.maximum(q, -aj))
            # 不能超过目标余量
            q = np.where(q > 0.0, np.minimum(q, cj - aj),
                         np.maximum(q, -(ci - ai)))
            m = np.abs(q) > 0.0
            if not m.any():
                continue
            i, jj, q = i[m], jj[m], q[m]
            np.add.at(amt, i, -q)
            np.add.at(amt, jj, q)
            # 液体类型跟着量走：源有液 → 目标空则继承类型
            src_f = fid[i]
            dst_empty = fid[jj] == 0
            if dst_empty.any():
                sel = dst_empty & (src_f != 0) & (q > 0.0)
                if sel.any():
                    fid[jj[sel]] = src_f[sel]
                sel2 = dst_empty & (src_f == 0) & (q < 0.0)
                if sel2.any():
                    fid[i[sel2]] = fid[jj[sel2]]
            total += float(np.abs(q).sum())
        return total

    def _run_pumps(self, dt: float, power) -> float:
        """泵：单向、无视压差、速率 PUMP_FLOW_RATE × 供电比例。"""
        if not self.pumps:
            return 0.0
        total = 0.0
        w, h = self.grid.w, self.grid.h
        for x, y, d in self.pumps:
            factor = (power.factor_at(x, y)
                      if hasattr(power, "factor_at")
                      else (power if isinstance(power, (int, float)) else 1.0))
            if factor <= 0.0:
                continue
            in_cell = ((x - C.DX[d]) % w, (y - C.DY[d]) % h)
            out_cell = ((x + C.DX[d]) % w, (y + C.DY[d]) % h)
            i_in = self.index.get(in_cell)
            i_out = self.index.get(out_cell)
            if i_in is None or i_out is None:
                continue
            src_amt = float(self.amt[i_in])
            if src_amt <= C.FLUID_EPS:
                continue
            src_f = int(self.fid[i_in])
            dst_f = int(self.fid[i_out])
            if dst_f != 0 and dst_f != src_f:
                continue   # 目标格装着别的液体：不混
            room = float(self.cap[i_out] - self.amt[i_out])
            if room <= C.FLUID_EPS:
                continue
            q = min(float(C.PUMP_FLOW_RATE) * dt * float(factor),
                    src_amt, room)
            if q <= 0.0:
                continue
            self.amt[i_in] = np.float32(src_amt - q)
            self.amt[i_out] = np.float32(self.amt[i_out] + q)
            if dst_f == 0:
                self.fid[i_out] = src_f
            total += q
        return total

    # ---------- 机器接口 ----------

    def cell_near(self, x: int, y: int, fid: int = -1):
        """机器格四邻里第一个合适液体格的下标；没有返回 None。

        fid >= 0 时只认"装着该液体"或"空"的格子（空格可以接新液体）。
        """
        self._ensure()
        w, h = self.grid.w, self.grid.h
        for d in range(4):
            j = self.index.get(((x + C.DX[d]) % w, (y + C.DY[d]) % h))
            if j is None:
                continue
            if fid < 0 or self.fid[j] == 0 or int(self.fid[j]) == fid:
                return j
        return None

    def pull(self, x: int, y: int, fid: int, amount: float) -> float:
        """机器从四邻抽液体：返回实际抽到的量。"""
        if amount <= 0.0:
            return 0.0
        self._ensure()
        j = self.cell_near(x, y, fid)
        if j is None or int(self.fid[j]) != fid:
            return 0.0
        got = min(float(amount), float(self.amt[j]))
        if got <= 0.0:
            return 0.0
        self.amt[j] = np.float32(self.amt[j] - got)
        return got

    def push(self, x: int, y: int, fid: int, amount: float) -> float:
        """机器往四邻排液体：返回实际排出的量（目标格装满/装别的液体就停）。"""
        if amount <= 0.0:
            return 0.0
        self._ensure()
        j = self.cell_near(x, y, fid)
        if j is None:
            return 0.0
        if int(self.fid[j]) not in (0, fid):
            return 0.0
        room = float(self.cap[j] - self.amt[j])
        got = min(float(amount), room)
        if got <= 0.0:
            return 0.0
        self.amt[j] = np.float32(self.amt[j] + got)
        if int(self.fid[j]) == 0:
            self.fid[j] = fid
        return got

    # ---------- 查询 / 调试 ----------

    def amount_at(self, x: int, y: int) -> float:
        self._ensure()
        j = self.index.get((int(x) % self.grid.w, int(y) % self.grid.h))
        return float(self.amt[j]) if j is not None else 0.0

    def fid_at(self, x: int, y: int) -> int:
        self._ensure()
        j = self.index.get((int(x) % self.grid.w, int(y) % self.grid.h))
        return int(self.fid[j]) if j is not None else 0

    def cap_at(self, x: int, y: int) -> float:
        self._ensure()
        j = self.index.get((int(x) % self.grid.w, int(y) % self.grid.h))
        return float(self.cap[j]) if j is not None else 0.0

    def amount_clear(self, x: int, y: int):
        """把某格液体清零（拆格前的"泼不完就丢"用）。"""
        self._ensure()
        j = self.index.get((int(x) % self.grid.w, int(y) % self.grid.h))
        if j is not None:
            self.amt[j] = 0.0
            self.fid[j] = 0

    def fill_at(self, x: int, y: int, fid: int, amount: float) -> float:
        """直接往某格灌液体（调试/测试/存档恢复用）。返回实际灌入量。"""
        self._ensure()
        j = self.index.get((int(x) % self.grid.w, int(y) % self.grid.h))
        if j is None:
            return 0.0
        if int(self.fid[j]) not in (0, fid):
            return 0.0
        room = float(self.cap[j] - self.amt[j])
        got = min(float(amount), room)
        if got <= 0.0:
            return 0.0
        self.amt[j] = np.float32(self.amt[j] + got)
        self.fid[j] = fid
        return got

    def total_of(self, fid: int) -> float:
        """全场某种液体的总量（HUD/自检）。"""
        self._ensure()
        if not len(self.cells):
            return 0.0
        return float(self.amt[self.fid == int(fid)].sum())

    def total_all(self) -> float:
        self._ensure()
        return float(self.amt.sum()) if len(self.cells) else 0.0

    def count_cells(self) -> int:
        self._ensure()
        return len(self.cells)

    def dump_cells(self) -> list[dict]:
        """存档：只存有液体的格。"""
        self._ensure()
        out = []
        for i, (x, y) in enumerate(self.cells):
            a = float(self.amt[i])
            if a > C.FLUID_EPS:
                out.append({"x": int(x), "y": int(y),
                            "f": int(self.fid[i]), "a": round(a, 3)})
        return out

    def load_cells(self, entries) -> None:
        """读档：先 ensure（把格表建好），再按坐标灌回去。"""
        self.rebuild()
        for e in entries or ():
            try:
                self.fill_at(int(e["x"]), int(e["y"]), int(e["f"]),
                             float(e["a"]))
            except (KeyError, TypeError, ValueError):
                continue
