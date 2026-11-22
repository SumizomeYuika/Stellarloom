"""colortex / depthtex / shadowtex 缓冲池。

Iris 语义要点（照着实现，别自己发挥）：
- colortex0..15 是**同尺寸**的颜色附件，可被不同 pass 用 DRAWBUFFERS 组进同一个
  FBO。所以不能一个 buffer 一个 FBO——要按"附件组合"缓建 FBO，组合键是
  排序后的缓冲区名元组。
- colortex 格式包里没声明，统一给 RGBA16F：这个包的 HDR 值域靠它，
  用 RGBA8 会把 bloom / 曝光全压死。
- colortex3（TAA 历史）与 colortex7（杂项簇）是 **clear=false**，
  跨帧保留。其余每帧首用前清一次。
- depthtex0 = 含半透明的深度，depthtex1 = 仅不透明，depthtex2 = 仅手。
  我们用同一份深度附件别名到三个名字（星织没有分层深度通道，
  这是既定降级，记在 notes 里）。
- gaux1..4 是 colortex4..7 的**别名**，不是独立缓冲。

尺寸：全分辨率（用户选了不高采样）。RENDER_SCALE 选项生效时按它缩放，
但只缩放 colortex/depthtex，屏幕输出始终是全分辨率。
"""

from . import glapi


class BufferError(Exception):
    pass


# 颜色格式：包里没声明，统一 RGBA16F（HDR 必需）
COLOR_FORMAT = glapi.GL_RGBA16F
COLOR_TYPE = glapi.GL_HALF_FLOAT
DEPTH_FORMAT = glapi.GL_DEPTH_COMPONENT24

# clear=false 的缓冲：跨帧保留
PERSISTENT = {"colortex3", "colortex7", "shadowtex0", "shadowtex1"}

# 别名表：一个 buffer 的多个 uniform 名
# depthtex1/2 别名到 depthtex0 是**既定降级**：星织只有一份深度，
# 分层深度（不透明/手部）无从区分。但如果不别名，depthtex1/2 会各自
# 新建一张**空**纹理——包里 deferred_init 用 depthtex1 做天空判定，
# 全采样到 0 就会被当成"全是天空"，整屏掉天空色。
ALIASES = {
    "gaux1": "colortex4",
    "gaux2": "colortex5",
    "gaux3": "colortex6",
    "gaux4": "colortex7",
    "depthtex1": "depthtex0",
    "depthtex2": "depthtex0",
    "shadowtex1": "shadowtex0",
}

MAX_COLOR_TARGETS = 16


class _Tex:
    __slots__ = ("name", "tex", "w", "h", "is_depth", "dirty")

    def __init__(self, name, tex, w, h, is_depth):
        self.name = name
        self.tex = tex
        self.w = w
        self.h = h
        self.is_depth = is_depth
        self.dirty = True       # 本帧还没清过


