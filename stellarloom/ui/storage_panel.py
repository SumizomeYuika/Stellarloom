"""箱子 / 采矿机 暂存面板：手动放入、取出。

两者都是"纯容器"（`.store` 或 `.buffer` 一个 dict，配 add_item / take_item），
所以共用一个面板。机器因为要区分原料槽/产物槽 + 配方选择，仍走 MachinePanel。

交互：
- 容器区每行：[取1] [全取]
- 背包区每行：[放1] [放10]
- 点面板外关闭
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef


class StoragePanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("storage_panel.json")
        self.rect = pygame.Rect(0, 0, 420, 500)
        self.container = None
        self.title = ""
        # M15a：写操作走 sim 指令；cell 用来定位容器（容器对象本身不再被直接改）
        self.sim = None
        self.cell: tuple[int, int] | None = None
        self.inv: dict[int, int] = {}
        self.per_cap = 10
        self.total_cap = None
        self.allowed: set[int] | None = None  # None = 任意物品
        # (rect, kind, item)  kind: "t1"/"tall"/"p1"/"p10"
        self._rows: list[tuple[pygame.Rect, str, int]] = []
        self._scroll = 0

    @property
    def open(self) -> bool:
        return self.container is not None

    def show(self, screen_size, title: str, container, per_cap: int,
             inventory: dict[int, int], total_cap: int | None = None,
             allowed: set[int] | None = None,
             cell: tuple[int, int] | None = None, sim=None):
        self.title = title
        self.container = container
        self.cell = cell
        if sim is not None:
            self.sim = sim
        self.per_cap = per_cap
        self.total_cap = total_cap
        self.inv = inventory
        self.allowed = allowed
        self._scroll = 0
        sw, sh = screen_size
        w = min(420, int(sw * 0.88))
        h = min(500, int(sh * 0.84))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.container = None

    def _store(self) -> dict[int, int]:
        c = self.container
        return c.store if hasattr(c, "store") else c.buffer

    def hit(self, pos) -> bool:
        if self.container is None:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        for rect, kind, item in self._rows:
            if not rect.collidepoint(pos):
                continue
            if kind == "t1":
                self._take(item, 1)
            elif kind == "tall":
                self._take(item, None)
            elif kind == "p1":
                self._put(item, 1)
            elif kind == "p10":
                self._put(item, 10)
            return True
        return True

    # ---------- 搬运（M15a：一律走 sim 指令） ----------

    def _take(self, item: int, count: int | None):
        sim = self.sim
        if sim is None or self.cell is None:
            return
        sim.container_take(self.cell[0], self.cell[1], item, count)

    def _put(self, item: int, count: int):
        sim = self.sim
        if sim is None or self.cell is None:
            return
        sim.container_put(self.cell[0], self.cell[1], item, count)

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if self.container is None:
            return
        r = self.rect
        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)
        uidef.draw_controls(
            screen, self.defs, r, self.fonts,
            {"text": {"title": self.title}})

        small = self.fonts.get(15)
        tiny = self.fonts.get(13)

        self._rows.clear()
        store = self._store()
        y = r.top + 42
        half = (r.height - 90) // 2

        # ---- 容器内容 ----
        cap_txt = f"每种最多 {self.per_cap}"
        if self.total_cap is not None:
            cap_txt += f" / 共 {self.total_cap}"
        screen.blit(small.render(f"内容（{cap_txt}）", True, C.C_TEXT),
                    (r.left + 14, y))
        y += 22
        items = sorted((i, n) for i, n in store.items() if n > 0)
        if not items:
            screen.blit(tiny.render("  (空)", True, (140, 145, 160)),
                        (r.left + 20, y))
            y += 20
        end_y = r.top + 42 + half
        for item, n in items:
            if y + 22 > end_y:
                screen.blit(tiny.render("  …（更多内容请先取走）", True,
                                        (120, 125, 140)), (r.left + 20, y))
                y += 20
                break
            y = self._draw_store_row(screen, tiny, r.left + 20, y, item, n,
                                     take=True, put=False)

        # ---- 背包（可放入的物品） ----
        y = end_y + 8
        screen.blit(small.render("背包（点放 1 / 放 10 存入）", True, C.C_TEXT),
                    (r.left + 14, y))
        y += 22
        cands = [
            (i, n) for i, n in sorted(self.inv.items())
            if n > 0 and (self.allowed is None or i in self.allowed)
        ]
        if not cands:
            screen.blit(tiny.render("  (没有可放入的物品)", True, (140, 145, 160)),
                        (r.left + 20, y))
        lim = r.bottom - 30
        for item, n in cands:
            if y + 22 > lim:
                screen.blit(tiny.render("  …（更多请滚动背包面板）", True,
                                        (120, 125, 140)), (r.left + 20, y))
                break
            y = self._draw_store_row(screen, tiny, r.left + 20, y, item, n,
                                     take=False, put=True)

        screen.blit(tiny.render("点面板外关闭", True, (100, 105, 120)),
                    (r.left + 14, r.bottom - 22))

    def _draw_store_row(self, screen, font, x, y, item, count,
                        take: bool, put: bool):
        name = C.ITEM_NAMES.get(item, f"?{item}")
        color = C.ITEM_COLORS.get(item, (200, 200, 200))
        pygame.draw.rect(screen, color, (x, y + 3, 12, 12))
        screen.blit(font.render(f"{name} ×{count}", True, C.C_TEXT), (x + 18, y))

        btns = []
        if take:
            btns.append(("t1", "取1", 34))
            btns.append(("tall", "全取", 40))
        if put:
            btns.append(("p1", "放1", 34))
            btns.append(("p10", "放10", 38))

        bw_total = sum(w for _, _, w in btns) + 4 * (len(btns) - 1)
        bx = self.rect.right - 18 - bw_total
        for kind, label, w in btns:
            rect = pygame.Rect(bx, y, w, 20)
            pygame.draw.rect(screen, (56, 82, 118), rect, border_radius=4)
            t = font.render(label, True, (235, 240, 250))
            screen.blit(t, (rect.centerx - t.get_width() // 2,
                            rect.centery - t.get_height() // 2))
            self._rows.append((rect, kind, item))
            bx += w + 4
        return y + 22