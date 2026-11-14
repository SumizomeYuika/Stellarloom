"""核心里：WorldState（服务器端世界）/ Game（前端应用）。

M6.24 架构分层：core 包本身不 import pygame——Game 用模块级 __getattr__
懒加载（from stellarloom.core import Game 仍可用，但只在真正用到前端时才
拉进 game.py；headless 路径只碰 WorldState，永不触发 pygame）。
"""

from .worldstate import WorldState

__all__ = ["Game", "WorldState"]


def __getattr__(name):
    if name == "Game":
        from .game import Game
        return Game
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")