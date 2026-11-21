"""MOD API（M6.27）：mod 的公共接口层。

mod = `mods/<名字>/` 目录：
  mod.json —— 元数据：name / version / description（必须有 name）
  main.py  —— 逻辑入口，可定义 on_load(ctx) / on_unload(ctx)

ctx 能力（按需取用）：
- ctx.log(msg) / ctx.toast(text)         —— 调试输出 / 前端提示
- ctx.sim                                —— 服务器端 Simulation
  （只读查询 + sim 指令 API：place_building/remove_building/do_craft…）
- ctx.mixin(target, method, wrapper, wrap)
  —— 运行时补丁，三类 wrap：
     before(self, *a, **k)    原方法前跑，返回 (args, kwargs) 可替换调用参数，
                              返回 None 则不干预
     after (self, result, *a, **k)   原方法后跑，返回非 None 覆盖返回值
     replace(self, *a, **k)  全权替换（不再调用原方法）
  卸载/重载时自动还原原方法（非永久，源码零改动）。
  注意：mixin 是 M6.27 的"全开放"模式——mod 可以动任何类，改坏了
  它自己负责；加载器只保证"单个 mod 崩了不影响游戏"。
- ctx.add_item(item_id, name, color)     —— 注册物品（id 冲突拒绝）
- ctx.add_recipe(rid, inputs, outputs, dur) —— 注册配方（手搓/机器自动可见）
- ctx.on_step(fn) / ctx.on_event(fn)     —— 每步进回调 / sim 事件订阅
"""

from __future__ import annotations

import sys

from . import config as C

# M12：API 版本常量。.slmmod manifest 的 api 字段必须 == 本值才放行加载，
# 保证未来 API 变更时老包能被明确拒绝而不是神秘炸掉。
API_VERSION = 1


class ModAPIError(Exception):
    """API 用错（id 冲突 / 参数非法）。mod 会被加载器判失败并回滚。"""


# ---------- Minecraft 风格 mixin（M7：注解式） ----------

class MixinAt:
    """@Inject(at=...) 注入点。TAIL 与 RETURN 同义（Minecraft 的 TAIL）。"""
    HEAD = "HEAD"
    RETURN = "RETURN"
    TAIL = "RETURN"


# Minecraft 兼容别名（Fabric 里写作 @At("HEAD")）
At = MixinAt


class CallbackInfo:
    """注入函数收到的回调参数（签名：def f(self, *原参数, cir)）。

    at=HEAD（cancellable=True）：调 cir.cancel() 跳过原方法；
      取消时的返回值用 cir.set_return(v)；想现场换参改 cir.args[i]。
    at=RETURN：cir.return_value / cir.get_return() 是原方法刚算出的
      返回值；改成新值即覆盖（cir.set_return(v)）。
    """

    __slots__ = ("at", "args", "method", "_cancelled", "return_value")

    def __init__(self, at, args, method, return_value=None):
        self.at = at
        self.args = args
        self.method = method
        self._cancelled = False
        self.return_value = return_value

    # Minecraft 风格命名（camelCase 与 snake_case 双别名）
    def cancel(self):
        """HEAD 注入点：取消调用原方法。"""
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def set_return(self, v):
        """RETURN 注入点：覆盖返回值；HEAD+cancel：取消时的返回值。"""
        self.return_value = v

    def get_return(self):
        return self.return_value

    # camelCase 别名（照 Minecraft CallbackInfo 抄）
    isCancelled = is_cancelled
    setReturnValue = set_return
    getReturnValue = get_return


def Mixin(target):
    """类装饰器：声明一个 mixin 类（Minecraft @Mixin 风格）。

    target：点分路径字符串（"stellarloom.sim.sim.Simulation"）或类对象。
    类里的 @Inject / @Overwrite 方法会被加载器自动收集并应用——main.py
    一加载（on_load 之前）即注册，无需手动调用。
    """
    def deco(cls):
        cls._slm_mixin_target = target
        return cls
    return deco


