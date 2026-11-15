#!/usr/bin/env python3
"""格雷科技·星海扩展（gregtech_extra）自检。

跑法：python tools/_gt_extracheck.py

三种配置顺序验证（同进程内切换，依靠加载器“先卸载再加载”）：
A. 仅 gregtech_heavy（临时目录）—— 组合式 sync 在重工单独存在时正常
B. 仅 gregtech_extra（临时目录）—— 独立运行：矿脉/链条/聚变供电/多方块
C. 两个 mod 同时（真实 mods 目录）—— 晚加载升级、机器对象不抖、闭包可达
末尾：卸载还原 + 二次加载幂等 + 渲染
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.mod import ModManager  # noqa: E402
from stellarloom.production.machines import MachineNetwork  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402
from stellarloom.ui import touch_ui as TUI  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class FakeUI:
    def __init__(self):
        self.layout_calls = 0

    def _layout(self):
        self.layout_calls += 1


class FakeGame:
    def __init__(self):
        self.sim = Simulation()
        self.ui = FakeUI()
        self._toasts: list[str] = []

    def _toast_msg(self, text, secs=2.0):
        self._toasts.append(text)

    def _draw_ui(self):
        """jade（游戏自带悬停信息 mod）要求前端存在 _draw_ui 才挂钩。"""
        pass

    @property
    def machines(self):
        return self.sim.machines

    def _try_open_panel(self, gx, gy):
        """最小面板桩：熔炉/制造台面板能开 = 机器实例在网络里。"""
        return self.sim.machines.get_machine(gx, gy) is not None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODS_DIR = os.path.join(ROOT, "mods")


def _step(mgr, sim, seconds, dt=0.5):
    """推进 sim 并按游戏节奏转发 mod 的 on_step（聚变供电注电走这里）。"""
    n = int(seconds / dt) + 1
    for _ in range(n):
        sim.step(dt)
        mgr.step(dt)


def _single_config(*subdirs: str):
    """把若干个 mod 拷到临时目录做成隔离配置，返回 (tmpdir, mgr)。

    加载顺序由依赖拓扑序决定（gregtech_extra 声明依赖 gregtech_heavy，
    所以无论拷贝顺序如何，加载总是 重工 → 扩展）。"""
    tmp = tempfile.mkdtemp(prefix="gt2_")
    for sub in subdirs:
        shutil.copytree(os.path.join(MODS_DIR, sub), os.path.join(tmp, sub),
                        ignore=shutil.ignore_patterns("__pycache__"))
    return tmp, ModManager(FakeGame(), tmp)


def _planted_count(sim) -> int:
    n = 0
    for ws in sim.worlds:
        g = ws.grid
        n += int(((g.ore_type >= 4) & (g.ore_type <= 8)).sum())
    return n


def main() -> int:
    # =================================================================
    # A. 仅重工
    # =================================================================
    print("== A. 仅 gregtech_heavy ==")
    tmpA, mgrA = _single_config("gregtech_heavy")
    mgrA.load_all()
    check("A 加载成功", not mgrA.failed, str(mgrA.failed))
    import mod_gregtech_heavy_main as GT
    simA = mgrA.game.sim
    # M13.2：开局不再白送核心 → 测试产线必须自己供电
    simA.inventory[C.BUILD_ITEM[C.B_WIND]] = 8
    for dx in range(6):
        simA.place_building(C.B_WIND, 8 + dx, 8, 0)
    simA.power.rebuild()
    simA.power.update(0.1)
    check("A 测试供电（风力 240 kW）", simA.power.last_supply >= 200.0,
          f"supply={simA.power.last_supply:.1f}")
    simA.tech.researched.add("gt_ore")
    simA.inventory[GT.I_GT_CRUSHER] = 5
    check("A 放置粉碎机", simA.place_building(GT.B_GT_CRUSHER, 10, 10, 0) == "ok")
    mx = simA.machines.get_machine(10, 10)
    mx.set_recipe("gt_cr_iron")
    for _ in range(4):
        mx.feed(C.I_IRON_ORE)
    _step(mgrA, simA, 12.0)   # 1.0s/件 → 4 件
    check("A 粉碎链正常", mx.outputs.get(GT.I_CR_IRON, 0) >= 3, str(mx.outputs))
    check("A 机器对象不被 sync 清场",
          simA.machines.machines[(10, 10)] is mx, "对象被重建")
    # 原版熔炉在仅重工配置下也要能开面板（组合式 sync 不吞原版机器）
    vfa, vya = 80, 80
    check("A 放原版熔炉", simA.place_building(C.B_FURNACE, vfa, vya, 0) == "ok")
    check("A 熔炉机器实例进场", simA.machines.get_machine(vfa, vya) is not None)
    check("A 原版熔炉面板可开", mgrA.game._try_open_panel(vfa, vya))
    _step(mgrA, simA, 4.0)
    check("A 跑帧后原版熔炉仍在", simA.machines.get_machine(vfa, vya) is not None)
    mgrA.unload()

    # =================================================================
    # B. 依赖门禁 + 临时目录联装（重工 + 扩展，带用户配置覆盖）
    # =================================================================
    print("== B. 依赖声明 / 联装（临时目录） ==")
    # B0. 只装扩展 → 干净失败（体现 M6.29 依赖系统）
    tmpB0, mgrB0 = _single_config("gregtech_extra")
    mgrB0.load_all()
    dep_ok = any(fname == "gregtech_extra" and "缺少依赖" in err
                 for fname, err in mgrB0.failed)
    check("B 单独扩展无法加载（缺依赖 gregtech_heavy）", dep_ok,
          str(mgrB0.failed))
    check("B 缺依赖时其它状态不受污染", not mgrB0.ctxs, str(mgrB0.ctxs))
    shutil.rmtree(tmpB0, ignore_errors=True)

    # B1. 联装：先把用户配置写进 mods/config/，验证 M6.29 合并与可调速项
    tmpB, mgrB = _single_config("gregtech_extra", "gregtech_heavy")
    cfg_dir = os.path.join(tmpB, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "gregtech_extra.json"), "w",
              encoding="utf-8") as f:
        f.write('{"reactor_power": 99.0, "vein_counts": [60, 50, 40, 30, 20]}')
    mgrB.load_all()
    check("B 联装加载成功", not mgrB.failed, str(mgrB.failed))
    import mod_gregtech_extra_main as X
    check("B 配置合并：reactor_power 被用户覆盖", X.REACTOR_POWER == 99.0,
          str(X.REACTOR_POWER))
    check("B 配置合并：vein_counts 被用户覆盖",
          X.VEIN_COUNTS == (60, 50, 40, 30, 20), str(X.VEIN_COUNTS))
    check("B 配置合并：未覆盖项保留作者默认", X._CFG.get("toasts", True) is True)

    simB = mgrB.game.sim
    # M13.2：测试产线自己供电（同 A）
    simB.inventory[C.BUILD_ITEM[C.B_WIND]] = 8
    for dx in range(6):
        simB.place_building(C.B_WIND, 8 + dx, 8, 0)
    simB.power.rebuild()
    simB.power.update(0.1)
    check("B 测试供电（风力 240 kW）", simB.power.last_supply >= 200.0,
          f"supply={simB.power.last_supply:.1f}")
    simB.tech.researched.update(
        {"ex_mining", "ex_form", "ex_chem", "ex_alloy", "ex_reactor",
         "ex_accel", "ex_mb", "ex_mb2"})
    gB = simB.worlds[0].grid
    check("B 世界补种新矿脉", _planted_count(simB) > 0,
          f"新矿格数 {_planted_count(simB)}")
    # 找一格锡矿挖一下
    tin_cell, tin_item = None, None
    for y in range(0, gB.h, 7):
        for x in range(0, gB.w, 7):
            if gB.ore_type[y, x] == X.ORE_TIN:
                tin_cell, tin_item = (x, y), gB.mine(x, y)
                break
        if tin_cell:
            break
    check("B 挖锡矿给锡矿石", tin_cell is not None and tin_item == X.I_ORE_TIN,
          f"{tin_cell} -> {tin_item}")

    # 矿→锭→青铜→板（联装态：ex_bronze 已被 on_load 升级为吃重工铜锭）
    simB.inventory[X.I_ORE_TIN] = 3
    simB.inventory[GT.I_INGOT_COPPER] = 2
    simB.inventory[GT.I_GRAPHENE] = 2
    simB.inventory[X.I_MACH_CHEM] = 2
    simB.inventory[X.I_MACH_FORMER] = 2
    simB.inventory[X.I_MACH_ACCEL] = 1
    simB.inventory[X.I_MACH_REACTOR] = 1
    simB.inventory[X.I_LARGE_CORE_ITEM] = 1
    simB.inventory[X.I_BRICK_ITEM] = 10
    check("B 放化工厂", simB.place_building(X.B_X_CHEM, 20, 20, 0) == "ok")
    chem = simB.machines.get_machine(20, 20)
    chem.set_recipe("ex_bronze")
    chem.add_input(X.I_TIN_INGOT, 2)
    chem.add_input(GT.I_INGOT_COPPER, 2)
    _step(mgrB, simB, 4.0)   # 升级配方 1.2s/次 ×2 件
    check("B 青铜锭 4（升级配方）", chem.outputs.get(X.I_BRONZE_INGOT, 0) >= 4,
          str(chem.outputs))
    # 联装时 on_load 直接完成联动升级（依赖声明保证重工先加载）
    check("B 高段科技改吃结构矩阵",
          C.TECH_PACK_RECIPE.get("ex_alloy") == "science_structure",
          str(C.TECH_PACK_RECIPE.get("ex_alloy")))

    # M8 建筑注册表 + 原版熔炉/制造台面板回归（组合式 sync 不吞原版机器）
    from stellarloom.registry import BUILDING_REGISTRY
    for b in X.MACHINE_TYPES + X.RING_TYPES:
        name = BUILDING_REGISTRY.name_of(b)
        check(f"B 建筑 {b} 已在 M8 注册表", name == f"gregtech_extra:b{b}", name)
        check(f"B 注册表反查 {name} -> {b}",
              BUILDING_REGISTRY.id_of(name) == b,
              str(BUILDING_REGISTRY.name_to_id().get(name)))
        check(f"B 建筑物品联动 BUILD_ITEM[{b}]", C.BUILD_ITEM.get(b) is not None)
    vfx, vfy = 82, 82
    check("B 放原版熔炉", simB.place_building(C.B_FURNACE, vfx, vfy, 0) == "ok")
    check("B 熔炉机器实例进场", simB.machines.get_machine(vfx, vfy) is not None)
    check("B 原版熔炉面板可开", mgrB.game._try_open_panel(vfx, vfy))
    simB.inventory[C.BUILD_ITEM[C.B_ASSEMBLER]] = \
        simB.inventory.get(C.BUILD_ITEM[C.B_ASSEMBLER], 0) + 1
    check("B 放原版制造台",
          simB.place_building(C.B_ASSEMBLER, vfx + 2, vfy, 0) == "ok")
    check("B 制造台机器实例进场", simB.machines.get_machine(vfx + 2, vfy) is not None)
    check("B 原版制造台面板可开", mgrB.game._try_open_panel(vfx + 2, vfy))
    _step(mgrB, simB, 4.0)
    check("B 跑帧后原版机器仍在",
          simB.machines.get_machine(vfx, vfy) is not None
          and simB.machines.get_machine(vfx + 2, vfy) is not None)

    # 聚变供电：烧氘芯时向电网注电，燃料耗尽后回落
    simB.inventory[X.I_MACH_REACTOR] = 1
    check("B 放聚变反应堆", simB.place_building(X.B_X_REACTOR, 24, 20, 0) == "ok")
    rct = simB.machines.get_machine(24, 20)
    rct.set_recipe("ex_fuel")
    supply0 = simB.power.last_supply
    rct.add_input(X.I_DEUTERIUM, 1)
    _step(mgrB, simB, 12.0)
    check("B 聚变注电生效", simB.power.last_supply >= supply0 + 55,
          f"{supply0} -> {simB.power.last_supply}")
    _step(mgrB, simB, 30.0)   # 20s 烧完 1 根氘芯
    check("B 燃料耗尽后注电回落",
          simB.power.last_supply < supply0 + 10,
          f"{supply0} -> {simB.power.last_supply}")

    # 粒子加速器：等离子体 + 石墨烯（升级配方） → 反物质
    check("B 放粒子加速器", simB.place_building(X.B_X_ACCEL, 28, 20, 0) == "ok")
    acc = simB.machines.get_machine(28, 20)
    acc.set_recipe("ex_antimatter")
    acc.add_input(X.I_PLASMA, 4)
    acc.add_input(GT.I_GRAPHENE, 2)
    _step(mgrB, simB, 10.0)
    check("B 反物质 1（升级配方）", acc.outputs.get(X.I_ANTIMATTER, 0) == 1,
          str(acc.outputs))

    # 多方块：大型高炉（核心 + 8 耐热砖块 3×3 环）
    cx, cy = 60, 60
    check("B 放大型高炉核心",
          simB.place_building(X.B_X_LARGE_FURNACE, cx, cy, 0) == "ok")
    core = simB.machines.get_machine(cx, cy)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (dx, dy) == (0, 0):
                continue
            check(f"B 放耐热砖块({dx},{dy})",
                  simB.place_building(X.B_X_BRICK, cx + dx, cy + dy, 0) == "ok")
    simB.machines.sync()
    check("B 环完整 → 核心成型",
          X._MB_ACTIVE.get(id(core)) is True, str(X._MB_ACTIVE.get(id(core))))
    core2 = simB.machines.get_machine(cx, cy)
    core2.set_recipe("ex_mb_bronze_big")
    core2.add_input(X.I_TIN_INGOT, 3)
    core2.add_input(C.I_COPPER_ORE, 3)
    _step(mgrB, simB, 8.0)   # 1×6.0s
    check("B 大型高炉批量出青铜", core2.outputs.get(X.I_BRONZE_INGOT, 0) >= 6,
          str(core2.outputs))
    # 拆一块砖 → 停工
    simB.remove_building(cx, cy + 1)
    simB.machines.sync()
    check("B 环残缺 → 核心停工",
          X._MB_ACTIVE.get(id(core2)) is False,
          str(X._MB_ACTIVE.get(id(core2))))
    feed_keep = dict(core2.inputs)
    _step(mgrB, simB, 3.0)
    check("B 未成型不吞料", core2.inputs == feed_keep, str(core2.inputs))

    # 拆除退款（机器内原料退回）
    n_deut = simB.inventory.get(X.I_DEUTERIUM, 0)
    rct.add_input(X.I_DEUTERIUM, 1)
    ok, refund = simB.remove_building(24, 20)
    check("B 拆反应堆退还机器", ok and refund == X.B_X_REACTOR, f"{ok} {refund}")
    check("B 机内氘芯退回背包",
          simB.inventory.get(X.I_DEUTERIUM, 0) == n_deut + 1,
          f"{n_deut} -> {simB.inventory.get(X.I_DEUTERIUM, 0)}")
    mgrB.unload()

    # =================================================================
    # C. 两个 mod 同时（真实 mods 目录）
    # =================================================================
    print("== C. 重工 + 星海扩展 ==")
    gameC = FakeGame()
    mgrC = ModManager(gameC, MODS_DIR).load_all()
    check("C 双 mod 加载成功", not mgrC.failed, str(mgrC.failed))
    namesC = [c.name for c in mgrC.ctxs]
    check("C mod 清单", "gregtech_extra" in namesC and "gregtech_heavy" in namesC,
          str(namesC))
    cats = [n for n, _ in TUI.CATEGORIES]
    check("C 底栏三个新分类",
          "重工" in cats and "星际工业" in cats and "多方块" in cats, str(cats))

    simC = gameC.sim
    # M13.2：测试产线自己供电（同 A/B）
    simC.inventory[C.BUILD_ITEM[C.B_WIND]] = 8
    for dx in range(6):
        simC.place_building(C.B_WIND, 8 + dx, 8, 0)
    simC.power.rebuild()
    simC.power.update(0.1)
    check("C 测试供电（风力 240 kW）", simC.power.last_supply >= 200.0,
          f"supply={simC.power.last_supply:.1f}")
    simC.tech.researched.update(
        {"ex_mining", "ex_form", "ex_chem", "ex_alloy", "ex_reactor",
         "ex_accel", "ex_mb", "ex_mb2"})
    # 联动升级在 on_load 完成（依赖声明确保重工先加载），加载完即是升级态
    check("C 高段科技改吃结构矩阵", C.TECH_PACK_RECIPE.get("ex_reactor") == "science_structure",
          str(C.TECH_PACK_RECIPE.get("ex_reactor")))
    check("C 终局科技改吃量子矩阵", C.TECH_PACK_RECIPE.get("ex_accel") == "science_quantum",
          str(C.TECH_PACK_RECIPE.get("ex_accel")))
    check("C 氘芯配方升级用重工精料",
          1023 in C.RECIPES["ex_dusterium"][0], str(C.RECIPES["ex_dusterium"][0]))
    check("C 反应堆图纸配方升级用高级电路板",
          1020 in C.RECIPES["ex_mach_reactor"][0], str(C.RECIPES["ex_mach_reactor"][0]))

    # M7 注册表：固定数字注册 = 旧式兼容路径，名字可反查、数字在分配表里稳
    from stellarloom.registry import ITEM_REGISTRY
    check("C M7 注册表：重工物品名字可反查",
          ITEM_REGISTRY.id_of("gregtech_heavy:item1001") == 1001,
          str(ITEM_REGISTRY.name_of(1001)))
    check("C M7 注册表：扩展物品显示名挂上",
          C.ITEM_NAMES.get(X.I_ORE_TIN) == "锡矿石" and
          "gregtech_extra:item2001" in C.ITEM_IDS,
          f"{C.ITEM_NAMES.get(X.I_ORE_TIN)} / {C.ITEM_IDS.get('gregtech_extra:item2001')}")

    # M8 建筑注册表断言（真实目录下数字与名字双向可查）
    from stellarloom.registry import BUILDING_REGISTRY
    check("C M8 注册表：重工建筑名字可反查",
          BUILDING_REGISTRY.id_of("gregtech_heavy:b20") == 20
          and BUILDING_REGISTRY.id_of("gregtech_extra:b37") == 37,
          f"{BUILDING_REGISTRY.name_of(20)} / {BUILDING_REGISTRY.name_of(37)}")

    # 原版熔炉/制造台面板回归（真实目录，含 jade，正是用户报障配置）
    simC.inventory[C.BUILD_ITEM[C.B_ASSEMBLER]] = \
        simC.inventory.get(C.BUILD_ITEM[C.B_ASSEMBLER], 0) + 1
    check("C 放原版熔炉", simC.place_building(C.B_FURNACE, 80, 90, 0) == "ok")
    check("C 熔炉机器实例进场", simC.machines.get_machine(80, 90) is not None)
    check("C 原版熔炉面板可开", gameC._try_open_panel(80, 90))
    check("C 放原版制造台",
          simC.place_building(C.B_ASSEMBLER, 82, 90, 0) == "ok")
    check("C 制造台机器实例进场", simC.machines.get_machine(82, 90) is not None)
    check("C 原版制造台面板可开", gameC._try_open_panel(82, 90))

    # 机器对象身份稳定：疯狂 sync 不重建（先推进到“半成品”再 sync）
    simC.inventory[X.I_MACH_FORMER] = 2
    check("C 放金属成型机", simC.place_building(X.B_X_FORMER, 12, 12, 0) == "ok")
    fm = simC.machines.get_machine(12, 12)
    fm.set_recipe("ex_form_tin")
    fm.add_input(X.I_TIN_INGOT, 1)
    simC.machines.update(0.3, 1.0)   # 0.5s 配方做一半
    for _ in range(5):
        simC.machines.sync()
    check("C sync×5 后对象不重建", simC.machines.machines[(12, 12)] is fm,
          "对象被重建")
    check("C sync×5 后配方/进度保留",
          fm.recipe_id == "ex_form_tin" and abs(fm.progress - 0.3) < 1e-9,
          f"rid={fm.recipe_id} progress={fm.progress}")
    simC.machines.update(0.5, 1.0)   # 补足 0.8s → 出 1 件
    check("C sync 后仍能正常完工", fm.outputs.get(X.I_TIN_PLATE, 0) == 1,
          str(fm.outputs))

    # 重工机器在双 mod 下也正常（组合式 sync 不打架）
    simC.tech.researched.add("gt_ore")
    simC.inventory[GT.I_GT_CRUSHER] = 2
    check("C 放粉碎机", simC.place_building(GT.B_GT_CRUSHER, 16, 12, 0) == "ok")
    cr = simC.machines.get_machine(16, 12)
    cr.set_recipe("gt_cr_iron")
    for _ in range(4):
        cr.feed(C.I_IRON_ORE)
    _step(mgrC, simC, 12.0)   # 1.0s/件 → 4 件
    check("C 粉碎链正常", cr.outputs.get(GT.I_CR_IRON, 0) >= 3, str(cr.outputs))

    # 科技闭包可达（升级后状态；含全部 mod）
    print("== D. 科技闭包可达性（双 mod 升级后） ==")
    import stellarloom.sim as _sim_pkg
    have = set(C.STARTING_ITEMS) | set(C.ORE_TO_ITEM.values())
    reach_techs: set[str] = set()
    reach_buildings = {C.B_CORE}
    for _ in range(300):
        grew = False
        for rid, (ins, outs, _, allows) in C.RECIPES.items():
            if all(i in have for i in ins) and set(outs) - have:
                have |= set(outs)
                grew = True
        for btype, item in C.BUILD_ITEM.items():
            if btype in reach_buildings or item not in have:
                continue
            tid = C.TECH_UNLOCK_BUILDING.get(btype)
            if tid is not None and tid not in reach_techs:
                continue
            reach_buildings.add(btype)
            grew = True
        if C.B_LAB in reach_buildings:
            for tech_id, (_, _, prereqs, _) in C.TECH_TREE.items():
                if tech_id in reach_techs:
                    continue
                if not all(p in reach_techs for p in prereqs):
                    continue
                rid = C.TECH_PACK_RECIPE.get(tech_id)
                r = C.RECIPES.get(rid) if rid else None
                if r is None or not all(i in have for i in r[1]):
                    continue
                reach_techs.add(tech_id)
                grew = True
        if not grew:
            break
    stuck = [t for t in C.TECH_TREE if t not in reach_techs]
    check("全部科技可达（无开局死锁）", not stuck, f"卡死 {stuck}")
    check("星海扩展科技全可达",
          all(t in reach_techs for t in X.TECHS),
          f"卡死 {[t for t in X.TECHS if t not in reach_techs]}")
    check("终极物品曲率驱动器可产出", X.I_WARP_DRIVE in have, f"缺 {X.I_WARP_DRIVE}")
    check("两 mod 全部建筑可达",
          all(b in reach_buildings for b in (30, 31, 32, 33, 34, 35, 36, 37)
              + GT.GT_MACHINE_TYPES),
          str([b for b in (30, 31, 32, 33, 34, 35, 36, 37)
               + GT.GT_MACHINE_TYPES if b not in reach_buildings]))

    # 渲染
    print("== E. 渲染 ==")
    from stellarloom.render.layers import ChunkRenderer
    sE = Simulation()
    pool = sE.inventory
    sE.tech.researched.update({"ex_mining", "ex_form", "ex_chem", "ex_alloy",
                               "ex_reactor", "ex_accel", "ex_mb", "ex_mb2"})
    for i, bt in enumerate((31, 32, 33, 34, 35, 36, 37, 30, 35)):
        btype_item = C.BUILD_ITEM[bt]
        pool[btype_item] = 1
        sE.place_building(bt, 2 + i, 2, 0)
    cr = ChunkRenderer(sE.grid)
    surf = cr._get(0, 0, 24)
    check("E chunk 渲染含新建筑图案", surf is not None
          and surf.get_size() == (32 * 24, 32 * 24))
    surf2 = ChunkRenderer(sE.grid)._get(0, 0, 18)
    check("E 缩放下渲染正常", surf2 is not None and surf2.get_size() == (32 * 18, 32 * 18))

    # 卸载还原 + 幂等重载
    print("== F. 卸载 / 重载 ==")
    mgrC.unload()
    check("F 卸载后 ex_ 配方清空", not any(r.startswith("ex_") for r in C.RECIPES))
    check("F 卸载后 ex_ 科技清空",
          not any(t.startswith("ex_") for t in C.TECH_TREE))
    check("F 卸载后新矿表还原",
          all(v not in C.ORE_TO_ITEM.values() for v in (2001, 2002, 2003, 2004, 2005))
          and all(ot not in C.ORE_COLORS for ot in (4, 5, 6, 7, 8)),
          str(C.ORE_TO_ITEM))
    check("F 卸载后分类还原",
          all(n not in ("重工", "星际工业", "多方块") for n, _ in TUI.CATEGORIES))
    check("F 卸载后建筑表还原",
          all(C.BUILD_ITEM.get(b) is None for b in (30, 31, 32, 33, 34, 35, 36, 37)))
    check("F 卸载后 sync 还原原版", MachineNetwork.sync.__name__ == "sync")
    check("F 卸载后 place_building 还原",
          Simulation.place_building.__name__ == "place_building")

    mgrC.load_all()
    names2 = [c.name for c in mgrC.ctxs]
    check("F 二次加载成功", "gregtech_extra" in names2 and "gregtech_heavy" in names2,
          str(names2))
    check("F 二次加载后内容恢复",
          "science_structure" in C.RECIPES and "ex_fuel" in C.RECIPES
          and "ex_mb" in C.TECH_TREE
          and all(n in [x for x, _ in TUI.CATEGORIES]
                  for n in ("重工", "星际工业", "多方块")))
    mgrC.unload()

    shutil.rmtree(tmpA, ignore_errors=True)
    shutil.rmtree(tmpB, ignore_errors=True)

    print()
    if FAILS:
        print(f"FAIL {len(FAILS)} 项未通过: {FAILS}")
        return 1
    print("PASS 星海扩展自检全部通过（三配置）")
    return 0


if __name__ == "__main__":
    sys.exit(main())