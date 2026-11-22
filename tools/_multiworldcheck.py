#!/usr/bin/env python3
"""M5 星际最小版自检：多行星独立世界 + 切换 + 存档 v10 + 迁移。

跑法：python tools/_multiworldcheck.py （dummy pygame，不开窗口）
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

pygame.init()
screen = pygame.display.set_mode((640, 480))

from stellarloom import config as C  # noqa: E402
from stellarloom.core import Game  # noqa: E402
from stellarloom.save import SaveManager  # noqa: E402
from stellarloom.ui.orbit_panel import OrbitPanel  # noqa: E402

fails = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"    {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def new_game() -> Game:
    g = Game(screen)
    g.menu.open = False  # 测试直达游戏态（默认启动是主菜单）
    return g


def main() -> int:
    # ---------- 1. 多行星构造 ----------
    print("[1] 多行星构造:")
    g = new_game()
    check("开局 2 颗行星", len(g.worlds) == 2, f"实际 {len(g.worlds)}")
    check("当前激活第 0 颗", g.world_index == 0)
    check("两行星网格是独立对象", g.worlds[0].grid is not g.worlds[1].grid)
    check("两行星轨道独立", g.worlds[0].planet is not g.worlds[1].planet)
    same_ore = np.array_equal(g.worlds[0].grid.ore, g.worlds[1].grid.ore)
    check("两行星矿脉分布不同（seed 生效）", not same_ore)
    check("两行星都不预置核心（M13.2 起开局无电）",
          g.worlds[0].core_pos is None and g.worlds[1].core_pos is None)
    check("戴森云为恒星级共享",
          g.worlds[0].power.dyson is g.dyson and g.worlds[1].power.dyson is g.dyson)
    check("tech 为玩家级共享",
          getattr(g.worlds[0].labs, "_tech", None) is g.tech)

    # ---------- 2. 行星切换与独立 ----------
    print("[2] 切换与独立:")
    g._activate_world(0)
    g.grid.place(5, 5, C.B_FURNACE, 0)
    g.grid.overlay_gen += 1
    w0_building = int(g.grid.building.sum())
    g._activate_world(1)
    check("切换后 self.grid 指向世界 1",
          g.grid is g.worlds[1].grid)
    check("世界 1 网格没被世界 0 的建筑污染",
          int((g.grid.building == C.B_FURNACE).sum()) == 0,
          f"熔炉数 {int((g.grid.building == C.B_FURNACE).sum())}")
    check("世界 0 的建筑还在",
          int((g.worlds[0].grid.building == C.B_FURNACE).sum()) == 1)
    check("切换后 dyson.grid 指向世界 1", g.dyson.grid is g.worlds[1].grid)
    check("切换后 power.planet 是世界 1 的轨道",
          g.power.planet is g.worlds[1].planet)
    check("世界 1 相机独立", g.camera is g.worlds[1].camera)

    # 世界 1 开局也没有电（M13.2：核心不再预置，电力全靠自己铺）
    g.power.update(0.0)
    check("世界 1 开局无电（需自己建发电）",
          g.power.last_supply == 0.0,
          f"supply={g.power.last_supply:.1f}")

    # ---------- 3. 双行星存档往返 ----------
    print("[3] 双行星存档往返:")
    g._activate_world(0)
    for i in range(8):
        g.grid.place(30 + i, 30, C.B_BELT, 0)
    g.grid.overlay_gen += 1
    g.belts.rebuild()
    lane = g.belts.lanes[0]
    if lane:
        lane.positions = np.array([0.5, 2.5], dtype=np.float32)
        lane.items = np.array([C.I_IRON_ORE, C.I_IRON_PLATE], dtype=np.int32)
    g.worlds[1].grid.place(60, 60, C.B_CHEST, 0)
    g.worlds[1].chests.sync()
    ch = g.worlds[1].chests.get(60, 60)
    if ch is not None:
        ch.store = {C.I_GEAR: 9}
    g.worlds[0].planet.angle = 123.0
    g.worlds[1].planet.angle = 240.0
    g.world_index = 1  # 存档时玩家在第二行星
    tmp = tempfile.mkdtemp(prefix="slm_multi_")
    sm = SaveManager(tmp)
    sm.save(g, "t.slm")
    h = new_game()
    sm.load(h, "t.slm")
    check("读档后激活的行星是存档里的世界 1",
          h.world_index == 1 and h.grid is h.worlds[1].grid)
    check("世界 0 的传送带物品往返一致",
          len(h.worlds[0].belts.lanes) == 1
          and list(h.worlds[0].belts.lanes[0].items) == [C.I_IRON_ORE,
                                                         C.I_IRON_PLATE])
    ch2 = h.worlds[1].chests.get(60, 60)
    check("世界 1 的箱子往返一致",
          ch2 is not None and ch2.store.get(C.I_GEAR) == 9)
    check("两行星轨道角度往返一致",
          abs(h.worlds[0].planet.angle - 123.0) < 1e-6
          and abs(h.worlds[1].planet.angle - 240.0) < 1e-6)
    check("世界 0 建筑不污染世界 1",
          int((h.worlds[1].grid.building == C.B_BELT).sum()) == 0)
    check("读档后 dyson.grid 挂到激活世界", h.dyson.grid is h.worlds[1].grid)

    # ---------- 4. v9 老档迁移 ----------
    print("[4] v9 老档迁移（平铺 -> worlds）:")
    from stellarloom.save.savefile import SAVE_VERSION
    old = {
        "version": 9,
        "planet": {"angle": 55.0, "period": 300.0, "eccentricity": 0.3},
        "grid": {"w": 512, "h": 512}, "belts": [], "machines": [],
        "miners": [], "chests": [], "towers": [], "labs": [], "drones": [],
        "camera": {"x": 1.0, "y": 2.0, "zoom": 0.75},
        "power": {"time": 10.0, "day_length": 120.0},
        "dyson": {"orbit_count": [1, 0, 0], "orbit_angle": [0.0, 0.0, 0.0],
                  "emitters": []},
        "tech": {"researched": [], "current": None, "progress": 0.0,
                 "queue": []},
        "stats": {"inventory": {"1": 3}},
    }
    new = SaveManager()._migrate(old)
    w0 = new["worlds"][0]
    check("版本升到当前版本", new["version"] == SAVE_VERSION)
    # M7：迁移后物品键是名字（数字 1 → stellarloom:iron_ore）
    check("物品键名字化", new["stats"]["inventory"]
          == {"stellarloom:iron_ore": 3})
    check("worlds[0] 收下 planet", w0.get("planet", {}).get("angle") == 55.0)
    check("worlds[0] 收下 grid", "grid" in w0)
    check("worlds[0] 收下 camera/power", "camera" in w0 and "power" in w0)
    check("dyson/tech/stats 留在顶层",
          "dyson" in new and "tech" in new and "stats" in new)
    check("world_index 默认 0", new.get("world_index") == 0)

    # ---------- 5. 轨道面板切换 ----------
    print("[5] 轨道面板点击行星切换:")
    g._activate_world(0)
    switched = []
    panel = OrbitPanel(g.fonts)
    panel.show(g.dyson, g.tech, g.worlds, 0, (640, 480),
               lambda i: switched.append(i))
    panel.draw(screen)  # 算出 _center/_radius_base
    for i in range(len(g.worlds)):
        px, py = panel._planet_xy(i)
        panel.hit((int(px), int(py)))
    check("点行星 1 圆点触发切换回调", switched == [1], f"回调 {switched}")
    check("点当前行星圆点不切换", len(switched) == 1)
    # 真实 Game 的切换路径
    g._switch_planet(1)
    check("Game._switch_planet 切到世界 1",
          g.world_index == 1 and g.grid is g.worlds[1].grid)

    # ---------- 6. HUD 状态栏 ----------
    print("[6] HUD 状态栏（含行星名）:")
    g._activate_world(0)
    g._draw_ui()
    check("故乡星 HUD 渲染不崩", True)
    g._activate_world(1)
    g._draw_ui()
    check("余烬星 HUD 渲染不崩", True)

    print()
    print("======== 多行星自检 ========")
    if fails:
        print(f"FAIL {len(fails)} 项: {fails}")
        return 1
    print("PASS 多行星全部通过  exit=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())