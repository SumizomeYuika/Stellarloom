#!/usr/bin/env python3
"""性能压测：headless，不初始化 display，直接跑逻辑链路。

用法：
    python tools/bench.py --belts 40 --items-per-belt 250 --drones 500 --frames 300
    python tools/bench.py --preset 10k
    python tools/bench.py --preset 30k

输出：update / sync / render 三段 frame time 的 avg / p95 / worst。
"""

import argparse
import math
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# headless：必须在 import pygame 之前设置
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402

try:
    import pygame  # noqa: E402
    pygame.init()
    _SCREEN = pygame.display.set_mode((320, 240))  # dummy 驱动下不真开窗
    HAS_PYGAME = True
except Exception as e:  # 没有 pygame 的机器也能测逻辑段
    pygame = None
    _SCREEN = None
    HAS_PYGAME = False
    print(f"[bench] 无 pygame（{e}），只测 update/sync，跳过 render")

from stellarloom import config as C                       # noqa: E402
from stellarloom.logistics import (                       # noqa: E402
    BeltNetwork, DroneNetwork, InserterNetwork, TowerNetwork,
)
from stellarloom.logistics.drones import Drone            # noqa: E402
from stellarloom.power import PowerGrid                   # noqa: E402
from stellarloom.production import MachineNetwork         # noqa: E402
from stellarloom.tech import LabNetwork, TechTree         # noqa: E402
from stellarloom.world import WorldGrid                   # noqa: E402

PRESETS = {
    "10k": dict(belts=40, items_per_belt=250, drones=500, frames=300),
    "30k": dict(belts=60, items_per_belt=500, drones=1500, frames=200),
    "small": dict(belts=10, items_per_belt=100, drones=50, frames=300),
}


