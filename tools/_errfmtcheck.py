#!/usr/bin/env python3
"""M15d 报错格式自检（第 37 项）：Java 风格栈 + 服务端打包可启动。

[1] 格式：`at 模块.类.方法:行号`，**不含文件路径**（无 .py / 盘符 / 斜杠）
[2] 类名拼接：方法调用显示 `Class.method`，模块函数显示 `module.func`
[3] mod 入口模块名美化：mod_foo_main → foo
[4] 异常链：Caused by 段落
[5] install_excepthook 生效（sys.excepthook 被替换，格式一致）
[6] 服务端打包：--check-only 通过（客户端模块也收，逻辑层仍禁 pygame）
[7] 打包产物能启动：run_server --headless-check 正常输出哈希

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_errfmtcheck.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from stellarloom.core.errfmt import (format_exc, install_excepthook,  # noqa: E402
                                     _frame_name)

ROOT = Path(__file__).resolve().parent.parent
bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


class Demo:
    def boom(self):
        raise ValueError("炸了")

    def chain(self):
        try:
            self.boom()
        except ValueError as e:
            raise RuntimeError("外层") from e


def module_level():
    raise KeyError("模块级")


def main() -> int:
    global bad

    # ---------- [1][2] 格式与类名 ----------
    print("[1] 格式（无文件路径）:")
    try:
        Demo().boom()
    except ValueError as e:
        text = format_exc(e)
    lines = text.splitlines()
    check(lines[0] == "ValueError: 炸了", f"首行不是异常摘要: {lines[0]!r}")
    frames = [ln for ln in lines if ln.startswith("    at ")]
    check(len(frames) >= 2, f"帧数不足: {frames}")
    check(any("Demo.boom" in f for f in frames),
          f"方法调用没拼类名: {frames}")
    # 绝不能出现文件路径特征
    for token in (".py", "\\", "/", "C:", "line "):
        check(token not in text,
              f"输出里出现了文件路径特征 {token!r}: {text}")
    check(all(":" in f for f in frames), f"帧缺行号: {frames}")

    # ---------- [3] mod 入口名美化 ----------
    print("[3] mod 入口命名:")
    import types
    fake = types.FrameType
    mod = types.ModuleType("mod_shaderbridge_main")
    mod.__dict__["__name__"] = "mod_shaderbridge_main"
    # 用真实帧模拟：定义一个函数，临时改 __name__
    ns = {"__name__": "mod_shaderbridge_main"}
    exec(compile("def on_load(ctx):\n    raise RuntimeError('x')\n",
                 "<mod>", "exec"), ns)
    try:
        ns["on_load"](None)
    except RuntimeError as e:
        t3 = format_exc(e)
    check("at shaderbridge.on_load:" in t3,
          f"mod 入口模块名没美化: {t3}")
    check("mod_shaderbridge_main" not in t3, "仍暴露 mod_ 前缀")

    # ---------- [4] 异常链 ----------
    print("[4] Caused by 链:")
    try:
        Demo().chain()
    except RuntimeError as e:
        t4 = format_exc(e)
    check("RuntimeError: 外层" in t4 and "Caused by: ValueError: 炸了" in t4,
          f"异常链没展开:\n{t4}")

    # ---------- [5] excepthook ----------
    print("[5] install_excepthook:")
    old = sys.excepthook
    try:
        install_excepthook()
        check(sys.excepthook is not old, "excepthook 没被替换")
    finally:
        sys.excepthook = old

    # ---------- [6] 打包闭包 ----------
    print("[6] 服务端打包闭包:")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_server.py"),
                        "--check-only"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    check(r.returncode == 0, f"闭包检查失败: {r.stdout[-300:]}")
    check("逻辑层 import pygame" not in r.stdout, "逻辑层仍有 pygame")

    # ---------- [7] 打包并启动 ----------
    print("[7] 打包服务端可启动:")
    tmp = Path(tempfile.mkdtemp(prefix="slm_efmt_"))
    out = tmp / "server"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_server.py"),
                        "--out", str(out)], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    check(r.returncode == 0, f"打包失败: {r.stdout[-300:]}")
    r2 = subprocess.run([sys.executable, str(out / "run_server.py"),
                         "--headless-check", "30"], cwd=out,
                        capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=300)
    check(r2.returncode == 0, f"打包服务端启动失败: {r2.stderr[-400:]}")
    check("hash=" in (r2.stdout or ""), f"没输出哈希: {r2.stdout[-200:]}")
    check("Traceback" not in (r2.stderr or "")
          and "File \"" not in (r2.stderr or ""),
          f"仍有标准 traceback 输出: {r2.stderr[-300:]}")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    if bad:
        print(f"FAIL {bad} 项: _errfmtcheck")
        return 1
    print("PASS 报错格式 + 服务端打包全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
