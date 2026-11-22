"""整条链的离线自检：预处理 → 转译 → glslangValidator，不碰 GL。

这一层验证的是"包能被完整消化"：每个 pass 的 vsh/fsh 都产出了合法
ES 300 源码。GL 编译那一步要靠 glslangValidator 代理——它不是真驱动，
但语法/类型/精度/location 的错误它都抓得到，是真机前的最后一道闸。

跑法：python3 devtools/_chaincheck.py <shaders根目录> [world]
"""

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.dirname(os.path.dirname(ROOT))
sys.path.insert(0, ROOT)
sys.path.insert(0, GAME)

from core import chain, packscan                           # noqa: E402


def validate(src, ext, tmpdir, tag):
    """用 glslangValidator 校验一段 ES 300 源码。返回 (ok, 消息)。"""
    path = os.path.join(tmpdir, tag + "." + ext)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        pr = subprocess.run(["glslangValidator", "-S", ext, path],
                            capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return None, "没装 glslangValidator（跳过）"
    except subprocess.TimeoutExpired:
        return False, "校验超时"
    text = ((pr.stdout or "") + (pr.stderr or "")).strip()
    return pr.returncode == 0, text


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    return cond


def main():
    if len(sys.argv) < 2:
        print("用法: _chaincheck.py <包根或 shaders 目录> [world]")
        return 2
    pack = sys.argv[1]
    world = sys.argv[2] if len(sys.argv) > 2 else "world0"

    print("== 扫描包 ==")
    info = packscan.scan_pack(pack)
    print("  包名 %s，程序入口 %d，选项 %d"
          % (info.name, len(info.programs), len(info.options)))
    if not info.found:
        print("  找不到 shaders/")
        return 1

    defines = chain.option_defines(info)
    print("  注入宏定义 %d 个（只含 #define 形式选项）" % len(defines))

    print("\n== 构建 pass 表 ==")
    from core import glsl_es, passes, preproc
    specs = passes.build_passes(info, world)
    print("  world=%s → %d 条 pass" % (world, len(specs)))
    if not specs:
        print("  没有可执行的 pass")
        return 1
    names = [s.name for s in specs]
    print("  顺序: %s" % ", ".join(names[:12]))
    if len(names) > 12:
        print("        %s" % ", ".join(names[12:]))

    ok = True
    print("\n== 逐 pass 预处理+转译+校验 ==")
    shaders = os.path.join(pack, "shaders")
    if not os.path.isdir(shaders):
        shaders = pack
    pp = preproc.Preprocessor(shaders, defines)

    tmpdir = tempfile.mkdtemp(prefix="chainchk_")
    n_ok = n_fail = n_skip = 0
    bad = []
    io_filled = {}

    for spec in specs:
        if not spec.fsh_rel:
            n_skip += 1
            continue
        tag = spec.name
        try:
            r = pp.build(spec.fsh_rel, "FRAGMENT", defines)
            tf = glsl_es.transpile(r["src"], "FRAGMENT", r["drawbuffers"])
        except Exception as e:
            print("  FAIL %-20s 预处理/转译异常: %s" % (tag, e))
            bad.append((tag, "frag", str(e)))
            n_fail += 1
            continue
        io_filled[spec.name] = (r["drawbuffers"], tf.src)
        fok, fmsg = validate(tf.src, "frag", tmpdir, tag + "_f")
        if fok is None:
            n_skip += 1
            continue
        if not fok:
            print("  FAIL %-20s frag: %s" % (tag, fmsg.splitlines()[0][:100]))
            bad.append((tag, "frag", fmsg[:300]))
            n_fail += 1
            continue

        if spec.vsh_rel:
            try:
                rv = pp.build(spec.vsh_rel, "VERTEX", defines)
                tv = glsl_es.transpile(rv["src"], "VERTEX", None)
            except Exception as e:
                print("  FAIL %-20s vsh 异常: %s" % (tag, e))
                bad.append((tag, "vert", str(e)))
                n_fail += 1
                continue
            vok, vmsg = validate(tv.src, "vert", tmpdir, tag + "_v")
            if vok is False:
                print("  FAIL %-20s vert: %s"
                      % (tag, vmsg.splitlines()[0][:100]))
                bad.append((tag, "vert", vmsg[:300]))
                n_fail += 1
                continue

        n_ok += 1
        print("  OK   %-20s fsh %d 行%s"
              % (tag, len(tf.src.splitlines()),
                 "，DB=%s" % r["drawbuffers"] if r["drawbuffers"] else ""))

    print("\n" + "=" * 66)
    print("链路自检：通过 %d / 失败 %d / 跳过 %d（共 %d 条 pass）"
          % (n_ok, n_fail, n_skip, len(specs)))
    ok &= n_fail == 0

    print("\n== 补全 IO 依赖 ==")
    passes.fill_io(specs, io_filled)
    writers = {}
    for s in specs:
        for o in s.outputs:
            writers.setdefault("colortex%d" % o, []).append(s.name)
    print("  有写者的缓冲: %s" % ", ".join(sorted(writers)))
    ENGINE = {"depthtex0", "depthtex1", "depthtex2", "shadowtex0",
              "shadowtex1", "noisetex", "normals", "specular", "tex"}
    orphans = []
    for s in specs:
        for nm in s.inputs:
            if nm in ENGINE or nm in writers:
                continue
            orphans.append((s.name, nm))
    if orphans:
        for sname, nm in orphans[:8]:
            print("  警告 %s 读了没人写的 %s" % (sname, nm))
    ok &= check(not orphans, "所有输入都有来源（%d 个孤儿）" % len(orphans))

    if bad:
        print("\n失败明细（最多 5 条）:")
        for tag, stage, msg in bad[:5]:
            print("  [%s/%s] %s" % (tag, stage, msg.splitlines()[0][:140]))

    print("\n" + ("全部通过" if ok else "有失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())