"""全局配置常量。"""

from .data import load_recipes, load_recipe_fluids  # noqa: E402
from .registry import (ITEM_REGISTRY, BUILDING_REGISTRY, FLUID_REGISTRY,
                       VANILLA)  # noqa: E402

# 窗口
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
FPS = 60
TITLE = "星织：无尽沙盒 StellarLoom-PG v0.1"

# 世界
GRID_W = 512
GRID_H = 512
TILE = 24  # 1x 缩放下的像素尺寸

# 相机
CAM_SPEED = 600.0      # 像素/秒（1x 缩放下）
ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 1.15
# 星系视图（M6.32）：缩到最小后继续缩小会攒"出界进度"，满了进星系视图
ZOOM_PULL_RATE = 2.6       # 进度 = -ln(缩放系数) × 这个值（滚轮一格 ≈0.36，3 格进）
ZOOM_PULL_MIN_STEP = 0.25  # 捏合一帧再小也至少推进这么多（手势事件少也能进）

# 传送带
BELT_SPEED = 2.0        # 格/秒
ITEM_SPACING = 0.25     # 物品间最小间距（格）
ITEM_CAPACITY_PER_CELL = 1 / ITEM_SPACING  # 每格最多 4 个

# 分拣器（M10：三段式机械臂，纯视觉；逻辑仍是 1 格 overlay）
INSERTER_COOLDOWN = 1.0     # 抓取间隔（秒）
INSERTER_SWING_TIME = 0.35  # 单程摆动时间（去程/回程各占一半）

# ---------------- 建筑注册表（M8：MC 风格，命名空间 stellarloom:） ----------------
# 原版建筑固定 id 注册（值 1-13 与老常量一致 → 网格/存档数字不漂移）；
# mod 建筑走 ctx.add_building：名字注册动态分配（100+），旧式固定数字兼容。
_VANILLA_BUILDINGS = [
    # (id, 名字key, 显示名)
    (1,  "belt",          "传送带"),
    (2,  "miner",         "采矿机"),
    (3,  "furnace",       "熔炉"),
    (4,  "assembler",     "制造台"),
    (5,  "core",          "核心"),
    (6,  "inserter",      "分拣器"),
    (7,  "solar",         "太阳能"),
    (8,  "wind",          "风力"),
    (9,  "tower_supply",  "供应塔"),
    (10, "tower_request", "请求塔"),
    (11, "lab",           "科研站"),
    (12, "chest",         "箱子"),
    (13, "emitter",       "太阳帆发射器"),
    (14, "launch_pad",    "发射台"),
    (15, "planet_engine", "行星引擎"),
    (16, "power_pole",    "电力塔"),
    # M14 液体系统（17-19）：每格独立液量 + 限速均流 + 泵单向加压
    (17, "pipe",          "管道"),
    (18, "tank",          "储液罐"),
    (19, "fluid_pump",    "液体泵"),
]
for _bid, _bkey, _bdisp in _VANILLA_BUILDINGS:
    BUILDING_REGISTRY.fixed_register(_bid, f"{VANILLA}:{_bkey}", _bdisp)

# B_* 常量：内部引用用（值 = 注册表 id，与原固定段一致，别改）
B_BELT = BUILDING_REGISTRY.id_of("stellarloom:belt")
B_MINER = BUILDING_REGISTRY.id_of("stellarloom:miner")
B_FURNACE = BUILDING_REGISTRY.id_of("stellarloom:furnace")
B_ASSEMBLER = BUILDING_REGISTRY.id_of("stellarloom:assembler")
B_CORE = BUILDING_REGISTRY.id_of("stellarloom:core")
B_INSERTER = BUILDING_REGISTRY.id_of("stellarloom:inserter")
B_SOLAR = BUILDING_REGISTRY.id_of("stellarloom:solar")
B_WIND = BUILDING_REGISTRY.id_of("stellarloom:wind")
B_TOWER_SUPPLY = BUILDING_REGISTRY.id_of("stellarloom:tower_supply")
B_TOWER_REQUEST = BUILDING_REGISTRY.id_of("stellarloom:tower_request")
B_LAB = BUILDING_REGISTRY.id_of("stellarloom:lab")
B_CHEST = BUILDING_REGISTRY.id_of("stellarloom:chest")
B_EMITTER = BUILDING_REGISTRY.id_of("stellarloom:emitter")
B_LAUNCH_PAD = BUILDING_REGISTRY.id_of("stellarloom:launch_pad")
B_PLANET_ENGINE = BUILDING_REGISTRY.id_of("stellarloom:planet_engine")
B_POWER_POLE = BUILDING_REGISTRY.id_of("stellarloom:power_pole")
B_PIPE = BUILDING_REGISTRY.id_of("stellarloom:pipe")
B_TANK = BUILDING_REGISTRY.id_of("stellarloom:tank")
B_FLUID_PUMP = BUILDING_REGISTRY.id_of("stellarloom:fluid_pump")

