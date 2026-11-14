"""分拣器过滤面板：给某个分拣器指定"只抓某种物品"。

打开方式：查看模式下点分拣器。
点物品格 = 设为过滤；点"不限" = 清除过滤。点面板外关闭。

M6.26：外观（标题/配色/布局参数）走 `defs/filter_panel.json`
（UI 定义层，颜色取 theme.json 兜底）；物品网格是动态列表，行内容
业务画（颜色全取 meta_c，改主题一处换全肤色）。
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef

COLS = 3


class FilterPanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("filter_panel.json")
        self.open = False
        self.rect = pygame.Rect(0, 0, 460, 420)
        self.cell: tuple[int, int] | None = None   # 正在编辑的分拣器格子
        self.current = 0                           # 当前过滤物品，0 = 不限
        # (rect, item) 列表，item=0 表示"不限"
        self.rows: list[tuple[pygame.Rect, int]] = []

    def show(self, screen_size, cell: tuple[int, int], current: int):
        self.cell = cell
        self.current = current
        self.open = True
        sw, sh = screen_size
        w = min(460, int(sw * 0.9))
        h = min(420, int(sh * 0.78))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.open = False
        self.cell = None

    def hit(self, pos):
        """返回要设置的物品 ID（0=不限）；点面板外返回 None 且关闭。"""
        if not self.open:
            return None
        if not self.rect.collidepoint(pos):
            self.close()
            return None
        for r, item in self.rows:
            if r.collidepoint(pos):
                return item
        return None

    def _item_list(self) -> list[int]:
        # 只列非建筑物品（建筑物品进不了传送带管道，做过滤没意义）
        items = [i for i in C.ITEM_NAMES if i < 100]
        items.sort()
        return items

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        r = self.rect
        m = self.defs.meta_c
        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)

        # 静态控件（标题/当前/不限按钮/脚注）
        overrides = {"text": {}, "active": {}}
        overrides["text"]["current"] = \
            f"当前：{'不限' if self.current <= 0 else C.ITEM_NAMES.get(self.current, '?')}"
        overrides["active"]["clear"] = self.current <= 0
        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        # "不限"按钮的行（复用静态按钮的 rect 参与命中）
        self.rows = [(self.defs.rect(self.defs.ctrl("clear"), r), 0)]

        # 物品网格（动态行，参数在 defs 的 grid 列表控件）
        tiny = self.fonts.get(12)
        g = self.defs.ctrl("grid").raw
        cols = g.get("cols", COLS)
        pad = g["pad"]
        item_h = g["item_h"]
        gap = g["gap"]
        gw = r.width - pad * 2
        cell_w = gw // cols
        y = r.top + g["y"]
        for idx, item in enumerate(self._item_list()):
            col = idx % cols
            row = idx // cols
            cr = pygame.Rect(r.left + pad + col * cell_w,
                             y + row * (item_h + gap), cell_w - 4, item_h)
            if cr.bottom > r.bottom - 26:
                break  # 放不下就截断，不滚动（物品就这十几种）
            act = item == self.current
            color = C.ITEM_COLORS.get(item, (180, 180, 180))
            pygame.draw.rect(screen, m["item_active_bg"] if act else m["item_bg"],
                             cr, border_radius=4)
            pygame.draw.rect(screen, color if act else m["item_frame"],
                             cr, 1 if not act else 2, border_radius=4)
            pygame.draw.rect(screen, color, (cr.left + 5, cr.top + 9, 12, 12))
            name = C.ITEM_NAMES.get(item, "?")
            text = tiny.render(name, True,
                               m["text"] if act else m["hint"])
            screen.blit(text, (cr.left + 22, cr.top + 8))
            self.rows.append((cr, item))