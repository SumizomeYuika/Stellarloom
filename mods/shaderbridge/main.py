"""ShaderBridge —— 让星织跑真正的 Minecraft 光影包。

设计约束（用户已确认）：
- **不改源码、纯 mod**。世界层的 GL 绘制靠 mixin 顶替 ChunkRenderer.draw。
- **仅支持 Windows 桌面**（用户拍板）。GL 走 PyOpenGL + WGL 离屏上下文，
  需要桌面 OpenGL >= 3.3。GLES/EGL/ANGLE 那套跨平台复杂度已全部砍掉。
- **失败必须静默降级**。任何一步不行（没 GL3.3、WGL 建不出来、包编译失败）
  都退回 pygame 原生绘制，游戏照常玩。这是硬约束：光影是加分项，不是必需项。
- **真的执行包里的 composite 与 final**。不是把包当"滤镜参数表"读。

一帧的接线：

    Game._draw()
      ├─ screen.fill(C_BG)            ← 保留（GL 失败时的底色）
      ├─ self.chunks.draw(...)        ← 【mixin 顶替】走 GL 全链
      │     失败时退回原 pygame 分块绘制
      ├─ _draw_fluids / _draw_items ... ← 原样保留（pygame 叠加层）
      └─ _draw_ui / 面板 / flip        ← 原样保留

为什么只顶替 chunks.draw：
星织的地表是「每格一个 tile 的 pygame blit」，这是唯一占满屏幕的一层，
也是唯一值得用 GL 重画的部分。液面/物品/插入器/UI 都是薄薄一层叠加，
用 pygame 画反而更省事、更清晰，还能保证 GL 挂掉后 UI 依然完好。

设置面板（settings_panel.py）是在主菜单「模组」页旁边加一个入口，只在
GL 可用且包扫描成功时出现。
"""

from __future__ import annotations

import os
import sys

# ---- 模块加载方式说明（这个坑很深）：
# stellarloom.mod.load_main_module 用 `mod_<name>_main` 当模块名加载本文件，
# 因此 **不能用相对导入**（`from .core import x` 会炸 ImportError:
# attempted relative import with no known parent package）。
# 正确做法：把 mod 自己的目录塞进 sys.path，然后按裸模块名 import core.xxx。
_MOD_DIR = os.path.dirname(os.path.abspath(__file__))
if _MOD_DIR not in sys.path:
    sys.path.insert(0, _MOD_DIR)

# 合成包名。core/ 下所有模块都以它为前缀挂在 sys.modules 里，
# 这样它们内部的 `from . import xxx` 才能正确解析。
_PKG = "shaderbridge_core"


def _core(name):
    """按"合成包"方式导入 core 子模块。

    core/ 内部的模块互相用相对导入（`from . import glapi`），所以不能把它们
    当裸模块加载——那样没有 __package__，相对导入照样炸。做法是注册一个
    __path__ 指向 core/ 的合成包，子模块按 `shaderbridge_core.xxx` 的名字挂
    进去，相对导入就落到同一个包命名空间里。
    """
    import importlib
    pkg = sys.modules.get(_PKG)
    if pkg is None:
        import types
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [os.path.join(_MOD_DIR, "core")]
        pkg.__package__ = _PKG
        pkg.__file__ = os.path.join(_MOD_DIR, "core", "__init__.py")
        sys.modules[_PKG] = pkg
    return importlib.import_module(_PKG + "." + name)

_CFG_DEFAULTS = {
    "enabled": True,
    "pack": "",                      # 光影包目录（绝对路径或相对 game/mods/shaderpacks）
    "world": "auto",                 # auto / world0 / world-1 / world1
    "show_ore": True,
    "show_items": True,
    "log_gl": True,                  # 打印 GL 后端信息（排查用）
    "max_compile_failures": 6,       # 失败这么多 pass 就整体放弃
}

