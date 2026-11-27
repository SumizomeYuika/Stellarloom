"""Windows 桌面 GL 上下文（WGL 离屏），PyOpenGL 专用。

为什么不用 pygame.OPENGL：游戏窗口是 pygame 软件表面，一旦用
`pygame.display.set_mode(OPENGL)` 重建，pygame 的所有 blit 就画不上去了。
也不能用 EGL pbuffer：这台机器上根本没有 libEGL.dll / libGLESv2.dll。

正解（用户拍板）：**自己用 Win32 + WGL 建一个隐藏窗口当 GL 宿主**。
窗口只有 16x16、永不显示，只用来拿到 HDC → wglCreateContext。
真正渲染目标是 buffers.BufferPool 自己的 FBO（屏幕输出也走屏幕 FBO，
见 buffers.bind_screen），所以这个窗口多大完全无所谓。

实现：纯 ctypes 调 user32/gdi32/opengl32，零第三方依赖（PyOpenGL 已是
项目依赖）。wglCreateContext 给的是**兼容性上下文**，Intel 核显直接给
到 4.x，跑 #version 330 core 的着色器没问题。

线程纪律：WGL context 绑定当前线程。绘制在主线程（Game._draw）里做，
create 也在主线程（on_load）。每帧 make_current 一次防被抢（很便宜）。
"""

import ctypes
from ctypes import wintypes

# ---------------------------------------------------------------- Win32
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_gl32 = ctypes.windll.opengl32
_kernel32 = ctypes.windll.kernel32

_WS_POPUP = 0x80000000
_PM_NOREMOVE = 0x0000

_PFD_DRAW_TO_WINDOW = 0x00000004
_PFD_SUPPORT_OPENGL = 0x00000020
_PFD_DOUBLEBUFFER = 0x00000001
_PFD_TYPE_RGBA = 0
_PFD_MAIN_PLANE = 0


class PIXELFORMATDESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("nSize", wintypes.WORD),
        ("nVersion", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("iPixelType", ctypes.c_byte),
        ("cColorBits", ctypes.c_byte),
        ("cRedBits", ctypes.c_byte), ("cRedShift", ctypes.c_byte),
        ("cGreenBits", ctypes.c_byte), ("cGreenShift", ctypes.c_byte),
        ("cBlueBits", ctypes.c_byte), ("cBlueShift", ctypes.c_byte),
        ("cAlphaBits", ctypes.c_byte), ("cAlphaShift", ctypes.c_byte),
        ("cAccumBits", ctypes.c_byte),
        ("cAccumRedBits", ctypes.c_byte),
        ("cAccumGreenBits", ctypes.c_byte),
        ("cAccumBlueBits", ctypes.c_byte),
        ("cAccumAlphaBits", ctypes.c_byte),
        ("cDepthBits", ctypes.c_byte),
        ("cStencilBits", ctypes.c_byte),
        ("cAuxBuffers", ctypes.c_byte),
        ("iLayerType", ctypes.c_byte),
        ("bReserved", ctypes.c_byte),
        ("dwLayerMask", wintypes.DWORD),
        ("dwVisibleMask", wintypes.DWORD),
        ("dwDamageMask", wintypes.DWORD),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)

_user32.DefWindowProcW.restype = ctypes.c_long
_user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM)
_user32.RegisterClassW.argtypes = (ctypes.c_void_p,)
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
_user32.DestroyWindow.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_gdi32.ChoosePixelFormat.argtypes = (wintypes.HDC, ctypes.c_void_p)
_gdi32.ChoosePixelFormat.restype = ctypes.c_int
_gdi32.SetPixelFormat.argtypes = (wintypes.HDC, ctypes.c_int,
                                  ctypes.c_void_p)
_gdi32.SetPixelFormat.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_gl32.wglCreateContext.restype = wintypes.HANDLE
_gl32.wglCreateContext.argtypes = (wintypes.HDC,)
_gl32.wglMakeCurrent.restype = wintypes.BOOL
_gl32.wglMakeCurrent.argtypes = (wintypes.HDC, wintypes.HANDLE)
_gl32.wglDeleteContext.argtypes = (wintypes.HANDLE,)
_gl32.wglGetCurrentContext.restype = wintypes.HANDLE
_gl32.wglGetProcAddress.restype = ctypes.c_void_p
_gl32.wglGetProcAddress.argtypes = (ctypes.c_char_p,)

