"""M15b 客户端：连服务端、收快照/事件/脏格、把 sim 指令转发成 CMD。

- `NetClient`：网络线程只做收发；`poll()` 在游戏主线程被调用，把入队消息
  应用到本地镜像 `Simulation`（关键帧）或回调给 Game（事件/脏格/聊天）。
- `RemoteSim`：外观与 Simulation 一致的代理——读属性穿透到本地镜像，
  白名单指令方法转发网络调用（阻塞等 ACK，RTT 内 UI 短暂停顿，LAN 无感）。
"""

from __future__ import annotations

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


class NetClient:
    def __init__(self, host: str, port: int, name: str,
                 mirror: Simulation | None = None,
                 timeout: float = 5.0):
        self.host = host
        self.port = port
        self.name = name
        self.mirror = mirror or Simulation()
        self.player_id = 0
        self.connected = False
        self.disconnect_reason = ""
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._pending: dict[int, dict] = {}   # seq -> {"ev": Event, "ack": msg}
        self._inbox: queue.Queue = queue.Queue()     # keyframe/events/dirty/chat
        self._saves = SaveManager()
        self._ever_connected = False
        self.server_mods: list[tuple[str, str]] = []
        # 回调（由 Game.attach_net 注入；主线程上下文执行）
        self.on_events = None
        self.on_dirty = None
        self.on_chat = None
        self.on_keyframe = None
        self.on_disconnect = None

    # ---------- 连接 ----------

    def connect(self, timeout: float = 5.0) -> bool:
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(None)
        except OSError as e:
            self.disconnect_reason = f"连不上: {e}"
            return False
        self._sock = sock
        self._send({"type": "hello", "proto": P.PROTO_VERSION,
                    "name": self.name})
        # 等 hello_ack / deny（握手同步，超时即失败）
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = P.read_frame(sock)
            if msg is None:
                self.disconnect_reason = "握手断线"
                return False
            t = msg.get("type")
            if t == "deny":
                self.disconnect_reason = str(msg.get("reason", "被拒"))
                return False
            if t == "hello_ack":
                self.player_id = int(msg.get("player_id", 0))
                sv = int(msg.get("save_version", -1))
                if sv != SAVE_VERSION:
                    self.disconnect_reason = (
                        f"存档版本不一致 服务端{sv}/本地{SAVE_VERSION}")
                    return False
                # M15c：服务端 mod 清单（客户端比对用，差异只警告不拒绝——
                # 逻辑在服务端跑，客户端缺内容 mod 只是渲染占位）
                self.server_mods = [tuple(m) for m in msg.get("mods", [])]
                self.connected = True
                self._ever_connected = True
                # 等首帧关键帧（其它消息入队，不许丢——服务端可能先发事件/聊天）
                while time.monotonic() < deadline:
                    nxt = P.read_frame(sock)
                    if nxt is None:
                        break
                    if nxt.get("type") == "keyframe":
                        self._apply_keyframe(nxt)
                        break
                    self._inbox.put(nxt)
                self._reader = threading.Thread(target=self._reader_loop,
                                                name="net-reader", daemon=True)
                self._reader.start()
                return True
            # 其它消息（聊天等）握手期直接入队
            self._inbox.put(msg)
        self.disconnect_reason = "握手超时"
        return False

    def close(self):
        was = self.connected or getattr(self, "_ever_connected", False)
        self.connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if was:
            # 本地主动断开也让 Game 走"回退单机"收尾（镜像变本地权威）
            self._inbox.put({"type": "_dropped", "reason": "本地断开"})

    # ---------- 收发 ----------

    def _send(self, msg: dict) -> bool:
        try:
            data = P.pack(msg)
        except P.ProtocolError:
            return False
        try:
            with self._send_lock:
                self._sock.sendall(data)
            return True
        except (ConnectionError, OSError):
            self._drop("发送失败")
            return False

    def _reader_loop(self):
        while self.connected:
            msg = P.read_frame(self._sock)
            if msg is None:
                break
            t = msg.get("type")
            if t == "ack":
                seq = int(msg.get("seq", 0))
                slot = self._pending.get(seq)
                if slot is not None:
                    slot["ack"] = msg
                    slot["ev"].set()
                continue
            self._inbox.put(msg)
        self._drop("连接断开")

    def _drop(self, reason: str):
        if not self.connected:
            return
        self.connected = False
        self.disconnect_reason = reason
        self._inbox.put({"type": "_dropped", "reason": reason})

    # ---------- 主线程消费 ----------

    def poll(self):
        """游戏主线程每帧调用：应用快照、回调事件/脏格/聊天。"""
        while True:
            try:
                msg = self._inbox.get_nowait()
            except queue.Empty:
                break
            t = msg.get("type")
            if t == "keyframe":
                self._apply_keyframe(msg)
                if self.on_keyframe is not None:
                    self.on_keyframe()
            elif t == "events":
                if self.on_events is not None:
                    self.on_events([tuple(e) for e in msg.get("items", [])])
            elif t == "dirty":
                if self.on_dirty is not None:
                    self.on_dirty([(int(x), int(y))
                                   for x, y in msg.get("cells", [])])
            elif t == "chat":
                if self.on_chat is not None:
                    self.on_chat(str(msg.get("player", "?")),
                                 str(msg.get("text", "")))
            elif t == "_dropped":
                if self.on_disconnect is not None:
                    self.on_disconnect(str(msg.get("reason", "")))
            elif t == "pong":
                pass

    def _apply_keyframe(self, msg: dict):
        try:
            data = json.loads(zlib.decompress(
                P.b64d(str(msg.get("blob", "")))).decode("utf-8"))
        except (ValueError, zlib.error, UnicodeDecodeError):
            return
        try:
            self._saves.load_into(self.mirror, data)
        except Exception:
            # 镜像坏了就整体重建一次（最坏情况 = 重新进服）
            self.mirror = Simulation()
            self._saves.load_into(self.mirror, data)

    # ---------- 指令 ----------

    def call(self, name: str, *args, world=None, timeout: float = 3.0,
             **kwargs):
        """远程调用 sim 指令，阻塞等 ACK（带超时）。"""
        if not self.connected:
            return None
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        slot = {"ev": threading.Event(), "ack": None}
        self._pending[seq] = slot
        try:
            msg = {"type": "cmd", "seq": seq, "name": name,
                   "args": list(args), "kwargs": kwargs}
            if world is not None:
                msg["world"] = int(world)
            if not self._send(msg):
                return None
            if not slot["ev"].wait(timeout):
                return None            # 超时：UI 层按失败处理
            ack = slot["ack"] or {}
            if ack.get("error"):
                return None
            return ack.get("result")
        finally:
            self._pending.pop(seq, None)

    def send_chat(self, text: str):
        self._send({"type": "chat", "text": text})


class RemoteSim:
    """外观像 Simulation 的代理：读穿透镜像，白名单指令走网络。

    Game 把它当 self.sim 用：
    - 读状态（grid/inventory/machines/...）→ 本地镜像（只读，绝不本地改）
    - 调指令（place_building/...）→ 网络 CMD → 服务端执行 → 快照回流
    """

    def __init__(self, client: NetClient):
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name: str):
        client = object.__getattribute__(self, "_client")
        mirror = client.mirror
        if name in CMDS.COMMANDS:
            def remote(*args, **kwargs):
                return client.call(name, *args,
                                   world=mirror.world_index, **kwargs)
            remote.__name__ = name
            return remote
        return getattr(mirror, name)

    def __setattr__(self, name: str, value):
        raise AttributeError(
            f"RemoteSim.{name} 是只读的（联机状态由服务端权威）")