# 全局状态：mixin 的 wrapper 是普通函数，拿不到 self 之外的上下文，
# 所以用模块级单例。卸载时清掉。
_STATE = {
    "comp": None,        # composite_gl.CompositeGL
    "chain": None,       # chain.ShaderChain
    "info": None,        # packscan.PackInfo
    "cfg": {},
    "game": None,
    "size": (0, 0),
    "failed": False,     # 已经降级过，别再重试
    "why": "",
    "frame": 0,
    "elapsed": 0.0,
    "last_dt": 0.016,
    "tried_packs": [],
}


# =====================================================================
# 包发现
# =====================================================================

def _pack_search_dirs(ctx):
    """光影包可能放的地方，按优先级。"""
    dirs = []
    # 1) mod 包自带的光影包（.slmmod 的 resources/shaderpacks）
    try:
        d = ctx.resource("shaderpacks")
        if d and os.path.isdir(str(d)):
            dirs.append(str(d))
    except Exception:
        pass
    # 2) 游戏根目录下的 shaderpacks/
    game_root = _game_root(ctx)
    if game_root:
        p = os.path.join(game_root, "shaderpacks")
        if os.path.isdir(p):
            dirs.append(p)
        # 3) 游戏根目录本身（用户可能直接把 shaders/ 放在这）
        if os.path.isdir(os.path.join(game_root, "shaders")):
            dirs.append(game_root)
    return dirs


def _game_root(ctx):
    """游戏根目录（含 stellarloom/ 的那一层）。"""
    try:
        import stellarloom
        return os.path.dirname(os.path.dirname(
            os.path.abspath(stellarloom.__file__)))
    except Exception:
        return None


def _has_shaders(path):
    """目录或 zip 是否是光影包根（有 shaders/ 或自己就是 shaders）。"""
    try:
        packscan = _core("packscan")
        return packscan.pack_has_shaders(path)
    except Exception:
        return False


def find_packs(ctx, cfg):
    """返回候选包根目录列表。配置里指定的排第一。"""
    out = []
    want = str(cfg.get("pack") or "").strip()
    if want:
        if _has_shaders(want):
            out.append(want)
        else:
            # 相对路径按搜索目录找
            for d in _pack_search_dirs(ctx):
                p = os.path.join(d, want)
                if _has_shaders(p):
                    out.append(p)
                    break
    for d in _pack_search_dirs(ctx):
        try:
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if _has_shaders(p) and p not in out:
                    out.append(p)
        except OSError:
            continue
        if _has_shaders(d) and d not in out:
            out.append(d)
    return out


def _pick_world(info, cfg):
    """决定用哪个 world 变体。auto = 优先 world-1（主世界），退 world0。"""
    want = str(cfg.get("world") or "auto").lower()
    avail = set()
    for ent in info.programs.values():
        for rel in (ent.get("fsh"), ent.get("vsh")):
            if rel and "/" in rel:
                avail.add(rel.split("/", 1)[0])
    if want != "auto":
        return want if (want in avail or not avail) else "world0"
    for cand in ("world-1", "world0", "world1", ""):
        if cand in avail or (cand == "" and not avail):
            return cand
    return "world0"


# =====================================================================
# 初始化（on_load 里做，一次性）
# =====================================================================

def _log(ctx, msg):
    try:
        ctx.log(msg)
    except Exception:
        print("[shaderbridge]", msg)