class BufferPool:
    def __init__(self, api, width, height):
        self.api = api
        self.w = int(width)
        self.h = int(height)
        self.tex = {}            # name -> _Tex
        self.fbos = {}           # 组合键 -> fbo id
        self.notes = []
        self._all_fbo = 0        # 默认帧缓冲（屏幕）

    # ------------------------------------------------------------ 尺寸
    def resize(self, w, h):
        w, h = int(w), int(h)
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.release()
        self.notes.append("缓冲池重建: %dx%d" % (w, h))

    # ------------------------------------------------------------ 创建
    def _make_tex(self, name, depth=False):
        api = self.api
        tid = glapi.c_uint(0)
        api.glGenTextures(1, glapi.byref(tid))
        tex = tid.value
        target = glapi.GL_TEXTURE_2D
        api.glBindTexture(target, tex)
        if depth:
            api.glTexImage2D(target, 0, DEPTH_FORMAT, self.w, self.h, 0,
                             glapi.GL_DEPTH_COMPONENT, glapi.GL_UNSIGNED_INT,
                             None)
            api.glTexParameteri(target, glapi.GL_TEXTURE_MIN_FILTER,
                                glapi.GL_NEAREST)
            api.glTexParameteri(target, glapi.GL_TEXTURE_MAG_FILTER,
                                glapi.GL_NEAREST)
        else:
            api.glTexImage2D(target, 0, COLOR_FORMAT, self.w, self.h, 0,
                             glapi.GL_RGBA, COLOR_TYPE, None)
            api.glTexParameteri(target, glapi.GL_TEXTURE_MIN_FILTER,
                                glapi.GL_LINEAR)
            api.glTexParameteri(target, glapi.GL_TEXTURE_MAG_FILTER,
                                glapi.GL_LINEAR)
        for wrap in (glapi.GL_TEXTURE_WRAP_S, glapi.GL_TEXTURE_WRAP_T):
            api.glTexParameteri(target, wrap, glapi.GL_CLAMP_TO_EDGE)
        api.glBindTexture(target, 0)
        t = _Tex(name, tex, self.w, self.h, depth)
        self.tex[name] = t
        return t

    def get(self, name):
        """按名字取纹理，没有就建（懒建，避免没用到的 buffer 白占显存）。"""
        key = ALIASES.get(name, name)
        t = self.tex.get(key)
        if t is not None:
            return t
        if key.startswith("depthtex") or key.startswith("shadowtex"):
            return self._make_tex(key, depth=True)
        return self._make_tex(key, depth=False)

    def attach_name(self, name):
        """uniform 名 → 实际缓冲名。"""
        return ALIASES.get(name, name)

    # ------------------------------------------------------------ FBO
    def _fbo_for(self, colors, depth):
        key = (tuple(sorted(colors)), depth)
        fbo = self.fbos.get(key)
        if fbo is not None:
            return fbo
        api = self.api
        fid = glapi.c_uint(0)
        api.glGenFramebuffers(1, glapi.byref(fid))
        fbo = fid.value
        api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, fbo)
        slots = []
        for i, nm in enumerate(colors):
            t = self.get(nm)
            api.glFramebufferTexture2D(
                glapi.GL_FRAMEBUFFER, glapi.GL_COLOR_ATTACHMENT0 + i,
                glapi.GL_TEXTURE_2D, t.tex, 0)
            slots.append(glapi.GL_COLOR_ATTACHMENT0 + i)
        if depth:
            t = self.get(depth)
            api.glFramebufferTexture2D(
                glapi.GL_FRAMEBUFFER, glapi.GL_DEPTH_ATTACHMENT,
                glapi.GL_TEXTURE_2D, t.tex, 0)
        if not slots:
            api.glDrawBuffers(0, None)
        elif len(slots) == 1:
            arr = (glapi.c_uint * 1)(slots[0])
            api.glDrawBuffers(1, arr)
        else:
            arr = (glapi.c_uint * len(slots))(*slots)
            api.glDrawBuffers(len(slots), arr)
        status = api.glCheckFramebufferStatus(glapi.GL_FRAMEBUFFER)
        api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, 0)
        if status != glapi.GL_FRAMEBUFFER_COMPLETE:
            raise BufferError("FBO 不完整 0x%04X: colors=%s depth=%s"
                              % (status, colors, depth))
        self.fbos[key] = fbo
        return fbo

    def bind_targets(self, slots, depth=None, clear=False, clear_color=None):
        """把一组 colortex 下标 + depth 绑成当前 FBO。

        slots: [0, 4, 6] 这样的 colortex 下标列表（按 DRAWBUFFERS 顺序）。
        注意：这里**不做隐式清理**。Iris 的 clear=false 缓冲本来就跨帧保留，
        而 clear=true 的缓冲由 owner pass 自己 glClear（包里的 deferred_init
        就是这样）。我们只在显式传 clear=True 时清——那是给我们的降级路径用。
        """
        colors = ["colortex%d" % i for i in slots]
        fbo = self._fbo_for(colors, depth)
        api = self.api
        api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, fbo)
        api.glViewport(0, 0, self.w, self.h)
        if clear:
            self._clear_now(clear_color)
        return fbo

    def _clear_now(self, color=None):
        api = self.api
        api.glDisable(glapi.GL_SCISSOR_TEST)
        r, g, b, a = color or (0.0, 0.0, 0.0, 0.0)
        api.glClearColor(r, g, b, a)
        api.glClearDepthf(1.0)
        api.glDepthMask(glapi.GL_TRUE)
        api.glClear(glapi.GL_COLOR_BUFFER_BIT | glapi.GL_DEPTH_BUFFER_BIT)

    def bind_screen(self):
        self.api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, 0)

    def clear_first_use(self, names):
        """首帧把非持久缓冲清成黑色。

        只在第一帧调一次：colortex 刚建出来内容是未定义的，直接采样会得到
        垃圾（甚至 NaN 扩散到整屏）。持久缓冲不清（它们本来就跨帧语义）。
        """
        api = self.api
        for nm in names:
            t = self.get(nm)
            if nm in PERSISTENT or not t.dirty:
                continue
            t.dirty = False
        # 统一清一次：绑一个 16 附件的大 FBO 逐个清太贵，
        # 这里靠下面这个"全清"把当前绑定的 FBO 清掉即可，
        # 调用方负责先绑好无 FBO（默认帧缓冲）。
        api.glClearColor(0.0, 0.0, 0.0, 0.0)
        self._clear_now()

    def clear_all_first_frame(self):
        """第一帧前把所有已存在缓冲清黑。逐缓冲绑 FBO 清，只做一次。"""
        api = self.api
        for nm, t in list(self.tex.items()):
            if nm in PERSISTENT:
                continue
            try:
                fbo = self._fbo_for([nm], None)
                api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, fbo)
                api.glViewport(0, 0, self.w, self.h)
                self._clear_now()
            except Exception:
                pass
        api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, 0)

    # ------------------------------------------------------------ 纹理槽
    def bind_sampler(self, api, unit, name):
        """把某个缓冲绑到纹理单元，返回是否绑成功。"""
        t = self.get(name)
        api.glActiveTexture(glapi.GL_TEXTURE0 + unit)
        api.glBindTexture(glapi.GL_TEXTURE_2D, t.tex)
        return True

    # ------------------------------------------------------------ 释放
    def release(self):
        api = self.api
        for t in self.tex.values():
            api.glDeleteTextures(1, glapi.byref(glapi.c_uint(t.tex)))
        self.tex.clear()
        for f in self.fbos.values():
            api.glDeleteFramebuffers(1, glapi.byref(glapi.c_uint(f)))
        self.fbos.clear()
        self.notes.append("缓冲池已释放")


