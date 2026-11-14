#!/usr/bin/env python3
"""分项性能剖析：把 Game._update 里每一段单独计时，定位真瓶颈。

bench.py 只给 update / sync 两段总时间，看不出是哪个子系统在吃。
这个脚本按子系统拆开，跑同一份场景。

跑法：python tools/_profile.py [--preset small|10k|30k]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from stellarloom import config as C
from stellarloom.logistics import BeltNetwork, DroneNetwork, InserterNetwork, TowerNetwork
from stellarloom.power import PowerGrid
from stellarloom.production import MachineNetwork
from stellarloom.tech import LabNetwork, TechTree
from stellarloom.world import WorldGrid

PRESETS = {
    "small": dict(belts=10, items=100, drones=50, frames=200),
    "10k": dict(belts=40, items=250, drones=500, frames=120),
    "30k": dict(belts=60, items=500, drones=1500, frames=60),
}


class World:
    def __init__(self, belts_n: int, items_per_belt: int, drones_n: int):
        self.grid = WorldGrid()
        g = self.grid
        gw, gh = g.w, g.h
        # 横向铺 belts_n 条长带子，每条 items_per_belt 个物品
        self.lanes_cells = []
        lane_len = max(items_per_belt * 2, 40)
        for i in range(belts_n):
            y = (i * 8 + 4) % gh
            x0 = 10
            for k in range(lane_len):
                g.place(x0 + k, y, C.B_BELT, 0)
        g.belts_changed()
        self.belts = BeltNetwork(g)
        self.machines = MachineNetwork(g)
        self.inserters = InserterNetwork(g, self.belts)
        self.towers = TowerNetwork(g)
        self.drones = DroneNetwork(g)
        self.labs = LabNetwork(g)
        self.tech = TechTree()
        self.labs.bind(self.tech)
        self.inserters.labs = self.labs
        self.power = PowerGrid(g)
        self.machines.sync()
        self.towers.sync(self.drones)
        self.labs.sync()

        # 往每条 lane 塞物品
        for lane in self.belts.lanes:
            n = min(items_per_belt, int(lane.length / C.ITEM_SPACING))
            if n <= 0:
                continue
            lane.positions = np.linspace(
                0, lane.length - 0.1, n).astype(np.float32)
            kinds = [C.I_IRON_ORE, C.I_IRON_PLATE, C.I_GEAR, C.I_CIRCUIT,
                     C.I_COPPER_ORE, C.I_STONE]
            lane.items = np.array(
                [kinds[i % len(kinds)] for i in range(n)], dtype=np.int32)

        # 造塔：供应塔和请求塔交替
        n_towers = max(drones_n // C.DRONES_PER_TOWER, 2)
        for i in range(n_towers):
            x = (i * 37 + 100) % gw
            y = (i * 53 + 200) % gh
            btype = C.B_TOWER_SUPPLY if i % 2 == 0 else C.B_TOWER_REQUEST
            g.place(x, y, btype, 0)
        g.belts_changed()
        self.towers.sync(self.drones)
        for t in self.towers.towers.values():
            t.inventory = {C.I_IRON_PLATE: 15}


def timed(fn, frames):
    t0 = time.perf_counter()
    for _ in range(frames):
        fn()
    dt = time.perf_counter() - t0
    return dt * 1000.0 / frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="10k", choices=list(PRESETS))
    args = ap.parse_args()
    p = PRESETS[args.preset]
    print(f"[profile] preset={args.preset} belts={p['belts']} "
          f"items={p['belts'] * p['items']} drones={p['drones']}")

    w = World(p["belts"], p["items"], p["drones"])
    dt = 1 / 60.0
    frames = p["frames"]
    total_items = sum(len(l.items) for l in w.belts.lanes)
    print(f"实际物品 {total_items} | lane {len(w.belts.lanes)} | "
          f"塔 {len(w.towers.towers)} | 无人机 {len(w.drones.drones)}")
    print("-" * 62)

    rows = []

    def bench(name, fn, frames_):
        ms = timed(fn, frames_)
        rows.append((name, ms))
        print(f"  {name:<22} {ms:8.3f} ms", flush=True)

    bench("belts.update", lambda: w.belts.update(dt), frames)
    bench("machines.update", lambda: w.machines.update(dt, 1.0), frames)
    bench("inserters.update", lambda: w.inserters.update(dt, w.machines), frames)
    bench("towers.update", lambda: w.towers.update(dt, w.belts, w.drones), frames)
    bench("drones.update", lambda: w.drones.update(dt), frames)
    bench("drones.assign_tasks",
          lambda: w.drones.assign_tasks(list(w.towers.towers.values())), frames)
    bench("labs.update", lambda: w.labs.update(dt, 1.0), frames)
    bench("power.update", lambda: w.power.update(dt), frames)
    # 全图扫描（sync）单独测
    bench("machines.sync", lambda: w.machines.sync(), 20)
    bench("towers.sync", lambda: w.towers.sync(w.drones), 20)
    bench("belts.rebuild", lambda: w.belts.rebuild(), 10)

    rows.sort(key=lambda r: -r[1])
    total = sum(v for _, v in rows)
    print("-" * 62)
    for name, ms in rows:
        pct = ms / total * 100 if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {name:<22} {ms:8.3f} ms  {pct:5.1f}%  {bar}")
    print("-" * 62)
    print(f"  合计 {total:.3f} ms/帧  → 理论 FPS 上限 {1000 / total:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())