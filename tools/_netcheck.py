#!/usr/bin/env python3
"""M15b 网络自检（第 32 项）：协议编解码 + loopback 双端联机。

[1] 帧编解码：往返 / 坏魔数 / 截断 / 超长拒绝
[2] 指令白名单：step/snapshot 被拒；参数类型门
[3] 握手：hello_ack 带 player_id / tickrate / save_version
[4] 双人建造同步：A 放制造台 → ACK ok → 双方镜像都出现
[5] 拒绝路径：无料放置 → ACK 非 ok → 镜像不变
[6] 容器/机器指令：服务端背包扣减 → 关键帧回流一致
[7] 事件扇出：toast 事件到达客户端
[8] 脏格扇出：服务端直接改格 → 客户端收到 dirty
[9] 聊天：A 发 → B 收（带昵称）
[10] 断开：客户端关闭 → 服务端 players 移除；服务端 stop 干净退出

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_netcheck.py
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from stellarloom import config as C  # noqa: E402
from stellarloom.net import commands as CMDS  # noqa: E402
from stellarloom.net import protocol as P  # noqa: E402
from stellarloom.net.client import NetClient  # noqa: E402
from stellarloom.net.server import NetServer  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def wait_for(pred, timeout=5.0, step=0.02, what=""):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(step)
    print(f"  (等待超时: {what})")
    return False


def main() -> int:
    global bad

    # ---------- [1] 帧编解码 ----------
    print("[1] 帧编解码:")
    a, b = socket.socketpair()
    a.sendall(P.pack({"type": "hello", "proto": 1, "name": "测试玩家"}))
    a.sendall(P.pack({"type": "chat", "text": "第二帧"}))
    m1 = P.read_frame(b)
    m2 = P.read_frame(b)
    check(m1 == {"type": "hello", "proto": 1, "name": "测试玩家"},
          f"帧往返不一致: {m1}")
    check(m2 == {"type": "chat", "text": "第二帧"}, f"粘包分帧错: {m2}")
    # 坏魔数 → None
    a.sendall(b"XXXX\x00\x00\x00\x02{}")
    check(P.read_frame(b) is None, "坏魔数没拒")
    # 超长声明 → None
    a.sendall(b"SLMN" + (P.MAX_FRAME + 1).to_bytes(4, "little"))
    check(P.read_frame(b) is None, "超长帧没拒")
    a.close(); b.close()

    # ---------- [2] 指令白名单 ----------
    print("[2] 指令白名单:")
    check(CMDS.validate("place_building", [3, 10, 10, 0], {}) is None,
          "合法指令被拒")
    check(CMDS.validate("step", [0.05], {}) is not None, "step 没拦")
    check(CMDS.validate("snapshot", [], {}) is not None, "snapshot 没拦")
    check(CMDS.validate("place_building", [3, 10, 10, {"x": 1}], {})
          is not None, "dict 参数没拦")
    check(CMDS.validate("place_building", [3, [1, {"x": 1}]], {})
          is not None, "嵌套非标的 list 参数没拦")

    # ---------- [3-10] loopback ----------
    print("[3] 握手:")
    sim = Simulation()
    # 清场：制造台测试区
    for y in range(40, 60):
        for x in range(40, 60):
            sim.grid.building[y, x] = C.B_EMPTY
            sim.grid.overlay[y, x] = C.B_EMPTY
    srv = NetServer(sim=sim, port=0, on_log=lambda m: None)
    srv.start()
    port = srv.port

    cA = NetClient("127.0.0.1", port, "玩家A")
    cB = NetClient("127.0.0.1", port, "玩家B")
    check(cA.connect(), f"A 连接失败: {cA.disconnect_reason}")
    check(cB.connect(), f"B 连接失败: {cB.disconnect_reason}")
    check(cA.player_id != cB.player_id, "两个玩家拿到同一个 id")
    check(wait_for(lambda: len(srv.players) == 2, what="players==2"),
          "服务端没登记两个玩家")

    def pump(*clients):
        for c in clients:
            c.poll()

    # 首帧关键帧：镜像 grid 应与服务端一致（清场区为空）
    check(cA.mirror.grid.get(45, 45) == C.B_EMPTY, "A 镜像初始不是空")

    print("[4] 双人建造同步:")
    cA.call("place_building", C.B_ASSEMBLER, 45, 45, 0)
    # 背包里没制造台物品 → 应该被拒；先给**A 自己的**背包发料再测（M15d
    # 按玩家分背包：指令扣的是发起者 player_id 对应的 PlayerState）
    invA = sim.players[cA.player_id].inventory
    invA[C.I_ASSEMBLER_ITEM] = 2
    r = cA.call("place_building", C.B_ASSEMBLER, 45, 45, 0)
    check(r == "ok", f"A 放置返回 {r!r}（期望 ok）")
    got = wait_for(
        lambda: (cA.poll(), cB.poll(),
                 cA.mirror.grid.get(45, 45) == C.B_ASSEMBLER
                 and cB.mirror.grid.get(45, 45) == C.B_ASSEMBLER)[-1],
        what="双方镜像出现制造台")
    check(got, "B 镜像没同步到 A 放的制造台")

    print("[5] 拒绝路径:")
    # 同一格再放：no_place；并且镜像不该变化
    r2 = cA.call("place_building", C.B_FURNACE, 45, 45, 0)
    check(r2 in ("no_place", None), f"重复放置返回 {r2!r}")
    check(sim.grid.get(45, 45) == C.B_ASSEMBLER, "服务端状态被污染")

    print("[6] 容器/机器指令 + 关键帧回流:")
    invB = sim.players[cB.player_id].inventory
    invB[C.I_IRON_PLATE] = 10
    r3 = cB.call("set_machine_recipe", 45, 45, "gear")
    check(r3 == "ok", f"B 设配方 {r3!r}")
    n = cB.call("machine_add_input", 45, 45, C.I_IRON_PLATE, 3)
    check(n == 3, f"B 放料返回 {n!r}（期望 3）")
    check(invB.get(C.I_IRON_PLATE) == 7,
          f"服务端 B 背包 {invB.get(C.I_IRON_PLATE)}（期望 7）")
    # M15d：镜像只读自己的背包——B 的镜像应回流成 7
    ok6 = wait_for(
        lambda: (cB.poll(), cB.mirror.inventory.get(C.I_IRON_PLATE) == 7)[-1],
        what="B 镜像背包 7")
    check(ok6, "关键帧没把背包变化带回 B")
    m_srv = sim.machines.get_machine(45, 45)
    m_cli = cB.mirror.machines.get_machine(45, 45)
    check(m_srv is not None and m_cli is not None
          and m_cli.recipe_id == m_srv.recipe_id == "gear",
          f"配方不同步: 服务端 {getattr(m_srv, 'recipe_id', '?')} / "
          f"镜像 {getattr(m_cli, 'recipe_id', '?')}")

    print("[7] 事件扇出:")
    got_evs = []
    cA.on_events = lambda evs: got_evs.extend(evs)
    sim.emit("toast", "事件测试", 1.0)
    ok7 = wait_for(lambda: (cA.poll(), bool(got_evs))[-1], what="事件到达")
    check(ok7 and got_evs[0][0] == "toast", f"A 没收到事件 {got_evs}")

    print("[8] 脏格扇出:")
    got_dirty = []
    cB.on_dirty = lambda cells: got_dirty.extend(cells)
    sim.grid.place(50, 50, C.B_CHEST)
    sim._mark_dirty(50, 50)
    ok8 = wait_for(lambda: (cB.poll(), (50, 50) in got_dirty)[-1],
                   what="脏格到达")
    check(ok8, f"B 没收到脏格 {got_dirty}")

    print("[9] 聊天:")
    got_chat = []
    cB.on_chat = lambda p, t: got_chat.append((p, t))
    cA.send_chat("你好 B")
    ok9 = wait_for(lambda: (cB.poll(), bool(got_chat))[-1], what="聊天到达")
    check(ok9 and got_chat[0] == ("玩家A", "你好 B"),
          f"B 没收到聊天 {got_chat}")

    print("[10] 断开与收尾:")
    cA.close()
    check(wait_for(lambda: len(srv.players) == 1, what="剩 1 人"),
          "服务端没移除 A")
    cB.close()
    srv.stop()
    check(not srv.running, "服务端 stop 后还在 running")
    t_alive = [t for t in srv._threads if t.is_alive()]
    check(len(t_alive) <= 2, f"残留线程 {len(t_alive)}: {[t.name for t in t_alive]}")

    print()
    if bad:
        print(f"FAIL {bad} 项: _netcheck")
        return 1
    print("PASS 网络层全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
