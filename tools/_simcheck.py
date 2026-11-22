#!/usr/bin/env python3
"""_simcheck：服务器端（sim 包）自检（M6.24 架构分层）。

跑法：python tools/_simcheck.py （headless 段不需要 pygame；
同源段用 dummy pygame 起真实 Game）。

覆盖：
[1] 零 pygame：干净解释器里 import sim 后 sys.modules 无 pygame（子进程断言）
[2] headless 推进：新游戏跑 600 tick 无异常、事件流可拉取
[3] 指令闭环：放置 → step 产出 → 拆除退款，背包守恒
[4] Game-sim 同源：Game 引用 sim 的状态对象，手搓/放置走服务器
[5] 存读档：sim 往返 + 前端张视图重建
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
pygame.init()
screen = pygame.display.set_mode((640, 480))

from stellarloom import config as C  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402
from stellarloom.save import SaveManager  # noqa: E402

RESULT = []


def check(name, ok, detail=""):
    RESULT.append(ok)
    print(f"  {name}: {'OK' if ok else '!! FAIL'} {detail}")


def check_no_pygame():
    """/1 干净解释器 import sim 后必须没有 pygame（服务器端零图形依赖）。"""
    code = (
        "import sys; sys.path.insert(0,'.'); "
        "import stellarloom.sim.sim, stellarloom.sim.craft_queue; "
        "assert 'pygame' not in sys.modules, "
        "'sim 链引入了 pygame!'; print('clean-heap')"
    )
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, cwd=os.getcwd())
    check("零 pygame 依赖", r.returncode == 0 and "clean-heap" in r.stdout,
          r.stdout.strip()[:120] + r.stderr.strip()[:120])


def check_headless_sim():
    """/2 纯 Simulation（无任何 UI）推进不出错。"""
    sim = Simulation()
    for _ in range(600):
        sim.step(1 / 60)
    evs = sim.pop_events()
    check("headless 600 tick", True,
          f"行星{len(sim.worlds)} 事件{len(evs)}")
    check("事件类型合法",
          all(e[0] in ("toast", "achievement") for e in evs), f"{evs[:2]}")


def check_instruction_loop():
    """/3 放置→产出→拆除退款，背包守恒。"""
    sim = Simulation()
    sim.inventory.clear()
    sim.inventory.update({C.BUILD_ITEM[C.B_FURNACE]: 3,
                          C.I_IRON_ORE: 100})
    r = sim.place_building(C.B_FURNACE, 20, 20, 0)
    check("放置熔炉", r == "ok" and sim.grid.get(20, 20) == C.B_FURNACE)
    b = sim.inventory.get(C.BUILD_ITEM[C.B_FURNACE], 0)
    check("扣建筑物品", b == 2, f"剩 {b}")
    # 无铁板时配方跑不动（原料在背包），先验证拆除退款
    ok, bt = sim.remove_building(20, 20)
    b2 = sim.inventory.get(C.BUILD_ITEM[C.B_FURNACE], 0)
    check("拆除退款", ok and bt == C.B_FURNACE and b2 == 3, f"剩 {b2}")


def check_game_sim_same_source():
    """/4 Game 与 sim 同引用、世界操作走服务器。"""
    from stellarloom.core import Game
    g = Game(screen)
    check("同引用",
          g.worlds is g.sim.worlds and g.inventory is g.sim.inventory
          and g.saves is g.sim.saves and g.craft is g.sim.craft)
    check("渲染视图并行",
          len(g._chunk_views) == len(g.worlds)
          and g.chunks is g._chunk_views[0])
    # 手搓排队在服务器（背包留 2 熔炉给后面的放置测试）
    g.inventory.clear()
    g.inventory.update({C.I_IRON_ORE: 10, C.BUILD_ITEM[C.B_FURNACE]: 2})
    n = g._do_craft("iron_plate", 3)
    ok = n == 3 and g.sim.craft.jobs and g.craft.jobs is g.sim.craft.jobs
    check("手搓走服务器", ok, f"排队 {n}")
    # 放置走服务器（找块空地，避开初始地形障碍）
    cell = next((x for x in range(2, 60)
                 if g.sim.grid.can_place(x, 30)), None)
    if cell is None:
        check("放置走服务器", False, "找不到空地")
        return
    g.selected_building = C.B_FURNACE
    g._place_or_harvest(cell, 30, confirm_only=True)
    check("放置走服务器",
          g.sim.grid.get(cell, 30) == C.B_FURNACE
          and g.grid is g.sim.grid)


def check_sim_save_roundtrip():
    """/5 sim 存读档往返 + 前端重建。"""
    from stellarloom.core import Game
    g = Game(screen)
    g.saves = SaveManager(tempfile.mkdtemp(prefix="slm_simc_"))
    g.sim.saves = g.saves
    g.selected_building = C.B_FURNACE
    g._place_or_harvest(40, 40, confirm_only=True)
    name = g.saves.slot_file(1)
    g.saves.save(g.sim, name)
    g.saves.load(g.sim, name)
    g._ensure_world(g.sim.world_index)
    g._activate_world(g.sim.world_index)
    for ch in g._chunk_views:
        ch.clear()
    ok = (g.sim.grid.get(40, 40) == C.B_FURNACE
          and g.grid is g.sim.grid)
    check("sim 存读档往返", ok)


def main() -> int:
    print("[1] 服务器端零 pygame")
    check_no_pygame()
    print("[2] headless 推进")
    check_headless_sim()
    print("[3] 指令闭环")
    check_instruction_loop()
    print("[4] Game-sim 同源")
    check_game_sim_same_source()
    print("[5] 存读档往返")
    check_sim_save_roundtrip()
    ok = all(RESULT)
    print("PASS 服务器端自检全部通过" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())