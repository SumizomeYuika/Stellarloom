"""条件编译求值器：#if / #ifdef / #ifndef / #elif / #else / #endif + #define / #undef。

设计要点：
- #ifdef STAGE_FRAGMENT 这种"双段文件"标记必须被真正求值，不能靠删行——
  删行会破坏外部条件块配对（v1 原型就栽在这）。
- 宏只做值替换（对象式）；函数式宏原样保留文本，交给 GLSL 编译器。
"""

import re

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUM_RE = re.compile(
    r"[-+]?(?:0[xX][0-9a-fA-F]+|\d+\.\d*(?:[eE][-+]?\d+)?|"
    r"\d*\.\d+(?:[eE][-+]?\d+)?|\d+)[uU]?")


class CondError(Exception):
    pass


class Cond:
    def __init__(self, preset=None):
        self.defs = dict(preset or {})
        self.warnings = []
        self.option_values = {}     # 宏名 -> [档位...]（来自 // [...] 注释）

    def is_defined(self, name):
        return name in self.defs

    def eval_expr(self, expr):
        s = expr
        s = re.sub(r"defined\s*\(\s*([A-Za-z_]\w*)\s*\)",
                   lambda m: "1" if self.is_defined(m.group(1)) else "0", s)
        s = re.sub(r"defined\s+([A-Za-z_]\w*)",
                   lambda m: "1" if self.is_defined(m.group(1)) else "0", s)

        def _sub(m):
            n = m.group(0)
            if n in ("true", "True"):
                return "1"
            if n in ("false", "False"):
                return "0"
            v = self.defs.get(n)
            if v is None:
                return "0"
            v = str(v).strip()
            return v if NUM_RE.fullmatch(v) else "1"

        s = TOKEN_RE.sub(_sub, s)
        s = s.replace("&&", " and ").replace("||", " or ")
        s = re.sub(r"!(?!=)", " not ", s)
        s = s.replace("/", "//")
        try:
            return bool(eval(s, {"__builtins__": {}}, {}))
        except Exception:
            self.warnings.append("条件表达式求值失败，按 false 处理: %r" % expr)
            return False

    def process(self, text):
        """返回 (处理后的源码, 统计信息)。"""
        out = []
        stack = []
        active = True
        stats = {"kept": 0, "dropped": 0, "cond": 0, "define": 0}
        for line in text.splitlines():
            s = line.strip()
            d = s.split(None, 1)[0] if s else ""
            if d in ("#ifdef", "#ifndef", "#if"):
                stats["cond"] += 1
                arg = s[len(d):].strip()
                if d == "#ifdef":
                    ok = self.is_defined(arg.split()[0] if arg else "")
                elif d == "#ifndef":
                    ok = not self.is_defined(arg.split()[0] if arg else "")
                else:
                    ok = self.eval_expr(arg)
                stack.append([active, ok, ok])
                active = active and ok
                continue
            if d == "#elif":
                if not stack:
                    raise CondError("#elif 没有匹配的 #if")
                top = stack[-1]
                arg = s[len(d):].strip()
                ok = False if top[2] else self.eval_expr(arg)
                top[1] = ok
                top[2] = top[2] or ok
                active = top[0] and ok
                continue
            if d == "#else":
                if not stack:
                    raise CondError("#else 没有匹配的 #if")
                top = stack[-1]
                ok = not top[2]
                top[1] = ok
                top[2] = True
                active = top[0] and ok
                continue
            if d == "#endif":
                if not stack:
                    raise CondError("#endif 多余")
                stack.pop()
                active = (stack[-1][0] and stack[-1][1]) if stack else True
                continue
            if d == "#define":
                if active:
                    self._do_define(s[len(d):].strip())
                    stats["define"] += 1
                continue
            if d == "#undef":
                if active:
                    body = s[len(d):].strip()
                    if body:
                        self.defs.pop(body.split()[0], None)
                continue
            if d in ("#version", "#extension", "#pragma"):
                if active:
                    out.append(line)
                continue
            if active:
                out.append(line)
                stats["kept"] += 1
            else:
                out.append("")
                stats["dropped"] += 1
        if stack:
            raise CondError("条件块未闭合，剩余 %d 层" % len(stack))
        return "\n".join(out), stats

    def _do_define(self, body):
        m = re.match(r"([A-Za-z_]\w*)", body)
        if not m:
            return
        name = m.group(1)
        rest = body[m.end():]
        if rest.startswith("("):
            self.defs[name] = rest          # 函数式宏：原样留着
            return
        # OptiFine 选项语法：#define NAME 值 // [档位1 档位2 ...]
        # 档位注释必须剥掉（否则值不是合法字面量），但档位表要留住给设置界面用。
        m2 = re.match(r"^(.*?)\s*//\s*(.*)$", rest)
        if m2:
            val, cmt = m2.group(1), m2.group(2).strip()
            self.defs[name] = val.strip() or "1"
            mc = re.match(r"^\[([^\]]*)\]", cmt)
            if mc:
                self.option_values[name] = mc.group(1).split()
        else:
            self.defs[name] = rest.strip() or "1"


