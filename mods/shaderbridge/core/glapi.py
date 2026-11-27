"""桌面 OpenGL 门面（PyOpenGL 后端），Windows 专用。

历史包袱说明：这个模块原来是"ctypes 逐符号 dlsym libGLESv2.so"的
Android 方案。现在用户已拍板：**只支持 Windows 桌面，直接用 PyOpenGL**。
GLES/EGL/ANGLE 那套全部砍掉。

为什么还保留这层"门面"而不是让所有模块直接 `from OpenGL import GL`：
上层（buffers / passes / program / world_gl / composite_gl）写代码时
按 C 风格的 ctypes 调用约定写好了（`glGenTextures(1, byref(c_uint))`、
`glGetShaderiv(sh, pname, byref(ok))`、指针参数等）。全部改成 PyOpenGL
原生风格要动 130+ 处调用点，收益为零、风险全在。所以这里只做**一层
薄薄的签名适配**：对外暴露与旧 ctypes 版完全相同的接口，对内调
`OpenGL.GL`。跨平台复杂度集中在这一层被消灭。

前提：调用前必须有当前 GL 上下文（见 glctx.GLContext，WGL 离屏）。
没有上下文时 PyOpenGL 会抛错——上层 composite_gl 会接住并干净降级。
"""

import ctypes
# 这些名字上层直接 `glapi.byref / glapi.c_uint ...` 引用，必须继续透出
from ctypes import (POINTER, byref, c_char, c_char_p, c_float, c_int,  # noqa
                    c_uint, c_void_p, create_string_buffer)

from OpenGL import GL as _gl

GL_LIB_NAMES = ()   # 历史名字保留，桌面版不再从 .so 加载
EGL_LIB_NAMES = ()

# ---------------------------------------------------------------- 常量
# GL 核心常量值在桌面 GL 与 GLES3 完全一致，原表保留。
GL_VERSION = 0x1F02
GL_RENDERER = 0x1F01
GL_VENDOR = 0x1F00
GL_FALSE = 0
GL_TRUE = 1
GL_TRIANGLES = 0x0004
GL_TRIANGLE_STRIP = 0x0005
GL_UNSIGNED_BYTE = 0x1401
GL_UNSIGNED_SHORT = 0x1403
GL_UNSIGNED_INT = 0x1405
GL_FLOAT = 0x1406
GL_BYTE = 0x1400
GL_SHORT = 0x1402
GL_INT = 0x1404

GL_DEPTH_COMPONENT = 0x1902
GL_COLOR = 0x1800
GL_DEPTH = 0x1801
GL_STENCIL = 0x1802
GL_COLOR_BUFFER_BIT = 0x4000
GL_DEPTH_BUFFER_BIT = 0x0100
GL_STENCIL_BUFFER_BIT = 0x0400
GL_DEPTH_STENCIL = 0x84F9
GL_UNSIGNED_INT_24_8 = 0x84FA

GL_RED = 0x1903
GL_RG = 0x8227
GL_RGB = 0x1907
GL_RGBA = 0x1908
GL_RGBA8 = 0x8058
GL_RGB8 = 0x8051
GL_RGBA16F = 0x881A
GL_RGBA32F = 0x8814
GL_RGB16F = 0x881B
GL_R11F_G11F_B10F = 0x8C3A
GL_RG16F = 0x822F
GL_R16F = 0x822D
GL_HALF_FLOAT = 0x140B
GL_DEPTH_COMPONENT16 = 0x81A5
GL_DEPTH_COMPONENT24 = 0x81A6
GL_DEPTH_COMPONENT32F = 0x8CAC

GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE_3D = 0x806F
GL_TEXTURE_CUBE_MAP = 0x8513
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_TEXTURE_WRAP_R = 0x8072
GL_NEAREST = 0x2600
GL_LINEAR = 0x2601
GL_NEAREST_MIPMAP_NEAREST = 0x2700
GL_LINEAR_MIPMAP_LINEAR = 0x2703
GL_CLAMP_TO_EDGE = 0x812F
GL_REPEAT = 0x2901
GL_TEXTURE_BASE_LEVEL = 0x813C
GL_TEXTURE_MAX_LEVEL = 0x813D

GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_DRAW_FRAMEBUFFER = 0x8CA9
GL_RENDERBUFFER = 0x8D41
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_DEPTH_ATTACHMENT = 0x8D00
GL_DEPTH_STENCIL_ATTACHMENT = 0x821A
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_DRAW_BUFFER0 = 0x8825
GL_NONE = 0

GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_INFO_LOG_LENGTH = 0x8B84
GL_ACTIVE_UNIFORMS = 0x8B86

