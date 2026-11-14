"""主循环：前端客户端（M6.24 架构分层后职责：渲染 + 输入 + UI）。

架构（类 Minecraft C/S，进程内）：
- stellarloom.sim.Simulation = 服务器端：全部游戏逻辑，headless 可跑。
- Game = 前端：读 sim 状态渲染、把输入翻译成 sim 指令、展示 sim 事件
  （toast/成就）、维护渲染态（chunks 缓存/面板/相机视图）。
- 输入同时支持键鼠与触屏：
  - 桌面：WASD 平移、滚轮缩放、左右键、数字键选建筑
  - 触屏：单指点按放置、单指拖拽平移（非建造）/连续放置（建造）、双指捏合缩放
- UI 由 TouchUI 绘制（顶栏 + 底栏），两套输入共用同一份状态。
"""

from __future__ import annotations

import math
import os

import numpy as np
import pygame

from .. import config as C
from ..input.gestures import DragEvent, PinchEvent, TapEvent
from ..input.gestures import GestureRecognizer
from ..input.touch import TouchState
from ..render import Camera
from ..render.fonts import FontBook
from ..render.layers import ChunkRenderer, arm_part_hidden, inserter_hand
from ..sim import Simulation
from ..ui.touch_ui import TouchUI
from ..ui.tower_panel import TowerPanel
from ..ui.pad_panel import PadPanel
from ..ui.engine_panel import EnginePanel
from ..ui.tech_panel import TechPanel
from ..ui.machine_panel import MachinePanel
from ..ui.craft_panel import BagPanel, CraftPanel
from ..ui.filter_panel import FilterPanel
from ..ui.storage_panel import StoragePanel
from ..ui.orbit_panel import OrbitPanel
from ..ui.lab_panel import LabPanel
from ..ui.save_panel import SavePanel
from ..ui.main_menu import MainMenu
from ..ui.achievement import AchievementPopup
from ..world import PlanetOrbit, WorldGrid
from .worldstate import WorldState
from ..world.planets import PLANETS


