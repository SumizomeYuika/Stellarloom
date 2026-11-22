"""GL 上下文获取：优先 PyOpenGL，失败退回 ctypes 直连 libGLESv2。

设计目标：**任何一步失败都必须干净地返回 None**，让上层 mod 走降级分支，
绝不抛异常把游戏带崩。
"""

from . import glapi


class GLUnavailable(Exception):
    pass


class GLContext:
    """一个尽量薄的 GL ES 3 封装。

    backend: "pyopengl" / "ctypes" / None
    """

    def __init__(self):
        self.backend = None
        self.gl = None
        self.version = ""
        self.renderer = ""
        self.vendor = ""
        self.es3 = False
        self.errors = []
        self.api = None

    # ---------------------------------------------------------------- 探测
    def probe(self):
        """依次尝试后端。返回是否成功。"""
        if self._try_pyopengl():
            return True
        if self._try_ctypes():
            return True
        return False

    def _read_strings(self):
        try:
            gl = self.gl
            self.version = str(gl.glGetString(gl.GL_VERSION) or b"")
            self.renderer = str(gl.glGetString(gl.GL_RENDERER) or b"")
            self.vendor = str(gl.glGetString(gl.GL_VENDOR) or b"")
        except Exception as e:
            self.errors.append("读 GL_VERSION 失败: %s" % e)
            return
        v = self.version.upper()
        self.es3 = ("OPENGL ES 3" in v)

    def _try_pyopengl(self):
        try:
            from OpenGL import GLES3 as gl          # noqa: N813
        except Exception as e:
            self.errors.append("PyOpenGL GLES3 导入失败: %s" % e)
            return False
        # 必须有已经创建的 GL 上下文，否则 GetString 返回 None
        try:
            ver = gl.glGetString(gl.GL_VERSION)
        except Exception as e:
            self.errors.append("PyOpenGL 调用失败（可能没有 GL 上下文）: %s" % e)
            return False
        if not ver:
            self.errors.append("PyOpenGL 可用但没有 GL 上下文")
            return False
        self.gl = gl
        self.backend = "pyopengl"
        self._read_strings()
        return True

    def _try_ctypes(self):
        try:
            api = glapi.open_gl()
        except glapi.GLError as e:
            self.errors.append(str(e))
            return False
        self.api = api
        try:
            ver = api.glGetString(glapi.GL_VERSION)
        except Exception as e:
            self.errors.append("ctypes glGetString 失败: %s" % e)
            return False
        if not ver:
            self.errors.append("ctypes 拿到 libGLESv2 但没有 GL 上下文")
            return False
        self.backend = "ctypes"
        self.gl = api
        self._read_strings()
        return True

    def summary(self):
        return {
            "backend": self.backend,
            "version": self.version,
            "vendor": self.vendor,
            "renderer": self.renderer,
            "es3": self.es3,
            "errors": self.errors,
        }


def find_gl_backend():
    """探测当前进程里的 GL 后端。"""
    c = GLContext()
    ok = c.probe()
    return ok, c
