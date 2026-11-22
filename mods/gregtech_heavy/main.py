# -*- coding: utf-8 -*-
"""格雷科技：星织重工（GregTech: StellarLoom Heavy Industry）—— 大型内容 mod。

仿照 Minecraft「格雷科技」的精神做一个重度科技树 mod：

  * 矿物处理链：原矿 → 粉碎 → 洗净 → 冶炼（锭）→ 轧制（板），
    离心/冶炼过程中产出**副产物**（硫粉 / 稀土粉 / 高炉渣）。
  * 四台新机器（建筑类型 20–23）：粉碎机 / 高炉 / 离心机 / 组装线，
    各自拥有专属配方、独立渲染图案、科技解锁、电网耗电与底栏入口。
  * 三级科研包体系：电磁矩阵（蓝）→ 结构矩阵（绿）→ 量子矩阵（青），
    每级科技吃对应科研包，把「格雷式」的昂贵多步配方锁在科技后面。
  * 元件树：马达 → 活塞 / 线圈 → 高级电路板 → 处理器 → 处理器单元
    → 超导线圈 / 激光组件 → 聚变线圈 → 星织引擎（终极里程碑）。
  * 全局增益：研究「传动学 IV」带速 +25%；「生产加速 I」全部机器提速 +25%。

实现方式（全部走 ModContext API + 运行时 mixin，不修改游戏源码）：
  * 内容（物品/配方/科技/科研包）→ ctx.add_item / ctx.add_recipe + 内存表扩展；
  * 新机器接入（同步/放置/拆除退款/面板/底栏/渲染）→ 若干外科手术式 mixin；
  * 卸载时全部还原（on_unload 手工还原内存表 + 加载器自动还原 mixin 与
    add_item/add_recipe 注册）。

M7.dev / M6.29 对齐（v1.2）：
  * 物品用**固定数字注册**（ctx.add_item(int, ...)）——旧式兼容路径被官方
    M7 注册表明确保留（token = gregtech_heavy:item<id>，旧存档数字可反查），
    新存档/配方 JSON 以名字持久化、运行时经注册表换算回同一 id，存档零漂移。
  * 作者默认配置 config.json（M6.29）：production_accel（生产加速 I 的倍率）
    与 toasts（加载提示）可被玩家 mods/config/gregtech_heavy.json 覆盖。
"""

from __future__ import annotations

import math

import numpy as np          # noqa: F401  与游戏同依赖（MachineNetwork.sync 重写用）
import pygame               # noqa: F401  渲染绘制（import 模块本身不需要初始化 display）

from stellarloom import config as C
from stellarloom.production.machines import Machine
from stellarloom.render.layers import ChunkRenderer
from stellarloom.ui import touch_ui as TUI

# =====================================================================
# 0) 数据表：物品 / 机器 / 配方 / 科技 / 科研包
# =====================================================================

# --- 新机器建筑类型（100 以下都没占用：20–23 安全）---
B_GT_CRUSHER = 20          # 粉碎机
B_GT_FURNACE = 21          # 高炉
B_GT_CENTRI = 22           # 离心机
B_GT_ASSEMBLY = 23         # 组装线
GT_MACHINE_TYPES = (B_GT_CRUSHER, B_GT_FURNACE, B_GT_CENTRI, B_GT_ASSEMBLY)

# --- 新物品 ID（1000+ 自留段，与内置 1–14 / 101–112 不冲突）---
I_CR_IRON = 1001           # 粉碎铁矿石
I_CR_COPPER = 1002         # 粉碎铜矿石
I_CR_STONE = 1003          # 碎石
I_WS_IRON = 1004           # 洗净铁矿石
I_WS_COPPER = 1005         # 洗净铜矿石
I_INGOT_IRON = 1006        # 铁锭
I_INGOT_COPPER = 1007      # 铜锭
I_INGOT_STEEL = 1008       # 钢锭
I_INGOT_SILICON = 1009     # 硅锭
I_WAFER = 1010             # 硅晶圆
I_SULFUR = 1011            # 硫粉（粉碎铁矿离心副产物）
I_RAREEARTH = 1012         # 稀土粉（粉碎铜矿离心副产物）
I_COKE = 1013              # 焦炭
I_SLAG = 1014              # 高炉渣（炼钢副产物）
I_GRAPHENE = 1015          # 石墨烯
I_PLATE_STEEL = 1016       # 钢板
I_COIL = 1017              # 磁线圈
I_MOTOR = 1018             # 电动马达
I_PISTON = 1019            # 电动活塞
I_ADV_CIRCUIT = 1020       # 高级电路板
I_PROCESSOR = 1021         # 处理器
I_PROCESSOR_UNIT = 1022    # 处理器单元
I_SUPERCONDUCTOR = 1023    # 超导线圈
I_LASER = 1024             # 激光组件
I_FUSION_COIL = 1025       # 聚变线圈
I_STELLAR_ENGINE = 1026    # 星织引擎（终极里程碑）

