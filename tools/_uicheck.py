#!/usr/bin/env python3
"""桩 pygame 集成测试：不开窗口，跑真实 Game 的交互路径。

本机 workspace 没装 pygame，所以用 unittest.mock 桩掉 pygame 的
surface / draw / font 等，验证的是游戏逻辑，不是渲染效果。

覆盖：
  1. Game 能初始化，背包 = STARTING_ITEMS
  2. 放熔炉扣料、拆除返还
  3. 手搓 10 铁矿 → 5 铁板
  4. 空背包手搓返回 0
  5. 矿脉 mine() 按矿种给对应物品
  6. 查看模式点分拣器 → 打开过滤面板
  7. 过滤面板选物品 → 写进 overlay_filter
  8. 非查看模式点分拣器 → 不开面板（不抢放置点击）
  9. 过滤后分拣器实际只抓指定物品（端到端）

跑法：python tools/_uicheck.py
"""

from __future__ import annotations

import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


# ---------- pygame 桩 ----------

class _FakeRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    @property
    def left(self): return self.x
    @property
    def top(self): return self.y
    @property
    def right(self): return self.x + self.w
    @property
    def bottom(self): return self.y + self.h
    @property
    def width(self): return self.w
    @property
    def height(self): return self.h
    @property
    def topleft(self): return (self.x, self.y)
    @property
    def centerx(self): return self.x + self.w // 2
    @property
    def centery(self): return self.y + self.h // 2

    def collidepoint(self, pos):
        px, py = pos
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def colliderect(self, other):
        return not (self.x + self.w <= other.x or other.x + other.w <= self.x
                    or self.y + self.h <= other.y or other.y + other.h <= self.y)

    def inflate(self, dx, dy):
        return _FakeRect(self.x - dx // 2, self.y - dy // 2,
                         self.w + dx, self.h + dy)

    def __getitem__(self, i):
        return (self.x, self.y, self.w, self.h)[i]

    @property
    def size(self):
        return (self.w, self.h)

    @size.setter
    def size(self, v):
        self.w, self.h = int(v[0]), int(v[1])

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    @center.setter
    def center(self, v):
        self.x = int(v[0]) - self.w // 2
        self.y = int(v[1]) - self.h // 2

    def copy(self):
        return _FakeRect(self.x, self.y, self.w, self.h)


class _FakeSurface:
    def __init__(self, size=(1, 1), flags=0):
        self._size = size

    def get_size(self):
        return self._size

    def fill(self, *a, **k):
        pass

    def blit(self, *a, **k):
        pass

    def convert(self):
        return self

    def convert_alpha(self):
        return self

    def subsurface(self, rect):
        return self

    def get_clip(self):
        return _FakeRect(0, 0, *self._size)

    def set_clip(self, *a, **k):
        pass

    def get_rect(self, **k):
        return _FakeRect(0, 0, *self._size)


class _FakeFont:
    def render(self, text, aa, color, *a):
        return _FakeSurface((max(len(str(text)) * 6, 1), 14))

    def get_height(self):
        return 14

    def size(self, text):
        return (len(str(text)) * 6, 14)


class _FakeFonts:
    def get(self, size=14):
        return _FakeFont()


def build_fake_pygame():
    pg = mock.MagicMock()
    pg.Rect = _FakeRect
    pg.Surface = _FakeSurface
    pg.SRCALPHA = 0x00010000
    pg.draw = mock.MagicMock()
    pg.display = mock.MagicMock()
    pg.time = mock.MagicMock()
    pg.time.get_ticks.return_value = 0
    pg.font = mock.MagicMock()
    pg.K_ESCAPE = 27
    # 常量，gestures 和其它模块 import 时会读
    for i, name in enumerate(["FINGERDOWN", "FINGERMOTION", "FINGERUP",
                              "QUIT", "KEYDOWN", "MOUSEBUTTONDOWN",
                              "MOUSEBUTTONUP", "MOUSEWHEEL", "MOUSEMOTION"]):
        setattr(pg, name, 1000 + i)
    return pg


_fakepg = build_fake_pygame()
sys.modules["pygame"] = _fakepg

from stellarloom import config as C  # noqa: E402


def new_game():
    """用桩 pygame 造一个真实 Game。"""
    from stellarloom.core.game import Game
    screen = _FakeSurface((1280, 720))
    with mock.patch.object(Game, "_draw_ui", lambda self: None), \
            mock.patch("stellarloom.render.fonts.FontBook",
                       lambda: _FakeFonts()):
        g = Game(screen)
    g.fonts = _FakeFonts()
    g.mod_mgr.unload()  # 卸掉真实 mods（mods/ 目录），防 mixin 污染测试基线
    g.menu.open = False  # 测试直达游戏态（默认启动是主菜单）
    return g


def check_init() -> bool:
    g = new_game()
    inv = dict(g.inventory)
    ok = inv.get(C.I_IRON_PLATE) == C.STARTING_ITEMS.get(C.I_IRON_PLATE)
    print(f"[1] 初始化背包={inv}")
    if not ok:
        print("  !! FAIL 初始背包不对")
        return False
    return True


def check_place_and_remove() -> bool:
    g = new_game()
    before = g._count(C.I_FURNACE_ITEM)
    # 找块空地
    for x in range(2, 40):
        if g.grid.can_place(x, 2):
            gx, gy = x, 2
            break
    g.selected_building = C.B_FURNACE
    g._place_or_harvest(gx, gy, confirm_only=True)
    placed = g.grid.get(gx, gy) == C.B_FURNACE
    mid = g._count(C.I_FURNACE_ITEM)
    g._remove_or_mine(gx, gy)
    after = g._count(C.I_FURNACE_ITEM)
    print(f"[2] 熔炉 背包 {before}→{mid}→{after}，放下={placed}")
    if not placed or mid != before - 1 or after != before:
        print("  !! FAIL 放置扣料 / 拆除返还不对")
        return False
    return True


