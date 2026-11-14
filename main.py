#!/usr/bin/env python3
"""星织：无尽沙盒 StellarLoom-PG — 入口。

注意：pygame 必须在 __main__ 模块里直接 import 并初始化。
Pydroid3 用 exec() 执行本文件，若 pygame 藏在包内间接导入，
Android SDL 找不到正确的入口点，会报 "did you include SDL_main.h"。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pygame  # noqa: E402  必须在主模块直接导入

from stellarloom import config as C  # noqa: E402
from stellarloom.core.bootstrap import create_game  # noqa: E402


def create_screen():
    """依次尝试候选分辨率，返回第一个能开出来的 Surface。"""
    candidates = [
        (C.WINDOW_WIDTH, C.WINDOW_HEIGHT),
        (960, 540),
        (800, 600),
        (640, 360),
        (480, 320),
    ]
    pygame.init()
    for w, h in candidates:
        try:
            if pygame.display.get_init():
                pygame.display.quit()
            pygame.display.init()
            screen = pygame.display.set_mode((w, h))
            print(f"[显示] 使用分辨率 {w}x{h}, 驱动 {pygame.display.get_driver()}")
            return screen
        except pygame.error as e:
            print(f"[显示] {w}x{h} 失败: {e}")
            continue
    raise SystemExit("所有候选分辨率都开不出窗口，SDL 显示栈不可用。")


if __name__ == "__main__":
    screen = create_screen()
    # M13：分步加载界面（大步骤进度条 + 当前加载项）
    create_game(screen).run()