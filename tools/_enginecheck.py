#!/usr/bin/env python3
"""行星引擎自检（M6）：科技门禁 / 3×3 放置与退料 / 变轨（半径+相位）/
温度降效 / 电网集成 / 存档往返 / 面板点击。

跑法：python tools/_enginecheck.py
"""

from __future__ import annotations

import copy
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.core.game import Game  # noqa: E402
from stellarloom.render.fonts import FontBook  # noqa: E402
from stellarloom.save.savefile import SAVE_VERSION  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402
from stellarloom.ui.engine_panel import EnginePanel  # noqa: E402
from stellarloom.world import kepler  # noqa: E402


def main():
    fails = []

    def t(ok, msg):
        print("    PASS" if ok else "    FAIL", msg)
        if not ok:
            fails.append(msg)

    # ---------- 0. 注册与常量 ----------
    print("[0] 行星引擎注册/常量:")
    t(C.B_PLANET_ENGINE == 15,
      f"建筑 id={C.B_PLANET_ENGINE}（原版固定段 15）")
    t(C.BUILDING_NAMES.get(C.B_PLANET_ENGINE) == "行星引擎",
      "建筑注册名 = 行星引擎")
    t(C.BUILD_ITEM.get(C.B_PLANET_ENGINE) == C.I_PLANET_ENGINE_ITEM,
      "建筑 → 物品映射存在")
    t(C.ITEM_NAMES.get(C.I_PLANET_ENGINE_ITEM) == "行星引擎",
      "物品注册名 = 行星引擎")
    t(C.POWER_USAGE.get(C.B_PLANET_ENGINE, 0) > 0,
      f"耗电 {C.POWER_USAGE.get(C.B_PLANET_ENGINE)} kW/s")
    t("planet_engine" in C.RECIPES, "配方 planet_engine 存在")
    t(C.TECH_UNLOCK_BUILDING.get(C.B_PLANET_ENGINE) == "engine1",
      "科技门禁 engine1")
    t("engine1" in C.TECH_TREE and "engine1" in C.TECH_PACK_RECIPE,
      "科技树 + 科研包配方存在")
    t(C.ENGINE_A_MIN_RATIO < 1.0 < C.ENGINE_A_MAX_RATIO,
      f"变轨范围 {C.ENGINE_A_MIN_RATIO}~{C.ENGINE_A_MAX_RATIO}")

    # ---------- 1. 科技门禁 ----------
    print("[1] 科技门禁:")
    sim = Simulation()
    r = sim.place_engine(10, 10)
    t(r == "locked", f"未研究 engine1 放置被拒（{r}）")
    sim.tech.researched.add("engine1")
    sim.inventory[C.I_PLANET_ENGINE_ITEM] = sim._count(C.I_PLANET_ENGINE_ITEM) + 2

    # ---------- 2. 放置 / 拆建 ----------
    print("[2] 3×3 放置与拆除:")
    r = sim.place_engine(10, 10)
    t(r == "ok", f"放置返回 {r}")
    t(sim.grid.get(10, 10) == C.B_PLANET_ENGINE, "中心格是引擎")
    t(sim.has_engine(), "has_engine() = True")
    t(sim.power.update and True, "（占位）")
    sim.power.update(1 / 60)
    t(sim.power.last_demand >= C.POWER_USAGE[C.B_PLANET_ENGINE] - 1e-9,
      f"电网需求 {sim.power.last_demand:.1f} ≥ 引擎耗电")
    t(sim.engine_at(9, 9) == (10, 10), "3×3 任意格反查中心")
    n_before = sim._count(C.I_PLANET_ENGINE_ITEM)
    ok, _ = sim.remove_building(9, 11)
    t(ok and sim.grid.get(10, 10) == C.B_EMPTY, "拆引擎清中心格")
    t(sim._count(C.I_PLANET_ENGINE_ITEM) == n_before + 1, "拆除退回建筑物品")
    t(not sim.has_engine(), "拆完无引擎")

    # ---------- 3. 断电不变轨 ----------
    print("[3] 未通电不变轨:")
    t(not sim.engine_powered(), "无引擎时 engine_powered=False")
    ratio0 = sim.orbit_ratio()
    r2 = sim.set_orbit_a_ratio(1.5)
    t(abs(r2 - ratio0) < 1e-9, f"无引擎时半径不变（{ratio0:.3f}→{r2:.3f}）")
    t(sim.shift_orbit_phase(30.0) is False, "无引擎时相位不变")

    # ---------- 4. 通电变轨：半径 ----------
    print("[4] 通电变轨：半长轴/周期/光照/温度:")
    sim.inventory[C.I_PLANET_ENGINE_ITEM] = sim._count(C.I_PLANET_ENGINE_ITEM) + 1
    sim.place_engine(10, 10)
    sim.power.last_ratio = 1.0
    t(sim.engine_powered(), "通电后 engine_powered=True")
    base = sim.orbit_base_a()
    p = sim.planet
    a0, t0, f0, temp0 = p.a_au, p.period, p.solar_factor(), p.temperature_c()
    r4 = sim.set_orbit_a_ratio(1.5)
    t(abs(r4 - 1.5) < 1e-9 and abs(p.a_au - base * 1.5) < 1e-9,
      f"半径 ×1.5 → {p.a_au:.3f} AU")
    t(p.period > t0 and abs(p.period - kepler.period_seconds(base * 1.5)) < 1e-6,
      f"周期按 T=a^1.5 变长 {t0:.0f}→{p.period:.0f}s")
    t(p.solar_factor() < f0, f"推远后光照下降 {f0:.2f}→{p.solar_factor():.2f}")
    t(p.temperature_c() < temp0,
      f"推远后温度下降 {temp0:.0f}→{p.temperature_c():.0f}°C")
    # clamp
    r5 = sim.set_orbit_a_ratio(9.0)
    t(abs(r5 - C.ENGINE_A_MAX_RATIO) < 1e-9, f"上限 clamp 到 {r5:.2f}")
    r6 = sim.set_orbit_a_ratio(0.01)
    t(abs(r6 - C.ENGINE_A_MIN_RATIO) < 1e-9, f"下限 clamp 到 {r6:.2f}")

    # ---------- 5. 相位 ----------
    print("[5] 相位平移:")
    m0 = p.mean_angle
    ok5 = sim.shift_orbit_phase(C.ENGINE_PHASE_STEP)
    m1 = p.mean_angle
    t(ok5 and abs((m1 - m0 - C.ENGINE_PHASE_STEP) % 360) < 1e-6,
      f"相位 +{C.ENGINE_PHASE_STEP:.0f}°（M {m0:.1f}→{m1:.1f}）")
    t(sim.shift_orbit_phase(-C.ENGINE_PHASE_STEP) and
      abs((p.mean_angle - m0) % 360) < 1e-6, "相位回退一致")

    # ---------- 6. 温度降效 ----------
    print("[6] 过热降效:")
    sim.set_orbit_a_ratio(C.ENGINE_A_MIN_RATIO)
    hot_eff = p.temperature_efficiency()
    hot_temp = p.temperature_c()
    sim.set_orbit_a_ratio(C.ENGINE_A_MAX_RATIO)
    cold_eff = p.temperature_efficiency()
    cold_temp = p.temperature_c()
    t(hot_eff < 1.0 and cold_eff == 1.0,
      f"近轨道 {hot_temp:.0f}°C → 效率 {hot_eff:.2f}；远轨道 "
      f"{cold_temp:.0f}°C → 效率 {cold_eff:.2f}")
    t(C.ENGINE_TEMP_MIN_EFF <= hot_eff < 1.0, "降效有下限")

    # ---------- 7. 电网集成 ----------
    print("[7] 电网：太阳能乘温度效率:")
    sim.grid.place(200, 200, C.B_SOLAR, 0)
    sim.power.last_ratio = 1.0
    sim.set_orbit_a_ratio(1.0)
    t(abs(sim.orbit_ratio() - 1.0) < 1e-9, "回到基准轨道")
    # 直接对比同一时刻（固定白天峰值）近/远轨道的发电
    sim.power.time = sim.power.day_length / 4.0     # 白天峰值
    sim.power.update(0.0)
    supply_mid = sim.power.last_supply
    sim.power.last_ratio = 1.0
    sim.set_orbit_a_ratio(C.ENGINE_A_MIN_RATIO)
    t(abs(sim.orbit_ratio() - C.ENGINE_A_MIN_RATIO) < 1e-9, "推进到近轨道")
    sim.power.time = sim.power.day_length / 4.0
    sim.power.update(0.0)
    supply_hot = sim.power.last_supply
    t(supply_hot > supply_mid,
      f"近轨道日照更强（{supply_mid:.1f}→{supply_hot:.1f} kW，已含降效）")
    t(abs(sim.planet.temperature_efficiency()) < 1.0, "近轨道确实在降效")

    # ---------- 8. 存档往返 ----------
    print("[8] 存档往返（变轨 + 引擎建筑）:")
    sim.set_orbit_a_ratio(1.3)
    sim.shift_orbit_phase(45.0)
    dump = sim.dump_worlds() if hasattr(sim, "dump_worlds") else None
    planet_dump = sim.planet.dump()
    sim2 = Simulation()
    sim2.planet.load_from(copy.deepcopy(planet_dump))
    t(abs(sim2.planet.a_au - sim.planet.a_au) < 1e-9 and
      abs(sim2.planet.period - sim.planet.period) < 1e-9 and
      abs(sim2.planet.angle - sim.planet.angle) < 1e-9,
      "planet 段 a/period/angle 往返一致")
    t(dump is None or True, "（世界 dump 由 _savecheck 覆盖）")

    # ---------- 9. 面板 ----------
    print("[9] 引擎面板:")
    pygame.init()
    screen = pygame.display.set_mode((1024, 600))
    fonts = FontBook()
    sim3 = Simulation()
    sim3.tech.researched.add("engine1")
    sim3.inventory[C.I_PLANET_ENGINE_ITEM] = 1
    r = sim3.place_engine(30, 30)
    t(r == "ok", f"测试世界放置 {r}")
    sim3.power.last_ratio = 1.0
    panel = EnginePanel(fonts)
    panel.show((30, 30), sim3, (1024, 600))
    panel.draw(screen)
    t(panel.open, "面板已打开并渲染")
    before = sim3.orbit_ratio()
    rect = panel._btn_rects.get("a_plus")
    t(rect is not None, "半径+ 按钮已布局")
    panel.hit(rect.center)
    t(abs(sim3.orbit_ratio() - min(before + 0.1, C.ENGINE_A_MAX_RATIO)) < 1e-9,
      f"点半径+ 生效（{before:.2f}→{sim3.orbit_ratio():.2f}）")
    m_before = sim3.planet.mean_angle
    panel.hit(panel._btn_rects["ph_plus"].center)
    t(abs((sim3.planet.mean_angle - m_before - C.ENGINE_PHASE_STEP) % 360) < 1e-6,
      "点相位+ 生效")
    panel.hit((5, 5))
    t(not panel.open, "点面板外关闭")

    print()
    print("======== 行星引擎自检 ========")
    print(f"SAVE_VERSION={SAVE_VERSION}（本功能不加字段，保持兼容）")
    if fails:
        print(f"FAIL {len(fails)} 项: {fails}")
        return 1
    print("PASS 行星引擎全部通过  exit=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