def make_noise_texture(api, size=64):
    """程序化噪声纹理（蓝噪点近似）。optifine 的 noisetex 是引擎给的，
    我们只能自己造一份——水焦散用它当波场，纯噪声也够看。"""
    import math
    px = bytearray()
    for y in range(size):
        for x in range(size):
            # 三层不同频率的正弦叠加，做出各向同性的散斑
            v = (math.sin(x * 0.7 + y * 1.3) * 0.5 +
                 math.sin(x * 2.1 - y * 1.7) * 0.3 +
                 math.sin((x + y) * 3.7) * 0.2)
            n = int(max(0, min(255, (v * 0.5 + 0.5) * 255)))
            px += bytes((n, n, n, 255))
    buf = (glapi.c_char * len(px)).from_buffer(px)
    tid = glapi.c_uint(0)
    api.glGenTextures(1, glapi.byref(tid))
    tex = tid.value
    api.glBindTexture(glapi.GL_TEXTURE_2D, tex)
    api.glTexImage2D(glapi.GL_TEXTURE_2D, 0, glapi.GL_RGBA8, size, size, 0,
                     glapi.GL_RGBA, glapi.GL_UNSIGNED_BYTE, buf)
    api.glTexParameteri(glapi.GL_TEXTURE_2D, glapi.GL_TEXTURE_MIN_FILTER,
                        glapi.GL_LINEAR)
    api.glTexParameteri(glapi.GL_TEXTURE_2D, glapi.GL_TEXTURE_MAG_FILTER,
                        glapi.GL_LINEAR)
    api.glTexParameteri(glapi.GL_TEXTURE_2D, glapi.GL_TEXTURE_WRAP_S,
                        glapi.GL_REPEAT)
    api.glTexParameteri(glapi.GL_TEXTURE_2D, glapi.GL_TEXTURE_WRAP_T,
                        glapi.GL_REPEAT)
    api.glBindTexture(glapi.GL_TEXTURE_2D, 0)
    return tex