def check_craft() -> bool:
    g = new_game()
    g.inventory.clear()
    g.inventory.update({C.I_IRON_ORE: 10})
    # 手搓现在是排队制：材料在排队时扣掉，产出要靠 update 推进时间
    n = g._do_craft("iron_plate", 10)
    plate0 = g._count(C.I_IRON_PLATE)
    ore0 = g._count(C.I_IRON_ORE)
    print(f"[3] 排 10 次 → 实排 {n}（10 铁矿刚好够），排队后铁板={plate0} 剩铁矿={ore0}")
    # iron_plate = 矿 1 → 铁板 1（统一配方和机器一致），10 铁矿正好排 10 次
    if n != 10 or plate0 != 0 or ore0 != 0:
        print("  !! FAIL 排队数量或扣料不对")
        return False
    if g.craft_panel.job is None:
        print("  !! FAIL 没生成手搓任务")
        return False
    # 手搓单件耗时 = 机器 dur(1.0) × HAND_CRAFT_TIME_MULT(2.5) = 2.5 秒
    hdur = C.RECIPES["iron_plate"][2] * C.HAND_CRAFT_TIME_MULT
    print(f"[3b] 手搓单件耗时 {hdur}s（机器 {C.RECIPES['iron_plate'][2]}s）")
    # 推进 hdur*3 - 0.1 → 应该出 2 件（未到 3 件）；队列推进在服务器端
    g.sim.step(hdur * 3 - 0.1)
    mid = g._count(C.I_IRON_PLATE)
    print(f"[3c] 推进 {hdur*3:.1f}s → 铁板={mid}（期望 2）")
    if mid != 2:
        print("  !! FAIL 手搓耗时不对（应该是逐个产出）")
        return False
    # 补足剩余 8 件
    g.sim.step(hdur * 8)
    plate = g._count(C.I_IRON_PLATE)
    print(f"[3d] 再推进 {hdur*8:.1f}s → 铁板={plate}，任务={g.craft_panel.job}")
    if plate != 10 or g.craft_panel.job is not None:
        print("  !! FAIL 手搓收尾不对")
        return False
    return True


def check_craft_empty() -> bool:
    g = new_game()
    g.inventory.clear()
    g._toast_msg = lambda *a, **k: None
    n = g._do_craft("iron_plate", 5)
    print(f"[4] 空背包手搓 = {n} (期望 0)，任务={g.craft_panel.job}")
    if n != 0 or g.craft_panel.job is not None:
        print("  !! FAIL 空背包竟然排上了")
        return False
    return True


def check_mine_by_oretype() -> bool:
    g = new_game()
    # 找一块铜矿
    ys, xs = np.nonzero(g.grid.ore_type == C.ORE_COPPER)
    if len(xs) == 0:
        print("[5] 地图没铜矿，跳过")
        return True
    x, y = int(xs[0]), int(ys[0])
    item = g.grid.mine(x, y)
    print(f"[5] 铜矿格 mine() → 物品 {item} (期望 {C.I_COPPER_ORE})")
    if item != C.I_COPPER_ORE:
        print("  !! FAIL 矿种产出不对")
        return False
    return True


def _inserter_case():
    g = new_game()
    # 清一块干净区域做测试
    for y in range(6, 12):
        for x in range(6, 14):
            g.grid.building[y, x] = C.B_EMPTY
            g.grid.overlay[y, x] = C.B_EMPTY
            g.grid.overlay_filter[y, x] = 0
    g.grid.place(7, 8, C.B_BELT, 0)   # 源格
    g.grid.place(8, 8, C.B_BELT, 0)   # 分拣器叠这格
    g.grid.place_overlay(8, 8, C.B_INSERTER, 0)
    g.grid.belts_changed()
    g.belts.rebuild()
    g.machines.sync()
    return g, (8, 8)


def check_filter_panel_open() -> bool:
    g, cell = _inserter_case()
    g.ui.view_mode = True
    opened = g._try_open_panel(*cell)
    is_open = g.filter_panel.open
    print(f"[6] 查看模式点分拣器 → 开面板={opened}/{is_open}")
    if not (opened and is_open):
        print("  !! FAIL 查看模式没打开过滤面板")
        return False
    # 非查看模式不能开（避免抢放置点击）
    g2, cell2 = _inserter_case()
    g2.ui.view_mode = False
    g2.selected_building = C.B_BELT
    opened2 = g2._try_open_panel(*cell2)
    print(f"[7] 非查看模式点分拣器 → 开面板={opened2} (期望 False)")
    if opened2:
        print("  !! FAIL 非查看模式抢了放置点击")
        return False
    return True


def check_filter_panel_apply() -> bool:
    g, cell = _inserter_case()
    g.ui.view_mode = True
    g._try_open_panel(*cell)
    # 直接走面板的 hit 逻辑：构造面板行再点
    fp = g.filter_panel
    screen = g.screen
    fp.draw(screen)          # draw 会填充 self.rows
    target = None
    for r, item in fp.rows:
        if item == C.I_COPPER_ORE:
            target = r
            break
    if target is None:
        print("  !! FAIL 面板里找不到铜矿选项")
        return False
    cx = target.left + target.w // 2
    cy = target.top + target.h // 2
    choice = fp.hit((cx, cy))
    if choice is not None:
        g.grid.set_overlay_filter(cell[0], cell[1], choice)
    got = g.grid.get_overlay_filter(*cell)
    print(f"[8] 面板点铜矿 → 过滤值={got} (期望 {C.I_COPPER_ORE})")
    if got != C.I_COPPER_ORE:
        print("  !! FAIL 过滤值没写进去")
        return False
    return True


def check_filter_end_to_end() -> bool:
    """过滤后分拣器端到端只抓指定物品。"""
    g, cell = _inserter_case()
    cx, cy = cell
    g.grid.set_overlay_filter(cx, cy, C.I_COPPER_ORE)
    # 分拣器朝右 d=0：源=(7,8) 目标=(9,8)，把熔炉放目标
    g.grid.direction[cy, cx] = 0
    g.grid.overlay_dir[cy, cx] = 0
    g.grid.building[cy, 9] = C.B_FURNACE
    g.grid.belts_changed()
    g.belts.rebuild()
    g.machines.sync()
    m = g.machines.get_machine(9, cy)
    if m is None:
        print("  !! FAIL 目标熔炉没建起来")
        return False
    m.set_recipe("copper_plate")

    lane = g.belts.cell_lane.get((7, cy))
    if lane is None:
        print("  !! FAIL 源格不在任何 lane 上")
        return False
    ln = g.belts.lanes[lane]
    ln.positions = np.array([ln.cell_index((7, cy)) + 0.5], dtype=np.float32)
    ln.items = np.array([C.I_IRON_ORE], dtype=np.int32)

    g.inserters.cooldowns.clear()
    g.inserters.update(0.0, g.machines)
    still = list(int(i) for i in ln.items)
    print(f"[9] 过滤=铜矿，源是铁矿 → 带子剩余={still}，熔炉={dict(m.inputs)}")
    if still != [C.I_IRON_ORE] or m.inputs:
        print("  !! FAIL 过滤失效，铁矿被误抓")
        return False

    ln.items = np.array([C.I_COPPER_ORE], dtype=np.int32)
    g.inserters.cooldowns.clear()
    g.inserters.update(0.0, g.machines)
    got = m.inputs.get(C.I_COPPER_ORE, 0)
    print(f"[10] 换成铜矿 → 熔炉={dict(m.inputs)}")
    if got != 1:
        print("  !! FAIL 铜矿没被抓走")
        return False
    return True


