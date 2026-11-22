"""M15b 权威服务端：独占跑 Simulation，接收指令、广播快照/事件/脏格。

线程模型（3 类线程，全部 daemon）：
- accept 线程：listen → 每个连接建 ClientSession
- 每客户端 reader 线程：读帧 → HELLO/CHAT 直接处理，CMD 进主队列
- tick 线程：20Hz 固定步长——先消化指令队列（串行执行，ACK 回执），
  再 sim.step，再扇出事件/脏格；每秒一帧关键帧（复用存档 dump）

命令行入口：
    python -m stellarloom.net.server --port 27715 [--save saves/save.slm]
        [--autosave 120] [--tickrate 20]
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import threading
import time
import zlib
from pathlib import Path

from ..save import SaveManager
from ..save.savefile import SAVE_VERSION
from ..sim import Simulation
from . import commands as CMDS
from . import protocol as P

SLOW_CMD_LIMIT = 64        # 单 tick 最多消化的指令数（防洪水饿死 tick）


class ClientSession:
    """一个连进来的玩家（服务端视角）。"""

    def __init__(self, server: "NetServer", sock: socket.socket, addr):
        self.server = server
        self.sock = sock
        self.addr = addr
        self.player_id = 0
        self.name = "?"
        self.alive = True
        self._send_lock = threading.Lock()
        self.joined = threading.Event()

    def send(self, msg: dict) -> bool:
        try:
            data = P.pack(msg)
        except P.ProtocolError:
            return False
        try:
            with self._send_lock:
                self.sock.sendall(data)
            return True
        except (ConnectionError, OSError):
            self.alive = False
            return False

    def close(self, reason: str = ""):
        if not self.alive:
            return
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        if self.name != "?":
            self.server._note(f"{self.name} 离开 {reason}".rstrip())


class NetServer:
    def __init__(self, sim: Simulation | None = None, port: int = 27715,
                 tickrate: int = 20, save_dir: str | None = None,
                 saves: SaveManager | None = None, on_log=print):
        self.sim = sim or Simulation()
        self.port = port
        self.tickrate = tickrate
        self.dt = 1.0 / tickrate
        self.saves = saves or SaveManager(save_dir)
        self.running = False
        self.tick = 0
        self.players: list[ClientSession] = []
        self.mods_meta: list[tuple[str, str]] = []
        self.mod_mgr = None
        self._players_lock = threading.Lock()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._events: list = []
        self._dirty: list = []
        self._ev_lock = threading.Lock()
        self._listen: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self.on_log = on_log
        # 关键帧按需重建（全量 dump ~210ms/次，绝不能每秒盲发）：
        # 有变化 ≥0.5s 一次；无论如何 2s 兜底一次（带物品位置会老化）。
        self._kf_needed = threading.Event()
        self._kf_state = {"rev": None, "inv": None, "tick": -999}

        # 服务端是 sim 事件/脏格的唯一消费者（fan-out 到自己队列）
        self.sim.subscribe_events(self._on_event)
        self.sim.subscribe_dirty(self._on_dirty)

    # ---------- 日志 ----------

    def _note(self, msg: str):
        self.on_log(f"[server] {msg}")

    # ---------- 事件扇出 ----------

    def _on_event(self, ev):
        with self._ev_lock:
            self._events.append(ev)

    def _on_dirty(self, x, y):
        with self._ev_lock:
            self._dirty.append((x, y))

    # ---------- 生命周期 ----------

    def start(self):
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind(("0.0.0.0", self.port))
        self._listen.listen(8)
        self.port = self._listen.getsockname()[1]   # 允许 port=0 取临时端口
        self.running = True
        self._spawn(self._accept_loop, "accept")
        self._spawn(self._tick_loop, "tick")
        self._note(f"监听 :{self.port} tickrate={self.tickrate} "
                   f"save_version={SAVE_VERSION}")

    def _spawn(self, fn, name: str):
        t = threading.Thread(target=fn, name=f"net-{name}", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self):
        self.running = False
        if self._listen is not None:
            try:
                self._listen.close()
            except OSError:
                pass
        with self._players_lock:
            players = list(self.players)
        for p in players:
            p.close("server stop")
        for t in self._threads:
            t.join(timeout=1.0)

    # ---------- accept / client reader ----------

    def _accept_loop(self):
        next_id = 1
        while self.running:
            try:
                sock, addr = self._listen.accept()
            except OSError:
                break
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            sess = ClientSession(self, sock, addr)
            sess.player_id = next_id
            next_id += 1
            self._spawn(lambda s=sess: self._client_loop(s),
                        f"client-{sess.player_id}")

    def _client_loop(self, sess: ClientSession):
        try:
            while self.running and sess.alive:
                msg = P.read_frame(sess.sock)
                if msg is None:
                    break
                self._handle(sess, msg)
        finally:
            sess.close()
            with self._players_lock:
                if sess in self.players:
                    self.players.remove(sess)

    def _handle(self, sess: ClientSession, msg: dict):
        t = msg.get("type")
        if t == "hello":
            self._on_hello(sess, msg)
        elif t == "cmd":
            self._cmd_queue.put((sess, msg))
        elif t == "chat":
            text = str(msg.get("text", ""))[:200]
            if text:
                self._note(f"{sess.name}: {text}")
                self._broadcast({"type": "chat", "player": sess.name,
                                 "text": text})
        elif t == "ping":
            sess.send({"type": "pong", "t": msg.get("t", 0)})

    def _on_hello(self, sess: ClientSession, msg: dict):
        if int(msg.get("proto", -1)) != P.PROTO_VERSION:
            sess.send({"type": "deny", "reason": "协议版本不匹配"})
            sess.close("bad proto")
            return
        sess.name = str(msg.get("name", "?"))[:24] or "?"
        with self._players_lock:
            self.players.append(sess)
        self._note(f"{sess.name} 加入 (id={sess.player_id})")
        sess.send({"type": "hello_ack", "player_id": sess.player_id,
                   "save_version": SAVE_VERSION,
                   "tickrate": self.tickrate,
                   "proto": P.PROTO_VERSION,
                   "mods": [list(m) for m in getattr(self, "mods_meta", [])]})
        sess.joined.set()
        # 关键帧交给 tick 线程构建（状态一致），下一个周期全员同步
        self._kf_needed.set()

    # ---------- 指令执行 ----------

    def _apply_command(self, sess: ClientSession, msg: dict) -> dict:
        name = str(msg.get("name", ""))
        args = msg.get("args", [])
        kwargs = msg.get("kwargs", {})
        world = msg.get("world")
        err = CMDS.validate(name, args, kwargs)
        if err is not None:
            return {"type": "ack", "seq": msg.get("seq", 0),
                    "result": None, "error": err}
        fn = getattr(self.sim, name, None)
        if fn is None:
            return {"type": "ack", "seq": msg.get("seq", 0),
                    "result": None, "error": f"sim 没有 {name}"}
        try:
            if CMDS.COMMANDS[name] and isinstance(world, int):
                with self.sim.with_world(world):
                    result = fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
        except Exception as e:
            return {"type": "ack", "seq": msg.get("seq", 0),
                    "result": None,
                    "error": f"{type(e).__name__}: {e}"}
        return {"type": "ack", "seq": msg.get("seq", 0),
                "result": self._jsonable(result)}

    @staticmethod
    def _jsonable(v):
        if isinstance(v, tuple):
            return [NetServer._jsonable(x) for x in v]
        if isinstance(v, dict):
            return {str(k): NetServer._jsonable(x) for k, x in v.items()}
        return v

    # ---------- tick ----------

    def _tick_loop(self):
        period = self.dt
        next_t = time.perf_counter()
        while self.running:
            # 1) 消化指令（与 sim.step 串行，避免竞态）
            n = 0
            while n < SLOW_CMD_LIMIT:
                try:
                    sess, msg = self._cmd_queue.get_nowait()
                except queue.Empty:
                    break
                if sess.alive:
                    sess.send(self._apply_command(sess, msg))
                n += 1
            # 2) 推进模拟（mod 的 on_step 钩子在 step 后同步触发，与单机一致）
            try:
                self.sim.step(period)
                if self.mod_mgr is not None:
                    self.mod_mgr.step(period)
            except Exception as e:
                self._note(f"sim.step 异常: {type(e).__name__}: {e}")
            self.tick += 1
            # 3) 扇出事件/脏格
            with self._ev_lock:
                events, self._events = self._events, []
                dirty, self._dirty = self._dirty, []
            if events:
                self._broadcast({"type": "events",
                                 "items": [list(e) for e in events]})
            if dirty:
                self._broadcast({"type": "dirty",
                                 "cells": [[x, y] for x, y in dirty]})
            # 4) 关键帧：按需重建（见 __init__ 注释的策略）
            revs = tuple(ws.grid.rev for ws in self.sim.worlds)
            inv = self._inv_sig()
            belts_live = any(len(l.positions)
                             for ws in self.sim.worlds
                             for l in ws.belts.lanes)
            changed = (revs != self._kf_state["rev"]
                       or inv != self._kf_state["inv"])
            since = self.tick - self._kf_state["tick"]
            if (self._kf_needed.is_set()
                    or self._kf_state["rev"] is None
                    or (changed and since >= 10)
                    or (belts_live and since >= 40)
                    or since >= 40):
                self._broadcast(self._make_keyframe())
                self._kf_needed.clear()
                self._kf_state.update(rev=revs, inv=inv, tick=self.tick)
            # 5) 定步长休眠（掉帧就跳过，不追帧——工厂游戏滞后好于风暴）
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()

    def _make_keyframe(self) -> dict:
        data = self.saves.dump(self.sim)
        blob = zlib.compress(json.dumps(data, ensure_ascii=False,
                                        separators=(",", ":")).encode(), 6)
        return {"type": "keyframe", "tick": self.tick, "blob": P.b64e(blob)}

    def _inv_sig(self):
        """玩家级状态的廉价签名：变了就重建关键帧。"""
        inv = tuple(sorted(self.sim.inventory.items()))
        t = self.sim.tech
        return (inv, len(t.researched), t.current, len(t.queue),
                self.sim.craft.job is not None)

    def _broadcast(self, msg: dict, exclude: ClientSession | None = None):
        with self._players_lock:
            players = list(self.players)
        for p in players:
            if p is exclude:
                continue
            p.send(msg)

    # ---------- 存档 ----------

    def save_now(self, name: str = "save.slm") -> str:
        return self.saves.save(self.sim, name)

    # ---------- mod（M15c：服务端也是权威，逻辑 mod 必须装在这里） ----------

    def load_mods(self, mods_dir=None):
        """在服务端 sim 上加载 mods（与单机同一套失败隔离/依赖拓扑）。

        返回加载到的 [(name, version)]，握手时随 hello_ack 发给客户端做比对。
        """
        from ..mod import load_mods
        shim = _ServerGameShim(self.sim)
        self.mod_mgr = load_mods(shim, mods_dir)
        self.mods_meta = [(c.name, c.version) for c in self.mod_mgr.ctxs]
        for name, err in self.mod_mgr.failed:
            self._note(f"mod {name} 加载失败: {err}")
        self._note(f"mod 加载 {len(self.mods_meta)} 个"
                   + (": " + ", ".join(n for n, _ in self.mods_meta)
                      if self.mods_meta else ""))
        return self.mods_meta

    def state_hash(self) -> str:
        """headless-check 用：世界建筑 + 背包 + 带位置的确定性哈希。

        只在 tick 边界调用（模拟暂停间隙），保证两次运行结果可逐位比较。
        """
        import hashlib
        h = hashlib.blake2b(digest_size=8)
        for ws in self.sim.worlds:
            g = ws.grid
            h.update(g.building.tobytes())
            h.update(g.direction.tobytes())
            h.update(g.overlay.tobytes())
        for item, n in sorted(self.sim.inventory.items()):
            h.update(item.to_bytes(4, "little"))
            h.update(n.to_bytes(4, "little", signed=True))
        for ws in self.sim.worlds:
            for lane in ws.belts.lanes:
                h.update(lane.positions.tobytes())
                h.update(lane.items.tobytes())
        return h.hexdigest()


class _ServerGameShim:
    """load_mods 需要的 game 外观：只暴露 sim + _toast_msg（服务端无 UI）。"""

    def __init__(self, sim: Simulation):
        self.sim = sim

    def _toast_msg(self, *args, **kwargs):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="StellarLoom 专用服务端")
    ap.add_argument("--port", type=int, default=27715)
    ap.add_argument("--tickrate", type=int, default=20)
    ap.add_argument("--save", default=None, help="启动时读入的存档名")
    ap.add_argument("--save-dir", default=None, help="存档目录（默认 saves/）")
    ap.add_argument("--autosave", type=float, default=120.0,
                    help="自动存档间隔秒（0=关闭）")
    ap.add_argument("--mods-dir", default=None,
                    help="mod 目录（默认项目 mods/；--no-mods 关闭）")
    ap.add_argument("--no-mods", action="store_true", help="不加载任何 mod")
    ap.add_argument("--headless-check", type=int, default=0, metavar="TICKS",
                    help="无网络自检：跑 N tick 后打印状态哈希并退出（CI 用）")
    args = ap.parse_args(argv)

    sim = Simulation()
    saves = SaveManager(args.save_dir)
    if args.save and saves.exists(args.save):
        saves.load(sim, args.save)
        print(f"[server] 已读档 {args.save}")

    if args.headless_check > 0:
        # CI 用：不开 socket，纯跑逻辑，两次运行哈希必须逐位一致
        dt = 1.0 / 20.0
        for _ in range(args.headless_check):
            sim.step(dt)
        tmp = NetServer(sim=sim, saves=saves, on_log=lambda m: None)
        print(f"headless_check ticks={args.headless_check} "
              f"hash={tmp.state_hash()}")
        return 0

    srv = NetServer(sim=sim, port=args.port, tickrate=args.tickrate,
                    saves=saves)
    if not args.no_mods:
        srv.load_mods(args.mods_dir)
    srv.start()
    print("[server] 控制台命令：status / save [名] / players / kick <id|名> / "
          "say <文本> / hash / stop")
    last_save = time.monotonic()
    try:
        while srv.running:
            line = sys_stdin_readline(timeout=0.5)
            if line is None:
                pass
            elif line == "stop":
                break
            elif line == "status":
                print(f"[server] tick={srv.tick} "
                      f"players={len(srv.players)} "
                      f"supply={srv.sim.power.last_supply:.0f}")
            elif line == "players":
                for p in srv.players:
                    print(f"  #{p.player_id} {p.name} {p.addr}")
            elif line.startswith("kick "):
                target = line[5:].strip()
                hit = next((p for p in srv.players
                            if str(p.player_id) == target
                            or p.name == target), None)
                if hit is None:
                    print(f"[server] 没有玩家 {target}")
                else:
                    print(f"[server] 踢出 {hit.name}")
                    hit.close("被管理员踢出")
            elif line.startswith("say "):
                text = line[4:].strip()[:200]
                if text:
                    srv._broadcast({"type": "chat", "player": "[服务器]",
                                    "text": text})
                    print(f"[server] 已广播: {text}")
            elif line == "hash":
                print(f"[server] state_hash={srv.state_hash()}")
            elif line.startswith("save"):
                parts = line.split(maxsplit=1)
                name = parts[1] if len(parts) > 1 else "save.slm"
                print(f"[server] 已存 {srv.save_now(name)}")
            if args.autosave > 0 and time.monotonic() - last_save >= args.autosave:
                last_save = time.monotonic()
                srv.save_now("autosave_server.slm")
    except KeyboardInterrupt:
        pass
    srv.stop()
    return 0


def sys_stdin_readline(timeout: float):
    """非阻塞 stdin 读一行（Windows 无 select on stdin，用线程）。"""
    import sys
    q = getattr(sys_stdin_readline, "_q", None)
    if q is None:
        q = queue.Queue()
        sys_stdin_readline._q = q

        def _reader():
            for ln in sys.stdin:
                q.put(ln.rstrip("\r\n"))
        threading.Thread(target=_reader, daemon=True).start()
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
