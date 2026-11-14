"""主菜单（M6.25）：启动封面 + 「开始新游戏 / 继续游戏 / 读档 / 退出」。

外观（遮罩/标题/按钮/配色）全部来自 defs/main_menu.json（UI 定义层机制）。

行为约定：
- show(screen_size, have_save)：have_save=False 时"继续游戏"按钮禁用（灰 + 不响应）。
- hit(pos) -> action（"new"/"continue"/"load"/"quit"）或 None。
- 菜单打开时由 Game 负责：手势全面拦截 + 世界模拟暂停（本类只管 UI）。
"""

from __future__ import annotations

import pygame

from . import uidef


class MainMenu:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("main_menu.json")
        self.open = False
        self._size = (640, 480)
        self._have_save = False

    # ---------- 生命周期 ----------

    def show(self, screen_size: tuple[int, int], have_save: bool = False):
        self.open = True
        self._size = screen_size
        self._have_save = have_save

    def close(self):
        self.open = False

    def _rect(self) -> pygame.Rect:
        return pygame.Rect(0, 0, *self._size)

    def _overrides(self):
        return {"disabled": {"continue": not self._have_save}}

    # ---------- 交互 ----------

    def hit(self, pos):
        """返回命中的动作（new / continue / load / quit），禁用的不响应。"""
        if not self.open:
            return None
        return uidef.hit_control(self.defs, self._rect(), pos,
                                 self._overrides())

    # ---------- 渲染 ----------

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        m = self.defs.meta_c
        overlay = pygame.Surface(self._size, pygame.SRCALPHA)
        overlay.fill(m["mask"])
        screen.blit(overlay, (0, 0))
        uidef.draw_controls(screen, self.defs, self._rect(), self.fonts,
                            self._overrides())