# 网格空位标记（building 数组 0 = 空）
B_EMPTY = 0

# 实时视图：建筑 id → 显示名（mod 注册后立刻可见）
BUILDING_NAMES = BUILDING_REGISTRY.names_map

# 物流塔
TOWER_RANGE = 30      # 覆盖半径（格）
TOWER_SIZE = 3        # 占地 3×3
TOWER_STACK = 20      # 每种物品最多存多少

# 无人机
DRONE_SPEED = 8.0         # 格/秒
DRONE_CAPACITY = 4        # 载货量
DRONE_MAX_ENERGY = 100.0
DRONE_ENERGY_PER_CELL = 1.0
DRONE_CHARGE_RATE = 20.0  # 每秒充电
DRONE_WAIT_TIMEOUT = 15.0 # 请求塔满时在塔旁等多久，超时带货回母塔
DRONE_RESERVE_ENERGY = 5.0  # 派工预留电量（防止半路刚好没电）
DRONES_PER_TOWER = 2

# ================= 电力（M9 真电网，单位：kW） =================
# 数值尺度：旧"抽象单位"×20 = kW；倍率统一，玩法平衡与旧档一致。
POWER_LEGACY_SCALE = 20.0
POWER_LINK_RANGE = 8.0   # 接线最大距离（格）：塔/机器之间在范围内即并网

# 每秒耗电（kW）
POWER_USAGE = {
    B_MINER: 20.0,
    B_FURNACE: 30.0,
    B_ASSEMBLER: 40.0,
    B_INSERTER: 4.0,
    B_TOWER_SUPPLY: 40.0,
    B_TOWER_REQUEST: 40.0,
    B_LAB: 20.0,
    B_EMITTER: 30.0,
    B_LAUNCH_PAD: 60.0,
    B_PLANET_ENGINE: 800.0,  # 行星引擎：大件，驱动整颗行星变轨
    B_FLUID_PUMP: 20.0,     # 液体泵（M14）：单向加压输送
}

# ---------------- 液体（M14）----------------
# 模型：每格独立液量（不做整段共享），相邻格按压差限速互流，泵单向加压。
PIPE_CELL_CAP = 100.0        # 一格管道装多少单位液体
TANK_CELL_CAP = 2500.0       # 一格储液罐（同一个数组，只是容量大）
PIPE_FLOW_RATE = 60.0        # 相邻两格之间每秒最多输运多少（压力差再大也就这么快）
PUMP_FLOW_RATE = 300.0       # 泵每秒输运上限（相当于 5 根直管）
FLUID_MACHINE_DRAW = 30.0    # 机器每秒从邻格抽多少
FLUID_MACHINE_PUSH = 30.0    # 机器每秒往邻格排多少
MACHINE_FLUID_CAP = 100.0    # 机器内部每种液体最多囤多少
FLUID_EPS = 1e-3             # 小于这个量视作空（防浮点尾巴）

# 发电（kW）
# B_CORE 是**遗留发电**：M13.2 起新开局不再预置核心，但旧存档里已经摆下的
# 核心必须继续发电，否则老档电力直接掉一半、整条产线降速（破坏存档）。
# 新档想有电就自己铺太阳能/风力。
POWER_GEN = {
    B_SOLAR: 60.0,  # 白天满功率，夜晚 0
    B_WIND: 40.0,   # 恒定
    B_CORE: 160.0,  # 仅旧档兼容：新开局不放核心
}

# 手动采矿（长按）：挖 1 个要几秒。不需要电、不需要采矿机。
MANUAL_MINE_SECONDS = 1.2

# 原版建筑 id 集合（mod 的电力数值按旧单位 ×POWER_LEGACY_SCALE 换算）
VANILLA_BUILDING_IDS = frozenset(b for b, _, _ in _VANILLA_BUILDINGS)

