"""EGL 离屏 GL 上下文（pbuffer）。

为什么必须自己建上下文：
pygame 用 SDL 软件表面（SDL_Surface）画一切，进程里**没有 GL 上下文**。
SDL 只有在 SDL_WINDOW_OPENGL 模式才建 GL，而那样 pygame 的 blit 就废了
（画不到 GL 窗口上）。所以两条路都不能走：

- 用 SDL 的 GL 窗口 → pygame 的 UI 绘制全废
- 用 SDL 软件表面 → 没有 GL 上下文

正解：**挂一个自己的 EGL pbuffer 上下文**。它跟 SDL 完全无关，
渲染到自己的 FBO，`glReadPixels` 读回成 numpy → pygame Surface → blit。
UI 还是 pygame 画，世界是 GL 画的位图，两边井水不犯河水。

线程纪律：EGL context 绑定**当前线程**。SDL 在 Android 上把事件循环放在
主线程，我们的绘制也在主线程（Game._draw 里），所以同一线程 make_current
一次即可。若将来挪到副线程，每个线程都要自己 make_current。
"""

import ctypes
from ctypes import POINTER, byref, c_char_p, c_int, c_uint, c_void_p

EGL_LIB_NAMES = ("libEGL.so", "libEGL.so.1")

# ---------------------------------------------------------------- 常量
EGL_DEFAULT_DISPLAY = ctypes.c_void_p(0)
EGL_NO_DISPLAY = ctypes.c_void_p(0)
EGL_NO_CONTEXT = ctypes.c_void_p(0)
EGL_NO_SURFACE = ctypes.c_void_p(0)

EGL_SUCCESS = 0x3000
EGL_NOT_INITIALIZED = 0x3001
EGL_BAD_ACCESS = 0x3002
EGL_BAD_ALLOC = 0x3003
EGL_BAD_ATTRIBUTE = 0x3004
EGL_BAD_CONFIG = 0x3005
EGL_BAD_CONTEXT = 0x3006

EGL_NONE = 0x3038
EGL_PBUFFER_BIT = 0x0001
EGL_WINDOW_BIT = 0x0004

EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_ES2_BIT = 0x0004
EGL_OPENGL_ES3_BIT = 0x0040
EGL_SURFACE_TYPE = 0x3033

EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_DEPTH_SIZE = 0x3025
EGL_STENCIL_SIZE = 0x3026

EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_CONTEXT_MAJOR_VERSION = 0x3098
EGL_CONTEXT_MINOR_VERSION = 0x30FB

EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056

EGL_VENDOR = 0x3053
EGL_VERSION = 0x3054
EGL_EXTENSIONS = 0x3055


class EGLError(Exception):
    pass


_ERR_NAME = {
    EGL_NOT_INITIALIZED: "EGL_NOT_INITIALIZED",
    EGL_BAD_ACCESS: "EGL_BAD_ACCESS",
    EGL_BAD_ALLOC: "EGL_BAD_ALLOC",
    EGL_BAD_ATTRIBUTE: "EGL_BAD_ATTRIBUTE",
    EGL_BAD_CONFIG: "EGL_BAD_CONFIG",
    EGL_BAD_CONTEXT: "EGL_BAD_CONTEXT",
}


