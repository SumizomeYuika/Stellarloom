"""仿 Minecraft Jade（WAILA）的悬停信息弹板。

在屏幕顶部中央（顶栏正下方）显示鼠标指向的格子信息：
建筑名 + 状态行（配方/进度/库存/电量/朝向…），物品行带色点、进度带进度条，
底部标注"来源 mod"（原版 / gregtech_xxx，取自 M7 注册表命名空间，通用无硬编码）。

M9 电网联动：
- 悬停发电建筑/电力塔时追加"电网"状态行（网内发电/需求、充足率进度条）；
- 鼠标所在的整张电网用半透明颜色铺层覆盖，颜色 = 充足率（绿→黄→橙→红）；
  可能有多张电网，只染色鼠标所在的那张（config 可关）。

实现要点（遵循 Docs/ModDev.md 与游戏代码）：
- 以 `ctx.mixin`（wrap="after"）挂到 `Game._draw_ui` 之后、面板/菜单绘制
  之前（Game._draw 的调用顺序保证：_draw_ui 之后才是各面板、菜单、flip），
  所以弹板 z 序恰好是"世界之上、浮窗面板之下"，每帧自动刷新。
- 纯只读：从不修改 sim/网格状态；卸载时 mixin 由加载器自动还原。
- 崩溃自愈：绘制过程任何异常只提示一次并自动禁用，绝不拖垮主循环
  （mixin 异常不会被 mod 管理器捕获，会直接炸掉 Game.run，必须自兜底）。
- 配置（M6.29 统一 config）：作者默认 config.json + 用户
  mods/config/jade.json 覆盖，重启保持。
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from stellarloom import config as C
from stellarloom.api import ModAPIError
from stellarloom.registry import (BUILDING_REGISTRY, ITEM_REGISTRY,
                                  VANILLA as VANILLA_NS)
try:
    from stellarloom.power import fmt_power   # M9 电网：kW 智能格式化
except Exception:                              # 旧版本兜底
    fmt_power = lambda kw: f"{kw:.1f} kW"      # noqa: E731

# 方向文字（与 TouchUI 的 方向→↓←↑ 一致）：0=右 1=下 2=左 3=上
_DIR_NAME = ("→ 右", "↓ 下", "← 左", "↑ 上")

_CFG: dict = {}                       # on_load 注入：ctx.cfg 合并配置
_ERR: dict = {"count": 0}             # 绘制异常计数（只报一次并自禁）


# =====================================================================
# 来源 mod：从注册表命名空间反查（M7 物品/建筑注册表，通用无硬编码）
#   "stellarloom:xxx"        → 原版
#   "gregtech_heavy:b20"     → gregtech_heavy
#   "gregtech_extra:item30"  → gregtech_extra
# =====================================================================

def _src_of_key(key) -> str | None:
    """注册表名字 key → 来源 mod 显示名；未知/无命名空间返回 None。"""
    s = str(key)
    if s.lstrip("-").isdigit():   # 未注册（老档拆了 mod 的 id）
        return None
    ns = s.split(":", 1)[0] if ":" in s else s
    if not ns or ns == s:
        return None
    return "原版" if ns == VANILLA_NS else ns


def _src_of_building(btype: int) -> str | None:
    try:
        return _src_of_key(BUILDING_REGISTRY.name_of(btype))
    except Exception:
        return None


def _src_of_item(item: int) -> str | None:
    try:
        return _src_of_key(ITEM_REGISTRY.name_of(item))
    except Exception:
        return None


# =====================================================================
# 悬停目标
# =====================================================================

def _hover_cell(game):
    """返回鼠标指向的格子 (gx, gy)；在 UI 区域/菜单/浮窗面板上 => None。"""
    menu = getattr(game, "menu", None)
    if menu is not None and getattr(menu, "open", False):
        return None
    mods_panel = getattr(game, "mods_panel", None)
    if mods_panel is not None and getattr(mods_panel, "open", False):
        return None
    pos = game._cursor_pos()
    ui = getattr(game, "ui", None)
    if ui is not None:
        if ui.in_bars(pos):
            return None
        for p in getattr(game, "panels", ()):   # 浮窗面板上不显示弹板
            if getattr(p, "open", False) and p.rect.collidepoint(pos):
                return None
    return game.mouse_grid(pos)


# =====================================================================
# 内容：每种格子一行标题 + 若干状态行
#   行格式：(kind, *payload)
#     ("t", text)          普通正文
#     ("d", text)          次要（灰）信息
#     ("i", text, item_id) 物品行：行首画物品色点
#     ("b", text, frac)    带进度条的行（frac 0~1）
# =====================================================================

def _iname(item: int) -> str:
    return C.ITEM_NAMES.get(item, f"物品 #{item}")


def _sorted_items(d: dict) -> list:
    """物品 dict → [(item, count)]，数量多的在前。"""
    return sorted(((k, v) for k, v in d.items() if v > 0),
                  key=lambda kv: -kv[1])


def _recipe_name(rid: str) -> str:
    rec = C.RECIPES.get(rid)
    if not rec:
        return rid
    return " + ".join(_iname(i) for i in rec[1])


def _machine_blocked(m, ins: dict, outs: dict) -> str | None:
    """机器为什么没在跑；正常工作中返回 None。"""
    for it, n in ins.items():
        if m.inputs.get(it, 0) < n:
            return "缺原料，等待补给"
    for o, on in outs.items():
        if m.output_space(o) < on:
            return "产物槽满，等待取走"
    return None


def _cell_items(game, gx: int, gy: int) -> list:
    """传送带本格正在运输的物品 [(item, count)]（只读查询，O(log n)）。"""
    belts = game.belts
    cell = (gx % game.grid.w, gy % game.grid.h)
    idx = belts.cell_lane.get(cell)
    if idx is None:
        return []
    lane = belts.lanes[idx]
    ci = lane.cell_index(cell)
    if ci < 0:
        return []
    lo = int(np.searchsorted(lane.positions, float(ci), side="left"))
    hi = int(np.searchsorted(lane.positions, float(ci + 1), side="left"))
    counts: dict[int, int] = {}
    for i in range(lo, hi):
        it = int(lane.items[i])
        counts[it] = counts.get(it, 0) + 1
    return _sorted_items(counts)


def _solar_power(game) -> float:
    """单块太阳能板的当前输出（与 PowerGrid 同式：昼夜 × 行星相位 × 温度）。"""
    p = game.power
    daylight = max(0.0, math.sin(2 * math.pi * p.time / p.day_length))
    orbit = p.planet.solar_factor() if p.planet is not None else 1.0
    temp = (p.planet.temperature_efficiency()
            if p.planet is not None else 1.0)
    return C.POWER_GEN[C.B_SOLAR] * daylight * orbit * temp


# =====================================================================
# 电网（M9 真电网）：空间连通的电力建筑组成一张网，可能有多张
# =====================================================================

def _power_net_at(game, x: int, y: int):
    """该格所属电网 → (net_idx, net_dict)；不在任何电网返回 None。"""
    p = getattr(game, "power", None)
    if p is None:
        return None
    g = game.grid
    key = (int(x) % g.w, int(y) % g.h)
    cell_net = getattr(p, "_cell_net", None) or {}
    i = cell_net.get(key)
    if i is None:
        return None
    nets = getattr(p, "_nets", None) or []
    if 0 <= i < len(nets):
        return i, nets[i]
    return None


def _net_lines(net_idx: int, net: dict, n_nets: int) -> list:
    """电网状态行：编号/节点数、网内发电/需求、电力充足率进度条。"""
    ratio = float(net.get("ratio", 1.0))
    label = f"电网 {net_idx + 1}/{n_nets} 张" if n_nets > 1 else "电网"
    lines = [("d", f"{label} · {len(net.get('nodes', ()))} 节点")]
    lines.append(("t", f"网内 发电 {fmt_power(net.get('gen', 0.0))} / "
                       f"需求 {fmt_power(net.get('dem', 0.0))}"))
    lines.append(("b", f"电力充足 {ratio * 100:.0f}%", ratio))
    return lines


def _describe(game, gx: int, gy: int):
    """返回 (标题, 标题色块|None, [状态行], 来源mod|None)；无可显示返回 None。"""
    grid = game.grid
    x, y = gx % grid.w, gy % grid.h
    btype = grid.get(x, y)
    overlay = grid.get_overlay(x, y)
    lines: list = []

    # ---- 分拣器（叠加层优先显示）----
    if overlay == C.B_INSERTER:
        d = grid.get_overlay_dir(x, y)
        flt = grid.get_overlay_filter(x, y)
        lines.append(("t", f"朝向 {_DIR_NAME[d % 4]}"))
        lines.append(("t", "过滤 " + (_iname(flt) if flt > 0 else "不限")))
        if btype != C.B_EMPTY:
            lines.append(("d", f"叠在 {C.BUILDING_NAMES.get(btype, '?')} 上"))
        return ("分拣器", C.BUILDING_COLORS.get(C.B_INSERTER), lines,
                _src_of_building(C.B_INSERTER))

    # ---- 传送带 ----
    if btype == C.B_BELT:
        d = int(grid.direction[y, x])
        lines.append(("t", f"朝向 {_DIR_NAME[d % 4]}"))
        items = _cell_items(game, x, y)
        if items:
            for it, n in items:
                lines.append(("i", f"{_iname(it)} ×{n}", it))
            lines.append(("d", f"本格共 {sum(n for _, n in items)} 件"))
        else:
            lines.append(("d", "空载"))
        return ("传送带", C.BUILDING_COLORS[C.B_BELT], lines,
                _src_of_building(btype))

    # ---- 采矿机 ----
    if btype == C.B_MINER:
        otype = grid.get_ore_type(x, y)
        ore_item = C.ORE_TO_ITEM.get(otype) if otype else None
        if ore_item is not None:
            lines.append(("i", f"挖 {_iname(ore_item)}（无限矿脉）", ore_item))
        else:
            lines.append(("d", "脚下无矿"))
        mn = game.miners.get(x, y)
        if mn is not None and mn.buffer:
            for it, n in _sorted_items(mn.buffer):
                lines.append(("i", f"{_iname(it)} ×{n}", it))
            lines.append(("d", f"暂存 {sum(mn.buffer.values())}/{C.MINER_BUFFER_CAP}"))
        else:
            lines.append(("d", f"暂存 0/{C.MINER_BUFFER_CAP}"))
        return ("采矿机", C.BUILDING_COLORS[C.B_MINER], lines,
                _src_of_building(btype))

    # ---- 机器（熔炉/制造台 + mod 机器，统一走 Machine 对象）----
    m = game.machines.get_machine(x, y)
    if m is not None:
        title = C.BUILDING_NAMES.get(btype, f"机器 #{btype}")
        if not m.recipe_id:
            lines.append(("d", "未设置配方（点开面板选择）"))
        else:
            rec = C.RECIPES.get(m.recipe_id)
            if rec is None:
                lines.append(("d", f"配方 {m.recipe_id} 已失效"))
            else:
                ins, outs, dur, _ = rec
                lines.append(("t", f"配方 {_recipe_name(m.recipe_id)}"))
                frac = min(m.progress / dur, 1.0) if dur > 0 else 0.0
                lines.append(("b", f"进度 {frac * 100:.0f}%", frac))
                blocked = _machine_blocked(m, ins, outs)
                if blocked:
                    lines.append(("d", blocked))
                if ins:
                    lines.append(("t", "原料 " + "  ".join(
                        f"{_iname(i)} {m.inputs.get(i, 0)}/{n}"
                        for i, n in ins.items())))
                outp = [(o, m.outputs.get(o, 0)) for o in outs]
                if sum(n for _, n in outp) > 0:
                    lines.append(("t", "产物 " + "  ".join(
                        f"{_iname(o)} ×{n}" for o, n in outp)))
        return (title, C.BUILDING_COLORS.get(btype), lines,
                _src_of_building(btype))

    # ---- 箱子 ----
    if btype == C.B_CHEST:
        ch = game.chests.get(x, y)
        if ch is not None and ch.store:
            for it, n in _sorted_items(ch.store):
                lines.append(("i", f"{_iname(it)} ×{n}/{C.CHEST_STACK}", it))
            lines.append(("d", f"共 {sum(ch.store.values())} 件"))
        else:
            lines.append(("d", "空箱"))
        return ("箱子", C.BUILDING_COLORS[C.B_CHEST], lines,
                _src_of_building(btype))

    # ---- 发电建筑（含所属电网状态）----
    if btype in (C.B_SOLAR, C.B_WIND, C.B_CORE):
        gen = C.POWER_GEN.get(btype, 0.0)
        if btype == C.B_SOLAR:
            p = _solar_power(game)
            lines.append(("t", f"发电 {p:.2f} kW"))
            lines.append(("d", "白天" if game.power.is_day else "夜晚：无输出"))
        elif btype == C.B_WIND:
            lines.append(("t", f"发电 {gen:.1f} kW（恒定）"))
        else:
            lines.append(("t", f"基础供电 {gen:.1f} kW"))
        pnet = _power_net_at(game, x, y)
        if pnet is not None:
            lines += _net_lines(pnet[0], pnet[1], game.power.net_count)
        return (C.BUILDING_NAMES.get(btype, "建筑"), C.BUILDING_COLORS.get(btype),
                lines, _src_of_building(btype))

    # ---- 电力塔（中继节点：接力并网，自身不发电不耗电）----
    if btype == C.B_POWER_POLE:
        pnet = _power_net_at(game, x, y)
        if pnet is None:
            lines.append(("d", "中继节点（尚未并入任何电网）"))
        else:
            lines.append(("d", "中继节点：接力并网，自身不发电不耗电"))
            lines += _net_lines(pnet[0], pnet[1], game.power.net_count)
        return ("电力塔", C.BUILDING_COLORS.get(C.B_POWER_POLE), lines,
                _src_of_building(btype))

    # ---- 物流塔（含 3×3 塔身空位）----
    tw = game.towers.get_tower(x, y)
    if tw is not None:
        is_supply = tw.mode == "supply"
        chip = C.BUILDING_COLORS.get(
            C.B_TOWER_SUPPLY if is_supply else C.B_TOWER_REQUEST)
        if tw.filter:
            lines.append(("i", f"过滤 {_iname(tw.filter)}", tw.filter))
        else:
            lines.append(("d", "过滤 不限"))
        if tw.inventory:
            for it, n in _sorted_items(tw.inventory):
                lines.append(("i", f"{_iname(it)} ×{n}/{C.TOWER_STACK}", it))
        else:
            lines.append(("d", "库存 空"))
        if not is_supply:
            miss = tw.missing_items()
            if miss:
                lines.append(("d", "缺货 " + "  ".join(
                    f"{_iname(i)}({n})" for i, n in list(miss.items())[:3])))
        lines.append(("d", f"无人机 {len(tw.drones)} 台"))
        src_b = (C.B_TOWER_SUPPLY if is_supply else C.B_TOWER_REQUEST)
        return ("供应塔" if is_supply else "请求塔", chip, lines,
                _src_of_building(src_b))

    # ---- 科研站 ----
    lab = game.labs.get_lab(x, y)
    if lab is not None:
        mode = lab["mode"]
        lines.append(("t", "模式 " +
                      ("研究" if mode == C.LAB_MODE_RESEARCH else "制造")))
        if mode == C.LAB_MODE_RESEARCH:
            tech = game.tech
            if tech.current is not None:
                name, cost, _, _ = C.TECH_TREE.get(
                    tech.current, (tech.current, 0, (), ""))
                frac = min(tech.progress / cost, 1.0) if cost else 0.0
                lines.append(("t", f"研究 {name}"))
                lines.append(("b", f"{int(tech.progress)}/{cost}", frac))
            else:
                lines.append(("d", "研究空闲（科技面板选题）"))
            stored = lab.get("stored", {})
            if stored:
                for it, n in _sorted_items(stored):
                    lines.append(("i", f"{_iname(it)} ×{n}", it))
            else:
                lines.append(("d", "未囤科研包"))
        else:
            rid = lab.get("recipe")
            rec = C.RECIPES.get(rid) if rid else None
            if rec is None:
                lines.append(("d", "未选制造配方"))
            else:
                ins, outs, dur, _ = rec
                lines.append(("t", f"制造 {_recipe_name(rid)}"))
                frac = min(lab["progress"] / dur, 1.0) if dur > 0 else 0.0
                lines.append(("b", f"进度 {frac * 100:.0f}%", frac))
                if ins:
                    lines.append(("t", "原料 " + "  ".join(
                        f"{_iname(i)} {lab['inputs'].get(i, 0)}/{n}"
                        for i, n in ins.items())))
                outp = [(o, lab["outputs"].get(o, 0)) for o in outs]
                if sum(n for _, n in outp) > 0:
                    lines.append(("t", "产物 " + "  ".join(
                        f"{_iname(o)} ×{n}" for o, n in outp)))
        return ("科研站", C.BUILDING_COLORS[C.B_LAB], lines,
                _src_of_building(btype))

    # ---- 太阳帆发射器 ----
    if btype == C.B_EMITTER:
        em = game.dyson.get(x, y)
        stored = em.total() if em is not None else 0
        lines.append(("t", f"储帆 {stored}/{C.DYSON_EMITTER_STORE_CAP}"))
        if em is not None and em.launched:
            lines.append(("d", f"已发射 {em.launched} 片"))
        dy = game.dyson
        if dy.total_sails() > 0:
            lines.append(("d", f"戴森云 {dy.total_sails()} 帆 · "
                               f"{dy.power_output():.0f} kW"))
        return ("太阳帆发射器", C.BUILDING_COLORS[C.B_EMITTER], lines,
                _src_of_building(btype))

    # ---- 空位：矿脉；什么都没有就不显示（Jade：空气不显示）----
    if btype == C.B_EMPTY:
        otype = grid.get_ore_type(x, y)
        ore_item = C.ORE_TO_ITEM.get(otype) if otype else None
        if ore_item is not None:
            lines.append(("i", f"种类 {_iname(ore_item)}", ore_item))
            lines.append(("d", "无建筑 · 右键开采"))
            return ("矿脉", C.ORE_COLORS.get(otype, C.ORE_FALLBACK_COLOR),
                    lines, _src_of_item(ore_item))
        return None

    # ---- 其余已知建筑兜底 ----
    return (C.BUILDING_NAMES.get(btype, f"建筑 #{btype}"),
            C.BUILDING_COLORS.get(btype), lines, _src_of_building(btype))


# =====================================================================
# 绘制：Jade 风格弹板（顶部中央，半透明深底 + 细边框，标题带色块）
# =====================================================================

def _bar(screen, x: int, y: int, w: int, frac: float):
    pygame.draw.rect(screen, (44, 54, 74), pygame.Rect(x, y, w, 6),
                     border_radius=3)
    fw = int(w * max(0.0, min(frac, 1.0)))
    if fw > 0:
        pygame.draw.rect(screen, (90, 220, 130), pygame.Rect(x, y, fw, 6),
                         border_radius=3)


# =====================================================================
# 电网覆盖层：鼠标所在的那张电网整网半透明染色，颜色 = 电力充足率（负荷）
#   绿=充足(≥75%) → 黄(≥50%) → 橙(≥25%) → 红=缺电(<25%)
# =====================================================================

_NET_LEVELS = (
    (0.75, (80, 220, 90)),    # 充足 绿
    (0.50, (230, 210, 60)),   # 偏紧 黄
    (0.25, (240, 150, 60)),   # 吃紧 橙
    (0.00, (235, 70, 70)),    # 缺电 红
)
_TILE_CACHE: dict = {}


def _net_color(ratio: float):
    r = min(1.0, max(0.0, float(ratio)))
    for thr, col in _NET_LEVELS:
        if r >= thr:
            return col
    return _NET_LEVELS[-1][1]


def _draw_net_overlay(game, net, cfg):
    """把整张电网的所有节点格铺一层半透明色（只读渲染，不改 sim 状态）。"""
    screen = game.screen
    size = screen.get_size()
    cam = game.camera
    tpx = cam.tile_px
    if tpx < 2:
        return
    color = _net_color(net.get("ratio", 1.0))
    alpha = int(cfg.get("net_overlay_alpha", 80))
    key = (color, alpha, tpx)
    tile = _TILE_CACHE.get(key)
    if tile is None:
        tile = pygame.Surface((tpx, tpx), pygame.SRCALPHA)
        tile.fill((*color, alpha))
        glow = tuple(min(255, c + 50) for c in color)
        pygame.draw.rect(tile, (*glow, alpha + 70), tile.get_rect(), 1)
        _TILE_CACHE[key] = tile
    sw, sh = size
    for x, y, _bt in net.get("nodes", ()):
        sx, sy = cam.world_to_screen(x * C.TILE, y * C.TILE, size)
        sx, sy = int(sx), int(sy)
        if sx < -tpx or sx > sw or sy < -tpx or sy > sh:
            continue
        screen.blit(tile, (sx, sy))


def _render_box(game, title, chip, lines, cfg):
    screen = game.screen
    sw = screen.get_width()
    fonts = game.fonts
    tsize = max(14, int(cfg.get("title_size", 20)))
    fsize = max(12, int(cfg.get("font_size", 18)))
    title_font = fonts.get(tsize)
    body_font = fonts.get(fsize)
    pad = 10
    gap = 2
    bar_w = 76
    chip_w = 20 if chip is not None else 0   # 12px 色块 + 8px 间距

    title_surf = title_font.render(str(title), True, (255, 255, 255))
    rows = []          # (surf, frac|None, item色|None)
    w = chip_w + title_surf.get_width()
    for kind, *rest in lines:
        if kind == "i":
            text, item = str(rest[0]), rest[1]
            col = C.ITEM_COLORS.get(item, (200, 200, 200))
            surf = body_font.render(text, True, (226, 232, 242))
            rows.append((surf, None, col))
            w = max(w, surf.get_width() + 20)
        elif kind == "b":
            text, frac = str(rest[0]), float(rest[1])
            surf = body_font.render(text, True, (226, 232, 242))
            rows.append((surf, frac, None))
            w = max(w, surf.get_width() + 10 + bar_w)
        elif kind == "d":
            surf = body_font.render(str(rest[0]), True, (152, 162, 178))
            rows.append((surf, None, None))
            w = max(w, surf.get_width())
        else:
            surf = body_font.render(str(rest[0]), True, (226, 232, 242))
            rows.append((surf, None, None))
            w = max(w, surf.get_width())
    w = min(w + pad * 2, int(sw * 0.92))
    h = pad * 2 + title_surf.get_height() + 4 + \
        sum(s.get_height() + gap for s, _, _ in rows)
    x = (sw - w) // 2
    y = int(getattr(game.ui, "top_h", 54)) + 8
    if y + h > screen.get_height() - 4:
        y = max(4, screen.get_height() - h - 4)

    box = pygame.Surface((w, h), pygame.SRCALPHA)
    box.fill((18, 22, 34, int(cfg.get("bg_alpha", 225))))
    pygame.draw.rect(box, (120, 160, 215), box.get_rect(), 1, border_radius=8)
    screen.blit(box, (x, y))

    cx = x + pad
    cy = y + pad
    if chip is not None:
        ch = pygame.Rect(cx, cy + (title_surf.get_height() - 12) // 2, 12, 12)
        pygame.draw.rect(screen, chip, ch, border_radius=3)
        pygame.draw.rect(screen, (70, 84, 112), ch, 1, border_radius=3)
        cx += chip_w
    screen.blit(title_surf, (cx, cy))
    cy += title_surf.get_height() + 4
    for surf, frac, col in rows:
        if frac is not None:
            screen.blit(surf, (x + pad, cy))
            _bar(screen, x + w - pad - bar_w,
                 cy + (surf.get_height() - 6) // 2, bar_w, frac)
        elif col is not None:
            rad = 5
            pygame.draw.circle(screen, col,
                               (x + pad + rad, cy + surf.get_height() // 2),
                               rad)
            screen.blit(surf, (x + pad + 18, cy))
        else:
            screen.blit(surf, (x + pad, cy))
        cy += surf.get_height() + gap


def _draw0(game, cfg):
    if not cfg.get("enabled", True):
        return
    cell = _hover_cell(game)
    if cell is None:
        return
    # 电网覆盖层：鼠标所在那张电网整网染色（可能有多个电网，只染这一张）。
    # 覆盖层只是辅助显示，出错不影响弹板与主循环。
    if cfg.get("show_net_overlay", True):
        try:
            pnet = _power_net_at(game, cell[0], cell[1])
            if pnet is not None:
                _draw_net_overlay(game, pnet[1], cfg)
        except Exception:
            pass
    info = _describe(game, cell[0], cell[1])
    if not info:
        return
    title, chip, lines, src = info
    if cfg.get("show_source", True) and src:
        lines = list(lines) + [("d", f"来源 {src}")]
    if cfg.get("show_coords", True):
        lines = list(lines) + [("d", f"坐标 ({cell[0]}, {cell[1]})")]
    max_lines = max(3, int(cfg.get("max_lines", 10)))
    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines] + [("d", f"… 还有 {extra} 行")]
    _render_box(game, title, chip, lines, cfg)


def _draw_jade(game):
    """每帧入口：任何异常只提示一次并自禁，不炸主循环。"""
    try:
        _draw0(game, _CFG)
    except Exception:
        _ERR["count"] += 1
        if _ERR["count"] == 1:
            import traceback
            traceback.print_exc()
            print("[mod jade] 悬停弹板绘制出错，已自动禁用"
                  "（修好后删 mods/config/jade.json 或把 enabled 改回 true）")
            _CFG["enabled"] = False


# =====================================================================
# 生命周期
# =====================================================================

def on_load(ctx):
    global _CFG
    _CFG = ctx.cfg   # 作者默认 config.json ⊕ 用户 mods/config/jade.json
    game = getattr(ctx, "_game", None)
    if game is None or not hasattr(game, "_draw_ui"):
        raise ModAPIError("jade 需要游戏前端（Game._draw_ui）才能挂载绘制钩子")

    def after_draw_ui(self, result, **kw):
        _draw_jade(self)
        return None

    ctx.mixin("stellarloom.core.game.Game", "_draw_ui",
              after_draw_ui, wrap="after")
    ctx.log("Jade 风格悬停信息弹板已挂载（顶部中央，每帧随鼠标刷新）")
    if _CFG.get("enabled", True):
        ctx.toast("Jade 已启用：指向建筑查看信息", 2.0)
    else:
        ctx.log("jade 配置 enabled=false，弹板关闭"
                "（可改 mods/config/jade.json 重新启用）")


def on_unload(ctx):
    ctx.log("jade 卸载：mixin 与悬停弹板由系统自动还原")
    ctx.toast("Jade 已卸载", 1.5)