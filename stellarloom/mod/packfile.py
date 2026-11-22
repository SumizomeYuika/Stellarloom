"""M12：mod 单文件包（.slmmod）——格式、验签、解压、依赖处理。

格式：`b"SLMMOD\\x01"`（8 字节魔数）+ 一个标准 ZIP。
ZIP 内第一项必须是 `manifest.json`：
  {
    "format": "slmmod",
    "api": 1,                      # 必须 == stellarloom.api.API_VERSION
    "name", "version", "description",
    "files": { "包内相对路径": "sha256 hex", ... },   # 全员清单（验签依据）
    "libs": { "名字": "libs/xxx" },                  # 纯 py：目录/.whl/.py
    "libs_src": { "名字": "libs_src/xxx.tar.gz" },   # 需编译：只带源码
  }

安全规则：
- 解压只信 manifest.files：路径规范化后必须留在包内（拒绝绝对路径/../\\），
  逐个校验 sha256，任何一个不匹配即判失败并删除整包缓存。
- 依赖 .whl 解压同样做路径防穿越检查。
- 游戏【不联网】下载依赖：libs/lib_src 必须自带（pack_cli 负责收进包）。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from ..api import API_VERSION

MAGIC = b"SLMMOD\x01"
PACK_EXT = ".slmmod"
MAX_PACK_BYTES = 256 * 1024 * 1024   # 单包解压上限，防 zip 炸弹


class PackError(Exception):
    """包格式/验签/解压错误（只影响该 mod）。"""


def _norm_zip_path(name: str) -> str:
    """zip 内成员名 → 规范化相对路径（反斜杠转正；拒绝穿越/绝对）。"""
    parts = name.replace("\\", "/").split("/")
    if any(p in ("..", "") for p in parts):
        raise PackError(f"非法路径: {name!r}")
    return "/".join(parts)


def read_pack_bytes(path: Path) -> bytes:
    """读 .slmmod 原始字节（校验魔数）。"""
    if len(path.read_bytes()) < len(MAGIC):
        raise PackError(f"{path.name}: 不是 slmmod（太短）")
    data = path.read_bytes()
    if not data.startswith(MAGIC):
        raise PackError(f"{path.name}: 魔数缺失（不是 slmmod 或已损坏）")
    return data[len(MAGIC):]


def load_manifest(path: Path) -> tuple[dict, bytes]:
    """返回 (manifest, zip_bytes)。只读不落盘。"""
    zip_bytes = read_pack_bytes(path)
    if len(zip_bytes) > MAX_PACK_BYTES:
        raise PackError(f"{path.name}: 包超过 {MAX_PACK_BYTES} 字节上限")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    with zf:
        try:
            m = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError:
            raise PackError(f"{path.name}: 缺 manifest.json") from None
        except Exception as e:
            raise PackError(f"{path.name}: manifest.json 解析失败: {e}") from None
    if not isinstance(m, dict) or m.get("format") != "slmmod":
        raise PackError(f"{path.name}: manifest.format 不是 slmmod")
    if int(m.get("api", -1)) != API_VERSION:
        raise PackError(
            f"{path.name}: API 版本 {m.get('api')} 不匹配（需要 {API_VERSION}）")
    return m, zip_bytes


def _verify_and_extract(m: dict, zip_bytes: bytes, dest: Path) -> None:
    """按 manifest.files 逐个解压 + sha256 校验。任何失败 → 清缓存目录抛错。"""
    files = m.get("files") or {}
    if not isinstance(files, dict) or not files:
        raise PackError("manifest.files 缺失或为空")
    # 规定：成员名必须在 files 里，files 的键必须真实存在（两次都查）；
    # manifest.json 本身不算（它是描述文件不是内容）
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {_norm_zip_path(n) for n in zf.namelist()
             if not n.endswith("/")}
    payload = names - {"manifest.json"}
    if any(k not in names for k in files):
        raise PackError("manifest.files 里有包内不存在的文件")
    if any(n not in files for n in payload):
        raise PackError("包内有 manifest 未声明的文件（拒绝）")
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zf:
            for rel, want_hash in files.items():
                info = zf.getinfo(rel)
                if info.file_size > MAX_PACK_BYTES:
                    raise PackError(f"{rel}: 超过解压上限")
                data = zf.read(rel)
                got = hashlib.sha256(data).hexdigest()
                if got != want_hash:
                    raise PackError(f"{rel}: sha256 不一致（包被篡改）")
                out = (dest / rel)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
    except PackError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise PackError(f"解压失败: {type(e).__name__}: {e}") from None


def _safe_extract_whl(wheel_path: Path, lib_dir: Path) -> None:
    """.whl 本质 zip：解到 _lib/（防穿越）。"""
    with zipfile.ZipFile(wheel_path) as zf:
        for info in zf.infolist():
            rel = _norm_zip_path(info.filename)
            out = (lib_dir / rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(info))


def install_libs(dest: Path, m: dict) -> Path | None:
    """把包的依赖装进 dest/_lib/，返回 _lib 目录（没有依赖返回 None）。

    - libs/*：纯 Python —— 目录整体拷入 / .whl 解入 / 单 .py 拷入。
    - libs_src/*：源码 tar.gz —— 首次编译（pip install --no-index --no-deps
      --target _lib），失败抛 PackError（该 mod 记 failed，不连累别人）。
    """
    libs = m.get("libs") or {}
    libs_src = m.get("libs_src") or {}
    if not libs and not libs_src:
        return None
    lib_dir = dest / "_lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    for name, rel in sorted(libs.items()):
        src = dest / rel
        if not src.exists():
            raise PackError(f"lib {name}: {rel} 不存在")
        if src.suffix == ".whl":
            _safe_extract_whl(src, lib_dir)
        elif src.is_dir():
            # 包目录整体 vendoring：保持顶层包名 _lib/<src.name>/...
            for p in src.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    out = lib_dir / src.name / p.relative_to(src)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, out)
        else:
            out = lib_dir / src.name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)

    for name, rel in sorted(libs_src.items()):
        src = dest / rel
        if not src.exists() or not src.name.endswith(".tar.gz"):
            raise PackError(f"lib_src {name}: {rel} 不是 .tar.gz")
        build = dest / "_build" / name
        if build.exists():
            shutil.rmtree(build)
        build.mkdir(parents=True, exist_ok=True)
        with tarfile.open(src, "r:gz") as tf:
            # tar 防穿越：拒绝 .. / 绝对路径成员
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                nm = _norm_zip_path(member.name)
                # sdist 惯例带一个顶层目录（cdep-1.0/...）：剥掉它，
                # 让 setup.py 落在 build 根（pip/setup.py 都按根找）
                parts = nm.split("/")
                nm = "/".join(parts[1:]) if len(parts) > 1 else nm
                out = build / nm
                out.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(member)
                if f is not None:
                    out.write_bytes(f.read())
        # 编译：pip 本地离线装进 _lib（无网；纯 py 源码包也一样走这条）
        _run_compile(name, build, lib_dir)
    return lib_dir


def _run_compile(name: str, build: Path, lib_dir: Path) -> None:
    """把源码目录离线编译/安装进 _lib。两条路，都失败抛 PackError：
    1) pip install --no-index --no-deps --no-build-isolation --target
       （--no-build-isolation 关键：不联网拉构建依赖，用运行时自带 setuptools）
    2) 旧式 setup.py build_ext --inplace，然后把产物（包目录/.so/.pyd/.py）
       拷进 _lib（无 pip / 无网络环境兜底）。
    """
    pip_args = [sys.executable, "-m", "pip", "install",
                "--no-index", "--no-deps", "--no-build-isolation",
                "--target", str(lib_dir), str(build)]
    try:
        if subprocess.call(pip_args, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0:
            return
    except OSError:
        pass
    # 兜底：直接 setup.py build_ext --inplace
    try:
        r = subprocess.call(
            [sys.executable, "setup.py", "build_ext", "--inplace"],
            cwd=str(build), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        if r != 0:
            raise PackError(f"lib_src {name}: 编译失败（pip/旧式均失败，"
                            f"退出码 {r}）——需要编译环境")
    except OSError as e:
        raise PackError(
            f"lib_src {name}: 无法运行 pip 编译（{e}）——需要编译环境") from None
    # 收集产物：build 根下除构建元数据外的包目录与二进制/脚本
    for p in sorted(build.iterdir()):
        nm = p.name
        if nm in ("build", "dist", "__pycache__") or nm.endswith(".egg-info"):
            continue
        if p.is_dir():
            out = lib_dir / nm
            shutil.copytree(p, out,
                            ignore=shutil.ignore_patterns("__pycache__"))
        elif p.suffix in (".py", ".so", ".pyd"):
            shutil.copy2(p, lib_dir / nm)