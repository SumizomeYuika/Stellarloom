"""着色器链：包 → 预处理 → 转译 → GL 编译，带缓存与失败隔离。

这一层是"能跑起来"和"炸掉游戏"之间的闸门：

- **懒编译 + 缓存**：一个 pass 第一次要执行时才编，编好的存 dict。
  换包或改选项才清缓存。
- **失败隔离**：某个 pass 编译失败只记进 `failures`，标记为不可用，
  其余 pass 照跑。最终屏幕至少能出 composite/final 的效果。
- **选项参与编译**：包里的 `#define` 选项改值必须重新预处理，
  因为很多分支是编译期决定的（`#if BLOOM_STRENGTH > 0`）。
  所以选项签名一变就整批失效。

依赖注入：packscan 给选项表，preproc 展开源码，glsl_es 转译，
program 编译。这里只做编排。
"""

import hashlib
import os

from . import glsl_es, passes, preproc, program, setters


def option_defines(info):
    """从包选项表产出应该注入的宏定义。

    关键：**只注入 `#define` 形式的选项**。`const float xxx = ...;` 形式的
    选项（source == "const"）已经在源码里声明了，再注入一个同名宏会把
    `const float ambientOcclusionLevel = 1.0;` 变成 `const float 1.0 = 1.0;`
    —— 直接语法错误。这个坑踩过一次，别重踩。
    """
    out = {}
    for nm, spec in info.options.items():
        if spec.source != "define":
            continue
        if spec.default is None or spec.default == "":
            continue
        if spec.kind in ("bool", "int", "float", "enum", "expr"):
            out[nm] = spec.default
    return out


class CompileResult:
    __slots__ = ("name", "ok", "prog", "vsh", "fsh", "log", "notes",
                 "drawbuffers", "degraded", "unsupported")

    def __init__(self, name):
        self.name = name
        self.ok = False
        self.prog = None
        self.vsh = ""
        self.fsh = ""
        self.log = ""
        self.notes = []
        self.drawbuffers = []
        self.degraded = []
        self.unsupported = []


