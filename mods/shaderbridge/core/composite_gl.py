"""一帧的 GL 渲染总调度：EGL → 缓冲 → pass 链 → 读回 pygame Surface。

这是所有核心模块的汇合点，也是"真的把光影包跑起来"的最后一环。

一帧的流程（严格按 Iris 语义）：

  1. 确保 EGL 上下文在当前线程
  2. 缓冲池尺寸对齐视口
  3. uniform 快照从星织相机推进一帧
  4. world_gl 生成顶点 → 上传
  5. shadow pass（若有）→ 画一遍几何写深度
  6. gbuffers_* pass → 画几何，写 colortex4/5 等
  7. deferred / composite / final → 全屏四边形，后处理
  8. 最后一个 pass 输出到屏幕 FBO（colortex0 或直接默认帧缓冲）
  9. glReadPixels → numpy → pygame.Surface（翻转 Y）

读回的性能取舍：一屏 1080p RGBA8 = 8MB/帧，手机上 memcpy 约 2~4ms。
用户在计划阶段选了"全分辨率、真执行"，这个代价是既定的。若将来要快，
可以改成 glBlitFramebuffer 到 EGL surface 再借用（但 Android 上 pyopengl
拿不到 native window，还是得读回）。

**任何一步失败都只记 failed 并返回 None** —— 上层看到 None 就退回
pygame 原生绘制。这是 mod 级硬约束：光影挂了游戏必须还能玩。
"""

import ctypes

from . import buffers, egl, glapi, glctx, uniforms


class GLFrameError(Exception):
    pass


