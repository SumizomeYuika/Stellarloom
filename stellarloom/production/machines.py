"""机器：熔炉、制造台。按配方加工。

设计（v2）：
- 配方默认未设置，必须玩家在面板里选；未设置配方时不吸收任何物品
- 内置储存：原料槽 + 产物槽，都是 dict[item_id, count]，每格有上限
- 只吸收当前配方需要的原料，多余物品拒收（分拣器自动堵住）
- 产物槽没空间时停止生产，不会吞掉材料
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class Machine:
    __slots__ = ("x", "y", "btype", "recipe_id", "inputs", "outputs",
                 "progress", "need")

    def __init__(self, x: int, y: int, btype: int):
        self.x = x
        self.y = y
        self.btype = btype
        # 配方默认不设：机器是空壳，必须玩家在面板里指定，否则不收任何东西
        self.recipe_id: str | None = None
        self.inputs: dict[int, int] = {}
        self.outputs: dict[int, int] = {}   # 内置产物储存
        self.progress = 0.0
        self._set_need()

    # ---------- 配方 ----------

    def _set_need(self):
        if self.recipe_id and self.recipe_id in C.RECIPES:
            ins, _, _, _ = C.RECIPES[self.recipe_id]
            # 输入现在是 dict，直接用
            self.need = dict(ins)
        else:
            self.need = {}

    def set_recipe(self, recipe_id: str | None):
        """切换配方。换配方时把不再需要的原料退回（丢弃，简单处理）。"""
        if recipe_id == self.recipe_id:
            return
        self.recipe_id = recipe_id
        self._set_need()
        # 只保留新配方还需要的原料
        self.inputs = {k: v for k, v in self.inputs.items()
                       if k in self.need and v > 0}
        self.progress = 0.0

    def available_recipes(self, researched: set[str] | None = None) -> list[str]:
        """这台机器能选的配方 id 列表（按 allows 过滤，空元组=只能手搓）。"""
        out = []
        for rid, (_, _, _, allows) in C.RECIPES.items():
            if not allows or self.btype not in allows:
                continue
            req = C.RECIPE_TECH.get(rid)
            if req and researched is not None and req not in researched:
                continue
            out.append(rid)
        return out

    # ---------- 原料 / 产物 ----------

    def input_space(self, item: int) -> int:
        """还能收几个这种原料。0 = 满。

        机器只收当前配方要的原料——手动放入也走这条规则，
        否则面板能往熔炉里塞齿轮，生产逻辑就乱了。
        """
        if item not in self.need:
            return 0
        return C.MACHINE_INPUT_CAP - self.inputs.get(item, 0)

    def feed(self, item: int) -> bool:
        """分拣器喂料。未设配方或不是配方原料 → 拒收。"""
        if self.input_space(item) <= 0:
            return False
        self.inputs[item] = self.inputs.get(item, 0) + 1
        return True

    # ---------- 手动存取（面板用） ----------

    def add_input(self, item: int, count: int) -> int:
        """手动放入原料，返回实际放入数量。"""
        n = min(count, self.input_space(item))
        if n > 0:
            self.inputs[item] = self.inputs.get(item, 0) + n
        return n

    def take_input(self, item: int, count: int | None = None) -> int:
        """手动取出原料。count=None 全取。返回实际取出数量。"""
        have = self.inputs.get(item, 0)
        if have <= 0:
            return 0
        n = have if count is None else min(have, count)
        left = have - n
        if left > 0:
            self.inputs[item] = left
        else:
            self.inputs.pop(item, None)
        return n

    def take_all_outputs(self) -> dict[int, int]:
        """产物格只能整体取空：返回 {物品: 数量}，并清空产物格。

        不提供单个取出的手动接口——产物格是给分拣器用的，
        玩家手动取就一次拿干净，省得点几十下。
        """
        out = {k: v for k, v in self.outputs.items() if v > 0}
        self.outputs.clear()
        return out

    def output_space(self, item: int) -> int:
        return C.MACHINE_OUTPUT_CAP - self.outputs.get(item, 0)

    def total_output(self) -> int:
        return sum(self.outputs.values())

    def take_output(self, item: int | None = None) -> int | None:
        """取一个产物（分拣器用）。传 item 只取指定种类。"""
        if item is not None:
            n = self.outputs.get(item, 0)
            if n <= 0:
                return None
            if n == 1:
                del self.outputs[item]
            else:
                self.outputs[item] = n - 1
            return item
        for it, n in self.outputs.items():
            if n > 0:
                if n == 1:
                    del self.outputs[it]
                else:
                    self.outputs[it] = n - 1
                return it
        return None

    def peek_output(self) -> int | None:
        for item, n in self.outputs.items():
            if n > 0:
                return item
        return None

    # ---------- 更新 ----------

    def update(self, dt: float, speed_factor: float):
        if not self.recipe_id or self.recipe_id not in C.RECIPES:
            self.progress = 0.0
            return

        ins, outs, duration, _ = C.RECIPES[self.recipe_id]
        # 材料齐没齐
        for it, n in self.need.items():
            if self.inputs.get(it, 0) < n:
                self.progress = 0.0
                return
        # 产物槽有没有空间（满了就停工，不吞材料）
        for out_item, out_n in outs.items():
            if self.output_space(out_item) < out_n:
                self.progress = 0.0
                return

        self.progress += dt * speed_factor
        if self.progress >= duration:
            for it, n in self.need.items():
                self.inputs[it] -= n
                if self.inputs[it] <= 0:
                    del self.inputs[it]
            for out_item, out_n in outs.items():
                self.outputs[out_item] = self.outputs.get(out_item, 0) + out_n
            self.progress = 0.0


class MachineNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.machines: dict[tuple[int, int], Machine] = {}
        self._dirty = True

    def sync(self):
        """建筑变化后同步：新建缺失的、删除不存在的。"""
        g = self.grid
        wanted: set[tuple[int, int]] = set()
        for btype in (C.B_FURNACE, C.B_ASSEMBLER):
            ys, xs = np.nonzero(g.building == btype)
            for y, x in zip(ys.tolist(), xs.tolist()):
                wanted.add((x, y))
                if (x, y) not in self.machines:
                    self.machines[(x, y)] = Machine(x, y, int(g.building[y, x]))
        # 删除已拆的
        dead = [k for k in self.machines if k not in wanted]
        for k in dead:
            del self.machines[k]

    def get_machine(self, x: int, y: int) -> Machine | None:
        return self.machines.get((x % self.grid.w, y % self.grid.h))

    def update(self, dt: float, power):
        """power 可以是全局倍率，也可以是 PowerGrid（按机器所在电网取比例）。"""
        if isinstance(power, (int, float)):
            for m in self.machines.values():
                m.update(dt, power)
            return
        for m in self.machines.values():
            m.update(dt, power.factor_at(m.x, m.y))

    def count_working(self) -> int:
        return sum(1 for m in self.machines.values() if m.progress > 0)