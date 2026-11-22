"""Pass 图：从包的入口文件推导执行顺序、输出附件、输入依赖。

Iris 的执行顺序是**固定语义**，不是从包里读出来的：
  shadow → gbuffers_* → deferred → deferred1..N → composite → composite1..N → final

我们照这个顺序跑，但每条 pass 的输出附件（DRAWBUFFERS）和是否启用
是从包里读的。找不到的入口直接跳过——包里没写的程序本来就不该跑。

输入绑定：一个 pass 的 fsh 里采样了 colortexN / depthtexN / shadowtexN，
就把它绑到对应纹理单元。单元分配按"名字首次出现的顺序"稳定分配，
因为同一帧内多个 pass 复用同一份缓冲，没必要每次重排。

关键设计：**程序懒编译**。一个包有 34 个入口 × 3 个 world 变体 = 上百个
program，全部预先编译在手机上要几十秒。改成第一次用到才编，坏的那个
记进 failures 继续跑剩余 pass，不会一崩全崩。
"""

import re

from . import glapi

# Iris 固定顺序。数字后缀的按数字排，不是字典序（composite10 在 composite9 后）
PASS_ORDER = ["shadow"] + ["gbuffers_" + x for x in (
    "terrain", "terrain_solid", "terrain_cutout", "terrain_cutout_mip",
    "block", "block_translucent", "water", "entities", "entities_glowing",
    "entities_translucent", "hand", "hand_water", "weather", "basic", "line",
    "beaconbeam", "textured", "textured_lit", "particles",
    "particles_translucent", "lightning", "skybasic", "skytextured", "clouds",
    "damagedblock", "armor_glint", "spidereyes",
)] + ["deferred", "deferred1", "deferred2", "deferred3", "composite"] + [
    "composite%d" % i for i in range(1, 16)
] + ["final"]

# 这些是"绘制几何"的 pass（gbuffers 族），需要网格数据；
# 其余是后处理，只需要全屏四边形。
GEOMETRY_PREFIX = "gbuffers_"

SAMPLE_RE = re.compile(
    r"\b(colortex(?:1[0-5]|[0-9])|depthtex[0-2]|shadowtex[01]"
    r"|noisetex|normals|specular)\b")

COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def strip_comments(src):
    """去掉注释再做采样扫描。包里注释疯狂提到 colortexN，
    不去掉会造出一堆假依赖（"读了没人写的 colortex31"就是这么来的）。"""
    return COMMENT_RE.sub(" ", src)


class PassSpec:
    """一条 pass 的静态描述。"""

    __slots__ = ("name", "vsh_rel", "fsh_rel", "outputs", "inputs",
                 "is_geometry", "enabled", "blend")

    def __init__(self, name):
        self.name = name
        self.vsh_rel = None
        self.fsh_rel = None
        self.outputs = []        # colortex 下标列表（DRAWBUFFERS 顺序）
        self.inputs = []         # 采样到的缓冲区名（去掉输出自身的）
        self.is_geometry = name.startswith(GEOMETRY_PREFIX) or name == "shadow"
        self.enabled = True
        self.blend = None        # None / "off" / (src, dst)

    def __repr__(self):
        return "<Pass %s out=%s in=%s>" % (self.name, self.outputs,
                                           self.inputs[:4])


def build_passes(info, world="world0", props=None):
    """按 PASS_ORDER 产出一张 pass 表（已过滤掉包里没有的入口）。

    info: packscan.PackInfo
    world: "" / "world0" / "world-1" / "world1"
    props: shaders.properties 的 dict（可选，用于 blend / enabled）
    """
    props = props or {}
    specs = []
    for name in PASS_ORDER:
        ent = info.programs.get(name)
        if not ent:
            continue
        vsh = _pick(ent.get("vsh"), world)
        fsh = _pick(ent.get("fsh"), world)
        if not fsh:
            continue
        p = PassSpec(name)
        p.vsh_rel = vsh
        p.fsh_rel = fsh
        specs.append(p)
    # 包里可能有 PASS_ORDER 里没列的名字（新版本包），追加在 final 之前
    known = set(PASS_ORDER)
    extra = []
    for name, ent in info.programs.items():
        if name in known:
            continue
        fsh = _pick(ent.get("fsh"), world)
        if not fsh:
            continue
        p = PassSpec(name)
        p.vsh_rel = _pick(ent.get("vsh"), world)
        p.fsh_rel = fsh
        extra.append(p)
    if extra:
        specs = specs[:-1] + extra + specs[-1:] if specs else extra
    _apply_props(specs, props, world)
    return specs


