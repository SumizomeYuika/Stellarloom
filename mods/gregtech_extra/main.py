"""格雷科技·星海扩展（gregtech_extra）

「格雷科技」主题扩展包，**依赖 gregtech_heavy**（mod.json dependencies ≥1.0，
加载器按依赖拓扑序保证重工先加载）：

1. 新矿脉：锡 / 煤 / 石英 / 锰 / 钨（世界生成 + 挖矿掉落 + 渲染上色）
2. 新机器：聚变反应堆（烧氘芯供电）/ 金属成型机 / 化工厂 / 粒子加速器
3. 多方块结构：耐热砖块 3×3 环 + 核心 → 大型高炉；合金框架 3×3 环 + 核心
   → 重型装配平台。环不完整时核心机器无法加工（有专门的多方块判定）。
4. 聚变供电：反应堆加载氘芯燃料后，按“能正常生产的台数”向电网注电。
5. 与 gregtech_heavy 联动（依赖声明保证加载顺序 → on_load 直接升级）：
   高级科技改吃「结构/量子矩阵」，若干配方升级为使用重工产的
   钢锭/铜锭/石墨烯/超导线圈 等精料。全程登记还原，卸载干净。

M6.29 / M7.dev 对齐（v1.1）：
  * mod.json 声明依赖 gregtech_heavy（>=1.0）——缺重工时本 mod 以
    “缺少依赖”干净失败，不再有“跑起来但悄悄退化成残缺版”的尴尬。
  * 作者默认配置 config.json：vein_counts（各矿脉条数）、reactor_power
    （单台聚变输出）、toasts；玩家可用 mods/config/gregtech_extra.json 覆盖。
  * 物品用**固定数字注册**（官方 M7 注册表的旧式兼容路径，token =
    gregtech_extra:item<id>）：旧存档数字可反查、新存档以名字持久化，
    存档零漂移；机器对象/配方内部照旧走数字 id。

设计约束（全部可卸载还原）：
- 物品 ID 2000+，建筑类型 30-37，矿脉类型 4-8（不与原版/重工冲突）
- 机器网络 sync 组合式 replace：最内层跑“安全原版补录”，每层只补/清
  自己管辖的类型，谁先装都行（重工/本 mod 单装或联装都不互相清场）
- Machine 有 __slots__，多方块状态用模块级 {id(machine): bool} 登记
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from stellarloom import config as C
from stellarloom.api import EnvType
from stellarloom.production.machines import Machine, MachineNetwork
from stellarloom.render.layers import ChunkRenderer
from stellarloom.ui import touch_ui as TUI

# =====================================================================
# 0) 常量
# =====================================================================

# ---- 矿脉类型（grid.ore_type 取值；原版 0-3 已占用）----
ORE_TIN = 4
ORE_COAL = 5
ORE_QUARTZ = 6
ORE_MANGANESE = 7
ORE_TUNGSTEN = 8

# ---- 建筑类型（原版 1-14 / 重工 20-23）----
B_X_REACTOR = 30          # 聚变反应堆（机器，烧氘芯供电）
B_X_FORMER = 31           # 金属成型机（机器）
B_X_CHEM = 32             # 化工厂（机器）
B_X_ACCEL = 33            # 粒子加速器（机器）
B_X_BRICK = 34            # 耐热砖块（多方块环：大型高炉）
B_X_LARGE_FURNACE = 35    # 大型高炉核心（机器，多方块）
B_X_FRAME = 36            # 合金框架（多方块环：重型装配平台）
B_X_HEAVY_PLATFORM = 37   # 重型装配平台核心（机器，多方块）

MACHINE_TYPES = (B_X_REACTOR, B_X_FORMER, B_X_CHEM, B_X_ACCEL,
                 B_X_LARGE_FURNACE, B_X_HEAVY_PLATFORM)
RING_TYPES = (B_X_BRICK, B_X_FRAME)
# 核心类型 → 它的环砖类型
MULTI_CORES = {B_X_LARGE_FURNACE: B_X_BRICK,
               B_X_HEAVY_PLATFORM: B_X_FRAME}
MULTI_CORE_TYPES = tuple(MULTI_CORES)  # (35, 37)
RING8 = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
              if (dx, dy) != (0, 0))

# ---- 物品（原版 1-14/101-112，重工 1000+）----
I_ORE_TIN = 2001          # 锡矿石
I_ORE_COAL = 2002         # 煤矿石
I_ORE_QUARTZ = 2003       # 石英矿石
I_ORE_MANGANESE = 2004    # 锰矿石
I_ORE_TUNGSTEN = 2005     # 钨矿石
I_TIN_INGOT = 2010        # 锡锭
I_COAL = 2011             # 煤
I_QUARTZ = 2012           # 石英
I_MANGANESE_INGOT = 2013  # 锰锭
I_TUNGSTEN_INGOT = 2014   # 钨锭
I_BRONZE_INGOT = 2015     # 青铜锭
I_MNSTEEL_INGOT = 2016    # 锰钢锭
I_WSTEEL_INGOT = 2017     # 钨钢锭
I_GLASS = 2018            # 玻璃
I_GRAPHITE = 2019         # 石墨
I_SIC = 2020              # 碳化硅
I_TIN_PLATE = 2021        # 锡板
I_BRONZE_PLATE = 2022     # 青铜板
I_MN_PLATE = 2023         # 锰钢板
I_W_PLATE = 2024          # 钨钢板
I_DEUTERIUM = 2025        # 氘芯（聚变燃料）
I_HELIUM3 = 2026          # 氦-3
I_PLASMA = 2027           # 等离子体
I_ANTIMATTER = 2028       # 反物质
I_ANTIMATTER_ENGINE = 2029  # 反物质引擎
I_WARP_DRIVE = 2030       # 曲率驱动器
I_MACH_REACTOR = 2040     # 聚变反应堆（物品）
I_MACH_FORMER = 2041      # 金属成型机
I_MACH_CHEM = 2042        # 化工厂
I_MACH_ACCEL = 2043       # 粒子加速器
I_BRICK_ITEM = 2044       # 耐热砖块
I_LARGE_CORE_ITEM = 2045  # 大型高炉核心
I_FRAME_ITEM = 2046       # 合金框架
I_PLATFORM_CORE_ITEM = 2047  # 重型装配平台核心

ITEMS = {
    I_ORE_TIN: ("锡矿石", "#D6D9E4"),
    I_ORE_COAL: ("煤矿石", "#4A4850"),
    I_ORE_QUARTZ: ("石英矿石", "#E4DEC0"),
    I_ORE_MANGANESE: ("锰矿石", "#9A90B2"),
    I_ORE_TUNGSTEN: ("钨矿石", "#92929C"),
    I_TIN_INGOT: ("锡锭", "#DEE0EA"),
    I_COAL: ("煤", "#3E3E46"),
    I_QUARTZ: ("石英", "#EEF2DE"),
    I_MANGANESE_INGOT: ("锰锭", "#A89EC6"),
    I_TUNGSTEN_INGOT: ("钨锭", "#B0B0C0"),
    I_BRONZE_INGOT: ("青铜锭", "#D08A3E"),
    I_MNSTEEL_INGOT: ("锰钢锭", "#A2B8E0"),
    I_WSTEEL_INGOT: ("钨钢锭", "#B8C0EA"),
    I_GLASS: ("玻璃", "#E2F8F8"),
    I_GRAPHITE: ("石墨", "#40404A"),
    I_SIC: ("碳化硅", "#8290D6"),
    I_TIN_PLATE: ("锡板", "#EAEAF2"),
    I_BRONZE_PLATE: ("青铜板", "#DC9850"),
    I_MN_PLATE: ("锰钢板", "#AABCE8"),
    I_W_PLATE: ("钨钢板", "#C2CCF2"),
    I_DEUTERIUM: ("氘芯", "#5ADCCB"),
    I_HELIUM3: ("氦-3", "#BCEAEA"),
    I_PLASMA: ("等离子体", "#F47CDA"),
    I_ANTIMATTER: ("反物质", "#EA5CF2"),
    I_ANTIMATTER_ENGINE: ("反物质引擎", "#F2A852"),
    I_WARP_DRIVE: ("曲率驱动器", "#5CEAF2"),
}
# 机器/建材物品在 MACHINES 表里统一注册（避免重复 add_item）

# ---- 机器数据：(btype, 物品, 名称, 颜色, 耗电, 解锁科技) ----
MACHINES = (
    (B_X_REACTOR, I_MACH_REACTOR, "聚变反应堆", (60, 70, 176), 0.5, "ex_reactor"),
    (B_X_FORMER, I_MACH_FORMER, "金属成型机", (160, 168, 184), 1.0, "ex_form"),
    (B_X_CHEM, I_MACH_CHEM, "化工厂", (96, 176, 120), 1.5, "ex_chem"),
    (B_X_ACCEL, I_MACH_ACCEL, "粒子加速器", (180, 88, 216), 2.0, "ex_accel"),
    (B_X_BRICK, I_BRICK_ITEM, "耐热砖块", (176, 92, 72), 0.0, "ex_mb"),
    (B_X_LARGE_FURNACE, I_LARGE_CORE_ITEM, "大型高炉核心", (184, 104, 52), 1.0, "ex_mb"),
    (B_X_FRAME, I_FRAME_ITEM, "合金框架", (106, 120, 190), 0.0, "ex_mb2"),
    (B_X_HEAVY_PLATFORM, I_PLATFORM_CORE_ITEM, "重型装配平台核心", (64, 80, 152), 2.0, "ex_mb2"),
)

# ---- 科技 ----
# tid: (名称, 消耗包配方 rid, 前置, 描述)
TECHS = {
    "ex_mining": ("采掘学 I", "science_blue", ("circuit1",),
                  "新矿脉辨识与冶炼：锡、煤、石英"),
    "ex_form": ("金属成型 I", "science_blue", ("ex_mining",),
                "金属成型机：锭 → 板材/型材"),
    "ex_chem": ("化工厂 I", "science_blue", ("ex_mining",),
                "化工厂：合金与化工链（青铜 / 玻璃 / 石墨）"),
    "ex_alloy": ("合金学 I", "science_red", ("ex_chem",),
                 "锰、钨矿冶炼与合金钢（锰钢 / 钨钢）"),
    "ex_mb": ("大型结构 I", "science_red", ("ex_chem",),
              "多方块结构：耐热砖块环 → 大型高炉核心"),
    "ex_reactor": ("聚变供电 I", "science_red", ("ex_alloy",),
                   "聚变反应堆：氘芯燃烧并入电网"),
    "ex_accel": ("粒子加速 I", "science_red", ("ex_reactor",),
                 "粒子加速器：等离子体对撞出反物质"),
    "ex_mb2": ("重型装配 II", "science_red", ("ex_accel", "ex_mb"),
               "合金框架环 → 重型装配平台：曲率驱动器"),
}
TECH_COSTS = (10, 20, 22, 30, 35, 45, 60, 75)

# ---- 配方：(rid, 输入, 输出, 时长, 允许机器, 解锁科技) ----
RECIPES = (
    # 冶炼（原版熔炉）
    ("ex_smelt_tin", {I_ORE_TIN: 1}, {I_TIN_INGOT: 1}, 1.0, (C.B_FURNACE,), "ex_mining"),
    ("ex_smelt_coal", {I_ORE_COAL: 1}, {I_COAL: 1}, 0.8, (C.B_FURNACE,), "ex_mining"),
    ("ex_smelt_quartz", {I_ORE_QUARTZ: 1}, {I_QUARTZ: 1}, 1.2, (C.B_FURNACE,), "ex_mining"),
    ("ex_smelt_mn", {I_ORE_MANGANESE: 1}, {I_MANGANESE_INGOT: 1}, 2.5, (C.B_FURNACE,), "ex_alloy"),
    ("ex_smelt_w", {I_ORE_TUNGSTEN: 1}, {I_TUNGSTEN_INGOT: 1}, 3.5, (C.B_FURNACE,), "ex_alloy"),
    # 金属成型机（锭 → 板）
    ("ex_form_tin", {I_TIN_INGOT: 1}, {I_TIN_PLATE: 1}, 0.5, (B_X_FORMER,), "ex_form"),
    ("ex_form_bronze", {I_BRONZE_INGOT: 1}, {I_BRONZE_PLATE: 1}, 0.5, (B_X_FORMER,), "ex_form"),
    ("ex_form_mn", {I_MNSTEEL_INGOT: 1}, {I_MN_PLATE: 1}, 0.6, (B_X_FORMER,), "ex_alloy"),
    ("ex_form_w", {I_WSTEEL_INGOT: 1}, {I_W_PLATE: 1}, 0.6, (B_X_FORMER,), "ex_alloy"),
    # 化工厂
    ("ex_bronze", {I_TIN_INGOT: 1, C.I_COPPER_ORE: 1}, {I_BRONZE_INGOT: 2}, 1.5, (B_X_CHEM,), "ex_chem"),
    ("ex_graphite", {I_COAL: 2}, {I_GRAPHITE: 1}, 2.0, (B_X_CHEM,), "ex_chem"),
    ("ex_glass", {I_QUARTZ: 1}, {I_GLASS: 1}, 1.0, (B_X_CHEM,), "ex_chem"),
    ("ex_sic", {I_QUARTZ: 2, I_COAL: 1}, {I_SIC: 1}, 3.0, (B_X_CHEM,), "ex_chem"),
    ("ex_mn_steel", {I_MANGANESE_INGOT: 1, C.I_IRON_PLATE: 2}, {I_MNSTEEL_INGOT: 1}, 3.0, (B_X_CHEM,), "ex_alloy"),
    ("ex_w_steel", {I_TUNGSTEN_INGOT: 1, C.I_IRON_PLATE: 3}, {I_WSTEEL_INGOT: 1}, 3.5, (B_X_CHEM,), "ex_alloy"),
    ("ex_dusterium", {I_W_PLATE: 2, I_GLASS: 4}, {I_DEUTERIUM: 1}, 8.0, (B_X_CHEM,), "ex_reactor"),
    # 聚变反应堆（燃料 → 氦-3 + 等离子体；燃烧期间向电网注电）
    ("ex_fuel", {I_DEUTERIUM: 1}, {I_HELIUM3: 2, I_PLASMA: 2}, 20.0, (B_X_REACTOR,), "ex_reactor"),
    # 粒子加速器
    ("ex_antimatter", {I_PLASMA: 4, I_QUARTZ: 8}, {I_ANTIMATTER: 1}, 8.0, (B_X_ACCEL,), "ex_accel"),
    ("ex_antimatter_engine", {I_ANTIMATTER: 2, I_W_PLATE: 2, I_GRAPHITE: 4},
     {I_ANTIMATTER_ENGINE: 1}, 10.0, (B_X_ACCEL,), "ex_accel"),
    # 多方块：大型高炉核心（批量配方）
    ("ex_mb_bronze_big", {I_TIN_INGOT: 3, C.I_COPPER_ORE: 3}, {I_BRONZE_INGOT: 6}, 6.0, (B_X_LARGE_FURNACE,), "ex_mb"),
    ("ex_mb_glass_big", {I_QUARTZ: 4}, {I_GLASS: 6}, 4.0, (B_X_LARGE_FURNACE,), "ex_mb"),
    ("ex_mb_sic_big", {I_QUARTZ: 6, I_COAL: 3}, {I_SIC: 4}, 6.0, (B_X_LARGE_FURNACE,), "ex_mb"),
    # 多方块：重型装配平台核心（终局）
    ("ex_warp", {I_ANTIMATTER_ENGINE: 1, I_SIC: 8, I_GLASS: 8}, {I_WARP_DRIVE: 1},
     12.0, (B_X_HEAVY_PLATFORM,), "ex_mb2"),
    # 机器/建材（原版制造台可造，自举）
    ("ex_mach_former", {C.I_IRON_PLATE: 4, C.I_GEAR: 2}, {I_MACH_FORMER: 1}, 3.0, (C.B_ASSEMBLER,), "ex_form"),
    ("ex_mach_chem", {C.I_IRON_PLATE: 4, C.I_CIRCUIT: 2, I_GLASS: 2}, {I_MACH_CHEM: 1}, 3.5, (C.B_ASSEMBLER,), "ex_chem"),
    ("ex_mach_reactor", {C.I_IRON_PLATE: 6, C.I_MAGNET: 4, I_SIC: 4}, {I_MACH_REACTOR: 1}, 5.0, (C.B_ASSEMBLER,), "ex_reactor"),
    ("ex_mach_accel", {C.I_IRON_PLATE: 6, I_SIC: 4, C.I_MAGNET: 4}, {I_MACH_ACCEL: 1}, 5.0, (C.B_ASSEMBLER,), "ex_accel"),
    ("ex_mach_brick", {C.I_STONE_BRICK: 2, I_GLASS: 1}, {I_BRICK_ITEM: 1}, 1.0, (C.B_ASSEMBLER,), "ex_mb"),
    ("ex_mach_largecore", {C.I_IRON_PLATE: 8, I_BRONZE_INGOT: 4, C.I_CIRCUIT: 4},
     {I_LARGE_CORE_ITEM: 1}, 5.0, (C.B_ASSEMBLER,), "ex_mb"),
    ("ex_mach_frame", {C.I_IRON_PLATE: 6, I_MN_PLATE: 4}, {I_FRAME_ITEM: 1}, 2.0, (C.B_ASSEMBLER,), "ex_mb2"),
    ("ex_mach_platform", {I_W_PLATE: 8, I_ANTIMATTER: 1, C.I_CIRCUIT: 6},
     {I_PLATFORM_CORE_ITEM: 1}, 8.0, (C.B_ASSEMBLER,), "ex_mb2"),
)

# ---- 矿脉生成：数量与单条规模 ----
VEIN_SPECS = (
    (ORE_TIN, I_ORE_TIN, 22, 20, 55),
    (ORE_COAL, I_ORE_COAL, 18, 18, 50),
    (ORE_QUARTZ, I_ORE_QUARTZ, 14, 16, 45),
    (ORE_MANGANESE, I_ORE_MANGANESE, 10, 14, 40),
    (ORE_TUNGSTEN, I_ORE_TUNGSTEN, 6, 10, 30),
)
ORE_COLOR_RGB = {           # 渲染器按 RGB 三元组取色（和原版 ORE_COLORS 一致）
    ORE_TIN: (214, 217, 228),
    ORE_COAL: (74, 72, 80),
    ORE_QUARTZ: (228, 222, 192),
    ORE_MANGANESE: (154, 144, 178),
    ORE_TUNGSTEN: (146, 146, 156),
}

# 聚变供电：单台满载输出（度/秒）
REACTOR_POWER = 60.0

# =====================================================================
# 1) 运行期状态（全部可卸载还原）
# =====================================================================

_MISSING = object()
_restores = []            # 卸载还原闭包（后注册先还原）
_MB_ACTIVE = {}           # id(machine) -> 多方块是否成型
_UPGRADED = False         # 与重工的“联动升级”是否已跑（on_load 里跑一次）
_UPGRADE_RESTORES = []    # (dict, key, 原值) 升级改动还原
_SIM = None               # ctx.sim（加载时的世界）
_GAME = None              # ctx._game（新开局/换档时动态取 sim）
_prev_sync_gt2 = None     # 安装 sync replace 时捕获的上层链
_CFG = {}                 # M6.29：运行时合并配置（作者 config.json ⊕ 用户覆盖）

_FALLBACK_PACKS = {       # 极少数“重工缺场”情况下的科研包（正常被联动覆盖）
    "ex_alloy": "science_red", "ex_mb": "science_red",
    "ex_reactor": "science_red", "ex_accel": "science_red",
    "ex_mb2": "science_red",
}

# 各矿脉条数（M6.29：可被 config.json 的 vein_counts 覆盖）
VEIN_COUNTS = tuple(s[2] for s in VEIN_SPECS)


def _patch_dict(d, k, v):
    """登记还原后写字典。"""
    orig = d.get(k, _MISSING)
    _restores.append(
        lambda: (d.pop(k, None) if orig is _MISSING else d.__setitem__(k, orig)))
    d[k] = v


def _patch_seq_get(obj, attr, value):
    orig = getattr(obj, attr)
    _restores.append(lambda: setattr(obj, attr, orig))
    setattr(obj, attr, value)


def _restore_categories(idx):
    _restores.append(lambda: TUI.CATEGORIES.pop(idx))


# =====================================================================
# 2) 内容注册
# =====================================================================

def _apply_config():
    """M6.29：把 ctx.cfg 里的可调速项落到模块常量（vein_counts / reactor_power）。"""
    global REACTOR_POWER, VEIN_COUNTS
    vc = _CFG.get("vein_counts")
    if isinstance(vc, (list, tuple)) and len(vc) == len(VEIN_SPECS) \
            and all(isinstance(n, (int, float)) and n >= 0 for n in vc):
        VEIN_COUNTS = tuple(int(n) for n in vc)
    rp = _CFG.get("reactor_power")
    if isinstance(rp, (int, float)) and rp > 0:
        REACTOR_POWER = float(rp)

def _register_items(ctx):
    for iid, (name, color) in ITEMS.items():
        ctx.add_item(iid, name, color)


def _register_ores(ctx):
    base = dict(C.ORE_TO_ITEM)
    base.update({ORE_TIN: I_ORE_TIN, ORE_COAL: I_ORE_COAL,
                 ORE_QUARTZ: I_ORE_QUARTZ, ORE_MANGANESE: I_ORE_MANGANESE,
                 ORE_TUNGSTEN: I_ORE_TUNGSTEN})
    _patch_seq_get(C, "ORE_TO_ITEM", base)
    cols = dict(C.ORE_COLORS)
    cols.update(ORE_COLOR_RGB)
    _patch_seq_get(C, "ORE_COLORS", cols)


def _register_recipes(ctx):
    for rid, ins, outs, dur, machines, tech in RECIPES:
        ctx.add_recipe(rid, ins, outs, dur, machines)
        _patch_dict(C.RECIPE_TECH, rid, tech)


def _register_machines(ctx):
    for btype, item, name, color, usage, tech in MACHINES:
        ctx.add_item(item, name, "#%02X%02X%02X" % color)
        # M8 建筑注册表：add_building 负责 BUILDING_REGISTRY + BUILD_ITEM 联动，
        # 在 add_recipe 之前调用，否则配方里的 machines 建筑 id 会校验失败。
        ctx.add_building(btype, name, item=item)
        _patch_dict(C.BUILDING_COLORS, btype, color)
        _patch_dict(C.POWER_USAGE, btype, usage)
        _patch_dict(C.TECH_UNLOCK_BUILDING, btype, tech)


def _register_techs(ctx):
    costs = dict(zip(TECHS, TECH_COSTS))
    for tid, (name, _pack, prereqs, desc) in TECHS.items():
        # C.TECH_TREE: tid -> (名称, 消耗, 前置, 描述)
        _patch_dict(C.TECH_TREE, tid, (name, costs[tid], tuple(prereqs), desc))
        rid = _FALLBACK_PACKS.get(tid) or "science_blue"
        _patch_dict(C.TECH_PACK_RECIPE, tid, rid)


def _register_ui(ctx):
    # 底栏两个新分类（触发 ui._layout 重排）
    g = ctx._game
    idx0 = len(TUI.CATEGORIES)
    _restore_categories(idx0)
    TUI.CATEGORIES.append(("星际工业", MACHINE_TYPES))
    idx1 = len(TUI.CATEGORIES)
    _restore_categories(idx1)
    TUI.CATEGORIES.append(("多方块", RING_TYPES))
    ui = getattr(g, "ui", None)
    if ui is not None and hasattr(ui, "_layout"):
        ui._layout()


# =====================================================================
# 3) 矿脉生成
# =====================================================================

def _plant_veins(grid):
    """在已有网格上补种新矿脉（只落空位，不覆盖原版矿）。"""
    for i, (ore_t, _item, _veins, lo, hi) in enumerate(VEIN_SPECS):
        for _ in range(VEIN_COUNTS[i]):
            x = int(grid.rng.integers(0, grid.w))
            y = int(grid.rng.integers(0, grid.h))
            size = int(grid.rng.integers(lo, hi))
            for _ in range(size):
                if grid.ore[y, x] == 0:
                    grid.ore[y, x] = int(grid.rng.integers(200, 1000))
                    grid.ore_type[y, x] = ore_t
                x = (x + int(grid.rng.integers(-1, 2))) % grid.w
                y = (y + int(grid.rng.integers(-1, 2))) % grid.h


def after_scatter_ore(self, result, *a, **k):
    """WorldGrid._scatter_ore after：新游戏/断档重建的世界也补种新矿。"""
    try:
        _plant_veins(self)
    except Exception:
        pass
    return result


# =====================================================================
# 4) 多方块判定
# =====================================================================

def _mb_complete(grid, cx, cy) -> bool:
    ring = MULTI_CORES.get(grid.get(cx, cy))
    if ring is None:
        return False
    for dx, dy in RING8:
        if grid.get(cx + dx, cy + dy) != ring:
            return False
    return True


# =====================================================================
# 5) 机器网络 sync：组合式 replace（不调原版破坏性 sync，避免机器对象
#    被清空重建而导致面板引用失效）。
#    规则：最内层（捕获到的是原版 sync 的那层）先跑“安全原版补录”，
#    其它层调用捕获到的上一层链；每层只补/清自己管辖的类型。
# =====================================================================

def _safe_vanilla_pass(net):
    """原版 sync 的“非破坏性”版本：只补录/清理 熔炉+制造台。"""
    g = net.grid
    wanted = set()
    for btype in (C.B_FURNACE, C.B_ASSEMBLER):
        ys, xs = np.nonzero(g.building == btype)
        for y, x in zip(ys.tolist(), xs.tolist()):
            key = (x, y)
            wanted.add(key)
            if key not in net.machines:
                net.machines[key] = Machine(x, y, int(g.building[y, x]))
    dead = [k for k, m in net.machines.items()
            if m.btype in (C.B_FURNACE, C.B_ASSEMBLER) and k not in wanted]
    for k in dead:
        del net.machines[k]


def replace_gt2_sync(self, *a, **k):
    g = self.grid
    snap = {}
    for key, m in list(self.machines.items()):
        if m.btype in MACHINE_TYPES:
            snap[key] = (m.recipe_id, dict(m.inputs), dict(m.outputs),
                         m.progress)
    prev = _prev_sync_gt2
    if prev is None or prev is getattr(MachineNetwork, "_gt_vanilla_sync", None):
        _safe_vanilla_pass(self)
    else:
        prev(self, *a, **k)
    wanted = set()
    for btype in MACHINE_TYPES:
        ys, xs = np.nonzero(g.building == btype)
        for y, x in zip(ys.tolist(), xs.tolist()):
            key = (x, y)
            wanted.add(key)
            m = self.machines.get(key)
            if m is None:
                m = Machine(x, y, int(g.building[y, x]))
                s = snap.get(key)
                if s is not None:
                    m.recipe_id, m.inputs, m.outputs, m.progress = s
                    m._set_need()
                self.machines[key] = m
    dead = [k for k, m in self.machines.items()
            if m.btype in MACHINE_TYPES and k not in wanted]
    for k in dead:
        _MB_ACTIVE.pop(id(self.machines[k]), None)
        del self.machines[k]
    # 多方块成型状态刷新
    for key, m in self.machines.items():
        if m.btype in MULTI_CORE_TYPES:
            _MB_ACTIVE[id(m)] = _mb_complete(g, m.x, m.y)


def before_machine_update(self, dt, speed_factor, **kw):
    """Machine.update before：多方块核心未成型时停工。"""
    if self.btype in MULTI_CORE_TYPES and not _MB_ACTIVE.get(id(self), False):
        return ((0.0, speed_factor), {})
    return None


# =====================================================================
# 6) 放置 / 拆除
# =====================================================================

def after_place(self, result, btype, gx, gy, direction=0, **kw):
    if result == "ok" and btype in MACHINE_TYPES:
        self.machines.sync()
    return result


def before_remove(self, gx, gy, **kw):
    self._gt2_removing = (gx, gy, self.grid.get(gx, gy))
    return None


def after_remove(self, result, gx, gy, **kw):
    rec = getattr(self, "_gt2_removing", None)
    try:
        if rec and rec[0] == gx and rec[1] == gy and rec[2] in MACHINE_TYPES:
            if self.grid.get(gx, gy) == C.B_EMPTY:
                m = self.machines.get_machine(gx, gy)
                if m is not None:
                    for store in (m.inputs, m.outputs):
                        for item, n in list(store.items()):
                            if n > 0:
                                self.inventory[item] = \
                                    self.inventory.get(item, 0) + n
                        store.clear()
                    self.machines.machines.pop((gx % self.grid.w,
                                                gy % self.grid.h), None)
                    _MB_ACTIVE.pop(id(m), None)
    finally:
        self._gt2_removing = None
    return result


# =====================================================================
# 7) 聚变供电 / 联动升级（on_load 完成）
# =====================================================================

def _reactor_ready(m) -> bool:
    if m.inputs.get(I_DEUTERIUM, 0) < 1:
        return False
    r = C.RECIPES.get("ex_fuel")
    if r is None:
        return False
    _, outs, _, _ = r
    for it, n in outs.items():
        if m.output_space(it) < n:
            return False
    return True


def _maybe_upgrade():
    """on_load 里运行：重工 mod 已在场（依赖声明保证），把高段科技与配方
    升级为「吃结构/量子矩阵、用重工精料」的形态。全程登记还原，可安全卸载。
    仍带“重工缺场”保护（例如手动热加载的奇怪顺序），缺了只跳过升级。"""
    global _UPGRADED
    if _UPGRADED:
        return
    _UPGRADED = True
    structure = "science_structure" in C.RECIPES
    quantum = "science_quantum" in C.RECIPES
    by_id = C.ITEM_NAMES
    has = {1007: 1007 in by_id, 1008: 1008 in by_id, 1015: 1015 in by_id,
           1020: 1020 in by_id, 1023: 1023 in by_id}

    def repoint(tid, rid):
        old = C.TECH_PACK_RECIPE.get(tid, _MISSING)
        _UPGRADE_RESTORES.append((C.TECH_PACK_RECIPE, tid, old))
        C.TECH_PACK_RECIPE[tid] = rid

    def upgrade_recipe(rid, ins, outs, dur):
        r = C.RECIPES.get(rid)
        if r is None:
            return
        _UPGRADE_RESTORES.append((C.RECIPES, rid, r))
        C.RECIPES[rid] = (ins, outs, dur, r[3])

    if structure:
        for t in ("ex_alloy", "ex_mb", "ex_reactor"):
            repoint(t, "science_structure")
    if quantum:
        for t in ("ex_accel", "ex_mb2"):
            repoint(t, "science_quantum")

    if has[1007]:
        upgrade_recipe("ex_bronze", {I_TIN_INGOT: 1, 1007: 1},
                       {I_BRONZE_INGOT: 2}, 1.2)
    if has[1008]:
        upgrade_recipe("ex_mn_steel", {I_MANGANESE_INGOT: 1, 1008: 1},
                       {I_MNSTEEL_INGOT: 2}, 2.5)
        upgrade_recipe("ex_w_steel", {I_TUNGSTEN_INGOT: 1, 1008: 2},
                       {I_WSTEEL_INGOT: 2}, 3.0)
    if has[1015] and has[1023]:
        upgrade_recipe("ex_dusterium",
                       {I_W_PLATE: 2, 1015: 2, 1023: 1}, {I_DEUTERIUM: 1}, 6.0)
    if has[1015]:
        upgrade_recipe("ex_antimatter", {I_PLASMA: 4, 1015: 2},
                       {I_ANTIMATTER: 1}, 7.0)
    if has[1023]:
        upgrade_recipe("ex_warp", {I_ANTIMATTER_ENGINE: 1, 1023: 2, I_SIC: 4},
                       {I_WARP_DRIVE: 1}, 10.0)
    if has[1020]:
        upgrade_recipe("ex_mach_platform",
                       {I_W_PLATE: 6, I_ANTIMATTER: 1, 1020: 2},
                       {I_PLATFORM_CORE_ITEM: 1}, 6.0)
        upgrade_recipe("ex_mach_reactor",
                       {C.I_IRON_PLATE: 4, 1020: 4, I_SIC: 4},
                       {I_MACH_REACTOR: 1}, 4.0)


def _on_step(dt):
    sim = _GAME.sim if _GAME is not None else _SIM   # 新开局会换 sim，动态取
    if sim is None:
        return
    # 聚变供电：统计当前世界“能烧料”的反应堆台数，向电网注电
    try:
        active = 0
        for m in sim.machines.machines.values():
            if m.btype == B_X_REACTOR and m.recipe_id == "ex_fuel" \
                    and _reactor_ready(m):
                active += 1
        if active:
            pg = sim.power
            pg.last_supply += active * REACTOR_POWER
            if pg.last_demand > 0:
                pg.last_ratio = min(1.0, pg.last_supply / pg.last_demand)
            else:
                pg.last_ratio = 1.0
    except Exception:
        pass


# =====================================================================
# 8) 渲染
# =====================================================================

def _paint_gt2(surf, rect, tile_px, btype):
    """在格子 rect 里画新建筑图案（在 ChunkRenderer._build 结果上覆盖）。"""
    base = C.BUILDING_COLORS.get(btype, (180, 180, 190))
    ChunkRenderer._base(surf, rect, base, tile_px)
    darkc = tuple(max(0, int(v * 0.55)) for v in base)
    lightc = tuple(min(255, int(v + (255 - v) * 0.45)) for v in base)
    cx, cy = rect.center
    if btype in (B_X_BRICK, B_X_LARGE_FURNACE):
        # 耐热砖块：2×2 砖缝
        if tile_px >= 8:
            mid_h = rect.top + rect.height // 2
            mid_w = rect.left + rect.width // 2
            pygame.draw.line(surf, darkc, (rect.left, mid_h), (rect.right, mid_h),
                             max(tile_px // 10, 1))
            pygame.draw.line(surf, darkc, (mid_w, rect.top), (mid_w, mid_h),
                             max(tile_px // 10, 1))
            pygame.draw.line(surf, darkc, (rect.left + rect.width // 4, mid_h),
                             (rect.left + rect.width // 4, rect.bottom),
                             max(tile_px // 10, 1))
            pygame.draw.line(surf, darkc, (rect.left + rect.width * 3 // 4, mid_h),
                             (rect.left + rect.width * 3 // 4, rect.bottom),
                             max(tile_px // 10, 1))
        if btype == B_X_LARGE_FURNACE and tile_px >= 10:
            t = max(tile_px // 3, 2)
            inner = rect.inflate(-max(tile_px // 8, 1) * 2,
                                 -max(tile_px // 8, 1) * 2)
            pygame.draw.rect(surf, (60, 40, 36), inner)
            pygame.draw.polygon(surf, lightc,
                                [(cx, cy + t), (cx - t, cy - t // 2),
                                 (cx + t, cy - t // 2)])
    elif btype == B_X_REACTOR:
        # 聚变反应堆：磁约束环 + 芯火
        r = max(tile_px // 3, 3)
        pygame.draw.circle(surf, darkc, (cx, cy), r, 0)
        pygame.draw.circle(surf, (120, 240, 230), (cx, cy), max(r * 2 // 3, 1), 0)
        pygame.draw.circle(surf, (250, 250, 200), (cx, cy), max(tile_px // 6, 1), 0)
        if tile_px >= 10:
            for a in (0.0, 1.57, 3.14, 4.71):
                ex = cx + int(math.cos(a) * r)
                ey = cy + int(math.sin(a) * r)
                pygame.draw.circle(surf, lightc, (ex, ey), max(tile_px // 8, 1))
    elif btype == B_X_FORMER:
        # 金属成型机：压头 + 模具
        t = max(tile_px // 4, 2)
        pygame.draw.rect(surf, darkc,
                         (rect.left + t, rect.top + t // 2,
                          rect.width - 2 * t, rect.height // 3))
        pygame.draw.rect(surf, lightc,
                         (rect.left + t, rect.top + rect.height // 2,
                          rect.width - 2 * t, rect.height // 4))
        pygame.draw.circle(surf, lightc, (cx, rect.top + t), max(tile_px // 6, 1))
    elif btype == B_X_CHEM:
        # 化工厂：反应釜 + 气泡
        t = max(tile_px // 4, 2)
        pygame.draw.rect(surf, darkc,
                         (cx - t, rect.top + t, 2 * t, rect.height - 2 * t))
        pygame.draw.circle(surf, (210, 240, 190), (cx, rect.top + t), t, 0)
        if tile_px >= 10:
            pygame.draw.circle(surf, (230, 250, 230), (cx, cy), max(tile_px // 7, 1))
            pygame.draw.circle(surf, (200, 240, 210),
                               (cx - t, cy + t), max(tile_px // 9, 1))
    elif btype == B_X_ACCEL:
        # 粒子加速器：光环 + 粒子
        t = max(tile_px // 3, 3)
        pygame.draw.circle(surf, darkc, (cx, cy), t, 0)
        pygame.draw.circle(surf, lightc, (cx, cy), t, max(tile_px // 7, 1))
        if tile_px >= 10:
            for i, a in enumerate((0.4, 2.5, 4.7)):
                ex = cx + int(math.cos(a) * t)
                ey = cy + int(math.sin(a) * t)
                pygame.draw.circle(surf, (240, 180, 255),
                                   (ex, ey), max(tile_px // 9, 1))
    elif btype in (B_X_FRAME, B_X_HEAVY_PLATFORM):
        # 合金框架 / 重型装配平台：桁架 + 起重臂
        if tile_px >= 8:
            pygame.draw.rect(surf, darkc, rect, max(tile_px // 8, 1))
            pygame.draw.line(surf, darkc, (rect.left, rect.top),
                             (rect.right, rect.bottom), max(tile_px // 10, 1))
            pygame.draw.line(surf, darkc, (rect.right, rect.top),
                             (rect.left, rect.bottom), max(tile_px // 10, 1))
        if btype == B_X_HEAVY_PLATFORM:
            pygame.draw.circle(surf, (240, 240, 130), (cx, cy),
                               max(tile_px // 5, 2))
            pygame.draw.circle(surf, darkc, (cx, cy), max(tile_px // 8, 1))


@EnvType("client")   # M15d：chunk 渲染补丁，服务端（headless）跳过
def after_build(self, result, cix, ciy, tile_px, **kw):
    """ChunkRenderer._build after：把本 mod 的建筑格子画上图案。"""
    if result is None:
        return result
    g = self.grid
    cpc = self.cpc
    bx0 = cix * cpc
    by0 = ciy * cpc
    for ly in range(cpc):
        wy = (by0 + ly) % g.h
        row = g.building[wy]
        for lx in range(cpc):
            wx = (bx0 + lx) % g.w
            b = int(row[wx])
            if b in _ALL_TYPES:
                rect = pygame.Rect(lx * tile_px, ly * tile_px, tile_px, tile_px)
                _paint_gt2(result, rect, tile_px, b)
    return result


_ALL_TYPES = MACHINE_TYPES + RING_TYPES


# =====================================================================
# 9) mixin 安装
# =====================================================================

def _install_mixins(ctx):
    sim = ctx.sim

    # 机器网络 sync：组合式 replace（见模块注释；不 replace 原版，避免清场）
    global _prev_sync_gt2
    if not hasattr(MachineNetwork, "_gt_vanilla_sync"):
        MachineNetwork._gt_vanilla_sync = MachineNetwork.sync
    _prev_sync_gt2 = MachineNetwork.sync
    ctx.mixin("stellarloom.production.machines.MachineNetwork", "sync",
              replace_gt2_sync, wrap="replace")

    # 多方块停工判定（每台机器每次更新一个 O(1) 检查）
    ctx.mixin("stellarloom.production.machines.Machine", "update",
              before_machine_update, wrap="before")

    # 放置后立即 sync（面板拿得到机器实例）
    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              after_place, wrap="after")

    # 拆除退款（机器内原料/产物退回背包）
    ctx.mixin("stellarloom.sim.sim.Simulation", "remove_building",
              before_remove, wrap="before")
    ctx.mixin("stellarloom.sim.sim.Simulation", "remove_building",
              after_remove, wrap="after")

    # 点放机器 → 开面板
    @EnvType("client")   # M15d：UI 补丁（开面板是前端行为），服务端跳过
    def after_place_or_harvest(self, result, gx, gy, confirm_only, **kw):
        b = self.grid.get(gx, gy)
        if b in MACHINE_TYPES:
            self.sim.machines.sync()
            self._try_open_panel(gx, gy)
        return result

    ctx.mixin("stellarloom.core.game.Game", "_place_or_harvest",
              after_place_or_harvest, wrap="after")

    # 机器面板标题：新机器显示自己的名字（复用重工已验证的覆盖法）
    @EnvType("client")   # M15d：UI 补丁，服务端跳过
    def after_machine_draw(self, result, screen, **kw):
        m = self.machine
        if m is not None and m.btype in MACHINE_TYPES + RING_TYPES:
            try:
                r = self.rect
                pygame.draw.rect(screen, (20, 24, 34),
                                 (r.left + 10, r.top + 8, r.width - 20, 26))
                name = C.BUILDING_NAMES.get(m.btype, f"机器{m.btype}")
                t = self.fonts.get(18).render(f"{name} ({m.x},{m.y})",
                                              True, (200, 220, 240))
                screen.blit(t, (r.left + 14, r.top + 10))
            except Exception:
                pass
        return result

    ctx.mixin("stellarloom.ui.machine_panel.MachinePanel", "draw",
              after_machine_draw, wrap="after")

    # 手搓目录刷新（面板在 mod 加载前已构造）
    @EnvType("client")   # M15d：UI 补丁，服务端跳过
    def after_craft_show(self, result, screen_size, inventory, **kw):
        try:
            newcat = {}
            for rid, (_ins, outs, _dur, allows) in C.RECIPES.items():
                if not allows:
                    continue
                for item in outs:
                    newcat.setdefault(item, rid)
            self._catalog.clear()
            self._catalog.update(newcat)
            if self.sel_item is not None and self.sel_item not in self._catalog:
                self.sel_item = None
        except Exception:
            pass
        return result

    ctx.mixin("stellarloom.ui.craft_panel.CraftPanel", "show",
              after_craft_show, wrap="after")

    # 新矿脉：新世界/断档重建时补种
    ctx.mixin("stellarloom.world.grid.WorldGrid", "_scatter_ore",
              after_scatter_ore, wrap="after")

    # chunk 渲染覆盖
    ctx.mixin("stellarloom.render.layers.ChunkRenderer", "_build",
              after_build, wrap="after")

    sim.machines.sync()


# =====================================================================
# 10) 生命周期
# =====================================================================

def on_load(ctx):
    global _restores, _MB_ACTIVE, _UPGRADED, _UPGRADE_RESTORES, _SIM, _GAME, _CFG
    _restores = []
    _MB_ACTIVE = {}
    _UPGRADED = False
    _UPGRADE_RESTORES = []
    _SIM = ctx.sim
    _GAME = getattr(ctx, "_game", None)
    _CFG = ctx.cfg                       # M6.29：作者默认 ⊕ 用户覆盖

    _register_items(ctx)
    _register_ores(ctx)
    _register_machines(ctx)   # 机器/建材物品先注册，配方才引用得到
    _register_recipes(ctx)
    _register_techs(ctx)
    _maybe_upgrade()          # 联动升级：依赖声明保证重工已加载（on_load 即生效）
    _apply_config()           # 配置可调速项落地（矿脉条数 / 聚变功率）
    _register_ui(ctx)
    _install_mixins(ctx)
    ctx.on_step(_on_step)     # 每帧：聚变供电注电

    # 已经生成的旧世界补种新矿脉
    for ws in getattr(ctx.sim, "worlds", ()):  # noqa: SIM102
        try:
            _plant_veins(ws.grid)
        except Exception:
            pass

    
    if _CFG.get("toasts", True):
        ctx.toast("格雷科技·星海扩展 已加载：新矿脉 / 聚变供电 / 多方块结构", 4.0)
    ctx.log(f"加载 gregtech_extra v1.1 "
            f"reactor_power={REACTOR_POWER} veins={VEIN_COUNTS}")


def on_unload(ctx):
    # 还原升级改动（配方字典整体原值、科研包映射原值）
    for d, k, orig in reversed(_UPGRADE_RESTORES):
        if orig is _MISSING:
            d.pop(k, None)
        else:
            d[k] = orig
    _UPGRADE_RESTORES.clear()
    _MB_ACTIVE.clear()
    for fn in reversed(_restores):
        try:
            fn()
        except Exception:
            pass
    _restores.clear()
    ui = getattr(ctx._game, "ui", None)
    if ui is not None and hasattr(ui, "_layout"):
        ui._layout()
    if ctx.cfg.get("toasts", True):
        ctx.toast("格雷科技·星海扩展 已卸载", 2.0)
    ctx.log("卸载 gregtech_extra —— 全部内容已还原")
