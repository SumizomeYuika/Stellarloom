"""轨道图面板（M4 戴森云 + 轨道系统最小版 + M5 星际）：同心轨道 + 帆群 + 多行星 + 统计。

交互：
- 点面板外 / ✕ / ESC 关闭
- 点非当前行星的圆点 -> 切换当前行星（M5 星际最小版）
- 轨道只做展示，不手动指定目标轨道（发射器自动挑最空的）
- 游戏不暂停，帆照样在转、行星照样在公转
"""

from __future__ import annotations

import math

import pygame

from .. import config as C
from ..logistics import pads as P
from ..world import kepler
from . import uidef


class OrbitPanel:
    """星系视图（M6.32）：全屏界面，不是浮窗。

    缩到最小继续缩小（或底栏按钮）进入；整屏铺星空背景 + 戴森轨道 +
    行星轨道；放大 / ESC / 「返回地图」退出。不参与面板拖动。
    """

    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("orbit_panel.json")
        self.open = False
        self.no_drag = True          # 全屏视图，不许当窗口拖
        self.rect = pygame.Rect(0, 0, 520, 560)
        self._dyson = None
        self._tech = None
        self._worlds: list | None = None
        self._current = 0
        self._on_switch = None
        self._fleet = None            # M5b：恒星级舰队（画在轨上）
        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._center = (0.0, 0.0)
        self._radius_base = 100.0

    def show(self, dyson, tech, worlds, current, screen_size, on_switch=None,
             fleet=None):
        self._dyson = dyson
        self._tech = tech
        self._fleet = fleet
        self._worlds = list(worlds) if isinstance(worlds, (list, tuple)) \
            else [worlds]
        self._current = current if 0 <= current < len(self._worlds) else 0
        self._on_switch = on_switch
        self.open = True
        sw, sh = screen_size
        # 全屏界面：铺满整个屏幕（不是居中弹层）
        self.rect = pygame.Rect(0, 0, sw, sh)

    def close(self):
        self.open = False
        self._dyson = None
        self._fleet = None

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if not self.open:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        if self._close_rect.collidepoint(pos):
            self.close()
            return True
        # 点非当前行星的圆点 -> 切换（坐标与 draw 用同一套公式）
        if self._on_switch is not None and self._worlds:
            for i in range(len(self._worlds)):
                if i == self._current:
                    continue
                px, py = self._planet_xy(i)
                if (pos[0] - px) ** 2 + (pos[1] - py) ** 2 <= 15 * 15:
                    self._on_switch(i)
                    return True
        # 点戴森轨道环 = 指定发射目标轨道（只认已解锁环；再点一次恢复自动）
        if self._dyson is not None:
            pcx, pcy = self._center
            dx, dy = pos[0] - pcx, pos[1] - pcy
            dist = math.hypot(dx, dy)
            tol = max(9.0, self._radius_base * 0.035)
            for i in range(C.DYSON_ORBITS):
                rad = self._radius_base * C.DYSON_ORBIT_RADIUS[i]
                if abs(dist - rad) <= tol and i < self._dyson.unlocked_orbits():
                    self._dyson.set_target_orbit(i)
                    return True
        return True  # 面板内一律消费，不穿透

    # ---------- 几何（真实椭圆轨道） ----------

    def _a_max(self) -> float:
        """全部行星里最大的半长轴（AU），用于把最外圈钉在面板边缘。"""
        if not self._worlds:
            return 1.0
        return max((ws.planet.a_au for ws in self._worlds), default=1.0) or 1.0

    def _orbit_a(self, p) -> float:
        """该行星椭圆轨道的显示半长轴（像素，按真实 AU 比例）。"""
        return self._radius_base * C.PLANET_ORBIT_RADIUS * (p.a_au / self._a_max())

    def _planet_xy(self, i: int) -> tuple[float, float]:
        """行星圆点位置：真近点角 + 椭圆半径 + 近点辐角旋转。"""
        p = self._worlds[i].planet
        a = self._orbit_a(p)
        r = p.radius_au / max(p.a_au, 1e-9)
        ang = math.radians(p.angle) + math.radians(p.arg_peri)
        pcx, pcy = self._center
        return (pcx + math.cos(ang) * a * r, pcy + math.sin(ang) * a * r)

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if not self.open or self._dyson is None:
            return
        r = self.rect
        sw, sh = screen.get_size()

        # ---- 全屏星空背景（不是弹层：不画遮罩、不画窗口边框） ----
        for i in range(0, sh, 4):
            t = i / max(sh, 1)
            col = (int(8 + 10 * t), int(12 + 14 * t), int(24 + 26 * t))
            pygame.draw.rect(screen, col, (0, i, sw, 4))
        # 固定伪随机星点（不闪烁，纯背景）
        for i in range(160):
            x = (i * 97 + 13) % max(sw, 1)
            y = (i * 57 + 29) % max(sh, 1)
            c = 200 if i % 7 == 0 else 120
            pygame.draw.rect(screen, (c, c, min(255, c + 25)), (x, y, 2, 2))

        big = self.fonts.get(26)
        mid = self.fonts.get(16)
        small = self.fonts.get(14)
        tiny = self.fonts.get(12)

        x0 = r.left + 22
        title = big.render("星系视图", True, (235, 242, 250))
        screen.blit(title, (x0, r.top + 14))
        sub = small.render(
            "戴森云与行星轨道 · 点轨道环指定发射目标 · 点行星切换", True,
            (130, 160, 195))
        screen.blit(sub, (x0 + title.get_width() + 12, r.top + 24))

        # 返回按钮（全屏视图没有"点外部关闭"）
        self._close_rect = pygame.Rect(r.right - 128, r.top + 14, 104, 30)
        pygame.draw.rect(screen, (34, 46, 62), self._close_rect,
                         border_radius=6)
        pygame.draw.rect(screen, (90, 120, 150), self._close_rect, 1,
                         border_radius=6)
        back = small.render("返回地图 ↵", True, (210, 228, 244))
        screen.blit(back, (self._close_rect.centerx - back.get_width() // 2,
                           self._close_rect.centery - back.get_height() // 2))

        # 顶部统计
        d = self._dyson
        sails = d.total_sails()
        pw = d.power_output()
        eff = d.sail_efficiency()
        stats = (f"太阳帆 {sails} / {d.total_cap()}    "
                 f"发电 {pw:.0f} kW    效率 ×{eff:.1f}")
        screen.blit(mid.render(stats, True, (170, 200, 235)), (x0, r.top + 56))
        # 当前行星相位（M6.31 真实轨道）：真近点角 + 日心距 + 相对日照
        cur_ws = self._worlds[self._current] if self._worlds else None
        if cur_ws is not None:
            p = cur_ws.planet
            p_str = (f"{cur_ws.name} 真近点角 {p.angle:.0f}° · 距恒星 "
                     f"{p.radius_au:.3f} AU · 日照 ×{p.solar_factor():.2f}")
            screen.blit(mid.render(p_str, True, (120, 190, 220)),
                        (x0, r.top + 78))

        # ---- 轨道区 ----
        area_top = r.top + 100
        area_h = r.height - 100 - 132
        self._center = (r.centerx, area_top + area_h / 2)
        self._radius_base = min(r.width * 0.40, area_h * 0.46)

        unlocked = d.unlocked_orbits()
        for i in range(C.DYSON_ORBITS):
            rad = self._radius_base * C.DYSON_ORBIT_RADIUS[i]
            active = i < unlocked
            targeted = (d.target_orbit == i)
            if targeted:
                ring_c = (255, 220, 120)
            else:
                ring_c = (60, 90, 140) if active else (44, 48, 58)
            pygame.draw.circle(screen, ring_c, (int(self._center[0]),
                                                int(self._center[1])),
                               int(rad), 2 if targeted else 1)
            # 轨道名 + 载量 + 目标标记
            lbl = f"{C.DYSON_ORBIT_NAMES[i]} {d.orbit_count[i]}/{C.DYSON_ORBIT_CAP[i]}"
            if not active:
                lbl += " 🔒"
            elif targeted:
                lbl += " ◀目标"
            screen.blit(tiny.render(lbl, True,
                                    (255, 220, 140) if targeted else
                                    ((150, 190, 230) if active else (110, 115, 128))),
                        (int(self._center[0]) + 4,
                         int(self._center[1] - rad) - 14))

        # 中心恒星
        pygame.draw.circle(screen, (255, 220, 120),
                           (int(self._center[0]), int(self._center[1])), 14)
        pygame.draw.circle(screen, (255, 250, 210),
                           (int(self._center[0]), int(self._center[1])), 7)

        # 帆
        for oi, ang in d.sail_positions():
            if oi >= unlocked:
                continue
            rad = self._radius_base * C.DYSON_ORBIT_RADIUS[oi]
            a = math.radians(ang)
            px = self._center[0] + math.cos(a) * rad
            py = self._center[1] + math.sin(a) * rad
            sz = 3 if sails < 80 else 2
            pygame.draw.rect(screen, C.ITEM_COLORS[C.I_SOLAR_SAIL],
                             (int(px) - sz // 2, int(py) - sz // 2, sz, sz))

        # ---- 行星轨道（M6.31 真实椭圆）：按真实半长轴比例画椭圆 ----
        if self._worlds:
            pcx, pcy = self._center
            for i, ws in enumerate(self._worlds):
                p = ws.planet
                a_disp = self._orbit_a(p)
                pts = kepler.orbit_points(a_disp, p.eccentricity, p.arg_peri)
                pts.append(pts[0])
                ring_c = (90, 120, 160) if i == self._current else (64, 80, 105)
                pygame.draw.lines(screen, ring_c, False,
                                  [(int(pcx + x), int(pcy + y))
                                   for x, y in pts], 1)
            for i, ws in enumerate(self._worlds):
                px, py = self._planet_xy(i)
                is_cur = (i == self._current)
                sz = 7 if is_cur else 5
                pygame.draw.circle(screen, ws.color,
                                   (int(px), int(py)), sz)
                if is_cur:
                    # 当前行星：白色光环，点它不切换
                    pygame.draw.circle(screen, (255, 255, 255),
                                       (int(px), int(py)), sz + 4, 2)
                else:
                    pygame.draw.circle(screen, (225, 242, 255),
                                       (int(px), int(py)), 2)
                lbl = ws.name + ("（当前）" if is_cur else "")
                screen.blit(tiny.render(lbl, True,
                                        (255, 255, 255) if is_cur
                                        else (165, 195, 225)),
                            (int(px) - 18, int(py) + 12))

        # ---- 运输船（M5b）：在途船按进度插值到两颗行星的连线上 ----
        if self._fleet is not None and self._worlds:
            pos = [self._planet_xy(i) for i in range(len(self._worlds))]
            for s in self._fleet.ships:
                if s.state == "docked" or s.target is None:
                    continue
                hw, tw = s.home[0], s.target[0]
                if not (0 <= hw < len(pos) and 0 <= tw < len(pos)):
                    continue
                t = s.progress()
                if s.state == "inbound":
                    t = 1.0 - t
                x1, y1 = pos[hw]
                x2, y2 = pos[tw]
                sx = x1 + (x2 - x1) * t
                sy = y1 + (y2 - y1) * t
                # 小菱形船标
                pts = [(int(sx), int(sy) - 4), (int(sx) + 4, int(sy)),
                       (int(sx), int(sy) + 4), (int(sx) - 4, int(sy))]
                pygame.draw.polygon(screen, C.C_LAUNCH_PAD, pts)
                pygame.draw.polygon(screen, (235, 245, 255), pts, 1)

        # ---- 底部说明 ----
        y = r.bottom - 124
        # M5b：当前行星 -> 下一颗行星的发射窗口预测
        win_line = None
        if cur_ws is not None and len(self._worlds) >= 2:
            wi = self._current
            tw = (wi + 1) % len(self._worlds)
            wait = P.window_wait(cur_ws, self._worlds[tw])
            if wait <= 0:
                win_line = f"到 {self._worlds[tw].name} 的发射窗口：现在开着"
            elif wait == float("inf"):
                win_line = f"到 {self._worlds[tw].name}：两星周期相同，无窗口"
            else:
                win_line = f"到 {self._worlds[tw].name} 的发射窗口：{wait:.0f} 秒后"
        if cur_ws is not None:
            cp = cur_ws.planet
            orbit_line = ("点轨道环：给发射器指定目标轨道（再点一次恢复自动）。")
        else:
            orbit_line = "点轨道环指定发射目标轨道；发射器自动选最空的环。"
        lines = [
            "太阳帆由发射器打到轨道上，帆越多发电越高。",
            f"每片帆 {C.DYSON_SAIL_POWER:.0f} kW × 效率加成；戴森云电力不占地面格子。",
            "发射器：分拣器喂「太阳帆」进去，它每 "
            f"{C.DYSON_LAUNCH_INTERVAL:.1f} 秒自动打一发。",
            "研究「戴森云 I」解锁内轨，「戴森云 II」解锁中轨和外轨。",
            orbit_line,
            win_line or "研究「星际物流 I」解锁发射台：行星相位对齐时运输船才能出发。",
        ]
        for i, ln in enumerate(lines):
            screen.blit(tiny.render(ln, True, (135, 145, 165)),
                        (x0, y + i * 17))

        screen.blit(tiny.render("放大 / ESC / 「返回地图」回到地表 · 游戏继续运行",
                                True, (100, 106, 122)),
                    (x0, r.bottom - 22))