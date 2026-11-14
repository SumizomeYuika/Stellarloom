"""相机：平移、缩放，世界坐标 <-> 屏幕坐标换算。

纯数值状态，不依赖 pygame（逻辑层可 headless）。pan 接受的 keys 是
pygame.key.get_pressed() 这类可按键盘码索引的可下标对象。
"""

from __future__ import annotations

from .. import config as C

# pygame.KeyCode 常量数值（WASD=ASCII，方向键固定值）：
# camera 属逻辑层，不 import pygame，但保持与 pygame 常量一致。
_K_W, _K_A, _K_S, _K_D = 119, 97, 115, 100
_K_UP, _K_DOWN, _K_LEFT, _K_RIGHT = 273, 274, 276, 275


class Camera:
    def __init__(self, world_pixel_w: int, world_pixel_h: int):
        # 相机中心点（世界像素坐标）
        self.x = world_pixel_w / 2
        self.y = world_pixel_h / 2
        self.zoom = 0.75  # 默认稍微缩小，能看到更多
        self.world_pw = world_pixel_w
        self.world_ph = world_pixel_h

    # ---------- 输入 ----------

    def pan(self, keys, dt: float):
        speed = C.CAM_SPEED * dt / self.zoom
        if keys[_K_W] or keys[_K_UP]:
            self.y -= speed
        if keys[_K_S] or keys[_K_DOWN]:
            self.y += speed
        if keys[_K_A] or keys[_K_LEFT]:
            self.x -= speed
        if keys[_K_D] or keys[_K_RIGHT]:
            self.x += speed
        # 相机允许卷绕，保持坐标在 [0, world) 内
        self.x %= self.world_pw
        self.y %= self.world_ph

    def zoom_at(self, screen_pos: tuple[int, int], factor: float,
                screen_size: tuple[int, int]):
        old = self.zoom
        self.zoom = max(C.ZOOM_MIN, min(C.ZOOM_MAX, self.zoom * factor))
        if self.zoom == old:
            return
        # 缩放时保持鼠标下的世界点不动
        wx, wy = self.screen_to_world(*screen_pos, screen_size=screen_size)
        self.x, self.y = self._anchor(wx, wy, screen_pos, screen_size)

    def _anchor(self, wx, wy, screen_pos, screen_size):
        sw, sh = screen_size
        x = wx - (screen_pos[0] - sw / 2) / self.zoom
        y = wy - (screen_pos[1] - sh / 2) / self.zoom
        return x % self.world_pw, y % self.world_ph

    # ---------- 换算 ----------

    def world_to_screen(self, wx: float, wy: float,
                        screen_size: tuple[int, int]) -> tuple[float, float]:
        sw, sh = screen_size
        tp = self.tile_px  # 整数格子像素，与 ChunkRenderer 渲染同式
        dx = (wx - self.x) % self.world_pw
        dy = (wy - self.y) % self.world_ph
        # 取最近路径（卷绕后距离超过半图则从另一侧画）
        if dx > self.world_pw / 2:
            dx -= self.world_pw
        if dy > self.world_ph / 2:
            dy -= self.world_ph
        # 世界像素差 -> 格子数 -> 整数渲染像素（缩放时格子与渲染严格对齐）
        return (sw / 2 + (dx / C.TILE) * tp,
                sh / 2 + (dy / C.TILE) * tp)

    def screen_to_world(self, sx: float, sy: float,
                        screen_size: tuple[int, int]) -> tuple[float, float]:
        sw, sh = screen_size
        tp = self.tile_px
        wx = (self.x + (sx - sw / 2) / tp * C.TILE) % self.world_pw
        wy = (self.y + (sy - sh / 2) / tp * C.TILE) % self.world_ph
        return wx, wy

    def screen_to_grid(self, sx: float, sy: float,
                       screen_size: tuple[int, int],
                       grid_w: int, grid_h: int) -> tuple[int, int]:
        wx, wy = self.screen_to_world(sx, sy, screen_size)
        return int(wx // C.TILE) % grid_w, int(wy // C.TILE) % grid_h

    @property
    def tile_px(self) -> int:
        """格子渲染像素：与 ChunkRenderer 的取整式一致，缩放时格子不错位。"""
        return max(1, int(round(C.TILE * self.zoom)))