def _parse_macro_define(rest):
    """解析 #define 之后的文本（已去掉宏名）→ (params, body) 或 None。

    两种情况要区分：
      " (a)  (bayer2(0.5 * (a)) * 0.25 + bayer2(a))"   ← 有参数表，函数式宏
      " (clamp(alphaTestRef, A, B))"                    ← 是对象宏的值，值本身带括号

    判定规则：#define NAME( 必须**紧贴**（宏名后无空格）才是函数式宏。
    调用方已经把"宏名紧贴的 ( "这一信息保留了，所以这里直接看 rest[0]。
    """
    s = rest
    if not s.startswith("("):
        return None
    depth = 0
    end = -1
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    head = s[1:end]
    # 参数表只能是纯标识符列表；出现非标识符字符 → 这不是参数表，是对象宏的值
    params = [p.strip() for p in head.split(",")]
    for p in params:
        if not re.fullmatch(r"[A-Za-z_]\w*", p or ""):
            return None
    body = s[end + 1:].strip()
    if not params or not body:
        return None
    return params, body


def expand_function_macros(src, defs, rounds=10):
    """展开函数式宏，如 #define bayer64(a) (bayer32(0.5*(a))*0.25 + bayer2(a))。

    做法：每轮扫描"宏名 + 配对括号实参"，把 body 里的形参做字面替换后回填。
    多轮直到不再变化（bayer64→bayer32→…→bayer2 这种链式需要多轮）。
    自引用宏（body 里再次出现同名调用）靠轮数上限保护，不会死循环。
    """
    fns = {}
    for k, v in defs.items():
        parsed = _parse_macro_define(str(v))
        if parsed:
            fns[k] = parsed
    if not fns:
        return src, 0

    total = 0
    names = sorted(fns, key=len, reverse=True)   # 长名优先，bayer16 不被 bayer1 抢
    for _ in range(rounds):
        changed = 0
        for name in names:
            params, body = fns[name]
            out_parts = []
            i = 0
            n = len(src)
            pat = re.compile(r"\b" + re.escape(name) + r"\s*\(")
            while True:
                mt = pat.search(src, i)
                if not mt:
                    out_parts.append(src[i:])
                    break
                # 括号配对取实参
                start = mt.end()
                depth = 1
                j = start
                while j < n and depth:
                    ch = src[j]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                    j += 1
                if depth:
                    out_parts.append(src[i:])
                    break
                args = _split_args(src[start:j - 1])
                if len(args) != len(params):
                    out_parts.append(src[i:j])
                    i = j
                    continue
                out_parts.append(src[i:mt.start()])
                frag = body
                for p, a in zip(params, args):
                    frag = re.sub(r"\b" + re.escape(p) + r"\b", a.strip(), frag)
                out_parts.append("(" + frag + ")")
                i = j
                changed += 1
            src = "".join(out_parts)
        total += changed
        if not changed:
            break
    return src, total


def _split_args(s):
    """按顶层逗号切参数（忽略括号内的逗号）。"""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def expand_object_macros(src, defs, rounds=6):
    """把对象式宏在代码里替换掉（不碰 #define 行本身，也不碰字符串）。

    只替换"看起来像常量"的宏（值能完整解析成数字/表达式），
    以免把 GLSL 关键字或类型名搞坏。
    """
    simple = {}
    for k, v in defs.items():
        v = str(v).strip()
        # 注意：不能把"以 ( 开头"当成函数式宏过滤掉——CUTOUT_REF 的值
        # 就是 (clamp(...)) 这种括号表达式，属于对象宏。函数式宏在
        # expand_function_macros 里已经处理过了。
        simple[k] = v if v else "1"
    if not simple:
        return src, 0

    # 先把"宏指向宏"（EFFECTIVE_RENDER_SCALE = RENDER_SCALE）解析到最终字面量，
    # 否则替换一轮后仍留着未定义的标识符。
    resolved = {}
    for k in simple:
        cur = simple[k]
        seen = {k}
        for _ in range(16):
            m = re.fullmatch(r"[A-Za-z_]\w*", cur)
            if not m or cur in seen:
                break
            seen.add(cur)
            nxt = simple.get(cur)
            if nxt is None:
                break
            cur = nxt
        resolved[k] = cur
    simple = resolved

    # 只替换"能安全内联"的值：数字、括号包裹的表达式、单个标识符（如 VARYING = in）。
    # 括号包裹/无运算符的表达式不会破坏优先级；含 ; { } 的绝不内联。
    safe = {}
    for k, v in simple.items():
        v = v.strip()
        if not v or any(c in v for c in ";{}"):
            continue
        if NUM_RE.fullmatch(v):
            safe[k] = v
        elif re.fullmatch(r"[A-Za-z_]\w*", v):
            safe[k] = v                      # VARYING -> in / out
        elif v.startswith("(") and v.endswith(")"):
            safe[k] = v                      # CUTOUT_REF -> (clamp(...))
        elif re.fullmatch(r"[A-Za-z_]\w*\s*\(.*\)", v, re.S):
            # 构造函数调用式宏值：WHITE -> vec3(1.0, 1.0, 1.0)、
            # UI2 -> uvec2(UI0, UI1)。整体是表达式，内联不破坏优先级。
            safe[k] = v
        elif re.fullmatch(r"[-+*/.\s0-9eExXa-fA-F]+", v):
            safe[k] = "(" + v + ")"
    simple = safe

    if not simple:
        return src, 0
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in
                                      sorted(simple, key=len, reverse=True)) + r")\b")
    total = 0
    for _ in range(rounds):
        new, n = pat.subn(lambda m: simple[m.group(1)], src)
        total += n
        if n == 0 or new == src:
            src = new
            break
        src = new
    return src, total
