#!/usr/bin/env python3
"""格雷科技 mod 自检：加载、内容注册、模拟流程、卸载还原、二次加载。

跑法：python tools/_gt_modcheck.py

覆盖：
1. mod 干净加载（无 failed）
2. 物品/配方/科技/机器配置全部注册
3. 科技锁：未研究不能放新机器
4. 模拟流程：粉碎→离心（副产物）→高炉（钢锭+炉渣）→ 组装线 → 科研站制包
5. 拆除新机器全额退料（含机内储存）
6. 全局增益 mixin：传动学 IV（带速）、生产加速 I（机器提速）
7. 底栏「重工」分类进入 CATEGORIES
8. 手搓面板目录刷新（mod 配方可见）+ 手搓链
9. chunk 渲染（新机器图案不炸）
10. 卸载还原 + 二次加载幂等
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402  只 import 模块（Surface/draw 不需要 init display）

from stellarloom import config as C  # noqa: E402
from stellarloom.mod import ModManager  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402
from stellarloom.ui import touch_ui as TUI  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class FakeUI:
    """最小 ui 桩：on_load 会调 ui._layout()。"""
    def __init__(self):
        self.layout_calls = 0

    def _layout(self):
        self.layout_calls += 1


class FakeGame:
    """最小 Game 桩：mod 加载只用到 sim / _toast_msg / ui。"""
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


MODS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "mods")


def _step(sim, seconds, dt=0.5):
    """用小步长推进足够长时间（机器每个 update 最多完成一件，要多次 update）。"""
    n = int(seconds / dt) + 1
    for _ in range(n):
        sim.step(dt)


def main() -> int:
    game = FakeGame()
    mgr = ModManager(game, MODS_DIR).load_all()

    # ---------- 1. 干净加载 ----------
    print("== 1. 加载 ==")
    names = [c.name for c in mgr.ctxs]
    print(f"  已加载 mod: {names}")
    check("gregtech_heavy 加载成功", "gregtech_heavy" in names)
    # M15d：mod 出错即崩——能走到这行就说明"没抛异常"；failed 恒为空
    check("加载未抛异常且 failed 为空", mgr.failed == [], f"failed={mgr.failed}")
    ctx = next((c for c in mgr.ctxs if c.name == "gregtech_heavy"), None)
    if ctx is None:
        print("FAIL 拿不到 mod ctx，终止")
        return 1
    check("toast 已触发", bool(game._toasts), str(game._toasts))

    # 引加载器注册的那个模块实例（mixins/on_step 引用的是它的全局状态）
    import mod_gregtech_heavy_main as GT  # noqa: E402

    # ---------- 2. 内容注册 ----------
    print("== 2. 内容注册 ==")
    check("全部物品注册", all(i in C.ITEM_NAMES for i, _, _ in GT.ITEMS))
    check("全部配方注册", all(r in C.RECIPES for r in GT.RID.values()))
    check("全部科技注册", all(t in C.TECH_TREE for t, _ in GT.TECHS))
    for btype, name, item, color, usage, tech in GT.MACHINES:
        check(f"建筑 {name} 配置完备",
              C.BUILDING_NAMES.get(btype) == name
              and C.BUILD_ITEM.get(btype) == item
              and C.POWER_USAGE.get(btype) == usage
              and C.TECH_UNLOCK_BUILDING.get(btype) == tech)
    check("结构矩阵/量子矩阵进科研站制造列表",
          "science_structure" in C.LAB_PRODUCE_RECIPES
          and "science_quantum" in C.LAB_PRODUCE_RECIPES)
    check("新科研包进手搓黑名单",
          "science_structure" in C.HANDCRAFT_BLACKLIST
          and "science_quantum" in C.HANDCRAFT_BLACKLIST)
    check("吃包映射齐全", all(t in C.TECH_PACK_RECIPE for t, _ in GT.TECHS))
    check("四级科研包类型登记",
          set(C.TECH_PACK_ITEM.values()) >= {GT.I_PACK_STRUCTURE, GT.I_PACK_QUANTUM})

    # ---------- 2b. M8 建筑注册表 ----------
    print("== 2b. M8 建筑注册表 ==")
    from stellarloom.registry import BUILDING_REGISTRY
    for b in GT.GT_MACHINE_TYPES:
        name = BUILDING_REGISTRY.name_of(b)
        check(f"建筑 {b} 已在 M8 注册表", name == f"gregtech_heavy:b{b}", name)
        check(f"注册表反查 {name} -> {b}",
              BUILDING_REGISTRY.id_of(name) == b, str(BUILDING_REGISTRY.name_to_id().get(name)))
        check(f"建筑物品联动 BUILD_ITEM[{b}]",
              C.BUILD_ITEM.get(b) is not None)

    # ---------- 3. 底栏分类 ----------
    print("== 3. 底栏「重工」分类 ==")
    cat_names = [n for n, _ in TUI.CATEGORIES]
    check("重工分类已加入", "重工" in cat_names)
    heavy = dict(TUI.CATEGORIES).get("重工")
    check("重工分类含四台机器",
          heavy is not None and tuple(heavy) == GT.GT_MACHINE_TYPES)
    check("UI 布局已重算", game.ui.layout_calls >= 1)

    # ---------- 4. 科技锁 ----------
    print("== 4. 科技锁 ==")
    sim = game.sim
    x, y = 60, 60
    # M13.2：开局不再白送核心，测试机器要自己供电。这台风力足够整片测试
    # 机器（粉碎机 20 + 离心 20 + 高炉 + 组装线），且与下面所有机器距离都
    # 在并网范围内（无电力塔时全场一张网）。
    sim.inventory[C.BUILD_ITEM[C.B_WIND]] = 8
    for dx in range(6):
        sim.place_building(C.B_WIND, x + dx, y - 1, 0)
    sim.power.rebuild()
    sim.power.update(0.1)
    check("测试供电已铺（风力 6 台 = 240 kW）",
          sim.power.last_supply >= 200.0,
          f"supply={sim.power.last_supply:.1f}")
    # M14b：电网强制分区后测试机器未必全在风场 8 格内 —— 本文件验的是
    # mod 内容（机器/配方/科技锁），不测电网拓扑，用官方钩子直接给满电。
    sim.power.force_ratio = 1.0
    sim.inventory[GT.I_GT_CRUSHER] = 3
    sim.inventory[GT.I_GT_FURNACE] = 3
    r = sim.place_building(GT.B_GT_CRUSHER, x, y, 0)
    check("未研究科技不能放粉碎机", r == "locked", r)
    sim.tech.researched.add("gt_ore")
    r = sim.place_building(GT.B_GT_CRUSHER, x, y, 0)
    check("研究后能放粉碎机", r == "ok", r)
    check("放置扣掉建筑物品", sim.inventory.get(GT.I_GT_CRUSHER) == 2)

    # ---------- 5. 模拟流程 ----------
    print("== 5. 模拟流程 ==")
    m = sim.machines.get_machine(x, y)
    check("机器网络识别新机器", m is not None and m.btype == GT.B_GT_CRUSHER)
    m.set_recipe("gt_cr_iron")
    check("粉碎机配方可选", "gt_cr_iron" in m.available_recipes({"gt_ore"}))
    for _ in range(4):
        m.feed(C.I_IRON_ORE)
    _step(sim, 8)   # 8s：4×1.0s 粉碎
    check("粉碎矿石产出 4", m.outputs.get(GT.I_CR_IRON, 0) == 4, str(m.outputs))

    # 离心机：粉碎铁矿石 → 洗净铁矿石 + 硫粉
    sim.tech.researched.add("gt_cent")
    cx, cy = x + 2, y
    sim.inventory[GT.I_GT_CENTRI] = 2
    check("研究后能放离心机", sim.place_building(GT.B_GT_CENTRI, cx, cy, 0) == "ok")
    cent = sim.machines.get_machine(cx, cy)
    cent.set_recipe("gt_wash_iron")
    for _ in range(3):
        cent.feed(GT.I_CR_IRON)
    _step(sim, 8)   # 3×2.0s
    check("离心机洗净+硫粉副产物",
          cent.outputs.get(GT.I_WS_IRON, 0) == 3
          and cent.outputs.get(GT.I_SULFUR, 0) == 3, str(cent.outputs))

    # 高炉：石矿 → 焦炭；铁锭+焦炭 → 钢锭 + 炉渣
    sim.tech.researched.add("gt_blast")
    fx, fy = x + 4, y
    sim.inventory[GT.I_GT_FURNACE] = 3
    check("研究后能放高炉", sim.place_building(GT.B_GT_FURNACE, fx, fy, 0) == "ok")
    bf = sim.machines.get_machine(fx, fy)
    bf.set_recipe("gt_coke")
    for _ in range(2):
        bf.feed(C.I_STONE)
    _step(sim, 5)   # 2×1.5s 焦炭
    check("高炉产焦炭 2", bf.outputs.get(GT.I_COKE, 0) == 2, str(bf.outputs))
    bf.set_recipe("gt_steel")
    for _ in range(2):
        bf.feed(GT.I_INGOT_IRON)
        bf.feed(GT.I_COKE)
    _step(sim, 8)   # 2×3.0s 炼钢
    check("钢锭+炉渣副产物",
          bf.outputs.get(GT.I_INGOT_STEEL, 0) == 2
          and bf.outputs.get(GT.I_SLAG, 0) == 2, str(bf.outputs))

    # 组装线：处理器单元
    sim.tech.researched.update({"gt_motor", "gt_elec", "gt_mach2"})
    ax, ay = x + 6, y
    sim.inventory[GT.I_GT_ASSEMBLY] = 2
    check("研究后能放组装线", sim.place_building(GT.B_GT_ASSEMBLY, ax, ay, 0) == "ok")
    al = sim.machines.get_machine(ax, ay)
    al.set_recipe("gt_processor_unit")
    for _ in range(2):
        al.feed(GT.I_PROCESSOR)
        al.feed(GT.I_PROCESSOR)
        al.feed(GT.I_ADV_CIRCUIT)
        al.feed(GT.I_MOTOR)
    _step(sim, 12)   # 2×5.0s
    check("组装线产处理器单元 2",
          al.outputs.get(GT.I_PROCESSOR_UNIT, 0) == 2, str(al.outputs))

    # 科研站制造模式：结构矩阵（三级包）
    labx, laby = x + 3, y + 2
    sim.inventory[C.I_LAB_ITEM] = 2
    check("能放科研站", sim.place_building(C.B_LAB, labx, laby, 0) == "ok")
    sim.labs.sync()   # 科研站在下一次 step 的 belts 重建里才 sync（与游戏内行为一致）
    lab = sim.labs.get_lab(labx, laby)
    sim.labs.set_mode(labx, laby, C.LAB_MODE_PRODUCE)
    sim.labs.set_recipe(labx, laby, "science_structure")
    check("科研站可选结构矩阵配方", lab["recipe"] == "science_structure")
    lab["inputs"][C.I_CIRCUIT] = 4
    lab["inputs"][C.I_MAGNET] = 4
    lab["inputs"][C.I_GRAIN] = 4
    _step(sim, 10)   # 1×6.0s
    check("科研站造出结构矩阵", lab["outputs"].get(GT.I_PACK_STRUCTURE, 0) == 1,
          str(lab["outputs"]))

    # ---------- 6. 拆除退款（含机内储存） ----------
    print("== 6. 拆除退款 ==")
    before = dict(sim.inventory)
    feed_before = sim.machines.get_machine(x, y).outputs.get(GT.I_CR_IRON, 0)
    ok, refund = sim.remove_building(x, y)
    check("拆除粉碎机成功", ok and refund == GT.B_GT_CRUSHER)
    check("机内产物退回背包",
          sim.inventory.get(GT.I_CR_IRON, 0) == before.get(GT.I_CR_IRON, 0) + feed_before)
    check("建筑物品退回",
          sim.inventory.get(GT.I_GT_CRUSHER, 0) == before.get(GT.I_GT_CRUSHER, 0) + 1)
    check("机器网络已清理", sim.machines.get_machine(x, y) is None)

    # ---------- 7. 全局增益 mixin ----------
    print("== 7. 全局增益 ==")
    bsm = sim.tech.belt_speed_multiplier()
    check("未研究传动学 IV 带速不变", bsm == 1.0, str(bsm))
    sim.tech.researched.add("gt_belt4")
    bsm2 = sim.tech.belt_speed_multiplier()
    check("传动学 IV 带速 ×1.25", abs(bsm2 - 1.25) < 1e-9, str(bsm2))

    for fn in ctx._step_fns:
        fn(0.016)
    check("无 gt_speed4 时不加速", GT._MACHINE_SPEED == 1.0, str(GT._MACHINE_SPEED))
    sim.tech.researched.add("gt_speed4")
    for fn in ctx._step_fns:
        fn(0.016)
    check("on_step 刷新机器提速缓存", GT._MACHINE_SPEED == 1.25, str(GT._MACHINE_SPEED))

    # 机器更新提速：1s 配方，dt=0.8 × 1.25 = 1.0 ≥ dur，应当完成
    m2 = sim.machines.get_machine(cx, cy)
    m2.set_recipe("gt_cr_iron")
    m2.feed(C.I_IRON_ORE)
    sim.machines.update(0.8, 1.0)
    check("生产加速 I 下 0.8s 干完 1s 活",
          m2.outputs.get(GT.I_CR_IRON, 0) == 1, str(m2.outputs))

    # ---------- 8. 手搓面板目录刷新 + 手搓链 ----------
    print("== 8. 手搓 ==")
    import stellarloom.ui.craft_panel as cp
    obj = types.SimpleNamespace(_catalog={"old": "x"}, sel_item=999999,
                                queue=types.SimpleNamespace(inv={}), inv={},
                                rect=pygame.Rect(0, 0, 440, 480))
    wrapped_show = cp.CraftPanel.show
    # 注意：after 包装器对调用方透明，仍按原签名 show(screen_size, inventory) 调用
    wrapped_show(obj, (800, 600), {})
    check("mod 配方进入手搓目录", GT.I_CR_IRON in obj._catalog
          and obj._catalog.get(GT.I_CR_IRON) == "gt_cr_iron")
    check("失效选中项被清空", obj.sel_item is None)

    artisan = Simulation()
    artisan.inventory.clear()
    artisan.inventory[C.I_IRON_ORE] = 3
    n = artisan.do_craft("gt_cr_iron", 3)
    check("手搓排队成功", n == 3, str(n))
    for _ in range(3):
        artisan.step(2.6)   # 手搓 2.5s/件
    check("手搓出粉碎铁矿石 3", artisan.inventory.get(GT.I_CR_IRON, 0) == 3,
          str(artisan.inventory))

    # ---------- 9. 渲染 ----------
    print("== 9. 渲染 ==")
    from stellarloom.render.layers import ChunkRenderer
    s2 = Simulation()
    s2.inventory[GT.I_GT_CRUSHER] = 1
    s2.tech.researched.add("gt_ore")
    s2.place_building(GT.B_GT_CRUSHER, 2, 2, 0)
    s2.place_building(GT.B_GT_FURNACE, 3, 2, 0)
    s2.place_building(GT.B_GT_CENTRI, 4, 2, 0)
    s2.place_building(GT.B_GT_ASSEMBLY, 5, 2, 0)
    cr = ChunkRenderer(s2.grid)
    surf = cr._get(0, 0, 24)
    check("chunk 渲染含新机器图案", surf is not None
          and surf.get_size() == (32 * 24, 32 * 24))
    surf2 = ChunkRenderer(s2.grid)._get(0, 0, 18)
    check("缩放下渲染正常", surf2 is not None and surf2.get_size() == (32 * 18, 32 * 18))

    # ---------- 9b. 原版熔炉/制造台面板回归（组合式 sync 不吞原版机器） ----------
    print("== 9b. 原版熔炉、制造台面板回归 ==")
    sim = game.sim
    vfx, vfy = 70, 70
    check("放原版熔炉", sim.place_building(C.B_FURNACE, vfx, vfy, 0) == "ok")
    check("熔炉机器实例进场", sim.machines.get_machine(vfx, vfy) is not None)
    check("原版熔炉面板可开", game._try_open_panel(vfx, vfy))
    vax, vay = vfx + 2, vfy
    sim.inventory[C.BUILD_ITEM[C.B_ASSEMBLER]] = \
        sim.inventory.get(C.BUILD_ITEM[C.B_ASSEMBLER], 0) + 1
    check("放原版制造台", sim.place_building(C.B_ASSEMBLER, vax, vay, 0) == "ok")
    check("制造台机器实例进场", sim.machines.get_machine(vax, vay) is not None)
    check("原版制造台面板可开", game._try_open_panel(vax, vay))
    _step(sim, 4)
    check("跑帧后原版熔炉仍在", sim.machines.get_machine(vfx, vfy) is not None)
    check("跑帧后原版制造台仍在", sim.machines.get_machine(vax, vay) is not None)
    check("组合式 sync 不移除原版机器",
          len(sim.machines.machines) >= 2, str(sorted(sim.machines.machines.keys())))

    # ---------- 10. 科技闭包可达（防完美死锁，算法同 tools/_startcheck.py） ----------
    print("== 10. 科技闭包可达性 ==")
    have = set(C.STARTING_ITEMS) | set(C.ORE_TO_ITEM.values())
    reach_techs: set[str] = set()
    reach_buildings = {C.B_CORE}
    for _ in range(200):
        grew = False
        for rid, (ins, outs, _, allows) in C.RECIPES.items():
            if all(i in have for i in ins):
                if set(outs) - have:
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
    check("mod 全部科技可达",
          all(t in reach_techs for t, _ in GT.TECHS),
          f"卡死 {[t for t, _ in GT.TECHS if t not in reach_techs]}")
    check("终极物品星织引擎可产出", GT.I_STELLAR_ENGINE in have,
          f"缺 {GT.I_STELLAR_ENGINE}")
    check("全部建筑可达",
          all(b in reach_buildings for b in GT.GT_MACHINE_TYPES),
          str([b for b in GT.GT_MACHINE_TYPES if b not in reach_buildings]))

    # ---------- 11. 卸载还原 + 二次加载幂等 ----------
    print("== 11. 卸载 / 重载 ==")
    mgr.unload()
    check("卸载后 mod 配方清空", not any(r in C.RECIPES for r in GT.RID.values()))
    check("卸载后 mod 科技清空", not any(t in C.TECH_TREE for t, _ in GT.TECHS))
    check("卸载后重工分类移除", "重工" not in [n for n, _ in TUI.CATEGORIES])
    check("卸载后建筑表还原",
          all(C.BUILD_ITEM.get(b) is None for b in GT.GT_MACHINE_TYPES))
    check("卸载后科研站列表还原",
          C.LAB_PRODUCE_RECIPES == ("science_blue", "science_red"))
    check("卸载后 mixin 还原",
          Simulation.place_building.__name__ == "place_building"
          and Simulation.remove_building.__name__ == "remove_building")
    check("卸载后原版熔炉仍在", sim.machines.get_machine(vfx, vfy) is not None)
    check("卸载后原版制造台仍在", sim.machines.get_machine(vax, vay) is not None)

    mgr.load_all()
    names2 = [c.name for c in mgr.ctxs]
    check("二次加载成功", "gregtech_heavy" in names2)
    check("二次加载后内容恢复",
          all(r in C.RECIPES for r in GT.RID.values())
          and all(t in C.TECH_TREE for t, _ in GT.TECHS)
          and "重工" in [n for n, _ in TUI.CATEGORIES])

    print()
    if FAILS:
        print(f"FAIL {len(FAILS)} 项未通过: {FAILS}")
        return 1
    print("PASS 格雷科技 mod 自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())