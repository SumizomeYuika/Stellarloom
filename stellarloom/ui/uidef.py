"""UI 定义层（M6.21）：JSON 描述控件 -> 加载器 -> 运行时绘制/命中。

目标：UI 以"控件"为单位定义在 `defs/*.json`，改 JSON（文案/颜色/尺寸/按钮顺序）
不用动代码，为皮肤 / 自定义布局铺路。当前示范：存档面板（SavePanel）、顶栏按钮
（TouchUI）。其余面板按同一机制逐个迁移（见 TechDebt #34）。

格式约定（defs/*.json）：

    {
      "name": "xxx",
      "meta": { "panel_bg": "#0E1220", "radius": 10, ... },   # 面板级主题参数
      "controls": [ {控件}, ... ]
    }

控件字段：
- id      唯一标识
- type    "label"（静态文本）| "button"（可点击，rect 必须给全）
- text    静态文案（动态文本由业务在 draw 时经 overrides 覆盖）
- font    字号（数字，字体表取对应尺寸）
- color   文字颜色；bg 底色；frame 边框色；active_bg 高亮态底色
- rect    平铺 x/y/w/h，或嵌套 {"x":..,"y":..,"w":..,"h":..}
  - anchor: "tl" | "tr" | "bl" | "br"，默认 "tl"
  - x/y 相对锚点：正 = 从锚点向外；负 = 相对对侧边缘向内
    （例如 anchor "tl" + y:-112 → 距底缘 112；anchor "tr" + x:-40 → 距右缘 40）
  - w/h 缺省 → label 按文字自适应（button 必须给）；负值 = 从对侧边缘向内延伸

颜色一律 #RRGGBB 或 #RRGGBBAA。

API：
- load_def(name) -> UiDef                 读取 defs/<name>.json（加载失败抛 ValueError）
- UiDef.ctrl(cid)                         按 id 取控件
- UiDef.rect(ctrl, panel_rect)            换算成 pygame.Rect（anchor/负值）
- draw_controls(screen, ui_def, panel_rect, fonts, overrides=None)
- hit_control(ui_def, panel_rect, pos) -> 命中的控件 id 或 None（只查 button）
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

# defs 目录与本文件同级：stellarloom/ui/defs/
DEFS_DIR = Path(__file__).resolve().parent / "defs"

ANCHORS = {"tl", "tr", "cc"}


def _parse_color(hex_str: str) -> tuple[int, int, int, int] | tuple[int, int, int]:
    s = hex_str.strip()
    if not s.startswith("#") or len(s) not in (7, 9):
        raise ValueError(f"颜色必须 #RRGGBB 或 #RRGGBBAA，收到 {hex_str!r}")
    r, g, b = (int(s[i:i + 2], 16) for i in (1, 3, 5))
    a = int(s[7:9], 16) if len(s) == 9 else None
    return (r, g, b, a) if a is not None else (r, g, b)


class UiCtrl:
    __slots__ = ("id", "type", "text", "font", "color", "bg", "frame",
                 "active_bg", "raw", "anchor")

    def __init__(self, data: dict, panel_meta: dict):
        self.id = data.get("id", "")
        self.type = data.get("type", "label")
        if self.type not in ("label", "button", "list"):
            raise ValueError(f"控件 {self.id!r}: 未知 type {self.type!r}")
        self.text = data.get("text", "")
        self.font = int(data.get("font", 14))
        self.color = _rr(data.get("color", panel_meta.get("text", "#E1E8F2")))
        self.bg = _rr(data.get("bg", panel_meta.get("btn_bg", "#385276")))
        self.frame = _rr(data.get("frame", panel_meta.get("btn_frame",
                                                          "#5A6482")))
        self.active_bg = _rr(data.get("active_bg",
                                      panel_meta.get("btn_active_bg",
                                                     "#466E9E")))
        raw = data.get("rect", data)
        if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
            raise ValueError(f"控件 {self.id!r}: 需要 rect(x,y[，w,h])")
        anchor = raw.get("anchor", "tl")
        if anchor not in ANCHORS:
            raise ValueError(f"控件 {self.id!r}: 未知 anchor {anchor!r}")
        self.raw = raw
        self.anchor = anchor

    @property
    def rect(self) -> dict:
        return self.raw


def _rr(v):
    """meta/控件里可能是 #hex 也可能直接是 rgb 三元组。"""
    if isinstance(v, str):
        return _parse_color(v)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return tuple(int(x) for x in v[:4]) if len(v) == 4 else \
            tuple(int(x) for x in v[:3])
    raise ValueError(f"颜色值不合法: {v!r}")


