#!/usr/bin/env python3
"""M15c 专用服务端打包器：从仓库源码自动生成独立服务端包。

产物（默认 dist/server/，--zip 再打成一个压缩包）：

    server/
      run_server.py            # 启动入口（等价 python -m stellarloom.net.server）
      stellarloom/             # 仅逻辑层包（config/registry/api/data/sim/world/
                               #   logistics/production/power/tech/save/mod/net/
                               #   core/worldstate.py + render/camera.py）
      mods/                    # 可选（--pack-mods）：跳过缓存/配置/__pycache__
      VERSION.txt              # 游戏版本 + SAVE_VERSION + 构建时间
      README.txt

**依赖闭包是硬检查**：打包时静态扫描全部 .py 的 import，凡 import 到包外的
stellarloom 子模块 → 失败；文件里出现 pygame → 失败（服务端必须零图形依赖）。
这样"逻辑层意外依赖渲染"会在构建期被拦住，而不是发到手机上才炸。

用法：
    python tools/build_server.py [--out dist/server] [--zip] [--pack-mods]
    python tools/build_server.py --check-only      # 只跑闭包检查，不落盘
"""

from __future__ import annotations

import argparse
import ast
import json
import py_compile
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "stellarloom"

# 服务端需要的包/文件（相对 stellarloom/）
#
# M15d 修正：**也收客户端模块**（render/ui/input/core.game）。原因：
# mod 顶层 `from stellarloom.render.layers import ChunkRenderer` 是正常写法
# （gregtech 就这么写），服务端包里没有这些模块 → 加载 mod 时
# ModuleNotFoundError。用户的规则是"mod 闯的祸不救"，但"包里缺模块"
# 是服务端打包的问题，得修。
# 真正的"逻辑层不许依赖 pygame"靠 check_closure 的 LOGIC_PREFIXES 守着，
# 不靠"文件不在包里"。
INCLUDE = [
    "__init__.py",
    "config.py",
    "registry.py",
    "api.py",
    "data/",
    "sim/",
    "world/",
    "logistics/",
    "production/",
    "power/",
    "tech/",
    "save/",
    "mod/",
    "net/",
    "core/",
    "render/",
    "ui/",
    "input/",
]

# 逻辑层：这些目录/文件**绝对不许** import pygame（headless 服务端要能跑）
LOGIC_PREFIXES = ("sim/", "world/", "logistics/", "production/", "power/",
                  "tech/", "save/", "mod/", "net/", "config.py", "api.py",
                  "registry.py", "core/worldstate.py", "core/errfmt.py")

_SKIP_DIRS = {"__pycache__", ".git", "_cache", ".idea", ".vscode"}
_SKIP_SUFFIX = {".pyc", ".pyo", ".DS_Store"}


def _collect_files() -> dict[str, bytes]:
    """按 INCLUDE 清单收集源码（相对 stellarloom/ 的路径 → 字节）。"""
    out: dict[str, bytes] = {}
    for entry in INCLUDE:
        p = SRC / entry
        if p.is_file():
            out[entry] = p.read_bytes()
            continue
        if not p.is_dir():
            raise SystemExit(f"build_server: 清单项不存在 {entry}")
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            if f.suffix in _SKIP_SUFFIX:
                continue
            # 目录项收全部文件（data/ 下有 recipes.json 这类非 .py 资源）
            rel = f.relative_to(SRC).as_posix()
            out[rel] = f.read_bytes()
    return out


