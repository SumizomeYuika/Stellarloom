"""触屏 UI：底部建造栏、顶栏。

尺寸全部按屏幕短边比例算，保证不同分辨率下热区够大。
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef

# 建筑分类：底栏只显示大类，点大类后在底栏上方展开具体建筑
CATEGORIES = [
    ("物流带", (C.B_BELT, C.B_INSERTER)),
    ("生产", (C.B_MINER, C.B_FURNACE, C.B_ASSEMBLER)),
    ("液体", (C.B_PIPE, C.B_TANK, C.B_FLUID_PUMP)),
    ("电力", (C.B_SOLAR, C.B_WIND, C.B_POWER_POLE)),
    ("物流塔", (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST, C.B_LAUNCH_PAD)),
    ("存储", (C.B_CHEST,)),
    ("科研·戴森", (C.B_LAB, C.B_EMITTER)),
    ("行星", (C.B_PLANET_ENGINE,)),
]

# 全部建筑（供快捷键/校验用，顺序固定）
TOOLBAR = [b for _, items in CATEGORIES for b in items]

TOP_BAR_H_RATIO = 0.075
BOTTOM_BAR_H_RATIO = 0.14
SUB_BAR_H_RATIO = 0.10        # 大类展开出来的子按钮条高度


class TouchUI:
    def __init__(self, screen_size: tuple[int, int], fonts):
        self.size = screen_size
        self.fonts = fonts
        self.tech = None  # 由 game 注入 TechTree
        self.stock: dict[int, int] = {}  # 由 game 每帧注入物品栏（显示库存角标）
        self.selected = C.B_BELT
        self.direction = 0
        self.paused = False
        self.view_mode = False  # 查看模式：只移相机/看面板，不放置
        self.bag_open = False    # 背包面板开着（由 game 同步）
        self.craft_open = False  # 合成面板开着（由 game 同步）
        self.orbit_open = False  # 轨道图开着（由 game 同步）
        self.cat_open: int | None = None  # 展开的大类下标（None = 收起）
        self.top_def = uidef.load_def("touch_top.json")  # 顶栏按钮（M6.21）
        self.top_buttons: list[tuple[str, pygame.Rect]] = []
        self._layout()

    def _layout(self):
        sw, sh = self.size
        self.top_h = max(int(sh * TOP_BAR_H_RATIO), 40)
        self.bottom_h = max(int(sh * BOTTOM_BAR_H_RATIO), 70)
        self.bottom_y = sh - self.bottom_h
        self.sub_h = max(int(sh * SUB_BAR_H_RATIO), 52)

        # 展开的子按钮条（点大类后才出现），占在底栏正上方
        self.sub_y = self.bottom_y - self.sub_h

        # 底栏：只放大类按钮，平铺一行
        n = len(CATEGORIES)
        pad = 6
        btn_w = (sw - pad * (n + 1)) / n
        btn_h = self.bottom_h - pad * 2
        self.buttons: list[tuple[pygame.Rect, int]] = []  # (rect, 分类下标)
        for i in range(n):
            x = pad + i * (btn_w + pad)
            rect = pygame.Rect(int(x), int(self.bottom_y + pad),
                               int(btn_w), int(btn_h))
            self.buttons.append((rect, i))

        # 顶栏右侧按钮：顺序 / 文案 / 参数由 defs/touch_top.json 定义，
        # 从右往左排，宽度按屏幕宽自适应（防止顶出屏幕）
        bh = self.top_h - 10
        meta = self.top_def.meta
        gap = meta["gap"]
        btn_defs = self.top_def.buttons
        n_top = len(btn_defs)
        bw = max(meta["btn_min_w"],
                 min(int(bh * meta["w_h_ratio"]),
                     int((sw * 0.74 - gap * (n_top - 1)) / n_top)))
        x = sw - meta["pad_right"] - bw
        self.top_buttons.clear()
        for b in btn_defs:
            self.top_buttons.append(
                (b["action"],
                 pygame.Rect(int(x), meta["pad_top"], int(bw), int(bh))))
            x -= bw + gap
        self.remove_mode = False

    def sync_open_category(self, btype: int):
        """选中建筑后，把底栏展开到它所在的大类（键盘快捷键用）。"""
        for ci, (_, items) in enumerate(CATEGORIES):
            if btype in items:
                # 所有大类都展开（即使只有一个建筑也展开，保持一致）
                self.cat_open = ci
                return

    def _sub_rects(self) -> list[tuple[pygame.Rect, int]]:
        """当前展开分类的子建筑按钮区（没展开时为空）。"""
        if self.cat_open is None:
            return []
        items = CATEGORIES[self.cat_open][1]
        sw = self.size[0]
        pad = 6
        n = len(items)
        btn_w = (sw - pad * (n + 1)) / n
        btn_h = self.sub_h - pad * 2
        out = []
        for i, b in enumerate(items):
            x = pad + i * (btn_w + pad)
            rect = pygame.Rect(int(x), int(self.sub_y + pad),
                               int(btn_w), int(btn_h))
            out.append((rect, b))
        return out

    # ---------- 命中测试 ----------

    def hit(self, pos) -> tuple[str, int | None] | None:
        # 展开中的子按钮优先
        for rect, b in self._sub_rects():
            if rect.collidepoint(pos):
                if b == self.selected:
                    # 再点已选中的子建筑 → 取消并收起
                    self.cat_open = None
                    return ("deselect", b)
                return ("select", b)
        # 大类按钮
        for rect, ci in self.buttons:
            if rect.collidepoint(pos):
                # 再点一次同一个大类收起；否则展开（哪怕只有一种建筑也展开）
                if self.cat_open == ci:
                    self.cat_open = None
                    return ("noop", None)
                self.cat_open = ci
                return ("noop", None)
        # 顶栏按钮（顺序/文案来自 defs JSON）
        for action, rect in self.top_buttons:
            if rect.collidepoint(pos):
                return (action, None)
        # 点到空白处（世界）→ 收起展开
        self.cat_open = None
        return None

    def in_bars(self, pos) -> bool:
        """点是否落在 UI 区域（不该穿透到世界）。"""
        if pos[1] < self.top_h:
            return True
        if pos[1] > self.bottom_y:
            return True
        if self.cat_open is not None and pos[1] > self.sub_y:
            return True
        return False

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface, stats: str):
        sw, sh = self.size
        font = self.fonts.get(20)
        small = self.fonts.get(16)

        # 顶栏
        top = pygame.Surface((sw, self.top_h), pygame.SRCALPHA)
        top.fill((18, 20, 28, 220))
        screen.blit(top, (0, 0))
        # 状态文字限制在按钮左侧，超长裁掉（按钮多了会顶过来）
        text_max_w = self.top_buttons[-1][1].left - 20
        stats_surf = font.render(stats, True, C.C_TEXT)
        if stats_surf.get_width() > text_max_w:
            clip = screen.subsurface(pygame.Rect(10, 8, max(text_max_w, 40),
                                                 stats_surf.get_height()))
            clip.blit(stats_surf, (0, 0))
        else:
            screen.blit(stats_surf, (10, 8))

        for action, rect in self.top_buttons:
            self._btn(screen, rect, self._top_text(action),
                      self._top_active(action))

        # 底栏
        bottom = pygame.Surface((sw, self.bottom_h), pygame.SRCALPHA)
        bottom.fill((18, 20, 28, 220))
        screen.blit(bottom, (0, self.bottom_y))

        # 大类按钮：高亮条件 = 当前选中的建筑属于这个大类，或这个大类正展开
        for rect, ci in self.buttons:
            name, items = CATEGORIES[ci]
            self._btn(screen, rect, name,
                      self.selected in items or self.cat_open == ci)

        # 展开的子按钮条（画在底栏上方）
        sub = self._sub_rects()
        if sub:
            panel = pygame.Surface((sw, self.sub_h), pygame.SRCALPHA)
            panel.fill((24, 28, 38, 238))
            screen.blit(panel, (0, self.sub_y))
            pygame.draw.line(screen, (70, 80, 105),
                             (0, self.sub_y), (sw, self.sub_y), 1)
            for rect, b in sub:
                locked = self.tech is not None and not self.tech.is_unlocked(b)
                name = C.BUILDING_NAMES[b]
                if locked:
                    name = "🔒" + name
                self._btn(screen, rect, name, b == self.selected and not locked)
                if not locked:
                    have = self._stock_of(b)
                    self._badge(screen, rect, have, small)

    def _btn(self, screen, rect: pygame.Rect, text: str, active: bool):
        small = self.fonts.get(16)
        bg = (70, 110, 160) if active else (40, 46, 60)
        pygame.draw.rect(screen, bg, rect, border_radius=6)
        pygame.draw.rect(screen, (90, 100, 130), rect, 1, border_radius=6)
        surf = small.render(text, True, C.C_TEXT)
        screen.blit(surf, (rect.centerx - surf.get_width() // 2,
                           rect.centery - surf.get_height() // 2))

    def _top_text(self, action: str) -> str:
        """顶栏按钮动态文案（静态文案在 defs JSON 里）。"""
        if action == "pause":
            return "继续" if self.paused else "暂停"
        if action == "rotate":
            return f"方向{'→↓←↑'[self.direction]}"
        for b in self.top_def.buttons:
            if b["action"] == action:
                return b["text"]
        return action

    def _top_active(self, action: str) -> bool:
        return {
            "pause": self.paused,
            "remove": self.remove_mode,
            "view": self.view_mode,
            "orbit": self.orbit_open,
            "bag": self.bag_open,
            "craft": self.craft_open,
        }.get(action, False)

    def _stock_of(self, btype: int) -> int | None:
        """该建筑在背包里还剩几个；None 表示这种建筑不消耗物品。"""
        item = C.BUILD_ITEM.get(btype)
        if item is None:
            return None
        return self.stock.get(item, 0)

    def _badge(self, screen, rect: pygame.Rect, have: int | None, font):
        """右下角库存角标：0 个显示红底，够用显示淡灰。"""
        if have is None:
            return
        txt = str(have)
        surf = font.render(txt, True, (255, 255, 255))
        w = max(surf.get_width() + 8, 16)
        h = surf.get_height() + 2
        box = pygame.Rect(rect.right - w - 2, rect.bottom - h - 2, w, h)
        bg = (170, 60, 60) if have <= 0 else (50, 60, 78)
        pygame.draw.rect(screen, bg, box, border_radius=4)
        screen.blit(surf, (box.centerx - surf.get_width() // 2,
                           box.centery - surf.get_height() // 2))