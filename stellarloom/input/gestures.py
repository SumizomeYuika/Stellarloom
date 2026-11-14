"""手势识别：单指点按/拖拽/长按 + 双指捏合。

只输出语义事件，不碰游戏逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

TAP_MAX_MS = 200
TAP_MAX_MOVE = 10
LONGPRESS_MS = 500
PINCH_MIN_DELTA = 8


@dataclass
class TapEvent:
    pos: tuple[float, float]


@dataclass
class DragEvent:
    start: tuple[float, float]
    current: tuple[float, float]
    delta: tuple[float, float]  # 帧间增量位移（不是累计）


@dataclass
class PinchEvent:
    center: tuple[float, float]
    factor: float


class GestureRecognizer:
    def __init__(self):
        self.touches: dict[int, dict] = {}
        self._pinch_dist = 0.0
        self._pinch_center = (0.0, 0.0)

    def handle(self, event: pygame.event.Event, screen_size) -> list:
        out = []
        sw, sh = screen_size
        et = event.type

        if et == pygame.FINGERDOWN:
            pos = (event.x * sw, event.y * sh)
            self.touches[event.finger_id] = {
                "start": pos, "pos": pos, "last": pos,
                "t": pygame.time.get_ticks(), "moved": False,
            }
            if len(self.touches) == 2:
                self._start_pinch()
        elif et == pygame.FINGERMOTION:
            tid = event.finger_id
            if tid not in self.touches:
                return out
            pos = (event.x * sw, event.y * sh)
            info = self.touches[tid]
            # 帧间增量（相对上次事件位置）
            ddx = pos[0] - info["last"][0]
            ddy = pos[1] - info["last"][1]
            info["pos"] = pos
            info["last"] = pos
            dx = pos[0] - info["start"][0]
            dy = pos[1] - info["start"][1]
            if abs(dx) > TAP_MAX_MOVE or abs(dy) > TAP_MAX_MOVE:
                info["moved"] = True
            if len(self.touches) == 2:
                out.extend(self._pinch_motion())
            elif info["moved"]:
                out.append(DragEvent(info["start"], pos, (ddx, ddy)))
        elif et == pygame.FINGERUP:
            tid = event.finger_id
            info = self.touches.pop(tid, None)
            if len(self.touches) < 2:
                self._pinch_dist = 0.0
            if info is None:
                return out
            elapsed = pygame.time.get_ticks() - info["t"]
            if not info["moved"] and elapsed < TAP_MAX_MS:
                out.append(TapEvent(info["start"]))
        return out

    # ---------- 捏合 ----------

    def _two_points(self):
        pts = list(self.touches.values())
        if len(pts) != 2:
            return None
        a, b = pts[0]["pos"], pts[1]["pos"]
        dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        center = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        return dist, center

    def _start_pinch(self):
        r = self._two_points()
        if r:
            self._pinch_dist, self._pinch_center = r

    def _pinch_motion(self) -> list:
        r = self._two_points()
        if not r:
            return []
        dist, center = r
        self._pinch_center = center
        if self._pinch_dist <= 0:
            self._pinch_dist = dist
            return []
        delta = abs(dist - self._pinch_dist)
        if delta < PINCH_MIN_DELTA:
            return []
        factor = dist / self._pinch_dist
        self._pinch_dist = dist
        return [PinchEvent(center, factor)]