class UiDef:
    def __init__(self, data: dict, name: str):
        self.name = name
        self.meta: dict = data.get("meta", {}) or {}
        # meta 内的颜色统一解析成元组，业务代码好直接用
        self.meta_c: dict = {k: (_rr(v) if isinstance(v, str) and
                                 v.startswith("#") else v)
                             for k, v in self.meta.items()}
        controls = data.get("controls") or []
        if not isinstance(controls, list):
            raise ValueError(f"defs/{name}: controls 必须是数组")
        self.controls = [UiCtrl(c, self.meta) for c in controls]
        self._by_id = {c.id: c for c in self.controls if c.id}
        # 非控件数据的按钮列表（如顶栏 {action,text} 序列），业务直接读
        self.buttons: list[dict] = data.get("buttons") or []

    @classmethod
    def load(cls, name: str) -> "UiDef":
        p = Path(name)
        if p.is_absolute():
            path = p
        else:
            path = DEFS_DIR / (name if name.endswith(".json")
                               else name + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise ValueError(f"UI 定义文件不存在: {path}") from None
        except json.JSONDecodeError as e:
            raise ValueError(f"UI 定义 JSON 解析失败 {path}: {e}") from None
        # M6.26 皮肤化：全局 theme.json 的 meta 兜底合并（面板 meta 优先）
        theme = load_theme()
        if theme:
            data["meta"] = {**theme, **data.get("meta", {})}
        return cls(data, path.stem)

    def ctrl(self, cid: str) -> UiCtrl | None:
        return self._by_id.get(cid)

    # ---------- 几何 ----------

    @staticmethod
    def _edge(raw: dict, pw: int, ph: int):
        """x/y 换算：正 = 距上/左边，负 = 距下/右边。
        （x 是距左缘还是右缘由 sign 决定，与锚点无关）"""
        return (raw["x"] if raw["x"] >= 0 else pw + raw["x"],
                raw["y"] if raw["y"] >= 0 else ph + raw["y"])

    def rect(self, ctrl: UiCtrl, panel_rect: pygame.Rect) -> pygame.Rect:
        raw = ctrl.raw
        pw, ph = panel_rect.width, panel_rect.height
        x, y = self._edge(raw, pw, ph)
        w = raw.get("w")
        h = raw.get("h")
        if w is None or h is None:
            raise ValueError(f"控件 {ctrl.id!r}（button）必须有 w/h")
        w = pw + w if w < 0 else w     # 负宽 = 延伸/收缩到右缘
        h = ph + h if h < 0 else h
        r = pygame.Rect(int(panel_rect.left + x), int(panel_rect.top + y),
                        int(w), int(h))
        if ctrl.anchor == "tr":
            # 右上对齐：x 负 = 距右缘；x 正 = 距左缘（右缘跟着走）
            rx = raw["x"]
            r.x = (panel_rect.right + rx - w) if rx < 0 else \
                (panel_rect.left + rx)
        elif ctrl.anchor == "cc":
            # 居中：x/y 变成相对面板中心的偏移（正 = 向右/下）
            r.centerx = panel_rect.centerx + raw["x"]
            r.centery = panel_rect.centery + raw["y"]
        return r

    def label_pos(self, ctrl: UiCtrl, panel_rect: pygame.Rect, tw: int,
                  th: int) -> tuple[int, int]:
        """label 落点：tl 左上对齐；tr 右上对齐（右缘贴齐）；cc 居中。"""
        raw = ctrl.raw
        pw, ph = panel_rect.width, panel_rect.height
        if ctrl.anchor == "cc":
            # 居中：x/y 是相对面板中心的偏移（正 = 向右/下）
            return (int(panel_rect.centerx + raw["x"] - tw / 2),
                    int(panel_rect.centery + raw["y"] - th / 2))
        x, y = self._edge(raw, pw, ph)
        if ctrl.anchor == "tr":
            x -= tw
        return (int(panel_rect.left + x), int(panel_rect.top + y))


def _over(overrides, key, cid, default):
    if not overrides:
        return default
    d = overrides.get(key)
    return d.get(cid, default) if d else default


def draw_window(screen, ui_def: UiDef, panel_rect: pygame.Rect, fonts=None):
    """M6.28 窗口化：画面板底（半透明圆角）+ 边框 + 顶部标题栏。

    标题栏 = 左上角等腰梯形色块（顶边短、底边长），高度 meta.titlebar_h
    （theme 兜底 26）。标题文字由各面板自己的 defs title 控件画（挪进栏内，
    外观仍在 JSON）。面板显示标题栏 = 可拖动（Game 的 WindowMgr 命中它）。
    """
    m = ui_def.meta_c
    surf = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
    surf.fill(m["panel_bg"])
    screen.blit(surf, panel_rect.topleft)
    pygame.draw.rect(screen, m["panel_border"], panel_rect, 2,
                     border_radius=m.get("radius", 8) or 8)
    h = int(ui_def.meta.get("titlebar_h") or 26)
    color = m.get("titlebar_bg", m["panel_bg"])
    pts = [(panel_rect.left + 18, panel_rect.top),
           (panel_rect.right - 18, panel_rect.top),
           (panel_rect.right - 6, panel_rect.top + h),
           (panel_rect.left + 6, panel_rect.top + h)]
    pygame.draw.polygon(screen, color, pts)


def wrap_text(text: str, font, max_w: int) -> list[str]:
    """按像素宽换行（pygame 无内置 wrap）：逐字累积测宽，超宽即断行。

    保留换行符；空行保留。长词（如 URL）也会被拦腰断——简单起见。
    """
    out: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if cur and font.size(cur + ch)[0] > max_w:
                out.append(cur)
                cur = ch
            else:
                cur += ch
        out.append(cur)
    return out


def draw_controls(screen, ui_def: UiDef, panel_rect: pygame.Rect, fonts,
                  overrides: dict | None = None):
    """按定义逐个画控件。overrides = {"text":{cid:str}, "visible":{cid:bool},
    "active":{cid:bool}, "disabled":{cid:bool}, "color":{cid:rgb}}——
    业务动态文案 / 显隐 / 高亮 / 禁用（灰字 + 不响应 / 单控件换色）。"""
    muted = ui_def.meta_c.get("muted", (122, 132, 152))
    for c in ui_def.controls:
        if c.type == "list":   # 动态列表模板（rect/参数），由业务代码渲染
            continue
        if not _over(overrides, "visible", c.id, True):
            continue
        text = _over(overrides, "text", c.id, c.text)
        disabled = _over(overrides, "disabled", c.id, False)
        if c.type == "label":
            color = _over(overrides, "color", c.id, c.color)
            if disabled:
                color = muted
            surf = fonts.get(c.font).render(text, True, color)
            x, y = ui_def.label_pos(c, panel_rect, surf.get_width(),
                                    surf.get_height())
            screen.blit(surf, (x, y))
        else:  # button
            r = ui_def.rect(c, panel_rect)
            active = _over(overrides, "active", c.id, False)
            bg = c.active_bg if active else c.bg
            pygame.draw.rect(screen, bg, r, border_radius=round(
                panel_rect.width * 0.012) + 2)
            pygame.draw.rect(screen, c.frame, r, 1, border_radius=round(
                panel_rect.width * 0.012) + 2)
            if text:
                color = _over(overrides, "color", c.id, c.color)
                if disabled:
                    color = muted
                surf = fonts.get(c.font).render(text, True, color)
                screen.blit(surf, (r.centerx - surf.get_width() // 2,
                                   r.centery - surf.get_height() // 2))


def hit_control(ui_def: UiDef, panel_rect: pygame.Rect, pos,
                overrides: dict | None = None) -> str | None:
    """命中测试：只查 button 控件（禁用的跳过），返回控件 id 或 None。"""
    for c in ui_def.controls:
        if c.type != "button":
            continue
        if _over(overrides, "disabled", c.id, False):
            continue
        if ui_def.rect(c, panel_rect).collidepoint(pos):
            return c.id
    return None


def load_def(name: str) -> UiDef:
    return UiDef.load(name)


# M6.26：全局主题（皮肤化）——defs/theme.json 的 meta 作为**兜底**
# 合并进每个面板：面板自己的 meta 优先，缺的键从主题补。
# 改 theme.json 一处 = 全面板换色轮换皮肤。
THEME_META: dict = {}
_theme_loaded = False


def load_theme() -> dict:
    """读取 defs/theme.json 的 meta 作为全局兜底（只读一次）。"""
    global THEME_META, _theme_loaded
    if not _theme_loaded:
        _theme_loaded = True
        p = DEFS_DIR / "theme.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    THEME_META = json.load(f).get("meta", {}) or {}
            except (OSError, json.JSONDecodeError) as e:
                raise ValueError(f"主题 theme.json 解析失败: {e}") from None
    return THEME_META