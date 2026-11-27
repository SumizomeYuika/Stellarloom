"""极简 GLSL 预处理：直接交给桌面 GL **compatibility profile** 编译。

历史：旧管线（glsl_es.py）是"源码结构重写"转译器——改 attribute/varying
名字、把 gl_FragData 换成具名 out、重排 layout location、补 vec/ivec
转换……按一个包调好的规则换包就炸。用户拍板改为**不转译**：
GL 兼容性上下文里 ftransform() / gl_FragColor / gl_MultiTexCoord0 /
attribute / varying / texture2D 全部原生可用，源码原样保留。

这里只做三件**机械**的事：
1. 版号行归一：`#version N core` → `#version N compatibility`；
   `#version N es` → `#version N`（桌面 GLSL 没有 es 后缀）；
   缺省补 `#version 150 compatibility`（compatibility 关键字 150 起才有）。
2. 剥 precision：桌面 GLSL 不认 highp/mediump/lowp/precision 声明，
   限定词直接删除（其余 token 一律不动）。
3. 其它一切原样保留，不做任何结构重写。

接口与旧 transpile 相同（src/notes/degraded/unsupported/ok），
chain 层无感切换。
"""

import re

_VERSION_RE = re.compile(r"^\s*#\s*version\s+(\d+)\s*(\w+)?")
# precision 声明整行删
_PRECISION_STMT_RE = re.compile(
    r"^\s*precision\s+(?:highp|mediump|lowp)\s+[\w\s,]+;", re.M)
# 限定词删词（只可能出现在声明/参数位置；GLSL 保留字不会当变量名）
_PRECISION_WORD_RE = re.compile(r"\b(?:highp|mediump|lowp)\s+")


class MinResult:
    """与 glsl_es.TranspileResult 同形状，chain 直接用。"""

    def __init__(self):
        self.src = ""
        self.stage = ""
        self.degraded = []
        self.unsupported = []
        self.notes = []
        self.ok = True

    def to_dict(self):
        return {"ok": self.ok, "stage": self.stage,
                "degraded": self.degraded,
                "unsupported": self.unsupported, "notes": self.notes,
                "lines": len(self.src.splitlines())}


def transpile(src, stage, drawbuffers=None, target="desktop"):
    """机械预处理。drawbuffers 不需要（compact glDrawBuffers 在 GL 侧做）。

    target 参数保留只为兼容旧调用签名，忽略。
    """
    r = MinResult()
    r.stage = stage
    version = None
    body = []
    for line in src.splitlines():
        m = _VERSION_RE.match(line)
        if m:
            num, prof = m.group(1), (m.group(2) or "").lower()
            if prof == "core":
                version = "#version %s compatibility" % num
            elif prof == "es":
                version = "#version %s" % num
            elif prof == "compatibility":
                version = "#version %s compatibility" % num
            else:
                version = "#version %s" % num
            continue
        body.append(line)
    body = "\n".join(body)

    n_prec = len(_PRECISION_STMT_RE.findall(body))
    body = _PRECISION_STMT_RE.sub("", body)
    n_word = len(_PRECISION_WORD_RE.findall(body))
    body = _PRECISION_WORD_RE.sub("", body)
    if n_prec or n_word:
        r.notes.append("剥 precision（声明 %d 行 / 限定词 %d 处）"
                       % (n_prec, n_word))

    if version is None:
        version = "#version 150 compatibility"
        r.notes.append("缺 #version，补 150 compatibility")

    r.src = version + "\n" + body
    if not r.src.endswith("\n"):
        r.src += "\n"
    r.ok = True
    return r