# ---------------- 物品注册表（M7：MC 风格，命名空间 stellarloom:） ----------------
# 原版固定 id 注册（id 与旧常量一致 → 旧存档数字反查不漂移）；
# mod 物品走 ctx.add_item：新式名字注册动态分配 id，旧式数字注册兼容段。
_VANILLA_ITEMS = [
    # (id, 名字key, 显示名, 颜色)
    (1,  "iron_ore",    "铁矿石",     (200, 140, 60)),
    (2,  "iron_plate",  "铁板",       (200, 200, 210)),
    (3,  "gear",        "齿轮",       (160, 160, 170)),
    (4,  "circuit",     "电路板",     (80, 200, 120)),
    (5,  "copper_ore",  "铜矿石",     (200, 110, 90)),
    (6,  "copper_plate","铜板",       (230, 150, 100)),
    (7,  "stone",       "石矿",       (150, 150, 155)),
    (8,  "stone_brick", "石材",       (170, 165, 150)),
    (9,  "copper_wire", "铜线",       (240, 180, 90)),
    (10, "magnet",      "磁铁",       (120, 140, 220)),
    (11, "science_blue","电磁矩阵",   (80, 130, 230)),
    (12, "science_red", "能量矩阵",   (230, 90, 80)),
    (13, "solar_sail",  "太阳帆",     (245, 235, 200)),
    (14, "grain",       "硅石",       (200, 195, 170)),
    (101, "belt",         "传送带",   (110, 130, 160)),
    (102, "inserter",     "分拣器",   (200, 170, 60)),
    (103, "miner",        "采矿机",   (90, 160, 90)),
    (104, "furnace",      "熔炉",     (180, 90, 70)),
    (105, "assembler",    "制造台",   (90, 130, 190)),
    (106, "solar",        "太阳能板", (60, 90, 200)),
    (107, "wind",         "风力涡轮", (170, 210, 220)),
    (108, "tower_supply", "供应塔",   (80, 200, 120)),
    (109, "tower_request","请求塔",   (230, 150, 50)),
    (110, "lab",          "科研站",   (180, 100, 200)),
    (111, "chest",        "箱子",     (150, 120, 80)),
    (112, "emitter",      "太阳帆发射器", (250, 220, 120)),
    (113, "launch_pad",   "发射台",   (110, 170, 230)),
    (114, "planet_engine","行星引擎", (150, 220, 190)),
    (115, "power_pole",   "电力塔",   (205, 180, 120)),
    # M14 液体建筑
    (116, "pipe",         "管道",     (110, 125, 145)),
    (117, "tank",         "储液罐",   (150, 160, 175)),
    (118, "fluid_pump",   "液体泵",   (120, 200, 200)),
]
for _iid, _key, _disp, _col in _VANILLA_ITEMS:
    ITEM_REGISTRY.fixed_register(_iid, f"{VANILLA}:{_key}", _disp, _col)

# I_* 常量：内部引用用（值 = 注册表 id，与原固定段一致，别改）
I_IRON_ORE = ITEM_REGISTRY.id_of("stellarloom:iron_ore")
I_IRON_PLATE = ITEM_REGISTRY.id_of("stellarloom:iron_plate")
I_GEAR = ITEM_REGISTRY.id_of("stellarloom:gear")
I_CIRCUIT = ITEM_REGISTRY.id_of("stellarloom:circuit")
I_COPPER_ORE = ITEM_REGISTRY.id_of("stellarloom:copper_ore")
I_COPPER_PLATE = ITEM_REGISTRY.id_of("stellarloom:copper_plate")
I_STONE = ITEM_REGISTRY.id_of("stellarloom:stone")
I_STONE_BRICK = ITEM_REGISTRY.id_of("stellarloom:stone_brick")
I_COPPER_WIRE = ITEM_REGISTRY.id_of("stellarloom:copper_wire")
I_MAGNET = ITEM_REGISTRY.id_of("stellarloom:magnet")
I_SCIENCE_BLUE = ITEM_REGISTRY.id_of("stellarloom:science_blue")
I_SCIENCE_RED = ITEM_REGISTRY.id_of("stellarloom:science_red")
I_SOLAR_SAIL = ITEM_REGISTRY.id_of("stellarloom:solar_sail")
I_GRAIN = ITEM_REGISTRY.id_of("stellarloom:grain")
# 建筑物品
I_BELT_ITEM = ITEM_REGISTRY.id_of("stellarloom:belt")
I_INSERTER_ITEM = ITEM_REGISTRY.id_of("stellarloom:inserter")
I_MINER_ITEM = ITEM_REGISTRY.id_of("stellarloom:miner")
I_FURNACE_ITEM = ITEM_REGISTRY.id_of("stellarloom:furnace")
I_ASSEMBLER_ITEM = ITEM_REGISTRY.id_of("stellarloom:assembler")
I_SOLAR_ITEM = ITEM_REGISTRY.id_of("stellarloom:solar")
I_WIND_ITEM = ITEM_REGISTRY.id_of("stellarloom:wind")
I_TOWER_SUPPLY_ITEM = ITEM_REGISTRY.id_of("stellarloom:tower_supply")
I_TOWER_REQUEST_ITEM = ITEM_REGISTRY.id_of("stellarloom:tower_request")
I_LAB_ITEM = ITEM_REGISTRY.id_of("stellarloom:lab")
I_CHEST_ITEM = ITEM_REGISTRY.id_of("stellarloom:chest")
I_EMITTER_ITEM = ITEM_REGISTRY.id_of("stellarloom:emitter")
I_LAUNCH_PAD_ITEM = ITEM_REGISTRY.id_of("stellarloom:launch_pad")
I_PLANET_ENGINE_ITEM = ITEM_REGISTRY.id_of("stellarloom:planet_engine")
I_POWER_POLE_ITEM = ITEM_REGISTRY.id_of("stellarloom:power_pole")
I_PIPE_ITEM = ITEM_REGISTRY.id_of("stellarloom:pipe")
I_TANK_ITEM = ITEM_REGISTRY.id_of("stellarloom:tank")
I_FLUID_PUMP_ITEM = ITEM_REGISTRY.id_of("stellarloom:fluid_pump")

