#!/usr/bin/env python3
"""_menuecheck：主菜单自检（M6.25）。

跑法：python tools/_menuecheck.py（dummy pygame + 真实渲染路径）。

覆盖：
[1] 定义加载：main_menu.json 7 个控件、标题 cc 锚点居中
[2] 启动即主菜单 + 命中：4 按钮 action；菜单关/屏外 → None
[3] 禁用态：无存档时"继续游戏"按钮不响应（overrides disabled）
[4] 菜单拦截：点按不放置 / 拖动不动相机 / 捏合不缩放 / 世界模拟暂停
[5] 关闭恢复：menu.close 后世界照常响应、sim 照常推进
[6] 顶栏入口：_apply_ui_action("menu") 打开菜单（且关掉已有面板）
[7] 新游戏：重建 sim、世界清零、存档文件保留
[8] 继续游戏：读最新自动档、菜单关闭
[9] ESC 关菜单进游戏
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
pygame.init()
screen = pygame.display.set_mode((640, 480))

from stellarloom import config as C  # noqa: E402
from stellarloom.core import Game  # noqa: E402
from stellarloom.input.gestures import DragEvent, PinchEvent, TapEvent  # noqa: E402
from stellarloom.save import SaveManager  # noqa: E402

RESULT = []


def check(name, ok, detail=""):
    RESULT.append(ok)
    print(f"  {name}: {'OK' if ok else '!! FAIL'} {detail}")


def game_with_saves(tmpdir=None, have_save=False) -> Game:
    g = Game(screen)
    if tmpdir is not None:
        sm = SaveManager(tmpdir)
        g.saves = sm
        g.sim.saves = sm
    g.menu.show(screen.get_size(), have_save=have_save)
    return g


def btn_center(g: Game, cid: str):
    m = g.menu
    return m.defs.rect(m.defs.ctrl(cid), m._rect()).center


def cell_center(g: Game, gx: int, gy: int) -> tuple[int, int]:
    wx = gx * C.TILE + C.TILE / 2
    wy = gy * C.TILE + C.TILE / 2
    return tuple(int(v) for v in
                 g.camera.world_to_screen(wx, wy, screen.get_size()))


def check_defs():
    """[1] 定义加载 + cc 居中锚点。"""
    m = Game(screen).menu
    ids = [c.id for c in m.defs.controls]
    check("控件齐全", ids == ["title", "subtitle", "new", "continue",
                              "load", "mods", "quit", "footer"], f"{ids}")
    # 标题（label）用 cc 锚点：渲染文字后中心应落在面板水平中线
    title = m.defs.ctrl("title")
    surf = m.fonts.get(title.font).render(title.text, True, (255, 255, 255))
    x, y = m.defs.label_pos(title, m._rect(),
                            surf.get_width(), surf.get_height())
    cx = x + surf.get_width() / 2
    check("标题 cc 水平居中",
          title.anchor == "cc" and abs(cx - screen.get_width() / 2) <= 1,
          f"center_x={cx:.1f}")
    # 5 个按钮纵向不重叠
    ys = [m.defs.rect(m.defs.ctrl(c), m._rect()).top
          for c in ("new", "continue", "load", "mods", "quit")]
    check("按钮纵向排开", ys == sorted(ys) and len(set(ys)) == 5, f"{ys}")


def check_start_and_hit():
    """[2] 启动即主菜单 + 命中/失中（有档态：全部按钮可点）。"""
    g = game_with_saves(have_save=True)
    check("启动即主菜单", g.menu.open)
    check("新游戏按钮", g.menu.hit(btn_center(g, "new")) == "new")
    check("续玩按钮", g.menu.hit(btn_center(g, "continue")) == "continue")
    check("读档按钮", g.menu.hit(btn_center(g, "load")) == "load")
    check("退出按钮", g.menu.hit(btn_center(g, "quit")) == "quit")
    check("屏外点失中", g.menu.hit((0, 0)) is None,
          f"got {g.menu.hit((0, 0))}")
    g.menu.close()
    check("菜单关后 hit=None", g.menu.hit(btn_center(g, "new")) is None)


def check_disabled_continue():
    """[3] 无存档时"继续游戏"禁用。"""
    g = game_with_saves(have_save=False)
    check("无档 continue 失中",
          g.menu.hit(btn_center(g, "continue")) is None)
    g.menu.show(screen.get_size(), have_save=True)
    check("有档 continue 可点",
          g.menu.hit(btn_center(g, "continue")) == "continue")


def check_menu_blocks_world():
    """[4] 菜单开着：不放置/不拖动/不缩放/不推进。"""
    g = game_with_saves()
    cam0 = (g.camera.x, g.camera.y, g.camera.zoom)
    gx = next(x for x in range(2, 40) if g.sim.grid.can_place(x, 30))
    # 点按世界格：不放建筑
    g.selected_building = C.B_FURNACE
    g.sim.inventory[C.BUILD_ITEM[C.B_FURNACE]] = 5
    pos = cell_center(g, gx, 30)
    g._handle_gesture(TapEvent(pos), 1 / 60)
    check("菜单吃世界点按",
          g.sim.grid.get(gx, 30) == C.B_EMPTY)
    # 拖动：相机不动
    g._handle_gesture(DragEvent((320, 240), (300, 210), (-30, -40)), 1 / 60)
    check("菜单吃拖动",
          (g.camera.x, g.camera.y) == (cam0[0], cam0[1]))
    # 捏合：不缩放
    g._handle_gesture(PinchEvent((320, 240), 1.3), 1 / 60)
    check("菜单吃捏合", abs(g.camera.zoom - cam0[2]) < 1e-6)
    # 世界模拟暂停：跑两帧库存不掉（菜单里没有任何自动化在推进）
    before = g.sim.inventory.get(C.I_IRON_ORE, 0)
    g._update(0.5)
    after = g.sim.inventory.get(C.I_IRON_ORE, 0)
    check("菜单暂停模拟", before == after)


def check_close_restores():
    """[5] 菜单关掉后世界恢复响应。"""
    g = game_with_saves()
    g.menu.close()
    gx = next(x for x in range(2, 40) if g.sim.grid.can_place(x, 32))
    g.selected_building = C.B_FURNACE
    g.sim.inventory[C.BUILD_ITEM[C.B_FURNACE]] = 5
    # 相机对准格子中心，保证点按不落在 UI 条
    g.camera.x = gx * C.TILE + C.TILE / 2
    g.camera.y = 32 * C.TILE + C.TILE / 2
    pos = cell_center(g, gx, 32)
    assert not g.ui.in_bars(pos), f"点按落进 UI 条: {pos}"
    g._handle_gesture(TapEvent(pos), 1 / 60)
    ok = g.sim.grid.get(gx, 32) == C.B_FURNACE
    check("关闭后点按可放置", ok)
    # 放置成功会弹机器面板（面板开着不许拖世界，M6.23 规则）：先关掉再拖
    g.machine_panel.close()
    cam0 = g.camera.x
    g._handle_gesture(DragEvent((320, 240), (300, 210), (-30, -40)), 1 / 60)
    check("关闭后可拖动", g.camera.x != cam0)


def check_topbar_entry():
    """[6] 顶栏"菜单"按钮 → _apply_ui_action("menu")。"""
    g = game_with_saves(have_save=False)
    g.menu.close()
    # 先开个面板，看是否被顺带关掉
    g.bag_panel.show(screen.get_size(), g.inventory)
    g._apply_ui_action("menu", None)
    check("顶栏打开菜单", g.menu.open and not g.bag_panel.open)


def check_new_game():
    """[7] 新游戏：重建 sim、世界清零、存档文件保留。"""
    tmp = tempfile.mkdtemp(prefix="slm_menu_")
    g = game_with_saves(tmpdir=tmp)
    g.menu.close()
    old_sim = g.sim
    gx = next(x for x in range(2, 40) if g.sim.grid.can_place(x, 34))
    g.sim.place_building(C.B_FURNACE, gx, 34, 0)
    g.saves.save(g.sim, g.saves.slot_file(0))   # 留一个存档（slot_1.slm）
    slot_path = os.path.join(tmp, "slot_1.slm")
    g._on_menu_action("new")
    check("新游戏关菜单", not g.menu.open)
    check("sim 已重建", g.sim is not old_sim)
    check("世界清零", g.sim.grid.get(gx, 34) == C.B_EMPTY)
    check("同源保持",
          g.inventory is g.sim.inventory and g.worlds is g.sim.worlds
          and g.saves is g.sim.saves)
    check("存档文件保留", os.path.exists(slot_path))


def check_continue():
    """[8] 继续游戏：读最新自动档。"""
    tmp = tempfile.mkdtemp(prefix="slm_menu_")
    g = game_with_saves(tmpdir=tmp)
    g.menu.close()
    gx = next(x for x in range(2, 40) if g.sim.grid.can_place(x, 36))
    g.sim.place_building(C.B_FURNACE, gx, 36, 0)
    g.saves.save_auto(g.sim)         # 造一个自动档
    g.sim.remove_building(gx, 36)    # 拆掉：进度只存在于档里
    g.menu.show(screen.get_size(), have_save=True)
    g._on_menu_action("continue")
    check("继续关菜单", not g.menu.open)
    check("读档恢复建筑", g.sim.grid.get(gx, 36) == C.B_FURNACE)
    check("存档目录保留", os.path.isdir(tmp))


def check_esc():
    """[9] ESC 关菜单。"""
    g = game_with_saves()
    g._on_key(pygame.K_ESCAPE)
    check("ESC 关菜单", not g.menu.open)


def main() -> int:
    print("[1] 定义加载")
    check_defs()
    print("[2] 启动 + 命中")
    check_start_and_hit()
    print("[3] 禁用态")
    check_disabled_continue()
    print("[4] 菜单拦截世界")
    check_menu_blocks_world()
    print("[5] 关闭恢复")
    check_close_restores()
    print("[6] 顶栏入口")
    check_topbar_entry()
    print("[7] 新游戏")
    check_new_game()
    print("[8] 继续游戏")
    check_continue()
    print("[9] ESC")
    check_esc()
    ok = all(RESULT)
    print("PASS 主菜单自检全部通过" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())