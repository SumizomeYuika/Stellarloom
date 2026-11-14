"""面板窗口化（M6.28）：拖标题栏移动面板。

- 每个面板顶部有标题栏（uidef.draw_window 画的左上角等腰梯形，高度
  meta.titlebar_h，theme 兜底 26）。
- Game 把 TouchUI 手势喂进来：TapEvent 按下在标题栏内 -> grab，
  DragEvent -> move（吃住移动，不滚世界/不滚列表），FINGERUP/鼠标抬起 -> end。
- 面板 rect 位置只在内存（当前会话），不写存档。
"""

from __future__ import annotations

import pygame

TITLEBAR_H = 26


class WindowMgr:
    def __init__(self, titlebar_h: int = TITLEBAR_H):
        self.titlebar_h = titlebar_h
        self.drag: tuple[object, int, int] | None = None  # (panel, dx, dy)

    def title_rect(self, panel) -> pygame.Rect:
        r = panel.rect
        h = getattr(panel, "_titlebar_h", self.titlebar_h)
        return pygame.Rect(r.left, r.top, r.width, h)

    def grab(self, panel, pos) -> bool:
        """pos 落在 open 面板的标题栏内则开始拖动，返回 True。"""
        if not getattr(panel, "open", False):
            return False
        if getattr(panel, "no_drag", False):
            return False          # 全屏界面（星系视图）不参与拖动
        if not self.title_rect(panel).collidepoint(pos):
            return False
        pr = panel.rect
        self.drag = (panel, int(pos[0]) - pr.x, int(pos[1]) - pr.y)
        return True

    def move(self, pos, screen_size) -> bool:
        if self.drag is None:
            return False
        panel, dx, dy = self.drag
        r = panel.rect
        r.x = int(pos[0]) - dx
        r.y = int(pos[1]) - dy
        # 限幅：至少留标题栏的一部分在屏内（不整窗飞丢）
        r.x = max(4 - r.width + 60, min(r.x, max(4, screen_size[0] - 60)))
        r.y = max(4, min(r.y, screen_size[1] - 30))
        return True

    def end(self):
        self.drag = None