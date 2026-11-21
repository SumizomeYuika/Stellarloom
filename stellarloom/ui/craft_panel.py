"""手搓合成面板 + 背包面板。

合成面板改版（M6.5）：
- 面板放大到接近全屏，左右两栏：左边是**可选产物列表**，右边显示选中产物的
  原料需求 / 产出 / 单次耗时 / 当前可做次数。
- **先选产物，才显示原料**。没选之前右栏是空提示。
- 手搓不是瞬间完成的：点了「做1 / 做10」之后进入**手搓队列**，按配方的
  `dur` 秒逐个产出，面板里显示进度条和剩余数量。
- 材料不够的配方显示为灰，但仍可点开看缺什么（方便玩家知道要挖什么矿）。

背包面板不变：纯展示物品数量。
"""

from __future__ import annotations

import pygame

from .. import config as C
from ..sim.craft_queue import CraftJob, CraftQueue
from . import uidef


def _hand_dur(rid: str) -> float:
    """手搓一件要多久：和机器同一份配方，但慢 HAND_CRAFT_TIME_MULT 倍。"""
    r = C.RECIPES.get(rid)
    return r[2] * C.HAND_CRAFT_TIME_MULT if r else 1.0


def _out_name(rid: str) -> str:
    """配方的产物名字（多个产物用 + 连），队列提示用。"""
    r = C.RECIPES.get(rid)
    if not r:
        return "?"
    return " + ".join(C.ITEM_NAMES.get(i, "?") for i in r[1])


def _machine_names(rid: str) -> str:
    """该配方能在哪些建筑上自动化（用于"该配方可用于 XXX"提示）。"""
    r = C.RECIPES.get(rid)
    if not r or not r[3]:
        return ""
    return " / ".join(C.BUILDING_NAMES.get(b, str(b)) for b in r[3])


def _can_handcraft(rid: str) -> bool:
    return rid not in C.HANDCRAFT_BLACKLIST