def build_belts(g: WorldGrid, n_belts: int):
    """铺 n 条横穿地图、方向向右的直带。"""
    rows = []
    step = max(g.h // max(n_belts, 1), 1)
    xs = np.arange(g.w)
    for i in range(n_belts):
        y = (i * step) % g.h
        rows.append(y)
        g.building[y, xs] = C.B_BELT
        g.direction[y, xs] = 0
    return rows


def fill_items(net: BeltNetwork, per_belt: int) -> int:
    """每条 lane 均匀塞 per_belt 个物品（绕过 try_insert 拥挤检查）。"""
    total = 0
    for lane in net.lanes:
        n = min(per_belt, max(int(lane.length * C.ITEM_CAPACITY_PER_CELL), 0))
        if n <= 0:
            continue
        lane.positions = np.linspace(0, lane.length - 0.5, n, dtype=np.float32)
        lane.items = np.ones(n, dtype=np.int32)
        total += n
    return total


def build_drones(g, drones: DroneNetwork, towers: TowerNetwork, n_drones: int):
    """建塔并 spawn 无人机到目标数量。"""
    if n_drones <= 0:
        return
    n_towers = max(2, int(math.ceil(n_drones / C.DRONES_PER_TOWER)))
    n_supply = n_towers // 2
    for i in range(n_towers):
        for attempt in range(300):
            x = int((i * 37 + attempt * 7) % g.w)
            y = int((i * 53 + attempt * 11) % g.h)
            if towers.can_place(x, y):
                mode = C.B_TOWER_SUPPLY if i < n_supply else C.B_TOWER_REQUEST
                g.building[y, x] = mode
                break
    towers.sync(drones)
    if not towers.towers:
        return
    first = next(iter(towers.towers.values()))
    while len(drones.drones) < n_drones:
        drones.drones.append(Drone(first))


def pct(values, p):
    if not values:
        return 0.0
    v = sorted(values)
    k = max(0, min(len(v) - 1, int(round((len(v) - 1) * p / 100.0))))
    return v[k]


def report(name, times_ms):
    print(f"  {name:8s} avg {statistics.mean(times_ms):7.2f} ms | "
          f"p95 {pct(times_ms, 95):7.2f} ms | "
          f"worst {max(times_ms):7.2f} ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list(PRESETS), default=None)
    ap.add_argument("--belts", type=int, default=40)
    ap.add_argument("--items-per-belt", type=int, default=250)
    ap.add_argument("--drones", type=int, default=500)
    ap.add_argument("--frames", type=int, default=300)
    args = ap.parse_args()

    if args.preset:
        p = PRESETS[args.preset]
        belts, per_belt, drones_n, frames = (
            p["belts"], p["items_per_belt"], p["drones"], p["frames"])
    else:
        belts, per_belt = args.belts, args.items_per_belt
        drones_n, frames = args.drones, args.frames

    print(f"=== bench: belts={belts} items/belt={per_belt} "
          f"drones={drones_n} frames={frames} ===")

    t0 = time.perf_counter()
    g = WorldGrid()
    build_belts(g, belts)
    belts_net = BeltNetwork(g)
    fill_items(belts_net, per_belt)

    machines = MachineNetwork(g)
    inserters = InserterNetwork(g, belts_net)
    power = PowerGrid(g)
    towers = TowerNetwork(g)
    drones = DroneNetwork(g)
    tech = TechTree()
    labs = LabNetwork(g)
    labs.bind(tech)
    inserters.labs = labs

    build_drones(g, drones, towers, drones_n)
    machines.sync()
    labs.sync()
    print(f"场景搭建 {(time.perf_counter()-t0)*1000:.0f} ms | "
          f"物品 {belts_net.item_count} | lane {len(belts_net.lanes)} | "
          f"塔 {towers.count()} | 无人机 {drones.count}")

    t_update, t_sync, t_render = [], [], []
    dt = 1.0 / 60.0
    view_w, view_h = 1280, 720
    tile_px = 24
    r = 4

    for f in range(frames):
        s = time.perf_counter()
        power.update(dt)
        sf = power.speed_factor
        belts_net.update(dt * sf * tech.belt_speed_multiplier())
        machines.update(dt, sf)
        inserters.update(dt, machines)
        towers.update(dt, belts_net, drones)
        drones.update(dt)
        labs.update(dt, sf)
        t_update.append((time.perf_counter() - s) * 1000)

        s = time.perf_counter()
        if f % 60 == 0:
            belts_net.rebuild()
            machines.sync()
            towers.sync(drones)
            labs.sync()
        t_sync.append((time.perf_counter() - s) * 1000)

        s = time.perf_counter()
        if HAS_PYGAME:
            _SCREEN.fill((12, 14, 20))
            for gx, gy, item in belts_net.iter_items():
                sx = int((gx * tile_px) % view_w)
                sy = int((gy * tile_px) % view_h)
                pygame.draw.circle(_SCREEN, C.ITEM_COLORS.get(item, C.C_ITEM),
                                   (sx, sy), r)
            for d in drones.drones:
                sx = int((d.x * tile_px) % view_w)
                sy = int((d.y * tile_px) % view_h)
                pygame.draw.polygon(_SCREEN, (80, 220, 80),
                                    [(sx, sy - r), (sx - r, sy + r), (sx + r, sy + r)])
        t_render.append((time.perf_counter() - s) * 1000)

    print("-" * 66)
    report("update", t_update)
    report("sync", t_sync)
    if HAS_PYGAME:
        report("render", t_render)
    else:
        print("  render   SKIP（无 pygame）")

    total = [a + b + c for a, b, c in zip(t_update, t_sync, t_render)]
    print("-" * 66)
    report("TOTAL", total)
    avg_total = statistics.mean(total)
    print("-" * 66)
    print(f"16.67ms(60fps) -> {'PASS' if avg_total < 16.67 else 'FAIL'}"
          f"  |  33.33ms(30fps) -> {'PASS' if avg_total < 33.33 else 'FAIL'}")
    print(f"FPS 上限 ≈ {1000.0 / avg_total:.1f}")


if __name__ == "__main__":
    main()