#!/usr/bin/env python3
"""UI 定义层自检（M6.21）：JSON 控件加载器 + 存档面板/顶栏 JSON 驱动验证。

跑法：
    $env:PYTHONIOENCODING='utf-8'   （GBK 控制台先设，否则 ✓ 报错）
    python tools/_uidefcheck.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from stellarloom.ui import uidef  # noqa: E402
from stellarloom.render.fonts import FontBook  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def main():
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    fonts = FontBook()

    # ---------- 1. 加载器单元 ----------
    print("[1] 加载器:")
    d = uidef.load_def("save_panel.json")
    check(d.ctrl("close") is not None and d.ctrl("close").type == "button",
          "close 控件缺失/类型错")
    check(d.ctrl("title").type == "label", "title 类型错")
    check(d.ctrl("slots").type == "list", "slots 类型错")
    check(d.meta_c["panel_bg"] == (14, 18, 32), "meta 颜色解析错")
    print(f"  控件 {[c.id for c in d.controls]}  meta 颜色 OK")

    # 锚点换算：close 在右上角（tr x:-34）；footer 在底部（tl y:-34）
    pr = pygame.Rect(50, 60, 470, 520)
    close_r = d.rect(d.ctrl("close"), pr)
    check(close_r.right == pr.right - 34 and close_r.top == pr.top + 3,
          f"close 锚点错: {close_r}")
    foot = d.ctrl("footer")
    fx, fy = d.label_pos(foot, pr, 100, 12)
    check(fx == pr.left + 14 and fy == pr.bottom - 34,
          f"footer 锚点错: {(fx, fy)}")
    hit = uidef.hit_control(d, pr, close_r.center)
    check(hit == "close", f"close 命中错: {hit}")
    check(uidef.hit_control(d, pr, (pr.left + 2, pr.top + 2)) is None,
          "空白处误命中")

    # 缺文件 / 坏 JSON / 缺 w/h / 未知类型 都要报错
    for name in ("no_such_def.json",):
        try:
            uidef.load_def(name)
            check(False, f"缺文件 {name} 没报错")
        except ValueError:
            check(True, "")
    with tempfile.NamedTemporaryFile("w", suffix=".json",
                                     delete=False, encoding="utf-8") as f:
        f.write("{ not json")
        p_bad = f.name
    try:
        uidef.load_def(p_bad)
        check(False, "坏 JSON 没报错")
    except ValueError:
        check(True, "")
    os.unlink(p_bad)
    try:
        uidef.UiDef({"controls": [{"id": "x", "type": "button",
                                   "x": 0, "y": 0}]}, "t3").rect(
            uidef.UiDef({"controls": [{"id": "x", "type": "button",
                                       "x": 0, "y": 0}]}, "t3").ctrl("x"),
            pr)
        check(False, "缺 w/h 没报错")
    except ValueError:
        check(True, "")
    try:
        uidef.UiDef({"controls": [{"id": "x", "type": "nope",
                                   "x": 0, "y": 0}]}, "t2")
        check(False, "未知 type 没报错")
    except ValueError:
        check(True, "")
    print("  缺文件/坏 JSON/缺 w/h/未知 type 全部按预期报错")

    # ---------- 2. 动态加载：改 JSON 就改 UI ----------
    print("[2] 动态加载（临时 JSON 改标题/尺寸生效）:")
    tmpdef = {
        "name": "demo",
        "meta": {"text": "#FFFFFF"},
        "controls": [
            {"id": "t", "type": "label", "x": 5, "y": 5, "font": 14,
             "text": "Hello"},
            {"id": "b", "type": "button", "x": 10, "y": 10, "w": 60,
             "h": 24, "text": "OK"},
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(tmpdef, f)
        p = f.name
    d1 = uidef.load_def(p)
    r1 = d1.rect(d1.ctrl("b"), pr)
    tmpdef["controls"][1]["x"] = 100          # 改 JSON
    with open(p, "w", encoding="utf-8") as f:
        json.dump(tmpdef, f)
    d2 = uidef.load_def(p)
    r2 = d2.rect(d2.ctrl("b"), pr)
    check(r2.left == pr.left + 100 and r2.left != r1.left,
          "改 JSON 后按钮位置没变")
    os.unlink(p)
    print(f"  按钮 x=10 -> x=100：left {r1.left} -> {r2.left} OK")

    # ---------- 3. 存档面板（JSON 驱动） ----------
    print("[3] 存档面板:")
    from stellarloom.ui.save_panel import SavePanel
    from stellarloom.save import SaveManager
    tmp = tempfile.mkdtemp(prefix="slm_uidef_")
    sm = SaveManager(tmp)
    # 槽 1/2 有档，槽 3-6 空
    from tools._savecheck import FakeGame, build_world  # noqa: E402
    fg = FakeGame()
    build_world(fg)
    sm.save(fg, sm.slot_file(0))
    sm.save(fg, sm.slot_file(1))

    panel = SavePanel(fonts)
    calls = []
    panel.show((640, 480), "save", sm.slot_list(), 0, lambda i: calls.append(i))
    panel.draw(screen)
    # 420 高面板最多排 5 行（底部留位给自动档/旧档按钮，不重叠）
    last_row = panel._rows[-1][0]
    auto_r0 = panel.defs.rect(panel.defs.ctrl("auto"), panel.rect)
    check(len(panel._rows) >= 5 and last_row.bottom <= auto_r0.top,
          f"存模式行数与布局: {len(panel._rows)} 行，末行底 {last_row.bottom}"
          f" vs auto 顶 {auto_r0.top}")
    row0 = panel._rows[0][0]
    panel.hit(row0.center)
    check(calls == [0], f"点槽1：应触发回调 0，实际 {calls}")

    calls.clear()
    panel.show((640, 480), "load", sm.slot_list(), 0, lambda i: calls.append(i))
    panel.draw(screen)
    check(len(panel._rows) == 2, f"读模式应有档 2 行可点，实际 "
          f"{len(panel._rows)}")
    # 底部捷径
    auto_r = panel.defs.rect(panel.defs.ctrl("auto"), panel.rect)
    panel.hit(auto_r.center)
    check(calls == [-1], f"点自动档捷径应回调 -1，实际 {calls}")
    legacy_r = panel.defs.rect(panel.defs.ctrl("legacy"), panel.rect)
    panel.hit(legacy_r.center)
    check(calls == [-1, -2], f"点旧档捷径应回调 -2，实际 {calls}")
    # 关闭按钮
    panel.show((640, 480), "save", sm.slot_list(), 0, lambda i: None)
    panel.draw(screen)
    close_r = panel.defs.rect(panel.defs.ctrl("close"), panel.rect)
    panel.hit(close_r.center)
    check(not panel.open, "点 ✕ 应关面板")

    # ---------- 4. 顶栏按钮（JSON 顺序） ----------
    print("[4] 顶栏:")
    from stellarloom.ui.touch_ui import TouchUI
    ui = TouchUI((640, 480), fonts)
    acts = [a for a, _ in ui.top_buttons]
    check(acts == ["pause", "rotate", "remove", "view", "tech", "orbit",
                   "bag", "craft", "save", "load", "menu"],
          f"顶栏顺序错: {acts}")
    # 点最左按钮（菜单）应返回 ("menu", None)
    r = ui.top_buttons[-1][1]
    check(ui.hit(r.center) == ("menu", None), "点末按钮应返回菜单 action")
    # 动态文案：暂停/继续、方向字
    ui.paused = True
    check(ui._top_text("pause") == "继续", "暂停态文案错")
    ui.paused = False
    ui.direction = 2
    check(ui._top_text("rotate") == "方向←", "方向文案错")
    print(f"  顺序 {acts}  OK")

    # ---------- 5. 皮肤化 + 迁移面板（M6.26） ----------
    print("[5] 主题兜底 + 迁移面板:")
    # theme.json 兜底：面板没写的颜色从全局主题补
    fd = uidef.load_def("filter_panel.json")
    check(fd.meta_c.get("panel_bg") is not None
          and fd.meta_c.get("text") is not None
          and fd.meta_c.get("radius") == 8,
          f"主题兜底没生效: {fd.meta_c.get('panel_bg')}")
    # 面板自己的 meta 优先于主题
    ld = uidef.load_def("lab_panel.json")
    check(ld.meta_c["panel_border"] == (110, 90, 160) and
          ld.meta_c["title"] == (210, 190, 239),
          f"面板 meta 覆盖主题失败: {ld.meta_c.get('panel_border')}")
    # 四个迁移面板的控件齐全
    for name, ids in (("filter_panel", ("title", "current", "clear", "grid")),
                      ("bag_panel", ("title", "list")),
                      ("lab_panel", ("title", "mode_r", "mode_p")),
                      ("tower_panel", ("title", "stock_h"))):
        d = uidef.load_def(name)
        have = {c.id for c in d.controls}
        check(set(ids) <= have, f"[{name}] 缺控件 {set(ids) - have}")

    # color override（单控件换色，塔标题绿/橙用）
    td = uidef.load_def("tower_panel.json")
    pr = pygame.Rect(100, 100, 320, 280)
    uidef.draw_controls(screen, td, pr, fonts,
                        {"text": {"title": "供应塔 (1,2)"},
                         "color": {"title": (0, 255, 0)}})

    # 四个面板 draw 冒烟（真实数据，必须不炸）
    from stellarloom.ui.filter_panel import FilterPanel
    from stellarloom.ui.lab_panel import LabPanel
    from stellarloom.ui.tower_panel import TowerPanel

    class _StubLabs:
        def set_mode(self, *a): pass
        def set_recipe(self, *a): pass
        def add_item(self, *a): return 0
        def take_item(self, *a): return 0
        def take_outputs(self, *a): return {}
        def _wanted_packs(self): return {}

    class _StubTower:
        mode = "supply"
        x = y = 5
        inventory = {2: 7}
        filter = None
        drones = []

    fp = FilterPanel(fonts)
    fp.show((640, 480), (5, 5), 2)
    fp.draw(screen)
    from stellarloom.ui.craft_panel import BagPanel
    bp = BagPanel(fonts)
    bp.show((640, 480), {2: 5, 3: 1})
    bp.draw(screen)
    lp = LabPanel(fonts)
    lp.show({"mode": 1, "stored": {1: 2}, "inputs": {}, "outputs": {},
             "recipe": None, "progress": 0.0}, _StubLabs(), 1, 1,
            (640, 480), {})
    lp.draw(screen)
    tp = TowerPanel(fonts)
    tp.show(_StubTower(), (640, 480))
    tp.draw(screen)
    check(True, "4 面板 draw 冒烟 OK")
    print("  主题兜底 / 面板覆盖 / color override / draw 冒烟 OK")

    print()
    if bad:
        print(f"FAIL {bad} 项")
        return 1
    print("PASS UI 定义层全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())