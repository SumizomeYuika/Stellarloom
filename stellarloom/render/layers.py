"""静态层分块预渲染（细节版）。

每格按建筑类型画不同图案，不再是大色块：
- 传送带：深色底 + 亮色侧边线 + 居中箭头
- 矿脉：散点状小圆点，有大有小
- 熔炉：深红底 + 内框 + 横排通风口
- 制造台：蓝底 + 内框 + 齿轮圆
- 太阳能：深蓝底 + 网格光伏纹
- 风力：浅蓝底 + 扇叶十字
- 采矿机：绿底 + 钻头三角
- 分拣器：黄底 + 菱形
- 核心：白底 + 十字
"""

from __future__ import annotations

import math

import pygame

from .. import config as C

MAX_CACHED_CHUNKS = 96


def arm_part_hidden(btype: int) -> bool:
    """分拣器头/尾所在格是机器（非空且非带）时，那一段不画。"""
    return int(btype) not in (C.B_EMPTY, C.B_BELT)


def inserter_hand(src, dst, phase: float) -> tuple[float, float]:
    """三段臂的手部位置：phase 0 = 停在来源格，1 = 伸到目标格。

    src / dst 是世界像素坐标。纯几何，供渲染与自检共用。
    """
    p = max(0.0, min(1.0, phase))
    return (src[0] + (dst[0] - src[0]) * p,
            src[1] + (dst[1] - src[1]) * p)


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


