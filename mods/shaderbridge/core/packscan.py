"""光影包扫描器：读 Iris/OptiFine 包的元信息，产出一张与包无关的选项表。

输入：包根目录（含 shaders/）
输出：PackInfo
  - name / descriptions（来自 shaders.properties 的 profile 或目录名）
  - screens：[(屏幕 id, 标题, [选项名...])]
  - sliders：哪些选项是滑条
  - options：{名字: OptionSpec}
  - programs：{入口文件名: (相对路径, 是否有 vsh/fsh)}
  - toggles：包级开关（sun/moon/stars/clouds/oldLighting/vignette...）
  - block_ids：block.properties 里的方块 id（可选，用于材质识别）

选项类型判定：
  constants.glsl 里 `#define X 1`       → bool/int
  `#define X 1.0`                        → float
  `#define X 0.7  // [0.5 0.6 0.7]`     → float + 档位
  `const float X = 1.0; // [0.0 0.5 1]` → float + 档位（const 声明式选项）
  `#define X vec3(...)`                 → vec3（只读展示，不给控件）
"""

import json
import os
import re

DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s*(.*)$")
CONST_RE = re.compile(
    r"^\s*const\s+(?:highp\s+|mediump\s+|lowp\s+)?"
    r"(float|int|bool|vec2|vec3|vec4)\s+([A-Za-z_]\w*)\s*=\s*([^;]+);(.*)$")
VALUES_RE = re.compile(r"\[([^\]]*)\]")
NUM_LITERAL_RE = re.compile(r"^-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?)$")


class OptionSpec:
    """一个可调项。"""

    __slots__ = ("name", "kind", "default", "values", "comment", "label",
                 "value_labels", "screen", "is_slider", "source")

    def __init__(self, name):
        self.name = name
        self.kind = "unknown"     # bool / int / float / enum / vec3 / other
        self.default = None
        self.values = []          # 可选档位（原样字符串）
        self.comment = ""
        self.label = ""           # 本地化显示名
        self.value_labels = {}    # 档位值 -> 本地化短名
        self.screen = ""
        self.is_slider = False
        self.source = ""          # define / const

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return "<Option %s %s=%r n=%d>" % (self.name, self.kind,
                                           self.default, len(self.values))


