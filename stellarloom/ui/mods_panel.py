"""模组管理页（M6.28，仿 minecraft）：主菜单「模组」入口打开，**全屏双栏**。

- 左栏：mods/ 下全部 mod 的**名字列表**（点击选中，当前选中高亮）
- 右栏：选中 mod 的详细信息（名称/版本/状态/描述/菜单路径）——描述超长自动换行
- 右栏底部 [禁用]/[启用] 切换（写 mods/.disabled + 热重载其余 mod，即时生效）
- [返回主菜单] 或 ✕ 关闭本页回到主菜单（本页是主菜单会话的一部分）

交互：
- 点左栏名字 → 右栏显示该 mod 详情
- 点 [禁用]/[启用] → ModManager.set_disabled（热重载 + 刷新）
- 点 [返回主菜单] / ✕ → close（Game 重新打开主菜单）
"""

from __future__ import annotations

import json

import pygame

from ..mod import ModManager
from . import uidef

# 左右栏几何
LEFT_W = 238
COL_GAP = 12
TOP = 58
ROW_H = 36
ROW_GAP = 6
BTN_H = 30


class ModsPanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("mods_panel.json")
        self.open = False
        self._mgr: ModManager | None = None
        self.rect = pygame.Rect(0, 0, 640, 480)
        self.selected: str | None = None
        self._left_rows: list[tuple[pygame.Rect, str]] = []   # (行rect, mod名)
        self._toggle_btn: pygame.Rect | None = None          # [禁用/启用]
        self._back_btn: pygame.Rect | None = None            # [返回主菜单]
        self._close_rect = pygame.Rect(0, 0, 0, 0)

    # ---------- 生命周期 ----------

    def show(self, mgr: ModManager, screen_size: tuple[int, int]):
        self._mgr = mgr
        self.open = True
        self.rect = pygame.Rect(0, 0, *screen_size)
        if self.selected not in self._names():
            # 之前选中的没了 → 默认第一个
            names = self._names()
            self.selected = names[0] if names else None
        self._left_rows.clear()
        self._toggle_btn = None
        self._back_btn = None

    def close(self):
        self.open = False
        self._mgr = None

    def _names(self) -> list[str]:
        return self._mgr.available() if self._mgr is not None else []

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if not self.open:
            return False
        if self._close_rect.collidepoint(pos):
            self.close()
            return True
        if self._back_btn is not None and self._back_btn.collidepoint(pos):
            self.close()
            return True
        if self._toggle_btn is not None and self._toggle_btn.collidepoint(pos) \
                and self.selected is not None:
            self._mgr.set_disabled(
                self.selected, not self._mgr.is_disabled(self.selected))
            return True
        for rect, name in self._left_rows:
            if rect.collidepoint(pos):
                self.selected = name
                return True
        return True   # 全屏页：什么都吃掉

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        r = self.rect
        m = self.defs.meta_c
        # 全屏底（不透明，盖住世界）
        screen.fill(m["panel_bg"])
        uidef.draw_window(screen, self.defs, r, self.fonts)
        small = self.fonts.get(15)
        tiny = self.fonts.get(12)
        mid = self.fonts.get(16)
        uidef.draw_controls(screen, self.defs, r, self.fonts)

        # ✕ 关闭按钮
        self._close_rect = pygame.Rect(r.right - 32, r.top + 3, 22, 20)
        pygame.draw.rect(screen, (60, 40, 45), self._close_rect, border_radius=6)
        pygame.draw.rect(screen, (170, 90, 90), self._close_rect, 2, border_radius=6)
        cx, cy = self._close_rect.center
        pygame.draw.line(screen, (230, 140, 140), (cx - 6, cy - 6), (cx + 6, cy + 6), 2)
        pygame.draw.line(screen, (230, 140, 140), (cx - 6, cy + 6), (cx + 6, cy - 6), 2)

        mgr = self._mgr
        if mgr is None:
            return
        names = self._names()
        bottom = r.bottom - 52

        # ---- 左栏：mod 名列表 ----
        self._left_rows.clear()
        y = r.top + TOP
        for name in names:
            if y + ROW_H > bottom:
                break
            row = pygame.Rect(r.left + 14, y, LEFT_W, ROW_H)
            sel = name == self.selected
            pygame.draw.rect(screen, m["row_sel_bg"] if sel else m["row_bg"],
                             row, border_radius=6)
            pygame.draw.rect(screen, m["row_sel_frame"] if sel else m["row_frame"],
                             row, 1, border_radius=6)
            color = (235, 240, 250) if sel else (170, 178, 194)
            screen.blit(small.render(name, True, color),
                        (row.left + 10, row.top + (ROW_H - 18) // 2))
            self._left_rows.append((row, name))
            y += ROW_H + ROW_GAP

        # ---- 右栏：选中 mod 详情 ----
        rx = r.left + LEFT_W + 40
        rw = r.right - rx - 40
        rrect = pygame.Rect(rx, r.top + TOP, rw, bottom - r.top - TOP - 6)
        pygame.draw.rect(screen, (16, 21, 32), rrect, border_radius=8)
        self._toggle_btn = None
        self._back_btn = None

        if self.selected is None or self.selected not in names:
            screen.blit(tiny.render("← 点左侧模组名查看详情", True, (110, 118, 134)),
                        (rx + 16, rrect.top + 16))
            self._draw_back(screen, mid, r, bottom)
            return

        meta = self._read_meta(self.selected)
        status = mgr.status_of(self.selected)
        disabled = mgr.is_disabled(self.selected)

        x = rrect.left + 16
        y = rrect.top + 14

        # 名称 + 版本
        name_txt = f"{self.selected}  v{meta.get('version', '0.0')}"
        screen.blit(mid.render(name_txt, True, (235, 240, 250)), (x, y))
        # 状态徽标（右上）
        st_color = {"已加载": m["ok"], "已禁用": m["muted"],
                    "未加载": m["warn"]}.get(status.split("：")[0], m["danger"])
        st = small.render(status, True, st_color)
        screen.blit(st, (rrect.right - st.get_width() - 16, y + 2))
        y += 28

        # 描述（换行，超长不截断）
        desc = meta.get("description") or "（没有描述）"
        lines = uidef.wrap_text(desc, small, rrect.width - 32)
        for ln in lines:
            screen.blit(small.render(ln, True, (150, 158, 176)), (x, y))
            y += 24

        y += 8
        # mod.json 路径
        try:
            p = (mgr.mods_dir / self.selected / "mod.json").resolve()
            path_txt = f"位置：{p}"
        except Exception:
            path_txt = "位置：mods/{name}/mod.json".format(name=self.selected)
        for ln in uidef.wrap_text(path_txt, tiny, rrect.width - 32):
            screen.blit(tiny.render(ln, True, (110, 118, 134)), (x, y))
            y += 20

        # M6.29：依赖关系
        deps = meta.get("dependencies") or {}
        if deps:
            y += 4
            dep_txt = "依赖：" + "，".join(
                f"{k}" + (f"{v}" if str(v).strip() else "")
                for k, v in deps.items())
            for ln in uidef.wrap_text(dep_txt, tiny, rrect.width - 32):
                screen.blit(tiny.render(ln, True, (150, 170, 210)), (x, y))
                y += 20

        # M6.29：配置状态（作者默认 config.json / 用户 mods/config/<name>.json）
        y += 4
        has_default = (mgr.mods_dir / self.selected / "config.json").is_file()
        cfg_path = mgr.mods_dir / "config" / f"{self.selected}.json"
        if cfg_path.is_file():
            cfg_status = f"配置：已保存（{cfg_path.name}，用户可改）"
            cfg_color = (150, 190, 150)
        elif has_default:
            cfg_status = "配置：作者有默认值 config.json（未改）"
            cfg_color = (140, 170, 200)
        else:
            cfg_status = "配置：无"
            cfg_color = (110, 118, 134)
        for ln in uidef.wrap_text(cfg_status, tiny, rrect.width - 32):
            screen.blit(tiny.render(ln, True, cfg_color), (x, y))
            y += 20

        # ---- [禁用]/[启用] 按钮（右栏底部） ----
        btn = pygame.Rect(rrect.right - 110, rrect.bottom - BTN_H - 12, 94, BTN_H)
        label = "启用" if disabled else "禁用"
        pygame.draw.rect(screen, (46, 78, 60) if disabled else (78, 60, 60),
                         btn, border_radius=6)
        t = tiny.render(label, True, (235, 240, 250))
        screen.blit(t, (btn.centerx - t.get_width() // 2,
                        btn.centery - t.get_height() // 2))
        self._toggle_btn = btn

        self._draw_back(screen, mid, r, bottom)

        # 底部统计
        bad = len([n for n in names
                   if mgr.status_of(n).startswith("加载失败")])
        screen.blit(tiny.render(
            f"共 {len(names)} 个 mod · 失败 {bad} 个 · 禁用写 mods/.disabled（重启仍生效）",
            True, (110, 118, 134)),
            (r.left + 16, r.bottom - 24))

    def _draw_back(self, screen, mid, r, bottom):
        # [返回主菜单] 固定左下
        self._back_btn = pygame.Rect(r.left + 14, bottom - 2 - BTN_H, 150, BTN_H)
        pygame.draw.rect(screen, (46, 58, 82), self._back_btn, border_radius=6)
        t = mid.render("返回主菜单", True, (235, 240, 250))
        screen.blit(t, (self._back_btn.centerx - t.get_width() // 2,
                        self._back_btn.centery - t.get_height() // 2))

    def _read_meta(self, name: str) -> dict:
        try:
            p = self._mgr.mods_dir / name / "mod.json"
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}