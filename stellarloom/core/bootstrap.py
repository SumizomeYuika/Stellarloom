"""M13：启动引导（bootstrap）。

把"开窗口 → 建游戏"之间插入分步加载界面：
    create_screen()（main.py）
        → create_game(screen)：LoadingScreen + Game 分阶段构造
        → game.run()

Game(screen) 直接构造的旧调用方式不受影响（loader=None 静默），
自检/调试代码不用改。
"""

from __future__ import annotations

from ..core import Game
from ..ui.loading import LoadingScreen


def create_game(screen, mods_dir=None) -> Game:
    """带加载界面地创建 Game（mods_dir 仅供自检覆盖）。"""
    loader = LoadingScreen(screen)
    loader.begin(Game.BOOT_STAGES)
    return Game(screen, loader=loader, mods_dir=mods_dir)