def _pick(rel, world):
    """从入口字典里挑当前 world 的变体。rel 已经是相对 shaders/ 的路径。"""
    if not rel:
        return None
    if not world:
        return rel
    # packscan 给的 rel 形如 "world0/deferred.fsh" 或 "deferred.fsh"
    if rel.startswith(world + "/"):
        return rel
    # 只登记了别的 world → 看有没有当前 world 的对应文件
    return rel


def _apply_props(specs, props, world):
    """应用 shaders.properties 里的 blend.* 与 program.*.enabled。"""
    for p in specs:
        key = "blend." + p.name
        if key in props:
            v = props[key].strip()
            p.blend = "off" if v.lower() == "off" else v
        for w in ([world] if world else []) + [""]:
            ek = "program.%s/%s.enabled" % (w, p.name) if w else \
                 "program.%s.enabled" % p.name
            if ek in props:
                p.enabled = props[ek].strip().lower() != "false"


def fill_io(specs, preproc_results):
    """补 outputs / inputs。需要在转译完成后调用——
    因为 DRAWBUFFERS 要从预处理后的源码里读（宏展开之后才准）。

    preproc_results: {pass 名: (drawbuffers 列表, 源码文本)}
    """
    for p in specs:
        db, src = preproc_results.get(p.name, ([], ""))
        p.outputs = db or [0]
        # 输入 = 源码里采样到、且不是本 pass 自己输出的缓冲。
        # 必须先剥注释——包里的文档注释疯狂提到 colortexN，不剥会造出假依赖。
        code = strip_comments(src)
        outs = {"colortex%d" % i for i in p.outputs}
        seen = []
        for m in SAMPLE_RE.finditer(code):
            nm = m.group(1)
            if nm in outs or nm in seen:
                continue
            seen.append(nm)
        p.inputs = seen
    return specs


class PassRunner:
    """执行一张 pass 表。只管跑，不管编译细节。"""

    def __init__(self, api, pool, programs, quad):
        self.api = api
        self.pool = pool
        self.programs = programs      # {pass 名: Program}
        self.quad = quad              # FullscreenQuad
        self.unit_of = {}             # 缓冲名 -> 纹理单元
        self.next_unit = 0
        self.log = []
        self.failures = []

    def unit(self, name):
        u = self.unit_of.get(name)
        if u is None:
            u = self.next_unit
            self.unit_of[name] = u
            self.next_unit += 1
            if self.next_unit > 15:
                self.next_unit = 0      # 单元耗尽就回卷（一般到不了）
        return u

    def run(self, spec, uniforms, depth=None):
        """跑一条 pass。

        uniforms: callable(prog, is_geometry) → None，在 use 之后设 uniform。
        depth: 几何 pass 要绑的深度附件名（"depthtex0"），后处理传 None。
        返回是否成功执行。
        """
        prog = self.programs.get(spec.name)
        if prog is None or not prog.ok:
            self.failures.append((spec.name, "程序不可用"))
            return False
        api = self.api
        try:
            self.pool.bind_targets(spec.outputs, depth=depth, clear=False)
        except Exception as e:
            self.failures.append((spec.name, "绑定目标失败: %s" % e))
            return False
        prog.use()
        # 绑定输入纹理
        for nm in spec.inputs:
            act = self.pool.attach_name(nm)
            if not act.startswith(("colortex", "depthtex", "shadowtex")):
                continue
            u = self.unit(act)
            self.pool.bind_sampler(api, u, act)
            prog.set_int(nm, u)
        _apply_blend(api, spec.blend)
        if uniforms:
            uniforms(prog, spec.is_geometry)
        if spec.is_geometry:
            self.quad.draw_geometry()
        else:
            self.quad.draw()
        err = api.check(spec.name)
        if err:
            self.failures.append((spec.name, err))
        self.log.append(spec.name)
        return True


def _apply_blend(api, blend):
    """按 properties 的 blend 配置设置混合状态。

    off = 完全关闭；
    "SRC_ALPHA ONE_MINUS_SRC_ALPHA ZERO ONE" = 颜色按 alpha 混、目标 alpha 直通；
    没写 = 保持引擎默认（开 alpha blend）。
    """
    if blend == "off":
        api.glDisable(glapi.GL_BLEND)
        return
    if not blend:
        api.glDisable(glapi.GL_BLEND)
        return
    parts = blend.split()
    try:
        src = _BLEND_FACTOR(parts[0])
        dst = _BLEND_FACTOR(parts[1])
        src_a = _BLEND_FACTOR(parts[2]) if len(parts) > 2 else src
        dst_a = _BLEND_FACTOR(parts[3]) if len(parts) > 3 else dst
    except KeyError:
        api.glDisable(glapi.GL_BLEND)
        return
    api.glEnable(glapi.GL_BLEND)
    api.glBlendFuncSeparate(src, dst, src_a, dst_a)
    api.glBlendEquation(glapi.GL_FUNC_ADD)