def check_closure(files: dict[str, bytes]) -> list[str]:
    """静态依赖闭包检查。返回问题列表（空 = 通过）。

    规则：
    - 文件里出现 pygame 字样 → 拒绝（服务端零图形依赖）
    - import 的 stellarloom 子模块必须都在包内（防漏收文件）
    - py_compile 每个文件（语法问题立刻现形）
    """
    problems: list[str] = []
    have = {"stellarloom." + rel[:-3].replace("/", ".")
            for rel in files if rel.endswith(".py")}
    have |= {m[:-len(".__init__")] for m in list(have)
             if m.endswith(".__init__")}
    for rel, data in files.items():
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(data.decode("utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as e:
            problems.append(f"{rel}: 语法错误 {e}")
            continue
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    if (mod == "pygame" or mod.startswith("pygame.")) \
                            and _is_logic(rel):
                        problems.append(
                            f"{rel}: 逻辑层 import {mod}（服务端要 headless）")
                    _check_mod(mod, rel, have, problems)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue          # 相对 import 一定在包内
                mod = node.module or ""
                if (mod == "pygame" or mod.startswith("pygame.")) \
                        and _is_logic(rel):
                    problems.append(
                        f"{rel}: 逻辑层 from {mod} import ...（服务端要 headless）")
                _check_mod(mod, rel, have, problems)
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            py_compile.compile(tmp.name, doraise=True)
        except py_compile.PyCompileError as e:
            problems.append(f"{rel}: 编译失败 {e}")
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    return problems


def _is_logic(rel: str) -> bool:
    """该文件是否属于"必须 headless"的逻辑层。"""
    return any(rel.startswith(p) or rel == p for p in LOGIC_PREFIXES)


def _check_mod(mod: str, rel: str, have: set[str], problems: list[str]):
    if not mod.startswith("stellarloom"):
        return
    if mod == "stellarloom":
        return
    if mod not in have:
        problems.append(f"{rel}: import {mod} 不在服务端包内")


def build(out_dir: Path, pack_mods: bool) -> Path:
    files = _collect_files()
    problems = check_closure(files)
    if problems:
        for p in problems[:10]:
            print(f"  !! {p}")
        raise SystemExit(f"build_server: 依赖闭包检查失败（{len(problems)} 项）")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    pkg_root = out_dir / "stellarloom"
    pkg_root.mkdir(parents=True)
    for rel, data in files.items():
        dest = pkg_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    # 入口
    (out_dir / "run_server.py").write_text(
        "#!/usr/bin/env python3\n"
        "\"\"\"StellarLoom 专用服务端入口（build_server.py 生成）。\"\"\"\n"
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
        "from stellarloom.net.server import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8")

    # 版本戳（直接文本解析，避免依赖当前进程的 sys.path）
    cfg_text = (SRC / "config.py").read_text(encoding="utf-8")
    sf_text = (SRC / "save" / "savefile.py").read_text(encoding="utf-8")
    title = next((ln.split("=", 1)[1].strip().strip('"')
                  for ln in cfg_text.splitlines()
                  if ln.startswith("TITLE")), "StellarLoom")
    save_ver = next((ln.split("=")[1].strip()
                     for ln in sf_text.splitlines()
                     if ln.startswith("SAVE_VERSION")), "?")
    (out_dir / "VERSION.txt").write_text(
        f"game={title}\nsave_version={save_ver}\n"
        f"built={time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "StellarLoom 专用服务端（build_server.py 自动生成）\n"
        "启动：python run_server.py --port 27715\n"
        "可选：--save <存档名> --save-dir <目录> --autosave 120\n"
        "      --mods-dir <mod目录> --no-mods --headless-check 600\n"
        "依赖：Python 3.11+ / numpy（不需要 pygame）\n",
        encoding="utf-8")

    # mod（可选）
    if pack_mods:
        mods_src = ROOT / "mods"
        mods_out = out_dir / "mods"
        copied = 0
        if mods_src.is_dir():
            for sub in sorted(p for p in mods_src.iterdir() if p.is_dir()):
                if sub.name.startswith(("_", ".")):
                    continue
                if not (sub / "mod.json").is_file():
                    continue
                dest = mods_out / sub.name
                shutil.copytree(
                    sub, dest,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "_cache", "*.pyc", ".disabled",
                        "config"))
                copied += 1
        print(f"[build] mods 打包 {copied} 个")
    return out_dir


def make_zip(out_dir: Path) -> Path:
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(out_dir.parent).as_posix())
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="StellarLoom 服务端打包器")
    ap.add_argument("--out", default=str(ROOT / "dist" / "server"))
    ap.add_argument("--zip", action="store_true", help="额外打 zip")
    ap.add_argument("--pack-mods", action="store_true", help="把 mods/ 一起打包")
    ap.add_argument("--check-only", action="store_true",
                    help="只跑依赖闭包检查，不落盘")
    args = ap.parse_args()

    if args.check_only:
        problems = check_closure(_collect_files())
        if problems:
            for p in problems[:10]:
                print(f"  !! {p}")
            return 1
        print("[build] 依赖闭包检查通过（未落盘）")
        return 0

    out = build(Path(args.out), args.pack_mods)
    print(f"[build] 服务端包 → {out}")
    if args.zip:
        print(f"[build] zip → {make_zip(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
