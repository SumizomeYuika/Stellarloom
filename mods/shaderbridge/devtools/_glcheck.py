"""ShaderBridge 最小 GL 自检：无窗口环境下验证整条桌面 GL 链路。

跑法（在仓库根目录）：
    python mods/shaderbridge/devtools/_glcheck.py

验证内容（任何一步失败都非零退出）：
  1. glctx.GLContext 建出 WGL 离屏上下文（compatibility profile）
  2. glGetString 拿到桌面 GL 版本（>= 3.3）
  3. 经 glapi 门面编译一个 **legacy 着色器**（ftransform / gl_FragColor /
     gl_MultiTexCoord0——光影包同款写法，compatibility profile 专有）
  4. client-state 固定管线指针喂顶点，渲染三角形，glReadPixels 读回非零
"""

import ctypes
import os
import sys

# 让 core/ 里的相对导入可用：与 main.py 同一套"合成包"手法
_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.dirname(_HERE)
if _MOD not in sys.path:
    sys.path.insert(0, _MOD)

import types  # noqa: E402
import importlib  # noqa: E402

_PKG = "shaderbridge_core"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.join(_MOD, "core")]
    pkg.__package__ = _PKG
    sys.modules[_PKG] = pkg

glctx = importlib.import_module(_PKG + ".glctx")
glapi = importlib.import_module(_PKG + ".glapi")


def fail(msg, code=1):
    print("[glcheck] FAIL: %s" % msg)
    sys.exit(code)


