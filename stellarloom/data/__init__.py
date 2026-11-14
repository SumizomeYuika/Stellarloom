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


def load_recipes() -> dict:
    """读取 recipes.json，返回与旧版一模一样的配方 dict。

    坏 JSON / 缺字段 / 数量非法 / 引用未注册物品或建筑 → ValueError
    启动即报（与 UI defs 同铁律，不静默）。machines 可省略（[] = 只能手搓）。
    """
    try:
        raw = json.loads(RECIPES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"配方文件 recipes.json 解析失败: {e}") from None
    if not isinstance(raw, dict):
        raise ValueError("recipes.json 顶层必须是 dict")
    out: dict = {}
    for rid, r in raw.items():
        if not isinstance(r, dict):
            raise ValueError(f"配方 {rid}: 必须是对象")
        try:
            ins = {_resolve_item(k): int(v) for k, v in r["inputs"].items()}
            outs = {_resolve_item(k): int(v) for k, v in r["outputs"].items()}
            dur = float(r["dur"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"配方 {rid}: inputs/outputs/dur 非法（{e}）") from None
        if not ins or not outs or dur <= 0:
            raise ValueError(f"配方 {rid}: inputs/outputs 不能空，dur 必须 > 0")
        machines = tuple(_resolve_building(m) for m in r.get("machines", []))
        out[rid] = (ins, outs, dur, machines)
    return out