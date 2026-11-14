"""科技树面板（M6.28 树状图版）：科技按「前置链」铺成有向树，
可拖动平移查看；点节点展开描述/研究。

交互：
- 拖动 / 滚轮 → 平移视角（树状图，不是滚动列表）
- 点节点 → 展开下方描述条（名字/状态/科研包/前置/解锁内容）
- 描述条里点 [开始研究] / [排队研究] → 开始或排队
- 点面板外 或 右上角 ✕ 或 ESC → 关闭
"""

from __future__ import annotations

import pygame

from .. import config as C


# 树状图布局参数
NODE_W = 178
NODE_H = 60
GAP_X = 52
GAP_Y = 22
PAD = 14
DETAIL_H = 86


class TechPanel:
    def __init__(self, fonts):
        self.fonts = fonts
        self.open = False
        self.rect = pygame.Rect(0, 0, 760, 560)
        self._tech = None
        self._close_rect = pygame.Rect(0, 0, 0, 0)
        self._area = pygame.Rect(0, 0, 0, 0)
        # 树状图布局：nodes {id: (世界坐标 rect)}；offset 平移（世界→屏幕）
        self._nodes: dict[str, pygame.Rect] = {}
        self._depth: dict[str, int] = {}
        self._world_w = 0.0
        self._world_h = 0.0
        self.off_x = 0.0
        self.off_y = 0.0
        self._max_off_x = 0.0
        self._max_off_y = 0.0
        # 选中节点 id（点节点展开描述）；None = 没选中
        self.selected: str | None = None
        self._detail_btn: list[tuple[pygame.Rect, str]] = []

    # ---------- 开关 ----------

    def show(self, tech, screen_size):
        self._tech = tech
        self.open = True
        self.selected = None
        sw, sh = screen_size
        w = min(860, max(340, int(sw * 0.94)))
        h = min(760, max(280, int(sh * 0.94)))
        self.rect = pygame.Rect(0, 0, w, h)
        self.rect.center = (sw // 2, sh // 2)
        self._build_layout()
        self.off_x = 0.0
        self.off_y = 0.0

    def close(self):
        self.open = False
        self._tech = None

    # ---------- 平移（可拖动查看） ----------

    def _build_layout(self):
        """按前置链铺树（M6.28 v3，mod 科技再多也不乱）：

        - 层 = **BFS 最短路径深度**（不是最长前置链）：父子必然相邻层，
          连线只需在"相邻列 52px 空隙"里走，不穿过任何节点。
        - X = 层，Y = 层内堆叠；层内按「父的上一层位置」就近排序，
          再按父的 centery 就近排序，连线交叉最少。
        """
        ids = list(C.TECH_TREE.keys())
        # BFS 分层（有向无环 → 父子必邻层）
        depth: dict[str, int] = {}
        queue = [t for t in ids if not C.TECH_TREE[t][2]]
        for t in queue:
            depth[t] = 0
        head = 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            for tid in ids:
                if tid in depth:
                    continue
                if cur in C.TECH_TREE[tid][2]:
                    depth[tid] = depth[cur] + 1
                    queue.append(tid)
        # 兜底：断层/孤立节点
        for tid in ids:
            if tid not in depth:
                prereqs = C.TECH_TREE[tid][2]
                depth[tid] = 0 if not prereqs \
                    else 1 + max(depth.get(p, 0) for p in prereqs)
        # 父子严格递增修正：BFS 会把"次要父"很浅的子节点压到同层/更浅
        # （如 speed3 被 dyson1 拉进层2，与 speed2 同列）→ 违反则子下移一层。
        # 保证父子之间永远存在列间隙，连线不落在节点列内。
        changed = True
        while changed:
            changed = False
            for tid in ids:
                for p in C.TECH_TREE[tid][2]:
                    if p in depth and depth[tid] <= depth[p]:
                        depth[tid] = depth[p] + 1
                        changed = True
        layers: dict[int, list[str]] = {}
        for tid in ids:
            layers.setdefault(depth[tid], []).append(tid)
        # 层内就近排序：先按父的最小上层位置，再按父的最小 centery
        for d in range(1, max(depth.values()) + 1):
            prev = {t: i for i, t in enumerate(layers[d - 1])}

            def key_func(tid):
                ps = [p for p in C.TECH_TREE[tid][2] if p in prev]
                if not ps:
                    return (0, 0)
                return (min(prev[p] for p in ps),
                        min(layers[d - 1][prev[p]] for p in ps))
            layers[d].sort(key=key_func)
        nodes: dict[str, pygame.Rect] = {}
        for d in range(max(depth.values()) + 1):
            x = PAD + d * (NODE_W + GAP_X)
            y = PAD
            for tid in layers.get(d, []):
                nodes[tid] = pygame.Rect(x, y, NODE_W, NODE_H)
                y += NODE_H + GAP_Y
        self._nodes = nodes
        self._depth = depth
        self._world_w = PAD * 2 + (max(depth.values()) + 1) * NODE_W \
            + max(depth.values()) * GAP_X
        self._world_h = PAD * 2 + max(len(v) for v in layers.values()) \
            * (NODE_H + GAP_Y)

    def drag_by(self, dx: float, dy: float):
        if not self.open:
            return
        self.off_x = max(self._max_off_x, min(0.0, self.off_x + dx))
        self.off_y = max(self._max_off_y, min(0.0, self.off_y + dy))

    def scroll_by(self, dy: float):
        self.drag_by(0.0, dy)   # 滚轮 = 垂直平移（兼容旧调用）

    def _to_screen(self, wx: float, wy: float):
        return int(self.rect.left + wx + self.off_x), \
            int(self.rect.top + wy + self.off_y)

    # ---------- 交互 ----------

    def hit(self, pos) -> bool:
        if not self.open:
            return False
        if not self.rect.collidepoint(pos):
            self.close()
            return True
        if self._close_rect.collidepoint(pos):
            self.close()
            return True
        if self._tech is None:
            return True
        # 描述条的 [研究] 按钮（固定区域，优先于节点）
        for rect, act in self._detail_btn:
            if rect.collidepoint(pos):
                if act == "study" and self.selected in self._nodes:
                    self._tech.start(self.selected)
                return True
        # 点节点 → 展开描述（不直接研究，避免误点）
        for tid, node in self._nodes.items():
            sx, sy = self._to_screen(node.left, node.top)
            if pygame.Rect(sx, sy, node.width, node.height).collidepoint(pos):
                self.selected = tid
                return True
        self.selected = None   # 点空白取消选中
        return True

    # ---------- 绘制 ----------

    def draw(self, screen: pygame.Surface):
        if not self.open or self._tech is None:
            return
        t = self._tech
        r = self.rect
        sw, sh = screen.get_size()

        mask = pygame.Surface((sw, sh), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 110))
        screen.blit(mask, (0, 0))

        panel = pygame.Surface(r.size, pygame.SRCALPHA)
        panel.fill((18, 22, 32, 240))
        screen.blit(panel, r.topleft)
        pygame.draw.rect(screen, (100, 120, 160), r, 2, border_radius=10)

        title_font = self.fonts.get(24)
        big = self.fonts.get(19)
        mid = self.fonts.get(16)
        small = self.fonts.get(14)
        tiny = self.fonts.get(12)

        x0 = r.left + PAD

        # 标题 + 科研包提示
        screen.blit(title_font.render("科技树", True, (235, 215, 140)), (x0, r.top + 10))
        pt_text = "蓝: 电磁矩阵  红: 能量矩阵"
        pw = mid.size(pt_text)[0]
        screen.blit(mid.render(pt_text, True, (150, 190, 230)),
                    (r.right - pw - PAD - 44, r.top + 16))

        # 关闭按钮
        self._close_rect = pygame.Rect(r.right - PAD - 28, r.top + 8, 28, 28)
        pygame.draw.rect(screen, (60, 40, 45), self._close_rect, border_radius=6)
        pygame.draw.rect(screen, (170, 90, 90), self._close_rect, 2, border_radius=6)
        cx, cy = self._close_rect.center
        pygame.draw.line(screen, (230, 140, 140), (cx - 7, cy - 7), (cx + 7, cy + 7), 2)
        pygame.draw.line(screen, (230, 140, 140), (cx - 7, cy + 7), (cx + 7, cy - 7), 2)

        # 当前研究进度 + 队列（顶部固定）
        y = r.top + 44
        bar_w = r.width - PAD * 2
        if t.current is not None:
            name, cost, _, _ = C.TECH_TREE[t.current]
            pack_name = self._pack_name(t.current)
            pct = min(t.progress / cost, 1.0) if cost else 0.0
            pygame.draw.rect(screen, (40, 46, 60), (x0, y, bar_w, 16), border_radius=5)
            pygame.draw.rect(screen, (220, 200, 80),
                             (x0, y, int(bar_w * pct), 16), border_radius=5)
            screen.blit(small.render(
                f"研究中: {name}  {int(t.progress)}/{cost} {pack_name}",
                True, (25, 25, 25)), (x0 + 8, y + 1))
        else:
            screen.blit(small.render("没有在研究任何科技，点点节点看详情并开始研究",
                                     True, (160, 166, 182)), (x0, y - 1))
        if t.queue:
            qtxt = "队列: " + " → ".join(
                C.TECH_TREE[q][0] for q in t.queue[:4] if q in C.TECH_TREE)
            if len(t.queue) > 4:
                qtxt += " …"
            screen.blit(small.render(qtxt, True, (200, 185, 230)),
                        (x0, r.top + 62))

        # ---- 树区（可平移）----
        header_h = 80
        area = pygame.Rect(r.left + 8, r.top + header_h,
                           r.width - 16, r.height - header_h - DETAIL_H - 8)
        self._area = area
        # 平移范围（允许把整棵树看完）
        self._max_off_x = min(0.0, area.width - self._world_w - PAD)
        self._max_off_y = min(0.0, area.height - self._world_h - PAD)
        self.off_x = max(self._max_off_x, min(0.0, self.off_x))
        self.off_y = max(self._max_off_y, min(0.0, self.off_y))

        clip_prev = screen.get_clip()
        screen.set_clip(area)

        # 连线（先画，节点盖在上层）。每个子只画一条"主路径线"连到
        # 最深父（严格递增后必在子左邻列）→ 三段全走列空隙，零穿节点；
        # 其余前置照旧列在描述条里。
        for tid, node in self._nodes.items():
            ps = [p for p in C.TECH_TREE[tid][2] if p in self._nodes]
            if not ps:
                continue
            pid = max(ps, key=lambda p: self._depth.get(p, -1))
            parent = self._nodes[pid]
            mx, my = (parent.right + node.left) // 2, parent.centery
            px, py = self._to_screen(parent.right, parent.centery)
            m1x, m1y = self._to_screen(mx, my)
            m2x, m2y = self._to_screen(mx, node.centery)
            nx, ny = self._to_screen(node.left + 8, node.centery)
            pts = [(px, py), (m1x, m1y), (m2x, m2y), (nx, ny)]
            pygame.draw.lines(screen, (85, 100, 130), False, pts, 2)

        # 节点
        for tid, node in self._nodes.items():
            sx, sy = self._to_screen(node.left, node.top)
            scr = pygame.Rect(sx, sy, node.width, node.height)
            if not area.colliderect(scr):
                continue
            self._draw_node(screen, scr, tid, t, big, mid, small)

        screen.set_clip(clip_prev)

        # ---- 描述条（选中节点展开）----
        self._detail_btn.clear()
        drect = pygame.Rect(r.left + 8, area.bottom + 2, r.width - 16, DETAIL_H - 10)
        pygame.draw.rect(screen, (16, 22, 34), drect, border_radius=8)
        if self.selected and self.selected in self._nodes:
            self._draw_detail(screen, drect, self.selected, t, small, tiny, mid)
        else:
            screen.blit(tiny.render("点一个科技节点展开描述", True, (110, 116, 132)),
                        (drect.left + 12, drect.top + 10))
        screen.blit(tiny.render("拖动平移 · 滚轮上下 · 点面板外或 ✕ 关闭 · 游戏继续运行",
                                True, (100, 106, 122)),
                    (r.left + PAD, r.bottom - 20))

    def _node_state(self, tid, t):
        """返回 (bg, border, accent, status, clickable)。"""
        done = tid in t.researched
        researching = t.current == tid
        queued = tid in t.queue
        can, _ = t.can_research(tid)
        qcan, _ = t.can_queue(tid)
        if done:
            return (26, 46, 34), (70, 170, 105), (110, 220, 150), "✓ 已完成", False
        if researching:
            return (46, 42, 24), (200, 180, 70), (235, 210, 90), "▶ 研究中", True
        if queued:
            return (40, 34, 52), (170, 130, 220), (210, 180, 240), "… 排队中", True
        if can or qcan:
            return (30, 38, 54), (100, 150, 210), (180, 210, 240), "○ 可研究", True
        return (24, 26, 34), (55, 60, 74), (110, 116, 130), "✗ 未解锁", False

    def _draw_node(self, screen, card, tech_id, t, big, mid, small):
        name, cost, _, desc = C.TECH_TREE[tech_id]
        bg, border, accent, status, _ = self._node_state(tech_id, t)

        pygame.draw.rect(screen, bg, card, border_radius=7)
        pygame.draw.rect(screen, border, card, 2, border_radius=7)
        if self.selected == tech_id:
            pygame.draw.rect(screen, (250, 230, 120), card, 3, border_radius=7)

        pack_name = self._pack_name(tech_id)
        if tech_id in t.researched:
            cost_text, cost_color = "已完成", (110, 170, 130)
        elif t.current == tech_id:
            cost_text = f"{int(t.progress)}/{cost} {pack_name}"
            cost_color = (235, 210, 90)
        else:
            cost_text = f"{cost} × {pack_name}"
            cost_color = (170, 176, 192)

        st = small.render(status, True, border)
        screen.blit(big.render(name, True, accent), (card.left + 10, card.top + 4))
        screen.blit(st, (card.right - st.get_width() - 10, card.top + 8))
        screen.blit(mid.render(cost_text, True, cost_color),
                    (card.left + 10, card.top + 32))
        screen.blit(small.render(desc, True, (130, 136, 152)),
                    (card.left + 10, card.top + 48))

    def _draw_detail(self, screen, d, tech_id, t, small, tiny, mid):
        name, cost, prereqs, desc = C.TECH_TREE[tech_id]
        _, _, _, status, clickable = self._node_state(tech_id, t)
        pack_name = self._pack_name(tech_id)

        x = d.left + 12
        screen.blit(mid.render(f"{name}  [{status}]", True, (235, 220, 160)),
                    (x, d.top + 6))
        if prereqs:
            pre = " + ".join(C.TECH_TREE[p][0] for p in prereqs if p in C.TECH_TREE)
            screen.blit(small.render(f"前置: {pre}", True, (150, 160, 180)),
                        (x + 10, d.top + 28))
        y2 = d.top + 28
        # 描述 + 科研包需求挤在第二行
        req_txt = f"需要 {cost} × {pack_name}"
        ok = all(p in t.researched for p in prereqs)
        color = (170, 200, 120) if (ok or not prereqs) else (210, 160, 90)
        screen.blit(small.render(f"{req_txt} · {desc}", True, color),
                    (x + 10, y2))

        if tech_id not in t.researched:
            if t.current == tech_id:
                label = "研究中…"
            elif clickable:
                label = "开始研究" if t.current is None else "排队研究"
            else:
                label = "前置未满足"
            btn = pygame.Rect(d.right - 122, d.top + 10, 108, 26)
            pygame.draw.rect(screen, (56, 100, 118) if clickable else (46, 50, 60),
                             btn, border_radius=5)
            t_ = tiny.render(label, True, (235, 240, 250))
            screen.blit(t_, (btn.centerx - t_.get_width() // 2,
                             btn.centery - t_.get_height() // 2))
            if clickable:
                self._detail_btn.append((btn, "study"))

    def _pack_name(self, tech_id: str) -> str:
        rid = C.TECH_PACK_RECIPE.get(tech_id)
        r = C.RECIPES.get(rid) if rid else None
        if r is None:
            return "科研包"
        for item in r[1]:
            return C.ITEM_NAMES.get(item, "科研包")
        return "科研包"