class ShaderChain:
    """按包 + 选项编译整条 pass 链。

    选项分两类走两条路：
    - `#define` 形式 → 作为 defines 注入预处理器（覆盖源码里的同名 define）
    - `const`  形式 → 通过 preproc 的 overrides 做内存态源码改写
    两条路的签名合并成一个 hash，变一个就整批重编。
    """

    def __init__(self, api, pack_root, info, world="world0", defines=None,
                 const_values=None):
        self.api = api
        self.pack_root = pack_root
        self.shaders_dir = os.path.join(pack_root, "shaders")
        if os.path.basename(os.path.normpath(pack_root)) == "shaders":
            self.shaders_dir = pack_root
        self.info = info
        self.world = world
        self.defines = dict(defines or {})
        self.const_values = dict(const_values or {})
        self.programs = {}        # pass 名 -> Program
        self.results = {}         # pass 名 -> CompileResult
        self.specs = []
        self.failures = []
        self._sig = None
        self._const_overrides = None     # 计算一次，重编时复用

    # ------------------------------------------------------------ 签名
    def signature(self):
        """选项签名：值一变就要全部重编。"""
        h = hashlib.sha1()
        h.update(self.world.encode())
        for k in sorted(self.defines):
            h.update(("d:%s=%s;" % (k, self.defines[k])).encode())
        for k in sorted(self.const_values):
            h.update(("c:%s=%s;" % (k, self.const_values[k])).encode())
        return h.hexdigest()

    def set_options(self, defines, const_values):
        """更新两类选项值；签名变了就把已编程序全丢。返回是否失效。"""
        self.defines = dict(defines or {})
        cv = dict(const_values or {})
        if cv != self.const_values:
            self.const_values = cv
            self._const_overrides = None
        sig = self.signature()
        if sig != self._sig:
            self.release()
            self._sig = sig
            return True
        return False

    def _overrides(self):
        """按当前 const 选项值产出内存态源码覆盖表。"""
        if self._const_overrides is not None:
            return self._const_overrides
        ov = {}
        if self.const_values:
            files = setters.const_option_files(self.shaders_dir, self.info)
            for name, val in self.const_values.items():
                path = files.get(name)
                if not path:
                    continue
                text = ov.get(path)
                if text is None:
                    try:
                        text = open(path, "r", encoding="utf-8",
                                    errors="replace").read()
                    except OSError:
                        continue
                new_text, n = setters.patch_source_for_options(
                    text, self.info, {name: val})
                if n:
                    ov[path] = new_text
        self._const_overrides = ov
        return ov

    # ------------------------------------------------------------ 编译
    def build_all(self, force=False):
        """编译全部 pass。返回 (成功数, 失败数)。"""
        self._sig = self.signature()
        props = self._read_props()
        self.specs = passes.build_passes(self.info, self.world, props)

        pp = preproc.Preprocessor(self.shaders_dir, self.defines)
        pre_results = {}
        for spec in self.specs:
            res = CompileResult(spec.name)
            self.results[spec.name] = res
            try:
                built = self._build_one(pp, spec)
            except Exception as e:
                res.log = "预处理/转译异常: %s" % e
                self.failures.append((spec.name, res.log))
                continue
            if built is None:
                res.log = "缺入口源码"
                self.failures.append((spec.name, res.log))
                continue
            vsh_src, fsh_src, db, notes, degraded = built
            res.vsh, res.fsh = vsh_src, fsh_src
            res.drawbuffers = db
            res.notes = notes
            res.degraded = degraded
            pre_results[spec.name] = (db, fsh_src)
            if not spec.enabled:
                res.log = "properties 里禁用"
                continue
            prog = program.Program(self.api, spec.name, vsh_src, fsh_src,
                                   attribs=self._attribs_for(spec))
            if prog.ok:
                res.ok = True
                res.prog = prog
                self.programs[spec.name] = prog
            else:
                res.log = prog.log
                self.failures.append((spec.name, prog.log[:400]))

        passes.fill_io(self.specs, pre_results)
        ok_n = sum(1 for r in self.results.values() if r.ok)
        return ok_n, len(self.failures)

    def _read_props(self):
        path = os.path.join(self.shaders_dir, "shaders.properties")
        if not os.path.isfile(path):
            return {}
        from .packscan import _parse_properties
        return _parse_properties(
            open(path, "r", encoding="utf-8", errors="replace").read())

    def _build_one(self, pp, spec):
        """预处理 + 转译一个 pass。返回 (vsh, fsh, drawbuffers, notes, degraded)。"""
        notes = []
        degraded = []
        if not spec.fsh_rel:
            return None
        # 片段
        r = pp.build(spec.fsh_rel, "FRAGMENT", self.defines)
        t = glsl_es.transpile(r["src"], "FRAGMENT", r["drawbuffers"])
        fsh = t.src
        notes += t.notes
        degraded += t.degraded
        if not t.ok:
            degraded += t.unsupported
        db = r["drawbuffers"]

        # 顶点：没有就用全屏四边形着色器
        if spec.vsh_rel:
            rv = pp.build(spec.vsh_rel, "VERTEX", self.defines)
            tv = glsl_es.transpile(rv["src"], "VERTEX", None)
            vsh = tv.src
            notes += tv.notes
            degraded += tv.degraded
        else:
            vsh = passes.FullscreenQuad.VSH
        return vsh, fsh, db, notes, degraded

    def _attribs_for(self, spec):
        """几何 pass 与后处理 pass 的属性绑定，必须与转译器产出的名字一致。"""
        if spec.is_geometry:
            return dict(passes.FullscreenQuad.GEO_ATTRS)
        return dict(passes.FullscreenQuad.QUAD_ATTRS)

    # ------------------------------------------------------------ 查询
    def runner(self, pool, quad):
        return passes.PassRunner(self.api, pool, self.programs, quad)

    def summary(self):
        return {
            "world": self.world,
            "passes": len(self.specs),
            "compiled": sum(1 for r in self.results.values() if r.ok),
            "failed": len(self.failures),
            "failures": [(n, m[:120]) for n, m in self.failures[:8]],
        }

    def release(self):
        for p in self.programs.values():
            try:
                p.release()
            except Exception:
                pass
        self.programs.clear()
        self.results.clear()