def _setup_gl(ctx, cfg):
    """建 GL 全套。成功返回 True。任何失败都记 why 并返回 False。"""
    state = _STATE

    # 1) 包扫描必须先成功——没有包就没什么可跑
    packscan = _core("packscan")
    packs = find_packs(ctx, cfg)
    state["tried_packs"] = packs[:6]
    if not packs:
        state["why"] = "没找到光影包（shaderpacks/ 里没有带 shaders/ 的目录）"
        return False

    info = None
    pack_root = None
    for p in packs:
        try:
            cand = packscan.scan_pack(p)
        except Exception as e:
            _log(ctx, "扫描 %s 失败: %s" % (p, e))
            continue
        if cand.found and cand.programs:
            info, pack_root = cand, p
            break
    if info is None:
        state["why"] = "候选包里没有可用的程序入口"
        return False
    state["info"] = info
    _log(ctx, "选中光影包 %s（%d 入口，%d 选项）"
         % (info.name, len(info.programs), len(info.options)))

    # 2) GL 探测：只查 PyOpenGL + 桌面 GL 一条路（Windows 专用）
    glctx = _core("glctx")
    ok, probe = glctx.probe()
    if cfg.get("log_gl", True):
        s = probe.summary()
        if ok:
            _log(ctx, "GL 探测: %s | %s | %s"
                 % (s["gl_version"], s["gl_renderer"], s["gl_vendor"]))
        else:
            _log(ctx, "GL 探测失败: %s" % "; ".join(s["errors"]))
    # 无论探测成败都继续：真正的上下文由 composite_gl 建，那里失败才降级。
    # 探测只是提前把原因写进日志。
    if not ok:
        probe.release()

    # 3) 编译整条链
    chain = _core("chain")
    defines = chain.option_defines(info)
    const_defaults = {}
    for nm, spec in info.options.items():
        if spec.source == "const" and spec.default:
            const_defaults[nm] = spec.default
    world = _pick_world(info, cfg)
    state["world"] = world
    try:
        ch = chain.ShaderChain(None, pack_root, info, world=world,
                               defines=defines, const_values=const_defaults)
    except Exception as e:
        state["why"] = "建 shader chain 失败: %s" % e
        return False
    state["chain"] = ch
    state["defines"] = defines
    state["const_values"] = const_defaults
    _log(ctx, "world=%s，注入宏 %d 个，const 选项 %d 个"
         % (world, len(defines), len(const_defaults)))

    return True


def _setup_composite(ctx, cfg, size):
    """建 EGL + 缓冲 + 编译 pass。失败返回 False。"""
    composite_gl = _core("composite_gl")

    state = _STATE
    ch = state["chain"]
    if ch is None:
        return False

    comp = composite_gl.CompositeGL()
    ok = comp.setup(ch, size)
    if not ok:
        state["why"] = "GL 初始化失败: " + "; ".join(comp.errors[-4:])
        comp.release()
        return False

    # 建好上下文之后再编 pass（编译需要 GL）
    try:
        ch.api = comp.api
        okn, failn = ch.build_all()
    except Exception as e:
        state["why"] = "编译 pass 失败: %s: %s" % (type(e).__name__, e)
        comp.release()
        return False
    if okn == 0:
        state["why"] = "没有一个 pass 编译成功: " + "; ".join(
            "%s: %s" % (n, m[:80]) for n, m in ch.failures[:3])
        comp.release()
        return False
    limit = int(cfg.get("max_compile_failures", 6) or 6)
    if failn > limit and okn < 4:
        state["why"] = ("编译失败过多（%d 成功 / %d 失败），放弃"
                        % (okn, failn))
        comp.release()
        return False

    state["comp"] = comp
    state["size"] = size
    _log(ctx, "pass 编译完成: %d 成功 / %d 失败，视口 %dx%d"
         % (okn, failn, size[0], size[1]))
    if ch.failures and cfg.get("log_gl", True):
        for n, m in ch.failures[:5]:
            _log(ctx, "  pass %s 失败: %s" % (n, m[:160]))
    return True


# =====================================================================
# 每帧绘制（mixin 顶替 ChunkRenderer.draw）
# =====================================================================

def draw_world(self, screen, camera):
    """顶替 ChunkRenderer.draw。返回 True 表示已接管。

    self 是 ChunkRenderer，但我们要的是 Game 的状态（grid / camera / 时间）。
    这些都是同一份对象，从 _STATE['game'] 取。
    """
    state = _STATE
    comp = state["comp"]
    game = state["game"]
    if comp is None or comp.gl_ok is False or game is None:
        return False
    if game is None or getattr(game, "orbit_panel", None) is not None \
            and game.orbit_panel.open:
        return False

    size = screen.get_size()
    if size != state["size"]:
        if not comp.resize(size):
            state["failed"] = True
            state["why"] = "resize 失败"
            _disable(state, "resize 失败")
            return False
        state["size"] = size

    dt = state["last_dt"]
    state["elapsed"] += dt
    state["frame"] += 1

    grid = getattr(game, "grid", None)
    cam = getattr(game, "camera", None)
    if grid is None or cam is None:
        return False

    wp = (getattr(cam, "world_pw", 0), getattr(cam, "world_ph", 0))
    try:
        comp.begin_frame(cam, dt, state["elapsed"], wp, grid=grid)
        surf = comp.render(grid, cam, dt=dt, elapsed=state["elapsed"])
    except Exception as e:
        _disable(state, "渲染异常: %s" % e)
        return False
    if surf is None:
        _disable(state, "渲染返回空")
        return False

    screen.blit(surf, (0, 0))
    return True


