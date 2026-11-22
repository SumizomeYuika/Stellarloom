"""无人机：独立飞行实体，有位置、电量、载货量、状态机。

状态机：
  idle      → 停在塔上，等待任务
  pickup    → 飞向供应塔取货
  deliver   → 飞向请求塔送货
  return    → 飞回母塔
  charging  → 在塔上充电

电量：飞行按格耗电，耗尽则原地迫降（M2 简化为自动低速滑回母塔）。
"""

from __future__ import annotations

import math

from .. import config as C

# 状态
S_IDLE = 0
S_PICKUP = 1
S_DELIVER = 2
S_RETURN = 3
S_CHARGING = 4


class Drone:
    __slots__ = ("x", "y", "energy", "cargo", "state", "home",
                 "target_tower", "deliver_tower", "task_item", "task_count",
                 "wait")

    def __init__(self, home_tower):
        self.x = float(home_tower.x)
        self.y = float(home_tower.y)
        self.energy = C.DRONE_MAX_ENERGY
        self.cargo: int | None = None
        self.state = S_IDLE
        self.home = home_tower          # 母塔引用
        self.target_tower = None        # 取货的供应塔
        self.deliver_tower = None       # 送货的请求塔
        self.task_item: int | None = None
        self.task_count = 0
        self.wait = 0.0                 # 请求塔满时原地等待的累计秒数

    @property
    def busy(self) -> bool:
        return self.state not in (S_IDLE, S_CHARGING)

    @property
    def energy_ratio(self) -> float:
        return self.energy / C.DRONE_MAX_ENERGY

    def assign_pickup(self, source_tower, item: int, count: int):
        """派去供应塔取货。"""
        self.target_tower = source_tower
        self.task_item = item
        self.task_count = min(count, C.DRONE_CAPACITY)
        self.state = S_PICKUP
        self.wait = 0.0

    def update(self, dt: float, grid) -> None:
        if self.state == S_IDLE or self.state == S_CHARGING:
            self._charge(dt)
            return

        if self.state == S_PICKUP:
            t = self.target_tower
            if t is None:
                self.state = S_RETURN
                return
            self._fly_to(t.x, t.y, dt, grid)
            if self._at(t.x, t.y):
                got = t.remove_item(self.task_item, self.task_count)
                if got > 0:
                    self.cargo = self.task_item
                    self.task_count = got
                    self.state = S_DELIVER
                else:
                    # 供应塔没货了，回家
                    self.state = S_RETURN

        elif self.state == S_DELIVER:
            t = self.deliver_tower
            if t is None:
                self.state = S_RETURN
                return
            self._fly_to(t.x, t.y, dt, grid)
            if self._at(t.x, t.y):
                if self.cargo is not None:
                    leftover = t.add_item(self.cargo, self.task_count)
                    if leftover > 0:
                        # 请求塔满：剩下的货**不能丢**。留在塔旁等空间，
                        # 等太久（DRONE_WAIT_TIMEOUT）就带货回母塔卸。
                        self.task_count = leftover
                        self.wait += dt
                        if self.wait < C.DRONE_WAIT_TIMEOUT:
                            return
                        self.state = S_RETURN
                        return
                    self.cargo = None
                    self.task_count = 0
                self.wait = 0.0
                self.state = S_RETURN

        elif self.state == S_RETURN:
            self._fly_to(self.home.x, self.home.y, dt, grid)
            if self._at(self.home.x, self.home.y):
                if self.cargo is not None:
                    # 带货回家：能卸就卸；母塔也满就留在塔上边充电边等
                    leftover = self.home.add_item(self.cargo, self.task_count)
                    if leftover > 0:
                        self.task_count = leftover
                        self._charge(dt)
                        return
                    self.cargo = None
                    self.task_count = 0
                self.wait = 0.0
                self.state = S_CHARGING

    def _fly_to(self, tx: float, ty: float, dt: float, grid):
        """朝目标飞，支持环形卷绕最短路径。"""
        dx = tx - self.x
        dy = ty - self.y
        # 环形卷绕：取最短方向
        if abs(dx) > grid.w / 2:
            dx -= grid.w * (1 if dx > 0 else -1)
        if abs(dy) > grid.h / 2:
            dy -= grid.h * (1 if dy > 0 else -1)

        dist = math.hypot(dx, dy)
        if dist < 0.05:
            return

        # 电量不足时减速
        speed = C.DRONE_SPEED * (0.3 if self.energy < 10 else 1.0)
        step = min(speed * dt, dist)
        self.x += dx / dist * step
        self.y += dy / dist * step

        # 耗电
        self.energy -= step * C.DRONE_ENERGY_PER_CELL
        if self.energy < 0:
            self.energy = 0

        # 保持在世界内
        self.x %= grid.w
        self.y %= grid.h

    def _at(self, tx: float, ty: float) -> bool:
        """是否到达目标附近（考虑卷绕）。"""
        dx = abs(tx - self.x)
        dy = abs(ty - self.y)
        return dx < 0.5 and dy < 0.5

    def _charge(self, dt: float):
        if self.energy < C.DRONE_MAX_ENERGY:
            self.energy = min(C.DRONE_MAX_ENERGY,
                              self.energy + C.DRONE_CHARGE_RATE * dt)
            if self.energy >= C.DRONE_MAX_ENERGY:
                self.state = S_IDLE


