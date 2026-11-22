"""行星引擎面板（M6）：变轨控制台。

半透明浮窗，点外部关闭。数据来自 Simulation（当前行星的 PlanetOrbit）：
  - 半径 ±：调半长轴（60%~180% 原始值，周期按 T=a^1.5 跟着变）
  - 相位 ±：平移平近点角（15° 一档）
  - 只读：供电状态 / 半长轴 / 周期 / 日心距 / 光照 / 温度 / 太阳能效率

变轨必须引擎通电（电网不缺电），否则按钮不生效，面板只读。
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef


class EnginePanel:
    """行星引擎控制面板。Game 持有实例。"""

    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("engine_panel.json")
        self.pos = None            # 引擎中心格 (x, y)
        self.sim = None
        self.rect = pygame.Rect(0, 0, 380, 300)
        self._btn_rects: dict[str, pygame.Rect] = {}

    @property
    def open(self) -> bool:
        return self.pos is not None

    # ---------- 开关 ----------

    def show(self, pos, sim, screen_size):
        self.pos = pos
        self.sim = sim
        sw, sh = screen_size
        self.rect.center = (sw // 2, sh // 2)
        self.rect.size = (min(380, int(sw * 0.78)), min(300, int(sh * 0.60)))

    def close(self):
        self.pos = None
        self.sim = None

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if self.pos is None:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        for key, rect in self._btn_rects.items():
            if rect.collidepoint(pos) and self.sim is not None:
                if key == "a_minus":
                    self.sim.nudge_orbit_a(-0.1)
                elif key == "a_plus":
                    self.sim.nudge_orbit_a(0.1)
                elif key == "ph_minus":
                    self.sim.shift_orbit_phase(-C.ENGINE_PHASE_STEP)
                elif key == "ph_plus":
                    self.sim.shift_orbit_phase(C.ENGINE_PHASE_STEP)
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
        if self.pos is None or self.sim is None:
            return
        r = self.rect
        m = self.defs.meta_c
        sim = self.sim
        uidef.draw_window(screen, self.defs, r, self.fonts)
        overrides = {"text": {"title": f"行星引擎 ({self.pos[0]},{self.pos[1]})"}}
        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        small = self.fonts.get(15)
        x0 = r.left + 14
        y = r.top + 32

        powered = sim.engine_powered()
        p = sim.planet
        ratio = sim.orbit_ratio()
        base = sim.orbit_base_a()
        status = "供电正常" if powered else ("未通电（变轨禁用）"
                                            if sim.has_engine() else "无引擎")
        screen.blit(small.render(f"状态: {status}", True,
                                 m["text"] if powered else m["hint"]),
                    (x0, y))
        y += 24

        # 轨道数据
        lines = [
            f"半长轴: {p.a_au:.3f} AU  (原始 {base:.3f} × {ratio * 100:.0f}%)",
            f"公转一圈: {p.period:.0f} 秒",
            f"距恒星: {p.radius_au:.3f} AU · 光照 ×{p.solar_factor():.2f}",
            f"温度: {p.temperature_c():.0f}°C · 太阳能效率 ×{p.temperature_efficiency():.2f}",
        ]
        for ln in lines:
            screen.blit(small.render(ln, True, m["text"]), (x0, y))
            y += 20

        # 半径按钮
        y += 4
        self._btn_rects.clear()
        screen.blit(small.render("轨道半径", True, m["hint"]), (x0, y + 3))
        b1 = pygame.Rect(x0 + 84, y, 58, 24)
        b2 = pygame.Rect(x0 + 148, y, 58, 24)
        self._btn(screen, b1, "-10%", ratio > C.ENGINE_A_MIN_RATIO + 1e-6)
        self._btn(screen, b2, "+10%", ratio < C.ENGINE_A_MAX_RATIO - 1e-6)
        self._btn_rects["a_minus"] = b1
        self._btn_rects["a_plus"] = b2
        y += 32

        # 相位按钮
        screen.blit(small.render("轨道相位", True, m["hint"]), (x0, y + 3))
        b3 = pygame.Rect(x0 + 84, y, 58, 24)
        b4 = pygame.Rect(x0 + 148, y, 58, 24)
        self._btn(screen, b3, f"-{C.ENGINE_PHASE_STEP:.0f}°", True)
        self._btn(screen, b4, f"+{C.ENGINE_PHASE_STEP:.0f}°", True)
        self._btn_rects["ph_minus"] = b3
        self._btn_rects["ph_plus"] = b4

        screen.blit(small.render(
            f"范围 {C.ENGINE_A_MIN_RATIO:.0%}~{C.ENGINE_A_MAX_RATIO:.0%}；"
            "推近恒星更亮但会过热降效",
            True, m["hint"]), (x0, r.bottom - 40))
        screen.blit(small.render("点面板外关闭", True, m["hint"]),
                    (x0, r.bottom - 22))
