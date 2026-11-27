#!/usr/bin/env python3
"""M15d 联机按玩家分背包自检（第 36 项）：独立背包 + 共享地图。

[1] 两个客户端各自拿到不同 player_id，服务端各有独立 PlayerState
[2] A 放建筑：扣 A 的背包，B 的背包分毫不动；双方镜像都看到建筑（世界共享）
[3] B 往公共箱子放料：扣 B 的背包，A 不受影响；A 再从同一箱子取走
    （容器是世界的，背包是自己的）
[4] 手搓队列各自独立：A 排队手搓，B 的队列仍为空
[5] 科技共享：手动研究吃的是自己的背包，但科技是全队一条线
[6] 单机默认：新 Simulation 只有 players[0]，inventory/craft 指向它

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_playerscheck.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from stellarloom import config as C  # noqa: E402
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
    # ---------- [6] 单机默认（无网络） ----------
    print("[6] 单机默认:")
    solo = Simulation()
    check(sorted(solo.players) == [0], f"单机应只有 player 0: {solo.players}")
    check(solo.inventory is solo.players[0].inventory
          and solo.craft is solo.players[0].craft,
          "单机 inventory/craft 没指向 players[0]")
    solo.inventory[C.I_IRON_ORE] = 42
    check(solo.players[0].inventory[C.I_IRON_ORE] == 42, "单机背包写入失联")

    # ---------- [1]-[5] loopback 双客户端 ----------
    sim = Simulation()
    for y in range(40, 60):
        for x in range(40, 60):
            sim.grid.building[y, x] = C.B_EMPTY
            sim.grid.overlay[y, x] = C.B_EMPTY
    srv = NetServer(sim=sim, port=0, on_log=lambda m: None)
    srv.start()

    cA = NetClient("127.0.0.1", srv.port, "玩家A")
    cB = NetClient("127.0.0.1", srv.port, "玩家B")
    check(cA.connect() and cB.connect(), "连接失败")
    print("[1] 独立 PlayerState:")
    check(cA.player_id != cB.player_id, "player_id 撞车")
    check(cA.player_id in sim.players and cB.player_id in sim.players,
          f"服务端没建 PlayerState: {sorted(sim.players)}")
    invA = sim.players[cA.player_id].inventory
    invB = sim.players[cB.player_id].inventory
    check(invA is not invB, "两个玩家共享了同一个背包 dict")

    print("[2] A 放建筑：扣 A 不扣 B，世界共享:")
    invA[C.I_ASSEMBLER_ITEM] = 1
    beforeB = dict(invB)
    r = cA.call("place_building", C.B_ASSEMBLER, 45, 45, 0)
    check(r == "ok", f"A 放置返回 {r!r}")
    check(invA.get(C.I_ASSEMBLER_ITEM, 0) == 0, "A 没被扣料")
    check(dict(invB) == beforeB, f"A 放置动了 B 的背包: {invB}")
    okw = wait_for(
        lambda: (cA.poll(), cB.poll(),
                 cB.mirror.grid.get(45, 45) == C.B_ASSEMBLER)[-1],
        what="B 镜像看到 A 的建筑")
    check(okw, "世界没共享（B 看不到 A 放的建筑）")

    print("[3] 公共箱子，各自背包:")
    invB[C.I_IRON_PLATE] = 5
    invA.pop(C.I_IRON_PLATE, None)
    r = cA.call("place_building", C.B_CHEST, 50, 50, 0)
    # A 没有箱子物品 → 拒；给 A 发一个
    invA[C.I_CHEST_ITEM] = 1
    r = cA.call("place_building", C.B_CHEST, 50, 50, 0)
    check(r == "ok", f"A 放箱子返回 {r!r}")
    n = cB.call("chest_put", 50, 50, C.I_IRON_PLATE, 3)
    check(n == 3, f"B 存料返回 {n!r}（期望 3）")
    check(invB.get(C.I_IRON_PLATE) == 2, "B 没被扣料")
    check(invA.get(C.I_IRON_PLATE, 0) == 0, "B 存料动了 A 的背包")
    n = cA.call("chest_take", 50, 50, C.I_IRON_PLATE, 3)
    check(n == 3, f"A 取料返回 {n!r}（期望 3）")
    check(invA.get(C.I_IRON_PLATE) == 3, "A 没拿到料")
    check(invB.get(C.I_IRON_PLATE) == 2, "A 取料动了 B 的背包")

    print("[4] 手搓队列各自独立:")
    invA[C.I_IRON_ORE] = 4
    nq = cA.call("do_craft", "iron_plate", 1)
    check(nq == 1, f"A 手搓排队返回 {nq!r}")
    check(sim.players[cA.player_id].craft.job is not None,
          "A 的手搓队列没排上")
    check(sim.players[cB.player_id].craft.job is None,
          "B 的手搓队列被 A 污染")
    cA.call("cancel_craft")

    print("[5] 科技共享（全队一条线）:")
    tid = next(iter(C.TECH_TREE))
    sim.tech.researched.add(tid)
    ok5 = wait_for(
        lambda: (cA.poll(), cB.poll(),
                 tid in cB.mirror.tech.researched)[-1],
        what="科技同步到 B")
    check(ok5, "科技没共享（B 镜像没看到 A 侧研究的科技）")

    cA.close()
    cB.close()
    srv.stop()

    print()
    if bad:
        print(f"FAIL {bad} 项: _playerscheck")
        return 1
    print("PASS 按玩家分背包全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
