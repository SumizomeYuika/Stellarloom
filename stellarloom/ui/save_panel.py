"""多存档面板（M6.20）：6 个固定槽位，存 / 读两种模式。

M6.21 起外观由 `defs/save_panel.json` 定义（控件为单位，改 JSON 即可改
标题/颜色/尺寸/文案）；业务逻辑（槽位数据、回调、动态列表）留在代码里。

交互：
- 存模式：点任意槽位 -> 存档到该槽（空槽 = 新建）
- 读模式：点有档的槽位 -> 读档；底部两条捷径读自动档 / 旧档
- 点面板外 / ✕ 关闭
"""

from __future__ import annotations

import time

import pygame

from . import uidef


class SavePanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("save_panel.json")
        self.rect = pygame.Rect(0, 0, 460, 520)
        self.mode = "save"          # "save" | "load"
        self.slots: list[dict] = []
        self.current = 0            # 当前槽（快速存档 F5 的目标，高亮显示）
        self.on_slot = None         # callable(i)，i=-1 读最新自动档，i=-2 读旧档
        self._rows: list[tuple[pygame.Rect, int]] = []

    @property
    def open(self) -> bool:
        return self.on_slot is not None

    def show(self, screen_size, mode: str, slots: list[dict], current: int,
             on_slot):
        self.mode = mode
        self.slots = slots
        self.current = current
        self.on_slot = on_slot
        self._rows.clear()
        sw, sh = screen_size
        w = min(470, int(sw * 0.92))
        h = min(560, int(sh * 0.88))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.on_slot = None
        self._rows.clear()

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if not self.open:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        # 静态控件（定义在 defs JSON）
        cid = uidef.hit_control(self.defs, self.rect, pos)
        if cid == "close":
            self.close()
            return True
        if cid == "auto":
            self.on_slot(-1)
            return True
        if cid == "legacy":
            self.on_slot(-2)
            return True
        # 槽位动态行
        for rect, i in self._rows:
            if rect.collidepoint(pos):
                self.on_slot(i)
                return True
        return True  # 面板内一律消费

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        r = self.rect
        sw, sh = screen.get_size()
        m = self.defs.meta_c

        mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
        mask.fill(m["mask"])
        screen.blit(mask, (0, 0))

        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)

        # 动态文本 / 显隐
        overrides = {"text": {}, "visible": {}}
        overrides["text"]["title"] = "读档（点槽位读取）" if self.mode == "load" \
            else "存档（点槽位保存）"
        if self.mode == "save" and self.slots:
            overrides["text"]["current_hint"] = \
                f"当前快速存档(F5)目标：{self.slots[self.current]['label']}"
        else:
            overrides["visible"]["current_hint"] = False

        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        # 关闭按钮的 ✕（画在控件底色边框之上）
        close_r = self.defs.rect(self.defs.ctrl("close"), r)
        cx, cy = close_r.center
        pygame.draw.line(screen, m["danger"], (cx - 7, cy - 7),
                         (cx + 7, cy + 7), 2)
        pygame.draw.line(screen, m["danger"], (cx - 7, cy + 7),
                         (cx + 7, cy - 7), 2)

        # 槽位动态行（模板参数在 defs 的 slots 列表控件里）
        small = self.fonts.get(14)
        tiny = self.fonts.get(12)
        sctrl = self.defs.ctrl("slots")
        sr = sctrl.raw
        item_h, gap, label_x = sr["item_h"], sr["gap"], sr["label_x"]

        self._rows.clear()
        y = r.top + sr["y"]
        lim = r.bottom + sr["h"]
        for s in self.slots:
            if y + item_h > lim:
                break
            row = pygame.Rect(r.left + 12, y, r.width - 24, item_h)
            self._draw_row(screen, row, s, small, tiny, label_x, sr, m)
            if s["index"] == self.current and self.mode == "save":
                pygame.draw.rect(screen, m["current_frame"], row, 2,
                                 border_radius=8)
            else:
                pygame.draw.rect(screen, m["row_frame"], row, 1,
                                 border_radius=8)
            y += item_h + gap

    def _draw_row(self, screen, row: pygame.Rect, s: dict, small, tiny,
                  label_x: int, sr: dict, m: dict):
        if self.mode == "load" and (not s["has"] or s["broken"]):
            base = m["muted"]
        else:
            base = m["text"]
        pygame.draw.rect(screen, m["row_bg"], row, border_radius=8)
        bl = small.render(s["label"], True, base)
        screen.blit(bl, (row.left + 10, row.centery - bl.get_height() // 2))

        if not s["has"]:
            state = sr["empty_save"] if self.mode == "save" else sr["empty_load"]
            screen.blit(tiny.render(state, True, m["muted"]),
                        (row.left + label_x, row.centery - 8))
            if self.mode == "save":
                self._row_button(screen, row, sr["btn_save_empty_text"],
                                 small, sr)
                self._rows.append((row, s["index"]))
            return

        if s["broken"]:
            screen.blit(tiny.render(sr["broken_text"], True, m["danger"]),
                        (row.left + label_x, row.centery - 8))
            if self.mode == "save":   # 覆盖可修复：仍可点
                self._rows.append((row, s["index"]))
            return

        tstr = time.strftime("%m-%d %H:%M", time.localtime(s["mtime"]))
        info = f"{tstr} · {s['planet'] or '?'} · 物品 {s['items']}"
        if s["version"]:
            info += f" · v{s['version']}"
        screen.blit(tiny.render(info, True, m["hint"]),
                    (row.left + label_x, row.centery - 8))

        if self.mode == "save":
            self._row_button(screen, row, sr["btn_save_text"], small, sr)
        else:
            self._row_button(screen, row, sr["btn_load_text"], small, sr)
        self._rows.append((row, s["index"]))

    def _row_button(self, screen, row: pygame.Rect, text: str, small, sr: dict):
        """槽位行右侧的动作按钮。"""
        w = sr["btn_w_save"] if self.mode == "save" else sr["btn_w_load"]
        bx = row.right - 14 - w
        pygame.draw.rect(screen, self.defs.meta_c["btn_bg"],
                         (bx, row.centery - 12, w, 24), border_radius=4)
        t = small.render(text, True, (235, 240, 250))
        screen.blit(t, (bx + w // 2 - t.get_width() // 2,
                        row.centery - t.get_height() // 2))