I_GT_CRUSHER = 1030        # 粉碎机（建筑物品）
I_GT_FURNACE = 1031        # 高炉（建筑物品）
I_GT_CENTRI = 1032         # 离心机（建筑物品）
I_GT_ASSEMBLY = 1033       # 组装线（建筑物品）

I_PACK_STRUCTURE = 1040    # 结构矩阵（三级科研包）
I_PACK_QUANTUM = 1041      # 量子矩阵（四级科研包）

# 配方 id（全部 gt_ / science_ 前缀，不与内置冲突）
RID = {
    "cr_iron": "gt_cr_iron", "cr_copper": "gt_cr_copper", "cr_stone": "gt_cr_stone",
    "coke": "gt_coke",
    "ingot_iron": "gt_iron_ingot", "ingot_copper": "gt_copper_ingot",
    "steel": "gt_steel", "silicon": "gt_silicon_ingot",
    "wash_iron": "gt_wash_iron", "wash_copper": "gt_wash_copper",
    "wafer": "gt_wafer", "graphene": "gt_graphene",
    "plate_iron": "gt_iron_plate", "plate_copper": "gt_copper_plate",
    "plate_steel": "gt_steel_plate",
    "motor": "gt_motor", "piston": "gt_piston", "coil": "gt_coil",
    "adv_circuit": "gt_adv_circuit", "processor": "gt_processor",
    "processor_unit": "gt_processor_unit", "superconductor": "gt_superconductor",
    "laser": "gt_laser",
    "fusion_coil": "gt_fusion_coil", "stellar_engine": "gt_stellar_engine",
    "mach_crusher": "gt_mach_crusher", "mach_furnace": "gt_mach_furnace",
    "mach_centri": "gt_mach_centri", "mach_assembly": "gt_mach_assembly",
    "pack_structure": "science_structure", "pack_quantum": "science_quantum",
}

# (item_id, 名字, 颜色)
ITEMS = [
    (I_CR_IRON, "粉碎铁矿石", "#A86E38"),
    (I_CR_COPPER, "粉碎铜矿石", "#A05F4B"),
    (I_CR_STONE, "碎石", "#82868E"),
    (I_WS_IRON, "洗净铁矿石", "#C89553"),
    (I_WS_COPPER, "洗净铜矿石", "#C9795E"),
    (I_INGOT_IRON, "铁锭", "#C9C9D4"),
    (I_INGOT_COPPER, "铜锭", "#E0A069"),
    (I_INGOT_STEEL, "钢锭", "#96A2BE"),
    (I_INGOT_SILICON, "硅锭", "#78BEC8"),
    (I_WAFER, "硅晶圆", "#6EC8D7"),
    (I_SULFUR, "硫粉", "#D7C35A"),
    (I_RAREEARTH, "稀土粉", "#96DC9F"),
    (I_COKE, "焦炭", "#64605A"),
    (I_SLAG, "高炉渣", "#787468"),
    (I_GRAPHENE, "石墨烯", "#46D2BE"),
    (I_PLATE_STEEL, "钢板", "#AAB4D2"),
    (I_COIL, "磁线圈", "#EB9650"),
    (I_MOTOR, "电动马达", "#C8AA4E"),
    (I_PISTON, "电动活塞", "#BEBE96"),
    (I_ADV_CIRCUIT, "高级电路板", "#5ADC96"),
    (I_PROCESSOR, "处理器", "#50A0E6"),
    (I_PROCESSOR_UNIT, "处理器单元", "#8C6EE6"),
    (I_SUPERCONDUCTOR, "超导线圈", "#50DCEB"),
    (I_LASER, "激光组件", "#F45A5A"),
    (I_FUSION_COIL, "聚变线圈", "#C05AE6"),
    (I_STELLAR_ENGINE, "星织引擎", "#FFD966"),
    (I_GT_CRUSHER, "粉碎机", "#96643C"),
    (I_GT_FURNACE, "高炉", "#7A3C37"),
    (I_GT_CENTRI, "离心机", "#56B48C"),
    (I_GT_ASSEMBLY, "组装线", "#4B60C8"),
    (I_PACK_STRUCTURE, "结构矩阵", "#5CD878"),
    (I_PACK_QUANTUM, "量子矩阵", "#40C8E0"),
]

