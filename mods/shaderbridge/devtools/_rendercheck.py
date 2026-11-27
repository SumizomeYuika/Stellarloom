"""整帧渲染自检：compatibility profile 下真跑一个光影包一帧。

跑法（仓库根目录）：
    python mods/shaderbridge/devtools/_rendercheck.py [包路径...]
    不带参数时默认跑 shaderpacks/cm 与 shaderpacks/春眠 261014.zip。

每个包验证：
  - packscan 扫描（zip 直读，不落盘）
  - chain.build_all 编译全部 pass（失败的记 failures，不中断）
  - comp.render() 一帧，断言读回均值 > 5（不是黑屏）
  - 帧 PNG 存 %TEMP%/sb_render_<name>.png
  - 再渲染 2 帧测平均帧耗时
"""

import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.dirname(_HERE)
_GAME = os.path.dirname(os.path.dirname(_MOD))
for p in (_MOD, _GAME):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import types  # noqa: E402
import importlib  # noqa: E402

_PKG = "shaderbridge_core"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.join(_MOD, "core")]
    pkg.__package__ = _PKG
    sys.modules[_PKG] = pkg


def core(name):
    return importlib.import_module(_PKG + "." + name)


def pick_world(info):
    avail = set()
    for ent in info.programs.values():
        for rel in (ent.get("fsh"), ent.get("vsh")):
            if rel and "/" in rel:
                avail.add(rel.split("/", 1)[0])
    for cand in ("world-1", "world0", "world1", ""):
        if cand in avail or (cand == "" and not avail):
            return cand
    return "world0"


def run_pack(pack_path, label):
    packscan = core("packscan")
    chain = core("chain")
    composite_gl = core("composite_gl")

    print("=" * 60)
    print("包: %s" % pack_path)
    info = packscan.scan_pack(pack_path)
    if not info.found:
        print("  FAIL: 扫描不到 shaders/")
        return False
    zip_tag = "（zip 直读）" if getattr(info.source, "is_zip", False) \
        else "（目录）"
    print("  扫描: %s，%d 入口，%d 选项 %s"
          % (info.name, len(info.programs), len(info.options), zip_tag))

    defines = chain.option_defines(info)
    consts = {nm: s.default for nm, s in info.options.items()
              if s.source == "const" and s.default}
    world = pick_world(info)
    print("  world=%s，宏 %d 个，const 选项 %d 个"
          % (world, len(defines), len(consts)))

    ch = chain.ShaderChain(None, pack_path, info, world=world,
                           defines=defines, const_values=consts)
    comp = composite_gl.CompositeGL()
    if not comp.setup(ch, (960, 640)):
        print("  FAIL: GL 初始化: %s" % "; ".join(comp.errors[-3:]))
        return False
    ch.api = comp.api
    t0 = time.perf_counter()
    okn, failn = ch.build_all()
    t_compile = time.perf_counter() - t0
    print("  编译: %d 成功 / %d 失败（%.1f s）" % (okn, failn, t_compile))
    for n, m in ch.failures[:6]:
        print("    - %s: %s" % (n, m.splitlines()[0][:110]
                                if m else ""))

    from stellarloom import config as C
    from stellarloom.world.grid import WorldGrid
    from stellarloom.render.camera import Camera
    g = WorldGrid(64, 64, seed=7)
    g.building[32, 30] = C.B_BELT
    g.building[32, 31] = C.B_MINER
    g.ore[30, 32] = 100
    cam = Camera(64 * C.TILE, 64 * C.TILE)
    cam.zoom = 0.75
    wp = (64 * C.TILE, 64 * C.TILE)

    comp.begin_frame(cam, 0.016, 1.0, wp, grid=g)
    surf = comp.render(g, cam, dt=0.016, elapsed=1.0)
    if surf is None:
        print("  FAIL: 渲染返回空: %s" % "; ".join(comp.errors[-3:]))
        comp.release()
        return False
    print("  首帧: mean=%.2f，pass 成功 %d / 失败 %d"
          % (comp.last_mean, comp.last_passes, comp.last_failed))
    if comp.last_mean <= 5.0:
        print("  FAIL: 画面全黑（mean=%.2f）" % comp.last_mean)
        comp.release()
        return False

    # 存 PNG
    import pygame
    out = os.path.join(tempfile.gettempdir(),
                       "sb_render_%s.png" % label)
    pygame.image.save(surf, out)
    print("  PNG: %s" % out)

    # 再渲染 2 帧测耗时
    t0 = time.perf_counter()
    n = 2
    for i in range(n):
        comp.begin_frame(cam, 0.016, 1.2 + i * 0.016, wp, grid=g)
        s2 = comp.render(g, cam, dt=0.016, elapsed=1.2 + i * 0.016)
        if s2 is None:
            print("  FAIL: 第 %d 帧渲染失败" % (i + 2))
            comp.release()
            return False
    t_avg = (time.perf_counter() - t0) / n
    print("  帧耗时: %.1f ms（≈ %.0f fps）" % (t_avg * 1000, 1.0 / t_avg))

    comp.release()
    ch.release()
    return True


def main():
    packs = sys.argv[1:]
    if not packs:
        packs = [
            os.path.join(_GAME, "shaderpacks", "cm"),
            os.path.join(_GAME, "shaderpacks", "春眠 261014.zip"),
        ]
    ok = True
    for i, p in enumerate(packs):
        label = os.path.basename(os.path.normpath(p)) \
            .replace(" ", "_").replace(".zip", "")
        ok &= run_pack(p, label)
    print("=" * 60)
    print("全部通过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
