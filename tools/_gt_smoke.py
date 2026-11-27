#!/usr/bin/env python3
"""完整 Game 冒烟测试（dummy 显示驱动，不开窗口）：格雷科技 mod 全链路。

构造真实 Game（会加载全部 mod 并跑 _register_ui 重排底栏），推进若干帧，
走一遍「研究 → 放新机器 → 打开机器面板 → 底栏选中 → 拆除退款」全流程，
确认 UI 层（底栏/面板）与 mixin 在真实游戏对象上不炸。

跑法：python tools/_gt_smoke.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
# 注意：mod 模块实例（mod_gregtech_heavy_main）由 Game 构造时的加载器创建，
# 因此下面的 `import mod_gregtech_heavy_main as GT` 必须放在 Game(...) 之后。


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    from stellarloom.core import Game
    g = Game(screen)

    import mod_gregtech_heavy_main as GT  # noqa: E402, PLC0415
    mgr = g.mod_mgr
    names = [c.name for c in mgr.ctxs]
    print("mods:", names, "failed:", mgr.failed)
    assert any(c.name == "gregtech_heavy" for c in mgr.ctxs), "GT mod 未加载"
    # M15d：出错即崩，能到这里即"未抛异常"；failed 恒为空
    assert mgr.failed == [], f"failed 应恒为空 {mgr.failed}"

    # 底栏分类里有「重工」
    from stellarloom.ui import touch_ui as TUI
    assert "重工" in [n for n, _ in TUI.CATEGORIES], "底栏缺重工分类"

    # 推进几帧（含 mod on_step 转发）
    for _ in range(6):
        g._update(0.033)
        g._draw()

    # —— 研究中，直接走 sim 指令放一台粉碎机 ——
    g.sim.inventory[GT.I_GT_CRUSHER] = 5
    g.sim.tech.researched.add("gt_ore")
    gx, gy = 200, 200
    r = g.sim.place_building(GT.B_GT_CRUSHER, gx, gy, 0)
    assert r == "ok", f"放置失败 {r}"
    assert g.sim.machines.get_machine(gx, gy) is not None, "机器网络没有粉碎机"

    # —— 原版熔炉：放下去就能开面板（组合式 sync 不吞原版机器）——
    vfx, vfy = 204, 200
    assert g.sim.place_building(C.B_FURNACE, vfx, vfy, 0) == "ok"
    assert g.sim.machines.get_machine(vfx, vfy) is not None, "熔炉机器实例缺失"
    g._try_open_panel(vfx, vfy)
    assert g.machine_panel.open, "原版熔炉面板未开"
    g.machine_panel.close()
    for _ in range(3):
        g._update(0.033)
        g._draw()
    assert g.sim.machines.get_machine(vfx, vfy) is not None, "跑帧后熔炉丢失"

    # —— 打开机器面板（点一次放置后立即开面板的路径）——
    g._try_open_panel(gx, gy)
    assert g.machine_panel.open, "机器面板未打开"
    for _ in range(3):
        g._update(0.033)
        g._draw()

    # —— 底栏选中新机器（模拟点「重工 → 高炉」）——
    g._apply_ui_action("select", GT.B_GT_FURNACE)
    assert g.selected_building == GT.B_GT_FURNACE, "底栏未能选中高炉"
    g._draw()

    # 高炉被科技锁：直接放置应被拒（返回 locked）
    r2 = g.sim.place_building(GT.B_GT_FURNACE, gx + 3, gy, 0)
    assert r2 == "locked", f"未研究科技却放出了高炉 {r2}"

    # —— 拆除粉碎机：建筑与机内物料全额退回 ——
    m = g.sim.machines.get_machine(gx, gy)
    m.set_recipe("gt_cr_iron")
    m.feed(C.I_IRON_ORE)
    ok, _ = g.sim.remove_building(gx, gy)
    assert ok, "拆除失败"
    assert g.sim.inventory.get(GT.I_GT_CRUSHER, 0) >= 5, "建筑未退回"
    assert g.sim.machines.get_machine(gx, gy) is None, "网络残留"

    # 关上面板再跑几帧收尾
    g.machine_panel.close()
    for _ in range(3):
        g._update(0.033)
        g._draw()

    pygame.quit()
    print("PASS 完整 Game 冒烟通过：mod 加载 / 底栏 / 放置 / 原版熔炉面板 / 面板 / 拆除退款")
    return 0


if __name__ == "__main__":
    sys.exit(main())