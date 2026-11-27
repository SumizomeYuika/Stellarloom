"""GLSL 330 compatibility → 桌面 GLSL 3.30 core 转译。

历史说明：本转译器原来输出 GLSL ES 3.00（`#version 300 es`）。
现在 mod 只支持 Windows 桌面（PyOpenGL + 桌面 GL），默认 target 改为
"desktop330"：输出版本行换成 `#version 330 core`，不再注入 ES 精度块，
并剥掉源码里的 highp/mediump/lowp 限定词（桌面 GLSL 330 不认识）。
旧的 "es300" 路径保留，只为 devtools 的对照测试用，不再走正式链。

原则：**能转的转，不能转的明确标记降级，绝不静默产生错误代码**。

处理内容：
1. 版本行：#version 330 compatibility → #version 330 core（桌面目标）
2. 输入输出：varying/attribute → in/out；gl_FragData[n] → 具名 out
3. 兼容内建：gl_ModelViewProjectionMatrix / ftransform() / texture2D /
   textureCube / texture3D / gl_Color / gl_TexCoord[]
4. 精度：桌面目标剥掉所有 highp/mediump/lowp；es300 目标补默认精度
5. 不支持特性：双精度、几何着色、gl_TexCoord 特殊用法 → 标记
"""

import re

SAMPLER_DECL_RE = re.compile(
    r"^(\s*)uniform\s+(sampler\w+)\s+([A-Za-z_]\w*)\s*;", re.M)

COMPAT_GLSL_FUNCS = {
    "texture2D": "texture",
    "texture2DLod": "textureLod",
    "texture2DProj": "textureProj",
    "textureCube": "texture",
    "textureCubeLod": "textureLod",
    "texture3D": "texture",
    "texture3DLod": "textureLod",
    "shadow2D": "texture",
    "shadow2DProj": "textureProj",
}

UNSUPPORTED_PATTERNS = [
    (re.compile(r"\bdouble\b|\bdvec[234]\b"), "双精度浮点（ES 不支持）"),
    (re.compile(r"\bgl_FragDepth\b"), "gl_FragDepth（ES3 需 EXT_frag_depth）"),
    (re.compile(r"#extension\s+GL_ARB_"), "GL_ARB_* 扩展"),
    (re.compile(r"\bgl_TexCoord\s*\["), "gl_TexCoord[]（固定管线遗留）"),
    (re.compile(r"\bgl_PrimitiveID\b"), "gl_PrimitiveID（几何着色器特性）"),
]


class TranspileResult:
    def __init__(self):
        self.src = ""
        self.stage = ""
        self.degraded = []
        self.unsupported = []
        self.notes = []
        self.ok = True

    def fail(self, why):
        self.ok = False
        self.unsupported.append(why)

    def to_dict(self):
        return {"ok": self.ok, "stage": self.stage, "degraded": self.degraded,
                "unsupported": self.unsupported, "notes": self.notes,
                "lines": len(self.src.splitlines())}


def _strip_version(src):
    out, ver = [], None
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#version"):
            ver = s
            continue
        out.append(line)
    return "\n".join(out), ver


def _precision_block():
    return "\n".join([
        "precision highp float;",
        "precision highp int;",
        "precision highp sampler2D;",
        "precision highp sampler3D;",
        "precision highp samplerCube;",
        "precision highp sampler2DShadow;",
        "precision highp sampler2DArray;",
    ])


def _fix_sampler_precision(src):
    def sub(m):
        ind, typ, name = m.group(1), m.group(2), m.group(3)
        return "%suniform highp %s %s;" % (ind, typ, name)
    return SAMPLER_DECL_RE.sub(sub, src)


def _convert_varying(src, stage):
    if not re.search(r"^\s*(varying|attribute)\b", src, re.M):
        return src, False
    vdir = "out" if stage == "VERTEX" else "in"
    out_lines = []
    for line in src.splitlines():
        s = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        if s.startswith("varying "):
            out_lines.append(indent + vdir + " " + s[len("varying "):])
        elif s.startswith("attribute "):
            if stage == "VERTEX":
                out_lines.append(indent + "in " + s[len("attribute "):])
            else:
                out_lines.append("// [ES] attribute 在片段阶段无意义")
        else:
            out_lines.append(line)
    return "\n".join(out_lines), True


def _remap_layout_locations(src, drawbuffers):
    """把源码里显式的 `layout(location = k)` 重映射到全局 colortex 下标。

    光影包惯例（春眠/cm 等）：`/* DRAWBUFFERS:45 */` 配合
    `layout(location = 0) out ... // colortex4`——这里的 location 是
    **DRAWBUFFERS 列表里的序号**，不是 colortex 编号。我们的 FBO 按
    "附件下标 = colortex 下标"挂（buffers._fbo_for），所以必须在这里
    把序号翻译成编号：location 0→4、1→5。
    """
    if not drawbuffers:
        return src, 0
    n = [0]

    def sub(m):
        k = int(m.group(1))
        if 0 <= k < len(drawbuffers):
            new = drawbuffers[k]
            if new != k:
                n[0] += 1
                return "layout(location = %d) out" % new
        return m.group(0)

    out = re.sub(r"layout\s*\(\s*location\s*=\s*(\d+)\s*\)\s*out", sub, src)
    return out, n[0]