def Inject(method: str, at: str = MixinAt.HEAD, cancellable: bool = False):
    """方法装饰器：注入到原方法（Minecraft @Inject 风格）。

    - at="HEAD"：进入原方法前；cancellable=True 时可用 cir.cancel() 跳过
      原方法；改 cir.args 可换参。
    - at="RETURN"：原方法正常返回后；改 cir.return_value 覆盖返回值。
    """
    if str(at).upper() not in (MixinAt.HEAD, MixinAt.RETURN):
        raise ModAPIError(f"@Inject(at=...) 必须 HEAD/RETURN，收到 {at!r}")

    def deco(fn):
        fn._slm_inject = {"method": method, "at": str(at).upper(),
                          "cancellable": bool(cancellable)}
        return fn
    return deco


def Overwrite(method: str):
    """方法装饰器：完全替换原方法（Minecraft @Overwrite 风格）。"""
    def deco(fn):
        fn._slm_overwrite = method
        return fn
    return deco


def collect_mixins(module) -> list:
    """扫模块顶层，返回所有被 @Mixin 标记的类（按定义顺序）。"""
    return [obj for obj in vars(module).values()
            if isinstance(obj, type) and hasattr(obj, "_slm_mixin_target")]


# 注解式 mixin 的注入函数全局去重表（跨 ctx 防重复包装；卸载时清）
_APPLIED_MIXIN_IDS: set[int] = set()


