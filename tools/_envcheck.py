#!/usr/bin/env python3
"""M15d @EnvType 侧标自检（第 34 项）。

[1] @EnvType("client") 的 @Mixin 类：客户端装、服务端跳
[2] @EnvType("server") 的 @Mixin 类：服务端装、客户端跳
[3] mixin 方法级 @EnvType：同类里按方法过滤
[4] ctx.mixin 的 wrapper 带 @EnvType：命令式补丁同样过滤
[5] on_load 带 @EnvType("client")：服务端整段跳过
[6] 未标记的旧 mod：两侧都装（兼容默认 both）
[7] 真实 mods/：服务端侧加载 jade（纯 UI mod）被跳过、不崩

跑法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/_envcheck.py
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom.mod import load_mods  # noqa: E402
from stellarloom.sim import Simulation  # noqa: E402

bad = 0


def check(cond, msg):
    global bad
    if not cond:
        bad += 1
        print(f"  !! FAIL {msg}")


class _Shim:
    """最小 game 外观（load_mods 只需要 sim + _toast_msg）。"""

    def __init__(self):
        self.sim = Simulation()

    def _toast_msg(self, *a, **k):
        pass


MOD_SRC = '''
from stellarloom.api import Mixin, Inject, EnvType

HITS = {"cli_cls": 0, "srv_cls": 0, "cli_fn": 0, "srv_fn": 0,
        "cli_wrap": 0, "srv_wrap": 0, "both_wrap": 0, "onload": 0}


@EnvType("client")
@Mixin("stellarloom.sim.sim.Simulation")
class CliOnly:
    @Inject(method="cancel_craft", at="HEAD")
    def h(self, cir):
        HITS["cli_cls"] += 1


@EnvType("server")
@Mixin("stellarloom.sim.sim.Simulation")
class SrvOnly:
    @Inject(method="cancel_craft", at="HEAD")
    def h(self, cir):
        HITS["srv_cls"] += 1


@Mixin("stellarloom.sim.sim.Simulation")
class BothCls:
    @EnvType("client")
    @Inject(method="cancel_craft", at="HEAD")
    def hc(self, cir):
        HITS["cli_fn"] += 1

    @EnvType("server")
    @Inject(method="cancel_craft", at="HEAD")
    def hs(self, cir):
        HITS["srv_fn"] += 1


def on_load(ctx):
    HITS["onload"] += 1

    @EnvType("client")
    def w_cli(self, *a, **k):
        HITS["cli_wrap"] += 1

    @EnvType("server")
    def w_srv(self, *a, **k):
        HITS["srv_wrap"] += 1

    def w_both(self, *a, **k):
        HITS["both_wrap"] += 1

    ctx.mixin("stellarloom.sim.sim.Simulation", "cancel_craft",
              w_cli, wrap="before")
    ctx.mixin("stellarloom.sim.sim.Simulation", "cancel_craft",
              w_srv, wrap="before")
    ctx.mixin("stellarloom.sim.sim.Simulation", "cancel_craft",
              w_both, wrap="before")
'''

MOD_SRC_CLIONLY_ONLOAD = '''
from stellarloom.api import EnvType

HITS = {"onload": 0}


@EnvType("client")
def on_load(ctx):
    HITS["onload"] += 1
'''


def _write_mod(base: Path, name: str, src: str):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "mod.json").write_text(
        json.dumps({"name": name, "version": "1.0"}), encoding="utf-8")
    (d / "main.py").write_text(src, encoding="utf-8")


def _hits(mod_name):
    m = importlib.import_module(f"mod_{mod_name}_main")
    return dict(m.HITS)


def main() -> int:
    shim = _Shim()

    # ---------- [1-4][6] mixin 类级 / 方法级 / wrapper 级 / 未标默认 ----------
    print("[1-4][6] mixin 侧标过滤:")
    base = Path(tempfile.mkdtemp(prefix="slm_env_"))
    _write_mod(base, "envmod", MOD_SRC)

    # 服务端侧：client 标的全跳、server 标的全装、未标（both）照装
    mgr_s = load_mods(shim, base, side="server")
    shim.sim.cancel_craft()
    hs = _hits("envmod")
    check(hs["cli_cls"] == 0 and hs["cli_fn"] == 0 and hs["cli_wrap"] == 0,
          f"服务端没跳过 client 标: {hs}")
    check(hs["srv_cls"] == 1 and hs["srv_fn"] == 1 and hs["srv_wrap"] == 1,
          f"服务端没装 server 标: {hs}")
    check(hs["both_wrap"] == 1, f"服务端没装未标 mixin: {hs}")
    check(hs["onload"] == 1, f"服务端没跑未标 on_load: {hs}")
    mgr_s.unload()

    # 客户端侧：正好反过来
    mgr_c = load_mods(shim, base, side="client")
    shim.sim.cancel_craft()
    hc = _hits("envmod")
    check(hc["cli_cls"] == 1 and hc["cli_fn"] == 1 and hc["cli_wrap"] == 1,
          f"客户端没装 client 标: {hc}")
    check(hc["srv_cls"] == 1 and hc["srv_fn"] == 1 and hc["srv_wrap"] == 1,
          f"客户端没跳过 server 标（计数应仍是服务端时的 1）: {hc}")
    mgr_c.unload()

    # ---------- [5] on_load 的 @EnvType ----------
    print("[5] on_load 侧标:")
    base2 = Path(tempfile.mkdtemp(prefix="slm_envol_"))
    _write_mod(base2, "olmod", MOD_SRC_CLIONLY_ONLOAD)
    mgr2 = load_mods(shim, base2, side="server")
    check(_hits("olmod")["onload"] == 0,
          "服务端没跳过 client 标的 on_load")
    check(any(c.name == "olmod" for c in mgr2.ctxs),
          "on_load 被跳过不应影响 mod 登记（mixin/配置仍生效）")
    mgr2.unload()
    mgr3 = load_mods(shim, base2, side="client")
    check(_hits("olmod")["onload"] == 1, "客户端没跑 on_load")
    mgr3.unload()

    # ---------- [7] 真实 mods/：服务端侧 jade 被跳过、整体不崩 ----------
    print("[7] 真实 mods/ 服务端侧:")
    mgr4 = load_mods(shim, side="server")
    names = [c.name for c in mgr4.ctxs]
    check("gregtech_heavy" in names, f"逻辑 mod 没装上: {names}")
    # jade 的 mixin 目标是 Game._draw_ui（纯 UI）：服务端侧必须没打补丁
    from stellarloom.core.game import Game
    check(Game._draw_ui.__name__ == "_draw_ui",
          "jade 的 UI mixin 在服务端竟然生效了")
    mgr4.unload()

    print()
    if bad:
        print(f"FAIL {bad} 项: _envcheck")
        return 1
    print("PASS @EnvType 侧标全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
