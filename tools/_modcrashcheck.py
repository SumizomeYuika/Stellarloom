#!/usr/bin/env python3
"""M15d "mod 加载出错即崩" 自检（第 35 项）。

失败隔离已删除：任何一类 mod 错误都必须从 load_mods / ModManager.load_all
**抛异常**（不 catch、不写 failed），由 crash_guard mod 兜底写崩溃报告。
本自检逐类断言 raise，并确认：
- `mgr.failed` 恒为空 list（仅兼容读取方）；
- 抛过一次之后，换健康目录加载不受影响（没有半成品状态污染）。

错误类别：
[1] mod.json 解析失败        [2] main.py 语法错
[3] on_load 抛异常           [4] mixin 目标不存在
[5] 依赖不满足               [6] 依赖环
[7] 显式 main 入口缺失       [8] 入口路径穿越

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_modcrashcheck.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom.mod import ModManager, load_mods  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


class _Shim:
    def __init__(self):
        self.sim = Simulation()

    def _toast_msg(self, *a, **k):
        pass


def _mod(base: Path, name: str, main: str | None, meta_extra=None):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"name": name, "version": "1.0"}
    meta.update(meta_extra or {})
    (d / "mod.json").write_text(json.dumps(meta), encoding="utf-8")
    if main is not None:
        (d / "main.py").write_text(main, encoding="utf-8")
    return d


def expect_raise(label: str, fn, *substrings):
    try:
        fn()
    except Exception as e:
        text = f"{type(e).__name__}: {e}"
        ok = any(s in text for s in substrings) if substrings else True
        check(ok, f"{label}: 抛了但信息不符 {substrings}: {text}")
        print(f"  {label}: raise ✓ ({type(e).__name__})")
        return
    check(False, f"{label}: 没抛异常（M15d 要求出错即崩）")


def main() -> int:
    shim = _Shim()
    root = Path(tempfile.mkdtemp(prefix="slm_crash_"))

    # [1] mod.json 解析失败
    d = root / "c1"
    (d / "m").mkdir(parents=True)
    (d / "m" / "mod.json").write_text("{oops", encoding="utf-8")
    expect_raise("mod.json 解析失败", lambda: load_mods(shim, d), "mod.json")

    # [2] main.py 语法错
    d = root / "c2"
    _mod(d, "m", "def ::\n")
    expect_raise("main.py 语法错", lambda: load_mods(shim, d), "SyntaxError")

    # [3] on_load 抛异常
    d = root / "c3"
    _mod(d, "m", "def on_load(ctx):\n    raise RuntimeError('boom')\n")
    expect_raise("on_load 抛异常", lambda: load_mods(shim, d), "boom")

    # [4] mixin 目标不存在
    d = root / "c4"
    _mod(d, "m", "def on_load(ctx):\n"
                 "    ctx.mixin('no.such.Class', 'm', lambda self: None)\n")
    expect_raise("mixin 目标不存在", lambda: load_mods(shim, d), "no.such")

    # [5] 依赖不满足
    d = root / "c5"
    _mod(d, "a", "def on_load(ctx): pass")
    _mod(d, "b", "def on_load(ctx): pass",
         {"dependencies": {"a": ">=9.9"}})
    expect_raise("依赖版本不满足", lambda: load_mods(shim, d), "不满足")

    # [6] 依赖环
    d = root / "c6"
    _mod(d, "f", "def on_load(ctx): pass", {"dependencies": {"g": ""}})
    _mod(d, "g", "def on_load(ctx): pass", {"dependencies": {"f": ""}})
    expect_raise("依赖环", lambda: load_mods(shim, d), "依赖环")

    # [7] 显式 main 入口缺失
    d = root / "c7"
    _mod(d, "m", None, {"main": "nope.py"})
    expect_raise("显式入口缺失", lambda: load_mods(shim, d), "nope.py")

    # [8] 入口路径穿越
    d = root / "c8"
    _mod(d, "m", "X=1\n", {"main": "../evil.py"})
    expect_raise("入口路径穿越", lambda: load_mods(shim, d), "非法")

    # failed 恒空（兼容读取方）
    mgr = ModManager(shim, root / "c1")
    check(mgr.failed == [], "failed 应恒为空 list")

    # 抛过一串之后，健康目录照常加载（无半成品状态污染）
    d = root / "healthy"
    _mod(d, "ok1", "def on_load(ctx): ctx.log('ok')\n")
    mgr2 = load_mods(shim, d)
    check([c.name for c in mgr2.ctxs] == ["ok1"], "健康目录加载受污染")
    mgr2.unload()

    print()
    if bad:
        print(f"FAIL {bad} 项: _modcrashcheck")
        return 1
    print("PASS mod 出错即崩全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