class ModContext:
    def __init__(self, name: str, version: str, description: str, game):
        self.name = name
        self.version = version
        self.description = description
        self._game = game
        self._sim = None          # 由加载器在 on_load 前注入
        self._patches: list[tuple[type, str, object]] = []
        self._step_fns: list = []
        self._event_fns: list = []
        self._added_items: list[int] = []
        self._added_recipes: list[str] = []
        # M14：液体相关注册（卸载时一并撤销）
        self._added_fluids: list[str] = []
        self._added_fluid_recipes: list[str] = []
        self._added_buildings: list[str] = []   # M8：注册的建筑名字 token
        self._added_building_items: list[int] = []  # M8：BUILD_ITEM 联动键
        # M6.29：统一配置（作者默认 config.json + 用户 mods/config/<name>.json）
        self._cfg_dir = None      # 由加载器注入（mods/config/）
        self._cfg = {}            # 合并后的运行时配置（用户优先覆盖默认）
        self._cfg_has_default = False   # 作者是否提供 config.json
        # M7：注解式 mixin（@Mixin/@Inject/@Overwrite）已应用的注入函数 id
        self._mixin_ids: list[int] = []
        # M12：单文件包解压目录（目录 mod 为 None）+ _lib 依赖目录
        self._mod_dir = None
        self._lib_dir = None

    # ---------- 交互 ----------

    def log(self, msg: str):
        print(f"[mod {self.name}] {msg}")

    def toast(self, text: str, secs: float = 2.0):
        g = self._game
        if g is not None and hasattr(g, "_toast_msg"):
            g._toast_msg(text, secs)

    # ---------- 服务器访问 ----------

    @property
    def sim(self):
        """服务器端 Simulation：只读查询 + 指令 API。"""
        if self._sim is None:
            raise ModAPIError(f"mod {self.name}: sim 尚未注入（on_load 里才可用）")
        return self._sim

    # ---------- 配置（M6.29：统一 config 存/写） ----------

    @property
    def cfg(self) -> dict:
        """运行时配置（作者 config.json 默认 + 用户配置合并，用户优先）。
        可读可改；改动要落盘就调 save_config()。"""
        return self._cfg

    def cfg_get(self, key, default=None):
        return self._cfg.get(key, default)

    def cfg_set(self, key, value):
        self._cfg[key] = value

    def save_config(self):
        """把当前 cfg 整个写盘到 mods/config/<name>.json（用户配置，
        独立于 mod 包，卸载/重载不清除，重启保持）。返回写的路径。"""
        if self._cfg_dir is None:
            raise ModAPIError(
                f"mod {self.name}: 配置目录未注入（加载器没初始化 config）")
        self._cfg_dir.mkdir(parents=True, exist_ok=True)
        p = self._cfg_dir / f"{self.name}.json"
        p.write_text(_json_dump(self._cfg), encoding="utf-8")
        return str(p)

    @property
    def config_path(self) -> str | None:
        """用户配置文件路径（可能在 save_config 前还不存在）。"""
        if self._cfg_dir is None:
            return None
        return str(self._cfg_dir / f"{self.name}.json")

    # ---------- M12：单文件包资源 ----------

    def resource(self, rel: str):
        """读包内资源（仅 .slmmod 包可用）：返回解压目录下的 Path。

        路径在包内 resources/ 下；拒绝 ../ 穿越。目录 mod 没有包资源，
        会抛 ModAPIError。
        """
        if self._mod_dir is None:
            raise ModAPIError(
                f"mod {self.name}: 不是单文件包，没有 resources/")
        base = (self._mod_dir / "resources").resolve()
        p = (base / rel).resolve()
        if not p.is_relative_to(base):
            raise ModAPIError(f"mod {self.name}: 非法资源路径 {rel!r}")
        return p

    @property
    def mod_dir(self) -> str | None:
        """单文件包的解压目录（目录 mod 返回 None）。"""
        return str(self._mod_dir) if self._mod_dir is not None else None

    # ---------- mixin（全开放补丁） ----------

    def mixin(self, target: str, method: str, wrapper, wrap: str = "before"):
        """运行时打补丁。target = 点分路径，如
        "stellarloom.sim.simulation.Simulation"，或类对象；wrap =
        before|after|replace。原方法引用被记住，卸载时还原。"""
        if wrap not in ("before", "after", "replace"):
            raise ModAPIError(f"mixin wrap 必须是 before/after/replace，收到 {wrap!r}")
        cls = target if isinstance(target, type) else _resolve(target)
        if not hasattr(cls, method):
            raise ModAPIError(f"mixin 目标 {target} 没有方法 {method}")
        orig = getattr(cls, method)
        if not callable(orig):
            raise ModAPIError(f"mixin 目标 {target}.{method} 不可调用")

        def wrapped(self, *a, **k):
            if wrap == "replace":
                return wrapper(self, *a, **k)
            if wrap == "before":
                r = wrapper(self, *a, **k)
                if r is not None:
                    a, k = r
                return orig(self, *a, **k)
            res = orig(self, *a, **k)
            r = wrapper(self, res, *a, **k)
            return res if r is None else r

        setattr(cls, method, wrapped)
        self._patches.append((cls, method, orig))
        self.log(f"mixin {wrap} {target}.{method}")

    # ---------- M7：注解式 mixin（@Mixin / @Inject / @Overwrite） ----------

    def apply_mixin_class(self, cls):
        """把 @Mixin 类应用到目标（HEAD/RETURN/Overwrite 三路）。
        自动被加载器调用；on_load 里也可手动补注册。
        已应用过的注入函数（id 去重）不会重复包装。"""
        global _APPLIED_MIXIN_IDS
        target = cls._slm_mixin_target
        target_cls = _resolve(target) if isinstance(target, str) else target
        for name in vars(cls):
            fn = getattr(cls, name)
            inject = getattr(fn, "_slm_inject", None)
            overwrite = getattr(fn, "_slm_overwrite", None)
            if inject is None and overwrite is None:
                continue
            if id(fn) in _APPLIED_MIXIN_IDS:
                self.log(f"mixin 注入函数 {cls.__name__}.{name} 已应用过，跳过")
                continue
            if overwrite is not None:
                wrapper = fn
                method = overwrite
            else:
                method = inject["method"]
                at = inject["at"]

                def make_wrapper(fn_, at_, orig_):
                    if at_ == MixinAt.HEAD:
                        def wrapped(self, *a, **k):
                            cir = CallbackInfo("HEAD", list(a), orig_)
                            fn_(self, *a, cir)
                            if cir.is_cancelled():
                                return cir.get_return()
                            return orig_(self, *cir.args, **k)
                    else:  # RETURN
                        def wrapped(self, *a, **k):
                            res = orig_(self, *a, **k)
                            cir = CallbackInfo("RETURN", list(a), orig_,
                                               return_value=res)
                            fn_(self, *a, cir)
                            return cir.get_return()
                    return wrapped

                # 注意：orig 取自**目标类当前属性**（同方法多注入依序包装，
                # 后一个拿到前一个的包装版，还原链也顺）。
                wrapper = make_wrapper(fn, at, getattr(target_cls, method))
            self._apply_one(target, method, wrapper)
            self._mixin_ids.append(id(fn))
            _APPLIED_MIXIN_IDS.add(id(fn))
        self.log(f"mixin 类 {cls.__name__} 已应用")

    def _apply_one(self, target, method, wrapper):
        # 走 mixin() 的 replace 通道（记录 orig，卸载自动还原）
        self.mixin(target, method, wrapper, "replace")

    # ---------- 内容扩展 ----------

    def add_item(self, item, name=None, color=None):
        """注册物品（M7 注册表）。

        - item 传 **名字**（"mymod:magic_ingot"）→ 动态分配数字 id（推荐）；
        - item 传 int（旧式兼容，如 300）→ 固定 id 注册，键名
          "<mod名>:item300"——旧存档数字可反查，旧代码不破。
        name = 显示名（可省，缺省用键名）；color = "#RRGGBB[AA]" 可选。
        名字/固定 id 已被占用 → 拒绝并让该 mod 加载失败。"""
        from .registry import ITEM_REGISTRY, RegistryError
        if isinstance(item, int):
            token = f"{self.name}:item{item}"
            fixed = item
        else:
            token = str(item)
            if ":" not in token:
                token = f"{self.name}:{token}"
            fixed = None
        display = name or token
        color_ = _hex(color) if color else None
        try:
            if fixed is not None:
                rid = ITEM_REGISTRY.fixed_register(
                    fixed, token, display, color_)
            else:
                rid = ITEM_REGISTRY.dynamic_register(token, display, color_)
        except RegistryError as e:
            raise ModAPIError(f"add_item {token}: {e}") from None
        self._added_items.append(token)
        self.log(f"注册物品 {rid} {token}")

    def add_recipe(self, rid: str, inputs: dict, outputs: dict,
                   dur: float, machines: tuple = (),
                   fluid_inputs: dict | None = None,
                   fluid_outputs: dict | None = None):
        """注册配方（M7 起原料/产物可用名字 "stellarloom:iron_ore" 或数字）。
        machines = 能造的机器（建筑 id 元组，原版可写数字）。

        M14：`fluid_inputs` / `fluid_outputs` 用液体名字（"stellarloom:crude_oil"）
        → 液体量（float）。这条配方可以**只有液体**（inputs/outputs 传空 dict），
        机器会自动从相邻管道抽料、把产物排回管道。
        """
        if rid in C.RECIPES:
            raise ModAPIError(f"add_recipe: 配方 {rid} 已存在")
        has_fluid = bool(fluid_inputs) or bool(fluid_outputs)
        if not has_fluid and (not inputs or not outputs):
            raise ModAPIError(f"add_recipe {rid}: inputs/outputs/dur 非法")
        if dur <= 0:
            raise ModAPIError(f"add_recipe {rid}: dur 必须 > 0")
        from .registry import (ITEM_REGISTRY, BUILDING_REGISTRY,
                               FLUID_REGISTRY, RegistryError)
        try:
            ins = {ITEM_REGISTRY.id_of(k): int(v)
                   for k, v in (inputs or {}).items()}
            outs = {ITEM_REGISTRY.id_of(k): int(v)
                    for k, v in (outputs or {}).items()}
        except RegistryError as e:
            raise ModAPIError(f"add_recipe {rid}: {e}") from None
        try:
            machines = tuple(BUILDING_REGISTRY.id_of(m) for m in machines)
        except RegistryError as e:
            raise ModAPIError(f"add_recipe {rid}: machines {e}") from None
        fin: dict = {}
        fout: dict = {}
        try:
            fin = {FLUID_REGISTRY.id_of(k): float(v)
                   for k, v in (fluid_inputs or {}).items()}
            fout = {FLUID_REGISTRY.id_of(k): float(v)
                    for k, v in (fluid_outputs or {}).items()}
        except RegistryError as e:
            raise ModAPIError(f"add_recipe {rid}: 液体 {e}") from None
        # 4 元组与原版一致：(原料, 产物, 单件耗时, 可制造的机器列表)
        C.RECIPES[rid] = (ins, outs, float(dur), machines)
        if fin or fout:
            C.RECIPE_FLUIDS[rid] = (fin, fout)
        self._added_recipes.append(rid)
        if fin or fout:
            self._added_fluid_recipes.append(rid)
        self.log(f"注册配方 {rid}"
                 + ("（含液体）" if (fin or fout) else ""))

    def add_fluid(self, name, display=None, color=None) -> int:
        """注册一种液体（M14）。name 用命名空间（"mymod:sludge"）。

        返回数字 id。液体是独立 id 段：不进背包、不上传送带、
        不进分拣器过滤列表；配方用 add_recipe(fluid_inputs=...) 引用。
        """
        from .registry import FLUID_REGISTRY, RegistryError
        if not isinstance(name, str) or ":" not in name:
            raise ModAPIError(
                f"add_fluid: 名字必须是 命名空间:名字，收到 {name!r}")
        try:
            fid = FLUID_REGISTRY.dynamic_register(
                name, display or name.split(":", 1)[1],
                _hex(color) if color else None)
        except RegistryError as e:
            raise ModAPIError(f"add_fluid {name}: {e}") from None
        self._added_fluids.append(name)
        self.log(f"注册液体 {name} → id {fid}")
        return fid

    def add_building(self, btype, name=None, item=None):
        """注册建筑类型（M8 建筑注册表）。

        - btype 传 **名字**（"mymod:foundry"）→ 动态分配数字 id（≥100，
          避开原版 1-13 与存量 mod 硬编码段），**推荐**；
        - btype 传 int（旧式兼容）→ 固定注册，键 "<mod名>:b<id>"，
          建筑内部照旧用该数字（mod 已有硬编码常量时可登记以拿显示名）。
        name = 显示名（可省，缺省用键名）；item = 放置时消耗的建筑物品
        （名字或数字，如 "gregtech_extra:item2040"），注册
        BUILD_ITEM[btype] 联动——底栏取物/拆除返还/放置消耗自动生效。
        返回建筑类型数字 id（放网格数组用）。"""
        from .registry import BUILDING_REGISTRY, RegistryError
        if isinstance(btype, int):
            token = f"{self.name}:b{btype}"
            fixed = btype
        else:
            token = str(btype)
            if ":" not in token:
                token = f"{self.name}:{token}"
            fixed = None
        display = name or token
        try:
            if fixed is not None:
                bid = BUILDING_REGISTRY.fixed_register(fixed, token, display)
            else:
                bid = BUILDING_REGISTRY.dynamic_register(token, display)
        except RegistryError as e:
            raise ModAPIError(f"add_building {token}: {e}") from None
        # 建筑物品联动（可选）：放置消耗/拆除返还/底栏取物查 BUILD_ITEM
        if item is not None:
            from .registry import ITEM_REGISTRY
            try:
                item_id = ITEM_REGISTRY.id_of(item)
            except RegistryError as e:
                # 建筑注册本身有效，联动失败单独报
                raise ModAPIError(
                    f"add_building {token}: 建筑物品 {item!r} 未注册"
                    f"（{e}）请先 add_item") from None
            C.BUILD_ITEM[bid] = item_id
            self._added_building_items.append(bid)
        self._added_buildings.append(token)
        self.log(f"注册建筑 {bid} {token}")
        return bid

    # ---------- 事件钩子 ----------

    def on_step(self, fn):
        """每服务器步进调一次 fn(dt)。"""
        self._step_fns.append(fn)

    def on_event(self, fn):
        """sim 事件流里的每条事件调 fn(event)（event=(kind, *payload)）。"""
        self._event_fns.append(fn)

    # 加载器内部回调（mod 不直接调）
    def _unload(self):
        global _APPLIED_MIXIN_IDS
        for cls, method, orig in reversed(self._patches):
            setattr(cls, method, orig)
        self._patches.clear()
        _APPLIED_MIXIN_IDS.difference_update(self._mixin_ids)
        self._mixin_ids.clear()
        # 撤销内容注册（只清自己注册的；非永久，重载/卸载后干净）
        from .registry import ITEM_REGISTRY
        for token in self._added_items:
            ITEM_REGISTRY.unregister(token)
        self._added_items.clear()
        for rid in self._added_recipes:
            C.RECIPES.pop(rid, None)
        self._added_recipes.clear()
        for rid in self._added_fluid_recipes:
            C.RECIPE_FLUIDS.pop(rid, None)
        self._added_fluid_recipes.clear()
        from .registry import FLUID_REGISTRY
        for token in self._added_fluids:
            FLUID_REGISTRY.unregister(token)
        self._added_fluids.clear()
        # M8：建筑注册还原（含 BUILD_ITEM 联动）
        from .registry import BUILDING_REGISTRY
        for token in self._added_buildings:
            BUILDING_REGISTRY.unregister(token)
        self._added_buildings.clear()
        for bid in self._added_building_items:
            C.BUILD_ITEM.pop(bid, None)
        self._added_building_items.clear()


