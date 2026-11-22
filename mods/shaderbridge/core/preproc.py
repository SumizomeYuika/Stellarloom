"""预处理器 v2：include 展开 → 条件求值 → 对象宏替换 → DRAWBUFFERS 提取。

与 v1 的区别：不再"删行"处理 STAGE_ 标记，而是交给 Cond 真正求值，
保证 #if/#endif 配对完整。
"""

import os
import re

INC_RE = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]')
DRAW_RE = re.compile(r"/\*\s*DRAWBUFFERS\s*:\s*([0-9a-fA-F+\s]+?)\s*\*/")


class PreprocError(Exception):
    pass


class Preprocessor:
    def __init__(self, root, defines=None, overrides=None):
        """
        overrides: {绝对路径: 替换后的文本}。用于 const 形式的选项改写——
        不能改用户磁盘上的包，只在内存里替换，换包/还原丢缓存即可。
        """
        self.root = os.path.abspath(root)
        self.initial_defines = dict(defines or {})
        self.overrides = dict(overrides or {})
        self.stack = []
        self.stats = {"files": 0, "includes": 0, "maxdepth": 0}
        self.missing = []

    def set_overrides(self, overrides):
        self.overrides = dict(overrides or {})

    def resolve(self, inc):
        p = inc.strip()
        if p.startswith("/"):
            p = p[1:]
        return os.path.normpath(os.path.join(self.root, p))

    def read_tree(self, path, depth=0):
        """递归取回 entry 文件 + 所有 include 的**原始文本树**（不展开）。"""
        self.stats["maxdepth"] = max(self.stats["maxdepth"], depth)
        ap = os.path.abspath(path)
        if depth > 32:
            raise PreprocError("include 嵌套过深（>32）: %s" % path)
        if ap in self.stack:
            chain = " -> ".join(os.path.basename(x) for x in self.stack)
            raise PreprocError("include 循环: %s -> %s"
                               % (chain, os.path.basename(ap)))
        # 内存覆盖优先（const 选项改写走这条路）
        text = self.overrides.get(ap)
        if text is None:
            if not os.path.isfile(ap):
                self.missing.append(ap)
                raise PreprocError("找不到文件: %s" % ap)
            self.stats["files"] += 1
            text = open(ap, "r", encoding="utf-8", errors="replace").read()
        self.stack.append(ap)
        out = []
        for line in text.splitlines():
            m = INC_RE.match(line)
            if m:
                self.stats["includes"] += 1
                out.append(self.read_tree(self.resolve(m.group(1)), depth + 1))
            else:
                out.append(line)
        self.stack.pop()
        return "\n".join(out)

    def build(self, entry, stage, extra_defines=None):
        """产出一个可直接交给编译器的单段源码。

        entry: 相对 root 的入口文件，如 'world-1/final.fsh'
        stage: 'VERTEX' / 'FRAGMENT'
        """
        raw = self.read_tree(os.path.join(self.root, entry))
        defines = dict(self.initial_defines)
        defines.update(extra_defines or {})
        defines["STAGE_" + stage] = "1"

        try:
            from .glslmacro import (Cond, expand_function_macros,
                                    expand_object_macros)
        except ImportError:                       # 被当独立脚本/工具调用
            from glslmacro import (Cond, expand_function_macros,
                                   expand_object_macros)
        c = Cond(defines)
        src, stats = c.process(raw)
        src, nfn = expand_function_macros(src, c.defs)
        src, nmac = expand_object_macros(src, c.defs)
        nmac += nfn

        # 收拢空行（避免超长文件拖慢编译器）
        lines = [ln for ln in src.splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        src = "\n".join(lines)
        if not src.endswith("\n"):
            src += "\n"
        return {
            "src": src,
            "defines": c.defs,
            "stats": stats,
            "macros_expanded": nmac,
            "drawbuffers": parse_drawbuffers(src),
            "warnings": c.warnings,
        }


def parse_drawbuffers(src):
    m = DRAW_RE.search(src)
    if not m:
        return []
    txt = m.group(1).replace(" ", "")
    if "+" in txt:
        try:
            mask = int(txt, 16)
        except ValueError:
            return []
        return [i for i in range(16) if (mask >> i) & 1]
    out = []
    for ch in txt:
        try:
            out.append(int(ch, 16))
        except ValueError:
            return []
    return out