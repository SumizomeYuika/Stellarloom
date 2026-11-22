#!/usr/bin/env python3
"""完整 Game 冒烟（dummy 显示驱动）：重工 + 星海扩展 双 mod。

走一遍真实 Game 路径：构造（含全部 UI/渲染器，mod 加载后重排底栏）→
研究 → 放金属成型机/化工厂 → 组建大型高炉多方块 → 放聚变反应堆喂氘芯 →
开面板 → 拆砖停工 → 若干帧绘制。任何异常即失败。

跑法：python tools/_gt_extra_smoke.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    from stellarloom.core import Game
    g = Game(screen)
    mgr = g.mod_mgr
    assert not mgr.failed, f"加载失败 {mgr.failed}"
    names = [c.name for c in mgr.ctxs]
    assert "gregtech_extra" in names and "gregtech_heavy" in names, names

    g.menu.open = False   # 关掉主菜单让世界推进（和真实点击“开始游戏”一致）
    g.paused = False
    g.ui.paused = False

    import mod_gregtech_extra_main as X  # noqa: PLC0415,E402
    from stellarloom.ui import touch_ui as TUI  # noqa: PLC0415
    catnames = [n for n, _ in TUI.CATEGORIES]
    assert "星际工业" in catnames and "多方块" in catnames

    sim = g.sim
    sim.tech.researched.update(
        {"ex_mining", "ex_form", "ex_chem", "ex_alloy", "ex_reactor",
         "ex_accel", "ex_mb", "ex_mb2"})
    for _ in range(4):
        g._update(0.033)
        g._draw()

    # —— 原版熔炉 / 制造台：放下去就能开面板（组合式 sync 不吞原版机器）——
    sim.inventory[C.BUILD_ITEM[C.B_ASSEMBLER]] = \
        sim.inventory.get(C.BUILD_ITEM[C.B_ASSEMBLER], 0) + 1
    assert sim.place_building(C.B_FURNACE, 36, 30, 0) == "ok"
    assert sim.machines.get_machine(36, 30) is not None, "熔炉机器实例缺失"
    g._try_open_panel(36, 30)
    assert g.machine_panel.open, "原版熔炉面板未开"
    g.machine_panel.close()
    assert sim.place_building(C.B_ASSEMBLER, 38, 30, 0) == "ok"
    assert sim.machines.get_machine(38, 30) is not None, "制造台机器实例缺失"
    g._try_open_panel(38, 30)
    assert g.machine_panel.open, "原版制造台面板未开"
    g.machine_panel.close()
    for _ in range(3):
        g._update(0.033)
        g._draw()
    assert sim.machines.get_machine(36, 30) is not None, "跑帧后熔炉丢失"
    assert sim.machines.get_machine(38, 30) is not None, "跑帧后制造台丢失"

    # —— 金属成型机：放置即开面板 ——
    sim.inventory[X.I_MACH_FORMER] = 5
    assert sim.place_building(X.B_X_FORMER, 40, 30, 0) == "ok"
    g._try_open_panel(40, 30)
    assert g.machine_panel.open, "成型机面板未开"
    g._apply_ui_action("select", X.B_X_FORMER)
    assert g.selected_building == X.B_X_FORMER
    for _ in range(3):
        g._update(0.033)
        g._draw()

    # —— 多方块：大型高炉 ——
    cx, cy = 44, 30
    sim.inventory[X.I_LARGE_CORE_ITEM] = 5
    sim.inventory[X.I_BRICK_ITEM] = 40
    assert sim.place_building(X.B_X_LARGE_FURNACE, cx, cy, 0) == "ok"
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (dx, dy) == (0, 0):
                continue
            assert sim.place_building(X.B_X_BRICK, cx + dx, cy + dy, 0) == "ok"
    sim.machines.sync()   # 与游戏内 step 的 belts 重建同步时机一致
    for _ in range(3):
        g._update(0.033)
        g._draw()
    core = sim.machines.get_machine(cx, cy)
    assert X._MB_ACTIVE.get(id(core)) is True, "多方块未成型"
    g._try_open_panel(cx, cy)
    assert g.machine_panel.open, "核心面板未开"
    for _ in range(3):
        g._update(0.033)
        g._draw()
    # 拆一块砖 → 停工（不回崩）
    sim.remove_building(cx, cy + 1)
    sim.machines.sync()
    for _ in range(3):
        g._update(0.033)
        g._draw()
    assert X._MB_ACTIVE.get(id(core)) is False, "拆砖后未停工"

    # —— 聚变反应堆：喂料后电网注电 ——
    sim.inventory[X.I_MACH_REACTOR] = 2
    assert sim.place_building(X.B_X_REACTOR, 48, 30, 0) == "ok"
    rct = sim.machines.get_machine(48, 30)
    rct.set_recipe("ex_fuel")
    s0 = sim.power.last_supply
    rct.add_input(X.I_DEUTERIUM, 1)
    for _ in range(40):
        g._update(0.05)   # 2s
    assert sim.power.last_supply >= s0 + 55, f"注电不足 {s0}->{sim.power.last_supply}"

    # 收尾帧
    for _ in range(5):
        g._update(0.033)
        g._draw()
    pygame.quit()
    print("PASS 星海扩展完整 Game 冒烟通过：双 mod / 底栏 / 放置 / 原版熔炉制造台面板 / 多方块 / 聚变供电 / 面板")
    return 0


if __name__ == "__main__":
    sys.exit(main())