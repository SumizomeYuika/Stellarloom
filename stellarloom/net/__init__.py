"""网络层（M15b）：权威服务器 + 镜像客户端。

原则：
- 只有服务端跑 `Simulation.step`；客户端只发指令、收快照/事件/脏格。
- 帧格式固定：`MAGIC(4) + len(4) + json(utf-8)`，TCP 单通道。
- 关键帧直接复用存档格式（SaveManager.dump/load_into），不另造状态编解码。
"""

from .client import NetClient, RemoteSim  # noqa: F401
from .server import NetServer  # noqa: F401

__all__ = ["NetClient", "NetServer", "RemoteSim"]
