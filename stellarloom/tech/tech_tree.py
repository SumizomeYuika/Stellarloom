"""科技树：科研包驱动的进度与解锁。

进度不再靠"研究点"二次转换，而是科研站每吃一个科研包就给当前科技 +1。
TECH_TREE 里的数字就是"需要多少个科研包"。
"""

from __future__ import annotations

from .. import config as C


class TechTree:
    def __init__(self):
        self.researched: set[str] = set()   # 已完成的科技 id
        self.current: str | None = None     # 正在研究的科技 id
        self.progress = 0.0                 # 当前科技已吃掉的科研包数
        self.queue: list[str] = []          # 研究队列（M6.11）：current 之后依次自动开研

    def is_unlocked(self, building: int) -> bool:
        tech_id = C.TECH_UNLOCK_BUILDING.get(building)
        if tech_id is None:
            return True
        return tech_id in self.researched

    def can_research(self, tech_id: str) -> tuple[bool, str]:
        """能否立刻开始研究（前置全在 researched 里）。"""
        if tech_id in self.researched:
            return False, "已研究"
        if tech_id not in C.TECH_TREE:
            return False, "不存在"
        _, _, prereqs, _ = C.TECH_TREE[tech_id]
        for p in prereqs:
            if p not in self.researched:
                return False, f"需要先研究 {C.TECH_TREE[p][0]}"
        return True, ""

    def _planned(self) -> set[str]:
        """已经排进计划（current + 队列）的科技，判断前置时算作"将来会完成"。"""
        s = set(self.queue)
        if self.current is not None:
            s.add(self.current)
        return s

    def can_queue(self, tech_id: str) -> tuple[bool, str]:
        """能否开始或排队研究。

        前置只要在 researched、current 或队列里就算满足——排在前面的会先完成。
        """
        if tech_id in self.researched:
            return False, "已研究"
        if tech_id == self.current or tech_id in self.queue:
            return False, "已在计划中"
        if tech_id not in C.TECH_TREE:
            return False, "不存在"
        _, _, prereqs, _ = C.TECH_TREE[tech_id]
        planned = self.researched | self._planned()
        for p in prereqs:
            if p not in planned:
                return False, f"需要先研究 {C.TECH_TREE[p][0]}"
        return True, ""

    def start(self, tech_id: str) -> bool:
        """点科技卡片：没在研就开研，已在研就排进队列。返回是否成功。"""
        ok, _ = self.can_queue(tech_id)
        if not ok:
            return False
        if self.current is None:
            self.current = tech_id
            self.progress = 0.0
        else:
            self.queue.append(tech_id)
        return True

    def add_pack_progress(self, n: int = 1):
        """科研站吃一个科研包 → 当前科技 +1。够数就完成并自动接下一个。"""
        if self.current is None:
            return
        _, cost, _, _ = C.TECH_TREE[self.current]
        self.progress += n
        if self.progress < cost:
            return
        self.researched.add(self.current)
        self.current = None
        self.progress = 0.0
        # 自动从队列里接过下一个能研的
        while self.queue:
            nxt = self.queue.pop(0)
            if nxt in self.researched or nxt not in C.TECH_TREE:
                continue
            self.current = nxt
            self.progress = 0.0
            break

    def manual_research(self, tech_id: str, inventory: dict) -> tuple[bool, str]:
        """手动研究：直接吃背包里的科研包，不需要科研站、不需要电。

        每次调用推进 1 点进度（扣 1 个科研包），够数即完成。
        这是开局唯一的科技推进方式——没电时科研站转不起来。
        """
        if tech_id in self.researched:
            return False, "已研究"
        if tech_id not in C.TECH_TREE:
            return False, "不存在"
        # 前置必须全部完成（不能靠队列跳过，因为这是立刻生效的）
        _, _, prereqs, _ = C.TECH_TREE[tech_id]
        for p in prereqs:
            if p not in self.researched:
                return False, f"需要先研究 {C.TECH_TREE[p][0]}"
        # 多条科技同时手动研究没有意义：同一时刻只允许一条
        if self.current is not None and self.current != tech_id:
            return False, f"正在研究 {C.TECH_TREE[self.current][0]}"
        rid = C.TECH_PACK_RECIPE.get(tech_id)
        if rid is None:
            return False, "该科技没有科研包配方"
        r = C.RECIPES.get(rid)
        if r is None:
            return False, "配方缺失"
        pack_item = next(iter(r[1]), None)
        if pack_item is None:
            return False, "配方没有产物"
        if inventory.get(pack_item, 0) <= 0:
            return False, f"缺少 {C.ITEM_NAMES.get(pack_item, '科研包')}"
        # 扣 1 个包，进度 +1
        left = inventory[pack_item] - 1
        if left > 0:
            inventory[pack_item] = left
        else:
            inventory.pop(pack_item, None)
        if self.current is None:
            self.current = tech_id
            self.progress = 0.0
        _, cost, _, _ = C.TECH_TREE[tech_id]
        self.progress += 1
        if self.progress >= cost:
            self.researched.add(tech_id)
            self.current = None
            self.progress = 0.0
            while self.queue:
                nxt = self.queue.pop(0)
                if nxt in self.researched or nxt not in C.TECH_TREE:
                    continue
                self.current = nxt
                self.progress = 0.0
                break
            return True, "研究完成"
        return True, "进度 +1"

    def queue_count(self) -> int:
        return len(self.queue)

    def cost_of(self, tech_id: str) -> int:
        return C.TECH_TREE[tech_id][1] if tech_id in C.TECH_TREE else 0

    def belt_speed_multiplier(self) -> float:
        m = 1.0
        if "speed1" in self.researched:
            m *= 1.5
        if "speed2" in self.researched:
            m *= 1.5
        return m

    def status_text(self) -> str:
        if self.current is None:
            return "研 空闲"
        name, cost, _, _ = C.TECH_TREE[self.current]
        pct = int(self.progress / cost * 100) if cost else 0
        return f"研 {name} {pct}%"