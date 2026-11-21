"""配方数据（M6.28 + M7）：内置配方在 data/recipes.json，
import config 时加载一次，格式与运行期一致：

    C.RECIPES[rid] = (输入 dict[int,int], 输出 dict[int,int], 耗时秒, machines 元组)

machines = 能造该配方的建筑 id 元组（空 = 只能手搓）。
JSON 存成 {"inputs": {"命名空间:物品名": 数量}, "outputs": ..., "dur": 秒,
"machines": ["命名空间:建筑名"]}——M7 起物品/建筑用 **名字**（stellarloom:
前缀，MC 风格注册表）；数字 id 与数字字符串仍兼容读取（老文件/老 mod）。
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent
RECIPES_JSON = DATA_DIR / "recipes.json"


# M8：建筑也从注册表解析（原版固定段 + mod 动态段，数字仍兼容）
def _resolve_building(key) -> int:
    """建筑 id：名字（stellarloom:belt / mymod:foundry）或数字/数字字符串。"""
    from ..registry import BUILDING_REGISTRY
    try:
        return BUILDING_REGISTRY.id_of(key)
    except Exception as e:
        raise ValueError(f"配方引用了未注册建筑 {key!r}（{e}）") from None


def _resolve_item(key) -> int:
    """物品 id：名字（stellarloom:iron_ore）或数字/数字字符串（兼容旧文件）。"""
    from ..registry import ITEM_REGISTRY
    try:
        return ITEM_REGISTRY.id_of(key)
    except Exception as e:
        raise ValueError(f"配方引用了未注册物品 {key!r}（{e}）") from None


def _resolve_fluid(key) -> int:
    """液体 id（M14）：名字（stellarloom:crude_oil）或数字。"""
    from ..registry import FLUID_REGISTRY
    try:
        return FLUID_REGISTRY.id_of(key)
    except Exception as e:
        raise ValueError(f"配方引用了未注册液体 {key!r}（{e}）") from None


def _load_raw() -> dict:
    try:
        raw = json.loads(RECIPES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"配方文件 recipes.json 解析失败: {e}") from None
    if not isinstance(raw, dict):
        raise ValueError("recipes.json 顶层必须是 dict")
    return raw


def load_recipes() -> dict:
    """读取 recipes.json，返回与旧版一模一样的配方 dict。

    坏 JSON / 缺字段 / 数量非法 / 引用未注册物品或建筑 → ValueError
    启动即报（与 UI defs 同铁律，不静默）。machines 可省略（[] = 只能手搓）。

    M14：允许"纯液体配方"（inputs/outputs 空，只有 fluid_inputs/fluid_outputs），
    液体部分另由 load_recipe_fluids() 读（不塞进 4 元组，避免破坏解包）。
    """
    raw = _load_raw()
    out: dict = {}
    for rid, r in raw.items():
        if not isinstance(r, dict):
            raise ValueError(f"配方 {rid}: 必须是对象")
        try:
            ins = {_resolve_item(k): int(v)
                   for k, v in (r.get("inputs") or {}).items()}
            outs = {_resolve_item(k): int(v)
                    for k, v in (r.get("outputs") or {}).items()}
            dur = float(r["dur"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"配方 {rid}: inputs/outputs/dur 非法（{e}）") from None
        has_fluid = bool(r.get("fluid_inputs") or r.get("fluid_outputs"))
        if (not ins or not outs) and not has_fluid:
            raise ValueError(
                f"配方 {rid}: inputs/outputs 不能空（除非是纯液体配方）")
        if dur <= 0:
            raise ValueError(f"配方 {rid}: dur 必须 > 0")
        machines = tuple(_resolve_building(m) for m in r.get("machines", []))
        out[rid] = (ins, outs, dur, machines)
    return out


def load_recipe_fluids() -> dict:
    """读取 recipes.json 的液体部分（M14）：rid -> (输入液体, 输出液体)。

    与 RECIPES 分离存放，所以 26 条既有配方的 4 元组解包完全不受影响。
    """
    raw = _load_raw()
    out: dict = {}
    for rid, r in raw.items():
        if not isinstance(r, dict):
            continue
        fin_raw = r.get("fluid_inputs") or {}
        fout_raw = r.get("fluid_outputs") or {}
        if not fin_raw and not fout_raw:
            continue
        try:
            fin = {_resolve_fluid(k): float(v) for k, v in fin_raw.items()}
            fout = {_resolve_fluid(k): float(v) for k, v in fout_raw.items()}
        except (TypeError, ValueError) as e:
            raise ValueError(f"配方 {rid}: 液体字段非法（{e}）") from None
        out[rid] = (fin, fout)
    return out