#!/usr/bin/env python3
"""真电网自检（M9）：分区连通、独立供电比、per-网机器速度、kW/MW、存档。

跑法：python tools/_powercheck.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C  # noqa: E402
from stellarloom.power.grid_power import fmt_power  # noqa: E402
from stellarloom.save.savefile import SaveManager  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402


def find_empty(sim, start=(40, 40)):
    g = sim.grid
    for y in range(start[1], g.h):
        for x in range(start[0], g.w):
            if g.can_place(x, y):
                return (x, y)
    raise RuntimeError("找不到空格")


class FakeDyson:
    def __init__(self, out):
        self._out = out

    def power_output(self):
        return self._out


def main():
    fails = []

    def t(ok, msg):
        print("    PASS" if ok else "    FAIL", msg)
        if not ok:
            fails.append(msg)

    def fresh():
        sim = Simulation()
        sim.power.time = 0.0
        return sim

    # ---------- 1. 单位与格式 ----------
    print("[1] 真实单位（kW）:")
    t(C.POWER_USAGE[C.B_ASSEMBLER] == 40.0, "制造台 40 kW")
    t(C.POWER_GEN[C.B_SOLAR] == 60.0, "太阳能 60 kW")
    t(C.POWER_GEN.get(C.B_CORE) == 160.0, "核心 160 kW（仅旧档兼容发电）")
    t(fmt_power(40) == "40 kW" and fmt_power(1500) == "1.50 MW",
      f"格式化 {fmt_power(40)} / {fmt_power(1500)}")

    # ---------- 2. 没有电力塔也照样分区（M14b：废除全球一张网的兼容） ----------
    print("[2] 无塔也按 8 格分区:")
    sim = fresh()
    ax, ay = find_empty(sim, (60, 60))
    sim.grid.place(ax, ay, C.B_ASSEMBLER)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(not hasattr(sim.power, "_legacy") or not sim.power._legacy,
      "不再有 legacy 兼容分支")
    # 孤零零一台制造台：自己一张网、没发电 → 0（不再白蹭全球比例）
    t(sim.power.factor_at(ax, ay) == 0.0,
      f"孤立耗电网络没有电 {sim.power.factor_at(ax, ay):.2f}")
    # 旁边 3 格放一台风机（8 格内）→ 自动并网，不需要电力塔
    bx, by = ax + 3, ay
    sim.grid.place(bx, by, C.B_WIND)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(sim.power.factor_at(ax, ay) >= 0.99,
      f"3 格外的风机自动并网 → {sim.power.factor_at(ax, ay):.2f}")
    # 超过 8 格 → 自动分成两张网
    cx, cy = find_empty(sim, (ax + 30, ay))
    sim.grid.place(cx, cy, C.B_ASSEMBLER)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(sim.power.factor_at(cx, cy) == 0.0,
      f"30 格外的制造台另成一网且缺电 {sim.power.factor_at(cx, cy):.2f}")
    t(sim.power.net_count >= 2, f"自动分成 {sim.power.net_count} 张网")
    t(sim.power.starved_nets() >= 1, "starved_nets 能报出缺电网")

    # ---------- 3. 有塔：两张互不相连的网 ----------
    print("[3] 分区：两张网互不借电:")
    sim = fresh()
    (x1, y1) = find_empty(sim, (40, 40))
    # A 网：电力塔 + 风力 + 制造台（都在 8 格内）
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.grid.place(x1 + 3, y1, C.B_WIND)
    sim.grid.place(x1 + 6, y1, C.B_ASSEMBLER)
    # B 网：远处的塔 + 制造台（同网，但没有发电）
    (x2, y2) = find_empty(sim, (200, 200))
    sim.grid.place(x2, y2, C.B_POWER_POLE)
    sim.grid.place(x2 + 3, y2, C.B_ASSEMBLER)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(sim.power.net_count >= 2, f"分成 {sim.power.net_count} 张网（含出生核心）")
    fa = sim.power.factor_at(x1 + 6, y1)
    fb = sim.power.factor_at(x2 + 3, y2)
    t(fa >= 0.99, f"A 网有风发电 → {fa:.2f}")
    t(fb == 0.0, f"B 网没发电 → {fb:.2f}（不被 A 借电）")
    t(sim.power._cell_net[(x1, y1)] != sim.power._cell_net[(x2, y2)],
      "A/B 在两张不同的网上")
    n_before = sim.power.net_count

    # ---------- 4. 把 B 挪到 A 旁边：并成一张网 ----------
    print("[4] 塔接力并网:")
    sim.grid.remove(x2, y2)
    sim.grid.remove(x2 + 3, y2)
    by = y1 + 6
    sim.grid.place(x1, by, C.B_POWER_POLE)
    sim.grid.place(x1 + 3, by, C.B_WIND)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(sim.power.net_count == n_before - 1,
      f"网数 {n_before} → {sim.power.net_count}")
    t(sim.power._cell_net[(x1, by)] == sim.power._cell_net[(x1, y1)],
      "新塔与 A 网连通")

    # ---------- 5. 戴森云按需求摊派 ----------
    print("[5] 戴森云摊派:")
    sim = fresh()
    (x1, y1) = find_empty(sim, (40, 40))
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.grid.place(x1 + 6, y1, C.B_ASSEMBLER)     # 40 kW
    (x2, y2) = find_empty(sim, (200, 200))
    sim.grid.place(x2, y2, C.B_POWER_POLE)
    sim.grid.place(x2 + 6, y2, C.B_ASSEMBLER)     # 40 kW
    sim.power.dyson = FakeDyson(400.0)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(sim.power.factor_at(x1 + 6, y1) >= 0.99
      and sim.power.factor_at(x2 + 6, y2) >= 0.99,
      f"两网都拿到分摊：{sim.power.factor_at(x1 + 6, y1):.2f}/"
      f"{sim.power.factor_at(x2 + 6, y2):.2f}")

    # ---------- 6. 分拣器（叠加层）也耗电 ----------
    print("[6] 分拣器计入需求:")
    sim = fresh()
    (x1, y1) = find_empty(sim, (40, 40))
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.power.rebuild()
    sim.power.update(0.1)
    d0 = sim.power.last_demand
    sim.grid.place_overlay(x1 + 2, y1, C.B_INSERTER)
    sim.power.rebuild()
    sim.power.update(0.1)
    t(abs(sim.power.last_demand - d0 - C.POWER_USAGE[C.B_INSERTER]) < 1e-6,
      f"需求 {d0:.0f} → {sim.power.last_demand:.0f} kW")

    # ---------- 7. 机器按各自电网变速 ----------
    print("[7] 每台机器用自己的电网比例:")
    sim = fresh()
    sim.inventory.clear()
    (x1, y1) = find_empty(sim, (40, 40))
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.grid.place(x1 + 3, y1, C.B_WIND)
    sim.grid.place(x1 + 6, y1, C.B_ASSEMBLER)
    (x2, y2) = find_empty(sim, (200, 200))
    sim.grid.place(x2, y2, C.B_POWER_POLE)
    sim.grid.place(x2 + 3, y2, C.B_ASSEMBLER)     # 没电
    sim.grid.belts_changed()
    sim.power.rebuild()
    sim.machines.sync()
    sim.power.update(0.0)
    ma = sim.machines.get_machine(x1 + 6, y1)
    mb = sim.machines.get_machine(x2 + 3, y2)
    rid = "gear" if "gear" in C.RECIPES else next(iter(C.RECIPES))
    for m in (ma, mb):
        m.set_recipe(rid)
        m.inputs = dict(m.need)
        m.outputs.clear()
        m.progress = 0.0
    sim.machines.update(0.3, sim.power)
    t(ma.progress > 0.2, f"有电制造台推进 {ma.progress:.2f}")
    t(mb.progress == 0.0, f"没电制造台不动 {mb.progress:.2f}")

    # ---------- 8. mod 旧单位换算 ----------
    print("[8] mod 旧单位 ×20:")
    sim = fresh()
    mod_bt = 120
    C.POWER_USAGE[mod_bt] = 5.0       # 旧单位 → 100 kW
    try:
        (x1, y1) = find_empty(sim, (40, 40))
        sim.grid.place(x1, y1, C.B_POWER_POLE)
        sim.grid.place(x1 + 3, y1, mod_bt)
        sim.power.rebuild()
        sim.power.update(0.1)
        t(abs(sim.power.last_demand - 100.0) < 1e-6,
          f"mod 5 旧单位 → {sim.power.last_demand:.0f} kW")
    finally:
        C.POWER_USAGE.pop(mod_bt, None)

    # ---------- 9. 存档往返 ----------
    print("[9] 存档往返:")
    sim = fresh()
    (x1, y1) = find_empty(sim, (70, 70))
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.grid.place(x1 + 3, y1, C.B_WIND)
    sim.grid.place(x1 + 6, y1, C.B_ASSEMBLER)
    tmp = tempfile.mkdtemp(prefix="slm_pow_")
    sm = SaveManager(tmp)
    sim.saves = sm
    sm.save(sim, "p.slm")
    s2 = Simulation()
    s2.saves = sm
    ok = sm.load(s2, "p.slm")
    s2.power.rebuild()
    s2.power.update(0.1)
    t(ok and s2.power.factor_at(x1 + 6, y1) >= 0.99,
      f"读档后电网因子 {s2.power.factor_at(x1 + 6, y1):.2f}")
    t(s2.grid.get(x1, y1) == C.B_POWER_POLE, "电力塔存档保留")

    # ---------- 10. HUD 文本 ----------
    print("[10] HUD 文本:")
    sim = fresh()
    (x1, y1) = find_empty(sim, (40, 40))
    sim.grid.place(x1, y1, C.B_POWER_POLE)
    sim.grid.place(x1 + 3, y1, C.B_WIND)
    sim.power.rebuild()
    sim.power.update(0.1)
    txt = sim.power.status_text()
    t("kW" in txt or "MW" in txt, f"status_text = {txt}")

    print()
    print("======== 真电网自检 ========")
    if fails:
        print(f"FAIL {len(fails)} 项: {fails}")
        return 1
    print("PASS 真电网全部通过  exit=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