# 数字视图（UI/渲染/内部 dict 用 int 查——**实时引用**注册表内部 dict，
# mod 注册/卸载物品后这里立刻同步，消费方零改动）
ITEM_NAMES = ITEM_REGISTRY.names_map
ITEM_COLORS = ITEM_REGISTRY.colors_map
# 名字视图（存档 / 配方 JSON / mod API 用 "stellarloom:iron_ore"）
ITEM_IDS = ITEM_REGISTRY.ids_map

# ---------------- 液体注册表（M14）----------------
# 液体是独立 id 段（0 = 空），**不进背包/传送带/分拣器过滤**。
_VANILLA_FLUIDS = [
    (1, "crude_oil", "原油",   (58, 48, 40)),
    (2, "fuel_oil",  "燃料油", (196, 116, 40)),
    (3, "petroleum", "石油气", (176, 196, 124)),
]
for _fid, _fkey, _fdisp, _fcol in _VANILLA_FLUIDS:
    FLUID_REGISTRY.fixed_register(_fid, f"{VANILLA}:{_fkey}", _fdisp, _fcol)

F_EMPTY = 0
F_CRUDE_OIL = FLUID_REGISTRY.id_of("stellarloom:crude_oil")
F_FUEL_OIL = FLUID_REGISTRY.id_of("stellarloom:fuel_oil")
F_PETROLEUM = FLUID_REGISTRY.id_of("stellarloom:petroleum")

# 实时视图（mod 注册液体后立刻可见）
FLUID_NAMES = FLUID_REGISTRY.names_map
FLUID_COLORS = FLUID_REGISTRY.colors_map
FLUID_IDS = FLUID_REGISTRY.ids_map
FLUID_FALLBACK_COLOR = (150, 150, 150)

# 矿脉类型（grid.ore_type 数组的值）
ORE_NONE = 0
ORE_IRON = 1
ORE_COPPER = 2
ORE_STONE = 3
# 矿类型 → 挖出来的物品
ORE_TO_ITEM = {
    ORE_IRON: I_IRON_ORE,
    ORE_COPPER: I_COPPER_ORE,
    ORE_STONE: I_STONE,
}
# 矿脉渲染颜色（铁橙 / 铜红棕 / 石灰蓝）
ORE_COLORS = {
    ORE_IRON: (200, 140, 60),
    ORE_COPPER: (190, 100, 70),
    ORE_STONE: (140, 150, 165),
}
ORE_FALLBACK_COLOR = (200, 140, 60)