def check_chest_place_and_panel() -> bool:
    """放箱子要扣料、能自动开暂存面板、拆除时里面的货退回背包。"""
    g = new_game()
    g.inventory[C.I_CHEST_ITEM] = 5
    # 找块空地
    cell = None
    for x in range(2, 60):
        if g.grid.can_place(x, 20):
            cell = (x, 20)
            break
    if cell is None:
        print("  !! FAIL 找不到空地")
        return False
    before = g._count(C.I_CHEST_ITEM)
    g.selected_building = C.B_CHEST
    g._place_or_harvest(*cell, confirm_only=True)
    placed = g.grid.get(*cell) == C.B_CHEST
    mid = g._count(C.I_CHEST_ITEM)
    opened = g.storage_panel.open
    print(f"[11] 放箱子：背包 {before}→{mid}，放下={placed}，面板自动打开={opened}")
    if not placed or mid != before - 1 or not opened:
        print("  !! FAIL 放箱子扣料或开面板失败")
        return False

    # 箱子里塞点货，然后拆掉，货必须退回背包
    ch = g.chests.get(*cell)
    if ch is None:
        print("  !! FAIL 箱子对象不存在")
        return False
    ch.store = {C.I_IRON_PLATE: 7, C.I_GEAR: 3}
    plate_before = g._count(C.I_IRON_PLATE)
    gear_before = g._count(C.I_GEAR)
    g.storage_panel.close()
    g._remove_or_mine(*cell)
    plate_after = g._count(C.I_IRON_PLATE)
    gear_after = g._count(C.I_GEAR)
    chest_back = g._count(C.I_CHEST_ITEM)
    print(f"[11b] 拆箱子：铁板 {plate_before}→{plate_after}，"
          f"齿轮 {gear_before}→{gear_after}，箱子物品 {mid}→{chest_back}")
    if plate_after != plate_before + 7 or gear_after != gear_before + 3:
        print("  !! FAIL 拆箱子时里面的货蒸发了")
        return False
    if chest_back != mid + 1:
        print("  !! FAIL 拆箱子没返还建筑物品")
        return False
    return True


