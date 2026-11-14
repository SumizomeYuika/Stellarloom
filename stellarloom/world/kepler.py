"""开普勒轨道力学（M6.31）：用真实行星参数算轨道、周期、日照。

真实太阳系数据（J2000，单位 AU / 年）：
  水星  a=0.38710  e=0.20563  T=0.2408
  金星  a=0.72333  e=0.00677  T=0.6152
  地球  a=1.00000  e=0.01671  T=1.0000
  火星  a=1.52371  e=0.09339  T=1.8808

公式（太阳质量下开普勒两大定律）：
- 第三定律：T(年) = a(AU)^1.5（周期由半长轴定，不再手填）
- 椭圆：r(ν) = a(1-e²)/(1+e·cosν)，ν = 真近点角
- 开普勒方程：M = E - e·sinE（M 平近点角），用牛顿法解 E
- 日照：F ∝ 1/r²，以地球平均距离（1 AU）为 1.0

游戏时间尺度：1 地球年 = C.SECONDS_PER_YEAR 秒（默认 600 秒 = 10 分钟）。
"""

from __future__ import annotations

import math

from .. import config as C


def solve_kepler(mean_anomaly_rad: float, e: float, iters: int = 8) -> float:
    """解开普勒方程 M = E - e·sinE，牛顿法。返回偏近点角 E（弧度）。"""
    M = mean_anomaly_rad
    E = M if e < 0.8 else math.pi
    for _ in range(iters):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        if abs(fp) < 1e-12:
            break
        d = f / fp
        E -= d
        if abs(d) < 1e-12:
            break
    return E


def true_anomaly(mean_anomaly_deg: float, e: float) -> float:
    """平近点角（度）→ 真近点角（度，0~360）。"""
    M = math.radians(mean_anomaly_deg % 360.0)
    E = solve_kepler(M, e)
    v = 2.0 * math.atan2(math.sqrt(1.0 + e) * math.sin(E / 2.0),
                         math.sqrt(1.0 - e) * math.cos(E / 2.0))
    return math.degrees(v) % 360.0


def mean_anomaly_from_true(true_anomaly_deg: float, e: float) -> float:
    """真近点角（度）→ 平近点角（度，0~360）。"""
    nu = math.radians(true_anomaly_deg % 360.0)
    E = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0),
                         math.sqrt(1.0 + e) * math.cos(nu / 2.0))
    M = E - e * math.sin(E)
    return math.degrees(M) % 360.0


def radius_au(a_au: float, e: float, true_anomaly_deg: float) -> float:
    """椭圆轨道上真近点角处的日心距（AU）。"""
    nu = math.radians(true_anomaly_deg)
    return a_au * (1.0 - e * e) / (1.0 + e * math.cos(nu))


def radius_at_mean(a_au: float, e: float, mean_anomaly_deg: float) -> float:
    """平近点角处的日心距：r = a(1 - e·cosE)。"""
    E = solve_kepler(math.radians(mean_anomaly_deg % 360.0), e)
    return a_au * (1.0 - e * math.cos(E))


def period_seconds(a_au: float,
                  seconds_per_year: float | None = None) -> float:
    """开普勒第三定律：T(年) = a^1.5 → 游戏秒。"""
    spy = C.SECONDS_PER_YEAR if seconds_per_year is None else seconds_per_year
    return (a_au ** 1.5) * spy


def period_days(a_au: float) -> float:
    """真实公转周期（地球日）：T(年) = a^1.5，1 年 = 365.256 地球日。"""
    return (a_au ** 1.5) * 365.256


def semi_major_from_period(period_s: float,
                           seconds_per_year: float | None = None) -> float:
    """由游戏周期反推半长轴（老存档兼容用）。"""
    spy = C.SECONDS_PER_YEAR if seconds_per_year is None else seconds_per_year
    if period_s <= 0 or spy <= 0:
        return 1.0
    return (period_s / spy) ** (2.0 / 3.0)


def solar_flux(a_au_unused: float | None, r_au: float) -> float:
    """相对地球平均日照的倍率：F = (1 AU / r)²，地球平均 = 1.0。"""
    if r_au <= 0:
        return 0.0
    return (1.0 / r_au) ** 2


def orbit_points(a_disp: float, e: float, arg_peri_deg: float,
                 n: int = 72) -> list[tuple[float, float]]:
    """采样椭圆轨道（显示用）。返回相对恒星中心的 (x, y)，y 轴向下（屏幕坐标）。

    a_disp：显示用的半长轴像素；e：偏心率；arg_peri_deg：近点辐角。
    """
    ap = math.radians(arg_peri_deg)
    ca, sa = math.cos(ap), math.sin(ap)
    pts = []
    for i in range(n):
        nu = 2.0 * math.pi * i / n
        r = a_disp * (1.0 - e * e) / (1.0 + e * math.cos(nu))
        x = r * math.cos(nu)
        y = r * math.sin(nu)
        pts.append((x * ca - y * sa, x * sa + y * ca))
    return pts
