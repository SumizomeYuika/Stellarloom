"""科研站面板（M6.11）：研究 / 制造双模式。

- 研究模式：只输入，吃科研包推进当前研究项，不产出。显示囤的科研包 + 手动存取。
- 制造模式：选一种矩阵配方（science_blue/red），原料进、矩阵出，可手动存取。

布局和机器/容器面板一致：点面板外关闭。
M6.26：外观（标题/模式按钮/配色/行参数）走 `defs/lab_panel.json`；
动态行列（存/取的物品行、配方行、进度条）仍业务画，颜色取 meta_c。
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef


class LabPanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("lab_panel.json")
        self.lab = None
        self.labs = None       # LabNetwork
        # M15a：写操作走 sim 指令（联机时由服务端执行）
        self.sim = None
        self.cell = (0, 0)
        self.rect = pygame.Rect(0, 0, 440, 580)
        self.inventory: dict[int, int] = {}
        # (rect, action, item)  action: mode_r/mode_p/rec/mode-agnostic 存取
        self._btn: list[tuple[pygame.Rect, str, int]] = []
        self._rec: list[tuple[pygame.Rect, str | None]] = []

    @property
    def open(self) -> bool:
        return self.lab is not None

    def show(self, lab, labs, x: int, y: int, screen_size, inventory: dict[int, int]):
        self.lab = lab
        self.labs = labs
        self.cell = (x, y)
        self.inventory = inventory
        sw, sh = screen_size
        w = min(440, int(sw * 0.90))
        h = min(580, int(sh * 0.86))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.lab = None

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if self.lab is None:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        x, y = self.cell
        # 静态控件（模式切换按钮，定义在 defs JSON）
        cid = uidef.hit_control(self.defs, self.rect, pos)
        if cid == "mode_r":
            self._cmd("lab_set_mode", C.LAB_MODE_RESEARCH)
            return True
        if cid == "mode_p":
            self._cmd("lab_set_mode", C.LAB_MODE_PRODUCE)
            return True
        for rect, rid in self._rec:
            if rect.collidepoint(pos):
                self._cmd("lab_set_recipe", rid)
                return True
        for rect, action, item in self._btn:
            if rect.collidepoint(pos):
                self._do(action, item)
                return True
        return True

    def _cmd(self, name: str, *args):
        """M15a：面板写操作统一走 sim 指令（联机时由服务端执行）。"""
        sim = self.sim
        if sim is None:
            return None
        x, y = self.cell
        fn = getattr(sim, name, None)
        if fn is None:
            return None
        return fn(x, y, *args)

    def _do(self, action: str, item: int):
        if action in ("mode_r", "mode_p"):
            self._cmd("lab_set_mode",
                      C.LAB_MODE_RESEARCH if action == "mode_r"
                      else C.LAB_MODE_PRODUCE)
        elif action == "t1":
            self._cmd("lab_take_item", item, 1)
        elif action == "tall":
            self._cmd("lab_take_item", item, None)
        elif action == "p1":
            self._cmd("lab_add_item", item, 1)
        elif action == "p10":
            self._cmd("lab_add_item", item, 10)
        elif action == "out_all":
            self._cmd("lab_take_outputs")

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if self.lab is None:
            return
        lab = self.lab
        r = self.rect
        m = self.defs.meta_c
        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)

        font = self.fonts.get(18)
        small = self.fonts.get(15)
        tiny = self.fonts.get(13)

        x, y = self.cell
        # 静态控件（标题/模式按钮/脚注）
        overrides = {"text": {}, "active": {}}
        overrides["text"]["title"] = f"科研站 ({x},{y})"
        research = lab["mode"] == C.LAB_MODE_RESEARCH
        overrides["active"]["mode_r"] = research
        overrides["active"]["mode_p"] = not research
        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        self._btn.clear()
        self._rec.clear()
        y = r.top + 70   # 模式按钮底部（mode_r y=40 h=26 → 70）
        if research:
            y = self._draw_research(screen, small, tiny, y, m)
        else:
            y = self._draw_produce(screen, small, tiny, y, m)

    def _draw_research(self, screen, small, tiny, y, m):
        r = self.rect
        lab = self.lab
        sec = m.get("sec_heading", m["text"])
        screen.blit(small.render(
            "研究模式：只输入，吃科研包推进当前研究项", True, sec),
            (r.left + 14, y))
        y += 24
        # 囤的科研包
        screen.blit(tiny.render(f"已存科研包（每种上限 {C.LAB_STORE_CAP}）",
                                True, m["text"]), (r.left + 14, y))
        y += 20
        stored = sorted((i, n) for i, n in lab["stored"].items() if n > 0)
        if not stored:
            screen.blit(tiny.render("  (空) 让分拣器喂电磁矩阵/能量矩阵",
                                    True, m["hint"]), (r.left + 20, y))
            y += 20
        else:
            for item, n in stored:
                y = self._row(screen, tiny, r.left + 20, y, item, n,
                              take=True, put=False, m=m)
        # 背包里能放的科研包
        y += 6
        wanted = self.labs._wanted_packs()
        cands = [(i, self.inventory.get(i, 0)) for i in sorted(wanted)
                 if self.inventory.get(i, 0) > 0]
        if cands:
            screen.blit(tiny.render("背包（点放 1 / 放 10 存入）", True,
                                    m.get("item_accent", m["text"])),
                        (r.left + 14, y))
            y += 20
            for item, have in cands:
                y = self._row(screen, tiny, r.left + 20, y, item, have,
                              take=False, put=True, m=m)
        return y

    def _draw_produce(self, screen, small, tiny, y, m):
        r = self.rect
        lab = self.lab
        sec = m.get("sec_heading", m["text"])
        # 配方选择
        screen.blit(small.render("制造配方（选一种）", True, sec),
                    (r.left + 14, y))
        y += 22
        self._rec_row(screen, tiny, r.left + 18, y, None,
                      lab["recipe"] is None, "无（不制造）", m)
        y += 24
        for rid in C.LAB_PRODUCE_RECIPES:
            outs = C.RECIPES[rid][1]
            name = " + ".join(C.ITEM_NAMES.get(i, "?") for i in outs)
            self._rec_row(screen, tiny, r.left + 18, y, rid,
                          lab["recipe"] == rid, name, m)
            y += 24
        # 进度
        rid = lab["recipe"]
        if rid and rid in C.RECIPES:
            dur = C.RECIPES[rid][2]
            frac = min(lab["progress"] / dur, 1.0) if dur > 0 else 0.0
            pygame.draw.rect(screen, m["progress_bg"],
                             (r.left + 14, y, r.width - 28, 10))
            pygame.draw.rect(screen, m["progress_fill"],
                             (r.left + 14, y, int((r.width - 28) * frac), 10))
            y += 20
        else:
            screen.blit(tiny.render("未选配方 → 不制造", True,
                                    m.get("warn", m["hint"])), (r.left + 14, y))
            y += 20

        need = C.RECIPES[rid][0] if rid else {}
        # 原料
        screen.blit(tiny.render("原料", True, m["text"]), (r.left + 14, y))
        y += 20
        ins = sorted((i, n) for i, n in lab["inputs"].items() if n > 0)
        if not ins:
            screen.blit(tiny.render("  (空)", True, m["hint"]),
                        (r.left + 20, y))
            y += 20
        else:
            for item, n in ins:
                y = self._row(screen, tiny, r.left + 20, y, item, n,
                              take=True, put=False, m=m)
        put_items = [(i, self.inventory.get(i, 0)) for i in sorted(need)
                     if self.inventory.get(i, 0) > 0]
        if put_items:
            screen.blit(tiny.render("背包（点放 1 / 放 10）", True,
                                    m.get("item_accent", m["text"])),
                        (r.left + 14, y))
            y += 20
            for item, have in put_items:
                y = self._row(screen, tiny, r.left + 20, y, item, have,
                              take=False, put=True, m=m)
        # 产物
        y += 6
        screen.blit(tiny.render(
            f"产物（每种上限 {C.LAB_PRODUCE_OUTPUT_CAP}）", True, m["text"]),
            (r.left + 14, y))
        y += 20
        outs = sorted((i, n) for i, n in lab["outputs"].items() if n > 0)
        if not outs:
            screen.blit(tiny.render("  (空)", True, m["hint"]),
                        (r.left + 20, y))
            y += 20
        else:
            for item, n in outs:
                color = C.ITEM_COLORS.get(item, (200, 200, 200))
                pygame.draw.rect(screen, color, (r.left + 20, y + 3, 12, 12))
                name = C.ITEM_NAMES.get(item, f"?{item}")
                screen.blit(tiny.render(f"{name}  {n}", True, m["text"]),
                            (r.left + 38, y))
                self._button(screen, tiny, "全取", r.right - 66, y,
                             "out_all", 0, m)
                y += 22
        return y

    # ---------- 小组件 ----------

    def _rec_row(self, screen, font, x, y, rid, selected, label, m):
        rect = pygame.Rect(x, y, self.rect.width - 36, 22)
        if selected:
            pygame.draw.rect(screen, m["item_active_bg"], rect, border_radius=4)
            pygame.draw.rect(screen, m["item_active_frame"], rect, 1,
                             border_radius=4)
        color = (200, 230, 255) if selected else m["hint"]
        screen.blit(font.render(label, True, color), (x + 6, y + 3))
        self._rec.append((rect, rid))

    def _row(self, screen, font, x, y, item, count, take, put, m):
        color = C.ITEM_COLORS.get(item, (200, 200, 200))
        pygame.draw.rect(screen, color, (x, y + 3, 12, 12))
        name = C.ITEM_NAMES.get(item, f"?{item}")
        screen.blit(font.render(f"{name}  {count}", True, m["text"]),
                    (x + 18, y))
        if take:
            self._button(screen, font, "取1", self.rect.right - 96, y,
                         "t1", item, m)
            self._button(screen, font, "全取", self.rect.right - 56, y,
                         "tall", item, m)
        elif put:
            self._button(screen, font, "放1", self.rect.right - 96, y,
                         "p1", item, m)
            self._button(screen, font, "放10", self.rect.right - 56, y,
                         "p10", item, m)
        return y + 22

    def _button(self, screen, font, label, x, y, action, item, m):
        rect = pygame.Rect(int(x), int(y), 36, 20)
        pygame.draw.rect(screen, m["btn_bg"], rect, border_radius=4)
        t = font.render(label, True, (235, 240, 250))
        screen.blit(t, (rect.centerx - t.get_width() // 2,
                        rect.centery - t.get_height() // 2))
        self._btn.append((rect, action, item))