class DroneNetwork:
    def __init__(self, grid):
        self.grid = grid
        self.drones: list[Drone] = []

    def spawn_for_tower(self, tower):
        """塔建好时为它生成无人机。"""
        for _ in range(C.DRONES_PER_TOWER):
            self.drones.append(Drone(tower))

    def remove_for_tower(self, tower):
        """塔被拆时删掉它的无人机。"""
        self.drones = [d for d in self.drones if d.home is not tower]

    def update(self, dt: float):
        for d in self.drones:
            d.update(dt, self.grid)

    def _wdist(self, ax: float, ay: float, bx: float, by: float) -> float:
        """环形曼哈顿距离（调度用；实际飞行是欧氏，略保守）。"""
        w, h = self.grid.w, self.grid.h
        dx = abs(ax - bx) % w
        dx = min(dx, w - dx)
        dy = abs(ay - by) % h
        dy = min(dy, h - dy)
        return dx + dy

    def _can_fly(self, d, sup, req) -> bool:
        """家→供应塔→请求塔→家 的全程电量够不够（含预留）。"""
        need = (self._wdist(d.home.x, d.home.y, sup.x, sup.y)
                + self._wdist(sup.x, sup.y, req.x, req.y)
                + self._wdist(req.x, req.y, d.home.x, d.home.y)
                ) * C.DRONE_ENERGY_PER_CELL
        return d.energy >= need + C.DRONE_RESERVE_ENERGY

    def assign_tasks(self, towers: list) -> None:
        """贪心调度：遍历请求塔的缺口，找有货的供应塔，派空闲无人机去取。

        约束（还 TechDebt #7）：供应塔必须在 TOWER_RANGE 内；无人机电量
        必须够飞完 家→供应→请求→家 全程，否则不派（避免半路没电爬行）。
        """
        idle_drones = [d for d in self.drones
                       if not d.busy and d.energy >= C.DRONE_MAX_ENERGY * 0.5]
        if not idle_drones:
            return

        supply_towers = [t for t in towers if t.mode == "supply"]
        request_towers = [t for t in towers if t.mode == "request"]
        if not supply_towers or not request_towers:
            return

        for req in request_towers:
            if not idle_drones:
                break
            # missing_items() -> {item_id: 缺口数量}
            for item_id, need in req.missing_items().items():
                if not idle_drones:
                    break
                if need <= 0:
                    continue
                # 只看覆盖半径内、有货的供应塔，近的优先
                cands = [s for s in supply_towers
                         if s.has(item_id, 1)
                         and self._wdist(s.x, s.y, req.x, req.y)
                         <= C.TOWER_RANGE]
                if not cands:
                    continue
                cands.sort(key=lambda s: self._wdist(s.x, s.y, req.x, req.y))
                found = cands[0]
                # 电量够飞完全程的无人机里，挑母塔离请求塔最近的
                usable = [d for d in idle_drones
                          if self._can_fly(d, found, req)]
                if not usable:
                    continue
                drone = min(
                    usable,
                    key=lambda d: self._wdist(d.home.x, d.home.y,
                                              req.x, req.y),
                )
                idle_drones.remove(drone)
                # 无人机先去供应塔取货；取到后由 update 里的逻辑送往 req
                drone.assign_pickup(found, item_id, min(need, C.DRONE_CAPACITY))
                drone.deliver_tower = req  # 送货目标（见 Drone 注释）

    @property
    def count(self) -> int:
        return len(self.drones)

    @property
    def busy_count(self) -> int:
        return sum(1 for d in self.drones if d.busy)