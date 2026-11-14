"""机器面板：点熔炉/制造台弹出，显示当前配方、手动存取、生产进度。

交互（M6.28 配方选择器）：
- 主界面只显示「当前配方」+ [点击选择配方]；点它打开配方选择器
- 选择器按机器类型列出已解锁配方（同合成面板风格），点选即切配方
- 切换会把不匹配的原料倒掉（machines.set_recipe 语义）
- 点「无配方」清空配方，机器拒收一切物品，分拣器自动堵住
- 点面板外关闭
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef


class MachinePanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("machine_panel.json")
        self.machine = None
        self.rect = pygame.Rect(0, 0, 440, 470)
        self._recipe_rects: list[tuple[pygame.Rect, str | None]] = []
        # M6.28：配方选择器态（True = 当前显示配方列表页）
        self._picker = False
        # 主界面「点击选择配方」入口按钮：(rect, "picker")
        self._picker_btn: list[tuple[pygame.Rect, str]] = []
        # 由 game 注入，用于过滤未解锁的配方
        self.researched: set[str] = set()
        # 由 game 注入玩家背包，用于手动放料
        self.inventory: dict[int, int] = {}
        # 按钮区：(rect, 动作, 物品)  动作: take_input/take_all_out/put_input/put10
        self._btn_rects: list[tuple[pygame.Rect, str, int]] = []
        self._tab = "input"  # 当前显示哪一半的背包存取行

    @property
    def open(self) -> bool:
        return self.machine is not None

    def show(self, machine, screen_size, researched: set[str] | None = None,
             inventory: dict[int, int] | None = None):
        self.machine = machine
        self._picker = False    # 开面板回到主界面（不记忆上次的选择器页）
        self._recipe_rects.clear()
        self._picker_btn.clear()
        self._btn_rects.clear()
        if researched is not None:
            self.researched = researched
        if inventory is not None:
            self.inventory = inventory
        sw, sh = screen_size
        # 主界面变瘦（配方详情在独立选择器页），面板可以小一些
        w = min(460, int(sw * 0.92))
        h = min(560, int(sh * 0.88))
        self.rect.size = (w, h)
        self.rect.center = (sw // 2, sh // 2)

    def close(self):
        self.machine = None
        self._picker = False

    def hit(self, pos) -> bool:
        if self.machine is None:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        if self._picker:
            for rect, rid in self._recipe_rects:
                if rect.collidepoint(pos):
                    if rid is None:
                        self.machine.set_recipe(None)
                    else:
                        req = C.RECIPE_TECH.get(rid)
                        if req and req not in self.researched:
                            return True  # 未解锁：点了没反应，不切换配方
                        self.machine.set_recipe(rid)
                    self._picker = False  # 选中即回主界面
                    self._btn_rects.clear()
                    return True
            return True  # 选择器内空白也消费
        # 主界面：点「点击选择配方」→ 打开选择器
        for rect, act in self._picker_btn:
            if rect.collidepoint(pos):
                if act == "picker":
                    self._picker = True
                    self._recipe_rects.clear()
                    return True
        for rect, action, item in self._btn_rects:
            if rect.collidepoint(pos):
                self._do_action(action, item)
                return True
        return True  # 点在面板空白处也消费，不穿透

    def _do_action(self, action: str, item: int):
        m = self.machine
        if m is None:
            return
        if action == "take1":
            n = m.take_input(item, 1)
            if n:
                self.inventory[item] = self.inventory.get(item, 0) + n
        elif action == "takeall":
            n = m.take_input(item, None)
            if n:
                self.inventory[item] = self.inventory.get(item, 0) + n
        elif action == "put1":
            self._put(item, 1)
        elif action == "put10":
            self._put(item, 10)
        elif action == "takeout_all":
            got = m.take_all_outputs()
            for it, n in got.items():
                self.inventory[it] = self.inventory.get(it, 0) + n

    def _put(self, item: int, count: int):
        have = self.inventory.get(item, 0)
        if have <= 0:
            return
        n = self.machine.add_input(item, min(have, count))
        if n <= 0:
            return
        left = have - n
        if left > 0:
            self.inventory[item] = left
        else:
            self.inventory.pop(item, None)

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if self.machine is None:
            return
        m = self.machine
        r = self.rect
        uidef.draw_window(screen, self.defs, r, self.fonts)
        small = self.fonts.get(15)
        tiny = self.fonts.get(13)

        bname = "熔炉" if m.btype == C.B_FURNACE else "制造台"
        uidef.draw_controls(
            screen, self.defs, r, self.fonts,
            {"text": {"title": f"{bname} ({m.x},{m.y})"}})

        if self._picker:
            self._draw_picker(screen, small, tiny)
            return
        self._draw_main(screen, m, small, tiny)

    def _draw_main(self, screen, m, small, tiny):
        """主界面：当前配方卡 + 进度 + 原料/产物手动存取。"""
        r = self.rect
        self._picker_btn.clear()
        self._btn_rects.clear()
        y = r.top + 58

        # ---- 当前配方卡 ----
        card = pygame.Rect(r.left + 12, y - 4, r.width - 24, 36)
        pygame.draw.rect(screen, (34, 40, 54), card, border_radius=6)
        if m.recipe_id and m.recipe_id in C.RECIPES:
            _, outs, dur, _ = C.RECIPES[m.recipe_id]
            color = C.ITEM_COLORS.get(next(iter(outs)), (200, 200, 200))
            pygame.draw.rect(screen, color, (card.left + 8, card.top + 12, 12, 12))
            out_txt = " + ".join(f"{C.ITEM_NAMES.get(i, '?')}×{n}"
                                 for i, n in outs.items())
            screen.blit(small.render(out_txt, True, (200, 210, 230)),
                        (card.left + 26, card.top + 8))
            screen.blit(tiny.render(f"{dur:.1f}s/次", True, (110, 116, 130)),
                        (card.left + 26, card.top + 22))
            # [换配方] 入口（列表在 picker 页）
            btn = pygame.Rect(card.right - 88, card.top + 7, 76, 22)
            pygame.draw.rect(screen, (56, 82, 118), btn, border_radius=4)
            t = tiny.render("换配方", True, (235, 240, 250))
            screen.blit(t, (btn.centerx - t.get_width() // 2,
                            btn.centery - t.get_height() // 2))
            self._picker_btn.append((btn, "picker"))
        else:
            screen.blit(tiny.render("未设配方 → 拒收所有物品", True,
                                    (220, 140, 100)),
                        (card.left + 12, card.top + 10))
            btn = pygame.Rect(card.right - 108, card.top + 7, 96, 22)
            pygame.draw.rect(screen, (56, 82, 118), btn, border_radius=4)
            t = tiny.render("点击选择配方", True, (235, 240, 250))
            screen.blit(t, (btn.centerx - t.get_width() // 2,
                            btn.centery - t.get_height() // 2))
            self._picker_btn.append((btn, "picker"))
        y += 42

        # ---- 生产进度 ----
        if m.recipe_id and m.recipe_id in C.RECIPES:
            _, _, dur, _ = C.RECIPES[m.recipe_id]
            frac = min(m.progress / dur, 1.0) if dur > 0 else 0.0
            pygame.draw.rect(screen, (50, 55, 70), (r.left + 14, y, r.width - 28, 10))
            pygame.draw.rect(screen, (80, 220, 80),
                             (r.left + 14, y, int((r.width - 28) * frac), 10))
            y += 20
        y += 6

        # ---- 原料槽 ----
        screen.blit(small.render(
            f"原料 ({C.MACHINE_INPUT_CAP}/种) · 点击按钮手动存取", True, C.C_TEXT),
            (r.left + 14, y))
        y += 20
        if not m.inputs:
            screen.blit(tiny.render("  (空)", True, (140, 145, 160)),
                        (r.left + 22, y))
            y += 20
        else:
            for item, n in sorted(m.inputs.items()):
                y = self._draw_input_slot(screen, tiny, r.left + 22, y, item, n,
                                          item in m.need)
        # 可放入：配方需要的原料中背包里还有的
        put_items = [(i, self.inventory.get(i, 0)) for i in m.need
                     if self.inventory.get(i, 0) > 0]
        if put_items:
            for item, have in put_items:
                y = self._draw_put_row(screen, tiny, r.left + 22, y, item, have)

        # ---- 产物槽：只能全取 ----
        y += 8
        screen.blit(small.render(
            f"产物 ({C.MACHINE_OUTPUT_CAP}/种) · 只能整体取出", True, C.C_TEXT),
            (r.left + 14, y))
        y += 20
        if not m.outputs:
            screen.blit(tiny.render("  (空)", True, (140, 145, 160)),
                        (r.left + 22, y))
            y += 20
        else:
            for item, n in sorted(m.outputs.items()):
                color = C.ITEM_COLORS.get(item, (200, 200, 200))
                pygame.draw.rect(screen, color, (r.left + 22, y + 3, 12, 12))
                name = C.ITEM_NAMES.get(item, f"?{item}")
                screen.blit(tiny.render(f"{name}  {n}/{C.MACHINE_OUTPUT_CAP}",
                                        True, C.C_TEXT), (r.left + 40, y))
                self._draw_button(screen, tiny, "全取", r.right - 66, y,
                                  "takeout_all", 0)
                y += 22

        screen.blit(tiny.render("点面板外关闭", True, (100, 105, 120)),
                    (r.left + 14, r.bottom - 22))

    def _draw_picker(self, screen, small, tiny):
        """配方选择器：按机器类型列出已解锁配方（同合成面板风格）。"""
        m = self.machine
        r = self.rect
        self._recipe_rects.clear()
        y = r.top + 40
        screen.blit(small.render(
            "选择配方（按机器类型 · 已解锁）", True, (170, 200, 235)),
            (r.left + 14, y))
        y += 24

        recipes = [None] + list(m.available_recipes(None))  # None = 无配方
        row_h = 32
        for rid in recipes:
            if y + row_h > r.bottom - 26:
                break
            row = pygame.Rect(r.left + 12, y, r.width - 24, row_h)
            is_cur = m.recipe_id == rid
            pygame.draw.rect(screen, (34, 40, 54), row, border_radius=6)
            if is_cur:
                pygame.draw.rect(screen, (50, 70, 95), row, border_radius=6)
                pygame.draw.rect(screen, (120, 200, 255), row, 1, border_radius=6)
            else:
                pygame.draw.rect(screen, (70, 78, 96), row, 1, border_radius=6)
            self._recipe_rects.append((row, rid))

            if rid is None:
                color = (200, 140, 120) if is_cur else (150, 155, 170)
                screen.blit(tiny.render("无配方（不生产）", True, color),
                            (row.left + 12, row.top + 9))
                y += row_h + 4
                continue
            req = C.RECIPE_TECH.get(rid)
            locked = req is not None and req not in self.researched
            ins, outs, dur, _ = C.RECIPES[rid]
            first = next(iter(outs))
            ic = C.ITEM_COLORS.get(first, (200, 200, 200))
            pygame.draw.rect(screen, ic, (row.left + 10, row.top + 10, 12, 12))
            out_txt = " + ".join(f"{C.ITEM_NAMES.get(i, '?')}×{n}"
                                 for i, n in outs.items())
            in_txt = " + ".join(f"{C.ITEM_NAMES.get(i, '?')}×{n}"
                                for i, n in ins.items())
            t = small.render(out_txt, True,
                             (125, 170, 205) if locked else (200, 215, 235))
            screen.blit(t, (row.left + 28, row.top + 6))
            it = tiny.render(f"← {in_txt} · {dur:.1f}s"
                             + (f"  🔒{C.TECH_TREE.get(req, (req,))[0]}"
                                if locked else ""),
                             True, (110, 116, 130))
            screen.blit(it, (row.left + 28, row.top + 19))
            if is_cur:
                screen.blit(tiny.render("√", True, (120, 200, 255)),
                            (row.right - 22, row.top + 8))
            y += row_h + 4

        screen.blit(tiny.render("点面板外关闭", True, (100, 105, 120)),
                    (r.left + 14, r.bottom - 22))

    def _draw_input_slot(self, screen, font, x, y, item, count, needed):
        """原料行：[物品] 名字 数量 [取1][全取]"""
        color = C.ITEM_COLORS.get(item, (200, 200, 200))
        pygame.draw.rect(screen, color, (x, y + 3, 12, 12))
        if not needed:
            # 不受配方需要的原料：灰掉，因为切换配方会被倒掉
            pygame.draw.line(screen, (120, 120, 120), (x, y + 3), (x + 12, y + 15), 1)
        name = C.ITEM_NAMES.get(item, f"?{item}")
        screen.blit(font.render(f"{name}  {count}/{C.MACHINE_INPUT_CAP}",
                                True, C.C_TEXT), (x + 18, y))
        self._draw_button(screen, font, "取1", self.rect.right - 96, y, "take1", item)
        self._draw_button(screen, font, "全取", self.rect.right - 56, y, "takeall", item)
        return y + 22

    def _draw_put_row(self, screen, font, x, y, item, have):
        """可放入行：[物品] 背包有 N [放1][放10]"""
        color = C.ITEM_COLORS.get(item, (200, 200, 200))
        pygame.draw.rect(screen, color, (x, y + 3, 12, 12))
        name = C.ITEM_NAMES.get(item, f"?{item}")
        screen.blit(font.render(f"{name}  背包 {have}", True, (170, 200, 225)),
                    (x + 18, y))
        self._draw_button(screen, font, "放1", self.rect.right - 96, y, "put1", item)
        self._draw_button(screen, font, "放10", self.rect.right - 56, y, "put10", item)
        return y + 22

    def _draw_button(self, screen, font, label, x, y, action, item):
        rect = pygame.Rect(int(x), int(y), 36, 20)
        pygame.draw.rect(screen, (56, 82, 118), rect, border_radius=4)
        t = font.render(label, True, (235, 240, 250))
        screen.blit(t, (rect.centerx - t.get_width() // 2,
                        rect.centery - t.get_height() // 2))
        self._btn_rects.append((rect, action, item))