# 机器定义：(btype, 名字, 建筑物品id, 渲染基色, 每秒耗电, 解锁科技)
MACHINES = [
    (B_GT_CRUSHER, "粉碎机", I_GT_CRUSHER, (150, 100, 60), 1.2, "gt_ore"),
    (B_GT_FURNACE, "高炉", I_GT_FURNACE, (122, 62, 56), 3.0, "gt_blast"),
    (B_GT_CENTRI, "离心机", I_GT_CENTRI, (82, 176, 134), 1.8, "gt_cent"),
    (B_GT_ASSEMBLY, "组装线", I_GT_ASSEMBLY, (72, 94, 196), 2.5, "gt_mach2"),
]

# 配方：(rid, 输入, 输出, 耗时秒, 可造机器, 所需科技[None=不限])
RECIPES = [
    # --- 粉碎机 ---
    (RID["cr_iron"],  {C.I_IRON_ORE: 1},   {I_CR_IRON: 1},   1.0, (B_GT_CRUSHER,), "gt_ore"),
    (RID["cr_copper"], {C.I_COPPER_ORE: 1}, {I_CR_COPPER: 1}, 1.0, (B_GT_CRUSHER,), "gt_ore"),
    (RID["cr_stone"], {C.I_STONE: 2},      {I_CR_STONE: 1},  0.8, (B_GT_CRUSHER,), "gt_ore"),
    # --- 高炉 ---
    (RID["coke"],     {C.I_STONE: 1},      {I_COKE: 1},      1.5, (B_GT_FURNACE,), "gt_blast"),
    (RID["ingot_iron"], {I_WS_IRON: 1},    {I_INGOT_IRON: 1},  2.0, (B_GT_FURNACE,), "gt_blast"),
    (RID["ingot_copper"], {I_WS_COPPER: 1}, {I_INGOT_COPPER: 1}, 2.0, (B_GT_FURNACE,), "gt_blast"),
    (RID["steel"],    {I_INGOT_IRON: 1, I_COKE: 1},
                     {I_INGOT_STEEL: 1, I_SLAG: 1},           3.0, (B_GT_FURNACE,), "gt_blast"),
    (RID["silicon"],  {C.I_GRAIN: 2},      {I_INGOT_SILICON: 1}, 2.5, (B_GT_FURNACE,), "gt_cent"),
    # --- 离心机 ---
    (RID["wash_iron"],  {I_CR_IRON: 1},    {I_WS_IRON: 1, I_SULFUR: 1},   2.0, (B_GT_CENTRI,), "gt_cent"),
    (RID["wash_copper"], {I_CR_COPPER: 1}, {I_WS_COPPER: 1, I_RAREEARTH: 1}, 2.0, (B_GT_CENTRI,), "gt_cent"),
    (RID["wafer"],    {I_INGOT_SILICON: 1}, {I_WAFER: 1},     3.0, (B_GT_CENTRI,), "gt_elec"),
    (RID["graphene"], {C.I_GRAIN: 2, I_SULFUR: 1, I_RAREEARTH: 1},
                     {I_GRAPHENE: 1},                          5.0, (B_GT_CENTRI,), "gt_chem"),
    # --- 熔炉 / 高炉：锭→板（GT 路线，产出与内置铁板/铜板同物）---
    (RID["plate_iron"],   {I_INGOT_IRON: 1},   {C.I_IRON_PLATE: 1},  1.0, (C.B_FURNACE, B_GT_FURNACE), "gt_blast"),
    (RID["plate_copper"], {I_INGOT_COPPER: 1}, {C.I_COPPER_PLATE: 1}, 1.0, (C.B_FURNACE, B_GT_FURNACE), "gt_blast"),
    (RID["plate_steel"],  {I_INGOT_STEEL: 1},  {I_PLATE_STEEL: 1},   1.5, (C.B_FURNACE, B_GT_FURNACE), "gt_blast"),
    # --- 制造台：元件 ---
    (RID["motor"],    {C.I_MAGNET: 2, C.I_COPPER_WIRE: 4, I_INGOT_IRON: 1},
                     {I_MOTOR: 1},                            3.0, (C.B_ASSEMBLER,), "gt_motor"),
    (RID["piston"],   {I_MOTOR: 1, I_INGOT_IRON: 2, C.I_GEAR: 1},
                     {I_PISTON: 1},                           3.0, (C.B_ASSEMBLER,), "gt_motor"),
    (RID["coil"],     {C.I_COPPER_WIRE: 4, I_INGOT_STEEL: 1},
                     {I_COIL: 2},                             2.5, (C.B_ASSEMBLER,), "gt_motor"),
    (RID["adv_circuit"], {C.I_CIRCUIT: 2, C.I_COPPER_WIRE: 4},
                     {I_ADV_CIRCUIT: 1},                      3.0, (C.B_ASSEMBLER,), "gt_elec"),
    (RID["processor"], {I_ADV_CIRCUIT: 1, I_WAFER: 1, C.I_COPPER_WIRE: 2},
                     {I_PROCESSOR: 1},                        4.0, (C.B_ASSEMBLER,), "gt_elec"),
    # --- 组装线：高级元件（重工） ---
    (RID["processor_unit"], {I_PROCESSOR: 2, I_ADV_CIRCUIT: 1, I_MOTOR: 1},
                     {I_PROCESSOR_UNIT: 1},                   5.0, (B_GT_ASSEMBLY,), "gt_mach2"),
    (RID["superconductor"], {I_GRAPHENE: 2, I_COIL: 2, I_PROCESSOR: 1},
                     {I_SUPERCONDUCTOR: 1},                   6.0, (B_GT_ASSEMBLY,), "gt_qian"),
    (RID["laser"],    {I_PROCESSOR_UNIT: 1, I_PLATE_STEEL: 2, I_GRAPHENE: 1},
                     {I_LASER: 1},                            6.0, (B_GT_ASSEMBLY,), "gt_qian"),
    (RID["fusion_coil"], {I_SUPERCONDUCTOR: 2, I_LASER: 2, I_PROCESSOR_UNIT: 1},
                     {I_FUSION_COIL: 1},                      8.0, (B_GT_ASSEMBLY,), "gt_fusion"),
    (RID["stellar_engine"], {I_FUSION_COIL: 1, I_PROCESSOR_UNIT: 2, I_GRAPHENE: 2},
                     {I_STELLAR_ENGINE: 1},                   12.0, (B_GT_ASSEMBLY,), "gt_fusion"),
    # --- 制造台：机器本身 ---
    (RID["mach_crusher"],  {C.I_IRON_PLATE: 4, C.I_GEAR: 2, C.I_CIRCUIT: 2},
                     {I_GT_CRUSHER: 1},                       3.0, (C.B_ASSEMBLER,), "gt_ore"),
    (RID["mach_furnace"],  {C.I_IRON_PLATE: 6, C.I_STONE_BRICK: 2, C.I_CIRCUIT: 4, C.I_MAGNET: 2},
                     {I_GT_FURNACE: 1},                       4.0, (C.B_ASSEMBLER,), "gt_blast"),
    (RID["mach_centri"],   {C.I_IRON_PLATE: 5, C.I_GEAR: 3, C.I_MAGNET: 3},
                     {I_GT_CENTRI: 1},                        4.0, (C.B_ASSEMBLER,), "gt_cent"),
    (RID["mach_assembly"], {I_PLATE_STEEL: 6, C.I_GEAR: 4, I_MOTOR: 2, C.I_CIRCUIT: 4},
                     {I_GT_ASSEMBLY: 1},                      6.0, (C.B_ASSEMBLER,), "gt_mach2"),
    # --- 科研站：三级 / 四级科研包（矩阵垄断：只能科研站造）---
    (RID["pack_structure"], {C.I_CIRCUIT: 2, C.I_MAGNET: 2, C.I_GRAIN: 2},
                     {I_PACK_STRUCTURE: 1},                   6.0, (C.B_LAB,), None),
    (RID["pack_quantum"], {I_PROCESSOR: 1, I_WAFER: 2, C.I_COPPER_WIRE: 4},
                     {I_PACK_QUANTUM: 1},                     10.0, (C.B_LAB,), "gt_qian"),
]