def check_machine_panel_manual() -> bool:
    """机器面板：原料能手动放入/取出，产物只能整体取出。"""
    g = new_game()
    g.machines.sync()
    # 找块空地放熔炉（绕过扣料直接用网格摆）
    cell = None
    for x in range(2, 60):
        if g.grid.can_place(x, 30):
            cell = (x, 30)
            break
    if cell is None:
        print("  !! FAIL 找不到空地")
        return False
    g.grid.place(*cell, C.B_FURNACE, 0)
    g.grid.belts_changed()
    g.belts.rebuild()
    g.machines.sync()
    m = g.machines.get_machine(*cell)
    if m is None:
        print("  !! FAIL 熔炉没建起来")
        return False
    m.set_recipe("iron_plate")

    g.inventory[C.I_IRON_ORE] = 20
    g.machine_panel.show(m, g.screen.get_size(), g.tech.researched, g.inventory)
    mp = g.machine_panel
    mp.draw(g.screen)   # 填充按钮区

    def click(action):
        for rect, act, item in mp._btn_rects:
            if act == action:
                mp.hit((rect.left + rect.w // 2, rect.top + rect.h // 2))
                return True
        return False

    if not click("put10"):
        print("  !! FAIL 面板里找不到放10按钮")
        return False
    after_put = m.inputs.get(C.I_IRON_ORE, 0)
    inv_left = g.inventory.get(C.I_IRON_ORE, 0)
    print(f"[12] 面板放10 → 熔炉原料 {after_put}，背包剩 {inv_left}")
    if after_put != 10 or inv_left != 10:
        print("  !! FAIL 手动放入不对")
        return False

    # 再放一次应该被上限挡住（10 是上限）
    mp.draw(g.screen)
    click("put10")
    capped = m.inputs.get(C.I_IRON_ORE, 0)
    print(f"[12b] 再放10 → 熔炉原料 {capped}（上限 {C.MACHINE_INPUT_CAP}）")
    if capped > C.MACHINE_INPUT_CAP:
        print("  !! FAIL 面板能超上限塞料")
        return False

    # 取回 1 个
    mp.draw(g.screen)
    click("take1")
    got = m.inputs.get(C.I_IRON_ORE, 0)
    print(f"[12c] 取1 → 熔炉原料 {got}")
    if got != capped - 1:
        print("  !! FAIL 手动取出不对")
        return False

    # 产物整体取
    m.outputs = {C.I_IRON_PLATE: 5}
    mp.draw(g.screen)
    if not click("takeout_all"):
        print("  !! FAIL 面板里找不到全取按钮")
        return False
    print(f"[12d] 全取产物 → 产物 {m.outputs}，背包铁板 {g._count(C.I_IRON_PLATE)}")
    if m.outputs:
        print("  !! FAIL 产物没被取空")
        return False
    return True


def check_miner_panel() -> bool:
    """采矿机：放下自动开面板，能手动存取 50 格暂存。"""
    g = new_game()
    g.inventory[C.I_MINER_ITEM] = 3
    ys, xs = np.nonzero(g.grid.ore > 0)
    if not len(xs):
        print("  !! FAIL 地图上没矿")
        return False
    cell = (int(xs[0]), int(ys[0]))
    g.selected_building = C.B_MINER
    g._place_or_harvest(*cell, confirm_only=True)
    placed = g.grid.get(*cell) == C.B_MINER
    opened = g.storage_panel.open
    print(f"[13] 放采矿机：放下={placed}，面板自动打开={opened}")
    if not placed or not opened:
        print("  !! FAIL 放采矿机失败")
        return False
    mn = g.miners.get(*cell)
    if mn is None:
        print("  !! FAIL 采矿机对象不存在")
        return False
    mn.buffer = {C.I_IRON_ORE: 30}
    sp = g.storage_panel
    sp.draw(g.screen)
    target = None
    for rect, kind, item in sp._rows:
        if kind == "tall" and item == C.I_IRON_ORE:
            target = rect
            break
    if target is None:
        print("  !! FAIL 面板里找不到全取按钮")
        return False
    before_inv = g._count(C.I_IRON_ORE)
    sp.hit((target.left + target.w // 2, target.top + target.h // 2))
    after_inv = g._count(C.I_IRON_ORE)
    print(f"[13b] 全取 30 个矿 → 暂存 {mn.buffer}，背包 {before_inv}→{after_inv}")
    if mn.buffer or after_inv != before_inv + 30:
        print("  !! FAIL 采矿机手动全取不对")
        return False
    return True


def check_craft_panel_ui() -> bool:
    """合成面板改版：先选产物才显示原料 + 面板放大 + 科研站能手搓。"""
    g = new_game()
    g.inventory.clear()
    g.inventory.update({C.I_IRON_PLATE: 100, C.I_STONE_BRICK: 100,
                        C.I_COPPER_WIRE: 100, C.I_MAGNET: 100,
                        C.I_GEAR: 100, C.I_COPPER_PLATE: 100})
    cp = g.craft_panel
    cp.show(g.screen.get_size(), g.inventory)

    # [20] 面板确实变大了
    old_w, old_h = 440, 480
    print(f"[20] 面板尺寸 {cp.rect.w}×{cp.rect.h}（旧版 {old_w}×{old_h}）")
    if cp.rect.w <= old_w * 1.1 or cp.rect.h <= old_h * 1.05:
        print("  !! FAIL 面板没变大")
        return False

    # [21] 初始没选产物，右栏不显示原料
    if cp.sel_item is not None:
        print("  !! FAIL 初始就选了产物")
        return False
    print(f"[21] 初始 sel_item={cp.sel_item}（期望 None，右栏应显示提示）")

    # [22] 截图口径：draw 后应该有产物行点击区，且能选中
    cp.draw(g.screen)
    if not cp._item_rects:
        print("  !! FAIL 产物列表是空的（手搓配方没进目录）")
        return False
    target = None
    for rect, item in cp._item_rects:
        if item == C.I_LAB_ITEM:
            target = rect
            break
    print(f"[22] 产物行 {len(cp._item_rects)} 个，科研站在列表里={target is not None}")
    if target is None:
        print("  !! FAIL 科研站没进手搓列表")
        return False

    # [23] 点科研站行 → 选中，再 draw 右栏才有内容
    hit_res = cp.hit((target.left + 5, target.top + 5))
    print(f"[23] 点科研站行 → 返回 {hit_res}（期望 None，只是选中），"
          f"sel={cp.sel_item == C.I_LAB_ITEM}")
    if hit_res is not None or cp.sel_item != C.I_LAB_ITEM:
        print("  !! FAIL 点产物行没选中")
        return False

    # [24] 选中后右栏出现"做1/做10"按钮
    cp.draw(g.screen)
    acts = {a for _, a in cp._btn_rects}
    print(f"[24] 选中后按钮: {acts}")
    if not {"make1", "make10"} <= acts:
        print("  !! FAIL 材料够却没出现制作按钮")
        return False

    # [25] 点"做1" → 排队 1 个科研站，材料当场扣
    b1 = next(rect for rect, a in cp._btn_rects if a == "make1")
    plate_before = g.inventory.get(C.I_IRON_PLATE, 0)
    res = cp.hit((b1.centerx, b1.centery))
    print(f"[25] 点做1 → {res}，job={cp.job.left if cp.job else None}，"
          f"铁板 {plate_before}→{g.inventory.get(C.I_IRON_PLATE, 0)}")
    if res is None or res[0] != "craft" or cp.job is None or cp.job.left != 1:
        print("  !! FAIL 点做1没排队")
        return False

    # [26] 推进 手搓耗时 后科研站到手（队列在服务器端推进）
    dur = C.RECIPES["lab"][2] * C.HAND_CRAFT_TIME_MULT
    lab_before = g.inventory.get(C.I_LAB_ITEM, 0)
    g.sim.step(dur + 0.01)
    lab_after = g.inventory.get(C.I_LAB_ITEM, 0)
    print(f"[26] 推进 {dur}s（机器 {C.RECIPES['lab'][2]}s × 2.5）→ 科研站 {lab_before}→{lab_after}")
    if lab_after != lab_before + 1 or cp.job is not None:
        print("  !! FAIL 科研站手搓没出成品")
        return False
    return True


def check_craft_queue() -> bool:
    """手搓队列不许互相顶掉：搓 A 时点 B，A 的进度和材料都要保住。"""
    g = new_game()
    g._toast_msg = lambda *a, **k: None
    # 铁矿 → 铁板、铜矿 → 铜板。两条不同配方，看会不会互相覆盖。
    # 原地更新（保持 Game.inventory 与服务器端同引用）
    g.inventory.clear()
    g.inventory.update({C.I_IRON_ORE: 10, C.I_COPPER_ORE: 10})
    n1 = g._do_craft("iron_plate", 3)
    hdur_plate = C.RECIPES["iron_plate"][2] * C.HAND_CRAFT_TIME_MULT
    cp = g.craft_panel
    print(f"[queue] 先排铁板 {n1} 件，jobs={[(j.rid, j.left) for j in cp.jobs]}")
    if n1 != 3 or len(cp.jobs) != 1:
        print("  !! FAIL 第一条任务没排上")
        return False

    # 推进 1 件的时间，让第一件出场（队列推进在服务器端）
    g.sim.step(hdur_plate + 0.01)
    plate1 = g._count(C.I_IRON_PLATE)
    left1 = cp.jobs[0].left if cp.jobs else 0
    print(f"[queue] 推进 {hdur_plate:.1f}s → 铁板={plate1}，剩 {left1} 件")
    if plate1 != 1 or left1 != 2:
        print("  !! FAIL 第一件没正常产出")
        return False

    # 关键：此时排铜板，铁板的 2 件必须还在、进度不能归零
    n2 = g._do_craft("copper_plate", 2)
    lst = [(j.rid, j.left) for j in cp.jobs]
    print(f"[queue] 排铜板 {n2} 件 → 队列={lst}")
    if n2 != 2 or len(cp.jobs) != 2:
        print(f"  !! FAIL 新任务顶掉了旧任务，队列={lst}")
        return False
    if cp.jobs[0].rid != "iron_plate" or cp.jobs[0].left != 2:
        print(f"  !! FAIL 旧任务进度被改，队首={lst[0]}")
        return False

    # 同配方连点要合并到队尾，不刷两行
    g.inventory[C.I_COPPER_ORE] = 5
    n3 = g._do_craft("copper_plate", 1)
    lst = [(j.rid, j.left) for j in cp.jobs]
    print(f"[queue] 再排 1 件铜板 → 队列={lst}")
    if n3 != 1 or len(cp.jobs) != 2 or cp.jobs[-1].left != 3:
        print(f"  !! FAIL 同配方没合并，队列={lst}")
        return False

    # 一路推到底：铁板 3 + 铜板 3 都要到手
    hdur_cu = C.RECIPES["copper_plate"][2] * C.HAND_CRAFT_TIME_MULT
    g.sim.step(hdur_plate * 2 + hdur_cu * 3 + 1.0)
    plate = g._count(C.I_IRON_PLATE)
    cu = g._count(C.I_COPPER_PLATE)
    print(f"[queue] 全推完 → 铁板={plate}(期望3) 铜板={cu}(期望3) "
          f"剩余任务={len(cp.jobs)}")
    if plate != 3 or cu != 3 or cp.jobs:
        print("  !! FAIL 队列跑完数量不对")
        return False

    # 大 dt 一次跨多个任务：时间不能浪费
    g.inventory.clear()
    g.inventory.update({C.I_IRON_ORE: 1, C.I_COPPER_ORE: 1})
    g._do_craft("iron_plate", 1)
    g._do_craft("copper_plate", 1)
    p0, c0 = g._count(C.I_IRON_PLATE), g._count(C.I_COPPER_PLATE)
    g.sim.step(hdur_plate + hdur_cu + 0.5)
    p1, c1 = g._count(C.I_IRON_PLATE), g._count(C.I_COPPER_PLATE)
    print(f"[queue] 一次推进 {hdur_plate + hdur_cu + 0.5:.1f}s → "
          f"铁板 {p0}→{p1} 铜板 {c0}→{c1}")
    if p1 != p0 + 1 or c1 != c0 + 1:
        print("  !! FAIL 跨任务时剩余时间被吞掉")
        return False

    # 取消要一次清空全部排队
    g.inventory.clear()
    g.inventory.update({C.I_IRON_ORE: 5, C.I_COPPER_ORE: 5})
    g._do_craft("iron_plate", 2)
    g._do_craft("copper_plate", 2)
    cp.cancel()
    print(f"[queue] 取消后排队长={len(cp.jobs)}（期望 0）")
    if cp.jobs:
        print("  !! FAIL 取消没清空队列")
        return False
    return True


def check_category_toolbar() -> bool:
    """底栏分类制：只显示大类，点开才出具体建筑。"""
    from stellarloom.ui import touch_ui as TU
    g = new_game()
    ui = g.ui
    cats = TU.CATEGORIES
    print(f"[cate] 大类 {len(cats)} 个，建筑 {len(TU.TOOLBAR)} 种")
    if len(ui.buttons) != len(cats):
        print(f"  !! FAIL 底栏按钮数 {len(ui.buttons)} != 大类数 {len(cats)}")
        return False
    # 全部可建造建筑都得出现在某个大类里，一个不能漏（核心 B_CORE 不可建，排除）
    buildable = set(C.BUILDING_NAMES) - {C.B_CORE}
    all_b = {b for _, items in cats for b in items}
    if all_b != buildable:
        miss = buildable - all_b
        extra = all_b - buildable
        print(f"  !! FAIL 分类对不上：漏 {miss} 多 {extra}")
        return False
    # 同一建筑不许出现在两个大类
    total = [b for _, items in cats for b in items]
    if len(total) != len(set(total)):
        print("  !! FAIL 有建筑被重复归类")
        return False

    # 默认收起，没有子按钮
    if ui.cat_open is not None or ui._sub_rects():
        print("  !! FAIL 默认应该是收起的")
        return False

    # 点第一个多建筑大类 → 展开
    ci = next(i for i, (_, items) in enumerate(cats) if len(items) > 1)
    rect, _ = next((r, i) for r, i in ui.buttons if i == ci)
    res = ui.hit((rect.centerx, rect.centery))
    subs = ui._sub_rects()
    print(f"[cate] 点大类 {cats[ci][0]} → {res}，展开 {len(subs)} 个子按钮")
    if ui.cat_open != ci or len(subs) != len(cats[ci][1]):
        print("  !! FAIL 大类没正确展开")
        return False
    # 展开后子按钮条要算在 UI 区里（不能穿透到世界去放建筑）
    sr, sb = subs[0]
    if not ui.in_bars((sr.centerx, sr.centery)):
        print("  !! FAIL 子按钮区没算进 UI 区，点下去会穿透放建筑")
        return False
    # 点其中一个「非当前选中」的子建筑 → 选中（走 game 的动作分发才真正改 selected）
    sr, sb = next((r, b) for r, b in subs if b != ui.selected)
    res = ui.hit((sr.centerx, sr.centery))
    if res:
        g._apply_ui_action(*res)
    print(f"[cate] 点子建筑 {C.BUILDING_NAMES[sb]} → {res}，selected={C.BUILDING_NAMES.get(ui.selected)}")
    if res != ("select", sb) or ui.selected != sb or g.selected_building != sb:
        print("  !! FAIL 点子建筑没选中")
        return False
    # 再点一次同一个 → 取消并收起
    res = ui.hit((sr.centerx, sr.centery))
    if res:
        g._apply_ui_action(*res)
    print(f"[cate] 再点同一个 → {res}，cat_open={ui.cat_open}，selected={ui.selected}")
    if res is None or res[0] != "deselect" or ui.cat_open is not None:
        print("  !! FAIL 再点已选中的子建筑应该取消并收起")
        return False

    # 单建筑大类也要展开（不再"直接选中省一步"）
    single = next(((r, i) for r, i in ui.buttons if len(cats[i][1]) == 1), None)
    if single is not None:
        ui.cat_open = None
        ui.selected = C.B_EMPTY  # 清掉选中，确保子按钮是"未选中"状态
        r, i = single
        res = ui.hit((r.centerx, r.centery))
        subs = ui._sub_rects()
        print(f"[cate] 点单建筑大类 {cats[i][0]} → {res}，"
              f"cat_open={ui.cat_open}，子按钮 {len(subs)}")
        if res is None or res[0] != "noop" or ui.cat_open != i or len(subs) != 1:
            print("  !! FAIL 单建筑大类也应该展开")
            return False
        # 展开后点子按钮 → 选中
        sr, sb = subs[0]
        res = ui.hit((sr.centerx, sr.centery))
        if res:
            g._apply_ui_action(*res)
        print(f"[cate] 点子建筑 {C.BUILDING_NAMES[sb]} → {res}")
        if res != ("select", sb):
            print("  !! FAIL 单建筑大类子按钮没选中")
            return False
    return True


def check_lab_panel() -> bool:
    """科研站面板：点开、切制造模式、选配方、产出矩阵、取产物、切回研究。"""
    g = new_game()
    g.grid.place(10, 10, C.B_LAB)
    g.grid.belts_changed()
    g.labs.sync()
    opened = g._try_open_panel(10, 10)
    print(f"[lab] 点科研站开面板={opened}，panel.open={g.lab_panel.open}")
    if not opened or not g.lab_panel.open:
        print("  !! FAIL 科研站点不开面板")
        return False

    # 切制造模式（按钮定义在 defs JSON，从 defs 拿 rect 再走 hit）
    g.lab_panel.draw(g.screen)
    mp = g.lab_panel.defs.rect(g.lab_panel.defs.ctrl("mode_p"), g.lab_panel.rect)
    g.lab_panel.hit((mp.centerx, mp.centery))
    lab = g.labs.get_lab(10, 10)
    print(f"[lab] 点制造模式 → mode={lab['mode']}")
    if lab["mode"] != C.LAB_MODE_PRODUCE:
        print("  !! FAIL 没切到制造模式")
        return False

    # 选 science_blue 配方
    g.lab_panel.draw(g.screen)
    rb = next((rect for rect, rid in g.lab_panel._rec if rid == "science_blue"),
              None)
    if rb is None:
        print("  !! FAIL 制造模式没有矩阵配方可选")
        return False
    g.lab_panel.hit((rb.centerx, rb.centery))
    print(f"[lab] 选配方 → recipe={lab['recipe']}")
    if lab["recipe"] != "science_blue":
        print("  !! FAIL 配方没选上")
        return False

    # 喂原料 → 跑够时间 → 有产物
    need = C.RECIPES["science_blue"][0]
    for it, n in need.items():
        for _ in range(n):
            g.labs.feed(10, 10, it)
    dur = C.RECIPES["science_blue"][2]
    g.labs.update(dur + 0.5, 1.0)
    produced = lab["outputs"].get(C.I_SCIENCE_BLUE, 0)
    print(f"[lab] 制造后产物电磁矩阵={produced}")
    if produced < 1:
        print("  !! FAIL 制造模式没产出")
        return False

    # 全取产物进背包
    g.lab_panel.draw(g.screen)
    oa = next((rect for rect, act, _ in g.lab_panel._btn if act == "out_all"),
              None)
    if oa is None:
        print("  !! FAIL 没有'全取'按钮")
        return False
    before = g.inventory.get(C.I_SCIENCE_BLUE, 0)
    g.lab_panel.hit((oa.centerx, oa.centery))
    after = g.inventory.get(C.I_SCIENCE_BLUE, 0)
    print(f"[lab] 全取 → 背包电磁矩阵 {before}→{after}，产物={lab['outputs']}")
    if after <= before or lab["outputs"]:
        print("  !! FAIL 产物没取干净")
        return False

    # 切回研究模式（相同：defs 按钮）
    g.lab_panel.draw(g.screen)
    mr = g.lab_panel.defs.rect(g.lab_panel.defs.ctrl("mode_r"), g.lab_panel.rect)
    g.lab_panel.hit((mr.centerx, mr.centery))
    print(f"[lab] 切回研究 → mode={lab['mode']}")
    if lab["mode"] != C.LAB_MODE_RESEARCH:
        print("  !! FAIL 没切回研究模式")
        return False
    return True


def check_tech_tree() -> bool:
    """科技树树状图：深度分层 / 点节点展开描述 / 研究按钮 / 拖动平移。"""
    g = new_game()
    tp = g.tech_panel
    tp.show(g.tech, g.screen.get_size())
    tp.draw(g.screen)

    # 深度分层：根科技 depth 0，前置链 +1
    d0 = (tp._depth["logistics1"], tp._depth["power1"], tp._depth["circuit1"])
    d1 = tp._depth["speed1"]
    d2 = tp._depth["speed2"]
    d3 = tp._depth["speed3"]
    print(f"[teetree] 深度 logistics1={d0[0]} speed1={d1} speed2={d2} "
          f"speed3={d3}")
    if d0 != (0, 0, 0) or d1 != 1 or d2 != 2 or d3 != 3:
        print("  !! FAIL 深度分层不对")
        return False

    # 点节点 → 展开描述
    n = tp._nodes["logistics1"]
    tp.hit(tp._to_screen(n.left + 10, n.top + 10))
    if tp.selected != "logistics1":
        print("  !! FAIL 点节点没展开描述")
        return False
    tp.draw(g.screen)
    if not tp._detail_btn:
        print("  !! FAIL 描述条没出现研究按钮")
        return False
    # 点 [开始研究] → 开始研究
    tp.hit(tp._detail_btn[0][0].center)
    print(f"[teetree] 点研究按钮后 current={g.tech.current}")
    if g.tech.current != "logistics1":
        print("  !! FAIL 开始研究没生效")
        return False

    # 拖动平移视角
    old = tp.off_x
    tp.drag_by(-40, 0)
    print(f"[teetree] 左拖 off_x {old} -> {tp.off_x}")
    if not (tp.off_x < old):
        print("  !! FAIL 拖动没平移")
        return False
    return True


def check_tech_queue() -> bool:
    """研究队列：连排多个科技，完成后自动接下一个。"""
    g = new_game()
    t = g.tech
    t.start("logistics1")
    t.start("power1")      # 排进队列
    t.start("wind1")       # 前置 power1 在队列里 → 允许
    t.start("speed1")      # 前置 logistics1 在 current → 允许
    ok_bad, _ = t.can_queue("dyson2")   # 前置 dyson1 没计划 → 拒绝
    print(f"[queue] current={t.current} queue={t.queue} 乱排 dyson2={ok_bad}")
    if t.current != "logistics1" or t.queue != ["power1", "wind1", "speed1"]:
        print("  !! FAIL 队列内容不对")
        return False
    if ok_bad:
        print("  !! FAIL 前置未满足也允许排队")
        return False

    # 吃完 logistics1 的包 → 完成并自动接 power1
    cost = C.TECH_TREE["logistics1"][1]
    t.add_pack_progress(cost)
    print(f"[queue] 完成 logistics1 后 current={t.current} queue={t.queue} "
          f"researched={sorted(t.researched)}")
    if "logistics1" not in t.researched:
        print("  !! FAIL logistics1 没完成")
        return False
    if t.current != "power1":
        print("  !! FAIL 没自动接下一个")
        return False
    if t.queue != ["wind1", "speed1"]:
        print("  !! FAIL 队列没出队")
        return False
    return True


def check_craft_show_all() -> bool:
    """合成栏显示全部配方（含不能手搓的），不能手搓的禁用制作并提示可用机器。"""
    from stellarloom.ui.craft_panel import _machine_names
    g = new_game()
    cp = g.craft_panel
    cp.show(g.screen.get_size(), g.inventory)
    cp.draw(g.screen)
    has = any(item == C.I_SCIENCE_BLUE for _, item in cp._item_rects)
    print(f"[craftall] 电磁矩阵进合成列表={has}")
    if not has:
        print("  !! FAIL 不能手搓的配方没显示在合成栏里")
        return False
    row = next(r for r, item in cp._item_rects if item == C.I_SCIENCE_BLUE)
    cp.hit((row.left + 5, row.top + 5))
    cp.draw(g.screen)
    acts = {a for _, a in cp._btn_rects}
    mn = _machine_names("science_blue")
    print(f"[craftall] 选中后按钮={acts}，可用机器='{mn}'")
    if "make1" in acts or "make10" in acts:
        print("  !! FAIL 不能手搓的配方却出现制作按钮")
        return False
    if "科研站" not in mn:
        print("  !! FAIL 可用机器提示里没有科研站")
        return False
    return True


def check_machine_locked_recipe() -> bool:
    """制造台配方选择器：显示全部配方，未解锁的电路板标🔒且点不动。"""
    g = new_game()
    g.machines.sync()
    cell = None
    for x in range(2, 60):
        if g.grid.can_place(x, 30):
            cell = (x, 30)
            break
    if cell is None:
        print("  !! FAIL 找不到空地")
        return False
    g.grid.place(*cell, C.B_ASSEMBLER, 0)
    g.grid.belts_changed()
    g.belts.rebuild()
    g.machines.sync()
    m = g.machines.get_machine(*cell)
    g.machine_panel.show(m, g.screen.get_size(), g.tech.researched, g.inventory)
    mp = g.machine_panel
    mp.draw(g.screen)

    # M6.28：先点 [点击选择配方] 打开选择器，再查配方列表
    pick = next(iter(mp._picker_btn), None)
    if pick is None:
        print("  !! FAIL 主界面没有选配方按钮")
        return False
    mp.hit((pick[0].centerx, pick[0].centery))
    if not mp._picker:
        print("  !! FAIL 点选配方按钮没打开选择器")
        return False
    mp.draw(g.screen)

    row = next((r for r, rid in mp._recipe_rects if rid == "circuit"), None)
    print(f"[craftlock] 制造台列表里有电路板={row is not None}")
    if row is None:
        print("  !! FAIL 未解锁的电路板配方没显示在制造台面板")
        return False
    mp.hit((row.left + row.w // 2, row.top + row.h // 2))
    print(f"[craftlock] 点未解锁电路板后 recipe={m.recipe_id} (期望 None)")
    if m.recipe_id is not None:
        print("  !! FAIL 未解锁配方被选中了")
        return False
    # 选择器列表不得顶穿面板底部（配方行溢出即爆版）
    over = [rid for rect, rid in mp._recipe_rects
            if rect.bottom > mp.rect.bottom - 30]
    print(f"[craftlock] 顶出面板底部的配方格: {over if over else '无'} "
          f"(共 {len(mp._recipe_rects)} 格)")
    if over:
        print("  !! FAIL 配方格子溢出面板底部")
        return False
    # 选择已解锁配方应生效并回到主界面
    ok_row = next((r for r, rid in mp._recipe_rects if rid == "gear"), None)
    if ok_row is not None:
        mp.hit((ok_row.centerx, ok_row.centery))
        print(f"[craftlock] 点已解锁 gear 后 recipe={m.recipe_id} "
              f"picker={mp._picker} (期望 gear / False)")
        if m.recipe_id != "gear" or mp._picker:
            print("  !! FAIL 已解锁配方没被选中/没回到主界面")
            return False
    return True


def check_save_panel() -> bool:
    import tempfile
    from stellarloom.save import SaveManager
    tmp = tempfile.mkdtemp(prefix="slm_uicheck_")

    # 存模式：点槽 1 -> 存档，面板自动关
    g = new_game()
    g.saves = SaveManager(tmp)
    g._open_save_panel()
    g.save_panel.draw(g.screen)  # 桩下 _rows 由 draw 填充
    if not g.save_panel.open:
        print("  !! FAIL 存档面板没打开")
        return False
    row0 = g.save_panel._rows[0][0]
    g.save_panel.hit((row0.centerx, row0.centery))
    if not g.saves.exists(g.saves.slot_file(0)):
        print("  !! FAIL 点槽1 没有存档")
        return False
    if g.save_panel.open:
        print("  !! FAIL 存档后面板没关")
        return False
    if g.current_slot != 0:
        print("  !! FAIL 当前槽没更新")
        return False

    # F5 快速存档到当前槽
    g.current_slot = 2
    g._quick_save()
    if not g.saves.exists(g.saves.slot_file(2)):
        print("  !! FAIL 快速存档没写到槽3")
        return False

    # 读模式：点有档的槽可读，空槽提示不执行
    g._open_load_panel()
    g.save_panel.draw(g.screen)
    if not g.save_panel.open:
        print("  !! FAIL 读档面板没打开")
        return False
    # 读模式空槽不进 _rows（画成灰色不响应），只可能有档的槽
    slots_n = len(g.save_panel.slots)
    has_any = any(s["has"] for s in g.save_panel.slots)
    if not has_any or len(g.save_panel._rows) < 1:
        print("  !! FAIL 读面板应有可读槽位")
        return False
    idx0 = g.save_panel._rows[0][1]
    g.save_panel.hit((g.save_panel._rows[0][0].centerx,
                      g.save_panel._rows[0][0].centery))
    if g.save_panel.open:
        print("  !! FAIL 读档后面板没关")
        return False
    # 空槽数量的展示一致性：save 模式 rows 应该 = 槽总数
    g._open_save_panel()
    g.save_panel.draw(g.screen)
    if len(g.save_panel._rows) != slots_n:
        print(f"  !! FAIL 存模式应每槽可点（{slots_n}），实际 "
              f"{len(g.save_panel._rows)}")
        return False

    # 摘要
    m = g.saves.slot_meta(g.saves.slot_file(2))
    if m is None or not m.get("items"):
        print(f"  !! FAIL 槽摘要异常: {m}")
        return False
    print(f"[savepanel] 槽1/槽3 独立，摘要: 行星={m.get('planet')} "
          f"物品={m.get('items')} v{m.get('version')}")
    return True


def check_drag_block() -> bool:
    """M6.23：任何面板打开时，拖动 / 双指捏合不许穿透到地图（相机不动）。"""
    from stellarloom.input.gestures import DragEvent, PinchEvent
    g = new_game()
    # 直接网格摆放熔炉 + 同步（桩下 _place_or_harvest 的扣料/注册不可靠）
    g.grid.place(20, 20, C.B_FURNACE, 0)
    g.grid.belts_changed()
    g.belts.rebuild()
    g.machines.sync()
    if g.machines.get_machine(20, 20) is None:
        print("  !! FAIL 熔炉没建起来")
        return False
    size = (1280, 720)
    openers = [
        ("存档", lambda: g._open_save_panel(),
         lambda: g.save_panel.open),
        ("轨道", lambda: g._apply_ui_action("orbit", None),
         lambda: g.orbit_panel.open),
        ("箱子/采矿机", lambda: g.storage_panel.show(size, "t", g, 10, {}),
         lambda: g.storage_panel.open),
        ("背包", lambda: g.bag_panel.show(size, {}),
         lambda: g.bag_panel.open),
        ("手搓", lambda: g.craft_panel.show(size, {}),
         lambda: g.craft_panel.open),
        ("科技", lambda: g.tech_panel.show(g.tech, size),
         lambda: g.tech_panel.open),
        ("科研站", lambda: g.lab_panel.show(g.labs, g.worlds[0].labs,
                                           5, 5, size, {}),
         lambda: g.lab_panel.open),
        ("机器", lambda: g._try_open_panel(20, 20),
         lambda: g.machine_panel.open),
        ("过滤", lambda: g.filter_panel.show(size, (5, 5), 0),
         lambda: g.filter_panel.open),
    ]
    bad = []
    for name, op, opened in openers:
        op()
        if not opened():
            bad.append(f"{name}-未打开")
            g._on_key(_fakepg.K_ESCAPE)
            continue
        g.camera.x, g.camera.y = 100.0, 200.0
        z0 = g.camera.zoom
        g._handle_gesture(DragEvent((320, 240), (400, 300), (80, 60)),
                          1 / 60)
        if (g.camera.x, g.camera.y) != (100.0, 200.0):
            bad.append(f"{name}-拖动")
        g._handle_gesture(PinchEvent((320, 240), 1.5), 1 / 60)
        if g.camera.zoom != z0:
            bad.append(f"{name}-捏合")
        g._on_key(_fakepg.K_ESCAPE)
    if bad:
        print(f"  !! FAIL 穿透: {', '.join(bad)}")
        return False
    print("[dragblock] 9 个面板拖动/捏合全部拦截")
    return True


def check_window_drag() -> bool:
    """M6.28 窗口拖动：按下抓标题栏 → 拖动移动 → 抬起释放；
    松开后再点击任何地方，窗口不得瞬移（防"点击他处窗口飞走"回归）。"""
    from stellarloom.input.gestures import TapEvent, DragEvent
    g = new_game()
    size = (1280, 720)
    g.bag_panel.show(size, {})
    tp = g.bag_panel
    if not tp.open:
        print("  !! FAIL 背包面板没打开")
        return False
    orig = (tp.rect.x, tp.rect.y)
    # 按下（抓标题栏）
    title_pos = (tp.rect.centerx, tp.rect.top + 8)
    if not g.window_mgr.grab(tp, title_pos):
        print("  !! FAIL 标题栏没抓到")
        return False
    # 拖动（带位移）→ 跟随
    g._handle_gesture(DragEvent(title_pos,
                                (title_pos[0] + 60, title_pos[1] + 30),
                                (60, 30)), 1 / 60)
    if (tp.rect.x, tp.rect.y) == orig:
        print("  !! FAIL 拖动没移动窗口")
        return False
    # 抬起 → 释放
    g.window_mgr.end()
    if g.window_mgr.drag is not None:
        print("  !! FAIL 抬起后拖动状态没清")
        return False
    # 松手后点击别处 → 窗口位置必须纹丝不动（不得瞬移/跟随）
    cur = (tp.rect.x, tp.rect.y)
    g._handle_gesture(TapEvent((tp.rect.centerx + 260, tp.rect.centery + 240)),
                      1 / 60)
    if (tp.rect.x, tp.rect.y) != cur:
        print(f"  !! FAIL 点击他处窗口瞬移: {cur} -> "
              f"{(tp.rect.x, tp.rect.y)}")
        return False
    print(f"[winddrag] 抓→移→放 ✓ 点击不瞬移 ✓ (窗口在 {cur})")
    return True


def main():
    cases = [
        ("Game 初始化", check_init),
        ("放置扣料 + 拆除返还", check_place_and_remove),
        ("手搓", check_craft),
        ("空背包手搓", check_craft_empty),
        ("手搓队列不互相顶掉", check_craft_queue),
        ("底栏分类制", check_category_toolbar),
        ("合成栏显示全部配方", check_craft_show_all),
        ("科研站双模式面板", check_lab_panel),
        ("研究队列自动接续", check_tech_queue),
        ("科技树树状图（分层/描述/研究/平移）", check_tech_tree),
        ("合成面板先选后算", check_craft_panel_ui),
        ("矿种产出", check_mine_by_oretype),
        ("过滤面板开合", check_filter_panel_open),
        ("过滤面板写值", check_filter_panel_apply),
        ("过滤端到端", check_filter_end_to_end),
        ("箱子放置/面板/拆箱退货", check_chest_place_and_panel),
        ("机器面板手动存取", check_machine_panel_manual),
        ("制造台显示未解锁配方并拦截", check_machine_locked_recipe),
        ("采矿机面板手动存取", check_miner_panel),
        ("多存档面板（槽位存/读/快速存档）", check_save_panel),
        ("面板打开时拖动/捏合不穿透到地图", check_drag_block),
        ("窗口拖动（抓→移→放，点击不瞬移）", check_window_drag),
    ]
    results = []
    for name, fn in cases:
        try:
            results.append((name, bool(fn())))
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"  !! EXCEPTION in {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            results.append((name, False))
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 桩 pygame 集成测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())