"""发射台面板（M5b）：模式切换 / 目标行星 / 库存 / 发射窗口倒计时。

半透明浮窗，点外部关闭。业务数据来自 LaunchPad + Simulation：
  - mode  : supply/request 两个按钮切换（走 sim.set_pad_mode）
  - target: 目标行星循环切换（走 sim.set_pad_target）
  - 窗口  : pads.window_open/window_wait 实时算
  - 船    : ships 状态（待命/在途/返航）与进度
"""

from __future__ import annotations

import pygame

from .. import config as C
from ..logistics import pads as P
from . import uidef


def _fmt_wait(sec: float) -> str:
    if sec <= 0:
        return "现在可发射"
    if sec == float("inf"):
        return "无窗口（周期相同）"
    if sec >= 60:
        return f"{int(sec // 60)} 分 {int(sec % 60)} 秒后"
    return f"{sec:.1f} 秒后"


class PadPanel:
    """发射台详情面板。Game 持有实例。"""

    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("pad_panel.json")
        self.pad = None
        self.sim = None
        self.rect = pygame.Rect(0, 0, 340, 340)
        self._btn_rects: dict[str, pygame.Rect] = {}

    @property
    def open(self) -> bool:
        return self.pad is not None

    # ---------- 开关 ----------

    def show(self, pad, sim, screen_size):
        self.pad = pad
        self.sim = sim
        sw, sh = screen_size
        self.rect.center = (sw // 2, sh // 2)
        self.rect.size = (min(340, int(sw * 0.74)), min(340, int(sh * 0.66)))

    def close(self):
        self.pad = None
        self.sim = None

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if self.pad is None:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        for key, rect in self._btn_rects.items():
            if rect.collidepoint(pos) and self.sim is not None:
                p = self.pad
                if key in ("supply", "request"):
                    self.sim.set_pad_mode(p.x, p.y, key)
                elif key == "target":
                    n = len(self.sim.worlds)
                    if n >= 2:
                        cur = p.target if p.target is not None else p.x
                        self.sim.set_pad_target(p.x, p.y, (cur + 1) % n)
                return True
        return True

    # ---------- 绘制 ----------

    def _btn(self, screen, rect, text, active):
        m = self.defs.meta_c
        bg = m["btn_on"] if active else m["btn_bg"]
        pygame.draw.rect(screen, bg, rect, border_radius=5)
        pygame.draw.rect(screen, m["btn_border"], rect, 1, border_radius=5)
        f = self.fonts.get(15)
        surf = f.render(text, True, m["text"])
        screen.blit(surf, (rect.centerx - surf.get_width() // 2,
                           rect.centery - surf.get_height() // 2))

    def draw(self, screen: pygame.Surface):
        if self.pad is None:
            return
        p = self.pad
        r = self.rect
        m = self.defs.meta_c
        uidef.draw_window(screen, self.defs, r, self.fonts)
        title = "发射台·供货" if p.mode == "supply" else "发射台·要货"
        overrides = {"text": {"title": f"{title} ({p.x},{p.y})"}}
        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        small = self.fonts.get(15)
        x0 = r.left + 14
        y = r.top + 32

        # 模式按钮
        self._btn_rects.clear()
        b1 = pygame.Rect(x0, y, 96, 24)
        b2 = pygame.Rect(x0 + 104, y, 96, 24)
        self._btn(screen, b1, "供货", p.mode == "supply")
        self._btn(screen, b2, "要货", p.mode == "request")
        self._btn_rects["supply"] = b1
        self._btn_rects["request"] = b2
        y += 32

        # 目标行星
        worlds = self.sim.worlds if self.sim is not None else []
        tgt = p.target
        tname = worlds[tgt].name if (tgt is not None and 0 <= tgt < len(worlds)) \
            else "自动（下一颗）"
        screen.blit(small.render(f"目标行星: {tname}", True, m["text"]),
                    (x0, y + 3))
        bt = pygame.Rect(r.right - 76, y, 62, 24)
        self._btn(screen, bt, "切换", False)
        self._btn_rects["target"] = bt
        y += 32

        # 发射窗口
        if self.sim is not None and len(worlds) >= 2:
            wi = self.sim.world_index
            tw = tgt if (tgt is not None and tgt != wi) else (wi + 1) % len(worlds)
            w_in = worlds[tw]
            if p.mode == "supply":
                wtext = _fmt_wait(P.window_wait(worlds[wi], w_in))
            else:
                wtext = "（要货台不发射）"
            screen.blit(small.render(f"窗口: {wtext}", True, m["window_w"]),
                        (x0, y + 3))
        y += 28

        # 船状态
        ships = getattr(p, "ships", [])
        if p.mode != "supply":
            shtext = "无船（要货台）"
        elif not ships:
            shtext = "无船"
        else:
            s = ships[0]
            state = {"docked": "待命", "outbound": "去程",
                     "inbound": "返航"}.get(s.state, "?")
            if s.state == "docked":
                shtext = f"船: {state}  货 {sum(s.cargo.values())}"
            else:
                shtext = f"船: {state} {int(s.progress() * 100)}%  货 " \
                         f"{sum(s.cargo.values())}"
        screen.blit(small.render(shtext, True, m["text"]), (x0, y + 2))
        y += 26

        # 库存
        if not p.inventory:
            screen.blit(small.render("  (空)", True, m["hint"]), (x0, y + 3))
        else:
            for item_id, count in list(p.inventory.items())[:6]:
                name = C.ITEM_NAMES.get(item_id, f"?{item_id}")
                color = C.ITEM_COLORS.get(item_id, (200, 200, 200))
                pygame.draw.rect(screen, color, (x0 + 4, y + 3, 14, 14))
                screen.blit(small.render(f"{name}  ×{count}", True, m["text"]),
                            (x0 + 26, y + 1))
                y += 18
            if len(p.inventory) > 6:
                screen.blit(small.render(f"…共 {len(p.inventory)} 种",
                                         True, m["hint"]), (x0 + 26, y + 1))

        screen.blit(small.render("点面板外关闭", True, m["hint"]),
                    (x0, r.bottom - 24))
