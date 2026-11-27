"""MOD 加载器（M6.27 + M6.29 + M12）。

扫描 `mods/<名字>/`（默认项目根 mods/ 目录）：
  mod.json（必须）—— {name, version, description, dependencies?}
  main.py（可选）  —— on_load(ctx) / on_unload(ctx)
  config.json（可选，M6.29）—— 作者提供的默认配置（JSON 对象）

M12 新增：
- **单文件包**：`mods/*.slmmod`（自创格式：魔数 + ZIP + manifest.json），
  启动自动验签解压到 `mods/_cache/<name>__<ver>__<hash8>/`；
  纯 Python 依赖从 `libs/` 装进 `_lib/` 挂 sys.path；需编译依赖
  （`libs_src/*.tar.gz`）首次加载自动 `pip install --no-index --no-deps
  --target` 编译并缓存，失败直接 raise（M15d）。
- 解压目录以 `_` 开头 → 不作为普通目录 mod 扫描；`mods/<同名>/` 目录 mod
  优先于同名包。

M6.29 新增：
- **统一 config 存/写**：mod 包内 config.json = 作者默认；运行期
  `ctx.cfg` 读写合并后的配置，`ctx.save_config()` 把用户配置写到
  `mods/config/<名字>.json`（独立于 mod 包，卸载/重载不清、重启保持）。
- **依赖关系**：mod.json 的 `dependencies`：`{"别的mod名字": ">=1.0"}`，
  版本表达式支持 > / >= / == / < / <=（裸数字 = 精确；空串/缺省 = 任意）。
  按依赖拓扑序加载；缺依赖 / 版本不满足 / 依赖环 / 依赖者加载失败 →
  直接抛异常（M15d），加载中断，交给 crash_guard 写崩溃报告。

原则（M15d 改版）：
- **出错即崩**：单个 mod（清单坏 / main.py 语法错 / on_load 抛错 / mixin
  目标不存在 / 依赖不满足 / 依赖环 / 包校验失败）一律 raise，不做失败
  隔离、不吞异常——崩溃报告由 crash_guard mod 兜底。
  `self.failed` 属性保留（恒为空 list）仅为兼容读它的旧代码。
- 非永久：mixin 补丁只动内存，卸载/重载时还原原方法（源码零改动）。
- 确定性：同一层依赖按目录名排序加载；同一 mod 可重复 load（先卸载旧的）。
- 侧标（M15d）：`side="server"`（headless 服务端）跳过一切
  @EnvType("client") 的 mixin 类/方法/on_load；"client" 侧反之。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
from collections import deque
from pathlib import Path

from ..api import (ModAPIError, ModContext, collect_mixins, env_ok,
                   load_main_module)
from . import packfile as PK

MODS_DIR = Path(__file__).resolve().parent.parent.parent / "mods"

# M15d：同进程同一时刻只允许一个 ModManager 处于"已加载"状态。
# 真实游戏只有一个 Game；自检脚本会在一个进程里建多个 Game——后建的
# load_all 会先把前一个管理器的 mod 卸载干净（注册表/mixin 全局态还原），
# 否则第二次加载会因 id 冲突崩掉（那不是 mod 的错，是生命周期没闭环）。
_ACTIVE: "ModManager | None" = None


class ModManager:
    def __init__(self, game, mods_dir: Path | str | None = None,
                 side: str = "client"):
        self.game = game
        self.mods_dir = Path(mods_dir) if mods_dir else MODS_DIR
        self.side = side   # "client"（游戏前端）/ "server"（headless 服务端）
        self.ctxs: list[ModContext] = []
        # M15d：加载出错直接 raise，failed 恒空（仅兼容 status_of 等旧读取方）
        self.failed: list[tuple[str, str]] = []
        self._disabled: set[str] = set()          # M6.28：禁用名单

    # ---------- M12：.slmmod 单文件包 ----------

    def _unpack_packs(self):
        """mods/*.slmmod → 验签 → 解压到缓存 + 装依赖。失败直接 raise（M15d）。"""
        d = self.mods_dir
        cache = d / "_cache"
        cache.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for p in sorted(d.glob(f"*{PK.PACK_EXT}")):
            m, zb = PK.load_manifest(p)
            name = str(m.get("name") or "").strip()
            if not name:
                raise PK.PackError(f"{p.name}: manifest 缺 name")
            # 同名目录 mod 优先：包直接跳过（不浪费编译）
            if (d / name).is_dir():
                self.log(f"{p.name}: 存在同名目录 mod，单文件包被忽略")
                continue
            v = str(m.get("version") or "0.0")
            h8 = hashlib.sha256(zb).hexdigest()[:8]
            dest = cache / f"{name}__{v}__{h8}"
            if not (dest / ".ok").is_file():
                PK._verify_and_extract(m, zb, dest)
                lib_dir = PK.install_libs(dest, m)
                (dest / ".ok").write_text(
                    json.dumps({"api": m.get("api")}), encoding="utf-8")
            else:
                lib_dir = dest / "_lib" if (dest / "_lib").is_dir() else None
            used.add(dest.name)
            self._pack_named[name] = {
                "dir": str(dest), "lib_dir": str(lib_dir) if lib_dir else None,
            }
        # 清理不再被引用的旧缓存（换版本/删包后不残留）
        for c in sorted(cache.iterdir()):
            if c.is_dir() and c.name not in used:
                shutil.rmtree(c, ignore_errors=True)

    def _collect_meta(self, sub: Path) -> dict | None:
        """读一个目录（普通 mod 或包解压目录）的 mod.json → meta。"""
        if not (sub / "mod.json").is_file():
            return None   # 没有 mod.json 的目录不是 mod
        try:
            meta = json.loads(
                (sub / "mod.json").read_text(encoding="utf-8"))
        except Exception as e:
            raise ModAPIError(
                f"{sub.name}: mod.json 读取失败: {type(e).__name__}: {e}"
            ) from None
        name = str(meta.get("name") or "").strip()
        if not name:
            raise ModAPIError(f"{sub.name}: mod.json 缺 name")
        deps = meta.get("dependencies") or {}
        if not isinstance(deps, dict):
            raise ModAPIError(f"{sub.name}: dependencies 必须是 dict")
        # M13：可选入口字段：main（默认 main.py）、mixins（混入文件列表）
        main_rel = meta.get("main", "main.py")
        mixins = meta.get("mixins", [])
        if not isinstance(main_rel, str) or not main_rel:
            raise ModAPIError(f"{sub.name}: main 必须是非空字符串")
        if (not isinstance(mixins, list)
                or any(not isinstance(x, str) for x in mixins)):
            raise ModAPIError(f"{sub.name}: mixins 必须是字符串数组")
        for rel in [main_rel, *mixins]:
            if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
                raise ModAPIError(f"{sub.name}: 入口路径非法: {rel!r}")
        # M15d：环境侧标声明在 mod.json 里（"client"/"server"/"both"）。
        # 关键：服务端在 **import main.py 之前**就能跳过纯前端 mod——
        # 否则 crash_guard/jade 这类 on_load 里 import Game 的 mod 会直接
        # ModuleNotFoundError（服务端包里没有 pygame/core.game）。
        env = str(meta.get("env") or "both").strip().lower()
        if env not in ("client", "server", "both"):
            raise ModAPIError(
                f"{sub.name}: env 必须是 client/server/both，收到 {env!r}")
        return {
            "name": name,
            "version": str(meta.get("version") or "0.0"),
            "dir": sub,
            "dependencies": {str(k): str(v) for k, v in deps.items()},
            "main": main_rel,
            "main_explicit": "main" in meta,
            "mixins": mixins,
            "env": env,
            "lib_dir": None,
        }

    # ---------- 生命周期 ----------

    def load_all(self, progress=None) -> "ModManager":
        global _ACTIVE
        # 同进程已有另一个管理器挂着 mod → 先卸载它（全局注册表/mixin 归位），
        # 保证本次加载面对干净的全局态（真实游戏单 Game 时这是 no-op）
        if _ACTIVE is not None and _ACTIVE is not self and _ACTIVE.ctxs:
            self.log(f"卸载上一个管理器的 {len(_ACTIVE.ctxs)} 个 mod")
            _ACTIVE.unload()
        self.unload()
        # M15d：在 import 任何 mod 之前公布本侧，mod 顶层可按 current_side()
        # 决定是否 import pygame/render/ui（服务端没有这些模块）
        from ..api import set_side
        set_side(self.side)
        self._disabled = self._read_disabled()
        d = self.mods_dir
        if not d.is_dir():
            return self
        # M12：先解 .slmmod 单文件包（验签→缓存目录→装依赖）
        self._pack_named: dict[str, dict] = {}
        self._unpack_packs()
        # 1) 收集全部 mod 元数据（坏清单此时直接 raise）
        metas: dict[str, dict] = {}
        for sub in sorted(p for p in d.iterdir() if p.is_dir()):
            if sub.name.startswith(("_", ".")):
                continue   # _cache 等内部目录不是 mod
            m = self._collect_meta(sub)
            if m is not None:
                metas[sub.name] = m
        # 包解压目录也参与（key=缓存目录名，唯一）
        for name, pinfo in sorted(self._pack_named.items()):
            m = self._collect_meta(Path(pinfo["dir"]))
            if m is not None:
                m["lib_dir"] = pinfo.get("lib_dir")
                m["pack_dir"] = pinfo["dir"]   # M13：无依赖的包也要记
                metas[Path(pinfo["dir"]).name] = m
        # 1.5) M15d：按 mod.json 的 env 侧标先剔掉不属于本侧的 mod。
        # 必须在 import main.py 之前做：纯前端 mod 的 on_load 会 import
        # Game/pygame，服务端包里根本没有这些东西。
        skipped = []
        for dir_name in list(metas):
            env = metas[dir_name].get("env", "both")
            if env != "both" and env != self.side:
                skipped.append((metas[dir_name]["name"], env))
                del metas[dir_name]
        for nm, env in skipped:
            self.log(f"侧标 {env}，本侧 {self.side} 跳过 {nm}")
        # 2) 依赖拓扑序（禁用的不参与；环 → raise）
        order, cycle = _topo(metas, self._disabled)
        if cycle:
            raise ModAPIError("依赖环：" + " → ".join(cycle))
        # 3) 依序加载 + 依赖门禁（任何不满足 → raise，M15d 不再隔离）
        loaded: dict[str, str] = {}   # mod name -> version（仅成功加载者）
        total = len(order)
        for idx, dir_name in enumerate(order):
            meta = metas[dir_name]
            for dep, expr in meta["dependencies"].items():
                if dep not in loaded:
                    raise ModAPIError(
                        f"{dir_name}: 缺少依赖 {dep}"
                        + (f" ({expr})" if expr else ""))
                if expr and not _ver_match(loaded[dep], expr):
                    raise ModAPIError(
                        f"{dir_name}: 依赖 {dep} 版本 {loaded[dep]} "
                        f"不满足 {expr}")
            # M13：加载界面回调（mod 名、第几个、总数）
            if progress is not None:
                try:
                    progress(meta["name"], idx + 1, total)
                except Exception:
                    pass   # 进度回调不许炸加载
            self._load_one(sub=meta["dir"], meta=meta)
            loaded[meta["name"]] = meta["version"]
        _ACTIVE = self
        return self

    # ---------- M6.28 启用/禁用（仿 minecraft 的 mod 管理） ----------

    def available(self) -> list[str]:
        """mods_dir 下全部 mod 目录名（含禁用的，含加载失败的）。"""
        d = self.mods_dir
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir()
                      if p.is_dir() and (p / "mod.json").is_file())

    def is_disabled(self, name: str) -> bool:
        return name in self._disabled

    def status_of(self, name: str) -> str:
        """mod 名 → 状态文案：已禁用 / 已加载 / 加载失败+原因 / 未加载。"""
        if name in self._disabled:
            return "已禁用"
        if any(c.name == name for c in self.ctxs):
            return "已加载"
        for fname, err in self.failed:
            if fname == name:
                return f"加载失败：{err}"
        return "未加载"

    def set_disabled(self, name: str, disabled: bool) -> "ModManager":
        """开/关一个 mod（写 mods/.disabled 名单并热重载其余 mod）。"""
        if disabled:
            self._disabled.add(name)
        else:
            self._disabled.discard(name)
        self._write_disabled(self._disabled)
        # M15d：热重载出错同样直接崩（不吞），crash_guard 兜底
        self.load_all()
        return self

    def _disabled_file(self) -> Path:
        return self.mods_dir / ".disabled"

    def _read_disabled(self) -> set[str]:
        try:
            return {s.strip() for s in
                    self._disabled_file().read_text(encoding="utf-8").splitlines()
                    if s.strip()}
        except OSError:
            return set()

    def _write_disabled(self, names: set[str]):
        try:
            self._disabled_file().parent.mkdir(parents=True, exist_ok=True)
            self._disabled_file().write_text(
                "\n".join(sorted(names)) + ("\n" if names else ""),
                encoding="utf-8")
        except OSError:
            self.log("无法写 mods/.disabled（禁用名单未持久化）")

    def _load_one(self, sub: Path, meta: dict):
        """加载单个 mod。M15d：任何出错直接向上抛（不隔离、不吞异常，
        崩溃报告交给 crash_guard）。"""
        name = meta["name"]
        version = meta["version"]
        desc = str(meta.get("description") or "")
        ctx = ModContext(name, version, desc, self.game)
        ctx._sim = _sim_of(self.game)
        ctx._side = self.side   # M15d：@EnvType 侧标过滤用
        # M12：单文件包 → 挂资源目录 + _lib 依赖进 sys.path（目录 mod 不变）
        pack_dir = meta.get("pack_dir")
        lib_dir = meta.get("lib_dir")
        if pack_dir:
            ctx._mod_dir = Path(pack_dir)   # 无依赖的包也有资源目录
        if lib_dir:
            ctx._lib_dir = Path(lib_dir)
            for p in (str(Path(meta["dir"])), str(lib_dir)):
                if p not in sys.path:
                    sys.path.insert(0, p)
        # M6.29 统一配置：作者默认 config.json + 用户 mods/config/<name>.json
        cfg_dir = self.mods_dir / "config"
        ctx._cfg_dir = cfg_dir
        defaults: dict = {}
        if (sub / "config.json").is_file():
            try:
                defaults = json.loads(
                    (sub / "config.json").read_text(encoding="utf-8"))
            except Exception as e:
                raise ModAPIError(
                    f"{name}: 作者 config.json 解析失败: {e}") from None
            if not isinstance(defaults, dict):
                raise ModAPIError(f"{name}: config.json 必须是 JSON 对象")
            ctx._cfg_has_default = True
        user: dict = {}
        user_path = cfg_dir / f"{name}.json"
        if user_path.is_file():
            try:
                user = json.loads(
                    user_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ModAPIError(
                    f"{name}: 用户配置 {user_path} 解析失败: {e}") from None
            if not isinstance(user, dict):
                raise ModAPIError(
                    f"{name}: 用户配置必须是 JSON 对象")
        ctx._cfg = {**defaults, **user}
        # M13：mixins 文件先加载（main 之前），逐个收 @Mixin 类
        for i, rel in enumerate(meta.get("mixins") or []):
            mp = sub / rel
            if not mp.is_file():
                raise ModAPIError(f"{name}: mixins 文件不存在: {rel}")
            mm = load_main_module(f"{name}__mx{i}", mp)
            for mixin_cls in collect_mixins(mm):
                ctx.apply_mixin_class(mixin_cls)
        main_rel = meta.get("main") or "main.py"
        main_path = sub / main_rel
        if main_path.is_file():
            main_mod = load_main_module(name, main_path)
            # M7：@Mixin 注解类自动收集应用（on_load 之前注册即生效）
            for mixin_cls in collect_mixins(main_mod):
                ctx.apply_mixin_class(mixin_cls)
            on_load = getattr(main_mod, "on_load", None)
            # M15d：@EnvType("client") 的 on_load 在服务端整段跳过（反之亦然）
            if on_load is not None and env_ok(on_load, self.side):
                on_load(ctx)
            elif on_load is not None:
                self.log(f"{name}: on_load 侧标 "
                         f"{getattr(on_load, '_slm_env', '?')}，"
                         f"本侧 {self.side} 跳过")
        elif meta.get("main_explicit"):
            raise ModAPIError(
                f"{name}: mod.json 指定的入口 {main_rel} 不存在")
        elif meta.get("mixins"):
            pass   # 只有 mixin 文件、没有 main 也合法（纯补丁 mod）
        self.ctxs.append(ctx)
        print(f"[mod] 加载 {name} v{version}"
              + (f" —— {desc}" if desc else ""))

    def unload(self):
        global _ACTIVE
        for ctx in reversed(self.ctxs):
            self._unload_one(ctx)
        self.ctxs.clear()
        if _ACTIVE is self:
            _ACTIVE = None

    def _unload_one(self, ctx: ModContext):
        try:
            mname = f"mod_{ctx.name}_main"
            main_mod = importlib.import_module(mname)
            on_unload = getattr(main_mod, "on_unload", None)
            if on_unload is not None:
                on_unload(ctx)
        except Exception as e:
            self.log(f"{ctx.name} on_unload 出错: {type(e).__name__}: {e}")
        ctx._unload()   # 还原全部 mixin 补丁
        # M12：包 mod 摘掉自己挂进的 sys.path，避免二次加载残留
        if ctx._lib_dir is not None:
            for p in (str(ctx._mod_dir), str(ctx._lib_dir)):
                if p in sys.path:
                    sys.path.remove(p)

    # ---------- 每帧钩子（Game 转发） ----------

    def step(self, dt: float):
        for ctx in self.ctxs:
            for fn in ctx._step_fns:
                try:
                    fn(dt)
                except Exception as e:
                    self.log(f"{ctx.name} on_step 出错: {type(e).__name__}: {e}")

    def emit(self, event: tuple):
        for ctx in self.ctxs:
            for fn in ctx._event_fns:
                try:
                    fn(event)
                except Exception as e:
                    self.log(f"{ctx.name} on_event 出错: {type(e).__name__}: {e}")

    # ---------- 工具 ----------

    def log(self, msg: str):
        print(f"[mod] {msg}")


def load_mods(game, mods_dir=None, progress=None, side="client") -> ModManager:
    """扫描并加载 mods。M15d：任何 mod 出错直接 raise（崩溃即真相，
    crash_guard 负责写报告）；side="server" 时跳过 @EnvType("client")
    的 mixin/on_load（headless 服务端不装 UI 补丁）。

    progress(name, i, total)：M13 加载界面的逐项进度回调（可选）。
    """
    return ModManager(game, mods_dir, side=side).load_all(progress=progress)


def _sim_of(game):
    return getattr(game, "sim", None) if game is not None else None


# ---------- M6.29 依赖解析 ----------

def _parse_ver(v) -> tuple:
    """"1.2.3" → (1,2,3)；比不出数字的当 (0,)。"""
    parts = re.findall(r"\d+", str(v))
    return tuple(int(x) for x in parts) or (0,)


def _ver_match(installed: str, expr: str) -> bool:
    """installed 版本是否满足表达式（>=、>、==、<、<=，裸数字=精确）。"""
    m = re.match(r"^(>=|<=|>|<|==)?\s*(\S+)$", expr.strip())
    op = m.group(1) or "=="
    want = m.group(2)
    a, b = _parse_ver(installed), _parse_ver(want)
    c = (a > b) - (a < b)
    return {
        "==": c == 0, ">": c > 0, "<": c < 0,
        ">=": c >= 0, "<=": c <= 0,
    }[op]


def _topo(metas: dict, disabled: set) -> tuple[list[str], list[str]]:
    """依赖拓扑序（Kahn）。返回 (按目录名的加载顺序, 环上 mod 名字)。
    禁用的 mod 不参与排序——依赖它们的会在加载门禁里判"缺少依赖"。"""
    name2dir = {m["name"]: d for d, m in metas.items()}
    enabled_dirs = [d for d in metas
                    if d not in disabled
                    and metas[d]["name"] not in disabled]
    deg: dict[str, int] = {}
    children: dict[str, list[str]] = {}
    for d in enabled_dirs:
        deps = [dv for dv in metas[d]["dependencies"]
                if dv in name2dir
                and name2dir[dv] not in disabled
                and dv not in disabled]
        deg[metas[d]["name"]] = len(deps)
        for dv in deps:
            children.setdefault(dv, []).append(metas[d]["name"])
    q = deque(sorted(n for n, k in deg.items() if k == 0))
    order: list[str] = []
    while q:
        n = q.popleft()
        order.append(name2dir[n])
        for c in sorted(children.get(n, [])):
            deg[c] -= 1
            if deg[c] == 0:
                q.append(c)
    # 环上节点（Kahn 结束后仍有剩余度的）：order 里存的是目录名，比较要看目录名
    cycle = [metas[d]["name"] for d in enabled_dirs
             if d not in order]
    return order, cycle