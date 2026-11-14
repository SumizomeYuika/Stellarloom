#!/usr/bin/env python3
"""行星轨道自检（M6.31 真实开普勒参数）：开普勒方程 + 真实周期 + 1/r² 日照 + 存档。

跑法：python tools/_orbitcheck.py
不需要 pygame。
"""

from __future__ import annotations

import copy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.world import PlanetOrbit
from stellarloom.world import kepler


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def main():
    fails = []

    def t(ok, msg):
        print("    PASS" if ok else "    FAIL", msg)
        if not ok:
            fails.append(msg)

    # ---------- 0. 常量 ----------
    print("[0] 真实轨道常量:")
    t(C.SECONDS_PER_YEAR > 0, f"SECONDS_PER_YEAR={C.SECONDS_PER_YEAR} 必须 > 0")
    t(approx(C.PLANET_ORBIT_PERIOD, C.SECONDS_PER_YEAR),
      "PLANET_ORBIT_PERIOD = 地球基准年（兼容旧常量）")
    t(0.0 < C.PLANET_ECCENTRICITY < 1.0,
      f"PLANET_ECCENTRICITY={C.PLANET_ECCENTRICITY}（地球真实偏心率）")

    # ---------- 1. 开普勒第三定律：周期由半长轴决定 ----------
    print("[1] 开普勒第三定律（T=a^1.5）:")
    t(approx(kepler.period_seconds(1.0), 600.0),
      f"地球 a=1 AU → {kepler.period_seconds(1.0):.1f}s（游戏 1 年）")
    mars_t = kepler.period_seconds(1.52371)
    t(approx(mars_t, 1.52371 ** 1.5 * 600.0),
      f"火星 a=1.52371 AU → {mars_t:.1f}s = 1.8808 地球年")
    t(abs(kepler.period_days(1.0) - 365.256) < 0.01,
      f"真实周期：地球 {kepler.period_days(1.0):.1f} 地球日")
    t(abs(kepler.period_days(1.52371) - 686.98) < 0.05,
      f"真实周期：火星 {kepler.period_days(1.52371):.1f} 地球日（真实 686.98）")
    mer = kepler.period_days(0.38710)
    t(abs(mer - 87.97) < 0.1, f"真实周期：水星 {mer:.2f} 地球日（真实 87.97）")
    # 反推：由周期还原半长轴
    t(approx(kepler.semi_major_from_period(600.0), 1.0),
      "semi_major_from_period(600) ≈ 1 AU")

    # ---------- 2. 开普勒方程与椭圆几何 ----------
    print("[2] 开普勒方程 / 椭圆:")
    e = 0.3
    for M in (0.0, 45.0, 90.0, 180.0, 270.0):
        nu = kepler.true_anomaly(M, e)
        E = kepler.solve_kepler(math.radians(M), e)
        M2 = math.degrees(E - e * math.sin(E)) % 360.0
        t(approx(M2, M % 360.0, 1e-6),
          f"M={M:.0f}° → E→M 反算一致（{M2:.4f}）")
        t(approx(kepler.mean_anomaly_from_true(nu, e), M % 360.0, 1e-6),
          f"M={M:.0f}° → 真近点角 {nu:.2f}° 反解回 M")
    # 圆轨道：真近点角 = 平近点角
    t(approx(kepler.true_anomaly(123.0, 0.0), 123.0), "e=0 时 ν=M")
    # 椭圆半径：近日点 a(1-e)，远日点 a(1+e)
    r_peri = kepler.radius_au(1.0, e, 0.0)
    r_ap = kepler.radius_au(1.0, e, 180.0)
    t(approx(r_peri, 1.0 - e) and approx(r_ap, 1.0 + e),
      f"近日点 {r_peri:.3f} AU / 远日点 {r_ap:.3f} AU")
    # 地球真实偏心率下近日/远日
    rp = kepler.radius_au(1.0, 0.01671, 0.0)
    ra = kepler.radius_au(1.0, 0.01671, 180.0)
    t(approx(rp, 1.0 - 0.01671) and approx(ra, 1.0 + 0.01671),
      f"地球 近日 {rp:.4f} / 远日 {ra:.4f} AU")

    # ---------- 3. 公转推进（平近点角线性，真近点角变速） ----------
    print("[3] 公转推进:")
    p = PlanetOrbit(a_au=1.0, eccentricity=0.01671)
    print(f"    初始 ν={p.angle:.2f}° r={p.radius_au:.4f}AU "
          f"T={p.period:.0f}s")
    p.update(p.period / 4.0)
    t(approx(p.mean_angle, 90.0, 1e-6), f"1/4 圈后平近点角 {p.mean_angle:.2f}°")
    t(0.0 < p.phase < 0.3, f"phase={p.phase:.3f}")
    p.update(p.period)  # 再过一整圈
    t(approx(p.mean_angle, 90.0, 1e-6), "整圈后回到 90°（取模）")
    # 高偏心率：近日点附近真近点角推进快，远日点慢
    q = PlanetOrbit(mean_angle=350.0, a_au=1.0, eccentricity=0.3)
    q2 = PlanetOrbit(mean_angle=170.0, a_au=1.0, eccentricity=0.3)
    q.update(q.period / 20.0)     # 平近点角走 18°
    q2.update(q2.period / 20.0)
    t(abs(q.angle - 350.0) > abs(q2.angle - 170.0),
      f"近点推进快（350°→{q.angle:.1f}° vs 170°→{q2.angle:.1f}°）")
    t(approx(q.radius_au, kepler.radius_au(1.0, 0.3, q.angle), 1e-9),
      "radius_au 与真近点角一致")

    # ---------- 4. 日照 1/r² ----------
    print("[4] 日照（1/r²）:")
    f_mid = PlanetOrbit(a_au=1.0, eccentricity=0.0).solar_factor()
    t(approx(f_mid, 1.0), f"圆轨道 1 AU 日照 ×{f_mid:.3f}（地球基准 1.0）")
    home = PlanetOrbit(mean_angle=0.0, a_au=1.0, eccentricity=0.01671)
    home_ap = PlanetOrbit(mean_angle=180.0, a_au=1.0, eccentricity=0.01671)
    t(home.solar_factor() > home_ap.solar_factor(),
      f"近日点更亮 {home.solar_factor():.3f} > {home_ap.solar_factor():.3f}")
    t(approx(home.solar_factor(), (1 / home.radius_au) ** 2),
      "日照 = 1/r²")
    mars = PlanetOrbit(mean_angle=0.0, a_au=1.52371, eccentricity=0.09339)
    t(0.3 < mars.solar_factor() < 0.6,
      f"火星日照 ×{mars.solar_factor():.2f}（真实 1/1.52²≈0.43）")
    # 整个轨道范围内日照有起伏（不再近似）
    lo = hi = None
    mm = 0.0
    while mm < 360.0:
        f = PlanetOrbit(mean_angle=mm, a_au=1.52371, eccentricity=0.09339) \
            .solar_factor()
        lo = f if lo is None or f < lo else lo
        hi = f if hi is None or f > hi else hi
        mm += 10.0
    t(hi > lo * 1.3, f"火星日照起伏 {lo:.2f}~{hi:.2f}（>30%）")

    # ---------- 5. 存档往返 ----------
    print("[5] 存档往返:")
    p = PlanetOrbit(mean_angle=137.0, a_au=1.52371, eccentricity=0.09339,
                    arg_peri=40.0)
    d = p.dump()
    q = PlanetOrbit()
    q.load_from(copy.deepcopy(d))
    same = (approx(q.angle, p.angle) and approx(q.mean_angle, p.mean_angle)
            and approx(q.period, p.period) and approx(q.eccentricity, p.eccentricity)
            and approx(q.a_au, p.a_au) and approx(q.arg_peri, p.arg_peri))
    print(f"    ν {p.angle:.3f}→{q.angle:.3f}  M {p.mean_angle:.3f}→"
          f"{q.mean_angle:.3f}  a {q.a_au:.3f}  e {q.eccentricity:.4f}  "
          f"一致={same}")
    t(same, "真实轨道字段往返一致")
    t(approx(q.radius_au, p.radius_au), "读档后日心距一致")
    # 老档（只有 angle/period/ecc）：按周期反推半长轴，行为不变
    old = {"angle": 55.0, "period": 300.0, "eccentricity": 0.3}
    p3 = PlanetOrbit()
    p3.load_from(old)
    t(approx(p3.angle, 55.0, 1e-6) and approx(p3.period, 300.0)
      and approx(p3.a_au, kepler.semi_major_from_period(300.0)),
      f"老档兼容：a 由周期反推 {p3.a_au:.4f} AU")

    # ---------- 6. v8 老档迁移 ----------
    print("[6] v8 老档迁移:")
    from stellarloom.save.savefile import SAVE_VERSION, SaveManager
    old = copy.deepcopy({"version": 8, "grid": {}, "tech": {}, "power": {},
                         "camera": {}, "stats": {}})
    new = SaveManager()._migrate(old)
    worlds = new.get("worlds") or [{}]
    w0 = worlds[0] if isinstance(worlds, list) else worlds
    got = w0.get("planet", None)
    print(f"    v8 -> v{new['version']}  worlds[0].planet 段: {got}")
    t(new["version"] == SAVE_VERSION, "v8 迁移后版本号正确")
    t(got is not None, "v8 老档迁移补 planet 段")
    t(got is not None and approx(got.get("angle", -1), 0.0),
      "v8 老档迁移的 planet 真近点角为 0")
    t("tech" in new and "stats" in new, "v8 老档迁移保留顶层 tech/stats")

    print()
    if fails:
        for f in fails:
            print(f"!! FAIL {f}")
        print("FAIL 行星轨道自检未通过")
        return 1
    print("PASS 行星轨道自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
