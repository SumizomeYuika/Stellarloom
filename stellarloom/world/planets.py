"""行星定义（M5 星际骨架 + M6.31 真实轨道参数）：多颗可殖民行星的静态配置。

每颗行星 = 一个独立 WorldGrid + 全套网络 + 自己的 PlanetOrbit。
Tech（科技树）和 Dyson（戴森云，绕恒星）是整个星系共享的，不放这里。

M6.31：轨道参数不再是"手感数值"，而是真实太阳系数据——
- `a_au`：半长轴（AU）
- `eccentricity`：真实偏心率
- `arg_peri`：近点辐角（度，轨道朝向）
- 公转周期由开普勒第三定律 T(年)=a^1.5 自动算出（`orbit_period` 属性），
  游戏时间 1 地球年 = `C.SECONDS_PER_YEAR` 秒。
- 日照由真实日心距 r(ν) 算 F=1/r²（地球平均 = 1.0）。

生成：WorldGrid(seed=...) 按 seed 撒矿，副行星换 seed 就有不同矿脉分布。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import kepler


@dataclass(frozen=True)
class PlanetDef:
    pid: str               # 唯一 id（存档用）
    name: str              # 中文名
    color: tuple           # 轨道面板/顶栏的颜色
    desc: str              # 一句话描述
    seed: int              # WorldGrid 矿脉种子
    a_au: float            # 半长轴（AU，真实数据）
    eccentricity: float    # 偏心率（真实数据）
    arg_peri: float        # 近点辐角（度）
    angle0: float          # 开局平近点角（度）
    has_core: bool         # 出生点是否有核心（保证开局有电）
    ref: str = ""          # 参考的真实天体（文档/面板展示用）

    @property
    def orbit_period(self) -> float:
        """游戏内公转一圈的秒数（开普勒第三定律）。"""
        return kepler.period_seconds(self.a_au)

    @property
    def real_period_days(self) -> float:
        """真实公转周期（地球日），只用于展示。"""
        return kepler.period_days(self.a_au)


# 参考真实数据：地球 a=1.00000 AU e=0.01671 T=365.25d；
# 火星 a=1.52371 AU e=0.09339 T=686.98d。
PLANETS: list[PlanetDef] = [
    PlanetDef(
        pid="home", name="故乡星", color=(90, 180, 230),
        desc="你的出生地：铁铜石均衡，轨道接近正圆，昼夜平稳。",
        seed=42,
        a_au=1.00000, eccentricity=0.01671, arg_peri=0.0, angle0=0.0,
        has_core=True, ref="地球",
    ),
    PlanetDef(
        pid="ember", name="余烬星", color=(230, 120, 80),
        desc="殖民星：偏心的轨道让它离恒星忽远忽近，日照起伏剧烈。",
        seed=7,
        a_au=1.52371, eccentricity=0.09339, arg_peri=40.0, angle0=120.0,
        has_core=True, ref="火星",
    ),
]


def by_pid(pid: str) -> PlanetDef:
    for p in PLANETS:
        if p.pid == pid:
            return p
    return PLANETS[0]
