"""选项值 → 源码改写。

两类选项，两种改法（这是扫描器 `source` 字段存在的原因）：
- `#define X value`      → 通过预处理器注入的 defines 覆盖，不动文件
- `const float X = 0.5;` → 必须在常量文件里**就地改写**，因为 const 不是宏

花括号前必须先确认改的是哪一类，否则会把 `const` 项当宏注入，
生成 `const float 1.0 = 1.0;` 这种垃圾（真踩过）。

改写是内存态的：不改用户磁盘上的包，产出的是"改过常量的文本"，
由预处理器读进去。这样换包/还原只要丢掉缓存。
"""

import os
import re


def const_value_re(name):
    """匹配 `const <type> <name> = <value>;` 的 value 部分。"""
    return re.compile(
        r"(\bconst\s+(?:highp\s+|mediump\s+|lowp\s+)?"
        r"(?:float|int|bool|vec2|vec3|vec4)\s+"
        + re.escape(name) + r"\s*=\s*)([^;]+)(;)")


def patch_source_for_options(text, info, values):
    """把 values 里属于 const 形式的选项写进源码文本。返回 (新文本, 改动数)。

    text: 某个 .glsl 的全文
    info: packscan.PackInfo
    values: {选项名: 新值字符串}
    """
    changed = 0
    for name, val in values.items():
        spec = info.options.get(name)
        if spec is None or spec.source != "const":
            continue
        pat = const_value_re(name)
        if not pat.search(text):
            continue
        new_text, n = pat.subn(lambda m: m.group(1) + str(val) + m.group(3),
                               text, count=1)
        if n:
            text = new_text
            changed += n
    return text, changed


def const_option_files(shaders_dir, info, source=None):
    """找出声明了 const 形式选项的文件（只需扫这些，不用扫全包）。

    source: packscan.DirSource/ZipSource（zip 直读时必传）；
    不传时维持旧行为（os.walk 扫 shaders_dir）。
    返回 {选项名: canonical 路径}。"""
    names = [n for n, s in info.options.items() if s.source == "const"]
    if not names:
        return {}
    # 逐个名字建正则，找第一个命中的文件
    found = {}
    pats = {n: const_value_re(n) for n in names}
    if source is not None:
        for rel, key in source.walk_files():
            if not rel.endswith(".glsl"):
                continue
            try:
                text = source.read_canonical(key)
            except Exception:
                continue
            for n, pat in pats.items():
                if n in found:
                    continue
                if pat.search(text):
                    found[n] = key
            if len(found) == len(pats):
                return found
        return found
    for dirpath, dirnames, files in os.walk(shaders_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".glsl"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = open(path, "r", encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            for n, pat in pats.items():
                if n in found:
                    continue
                if pat.search(text):
                    found[n] = path
            if len(found) == len(pats):
                return found
    return found


def apply_to_text_tree(texts, info, values):
    """对一批 {路径: 文本} 就地改写 const 选项。返回总改动数。"""
    total = 0
    for path in list(texts):
        new_text, n = patch_source_for_options(texts[path], info, values)
        if n:
            texts[path] = new_text
            total += n
    return total


def validate_value(spec, raw):
    """把界面给的值规范化成源码里能用的字面量。返回 (ok, 值或错误)。"""
    if raw is None:
        return False, "空值"
    s = str(raw).strip()
    if not s:
        return False, "空值"

    kind = spec.kind
    if kind == "bool":
        low = s.lower()
        if low in ("1", "true", "on", "yes"):
            return True, "true"
        if low in ("0", "false", "off", "no"):
            return True, "false"
        return False, "布尔值只接受 true/false"
    if kind in ("int", "enum"):
        # enum 的合法值必须落在档位表里
        if spec.values and kind == "enum":
            if s not in spec.values:
                return False, "必须是 %s 之一" % "/".join(spec.values)
            return True, s
        try:
            return True, str(int(float(s)))
        except (TypeError, ValueError):
            return False, "需要整数"
    if kind == "float":
        try:
            v = float(s)
        except (TypeError, ValueError):
            return False, "需要数字"
        # 保留原样的小数表示，避免 1.0 变成 1
        if "." not in s and "e" not in s.lower():
            return True, "%.1f" % v
        return True, s
    if kind == "vec3":
        if not (s.startswith("vec3(") and s.endswith(")")):
            return False, "需要 vec3(...)"
        return True, s
    return True, s


def clamp_slider(spec, raw):
    """滑条：按档位表做就近取值。没有档位表就原样返回。"""
    if not spec.values:
        return raw
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return raw
    best = None
    best_d = None
    for cand in spec.values:
        try:
            cv = float(cand)
        except ValueError:
            continue
        d = abs(cv - v)
        if best_d is None or d < best_d:
            best_d = d
            best = cand
    return best if best is not None else raw