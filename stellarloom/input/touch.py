"""触摸状态：维护触摸模式与虚拟摇杆式的相机拖动状态。"""

from __future__ import annotations

import pygame


class TouchState:
    """记录最近输入源，用于自动切换 UI 模式。"""

    def __init__(self, switch_delay_ms: int = 2000):
        self.last_touch_ms = -10_000
        self.last_mouse_ms = -10_000
        self.switch_delay_ms = switch_delay_ms
        self.locked_mode: str | None = None  # None | "touch" | "desktop"
        self._ever_touched = False

    def note_touch(self):
        self.last_touch_ms = pygame.time.get_ticks()
        self._ever_touched = True

    @property
    def ever_touched(self) -> bool:
        """本 session 是否用过触屏（用于永久屏蔽触摸模拟鼠标）。"""
        return self._ever_touched

    def note_mouse(self):
        self.last_mouse_ms = pygame.time.get_ticks()

    @property
    def mode(self) -> str:
        if self.locked_mode:
            return self.locked_mode
        if self.last_touch_ms > self.last_mouse_ms:
            return "touch"
        return "desktop"

    @property
    def is_touch(self) -> bool:
        return self.mode == "touch"