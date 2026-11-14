"""headless 运行器：服务器端独立跑（零 pygame）。

用法：
    python -m stellarloom.sim.headless [存档名] [tick 数]
不带参数 = 新游戏跑 600 tick（默认 1/60 步长 = 10 秒游戏时间）。

只有纯逻辑：Simulation + SaveManager，不初始化图形、不建窗口。
输出结束时各行星概览（建筑数/背包物品数/事件数）和每秒 tick 吞吐。
"""

from __future__ import annotations

import sys
import time

from .sim import Simulation


def _run(sim, stop_after: int, quiet: bool = False):
    t0 = time.perf_counter()
    for _ in range(stop_after):
        sim.step(1 / 60)
    wall = time.perf_counter() - t0
    if quiet:
        return wall
    from .. import config as C
    print(f"模拟 {stop_after} tick 耗时 {wall:.3f}s "
          f"({stop_after / wall:.0f} tick/s)")
    for i, ws in enumerate(sim.worlds):
        n_build = int((ws.grid.building != C.B_EMPTY).sum())
        core = "★" if ws.core_pos else ""
        print(f"  行星{i} {ws.name}{core}: 建筑 {n_build} 格 | "
              f"相机 {ws.camera.x:.0f},{ws.camera.y:.0f} "
              f"x{ws.camera.zoom:.2f}")
    items = sum(sim.inventory.values())
    print(f"  背包 {len(sim.inventory)} 种，共 {items} 件 | "
          f"科研 {len(sim.tech.researched)} 项")
    return wall


def main(argv: list[str]) -> int:
    save_name = None
    ticks = 600
    rest = []
    for a in argv:
        if a.isdigit():
            ticks = int(a)
        else:
            save_name = a
    sim = Simulation()
    if save_name:
        sim.saves.load(sim, save_name)
        print(f"[读档] {save_name}")
    else:
        print("[新游戏] 生成默认行星")
    _run(sim, ticks)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))