#!/usr/bin/env python3
"""星际物流自检（M5b）：发射窗口 + 发射台 + 运输船 + 存档 + 面板。

跑法：python tools/_shipcheck.py
段 [7] 需要 pygame（dummy 视频驱动），其余纯逻辑。
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from stellarloom import config as C
from stellarloom.logistics import pads as P
from stellarloom.sim.sim import Simulation


def check(ok: bool, msg: str = ""):
    if ok:
        print("    PASS", msg)
    else:
        print("    FAIL", msg)
    return ok


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _sim_with_tech():
    s = Simulation()
    s.tech.researched.add("interstellar1")
    s.inventory[C.I_LAUNCH_PAD_ITEM] = 10
    return s


def main():
    fails = []

    def t(ok, msg=""):
        if not check(ok, msg):
            fails.append(msg or "断言失败")

    # ---------- 0. 常量 ----------
    print("[0] 星际物流常量:")
    print(f"    PAD_STACK={C.PAD_STACK} SHIP_CARGO_CAP={C.SHIP_CARGO_CAP} "
          f"FLIGHT_BASE={C.SHIP_FLIGHT_BASE} WINDOW={C.SHIP_WINDOW_ANGLE}°")
    t(C.PAD_STACK > 0, "PAD_STACK 必须 > 0")
    t(C.SHIP_CARGO_CAP > 0, "SHIP_CARGO_CAP 必须 > 0")
    t(C.SHIP_FLIGHT_BASE > 0, "SHIP_FLIGHT_BASE 必须 > 0")
    t(0 < C.SHIP_WINDOW_ANGLE < 180, "SHIP_WINDOW_ANGLE 必须在 (0,180)")

    # ---------- 1. 相位 / 发射窗口 ----------
    print("[1] 相位与发射窗口:")
    s = _sim_with_tech()
    w0, w1 = s.worlds[0], s.worlds[1]
    w0.planet.angle, w1.planet.angle = 0.0, 0.0
    t(approx(P.phase_diff(w0, w1), 0.0), "同相位时差应为 0")
    t(P.window_open(w0, w1), "同相位应开窗口")
    t(P.window_wait(w0, w1) == 0.0, "窗口内等待应为 0")

    w0.planet.angle, w1.planet.angle = 0.0, 100.0
    d = P.phase_diff(w0, w1)
    t(approx(d, 100.0), f"相位差 100°（实际 {d:.2f}）")
    t(not P.window_open(w0, w1), "相位差 100° 应关窗口")

    # 解析等待 vs 数值模拟对照（两颗星按各自开普勒轨道公转）
    wait = P.window_wait(w0, w1)
    dt, sim_t = 0.5, 0.0
    while sim_t < 6000:
        sim_t += dt
        d = abs(((w0.planet.angle_after(sim_t)
                  - w1.planet.angle_after(sim_t) + 180) % 360) - 180)
        if d <= C.SHIP_WINDOW_ANGLE:
            break
    t(wait <= sim_t <= wait + dt,
      f"窗口等待 {wait:.2f}s ≈ 数值 {sim_t:.2f}s")

    w0.planet.angle, w1.planet.angle = 0.0, 150.0
    hold = P.window_hold(w0, w1)
    t(hold == 0.0, "不在窗口内 hold 应为 0")
    w0.planet.angle, w1.planet.angle = 0.0, 10.0
    t(P.window_hold(w0, w1) > 0, "窗口内 hold 应 > 0")

    # 同周期 --> 永不换窗口
    same1 = types.SimpleNamespace(planet=types.SimpleNamespace(
        angle=0.0, period=600.0))
    same2 = types.SimpleNamespace(planet=types.SimpleNamespace(
        angle=120.0, period=600.0))
    t(P.window_wait(same1, same2) == float("inf"),
      "同周期且不齐时等待应为 inf")

    # 飞行时间：相位越远越久
    w0.planet.angle, w1.planet.angle = 0.0, 0.0
    near = P.flight_time(w0, w1)
    w1.planet.angle = 180.0
    far = P.flight_time(w0, w1)
    t(far > near, f"远相位飞行更久（{near:.1f}s < {far:.1f}s）")

    # ---------- 2. 发射台放置 ----------
    print("[2] 发射台放置:")
    s = _sim_with_tech()
    s.tech.researched.discard("interstellar1")
    t(s.place_pad(C.B_LAUNCH_PAD, 100, 100) == "locked", "未研究应返回 locked")
    s.tech.researched.add("interstellar1")
    t(s.place_pad(C.B_LAUNCH_PAD, 100, 100) == "ok", "研究后应能放")
    t(len(s.pads.pads) == 1, "应记录 1 座发射台")
    t(len(s.fleet.ships) == 1, "每座供货台自动配 1 条船")
    t(s.fleet.ships[0].home == (0, 100, 100), "船母港记录正确")
    # 3×3 内再放应失败（重叠）
    t(s.place_pad(C.B_LAUNCH_PAD, 101, 101) == "no_place", "重叠应拒绝")
    # 拆台：退料 + 清船
    before = s.inventory.get(C.I_LAUNCH_PAD_ITEM, 0)
    ok, _ = s.remove_building(101, 101)
    t(ok and s.inventory.get(C.I_LAUNCH_PAD_ITEM, 0) == before + 1,
      "拆台退回建筑物品")
    t(len(s.pads.pads) == 0 and len(s.fleet.ships) == 0, "拆台清掉船")

    # ---------- 3. 装货 → 飞行 → 卸货闭环 ----------
    print("[3] 运输闭环:")
    s = _sim_with_tech()
    w0, w1 = s.worlds[0], s.worlds[1]
    w0.planet.angle = w1.planet.angle = 0.0     # 窗口全开
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    src = s.pads.pads[(100, 100)]
    src.inventory[C.I_IRON_PLATE] = 25
    s.activate_world(1)
    s.place_pad(C.B_LAUNCH_PAD, 60, 60)
    s.set_pad_mode(60, 60, "request")
    dst = s.pads.pads[(60, 60)]
    s.activate_world(0)
    s.set_pad_target(100, 100, 1)
    ship = s.fleet.ships[0]
    for _ in range(60 * 60):
        s.step(1.0 / 60.0)
    t(dst.inventory.get(C.I_IRON_PLATE, 0) == 25,
      f"25 铁板送达（实际 {dst.inventory.get(C.I_IRON_PLATE, 0)}）")
    t(not src.inventory, "供货台已清空")
    t(ship.state == "docked" and not ship.cargo, "船已返航并卸空")

    # ---------- 4. 窗口关闭时按兵不动 ----------
    print("[4] 窗口关闭:")
    s = _sim_with_tech()
    w0, w1 = s.worlds[0], s.worlds[1]
    w0.planet.angle, w1.planet.angle = 0.0, 150.0
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    pad = s.pads.pads[(100, 100)]
    pad.inventory[C.I_IRON_PLATE] = 5
    s.activate_world(1)
    s.place_pad(C.B_LAUNCH_PAD, 60, 60)
    s.set_pad_mode(60, 60, "request")
    s.activate_world(0)
    s.set_pad_target(100, 100, 1)
    for _ in range(300):
        s.step(1.0 / 60.0)
    t(s.fleet.ships[0].state == "docked", "窗口关时不发船")
    t(pad.inventory.get(C.I_IRON_PLATE) == 5, "货还在原台")

    # ---------- 5. 目标台满 → 剩货带回 ----------
    print("[5] 目标台满:")
    s = _sim_with_tech()
    w0, w1 = s.worlds[0], s.worlds[1]
    w0.planet.angle = w1.planet.angle = 0.0
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    src = s.pads.pads[(100, 100)]
    src.inventory[C.I_IRON_PLATE] = 30
    s.activate_world(1)
    s.place_pad(C.B_LAUNCH_PAD, 60, 60)
    s.set_pad_mode(60, 60, "request")
    dst = s.pads.pads[(60, 60)]
    dst.inventory[C.I_IRON_PLATE] = C.PAD_STACK   # 满仓
    s.activate_world(0)
    s.set_pad_target(100, 100, 1)
    for _ in range(60 * 90):
        s.step(1.0 / 60.0)
    # 满仓收不下 → 船带回，返航卸回母台（母台已被清空，能收）
    t(dst.inventory.get(C.I_IRON_PLATE) == C.PAD_STACK,
      f"目标台保持满仓（{dst.inventory.get(C.I_IRON_PLATE)}）")
    t(src.inventory.get(C.I_IRON_PLATE, 0) == 30,
      f"剩货全部带回母台（{src.inventory.get(C.I_IRON_PLATE, 0)}）")

    # ---------- 6. 存档往返（含在途船） ----------
    print("[6] 存档往返:")
    from stellarloom.save.savefile import SaveManager
    s = _sim_with_tech()
    w0, w1 = s.worlds[0], s.worlds[1]
    w0.planet.angle = w1.planet.angle = 0.0
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    s.pads.pads[(100, 100)].inventory[C.I_IRON_PLATE] = 12
    s.activate_world(1)
    s.place_pad(C.B_LAUNCH_PAD, 60, 60)
    s.set_pad_mode(60, 60, "request")
    s.activate_world(0)
    s.set_pad_target(100, 100, 1)
    for _ in range(90):   # 1.5s：船应已在途
        s.step(1.0 / 60.0)
    t(s.fleet.ships[0].state == "outbound", "存档前船在去程")
    tmp = tempfile.mkdtemp(prefix="slm_ship_")
    sm = SaveManager(tmp)
    sm.save(s, "s.slm")
    s2 = Simulation()
    sm.load(s2, "s.slm")
    p0 = s2.worlds[0].pads.pads.get((100, 100))
    p1 = s2.worlds[1].pads.pads.get((60, 60))
    t(p0 is not None and p1 is not None, "两座发射台都回来了")
    t(p0.mode == "supply" and p0.target == 1, "供货台模式/目标还在")
    t(p1.mode == "request", "要货台模式还在")
    t(len(s2.fleet.ships) == 1, "舰队回 1 条船")
    sh2 = s2.fleet.ships[0]
    t(sh2.state == "outbound" and sh2.target is not None, "在途船状态保留")
    t(sh2.cargo.get(C.I_IRON_PLATE, 0) == 12, "在途货物保留")

    # ---------- 7. 模式切换 ----------
    print("[7] 模式切换:")
    s = _sim_with_tech()
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    pad = s.pads.pads[(100, 100)]
    t(s.set_pad_mode(100, 100, "request"), "切到要货")
    t(pad.mode == "request" and not s.fleet.ships, "要货台不配船")
    t(s.set_pad_mode(100, 100, "supply"), "切回供货")
    t(len(s.fleet.ships) == 1, "供货台重新配船")
    t(not s.set_pad_mode(100, 100, "nope"), "非法模式拒绝")

    # ---------- 8. 面板渲染 ----------
    print("[8] 发射台面板:")
    import pygame
    pygame.init()
    pygame.display.set_mode((1024, 600))
    from stellarloom.render.fonts import FontBook
    from stellarloom.ui.pad_panel import PadPanel
    fonts = FontBook()
    s = _sim_with_tech()
    s.place_pad(C.B_LAUNCH_PAD, 100, 100)
    pad = s.pads.pads[(100, 100)]
    pad.inventory[C.I_IRON_PLATE] = 5
    panel = PadPanel(fonts)
    panel.show(pad, s, (1024, 600))
    t(panel.open, "面板已打开")
    surf = pygame.Surface((1024, 600))
    panel.draw(surf)
    t(True, "面板渲染不崩")
    # 点"要货"按钮 → 模式切换
    b = panel._btn_rects["request"]
    panel.hit(b.center)
    t(pad.mode == "request", "点要货按钮切换成功")
    # 点面板外 → 关闭
    panel.hit((5, 5))
    t(not panel.open, "点外部关闭")
    pygame.quit()

    print()
    if fails:
        for f in fails:
            print(f"!! FAIL {f}")
        print(f"FAIL 星际物流自检未通过（{len(fails)} 项）")
        return 1
    print("PASS 星际物流自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
