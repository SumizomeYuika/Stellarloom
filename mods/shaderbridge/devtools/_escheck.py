"""ES 300 校验：预处理 → 转译 → glslangValidator（按 ESSL 校验）→ 汇总错误类型。"""

import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
from preproc import Preprocessor          # noqa: E402
from glsl_es import transpile              # noqa: E402

ERR_RE = re.compile(r"^ERROR: \d+:(\d+): (.*)$")

# 把错误消息粗分类，便于统计"哪类问题占大头"
BUCKETS = [
    (re.compile(r"wrong operand types"), "隐式类型不匹配"),
    (re.compile(r"no matching overloaded function"), "重载不匹配（多是隐式转换）"),
    (re.compile(r"undeclared identifier"), "未声明标识符"),
    (re.compile(r"syntax error"), "语法错误"),
    (re.compile(r"cannot convert"), "不能转换"),
    (re.compile(r"l-value|assign"), "赋值左值问题"),
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


def main():
    root = sys.argv[1]
    work = sys.argv[2]
    os.makedirs(work, exist_ok=True)
    jobs = entries(root)
    ok, fail = [], []
    buckets = collections.Counter()
    samples = collections.defaultdict(list)

    for rel, stage in jobs:
        out = os.path.join(work, rel.replace("/", "_"))
        try:
            r = Preprocessor(root).build(rel, stage)
            t = transpile(r["src"], stage, r["drawbuffers"])
        except Exception as e:
            fail.append((rel, stage, ["预处理/转译异常: %s" % e]))
            buckets["转译异常"] += 1
            continue
        open(out, "w", encoding="utf-8").write(t.src)
        ext = "vert" if stage == "VERTEX" else "frag"
        pr = subprocess.run(["glslangValidator", "-S", ext, out],
                            capture_output=True, text=True, timeout=300)
        text = (pr.stdout or "") + (pr.stderr or "")
        if pr.returncode == 0:
            ok.append((rel, stage))
            continue
        msgs = []
        for line in text.splitlines():
            m = ERR_RE.match(line.strip())
            if m:
                msgs.append((int(m.group(1)), m.group(2).strip()))
        if not msgs:
            msgs = [(0, l.strip()) for l in text.splitlines() if l.strip()][:4]
        fail.append((rel, stage, msgs))
        for ln, msg in msgs:
            b = classify(msg)
            buckets[b] += 1
            if len(samples[b]) < 6:
                samples[b].append((rel, ln, msg[:110]))

    print("=" * 74)
    print("ES 300 校验：共 %d | 通过 %d | 失败 %d"
          % (len(jobs), len(ok), len(fail)))
    print("=" * 74)
    print("\n错误类型分布：")
    for b, n in buckets.most_common():
        print("  %-24s %d" % (b, n))
    print("\n各类样例：")
    for b in buckets:
        print("\n[%s]" % b)
        for rel, ln, msg in samples[b]:
            print("   %-34s L%-6d %s" % (rel, ln, msg))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())