def _fragdata_to_out(src, drawbuffers):
    """决定输出槽声明。

    规则（避免 location 冲突）：
    - 源里已有 `layout(location = N) out` → 先按 DRAWBUFFERS 序号→编号
      重映射，再原样尊重，自己不再补
    - 用了 gl_FragData[n] → 按实际用到的下标补
    - 只有 DRAWBUFFERS → 按它补
    - 什么都没有 → 补一个 location 0 + gl_FragColor 别名
    """
    src, nremap = _remap_layout_locations(src, drawbuffers)
    existing = set(int(m) for m in
                   re.findall(r"layout\s*\(\s*location\s*=\s*(\d+)\s*\)\s*out\b",
                              src))
    decls = []

    uses = re.findall(r"gl_FragData\s*\[\s*(\d+)\s*\]", src)
    idxs = sorted({int(i) for i in uses} - existing)
    if idxs:
        for i in idxs:
            decls.append("layout(location = %d) out vec4 slm_out%d;" % (i, i))
        src = re.sub(r"gl_FragData\s*\[\s*(\d+)\s*\]",
                     lambda m: "slm_out%s" % m.group(1), src)
    elif drawbuffers:
        want = [i for i in drawbuffers if i not in existing]
        for i in want:
            decls.append("layout(location = %d) out vec4 slm_out%d;" % (i, i))
        if not existing and len(drawbuffers) == 1:
            decls.append("#define gl_FragColor slm_out%d" % drawbuffers[0])
        elif existing and re.search(r"\bgl_FragColor\b", src):
            decls.append("#define gl_FragColor slm_out_auto")
            decls.append("layout(location = %d) out vec4 slm_out_auto;"
                         % _free_location(existing))
    elif not existing:
        decls.append("layout(location = 0) out vec4 slm_out0;")
        decls.append("#define gl_FragColor slm_out0")
    return src, decls


def _free_location(used):
    i = 0
    while i in used:
        i += 1
    return i


def _compat_builtins(src, stage):
    notes = []
    # 纹理矩阵要先处理：它是数组，不是矩阵名的子串替换
    src, texmat_ids = _fix_texmatrix(src, notes)
    # 矩阵类
    for old, new in COMPAT_MATRICES.items():
        if old in src:
            src = src.replace(old, new)
            if old not in src:
                notes.append("%s → %s" % (old, new))
    for old, new in COMPAT_VECTORS.items():
        if re.search(r"\b" + re.escape(old) + r"\b", src):
            src = re.sub(r"\b" + re.escape(old) + r"\b", new, src)
            notes.append("%s → %s" % (old, new))

    if "ftransform()" in src:
        src = src.replace("ftransform()", "(slm_mvp * slm_vertex)")
        notes.append("ftransform() → (slm_mvp * slm_vertex)")

    for old, new in COMPAT_GLSL_FUNCS.items():
        pat = re.compile(r"\b" + old + r"\s*\(")
        if pat.search(src):
            src = pat.sub(new + "(", src)
            notes.append("%s() → %s()" % (old, new))
    return src, notes


COMPAT_MATRICES = {
    "gl_ModelViewProjectionMatrix": "slm_mvp",
    "gl_ModelViewMatrix": "slm_mv",
    "gl_ProjectionMatrix": "slm_proj",
    "gl_NormalMatrix": "slm_normal",
}

# 纹理矩阵是**独立数组**，不是矩阵的列。
# 老实现把 gl_TextureMatrix[1] 里的 "[1]" 留在原地 → 变成 slm_texmat[1]，
# 语法合法（mat4 的列是 vec4）但语义全错：lmcoord 变成矩阵第 1 列的逐分量
# 乘法，值全是垃圾。校验器抓不住，只能这里按数组下标逐个换名。
_TEXMAT_RE = re.compile(r"gl_TextureMatrix\s*\[\s*(\d+)\s*\]")

# 下标 -> uniform 名。OptiFine 只用到 0（纹理变换）和 1（光照贴图坐标变换）。
TEXMAT_NAMES = {0: "slm_texmat0", 1: "slm_texmat1"}


