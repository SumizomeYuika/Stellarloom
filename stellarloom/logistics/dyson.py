"""戴森云（M4）：太阳帆发射器 + 轨道帆群 + 发电。

设计要点：
- 发射器（B_EMITTER）是普通建筑，占一格，靠分拣器喂太阳帆进它的内置储存。
- 每 DYSON_LAUNCH_INTERVAL 秒消耗 1 片帆，把它打到某条轨道上。
- 轨道是极坐标环：每条轨道有容量上限，帆按角度均分铺满整圈。
- 帆群发电：总功率 = 帆数 × DYSON_SAIL_POWER × 太阳帆效率加成，
  由 PowerGrid 拿来当"无限上限"的补充供给（不占地面格子）。
- 太阳帆效率靠科技 sail1（+50%）。

轨道和帆数是全局状态（不属于某台发射器），所以放在 DysonNetwork 里，
发射器只负责"往里塞帆 + 定时打出去"。
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class Emitter:
    """太阳帆发射器：囤帆 + 定时发射。"""

    __slots__ = ("x", "y", "store", "timer", "launched")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.store: dict[int, int] = {}   # 这里只会存太阳帆
        self.timer = 0.0
        self.launched = 0                 # 累计打出去的帆数（统计用）

    # ---------- 容器接口（让 StoragePanel 能直接用） ----------

    def space(self, item: int) -> int:
        return C.DYSON_EMITTER_STORE_CAP - self.store.get(item, 0)

    def add_item(self, item: int, count: int) -> int:
        if item != C.I_SOLAR_SAIL:
            return 0
        n = min(count, self.space(item))
        if n > 0:
            self.store[item] = self.store.get(item, 0) + n
        return n

    def take_item(self, item: int, count: int | None = None) -> int:
        have = self.store.get(item, 0)
        if have <= 0:
            return 0
        n = have if count is None else min(have, count)
        left = have - n
        if left > 0:
            self.store[item] = left
        else:
            self.store.pop(item, None)
        return n

    def total(self) -> int:
        return sum(self.store.values())

    def feed(self, item: int) -> bool:
        """分拣器喂料：只收太阳帆。"""
        return self.add_item(item, 1) > 0

    def has_sail(self) -> bool:
        return self.store.get(C.I_SOLAR_SAIL, 0) > 0


class DysonNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.emitters: dict[tuple[int, int], Emitter] = {}
        # 每条轨道挂了多少片帆
        self.orbit_count: list[int] = [0] * C.DYSON_ORBITS
        # 每条轨道当前旋转角度（度，纯视觉）
        self.orbit_angle: list[float] = [0.0] * C.DYSON_ORBITS
        # M6.32：玩家在星系视图里点选的发射目标轨道（None = 自动选最空）
        self.target_orbit: int | None = None
        self._tech = None

    def bind(self, tech):
        self._tech = tech

    # ---------- 同步 ----------

    def sync(self):
        g = self.grid
        ys, xs = np.nonzero(g.building == C.B_EMITTER)
        wanted: set[tuple[int, int]] = set()
        for y, x in zip(ys.tolist(), xs.tolist()):
            wanted.add((x, y))
            if (x, y) not in self.emitters:
                self.emitters[(x, y)] = Emitter(x, y)
        for k in [k for k in self.emitters if k not in wanted]:
            del self.emitters[k]

    def get(self, x: int, y: int) -> Emitter | None:
        return self.emitters.get((x % self.grid.w, y % self.grid.h))

    # ---------- 轨道容量 ----------

    def unlocked_orbits(self) -> int:
        """dyson1 解锁内轨，dyson2 解锁另外两条。"""
        if self._tech is None:
            return C.DYSON_ORBITS
        if "dyson2" in self._tech.researched:
            return C.DYSON_ORBITS
        if "dyson1" in self._tech.researched:
            return 1
        return 0

    def cap_of(self, orbit: int) -> int:
        return C.DYSON_ORBIT_CAP[orbit] if 0 <= orbit < C.DYSON_ORBITS else 0

    def space_of(self, orbit: int) -> int:
        return max(0, self.cap_of(orbit) - self.orbit_count[orbit])

    def total_sails(self) -> int:
        return sum(self.orbit_count)

    def total_cap(self) -> int:
        n = self.unlocked_orbits()
        return sum(C.DYSON_ORBIT_CAP[:n])

    # ---------- 目标轨道（M6.32：星系视图里点轨道环指定） ----------

    def set_target_orbit(self, orbit: int | None) -> bool:
        """指定发射目标轨道；传 None 或重复点同一环 = 恢复自动。

        只接受已解锁轨道；返回是否改变。
        """
        if orbit is not None and not (0 <= orbit < self.unlocked_orbits()):
            return False
        if orbit == self.target_orbit:
            self.target_orbit = None
        else:
            self.target_orbit = orbit
        return True

    # ---------- 发射 ----------

    def _pick_orbit(self) -> int | None:
        """选目标轨道：玩家指定且有空间就照办，否则最空的已解锁轨道。"""
        tgt = self.target_orbit
        if tgt is not None and 0 <= tgt < self.unlocked_orbits() \
                and self.space_of(tgt) > 0:
            return tgt
        n = self.unlocked_orbits()
        best, best_space = None, 0
        for i in range(n):
            sp = self.space_of(i)
            if sp > best_space:
                best, best_space = i, sp
        return best

    def launch(self, count: int = 1) -> int:
        """往轨道打 count 片帆，返回实际打出去的数量。"""
        done = 0
        for _ in range(count):
            oi = self._pick_orbit()
            if oi is None:
                break
            self.orbit_count[oi] += 1
            done += 1
        return done

    # ---------- 发电 ----------

    def sail_efficiency(self) -> float:
        """太阳帆效率加成：sail1 科技 +50%。"""
        if self._tech is not None and "sail1" in self._tech.researched:
            return 1.5
        return 1.0

    def power_output(self) -> float:
        """戴森云总发电量。"""
        return self.total_sails() * C.DYSON_SAIL_POWER * self.sail_efficiency()

    # ---------- 更新 ----------

    def update(self, dt: float, power):
        """power 可以是全局倍率，也可以是 PowerGrid（发射器按所在电网取比例）。"""
        # 轨道自转（纯视觉）
        for i in range(C.DYSON_ORBITS):
            self.orbit_angle[i] = (
                self.orbit_angle[i] + C.DYSON_ROTATE_SPEED[i] * dt) % 360.0

        for e in self.emitters.values():
            if not e.has_sail():
                e.timer = 0.0
                continue
            sf = (float(power) if isinstance(power, (int, float))
                  else power.factor_at(e.x, e.y))
            e.timer += dt * sf
            if e.timer < C.DYSON_LAUNCH_INTERVAL:
                continue
            e.timer -= C.DYSON_LAUNCH_INTERVAL
            # 一次发射可以连打多片（DYSON_SAIL_PER_LAUNCH）
            want = min(C.DYSON_SAIL_PER_LAUNCH,
                       e.store.get(C.I_SOLAR_SAIL, 0))
            n = self.launch(want)
            if n > 0:
                e.take_item(C.I_SOLAR_SAIL, n)
                e.launched += n

    # ---------- 状态文本 ----------

    def status_text(self) -> str:
        if self.total_sails() <= 0:
            return ""
        return f"云 {self.total_sails()}帆 {self.power_output():.0f}kW"

    # ---------- 存档 ----------

    def dump(self) -> dict:
        return {
            "orbit_count": list(self.orbit_count),
            "orbit_angle": list(self.orbit_angle),
            "target_orbit": self.target_orbit,
            "emitters": [
                {"x": x, "y": y,
                 "store": {str(k): v for k, v in e.store.items()},
                 "timer": e.timer, "launched": e.launched}
                for (x, y), e in self.emitters.items()
            ],
        }

    def load_from(self, data: dict):
        oc = data.get("orbit_count") or []
        for i in range(min(len(oc), C.DYSON_ORBITS)):
            self.orbit_count[i] = int(oc[i])
        oa = data.get("orbit_angle") or []
        for i in range(min(len(oa), C.DYSON_ORBITS)):
            self.orbit_angle[i] = float(oa[i])
        tgt = data.get("target_orbit")
        self.target_orbit = (int(tgt) if tgt is not None
                             and 0 <= int(tgt) < C.DYSON_ORBITS else None)
        self.sync()
        for ed in data.get("emitters", []):
            e = self.get(ed["x"], ed["y"])
            if e is None:
                continue
            e.store = {int(k): v for k, v in ed.get("store", {}).items()}
            e.timer = ed.get("timer", 0.0)
            e.launched = ed.get("launched", 0)

    # ---------- 绘制辅助：算出每片帆的屏幕位置 ----------

    def sail_positions(self):
        """产出 (轨道索引, 角度) 列表，渲染层自己转屏幕坐标。"""
        out = []
        for i in range(C.DYSON_ORBITS):
            n = self.orbit_count[i]
            if n <= 0:
                continue
            base = self.orbit_angle[i]
            for k in range(n):
                out.append((i, (base + k * 360.0 / n) % 360.0))
        return out
