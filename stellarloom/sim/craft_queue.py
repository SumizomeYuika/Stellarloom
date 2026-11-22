"""手搓队列（服务器端逻辑，不依赖 pygame）。

原实现嵌在 ui/craft_panel.py，M6.24 抽出为 sim 组件：玩家点"制作"向队列
排任务，材料在排队时扣掉，每件按配方时长推进，产出直接进背包。
"""

from __future__ import annotations

from .. import config as C


def _hand_dur(rid: str) -> float:
    """手搓一件要多久：和机器同一份配方，但慢 HAND_CRAFT_TIME_MULT 倍。

    （与 ui/craft_panel._hand_dur 同式；逻辑层不依赖 UI。）
    """
    r = C.RECIPES.get(rid)
    return r[2] * C.HAND_CRAFT_TIME_MULT if r else 1.0


class CraftJob:
    """一条手搓任务：做一个花 dur 秒，做 n 个就排队 n 次。"""

    __slots__ = ("rid", "left", "elapsed")

    def __init__(self, rid: str, times: int):
        self.rid = rid
        self.left = times
        self.elapsed = 0.0


class CraftQueue:
    """手搓队列：按顺序逐个完成，队首在跑。"""

    def __init__(self, inventory: dict[int, int]):
        self.inv = inventory
        self.jobs: list[CraftJob] = []

    # ---------- 查询 ----------

    @property
    def job(self) -> CraftJob | None:
        """队首任务（没在跑时为 None）。"""
        return self.jobs[0] if self.jobs else None

    # ---------- 推进 ----------

    def update(self, dt: float) -> bool:
        """推进手搓队列。返回 True 表示这一刻产出了东西。

        用 while 消化 dt：低帧率或长 dt 时一帧也能补上多件，不会平白吞时间。
        队首做完自动接下一个，一帧内可以跨多个任务。
        """
        produced = False
        remaining = dt
        while self.jobs:
            job = self.jobs[0]
            r = C.RECIPES.get(job.rid)
            if r is None:
                self.jobs.pop(0)
                continue
            outs = r[1]
            dur = _hand_dur(job.rid)
            if dur <= 0:
                dur = 0.01
            job.elapsed += remaining
            while job.left > 0 and job.elapsed >= dur:
                job.elapsed -= dur
                for item, n in outs.items():
                    self.inv[item] = self.inv.get(item, 0) + n
                job.left -= 1
                produced = True
            if job.left > 0:
                # 队首还没做完，剩余时间到此为止
                break
            # 队首做完，超出 dur 的那部分时间接着喂下一个任务
            remaining = job.elapsed
            self.jobs.pop(0)
        return produced

    def start(self, rid: str, times: int) -> int:
        """开始手搓，返回实际排进去的次数（材料决定上限）。

        排队按顺序执行：正在搓 A 时点 B，B 排在 A 后面，A 的进度和已扣材料都保留。
        同一配方连续点击会合并到已有的那条里，不刷一堆一行任务。
        """
        r = C.RECIPES.get(rid)
        if r is None:
            return 0
        ins = r[0]
        ok = 0
        for _ in range(times):
            if any(self.inv.get(i, 0) < n for i, n in ins.items()):
                break
            for i, n in ins.items():
                left = self.inv.get(i, 0) - n
                if left > 0:
                    self.inv[i] = left
                else:
                    self.inv.pop(i, None)
            ok += 1
        if ok == 0:
            return 0
        # 队尾就是同一配方 → 直接累加，避免重复行
        if self.jobs and self.jobs[-1].rid == rid:
            self.jobs[-1].left += ok
        else:
            self.jobs.append(CraftJob(rid, ok))
        return ok

    def cancel(self):
        """取消全部排队任务，已扣材料不退还（算进当前这一件）。"""
        self.jobs.clear()