def _fix_texmatrix(src, notes):
    """gl_TextureMatrix[N] → slm_texmatN（各自独立 mat4）。"""
    used = set()

    def sub(m):
        idx = int(m.group(1))
        name = TEXMAT_NAMES.get(idx, "slm_texmat%d" % idx)
        used.add(idx)
        return name

    new = _TEXMAT_RE.sub(sub, src)
    if used:
        notes.append("gl_TextureMatrix[] → 独立 uniform %s"
                     % ",".join("slm_texmat%d" % i for i in sorted(used)))
    # 裸写的 gl_TextureMatrix（无下标）= [0]
    if re.search(r"\bgl_TextureMatrix\b(?!\s*\[)", new):
        new = re.sub(r"\bgl_TextureMatrix\b(?!\s*\[)", "slm_texmat0", new)
        used.add(0)
        notes.append("裸 gl_TextureMatrix → slm_texmat0")
    return new, sorted(used)

COMPAT_VECTORS = {
    "gl_Vertex": "slm_vertex",
    "gl_MultiTexCoord0": "slm_uv0",
    "gl_MultiTexCoord1": "slm_uv1",
    "gl_MultiTexCoord2": "slm_uv2",
    "gl_MultiTexCoord3": "slm_uv3",
    "gl_Color": "slm_color",
    "gl_Normal": "slm_normal_in",
}

REQUIRED_DECLS = {
    "slm_mvp": "uniform mat4 slm_mvp;",
    "slm_mv": "uniform mat4 slm_mv;",
    "slm_proj": "uniform mat4 slm_proj;",
    "slm_normal": "uniform mat3 slm_normal;",
    "slm_texmat0": "uniform mat4 slm_texmat0;",
    "slm_texmat1": "uniform mat4 slm_texmat1;",
    "slm_vertex": "in vec4 slm_vertex;",
    "slm_uv0": "in vec4 slm_uv0;",
    "slm_uv1": "in vec4 slm_uv1;",
    "slm_uv2": "in vec4 slm_uv2;",
    "slm_uv3": "in vec4 slm_uv3;",
    "slm_color": "in vec4 slm_color;",
    "slm_normal_in": "in vec3 slm_normal_in;",
}


def _inject_vertex_inputs(src):
    """按正文里实际出现的 slm_* 名字补声明（全文扫，不只看 main）。"""
    decls = []
    for name, decl in REQUIRED_DECLS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", src):
            decls.append(decl)
    return decls


# 向量类型 -> 分量数；整数域用于判断哪个方向需要补转换
INT_VEC = {"ivec2": 2, "ivec3": 3, "ivec4": 4}
FLOAT_VEC = {"vec2": 2, "vec3": 3, "vec4": 4}


def _track_array_elem_types(src):
    """数组名 -> 元素类型。认 `const vec2 FOO[16]` / `ivec2 bar[4]`。"""
    types = {}
    pat = re.compile(
        r"\b(ivec[234]|uvec[234]|vec[234]|int|uint|float)\s+"
        r"([A-Za-z_]\w*)\s*\[")
    for m in pat.finditer(src):
        types[m.group(2)] = m.group(1)
    return types


DECL_RE = re.compile(
    r"\b(ivec[234]|uvec[234]|vec[234]|int|uint|float)\s+"
    r"([A-Za-z_]\w*)\s*(?=[=;,\)\[])")


