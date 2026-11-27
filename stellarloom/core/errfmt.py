"""Java 风格栈打印（M15d）：报错不显示文件路径，显示类名式点分名。

格式：

    ModuleNotFoundError: No module named 'stellarloom.core.game'
        at crash_guard.on_load:369
        at stellarloom.mod.ModManager._load_one:327
        at stellarloom.mod.load_mods:396
    Caused by: ...

规则：
- 帧的"类名"取 frame 的全局 __name__（模块点分路径）；若帧里有 self/cls
  再拼一层类名，得到 stellarloom.mod.ModManager.load_all 这种形状。
- mod 入口模块名 mod_<名字>_main 显示为 <名字>（去掉 mod_ 前缀/_main 后缀），
  一眼看出"这是哪个 mod 闯的祸"。
- 纯文本工具，零 pygame 依赖（服务端/崩溃报告/mod 加载期都能用）。
"""

from __future__ import annotations

import sys
import traceback


def _frame_name(frame) -> str:
    mod = frame.f_globals.get("__name__") or "?"
    func = frame.f_code.co_name
    if mod.startswith("mod_") and mod.endswith("_main"):
        # mod_<名字>_main → <名字>（mod 入口一眼可认）
        mod = mod[4:-5]
    # 方法调用：拼类名（Java 的 ClassName.method 形状）
    self_obj = frame.f_locals.get("self")
    if self_obj is not None:
        qual = type(self_obj).__qualname__.replace(".<locals>", "")
        func = f"{qual}.{func}"
    else:
        cls_obj = frame.f_locals.get("cls")
        if isinstance(cls_obj, type):
            func = f"{cls_obj.__qualname__}.{func}"
    return f"{mod}.{func}"


def format_exc(exc: BaseException | None = None) -> str:
    """Java 风格栈文本。exc=None 时取当前异常（sys.exc_info）。"""
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return ""
    lines: list[str] = []
    cur: BaseException | None = exc
    first = True
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if first:
            lines.append(f"{type(cur).__name__}: {cur}")
            first = False
        else:
            lines.append(f"Caused by: {type(cur).__name__}: {cur}")
        tb = cur.__traceback__
        while tb is not None:
            lines.append(f"    at {_frame_name(tb.tb_frame)}:{tb.tb_lineno}")
            tb = tb.tb_next
        cur = cur.__cause__ or (cur.__context__
                                if not cur.__suppress_context__ else None)
    return "\n".join(lines)


def print_exc(exc: BaseException | None = None, file=None):
    """打印到 stderr（默认）。"""
    out = file if file is not None else sys.stderr
    out.write(format_exc(exc) + "\n")


def install_excepthook():
    """把未捕获异常的默认输出换成 Java 风格栈。

    服务端入口调用；游戏端由 crash_guard mod 调用（崩溃页/报告同一份格式）。
    """
    def hook(etype, value, tb):
        sys.stderr.write(format_exc(value) + "\n")
    sys.excepthook = hook
    # 线程里的未捕获异常也走同一格式
    try:
        import threading
        def thread_hook(args):
            sys.stderr.write(format_exc(args.exc_value) + "\n")
        threading.excepthook = thread_hook
    except Exception:
        pass


def tb_of(exc: BaseException):
    """测试用：直接给 traceback.extract_tb 兼容视图。"""
    return traceback.extract_tb(exc.__traceback__) if exc is not None else []
