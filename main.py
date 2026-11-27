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
    import argparse
    # M15d：未捕获异常按 Java 风格栈打印（模块.类.方法:行号，不显示文件路径）
    from stellarloom.core.errfmt import install_excepthook
    install_excepthook()

    ap = argparse.ArgumentParser(description="星织 StellarLoom-PG")
    ap.add_argument("--join", default=None, metavar="HOST[:PORT]",
                    help="联机：加入专用服务端（默认端口 27715）")
    ap.add_argument("--name", default="玩家", help="联机昵称")
    args, _unknown = ap.parse_known_args()

    screen = create_screen()
    # M13：分步加载界面（大步骤进度条 + 当前加载项）
    game = create_game(screen)
    if args.join:
        host, _, port_s = args.join.partition(":")
        port = int(port_s) if port_s else 27715
        from stellarloom.net.client import NetClient
        client = NetClient(host, port, args.name, mirror=game.sim)
        if client.connect():
            game.attach_net(client)
            game._toast_msg(f"已加入 {host}:{port}", 3.0)
        else:
            game._toast_msg(f"联机失败：{client.disconnect_reason}", 4.0)
    game.run()