class Game:
    # M13：启动大步骤（加载界面总进度条的格数 = 这个清单长度）
    BOOT_STAGES = ["字体", "世界生成", "渲染视图", "界面面板",
                   "加载模组", "主菜单"]

    def __init__(self, screen, loader=None, mods_dir=None):
        # pygame 已在 main.py 里初始化好，这里只接手 screen。
        # M13：loader 是可选的 LoadingScreen；传 None 静默（自检/调试）。
        self._loader = loader
        self._mods_dir = mods_dir
        self.screen = screen
        pygame.display.set_caption(C.TITLE)
        self.clock = pygame.time.Clock()
        self._stage("字体")
        self.fonts = FontBook()
        if loader is not None:
            loader.attach_fonts(self.fonts)
        print(f"[字体] {'OK: ' + str(self.fonts.path) if self.fonts.ok else '未找到中文字体，回退默认'}")

        # M6.24：服务器端 Simulation 持有全部逻辑状态（世界/科技/戴森云/
        # 背包/手搓队列/存档）。前端只引用 + 渲染，改状态一律走 sim 指令。
        self._stage("世界生成")
        self.sim = Simulation()
        self.tech = self.sim.tech
        self.dyson = self.sim.dyson
        self.saves = self.sim.saves
        self.inventory = self.sim.inventory
        self.worlds = self.sim.worlds
        self.craft = self.sim.craft
        self.world_index = self.sim.world_index
        self._belts_dirty = False
        self._last_drag_cell: tuple[int, int] | None = None

        # 渲染视图：每行星一份 chunk 缓存（逻辑层不持有渲染对象）
        self._stage("渲染视图")
        self._chunk_views = [ChunkRenderer(ws.grid) for ws in self.worlds]

        # 输入
        self._stage("界面面板")
        self.gestures = GestureRecognizer()
        self.touch = TouchState()
        self.ui = TouchUI(screen.get_size(), self.fonts)
        self.ui.tech = self.tech
        self.tower_panel = TowerPanel(self.fonts)
        self.pad_panel = PadPanel(self.fonts)
        self.engine_panel = EnginePanel(self.fonts)
        self.tech_panel = TechPanel(self.fonts)
        self.machine_panel = MachinePanel(self.fonts)
        self.craft_panel = CraftPanel(self.fonts)
        self.bag_panel = BagPanel(self.fonts)
        self.filter_panel = FilterPanel(self.fonts)
        self.storage_panel = StoragePanel(self.fonts)
        self.orbit_panel = OrbitPanel(self.fonts)
        self.lab_panel = LabPanel(self.fonts)
        self.save_panel = SavePanel(self.fonts)
        self.current_slot = 0  # 多存档：F5 快速存档目标槽
        self.ach = AchievementPopup(self.fonts)

        # M6.28 窗口化：浮窗面板可拖标题栏移动（z 序从底到顶；
        # craft/tech 是全屏页，不参与窗口拖动）
        from ..ui.window import WindowMgr
        self.window_mgr = WindowMgr()
        self.panels = [self.orbit_panel, self.save_panel,
                       self.storage_panel, self.lab_panel, self.machine_panel,
                       self.tower_panel, self.pad_panel, self.engine_panel,
                       self.filter_panel,
                       self.bag_panel]

        # 星系视图（M6.32）：缩到最小后继续缩小攒的出界进度 0~1（粘性，不回落）
        self._zoom_pull = 0.0
        self._zoom_bar_rect = pygame.Rect(0, 0, 0, 0)

        # 主菜单（M6.25）：启动即进菜单，世界在背后已生成（暂停态背景）
        self.menu = MainMenu(self.fonts)
        # M6.28：模组管理页（主菜单「模组」入口，仿 minecraft）
        from ..ui.mods_panel import ModsPanel
        self.mods_panel = ModsPanel(self.fonts)

        # 手搓面板的队列接到服务器端同一条（材料扣/产都在 sim）
        self.craft_panel.queue = self.craft

        # 玩家状态（输入/交互，不属于服务器）
        self.selected_building = C.B_BELT
        self.belt_dir = 0
        self.running = True
        self.paused = False
        # 两点放置（传送带、分拣器）
        self.pending_start: tuple[int, int] | None = None

        # 自动存档计时（前端策略：调 sim 存）
        self._autosave_acc = 0.0
        self._autosave_interval = 120.0  # 秒
        self._toast = ""                 # 临时提示文字
        self._toast_t = 0.0

        # 帧耗时统计
        self._fps_smooth = 60.0

        # 渲染 sprite 缓存：预渲染小圆/三角，用 blit 替代上万次 draw.circle
        # 键：(item, r) -> Surface / (电量档, r) -> Surface
        self._item_sprites: dict[tuple[int, int], pygame.Surface] = {}
        self._drone_sprites: dict[tuple[str, int], pygame.Surface] = {}

        self._activate_world(0)

        # M6.27 MOD 支持：扫描 mods/ 加载（失败隔离，坏 mod 不影响游戏；
        # mixin 补丁只动内存，重载/卸载自动还原）
        # M13：加载界面按 mod 逐个报进度（load_all 的 progress 回调）
        self._stage("加载模组")
        from ..mod import load_mods

        def _mod_progress(name, i, n):
            if self._loader is not None:
                self._loader.step(f"模组 {name}（{i}/{n}）",
                                  i / max(n, 1))

        self.mod_mgr = load_mods(self, self._mods_dir,
                                 progress=_mod_progress)
        for name, err in self.mod_mgr.failed:
            self._toast_msg(f"mod {name} 加载失败：{err}", 3.5)

        self._stage("主菜单")
        self._open_menu()   # 启动即主菜单（世界暂停在背后）
        if self._loader is not None:
            self._loader.done()

    # ---------- M13：启动分步（加载界面） ----------

    def _stage(self, label: str):
        """进入下一个启动大步骤；无 loader 时静默。"""
        if self._loader is not None:
            self._loader.major(label)

    # ---------- 行星世界（M5 星际最小版）----------

    def _ensure_world(self, i: int):
        """要读档的行星不存在就按配置生成（存档可能含 PLANETS 之外更多行星）。

        逻辑侧由 sim.ensure_world 生成，前端只补渲染视图（chunk 缓存）。
        """
        self.sim.ensure_world(i)
        while len(self._chunk_views) < len(self.worlds):
            ws = self.worlds[len(self._chunk_views)]
            self._chunk_views.append(ChunkRenderer(ws.grid))

    def _activate_world(self, i: int):
        """切换当前行星：sim 侧激活逻辑，前端挂回渲染组件。"""
        if not (0 <= i < len(self.worlds)):
            return
        self.sim.activate_world(i)   # 逻辑组件 + belts_dirty 消费
        ws = self.worlds[i]
        self.world_index = i
        self.grid = ws.grid
        self.belts = ws.belts
        self.camera = ws.camera
        self.chunks = self._chunk_views[i]   # 渲染视图（逻辑层不持有）
        self.machines = ws.machines
        self.miners = ws.miners
        self.chests = ws.chests
        self.inserters = ws.inserters
        self.power = ws.power
        self.planet = ws.planet
        self.towers = ws.towers
        self.drones = ws.drones
        self.pads = ws.pads
        self.labs = ws.labs
        self.core_pos = ws.core_pos
        # 戴森云扫的是"当前行星"的发射器（帆是恒星级、跟人走）
        self.dyson.grid = ws.grid
        self.chunks.clear()

    def _switch_planet(self, i: int):
        """轨道面板点击行星圆点 -> 切换当前行星。"""
        if i == self.world_index or not (0 <= i < len(self.worlds)):
            return
        self._activate_world(i)
        # 面板内容跟行星绑定，全部关掉
        for panel in (self.tower_panel, self.machine_panel, self.tech_panel,
                      self.craft_panel, self.bag_panel, self.lab_panel,
                      self.storage_panel, self.orbit_panel, self.pad_panel,
                      self.engine_panel):
            panel.close()
        self.ui.orbit_open = self.ui.bag_open = self.ui.craft_open = False
        self.pending_start = None
        self._toast_msg(f"已抵达 {self.worlds[i].name}")

    # ---------- 主菜单（M6.25） ----------

    def _open_menu(self):
        """关掉所有面板，打开主菜单。菜单开着时手势被全面拦截、世界暂停。"""
        for panel in (self.tower_panel, self.machine_panel, self.tech_panel,
                      self.craft_panel, self.bag_panel, self.lab_panel,
                      self.storage_panel, self.orbit_panel,
                      self.filter_panel, self.save_panel, self.pad_panel,
                      self.engine_panel):
            panel.close()
        self.ui.orbit_open = self.ui.bag_open = self.ui.craft_open = False
        self.pending_start = None
        self.menu.show(self.screen.get_size(),
                       have_save=self.saves.latest_autosave() is not None)

    def _on_menu_action(self, action: str):
        """主菜单按钮分发：新游戏 / 继续 / 读档 / 退出。"""
        if action == "new":
            self.menu.close()
            self._start_new_game()
        elif action == "continue":
            name = self.saves.latest_autosave()
            self.menu.close()
            if name is None:
                self._toast_msg("没有自动存档")
                self._open_menu()
                return
            self._load_game(name, "自动存档")
        elif action == "load":
            self.menu.close()
            self._open_load_panel()
        elif action == "mods":
            # M6.28：模组管理页（仿 minecraft）
            self.menu.close()
            self.mods_panel.show(self.mod_mgr, self.screen.get_size())
        elif action == "quit":
            self.menu.close()
            self.running = False

    def _start_new_game(self):
        """全新开局：重建服务器端 sim，前端全部重挂。已存文件一律不动。"""
        self.sim = Simulation()
        self.sim.saves = self.saves   # 保留存档目录（只重置世界，不丢档）
        self.tech = self.sim.tech
        self.dyson = self.sim.dyson
        self.saves = self.sim.saves
        self.inventory = self.sim.inventory
        self.worlds = self.sim.worlds
        self.craft = self.sim.craft
        self.world_index = self.sim.world_index
        self._chunk_views = [ChunkRenderer(ws.grid) for ws in self.worlds]
        self.craft_panel.queue = self.craft
        # 交互状态复位
        self.selected_building = C.B_BELT
        self.belt_dir = 0
        self.pending_start = None
        self.ui.selected = C.B_BELT
        self.ui.remove_mode = False
        self.paused = False
        self.ui.paused = False
        self._autosave_acc = 0.0
        self._toast_t = 0.0
        self._activate_world(0)
        self._toast_msg("新游戏开始，去铺第一段传送带吧")

    # ---------- 主循环 ----------

    def run(self):
        while self.running:
            dt = min(self.clock.tick(C.FPS) / 1000.0, 0.1)
            self._events(dt)
            self._update(dt)
            self._draw()
        pygame.quit()

    # ---------- 事件 ----------

    def _events(self, dt: float):
        size = self.screen.get_size()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False

            # --- 触屏 ---
            elif e.type in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
                self.touch.note_touch()
                if e.type == pygame.FINGERUP:
                    self.window_mgr.end()   # M6.28：抬起结束窗口拖动
                if e.type == pygame.FINGERDOWN:
                    # M6.28：按下即抓（不等于"点击"——只有拖动才移动窗口）。
                    # 只抓浮窗面板的标题栏；菜单/模组页开着时面板都已关闭。
                    fpos = (int(e.x * size[0]), int(e.y * size[1]))
                    for p in reversed(self.panels):
                        if self.window_mgr.grab(p, fpos):
                            break
                for ev in self.gestures.handle(e, size):
                    self._handle_gesture(ev, dt)

            # --- 键鼠 ---
            elif e.type == pygame.KEYDOWN:
                self.touch.note_mouse()
                self._on_key(e.key)
            elif e.type == pygame.MOUSEBUTTONDOWN:
                # 触屏设备上 SDL 会把触摸模拟成鼠标事件，屏蔽掉（否则会双击）
                if getattr(e, "touch", False) or self.touch.ever_touched:
                    continue
                self.touch.note_mouse()
                # M6.28：鼠标左键点标题栏 = 开始拖窗口
                if e.button == 1:
                    for p in reversed(self.panels):
                        if self.window_mgr.grab(p, e.pos):
                            break
                self._on_mouse_down(e.button, e.pos)
            elif e.type == pygame.MOUSEBUTTONUP:
                self.touch.note_mouse()
                self.window_mgr.end()   # M6.28：松开结束窗口拖动
                if e.button == 4:
                    self._zoom_by(C.ZOOM_STEP, e.pos)
                elif e.button == 5:
                    self._zoom_by(1 / C.ZOOM_STEP, e.pos)
            elif e.type == pygame.MOUSEWHEEL:
                if self.menu.open:
                    continue  # 主菜单开着：滚轮不缩放世界
                # 手搓面板：滚轮滚动左侧产物列表
                if self.craft_panel.open:
                    self.craft_panel.scroll_by(-e.y * 3 * 22)
                    continue
                # 科技树全屏页：滚轮滚动列表，不缩放世界
                if self.tech_panel.open:
                    self.tech_panel.scroll_by(-e.y * 48)
                    continue
                mx, my = pygame.mouse.get_pos()
                # 星系视图开着：向上滚 = 放大 = 回地图；向下滚不做事
                if self.orbit_panel.open:
                    if e.y > 0:
                        self._exit_system_view()
                    continue
                # M6.23：其他面板开着时滚轮也不缩放世界（与拖动同规则）
                if (self.filter_panel.open or self.bag_panel.open
                        or self.save_panel.open
                        or self.storage_panel.open or self.lab_panel.open
                        or self.machine_panel.open or self.tower_panel.open
                        or self.pad_panel.open or self.engine_panel.open):
                    continue
                factor = C.ZOOM_STEP ** e.y
                self._zoom_by(factor, (mx, my))
            elif e.type == pygame.MOUSEMOTION:
                self.touch.note_mouse()
                # M6.28：拖窗口中 → 鼠标移动跟手
                if self.window_mgr.drag is not None:
                    self.window_mgr.move(e.pos, size)

    # ---------- 手势 ----------

    def _handle_gesture(self, ev, dt: float):
        if isinstance(ev, TapEvent):
            pos = (int(ev.pos[0]), int(ev.pos[1]))
            # 主菜单开了：只认菜单按钮，世界全部不响应
            if self.menu.open:
                action = self.menu.hit(pos)
                if action:
                    self._on_menu_action(action)
                return
            # M6.28：模组管理页（替代主菜单会话）
            if self.mods_panel.open:
                self.mods_panel.hit(pos)
                if not self.mods_panel.open:
                    # 返回主菜单
                    self._open_menu()
                return
            # M6.28：点中打开的窗口标题栏 → 开始拖动，本次点击被吃掉
            for p in reversed(self.panels):
                if self.window_mgr.grab(p, pos):
                    return
            # 星系视图进度条：点它也能进星系视图（触屏没有滚轮的兜底）
            if self._zoom_pull > 0.15 and self._zoom_bar_rect.collidepoint(pos):
                self._zoom_pull = 0.0
                self._apply_ui_action("orbit", None)
                return
            # 过滤面板优先吃点击
            if self.filter_panel.open:
                choice = self.filter_panel.hit(pos)
                if choice is not None and self.filter_panel.cell is not None:
                    cx, cy = self.filter_panel.cell
                    self.sim.set_overlay_filter(cx, cy, choice)
                    name = "不限" if choice <= 0 else C.ITEM_NAMES.get(choice, "?")
                    self._toast_msg(f"分拣器过滤 → {name}", 1.6)
                return
            # 手搓面板优先吃点击（返回 ("craft"/"cancel", rid, times)）
            if self.craft_panel.open:
                res = self.craft_panel.hit(pos)
                if res is not None:
                    self.craft_panel.refresh_inventory(self.inventory)
                    kind, rid, n = res
                    if kind == "craft":
                        self._toast_msg(f"手搓排队 {n} 个", 1.5)
                self.ui.craft_open = self.craft_panel.open
                return
            if self.bag_panel.open:
                self.bag_panel.hit(pos)
                self.ui.bag_open = self.bag_panel.open
                return
            # 科技面板打开时优先吃点击
            if self.tech_panel.open:
                self.tech_panel.hit(pos)
                return
            # 轨道图（M4）
            if self.orbit_panel.open:
                self.orbit_panel.hit(pos)
                self.ui.orbit_open = self.orbit_panel.open
                return
            # 多存档面板
            if self.save_panel.open:
                self.save_panel.hit(pos)
                return
            # 暂存面板（箱子/采矿机）优先吃点击
            if self.storage_panel.open:
                self.storage_panel.hit(pos)
                return
            # 科研站面板
            if self.lab_panel.open:
                self.lab_panel.hit(pos)
                return
            # 机器面板打开时优先吃点击
            if self.machine_panel.open:
                self.machine_panel.hit(pos)
                return
            # 塔面板打开时优先吃点击
            if self.tower_panel.open:
                self.tower_panel.hit(pos)
                return
            # 发射台面板（M5b）
            if self.pad_panel.open:
                self.pad_panel.hit(pos)
                return
            # 行星引擎面板（M6）
            if self.engine_panel.open:
                self.engine_panel.hit(pos)
                return
            hit = self.ui.hit(pos)
            if hit:
                self._apply_ui_action(*hit)
                return
            if self.ui.in_bars(pos):
                return
            gx, gy = self.mouse_grid(pos)
            # 点到已有塔/机器 → 开面板（仅当未选塔建筑放置时）
            if self.selected_building not in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST) \
                    and not self.ui.remove_mode:
                if self._try_open_panel(gx, gy):
                    return
            self._place_or_harvest(gx, gy, confirm_only=True)

        elif isinstance(ev, DragEvent):
            dx, dy = ev.delta
            if self.menu.open:
                return  # 主菜单开着：不拖世界
            # M6.28：拖窗口中 → 跟手移动（盖过滚列表/滚地图）
            if self.window_mgr.move(ev.current, self.screen.get_size()):
                return
            if self.craft_panel.open:
                # 手搓面板：拖动滚动左侧产物列表（触屏设备主要靠这个）
                self.craft_panel.scroll_by(-dy)
                return
            if self.bag_panel.open or self.filter_panel.open:
                return  # 面板开着别拖世界
            if self.tech_panel.open:
                # 科技树树状图：拖动 = 平移视图
                self.tech_panel.drag_by(dx, dy)
                return
            # M6.23：其余面板打开时拖动不许穿透到地图
            if (self.orbit_panel.open or self.save_panel.open
                    or self.storage_panel.open or self.lab_panel.open
                    or self.machine_panel.open or self.tower_panel.open
                    or self.pad_panel.open or self.engine_panel.open):
                return
            # 拖动只移动相机，不再放建筑（两点模式下放置靠点按）
            self.camera.x = (self.camera.x - dx / self.camera.zoom) % self.camera.world_pw
            self.camera.y = (self.camera.y - dy / self.camera.zoom) % self.camera.world_ph

        elif isinstance(ev, PinchEvent):
            # 星系视图开着：捏合放大 = 回地图
            if self.orbit_panel.open:
                if ev.factor > 1.0:
                    self._exit_system_view()
                return
            # M6.23：任何面板打开时都不让双指缩放世界（含手搓/科技）；
            # 主菜单开着时同规则
            if (self.menu.open or self.craft_panel.open or self.tech_panel.open
                    or self.filter_panel.open or self.bag_panel.open
                    or self.save_panel.open
                    or self.storage_panel.open or self.lab_panel.open
                    or self.machine_panel.open or self.tower_panel.open
                    or self.pad_panel.open or self.engine_panel.open):
                return
            self._zoom_by(ev.factor, (int(ev.center[0]), int(ev.center[1])))

    # ---------- 缩放 / 星系视图（M6.32） ----------

    def _zoom_by(self, factor: float, pos=None):
        """统一缩放入口：缩到最小后继续缩小 → 攒进度 → 进星系视图。

        factor < 1 是缩小（拉远），> 1 是放大。
        地图缩到 ZOOM_MIN 后，再继续缩小的量按 -ln(factor) 记进进度条；
        进度满 100% 打开星系视图（轨道/戴森面板）。
        """
        size = self.screen.get_size()
        if pos is None:
            pos = (size[0] // 2, size[1] // 2)
        # 星系视图开着：放大 = 回地图（不在这里缩放相机，保持进入前/最小缩放）
        if self.orbit_panel.open:
            if factor > 1.0:
                self._exit_system_view()
            return
        prev = self.camera.zoom
        self.camera.zoom_at(pos, factor, size)
        if factor < 1.0:
            at_min = (self.camera.zoom <= C.ZOOM_MIN + 1e-6
                      and prev <= C.ZOOM_MIN + 1e-6)
            if at_min:
                gain = max(C.ZOOM_PULL_MIN_STEP,
                           -math.log(factor) * C.ZOOM_PULL_RATE)
                self._zoom_pull = min(1.0, self._zoom_pull + gain)
                if self._zoom_pull >= 1.0 - 1e-9:
                    self._zoom_pull = 0.0
                    self._apply_ui_action("orbit", None)
        else:
            self._zoom_pull = 0.0

    def _exit_system_view(self):
        """星系视图放大 / ESC → 回到地图（保持进入前的缩放）。"""
        self.orbit_panel.close()
        self.ui.orbit_open = False
        self._zoom_pull = 0.0
        self.pending_start = None

    def _draw_zoom_hint(self):
        """屏幕顶部进度条：提示"继续缩小进入星系视图"。"""
        if self._zoom_pull <= 0.01 or self.orbit_panel.open:
            return
        sw = self.screen.get_width()
        w = int(min(320, sw * 0.44))
        h = 12
        x = (sw - w) // 2
        y = int(self.screen.get_height() * 0.075) + 8
        pygame.draw.rect(self.screen, (18, 24, 34), (x - 2, y - 2, w + 4, h + 4),
                         border_radius=6)
        pygame.draw.rect(self.screen, (44, 54, 70), (x, y, w, h), border_radius=4)
        fill = int(w * self._zoom_pull)
        if fill > 0:
            pygame.draw.rect(self.screen, (110, 200, 230), (x, y, fill, h),
                             border_radius=4)
        pct = int(round(self._zoom_pull * 100))
        txt = self.fonts.get(14).render(
            f"继续缩小进入星系视图  {pct}%（点这里也行）", True, (220, 235, 245))
        self.screen.blit(txt, (x + (w - txt.get_width()) // 2, y + h + 2))
        # 命中区：条 + 文字，方便触屏点
        self._zoom_bar_rect = pygame.Rect(
            x, y, w, h + 4 + txt.get_height())

    def _apply_ui_action(self, action: str, value):
        if action == "select":
            self.selected_building = value
            self.ui.selected = value
            self.ui.remove_mode = False
            self.pending_start = None  # 切建筑清状态
            # 底栏分类：选中建筑时自动展开它所在的大类
            self.ui.sync_open_category(value)
        elif action == "deselect":
            # 取消选择：未选中状态点按只移相机/开面板
            self.selected_building = None
            self.ui.selected = None
            self.pending_start = None
        elif action == "view":
            self.ui.view_mode = not self.ui.view_mode
            self.pending_start = None
        elif action == "tech":
            # 科技树是全屏独立页面，开时关掉其他面板
            self.tower_panel.close()
            self.machine_panel.close()
            self.craft_panel.close()
            self.bag_panel.close()
            self.lab_panel.close()
            self.ui.bag_open = self.ui.craft_open = False
            self.tech_panel.show(self.tech, self.screen.get_size())
        elif action == "orbit":
            # 轨道图（M4）：开时关掉其他大面板
            self.tower_panel.close()
            self.machine_panel.close()
            self.tech_panel.close()
            self.craft_panel.close()
            self.bag_panel.close()
            self.lab_panel.close()
            self.storage_panel.close()
            self.ui.bag_open = self.ui.craft_open = False
            self.orbit_panel.show(self.dyson, self.tech, self.worlds,
                                  self.world_index, self.screen.get_size(),
                                  self._switch_planet,
                                  fleet=getattr(self.sim, "fleet", None))
            self.ui.orbit_open = True
        elif action == "bag":
            self.bag_panel.show(self.screen.get_size(), self.inventory)
            self.ui.bag_open = self.bag_panel.open
        elif action == "craft":
            self.craft_panel.show(self.screen.get_size(), self.inventory)
            self.ui.craft_open = self.craft_panel.open
        elif action == "pause":
            self.paused = not self.paused
            self.ui.paused = self.paused
        elif action == "rotate":
            self.belt_dir = (self.belt_dir + 1) % 4
            self.ui.direction = self.belt_dir
        elif action == "remove":
            self.ui.remove_mode = not self.ui.remove_mode
        elif action == "save":
            self._open_save_panel()
        elif action == "load":
            self._open_load_panel()
        elif action == "menu":
            self._open_menu()
        # "noop" 是底栏展开/收起大类用的空动作：状态已在 TouchUI 里改完

    # ---------- 键鼠 ----------

    def _on_key(self, key: int):
        if self.menu.open:
            # 主菜单开着：只认 ESC（关菜单进游戏），其余键全部忽略
            if key == pygame.K_ESCAPE:
                self.menu.close()
            return
        if key == pygame.K_ESCAPE:
            if self.filter_panel.open:
                self.filter_panel.close()
            elif self.craft_panel.open:
                self.craft_panel.close()
                self.ui.craft_open = False
            elif self.bag_panel.open:
                self.bag_panel.close()
                self.ui.bag_open = False
            elif self.tech_panel.open:
                self.tech_panel.close()
            elif self.orbit_panel.open:
                self._exit_system_view()
            elif self.save_panel.open:
                self.save_panel.close()
            elif self.machine_panel.open:
                self.machine_panel.close()
            elif self.storage_panel.open:
                self.storage_panel.close()
            elif self.lab_panel.open:
                self.lab_panel.close()
            elif self.tower_panel.open:
                self.tower_panel.close()
            elif self.pad_panel.open:
                self.pad_panel.close()
            elif self.engine_panel.open:
                self.engine_panel.close()
            elif self.pending_start is not None:
                self.pending_start = None
            else:
                self.running = False
        elif key == pygame.K_1:
            self._apply_ui_action("select", C.B_BELT)
        elif key == pygame.K_2:
            self._apply_ui_action("select", C.B_INSERTER)
        elif key == pygame.K_3:
            self._apply_ui_action("select", C.B_MINER)
        elif key == pygame.K_4:
            self._apply_ui_action("select", C.B_FURNACE)
        elif key == pygame.K_5:
            self._apply_ui_action("select", C.B_ASSEMBLER)
        elif key == pygame.K_6:
            self._apply_ui_action("select", C.B_SOLAR)
        elif key == pygame.K_7:
            self._apply_ui_action("select", C.B_WIND)
        elif key == pygame.K_8:
            self._apply_ui_action("select", C.B_CHEST)
        elif key == pygame.K_9:
            self._apply_ui_action("select", C.B_TOWER_SUPPLY)
        elif key == pygame.K_0:
            self._apply_ui_action("select", C.B_TOWER_REQUEST)
        elif key == pygame.K_l:
            self._apply_ui_action("select", C.B_LAB)
        elif key == pygame.K_e:
            self._apply_ui_action("select", C.B_EMITTER)
        elif key == pygame.K_o:
            self._apply_ui_action("orbit", None)
        elif key == pygame.K_r:
            self._apply_ui_action("rotate", None)
        elif key == pygame.K_SPACE:
            self._apply_ui_action("pause", None)
        elif key == pygame.K_F5:
            self._quick_save()
        elif key == pygame.K_F9:
            self._open_load_panel()

    def _on_mouse_down(self, button: int, pos: tuple[int, int]):
        if self.tech_panel.open:
            self.tech_panel.hit(pos)
            return
        if self.orbit_panel.open:
            self.orbit_panel.hit(pos)
            self.ui.orbit_open = self.orbit_panel.open
            return
        if self.save_panel.open:
            self.save_panel.hit(pos)
            return
        if self.filter_panel.open:
            choice = self.filter_panel.hit(pos)
            if choice is not None and self.filter_panel.cell is not None:
                cx, cy = self.filter_panel.cell
                self.sim.set_overlay_filter(cx, cy, choice)
            return
        # 手搓面板：原来鼠标点击根本没走这里，点面板会穿透到世界去放建筑
        if self.craft_panel.open:
            res = self.craft_panel.hit(pos)
            if res is not None:
                self.craft_panel.refresh_inventory(self.inventory)
                kind, rid, n = res
                if kind == "craft":
                    self._toast_msg(f"手搓排队 {n} 个", 1.5)
            self.ui.craft_open = self.craft_panel.open
            return
        if self.bag_panel.open:
            self.bag_panel.hit(pos)
            self.ui.bag_open = self.bag_panel.open
            return
        if self.storage_panel.open:
            self.storage_panel.hit(pos)
            return
        if self.lab_panel.open:
            self.lab_panel.hit(pos)
            return
        if self.machine_panel.open:
            self.machine_panel.hit(pos)
            return
        if self.tower_panel.open:
            self.tower_panel.hit(pos)
            return
        hit = self.ui.hit(pos)
        if hit:
            self._apply_ui_action(*hit)
            return
        if self.ui.in_bars(pos):
            return
        gx, gy = self.mouse_grid(pos)
        if button == 1:
            # 点到已有塔/机器 → 开面板
            if self.selected_building not in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST) \
                    and not self.ui.remove_mode:
                if self._try_open_panel(gx, gy):
                    return
            self._place_or_harvest(gx, gy, confirm_only=True)
        elif button == 3:
            self._remove_or_mine(gx, gy)

    def _can_open_panel(self) -> bool:
        """当前是否允许"点已有建筑 → 开面板"。

        以下几种情况必须禁止，否则会把放置动作吃掉：
        - 拆除模式
        - 手上有两点式工具（分拣器）或正在两点放置中
        - 选中的就是塔（塔的点击是用来放/拆的）
        """
        if self.ui.remove_mode:
            return False
        if self.ui.view_mode:
            return True   # 查看模式就是专门用来点开面板的
        if self.pending_start is not None:
            return False
        if self.selected_building == C.B_INSERTER:
            return False
        if self.selected_building in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST):
            return False
        return True

    def _try_open_panel(self, gx: int, gy: int) -> bool:
        """优先开机器面板（更具体），其次塔面板。返回 True 表示开了。"""
        if not self._can_open_panel():
            return False
        # 分拣器（overlay）：开过滤面板。只允许查看模式，
        # 否则玩家手里拿着传送带想铺过分拣器格时会被这个面板吃掉点击。
        if self.ui.view_mode and self.grid.get_overlay(gx, gy) == C.B_INSERTER:
            self.filter_panel.show(self.screen.get_size(), (gx, gy),
                                   self.grid.get_overlay_filter(gx, gy))
            return True
        m = self.machines.get_machine(gx, gy)
        if m is not None:
            self.machine_panel.show(m, self.screen.get_size(), self.tech.researched,
                                    self.inventory)
            return True
        chest = self.chests.get(gx, gy)
        if chest is not None:
            self.storage_panel.show(self.screen.get_size(), "箱子", chest,
                                    C.CHEST_STACK, self.inventory)
            return True
        mn = self.miners.get(gx, gy)
        if mn is not None:
            self.storage_panel.show(self.screen.get_size(), "采矿机", mn,
                                    C.MINER_BUFFER_CAP, self.inventory,
                                    total_cap=C.MINER_BUFFER_CAP)
            return True
        em = self.dyson.get(gx, gy)
        if em is not None:
            self.storage_panel.show(self.screen.get_size(), "太阳帆发射器", em,
                                    C.DYSON_EMITTER_STORE_CAP, self.inventory,
                                    allowed={C.I_SOLAR_SAIL})
            return True
        # 科研站（M6.11）：点开双模式面板
        lab = self.labs.get_lab(gx, gy)
        if lab is not None:
            self.lab_panel.show(lab, self.labs, gx, gy,
                                self.screen.get_size(), self.inventory)
            return True
        tw = self.towers.get_tower(gx, gy)
        if tw is not None:
            self.tower_panel.show(tw, self.screen.get_size())
            return True
        # 发射台（M5b）
        pad = self.pads.get_pad(gx, gy)
        if pad is not None:
            self.pad_panel.show(pad, self.sim, self.screen.get_size())
            return True
        # 行星引擎（M6）：点 3×3 任意格开变轨面板
        eng = self.sim.engine_at(gx, gy)
        if eng is not None:
            self.engine_panel.show(eng, self.sim, self.screen.get_size())
            return True
        return False

    # ---------- 物品栏 / 建造花费 ----------

    def _count(self, item: int) -> int:
        """物品数量（转发服务器端背包）。"""
        return self.sim._count(item)

    def _do_craft(self, rid: str, times: int) -> int:
        """把手搓任务排进队列，返回实际排进去的次数（材料不够会少排）。

        手搓不是瞬时的：每做一个花配方的 dur 秒，由 sim.step 推进。
        材料在排队时就扣掉，这样玩家不能靠连点无限刷。
        """
        self.craft_panel.refresh_inventory(self.inventory)
        return self.sim.do_craft(rid, times)

    # ---------- 世界操作 ----------

    def _place_or_harvest(self, gx: int, gy: int, confirm_only: bool):
        if self.ui.remove_mode:
            self._remove_or_mine(gx, gy)
            return

        # 查看模式或未选建筑：只开面板，不放置
        if self.ui.view_mode or self.selected_building is None:
            self._try_open_panel(gx, gy)
            return

        # 未选塔/发射台/引擎时，点已有塔/机器 → 开面板（不触发放置）
        if self.selected_building not in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST,
                                          C.B_LAUNCH_PAD, C.B_PLANET_ENGINE):
            if self._try_open_panel(gx, gy):
                return

        # 科技锁定：未研究的建筑不能放
        if not self.tech.is_unlocked(self.selected_building):
            self.pending_start = None
            return

        if self.selected_building == C.B_BELT:
            self._place_belt_two_point(gx, gy)
        elif self.selected_building == C.B_INSERTER:
            self._place_inserter_two_point(gx, gy)
        elif self.selected_building in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST):
            # 塔：单击放 3×3，只记中心格（规则在服务器端）
            self.sim.place_tower(self.selected_building, gx, gy, self.belt_dir)
            self.pending_start = None
        elif self.selected_building == C.B_LAUNCH_PAD:
            # 发射台：单击放 3×3，放下后直接开面板配置目标/模式
            if self.sim.place_pad(self.selected_building, gx, gy,
                                  self.belt_dir) == "ok":
                self._try_open_panel(gx, gy)
            self.pending_start = None
        elif self.selected_building == C.B_PLANET_ENGINE:
            # 行星引擎：单击放 3×3，放下后直接开变轨面板
            if self.sim.place_engine(gx, gy, self.belt_dir) == "ok":
                self._try_open_panel(gx, gy)
            self.pending_start = None
        else:
            # 其他建筑（采矿机、熔炉、制造台、太阳能、风力、箱子）：单击直接放
            r = self.sim.place_building(self.selected_building, gx, gy,
                                        self.belt_dir)
            if r == "ok" and self.selected_building in (
                    C.B_FURNACE, C.B_ASSEMBLER, C.B_CHEST, C.B_MINER):
                # 服务器已 sync 好网络，前端现场开面板
                self._try_open_panel(gx, gy)
            self.pending_start = None

    # ---------- 两点式放置 ----------

    def _place_belt_two_point(self, gx: int, gy: int):
        """第一击=起点，第二击=终点，自动铺直线。"""
        if self.pending_start is None:
            self.pending_start = (gx, gy)
            return
        sx, sy = self.pending_start
        ex, ey = gx, gy
        self.pending_start = None
        self._lay_belt_line(sx, sy, ex, ey)

    def _lay_belt_line(self, sx: int, sy: int, ex: int, ey: int):
        """从 (sx,sy) 到 (ex,ey) 铺 L 形传送带（规则在服务器端）。"""
        self.sim.lay_belt_line(sx, sy, ex, ey, self.belt_dir)

    def _place_inserter_two_point(self, gx: int, gy: int):
        """第一击=源（输出方），第二击=目标。
        源和目标必须隔一格（曼哈顿距离 2 且直线），分拣器放中间格。
        分拣器朝向=从源指向目标，背后抓源、前面送目标。
        分拣器是 overlay，可以直接叠在传送带上，不切断带子。
        """
        if self.pending_start is None:
            self.pending_start = (gx, gy)
            return
        sx, sy = self.pending_start
        tx, ty = gx, gy
        self.pending_start = None

        dx = tx - sx
        dy = ty - sy
        # 必须直线且距离 2
        if dx == 0 and abs(dy) == 2:
            d = 1 if dy > 0 else 3
        elif dy == 0 and abs(dx) == 2:
            d = 0 if dx > 0 else 2
        else:
            return  # 不符合条件，忽略

        # 分拣器放中间格（overlay，不与传送带冲突）；规则在服务器端
        mx, my = sx + C.DX[d], sy + C.DY[d]
        self.sim.place_inserter(mx, my, d)

    def _remove_or_mine(self, gx: int, gy: int):
        """拆除/开采格子（含容器退货等规则）——全在服务器端。"""
        self.sim.remove_building(gx, gy)

    # ---------- 更新 ----------

    def _update(self, dt: float):
        self._pan_by_keys(dt)
        # 成就弹窗靠每帧动画，暂停也继续走
        self.ach.update(dt)
        if not self.paused and not self.menu.open and not self.mods_panel.open:
            # M6.24：全部模拟推进在服务器端（含传送带重建/网络 sync）
            self.sim.step(dt)
            # mod 钩子：on_step 在步进后、事件收集前
            self.mod_mgr.step(dt)
            # 服务器事件 → 前端展示
            for ev in self.sim.pop_events():
                self.mod_mgr.emit(ev)      # M6.27：mod 订阅事件流
                if ev[0] == "toast":
                    self._toast_msg(ev[1], ev[2])
                elif ev[0] == "achievement":
                    self.ach.push(ev[1], ev[2])
            # 服务器标记的脏格子 → 刷新 chunk 缓存
            for cx, cy in self.sim.take_dirty_cells():
                self.chunks.invalidate_cell(cx, cy)
            # 自动存档（前端策略）
            self._autosave_acc += dt
            if self._autosave_acc >= self._autosave_interval:
                self._autosave_acc = 0.0
                self._do_save(auto=True)
        # toast 倒计时
        if self._toast_t > 0:
            self._toast_t -= dt
        # 平滑 FPS 显示
        inst = self.clock.get_fps()
        if inst > 0:
            self._fps_smooth += (inst - self._fps_smooth) * 0.1

    def _pan_by_keys(self, dt: float):
        keys = pygame.key.get_pressed()
        if any(keys[k] for k in (pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
                                 pygame.K_UP, pygame.K_DOWN,
                                 pygame.K_LEFT, pygame.K_RIGHT)):
            self.camera.pan(keys, dt)

    # ---------- 存档 ----------

    def _toast_msg(self, text: str, secs: float = 2.0):
        self._toast = text
        self._toast_t = secs

    def _do_save(self, auto: bool = False):
        """自动存档（多存档 M6.20 后：手动存档走存档面板）。"""
        try:
            path = self.saves.save_auto(self.sim)
            self._toast_msg(f"自动存档: {os.path.basename(path)}")
            print(f"[存档] {path}")
        except Exception as e:
            self._toast_msg(f"存档失败: {e}", 3.0)
            print(f"[存档失败] {e}")

    def _quick_save(self):
        """F5：立刻存到当前槽（不弹面板）。"""
        try:
            name = self.saves.slot_file(self.current_slot)
            path = self.saves.save(self.sim, name)
            size = os.path.getsize(path) // 1024
            self._toast_msg(
                f"已存到 {self.saves.slot_label(self.current_slot)} ({size} KB)")
            print(f"[快速存档] {path}")
        except Exception as e:
            self._toast_msg(f"存档失败: {e}", 3.0)
            print(f"[存档失败] {e}")

    def _open_save_panel(self):
        self.tower_panel.close()
        self.pad_panel.close()
        self.machine_panel.close()
        self.tech_panel.close()
        self.craft_panel.close()
        self.bag_panel.close()
        self.lab_panel.close()
        self.storage_panel.close()
        self.ui.bag_open = self.ui.craft_open = False
        self.save_panel.show(self.screen.get_size(), "save",
                             self.saves.slot_list(), self.current_slot,
                             self._save_slot)

    def _open_load_panel(self):
        self.tower_panel.close()
        self.pad_panel.close()
        self.machine_panel.close()
        self.tech_panel.close()
        self.craft_panel.close()
        self.bag_panel.close()
        self.lab_panel.close()
        self.storage_panel.close()
        self.ui.bag_open = self.ui.craft_open = False
        self.save_panel.show(self.screen.get_size(), "load",
                             self.saves.slot_list(), self.current_slot,
                             self._load_slot)

    def _save_slot(self, i: int):
        try:
            name = self.saves.slot_file(i)
            self.saves.save(self.sim, name)
            self.current_slot = i
            self._toast_msg(f"已存到 {self.saves.slot_label(i)}")
            print(f"[存档] {self.saves.slot_file(i)}")
        except Exception as e:
            self._toast_msg(f"存档失败: {e}", 3.0)
            print(f"[存档失败] {e}")
        finally:
            self.save_panel.close()

    def _load_slot(self, i: int):
        # i == -1 读最新自动存档（SavePanel 底部按钮）；i == -2 读旧档 save.slm
        if i == -1:
            name = self.saves.latest_autosave()
            if name is None:
                self._toast_msg("没有自动存档")
                return
            self._load_game(name, "自动存档")
            return
        if i == -2:
            if self.saves.exists("save.slm"):
                self._load_game("save.slm", "旧档")
            else:
                self._toast_msg("没有旧档文件")
            return
        name = self.saves.slot_file(i)
        if not self.saves.exists(name):
            self._toast_msg("这个槽位是空的")
            return
        self._load_game(name)
        self.current_slot = i
        self.save_panel.close()

    def _load_game(self, name: str, label: str | None = None):
        """按名字读档 + 收尾（槽位面板与自动档共用）。"""
        try:
            if not self.saves.exists(name):
                self._toast_msg("没有这个存档")
                return
            # 存档解到服务器端（sim 负责确保行星/激活逻辑）
            self.saves.load(self.sim, name)
            # 前端重新挂载组件 + 补齐并清空渲染视图
            self._ensure_world(self.sim.world_index)
            self._activate_world(self.sim.world_index)
            for ch in self._chunk_views:
                ch.clear()
            # 读档后世界全变了，面板里的旧塔引用作废
            self.tower_panel.close()
            self.pad_panel.close()
            self.machine_panel.close()
            self.tech_panel.close()
            self.craft_panel.close()
            self.bag_panel.close()
            self.lab_panel.close()
            self.ui.bag_open = self.ui.craft_open = False
            self.pending_start = None
            self._last_drag_cell = None
            self._belts_dirty = False
            # 存档里的科技进度可能退回到没解锁当前选中建筑
            if self.selected_building is not None and \
                    not self.tech.is_unlocked(self.selected_building):
                self._apply_ui_action("select", C.B_BELT)
            self._toast_msg(f"已读档 {label if label else name}")
            print(f"[读档] 成功 {name}")
        except Exception as e:
            self._toast_msg(f"读档失败: {e}", 3.0)
            print(f"[读档失败] {e}")

    # ---------- 渲染 ----------

    def _draw(self):
        # 星系视图是全屏界面：整屏切走，不画地表/UI（M6.32）
        if self.orbit_panel.open:
            self.orbit_panel.draw(self.screen)
            pygame.display.flip()   # 必须翻页：早退跳过了下面的 flip 会冻屏
            return
        self.screen.fill(C.C_BG)
        self.chunks.draw(self.screen, self.camera)
        self._draw_items()
        self._draw_inserters()
        self._draw_machine_status()
        self._draw_drones()
        self._draw_ghost()
        self._draw_ui()
        self._draw_zoom_hint()
        if self.tower_panel.open:
            self.tower_panel.draw(self.screen)
        if self.pad_panel.open:
            self.pad_panel.draw(self.screen)
        if self.engine_panel.open:
            self.engine_panel.draw(self.screen)
        if self.machine_panel.open:
            self.machine_panel.draw(self.screen)
        if self.storage_panel.open:
            self.storage_panel.draw(self.screen)
        if self.bag_panel.open:
            self.bag_panel.draw(self.screen)
        if self.craft_panel.open:
            self.craft_panel.draw(self.screen)
        if self.filter_panel.open:
            self.filter_panel.draw(self.screen)
        if self.tech_panel.open:
            self.tech_panel.draw(self.screen)
        if self.save_panel.open:
            self.save_panel.draw(self.screen)
        if self.lab_panel.open:
            self.lab_panel.draw(self.screen)
        if self.menu.open:
            # 主菜单永远画在最上层（半透明遮罩 + 按钮）
            self.menu.draw(self.screen)
        if self.mods_panel.open:
            # M6.28：模组管理页（遮罩页，主菜单之上）
            self.mods_panel.draw(self.screen)
        self.ach.draw(self.screen)
        pygame.display.flip()

    def _draw_items(self):
        """传送带上的物品：numpy 批量换算屏幕坐标 + 过滤可见，只画可见的。

        之前逐物品调 world_to_screen + 逐格 draw.circle，3 万物品时 Python 循环
        和函数调用是渲染大头。现在每条 lane 一次向量化变换 + 可见掩码，
        Python 循环只跑落在屏内的物品；圆点用预渲染 sprite blit。
        """
        size = self.screen.get_size()
        sw, sh = size
        r = max(int(self.camera.tile_px * 0.22), 1)
        cam = self.camera
        wpw, wph = cam.world_pw, cam.world_ph
        tp = cam.tile_px  # 整数格子像素，与 camera/ChunkRenderer 同式
        scale = tp / C.TILE
        half_w, half_h = sw / 2.0, sh / 2.0
        cx, cy = cam.x, cam.y
        cache = self._item_sprites
        g = self.grid
        tpx = C.TILE
        for lane in self.belts.lanes:
            n = len(lane.positions)
            if n == 0:
                continue
            x0, y0 = lane.cells[0]
            d = int(g.direction[y0, x0])
            dx, dy = C.DX[d], C.DY[d]
            pos = lane.positions
            if dx:
                wx = (x0 + 0.5 + dx * pos) * tpx
                wy = np.full(n, (y0 + 0.5) * tpx, dtype=np.float32)
            else:
                wy = (y0 + 0.5 + dy * pos) * tpx
                wx = np.full(n, (x0 + 0.5) * tpx, dtype=np.float32)
            # 相机偏移：与 world_to_screen 同样取最近路径
            ddx = (wx - cx) % wpw
            ddy = (wy - cy) % wph
            if wpw > 0:
                big = ddx > wpw / 2
                ddx[big] -= wpw
                big = ddy > wph / 2
                ddy[big] -= wph
            sx = half_w + ddx * scale
            sy = half_h + ddy * scale
            vis = (sx > -8) & (sx < sw + 8) & (sy > -8) & (sy < sh + 8)
            if not vis.any():
                continue
            items = lane.items
            for i in np.nonzero(vis)[0]:
                item = int(items[i])
                key = (item, r)
                spr = cache.get(key)
                if spr is None:
                    color = C.ITEM_COLORS.get(item, C.C_ITEM)
                    spr = pygame.Surface((r * 2 + 2, r * 2 + 2),
                                         pygame.SRCALPHA)
                    pygame.draw.circle(spr, color, (r + 1, r + 1), r)
                    cache[key] = spr
                self.screen.blit(spr, (int(sx[i]) - r - 1, int(sy[i]) - r - 1))

    def _arm_part_hidden(self, gx: int, gy: int) -> bool:
        """分拣器头/尾所在格是机器（非空且非带）时，那一段不画。"""
        return arm_part_hidden(int(self.grid.get(gx, gy)))

    def _draw_inserters(self):
        """分拣器三段式机械臂（M10，纯视觉）：尾（来源格）→连接部→头（目标格）。

        底座板由 chunk 静态层画；这里每帧画臂、头和手上的物品，
        传送带/机器不被整格色块盖住。缩放太小（<6px/格）时省略，只看底座板。
        """
        tp = self.camera.tile_px
        if tp < 6:
            return
        g = self.grid
        size = self.screen.get_size()
        sw, sh = size
        margin = tp * 1.5
        arm_w = max(2, int(tp * 0.10))
        dark = (110, 82, 18)
        metal = (232, 198, 96)
        ins = self.sim.inserters
        for x, y in ins.cells:
            d = int(g.overlay_dir[y, x])
            bcx, bcy = self.camera.world_to_screen(
                (x + 0.5) * C.TILE, (y + 0.5) * C.TILE, size)
            if not (-margin <= bcx <= sw + margin
                    and -margin <= bcy <= sh + margin):
                continue
            sx, sy = g.wrap(x - C.DX[d], y - C.DY[d])
            tx, ty = g.wrap(x + C.DX[d], y + C.DY[d])
            scx, scy = self.camera.world_to_screen(
                (sx + 0.5) * C.TILE, (sy + 0.5) * C.TILE, size)
            tcx, tcy = self.camera.world_to_screen(
                (tx + 0.5) * C.TILE, (ty + 0.5) * C.TILE, size)
            src_hide = self._arm_part_hidden(sx, sy)
            tgt_hide = self._arm_part_hidden(tx, ty)

            # 动画阶段：0 停在来源，1 伸到目标（去程带货，回程空手）
            rem = ins.anim.get((x, y), 0.0)
            phase = 0.0
            if rem > 0:
                half = C.INSERTER_SWING_TIME
                phase = 1.0 - abs(rem - half) / half
            hx, hy = inserter_hand((scx, scy), (tcx, tcy), phase)
            if tgt_hide:
                hx, hy = bcx, bcy   # 目标格是机器：手缩回机体，不画到机器上

            # 尾部（来源格底座 + 轴）
            if not src_hide:
                r = max(2, int(tp * 0.14))
                pygame.draw.circle(self.screen, dark, (int(scx), int(scy)), r)
                pygame.draw.circle(self.screen, metal, (int(scx), int(scy)),
                                   max(1, r - 1), 1)
            # 连接部（臂）
            pygame.draw.line(self.screen, dark, (scx, scy), (hx, hy),
                             arm_w + 2)
            pygame.draw.line(self.screen, metal, (scx, scy), (hx, hy), arm_w)
            # 机体转轴
            rr = max(2, int(tp * 0.09))
            pygame.draw.circle(self.screen, dark, (int(bcx), int(bcy)), rr)
            # 头部（抓手）
            if not tgt_hide:
                hr = max(2, int(tp * 0.13))
                pygame.draw.circle(self.screen, dark, (int(hx), int(hy)), hr)
                pygame.draw.circle(self.screen, metal, (int(hx), int(hy)),
                                   hr, max(1, arm_w // 2))
                carry = ins.carry.get((x, y))
                if carry is not None:
                    col = C.ITEM_COLORS.get(carry, (255, 255, 255))
                    s2 = max(3, int(tp * 0.22))
                    pygame.draw.rect(self.screen, col,
                                     (int(hx) - s2 // 2, int(hy) - s2 // 2,
                                      s2, s2))

    def _draw_machine_status(self):
        """机器工作指示灯 + 分拣器朝向箭头 + 输出物品。"""
        size = self.screen.get_size()
        sw, sh = size
        tpx = self.camera.tile_px
        if tpx < 6:
            return

        # 机器状态
        for (mx, my), m in self.machines.machines.items():
            sx, sy = self.camera.world_to_screen(mx * C.TILE, my * C.TILE, size)
            if not (-tpx < sx < sw + tpx and -tpx < sy < sh + tpx):
                continue
            if m.progress > 0:
                # 工作中：右下角绿点
                r = max(int(tpx * 0.12), 2)
                pygame.draw.circle(self.screen, (80, 220, 80),
                                   (int(sx + tpx * 0.75), int(sy + tpx * 0.75)), r)
                # 进度条
                if m.recipe_id:
                    _, _, dur, _ = C.RECIPES[m.recipe_id]
                    frac = min(m.progress / dur, 1.0) if dur > 0 else 0
                    bar_w = int(tpx * frac)
                    if bar_w > 0:
                        pygame.draw.rect(self.screen, (80, 220, 80),
                                         (int(sx), int(sy + tpx - 3), bar_w, 3))
            out_item = m.peek_output()
            if out_item is not None:
                # 产物槽有东西：左上角画小圆
                r = max(int(tpx * 0.15), 2)
                color = C.ITEM_COLORS.get(out_item, C.C_ITEM)
                pygame.draw.circle(self.screen, color,
                                   (int(sx + tpx * 0.25), int(sy + tpx * 0.25)), r)
            if m.recipe_id is None:
                # 空壳机器：画个灰色问号方块，提示还没设配方
                r = max(int(tpx * 0.16), 3)
                pygame.draw.rect(self.screen, (120, 120, 135),
                                 (int(sx + tpx * 0.5 - r), int(sy + tpx * 0.5 - r),
                                  r * 2, r * 2), 1)

        # 分拣器朝向箭头（用缓存的坐标集合，不再每帧扫 overlay 数组）
        g = self.grid
        for x, y in self.inserters.cells:
            sx, sy = self.camera.world_to_screen(x * C.TILE, y * C.TILE, size)
            if not (-tpx < sx < sw + tpx and -tpx < sy < sh + tpx):
                continue
            d = int(g.overlay_dir[y, x])
            cx = sx + tpx / 2
            cy = sy + tpx / 2
            t = max(int(tpx * 0.2), 2)
            # 箭头：空心三角，黄色
            if d == 0:
                pts = [(cx + t, cy), (cx - t, cy - t), (cx - t, cy + t)]
            elif d == 2:
                pts = [(cx - t, cy), (cx + t, cy - t), (cx + t, cy + t)]
            elif d == 1:
                pts = [(cx, cy + t), (cx - t, cy - t), (cx + t, cy - t)]
            else:
                pts = [(cx, cy - t), (cx - t, cy + t), (cx + t, cy + t)]
            pygame.draw.polygon(self.screen, (255, 230, 100), pts, 2)

    def _draw_drones(self):
        """无人机：预渲染三角 sprite 按电量着色，blit 替代逐台 polygon。"""
        size = self.screen.get_size()
        sw, sh = size
        tpx = self.camera.tile_px
        if tpx < 4:
            return
        r = max(int(tpx * 0.25), 3)
        cache = self._drone_sprites
        for d in self.drones.drones:
            sx, sy = self.camera.world_to_screen(d.x * C.TILE, d.y * C.TILE, size)
            if not (-r < sx < sw + r and -r < sy < sh + r):
                continue
            # 电量配色：满电绿 → 半电黄 → 低电红
            e = d.energy_ratio
            if e > 0.5:
                key = "hi"
                color = (80, 220, 80)
            elif e > 0.2:
                key = "mid"
                color = (230, 200, 60)
            else:
                key = "lo"
                color = (220, 80, 60)
            spr = cache.get((key, r))
            if spr is None:
                r2 = r + 1
                spr = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
                # 简化：三角全部朝上（和以前一致）
                pygame.draw.polygon(
                    spr, color,
                    [(r2, r2 - r), (r2 - int(r * 0.8), r2 + int(r * 0.7)),
                     (r2 + int(r * 0.8), r2 + int(r * 0.7))])
                cache[(key, r)] = spr
            self.screen.blit(spr, (int(sx) - r - 1, int(sy) - r - 1))
            # 载货指示：中心小点
            if d.cargo is not None:
                cargo_color = C.ITEM_COLORS.get(d.cargo, (255, 255, 255))
                pygame.draw.circle(self.screen, cargo_color,
                                   (int(sx), int(sy)), max(r // 3, 1))

    def _draw_ghost(self):
        # 未选建筑或查看模式下不画 ghost
        if self.selected_building is None or self.ui.view_mode:
            return
        pos = self._cursor_pos()
        if self.ui.in_bars(pos):
            return
        gx, gy = self.mouse_grid(pos)
        size = self.screen.get_size()
        tpx = self.camera.tile_px
        sx, sy = self.camera.world_to_screen(gx * C.TILE, gy * C.TILE, size)

        # 预览线：传送带/分拣器的两点放置
        if self.pending_start is not None:
            px0, py0 = self.pending_start
            sx0, sy0 = self.camera.world_to_screen(
                px0 * C.TILE + C.TILE / 2, py0 * C.TILE + C.TILE / 2, size)
            sx1, sy1 = self.camera.world_to_screen(
                gx * C.TILE + C.TILE / 2, gy * C.TILE + C.TILE / 2, size)
            pygame.draw.line(self.screen, C.C_SELECT,
                             (int(sx0), int(sy0)), (int(sx1), int(sy1)), 2)
            # 起点高亮
            rect0 = pygame.Rect(int(sx0 - tpx / 2), int(sy0 - tpx / 2),
                                int(tpx), int(tpx))
            pygame.draw.rect(self.screen, C.C_SELECT, rect0, 2)

        # 塔/发射台/引擎：3×3 ghost 预览
        if self.selected_building in (C.B_TOWER_SUPPLY, C.B_TOWER_REQUEST):
            ok = self.towers.can_place(gx, gy)
            color = C.C_GHOST_BAD if self.ui.remove_mode else (
                C.C_GHOST_OK if ok else C.C_GHOST_BAD)
            big = pygame.Rect(int(sx - tpx), int(sy - tpx), int(tpx * 3), int(tpx * 3))
            pygame.draw.rect(self.screen, color, big, 2)
            return
        if self.selected_building in (C.B_LAUNCH_PAD, C.B_PLANET_ENGINE):
            ok = self.pads.can_place(gx, gy)
            color = C.C_GHOST_BAD if self.ui.remove_mode else (
                C.C_GHOST_OK if ok else C.C_GHOST_BAD)
            big = pygame.Rect(int(sx - tpx), int(sy - tpx), int(tpx * 3), int(tpx * 3))
            pygame.draw.rect(self.screen, color, big, 2)
            return

        ok = self.grid.can_place(gx, gy)
        if self.ui.remove_mode:
            color = C.C_GHOST_BAD
        elif self.pending_start is not None:
            # 分拣器第二点：中间格预览（overlay，允许叠在带子上）
            if self.selected_building == C.B_INSERTER:
                sx0, sy0 = self.pending_start
                ddx, ddy = gx - sx0, gy - sy0
                if (ddx == 0 and abs(ddy) == 2) or (ddy == 0 and abs(ddx) == 2):
                    d = 0 if ddx == 2 else (2 if ddx == -2 else (1 if ddy == 2 else 3))
                    mx, my = sx0 + C.DX[d], sy0 + C.DY[d]
                    msx, msy = self.camera.world_to_screen(
                        mx * C.TILE, my * C.TILE, size)
                    mrect = pygame.Rect(int(msx), int(msy), int(tpx), int(tpx))
                    can = self.grid.get_overlay(mx, my) == C.B_EMPTY
                    pygame.draw.rect(
                        self.screen, C.C_GHOST_OK if can else C.C_GHOST_BAD,
                        mrect, 2)
                    return
            color = C.C_SELECT
        else:
            color = C.C_GHOST_OK if ok else C.C_GHOST_BAD
        rect = pygame.Rect(int(sx), int(sy), int(tpx), int(tpx))
        pygame.draw.rect(self.screen, color, rect, 2)

    def _draw_ui(self):
        day_mark = "☀" if self.power.is_day else "☾"
        stats = (f"行星 {self.worlds[self.world_index].name} | "
                 f"FPS {self._fps_smooth:.0f} | 物品 {self.belts.item_count} | "
                 f"铁板 {self._count(C.I_IRON_PLATE)} 齿轮 {self._count(C.I_GEAR)} | "
                 f"机 {self.drones.busy_count}/{self.drones.count} | "
                 f"{self.tech.status_text()} | {self.power.status_text()} {day_mark}")
        dy = self.dyson.status_text()
        if dy:
            stats += " | " + dy
        stats += " | " + self.planet.status_text()
        # 行星工程（M6）：有引擎时显示当前轨道倍率（通电才可变轨）
        if self.sim.has_engine():
            stats += (f" | 轨道 ×{self.sim.orbit_ratio():.2f}"
                      + ("" if self.sim.engine_powered() else "（缺电）"))
        if self.ui.view_mode:
            stats += " | [查看]"
        elif self.selected_building is None:
            stats += " | 未选建筑"
        if self.pending_start is not None:
            stats += " | 选第二点"
        self.ui.stock = self.inventory   # 底栏按钮显示库存角标
        self.ui.draw(self.screen, stats)
        if self._toast_t > 0 and self._toast:
            font = self.fonts.get(22) or self.fonts.get(20)
            surf = font.render(self._toast, True, (255, 255, 255))
            pad = 10
            w = surf.get_width() + pad * 2
            h = surf.get_height() + pad
            box = pygame.Surface((w, h), pygame.SRCALPHA)
            box.fill((20, 24, 34, 220))
            pygame.draw.rect(box, (110, 150, 200), box.get_rect(), 1, border_radius=6)
            box.blit(surf, (pad, pad // 2))
            self.screen.blit(box, ((self.screen.get_width() - w) // 2,
                                   int(self.screen.get_height() * 0.35)))
        if self.paused:
            font = self.fonts.get(30)
            surf = font.render("已暂停", True, (255, 220, 120))
            self.screen.blit(surf, ((self.screen.get_width() - surf.get_width()) // 2,
                                    self.screen.get_height() // 2))

    # ---------- 工具 ----------

    def _cursor_pos(self) -> tuple[int, int]:
        if self.touch.is_touch:
            pts = list(self.gestures.touches.values())
            if pts:
                return int(pts[0]["pos"][0]), int(pts[0]["pos"][1])
        return pygame.mouse.get_pos()

    def mouse_grid(self, pos: tuple[int, int] | None = None):
        if pos is None:
            pos = self._cursor_pos()
        return self.camera.screen_to_grid(
            *pos, screen_size=self.screen.get_size(),
            grid_w=self.grid.w, grid_h=self.grid.h)