# 配方：id -> (输入dict, 输出dict, 机器耗时秒, 允许的建筑)
#
# **统一配方（M6.6）**：一个物品只有一个配方，手搓和机器共用同一份数据，
# 不再有 hand_xxx / mk_xxx 两套。区别只在「在哪做」和「多快」：
#   - 机器做：按上面的 dur 秒/次，可自动化、可并行流水线。
#   - 手搓做：同样消耗同样原料，但每件耗时 dur × HAND_CRAFT_TIME_MULT，
#     而且玩家自己盯着，不能并行。
# 因此"手搓更贵"不再靠配方涨价，而是靠**时间成本**——这是更干净的建模。
#
# allows（machines）= 能做这个配方的建筑；空元组 () 表示"任何机器都不做，
# 只能手搓"（目前一个都没有——用户要求所有东西都能自动化）。
#
# M6.28：内置配方迁到 data/recipes.json（JSON 存储，启动时加载），
# 格式保持不变。mod 仍可用 ctx.add_recipe 注入同一 dict。
RECIPES = load_recipes()

# M6.28 启动校验：recipes.json 引用的物品/建筑 id 必须存在（防手误，启动即报）
for _rid, (_ins, _outs, _dur, _mach) in RECIPES.items():
    for _it in {**_ins, **_outs}:
        if _it not in ITEM_NAMES:
            raise ValueError(
                f"配方 {_rid} 引用了未注册物品 id {_it}（数据/recipes.json）")

# ---------------- 液体配方旁挂表（M14）----------------
# 为了让 26 条既有配方和 mod 的 4 元组解包零改动，液体不进 RECIPES 元组，
# 而是这张旁挂表：rid -> (输入液体 {fid: 量}, 输出液体 {fid: 量})。
# 同一 rid 可以既有物品配方（RECIPES）又有液体配方——比如"原油→燃料油+石油气"
# 只有液体，也允许"塑料：石油气 + 石砖 → 塑料"这种混搭。
RECIPE_FLUIDS: dict[str, tuple[dict, dict]] = load_recipe_fluids()


def fluid_recipe_of(rid: str) -> tuple[dict, dict]:
    """配方用到的液体：(输入, 输出)。没有液体配方返回两个空 dict。"""
    return RECIPE_FLUIDS.get(rid, ({}, {}))


# 能做配方 = 建筑 id 是否出现在该配方的 machines 元组里（液体配方共用）。
def recipe_machines(rid: str) -> tuple:
    r = RECIPES.get(rid)
    return r[3] if r else ()

# 手搓耗时倍率：手搓比机器慢这么多倍。成本完全一样，只是时间。
HAND_CRAFT_TIME_MULT = 2.5

# 旧存档里的配方 id 映射（M6.6 之前的 hand_*/mk_* 两套并进统一表）。
# 只用于开旧档时把 machine.recipe_id 翻译过来，新存档不会出现这些 key。
LEGACY_RECIPE_ALIAS = {
    "hand_iron_plate": "iron_plate",
    "hand_copper_plate": "copper_plate",
    "hand_stone_brick": "stone_brick",
    "hand_magnet": "magnet",
    "hand_gear": "gear",
    "hand_copper_wire": "copper_wire",
    "hand_circuit": "circuit",
    "hand_belt": "belt",
    "hand_inserter": "inserter",
    "hand_furnace": "furnace",
    "hand_miner": "miner",
    "hand_assembler": "assembler",
    "hand_chest": "chest",
    "hand_solar": "solar",
    "hand_wind": "wind",
    "hand_tower_s": "tower_s",
    "hand_tower_r": "tower_r",
    "hand_lab": "lab",
    "mk_belt": "belt",
    "mk_inserter": "inserter",
    "mk_furnace": "furnace",
    "mk_miner": "miner",
    "mk_assembler": "assembler",
    "mk_solar": "solar",
    "mk_wind": "wind",
    "mk_tower_s": "tower_s",
    "mk_tower_r": "tower_r",
    "mk_lab": "lab",
    "mk_chest": "chest",
}

# 建筑 → 放置时消耗的物品
BUILD_ITEM = {
    B_BELT: I_BELT_ITEM,
    B_INSERTER: I_INSERTER_ITEM,
    B_MINER: I_MINER_ITEM,
    B_FURNACE: I_FURNACE_ITEM,
    B_ASSEMBLER: I_ASSEMBLER_ITEM,
    B_SOLAR: I_SOLAR_ITEM,
    B_WIND: I_WIND_ITEM,
    B_TOWER_SUPPLY: I_TOWER_SUPPLY_ITEM,
    B_TOWER_REQUEST: I_TOWER_REQUEST_ITEM,
    B_LAB: I_LAB_ITEM,
    B_CHEST: I_CHEST_ITEM,
    B_EMITTER: I_EMITTER_ITEM,
    B_LAUNCH_PAD: I_LAUNCH_PAD_ITEM,
    B_PLANET_ENGINE: I_PLANET_ENGINE_ITEM,
    B_POWER_POLE: I_POWER_POLE_ITEM,
    B_PIPE: I_PIPE_ITEM,
    B_TANK: I_TANK_ITEM,
    B_FLUID_PUMP: I_FLUID_PUMP_ITEM,
}

