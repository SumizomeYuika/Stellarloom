"""桌面 GLSL 330 校验：预处理 → 转译（desktop330）→ 驱动编译 → 汇总。

历史：本工具原来调外部 glslangValidator 按 ESSL 校验——那是 GLES 时代的
设计，而且这台机器上根本没装 glslangValidator。现在直接拿**真驱动**
（WGL 离屏上下文 + PyOpenGL）编译，比外部校验器更准：能通过 Intel 驱动
编译的就是能跑的。

跑法（仓库根目录）：
    python mods/shaderbridge/devtools/_escheck.py shaderpacks/cm/shaders [work]

退出码：有编译失败 = 1，全过 = 0。
"""

import collections
import os
import re
import shutil
import sys
import types
import importlib

# 与 main.py 同一套"合成包"手法，让 core/ 的相对导入可用
_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.dirname(_HERE)
if _MOD not in sys.path:
    sys.path.insert(0, _MOD)
_PKG = "shaderbridge_core"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.join(_MOD, "core")]
    pkg.__package__ = _PKG
    sys.modules[_PKG] = pkg

preproc = importlib.import_module(_PKG + ".preproc")
glsl_es = importlib.import_module(_PKG + ".glsl_es")
glctx = importlib.import_module(_PKG + ".glctx")
glapi = importlib.import_module(_PKG + ".glapi")
program = importlib.import_module(_PKG + ".program")

Preprocessor = preproc.Preprocessor
transpile = glsl_es.transpile

# 把错误消息粗分类，便于统计"哪类问题占大头"
BUCKETS = [
    (re.compile(r"wrong operand types"), "隐式类型不匹配"),
    (re.compile(r"no matching overloaded function"), "重载不匹配（多是隐式转换）"),
    (re.compile(r"undeclared identifier|Undeclared"), "未声明标识符"),
    (re.compile(r"syntax error|Syntax error"), "语法错误"),
    (re.compile(r"cannot convert|Cannot convert"), "不能转换"),
    (re.compile(r"l-value|assign"), "赋值左值问题"),
    (re.compile(r"version|#version"), "版本行问题"),
]


def classify(msg):
    for pat, name in BUCKETS:
        if pat.search(msg):
            return name
    return "其他"


def entries(root):
    out = []
    for world in ("", "world0", "world-1", "world1"):
        base = os.path.join(root, world) if world else root
        if not os.path.isdir(base):
            continue
        for n in sorted(os.listdir(base)):
            if n.endswith(".vsh") or n.endswith(".fsh"):
                out.append(((world + "/" + n) if world else n,
                            "VERTEX" if n.endswith(".vsh") else "FRAGMENT"))
    return out


def compile_stage(api, stage, src):
    """用驱动编译单阶段源码，返回错误日志（空 = 通过）。"""
    kind = glapi.GL_VERTEX_SHADER if stage == "VERTEX" \
        else glapi.GL_FRAGMENT_SHADER
    sh = api.glCreateShader(kind)
    api.glShaderSource(sh, 1, (glapi.c_char_p * 1)(
        src.encode("utf-8")), None)
    api.glCompileShader(sh)
    ok = glapi.c_int(0)
    api.glGetShaderiv(sh, glapi.GL_COMPILE_STATUS, glapi.byref(ok))
    log = ""
    if not ok.value:
        ln = glapi.c_int(0)
        api.glGetShaderiv(sh, glapi.GL_INFO_LOG_LENGTH, glapi.byref(ln))
        buf = glapi.create_string_buffer(max(2, ln.value))
        api.glGetShaderInfoLog(sh, ln.value, None, buf)
        log = buf.value.decode("utf-8", "replace")
    api.glDeleteShader(sh)
    return log


def main():
    root = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else ""
    if work:
        os.makedirs(work, exist_ok=True)

    okc, ctx = glctx.probe()
    if not okc:
        print("建 WGL 上下文失败: %s" % "; ".join(ctx.errors))
        return 2
    print("驱动: %s | %s\n" % (ctx.version, ctx.renderer))
    api = glapi.open_gl()

    jobs = entries(root)
    ok, fail = [], []
    buckets = collections.Counter()
    samples = collections.defaultdict(list)

    for rel, stage in jobs:
        try:
            r = Preprocessor(root).build(rel, stage)
            t = transpile(r["src"], stage, r["drawbuffers"],
                          target="desktop330")
        except Exception as e:
            fail.append((rel, stage, ["预处理/转译异常: %s" % e]))
            buckets["转译异常"] += 1
            continue
        if work:
            open(os.path.join(work, rel.replace("/", "_")),
                 "w", encoding="utf-8").write(t.src)
        log = compile_stage(api, stage, t.src)
        if not log:
            ok.append((rel, stage))
            continue
        msgs = [l.strip() for l in log.splitlines() if l.strip()][:4]
        fail.append((rel, stage, msgs))
        for msg in msgs:
            b = classify(msg)
            buckets[b] += 1
            if len(samples[b]) < 6:
                samples[b].append((rel, msg[:110]))

    ctx.release()

    print("=" * 74)
    print("桌面 330 校验（真驱动编译）：共 %d | 通过 %d | 失败 %d"
          % (len(jobs), len(ok), len(fail)))
    print("=" * 74)
    if buckets:
        print("\n错误类型分布：")
        for b, n in buckets.most_common():
            print("  %-24s %d" % (b, n))
        print("\n各类样例：")
        for b in buckets:
            print("\n[%s]" % b)
            for rel, msg in samples[b]:
                print("   %-34s %s" % (rel, msg))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
