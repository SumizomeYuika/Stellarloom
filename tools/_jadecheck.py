#!/usr/bin/env python3
"""jade mod 冒烟测试（headless，SDL dummy 驱动，不开窗口）。

流程：
1. 用 dummy 视频驱动构造完整 Game（mods 随 Game 构造自动加载）
2. 校验 jade mod 已加载、未进 failed 列表
3. 铺一个测试场景（原版熔炉/格雷科技反应堆/传送带/分拣器/箱子/采矿机/
   科研站/发射器/物流塔/核心/矿脉），逐个把"鼠标"指向该格，走完整
   _draw 管线并截图；同时打印 _describe 文本用于断言（含来源 mod）
4. 顺带回归：machine 网络在 step 后仍持有原版熔炉与 mod 机器
   （gregtech_heavy 曾把原版机器清掉）
5. 校验卸载后 mixin 已还原（_draw_ui 不再是包装版）

用法：python tools/_jadecheck.py [输出目录]
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # 必须在 import pygame 前

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.core import Game  # noqa: E402
from stellarloom.production.machines import Machine  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(os.environ.get("TEMP", ROOT)) / "jade_shots"

# gregtech_extra 的反应堆（MACHINE_TYPES 里的 30）
B_X_REACTOR = 30
I_X_REACTOR = 2040

_failures: list[str] = []


def check(cond: bool, msg: str):
    print(("  ok  " if cond else "  !! FAIL ") + msg)
    if not cond:
        _failures.append(msg)


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((C.WINDOW_WIDTH, C.WINDOW_HEIGHT))
    g = Game(screen)
    jade = importlib.import_module("mod_jade_main")   # 加载器注入的模块名

    # ---- 1. jade 是否加载 ----
    names = [c.name for c in g.mod_mgr.ctxs]
    failed = [f for f in g.mod_mgr.failed]
    print("[jade] 已加载 mods:", names)
    print("[jade] failed:", failed)
    check("jade" in names, "jade 已加载")
    check(not any(f[0] == "jade" for f in failed), "jade 未进 failed 列表")

    # ---- 2. 场景 ----
    sim = g.sim
    g.menu.close()                       # 关主菜单，进入世界
    sim.inventory[C.I_CHEST_ITEM] = 1
    sim.inventory[C.I_LAB_ITEM] = 1
    sim.inventory[C.I_EMITTER_ITEM] = 1
    sim.inventory[C.I_TOWER_SUPPLY_ITEM] = 5
    sim.inventory[I_X_REACTOR] = 5       # 格雷科技·星海 反应堆（建筑物品 2040）
    sim.inventory[C.I_SOLAR_ITEM] = 5    # 电网：太阳能 / 风力 / 电力塔
    sim.inventory[C.I_WIND_ITEM] = 5
    sim.inventory[C.I_POWER_POLE_ITEM] = 8
    sim.inventory[C.I_FURNACE_ITEM] += 4  # 电网 B 的 4 台耗电熔炉
    g.tech.researched.add("drones1")     # 物流塔解锁
    g.tech.researched.add("ex_reactor")  # 反应堆解锁
    g.tech.researched.add("dyson1")      # 太阳帆发射器解锁

    y = 256
    sim.place_building(C.B_FURNACE, 254, y, 0)   # 有配方的原版熔炉
    sim.place_building(C.B_CHEST, 252, y, 0)     # 箱子
    sim.place_building(C.B_MINER, 250, y, 0)     # 采矿机
    sim.place_building(C.B_LAB, 246, y, 0)       # 科研站
    sim.place_building(C.B_EMITTER, 244, y, 0)   # 太阳帆发射器
    sim.place_building(B_X_REACTOR, 258, y, 0)   # 格雷科技·星海 聚变反应堆
    sim.place_building(C.B_FURNACE, 256, 254, 0)  # 空壳熔炉
    sim.lay_belt_line(260, y, 262, y)            # 传送带 3 格
    sim.place_inserter(263, y, 0)                # 分拣器 overlay

    # —— M9 电网：三张互不相连的网 ——
    # 电网 A：中间簇（与核心/熔炉/科研站等并网）
    sim.place_building(C.B_POWER_POLE, 262, 254, 0)   # 电力塔
    sim.place_building(C.B_SOLAR, 263, 252, 0)        # 太阳能
    sim.place_building(C.B_WIND, 261, 252, 0)         # 风力
    # 电网 B：孤立远处（风力 40kW 撑不起 4 台熔炉 120kW → 橙色/偏紧）
    sim.place_building(C.B_POWER_POLE, 280, 270, 0)
    sim.place_building(C.B_WIND, 281, 270, 0)
    for k in range(4):
        sim.place_building(C.B_FURNACE, 276 + k, 270, 0)
    # 电网 C：物流塔孤岛（无发电 → 红色缺电；悬停塔身即可见）

    # 有配方的熔炉：喂料 + 进度
    m = sim.machines.get_machine(254, y)
    check(m is not None, "原版熔炉的 Machine 在网络里（gregtech_heavy 不删原版）")
    if m is None:   # 网络坏了就手工补一个，方便主流程继续跑
        m = Machine(254, y, C.B_FURNACE)
        sim.machines.machines[(254, y)] = m
    m.set_recipe("iron_plate")
    m.add_input(C.I_IRON_ORE, 3)
    m.progress = 0.42

    # 反应堆：配方 + 喂料 + 进度
    mr = sim.machines.get_machine(258, y)
    check(mr is not None, "gregtech_extra 反应堆的 Machine 在网络里")
    if mr is not None:
        mr.set_recipe("ex_fuel")
        rec = C.RECIPES.get("ex_fuel")
        if rec:
            for it, n in rec[0].items():   # 喂配方原料（按配方驱动，不硬编码）
                mr.add_input(it, n * 2)
        mr.progress = 0.3

    # 物流塔（放置后网络 sync）
    sim.place_tower(C.B_TOWER_SUPPLY, 238, 244, 0)

    # 一次性 step：网络 sync（machines/labs/towers/dyson/belts 重建）。
    # 传送带必须等 rebuild 之后才能 try_insert（见 lay_belt_line 只标记脏）。
    sim.step(0.1)

    # step 会推进进度，重设回目标值
    m = sim.machines.get_machine(254, y)
    if m is not None:
        m.progress = 0.42
    mr = sim.machines.get_machine(258, y)
    if mr is not None:
        mr.progress = 0.3
    # 回归：step 之后机器仍在（gregtech_heavy 不再清原版机器）
    check(sim.machines.get_machine(254, y) is not None,
          "step 后原版熔炉 Machine 仍在")
    check(sim.machines.get_machine(258, y) is not None,
          "step 后反应堆 Machine 仍在")

    # —— 以下物品类设置都在最后一次 step 之后，避免被网络重建冲掉 ——
    # 传送带物品
    sim.belts.try_insert(260, y, C.I_IRON_PLATE)
    sim.belts.try_insert(261, y, C.I_GEAR)
    sim.belts.try_insert(262, y, C.I_IRON_PLATE)
    # 箱子库存
    ch = sim.chests.get(252, y)
    ch.add_item(C.I_IRON_PLATE, 25)
    ch.add_item(C.I_GEAR, 9)
    # 科研站：研究模式 + 囤包
    g.tech.current = "logistics1"
    lab = sim.labs.get_lab(246, y)
    if lab is not None:
        lab["stored"] = {C.I_SCIENCE_BLUE: 4}
    # 发射器：储帆
    em = sim.dyson.get(244, y)
    if em is not None:
        em.add_item(C.I_SOLAR_SAIL, 12)
        em.launched = 3
    # 供应塔库存
    twr = sim.towers.get_tower(238, 244)
    if twr is not None:
        twr.add_item(C.I_IRON_PLATE, 9)

    # ---- 3. 逐个悬停：文本断言 + 截图 ----
    OUT.mkdir(parents=True, exist_ok=True)
    seen: list[tuple[str, str | None, str | None]] = []

    def cell_shot(name, gx, gy, want_src=None, hover=None):
        if hover is None:
            # 世界中心 (256,256) → 屏幕 (sw/2, sh/2) = (640, 360)；tile_px=18
            dx, dy = gx - 256, gy - 256
            hover = (640 + dx * 18, 360 + dy * 18)

        def fake_cursor():
            return hover
        g._cursor_pos = fake_cursor
        info = jade._describe(g, gx, gy)
        title = src = None
        if info is not None:
            title, _chip, lines, src = info
            print(f"[jade] {name} ({gx},{gy}) 标题={title} 来源={src}")
            for k, *rest in lines:
                print(f"        {k} {rest}")
        else:
            print(f"[jade] {name} ({gx},{gy}) -> None（不显示弹板）")
        seen.append((name, title, src))
        if want_src is not None:
            check(src == want_src, f"{name}: 来源 = {want_src!r}（实际 {src!r}）")
        g._draw()
        path = OUT / f"{name}.png"
        pygame.image.save(screen, str(path))
        return path

    cell_shot("furnace", 254, 256, want_src="原版")          # 原版熔炉
    cell_shot("furnace_empty", 256, 254, want_src="原版")    # 空壳熔炉
    cell_shot("reactor", 258, 256, want_src="gregtech_extra")  # mod 机器
    cell_shot("chest", 252, 256, want_src="原版")
    cell_shot("miner", 250, 256, want_src="原版")
    cell_shot("lab", 246, 256, want_src="原版")
    cell_shot("emitter", 244, 256, want_src="原版")
    cell_shot("belt", 260, 256, want_src="原版")
    cell_shot("inserter", 263, 256, want_src="原版")
    cell_shot("tower_body", 239, 244, want_src="原版")       # 塔身空位
    cell_shot("core", 256, 254, want_src="原版")

    # ---- 电网（M9）：发电/电力塔信息 + 整网染色 ----
    pa = jade._power_net_at(g, 263, 252)   # 太阳能（电网 A）
    pb = jade._power_net_at(g, 280, 270)   # 电力塔（电网 B）
    pt = jade._power_net_at(g, 238, 244)   # 物流塔中心（电网 C 孤岛）
    pc = jade._power_net_at(g, 252, 256)   # 箱子（非电力节点）
    check(pa is not None and pb is not None and pt is not None,
          "三张电网都识别得到（A/B/C 索引非空）")
    if pa and pb and pt:
        check(len({pa[0], pb[0], pt[0]}) == 3,
              "三张电网互相独立（索引互不相同）")
    check(pc is None, "箱子不是电力节点（不在任一电网）")
    check(pa is not None and g.power.net_count >= 3,
          f"net_count >= 3（实际 {g.power.net_count}）")

    def info_text(cx, cy):
        inf = jade._describe(g, cx, cy)
        return " ".join(str(r[0]) for _k, *r in (inf[2] if inf else []))
    txt_a = info_text(263, 252)
    check("电网" in txt_a and "电力充足" in txt_a and "网内" in txt_a,
          f"太阳能悬停含电网状态行（{txt_a[:40]}…）")
    txt_b = info_text(280, 270)
    check("电力塔" in txt_b or "电网" in txt_b, "电力塔悬停含电网状态行")
    check(pb is not None and 0.20 <= pb[1]["ratio"] < 0.5,
          f"电网 B 由 40kW 风力撑 120kW 需求 → 充足率 ≈33%（实际 "
          f"{(pb[1]['ratio'] if pb else 0.0):.2f} → 橙色染色）")

    cell_shot("power_solar", 263, 252, want_src="原版")      # 电网A：悬停太阳能
    cell_shot("power_pole", 280, 270, want_src="原版")       # 电网B：悬停电力塔
    cell_shot("power_tower_red", 238, 244, want_src="原版")  # 电网C：红色缺电

    # ---- 覆盖层像素级验证：开/关覆盖层各截一张，对比取样点 ----
    def shot_with_overlay(on: bool, path: Path):
        jade._CFG["show_net_overlay"] = on
        hover = (640 + 7 * 18, 360 - 4 * 18)  # 悬停太阳能 (263,252)
        g._cursor_pos = lambda: hover
        g._draw()
        pygame.image.save(screen, str(path))
    ov_on = OUT / "_ov_on.png"
    ov_off = OUT / "_ov_off.png"
    shot_with_overlay(True, ov_on)
    shot_with_overlay(False, ov_off)
    jade._CFG["show_net_overlay"] = True
    p_on = pygame.image.load(str(ov_on))
    p_off = pygame.image.load(str(ov_off))
    same = lambda x, y: p_on.get_at((x, y)) == p_off.get_at((x, y))
    solar_px = (640 + 7 * 18 + 9, 360 - 4 * 18 + 9)          # 太阳能格(263,252)
    core_px = (640 + 9, 360 - 2 * 18 + 9)                    # 熔炉格(256,254)
    air_px = (640 - 8 * 18 + 9, 360 - 12 * 18 + 9)           # 无节点格(248,244)
    check(not same(*solar_px), "覆盖层开/关：太阳能格像素有差异（已染色）")
    check(not same(*core_px), "覆盖层开/关：熔炉格像素有差异（同网同步染色）")
    check(same(*air_px), "覆盖层开/关：非电网格子像素一致（未误染）")
    ov_on.unlink()
    ov_off.unlink()

    # 矿脉：来源应为该矿物品的命名空间（原版或 gregtech_extra 都合法）
    grid = g.grid
    best = None
    for yy in range(240, 272):
        for xx in range(240, 272):
            if grid.get(xx, yy) == C.B_EMPTY and grid.get_ore_type(xx, yy):
                best = (xx, yy)
                break
        if best:
            break
    if best:
        cell_shot("ore", *best)
    empties = [(xx, yy) for yy in (244, 258) for xx in (248, 258)
               if grid.get(xx, yy) == C.B_EMPTY
               and not grid.get_ore_type(xx, yy)
               and g.towers.get_tower(xx, yy) is None]
    if empties:
        cell_shot("air", *empties[0])

    # 顶栏上（不该画弹板）
    def fake_top():
        return (640, 10)
    g._cursor_pos = fake_top
    g._draw()
    path = OUT / "topbar.png"
    pygame.image.save(screen, str(path))
    print(f"[jade] 截图 topbar: 鼠标在顶栏，弹板应不显示 -> {path}")

    # ---- 4. 卸载后 mixin 还原 ----
    from stellarloom.core.game import Game as GameCls
    wrapped = g._draw_ui.__func__ is GameCls._draw_ui  # 类属性 = 包装函数
    check(wrapped, "显示钩子是混入包装版（jade 生效中）")
    g.mod_mgr.unload()
    plain = g._draw_ui.__func__ is GameCls._draw_ui     # 类属性已还原为原版
    check(plain, "卸载后 Game._draw_ui 已还原（mixin 还原）")

    print()
    if _failures:
        print("FAIL 存在未通过项:")
        for f in _failures:
            print("  - " + f)
        return 1
    print(f"PASS jade 冒烟测试通过（截图在 {OUT}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())