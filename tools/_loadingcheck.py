#!/usr/bin/env python3
"""M13 启动加载界面 + mod 拆文件入口自检（第 27 项）。

覆盖：
[1] LoadingScreen 渲染（大步骤条/当前项/子进度/事件 pump）
[2] Game 分阶段构造：spy loader 收到 BOOT_STAGES 顺序 + done
[3] load_mods progress 回调（含失败隔离时序）
[4] mod.json "main"/"mixins" 入口：mixins 先加载、@Mixin 生效、顺序正确
[5] 坏入口拒绝：显式 main 缺失 / mixins 文件缺失 / 路径穿越
[6] 打包 mod 的入口字段同样生效
[7] loader=None 静默兼容（Game(screen) 不受影响）

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_loadingcheck.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from stellarloom.core import Game  # noqa: E402
from stellarloom.core.bootstrap import create_game  # noqa: E402
from stellarloom.mod import load_mods  # noqa: E402
from stellarloom.render.fonts import FontBook  # noqa: E402
from stellarloom.ui.loading import LoadingScreen  # noqa: E402

TOOLS = Path(__file__).resolve().parent
bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def _load_pack_cli():
    spec = importlib.util.spec_from_file_location(
        "pack_mod", TOOLS / "pack_mod.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    global bad
    pygame.init()
    screen = pygame.display.set_mode((640, 480))

    # ---------- [1] LoadingScreen 渲染 ----------
    print("[1] LoadingScreen 渲染:")
    loader = LoadingScreen(screen)
    bg = screen.copy()
    loader.begin(Game.BOOT_STAGES)
    check(_diff(screen, bg), "begin 后画面没变化")
    fonts = FontBook()
    loader.attach_fonts(fonts)
    for i, st in enumerate(Game.BOOT_STAGES):
        loader.major(st)
        loader.step(f"当前项 {st}", (i + 1) / len(Game.BOOT_STAGES))
    loader.done()
    # 大步骤条区域应非背景色
    w, h = screen.get_size()
    mid = screen.get_at((w // 2, int(h * 0.52) + 3))[:3]
    check(mid != (16, 20, 30), f"进度条区域仍背景色: {mid}")

    # ---------- [2] Game 分阶段构造（spy loader） ----------
    print("[2] Game 分阶段 & spy loader:")
    calls = []

    class Spy:
        def begin(self, majors): calls.append(("begin", list(majors)))
        def attach_fonts(self, f): calls.append(("fonts", None))
        def major(self, label): calls.append(("major", label))
        def step(self, label, frac=None): calls.append(("step", label))
        def done(self): calls.append(("done", None))

    tmp_mods = Path(tempfile.mkdtemp(prefix="slm_load_"))
    import stellarloom.core.bootstrap as _boot
    spy = Spy()
    orig_cls = _boot.LoadingScreen
    _boot.LoadingScreen = lambda screen: spy
    try:
        g = create_game(screen, mods_dir=tmp_mods)
    finally:
        _boot.LoadingScreen = orig_cls
    majors = [c[1] for c in calls if c[0] == "major"]
    check(majors == Game.BOOT_STAGES,
          f"大步骤顺序错: {majors} != {Game.BOOT_STAGES}")
    check(calls[0][0] == "begin" and calls[-1][0] == "done",
          "begin/done 位置错")
    check(g.menu.open, "菜单没开")

    # ---------- [3] progress 回调 ----------
    print("[3] load_mods progress 回调:")
    for name in ("m_a", "m_b"):
        d = tmp_mods / name
        d.mkdir()
        (d / "mod.json").write_text(
            json.dumps({"name": name, "version": "1.0"}), encoding="utf-8")
        (d / "main.py").write_text("X=1\n", encoding="utf-8")
    bad_dir = tmp_mods / "m_bad"
    bad_dir.mkdir()
    (bad_dir / "mod.json").write_text(
        json.dumps({"name": "m_bad", "version": "1.0"}), encoding="utf-8")
    (bad_dir / "main.py").write_text("def ::\n", encoding="utf-8")
    prog = []
    mgr = load_mods(g, tmp_mods,
                    progress=lambda n, i, t: prog.append((n, i, t)))
    loaded = [c.name for c in mgr.ctxs]
    check(sorted(loaded) == ["m_a", "m_b"], f"加载列表错: {loaded}")
    # progress 覆盖全部尝试项（含加载失败者，loading bar 按扫描总数走）
    check([n for n, _, _ in prog] == ["m_a", "m_b", "m_bad"],
          f"progress 顺序错: {prog}")
    check(all(t == 3 for _, _, t in prog),
          f"progress 总数错: {prog}")
    g.mod_mgr.unload()

    # ---------- [4] main/mixins 入口 ----------
    print("[4] mod.json main/mixins 入口:")
    em = tmp_mods / "m_entry"
    (em / "mx").mkdir(parents=True)
    (em / "mod.json").write_text(json.dumps({
        "name": "m_entry", "version": "1.0",
        "main": "boot.py", "mixins": ["mx/a.py"],
    }), encoding="utf-8")
    (em / "mx" / "a.py").write_text(
        "from pathlib import Path\n"
        "from stellarloom.api import Mixin, Inject\n"
        "(Path(__file__).parent.parent / 'order.txt')"
        ".write_text('mx;', encoding='utf-8')\n"
        "MX_COUNT = [0]\n"
        "@Mixin('stellarloom.sim.sim.Simulation')\n"
        "class Mx:\n"
        "    @Inject('place_building', at='RETURN')\n"
        "    def hook(self, *a, cir=None):\n"
        "        MX_COUNT[0] += 1\n", encoding="utf-8")
    (em / "boot.py").write_text(
        "from pathlib import Path\n"
        "def on_load(ctx):\n"
        "    p = Path(__file__).parent / 'order.txt'\n"
        "    p.write_text(p.read_text() + 'main;', encoding='utf-8')\n"
        "    ctx._entry_ok = True\n", encoding="utf-8")
    mgr2 = load_mods(g, tmp_mods)
    me = next((c for c in mgr2.ctxs if c.name == "m_entry"), None)
    check(me is not None, f"m_entry 没加载: {mgr2.failed}")
    order_txt = (em / "order.txt").read_text(encoding="utf-8") \
        if (em / "order.txt").exists() else ""
    check(order_txt == "mx;main;",
          f"mixins 应先于 main 加载: {order_txt!r}")
    # @Mixin 生效：调用 place_building 应计数
    import sys as _s
    mx_mod = _s.modules.get("mod_m_entry__mx0_main")
    check(mx_mod is not None, "mixin 模块没进 sys.modules")
    g.sim.place_building(1, 3, 3, 0)
    check(mx_mod.MX_COUNT[0] == 1,
          f"mixin 没生效: {mx_mod.MX_COUNT[0]}")

    # ---------- [5] 坏入口拒绝 ----------
    print("[5] 坏入口拒绝:")
    for name, extra in (
            ("m_nomain", {"main": "nope.py"}),
            ("m_nomix", {"mixins": ["no/such.py"]}),
            ("m_evil", {"main": "../evil.py"})):
        d = tmp_mods / name
        d.mkdir(exist_ok=True)
        (d / "mod.json").write_text(
            json.dumps({"name": name, "version": "1.0", **extra}),
            encoding="utf-8")
        (d / "main.py").write_text("Y=1\n", encoding="utf-8")
    mgr3 = load_mods(g, tmp_mods)
    fnames = {n for n, _ in mgr3.failed}
    check({"m_nomain", "m_nomix", "m_evil"} <= fnames,
          f"坏入口没全拒: {mgr3.failed}")
    check("m_entry" in [c.name for c in mgr3.ctxs],
          "好 mod 被连坐")

    # ---------- [6] 打包 mod 的入口字段 ----------
    print("[6] 打包 mod 入口字段:")
    pc = _load_pack_cli()
    pack_path = tmp_mods / "m_entry.slmmod"
    pc.pack(em, pack_path, [], [])
    loader_dir = Path(tempfile.mkdtemp(prefix="slm_loadpk_"))
    import shutil
    shutil.copy2(pack_path, loader_dir / "m_entry.slmmod")
    mgr4 = load_mods(g, loader_dir)
    pe = next((c for c in mgr4.ctxs if c.name == "m_entry"), None)
    check(pe is not None, f"打包 mod 没加载: {mgr4.failed}")
    if pe is not None:
        pe_order = Path(pe._mod_dir) / "order.txt"
        check(pe_order.exists()
              and pe_order.read_text(encoding="utf-8") == "mx;main;",
              "打包 mod 入口顺序错")

    # ---------- [7] loader=None 静默兼容 ----------
    print("[7] 静默兼容:")
    g2 = Game(screen)   # 不传 loader（真实 mods 目录，和其它自检一致）
    check(g2.menu.open and g2.mod_mgr is not None, "Game(screen) 坏了")
    g2.mod_mgr.unload()
    g.mod_mgr.unload()

    print()
    if bad:
        print(f"FAIL {bad} 项: _loadingcheck")
        return 1
    print("PASS 启动加载界面 + 入口字段全部通过")
    import shutil as _sh
    _sh.rmtree(tmp_mods, ignore_errors=True)
    _sh.rmtree(loader_dir, ignore_errors=True)
    return 0


def _diff(a: pygame.Surface, b: pygame.Surface) -> bool:
    w, h = a.get_size()
    for _ in range(200):
        import random
        x, y = random.randrange(w), random.randrange(h)
        if a.get_at((x, y))[:3] != b.get_at((x, y))[:3]:
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())