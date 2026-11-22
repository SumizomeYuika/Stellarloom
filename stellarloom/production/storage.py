"""通用物品暂存容器操作。

所有暂存都是 `dict[item_id, count]`。机器原料槽、产物槽、箱子、矿机暂存、
科研站科研包槽共用这一套语义，免得每处各写一遍、各写错一遍。

两种上限：
- per_cap：每种物品最多囤多少
- total_cap：整个容器最多囤多少（None = 不限）

箱子只用 per_cap；矿机用 total_cap（50 个暂存格，可混装）。
"""

from __future__ import annotations


def total(store: dict[int, int]) -> int:
    return sum(store.values())


def space(store: dict[int, int], item: int, per_cap: int,
          total_cap: int | None = None) -> int:
    """还能放几个这种物品。0 = 放不下。"""
    room = per_cap - store.get(item, 0)
    if total_cap is not None:
        room = min(room, total_cap - total(store))
    return max(room, 0)


def add(store: dict[int, int], item: int, count: int, per_cap: int,
        total_cap: int | None = None) -> int:
    """放入 count 个，返回实际放进去了几个（放不下的丢掉，由调用方决定怎么办）。"""
    n = min(count, space(store, item, per_cap, total_cap))
    if n > 0:
        store[item] = store.get(item, 0) + n
    return n


def take(store: dict[int, int], item: int, count: int | None = None) -> int:
    """取出。count=None 表示全取。返回实际取出数量。"""
    have = store.get(item, 0)
    if have <= 0:
        return 0
    n = have if count is None else min(have, count)
    left = have - n
    if left > 0:
        store[item] = left
    else:
        store.pop(item, None)
    return n