# 科技树补充：(tech_id, 名字, 需要的科研包数, 前置, 描述, 吃的科研包配方)
TECHS = [
    ("gt_ore",    ("矿石学 I",    12, ("circuit1",),   "解锁粉碎机：铁/铜矿石可破碎加工")),
    ("gt_blast",  ("高炉冶金 I",  20, ("gt_ore",),     "解锁高炉：焦炭、铁锭/铜锭/钢锭与炉渣副产物")),
    ("gt_cent",   ("矿物离心 I",  22, ("gt_ore",),     "解锁离心机：洗净矿石并分离硫粉/稀土粉")),
    ("gt_motor",  ("电机工学 I",  25, ("gt_blast",),   "解锁电动马达/电动活塞/磁线圈")),
    ("gt_elec",   ("微电子 I",    30, ("gt_motor",),   "解锁高级电路板/处理器/硅晶圆")),
    ("gt_chem",   ("材料化工 I",  35, ("gt_cent",),    "解锁石墨烯精炼（硫粉+稀土粉路线）")),
    ("gt_mach2",  ("重工产线 I",  45, ("gt_motor", "gt_elec"), "解锁组装线：处理器单元等高级元件")),
    ("gt_qian",   ("量子电子 I",  60, ("gt_elec", "gt_mach2"), "解锁超导线圈/激光组件/量子矩阵")),
    ("gt_fusion", ("聚变技术 I",  80, ("gt_chem", "gt_qian"),  "解锁聚变线圈与星织引擎（终极工艺）")),
    ("gt_belt4",  ("传动学 IV",   55, ("speed3", "gt_mach2"),  "传送带速度再 +25%")),
    ("gt_speed4", ("生产加速 I",  50, ("gt_blast",),   "全部机器生产速度 +25%")),
]
TECH_PACK = {
    "gt_ore": "science_blue",
    "gt_blast": "science_blue",
    "gt_cent": "science_blue",
    "gt_motor": RID["pack_structure"],
    "gt_elec": RID["pack_structure"],
    "gt_chem": RID["pack_structure"],
    "gt_mach2": RID["pack_structure"],
    "gt_qian": RID["pack_quantum"],
    "gt_fusion": RID["pack_quantum"],
    "gt_belt4": RID["pack_structure"],
    "gt_speed4": RID["pack_structure"],
}

