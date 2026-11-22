"""GLES 3.0 入口绑定（ctypes），零第三方依赖。

为什么不直接用 PyOpenGL：PyOpenGL 的 GLES3 模块要 import 时就解析全部
入口，某些 Android 驱动缺符号会直接 ImportError，把 mod 整个带崩。
这里按需逐符号 dlsym，缺哪个只影响用到它的功能，其余照跑。

符号来源依次尝试：
1. libGLESv2.so 的 dlsym（多数实现把 gl* 直接导出）
2. eglGetProcAddress（GLES 规范正路，必须能覆盖扩展/新版入口）

所有 argtypes 都显式声明——ctypes 默认把 Python int 当 c_int 传，
指针参数会被截成 32 位，在 64 位 ARM 上直接段错误。
"""

import ctypes
from ctypes import (POINTER, byref, c_char, c_char_p, c_float, c_int,
                    c_uint, c_void_p, create_string_buffer)

GL_LIB_NAMES = ("libGLESv2.so", "libGLESv2.so.2", "libGLESv2.so.3")
EGL_LIB_NAMES = ("libEGL.so", "libEGL.so.1")

# ---------------------------------------------------------------- 常量
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

# ---------------------------------------------------------------- 绑定表
# (名字, 返回类型, 参数类型元组)
_BINDINGS = [
    # 状态
    ("glGetString", c_char_p, (c_uint,)),
    ("glGetIntegerv", None, (c_uint, POINTER(c_int))),
    ("glGetError", c_uint, ()),
    ("glViewport", None, (c_int, c_int, c_int, c_int)),
    ("glScissor", None, (c_int, c_int, c_int, c_int)),
    ("glEnable", None, (c_uint,)),
    ("glDisable", None, (c_uint,)),
    ("glBlendFunc", None, (c_uint, c_uint)),
    ("glBlendFuncSeparate", None, (c_uint, c_uint, c_uint, c_uint)),
    ("glBlendEquation", None, (c_uint,)),
    ("glBlendEquationSeparate", None, (c_uint, c_uint)),
    ("glColorMask", None, (c_uint, c_uint, c_uint, c_uint)),
    ("glDepthMask", None, (c_uint,)),
    ("glDepthFunc", None, (c_uint,)),
    ("glClear", None, (c_uint,)),
    ("glClearColor", None, (c_float, c_float, c_float, c_float)),
    ("glClearDepthf", None, (c_float,)),
    ("glCullFace", None, (c_uint,)),
    ("glFrontFace", None, (c_uint,)),
    ("glPixelStorei", None, (c_uint, c_int)),
    ("glFinish", None, ()),
    ("glFlush", None, ()),
    # 着色器
    ("glCreateShader", c_uint, (c_uint,)),
    ("glShaderSource", None, (c_uint, c_int, POINTER(c_char_p), c_void_p)),
    ("glCompileShader", None, (c_uint,)),
    ("glGetShaderiv", None, (c_uint, c_uint, POINTER(c_int))),
    ("glGetShaderInfoLog", None, (c_uint, c_int, c_void_p, c_char_p)),
    ("glDeleteShader", None, (c_uint,)),
    ("glCreateProgram", c_uint, ()),
    ("glAttachShader", None, (c_uint, c_uint)),
    ("glBindAttribLocation", None, (c_uint, c_uint, c_char_p)),
    ("glLinkProgram", None, (c_uint,)),
    ("glGetProgramiv", None, (c_uint, c_uint, POINTER(c_int))),
    ("glGetProgramInfoLog", None, (c_uint, c_int, c_void_p, c_char_p)),
    ("glUseProgram", None, (c_uint,)),
    ("glDeleteProgram", None, (c_uint,)),
    ("glGetUniformLocation", c_int, (c_uint, c_char_p)),
    ("glGetAttribLocation", c_int, (c_uint, c_char_p)),
    # uniform
    ("glUniform1i", None, (c_int, c_int)),
    ("glUniform2i", None, (c_int, c_int, c_int)),
    ("glUniform3i", None, (c_int, c_int, c_int, c_int)),
    ("glUniform4i", None, (c_int, c_int, c_int, c_int, c_int)),
    ("glUniform1f", None, (c_int, c_float)),
    ("glUniform2f", None, (c_int, c_float, c_float)),
    ("glUniform3f", None, (c_int, c_float, c_float, c_float)),
    ("glUniform4f", None, (c_int, c_float, c_float, c_float, c_float)),
    ("glUniform1fv", None, (c_int, c_int, POINTER(c_float))),
    ("glUniform2fv", None, (c_int, c_int, POINTER(c_float))),
    ("glUniform3fv", None, (c_int, c_int, POINTER(c_float))),
    ("glUniform4fv", None, (c_int, c_int, POINTER(c_float))),
    ("glUniform1iv", None, (c_int, c_int, POINTER(c_int))),
    ("glUniform2iv", None, (c_int, c_int, POINTER(c_int))),
    ("glUniform3iv", None, (c_int, c_int, POINTER(c_int))),
    ("glUniform4iv", None, (c_int, c_int, POINTER(c_int))),
    ("glUniformMatrix2fv", None, (c_int, c_int, c_uint, POINTER(c_float))),
    ("glUniformMatrix3fv", None, (c_int, c_int, c_uint, POINTER(c_float))),
    ("glUniformMatrix4fv", None, (c_int, c_int, c_uint, POINTER(c_float))),
    # 纹理
    ("glGenTextures", None, (c_int, POINTER(c_uint))),
    ("glBindTexture", None, (c_uint, c_uint)),
    ("glTexImage2D", None, (c_uint, c_int, c_int, c_int, c_int, c_int,
                            c_uint, c_uint, c_void_p)),
    ("glTexSubImage2D", None, (c_uint, c_int, c_int, c_int, c_int, c_int,
                               c_uint, c_uint, c_void_p)),
    ("glTexParameteri", None, (c_uint, c_uint, c_int)),
    ("glTexParameterf", None, (c_uint, c_uint, c_float)),
    ("glActiveTexture", None, (c_uint,)),
    ("glDeleteTextures", None, (c_int, POINTER(c_uint))),
    ("glGenerateMipmap", None, (c_uint,)),
    # FBO / RBO
    ("glGenFramebuffers", None, (c_int, POINTER(c_uint))),
    ("glBindFramebuffer", None, (c_uint, c_uint)),
    ("glFramebufferTexture2D", None, (c_uint, c_uint, c_uint, c_uint, c_int)),
    ("glCheckFramebufferStatus", c_uint, (c_uint,)),
    ("glDrawBuffers", None, (c_int, POINTER(c_uint))),
    ("glDeleteFramebuffers", None, (c_int, POINTER(c_uint))),
    ("glGenRenderbuffers", None, (c_int, POINTER(c_uint))),
    ("glBindRenderbuffer", None, (c_uint, c_uint)),
    ("glRenderbufferStorage", None, (c_uint, c_uint, c_int, c_int)),
    ("glFramebufferRenderbuffer", None, (c_uint, c_uint, c_uint, c_uint)),
    ("glDeleteRenderbuffers", None, (c_int, POINTER(c_uint))),
    ("glBlitFramebuffer", None, (c_int, c_int, c_int, c_int, c_int, c_int,
                                 c_int, c_int, c_uint, c_uint)),
    # VAO / VBO
    ("glGenVertexArrays", None, (c_int, POINTER(c_uint))),
    ("glBindVertexArray", None, (c_uint,)),
    ("glDeleteVertexArrays", None, (c_int, POINTER(c_uint))),
    ("glGenBuffers", None, (c_int, POINTER(c_uint))),
    ("glBindBuffer", None, (c_uint, c_uint)),
    ("glBufferData", None, (c_uint, c_void_p, c_void_p, c_uint)),
    ("glBufferSubData", None, (c_uint, c_void_p, c_void_p, c_void_p)),
    ("glEnableVertexAttribArray", None, (c_uint,)),
    ("glDisableVertexAttribArray", None, (c_uint,)),
    ("glVertexAttribPointer", None, (c_uint, c_int, c_uint, c_uint,
                                     c_int, c_void_p)),
    ("glDrawArrays", None, (c_uint, c_int, c_int)),
    ("glDrawElements", None, (c_uint, c_int, c_uint, c_void_p)),
    ("glDeleteBuffers", None, (c_int, POINTER(c_uint))),
    # 读回
    ("glReadPixels", None, (c_int, c_int, c_int, c_int, c_uint, c_uint,
                            c_void_p)),
]