def _disable(state, why):
    """彻底关掉 GL 并记原因。不抛异常、不阻塞。"""
    state["failed"] = True
    state["why"] = why
    comp = state["comp"]
    if comp is not None:
        try:
            comp.release()
        except Exception:
            pass
    state["comp"] = None


# =====================================================================
# 生命周期
# =====================================================================

# M15d：纯渲染管线的 mod（mixin 顶替 ChunkRenderer.draw / Game._update），
# headless 服务端整段跳过。
from stellarloom.api import EnvType as _EnvType


@_EnvType("client")
def on_load(ctx):
    """mod 入口。加载 GL、编译链、打 mixin。失败只 toast 一次。"""
    state = _STATE
    state["game"] = getattr(ctx, "_game", None)

    cfg = dict(_CFG_DEFAULTS)
    try:
        cfg.update({k: v for k, v in (ctx.cfg or {}).items()
                    if k in _CFG_DEFAULTS})
    except Exception:
        pass
    state["cfg"] = cfg

    if not cfg.get("enabled", True):
        _log(ctx, "配置里已禁用，不加载")
        return

    if not _setup_gl(ctx, cfg):
        _log(ctx, "跳过 GL: %s" % state["why"])
        _toast(ctx, "光影包未启用: %s" % state["why"], 4.0)
        return

    # 尺寸要等 screen 存在。Game.__init__ 里 screen 已经在手，on_load 时可用。
    screen = getattr(state["game"], "screen", None)
    if screen is None:
        state["why"] = "拿不到 Game.screen（无法确定视口尺寸）"
        _log(ctx, "跳过 GL: %s" % state["why"])
        return
    if not _setup_composite(ctx, cfg, screen.get_size()):
        _log(ctx, "GL 初始化失败: %s" % state["why"])
        _toast(ctx, "光影无法启用: %s" % state["why"], 4.0)
        return
    _toast(ctx, "光影已启用: %s" % state["info"].name, 2.5)

    # 打补丁：顶替地表绘制
    try:
        ctx.mixin("stellarloom.render.layers.ChunkRenderer", "draw",
                  draw_world, wrap="replace")
    except Exception as e:
        _log(ctx, "打 mixin 失败: %s" % e)
        _toast(ctx, "光影挂钩失败: %s" % e, 3.5)
        _teardown()
        return

    # 每帧 dt：从 clock 推，Game 没暴露就别猜
    _install_dt_hook(ctx)
    _install_dirty_hook(ctx)
    _log(ctx, "ShaderBridge 就绪")


def _install_dirty_hook(ctx):
    """世界变化 → 重烘几何。pygame 的 ChunkRenderer._build 在世界变化时
    触发（建/拆建筑、矿脉变化），借它当地图脏信号，让 world_gl 的
    顶点缓存只在真的变了才重建。"""
    state = _STATE

    def after(self, result, *a, **k):
        comp = state.get("comp")
        if comp is not None and comp.world is not None:
            try:
                comp.world.mark_dirty()
            except Exception:
                pass
        return None

    try:
        ctx.mixin("stellarloom.render.layers.ChunkRenderer", "_build",
                  after, wrap="after")
    except Exception as e:
        _log(ctx, "脏标记钩子失败（几何将每帧重烘，仅性能损失）: %s" % e)


