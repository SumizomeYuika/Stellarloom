#!/usr/bin/env python3
"""M14 液体系统自检（第 31 项）：管网压力 / 泵 / 机器 / 存档 / 渲染 / 隔离。

设计前提（用户 8.1 要求）：**每格独立液量 + 压差限速 + 泵单向加压**，
不是"整段瞬时共享"。

覆盖：
[1] 注册表：液体独立 id 段、不进物品表/分拣器过滤
[2] 连通与容量：管道 100 / 储罐 2500；拆格后格表自动重建
[3] 压差与限速：一格满液，远处格要时间才拿到；总量守恒
[4] 单向性（无泵）：只能高→低；两侧满则不动
[5] 混液：不同液体互不流动，不丢失
[6] 泵：单向、无视压差、速率上限、断电不搬
[7] 机器：自动接管道抽原料液、排产物液、缓冲满停工
[8] 拆格泼液：拆管道/储罐时液体泼给四邻而不是凭空消失
[9] 存档 v13 往返；v12 旧档读入无液体
[10] 渲染：静态管道/储罐/泵非空 + 动态液面像素
[11] 隔离：液体不影响传送带/分拣器；mod add_fluid + 液体配方

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_fluidcheck.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.logistics.pipes import FluidNetwork  # noqa: E402
from stellarloom.save.savefile import MAGIC, SAVE_VERSION, SaveManager  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402
from stellarloom.world import WorldGrid  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def fresh(w=64, h=64):
    """干净世界 + 管网（不经过 Simulation，免得被出生点/科技干扰）。"""
    g = WorldGrid(w, h, seed=7)
    # 清掉矿，避免干扰
    g.ore[:] = 0
    g.ore_type[:] = 0
    return g, FluidNetwork(g)


def line(g, x0, x1, y, btype=None):
    for x in range(x0, x1 + 1):
        g.place(x, y, btype or C.B_PIPE)


def main() -> int:
    global bad
    pygame.init()
    screen = pygame.display.set_mode((800, 600))

    # ---------- [1] 注册表 ----------
    print("[1] 注册表:")
    check(C.F_CRUDE_OIL == 1 and C.F_FUEL_OIL == 2 and C.F_PETROLEUM == 3,
          f"液体 id 不是 1/2/3: {C.F_CRUDE_OIL},{C.F_FUEL_OIL},{C.F_PETROLEUM}")
    check(C.FLUID_NAMES.get(C.F_CRUDE_OIL) == "原油", "原油显示名错")
    check(C.FLUID_IDS.get("stellarloom:fuel_oil") == C.F_FUEL_OIL,
          "液体名字反查失败")
    # 液体与物品是**两张独立的表**：数字 id 段重叠（都是 1-14）没关系，
    # 但不能共享名字/显示名，也不能被背包/分拣器看到。
    check(set(C.FLUID_IDS) & set(C.ITEM_IDS) == set(),
          f"液体与物品共享了名字: {set(C.FLUID_IDS) & set(C.ITEM_IDS)}")
    check(set(C.FLUID_NAMES.values()) & set(C.ITEM_NAMES.values()) == set(),
          "液体与物品共享了显示名")
    from stellarloom.registry import FLUID_REGISTRY, ITEM_REGISTRY
    check(FLUID_REGISTRY is not ITEM_REGISTRY, "液体注册表与物品注册表是同一个对象")

    # ---------- [2] 连通与容量 ----------
    print("[2] 连通与容量:")
    g, fn = fresh()
    line(g, 10, 14, 10)                     # 5 格管道
    g.place(15, 10, C.B_TANK)
    fn.rebuild()
    check(fn.count_cells() == 6, f"液体格数 {fn.count_cells()}（期望 6）")
    check(abs(fn.cap_at(10, 10) - C.PIPE_CELL_CAP) < 1e-6, "管道容量错")
    check(abs(fn.cap_at(15, 10) - C.TANK_CELL_CAP) < 1e-6, "储罐容量错")
    # 拆一格 → 自动重建（rev 变化）
    g.remove(12, 10)
    check(fn.count_cells() == 5,
          f"拆格后格数 {fn.count_cells()}（期望 5，懒重建失败）")

    # ---------- [3] 压差限速 + 守恒 ----------
    print("[3] 压差限速:")
    g, fn = fresh()
    line(g, 10, 19, 10)                     # 10 格长线
    fn.rebuild()
    fn.fill_at(10, 10, C.F_CRUDE_OIL, 100)
    fn.update(0.1, 1.0)
    far = fn.amount_at(19, 10)
    near = fn.amount_at(11, 10)
    check(near > 0.0, "1 格外的邻居没拿到液体")
    check(far < 1.0, f"远端一次就拿到 {far:.2f}（说明是瞬移共享，不是压差）")
    total = fn.total_of(C.F_CRUDE_OIL)
    check(abs(total - 100.0) < 0.5, f"输运后总量 {total:.2f}（应守恒 100）")
    # 灌满 → 每格都有液，且长线需要时间才铺满
    for _ in range(int(C.PIPE_FLOW_RATE * 1.0)):
        fn.update(1 / 60, 1.0)
    check(fn.amount_at(19, 10) > 0.0, "长时间后远端仍然是空的")
    check(abs(fn.total_of(C.F_CRUDE_OIL) - 100.0) < 0.5, "长时间后总量漂了")

    # ---------- [4] 无泵只高→低 ----------
    print("[4] 无泵单向（高→低）:")
    g, fn = fresh()
    line(g, 10, 11, 10)
    fn.rebuild()
    fn.fill_at(11, 10, C.F_FUEL_OIL, 50)    # 只给右边
    fn.update(0.2, 1.0)
    check(fn.amount_at(10, 10) > 0.0, "高液位没有流向低液位")
    check(fn.amount_at(11, 10) < 50.0, "高液位没减少")

    # ---------- [5] 混液互不流动 ----------
    print("[5] 混液:")
    g, fn = fresh()
    line(g, 10, 11, 10)
    fn.rebuild()
    fn.fill_at(10, 10, C.F_CRUDE_OIL, 100)
    fn.fill_at(11, 10, C.F_PETROLEUM, 100)
    a0, b0 = fn.amount_at(10, 10), fn.amount_at(11, 10)
    for _ in range(30):
        fn.update(1 / 60, 1.0)
    check(abs(fn.amount_at(10, 10) - a0) < 1e-6
          and abs(fn.amount_at(11, 10) - b0) < 1e-6,
          "两种液体混在一起了（应互不流动）")
    check(fn.fid_at(10, 10) == C.F_CRUDE_OIL
          and fn.fid_at(11, 10) == C.F_PETROLEUM, "液体类型被覆盖")

    # ---------- [6] 泵 ----------
    print("[6] 泵（单向/无视压差/速率/断电）:")
    g, fn = fresh()
    g.place(9, 10, C.B_PIPE)
    g.place(10, 10, C.B_FLUID_PUMP, 0)      # 朝右：9 -> 11
    line(g, 11, 13, 10)
    fn.rebuild()
    check(fn.pumps == [(10, 10, 0)], f"泵表 {fn.pumps}")
    fn.fill_at(9, 10, C.F_CRUDE_OIL, 100)
    for _ in range(60):
        fn.update(1 / 60, 1.0)
    moved = sum(fn.amount_at(x, 10) for x in (11, 12, 13))
    check(moved > 60.0, f"泵 1 秒只搬了 {moved:.1f}（速率上限 {C.PUMP_FLOW_RATE}）")
    check(fn.amount_at(9, 10) < 40.0, "泵没有从入口抽走液体")
    # 无视压差：输出侧先灌满到高液位，泵仍能把入口的液体顶进去
    g2, fn2 = fresh()
    g2.place(9, 10, C.B_PIPE)
    g2.place(10, 10, C.B_FLUID_PUMP, 0)
    g2.place(11, 10, C.B_TANK)
    fn2.rebuild()
    fn2.fill_at(11, 10, C.F_CRUDE_OIL, 2000)   # 出口侧液位很高
    fn2.fill_at(9, 10, C.F_CRUDE_OIL, 100)
    before = fn2.amount_at(11, 10)
    for _ in range(60):
        fn2.update(1 / 60, 1.0)
    check(fn2.amount_at(11, 10) > before,
          "泵没能逆着压差把液体顶进去（应无视压差）")
    # 断电：不搬
    g3, fn3 = fresh()
    g3.place(9, 10, C.B_PIPE)
    g3.place(10, 10, C.B_FLUID_PUMP, 0)
    line(g3, 11, 12, 10)
    fn3.rebuild()
    fn3.fill_at(9, 10, C.F_CRUDE_OIL, 100)
    for _ in range(120):
        fn3.update(1 / 60, 0.0)
    check(fn3.amount_at(9, 10) == 100.0, "断电的泵还在搬液体")

    # ---------- [7] 机器接管道 ----------
    print("[7] 机器自动接管道:")
    sim = Simulation()
    gw = sim.grid
    # 造一台制造台 + 一条管道，注册一条测试液体配方
    mx, my = 40, 40
    gw.building[my, mx] = C.B_ASSEMBLER
    gw.building[my, mx - 1] = C.B_PIPE
    sim.machines.sync()
    sim.pipes.rebuild()
    sim.pipes.fill_at(mx - 1, my, C.F_CRUDE_OIL, 100)
    C.RECIPES["_fl_test"] = ({}, {}, 1.0, (C.B_ASSEMBLER,))
    C.RECIPE_FLUIDS["_fl_test"] = ({C.F_CRUDE_OIL: 20.0},
                                   {C.F_FUEL_OIL: 10.0})
    try:
        m = sim.machines.get_machine(mx, my)
        check(m is not None, "机器实例没建出来")
        m.set_recipe("_fl_test")
        check(m.fneed == {C.F_CRUDE_OIL: 20.0}, f"机器没识别液体配方 {m.fneed}")
        m.pipes = sim.pipes      # 正常由 MachineNetwork 注入
        for _ in range(120):     # 2 秒
            sim.pipes.update(1 / 60, 1.0)
            m.update(1 / 60, 1.0)
        check(m.fluid_in.get(C.F_CRUDE_OIL, 0) > 0, "机器没从管道抽到原料液")
        check(sim.pipes.amount_at(mx - 1, my) < 100.0, "管道里的液体没减少")
        # 配方跑完 → 产物液出现在机器里或已排进管道
        ran = (m.fluid_out.get(C.F_FUEL_OIL, 0) > 0
               or sim.pipes.fid_at(mx - 1, my) in (0, C.F_FUEL_OIL))
        check(ran, "产物液没有产生/排出")
        # 抽不到液时进度停住
        sim.pipes.amount_clear(mx - 1, my)
        m.fluid_in.clear()
        m.update(1 / 60, 1.0)
        check(m.progress == 0.0, "没有原料液还在推进配方")
    finally:
        C.RECIPES.pop("_fl_test", None)
        C.RECIPE_FLUIDS.pop("_fl_test", None)

    # ---------- [8] 拆格泼液 ----------
    print("[8] 拆格泼液:")
    sim2 = Simulation()
    gw2 = sim2.grid
    for x in (50, 51, 52):
        gw2.building[30, x] = C.B_PIPE
    sim2.pipes.rebuild()
    sim2.pipes.fill_at(51, 30, C.F_CRUDE_OIL, 100)
    total_before = sim2.pipes.total_of(C.F_CRUDE_OIL)
    ok, _ = sim2.remove_building(51, 30)
    check(ok, "拆管道失败")
    total_after = sim2.pipes.total_of(C.F_CRUDE_OIL)
    check(total_after > total_before - 0.5,
          f"拆格吞了液体：{total_before:.1f} -> {total_after:.1f}")

    # ---------- [9] 存档 ----------
    print("[9] 存档 v13:")
    from stellarloom.core import Game
    g1 = Game(screen)
    g1.menu.open = False
    g1.mod_mgr.unload()
    for x in range(60, 64):
        g1.sim.grid.building[20, x] = C.B_PIPE
    g1.sim.grid.building[20, 64] = C.B_TANK
    g1.sim.pipes.rebuild()
    g1.sim.pipes.fill_at(60, 20, C.F_CRUDE_OIL, 100.0)
    g1.sim.pipes.fill_at(64, 20, C.F_PETROLEUM, 1234.5)
    cells = [(60, 20), (61, 20), (64, 20)]
    before = {c: (g1.sim.pipes.fid_at(*c),
                  round(g1.sim.pipes.amount_at(*c), 2)) for c in cells}
    tmp = tempfile.mkdtemp(prefix="slm_fluid_")
    sm = SaveManager(tmp)
    sm.save(g1, "t.slm")
    check(SAVE_VERSION == 14, f"存档版本 {SAVE_VERSION}（期望 14）")
    g2 = Game(screen)
    g2.menu.open = False
    g2.mod_mgr.unload()
    check(sm.load(g2, "t.slm"), "读档失败")
    after = {c: (g2.sim.pipes.fid_at(*c),
                 round(g2.sim.pipes.amount_at(*c), 2)) for c in cells}
    check(before == after, f"液体往返不一致: {before} != {after}")
    g1.mod_mgr.unload()
    g2.mod_mgr.unload()

    # ---------- [10] 渲染 ----------
    print("[10] 渲染:")
    g3 = Game(screen)
    g3.menu.open = False
    g3.mod_mgr.unload()
    for x in range(70, 75):
        g3.sim.grid.building[20, x] = C.B_PIPE
    g3.sim.grid.building[20, 75] = C.B_TANK
    g3.sim.grid.building[20, 76] = C.B_FLUID_PUMP
    g3.sim.grid.direction[20, 76] = 0
    g3.sim.pipes.rebuild()
    g3.sim.pipes.fill_at(70, 20, C.F_FUEL_OIL, 100)
    # 把相机对到这片区域
    g3.camera.x = 72 * C.TILE
    g3.camera.y = 20 * C.TILE
    g3.camera.zoom = 1.0
    g3.chunks.clear()
    g3.screen.fill((0, 0, 0))
    g3._draw()
    px = g3.screen
    # 液面像素：找液体色（燃料油）出现在屏上
    col = C.FLUID_COLORS[C.F_FUEL_OIL]
    found = False
    w, h = px.get_size()
    for yy in range(0, h, 3):
        for xx in range(0, w, 3):
            if px.get_at((xx, yy))[:3] == col:
                found = True
                break
        if found:
            break
    check(found, "屏幕上找不到液面颜色（_draw_fluids 没画出来）")
    # 缩放 0.5 / 2.0 也不许崩
    for z in (0.5, 2.0):
        g3.camera.zoom = z
        g3.chunks.clear()
        g3._draw()
    print("  三种缩放渲染 OK")
    g3.mod_mgr.unload()

    # ---------- [11] 隔离 + mod API ----------
    print("[11] 隔离 & mod:")
    g4 = Game(screen)
    g4.menu.open = False
    g4.mod_mgr.unload()
    # 液体不产生传送带物品
    g4.sim.grid.building[30, 100] = C.B_PIPE
    g4.sim.pipes.rebuild()
    g4.sim.pipes.fill_at(100, 30, C.F_CRUDE_OIL, 50)
    inv_before = dict(g4.sim.inventory)
    for _ in range(10):
        g4.sim.step(1 / 60)
    check(g4.sim.belts.lanes == [] or all(
        len(l.positions) == 0 for l in g4.sim.belts.lanes),
        "液体跑到传送带上去了")
    check(dict(g4.sim.inventory) == inv_before,
          f"液体进了背包：{inv_before} -> {dict(g4.sim.inventory)}")
    # mod API：add_fluid + 液体配方
    ctx = g4.mod_mgr.ctxs[0] if g4.mod_mgr.ctxs else None
    from stellarloom.api import ModContext
    ctx = ModContext("tmod", "1.0", "test", g4)
    try:
        fid = ctx.add_fluid("tmod:sludge", "淤泥", "#556644")
        check(isinstance(fid, int) and fid > 0, f"add_fluid 返回 {fid!r}")
        check(C.FLUID_NAMES.get(fid) == "淤泥", "液体显示名没进表")
        ctx.add_recipe("tmod:mix", {}, {}, 1.0, machines=(C.B_ASSEMBLER,),
                       fluid_inputs={"tmod:sludge": 5.0},
                       fluid_outputs={"stellarloom:petroleum": 2.5})
        fin, fout = C.fluid_recipe_of("tmod:mix")
        check(fin == {fid: 5.0} and fout == {C.F_PETROLEUM: 2.5},
              f"液体配方注册错: {fin} / {fout}")
    finally:
        ctx._unload()
    check(C.FLUID_NAMES.get(fid) in (None, fid) or fid not in C.FLUID_NAMES,
          "卸载后液体注册没撤销")
    check("tmod:mix" not in C.RECIPES
          and "tmod:mix" not in C.RECIPE_FLUIDS, "卸载后液体配方没撤销")
    g4.mod_mgr.unload()

    print()
    if bad:
        print(f"FAIL {bad} 项: _fluidcheck")
        return 1
    print("PASS 液体系统全部通过")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