# =====================================================================
# 1) 可卸载状态：登记所有手工内存表改动，on_unload 逐条还原
# =====================================================================

_MISSING = object()
_restores: list = []          # 每项是 () -> None 的还原闭包
_MACHINE_SPEED = 1.0          # on_step 刷新的全局机器提速缓存


def _patch_dict(d, key, value):
    old = d.get(key, _MISSING)
    d[key] = value
    _restores.append(lambda d=d, k=key, o=old: _undo_key(d, k, o))


def _undo_key(d, key, old):
    if old is _MISSING:
        d.pop(key, None)
    else:
        d[key] = old


def _patch_seq_get(obj, attr, value):
    """保存序列/集合的旧值，设置新值，登记还原。"""
    old = getattr(obj, attr)
    setattr(obj, attr, value)
    _restores.append(lambda o=obj, a=attr, v=old: setattr(o, a, v))


def _restore_categories(idx):
    """卸载时把「重工」大类从底栏分类里精确摘掉。"""
    _restores.append(lambda: TUI.CATEGORIES.pop(idx) if idx < len(TUI.CATEGORIES) else None)


# =====================================================================
# 2) 内容注册
# =====================================================================

def _register_items(ctx):
    for iid, name, color in ITEMS:
        ctx.add_item(iid, name, color)


def _register_recipes(ctx):
    for rid, ins, outs, dur, machines, tech in RECIPES:
        ctx.add_recipe(rid, dict(ins), dict(outs), dur, machines=tuple(machines))
        if tech:
            _patch_dict(C.RECIPE_TECH, rid, tech)


def _register_machines(ctx):
    for btype, name, item, color, usage, tech in MACHINES:
        # M8 建筑注册表：add_building 负责 BUILDING_REGISTRY + BUILD_ITEM 联动，
        # 在 add_recipe 之前调用，否则配方里的 machines 建筑 id 会校验失败。
        ctx.add_building(btype, name, item=item)
        _patch_dict(C.BUILDING_COLORS, btype, color)
        _patch_dict(C.POWER_USAGE, btype, usage)
        _patch_dict(C.TECH_UNLOCK_BUILDING, btype, tech)


def _register_tech(ctx):
    for tid, (name, cost, prereqs, desc) in TECHS:
        _patch_dict(C.TECH_TREE, tid, (name, cost, prereqs, desc))
        _patch_dict(C.TECH_PACK_RECIPE, tid, TECH_PACK[tid])
    # 科研包类型登记（科研站 idle 时认这些包）
    _patch_dict(C.TECH_PACK_ITEM, RID["pack_structure"], I_PACK_STRUCTURE)
    _patch_dict(C.TECH_PACK_ITEM, RID["pack_quantum"], I_PACK_QUANTUM)
    # 科研站制造模式可选的矩阵配方 + 手搓黑名单
    _patch_seq_get(C, "LAB_PRODUCE_RECIPES",
                   C.LAB_PRODUCE_RECIPES + (RID["pack_structure"], RID["pack_quantum"]))
    _patch_seq_get(C, "HANDCRAFT_BLACKLIST",
                   set(C.HANDCRAFT_BLACKLIST) | {RID["pack_structure"], RID["pack_quantum"]})


def _register_ui(ctx):
    """把四台新机器挂进底栏「重工」分类（并重排按钮布局）。"""
    g = ctx._game
    idx = len(TUI.CATEGORIES)
    TUI.CATEGORIES.append(("重工", GT_MACHINE_TYPES))
    _restore_categories(idx)
    ui = getattr(g, "ui", None)
    if ui is not None and hasattr(ui, "_layout"):
        ui._layout()