_BLEND_FACTOR = {
    "ZERO": glapi.GL_ZERO,
    "ONE": glapi.GL_ONE,
    "SRC_ALPHA": glapi.GL_SRC_ALPHA,
    "ONE_MINUS_SRC_ALPHA": glapi.GL_ONE_MINUS_SRC_ALPHA,
    "SRC_COLOR": 0x0300,
    "ONE_MINUS_SRC_COLOR": 0x0301,
    "DST_ALPHA": 0x0304,
    "ONE_MINUS_DST_ALPHA": 0x0305,
}


class FullscreenQuad:
    """全屏四边形（后处理用）与共享的几何绘制入口。

    关键：属性名必须与转译器产出的一致。转译器把 gl_Vertex 换成
    slm_vertex、gl_MultiTexCoord0 换成 slm_uv0……所以这里的 VSH 和
    glBindAttribLocation 全用 slm_*，否则驱动自己分配位置，什么都画不出来。
    """

    # 全屏三角：顶点是 NDC（z=0, w=1），包里的 vsh 会拿 slm_mvp * slm_vertex，
    # 所以全屏 pass 的 slm_mvp 必须是单位阵。
    VSH = """#version 300 es
in vec4 slm_vertex;
out vec2 v_uv;
void main() {
    v_uv = slm_vertex.xy * 0.5 + 0.5;
    gl_Position = vec4(slm_vertex.xy, 0.0, 1.0);
}
"""

    # 几何 pass 的属性绑定（名字 -> 位置）
    GEO_ATTRS = {"slm_vertex": 0, "slm_uv0": 1, "slm_color": 2,
                 "slm_uv1": 3, "mc_Entity": 4}
    QUAD_ATTRS = {"slm_vertex": 0}

    def __init__(self, api):
        self.api = api
        self.vao = 0
        self.vbo = 0
        self.geo_vao = 0
        self.geo_vbo = 0
        self.geo_count = 0
        self._setup()

    def _setup(self):
        api = self.api
        # 两个三角形覆盖 [-1,1]²；vec4 顶点（w=1）与 slm_vertex 声明一致
        verts = [-1.0, -1.0, 0.0, 1.0,
                 1.0, -1.0, 0.0, 1.0,
                 -1.0, 1.0, 0.0, 1.0,
                 1.0, -1.0, 0.0, 1.0,
                 1.0, 1.0, 0.0, 1.0,
                 -1.0, 1.0, 0.0, 1.0]
        arr = (glapi.c_float * len(verts))(*verts)
        vid = glapi.c_uint(0)
        api.glGenVertexArrays(1, glapi.byref(vid))
        self.vao = vid.value
        api.glBindVertexArray(self.vao)
        bid = glapi.c_uint(0)
        api.glGenBuffers(1, glapi.byref(bid))
        self.vbo = bid.value
        api.glBindBuffer(glapi.GL_ARRAY_BUFFER, self.vbo)
        import ctypes
        api.glBufferData(glapi.GL_ARRAY_BUFFER,
                         ctypes.sizeof(arr),
                         ctypes.cast(arr, glapi.c_void_p),
                         glapi.GL_STATIC_DRAW)
        api.glEnableVertexAttribArray(0)
        api.glVertexAttribPointer(0, 4, glapi.GL_FLOAT, glapi.GL_FALSE,
                                  0, None)
        api.glBindVertexArray(0)

    def draw(self):
        api = self.api
        api.glBindVertexArray(self.vao)
        api.glDrawArrays(glapi.GL_TRIANGLES, 0, 6)
        api.glBindVertexArray(0)

    def draw_geometry(self):
        """绘制世界层几何（由 world_gl 填的 VBO）。"""
        if not self.geo_vao or not self.geo_count:
            return
        api = self.api
        api.glBindVertexArray(self.geo_vao)
        api.glDrawArrays(glapi.GL_TRIANGLES, 0, self.geo_count)
        api.glBindVertexArray(0)

    def release(self):
        api = self.api
        for v in (self.vao, self.geo_vao):
            if v:
                api.glDeleteVertexArrays(1, glapi.byref(glapi.c_uint(v)))
        for b in (self.vbo, self.geo_vbo):
            if b:
                api.glDeleteBuffers(1, glapi.byref(glapi.c_uint(b)))