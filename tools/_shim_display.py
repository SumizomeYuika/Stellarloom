# -*- coding: utf-8 -*-
"""无显示环境下的 pygame 显示垫层（自检专用）。

背景：Pydroid 的 SDL2 是定制版，`pygame.display.set_mode()` 必须挂在
Android Activity 的 JNI 上下文里，纯 adb shell / 无 Surface 的 Linux
沙箱一律报：
    pygame.error: Application didn't initialize properly,
    did you include SDL_main.h in the file containing your main() function?

但 `pygame.Surface` / `font` / `draw` / `transform` / `image` 全部可用，
渲染类自检只是"画到 surface 再断言状态"，根本不需要真窗口。

本垫层把 `set_mode` 换成返回普通 Surface、`flip/update` 变 noop、
`time.Clock` 换成确定性假时钟，让 `tools/_*check.py` 里的显示类用例
可以跑。

用法（两种都行）：
    python3 tools/_shim_display.py tools/_simcheck.py
    python3 -c "import sys;sys.argv=['_shim_display.py','tools/_simcheck.py'];\
exec(open('tools/_shim_display.py').read())"

注意：这是**测试垫层**，不要在生产代码里 import。
"""
import os
import runpy
import sys

import pygame

_SCREEN = {"surf": None}

FLIP_COUNT = [0]


def _fake_set_mode(size=(640, 480), flags=0, depth=0, display=0, vsync=0):
    surf = pygame.Surface((int(size[0]), int(size[1])))
    _SCREEN["surf"] = surf
    return surf


def _fake_get_surface():
    return _SCREEN["surf"]


def _fake_get_window_size():
    s = _SCREEN["surf"]
    return s.get_size() if s is not None else (0, 0)

def _fake_get_pressed():
    """返回"全键松开"的假键盘状态，支持 [K_x] 下标。"""

    class _Keys(object):
        def __getitem__(self, _k):
            return False

        def __len__(self):
            return 512

    return _Keys()


def _fake_event_get(*_a, **_k):
    return []


def _fake_event_poll():
    return None


def _fake_mouse_get_pos():
    return (0, 0)


def _fake_mouse_get_pressed(*_a, **_k):
    return (0, 0, 0)


def _fake_get_mods(*_a, **_k):
    return 0


def _noop(*_a, **_k):
    return None



def _flip():
    FLIP_COUNT[0] += 1


class FakeClock(object):
    """确定性假时钟：每 tick 自增固定毫秒，不依赖 SDL timer。"""

    def __init__(self):
        self._period = 16
        self._t = 0

    def tick(self, framerate=0):
        self._period = int(1000 / framerate) if framerate else 16
        self._t += self._period
        return self._period

    def tick_busy_loop(self, framerate=0):
        return self.tick(framerate)

    def get_time(self):
        return self._period

    def get_rawtime(self):
        return self._period

    def get_fps(self):
        return 1000.0 / self._period if self._period else 0.0


def install():
    """把垫层装到 pygame 上，返回被替换的原始对象（供需要时还原）。"""
    orig = {
        "set_mode": pygame.display.set_mode,
        "flip": pygame.display.flip,
        "update": pygame.display.update,
        "get_surface": pygame.display.get_surface,
        "get_window_size": getattr(pygame.display, "get_window_size", None),
        "set_caption": pygame.display.set_caption,
        "set_icon": getattr(pygame.display, "set_icon", None),
        "toggle_fullscreen": getattr(pygame.display, "toggle_fullscreen", None),
        "Clock": pygame.time.Clock,
    }
    pygame.display.set_mode = _fake_set_mode
    pygame.display.flip = _flip
    pygame.display.update = _noop
    pygame.display.get_surface = _fake_get_surface
    pygame.display.set_caption = _noop
    if orig["set_icon"] is not None:
        pygame.display.set_icon = _noop
    if orig["toggle_fullscreen"] is not None:
        pygame.display.toggle_fullscreen = _noop
    try:
        pygame.display.get_window_size = _fake_get_window_size
    except Exception:
        pass
    pygame.time.Clock = FakeClock

    # 事件 / 键盘 / 鼠标：无显示环境下 video system 没初始化，这些全要垫
    pygame.event.get = _fake_event_get
    pygame.event.poll = _fake_event_poll
    pygame.event.pump = _noop
    pygame.event.clear = _noop
    pygame.key.get_pressed = _fake_get_pressed
    pygame.key.get_mods = _fake_get_mods
    pygame.key.set_repeat = _noop
    pygame.mouse.get_pos = _fake_mouse_get_pos
    pygame.mouse.get_pressed = _fake_mouse_get_pressed
    pygame.mouse.set_visible = _noop
    pygame.mouse.set_cursor = _noop
    return orig


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write("用法: python3 tools/_shim_display.py <目标自检脚本> [参数...]\n")
        return 2
    target = argv[0]
    if not os.path.exists(target):
        sys.stderr.write("找不到目标脚本: %s\n" % target)
        return 2

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    install()

    # 让目标脚本看到自己是 __main__，且 sys.argv[0] 指向它本体
    old_argv = sys.argv
    sys.argv = [target] + argv[1:]
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as e:
        code = e.code
        return 0 if code is None else int(code) if isinstance(code, int) else 1
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    sys.exit(main())