def _fix_int_vec_ops(src):
    """ES 不允许 vecN 与 ivecN 直接混算（桌面 GLSL 有 int→float 隐式转换，
    ES 3.00 没有），显式补转换。

    两个必须做对的地方：
    1. 数组元素类型查表，整数数组一律不动——否则把合法的 `ivec2 + ivec2` 掰坏
    2. 类型按**行**累积，不用全局表——同名变量在不同函数里类型不同
       （`extent` 在一处是 ivec2、另一处是 float），全局表会被后来的声明覆盖
    """
    arr_elem = _track_array_elem_types(src)
    int_names = set()
    for m in DECL_RE.finditer(src):
        if m.group(1) in INT_VEC:
            int_names.add(m.group(2))
    if not int_names:
        return src, 0
    fixed = [0]

    def _sub(pat, fn, s):
        def cb(m):
            new = fn(m)
            if new != m.group(0):
                fixed[0] += 1
            return new
        return pat.sub(cb, s)

    cur = {}
    out = []
    for line in src.splitlines(True):
        for m in DECL_RE.finditer(line):
            cur[m.group(2)] = m.group(1)
        # 该行真正生效的 ivec 名
        live = [(n, cur[n]) for n in int_names
                if cur.get(n) in INT_VEC and n in line]
        for name, typ in live:
            n = INT_VEC[typ]
            ftype = "vec%d" % n
            nm = re.escape(name)

            # ① <浮点数组元素> ⊙ <ivec名>
            pat1 = re.compile(
                r"(\b[A-Za-z_]\w*)\s*\[([^\]]+)\]\s*([*/+-])\s*" + nm + r"\b")

            def r1(m, ftype=ftype, name=name):
                elem = arr_elem.get(m.group(1))
                if elem not in FLOAT_VEC:
                    return m.group(0)
                return "%s(%s[%s]) %s %s(%s)" % (elem, m.group(1), m.group(2),
                                                 m.group(3), ftype, name)
            line = _sub(pat1, r1, line)

            # ①' <ivec名> ⊙ <浮点数组元素>
            pat1b = re.compile(
                r"\b" + nm + r"\s*([*/+-])\s*(\b[A-Za-z_]\w*)\s*\[([^\]]+)\]")

            def r1b(m, ftype=ftype, name=name):
                elem = arr_elem.get(m.group(2))
                if elem not in FLOAT_VEC:
                    return m.group(0)
                return "%s(%s) %s %s(%s[%s])" % (ftype, name, m.group(1),
                                                 elem, m.group(2), m.group(3))
            line = _sub(pat1b, r1b, line)

            # ② swizzle ⊙ ivec名
            pat2 = re.compile(
                r"(\b[A-Za-z_]\w*\s*\.\s*[xyzwrgba]{2,4})\s*([*/+-])\s*"
                + nm + r"\b")

            def r2(m, ftype=ftype, name=name):
                return "%s %s %s(%s)" % (m.group(1), m.group(2), ftype, name)
            line = _sub(pat2, r2, line)

            # ③ ivec名 ⊙ swizzle/浮点字面量
            pat3 = re.compile(
                r"\b" + nm + r"\s*(\*)\s*"
                r"(\b[A-Za-z_]\w*\s*\.\s*[xyzwrgba]{2,4}|\d+\.\d*f?)")

            def r3(m, ftype=ftype, name=name):
                return "%s(%s) %s %s" % (ftype, name, m.group(1), m.group(2))
            line = _sub(pat3, r3, line)
        out.append(line)
    return "".join(out), fixed[0]


def _scan_unsupported(src):
    found = []
    for pat, why in UNSUPPORTED_PATTERNS:
        m = pat.search(src)
        if m:
            lo = max(0, m.start() - 20)
            snip = src[lo:m.start() + 30].replace("\n", " ")
            found.append("%s（%r 附近）" % (why, snip))
    return found


# 精度限定词：桌面 GLSL 330 里根本没有这个概念，必须整体剥掉。
# 限定词只可能出现在声明/参数位置，按"词边界 + 后跟空白"剥足够安全
# （包里不会有人拿 highp 当变量名——那是 GLSL 保留字）。
_PRECISION_WORD_RE = re.compile(r"\b(?:highp|mediump|lowp)\s+")


def _strip_precision(src):
    return _PRECISION_WORD_RE.sub("", src)


def transpile(src, stage, drawbuffers=None, target="desktop330"):
    """主入口。stage: 'VERTEX' / 'FRAGMENT'。
    target: "desktop330"（默认，桌面 GL）/ "es300"（仅自检对照用）。"""
    desktop = target != "es300"
    r = TranspileResult()
    r.stage = stage

    bad = _scan_unsupported(src)
    if bad:
        # gl_FragDepth 在桌面 330 是核心特性，不算不支持
        if desktop:
            bad = [b for b in bad if not b.startswith("gl_FragDepth")]
        r.unsupported.extend(bad)

    body, _ver = _strip_version(src)
    # 先剥精度，后面所有处理都在无精度限定的源码上做
    if desktop:
        body = _strip_precision(body)

    decls = []
    if not desktop:
        decls.append(_precision_block())
    if stage == "VERTEX":
        decls.extend(_inject_vertex_inputs(body))

    body, used_varying = _convert_varying(body, stage)
    if used_varying:
        r.notes.append("varying/attribute 已按阶段转 in/out")

    if stage == "FRAGMENT":
        body, out_decls = _fragdata_to_out(body, drawbuffers)
        decls.extend(out_decls)

    body, notes = _compat_builtins(body, stage)
    r.notes.extend(notes)

    body, nfix = _fix_int_vec_ops(body)
    if nfix:
        r.notes.append("补齐 vec/ivec 混算的显式转换 %d 处" % nfix)

    if not desktop:
        body = _fix_sampler_precision(body)

    # 注意：_inject_vertex_inputs 必须在 _compat_builtins **之后**调用，
    # 否则那时 slm_mvp 还没出现在正文里，会漏声明。
    if stage == "VERTEX":
        extra = _inject_vertex_inputs(body)
        if extra:
            decls.extend(extra)

    if desktop:
        header = "#version 330 core\n"
        if decls:
            header += "\n".join(decls) + "\n"
    else:
        header = "#version 300 es\n" + "\n".join(decls) + "\n"
    r.src = header + body
    if not r.src.endswith("\n"):
        r.src += "\n"
    r.ok = not r.unsupported
    return r