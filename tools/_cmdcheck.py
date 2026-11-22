#!/usr/bin/env python3
"""M15a 指令层自检（第 32 项）：联机前置——所有状态修改必须经过 sim。

覆盖：
[1] 机器指令：设配方（含科技/机型校验）、放料/取料/取产物、背包守恒
[2] 容器指令：箱子/采矿机/发射器统一 container_take/put
[3] 科研站指令：模式/配方/取放/取产物
[4] 塔指令：过滤设置
[5] 研究指令：start_research 走 can_queue（允许预排）
[6] 事件/脏格 fan-out：订阅者与 pop_events 都能拿到，互不吞噬
[7] with_world：指令带行星作用域，退出后还原
[8] 面板不越权：静态检查 UI 源码里不再出现直接改状态的调用

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_cmdcheck.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from stellarloom import config as C  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def fresh():
    s = Simulation()
    g = s.grid
    # 清出一片空白区（避开出生核心与矿脉）
    for y in range(40, 60):
        for x in range(40, 60):
            g.building[y, x] = C.B_EMPTY
            g.overlay[y, x] = C.B_EMPTY
    return s


def main() -> int:
    global bad

    # ---------- [1] 机器指令 ----------
    print("[1] 机器指令:")
    s = fresh()
    g = s.grid
    g.place(45, 45, C.B_ASSEMBLER)
    s.machines.sync()
    check(s.set_machine_recipe(45, 45, "no_such") == "no_recipe",
          "不存在的配方没被拒")
    check(s.set_machine_recipe(45, 45, "iron_plate") == "no_recipe",
          "熔炉配方被塞进制造台（机型不匹配应拒）")
    check(s.set_machine_recipe(45, 45, "gear") == "ok", "设齿轮配方失败")
    check(s.machines.get_machine(45, 45).recipe_id == "gear", "配方没写进机器")
    # 放料：背包扣、机器加
    s.inventory[C.I_IRON_PLATE] = 5
    n = s.machine_add_input(45, 45, C.I_IRON_PLATE, 3)
    check(n == 3, f"放入 3 个返回 {n}")
    check(s.inventory.get(C.I_IRON_PLATE) == 2, "背包没扣")
    m = s.machines.get_machine(45, 45)
    check(m.inputs.get(C.I_IRON_PLATE) == 3, "机器没收到料")
    # 非配方原料：机器拒收，背包不变
    check(s.machine_add_input(45, 45, C.I_STONE, 2) == 0, "机器收了不该收的料")
    check(s.inventory.get(C.I_STONE, 0) == 0, "被拒的料却从背包扣了")
    # 取料：机器减、背包加
    check(s.machine_take_input(45, 45, C.I_IRON_PLATE, 1) == 1, "取 1 个失败")
    check(s.inventory.get(C.I_IRON_PLATE) == 3, "取出没进背包")
    # 产物：跑一次配方再整体取
    m.inputs[C.I_IRON_PLATE] = 5
    m.update(5.0, 1.0)
    tot = sum(m.outputs.values())
    got = s.machine_take_outputs(45, 45)
    check(sum(got.values()) == tot, f"产物取出 {got} != 机器里 {tot}")
    check(m.outputs == {}, "取完机器产物槽没空")
    # 无机器格：安全返回
    check(s.set_machine_recipe(10, 10, None) == "no_machine", "空格的指令没被拒")
    check(s.machine_take_input(10, 10, C.I_IRON_PLATE) == 0, "空格取料应返回 0")

    # ---------- [2] 容器指令 ----------
    print("[2] 容器指令（箱子/采矿机/发射器）:")
    s = fresh()
    g = s.grid
    g.place(45, 45, C.B_CHEST)
    g.place(48, 45, C.B_MINER, 0)
    s.chests.sync()
    s.miners.sync()
    check(s.container_at(45, 45)[0] == "chest", "箱子没被识别")
    check(s.container_at(48, 45)[0] == "miner", "采矿机没被识别")
    check(s.container_at(10, 10)[0] is None, "空格居然有容器")
    s.inventory[C.I_IRON_ORE] = 10
    n = s.container_put(45, 45, C.I_IRON_ORE, 4)
    check(n == 4 and s.inventory[C.I_IRON_ORE] == 6, f"放箱 {n} 后背包应 6")
    n = s.container_take(45, 45, C.I_IRON_ORE, 2)
    check(n == 2 and s.inventory[C.I_IRON_ORE] == 8, f"取箱 {n} 后背包应 8")

    # ---------- [3] 科研站指令 ----------
    print("[3] 科研站指令:")
    s = fresh()
    g = s.grid
    g.place(45, 45, C.B_LAB)
    s.labs.sync()
    check(s.lab_set_mode(45, 45, "bogus") == "bad_mode", "非法模式没被拒")
    check(s.lab_set_mode(45, 45, C.LAB_MODE_PRODUCE) == "ok", "切制造模式失败")
    check(s.lab_set_recipe(45, 45, "gear") == "no_recipe",
          "非矩阵配方被塞进科研站")
    check(s.lab_set_recipe(45, 45, "science_blue") == "ok", "设蓝包配方失败")
    s.inventory[C.I_MAGNET] = 1
    s.inventory[C.I_COPPER_WIRE] = 2
    n = s.lab_add_item(45, 45, C.I_MAGNET, 1)
    check(n == 1 and s.inventory.get(C.I_MAGNET, 0) == 0, "科研站放料失败")
    check(s.lab_take_item(45, 45, C.I_MAGNET, 1) == 1, "科研站取料失败")
    check(s.lab_add_item(10, 10, C.I_MAGNET, 1) == 0, "空格科研站指令应返回 0")

    # ---------- [4] 塔过滤 ----------
    print("[4] 塔指令:")
    s = fresh()
    g = s.grid
    g.place(45, 45, C.B_TOWER_SUPPLY)
    s.towers.sync(s.drones)
    check(s.set_tower_filter(45, 45, C.I_IRON_ORE) == "ok", "设塔过滤失败")
    tw = s.towers.get_tower(45, 45)
    check(tw is not None and tw.filter == C.I_IRON_ORE, "过滤没写进塔")
    check(s.set_tower_filter(45, 45, None) == "ok" and tw.filter is None,
          "清空塔过滤失败")
    check(s.set_tower_filter(10, 10, 1) == "no_tower", "空格设过滤没被拒")

    # ---------- [5] 研究指令 ----------
    print("[5] 研究指令:")
    s = fresh()
    ok, msg = s.start_research("power1")
    check(ok, f"首个科技排不进队列: {msg}")
    check(s.tech.current == "power1" or "power1" in s.tech.queue,
          "科技没进 current/queue")
    ok2, msg2 = s.start_research("power1")
    check(not ok2, f"重复研究没被拒: {msg2}")
    # can_queue 语义：直接前置已在 current/queue 里 → 允许预排
    ok3, msg3 = s.start_research("wind1")     # 前置 power1 正在研究
    check(ok3, f"前置在研的科技应可预排: {msg3}")
    # 前置离得太远 → 拒绝（不能跳过整条链）
    ok4, msg4 = s.start_research("engine1")
    check(not ok4, f"跨多级预排应被拒: {msg4}")

    # ---------- [6] fan-out ----------
    print("[6] 事件/脏格 fan-out:")
    s = fresh()
    evs, dirties = [], []
    unsub_ev = s.subscribe_events(lambda e: evs.append(e))
    unsub_d = s.subscribe_dirty(lambda x, y: dirties.append((x, y)))
    s.emit("toast", "你好", 1.0)
    s._mark_dirty(7, 8)
    check(len(evs) == 1 and evs[0][0] == "toast", f"订阅者没收到事件 {evs}")
    check(dirties == [(7, 8)], f"订阅者没收到脏格 {dirties}")
    # pop_events 仍能拿到（互不吞噬）
    popped = s.pop_events()
    check(len(popped) == 1, f"pop_events 拿到 {len(popped)} 条（应 1）")
    check(s.pop_events() == [], "pop_events 没清空")
    # 脏格：本地队列与订阅者都拿到（先清掉上面那条 (7,8)）
    s.take_dirty_cells()
    dirties.clear()
    s._mark_dirty(9, 9)
    local = set(s.take_dirty_cells())
    check(local == {(9, 9)}, f"本地脏格队列丢了 {local}")
    check(dirties == [(9, 9)], f"订阅者没拿到第二次脏格 {dirties}")
    unsub_ev(); unsub_d()
    evs.clear()
    s.emit("toast", "退订后", 1.0)
    check(evs == [], "退订后还收到事件")

    # ---------- [7] with_world ----------
    print("[7] with_world 作用域:")
    s = fresh()
    check(len(s.worlds) >= 2, "测试世界不足 2 颗")
    w0 = s.world_index
    with s.with_world(1) as sw:
        check(sw is s and s.world_index == 1, "with_world 没切世界")
        check(s.grid is s.worlds[1].grid, "grid 没跟着切")
    check(s.world_index == w0, f"退出后没还原（{s.world_index} != {w0}）")
    check(s.grid is s.worlds[w0].grid, "grid 没还原")
    with s.with_world(99):
        check(s.world_index == w0, "非法 world 不该切换")

    # ---------- [8] 面板不越权（静态检查） ----------
    print("[8] 面板直改状态扫描:")
    ui = Path(__file__).resolve().parent.parent / "stellarloom" / "ui"
    forbidden = [
        (r"self\.machine\.set_recipe\(", "machine_panel 直接设配方"),
        (r"\.take_all_outputs\(", "面板直接取产物"),
        (r"self\.inv\.pop\(", "storage_panel 直接改背包"),
        (r"self\.tower\.filter\s*=\s*(?!None if)", "tower_panel 直接改过滤"),
        (r"self\._tech\.start\(self\.selected\)", "tech_panel 直接开研究"),
    ]
    hits = []
    for py in sorted(ui.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        lines = text.splitlines()
        for pat, label in forbidden:
            for m in re.finditer(pat, text):
                line_no = text[:m.start()].count("\n") + 1
                # 允许"sim 不可用时的兜底分支"：看前两行有没有 else / sim is None
                window = "\n".join(lines[max(0, line_no - 3):line_no])
                if ("else:" in window or "self.sim is None" in window
                        or "self._sim is not None" in window):
                    continue
                hits.append(f"{py.name}:{line_no} {label}")
    check(not hits, "面板仍在直接改状态: " + "; ".join(hits[:4]))
    print(f"  扫描 {len(list(ui.glob('*.py')))} 个 UI 文件，越权点 {len(hits)} 处")

    print()
    if bad:
        print(f"FAIL {bad} 项: _cmdcheck")
        return 1
    print("PASS 指令层全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
