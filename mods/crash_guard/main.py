"""crash_guard —— Forge 风格崩溃守卫（Minecraft Forge 的崩溃页翻版）。

游戏崩溃（任何未捕获异常冲出主线程）时：
1. 弹出 Forge 风格**崩溃页面**：深色底、红字标题、异常摘要 + 可滚动完整
   堆栈；滚轮/方向键滚动，ESC 或关闭窗口退出；
2. 把**完整崩溃报告**（异常 + 堆栈 + 模组列表 + 环境信息）写入
   `crash-reports/crash-<时间>.txt`；
3. 卸载/禁用自动还原：`Game.run` 的 mixin 与 `sys.excepthook` 全部还原，
   游戏源码零改动。

实现要点（遵循 Docs/ModDev.md）：
- `ctx.mixin("stellarloom.core.game.Game", "run", wrap="replace")` 包住主循环：
  先 `_ORIG_RUN = Game.run` 存下原方法，wrapper 里调用它并 try/except；
  任何异常逃出主循环都会落进这里（无内部兜底，见 game.py run()）。
- 同时挂 `sys.excepthook`：主循环之外（例如 __init__ 后半段）的未捕获
  异常同样弹页 + 存报告；与 run wrapper 用 (id(exc), id(tb)) 去重，
  避免同一场崩溃弹两次页。
- 只拦 `Exception`（正常错误）；`KeyboardInterrupt` / `SystemExit`
  （用户 Ctrl-C / 主动退出）放行不拦截。
- 崩溃页绘制全程 try/except 兜底：渲染或 flip 失败就退回控制台打印报告
  路径，守卫自己绝不二次崩溃。
"""

from __future__ import annotations

import sys
import time
import traceback
import os
from pathlib import Path

import pygame

try:
    from stellarloom import config as C
except Exception:                    # 极端情况下游戏 config 都不可用
    C = None


def _fmt_stack(exc) -> str:
    """Java 风格堆栈（M15d）：`at stellarloom.模块.类.方法:行号`，不显示路径。

    游戏本体自带实现（stellarloom.core.errfmt），这里只是薄封装——
    万一 errfmt 不可用（极端加载顺序）就退回标准 traceback。
    """
    try:
        from stellarloom.core.errfmt import format_exc
        return format_exc(exc)
    except Exception:
        return "".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__))

_CFG: dict = {}                      # on_load 注入：ctx.cfg 合并配置
_GAME = None                         # on_load 注入：游戏实例（钩子用）
_ORIG_RUN = None                     # 原 Game.run（replace mixin 里手动调）
_PREV_HOOK = None                    # 原 sys.excepthook（卸载恢复）
_LAST_KEY: tuple | None = None       # 已处理异常去重键 (id(exc), id(tb))

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent.parent           # 游戏根目录（main.py 所在）

# ---------------- 配色（Forge 崩溃页色系） ----------------

_BG = (26, 28, 36)                   # 页面底色（深蓝灰）
_TITLE_RED = (235, 90, 80)           # 标题红
_TXT = (232, 236, 244)               # 正文
_DIM = (150, 158, 172)               # 次要文字
_FILE = (176, 190, 214)              # 堆栈 File 行（蓝）
_SRC = (140, 148, 164)               # 堆栈源码行
_ERROR = (255, 130, 110)             # 异常行（橙红）
_GREEN = (120, 210, 150)             # 报告路径（绿）
_BOX = (40, 43, 54)                  # 摘要框底色
_BORDER = (70, 76, 92)               # 摘要框/堆栈区边框


# =====================================================================
# 崩溃报告（写 crash-reports/crash-<时间戳>.txt）
# =====================================================================