class PackInfo:
    def __init__(self, root):
        self.root = root
        self.name = os.path.basename(os.path.normpath(root))
        self.screens = []        # [(id, 标题, [选项名])]
        self.sliders = set()
        self.options = {}        # name -> OptionSpec
        self.toggles = {}        # sun/moon/stars/clouds/oldLighting/vignette
        self.programs = {}       # 名字 -> {"vsh": rel|None, "fsh": rel|None}
        self.block_ids = {}
        self.warnings = []
        self.found = False

    def option_list(self):
        return [self.options[n] for n in sorted(self.options)]

    def to_summary(self):
        return {
            "name": self.name,
            "screens": [(sid, title, len(names))
                        for sid, title, names in self.screens],
            "options": len(self.options),
            "sliders": len(self.sliders),
            "toggles": self.toggles,
            "programs": len(self.programs),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------- properties

def _parse_properties(text):
    """shaders.properties → dict。支持 #ifdef 之外的行（条件行原样记录忽略）。"""
    out = {}
    cond_stack = []
    active = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            # #ifdef 等仍需跟踪，但 Iris 的 properties 条件一般不影响选项表
            if line.startswith("#if"):
                cond_stack.append(active)
                active = False       # 条件块里的内容先当未知处理（保持保守）
            elif line.startswith("#endif"):
                active = cond_stack.pop() if cond_stack else True
            elif line.startswith("#comment") or line.startswith("#"):
                if active and line.startswith("#") and "=" in line:
                    k, _, v = line.lstrip("#").partition("=")
                    out.setdefault(k.strip(), v.strip())
            continue
        if not active:
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
        else:
            out[line] = ""
    return out


def _split_tokens(s):
    return [t for t in re.split(r"[\s]+", s.strip()) if t]


def scan_pack(root):
    info = PackInfo(root)
    shaders = os.path.join(root, "shaders")
    if not os.path.isdir(shaders):
        # 也允许直接把 shaders 目录当根
        if os.path.basename(os.path.normpath(root)) == "shaders":
            shaders = root
            info.root = os.path.dirname(os.path.normpath(root))
        else:
            info.warnings.append("找不到 shaders/ 目录")
            return info
    info.found = True

    props = {}
    ptext_path = os.path.join(shaders, "shaders.properties")
    if os.path.isfile(ptext_path):
        props = _parse_properties(
            open(ptext_path, "r", encoding="utf-8", errors="replace").read())
    else:
        info.warnings.append("缺少 shaders.properties")

    # 包级开关
    for key in ("sun", "moon", "stars", "clouds", "oldLighting", "oldHandLight",
                "separateAo", "underwaterOverlay", "vignette", "rain.depth",
                "shadowTerrain", "shadowTranslucent", "shadowEntities"):
        if key in props:
            info.toggles[key] = props[key]

    # 屏幕分组：screen = [A] [B]   screen.A = opt1 opt2 ...
    screen_order = re.findall(r"\[([^\]]+)\]", props.get("screen", ""))
    for sid in screen_order:
        names = _split_tokens(props.get("screen." + sid, ""))
        info.screens.append((sid, sid, names))

    for k, v in props.items():
        if k.startswith("screen.") and k[7:] not in screen_order:
            info.screens.append((k[7:], k[7:], _split_tokens(v)))

    for name in _split_tokens(props.get("sliders", "")):
        info.sliders.add(name)

    _scan_constants(info, shaders)
    _scan_lang(info, shaders)
    _scan_programs(info, shaders)
    return info


def _scan_constants(info, shaders):
    """从所有 .glsl 里收集 #define 与 const 声明的选项（带 // [档位] 的才算选项）。"""
    cand = {}
    for dirpath, dirnames, names in os.walk(shaders):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for n in names:
            if not n.endswith(".glsl"):
                continue
            path = os.path.join(dirpath, n)
            try:
                text = open(path, "r", encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            for line in text.splitlines():
                m = DEFINE_RE.match(line)
                if m:
                    nm, rest = m.group(1), m.group(2)
                    _record(cand, nm, rest, "define")
                    continue
                m = CONST_RE.match(line)
                if m:
                    typ, nm, val, tail = (m.group(1), m.group(2),
                                          m.group(3), m.group(4))
                    _record(cand, nm, val + tail, "const", typ)
    # 只保留"有档位注释"或"在屏幕分组里出现"的项
    listed = set()
    for _, _, names in info.screens:
        listed.update(names)
    listed.update(info.sliders)
    for nm, spec in cand.items():
        if spec.values or nm in listed:
            info.options[nm] = spec
    # 屏幕分组里引用了但没找到定义的，也留位置（显示为未知）
    for nm in listed:
        if nm not in info.options and nm not in info.toggles:
            info.options[nm] = OptionSpec(nm)
    # 归属屏幕
    for sid, _title, names in info.screens:
        for nm in names:
            if nm in info.options:
                info.options[nm].screen = sid
    for nm in info.sliders:
        if nm in info.options:
            info.options[nm].is_slider = True


def _record(cand, name, raw, source, ctype=None):
    """解析一行定义里的值 + 档位注释。"""
    val, comment = raw, ""
    pos = raw.find("//")
    if pos >= 0:
        val, comment = raw[:pos], raw[pos + 2:]
    val = val.strip()
    comment = comment.strip()
    spec = cand.get(name)
    if spec is None:
        spec = OptionSpec(name)
        cand[name] = spec
    if not spec.source or source == "define":
        spec.source = source
    spec.default = val
    if comment and not spec.comment:
        spec.comment = comment
    mv = VALUES_RE.search(comment)
    if mv and not spec.values:
        spec.values = _split_tokens(mv.group(1))
    if ctype:
        spec.kind = {"true": "bool", "false": "bool"}.get(val, ctype)
    if spec.kind in ("unknown", ""):
        spec.kind = _guess_kind(val)
    if spec.values and spec.kind in ("float", "int", "unknown"):
        spec.kind = "enum"
    return spec


def _guess_kind(val):
    v = (val or "").strip()
    if v in ("true", "false"):
        return "bool"
    if v == "":
        return "bool"         # #define X（无值）= 开关
    if NUM_LITERAL_RE.match(v):
        return "float" if ("." in v or "e" in v.lower()) else "int"
    if v.startswith("vec2") or v.startswith("vec3") or v.startswith("vec4"):
        return "vec3"
    if v.startswith("("):
        return "expr"
    return "other"


def _scan_lang(info, shaders):
    """读 lang/*.lang，挂上显示名、说明、档位短名。中文优先。"""
    lang_dir = os.path.join(shaders, "lang")
    if not os.path.isdir(lang_dir):
        return
    files = {}
    for n in os.listdir(lang_dir):
        if n.endswith(".lang"):
            try:
                files[n] = open(os.path.join(lang_dir, n), "r",
                                encoding="utf-8", errors="replace").read()
            except OSError:
                pass
    prefer = []
    for pfx in ("zh_cn", "zh_CN", "en_us", "en_US"):
        for n in files:
            if n.startswith(pfx):
                prefer.append(n)
    prefer += [n for n in files if n not in prefer]
    merged = {}
    for n in reversed(prefer):        # 反向覆盖 → 高优先级最后写
        for line in files[n].splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            merged[k.strip()] = v.strip()

    for k, v in merged.items():
        if k.startswith("screen."):
            sid = k[7:]
            for i, (s, title, names) in enumerate(info.screens):
                if s == sid:
                    info.screens[i] = (s, v, names)
                    break
            else:
                info.screens.append((sid, v, []))
            continue
        if not k.startswith("option."):
            if k.startswith("value."):
                rest = k[6:]
                nm, _, vk = rest.rpartition(".")
                spec = info.options.get(nm)
                if spec:
                    spec.value_labels[vk] = v
            continue
        rest = k[7:]
        if rest.endswith(".comment"):
            nm = rest[:-8]
            spec = info.options.get(nm)
            if spec:
                spec.comment = v
        else:
            spec = info.options.get(rest)
            if spec:
                spec.label = v


def _scan_programs(info, shaders):
    """收集各 world 变体 + 根目录的 program 入口。"""
    dirs = [""]
    for n in sorted(os.listdir(shaders)):
        if n.startswith("world") and os.path.isdir(os.path.join(shaders, n)):
            dirs.append(n)
    for d in dirs:
        base = os.path.join(shaders, d) if d else shaders
        if not os.path.isdir(base):
            continue
        for n in sorted(os.listdir(base)):
            if not (n.endswith(".vsh") or n.endswith(".fsh")):
                continue
            stem = n.rsplit(".", 1)[0]
            ent = info.programs.setdefault(stem, {"vsh": None, "fsh": None})
            rel = (d + "/" + n) if d else n
            ent["vsh" if n.endswith(".vsh") else "fsh"] = rel


def dump_summary(info):
    s = info.to_summary()
    lines = []
    lines.append("包名: %s" % s["name"])
    lines.append("找到 shaders/: %s" % info.found)
    lines.append("选项总数: %d（滑条 %d）" % (s["options"], s["sliders"]))
    lines.append("程序入口: %d" % s["programs"])
    lines.append("包级开关: %s" % json.dumps(s["toggles"], ensure_ascii=False))
    lines.append("")
    for sid, title, names in info.screens:
        lines.append("[%s] %s（%d 项）" % (sid, title, len(names)))
        for nm in names[:4]:
            spec = info.options.get(nm)
            if spec:
                lines.append("    %-28s %-6s = %-8s 选项值=%d %s"
                             % (nm, spec.kind, str(spec.default)[:8],
                                len(spec.values), spec.label or ""))
        if len(names) > 4:
            lines.append("    ... 还有 %d 项" % (len(names) - 4))
    if info.warnings:
        lines.append("")
        lines.append("警告: %s" % "; ".join(info.warnings))
    return "\n".join(lines)