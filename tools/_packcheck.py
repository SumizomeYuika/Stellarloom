#!/usr/bin/env python3
"""M12 单文件包自检（第 26 项）：打包 → 加载（纯 py 依赖 + 源码编译依赖）
+ 缓存命中 + 篡改/路径穿越/API 版本拒绝 + 同名目录优先 + 卸载清 sys.path。

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_packcheck.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.core import Game  # noqa: E402
from stellarloom.mod import packfile as PK  # noqa: E402
from stellarloom.mod import load_mods  # noqa: E402

TOOLS = Path(__file__).resolve().parent


def _load_pack_cli():
    spec = importlib.util.spec_from_file_location(
        "pack_mod", TOOLS / "pack_mod.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _pip_ok() -> bool:
    try:
        return subprocess.call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def _fake_compile(name: str, build: Path, lib_dir: Path):
    """模拟编译：把源码包里的同名包目录直接拷进 _lib/（测试用）。"""
    # tar.gz 顶层是 "cdep-1.0/"，真正的包在里面：找含 __init__.py 的目录
    pkg = None
    root = build / name if (build / name).is_dir() else build
    for cand in sorted(root.iterdir()) if root.is_dir() else []:
        if cand.is_dir() and (cand / "__init__.py").is_file():
            pkg = cand
            break
    if pkg is None:
        for cand in build.rglob("*"):
            if cand.is_dir() and (cand / "__init__.py").is_file():
                pkg = cand
                break
    if pkg is None:
        raise PK.PackError(f"stub 编译找不到包目录 {name}")
    dst = lib_dir / pkg.name
    shutil.copytree(pkg, dst, ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "__stub_built__").write_text("1", encoding="utf-8")


def _make_source_mod(src: Path, name: str, main_src: str,
                     extra: str = "") -> None:
    src.mkdir(parents=True, exist_ok=True)
    (src / "mod.json").write_text(
        '{"name": "%s", "version": "1.0", "description": "t"%s}\n'
        % (name, (", " + extra) if extra else ""), encoding="utf-8")
    (src / "main.py").write_text(main_src, encoding="utf-8")


def _make_cdep_tar(path: Path) -> Path:
    """造一个纯 python 源码包 cdep-1.0.tar.gz（setup.py + cdep/）。"""
    tmp = Path(tempfile.mkdtemp(prefix="cdep_"))
    d = tmp / "cdep-1.0"
    (d / "cdep").mkdir(parents=True)
    (d / "setup.py").write_text(
        'from setuptools import setup\n'
        'setup(name="cdep", version="1.0", packages=["cdep"])\n',
        encoding="utf-8")
    (d / "cdep" / "__init__.py").write_text(
        'VERSION = "1.0"\n', encoding="utf-8")
    out = path
    import tarfile
    with tarfile.open(out, "w:gz") as tf:
        tf.add(d, arcname="cdep-1.0")
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def main() -> int:
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    g = Game(screen)
    g.menu.open = False
    g.mod_mgr.unload()          # 清掉真实 mods/，保持基线
    pack_cli = _load_pack_cli()

    base = Path(tempfile.mkdtemp(prefix="slm_pack_"))
    bad = 0

    def check(cond, msg):
        nonlocal bad
        if not cond:
            bad += 1
            print(f"  !! FAIL {msg}")

    # ---------- 素材 ----------
    src = base / "src" / "packdemo"
    (src / "resources").mkdir(parents=True)
    (src / "resources" / "icon.txt").write_text("OK", encoding="utf-8")
    (src / "mod.json").write_text(
        '{"name": "packdemo", "version": "1.0", "description": "t"}',
        encoding="utf-8")
    (src / "main.py").write_text(
        "from packdemo_lib import greet\n"
        "MARK = None\n"
        "def on_load(ctx):\n"
        "    global MARK\n"
        "    r = ctx.resource('icon.txt').read_text().strip()\n"
        "    MARK = greet() + '/' + r\n",
        encoding="utf-8")
    pylib = base / "pylib"
    (pylib / "packdemo_lib").mkdir(parents=True)
    (pylib / "packdemo_lib" / "__init__.py").write_text(
        'def greet():\n    return "hi"\n', encoding="utf-8")
    cdep_tar = _make_cdep_tar(base / "cdep-1.0.tar.gz")

    pack_path = base / "packdemo.slmmod"
    manifest = pack_cli.pack(src, pack_path,
                             [pylib / "packdemo_lib"], [cdep_tar])
    check(pack_path.read_bytes().startswith(PK.MAGIC), "魔数缺失")
    check(len(manifest["files"]) >= 5, "manifest 文件清单不足")

    # ---------- [1] 加载：纯 py 依赖 + 源码依赖（确定性用 stub 编译） ----------
    print("[1] 打包加载 & 依赖:")
    orig_run = PK._run_compile
    calls = {"n": 0}

    def counting_compile(name, build, lib_dir):
        calls["n"] += 1
        return _fake_compile(name, build, lib_dir)

    loader1 = base / "ldr1"
    loader1.mkdir()
    shutil.copy2(pack_path, loader1 / "packdemo.slmmod")
    PK._run_compile = counting_compile
    try:
        mgr = load_mods(g, loader1)
    finally:
        PK._run_compile = orig_run
    names = [c.name for c in mgr.ctxs]
    check("packdemo" in names, f"packdemo 没加载: {names} {mgr.failed}")
    pd = next(c for c in mgr.ctxs if c.name == "packdemo")
    pd_main = sys.modules.get(f"mod_{pd.name}_main")
    check(getattr(pd_main, "MARK", None) == "hi/OK",
          f"依赖没生效/资源读不到: MARK={getattr(pd_main, 'MARK', None)}")
    cache = loader1 / "_cache"
    cdirs = [d for d in cache.iterdir() if d.is_dir()]
    check(len(cdirs) == 1, f"缓存目录数 {len(cdirs)}")
    lib = cdirs[0] / "_lib"
    check((lib / "packdemo_lib" / "__init__.py").is_file(),
          "纯 py 依赖没进 _lib")
    check((lib / "cdep" / "__stub_built__").is_file(),
          "源码依赖没编译进 _lib")
    check(calls["n"] == 1, f"首次编译被调 {calls['n']} 次（期望 1）")

    # ---------- [2] 缓存命中：不重复编译 ----------
    print("[2] 二次加载命中缓存:")
    PK._run_compile = counting_compile
    try:
        mgr2 = load_mods(g, loader1)
    finally:
        PK._run_compile = orig_run
    check(calls["n"] == 1, f"二次加载又编译了（期望还是 1，实际 {calls['n']}）")
    check("packdemo" in [c.name for c in mgr2.ctxs], "二次加载失败")

    # ---------- [3] 卸载清理 sys.path ----------
    print("[3] 卸载清理:")
    saved = [p for p in sys.path if str(lib) in p or str(cdirs[0]) in p]
    mgr2.unload()
    left = [p for p in sys.path if str(lib) in p or str(cdirs[0]) in p]
    check(len(saved) == 2 and len(left) == 0,
          f"sys.path 残留: {left}")

    # ---------- [4] 篡改拒载 ----------
    print("[4] 篡改文件 → 拒载:")
    raw = pack_path.read_bytes()
    zb = raw[len(PK.MAGIC):]
    zf = zipfile.ZipFile(io.BytesIO(zb))
    tampered_members = {}
    with zf:
        for n in zf.namelist():
            data = zf.read(n)
            if n == "main.py":
                data = data + b"\n# tampered"
            tampered_members[n] = data
    b2 = io.BytesIO()
    with zipfile.ZipFile(b2, "w", zipfile.ZIP_DEFLATED) as wz:
        for n, d in tampered_members.items():
            wz.writestr(n, d)
    loader2 = base / "ldr2"
    loader2.mkdir()
    (loader2 / "tampered.slmmod").write_bytes(PK.MAGIC + b2.getvalue())
    # M15d：篡改包 = pack 校验失败 → 加载直接 raise（不再记 failed）
    try:
        load_mods(g, loader2)
        check(False, "篡改包没被拒（M15d 要求 raise）")
    except Exception as e:
        check(True, f"篡改包 raise ✓ ({type(e).__name__})")

    # ---------- [5] 路径穿越 / API 版本 ----------
    print("[5] 路径穿越 / API 拒绝:")
    for fname, evil_key, api in (
            ("evil.slmmod", "../evil.txt", 1),
            ("api99.slmmod", "main.py", 99)):
        mf = {"format": "slmmod", "api": api, "name": "evil",
              "version": "1.0",
              "files": {evil_key: "0" * 64}}
        bb = io.BytesIO()
        with zipfile.ZipFile(bb, "w", zipfile.ZIP_DEFLATED) as wz:
            wz.writestr("manifest.json", json.dumps(mf))
            if evil_key == "../evil.txt":
                wz.writestr("../evil.txt", b"EVIL")
            else:
                wz.writestr("main.py", b"x")
        ld = base / f"ldr_{fname}"
        ld.mkdir()
        (ld / fname).write_bytes(PK.MAGIC + bb.getvalue())
        # M15d：路径穿越 / API 版本不符 → 直接 raise
        try:
            load_mods(g, ld)
            check(False, f"{fname} 没抛异常（M15d 要求 raise）")
        except Exception:
            check(True, f"{fname} raise ✓")
        check(not any(Path(p).name == "evil.txt"
                      for p in Path(base).rglob("evil.txt")),
              "路径穿越落地了？!")

    # ---------- [6] 同名目录优先 ----------
    print("[6] 同名目录 mod 优先:")
    loader3 = base / "ldr3"
    (loader3 / "packdemo").mkdir(parents=True)
    (loader3 / "packdemo" / "mod.json").write_text(
        '{"name": "packdemo", "version": "2.0", "description": "dir"}',
        encoding="utf-8")
    (loader3 / "packdemo" / "main.py").write_text("MARK='dir'\n",
                                                  encoding="utf-8")
    shutil.copy2(pack_path, loader3 / "packdemo.slmmod")
    mgr5 = load_mods(g, loader3)   # 同名包被静默忽略（M15d：这不是错误）
    check(mgr5.failed == [], "failed 应恒为空")
    pd5 = next((c for c in mgr5.ctxs if c.name == "packdemo"), None)
    pd5_main = sys.modules.get(f"mod_{pd5.name}_main") if pd5 else None
    check(getattr(pd5_main, "MARK", None) == "dir",
          "目录版 packdemo 没优先加载")

    # ---------- [7] 真实 pip 编译（有 pip 时跑一遍真流程） ----------
    print("[7] 真实编译（若可用）:")
    if _pip_ok():
        loader4 = base / "ldr4"
        loader4.mkdir()
        shutil.copy2(pack_path, loader4 / "packdemo.slmmod")
        try:
            PK._run_compile = PK._run_compile  # 真实现
            mgr6 = load_mods(g, loader4)
        finally:
            pass
        ok6 = ("packdemo" in [c.name for c in mgr6.ctxs]
               and any((d / "_lib" / "cdep" / "__init__.py").is_file()
                       for d in (loader4 / "_cache").iterdir() if d.is_dir()))
        check(ok6, f"真实 pip 编译失败: {[m for _, m in mgr6.failed]}")
        print("     真实 pip 编译 ✓"
              if ok6 else "     真实 pip 编译 ✗")
    else:
        print("     无 pip，跳过真实编译路径")

    print()
    if bad:
        print(f"FAIL {bad} 项: _packcheck")
        return 1
    print("PASS 单文件包全部通过")
    print(f"  缓存目录: {cache}")
    shutil.rmtree(base, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())