def _system_info() -> str:
    lines = []
    if C is not None and hasattr(C, "TITLE"):
        lines.append(f"游戏: {getattr(C, 'TITLE', 'StellarLoom-PG')}")
    lines.append(f"Python: {sys.version.split()[0]}")
    try:
        lines.append(f"pygame: {pygame.version.ver}")
    except Exception:
        pass
    try:
        import numpy
        lines.append(f"numpy: {numpy.__version__}")
    except Exception:
        pass
    return "\n".join(lines)


def _mod_list(game) -> str:
    mm = getattr(game, "mod_mgr", None)
    if mm is None:
        return "（模组管理器不可用）"
    lines = []
    if getattr(mm, "ctxs", None):
        lines.append("已加载: " + ", ".join(
            f"{c.name} v{c.version}" for c in mm.ctxs))
    if getattr(mm, "failed", None):
        lines.append("失败: " + "; ".join(
            f"{n}（{e}）" for n, e in mm.failed))
    return "\n".join(lines) if lines else "（无）"


def _save_report(exc, tb, game) -> Path:
    """写崩溃报告 → 返回报告路径（写失败返回 Path('.')）。"""
    rep_dir = _ROOT / "crash-reports"
    for cand in (rep_dir, Path.cwd() / "crash-reports", Path(".")):
        try:
            cand.mkdir(parents=True, exist_ok=True)
            rep_dir = cand
            break
        except OSError:
            continue
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = rep_dir / f"crash-{stamp}.txt"
    body = [
        "=" * 66,
        "   星织 StellarLoom-PG 崩溃报告（Crash Report）",
        "=" * 66,
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        _system_info(),
        "",
        f"异常: {type(exc).__name__}: {exc}",
        "",
        "---- Traceback ----",
        _fmt_stack(exc),
        "---- Mods ----",
        _mod_list(game),
        "=" * 66,
    ]
    try:
        path.write_text("\n".join(body), encoding="utf-8")
        return path
    except OSError:
        return Path(".")


# =====================================================================
# 崩溃页面（Forge 风格：红标题 + 异常摘要 + 可滚动堆栈）
# =====================================================================

def _wrap(text: str, font, width: int) -> list:
    """按像素宽度折行（二分找最长可放前缀）。"""
    out: list[str] = []
    for ln in text.split("\n"):
        while font.size(ln)[0] > width > 0 and len(ln) > 1:
            lo, hi = 1, len(ln)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.size(ln[:mid])[0] <= width:
                    lo = mid
                else:
                    hi = mid - 1
            lo = max(lo, 1)
            out.append(ln[:lo])
            ln = ln[lo:]
        out.append(ln)
    return out or [""]


def _trace_rows(exc, tb, font, width) -> list:
    """完整堆栈 → [(行文本, 颜色)]，已折行；异常行标红色。

    M15d：堆栈行改成 Java 风格 `at 模块.类.方法:行号`，不显示文件路径。
    """
    rows: list[tuple[str, tuple]] = []
    for ln in _fmt_stack(exc).split("\n"):
        if not ln:
            continue
        if ln.startswith("    at "):
            col = _FILE
        elif ln.startswith("Caused by:"):
            col = _DIM
        else:
            col = _ERROR if ln is None else _TXT
        for piece in _wrap(ln, font, width):
            rows.append((piece, col))
    if rows:
        # 第一行（异常类型+消息）总是红色
        rows[0] = (rows[0][0], _ERROR)
    return rows