# 可当"液体格"的建筑（参与管网计算，容量见 PIPE_CELL_CAP/TANK_CELL_CAP）
FLUID_CELL_BUILDINGS = frozenset({B_PIPE, B_TANK})

# 机器类建筑（MachineNetwork.sync 按这个集合建实例；mod 建筑可自行加入）
MACHINE_BTYPES = (B_FURNACE, B_ASSEMBLER)

# 开局送一批启动物资（不然连第一条带子都铺不了）
STARTING_ITEMS = {
    I_IRON_PLATE: 50,
    I_GEAR: 20,
    I_BELT_ITEM: 30,
    I_INSERTER_ITEM: 8,
    I_FURNACE_ITEM: 2,
    I_MINER_ITEM: 2,
}

# 箱子：每种物品最多囤多少（箱子可混装多种）
CHEST_STACK = 50
# 采矿机内置暂存格：总共能囤几个矿（混装），满了就停止挖掘，不白挖
MINER_BUFFER_CAP = 50

# 机器放下去是空壳：没有配方，不收任何物品，玩家必须在机器面板里自己指定

# 机器内置储存容量
MACHINE_INPUT_CAP = 10   # 每种原料最多囤 10 个
MACHINE_OUTPUT_CAP = 10  # 每种产物最多囤 10 个

# 配方需要的科技（未研究时机器面板不显示该配方）
RECIPE_TECH = {
    "circuit": "circuit1",
}

# 方向：0=右 1=下 2=左 3=上
DX = (1, 0, -1, 0)
DY = (0, 1, 0, -1)

# 颜色
C_BG = (12, 14, 20)
C_GRID = (28, 32, 44)
C_ORE = (200, 140, 60)
C_BELT = (70, 90, 120)
C_BELT_DIR = (130, 170, 220)
C_ITEM = (230, 200, 90)
C_MINER = (90, 160, 90)
C_FURNACE = (180, 90, 70)
C_ASSEMBLER = (90, 130, 190)
C_CORE = (220, 220, 240)
C_SELECT = (250, 220, 80)
C_TEXT = (210, 215, 225)
C_GHOST_OK = (90, 220, 120)
C_GHOST_BAD = (220, 80, 80)
C_INSERTER = (200, 170, 60)
C_SOLAR = (60, 90, 200)
C_WIND = (170, 210, 220)
C_TOWER_SUPPLY = (80, 200, 120)
C_TOWER_REQUEST = (230, 150, 50)
C_LAB = (180, 100, 200)
C_CHEST = (150, 120, 80)
C_EMITTER = (250, 220, 120)
C_LAUNCH_PAD = (110, 170, 230)
C_PLANET_ENGINE = (150, 220, 190)
C_POWER_POLE = (205, 180, 120)
C_PIPE = (110, 125, 145)
C_TANK = (150, 160, 175)
C_FLUID_PUMP = (120, 200, 200)

BUILDING_COLORS = {
    B_BELT: C_BELT,
    B_MINER: C_MINER,
    B_FURNACE: C_FURNACE,
    B_ASSEMBLER: C_ASSEMBLER,
    B_CORE: C_CORE,
    B_INSERTER: C_INSERTER,
    B_SOLAR: C_SOLAR,
    B_WIND: C_WIND,
    B_TOWER_SUPPLY: C_TOWER_SUPPLY,
    B_TOWER_REQUEST: C_TOWER_REQUEST,
    B_LAB: C_LAB,
    B_CHEST: C_CHEST,
    B_EMITTER: C_EMITTER,
    B_LAUNCH_PAD: C_LAUNCH_PAD,
    B_PLANET_ENGINE: C_PLANET_ENGINE,
    B_POWER_POLE: C_POWER_POLE,
    B_PIPE: C_PIPE,
    B_TANK: C_TANK,
    B_FLUID_PUMP: C_FLUID_PUMP,
}