GL_ARRAY_BUFFER = 0x8892
GL_ELEMENT_ARRAY_BUFFER = 0x8893
GL_STATIC_DRAW = 0x88E4
GL_DYNAMIC_DRAW = 0x88E8
GL_STREAM_DRAW = 0x88E0

GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BLEND = 0x0BE2
GL_SCISSOR_TEST = 0x0C11
GL_LEQUAL = 0x0203
GL_LESS = 0x0201
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_ONE = 1
GL_ZERO = 0
GL_FUNC_ADD = 0x8006
GL_KEEP = 0x1E00
GL_REPLACE = 0x1E01
GL_BACK = 0x0405
GL_CCW = 0x0901
GL_CW = 0x0900
GL_UNPACK_ALIGNMENT = 0x0CF5
GL_PACK_ALIGNMENT = 0x0D05
GL_NO_ERROR = 0

# ---- compatibility profile 专用：固定管线矩阵与 client-state 顶点数组。
# 光影包的 GLSL 直接读 gl_ModelViewProjectionMatrix / gl_TextureMatrix /
# gl_MultiTexCoord0 等内建（compatibility profile 下存在），这些不是
# uniform，必须由固定管线状态喂——所以才有下面这组"老 GL"入口。
GL_MODELVIEW = 0x1700
GL_PROJECTION = 0x1701
GL_TEXTURE = 0x1702
GL_VERTEX_ARRAY = 0x8074
GL_NORMAL_ARRAY = 0x8075
GL_COLOR_ARRAY = 0x8076
GL_TEXTURE_COORD_ARRAY = 0x8078
GL_ACTIVE_TEXTURE = 0x84E0


class GLError(Exception):
    pass


# ---------------------------------------------------------------- 指针适配
def _unwrap(ptr):
    """byref(x) / cast 出来的 CArgObject → 里面的 ctypes 对象。"""
    return getattr(ptr, "_obj", ptr)


def _addr(data):
    """把调用方给的数据参数转成 PyOpenGL 能吃的形式。

    调用方会给三类东西：None（空上传）、ctypes 数组/缓冲、c_void_p。
    PyOpenGL 直接吃前两类的 buffer 接口对象；c_void_p 只有地址，必须
    结合调用点已知的字节数包一层 from_address。
    """
    if data is None:
        return None
    if isinstance(data, c_void_p):
        if not data.value:
            return None
        return data.value          # int 地址，配合 _from_addr 使用
    return data


def _from_addr(addr, nbytes):
    return (c_char * int(nbytes)).from_address(addr)


