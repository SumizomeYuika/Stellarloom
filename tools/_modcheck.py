#!/usr/bin/env python3
"""MOD 系统自检（M6.27，第 21 项）：加载器 + mixin（before/after/replace 全开放）
+ API 内容扩展（物品/配方）+ 钩子（on_step/on_event）+ 卸载还原 + 失败隔离。

临时构造若干 mod（M15d：坏 mod 一律 raise，不再进 failed 隔离）：
  stat_mixin   —— after 包 Simulation.place_building 计数
  content      —— before 计数 + replace 包 CraftQueue.update、add_item×2、add_recipe、
                  on_step/on_event 计数
  bad_syntax   —— main.py 语法错（加载必须抛异常）
  bad_target   —— mixin 目标不存在（加载必须抛异常）

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_modcheck.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from stellarloom import config as C  # noqa: E402
from stellarloom.core import Game  # noqa: E402
from stellarloom.mod import load_mods  # noqa: E402
from stellarloom.sim.sim import Simulation  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


def main():
    pygame.init()
    screen = pygame.display.set_mode((640, 480))

    tmp = tempfile.mkdtemp(prefix="slm_mod_")
    base = Path(tmp)

    def write_mod(name, main_src, json_extra=""):
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "mod.json").write_text(
            '{"name": "%s", "version": "1.0", "description": "t"%s}\n'
            % (name, (", " + json_extra) if json_extra else ""),
            encoding="utf-8")
        (d / "main.py").write_text(main_src, encoding="utf-8")

    write_mod("stat_mixin", """
COUNT = 0
def on_load(ctx):
    def after_place(self, result, btype, gx, gy, rot, **kw):
        global COUNT
        COUNT += 1
    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              after_place, wrap="after")
""")

    write_mod("content", """
STEP = 0
EVT = 0
BEFORE = 0
def on_load(ctx):
    ctx.add_item(300, "特制煤块", "#A06040")
    ctx.add_item(301, "幻想锭", "#C0A8FF")
    ctx.add_recipe("magic_bar", {300: 2}, {301: 1}, 1.0)
    def before_place(self, btype, gx, gy, rot, **kw):
        global BEFORE
        BEFORE += 1
        return ((btype, gx + 1, gy, rot), {})   # 替换调用参数：放点右移一格
    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              before_place, wrap="before")
    def replace_update(self, dt):
        pass   # replace 语义：完全接管，不调原方法
    ctx.mixin("stellarloom.sim.craft_queue.CraftQueue", "update",
              replace_update, wrap="replace")
    def on_step(dt):
        global STEP
        STEP += 1
    def on_event(ev):
        global EVT
        EVT += 1
    ctx.on_step(on_step)
    ctx.on_event(on_event)
""")

    # M15d：坏 mod 放独立目录，各自断言"加载直接 raise"（不再进 failed）
    bad_dir = Path(tempfile.mkdtemp(prefix="slm_modbad_"))

    def write_bad(name, main_src):
        d = bad_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "mod.json").write_text(
            '{"name": "%s", "version": "1.0"}\n' % name, encoding="utf-8")
        (d / "main.py").write_text(main_src, encoding="utf-8")

    write_bad("bad_syntax", "def ::\n")
    write_bad("bad_target", """
def on_load(ctx):
    def w(self): pass
    ctx.mixin("no.such.module.Class", "m", w, wrap="before")
