"""科研站网络：双模式（M6.11）。

每台科研站有一个 dict 状态，两种模式：

- research（研究模式，默认）：只输入，不吃原料、不产出。分拣器往里喂当前
  科技需要的科研包（蓝/红），每 LAB_CONSUME_INTERVAL 秒消耗一个，给当前
  研究项推进 1 点。多台科研站统一推进同一个当前研究项。
- produce（制造模式）：制造矩阵。玩家选一种矩阵配方（science_blue/red），
  分拣器喂原料、取产物；也可以手动在面板里存取。所有矩阵只能由科研站制造。

lab dict 的键：
    x, y          坐标
    mode          C.LAB_MODE_RESEARCH / C.LAB_MODE_PRODUCE
    timer         research 模式的消耗计时
    stored        research 模式囤的科研包 {item: n}
    recipe        produce 模式选的配方 id（None = 未选，拒收）
    inputs        produce 模式原料 {item: n}
    outputs       produce 模式产物 {item: n}
    progress      produce 模式生产进度（秒）
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class LabNetwork:
    def __init__(self, grid):
        self.grid = grid
        # (x, y) -> lab dict（见模块 docstring）
        self.labs: dict[tuple[int, int], dict] = {}
        self._tech = None  # 由 game 注入 TechTree

    def bind(self, tech):
        self._tech = tech

    def _new_lab(self, x: int, y: int) -> dict:
        return {
            "x": x, "y": y,
            "mode": C.LAB_MODE_RESEARCH,
            "timer": 0.0,
            "stored": {},
            "recipe": None,
            "inputs": {},
            "outputs": {},
            "progress": 0.0,
        }

    def sync(self):
        g = self.grid
        ys, xs = np.nonzero(g.building == C.B_LAB)
        wanted = set()
        for y, x in zip(ys.tolist(), xs.tolist()):
            wanted.add((x, y))
            if (x, y) not in self.labs:
                self.labs[(x, y)] = self._new_lab(x, y)
        dead = [k for k in self.labs if k not in wanted]
        for k in dead:
            del self.labs[k]

    def get_lab(self, x: int, y: int):
        return self.labs.get((x % self.grid.w, y % self.grid.h))

    def count(self) -> int:
        return len(self.labs)

    # ---------- 制造模式内部辅助 ----------

    def _produce_need(self, lab: dict) -> dict[int, int]:
        rid = lab.get("recipe")
        if not rid or rid not in C.RECIPES:
            return {}
        return C.RECIPES[rid][0]

    # ---------- 分拣器接口 ----------

    def feed(self, x: int, y: int, item: int) -> bool:
        """分拣器喂料。按模式分派。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return False
        if lab["mode"] == C.LAB_MODE_PRODUCE:
            need = self._produce_need(lab)
            if item not in need:
                return False
            if lab["inputs"].get(item, 0) >= C.LAB_PRODUCE_INPUT_CAP:
                return False
            lab["inputs"][item] = lab["inputs"].get(item, 0) + 1
            return True
        # research 模式：只收当前科技需要的科研包
        if item not in self._wanted_packs():
            return False
        have = lab["stored"].get(item, 0)
        if have >= C.LAB_STORE_CAP:
            return False
        lab["stored"][item] = have + 1
        return True

    def acceptable(self, x: int, y: int):
        """目标科研站能收哪些物品（分拣器用）。None = 没有科研站。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return None
        if lab["mode"] == C.LAB_MODE_PRODUCE:
            need = self._produce_need(lab)
            if not need:
                return set()
            return {i for i in need
                    if lab["inputs"].get(i, 0) < C.LAB_PRODUCE_INPUT_CAP}
        out = set()
        for p in self._wanted_packs():
            if lab["stored"].get(p, 0) < C.LAB_STORE_CAP:
                out.add(p)
        return out

    def grab(self, x: int, y: int, acceptable: set[int], flt: int = 0):
        """分拣器从科研站抓产物（制造模式）。返回 (物品, lab dict) 或 (None,None)。"""
        lab = self.get_lab(x, y)
        if lab is None or lab["mode"] != C.LAB_MODE_PRODUCE:
            return None, None
        any_ok = -1 in acceptable
        for item, n in list(lab["outputs"].items()):
            if n <= 0:
                continue
            if flt > 0 and item != flt:
                continue
            if any_ok or item in acceptable:
                if n == 1:
                    del lab["outputs"][item]
                else:
                    lab["outputs"][item] = n - 1
                return item, lab
        return None, None

    def put_back(self, x: int, y: int, item: int):
        """分拣器投递失败把产物放回科研站。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return
        lab["outputs"][item] = lab["outputs"].get(item, 0) + 1

    def _wanted_packs(self) -> set[int]:
        """当前科技要吃哪种科研包。

        没在研究时返回**所有**科研包种类（蓝+红），让玩家先把包囤进科研站，
        不然研究红科技时还得先等分拣器现搬。
        """
        if self._tech is not None and self._tech.current is not None:
            rid = C.TECH_PACK_RECIPE.get(self._tech.current)
            r = C.RECIPES.get(rid) if rid else None
            if r is not None:
                return set(r[1])
        return set(C.TECH_PACK_ITEM.values())

    def total_stored(self, x: int, y: int) -> int:
        lab = self.get_lab(x, y)
        return 0 if lab is None else sum(lab["stored"].values())

    # ---------- 面板用：切换模式 / 选配方 / 存取 ----------

    def set_mode(self, x: int, y: int, mode: str):
        lab = self.get_lab(x, y)
        if lab is None or mode not in (C.LAB_MODE_RESEARCH, C.LAB_MODE_PRODUCE):
            return
        if lab["mode"] == mode:
            return
        lab["mode"] = mode
        lab["timer"] = 0.0
        lab["progress"] = 0.0

    def set_recipe(self, x: int, y: int, rid: str | None):
        lab = self.get_lab(x, y)
        if lab is None or lab["mode"] != C.LAB_MODE_PRODUCE:
            return
        if rid not in C.LAB_PRODUCE_RECIPES:
            rid = None
        if rid == lab["recipe"]:
            return
        lab["recipe"] = rid
        # 切换配方：只保留新配方还需要的原料
        need = C.RECIPES[rid][0] if rid else {}
        lab["inputs"] = {k: v for k, v in lab["inputs"].items()
                         if k in need and v > 0}
        lab["progress"] = 0.0

    def add_item(self, x: int, y: int, item: int, count: int) -> int:
        """面板手动放入物品，返回实际放入数量。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return 0
        if lab["mode"] == C.LAB_MODE_PRODUCE:
            if item not in self._produce_need(lab):
                return 0
            have = lab["inputs"].get(item, 0)
            n = min(count, C.LAB_PRODUCE_INPUT_CAP - have)
            if n > 0:
                lab["inputs"][item] = have + n
            return n
        if item not in self._wanted_packs():
            return 0
        have = lab["stored"].get(item, 0)
        n = min(count, C.LAB_STORE_CAP - have)
        if n > 0:
            lab["stored"][item] = have + n
        return n

    def take_item(self, x: int, y: int, item: int, count: int | None = None) -> int:
        """面板手动取出物品（研究模式取科研包 / 制造模式取原料）。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return 0
        d = lab["inputs"] if lab["mode"] == C.LAB_MODE_PRODUCE else lab["stored"]
        have = d.get(item, 0)
        if have <= 0:
            return 0
        n = have if count is None else min(have, count)
        left = have - n
        if left > 0:
            d[item] = left
        else:
            d.pop(item, None)
        return n

    def take_outputs(self, x: int, y: int) -> dict[int, int]:
        """取空制造模式的产物。"""
        lab = self.get_lab(x, y)
        if lab is None:
            return {}
        out = {k: v for k, v in lab["outputs"].items() if v > 0}
        lab["outputs"].clear()
        return out

    # ---------- 更新 ----------

    def update(self, dt: float, power):
        """power 可以是全局倍率，也可以是 PowerGrid（按科研站所在电网取比例）。"""
        def _f(lab) -> float:
            if isinstance(power, (int, float)):
                return float(power)
            return power.factor_at(lab["x"], lab["y"])

        # 研究模式：吃包推进当前科技
        if self._tech is not None and self._tech.current is not None:
            wanted = self._wanted_packs()
            for lab in self.labs.values():
                if lab["mode"] != C.LAB_MODE_RESEARCH:
                    continue
                pack = next((p for p in wanted if lab["stored"].get(p, 0) > 0), None)
                if pack is None:
                    lab["timer"] = 0.0
                    continue
                lab["timer"] += dt * _f(lab)
                if lab["timer"] < C.LAB_CONSUME_INTERVAL:
                    continue
                lab["timer"] -= C.LAB_CONSUME_INTERVAL
                left = lab["stored"].get(pack, 0) - 1
                if left > 0:
                    lab["stored"][pack] = left
                else:
                    lab["stored"].pop(pack, None)
                self._tech.add_pack_progress(1)
        # 制造模式：跑配方
        for lab in self.labs.values():
            if lab["mode"] == C.LAB_MODE_PRODUCE:
                self._produce_update(lab, dt, _f(lab))

    def _produce_update(self, lab: dict, dt: float, speed_factor: float):
        rid = lab.get("recipe")
        if not rid or rid not in C.RECIPES:
            lab["progress"] = 0.0
            return
        ins, outs, duration, _ = C.RECIPES[rid]
        # 原料齐没齐
        for it, n in ins.items():
            if lab["inputs"].get(it, 0) < n:
                lab["progress"] = 0.0
                return
        # 产物空间够不够（满了就停工，不吞材料）
        for o, on in outs.items():
            if C.LAB_PRODUCE_OUTPUT_CAP - lab["outputs"].get(o, 0) < on:
                lab["progress"] = 0.0
                return
        lab["progress"] += dt * speed_factor
        if lab["progress"] >= duration:
            for it, n in ins.items():
                left = lab["inputs"].get(it, 0) - n
                if left > 0:
                    lab["inputs"][it] = left
                else:
                    lab["inputs"].pop(it, None)
            for o, on in outs.items():
                lab["outputs"][o] = lab["outputs"].get(o, 0) + on
            lab["progress"] = 0.0