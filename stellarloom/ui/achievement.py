"""右上角成就式提示（M6.11）。

仿 Minecraft 的"进度达成"弹窗：从屏幕右侧滑入，堆叠在右上角，几秒后淡出。
研究完成、队列自动接续都靠它提示，比居中单行 toast 更有分量。
"""

from __future__ import annotations

import pygame

DURATION = 4.0       # 每条停留多久（秒）
SLIDE_IN = 0.28      # 滑入时长
FADE_OUT = 0.45      # 淡出时长


class AchievementPopup:
    def __init__(self, fonts):
        self.fonts = fonts
        # 每项：{"title": str, "desc": str, "age": float}
        self.items: list[dict] = []

    def push(self, title: str, desc: str = ""):
        self.items.append({"title": title, "desc": desc, "age": 0.0})
        # 最多堆 5 条，多了丢最老的
        if len(self.items) > 5:
            self.items.pop(0)

    def update(self, dt: float):
        for it in self.items:
            it["age"] += dt
        self.items = [it for it in self.items if it["age"] < DURATION]

    def draw(self, screen: pygame.Surface):
        if not self.items:
            return
        sw = screen.get_width()
        card_w, card_h = 300, 56
        gap = 8
        x = sw - card_w - 12
        y = 12
        title_font = self.fonts.get(18)
        desc_font = self.fonts.get(14)
        for it in self.items:
            age = it["age"]
            # 滑入：从右侧滑到位
            slide = 0.0
            if age < SLIDE_IN:
                slide = card_w * (1.0 - age / SLIDE_IN)
            # 淡出
            alpha = 255
            remain = DURATION - age
            if remain < FADE_OUT:
                alpha = int(255 * max(remain / FADE_OUT, 0.0))
            card = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
            # 深棕底 + 金色边，Minecraft 风格
            card.fill((38, 30, 18, alpha))
            pygame.draw.rect(card, (200, 170, 80, alpha),
                             card.get_rect(), 2, border_radius=6)
            # 左侧图标块
            pygame.draw.rect(card, (235, 210, 120, alpha), (10, 12, 32, 32),
                             border_radius=4)
            if it["title"]:
                card.blit(title_font.render(it["title"], True,
                                            (255, 240, 200, alpha)), (52, 8))
            if it["desc"]:
                card.blit(desc_font.render(it["desc"], True,
                                           (200, 200, 175, alpha)), (52, 30))
            screen.blit(card, (int(x + slide), int(y)))
            y += card_h + gap