def _render_page(screen, game, exc, tb, report: Path, offset: int):
    """整页渲染（供事件循环与自检/截图用）。返回 (总行高, 可视区高)。"""
    w, h = screen.get_size()
    fonts = getattr(game, "fonts", None)
    by = lambda s: (fonts.get(s) if fonts is not None
                    else pygame.font.Font(None, s))
    t_font = by(int(_CFG.get("title_size", 32)))
    hd_font = by(int(_CFG.get("headline_size", 20)))
    b_font = by(int(_CFG.get("body_size", 16)))
    f_font = by(int(_CFG.get("footer_size", 14)))

    pad = 18
    screen.fill(_BG)

    # 标题
    title = t_font.render("星织 出现了一个错误！", True, _TITLE_RED)
    screen.blit(title, (pad, pad))
    sub = b_font.render(
        "游戏发生未处理的异常，已停止运行。滚动查看堆栈，ESC / 关闭窗口退出。",
        True, _DIM)
    screen.blit(sub, (pad, pad + title.get_height() + 6))

    # 异常摘要框
    head_line = f"{type(exc).__name__}: {exc}"
    head_w = w - pad * 2 - 6
    head_rows = _wrap(head_line, hd_font, head_w - 12)
    hx = pad
    hy = pad + title.get_height() + 6 + sub.get_height() + 12
    box_h = 4 + sum(hd_font.size(x)[1] + 2 for x in head_rows) + 4
    pygame.draw.rect(screen, _BOX, (hx, hy, w - pad * 2, box_h),
                     border_radius=6)
    pygame.draw.rect(screen, _BORDER, (hx, hy, w - pad * 2, box_h), 1,
                     border_radius=6)
    ty = hy + 4
    for rn in head_rows:
        screen.blit(hd_font.render(rn, True, _ERROR), (hx + 6, ty))
        ty += hd_font.size(rn)[1] + 2

    # 堆栈区（可滚动）
    area_top = hy + box_h + 10
    area_bot = h - 44
    area_h = max(60, area_bot - area_top)
    rows = _trace_rows(exc, tb, b_font, w - pad * 2 - 8)
    row_h = b_font.get_height() + 2
    total_h = len(rows) * row_h
    top = min(offset, max(0, total_h - area_h))
    area = pygame.Rect(pad - 2, area_top - 2, w - (pad - 2) * 2, area_h + 4)
    pygame.draw.rect(screen, (30, 32, 42), area, border_radius=4)
    pygame.draw.rect(screen, _BORDER, area, 1, border_radius=4)

    clip = screen.get_clip()
    screen.set_clip(area.inflate(-6, -6))
    yy = area.top + 8 - top
    for i in range(len(rows)):
        rtxt, rcol = rows[i]
        if yy + b_font.get_height() < area.top:
            yy += row_h
            continue
        if yy > area.bottom:
            break
        screen.blit(b_font.render(rtxt, True, rcol), (area.left + 8, yy))
        yy += row_h
    screen.set_clip(clip)

    # 滚动提示
    if total_h > area_h:
        hint = "↑ ↓ / 滚轮 / PgUp PgDn 滚动    "
    else:
        hint = "完整堆栈已全部显示    "
    screen.blit(f_font.render(hint, True, _DIM),
                (area.left + 8, area.bottom - f_font.get_height() - 6))

    # 页脚：报告路径 + 退出提示
    foot_y = h - 34
    report_txt = f"崩溃报告: {report}"
    screen.blit(f_font.render(report_txt, True, _GREEN), (pad, foot_y))
    quit_txt = "按 ESC 或关闭窗口退出游戏（报告已保存，可提交给作者）"
    qw = f_font.size(quit_txt)[0]
    screen.blit(f_font.render(quit_txt, True, _DIM), (w - pad - qw, foot_y))
    return total_h, area_h


def _show_page(game, exc, tb, report: Path):
    """崩溃页事件循环：渲染 + 滚动 + 等 ESC/关窗。返回是否正常退出。"""
    screen = game.screen
    offset = 0
    clock = pygame.time.Clock()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return True
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                    return True
                if e.key == pygame.K_UP:
                    offset -= 1
                elif e.key == pygame.K_DOWN:
                    offset += 1
                elif e.key == pygame.K_PAGEUP:
                    offset -= 12
                elif e.key == pygame.K_PAGEDOWN:
                    offset += 12
                elif e.key == pygame.K_HOME:
                    offset = -10**9
                elif e.key == pygame.K_END:
                    offset = 10**9
            elif e.type == pygame.MOUSEWHEEL:
                offset -= e.y * 3
        try:
            total_h, area_h = _render_page(screen, game, exc, tb, report,
                                           offset)
            offset = max(0, min(offset, max(0, total_h - area_h)))
            pygame.display.flip()
        except Exception:
            return False      # 渲染挂了：守卫自己不能炸
        clock.tick(30)