def _install_dt_hook(ctx):
    """给 Game._update 挂一个 after，记录真实 dt（uniform 的 frameTime 要用）。"""
    state = _STATE

    def after(self, result, dt, *a, **k):
        try:
            f = float(dt)
            if 0.0 < f < 0.5:
                state["last_dt"] = f
        except Exception:
            pass
        return None

    try:
        ctx.mixin("stellarloom.core.game.Game", "_update", after, wrap="after")
    except Exception as e:
        _log(ctx, "dt 钩子失败（frameTime 用默认值）: %s" % e)


def _toast(ctx, text, secs=3.0):
    try:
        ctx.toast(text, secs)
    except Exception:
        pass


def _teardown():
    state = _STATE
    comp = state.get("comp")
    if comp is not None:
        try:
            comp.release()
        except Exception:
            pass
    ch = state.get("chain")
    if ch is not None:
        try:
            ch.release()
        except Exception:
            pass
    state["comp"] = None
    state["chain"] = None


def on_unload(ctx):
    """还原：mixin 由加载器自动撤，这里只放 GL 资源。"""
    _teardown()
    _STATE["failed"] = True


# =====================================================================
# 设置面板 / 状态查询（给 settings_panel.py 用）
# =====================================================================

def status():
    """给面板显示用的一张小快照。"""
    state = _STATE
    comp = state.get("comp")
    info = state.get("info")
    s = {
        "enabled": not state["failed"],
        "why": state["why"],
        "pack": info.name if info else "",
        "pack_root": getattr(info, "root", "") if info else "",
        "world": state.get("world", ""),
        "packs_tried": list(state.get("tried_packs") or []),
        "frame": state["frame"],
    }
    if info is not None:
        s["options"] = len(info.options)
        s["programs"] = len(info.programs)
        s["screens"] = [(sid, title, len(names)) for sid, title, names
                        in info.screens]
    if comp is not None:
        s.update(comp.summary())
    return s


def option_specs():
    """当前包的选项表（面板要拿它建控件）。"""
    info = _STATE.get("info")
    if info is None:
        return []
    return info.option_list()


def get_option_value(name):
    info = _STATE.get("info")
    if info is None:
        return None
    spec = info.options.get(name)
    if spec is None:
        return None
    if spec.source == "const":
        return _STATE.get("const_values", {}).get(name, spec.default)
    return _STATE.get("defines", {}).get(name, spec.default)


def set_option(name, value):
    """改一个选项值并触发重编。返回 (ok, 消息)。

    重编会丢掉已编好的程序、重新跑预处理+转译+GL 编译——手机上可能卡几秒。
    所以这里只在真的变了才动手。
    """
    chain_mod = _core("chain")
    setters = _core("setters")

    info = _STATE.get("info")
    ch = _STATE.get("chain")
    if info is None or ch is None:
        return False, "光影未加载"

    spec = info.options.get(name)
    if spec is None:
        return False, "未知选项 %s" % name

    ok, val = setters.validate_value(spec, value)
    if not ok:
        return False, val

    defines = dict(_STATE.get("defines") or {})
    consts = dict(_STATE.get("const_values") or {})
    if spec.source == "const":
        if consts.get(name) == val:
            return True, "未变"
        consts[name] = val
    else:
        if defines.get(name) == val:
            return True, "未变"
        defines[name] = val

    changed = ch.set_options(defines, consts)
    _STATE["defines"] = defines
    _STATE["const_values"] = consts
    if not changed:
        return True, "已应用"

    comp = _STATE.get("comp")
    if comp is None:
        return True, "已记录（GL 未运行）"
    try:
        comp.ctx.make_current()
        okn, failn = ch.build_all(force=True)
    except Exception as e:
        return False, "重编失败: %s" % e
    return True, "重编完成 %d OK / %d 失败" % (okn, failn)


def save_config(ctx):
    """把当前 GL 相关配置写进用户配置。"""
    state = _STATE
    cfg = state.get("cfg") or {}
    try:
        for k, v in cfg.items():
            ctx.cfg_set(k, v)
        ctx.save_config()
        return True
    except Exception as e:
        _log(ctx, "保存配置失败: %s" % e)
        return False