# WGL_ARB_create_context 常量：我们**必须**要 compatibility profile——
# 光影包的 GLSL 用 ftransform() / gl_FragColor / gl_MultiTexCoord0 等
# legacy 内建，core profile 下根本不存在这些符号。
_WGL_CONTEXT_MAJOR_VERSION_ARB = 0x2091
_WGL_CONTEXT_MINOR_VERSION_ARB = 0x2092
_WGL_CONTEXT_PROFILE_MASK_ARB = 0x9126
_WGL_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001
_WGL_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB = 0x00000002

_WGLPROC = ctypes.WINFUNCTYPE(
    wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(ctypes.c_int))


def _get_create_context_attribs():
    """wglGetProcAddress 取 wglCreateContextAttribsARB。返回 callable 或 None。"""
    addr = _gl32.wglGetProcAddress(b"wglCreateContextAttribsARB")
    if not addr:
        return None
    return _WGLPROC(addr)

# DefWindowProcW 的地址直接当窗口过程用（我们只建消息不处理的宿主窗口）
_DEFPROC = ctypes.cast(_user32.DefWindowProcW, ctypes.c_void_p)


class GLUnavailable(Exception):
    pass


class GLContext:
    """一个隐藏窗口承载的桌面 GL 上下文。

    用法：
        ctx = GLContext()
        if ctx.create():      # 失败写 errors，不抛
            ctx.make_current()
            ...

    属性 backend/version/renderer/vendor 在建好后可读。
    """

    def __init__(self):
        self.hwnd = None
        self.hdc = None
        self.hglrc = None
        self.ok = False
        self.backend = "wgl"
        self.version = ""
        self.renderer = ""
        self.vendor = ""
        self.major = 0
        self.minor = 0
        self.errors = []
        self._class_registered = False
        self._class_name = "ShaderBridgeGLHost"

    # ------------------------------------------------------------ 创建
    def create(self):
        """建窗口 + DC + WGL 上下文并置为当前。返回是否成功。"""
        if self.ok:
            return True
        try:
            return self._create_inner()
        except Exception as e:
            self.errors.append("建 WGL 上下文异常: %s: %s"
                               % (type(e).__name__, e))
            self.release()
            return False

    def _create_inner(self):
        inst = _kernel32.GetModuleHandleW(None)

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = _DEFPROC.value
        wc.hInstance = inst
        wc.lpszClassName = self._class_name
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            # 已注册过（同进程第二次 create）不算失败
            err = _kernel32.GetLastError()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                self.errors.append("RegisterClassW 失败 err=%d" % err)
                return False
        self._class_registered = True

        hwnd = _user32.CreateWindowExW(
            0, self._class_name, "sb-gl", _WS_POPUP,
            0, 0, 16, 16, None, None, inst, None)
        if not hwnd:
            self.errors.append("CreateWindowExW 失败")
            return False
        self.hwnd = hwnd

        hdc = _user32.GetDC(hwnd)
        if not hdc:
            self.errors.append("GetDC 失败")
            return False
        self.hdc = hdc

        pfd = PIXELFORMATDESCRIPTOR()
        pfd.nSize = ctypes.sizeof(PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = (_PFD_DRAW_TO_WINDOW | _PFD_SUPPORT_OPENGL
                       | _PFD_DOUBLEBUFFER)
        pfd.iPixelType = _PFD_TYPE_RGBA
        pfd.cColorBits = 32
        pfd.cDepthBits = 24
        pfd.cStencilBits = 8
        pfd.iLayerType = _PFD_MAIN_PLANE
        fmt = _gdi32.ChoosePixelFormat(hdc, ctypes.byref(pfd))
        if not fmt:
            self.errors.append("ChoosePixelFormat 失败（无可用像素格式）")
            return False
        if not _gdi32.SetPixelFormat(hdc, fmt, ctypes.byref(pfd)):
            self.errors.append("SetPixelFormat 失败")
            return False

        hglrc = _gl32.wglCreateContext(hdc)
        if not hglrc:
            self.errors.append("wglCreateContext 失败")
            return False
        self.hglrc = hglrc
        if not _gl32.wglMakeCurrent(hdc, hglrc):
            self.errors.append("wglMakeCurrent 失败")
            return False

        # 普通 wglCreateContext 给的是"最高版本 compatibility"上下文
        # （WGL 规范：不带 attribs 时永远是兼容 profile）。但先拿到一个
        # 当前上下文才能调 wglGetProcAddress，然后升级成显式
        # compatibility attribs 上下文——这样驱动给的版本/特性才有保证，
        # 且日志里能明确确认 profile 类型。
        create_attribs = _get_create_context_attribs()
        upgraded = None
        if create_attribs is not None:
            for want in ((4, 6), (3, 3)):
                attrs = (ctypes.c_int * 8)(
                    _WGL_CONTEXT_MAJOR_VERSION_ARB, want[0],
                    _WGL_CONTEXT_MINOR_VERSION_ARB, want[1],
                    _WGL_CONTEXT_PROFILE_MASK_ARB,
                    _WGL_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB,
                    0, 0)
                try:
                    upgraded = create_attribs(hdc, attrs)
                except Exception:
                    upgraded = None
                if upgraded:
                    break
            if upgraded:
                # 切换：先解绑旧上下文再绑新的，然后销毁旧的
                _gl32.wglMakeCurrent(None, None)
                _gl32.wglDeleteContext(hglrc)
                self.hglrc = upgraded
                if not _gl32.wglMakeCurrent(hdc, upgraded):
                    self.errors.append("升级 compatibility 上下文后 "
                                       "makeCurrent 失败")
                    return False
        if not upgraded:
            self.errors.append("wglCreateContextAttribsARB 不可用，"
                               "回退普通上下文（默认 compatibility profile）")

        if not self._read_strings():
            return False
        self.ok = True
        return True

    def _read_strings(self):
        """读 GL 版本信息并检查 >= 3.3。"""
        try:
            from OpenGL import GL
            ver = GL.glGetString(GL.GL_VERSION)
            rend = GL.glGetString(GL.GL_RENDERER)
            vend = GL.glGetString(GL.GL_VENDOR)
        except Exception as e:
            self.errors.append("glGetString 失败（上下文未生效？）: %s" % e)
            return False
        if not ver:
            self.errors.append("glGetString(GL_VERSION) 返回空")
            return False
        self.version = ver.decode("utf-8", "replace") \
            if isinstance(ver, bytes) else str(ver)
        self.renderer = (rend or b"").decode("utf-8", "replace") \
            if isinstance(rend, bytes) else str(rend or "")
        self.vendor = (vend or b"").decode("utf-8", "replace") \
            if isinstance(vend, bytes) else str(vend or "")
        try:
            head = self.version.split()[0].split("-")[0]
            self.major, self.minor = (int(x) for x in head.split(".")[:2])
        except Exception:
            self.errors.append("解析 GL 版本失败: %r" % self.version)
            return False
        if (self.major, self.minor) < (3, 3):
            self.errors.append("需要桌面 OpenGL >= 3.3，实际 %s"
                               % self.version)
            return False
        return True

    # ------------------------------------------------------------ 使用
    def make_current(self):
        """把本上下文切回当前线程。每帧调一次，防被别的库抢走。"""
        if not self.ok:
            return False
        if _gl32.wglGetCurrentContext() == self.hglrc:
            return True
        return bool(_gl32.wglMakeCurrent(self.hdc, self.hglrc))

    def release(self):
        """销毁一切。幂等。"""
        try:
            if self.hglrc:
                _gl32.wglMakeCurrent(None, None)
                _gl32.wglDeleteContext(self.hglrc)
        except Exception:
            pass
        self.hglrc = None
        try:
            if self.hdc and self.hwnd:
                _user32.ReleaseDC(self.hwnd, self.hdc)
        except Exception:
            pass
        self.hdc = None
        try:
            if self.hwnd:
                _user32.DestroyWindow(self.hwnd)
        except Exception:
            pass
        self.hwnd = None
        try:
            if self._class_registered:
                _user32.UnregisterClassW(
                    self._class_name, _kernel32.GetModuleHandleW(None))
        except Exception:
            pass
        self._class_registered = False
        self.ok = False

    def summary(self):
        return {
            "backend": self.backend,
            "ok": self.ok,
            "gl_version": self.version,
            "gl_renderer": self.renderer,
            "gl_vendor": self.vendor,
            "errors": self.errors,
        }


def probe():
    """临时建一个上下文读 GL 信息然后释放。给日志/自检用。

    返回 (ok, GLContext)。ok=True 时该实例**仍然是活的**（没释放），
    调用方可以直接拿去用，也可以调 release() 丢掉。
    """
    c = GLContext()
    ok = c.create()
    return ok, c


# 兼容旧接口：main.py 早期版本调它做探测
def find_gl_backend():
    return probe()