class GLAPI:
    """与旧 ctypes 版同签名的桌面 GL 门面。

    所有方法只是把参数从 ctypes 风格翻成 PyOpenGL 风格，不做任何
    额外状态管理。缺入口在桌面 GL 3.3 上不存在（全部核心入口）。
    """

    def __init__(self):
        self.missing = []

    # ------------------------------------------------ 状态 / 查询
    def glGetString(self, name):
        return _gl.glGetString(name)

    def glGetIntegerv(self, pname, out):
        v = _gl.glGetIntegerv(pname)
        _unwrap(out).value = int(v)

    def glGetError(self):
        return _gl.glGetError()

    def glViewport(self, x, y, w, h):
        _gl.glViewport(x, y, w, h)

    def glScissor(self, x, y, w, h):
        _gl.glScissor(x, y, w, h)

    def glEnable(self, cap):
        _gl.glEnable(cap)

    def glDisable(self, cap):
        _gl.glDisable(cap)

    def glBlendFunc(self, s, d):
        _gl.glBlendFunc(s, d)

    def glBlendFuncSeparate(self, s, d, sa, da):
        _gl.glBlendFuncSeparate(s, d, sa, da)

    def glBlendEquation(self, m):
        _gl.glBlendEquation(m)

    def glBlendEquationSeparate(self, mrgb, ma):
        _gl.glBlendEquationSeparate(mrgb, ma)

    def glColorMask(self, r, g, b, a):
        _gl.glColorMask(r, g, b, a)

    def glDepthMask(self, f):
        _gl.glDepthMask(f)

    def glDepthFunc(self, f):
        _gl.glDepthFunc(f)

    def glClear(self, mask):
        _gl.glClear(mask)

    def glClearColor(self, r, g, b, a):
        _gl.glClearColor(r, g, b, a)

    def glClearDepthf(self, d):
        # 桌面 GL 没有 glClearDepthf，glClearDepth 语义相同（参数 double）
        _gl.glClearDepth(float(d))

    def glCullFace(self, m):
        _gl.glCullFace(m)

    def glFrontFace(self, m):
        _gl.glFrontFace(m)

    def glPixelStorei(self, pname, v):
        _gl.glPixelStorei(pname, v)

    # -------------------------------------- 固定管线矩阵（compatibility）
    def glMatrixMode(self, mode):
        _gl.glMatrixMode(mode)

    def glLoadMatrixf(self, m16):
        """m16: 16 float 列主序序列。"""
        arr = (c_float * 16)(*[float(x) for x in m16])
        _gl.glLoadMatrixf(arr)

    def glLoadIdentity(self):
        _gl.glLoadIdentity()

    def glGetActiveTexture(self):
        return int(_gl.glGetIntegerv(GL_ACTIVE_TEXTURE))

    # --------------------------------- client-state 顶点数组（compatibility）
    def glEnableClientState(self, cap):
        _gl.glEnableClientState(cap)

    def glDisableClientState(self, cap):
        _gl.glDisableClientState(cap)

    def glVertexPointer(self, size, typ, stride, ptr):
        _gl.glVertexPointer(size, typ, stride, self._off_ptr(ptr))

    def glColorPointer(self, size, typ, stride, ptr):
        _gl.glColorPointer(size, typ, stride, self._off_ptr(ptr))

    def glNormalPointer(self, typ, stride, ptr):
        _gl.glNormalPointer(typ, stride, self._off_ptr(ptr))

    def glTexCoordPointer(self, size, typ, stride, ptr):
        _gl.glTexCoordPointer(size, typ, stride, self._off_ptr(ptr))

    def glClientActiveTexture(self, unit):
        _gl.glClientActiveTexture(unit)

    @staticmethod
    def _off_ptr(ptr):
        """VBO 内字节偏移 → PyOpenGL 能吃的指针。None=0。"""
        if ptr is None:
            return ctypes.c_void_p(0)
        if isinstance(ptr, c_void_p):
            return ptr
        return ctypes.c_void_p(int(ptr))

    def glFinish(self):
        _gl.glFinish()

    def glFlush(self):
        _gl.glFlush()

    # ------------------------------------------------ 着色器 / 程序
    def glCreateShader(self, kind):
        return int(_gl.glCreateShader(kind))

    def glShaderSource(self, sh, count, strings, lengths):
        # 调用方给 (c_char_p * 1)(src)；桌面直接传 bytes 列表
        srcs = [strings[i] for i in range(count)]
        _gl.glShaderSource(sh, srcs)

    def glCompileShader(self, sh):
        _gl.glCompileShader(sh)

    def glGetShaderiv(self, sh, pname, out):
        _unwrap(out).value = int(_gl.glGetShaderiv(sh, pname))

    def glGetShaderInfoLog(self, sh, bufsize, length, buf):
        log = _gl.glGetShaderInfoLog(sh) or b""
        self._write_buf(buf, log)

    def glDeleteShader(self, sh):
        _gl.glDeleteShader(sh)

    def glCreateProgram(self):
        return int(_gl.glCreateProgram())

    def glAttachShader(self, prog, sh):
        _gl.glAttachShader(prog, sh)

    def glBindAttribLocation(self, prog, idx, name):
        _gl.glBindAttribLocation(prog, idx, name)

    def glLinkProgram(self, prog):
        _gl.glLinkProgram(prog)

    def glGetProgramiv(self, prog, pname, out):
        _unwrap(out).value = int(_gl.glGetProgramiv(prog, pname))

    def glGetProgramInfoLog(self, prog, bufsize, length, buf):
        log = _gl.glGetProgramInfoLog(prog) or b""
        self._write_buf(buf, log)

    def glUseProgram(self, prog):
        _gl.glUseProgram(prog)

    def glDeleteProgram(self, prog):
        _gl.glDeleteProgram(prog)

    def glGetUniformLocation(self, prog, name):
        return int(_gl.glGetUniformLocation(prog, name))

    def glGetAttribLocation(self, prog, name):
        return int(_gl.glGetAttribLocation(prog, name))

    @staticmethod
    def _write_buf(buf, data):
        """把 bytes 写进调用方的 create_string_buffer（含 \0 结尾）。"""
        if buf is None:
            return
        if isinstance(buf, c_char_p):
            return
        n = min(len(data), ctypes.sizeof(buf) - 1)
        if n > 0:
            ctypes.memmove(buf, data, n)
        ctypes.memset(ctypes.addressof(buf) + n, 0, 1)

    # ------------------------------------------------ uniform
    def glUniform1i(self, l, a):
        _gl.glUniform1i(l, a)

    def glUniform2i(self, l, a, b):
        _gl.glUniform2i(l, a, b)

    def glUniform3i(self, l, a, b, c):
        _gl.glUniform3i(l, a, b, c)

    def glUniform4i(self, l, a, b, c, d):
        _gl.glUniform4i(l, a, b, c, d)

    def glUniform1f(self, l, a):
        _gl.glUniform1f(l, a)

    def glUniform2f(self, l, a, b):
        _gl.glUniform2f(l, a, b)

    def glUniform3f(self, l, a, b, c):
        _gl.glUniform3f(l, a, b, c)

    def glUniform4f(self, l, a, b, c, d):
        _gl.glUniform4f(l, a, b, c, d)

    def glUniform1fv(self, l, n, p):
        _gl.glUniform1fv(l, n, _unwrap(p))

    def glUniform2fv(self, l, n, p):
        _gl.glUniform2fv(l, n, _unwrap(p))

    def glUniform3fv(self, l, n, p):
        _gl.glUniform3fv(l, n, _unwrap(p))

    def glUniform4fv(self, l, n, p):
        _gl.glUniform4fv(l, n, _unwrap(p))

    def glUniform1iv(self, l, n, p):
        _gl.glUniform1iv(l, n, _unwrap(p))

    def glUniform2iv(self, l, n, p):
        _gl.glUniform2iv(l, n, _unwrap(p))

    def glUniform3iv(self, l, n, p):
        _gl.glUniform3iv(l, n, _unwrap(p))

    def glUniform4iv(self, l, n, p):
        _gl.glUniform4iv(l, n, _unwrap(p))

    def glUniformMatrix2fv(self, l, n, t, p):
        _gl.glUniformMatrix2fv(l, n, bool(t), _unwrap(p))

    def glUniformMatrix3fv(self, l, n, t, p):
        _gl.glUniformMatrix3fv(l, n, bool(t), _unwrap(p))

    def glUniformMatrix4fv(self, l, n, t, p):
        _gl.glUniformMatrix4fv(l, n, bool(t), _unwrap(p))

    # ------------------------------------------------ 纹理
    def glGenTextures(self, n, out):
        ids = _gl.glGenTextures(n)
        self._fill_ids(n, ids, out)

    def glBindTexture(self, target, tex):
        _gl.glBindTexture(target, tex)

    def glTexImage2D(self, target, level, internal, w, h, border, fmt,
                     typ, data):
        _gl.glTexImage2D(target, level, internal, w, h, border, fmt, typ,
                         _addr(data))

    def glTexSubImage2D(self, target, level, x, y, w, h, fmt, typ, data):
        _gl.glTexSubImage2D(target, level, x, y, w, h, fmt, typ,
                            _addr(data))

    def glTexParameteri(self, target, pname, v):
        _gl.glTexParameteri(target, pname, v)

    def glTexParameterf(self, target, pname, v):
        _gl.glTexParameterf(target, pname, v)

    def glActiveTexture(self, unit):
        _gl.glActiveTexture(unit)

    def glDeleteTextures(self, n, out):
        ids = [_unwrap(out)[i] for i in range(n)] if n > 1 \
            else [_unwrap(out).value]
        _gl.glDeleteTextures(ids)

    def glGenerateMipmap(self, target):
        _gl.glGenerateMipmap(target)

    # ------------------------------------------------ FBO / RBO
    def glGenFramebuffers(self, n, out):
        self._fill_ids(n, _gl.glGenFramebuffers(n), out)

    def glBindFramebuffer(self, target, fbo):
        _gl.glBindFramebuffer(target, fbo)

    def glFramebufferTexture2D(self, target, attach, textarget, tex, level):
        _gl.glFramebufferTexture2D(target, attach, textarget, tex, level)

    def glCheckFramebufferStatus(self, target):
        return int(_gl.glCheckFramebufferStatus(target))

    def glDrawBuffers(self, n, bufs):
        if n == 0 or bufs is None:
            _gl.glDrawBuffer(GL_NONE)
            return
        arr = [_unwrap(bufs)[i] for i in range(n)]
        _gl.glDrawBuffers(arr)

    def glReadBuffer(self, mode):
        _gl.glReadBuffer(mode)

    def glDeleteFramebuffers(self, n, out):
        ids = [_unwrap(out)[i] for i in range(n)] if n > 1 \
            else [_unwrap(out).value]
        _gl.glDeleteFramebuffers(ids)

    def glGenRenderbuffers(self, n, out):
        self._fill_ids(n, _gl.glGenRenderbuffers(n), out)

    def glBindRenderbuffer(self, target, rbo):
        _gl.glBindRenderbuffer(target, rbo)

    def glRenderbufferStorage(self, target, fmt, w, h):
        _gl.glRenderbufferStorage(target, fmt, w, h)

    def glFramebufferRenderbuffer(self, target, attach, rbtarget, rbo):
        _gl.glFramebufferRenderbuffer(target, attach, rbtarget, rbo)

    def glDeleteRenderbuffers(self, n, out):
        ids = [_unwrap(out)[i] for i in range(n)] if n > 1 \
            else [_unwrap(out).value]
        _gl.glDeleteRenderbuffers(ids)

    def glBlitFramebuffer(self, *a):
        _gl.glBlitFramebuffer(*a)

    # ------------------------------------------------ VAO / VBO
    def glGenVertexArrays(self, n, out):
        self._fill_ids(n, _gl.glGenVertexArrays(n), out)

    def glBindVertexArray(self, vao):
        _gl.glBindVertexArray(vao)

    def glDeleteVertexArrays(self, n, out):
        ids = [_unwrap(out)[i] for i in range(n)] if n > 1 \
            else [_unwrap(out).value]
        _gl.glDeleteVertexArrays(ids)

    def glGenBuffers(self, n, out):
        self._fill_ids(n, _gl.glGenBuffers(n), out)

    def glBindBuffer(self, target, buf):
        _gl.glBindBuffer(target, buf)

    def glBufferData(self, target, nbytes, data, usage):
        if isinstance(data, c_void_p) and data.value:
            data = _from_addr(data.value, nbytes)
        elif isinstance(data, int):
            data = _from_addr(data, nbytes)
        _gl.glBufferData(target, int(nbytes), data, usage)

    def glBufferSubData(self, target, offset, nbytes, data):
        if isinstance(data, c_void_p) and data.value:
            data = _from_addr(data.value, nbytes)
        elif isinstance(data, int):
            data = _from_addr(data, nbytes)
        _gl.glBufferSubData(target, int(offset), int(nbytes), data)

    def glEnableVertexAttribArray(self, idx):
        _gl.glEnableVertexAttribArray(idx)

    def glDisableVertexAttribArray(self, idx):
        _gl.glDisableVertexAttribArray(idx)

    def glVertexAttribPointer(self, idx, size, typ, norm, stride, ptr):
        # ptr 是 VBO 内字节偏移。坑（实测 Intel + PyOpenGL 3.1.10）：
        # 直接传 Python int 会被 PyOpenGL 当成"数组对象"取它自己的堆地址，
        # 写进 VAO 的是 0x1E7Axxxxxxxx 这种垃圾指针——attr0 传 None 碰巧
        # 正确，attr1..4 全废，着色器读到全零（世界层全黑的根因）。
        # 必须包成 c_void_p，PyOpenGL 才会按裸指针值使用。
        if isinstance(ptr, c_void_p):
            ptr = ptr.value
        if isinstance(ptr, int):
            ptr = ctypes.c_void_p(ptr)
        _gl.glVertexAttribPointer(idx, size, typ, bool(norm), stride, ptr)

    def glDrawArrays(self, mode, first, count):
        _gl.glDrawArrays(mode, first, count)

    def glDrawElements(self, mode, count, typ, ptr):
        if isinstance(ptr, c_void_p):
            ptr = ptr.value
        if isinstance(ptr, int):
            ptr = ctypes.c_void_p(ptr)
        _gl.glDrawElements(mode, count, typ, ptr)

    def glDeleteBuffers(self, n, out):
        ids = [_unwrap(out)[i] for i in range(n)] if n > 1 \
            else [_unwrap(out).value]
        _gl.glDeleteBuffers(ids)

    # ------------------------------------------------ 读回
    def glReadPixels(self, x, y, w, h, fmt, typ, out):
        buf = _unwrap(out)
        _gl.glReadPixels(x, y, w, h, fmt, typ, buf)

    # ------------------------------------------------ 工具
    @staticmethod
    def _fill_ids(n, ids, out):
        """PyOpenGL 的 glGen*(1) 返回可能是 int / numpy 标量 / 数组，
        统一落到调用方的指针里。"""
        o = _unwrap(out)
        if n == 1:
            try:
                o.value = int(ids)          # int 或 numpy 标量
            except TypeError:
                o.value = int(ids[0])       # 真数组
        else:
            for i in range(n):
                o[i] = int(ids[i])

    def has(self, name):
        return hasattr(_gl, name)

    def check(self, where=""):
        err = _gl.glGetError()
        if err == GL_NO_ERROR:
            return None
        return "GL error 0x%04X @ %s" % (err, where or "?")


def open_gl():
    """返回桌面 GL 门面。没有当前上下文时由第一次调用炸出，上层接住。"""
    return GLAPI()