class EGLContext:
    """一个 pbuffer 承载的 GLES3 上下文。

    用法：
        ctx = EGLContext()
        if ctx.create():      # 失败会写 errors，不抛
            ...
        ctx.make_current()

    尺寸可以随窗口改变：pbuffer 不支持 resize，改尺寸就是重建 surface。
    这没关系——我们真正渲染的 FBO 是 buffers.BufferPool 自己的，pbuffer
    只是个"能让 GL 干活"的宿主，1x1 都够。所以默认给 1x1，永不用重建。
    """

    def __init__(self):
        self.lib = None
        self.display = EGL_NO_DISPLAY
        self.config = c_void_p(0)
        self.context = EGL_NO_CONTEXT
        self.surface = EGL_NO_SURFACE
        self.version = ""
        self.vendor = ""
        self.errors = []
        self.ok = False

    # ------------------------------------------------------------ 加载
    def _load(self):
        for n in EGL_LIB_NAMES:
            try:
                self.lib = ctypes.CDLL(n)
                break
            except OSError:
                continue
        if self.lib is None:
            self.errors.append("找不到 libEGL.so")
            return False
        try:
            L = self.lib
            L.eglGetDisplay.restype = c_void_p
            L.eglGetDisplay.argtypes = (c_void_p,)
            L.eglGetError.restype = c_int
            L.eglGetError.argtypes = ()
            L.eglInitialize.restype = c_uint
            L.eglInitialize.argtypes = (c_void_p, POINTER(c_int),
                                        POINTER(c_int))
            L.eglChooseConfig.restype = c_uint
            L.eglChooseConfig.argtypes = (c_void_p, POINTER(c_int),
                                          POINTER(c_void_p), c_int,
                                          POINTER(c_int))
            L.eglCreateContext.restype = c_void_p
            L.eglCreateContext.argtypes = (c_void_p, c_void_p, c_void_p,
                                           POINTER(c_int))
            L.eglCreatePbufferSurface.restype = c_void_p
            L.eglCreatePbufferSurface.argtypes = (c_void_p, c_void_p,
                                                  POINTER(c_int))
            L.eglMakeCurrent.restype = c_uint
            L.eglMakeCurrent.argtypes = (c_void_p, c_void_p, c_void_p,
                                        c_void_p)
            L.eglDestroySurface.restype = c_uint
            L.eglDestroySurface.argtypes = (c_void_p, c_void_p)
            L.eglDestroyContext.restype = c_uint
            L.eglDestroyContext.argtypes = (c_void_p, c_void_p)
            L.eglTerminate.restype = c_uint
            L.eglTerminate.argtypes = (c_void_p,)
            L.eglQueryString.restype = c_char_p
            L.eglQueryString.argtypes = (c_void_p, c_int)
            L.eglGetCurrentContext.restype = c_void_p
            L.eglGetCurrentContext.argtypes = ()
        except AttributeError as e:
            self.errors.append("libEGL 缺入口: %s" % e)
            return False
        return True

    # ------------------------------------------------------------ 创建
    def create(self):
        """建 display/config/context/surface。返回是否成功（失败写 errors）。"""
        if not self._load():
            return False
        L = self.lib
        self.display = L.eglGetDisplay(EGL_DEFAULT_DISPLAY)
        if not self.display:
            self.errors.append("eglGetDisplay 返回空（无 EGL 显示）")
            return False

        major, minor = c_int(0), c_int(0)
        if not L.eglInitialize(self.display, byref(major), byref(minor)):
            self.errors.append("eglInitialize 失败 0x%04X" % L.eglGetError())
            return False
        self.version = "%d.%d" % (major.value, minor.value)
        try:
            q = L.eglQueryString(self.display, EGL_VENDOR)
            self.vendor = (q or b"").decode("utf-8", "replace")
        except Exception:
            pass

        cfg = self._choose_config()
        if cfg is None:
            return False
        self.config = cfg

        ctx = self._make_context()
        if ctx is None:
            return False
        self.context = ctx

        surf = self._make_surface(cfg)
        if surf is None:
            L.eglDestroyContext(self.display, ctx)
            self.context = EGL_NO_CONTEXT
            return False
        self.surface = surf

        if not L.eglMakeCurrent(self.display, surf, surf, ctx):
            self.errors.append("eglMakeCurrent 失败 0x%04X"
                               % L.eglGetError())
            return False
        self.ok = True
        return True

    def _choose_config(self):
        """优先要 ES3，拿不到再退 ES2。pbuffer 载体，无窗口要求。"""
        L = self.lib
        for rt, tag in ((EGL_OPENGL_ES3_BIT, "ES3"),
                        (EGL_OPENGL_ES2_BIT, "ES2")):
            attrs = [
                EGL_RENDERABLE_TYPE, rt,
                EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                EGL_RED_SIZE, 8,
                EGL_GREEN_SIZE, 8,
                EGL_BLUE_SIZE, 8,
                EGL_ALPHA_SIZE, 8,
                EGL_DEPTH_SIZE, 24,
                EGL_NONE,
            ]
            arr = (c_int * len(attrs))(*attrs)
            out = (c_void_p * 1)()
            n = c_int(0)
            if L.eglChooseConfig(self.display, arr, out, 1, byref(n)) \
                    and n.value >= 1 and out[0]:
                return out[0]
            self.errors.append("eglChooseConfig(%s) 无可用配置" % tag)
        return None

    def _make_context(self):
        L = self.lib
        # 先按 3.0 建；失败再按 client_version=2（驱动老但兼容）
        variants = [
            [EGL_CONTEXT_MAJOR_VERSION, 3,
             EGL_CONTEXT_MINOR_VERSION, 0, EGL_NONE],
            [EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE],
        ]
        for attrs in variants:
            arr = (c_int * len(attrs))(*attrs)
            ctx = L.eglCreateContext(self.display, self.config,
                                     EGL_NO_CONTEXT, arr)
            if ctx:
                return ctx
            self.errors.append("eglCreateContext 失败 0x%04X attrs=%s"
                               % (L.eglGetError(), attrs[:-1]))
        return None

    def _make_surface(self, cfg):
        """1x1 pbuffer。真正渲染目标是我们自己的 FBO，pbuffer 只是宿主。"""
        L = self.lib
        attrs = [EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE]
        arr = (c_int * len(attrs))(*attrs)
        surf = L.eglCreatePbufferSurface(self.display, cfg, arr)
        if not surf:
            self.errors.append("eglCreatePbufferSurface 失败 0x%04X"
                               % L.eglGetError())
            return None
        return surf

    # ------------------------------------------------------------ 使用
    def make_current(self):
        """把本上下文切到当前线程。切线程/被抢走后可重复调用。"""
        if not self.ok:
            return False
        cur = self.lib.eglGetCurrentContext()
        if cur == self.context:
            return True
        ok = self.lib.eglMakeCurrent(self.display, self.surface,
                                    self.surface, self.context)
        if not ok:
            self.errors.append("eglMakeCurrent(重复) 失败 0x%04X"
                               % self.lib.eglGetError())
        return bool(ok)

    def release(self):
        """销毁一切。幂等。"""
        L = self.lib
        if L is None:
            return
        try:
            L.eglMakeCurrent(self.display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                             EGL_NO_CONTEXT)
        except Exception:
            pass
        if self.surface:
            L.eglDestroySurface(self.display, self.surface)
            self.surface = EGL_NO_SURFACE
        if self.context:
            L.eglDestroyContext(self.display, self.context)
            self.context = EGL_NO_CONTEXT
        if self.display:
            L.eglTerminate(self.display)
            self.display = EGL_NO_DISPLAY
        self.ok = False

    def summary(self):
        return {
            "ok": self.ok,
            "egl_version": self.version,
            "egl_vendor": self.vendor,
            "errors": self.errors,
        }
