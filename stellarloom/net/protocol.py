"""M15b 帧协议：MAGIC + 长度前缀 + JSON。

- `pack(msg)`：dict → 线上字节（JSON 必须可序列化；blob 用 base64 字符串）。
- `read_frame(sock)`：从 socket 精确读一帧；连接断开/协议错返回 None。
- 单帧上限 8 MiB（关键帧 ~200 KB，富余很大）。
"""

from __future__ import annotations

import base64
import json
import struct

PROTO_VERSION = 1
MAGIC = b"SLMN"
MAX_FRAME = 8 * 1024 * 1024

_HEADER = struct.Struct("<4sI")


class ProtocolError(Exception):
    pass


def pack(msg: dict) -> bytes:
    body = json.dumps(msg, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ProtocolError(f"帧过大 {len(body)}")
    return _HEADER.pack(MAGIC, len(body)) + body


def _recv_exact(sock, n: int) -> bytes | None:
    """精确收 n 字节；对端断开/出错返回 None。"""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (ConnectionError, OSError):
            return None
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def read_frame(sock) -> dict | None:
    """阻塞读一帧。断线/坏帧返回 None。"""
    head = _recv_exact(sock, _HEADER.size)
    if head is None:
        return None
    magic, ln = _HEADER.unpack(head)
    if magic != MAGIC or ln > MAX_FRAME:
        return None
    body = _recv_exact(sock, ln)
    if body is None:
        return None
    try:
        msg = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return msg if isinstance(msg, dict) else None


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))