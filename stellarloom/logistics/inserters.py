"""分拣器：从传送带/机器抓物品，放到传送带/机器。

抓取规则（M1 简化）：
- 朝向 = 目标方向（把物品往前送）
- 源 = 背后一格（反方向）
- 1 秒抓 1 次，一次最多 1 个
- 从传送带抓：取 lane 上路过本格的物品
- 从机器抓：取机器输出槽
"""

from __future__ import annotations

import numpy as np

from .. import config as C


class InserterNetwork:
    def __init__(self, grid, belts):
        self.grid = grid
        self.belts = belts
        self.labs = None  # 由 game 注入 LabNetwork
        self.chests = None  # 由 game 注入 ChestNetwork
        self.miners = None  # 由 game 注入 MinerNetwork
        self.dyson = None  # 由 game 注入 DysonNetwork（M4）
        # (x, y) -> 冷却剩余秒
        self.cooldowns: dict[tuple[int, int], float] = {}
        # M10 三段机械臂动画（纯视觉）：剩余动画秒 / 手上物品 id
        self.anim: dict[tuple[int, int], float] = {}
        self.carry: dict[tuple[int, int], int] = {}
        # 分拣器坐标集合的惰性缓存：grid.overlay_gen 变化（放/拆）时重建。
        # 之前每帧 np.nonzero 全图扫 26 万格，改成代数过期判定，谁用都正确。
        self._cells: set[tuple[int, int]] | None = None
        self._cells_gen: int = -1

    def invalidate(self):
        """强制下一次 cells 访问重扫（读档后用）。"""
        self._cells = None

    @property
    def cells(self) -> set[tuple[int, int]]:
        """当前分拣器坐标集合（惰性重建，grid 代数变化自动失效）。"""
        g = self.grid
        if self._cells is None or g.overlay_gen != self._cells_gen:
            ys, xs = np.nonzero(g.overlay == C.B_INSERTER)
            self._cells = {(int(x), int(y))
                           for y, x in zip(ys.tolist(), xs.tolist())}
            self._cells_gen = g.overlay_gen
            # 拆掉的分拣器清掉动画/手上物品
            for k in [k for k in self.anim if k not in self._cells]:
                self.anim.pop(k, None)
                self.carry.pop(k, None)
        return self._cells

    def update(self, dt: float, machines):
        g = self.grid
        # 动画衰减（纯视觉，不影响抓取逻辑）
        for key in list(self.anim):
            left = self.anim[key] - dt
            if left <= 0.0:
                self.anim.pop(key, None)
                self.carry.pop(key, None)
            else:
                self.anim[key] = left
        for x, y in self.cells:
            key = (x, y)
            cd = self.cooldowns.get(key, 0.0)
            if cd > 0:
                self.cooldowns[key] = cd - dt
                continue

            d = int(g.overlay_dir[y, x])
            # 过滤：0 = 不限，其余只抓这一种物品
            flt = int(g.overlay_filter[y, x])
            # 目标 = 前方
            tx, ty = g.wrap(x + C.DX[d], y + C.DY[d])
            # 源 = 后方
            sx, sy = g.wrap(x - C.DX[d], y - C.DY[d])

            # 先看目标能收什么，再去源抓——目标满了就不抓，不堵住
            acceptable = self._acceptable_items(tx, ty, machines)
            if not acceptable:
                continue
            # 过滤和目标需求取交集：目标不收的、过滤不要的都不抓
            if flt > 0:
                if -1 not in acceptable:
                    acceptable = acceptable & {flt}
                if not acceptable:
                    continue

            item, from_machine = self._grab(sx, sy, machines, acceptable, flt)
            if item is None:
                continue

            if self._deliver(tx, ty, item, machines):
                self.cooldowns[key] = C.INSERTER_COOLDOWN
                # 去程(带物品) + 回程(空手)，纯视觉
                self.anim[key] = C.INSERTER_SWING_TIME * 2.0
                self.carry[key] = item
            else:
                # 抓取和投递之间状态变了（如目标带子刚好被塞满），
                # 物品必须退回原处，否则直接消失。
                self._put_back(sx, sy, item, from_machine, machines)

    def _put_back(self, x: int, y: int, item: int, from_machine, machines):
        """把抓出来又投不回去的物品放回来源，避免凭空消失。

        来源可能是机器、箱子、采矿机暂存或传送带，必须一一对应放回去。
        """
        # 科研站（制造模式）：产物来自 lab dict，放回它的 outputs
        if isinstance(from_machine, dict):
            if self.labs is not None:
                self.labs.put_back(x, y, item)
            return
        # 传送带：按原位置放回（刚取出的槽位一定空的，不做间距检查）
        if isinstance(from_machine, tuple) and from_machine[0] == "belt":
            if self.belts.insert_at(from_machine[1], from_machine[2], item):
                return
            if self.belts.try_insert(x, y, item):
                return
            from_machine = None  # 实在放不回就落到下面的兜底
        if from_machine is not None:
            # 机器 / 箱子 / 采矿机都实现了 add_item，语义一致
            if hasattr(from_machine, "add_item"):
                if from_machine.add_item(item, 1) > 0:
                    return
                # 放不回去说明来源也满了（例如箱子被塞满），
                # 那只能退回最近的机器，别让物品消失
            else:
                from_machine.outputs[item] = from_machine.outputs.get(item, 0) + 1
                return
        if self.belts.try_insert(x, y, item):
            return
        # 源带子也满了（极罕见）：退回源格的机器产物槽，最后才认栽
        m = machines.get_machine(x, y)
        if m is not None:
            m.outputs[item] = m.outputs.get(item, 0) + 1

    def _deliver(self, x: int, y: int, item: int, machines) -> bool:
        # 优先给机器
        m = machines.get_machine(x, y)
        if m is not None:
            return m.feed(item)
        # 箱子
        if self.chests is not None:
            chest = self.chests.get(x, y)
            if chest is not None:
                return chest.feed(item)
        # 采矿机暂存
        if self.miners is not None:
            mn = self.miners.get(x, y)
            if mn is not None:
                return mn.add_item(item, 1) > 0
        # 再给科研站
        if self.labs is not None and self.labs.feed(x, y, item):
            return True
        # 太阳帆发射器（M4）
        if self.dyson is not None:
            em = self.dyson.get(x, y)
            if em is not None and em.feed(item):
                return True
        # 再放上传送带
        return self.belts.try_insert(x, y, item)

    def _acceptable_items(self, x: int, y: int, machines) -> set[int] | None:
        """目标格能收哪些物品。返回 None 表示什么都收不了，空 set 表示暂时满。"""
        m = machines.get_machine(x, y)
        if m is not None:
            # 机器：未设配方 → need 为空 → 返回空集，分拣器堵住不抓
            out = set()
            for item in m.need:
                if m.input_space(item) > 0:
                    out.add(item)
            return out
        # 箱子：什么都收，只要那种还没满
        if self.chests is not None:
            chest = self.chests.get(x, y)
            if chest is not None:
                return {i for i in C.ITEM_COLORS if chest.space(i) > 0}
        # 科研站：按模式返回能收的物品（研究=科研包，制造=原料）
        if self.labs is not None:
            acc = self.labs.acceptable(x, y)
            if acc is not None:
                return acc
        # 采矿机：只收矿石（暂存是混装的矿）
        if self.miners is not None:
            mn = self.miners.get(x, y)
            if mn is not None:
                return {i for i in C.ORE_TO_ITEM.values() if mn.space(i) > 0}
        # 太阳帆发射器：只收太阳帆
        if self.dyson is not None:
            em = self.dyson.get(x, y)
            if em is not None:
                if em.space(C.I_SOLAR_SAIL) > 0:
                    return {C.I_SOLAR_SAIL}
                return set()
        # 传送带：必须真的有空位才收，否则塞不进去会每帧抓了又放不回
        if self.belts.has_space(x, y):
            return {-1}  # 非空占位，表示可以塞任意物品
        return set()

    def _grab(self, x: int, y: int, machines, acceptable: set[int],
              flt: int = 0):
        """抓物品。返回 (物品ID, 来源容器或None)，抓不到返回 (None, None)。

        来源容器回传给 _put_back，保证投递失败时物品能放回原处。
        """
        # 优先从机器拿内置产物槽
        m = machines.get_machine(x, y)
        if m is not None:
            any_ok = -1 in acceptable
            for item, n in list(m.outputs.items()):
                if n <= 0:
                    continue
                if flt > 0 and item != flt:
                    continue  # 过滤只要这一种
                if any_ok or item in acceptable:
                    got = m.take_output(item)
                    if got is not None:
                        return got, m
            return None, None
        # 箱子：按目标需求挑货，不能只看"第一个有货的"
        if self.chests is not None:
            chest = self.chests.get(x, y)
            if chest is not None:
                for item, n in list(chest.store.items()):
                    if n <= 0:
                        continue
                    if flt > 0 and item != flt:
                        continue
                    if -1 in acceptable or item in acceptable:
                        if chest.take_one(item):
                            return item, chest
                return None, None
        # 采矿机暂存
        if self.miners is not None:
            mn = self.miners.get(x, y)
            if mn is not None:
                for item, n in list(mn.buffer.items()):
                    if n <= 0:
                        continue
                    if flt > 0 and item != flt:
                        continue
                    if -1 in acceptable or item in acceptable:
                        if mn.take_item(item, 1) > 0:
                            return item, mn
                return None, None
        # 科研站（制造模式）产物
        if self.labs is not None:
            lab = self.labs.get_lab(x, y)
            if lab is not None:
                got, obj = self.labs.grab(x, y, acceptable, flt)
                if got is not None:
                    return got, obj
                return None, None
        # 再从传送带拿（只拿 acceptable 里的物品）
        item, slot = self._grab_from_belt(x, y, acceptable, flt)
        return item, slot

    def _grab_from_belt(self, x: int, y: int, acceptable: set[int],
                        flt: int = 0):
        """从传送带抓一个物品。返回 (物品ID, ('belt', lane_idx, pos))，抓不到 (None, None)。"""
        idx = self.belts.cell_lane.get((x, y))
        if idx is None:
            return None, None
        lane = self.belts.lanes[idx]
        ci = lane.cell_index((x, y))
        if ci < 0 or not len(lane.positions):
            return None, None
        any_ok = -1 in acceptable
        # 找落在本格内（[ci, ci+1)）的物品，取最下游的
        for i in range(len(lane.positions) - 1, -1, -1):
            p = lane.positions[i]
            if ci <= p < ci + 1:
                item = int(lane.items[i])
                if flt > 0 and item != flt:
                    continue  # 过滤只要这一种，别的放过让下游去抓
                if not any_ok and item not in acceptable:
                    continue  # 目标不要这个，跳过
                pos = float(p)
                lane.positions = np.delete(lane.positions, i)
                lane.items = np.delete(lane.items, i)
                return item, ("belt", idx, pos)
        return None, None