# =====================================================================
# 3) 渲染：给四台新机器画专属图案（mixin after ChunkRenderer._build，
#    在整块 chunk 画完后把新机器格子覆盖成自己的图案，原逻辑零改动）
# =====================================================================

# 机器基色表（渲染用，模块级预计算避免每格重建）
_GT_BASE = dict((m[0], m[3]) for m in MACHINES)


def _paint_gt_building(surf, rect, tile_px, btype):
    base = _GT_BASE.get(btype, (120, 120, 120))
    ChunkRenderer._base(surf, rect, base, tile_px)
    darkc = tuple(max(0, int(v * 0.55)) for v in base)
    lightc = tuple(min(255, int(v + (255 - v) * 0.5)) for v in base)
    cx, cy = rect.center
    if btype == B_GT_CRUSHER:
        # 粉碎机：深色颚板 + 两侧迸出的碎屑
        t = max(tile_px // 3, 2)
        pygame.draw.polygon(surf, darkc,
                            [(cx - t, cy - t), (cx + t, cy - t),
                             (cx + t // 2, cy), (cx - t, cy + t)])
        if tile_px >= 10:
            for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (-1, 1))):
                px = cx + dx * (t + max(tile_px // 6, 1))
                py = cy + dy * t
                pygame.draw.circle(surf, lightc, (px, py), max(tile_px // 7, 1))
    elif btype == B_GT_FURNACE:
        # 高炉：内框 + 炉火
        inner = rect.inflate(-tile_px // 4, -tile_px // 4)
        pygame.draw.rect(surf, darkc, inner)
        if tile_px >= 10:
            t = max(tile_px // 3, 2)
            pygame.draw.polygon(surf, (235, 150, 60),
                                [(cx, cy + t), (cx - t, cy - t // 2), (cx + t, cy - t // 2)])
            pygame.draw.circle(surf, (245, 210, 90), (cx, cy - t // 3),
                               max(tile_px // 6, 1))
    elif btype == B_GT_CENTRI:
        # 离心机：圆筒 + 三叶转子
        r = max(tile_px // 3, 2)
        pygame.draw.circle(surf, darkc, (cx, cy), r)
        if tile_px >= 10:
            t = max(tile_px // 3, 2)
            for a in (0, 2.1, 4.2):
                x2 = cx + int(math.cos(a) * t)
                y2 = cy + int(math.sin(a) * t)
                pygame.draw.line(surf, lightc, (cx, cy), (x2, y2), 2)
            pygame.draw.circle(surf, lightc, (cx, cy), max(tile_px // 8, 1))
    else:  # B_GT_ASSEMBLY
        # 组装线：两条输送线 + 中央齿轮
        if tile_px >= 8:
            w = max(tile_px // 8, 1)
            for yy in (rect.top + rect.height // 3, rect.top + rect.height * 2 // 3):
                pygame.draw.line(surf, (40, 46, 60),
                                 (rect.left + 2, yy), (rect.right - 2, yy), w)
        r = max(tile_px // 4, 2)
        pygame.draw.circle(surf, darkc, (cx, cy), r)
        pygame.draw.circle(surf, lightc, (cx, cy), r, 2)
        t = max(tile_px // 8, 1)
        pygame.draw.line(surf, darkc, (cx - r, cy), (cx + r, cy), t)
        pygame.draw.line(surf, darkc, (cx, cy - r), (cx, cy + r), t)


def after_build(self, result, cix, ciy, tile_px, **kw):
    """ChunkRenderer._build after：把新机器的格子画上专属图案。"""
    if result is None:
        return result
    g = self.grid
    cpc = self.cpc
    bx0 = cix * cpc
    by0 = ciy * cpc
    surf = result
    for ly in range(cpc):
        wy = (by0 + ly) % g.h
        row = g.building[wy]
        for lx in range(cpc):
            wx = (bx0 + lx) % g.w
            b = int(row[wx])
            if b in GT_MACHINE_TYPES:
                rect = pygame.Rect(lx * tile_px, ly * tile_px, tile_px, tile_px)
                _paint_gt_building(surf, rect, tile_px, b)
    return surf


# =====================================================================
# 4) mixin 补丁
# =====================================================================

def _install_mixins(ctx):
    sim = ctx.sim

    # 4.1 机器网络 sync 纳入本 mod 机器。设计成「组合式 replace」：
    #    不调用原版破坏性 sync（避免机器对象被清空重建、面板引用失效）。
    #    最内层（捕获到原版 sync 的那层）先跑“安全原版补录”，其余层调用
    #    上一层链；每层只补/清自己管辖的类型，别的 mod 的机器一律不动。
    from stellarloom.production.machines import MachineNetwork

    def safe_vanilla_pass(net):
        g = net.grid
        wanted = set()
        for bt in (C.B_FURNACE, C.B_ASSEMBLER):
            ys, xs = np.nonzero(g.building == bt)
            for y, x in zip(ys.tolist(), xs.tolist()):
                key = (x, y)
                wanted.add(key)
                if key not in net.machines:
                    net.machines[key] = Machine(x, y, int(g.building[y, x]))
        dead = [k for k, m in net.machines.items()
                if m.btype in (C.B_FURNACE, C.B_ASSEMBLER) and k not in wanted]
        for k in dead:
            del net.machines[k]

    if not hasattr(MachineNetwork, "_gt_vanilla_sync"):
        MachineNetwork._gt_vanilla_sync = MachineNetwork.sync
    _prev_sync = MachineNetwork.sync  # 安装前链（可能是别的 mod 的包装）

    def replace_machine_sync(self, *a, **k):
        g = self.grid
        # 只清/补自己的类型；原版熔炉/制造台由「安全原版补录」那层统一维护，
        # 严禁把原版机器当“多出来的”清掉（否则熔炉/制造台面板会消失）。
        owned = GT_MACHINE_TYPES
        # 快照自己的机器（防第三方破坏性 sync 清场）
        snap = {}
        for key, m in list(self.machines.items()):
            if m.btype in GT_MACHINE_TYPES:
                snap[key] = (m.recipe_id, dict(m.inputs), dict(m.outputs),
                             m.progress)
        if _prev_sync is None or _prev_sync is MachineNetwork._gt_vanilla_sync:
            safe_vanilla_pass(self)
        else:
            _prev_sync(self, *a, **k)
        # 补自己的机器（被清掉的重建并恢复状态）
        wanted = set()
        for btype in GT_MACHINE_TYPES:
            ys, xs = np.nonzero(g.building == btype)
            for y, x in zip(ys.tolist(), xs.tolist()):
                key = (x, y)
                wanted.add(key)
                if key not in self.machines:
                    m = Machine(x, y, int(g.building[y, x]))
                    s = snap.get(key)
                    if s is not None:
                        m.recipe_id, m.inputs, m.outputs, m.progress = s
                        m._set_need()
                    self.machines[key] = m
        dead = [k for k, m in self.machines.items()
                if m.btype in GT_MACHINE_TYPES and k not in wanted]
        # ↑ 只清自己的机器；原版熔炉/制造台由「安全原版补录」维护，绝不删除
        for k in dead:
            del self.machines[k]

    ctx.mixin("stellarloom.production.machines.MachineNetwork", "sync",
              replace_machine_sync, wrap="replace")

    # 4.2 放置新机器后立即 sync（让前端立刻能开面板）
    def after_place(self, result, btype, gx, gy, direction=0, **kw):
        if result == "ok" and btype in GT_MACHINE_TYPES:
            self.machines.sync()
        return result

    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              after_place, wrap="after")

    # 4.3 拆除新机器：退回内部的原料/产物（before 记类型 + after 退款）
    def before_remove(self, gx, gy, **kw):
        self._mod_gt_removing = (gx, gy, self.grid.get(gx, gy))
        return None

    def after_remove(self, result, gx, gy, **kw):
        rec = getattr(self, "_mod_gt_removing", None)
        try:
            if rec and rec[0] == gx and rec[1] == gy and rec[2] in GT_MACHINE_TYPES:
                if self.grid.get(gx, gy) == C.B_EMPTY:
                    m = self.machines.get_machine(gx, gy)
                    if m is not None:
                        for store in (m.inputs, m.outputs):
                            for it, n in list(store.items()):
                                if n > 0:
                                    self.inventory[it] = self.inventory.get(it, 0) + n
                            store.clear()
                        self.machines.machines.pop(
                            (gx % self.grid.w, gy % self.grid.h), None)
        finally:
            self._mod_gt_removing = None
        return result

    ctx.mixin("stellarloom.sim.sim.Simulation", "remove_building",
              before_remove, wrap="before")
    ctx.mixin("stellarloom.sim.sim.Simulation", "remove_building",
              after_remove, wrap="after")

    # 4.4 传送带速度：「传动学 IV」再 +25%
    def after_belt_speed(self, result, **kw):
        if "gt_belt4" in self.researched:
            return result * 1.25
        return result

    ctx.mixin("stellarloom.tech.tech_tree.TechTree", "belt_speed_multiplier",
              after_belt_speed, wrap="after")

    # 4.5 机器生产速度：「生产加速 I」全部机器 +25%（模块级缓存由 on_step 刷新）
    def before_machine_update(self, dt, speed_factor, **kw):
        if _MACHINE_SPEED != 1.0:
            return ((dt * _MACHINE_SPEED, speed_factor), {})  # (args, kwargs)
        return None

    ctx.mixin("stellarloom.production.machines.MachineNetwork", "update",
              before_machine_update, wrap="before")

    # 4.6 手搓面板目录：mod 配方在建面板之后注册，打开时重建目录
    def after_craft_show(self, result, screen_size, inventory, **kw):
        newcat = {}
        for rid, (ins, outs, dur, allows) in C.RECIPES.items():
            for item in outs:
                newcat.setdefault(item, rid)
        self._catalog.clear()
        self._catalog.update(newcat)
        if self.sel_item is not None and self.sel_item not in self._catalog:
            self.sel_item = None
        return result

    ctx.mixin("stellarloom.ui.craft_panel.CraftPanel", "show",
              after_craft_show, wrap="after")

    # 4.7 机器面板标题：新机器显示自己的名字（原实现只有 熔炉/制造台 两分支）
    def after_machine_draw(self, result, screen, **kw):
        m = self.machine
        if m is not None and m.btype in GT_MACHINE_TYPES:
            r = self.rect
            pygame.draw.rect(screen, (20, 24, 34),
                             (r.left + 10, r.top + 8, r.width - 20, 26))
            name = C.BUILDING_NAMES.get(m.btype, f"机器{m.btype}")
            t = self.fonts.get(18).render(f"{name} ({m.x},{m.y})",
                                          True, (200, 220, 240))
            screen.blit(t, (r.left + 14, r.top + 10))
        return result

    ctx.mixin("stellarloom.ui.machine_panel.MachinePanel", "draw",
              after_machine_draw, wrap="after")

    # 4.8 点按放置新机器后：现场开面板（原实现只给熔炉/制造台/箱子/采矿机开）
    def after_place_or_harvest(self, result, gx, gy, confirm_only, **kw):
        try:
            if self.grid.get(gx, gy) in GT_MACHINE_TYPES:
                self._try_open_panel(gx, gy)
        except Exception:
            pass
        return result

    ctx.mixin("stellarloom.core.game.Game", "_place_or_harvest",
              after_place_or_harvest, wrap="after")

    # 4.9 chunk 渲染：新机器专属图案
    ctx.mixin("stellarloom.render.layers.ChunkRenderer", "_build",
              after_build, wrap="after")

    # 4.10 每帧：刷新机器提速缓存（只能世界推进时刷新，够用；
    #      新开局会换 sim，这里动态取，避免读到旧对象）
    game_ref = ctx._game
    cfg_ref = ctx.cfg          # M6.29：运行时合并配置（用户优先覆盖作者默认）

    def on_step(dt):
        global _MACHINE_SPEED
        try:
            live = game_ref.sim if game_ref is not None else sim
            if "gt_speed4" in live.tech.researched:
                accel = cfg_ref.get("production_accel", 1.25)
                _MACHINE_SPEED = accel if isinstance(accel, (int, float)) \
                    and accel > 0 else 1.25
            else:
                _MACHINE_SPEED = 1.0
        except Exception:
            _MACHINE_SPEED = 1.0

    ctx.on_step(on_step)


# =====================================================================
# 5) 生命周期钩子
# =====================================================================

def on_load(ctx):
    global _MACHINE_SPEED
    _MACHINE_SPEED = 1.0
    _restores.clear()
    cfg = ctx.cfg   # M6.29：作者默认 config.json ⊕ 用户 mods/config/…（用户优先）

    _register_items(ctx)
    _register_machines(ctx)   # 先注册建筑（M8），配方里的 machines 才能通过校验
    _register_recipes(ctx)
    _register_tech(ctx)
    _register_ui(ctx)
    _install_mixins(ctx)

    n_items = len(ITEMS)
    n_recipes = len(RECIPES)
    n_techs = len(TECHS)
    if cfg.get("toasts", True):
        ctx.toast("格雷科技：星织重工 已加载 —— 矿石加工 → 高炉冶金 → 量子时代", 3.5)
    ctx.log(
        f"内容：{n_items} 种新物品 / {n_recipes} 条配方 / {n_techs} 项科技"
        f" / {len(MACHINES)} 台新机器"
    )
    ctx.log("科技线：粉碎机 → 高炉(钢锭+炉渣) → 离心机(硫粉/稀土粉)"
            " → 马达/处理器 → 组装线 → 超导/激光 → 聚变线圈/星织引擎")


def on_unload(ctx):
    """卸载：还原所有手工内存表改动（mixin 与 add_item/add_recipe 由加载器自动还原）。"""
    # 按登记顺序逆序还原（内含底栏「重工」分类摘除）
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
        ctx.toast("格雷科技：星织重工 已卸载", 2.0)