# 科研站：吃电磁矩阵（一级科研包），一个包推进 1 点研究进度
LAB_CONSUME_ITEM = I_SCIENCE_BLUE
LAB_CONSUME_INTERVAL = 2.0  # 秒/个
LAB_STORE_CAP = 10          # 科研站每种科研包最多囤 10 个

# ---------- 科研站双模式（M6.11） ----------
# 科研站有两种工作模式：
#   research：只输入（吃科研包），统一推进当前研究项，不产出任何东西
#   produce ：制造矩阵（产出模式），可输入原料、输出矩阵
LAB_MODE_RESEARCH = "research"
LAB_MODE_PRODUCE = "produce"

# 科研站能制造的矩阵配方（制造模式二选一）。所有矩阵只能由科研站造，
# 制造台/手搓都不行——这是"矩阵垄断"铁律。
LAB_PRODUCE_RECIPES = ("science_blue", "science_red")
LAB_PRODUCE_INPUT_CAP = 10   # 制造模式每种原料最多囤 10 个
LAB_PRODUCE_OUTPUT_CAP = 10  # 制造模式每种产物最多囤 10 个

# 手搓黑名单：这些配方不许手搓，只能由科研站制造。
# 一级包（电磁矩阵）必须能手搓——开局没电，科研站转不起来，
# 「挖矿 → 手搓蓝包 → 手动研究 → 解锁电力」是唯一的开局推进路径。
# 二级包（能量矩阵）仍然垄断给科研站，保住后期自动化门槛。
HANDCRAFT_BLACKLIST = {"science_red"}

# ---------- 戴森云（M4） ----------
# 轨道：极坐标（角度 0~360 度），每个轨道能挂多少帆
DYSON_ORBITS = 3                    # 可建 3 条轨道
DYSON_ORBIT_NAMES = ("内轨", "中轨", "外轨")
DYSON_ORBIT_RADIUS = (0.35, 0.62, 0.90)   # 相对屏幕短边的半径比例
DYSON_ORBIT_CAP = (60, 120, 200)          # 每条轨道最多挂多少帆
DYSON_SAIL_POWER = 240.0               # 每片帆的发电量（kW）
DYSON_SAIL_PER_LAUNCH = 1              # 发射器一次打几片帆
DYSON_LAUNCH_INTERVAL = 1.2            # 发射间隔（秒）
DYSON_EMITTER_STORE_CAP = 30           # 发射器最多囤多少帆
# 轨道旋转：帆在轨道上环绕的速度（度/秒），只是视觉效果
DYSON_ROTATE_SPEED = (14.0, 8.0, 4.0)

# ---------- 行星轨道（M6.31：真实开普勒参数） ----------
# 不再是"手填周期 + 正弦近似"：行星轨道由真实半长轴 a(AU)、偏心率 e、
# 近点辐角决定，周期按开普勒第三定律 T(年)=a^1.5 换算成游戏秒；
# 日照 F=1/r²，以地球平均距离（1 AU）为 1.0。真实数据见 world/planets.py。
SECONDS_PER_YEAR = 600.0     # 游戏里 1 地球年 = 600 秒（10 分钟，肉眼可见在动）
PLANET_ORBIT_PERIOD = SECONDS_PER_YEAR   # 兼容旧常量：地球基准公转一圈
PLANET_ECCENTRICITY = 0.01671            # 兼容旧常量：地球真实偏心率
PLANET_COLOR = (90, 180, 230)    # 行星颜色（轨道图面板里画）
PLANET_ORBIT_RADIUS = 1.10       # 轨道图面板里最外层行星轨道半径（相对戴森云基准）

# ---------- 星际物流（M5b：发射台 + 运输船 + 发射窗口） ----------
# 发射台：3×3 大件，两种模式（supply 供货 / request 要货），靠相邻带子收发货。
# 运输船：恒星级舰队，跨行星飞；只有"发射窗口"开着（两颗行星相位对齐）才能发。
PAD_STACK = 50                # 发射台每种物品最多囤多少
SHIP_CARGO_CAP = 20           # 单船一次最多运多少
SHIP_FLIGHT_BASE = 12.0       # 基准单程飞行秒数（相位越远越久，见 pads.flight_time）
SHIP_WINDOW_ANGLE = 30.0      # 发射窗口：两颗行星相位差 ≤ 这个角度才能发射
SHIP_MIN_CARGO = 1            # 至少装多少才值得发（0 = 空船也发，没意义）