class CompositeGL:
    """GL 渲染器：持有 EGL 上下文、缓冲池、pass 链和读回 Surface。

    生命周期：
        comp = CompositeGL()
        comp.setup(chain, size)      # 建上下文 + 缓冲 + 四边形，失败返回 False
        comp.begin_frame(camera, dt) # 每帧
        surf = comp.render(grid)     # 返回 pygame.Surface 或 None
        comp.release()
    """

    def __init__(self):
        self.ctx = egl.EGLContext()
        self.api = None
        self.gl_ok = False
        self.pool = None
        self.quad = None
        self.chain = None
        self.state = uniforms.UniformState()
        self.world = None            # world_gl.WorldGeometry
        self.size = (0, 0)
        self.notes = []
        self.errors = []
        self.frame = 0
        self._noise_tex = 0
        self._read_buf = None        # 复用读回缓冲，避免每帧 malloc
        self._surface = None         # 复用 pygame.Surface
        self._present = None         # 兜底上屏程序
        self._final_ran = False      # 本帧 final 是否真的跑过
        self.last_passes = 0
        self.last_failed = 0

    # ------------------------------------------------------------ 建立
    def setup(self, chain, size):
        """建 GL 全套。返回是否成功——失败时 self.errors 里有原因。"""
        from . import passes as P
        from . import world_gl

        self.chain = chain
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0:
            self.errors.append("视口尺寸非法 %dx%d" % (w, h))
            return False

        if not self.ctx.create():
            self.errors.extend(self.ctx.errors)
            self.errors.append("EGL 上下文建立失败")
            return False
        self.ctx.make_current()

        try:
            self.api = glapi.open_gl()
        except glapi.GLError as e:
            self.errors.append(str(e))
            return False

        ver = self.api.glGetString(glapi.GL_VERSION) or b""
        ver_s = ver.decode("utf-8", "replace")
        if "OpenGL ES 3" not in ver_s.upper():
            self.errors.append("需要 GLES3，实际: %s" % ver_s)
            return False
        self.notes.append("GL: %s" % ver_s)

        try:
            self.pool = buffers.BufferPool(self.api, w, h)
            self.quad = P.FullscreenQuad(self.api)
            self.world = world_gl.WorldGeometry(self.api, self.quad)
            self._noise_tex = buffers.make_noise_texture(self.api, 64)
        except Exception as e:
            self.errors.append("建 GL 资源失败: %s: %s" % (type(e).__name__, e))
            self.release()
            return False

        self.size = (w, h)
        self.gl_ok = True
        self._alloc_readback()
        self._setup_gl_state()
        return True

    def _setup_gl_state(self):
        """一次性 GL 状态。每帧会被 pass 改，但这是基准值。"""
        api = self.api
        try:
            api.glDisable(glapi.GL_DEPTH_TEST)
            api.glDisable(glapi.GL_CULL_FACE)
            api.glDisable(glapi.GL_BLEND)
            api.glDisable(glapi.GL_SCISSOR_TEST)
            api.glDepthFunc(glapi.GL_LEQUAL)
            api.glPixelStorei(glapi.GL_UNPACK_ALIGNMENT, 1)
            api.glPixelStorei(glapi.GL_PACK_ALIGNMENT, 1)
            api.glViewport(0, 0, self.size[0], self.size[1])
        except Exception as e:
            self.notes.append("设 GL 状态时异常: %s" % e)

    def _alloc_readback(self):
        """预分配读回缓冲。RGBA8 → w*h*4 字节。"""
        w, h = self.size
        self._read_buf = (ctypes.c_ubyte * (w * h * 4))()

    # ------------------------------------------------------------ 尺寸
    def resize(self, size):
        """视口变了就重建缓冲（FBO 尺寸必须跟视口一致）。"""
        w, h = int(size[0]), int(size[1])
        if (w, h) == self.size:
            return True
        self.size = (w, h)
        if not self.gl_ok:
            return False
        self.ctx.make_current()
        try:
            self.pool.resize(w, h)
            self._alloc_readback()
            self._surface = None
            api = self.api
            api.glViewport(0, 0, w, h)
        except Exception as e:
            self.errors.append("resize 失败: %s" % e)
            return False
        return True

    # ------------------------------------------------------------ 每帧
    def begin_frame(self, camera, dt, elapsed, world_pixels, grid=None,
                    extra=None):
        """推进 uniform 快照。渲染前必须调一次。"""
        self.state.update(camera, self.size, world_pixels, dt, elapsed,
                          grid=grid, extra=extra)
        self.frame += 1

    def render(self, grid, camera, dt=0.016, elapsed=0.0):
        """跑完整条链，返回 pygame.Surface（画面）或 None（失败）。"""
        if not self.gl_ok:
            return None
        self.ctx.make_current()

        try:
            self._render_inner(grid, camera)
        except Exception as e:
            self.errors.append("渲染帧失败: %s: %s" % (type(e).__name__, e))
            # 出错就把 GL 标记为坏，上层退回 pygame
            self.gl_ok = False
            return None

        return self._readback()

    def _render_inner(self, grid, camera):
        api = self.api
        pool = self.pool

        # 1) 世界顶点（先建，几何 pass 才有的画）
        cells = self.world.build(grid, camera, self.size)
        self.notes_last = "格 %d" % cells

        # 2) 首帧清理：缓冲内容是未定义的，不清会采样到垃圾/NaN
        if self.frame == 1:
            pool.clear_all_first_frame()

        api.glViewport(0, 0, self.size[0], self.size[1])

        runner = self.chain.runner(pool, self.quad)
        uniforms_cb = self._uniform_cb
        self._final_ran = False

        ok = 0
        failed = 0
        for spec in self.chain.specs:
            if spec.name not in self.chain.programs:
                continue
            if spec.name == "final":
                self._run_final(runner, spec, uniforms_cb)
                continue
            # 几何 pass 必须绑深度附件并开深度测试，否则写不出遮挡关系，
            # 后期所有基于深度的效果（雾/SSR/TAA 重投影）全废。
            if spec.is_geometry:
                api.glEnable(glapi.GL_DEPTH_TEST)
                api.glDepthMask(glapi.GL_TRUE)
                api.glDepthFunc(glapi.GL_LESS)
                okp = runner.run(spec, uniforms_cb, depth="depthtex0")
            else:
                api.glDisable(glapi.GL_DEPTH_TEST)
                okp = runner.run(spec, uniforms_cb)
            if okp:
                ok += 1
            else:
                failed += 1
        self.last_passes = ok
        self.last_failed = failed

        # 3) 兜底：如果 final 没跑成（包里没有或编译失败），
        #    把 colortex0（或 6）直接 blit 到屏幕上，至少能看到东西。
        if not self._final_ran:
            self._fallback_present()

    def _fallback_present(self):
        """final 缺席时的兜底上屏：取一张有内容的 colortex 画满屏。

        包里主色惯例是 colortex0；「春眠」用 colortex6。两个都试。
        """
        api = self.api
        pool = self.pool
        for cand in ("colortex6", "colortex0", "colortex5", "colortex4"):
            t = pool.tex.get(cand)
            if t is None:
                continue
            try:
                pool.bind_screen()
                api.glViewport(0, 0, self.size[0], self.size[1])
                api.glDisable(glapi.GL_DEPTH_TEST)
                api.glDisable(glapi.GL_BLEND)
                prog = self._present_prog()
                if prog is None:
                    return
                prog.use()
                api.glActiveTexture(glapi.GL_TEXTURE0)
                api.glBindTexture(glapi.GL_TEXTURE_2D, t.tex)
                prog.set_int("u_tex", 0)
                self.quad.draw()
                return
            except Exception as e:
                self.notes.append("兜底上屏失败(%s): %s" % (cand, e))

    def _present_prog(self):
        """懒建一个只做「纹理贴满屏」的程序，兜底用。"""
        from .core import program as prog_mod
        if getattr(self, "_present", None) is not None:
            return self._present
        src_f = """#version 300 es
precision highp float;
uniform highp sampler2D u_tex;
out vec4 o;
void main() { o = vec4(texture(u_tex, gl_FragCoord.xy /
                  vec2(textureSize(u_tex, 0))).rgb, 1.0); }
"""
        try:
            p = prog_mod.Program(self.api, "_present", self.quad.VSH, src_f,
                                 attribs={"slm_vertex": 0})
        except Exception as e:
            self.notes.append("建兜底程序失败: %s" % e)
            self._present = None
            return None
        self._present = p if p.ok else None
        return self._present

    def _run_final(self, runner, spec, uniforms_cb):
        """final 直接写默认帧缓冲（屏幕），不需要 FBO。"""
        prog = self.chain.programs.get(spec.name)
        if prog is None or not prog.ok:
            self._final_ran = False
            return False
        api = self.api
        self.pool.bind_screen()
        api.glViewport(0, 0, self.size[0], self.size[1])
        api.glDisable(glapi.GL_BLEND)
        prog.use()
        for nm in spec.inputs:
            act = self.pool.attach_name(nm)
            if not act.startswith(("colortex", "depthtex", "shadowtex")):
                continue
            u = runner.unit(act)
            self.pool.bind_sampler(api, u, act)
            prog.set_int(nm, u)
        uniforms_cb(prog, False)
        self.quad.draw()
        self._final_ran = True
        return True

    def _uniform_cb(self, prog, geometry=False):
        """给一条 pass 设 uniform，并绑定固定纹理（noisetex / tex）。"""
        try:
            self.state.apply(prog, self.pool, geometry=geometry)
        except Exception as e:
            self.notes.append("设 uniform 异常: %s" % e)
        # 固定纹理：noisetex 与 tex（包里所有入口都采样）
        api = self.api
        for nm, tex in (("noisetex", self._noise_tex),
                        ("tex", self._noise_tex)):
            if not tex:
                continue
            u = prog.loc(nm)
            if u < 0:
                continue
            unit = 12 if nm == "noisetex" else 13
            api.glActiveTexture(glapi.GL_TEXTURE0 + unit)
            api.glBindTexture(glapi.GL_TEXTURE_2D, tex)
            prog.set_int(nm, unit)

    # ------------------------------------------------------------ 读回
    def _readback(self):
        """glReadPixels 默认帧缓冲 → pygame.Surface（Y 翻转）。"""
        import numpy as np
        import pygame

        w, h = self.size
        api = self.api
        api.glBindFramebuffer(glapi.GL_FRAMEBUFFER, 0)
        api.glReadPixels(0, 0, w, h, glapi.GL_RGBA, glapi.GL_UNSIGNED_BYTE,
                         ctypes.byref(self._read_buf))
        arr = np.frombuffer(self._read_buf, dtype=np.uint8).reshape((h, w, 4))
        # GL 原点在左下，pygame 在左上 → 上下翻
        arr = np.ascontiguousarray(arr[::-1, :, :3])
        if self._surface is None:
            self._surface = pygame.Surface((w, h))
        # pygame.surfarray 期望 (w,h,3)
        pygame.surfarray.blit_array(self._surface,
                                    arr.transpose((1, 0, 2)))
        return self._surface

    # ------------------------------------------------------------ 释放
    def release(self):
        if self.world is not None:
            try:
                self.world.release()
            except Exception:
                pass
            self.world = None
        if self.quad is not None:
            try:
                self.quad.release()
            except Exception:
                pass
            self.quad = None
        if self.pool is not None:
            try:
                self.pool.release()
            except Exception:
                pass
            self.pool = None
        if self._noise_tex and self.api is not None:
            try:
                self.api.glDeleteTextures(
                    1, glapi.byref(glapi.c_uint(self._noise_tex)))
            except Exception:
                pass
            self._noise_tex = 0
        self.ctx.release()
        self.gl_ok = False
        self._surface = None
        self._read_buf = None

    # ------------------------------------------------------------ 诊断
    def summary(self):
        return {
            "gl_ok": self.gl_ok,
            "size": self.size,
            "frame": self.frame,
            "passes_run": self.last_passes,
            "passes_failed": self.last_failed,
            "egl": self.ctx.summary(),
            "errors": self.errors[-6:],
        }
