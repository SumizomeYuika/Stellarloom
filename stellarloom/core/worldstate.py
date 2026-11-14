"""行星世界状态（M5 星际最小版）：一颗行星的完整可玩状态。

一颗行星 = 独立 WorldGrid + 全套网络（带/机器/分拣器/塔/无人机/科研/电网）
+ 自己的 PlanetOrbit（相位起伏）+ 自己的相机（记住你上次看哪）。

M6.24 架构分层（类 Minecraft C/S）：
- WorldState 属于**服务器端**（sim）：全逻辑，不依赖 pygame。
- 渲染视图（ChunkRenderer 等）移出本类，由前端按行星并行持有。

恒星级/玩家级共享（不放这里）：
- TechTree：研究一次全星系生效
- DysonNetwork：戴森云绕恒星，帆群发电全局供给
- 玩家 inventory / 手搓队列 / 成就

sim 持有 worlds: list[WorldState] + world_index，
切换时把当前行星的组件赋回 sim 同名属性（见 Simulation.activate_world）。
"""

from __future__ import annotations

from .. import config as C
from ..logistics import BeltNetwork, DroneNetwork, InserterNetwork, TowerNetwork
from ..logistics.dyson import DysonNetwork
from ..logistics.pads import PadsNetwork
from ..power import PowerGrid
from ..production import ChestNetwork, MachineNetwork, MinerNetwork
from ..render.camera import Camera
from ..tech import LabNetwork, TechTree
from ..world import PlanetOrbit, WorldGrid
from ..world.planets import PlanetDef


class WorldState:
    def __init__(self, pdef: PlanetDef, tech: TechTree, dyson: DysonNetwork,
                 on_belts_changed):
        self.pdef = pdef
        self.name = pdef.name
        self.color = pdef.color
        self.desc = pdef.desc

        # 每颗行星自己的一盏太阳钟：轨道相位（光照起伏）+ 昼夜。
        # M6.31：按真实参数（半长轴/偏心率/近点辐角）建椭圆轨道；
        # 周期由开普勒第三定律自动算出，angle0 是初始平近点角。
        self.planet = PlanetOrbit(mean_angle=pdef.angle0,
                                  a_au=pdef.a_au,
                                  eccentricity=pdef.eccentricity,
                                  arg_peri=pdef.arg_peri)

        self.grid = WorldGrid(seed=pdef.seed)
        self.grid.on_belts_changed = on_belts_changed

        self.belts = BeltNetwork(self.grid)
        self.camera = Camera(self.grid.w * C.TILE, self.grid.h * C.TILE)
        self.machines = MachineNetwork(self.grid)
        self.miners = MinerNetwork(self.grid)
        self.chests = ChestNetwork(self.grid)
        self.inserters = InserterNetwork(self.grid, self.belts)
        self.inserters.chests = self.chests
        self.inserters.miners = self.miners
        self.power = PowerGrid(self.grid)
        self.power.planet = self.planet
        self.power.dyson = dyson
        self.towers = TowerNetwork(self.grid)
        self.drones = DroneNetwork(self.grid)
        self.pads = PadsNetwork(self.grid)   # M5b 星际物流：发射台
        self.labs = LabNetwork(self.grid)
        self.labs.bind(tech)
        self.inserters.labs = self.labs

        # 出生点核心：保证开局有电（殖民地玩家自带一台）
        self.core_pos: tuple[int, int] | None = None
        if pdef.has_core:
            cx, cy = self.grid.w // 2, self.grid.h // 2
            self.grid.place(cx, cy, C.B_CORE)
            self.core_pos = (cx, cy)