# =====================================================================
# 拦截入口
# =====================================================================

def _handle_crash(game, exc, tb):
    """统一处理：存报告 + 弹页（渲染失败退回控制台）。"""
    report = _save_report(exc, tb, game)
    print(f"[mod crash_guard] 游戏崩溃已拦截：{type(exc).__name__}: {exc}")
    print(f"[mod crash_guard] 崩溃报告已保存：{report}")
    if game is None or not getattr(game, "screen", None):
        return report
    # M15d：出错即崩后崩溃拦截会更常被触发。headless/自检环境
    # （SDL_VIDEODRIVER=dummy）没有真人按 ESC，崩溃页事件循环会永远阻塞
    # ——只存报告 + 打控制台，不弹页。
    if os.environ.get("SDL_VIDEODRIVER") == "dummy":
        return report
    try:
        if pygame.display.get_init():
            _show_page(game, exc, tb, report)
    except Exception:
        pass
    return report


def _guard_run(self, *a, **k):
    """Game.run 的 replace wrapper：原循环 + 崩溃拦截。"""
    global _LAST_KEY
    try:
        return _ORIG_RUN(self, *a, **k)
    except BaseException:
        exc, tb = sys.exc_info()[1], sys.exc_info()[2]
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise                    # 用户 Ctrl-C / 主动退出：不拦截
        _LAST_KEY = (id(exc), id(tb))
        try:
            _handle_crash(self, exc, tb)
        finally:
            try:
                pygame.quit()
            except Exception:
                pass
        raise                        # 页已显示：把原异常继续抛给外层（console 有印）


def _hook(exc_type, exc, tb):
    """sys.excepthook：主循环之外（如 __init__ 后半段）的未捕获异常。"""
    global _LAST_KEY
    if exc is None or tb is None:
        return
    if (id(exc), id(tb)) == _LAST_KEY:
        return                       # 主循环守卫已弹页 + 存报告，不重复
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return
    try:
        _handle_crash(_GAME, exc, tb)
    except BaseException:
        print("[mod crash_guard] excepthook 处理失败，原异常继续上报")


# =====================================================================
# 生命周期
# =====================================================================

def on_load(ctx):
    global _CFG, _GAME, _ORIG_RUN, _PREV_HOOK
    from stellarloom.api import ModAPIError
    _CFG = ctx.cfg
    if not _CFG.get("enabled", True):
        ctx.log("enabled=false：崩溃守卫未挂载（改 mods/config/crash_guard.json 启用）")
        return
    game = getattr(ctx, "_game", None)
    if game is None:
        raise ModAPIError("crash_guard 需要游戏实例（ctx._game）")

    from stellarloom.core.game import Game
    _GAME = game
    _ORIG_RUN = Game.run

    def guard(self, *a, **k):
        return _guard_run(self, *a, **k)

    ctx.mixin("stellarloom.core.game.Game", "run", guard, wrap="replace")
    _PREV_HOOK = sys.excepthook
    sys.excepthook = _hook
    ctx.log("崩溃守卫已挂载：主循环/未捕获异常 → Forge 风格崩溃页 + "
            "crash-reports/ 崩溃报告")
    ctx.toast("崩溃守卫已启用：出错会弹详细报告页", 2.0)


def on_unload(ctx):
    global _PREV_HOOK, _GAME, _ORIG_RUN
    if sys.excepthook is _hook:
        sys.excepthook = _PREV_HOOK
    _PREV_HOOK = None
    _GAME = None
    _ORIG_RUN = None
    ctx.log("crash_guard 卸载：Game.run mixin 与 sys.excepthook 已还原")
