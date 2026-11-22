"""手势识别：单指点按/拖拽/长按 + 双指捏合。

只输出语义事件，不碰游戏逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

TAP_MAX_MS = 200
TAP_MAX_MOVE = 10
LONGPRESS_MS = 500
# 长按已触发后允许的手指抖动（px）：触屏按住不放几乎必然轻微滑动，
# 若还按 TAP_MAX_MOVE 判定，长按会被误降级成拖动，采矿永远采不出来。
LONGPRESS_DRIFT = 24
PINCH_MIN_DELTA = 8


@dataclass
class TapEvent:
    pos: tuple[float, float]


@dataclass
class LongPressEvent:
    """长按（按住不动超过 LONGPRESS_MS）——手动采矿用。

    held 表示这是持续触发（每帧一次，用于累加进度）；
    released 表示手指抬起（用于结束本次长按）。
    """
    pos: tuple[float, float]
    held: bool = True


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

    def poll_longpress(self) -> list:
        """每帧调用一次：判断哪些手指已经按住超过 LONGPRESS_MS。

        返回 LongPressEvent 列表（held=True）。只在第一次跨过阈值时输出一次，
        后续由调用方用 `is_holding` 判断是否继续按住；抬起时输出 held=False。
        """
        out = []
        now = pygame.time.get_ticks()
        for tid, info in self.touches.items():
            if info.get("moved"):
                continue
            if info.get("lp_done"):
                continue
            if now - info["t"] < LONGPRESS_MS:
                continue
            info["lp_done"] = True
            out.append(LongPressEvent(info["pos"], True))
        return out

    def holding_pos(self):
        """当前仍按在原地的长按手指位置；没有则 None。"""
        for info in self.touches.values():
            if info.get("lp_done") and not info.get("moved"):
                return info["pos"]
        return None

    def is_holding(self) -> bool:
        return self.holding_pos() is not None

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
            # 长按已成立：抖动阈值放宽（否则触屏按住会被判成拖动，采矿中断）
            limit = LONGPRESS_DRIFT if info.get("lp_done") else TAP_MAX_MOVE
            if abs(dx) > limit or abs(dy) > limit:
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