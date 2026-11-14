#!/usr/bin/env python3
"""物流流转边界回归：分拣器投递失败时的物品归属、无人机跨边界。

两个怀疑点：
  A. 分拣器从机器抓出物品 → 目标传送带满了 → 投递失败 → 走
     `belts.try_insert(源格)` 回退。可源格是机器不是带子，
     try_insert 直接 False，物品凭空消失。
  B. 无人机跨地图卷绕线飞行时，_at 用裸坐标判距离，
     可能永远判定不到达，卡在线上。

跑法：python tools/_flowcheck.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, InserterNetwork
from stellarloom.logistics.drones import Drone, S_DELIVER
from stellarloom.production import MachineNetwork
from stellarloom.world import WorldGrid


def check_inserter_no_item_loss() -> bool:
    """机器 → 满传送带，投递失败时物品不能消失。"""
    g = WorldGrid(48, 48)
    # 机器在 (10,10)，分拣器在 (11,10) 朝右，目标带子 (12,10)
    g.place(10, 10, C.B_FURNACE, 0)
    g.place_overlay(11, 10, C.B_INSERTER, 0)
    g.place(12, 10, C.B_BELT, 0)
    b = BeltNetwork(g)
    machines = MachineNetwork(g)
    machines.sync()
    ins = InserterNetwork(g, b)

    m = machines.get_machine(10, 10)
    m.set_recipe("iron_plate")
    m.outputs = {C.I_IRON_PLATE: 5}

    # 把目标带子塞满到插不进去
    lane_idx = b.cell_lane.get((12, 10))
    lane = b.lanes[lane_idx]
    ci = lane.cell_index((12, 10))
    lane.positions = np.array([float(ci) + 0.0], dtype=np.float32)
    lane.items = np.array([C.I_IRON_ORE], dtype=np.int32)

    before = m.outputs.get(C.I_IRON_PLATE, 0)
    ins.cooldowns.clear()
    ins.update(0.0, machines)
    after = m.outputs.get(C.I_IRON_PLATE, 0)
    on_belt = b.item_count
    total = after + on_belt
    print(f"[A] 机器产物 {before}→{after}，带子上物品 {on_belt}，"
          f"守恒总量={total}（应={before}+带子原有 1）")
    if total != before + 1:
        print("  !! FAIL 投递失败时物品凭空消失了")
        return False
    return True


def check_drone_wrap_arrival() -> bool:
    """无人机跨卷绕线飞向目标，必须能判定到达。"""
    g = WorldGrid(64, 64)

    class _T:
        def __init__(self, x, y):
            self.x, self.y = x, y
            self.inventory = {}

        def remove_item(self, item, count):
            return 0

        def add_item(self, item, count):
            return 0

    home = _T(63.5, 30.0)
    src = _T(1.0, 30.0)
    dst = _T(63.0, 30.0)
    d = Drone(home)
    d.x, d.y = 63.5, 30.0
    d.state = S_DELIVER
    d.cargo = C.I_IRON_ORE
    d.task_count = 1
    d.target_tower = src
    d.deliver_tower = dst

    arrived = False
    for _ in range(600):
        d.update(1 / 60, g)
        # 用与 _fly_to 相同的卷绕最短距离判断是否到达
        if d.state != S_DELIVER:
            arrived = True
            break
    print(f"[B] 无人机 10 秒后状态={d.state} 位置=({d.x:.2f},{d.y:.2f}) "
          f"到达={arrived}")
    if not arrived:
        print("  !! FAIL 跨卷绕线的无人机卡住了")
        return False
    return True


def check_miner_reverse_belt() -> bool:
    """采矿机朝向下游带子方向相反时，物品仍应落到带子上（不能丢）。"""
    g = WorldGrid(48, 48)
    # 找一块有矿的格子
    ys, xs = np.nonzero(g.ore > 0)
    if not len(xs):
        print("[C] 没矿，跳过")
        return True
    x, y = int(xs[0]), int(ys[0])
    g.place(x, y, C.B_MINER, 0)          # 朝右
    tx, ty = g.wrap(x + 1, y)
    g.place(tx, ty, C.B_BELT, 2)         # 带子朝左（逆流）
    b = BeltNetwork(g)
    item = g.mine(x, y)
    ok = b.try_insert(tx, ty, item)
    print(f"[C] 采矿机产物 {item} 塞进逆流带子={ok}，带子上物品={b.item_count}")
    if not ok:
        print("  !! FAIL 逆流带子塞不进，矿物被丢")
        return False
    return True


def check_infinite_ore() -> bool:
    """矿脉无限：同一格连挖几千次，矿种不变、储量标记不枯竭。"""
    g = WorldGrid(32, 32)
    ys, xs = np.nonzero(g.ore > 0)
    if not len(xs):
        print("[D] 没矿，跳过")
        return True
    x, y = int(xs[0]), int(ys[0])
    first = g.mine(x, y)
    ok = first != 0
    for _ in range(5000):
        if g.mine(x, y) != first:
            ok = False
            break
    alive = int(g.ore[y, x])
    print(f"[D] 连挖 5000 次矿种={first} 储量标记={alive}（矿脉无限，不枯竭）")
    if not ok:
        print("  !! FAIL 矿种变了")
        return False
    if alive <= 0:
        print("  !! FAIL 矿脉会枯竭")
        return False
    return True



class _FT:
    """假塔：够 Drone/调度用。"""

    def __init__(self, x, y, mode="supply", stock=None, full=False):
        self.x, self.y = float(x), float(y)
        self.mode = mode
        self.stock = dict(stock or {})
        self.full = full          # True：add_item 一律拒收（模拟满）
        self.added = 0

    def has(self, item, n=1):
        return self.stock.get(item, 0) >= n

    def remove_item(self, item, n):
        got = min(n, self.stock.get(item, 0))
        self.stock[item] = self.stock.get(item, 0) - got
        return got

    def add_item(self, item, n):
        if self.full:
            return n                 # 全退回 = 溢出
        self.added += n
        self.stock[item] = self.stock.get(item, 0) + n
        return 0

    def missing_items(self):
        return {C.I_IRON_ORE: 4} if self.mode == "request" else {}


def check_drone_overflow() -> bool:
    """请求塔满了：无人机不能丢货，先等空间，超时带货回母塔卸。"""
    g = WorldGrid(64, 64)
    home = _FT(10, 10)
    req = _FT(10, 10, mode="request", full=True)
    d = Drone(home)
    d.x, d.y = 10.0, 10.0
    d.state = S_DELIVER
    d.cargo = C.I_IRON_ORE
    d.task_count = 2
    d.deliver_tower = req

    for _ in range(60):              # 1 秒：应还在等，货没少
        d.update(1 / 60, g)
    print(f"[E] 满塔等 1s：state={d.state} cargo={d.cargo} n={d.task_count}")
    if d.cargo != C.I_IRON_ORE or d.task_count != 2 or d.state != S_DELIVER:
        print("  !! FAIL 请求塔满时把货丢了/提前走了")
        return False

    for _ in range(int(C.DRONE_WAIT_TIMEOUT * 60) + 120):
        d.update(1 / 60, g)
    print(f"[F] 超时后：state={d.state} cargo={d.cargo} 母塔收货={home.added}")
    if d.cargo is not None:
        print("  !! FAIL 带货回家后没卸到母塔")
        return False
    if home.added != 2:
        print("  !! FAIL 母塔少收了货（物品消失）")
        return False

    # 母塔也满：货留在手上，不消失
    home2 = _FT(10, 10, full=True)
    d2 = Drone(home2)
    d2.state = S_DELIVER
    d2.cargo = C.I_IRON_ORE
    d2.task_count = 1
    d2.deliver_tower = _FT(10, 10, mode="request", full=True)
    for _ in range(60 * 6):
        d2.update(1 / 60, g)
    print(f"[G] 母塔也满：state={d2.state} cargo={d2.cargo}")
    if d2.cargo != C.I_IRON_ORE:
        print("  !! FAIL 两塔都满时货又丢了")
        return False
    return True


def check_drone_dispatch() -> bool:
    """派工看 TOWER_RANGE 和全程电量（TechDebt #7）。"""
    from stellarloom.logistics.drones import DroneNetwork

    g = WorldGrid(128, 128)
    dn = DroneNetwork(g)
    home = _FT(10, 10)
    dn.drones = [Drone(home)]

    far = _FT(90, 10, stock={C.I_IRON_ORE: 10})
    near = _FT(35, 10, stock={C.I_IRON_ORE: 10})
    req = _FT(10, 10, mode="request")

    dn.assign_tasks([far, req])
    moved = [x for x in dn.drones if x.state == 1]
    print(f"[H] 供应塔 48 格远（>RANGE 30）：派工 {len(moved)} 架（期望 0）")
    if moved:
        print("  !! FAIL 超出 TOWER_RANGE 还派工")
        return False

    dn.assign_tasks([near, req])
    moved = [x for x in dn.drones if x.state == 1]
    print(f"[I] 供应塔 25 格：派工 {len(moved)} 架（期望 1）")
    if len(moved) != 1:
        print("  !! FAIL 范围内不派工")
        return False

    # 电量不够飞完全程 → 不派
    dn2 = DroneNetwork(g)
    d2 = Drone(home)
    d2.energy = 20.0
    dn2.drones = [d2]
    dn2.assign_tasks([near, req])
    print(f"[J] 电量 20（全程需 50）：派工 {int(d2.state == 1)} 架（期望 0）")
    if d2.state == 1:
        print("  !! FAIL 电量不够还派工")
        return False
    return True


def main():
    results = [
        ("分拣器投递失败不丢物品", check_inserter_no_item_loss()),
        ("无人机跨卷绕线能到达", check_drone_wrap_arrival()),
        ("逆流带子能接矿", check_miner_reverse_belt()),
        ("无人机溢出不丢货", check_drone_overflow()),
        ("无人机派工距离/电量", check_drone_dispatch()),
        ("矿脉无限不枯竭", check_infinite_ore()),
    ]
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"FAIL: {', '.join(bad)}")
        return 1
    print("PASS 物流流转边界全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())