""")

    def expect_raise(fn, substr, label):
        try:
            fn()
        except Exception as e:
            check(substr in f"{type(e).__name__}: {e}" or substr in str(e),
                  f"{label} 抛了但信息不含 {substr!r}: {type(e).__name__}: {e}")
            return
        check(False, f"{label} 没抛异常（M15d 要求出错即崩）")

    # ---------- 1. 加载 + 坏 mod 直接 raise ----------
    print("[1] 加载 + 出错即崩:")
    g = Game(screen)
    g.menu.open = False
    g.mod_mgr.unload()   # 先卸掉真实 mods/ 的示例 mod，保持基线干净
    # 原方法引用必须在任何 patch 之前捕获
    orig_place = Simulation.place_building
    from stellarloom.sim.craft_queue import CraftQueue  # noqa: E402
    orig_upd = CraftQueue.update
    mgr = load_mods(g, tmp)
    names = [c.name for c in mgr.ctxs]
    print(f"  加载成功 {names}")
    check(sorted(names) == ["content", "stat_mixin"],
          f"成功列表错: {names}")
    check(mgr.failed == [], "failed 应恒为空（M15d 出错即崩，不写 failed）")

    # ---------- 2. mixin：after / before / replace ----------
    print("[2] mixin 生效:")
    check(Simulation.place_building is not orig_place,
          "place_building 未被 patch")
    r = g.sim.place_building(C.B_BELT, 10, 10, 0)
    print(f"  place(10,10) → {r}  after={_m('stat_mixin', 'COUNT')} "
          f"before={_m('content', 'BEFORE')}")
    check(r == "ok", f"放置返回 {r}")
    check(_m("stat_mixin", "COUNT") == 1, "after wrap 没触发")
    check(_m("content", "BEFORE") == 1, "before wrap 没触发")
    # before 换参分支：放置点被右移到 (11,10)、(10,10) 保持空
    grid = g.sim.worlds[g.sim.world_index].grid
    check(grid.get(11, 10) == C.B_BELT and grid.get(10, 10) == 0,
          f"before 参数替换没生效: (11,10)={grid.get(11,10)} (10,10)={grid.get(10,10)}")

    # replace：CraftQueue.update 被完全接管 → sim.step 时不再推进
    check(CraftQueue.update is not orig_upd, "CraftQueue.update 未被 replace")
    g.sim.step(5.0)

    # ---------- 3. 内容扩展 API ----------
    print("[3] 内容扩展:")
    check(C.ITEM_NAMES.get(300) == "特制煤块", "add_item 300 失败")
    check(C.ITEM_COLORS.get(300) == (160, 96, 64), f"add_item 颜色错: "
          f"{C.ITEM_COLORS.get(300)}")
    check(C.RECIPES.get("magic_bar") == ({300: 2}, {301: 1}, 1.0, ()),
          f"add_recipe 失败: {C.RECIPES.get('magic_bar')}")
    # 材料冲突拒绝
    try:
        mgr.ctxs[0].add_item(300, "再来一个", "#FFFFFF")
        check(False, "add_item 冲突没拒绝")
    except Exception:
        check(True, "")
    # 手搓闭环：给材料 → 排队成功
    g.sim.inventory[300] = 2
    n = g.sim.do_craft("magic_bar", 1)
    check(n == 1 and g.sim.craft.jobs and
          g.sim.craft.jobs[0].rid == "magic_bar",
          f"do_craft 新配方失败: {n}")

    # ---------- 4. 钩子 ----------
    print("[4] 钩子:")
    mgr.step(0.25)
    check(_m("content", "STEP") == 1, "on_step 没触发")
    mgr.emit(("toast", "hi", 1.0))
    check(_m("content", "EVT") == 1, "on_event 没触发")

    # ---------- 5. 卸载还原（非永久） ----------
    print("[5] 卸载还原:")
    mgr.unload()
    check(Simulation.place_building is orig_place, "place_building 没还原")
    check(CraftQueue.update is orig_upd, "CraftQueue.update 没还原")
    before = _m("stat_mixin", "COUNT")
    r2 = g.sim.place_building(C.B_BELT, 11, 11, 0)
    check(r2 == "ok" and _m("stat_mixin", "COUNT") == before,
          "卸载后 patch 仍在生效")
    # 内容注册随卸载一起撤销（非永久）
    check(300 not in C.ITEM_NAMES and "magic_bar" not in C.RECIPES,
          "卸载后内容注册没撤销")

    # ---------- 6. 重载幂等 ----------
    print("[6] 重载:")
    mgr2 = load_mods(g, tmp)
    check([c.name for c in mgr2.ctxs] == ["content", "stat_mixin"],
          "重载列表错")
    mgr2.unload()

    # ---------- 6b. 坏 mod 直接 raise ----------
    # 注意：load_mods 会先把"上一个还挂着的管理器"卸干净（M15d 单活跃
    # 管理器），所以坏 mod 断言必须放在 mgr/mgr2 都卸载之后，否则会把
    # 后面要用的补丁链拆了。
    print("[6b] 坏 mod 出错即崩:")
    import shutil as _sh
    d1 = bad_dir / "only_syntax"
    d1.mkdir()
    _sh.copytree(bad_dir / "bad_syntax", d1 / "bad_syntax")
    expect_raise(lambda: load_mods(g, d1), "SyntaxError", "bad_syntax 加载")
    d2 = bad_dir / "only_target"
    d2.mkdir()
    _sh.copytree(bad_dir / "bad_target", d2 / "bad_target")
    expect_raise(lambda: load_mods(g, d2), "no.such", "bad_target 加载")
    print("  bad_syntax / bad_target 均直接 raise ✓")

    # ---------- 7. 真实 mods/ 目录（示例 mod 被真实 Game 加载） ----------
    print("[7] 真实 Game 加载:")
    from stellarloom.logistics.belts import BeltNetwork
    orig_upd2 = BeltNetwork.update   # 构造前捕获（此时已被前序 unload 还原）
    g2 = Game(screen)
    g2.menu.open = False
    check(g2.mod_mgr is not None, "Game 没挂 mod_mgr")
    names = [c.name for c in g2.mod_mgr.ctxs]
    check("example_speed_belt" in names,
          f"示例 mod 没被真实 Game 加载: {names}")
    check(BeltNetwork.update is not orig_upd2,
          "示例 mod 的 mixin 没生效")
    g2.mod_mgr.unload()
    check(BeltNetwork.update is orig_upd2, "示例 mod 卸载没还原")
    print(f"  示例 mod 挂载 ✓ mixin ×2 ✓ 卸载还原 ✓")

    # ---------- 8. 模组管理页（禁用名单 + ModsPanel） ----------
    print("[8] 模组管理:")
    from stellarloom.mod import ModManager
    mgr3 = ModManager(None, base).load_all()
    names3 = mgr3.available()
    check(sorted(names3) == ["content", "stat_mixin"],
          f"available 列表错: {names3}")
    check(mgr3.status_of("content") == "已加载", mgr3.status_of("content"))
    # M15d：坏 mod 不再进 failed，status_of 没有"加载失败"态可查，
    # 未加载的 mod 一律报"未加载"
    check(mgr3.status_of("ghost_mod") == "未加载",
          f"未加载状态错: {mgr3.status_of('ghost_mod')}")
    # 禁用 → 写 .disabled 并热重载（content 不再加载）
    mgr3.set_disabled("content", True)
    check(mgr3.is_disabled("content"), "禁用名单没生效")
    check(all(c.name != "content" for c in mgr3.ctxs),
          "禁用后仍加载了 content")
    check((base / ".disabled").is_file(), ".disabled 文件没写")
    check((base / ".disabled").read_text(encoding="utf-8").strip()
          == "content", ".disabled 内容错")
    # 重新启用 → 恢复加载
    mgr3.set_disabled("content", False)
    check("content" in [c.name for c in mgr3.ctxs], "重新启用后没恢复")
    mgr3.unload()
    # ModsPanel（M6.28 全屏双栏）：左栏列表/点选/右栏禁用/换行/关闭
    from stellarloom.ui.mods_panel import ModsPanel
    from stellarloom.ui import uidef
    mp = ModsPanel(g.fonts)
    mp.show(mgr3, (640, 480))
    mp.draw(screen)
    check(mp.open and bool(mp._left_rows), "ModsPanel 左栏列表缺失")
    name0 = mp._left_rows[0][1]
    mp.hit(mp._left_rows[0][0].center)
    check(mp.selected == name0, f"点左栏没选中: {mp.selected}")
    mp.draw(screen)
    check(mp._toggle_btn is not None and mp._back_btn is not None,
          "右栏 禁用/返回 按钮缺失")
    # 禁用选中 mod → .disabled 生效，右栏状态变"已禁用"
    mp.hit(mp._toggle_btn.center)
    check(mgr3.is_disabled(name0), "点禁用按钮没生效")
    check(mgr3.status_of(name0) == "已禁用", mgr3.status_of(name0))
    # 再启用还原
    mp.draw(screen)
    mp.hit(mp._toggle_btn.center)
    check(not mgr3.is_disabled(name0), "点启用按钮没还原")
    # wrap_text 换行（真实字体测宽）：长描述多行 + 每行不超宽
    small = g.fonts.get(15)
    lines = uidef.wrap_text("这是一个非常长的mod描述" * 20, small, 200)
    check(len(lines) >= 2 and all(small.size(ln)[0] <= 200 for ln in lines),
          f"wrap_text 换行/超宽错: {len(lines)} 行")
    check(uidef.wrap_text("a\nb", small, 100) == ["a", "b"],
          "wrap_text 丢换行符")
    mp.close()
    check(not mp.open, "ModsPanel 关闭失败")
    print("  available/status/禁用热重载/.disabled/全屏双栏面板/换行 ✓")

    # ---------- 9. 统一 config（作者默认 + 用户覆盖 + save_config 落盘） ----------
    print("[9] 统一 config:")
    mgr3.unload()

    def write_file(rel, content):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    write_mod("cfgmod", '''
def on_load(ctx):
    ctx.cfg_set("boost", 2.5)
    ctx.toast("cfg ok")
''')
    write_file("cfgmod/config.json", '{"speed": 1.5, "color": "#ffffff"}')
    # 用户配置预写：覆盖作者默认的 color
    write_file("config/cfgmod.json", '{"color": "#000000"}')
    mgr9 = ModManager(None, base).load_all()
    c9 = [c for c in mgr9.ctxs if c.name == "cfgmod"]
    check(bool(c9), "cfgmod 没加载")
    cx9 = c9[0]
    ok9 = (cx9.cfg_get("speed") == 1.5
           and cx9.cfg_get("color") == "#000000"
           and cx9.cfg_get("boost") == 2.5
           and cx9._cfg_has_default)
    check(ok9, f"合并错: {cx9.cfg} / has_default={cx9._cfg_has_default}")
    # save_config 落盘（含 on_load 里改的 boost）
    import json as _json
    sp = cx9.save_config()
    saved = _json.loads(Path(sp).read_text(encoding="utf-8"))
    check(saved.get("boost") == 2.5 and saved.get("color") == "#000000",
          f"save_config 内容错: {saved}")
    # 坏作者 config.json → M15d 直接 raise（独立目录，不拖累 base）
    write_mod("badcfg", "def on_load(ctx): pass")
    write_file("badcfg/config.json", "{oops")
    mgr9.unload()   # 先卸，防 content 二次注册冲突
    badcfg_dir = Path(tempfile.mkdtemp(prefix="slm_badcfg_"))
    import shutil as _sh2
    _sh2.copytree(base / "badcfg", badcfg_dir / "badcfg")
    expect_raise(lambda: ModManager(None, badcfg_dir).load_all(),
                 "config.json", "坏 config.json 加载")
    # 清走 base 里的 badcfg，后续段落用 base 都是健康 mod
    _sh2.rmtree(base / "badcfg")

    # ---------- 10. 依赖关系（拓扑序 / 版本门禁 / 缺依赖 / 环 / 禁用传导） ----------
    # M15d：依赖不满足/缺依赖/环一律 raise；好依赖链与坏依赖链分目录测。
    print("[10] 依赖关系:")
    write_mod("dep_a", "def on_load(ctx): pass")
    write_mod("dep_b", "def on_load(ctx): pass",
              '"dependencies": {"dep_a": ">=1.0"}')
    write_mod("dep_e", "def on_load(ctx): pass",
              '"dependencies": {"dep_a": "1.0"}')
    mgrA = ModManager(None, base).load_all()
    loadedA = [c.name for c in mgrA.ctxs]
    idxA = {n: i for i, n in enumerate(loadedA)}
    check("dep_a" in loadedA and "dep_b" in loadedA and "dep_e" in loadedA,
          f"依赖成功加载缺失: {loadedA}")
    check(idxA["dep_a"] < idxA.get("dep_b", 999)
          and idxA["dep_a"] < idxA.get("dep_e", 999),
          "依赖顺序错（A 应在 B/E 前）")

    def write_mod_in(dirpath, name, main_src, json_extra=""):
        d = Path(dirpath) / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "mod.json").write_text(
            '{"name": "%s", "version": "1.0", "description": "t"%s}\n'
            % (name, (", " + json_extra) if json_extra else ""),
            encoding="utf-8")
        (d / "main.py").write_text(main_src, encoding="utf-8")

    dep_dir = Path(tempfile.mkdtemp(prefix="slm_dep_"))
    # 版本不满足 → raise
    dv = dep_dir / "ver"
    write_mod_in(dv, "dep_a", "def on_load(ctx): pass")
    write_mod_in(dv, "dep_c", "def on_load(ctx): pass",
                 '"dependencies": {"dep_a": ">=2.0"}')
    expect_raise(lambda: ModManager(None, dv).load_all(),
                 "不满足", "版本门禁")
    # 缺依赖 → raise
    dm = dep_dir / "missing"
    write_mod_in(dm, "dep_d", "def on_load(ctx): pass",
                 '"dependencies": {"ghost_mod": ""}')
    expect_raise(lambda: ModManager(None, dm).load_all(),
                 "缺少依赖", "缺依赖")
    # 依赖环 → raise
    dc = dep_dir / "cycle"
    write_mod_in(dc, "dep_f", "def on_load(ctx): pass",
                 '"dependencies": {"dep_g": ""}')
    write_mod_in(dc, "dep_g", "def on_load(ctx): pass",
                 '"dependencies": {"dep_f": ""}')
    expect_raise(lambda: ModManager(None, dc).load_all(),
                 "依赖环", "依赖环")
    # 禁用传导：禁用 dep_a → 依赖它的 dep_b/dep_e 重载时 raise
    expect_raise(lambda: mgrA.set_disabled("dep_a", True),
                 "缺少依赖", "禁用传导")
    mgrA.set_disabled("dep_a", False)   # 恢复（load_all 正常）
    # 版本比较单元
    from stellarloom.mod import _ver_match
    check(_ver_match("1.0", ">=1.0") and _ver_match("1.2", ">1.0")
          and _ver_match("1.0", "==1.0") and not _ver_match("0.9", ">=1.0")
          and not _ver_match("1.1", "<1.0") and _ver_match("2.5", ">=1.0.9"),
          "版本比较错")
    mgrA.unload()
    print("  config 合并/落盘/坏文件隔离 ✓ 依赖拓扑/版本门禁/缺依赖/环/禁用传导 ✓")

    # ---------- 11. Minecraft 风格注解 mixin（@Mixin/@Inject/@Overwrite） ----------
    print("[11] 注解式 mixin:")
    write_mod("mcmixin", '''
from stellarloom.api import Mixin, Inject, At, Overwrite
from stellarloom.sim.sim import Simulation

HITS = {"head": 0, "ret": 0, "craft": 0}

@Mixin("stellarloom.sim.sim.Simulation")
class SimPatches:
    @Inject(method="place_building", at=At.HEAD, cancellable=True)
    def block_spot(self, btype, gx, gy, rot, cir):
        HITS["head"] += 1
        if gx == 77 and gy == 77:
            cir.cancel()
            cir.set_return("blocked")

    @Inject(method="place_building", at=At.RETURN)
    def annotate(self, btype, gx, gy, rot, cir):
        HITS["ret"] += 1
        if cir.get_return() == "ok":
            cir.set_return("ok_loud")

    @Overwrite(method="remove_building")
    def my_remove(self, gx, gy):
        return (False, "no")

@Mixin(Simulation)
class CraftProbe:
    @Inject(method="do_craft", at=At.HEAD)
    def probe(self, rid, times, cir):
        HITS["craft"] += 1
''')
    g11 = Game(screen)
    g11.mod_mgr.unload()          # 先卸真实 mods（mixin 污染铁律）
    mgr11 = ModManager(g11, base).load_all()
    check(any(c.name == "mcmixin" for c in mgr11.ctxs),
          "mcmixin 注解加载失败")
    g11.sim.inventory[100 + C.B_BELT] = 99   # 保证有传送带可建
    # HEAD + cancellable：cancel 跳过原方法并返回 set_return
    r = g11.sim.place_building(C.B_BELT, 77, 77, 0)
    check(r == "blocked", f"HEAD cancel 没生效: {r}")
    # HEAD 不 cancel 不改参：原调用照常；RETURN 覆盖 ok→ok_loud
    r = g11.sim.place_building(C.B_BELT, 5, 5, 0)
    check(r == "ok_loud", f"RETURN 覆盖没生效: {r}")
    hh = _m("mcmixin", "HITS")
    check(hh["head"] >= 2 and hh["ret"] >= 2, f"HITS 计数错: {hh}")
    r = g11.sim.remove_building(5, 5)
    check(r == (False, "no"), f"Overwrite 没生效: {r}")
    # 类对象 target + do_craft HEAD（无副作用计数）
    g11.sim.do_craft("iron_plate", 1)
    check(hh["craft"] >= 1, "类对象 target 注入没生效")
    # 卸载还原：包装撤掉，行为回到原版
    mgr11.unload()
    r = g11.sim.place_building(C.B_BELT, 6, 6, 0)
    check(r == "ok", f"卸载后未还原: {r}")
    r = g11.sim.remove_building(6, 6)
    check(r is not (False, "no"), "卸载后 Overwrite 未还原")
    # 坏注入目标 → M15d 直接 raise（独立目录）
    badmx_dir = Path(tempfile.mkdtemp(prefix="slm_badmx_"))
    write_mod_in(badmx_dir, "badmixin", '''
from stellarloom.api import Mixin, Inject
@Mixin("no.such.Class")
class BadMC:
    @Inject(method="nope", at="HEAD")
    def x(self, cir):
        pass
''')
    expect_raise(lambda: ModManager(g11, badmx_dir).load_all(),
                 "no.such", "坏 mixin 目标")
    g11.mod_mgr.unload()
    print("  @Mixin/@Inject(HEAD/RETURN)/@Overwrite/自动收集/类对象target/卸载还原/失败隔离 ✓")

    # ---------- 12. M7 物品注册表（MC 风格：名字注册动态分配 / 数字兼容 / 存档名字） ----------
    print("[12] M7 物品注册表:")
    from stellarloom.registry import ITEM_REGISTRY as IR
    from stellarloom.api import ModContext
    _mc = ModContext("regmod", "1.0", "t", None)   # 直接注册本 mod 的内容
    _mc.add_item("regmod:ingot", "注册锭", "#AA66FF")
    _mc.add_item("regmod:bar", "注册条", "#CC88FF")
    _mc.add_item(400, "固定锭", "#BB77FF")
    _mc.add_recipe("reg_bar",
                   {"regmod:ingot": 2, "stellarloom:iron_plate": 1},
                   {"regmod:bar": 1}, 1.0)
    ingot_id = IR.id_of("regmod:ingot")
    check(ingot_id >= 15 and ingot_id not in (101, 102),  # 动态段，避开原版
          f"动态分配错: {ingot_id}")
    check(IR.id_of(400) == 400 and IR.name_of(400) == "regmod:item400",
          "固定段兼容错")
    check(IR.id_of("1") == 1 and IR.name_of(1) == "stellarloom:iron_ore",
          "数字串/名字反查错")
    # 视图同步：mod 注册后 C.ITEM_NAMES 立即可见（UI 零改动）
    check(C.ITEM_NAMES.get(ingot_id) == "注册锭"
          and C.ITEM_COLORS.get(ingot_id) == (170, 102, 255),
          f"ITEM_NAMES 视图没同步: {ingot_id}")
    # 配方名字化后运行时数字
    ins, outs, dur, mach = C.RECIPES["reg_bar"]
    check(ins == {ingot_id: 2, C.I_IRON_PLATE: 1} and outs == {IR.id_of("regmod:bar"): 1},
          f"名字配方转数字错: {ins} -> {outs}")
    # 存档 dump 用名字键（mod 命名空间）
    from stellarloom.save.savefile import SaveManager
    _tmp = tempfile.mkdtemp(prefix="slm_reg_")
    _sm = SaveManager(_tmp)
    g12 = Game(screen)
    g12.mod_mgr.unload()
    g12.inventory[ingot_id] = 6
    g12.inventory[C.I_IRON_PLATE] = 2
    _d = _sm.dump(g12)
    _dinv = _d["stats"]["inventory"]
    check(_dinv.get("regmod:ingot") == 6
          and _dinv.get("stellarloom:iron_plate") == 2
          and all(":" in str(k) for k in _dinv),
          f"dump 物品键没名字化: {_dinv}")
    # 冲突拒绝 + 卸载还原（含固定段）
    try:
        _mc.add_item("regmod:ingot", "x"); check(False, "重名没拒绝")
    except Exception:
        check(True, "重名拒绝 OK")
    _mc._unload()
    check(not IR.has_name("regmod:ingot"), "卸载没还原名字注册")
    try:
        IR.id_of(400)
        check(False, "卸载后固定 400 还能查到")
    except Exception:
        check(True, "卸载后固定段已撤 OK")
    g12.mod_mgr.unload()
    print("  动态分配/固定段兼容/视图同步/名字配方/存档名字化/冲突拒绝/卸载还原 ✓")

    # ---------- 13. M8 建筑注册表（名字注册动态分配 / 数字兼容 / BUILD_ITEM 联动） ----------
    print("[13] M8 建筑注册表:")
    from stellarloom.registry import BUILDING_REGISTRY as BR
    _bc = ModContext("regmod", "1.0", "t", None)
    _fid = _bc.add_building("regmod:foundry", "铸造厂")
    check(_fid >= BR.DYNAMIC_START and _fid not in range(1, 14),
          f"建筑动态分配错: {_fid}")
    check(BR.name_of(_fid) == "regmod:foundry" and BR.id_of("regmod:foundry") == _fid,
          "建筑名字↔id 反查错")
    check(C.BUILDING_NAMES.get(_fid) == "铸造厂", "BUILDING_NAMES 视图没同步")
    # BUILD_ITEM 联动（放置消耗/拆除返还自动生效）
    _bc.add_item("regmod:foundry_kit", "铸造厂套装", "#AA66FF")
    _f2 = _bc.add_building("regmod:smelter", "熔炼塔",
                           item="regmod:foundry_kit")
    check(C.BUILD_ITEM.get(_f2) == C.ITEM_IDS["regmod:foundry_kit"],
          "BUILD_ITEM 联动没注册")
    # 固定段兼容 + 配方 machines 名字
    _b3 = _bc.add_building(90, "老式机器")
    check(BR.name_of(90) == "regmod:b90" and _b3 == 90, "建筑固定段错")
    _bc.add_recipe("reg_smelt", {"stellarloom:iron_ore": 2},
                   {"stellarloom:iron_plate": 1}, 1.0,
                   machines=("regmod:smelter",))
    check(C.RECIPES["reg_smelt"][3] == (_f2,),
          f"配方 machines 名字没转数字: {C.RECIPES['reg_smelt'][3]}")
    # machines 引用未注册建筑 → 拒绝
    try:
        _bc.add_recipe("reg_bad", {"stellarloom:iron_ore": 2},
                       {"stellarloom:iron_plate": 1}, 1.0,
                       machines=("no:such",))
        check(False, "未知机器没拒绝")
    except Exception:
        check(True, "未知机器拒绝 OK")
    # 卸载还原
    _bc._unload()
    check(not BR.has_name("regmod:foundry") and not BR.has_name("regmod:b90"),
          "建筑卸载没还原")
    check(_f2 not in C.BUILD_ITEM, "BUILD_ITEM 卸载没撤")
    print("  动态分配/视图同步/BUILD_ITEM 联动/固定段兼容/机器名字配方/冲突拒绝/卸载还原 ✓")

    pygame.quit()
    if bad:
        print(f"FAIL {bad} 处")
        return 1
    print("PASS MOD 系统全部通过")
    return 0


def _m(mod_name: str, var: str) -> int:
    import importlib
    return getattr(importlib.import_module(f"mod_{mod_name}_main"), var, -1)


sys.exit(main())