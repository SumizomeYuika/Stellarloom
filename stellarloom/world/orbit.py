"""行星轨道（M6.31 真实参数版）：开普勒椭圆 + 真实周期 + 1/r² 日照。

设计：
- 每颗行星的轨道由真实参数决定：半长轴 a（AU）、偏心率 e、近点辐角。
  公转周期不再手填，按开普勒第三定律 T(年)=a^1.5 换算成游戏秒
  （1 地球年 = C.SECONDS_PER_YEAR 秒）。
- 行星在椭圆上按开普勒方程运动（近日点快、远日点慢），不再匀速转圈：
  平近点角 M 线性推进，解 E，再得真近点角 ν 与日心距 r。
- 日照 F ∝ 1/r²，以地球平均距离（1 AU）为 1.0；
  数值落地：PowerGrid 的太阳能发电乘 solar_factor()。
- 视觉落地：轨道图面板画真实椭圆轨道（近点辐角旋转）+ 行星在真近点角处。

存档：angle（真近点角，给老档/显示兼容）+ mean_angle（平近点角，真状态）
+ period + eccentricity + a_au + arg_peri。
"""

from __future__ import annotations

import math

from .. import config as C
from . import kepler


class PlanetOrbit:
    def __init__(self, angle: float = 0.0,
                 period: float | None = None,
                 eccentricity: float | None = None,
                 a_au: float | None = None,
                 arg_peri: float = 0.0,
                 mean_angle: float | None = None):
        """angle: 真近点角（度）；mean_angle: 平近点角（度，优先）。

        a_au 给了就按真实半长轴算周期；否则用 period（缺省读 config）反推 a。
        """
        self.eccentricity = (C.PLANET_ECCENTRICITY if eccentricity is None
                             else float(eccentricity))
        self.arg_peri = float(arg_peri) % 360.0
        if a_au is None:
            self.period = C.PLANET_ORBIT_PERIOD if period is None else float(period)
            self.a_au = kepler.semi_major_from_period(self.period)
        else:
            self.a_au = float(a_au)
            self.period = (kepler.period_seconds(self.a_au) if period is None
                           else float(period))
        if mean_angle is not None:
            self._M = float(mean_angle) % 360.0
        else:
            self._M = kepler.mean_anomaly_from_true(angle, self.eccentricity)
        self._refresh(self._M)

    def _refresh(self, mean_angle: float):
        self._M = mean_angle % 360.0
        self._nu = kepler.true_anomaly(self._M, self.eccentricity)
        self._r = kepler.radius_au(self.a_au, self.eccentricity, self._nu)

    # ---------- 状态 ----------

    @property
    def angle(self) -> float:
        """真近点角（度，0 = 近日点方向）。"""
        return self._nu

    @angle.setter
    def angle(self, deg: float):
        self._refresh(kepler.mean_anomaly_from_true(deg, self.eccentricity))

    @property
    def mean_angle(self) -> float:
        """平近点角（度）。"""
        return self._M

    @mean_angle.setter
    def mean_angle(self, deg: float):
        self._refresh(deg)

    @property
    def radius_au(self) -> float:
        """当前日心距（AU）。"""
        return self._r

    @property
    def phase(self) -> float:
        """轨道相位 0~1（按平近点角算，匀速）。"""
        return self._M / 360.0

    # ---------- 更新 ----------

    def update(self, dt: float):
        """公转推进 dt 秒：平近点角按 360/period 线性前进。"""
        if self.period > 0:
            self._refresh(self._M + 360.0 * dt / self.period)

    def angle_after(self, dt: float) -> float:
        """dt 秒后的真近点角（不推进自身，给窗口预测用）。"""
        if self.period <= 0:
            return self._nu
        M = self._M + 360.0 * dt / self.period
        return kepler.true_anomaly(M, self.eccentricity)

    # ---------- 行星工程（M6）：变轨 ----------

    def set_semi_major(self, a_au: float):
        """设置半长轴（AU）：周期按 T=a^1.5 重算，当前位置保持相位不变。"""
        self.a_au = max(0.05, float(a_au))
        self.period = kepler.period_seconds(self.a_au)
        self._refresh(self._M)

    def shift_phase(self, delta_deg: float):
        """平移轨道相位（度）：平近点角整体转一个角度，太阳位置立刻变。"""
        self._refresh(self._M + float(delta_deg))

    # ---------- 数值 ----------

    def solar_factor(self) -> float:
        """相对地球平均日照的倍率：1/r²（地球平均 = 1.0）。"""
        return kepler.solar_flux(None, self._r)

    def temperature_c(self) -> float:
        """平衡温度（°C）：T ∝ (L/r²)^0.25，地球 1 AU = 288 K ≈ 15°C。"""
        return C.ENGINE_TEMP_BASE_K * (1.0 / max(self._r, 1e-6)) ** 0.5 - 273.15

    def temperature_efficiency(self) -> float:
        """过热降效：太阳能效率，低于 35°C 为 1，每高 1°C -0.5%，下限 0.35。"""
        t = self.temperature_c()
        if t <= C.ENGINE_TEMP_SAFE_C:
            return 1.0
        eff = 1.0 - (t - C.ENGINE_TEMP_SAFE_C) / C.ENGINE_TEMP_PENALTY
        return max(C.ENGINE_TEMP_MIN_EFF, eff)

    def status_text(self) -> str:
        return (f"距恒星 {self._r:.2f} AU · 光照 ×{self.solar_factor():.2f}"
                f" · {self.temperature_c():.0f}°C")

    # ---------- 存档 ----------

    def dump(self) -> dict:
        return {
            "angle": self._nu,
            "mean_angle": self._M,
            "period": self.period,
            "eccentricity": self.eccentricity,
            "a_au": self.a_au,
            "arg_peri": self.arg_peri,
        }

    def load_from(self, data: dict):
        self.eccentricity = float(data.get("eccentricity",
                                           C.PLANET_ECCENTRICITY))
        self.arg_peri = float(data.get("arg_peri", 0.0)) % 360.0
        if "a_au" in data:
            self.a_au = float(data["a_au"])
            self.period = float(data.get("period",
                                         kepler.period_seconds(self.a_au)))
        else:
            # 老档（v12 及以前）没有 a_au：按周期反推半长轴，保持旧节奏
            self.period = float(data.get("period", C.PLANET_ORBIT_PERIOD))
            self.a_au = kepler.semi_major_from_period(self.period)
        if "angle" in data:
            # 真近点角是显示/存档的权威值：反解平近点角，避免 ecc 变化后失真
            self.angle = float(data["angle"])
        elif "mean_angle" in data:
            self._refresh(float(data["mean_angle"]))