# ---------- 行星工程（M6）：行星引擎 ----------
# 引擎通电后可把本行星的轨道半径推拉到原始半长轴的 60%~180%：
# 周期按开普勒第三定律 T=a^1.5 跟着变，日照 1/r²、温度也随之变。
ENGINE_A_MIN_RATIO = 0.60     # 轨道半径下限（×原始半长轴）
ENGINE_A_MAX_RATIO = 1.80     # 轨道半径上限
ENGINE_PHASE_STEP = 15.0      # 面板点一次"相位 ±"转多少度
ENGINE_TEMP_BASE_K = 288.0    # 地球平均温度 288 K（≈15°C）
ENGINE_TEMP_SAFE_C = 35.0     # 低于此温度太阳能满效率
ENGINE_TEMP_PENALTY = 200.0   # 每高 1°C，太阳能效率 -1/200
ENGINE_TEMP_MIN_EFF = 0.35    # 效率下限（再热也不归零）
ENGINE_POWER_MIN_RATIO = 0.5  # 电网供电比例 ≥ 这个值引擎才工作（缺电不变轨）

# 太阳帆发射器没有配方输入，靠分拣器往里喂太阳帆；它把帆打到最空的那条轨道
# 轨道图面板里可以点轨道选"目标轨道"，否则自动选最空的

# 科技：需要哪种科研包 —— 一级（蓝）/ 二级（红）
TECH_PACK_ITEM = {
    "science_blue": I_SCIENCE_BLUE,
    "science_red": I_SCIENCE_RED,
}

# 科技树：id -> (名字, 需要多少个科研包, 前置科技, 解锁内容描述)
# 一级（蓝）是基础科技；二级（红）是戴森云时代的科技
TECH_TREE = {
    "logistics1": ("物流学 I", 5, (), "工业基础，无人机/传动前置"),
    "power1":     ("电力学 I", 10, (), "解锁太阳能板"),
    "circuit1":   ("电子学 I", 12, (), "解锁电路板配方"),
    "wind1":      ("风能 I", 14, ("power1",), "解锁风力涡轮"),
    "speed1":     ("传动学 I", 16, ("logistics1",), "传送带速度 +50%"),
    "drones1":    ("无人机 I", 24, ("logistics1",), "解锁物流塔"),
    "speed2":     ("传动学 II", 45, ("speed1",), "传送带速度再 +50%"),
    # --- 二级（红）科技：全部以蓝科技为前置 ---
    "dyson1":     ("戴森云 I", 20, ("power1",), "解锁太阳帆发射器"),
    "sail1":      ("太阳帆 I", 30, ("dyson1",), "太阳帆效率 +50%"),
    "dyson2":     ("戴森云 II", 60, ("dyson1", "speed1"), "解锁中轨 / 外轨"),
    "speed3":     ("传动学 III", 80, ("speed2", "dyson1"), "传送带速度再 +50%"),
    # --- 星际物流（M5b）：发射台 + 运输船 ---
    "interstellar1": ("星际物流 I", 40, ("drones1", "dyson1"),
                      "解锁发射台与运输船（行星间运货）"),
    # --- 行星工程（M6）：调整行星轨道 ---
    "engine1":    ("行星工程 I", 80, ("interstellar1", "dyson2"),
                   "解锁行星引擎：可调轨道半径与相位"),
}

# 科技解锁的建筑（未研究时底栏不显示/不能放）
# 建筑本身靠物品门槛 gating（缺料底栏显示红 0），科技只锁 3×3 大件里程碑
TECH_UNLOCK_BUILDING = {
    B_TOWER_SUPPLY: "drones1",
    B_TOWER_REQUEST: "drones1",
    B_EMITTER: "dyson1",
    B_LAUNCH_PAD: "interstellar1",
    B_PLANET_ENGINE: "engine1",
}

# 每个科技要吃的科研包配方 id。前 7 个吃一级电磁矩阵（蓝），
# 戴森云那几条吃二级能量矩阵（红）——科技门槛就是这么堆上去的。
TECH_PACK_RECIPE = {
    "logistics1": "science_blue",
    "power1": "science_blue",
    "circuit1": "science_blue",
    "wind1": "science_blue",
    "speed1": "science_blue",
    "drones1": "science_blue",
    "speed2": "science_blue",
    "dyson1": "science_red",
    "sail1": "science_red",
    "dyson2": "science_red",
    "speed3": "science_red",
    "interstellar1": "science_red",
    "engine1": "science_red",
}