class CraftPanel:
    """手搓面板：UI 只显示，手搓队列逻辑在 sim.craft_queue（M6.24 分层）。"""

    def __init__(self, fonts):
        self.fonts = fonts
        self.open = False
        self.rect = pygame.Rect(0, 0, 440, 480)
        self.inv: dict[int, int] = {}
        # 手搓队列（服务器端）：Game 构造时注入 sim.craft 同对象
        self.queue = CraftQueue(self.inv)
        # 选中的产物物品 id（None = 还没选）
        self.sel_item: int | None = None
        # 产物列表滚动偏移（行数）+ 累积小数像素（拖动手势专用）
        self.scroll = 0
        self._scroll_acc = 0.0
        # 点击区
        self._item_rects: list[tuple[pygame.Rect, int]] = []
        self._btn_rects: list[tuple[pygame.Rect, str]] = []  # make1/make10/cancel
        self._scroll_rect: pygame.Rect | None = None

        # 产物目录：全部配方都进目录（含不能手搓的），方便玩家查看配方/该去哪台机器造。
        # 不能手搓的配方在详情页会被禁用制作按钮并提示可用机器（M6.12）
        self._catalog: dict[int, str] = {}
        for rid, (ins, outs, dur, allows) in C.RECIPES.items():
            for item in outs:
                # 同一物品有多个配方时取第一个
                self._catalog.setdefault(item, rid)

    # ---------- 生命周期 ----------

    def show(self, screen_size, inventory: dict[int, int]):
        self.inv = inventory
        # 传入的背包引用与队列不同（独立测试/面板）时，队列跟着走
        if self.queue.inv is not inventory:
            self.queue.inv = inventory
        self.open = True
        sw, sh = screen_size
        # 面板尽量大：宽 94%、高 90%，上限 560×620
        w = min(560, int(sw * 0.94))
        h = min(620, int(sh * 0.90))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)
        # 保持上次的选择，但校验还在目录里
        if self.sel_item is not None and self.sel_item not in self._catalog:
            self.sel_item = None

    def close(self):
        self.open = False

    def refresh_inventory(self, inventory: dict[int, int]):
        self.inv = inventory
        if self.queue.inv is not inventory:
            self.queue.inv = inventory

    # ---------- 手搓队列（读 sim） ----------

    @property
    def jobs(self) -> list[CraftJob]:
        """未完成的手搓任务（队首在跑）。转发到 sim 队列。"""
        return self.queue.jobs

    @property
    def job(self) -> CraftJob | None:
        """队首任务（没在跑时为 None）。转发到 sim 队列。"""
        return self.queue.job

    def cancel(self):
        """取消全部排队任务（已扣材料不退还）。"""
        self.queue.cancel()

    # ---------- 交互 ----------

    def hit(self, pos):
        """返回 ("craft", rid, times) / ("cancel", None, 0) / None。

        点面板外关闭。点产物行 = 选中该产物。
        """
        if not self.open:
            return None
        if not self.rect.collidepoint(pos):
            self.close()
            return None

        # 产物列表
        for rect, item in self._item_rects:
            if rect.collidepoint(pos):
                self.sel_item = item
                return None
        # 按钮
        for rect, action in self._btn_rects:
            if rect.collidepoint(pos):
                if action == "cancel":
                    self.cancel()
                    return ("cancel", None, 0)
                if self.sel_item is None:
                    return None
                rid = self._catalog.get(self.sel_item)
                if rid is None:
                    return None
                times = 1 if action == "make1" else 10
                n = self.queue.start(rid, times)
                return ("craft", rid, n) if n else None
        return None

    def scroll_by(self, dy_px: float):
        """滚轮/拖动滚动产物列表。

        拖动手势每帧只有几像素，直接 `dy // 22` 永远是 0（这就是"划不动"
        的老 bug）——这里累积小数像素，够一行再滚。
        """
        self._scroll_acc += float(dy_px)
        # int(a / 22) 向零截断；用 // 会让负方向被 floor 拉成 -1，累加器震荡
        rows = int(self._scroll_acc / 22)
        if rows:
            self._scroll_acc -= rows * 22
            self.scroll = max(0, self.scroll + rows)

    # ---------- 绘制 ----------

    def _visible_rows(self, list_h: int) -> int:
        return max(1, (list_h - 8) // 22)

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        r = self.rect
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        surf.fill((20, 24, 34, 240))
        screen.blit(surf, r.topleft)
        pygame.draw.rect(screen, (90, 100, 130), r, 2, border_radius=8)

        font = self.fonts.get(18)
        small = self.fonts.get(15)
        tiny = self.fonts.get(13)

        screen.blit(font.render("手动合成", True, (200, 220, 240)),
                    (r.left + 14, r.top + 10))

        # 手搓队列状态：队首显示进度条，其余排队任务按顺序列在后面
        job = self.job
        if job is not None:
            rj = C.RECIPES.get(job.rid)
            dur = _hand_dur(job.rid) if rj else 1.0
            frac = min(job.elapsed / dur, 1.0) if dur > 0 else 0.0
            bar = pygame.Rect(r.left + 110, r.top + 14, r.width - 260, 12)
            pygame.draw.rect(screen, (50, 55, 70), bar, border_radius=4)
            pygame.draw.rect(screen, (90, 210, 120),
                             (bar.left, bar.top, int(bar.width * frac), bar.height),
                             border_radius=4)
            name = " + ".join(C.ITEM_NAMES.get(i, "?") for i in rj[1]) if rj else "?"
            screen.blit(tiny.render(f"{name} 剩 {job.left}", True, (200, 230, 210)),
                        (bar.right + 6, r.top + 13))
            if len(self.jobs) > 1:
                nxt = " → ".join(
                    f"{_out_name(j.rid)}×{j.left}"
                    for j in self.jobs[1:4] if j.rid in C.RECIPES
                )
                extra = f"排队 {len(self.jobs) - 1} 项"
                if nxt:
                    extra += f"：{nxt}"
                if len(self.jobs) > 4:
                    extra += " …"
                screen.blit(tiny.render(extra, True, (170, 185, 205)),
                            (r.left + 14, r.top + 30))
        else:
            screen.blit(tiny.render("空闲", True, (110, 116, 130)),
                        (r.left + 110, r.top + 13))

        body_top = r.top + 50
        body_h = r.height - 50 - 26
        split = int(r.width * 0.46)
        # 左栏底
        left = pygame.Rect(r.left + 8, body_top, split - 12, body_h)
        pygame.draw.rect(screen, (26, 30, 40), left, border_radius=6)
        # 右栏底
        right = pygame.Rect(left.right + 8, body_top,
                            r.width - split - 20, body_h)
        pygame.draw.rect(screen, (26, 30, 40), right, border_radius=6)

        screen.blit(tiny.render("选择产物", True, (150, 170, 200)),
                    (left.left + 8, left.top + 6))
        screen.blit(tiny.render("材料需求", True, (150, 170, 200)),
                    (right.left + 8, right.top + 6))

        self._item_rects.clear()
        self._btn_rects.clear()
        self._draw_list(screen, tiny, left)
        self._draw_detail(screen, small, tiny, right)

        screen.blit(tiny.render("先选产物 → 右侧显示原料 · 手搓需要时间 · 点面板外关闭",
                                True, (100, 105, 120)),
                    (r.left + 14, r.bottom - 20))

    def _draw_list(self, screen, tiny, box: pygame.Rect):
        rows = self._visible_rows(box.height - 24)
        items = sorted(self._catalog)
        max_scroll = max(0, len(items) - rows)
        if self.scroll > max_scroll:
            self.scroll = max_scroll
        y = box.top + 22
        for item in items[self.scroll:self.scroll + rows]:
            row = pygame.Rect(box.left + 6, y, box.width - 12, 20)
            selected = item == self.sel_item
            rid = self._catalog[item]
            ins = C.RECIPES[rid][0]
            can = all(self.inv.get(i, 0) >= n for i, n in ins.items())

            if selected:
                pygame.draw.rect(screen, (52, 76, 104), row, border_radius=4)
                pygame.draw.rect(screen, (120, 200, 255), row, 1, border_radius=4)
            elif can:
                pygame.draw.rect(screen, (34, 40, 54), row, border_radius=4)

            color = C.ITEM_COLORS.get(item, (200, 200, 200))
            pygame.draw.rect(screen, color, (row.left + 4, row.top + 4, 12, 12))
            name = C.ITEM_NAMES.get(item, f"?{item}")
            tc = (215, 235, 255) if can else (120, 126, 140)
            screen.blit(tiny.render(name, True, tc), (row.left + 22, row.top + 2))

            # 右侧标签：能手搓显示可做次数；不能手搓显示可用机器
            if not _can_handcraft(rid):
                tag = _machine_names(rid) or "不可手搓"
                t = tiny.render(tag, True, (210, 180, 120))
            else:
                outs = C.RECIPES[rid][1]
                per = max(outs.values()) if outs else 1
                limit = 999
                for i, n in ins.items():
                    limit = min(limit, self.inv.get(i, 0) // n)
                limit = min(limit, 999)
                tag = f"×{limit * per}" if limit > 0 else "缺料"
                t = tiny.render(tag, True,
                                (150, 200, 170) if limit > 0 else (190, 120, 110))
            screen.blit(t, (row.right - t.get_width() - 4, row.top + 2))

            self._item_rects.append((row, item))
            y += 22

        if len(items) > rows:
            screen.blit(tiny.render(f"滚动 {self.scroll + 1}-"
                                    f"{min(self.scroll + rows, len(items))}"
                                    f"/{len(items)}", True, (110, 116, 130)),
                        (box.left + 8, box.bottom - 16))

    def _draw_detail(self, screen, small, tiny, box: pygame.Rect):
        item = self.sel_item
        if item is None:
            screen.blit(small.render("← 左边选一个产物", True, (120, 126, 140)),
                        (box.left + 12, box.top + 40))
            screen.blit(tiny.render("选定后才显示需要的材料", True, (100, 106, 120)),
                        (box.left + 12, box.top + 64))
            return

        rid = self._catalog.get(item)
        if rid is None:
            return
        ins, outs, dur = C.RECIPES[rid][0], C.RECIPES[rid][1], C.RECIPES[rid][2]

        x = box.left + 10
        y = box.top + 24
        w = box.width - 20

        # 产物
        color = C.ITEM_COLORS.get(item, (200, 200, 200))
        pygame.draw.rect(screen, color, (x, y + 4, 14, 14))
        screen.blit(small.render(f"{C.ITEM_NAMES.get(item, '?')} "
                                 f"×{outs.get(item, 1)}", True, (220, 238, 255)),
                    (x + 20, y))
        y += 26

        # 原料
        screen.blit(tiny.render("需要:", True, (150, 170, 200)), (x, y))
        y += 18
        can_all = True
        for i, n in ins.items():
            have = self.inv.get(i, 0)
            ok = have >= n
            can_all = can_all and ok
            ic = C.ITEM_COLORS.get(i, (200, 200, 200))
            pygame.draw.rect(screen, ic, (x + 6, y + 3, 12, 12))
            nm = C.ITEM_NAMES.get(i, f"?{i}")
            txt = f"{nm}  {have}/{n}"
            screen.blit(tiny.render(txt, True,
                                    (190, 225, 195) if ok else (215, 140, 130)),
                        (x + 24, y + 1))
            y += 20

        # 该配方可用于哪台机器（所有配方都提示，方便玩家造自动化）
        mach = _machine_names(rid)
        if mach:
            screen.blit(tiny.render(f"该配方可用于：{mach}", True,
                                    (150, 190, 220)), (x, y))
            y += 18

        if not _can_handcraft(rid):
            # 不能手搓：提示只能靠机器造，不给制作按钮
            screen.blit(tiny.render("该配方只能由机器制造，不能手搓", True,
                                    (215, 150, 120)), (x, y))
            y += 18
        else:
            # 耗时 / 可做次数
            y += 6
            limit = 999
            for i, n in ins.items():
                limit = min(limit, self.inv.get(i, 0) // n)
            limit = min(limit, 999)
            hdur = _hand_dur(rid)
            screen.blit(tiny.render(f"手搓 {hdur:.1f}s/次（机器 {dur:.1f}s）",
                                    True, (170, 190, 215)), (x, y))
            y += 18
            screen.blit(tiny.render(f"最多可做 {limit} 次", True,
                                    (150, 200, 170) if limit > 0 else (200, 130, 120)),
                        (x, y))
            y += 22

            # 按钮：做1 / 做10
            bw = (w - 12) // 2
            b1 = pygame.Rect(x, y, bw, 26)
            b10 = pygame.Rect(x + bw + 12, y, bw, 26)
            for btn, label, act in ((b1, "做 1", "make1"), (b10, "做 10", "make10")):
                enabled = can_all
                pygame.draw.rect(screen, (60, 100, 150) if enabled else (44, 48, 58),
                                 btn, border_radius=5)
                t = tiny.render(label, True,
                                (255, 255, 255) if enabled else (110, 114, 126))
                screen.blit(t, (btn.centerx - t.get_width() // 2,
                                btn.centery - t.get_height() // 2))
                if enabled:
                    self._btn_rects.append((btn, act))
            y += 32

        if self.jobs:
            cb = pygame.Rect(x, y, w, 24)
            pygame.draw.rect(screen, (110, 66, 66), cb, border_radius=5)
            label = "取消全部排队" if len(self.jobs) > 1 else "取消当前手搓"
            t = tiny.render(label, True, (250, 230, 230))
            screen.blit(t, (cb.centerx - t.get_width() // 2,
                            cb.centery - t.get_height() // 2))
            self._btn_rects.append((cb, "cancel"))


class BagPanel:
    """背包：列出全部物品数量。纯展示。

    M6.26：外观走 `defs/bag_panel.json`（UI 定义层），背包列表是动态行，
    颜色取 meta_c（theme.json 兜底，改主题一处换全肤色）。
    """

    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("bag_panel.json")
        self.open = False
        self.rect = pygame.Rect(0, 0, 420, 460)
        self.inv: dict[int, int] = {}

    def show(self, screen_size, inventory: dict[int, int]):
        self.inv = inventory
        self.open = True
        sw, sh = screen_size
        w = min(420, int(sw * 0.86))
        h = min(460, int(sh * 0.80))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.open = False

    def hit(self, pos) -> bool:
        if not self.open:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
        return True

    def draw(self, screen: pygame.Surface):
        if not self.open:
            return
        r = self.rect
        m = self.defs.meta_c
        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)

        # 静态控件（标题/脚注）
        uidef.draw_controls(screen, self.defs, r, self.fonts)

        # 物品两列（动态行，参数在 defs 的 list 控件）
        small = self.fonts.get(15)
        g = self.defs.ctrl("list").raw
        pad = g["pad"]
        col_gap = g["col_gap"]
        row_h = g["row_h"]
        y = r.top + g["y"]
        items = sorted((i, n) for i, n in self.inv.items() if n > 0)
        if not items:
            screen.blit(small.render("(空)", True, m["hint"]),
                        (r.left + 18, y))
        col_w = (r.width - pad * 2 - col_gap) // 2
        for idx, (item, n) in enumerate(items):
            cx = r.left + pad + (idx % 2) * (col_w + col_gap)
            cy = y + (idx // 2) * row_h
            color = C.ITEM_COLORS.get(item, (200, 200, 200))
            pygame.draw.rect(screen, color, (cx, cy + 3, 12, 12))
            screen.blit(small.render(f"{C.ITEM_NAMES.get(item, '?')} ×{n}",
                                     True, m["text"]), (cx + 18, cy))
