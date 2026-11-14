#!/usr/bin/env python3
"""缩放/星系视图自检（M6.32）：最小缩放后继续缩小 → 进度条 → 星系视图；
放大回地图；戴森目标轨道（点环/存档/发射）。

跑法：python tools/_viewcheck.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.core.game import Game  # noqa: E402
from stellarloom.save.savefile import SaveManager  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402


def main():
    fails = []

    def t(ok, msg):
        print("    PASS" if ok else "    FAIL", msg)
        if not ok:
            fails.append(msg)

    pygame.init()
    screen = pygame.display.set_mode((1024, 600))
    g = Game(screen)
    g.menu.close()
    g.mod_mgr.unload()
    step = 1 / C.ZOOM_STEP

    # ---------- 1. 最小缩放 + 出界进度 ----------
    print("[1] 缩到最小后继续缩小：进度累积:")
    g.camera.zoom = C.ZOOM_MIN
    t(abs(g.camera.zoom - C.ZOOM_MIN) < 1e-6, f"缩放钳到最小 {g.camera.zoom:.3f}")
    t(g._zoom_pull == 0.0, "刚好到最小这一下不攒进度")
    before = g._zoom_pull
    g._zoom_by(step)
    t(g._zoom_pull > before, f"再缩一次开始攒进度 {g._zoom_pull:.2f}")
    t(not g.orbit_panel.open, "进度未满不进星系视图")

    # ---------- 2. 进度条绘制 ----------
    print("[2] 进度条绘制:")
    g._draw_zoom_hint()                    # 只画，不崩
    t(True, f"进度 {g._zoom_pull:.0%} 时绘制不崩")

    # ---------- 3. 进度满进星系视图 ----------
    print("[3] 进度满 → 星系视图:")
    n = 0
    while not g.orbit_panel.open and n < 20:
        g._zoom_by(step)
        n += 1
    t(g.orbit_panel.open, f"连续缩 {n + 2} 次后打开星系视图")
    t(g.ui.orbit_open, "底栏轨道状态同步")
    t(g._zoom_pull == 0.0, "进视图后进度清零")
    # 全屏分支必须自己 flip，否则画面停在上一帧（"点啥都没反应"）
    flips = {"n": 0}
    orig_flip = pygame.display.flip
    pygame.display.flip = lambda *a, **k: flips.__setitem__("n", flips["n"] + 1)
    g._draw()
    pygame.display.flip = orig_flip
    t(flips["n"] == 1, "全屏视图每帧照常翻页（不冻屏）")
    g._draw()
    pygame.display.flip()
    t(True, "星系视图渲染不崩")

    # ---------- 4. 放大回地图 ----------
    print("[4] 放大 / ESC 回地图:")
    g._zoom_by(1.0 / step)                 # 放大
    t(not g.orbit_panel.open, "放大退出星系视图")
    t(abs(g.camera.zoom - C.ZOOM_MIN) < 1e-6, "回到地图保持最小缩放")
    g._zoom_by(step)
    g._zoom_by(step)
    while not g.orbit_panel.open:
        g._zoom_by(step)
    g._on_key(pygame.K_ESCAPE)
    t(not g.orbit_panel.open and not g.ui.orbit_open, "ESC 退出星系视图")

    # ---------- 5. 进度粘性 + 点进度条进视图 ----------
    print("[5] 进度粘性 / 点条进入:")
    g.camera.zoom = C.ZOOM_MIN
    g._zoom_pull = 0.5
    g._update(2.0)
    g._update(2.0)
    t(abs(g._zoom_pull - 0.5) < 1e-9, f"停手 4 秒进度不掉（仍 {g._zoom_pull:.2f}）")
    g._draw()                               # 画一次，拿到条的位置
    from stellarloom.input.gestures import TapEvent
    if g._zoom_bar_rect.width > 0:
        g._handle_gesture(TapEvent(g._zoom_bar_rect.center), 1 / 60)
    t(g.orbit_panel.open, "点进度条也能进星系视图")
    g._on_key(pygame.K_ESCAPE)

    # ---------- 6. 戴森目标轨道 ----------
    print("[6] 戴森目标轨道:")
    sim = Simulation()
    sim.tech.researched.add("dyson1")
    sim.tech.researched.add("dyson2")
    d = sim.dyson
    t(d.unlocked_orbits() == C.DYSON_ORBITS, "三条轨道已解锁")
    t(d.target_orbit is None, "默认自动选最空")
    t(d.set_target_orbit(2), "指定外轨")
    t(d.target_orbit == 2, "target_orbit = 2")
    n0 = d.orbit_count[2]
    d.launch(5)
    t(d.orbit_count[2] == n0 + 5, f"发射进指定轨道（{n0}→{d.orbit_count[2]}）")
    t(d.set_target_orbit(2) and d.target_orbit is None, "再点同一环恢复自动")
    t(not d.set_target_orbit(9), "越界轨道被拒")
    # 目标环满 → 回落自动选最空
    d.set_target_orbit(2)
    d.orbit_count[2] = C.DYSON_ORBIT_CAP[2]
    d.orbit_count[0] = 0
    d.orbit_count[1] = 0
    d.launch(1)
    t(d.orbit_count[1] == 1, "目标环满时自动挑其它环（最空的）")
    d.orbit_count[2] = 3

    # ---------- 7. 面板点轨道环 = 设目标 ----------
    print("[7] 星系视图点轨道环:")
    # 面板读的是 Game 自己的科技树
    g.tech.researched.add("dyson1")
    g.tech.researched.add("dyson2")
    panel = g.orbit_panel
    g.orbit_panel.show(g.dyson, g.tech, g.worlds, g.world_index,
                       screen.get_size(), g._switch_planet)
    panel.draw(screen)
    pcx, pcy = panel._center
    rad1 = panel._radius_base * C.DYSON_ORBIT_RADIUS[1]
    g.dyson.set_target_orbit(None)
    panel.hit((int(pcx + rad1), int(pcy)))
    t(g.dyson.target_orbit == 1, f"点中轨 → target={g.dyson.target_orbit}")
    panel.hit((int(pcx + rad1), int(pcy)))
    t(g.dyson.target_orbit is None, "再点一次恢复自动")
    panel.hit((int(pcx + rad1), int(pcy)))
    # 点行星仍然切换（导航保留）
    switched = []
    panel._on_switch = lambda i: switched.append(i)
    px, py = panel._planet_xy(1)
    panel.hit((int(px), int(py)))
    t(switched == [1], f"点行星仍可切换（{switched}）")

    # ---------- 8. 存档往返 ----------
    print("[8] 目标轨道存档往返:")
    tmp = tempfile.mkdtemp(prefix="slm_view_")
    sm = SaveManager(tmp)
    s = Simulation(); s.saves = sm
    s.tech.researched.add("dyson1")
    s.tech.researched.add("dyson2")
    s.dyson.set_target_orbit(1)
    s.dyson.orbit_count[1] = 7
    sm.save(s, "t.slm")
    s2 = Simulation(); s2.saves = sm
    ok = sm.load(s2, "t.slm")
    t(ok and s2.dyson.target_orbit == 1 and s2.dyson.orbit_count[1] == 7,
      f"读档后 target={s2.dyson.target_orbit} 帆={s2.dyson.orbit_count[1]}")
    # 老档没有 target_orbit → 默认自动
    old = {"orbit_count": [0, 0, 0], "orbit_angle": [0, 0, 0], "emitters": []}
    s3 = Simulation()
    s3.dyson.load_from(dict(old))
    t(s3.dyson.target_orbit is None, "老档缺 target_orbit → 自动模式")

    print()
    print("======== 缩放/星系视图自检 ========")
    if fails:
        print(f"FAIL {len(fails)} 项: {fails}")
        return 1
    print("PASS 缩放/星系视图全部通过  exit=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