class ChunkRenderer:
    def __init__(self, grid, cells_per_chunk: int = 32):
        self.grid = grid
        self.cpc = cells_per_chunk
        self.cx_count = (grid.w + cells_per_chunk - 1) // cells_per_chunk
        self.cy_count = (grid.h + cells_per_chunk - 1) // cells_per_chunk
        self.cache: dict[tuple[int, int, int], pygame.Surface] = {}
        # 简单的 hash 用作每格随机种子
        self._rng_seed = 12345

    # ---------- 缓存管理 ----------

    def invalidate_cell(self, x: int, y: int):
        g = self.grid
        cix = (x % g.w) // self.cpc
        ciy = (y % g.h) // self.cpc
        for key in [k for k in self.cache if k[0] == cix and k[1] == ciy]:
            del self.cache[key]

    def clear(self):
        self.cache.clear()

    def _get(self, cix: int, ciy: int, tile_px: int) -> pygame.Surface:
        key = (cix, ciy, tile_px)
        surf = self.cache.get(key)
        if surf is not None:
            return surf
        surf = self._build(cix, ciy, tile_px)
        if len(self.cache) >= MAX_CACHED_CHUNKS:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = surf
        return surf

    # ---------- 每格伪随机 ----------

    @staticmethod
    def _hash(x: int, y: int, salt: int = 0) -> int:
        h = (x * 374761393 + y * 668265263 + salt * 144665) & 0xFFFFFFFF
        h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
        return h ^ (h >> 16)

    # ---------- 绘制单块 ----------

    def _build(self, cix: int, ciy: int, tile_px: int) -> pygame.Surface:
        cpc = self.cpc
        size = cpc * tile_px
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        g = self.grid
        bx0 = cix * cpc
        by0 = ciy * cpc

        for ly in range(cpc):
            wy = (by0 + ly) % g.h
            row_b = g.building[wy]
            row_o = g.ore[wy]
            row_ot = g.ore_type[wy]
            row_d = g.direction[wy]
            row_ov = g.overlay[wy]
            row_ovd = g.overlay_dir[wy]
            row_ovf = g.overlay_filter[wy]
            for lx in range(cpc):
                wx = (bx0 + lx) % g.w
                rect = pygame.Rect(lx * tile_px, ly * tile_px, tile_px, tile_px)

                b = row_b[wx]
                if b == C.B_EMPTY:
                    if row_o[wx] > 0:
                        self._draw_ore(surf, rect, wx, wy, tile_px, int(row_ot[wx]))
                else:
                    d = int(row_d[wx])
                    if b == C.B_BELT:
                        self._draw_belt(surf, rect, d, tile_px)
                    elif b == C.B_MINER:
                        self._draw_miner(surf, rect, d, tile_px)
                    elif b == C.B_FURNACE:
                        self._draw_furnace(surf, rect, tile_px)
                    elif b == C.B_ASSEMBLER:
                        self._draw_assembler(surf, rect, tile_px)
                    elif b == C.B_SOLAR:
                        self._draw_solar(surf, rect, tile_px)
                    elif b == C.B_WIND:
                        self._draw_wind(surf, rect, tile_px)
                    elif b == C.B_POWER_POLE:
                        self._draw_power_pole(surf, rect, tile_px)
                    elif b == C.B_INSERTER:
                        self._draw_inserter(surf, rect, d, tile_px)
                    elif b == C.B_TOWER_SUPPLY:
                        self._draw_tower(surf, rect, tile_px, supply=True)
                    elif b == C.B_TOWER_REQUEST:
                        self._draw_tower(surf, rect, tile_px, supply=False)
                    elif b == C.B_LAB:
                        self._draw_lab(surf, rect, tile_px)
                    elif b == C.B_CHEST:
                        self._draw_chest(surf, rect, wx, wy, tile_px)
                    elif b == C.B_EMITTER:
                        self._draw_emitter(surf, rect, tile_px)
                    elif b == C.B_LAUNCH_PAD:
                        self._draw_launch_pad(surf, rect, tile_px)
                    elif b == C.B_PLANET_ENGINE:
                        self._draw_planet_engine(surf, rect, tile_px)
                    elif b == C.B_CORE:
                        self._draw_core(surf, rect, tile_px)
                    else:
                        surf.fill(C.C_CORE, rect.inflate(-1, -1))

                # 叠加层（分拣器）：画在底图之上，半透明底方便看清底下的带子
                ov = row_ov[wx]
                if ov != C.B_EMPTY:
                    if ov == C.B_INSERTER:
                        self._draw_inserter_overlay(
                            surf, rect, int(row_ovd[wx]), tile_px,
                            int(row_ovf[wx]))
        return surf

    # ---------- 各种建筑的绘制 ----------

    @staticmethod
    def _base(surf, rect, color, tile_px):
        """底色 + 外边框 + 顶部高光线，营造一点立体感。"""
        surf.fill(color, rect)
        dark = _lerp(color, (0, 0, 0), 0.35)
        light = _lerp(color, (255, 255, 255), 0.15)
        pygame.draw.rect(surf, dark, rect, 1)
        if tile_px >= 12:
            pygame.draw.line(surf, light, rect.topleft, rect.topright)

    def _draw_belt(self, surf, rect, d, tile_px):
        dark = (40, 48, 62)
        mid = C.C_BELT
        surf.fill(dark, rect)
        # 侧边线
        if tile_px >= 8:
            w = max(tile_px // 6, 1)
            if d in (0, 2):
                pygame.draw.line(surf, mid, rect.midleft, rect.midright, w)
                pygame.draw.line(surf, mid, rect.topleft, rect.topright, 1)
                pygame.draw.line(surf, mid, rect.bottomleft, rect.bottomright, 1)
            else:
                pygame.draw.line(surf, mid, rect.midtop, rect.midbottom, w)
                pygame.draw.line(surf, mid, rect.topleft, rect.bottomleft, 1)
                pygame.draw.line(surf, mid, rect.topright, rect.bottomright, 1)
        # 箭头
        if tile_px >= 6:
            cx, cy = rect.center
            t = max(tile_px // 4, 2)
            if d == 0:
                pts = [(cx + t, cy), (cx - t, cy - t), (cx - t, cy + t)]
            elif d == 2:
                pts = [(cx - t, cy), (cx + t, cy - t), (cx + t, cy + t)]
            elif d == 1:
                pts = [(cx, cy + t), (cx - t, cy - t), (cx + t, cy - t)]
            else:
                pts = [(cx, cy - t), (cx - t, cy + t), (cx + t, cy + t)]
            pygame.draw.polygon(surf, C.C_BELT_DIR, pts)

    def _draw_ore(self, surf, rect, wx, wy, tile_px, ore_type=0):
        """矿脉：格子内随机散布几个亮点，颜色按矿种区分。"""
        ore_c = C.ORE_COLORS.get(ore_type, C.ORE_FALLBACK_COLOR)
        base = _lerp(ore_c, (0, 0, 0), 0.45)
        surf.fill(base, rect.inflate(-1, -1))
        n = 4 if tile_px >= 12 else 2
        for i in range(n):
            h = self._hash(wx, wy, i)
            ox = rect.left + 2 + h % max(tile_px - 4, 1)
            oy = rect.top + 2 + (h >> 8) % max(tile_px - 4, 1)
            r = max(tile_px // 6, 1)
            color = _lerp(ore_c, (255, 255, 255), 0.1 + (h >> 16) % 3 * 0.08)
            pygame.draw.circle(surf, color, (ox, oy), r)

    def _draw_miner(self, surf, rect, d, tile_px):
        self._base(surf, rect, C.C_MINER, tile_px)
        if tile_px >= 10:
            # 钻头：朝向的三角
            cx, cy = rect.center
            t = max(tile_px // 3, 2)
            dark = _lerp(C.C_MINER, (0, 0, 0), 0.4)
            if d == 0:
                pts = [(cx + t, cy), (cx, cy - t), (cx, cy + t)]
            elif d == 2:
                pts = [(cx - t, cy), (cx, cy - t), (cx, cy + t)]
            elif d == 1:
                pts = [(cx, cy + t), (cx - t, cy), (cx + t, cy)]
            else:
                pts = [(cx, cy - t), (cx - t, cy), (cx + t, cy)]
            pygame.draw.polygon(surf, dark, pts)

    def _draw_furnace(self, surf, rect, tile_px):
        self._base(surf, rect, C.C_FURNACE, tile_px)
        if tile_px >= 12:
            # 内框
            inner = rect.inflate(-tile_px // 4, -tile_px // 4)
            pygame.draw.rect(surf, _lerp(C.C_FURNACE, (0, 0, 0), 0.25), inner)
            # 通风口：3 条横线
            dark = _lerp(C.C_FURNACE, (0, 0, 0), 0.5)
            y0 = inner.top + inner.height // 4
            for i in range(3):
                y = y0 + i * max(inner.height // 3, 2)
                pygame.draw.line(surf, dark,
                                 (inner.left + 2, y), (inner.right - 2, y))

    def _draw_assembler(self, surf, rect, tile_px):
        self._base(surf, rect, C.C_ASSEMBLER, tile_px)
        if tile_px >= 12:
            # 中心齿轮圆
            cx, cy = rect.center
            r = max(tile_px // 3, 2)
            dark = _lerp(C.C_ASSEMBLER, (0, 0, 0), 0.3)
            pygame.draw.circle(surf, dark, (cx, cy), r)
            pygame.draw.circle(surf, C.C_ASSEMBLER, (cx, cy), r, 2)
            # 齿轮齿：十字
            t = max(tile_px // 6, 1)
            pygame.draw.line(surf, dark, (cx - r, cy), (cx + r, cy), t)
            pygame.draw.line(surf, dark, (cx, cy - r), (cx, cy + r), t)

    def _draw_solar(self, surf, rect, tile_px):
        self._base(surf, rect, C.C_SOLAR, tile_px)
        if tile_px >= 10:
            # 光伏网格
            dark = _lerp(C.C_SOLAR, (0, 0, 0), 0.4)
            step = max(tile_px // 4, 2)
            for x in range(rect.left, rect.right, step):
                pygame.draw.line(surf, dark, (x, rect.top), (x, rect.bottom))
            for y in range(rect.top, rect.bottom, step):
                pygame.draw.line(surf, dark, (rect.left, y), (rect.right, y))

    def _draw_power_pole(self, surf, rect, tile_px):
        """电力塔：细杆 + 顶部悬臂 + 绝缘子点。"""
        self._base(surf, rect, C.C_POWER_POLE, tile_px)
        if tile_px >= 8:
            cx, cy = rect.center
            dark = _lerp(C.C_POWER_POLE, (0, 0, 0), 0.45)
            h = max(tile_px // 2, 3)
            # 塔身
            pygame.draw.line(surf, dark, (cx, cy + h // 2), (cx, cy - h // 2),
                             max(tile_px // 10, 1))
            # 顶部横担
            arm = max(tile_px // 3, 2)
            pygame.draw.line(surf, dark, (cx - arm, cy - h // 2),
                             (cx + arm, cy - h // 2), max(tile_px // 12, 1))
            # 两点绝缘子
            pygame.draw.circle(surf, (235, 235, 210),
                               (cx - arm, cy - h // 2), max(tile_px // 12, 1))
            pygame.draw.circle(surf, (235, 235, 210),
                               (cx + arm, cy - h // 2), max(tile_px // 12, 1))

    def _draw_wind(self, surf, rect, tile_px):
        self._base(surf, rect, C.C_WIND, tile_px)
        if tile_px >= 10:
            cx, cy = rect.center
            t = max(tile_px // 3, 2)
            dark = _lerp(C.C_WIND, (0, 0, 0), 0.35)
            # 三扇叶
            for angle in (0, 2.1, 4.2):
                x2 = cx + int(math.cos(angle) * t)
                y2 = cy + int(math.sin(angle) * t)
                pygame.draw.line(surf, dark, (cx, cy), (x2, y2), 2)
            pygame.draw.circle(surf, dark, (cx, cy), max(tile_px // 8, 1))

    def _draw_inserter(self, surf, rect, d, tile_px):
        self._base(surf, rect, C.C_INSERTER, tile_px)
        if tile_px >= 8:
            # 菱形
            cx, cy = rect.center
            t = max(tile_px // 3, 2)
            dark = _lerp(C.C_INSERTER, (0, 0, 0), 0.3)
            pygame.draw.polygon(surf, dark, [
                (cx, cy - t), (cx + t, cy), (cx, cy + t), (cx - t, cy)])

    def _draw_inserter_overlay(self, surf, rect, d, tile_px, flt: int = 0):
        """分拣器叠加层（M10 三段式：底座在网格里，臂在动态层画）。

        这里只画一小块底座板 + 方向短杆 + 过滤点，**不再铺满整格**，
        保证下面的传送带/地面透出来；头/连接部/尾由 Game._draw_inserters
        每帧按动画状态画在屏幕层。
        """
        if tile_px < 6:
            return
        cx, cy = rect.center
        plate = max(tile_px // 3, 3)
        # 底座板（半格大小，圆角）
        pygame.draw.rect(surf, (200, 170, 60),
                         (cx - plate // 2, cy - plate // 2, plate, plate),
                         border_radius=max(plate // 4, 1))
        pygame.draw.rect(surf, (120, 90, 20),
                         (cx - plate // 2, cy - plate // 2, plate, plate),
                         max(tile_px // 24, 1), border_radius=max(plate // 4, 1))
        # 方向短杆（指向目标格）
        if tile_px >= 10:
            nub = plate // 2 + max(tile_px // 8, 1)
            ex = cx + C.DX[d] * nub
            ey = cy + C.DY[d] * nub
            pygame.draw.line(surf, (120, 90, 20), (cx, cy), (ex, ey),
                             max(tile_px // 14, 1))

        # 过滤小点：左上角，用被过滤物品的颜色
        if flt > 0 and tile_px >= 10:
            fc = C.ITEM_COLORS.get(flt, (255, 255, 255))
            r = max(tile_px // 7, 2)
            pygame.draw.circle(surf, (0, 0, 0),
                               (rect.left + r + 1, rect.top + r + 1), r + 1)
            pygame.draw.circle(surf, fc, (rect.left + r + 1, rect.top + r + 1), r)

    def _draw_chest(self, surf, rect, wx, wy, tile_px):
        """箱子：木棕色底 + 箱盖分隔线 + 中间锁扣。"""
        self._base(surf, rect, C.C_CHEST, tile_px)
        if tile_px >= 10:
            dark = _lerp(C.C_CHEST, (0, 0, 0), 0.45)
            light = _lerp(C.C_CHEST, (255, 255, 255), 0.25)
            # 箱盖：上三分之一处的横线
            lid_y = rect.top + rect.height // 3
            pygame.draw.line(surf, dark, (rect.left + 1, lid_y),
                             (rect.right - 1, lid_y), max(tile_px // 12, 1))
            # 锁扣：盖子线中央的小方块
            s = max(tile_px // 6, 2)
            pygame.draw.rect(surf, light, (rect.centerx - s // 2, lid_y - s // 2,
                                           s, s))
            # 竖向木纹
            vx = rect.left + rect.width // 4
            pygame.draw.line(surf, dark, (vx, lid_y), (vx, rect.bottom - 1))
            vx = rect.right - rect.width // 4
            pygame.draw.line(surf, dark, (vx, lid_y), (vx, rect.bottom - 1))

    def _draw_emitter(self, surf, rect, tile_px):
        """太阳帆发射器：亮金底 + 中央炮口圆 + 四道向上射线。"""
        self._base(surf, rect, C.C_EMITTER, tile_px)
        if tile_px >= 10:
            cx, cy = rect.center
            r = max(tile_px // 4, 2)
            dark = _lerp(C.C_EMITTER, (0, 0, 0), 0.45)
            light = _lerp(C.C_EMITTER, (255, 255, 255), 0.5)
            pygame.draw.circle(surf, dark, (cx, cy), r)
            pygame.draw.circle(surf, light, (cx, cy), max(r // 2, 1))
            # 发射角：右上、左上两条斜线
            t = max(tile_px // 3, 2)
            for dx in (-1, 1):
                pygame.draw.line(surf, light, (cx, cy),
                                 (cx + dx * t, cy - t), max(tile_px // 10, 1))

    def _draw_core(self, surf, rect, tile_px):
        self._base(surf, rect, C.C_CORE, tile_px)
        if tile_px >= 8:
            cx, cy = rect.center
            t = max(tile_px // 4, 2)
            dark = _lerp(C.C_CORE, (0, 0, 0), 0.4)
            pygame.draw.line(surf, dark, (cx - t, cy), (cx + t, cy), 2)
            pygame.draw.line(surf, dark, (cx, cy - t), (cx, cy + t), 2)

    def _draw_tower(self, surf, rect, tile_px, supply: bool):
        """物流塔：3×3 大图（画在中心格，超出 chunk 会被裁，TechDebt #4）。

        供应塔绿 / 请求塔橙；四角柱 + 中央起降台 + 天线。
        """
        col = C.C_TOWER_SUPPLY if supply else C.C_TOWER_REQUEST
        big = rect.inflate(tile_px * 2, tile_px * 2)
        self._base(surf, big, col, tile_px * 3)
        if tile_px < 8:
            return
        dark = _lerp(col, (0, 0, 0), 0.45)
        light = _lerp(col, (255, 255, 255), 0.45)
        b = big
        # 四角柱：三个可见角的小方块（右上/左上/左下），右下留通道感
        s = max(tile_px // 3, 2)
        for ox, oy in ((0, 0), (b.right - s, 0), (0, b.bottom - s)):
            pygame.draw.rect(surf, dark, (b.left + ox, b.top + oy, s, s))
            pygame.draw.rect(surf, light,
                             (b.left + ox + 1, b.top + oy + 1, s - 2, s - 2))
        # 中央起降台：中心格上叠一个亮圆台 + 暗圆环
        cx, cy = rect.center
        r = max(tile_px // 2, 3)
        pygame.draw.circle(surf, dark, (cx, cy), r + max(tile_px // 8, 1))
        pygame.draw.circle(surf, light, (cx, cy), r)
        pygame.draw.circle(surf, col, (cx, cy), max(r // 2, 2))
        # 天线：中心偏上的短竖线 + 顶部小点（无人机泊位灯）
        if tile_px >= 14:
            t = max(tile_px // 3, 2)
            pygame.draw.line(surf, dark, (cx, rect.top - 1),
                             (cx, rect.top - 1 - t), max(tile_px // 10, 1))
            pygame.draw.circle(surf, light, (cx, rect.top - 1 - t),
                               max(tile_px // 10, 1))

    def _draw_lab(self, surf, rect, tile_px):
        """科研台：紫底 + 烧瓶（圆底 + 细颈 + 液面）。"""
        self._base(surf, rect, C.C_LAB, tile_px)
        if tile_px < 8:
            return
        cx = rect.centerx
        dark = _lerp(C.C_LAB, (0, 0, 0), 0.45)
        light = _lerp(C.C_LAB, (255, 255, 255), 0.5)
        # 烧瓶圆底
        r = max(tile_px // 3, 2)
        by = rect.bottom - r - 1
        pygame.draw.circle(surf, dark, (cx, by), r)
        pygame.draw.circle(surf, light, (cx, by), max(r - 1, 1))
        pygame.draw.circle(surf, C.C_LAB, (cx, by), max(r // 2, 1))
        # 细颈 + 塞子
        neck_w = max(tile_px // 7, 1)
        pygame.draw.rect(surf, dark,
                         (cx - neck_w // 2, rect.top + 1, neck_w,
                          by - rect.top - r // 2))
        pygame.draw.rect(surf, C.C_LAB,
                         (cx - neck_w // 2 - 1, rect.top + 1,
                          neck_w + 2, max(tile_px // 8, 1)))

    def _draw_launch_pad(self, surf, rect, tile_px):
        """发射台：天蓝底 + 菱形台 + 小火箭（竖三角 + 尾焰）。"""
        self._base(surf, rect, C.C_LAUNCH_PAD, tile_px)
        if tile_px < 8:
            return
        cx, cy = rect.center
        dark = _lerp(C.C_LAUNCH_PAD, (0, 0, 0), 0.45)
        light = _lerp(C.C_LAUNCH_PAD, (255, 255, 255), 0.5)
        # 菱形起降台
        d = max(tile_px // 3, 2)
        pygame.draw.polygon(surf, dark,
                            [(cx, cy - d), (cx + d, cy),
                             (cx, cy + d), (cx - d, cy)])
        pygame.draw.polygon(surf, light,
                            [(cx, cy - d + 1), (cx + d - 1, cy),
                             (cx, cy + d - 1), (cx - d + 1, cy)])
        # 小火箭：机身上窄下宽 + 尖头 + 尾焰
        rw = max(tile_px // 4, 2)
        rh = max(tile_px // 3, 2)
        top = cy - d - rh
        pygame.draw.polygon(surf, (220, 225, 235),
                            [(cx, top), (cx - rw, top + rh),
                             (cx + rw, top + rh)])
        pygame.draw.line(surf, dark, (cx, top), (cx, top + rh),
                         max(tile_px // 10, 1))
        pygame.draw.circle(surf, (255, 190, 90), (cx, top + rh + 1),
                           max(tile_px // 12, 1))

    def _draw_planet_engine(self, surf, rect, tile_px):
        """行星引擎：3×3 大件（核心格居中）+ 外环 + 四向喷口。"""
        col = C.C_PLANET_ENGINE
        big = rect.inflate(tile_px * 2, tile_px * 2)
        self._base(surf, big, col, tile_px * 3)
        if tile_px < 8:
            return
        dark = _lerp(col, (0, 0, 0), 0.45)
        light = _lerp(col, (255, 255, 255), 0.5)
        cx, cy = rect.center
        # 外环（能量导流环）
        r = max(tile_px * 3 // 4, 3)
        pygame.draw.circle(surf, dark, (cx, cy), r, max(tile_px // 6, 1))
        pygame.draw.circle(surf, light, (cx, cy), max(r * 2 // 3, 2),
                           max(tile_px // 8, 1))
        # 核心
        pygame.draw.circle(surf, dark, (cx, cy), max(r // 2, 2))
        pygame.draw.circle(surf, (255, 235, 160), (cx, cy), max(r // 3, 1))
        # 四向喷口（上下左右的小矩形）
        nw = max(tile_px // 3, 2)
        nh = max(tile_px // 5, 1)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = cx + dx * (r - nh)
            ny = cy + dy * (r - nh)
            pygame.draw.rect(surf, dark,
                             (nx - nw // 2, ny - nh // 2, nw, nh))

    # ---------- 每帧绘制 ----------

    def draw(self, screen: pygame.Surface, camera):
        sw, sh = screen.get_size()
        tile_px = max(1, int(round(C.TILE * camera.zoom)))
        cam_cx = camera.x / C.TILE
        cam_cy = camera.y / C.TILE

        half_w = sw / tile_px / 2
        half_h = sh / tile_px / 2
        gx0 = int(cam_cx - half_w) - 1
        gx1 = int(cam_cx + half_w) + 1
        gy0 = int(cam_cy - half_h) - 1
        gy1 = int(cam_cy + half_h) + 1

        cpc = self.cpc
        cix0, cix1 = gx0 // cpc, gx1 // cpc
        ciy0, ciy1 = gy0 // cpc, gy1 // cpc

        for ciy in range(ciy0, ciy1 + 1):
            py = sh / 2 + (ciy * cpc - cam_cy) * tile_px
            wciy = ciy % self.cy_count
            for cix in range(cix0, cix1 + 1):
                px = sw / 2 + (cix * cpc - cam_cx) * tile_px
                surf = self._get(cix % self.cx_count, wciy, tile_px)
                screen.blit(surf, (int(px), int(py)))