def main():
    print("[glcheck] 1/4 建 WGL 离屏上下文（compatibility profile） ...")
    ctx = glctx.GLContext()
    if not ctx.create():
        fail("; ".join(ctx.errors))
    print("    GL_VERSION : %s" % ctx.version)
    print("    GL_RENDERER: %s" % ctx.renderer)
    print("    GL_VENDOR  : %s" % ctx.vendor)

    print("[glcheck] 2/4 检查版本 >= 3.3 ...")
    if (ctx.major, ctx.minor) < (3, 3):
        fail("GL 版本 %s 低于 3.3" % ctx.version)
    print("    OK (%d.%d)" % (ctx.major, ctx.minor))

    print("[glcheck] 3/4 编译 legacy 着色器 + 渲染三角形 ...")
    api = glapi.open_gl()

    # legacy 写法：ftransform / gl_MultiTexCoord0 / gl_TexCoord / gl_FragColor。
    # 这套符号只在 compatibility profile 存在——core profile 编不过。
    vsh = b"""#version 150 compatibility
void main() {
    gl_Position = ftransform();
    gl_TexCoord[0] = gl_MultiTexCoord0;
}
"""
    fsh = b"""#version 150 compatibility
void main() {
    gl_FragColor = vec4(gl_TexCoord[0].st, 0.3, 1.0);
}
"""
    vs = api.glCreateShader(glapi.GL_VERTEX_SHADER)
    api.glShaderSource(vs, 1, (glapi.c_char_p * 1)(vsh), None)
    api.glCompileShader(vs)
    ok = glapi.c_int(0)
    api.glGetShaderiv(vs, glapi.GL_COMPILE_STATUS, glapi.byref(ok))
    if not ok.value:
        fail("legacy 顶点着色器编译失败（compatibility profile 没建成？）")

    fs = api.glCreateShader(glapi.GL_FRAGMENT_SHADER)
    api.glShaderSource(fs, 1, (glapi.c_char_p * 1)(fsh), None)
    api.glCompileShader(fs)
    api.glGetShaderiv(fs, glapi.GL_COMPILE_STATUS, glapi.byref(ok))
    if not ok.value:
        fail("legacy 片段着色器编译失败（gl_FragColor 不可用）")

    prog = api.glCreateProgram()
    api.glAttachShader(prog, vs)
    api.glAttachShader(prog, fs)
    api.glLinkProgram(prog)
    api.glGetProgramiv(prog, glapi.GL_LINK_STATUS, glapi.byref(ok))
    if not ok.value:
        fail("程序链接失败")

    # FBO 64x64
    tid = glapi.c_uint(0)
    api.glGenTextures(1, glapi.byref(tid))
    api.glBindTexture(glapi.GL_TEXTURE_2D, tid.value)
    api.glTexImage2D(glapi.GL_TEXTURE_2D, 0, glapi.GL_RGBA8, 64, 64, 0,
                     glapi.GL_RGBA, glapi.GL_UNSIGNED_BYTE, None)
    fid = glapi.c_uint(0)
    api.glGenFramebuffers(1, glapi.byref(fid))
    api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, fid.value)
    api.glFramebufferTexture2D(glapi.GL_FRAMEBUFFER,
                               glapi.GL_COLOR_ATTACHMENT0,
                               glapi.GL_TEXTURE_2D, tid.value, 0)
    if api.glCheckFramebufferStatus(glapi.GL_FRAMEBUFFER) \
            != glapi.GL_FRAMEBUFFER_COMPLETE:
        fail("FBO 不完整")

    # client-state 固定管线指针：内建属性（gl_Vertex/gl_MultiTexCoord0）
    # 不走 generic attribute，只能靠这条路喂（实测 Intel UHD）。
    verts = []
    for x, y in ((-1.0, -1.0), (1.0, -1.0), (0.0, 1.0)):
        u = x * 0.5 + 0.5
        v = y * 0.5 + 0.5
        verts += [x, y, 0.0, 1.0, u, v, 0.0, 1.0]
    arr = (glapi.c_float * len(verts))(*verts)
    vbo = glapi.c_uint(0)
    api.glGenBuffers(1, glapi.byref(vbo))
    api.glBindBuffer(glapi.GL_ARRAY_BUFFER, vbo.value)
    api.glBufferData(glapi.GL_ARRAY_BUFFER, ctypes.sizeof(arr),
                     glapi.c_void_p(ctypes.addressof(arr)),
                     glapi.GL_STATIC_DRAW)
    api.glEnableClientState(glapi.GL_VERTEX_ARRAY)
    api.glVertexPointer(4, glapi.GL_FLOAT, 32, None)
    api.glEnableClientState(glapi.GL_TEXTURE_COORD_ARRAY)
    api.glTexCoordPointer(4, glapi.GL_FLOAT, 32, 16)

    api.glViewport(0, 0, 64, 64)
    api.glClearColor(0.0, 0.0, 0.0, 1.0)
    api.glClear(glapi.GL_COLOR_BUFFER_BIT)
    api.glUseProgram(prog)
    api.glDrawArrays(glapi.GL_TRIANGLES, 0, 3)
    api.glDisableClientState(glapi.GL_VERTEX_ARRAY)
    api.glDisableClientState(glapi.GL_TEXTURE_COORD_ARRAY)

    print("[glcheck] 4/4 glReadPixels 读回 ...")
    buf = (ctypes.c_ubyte * (64 * 64 * 4))()
    api.glReadPixels(0, 0, 64, 64, glapi.GL_RGBA, glapi.GL_UNSIGNED_BYTE,
                     buf)
    # 顶点颜色来自 gl_TexCoord[0].st（uv 渐变）+ 蓝通道 0.3：
    # 中心附近像素蓝通道应≈0.3*255≈77，整片三角形都非零。
    nz = sum(1 for i in range(0, len(buf), 4)
             if buf[i] > 0 or buf[i + 1] > 0 or buf[i + 2] > 0)
    print("    非零像素: %d / %d" % (nz, 64 * 64))
    if nz < 400:
        fail("三角形没画出来或 UV 全零（非零像素 %d 太少）" % nz)

    err = api.check("glcheck")
    if err:
        fail(err)

    ctx.release()
    print("[glcheck] PASS：compatibility 上下文 / legacy 编译 / "
          "client-state 渲染 / 读回 全链路 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
