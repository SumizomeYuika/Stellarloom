"""服务器端（sim 包）：纯游戏逻辑，headless，零 pygame 依赖。

架构（M6.24，类 Minecraft C/S 分层）：
- sim 包 = 服务器端：世界状态、全部网络模拟、手搓队列、玩家背包、
  科技/戴森云（恒星级），以及放置/拆除/手搓/读档存档等**指令**。
  它不 import pygame，可在无图形环境跑（headless）。
- 前端（core.Game / render / ui / input）只负责渲染仿真状态、把输入
  翻译成 sim 指令、展示 sim 发来的事件（提示/成就）。
"""

from .craft_queue import CraftJob, CraftQueue
from .sim import Simulation

__all__ = ["Simulation", "CraftQueue", "CraftJob"]