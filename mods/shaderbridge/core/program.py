"""着色器程序封装：编译 / 链接 / uniform 定位与设置。

关键点（踩过的坑都在这）：
- glShaderSource 要传 c_char_p 数组的指针，且**源码里不能有 \\0**。
  直接把 Python str encode 后塞进 (c_char_p * 1)(src) 是错的——ctypes
  会取临时对象的地址，函数返回后悬空。必须自己持有引用。
- glGetShaderInfoLog 的 length 参数是"缓冲区大小"，传 0 拿不到东西。
- ES 里 uniform 名字被优化掉后 glGetUniformLocation 返回 -1，
  这不是错误，必须静默跳过（否则一堆 valid shader 会报假错）。
- uniform 名字可能是数组形式 `foo[0]`，glGetUniformLocation 只认带 [0] 的写法。
"""

from . import glapi

MAX_INFO_LOG = 16384


class ShaderError(Exception):
    pass


def _enc(s):
    b = s.encode("utf-8")
    if b"\x00" in b:
        b = b.replace(b"\x00", b" ")
    return b


class Program:
    """一个链接好的 GL 程序。"""

    def __init__(self, api, name, vsh_src, fsh_src, attribs=None):
        self.api = api
        self.name = name
        self.prog = 0
        self.uniforms = {}       # 名字 -> location
        self.attribs = {}        # 名字 -> index
        self.ok = False
        self.log = ""
        self.vsh_src = vsh_src
        self.fsh_src = fsh_src
        self._attribs_req = attribs or {}
        self._compile()

    # ------------------------------------------------------------- 编译
    def _compile(self):
        api = self.api
        vs = self._shader(glapi.GL_VERTEX_SHADER, self.vsh_src, "vert")
        fs = self._shader(glapi.GL_FRAGMENT_SHADER, self.fsh_src, "frag")
        if not vs or not fs:
            return
        prog = api.glCreateProgram()
        api.glAttachShader(prog, vs)
        api.glAttachShader(prog, fs)
        # 属性位置必须先绑再链接（ES 里链接后不能改）
        for nm, idx in self._attribs_req.items():
            api.glBindAttribLocation(prog, idx, _enc(nm))
        api.glLinkProgram(prog)
        ok = glapi.c_int(0)
        api.glGetProgramiv(prog, glapi.GL_LINK_STATUS, glapi.byref(ok))
        if not ok.value:
            self.log = "链接失败: " + self._prog_log(prog)
            api.glDeleteProgram(prog)
            api.glDeleteShader(vs)
            api.glDeleteShader(fs)
            return
        api.glDeleteShader(vs)
        api.glDeleteShader(fs)
        self.prog = prog
        self.ok = True
        self._collect_uniforms()

    def _shader(self, kind, src, tag):
        api = self.api
        sh = api.glCreateShader(kind)
        b = _enc(src)
        arr = (glapi.c_char_p * 1)(b)
        api.glShaderSource(sh, 1, arr, None)
        api.glCompileShader(sh)
        ok = glapi.c_int(0)
        api.glGetShaderiv(sh, glapi.GL_COMPILE_STATUS, glapi.byref(ok))
        if not ok.value:
            self.log = "%s 编译失败(%s): %s" % (self.name, tag,
                                               self._shader_log(sh))
            api.glDeleteShader(sh)
            return 0
        return sh

    def _shader_log(self, sh):
        api = self.api
        ln = glapi.c_int(0)
        api.glGetShaderiv(sh, glapi.GL_INFO_LOG_LENGTH, glapi.byref(ln))
        if ln.value <= 1:
            return "(无日志)"
        buf = glapi.create_string_buffer(ln.value)
        api.glGetShaderInfoLog(sh, ln.value, None, buf)
        return buf.value.decode("utf-8", "replace").strip()[:2000]

    def _prog_log(self, prog):
        api = self.api
        ln = glapi.c_int(0)
        api.glGetProgramiv(prog, glapi.GL_INFO_LOG_LENGTH, glapi.byref(ln))
        if ln.value <= 1:
            return "(无日志)"
        buf = glapi.create_string_buffer(ln.value)
        api.glGetProgramInfoLog(prog, ln.value, None, buf)
        return buf.value.decode("utf-8", "replace").strip()[:2000]

    def _collect_uniforms(self):
        """把源码里出现的 uniform 名都试一遍定位。名字源是源码文本，
        不依赖 glGetActiveUniform——后者要再处理类型/数组名，收益不大。"""
        import re
        names = set(re.findall(r"\buniform\s+\w+\s+([A-Za-z_]\w*)",
                               self.vsh_src + "\n" + self.fsh_src))
        api = self.api
        for nm in names:
            loc = api.glGetUniformLocation(self.prog, _enc(nm))
            if loc >= 0:
                self.uniforms[nm] = loc
        # 数组：再加一遍带 [0] 的
        for nm in list(names):
            loc = api.glGetUniformLocation(self.prog, _enc(nm + "[0]"))
            if loc >= 0:
                self.uniforms[nm] = loc

    # ------------------------------------------------------------- 使用
    def use(self):
        self.api.glUseProgram(self.prog)

    def loc(self, name):
        return self.uniforms.get(name, -1)

    def set_int(self, name, v):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform1i(l, int(v))
            return True
        return False

    def set_float(self, name, v):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform1f(l, float(v))
            return True
        return False

    def set_vec2(self, name, x, y):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform2f(l, float(x), float(y))
            return True
        return False

    def set_vec3(self, name, x, y, z):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform3f(l, float(x), float(y), float(z))
            return True
        return False

    def set_vec4(self, name, x, y, z, w):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform4f(l, float(x), float(y), float(z), float(w))
            return True
        return False

    def set_mat4(self, name, m16):
        """m16: 16 个 float 的列主序序列。"""
        l = self.loc(name)
        if l < 0:
            return False
        arr = (glapi.c_float * 16)(*[float(x) for x in m16])
        self.api.glUniformMatrix4fv(l, 1, glapi.GL_FALSE, arr)
        return True

    def set_mat3(self, name, m9):
        """m9: 9 个 float 的列主序序列（法线矩阵）。"""
        l = self.loc(name)
        if l < 0:
            return False
        arr = (glapi.c_float * 9)(*[float(x) for x in m9])
        self.api.glUniformMatrix3fv(l, 1, glapi.GL_FALSE, arr)
        return True

    def set_ivec2(self, name, x, y):
        l = self.loc(name)
        if l >= 0:
            self.api.glUniform2i(l, int(x), int(y))
            return True
        return False

    def release(self):
        if self.prog:
            self.api.glDeleteProgram(self.prog)
            self.prog = 0
        self.ok = False

    def __repr__(self):
        return "<Program %s %s uniforms=%d>" % (
            self.name, "ok" if self.ok else "FAIL", len(self.uniforms))