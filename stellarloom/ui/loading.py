"""M13：游戏启动加载界面（LoadingScreen）。

启动序列改成"分步加载"：main.py 开好窗口后先建 LoadingScreen，
Game 构造期间每完成一个大步骤推进一步（major），每个大步骤内部
用 step(label, frac) 报告当前加载项（可选 0~1 子进度）。

特点：
- 只依赖 pygame + 可选 FontBook（字体阶段完成后 attach_fonts 换中文字体）。
- 每步重绘一次并 flip，顺手 pump 事件队列（Android 防 ANR），
  处理 QUIT（直接退出）。
- 纯展示，不持有任何游戏状态；Game 传 loader=None 时完全静默
  （自检/headless 路径不受影响）。
"""

from __future__ import annotations

import sys

import pygame

_BG = (16, 20, 30)
_PANEL = (30, 38, 54)
_BAR_BG = (44, 54, 74)
_BAR_FG = (90, 200, 140)
_SUB_FG = (120, 160, 220)
_TEXT = (225, 232, 245)
_DIM = (140, 150, 170)
_TITLE = (235, 240, 250)


class LoadingScreen:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self._majors: list[str] = []
        self._major_idx = 0
        self._item = ""
        self._frac: float | None = None
        self._fonts = None
        self._f_title = pygame.font.Font(None, 44)
        self._f_item = pygame.font.Font(None, 24)
        self._f_dim = pygame.font.Font(None, 20)

    # ---------- 生命周期 ----------

    def begin(self, majors: list[str]):
        """声明大步骤清单（决定总进度条的格数）。"""
        self._majors = list(majors)
        self._major_idx = 0
        self._item = ""
        self._frac = None
        self._draw()

    def attach_fonts(self, fonts):
        """字体阶段完成后换中文 FontBook。"""
        self._fonts = fonts
        self._f_title = fonts.get(40)
        self._f_item = fonts.get(22)
        self._f_dim = fonts.get(18)
        self._draw()

    def major(self, label: str):
        """进入下一个大步骤。"""
        self._major_idx = min(self._major_idx + 1, len(self._majors))
        self._item = label
        self._frac = None
        self._draw()

    def step(self, label: str, frac: float | None = None):
        """当前加载项（可选子进度 0~1）。"""
        self._item = label
        self._frac = frac
        self._draw()

    def done(self):
        self._item = "完成"
        self._frac = 1.0
        self._draw()

    # ---------- 绘制 ----------

    def _draw(self):
        s = self.screen
        w, h = s.get_size()
        s.fill(_BG)
        cx = w // 2
        # 标题
        t = self._f_title.render("星织 StellarLoom", True, _TITLE)
        s.blit(t, (cx - t.get_width() // 2, int(h * 0.28)))
        # 大步骤进度条
        n = max(len(self._majors), 1)
        bw = int(w * 0.6)
        bh = max(int(h * 0.035), 14)
        bx, by = cx - bw // 2, int(h * 0.52)
        pygame.draw.rect(s, _BAR_BG, (bx, by, bw, bh), border_radius=bh // 2)
        frac_total = self._major_idx / n
        if frac_total > 0:
            pygame.draw.rect(s, _BAR_FG,
                             (bx, by, int(bw * frac_total), bh),
                             border_radius=bh // 2)
        pygame.draw.rect(s, _PANEL, (bx, by, bw, bh), 1,
                         border_radius=bh // 2)
        # 大步骤名 + 计数
        label = (self._majors[self._major_idx - 1]
                 if 0 < self._major_idx <= len(self._majors) else "准备中")
        head = f"{label}  {self._major_idx}/{n}"
        ht = self._f_item.render(head, True, _TEXT)
        s.blit(ht, (cx - ht.get_width() // 2, by - ht.get_height() - 10))
        # 当前加载项 + 子进度条
        if self._item:
            it = self._f_dim.render(self._item, True, _DIM)
            s.blit(it, (cx - it.get_width() // 2, by + bh + 12))
        if self._frac is not None:
            sw = int(bw * 0.7)
            sh = max(bh // 3, 6)
            sx, sy = cx - sw // 2, by + bh + 12 + it.get_height() + 10
            pygame.draw.rect(s, _BAR_BG, (sx, sy, sw, sh),
                             border_radius=sh // 2)
            f = max(0.0, min(1.0, self._frac))
            if f > 0:
                pygame.draw.rect(s, _SUB_FG, (sx, sy, int(sw * f), sh),
                                 border_radius=sh // 2)
        pygame.display.flip()
        # pump 事件，防 Android ANR；允许用户直接关掉
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)