class GLError(Exception):
    pass


class GLAPI:
    """按需绑定的 GLES3 门面。用一个 dict 做方法分派，缺符号只在调用时炸。"""

    def __init__(self, lib, resolver):
        self._lib = lib
        self._resolver = resolver
        self._cache = {}
        self.missing = []

    def __getattr__(self, name):
        fn = self._cache.get(name)
        if fn is not None:
            return fn
        # 常量（GL_VERSION 这类）：直接透出模块级值，不当函数绑定
        if name.startswith("GL_") and name in globals():
            return globals()[name]
        spec = _SPECS.get(name)
        if spec is None:
            raise AttributeError("未登记的 GL 入口: %s" % name)
        restype, argtypes = spec
        raw = self._resolver(name)
        if raw is None:
            self.missing.append(name)
            raise GLError("驱动缺少 GL 入口: %s" % name)
        fn = ctypes.CFUNCTYPE(restype, *argtypes)(raw)
        self._cache[name] = fn
        return fn

    def has(self, name):
        try:
            getattr(self, name)
            return True
        except GLError:
            return False

    def check(self, where=""):
        """把 GL 错误码翻成可读信息；无错返回 None。"""
        err = self.glGetError()
        if err == GL_NO_ERROR:
            return None
        return "GL error 0x%04X @ %s" % (err, where or "?")


_SPECS = {name: (rt, at) for name, rt, at in _BINDINGS}


def open_gl():
    """加载 libGLESv2 并返回 GLAPI。失败抛 GLError。"""
    lib = None
    for n in GL_LIB_NAMES:
        try:
            lib = ctypes.CDLL(n)
            break
        except OSError:
            continue
    if lib is None:
        raise GLError("找不到 libGLESv2.so")

    egl = None
    for n in EGL_LIB_NAMES:
        try:
            egl = ctypes.CDLL(n)
            break
        except OSError:
            continue
    getproc = None
    if egl is not None:
        try:
            getproc = egl.eglGetProcAddress
            getproc.restype = c_void_p
            getproc.argtypes = (c_char_p,)
        except AttributeError:
            getproc = None

    def resolver(name):
        raw = None
        try:
            raw = ctypes.cast(getattr(lib, name), c_void_p).value
        except AttributeError:
            raw = None
        if not raw and getproc is not None:
            try:
                raw = getproc(name.encode())
            except Exception:
                raw = None
        return raw

    return GLAPI(lib, resolver)