# ---------- 内部工具 ----------

def _json_dump(obj) -> str:
    """容错 JSON dump：tuple → list，非基础类型 → str，避免 save_config 炸。"""
    def conv(o):
        if isinstance(o, tuple):
            return [conv(x) for x in o]
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, set)):
            return [conv(x) for x in o]
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        return str(o)
    return json.dumps(conv(obj), ensure_ascii=False, indent=2)


def _resolve(path: str):
    """点分路径 → 对象（类/模块属性）。只 import 模块部分。"""
    mod_path, _, attr = path.rpartition(".")
    if not mod_path:
        raise ModAPIError(f"mixin target 缺模块路径: {path!r}")
    try:
        obj = __import__(mod_path, fromlist=[attr.split(".")[0]])
    except ImportError as e:
        raise ModAPIError(f"mixin target 无法 import: {path}（{e}）") from None
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def _hex(color: str):
    """#RRGGBB / #RRGGBBAA → (r,g,b[,a])。"""
    s = color.lstrip("#")
    if len(s) not in (6, 8):
        raise ModAPIError(f"颜色必须是 #RRGGBB[AA]，收到 {color!r}")
    try:
        v = tuple(int(s[i:i+2], 16) for i in range(0, len(s), 2))
    except ValueError:
        raise ModAPIError(f"颜色解析失败: {color!r}") from None
    return v


# ---------- 加载/卸载入口（供 mod 加载器 / 调试用） ----------
import importlib.util  # noqa: E402
import json           # noqa: E402
from pathlib import Path  # noqa: E402


def load_main_module(name: str, main_path: Path):
    """从文件路径加载 mod 的 main.py（包名隔离：mod_<name>_main）。

    M12：缓存按"名字 + 文件路径"双键——同名 mod 换目录（如单文件包缓存
    目录 vs 普通目录）会重新加载，避免跨目录串包；同路径重复加载沿用旧
    行为（复用模块再跑一遍 on_load）。
    """
    mname = f"mod_{name}_main"
    existing = sys.modules.get(mname)
    if existing is not None:
        if getattr(existing, "__file__", None) == str(main_path):
            return existing
        sys.modules.pop(mname, None)   # 换路径了 → 换新模块
    spec = importlib.util.spec_from_file_location(mname, main_path)
    if spec is None or spec.loader is None:
        raise ModAPIError(f"{name}: main.py 无法作为模块加载")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mname] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        # 失败必须清掉半成品，否则二次加载会命中缓存误判成功
        sys.modules.pop(mname, None)
        raise
    return mod