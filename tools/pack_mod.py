#!/usr/bin/env python3
"""M12 打包工具：把目录 mod 打包成单文件 .slmmod。

用法：
    python tools/pack_mod.py <mod源目录> -o out.slmmod \
        [--lib <纯py路径> ...] \
        [--lib-src <源码.tar.gz> ...] \
        [--api 1] [--check]

说明：
- <mod源目录> 必须含 mod.json（name/version 从它读）。
- --lib    每个 = 一个纯 Python 依赖（包目录 / .whl / 单 .py），
           打进包内 libs/，运行时自动挂 sys.path（无需编译）。
- --lib-src 每个 = 一个需编译依赖的源码 tar.gz（不含编译产物），
           打进包内 libs_src/，游戏首次加载自动 pip 编译并缓存。
- 游戏加载时不联网下载依赖——所有依赖必须包内自带。
- --check  打包完跑一遍自检（魔数/清单/hash/zip/tar/whl 完整性）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stellarloom.api import API_VERSION  # noqa: E402
from stellarloom.mod import packfile as PK  # noqa: E402

_SKIP_DIRS = {"__pycache__", ".git", ".vscode", "node_modules"}
_SKIP_SUFFIX = {".pyc", ".pyo", ".DS_Store"}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_files(root: Path) -> dict[str, bytes]:
    """收集源目录全部文件（相对正斜杠路径 → 字节）。"""
    out: dict[str, bytes] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(seg in _SKIP_DIRS for seg in rel.split("/")):
            continue
        if p.suffix in _SKIP_SUFFIX or p.name == "mods/_cache":
            continue
        out[rel] = p.read_bytes()
    return out


def _check_lib_path(path: Path, kind: str) -> None:
    if not path.exists():
        raise SystemExit(f"{kind} 不存在: {path}")
    if kind == "whl":
        try:
            with zipfile.ZipFile(path) as zf:
                if zf.testzip() is not None:
                    raise SystemExit(f"whl 损坏: {path}")
        except zipfile.BadZipFile:
            raise SystemExit(f"不是合法 whl: {path}") from None
    if kind == "tar.gz":
        try:
            with tarfile.open(path, "r:gz") as tf:
                for m in tf.getmembers():
                    if not m.isfile():
                        continue
                    parts = m.name.replace("\\", "/").split("/")
                    if any(seg in ("..", "") for seg in parts):
                        raise SystemExit(
                            f"tar.gz 里有非法路径 {m.name!r}: {path}")
        except tarfile.TarError:
            raise SystemExit(f"不是合法 tar.gz: {path}") from None


def pack(src_dir: Path, out: Path, libs: list[Path],
         lib_srcs: list[Path], api: int = API_VERSION,
         check: bool = True) -> dict:
    src_dir = src_dir.resolve()
    if not (src_dir / "mod.json").is_file():
        raise SystemExit(f"{src_dir} 缺 mod.json，不是目录 mod")
    mod_meta = json.loads((src_dir / "mod.json").read_text(encoding="utf-8"))
    name = str(mod_meta.get("name") or src_dir.name).strip()
    version = str(mod_meta.get("version") or "0.0")

    staging = Path(tempfile.mkdtemp(prefix="slmmod_"))
    try:
        # 1) 代码/资源
        files = _collect_files(src_dir)
        # 2) 纯 py 依赖 → libs/
        lib_manifest: dict[str, str] = {}
        for lp in libs:
            lp = lp.resolve()
            if lp.suffix == ".whl":
                _check_lib_path(lp, "whl")
                rel = f"libs/{lp.name}"
                files[rel] = lp.read_bytes()
                lib_manifest[lp.stem] = rel
            elif lp.is_dir():
                for f, data in _collect_files(lp).items():
                    files[f"libs/{lp.name}/{f}"] = data
                lib_manifest[lp.name] = f"libs/{lp.name}"
            else:
                rel = f"libs/{lp.name}"
                files[rel] = lp.read_bytes()
                lib_manifest[lp.stem] = rel
        # 3) 需编译源码 → libs_src/
        src_manifest: dict[str, str] = {}
        for sp in lib_srcs:
            sp = sp.resolve()
            _check_lib_path(sp, "tar.gz")
            rel = f"libs_src/{sp.name}"
            files[rel] = sp.read_bytes()
            src_manifest[sp.name.removesuffix(".tar.gz")] = rel

        manifest = {
            "format": "slmmod",
            "api": api,
            "name": name,
            "version": version,
            "description": str(mod_meta.get("description") or ""),
            "files": {k: _hash_bytes(v) for k, v in files.items()},
            "libs": lib_manifest,
            "libs_src": src_manifest,
        }

        # 4) 写魔数 + zip（manifest.json 第一个成员）
        out.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=1))
            for rel in sorted(files):
                zf.writestr(rel, files[rel])
        out.write_bytes(PK.MAGIC + buf.getvalue())

        if check:
            _self_check(out)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _self_check(p: Path) -> None:
    m, zb = PK.load_manifest(p)
    zf = zipfile.ZipFile(io.BytesIO(zb))
    with zf:
        if zf.testzip() is not None:
            raise SystemExit(f"self-check: {p} zip 损坏")
        for rel, want in m["files"].items():
            got = _hash_bytes(zf.read(rel))
            if got != want:
                raise SystemExit(f"self-check: {rel} hash 不符")
        # 依赖容器本身要有效（whl/tar.gz 能打开；纯 py 目录是散文件不校验）
        for rel in (list(m.get("libs", {}).values())
                    + list(m.get("libs_src", {}).values())):
            if not rel.endswith((".whl", ".tar.gz")):
                continue
            data = zf.read(rel)
            if rel.endswith(".whl"):
                with zipfile.ZipFile(io.BytesIO(data)) as wz:
                    if wz.testzip() is not None:
                        raise SystemExit(f"self-check: whl {rel} 损坏")
            elif rel.endswith(".tar.gz"):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz"):
                    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="slmmod 打包工具")
    ap.add_argument("src", help="目录 mod 源路径（含 mod.json）")
    ap.add_argument("-o", "--out", default=None, help="输出 .slmmod 路径")
    ap.add_argument("--lib", action="append", default=[],
                    help="纯 py 依赖：目录 / .whl / .py（可多次）")
    ap.add_argument("--lib-src", action="append", default=[],
                    help="需编译依赖源码 tar.gz（可多次）")
    ap.add_argument("--api", type=int, default=API_VERSION,
                    help=f"API 版本（默认 {API_VERSION}）")
    ap.add_argument("--no-check", action="store_true", help="跳过自检")
    args = ap.parse_args()

    out = Path(args.out) if args.out else Path(f"{Path(args.src).name}.slmmod")
    manifest = pack(Path(args.src), out,
                    [Path(x) for x in args.lib],
                    [Path(x) for x in args.lib_src],
                    api=args.api, check=not args.no_check)
    print(f"[pack] {out}  {out.stat().st_size} 字节  "
          f"文件 {len(manifest['files'])}  纯py {len(manifest['libs'])}  "
          f"待编译 {len(manifest['libs_src'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())