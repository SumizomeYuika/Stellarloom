"""塔库存面板：点塔弹出，显示库存、无人机、过滤设置。

简化版：面板是半透明浮窗，点外部关闭，点物品图标切换过滤。

M6.26：标题/配色走 `defs/tower_panel.json`（theme.json 兜底皮肤化）；
库存行/无人机条是动态内容，业务画但颜色全取 meta_c。
"""

from __future__ import annotations

import pygame

from .. import config as C
from . import uidef


class TowerPanel:
    """塔详情面板。Game 持有实例，open(tower) 打开，close() 关闭。"""

    def __init__(self, fonts):
        self.fonts = fonts
        self.defs = uidef.load_def("tower_panel.json")
        self.tower = None  # 当前打开的 Tower 对象
        self.rect = pygame.Rect(0, 0, 320, 280)
        # 物品图标区域（点击切换过滤）
        self._item_rects: list[tuple[pygame.Rect, int]] = []

    @property
    def open(self) -> bool:
        return self.tower is not None

    def show(self, tower, screen_size):
        self.tower = tower
        sw, sh = screen_size
        self.rect.center = (sw // 2, sh // 2)
        self.rect.size = self._size_for(sw, sh)

    def _size_for(self, sw: int, sh: int):
        w = min(320, int(sw * 0.70))
        h = min(280, int(sh * 0.62))
        return (w, h)

    def close(self):
        self.tower = None

    def hit(self, pos) -> bool:
        """处理点击。返回 True 表示消费了这次点击。"""
        if self.tower is None:
            return False
        if not self.rect.collidepoint(pos):
            # 点外部 → 关闭
            self.close()
            return True
        # 点物品图标 → 切换过滤
        for rect, item_id in self._item_rects:
            if rect.collidepoint(pos):
                if self.tower.filter == item_id:
                    self.tower.filter = None
                else:
                    self.tower.filter = item_id
                return True
        return True  # 点在面板空白处也消费掉，不穿透

    def draw(self, screen: pygame.Surface):
        if self.tower is None:
            return
        t = self.tower
        r = self.rect
        m = self.defs.meta_c
        # M6.28 窗口化：底/边框/标题栏统一画（标题文字走 defs title 控件）
        uidef.draw_window(screen, self.defs, r, self.fonts)

        # 静态控件（标题走 defs，颜色按塔类型动态覆盖）
        overrides = {"text": {}, "color": {}}
        title = "供应塔" if t.mode == "supply" else "请求塔"
        overrides["text"]["title"] = f"{title} ({t.x},{t.y})"
        overrides["color"]["title"] = m["title_supply"] if t.mode == "supply" \
            else m["title_request"]
        uidef.draw_controls(screen, self.defs, r, self.fonts, overrides)

        small = self.fonts.get(15)
        y = r.top + 66   # 库存标题下方（stock_h y=44 h≈18 → 66）

        # 库存列表（动态行）
        self._item_rects.clear()
        if not t.inventory:
            screen.blit(small.render("  (空)", True, m["hint"]),
                        (r.left + 20, y))
            y += 20
        else:
            for item_id, count in t.inventory.items():
                name = C.ITEM_NAMES.get(item_id, f"?{item_id}")
                color = C.ITEM_COLORS.get(item_id, (200, 200, 200))
                # 物品色块
                icon = pygame.Rect(r.left + 20, y, 18, 18)
                pygame.draw.rect(screen, color, icon)
                # 过滤高亮框
                if t.filter == item_id:
                    pygame.draw.rect(screen, m["filter_frame"],
                                     icon.inflate(4, 4), 2)
                self._item_rects.append((icon, item_id))
                text = f"{name}  ×{count}"
                screen.blit(small.render(text, True, m["text"]),
                            (r.left + 46, y + 1))
                y += 22

        y += 8
        # 过滤状态
        if t.filter is None:
            ftext = "过滤: 不限"
        else:
            fname = C.ITEM_NAMES.get(t.filter, "?")
            ftext = f"过滤: 只收 {fname}"
        screen.blit(small.render(ftext + "  (点物品图标切换)", True, m["hint"]),
                    (r.left + 14, y))
        y += 24

        # 无人机状态
        drones = getattr(t, "drones", [])
        screen.blit(small.render(f"无人机: {len(drones)} 架", True, m["text"]),
                    (r.left + 14, y))
        y += 20
        for i, d in enumerate(drones[:4]):  # 最多显示 4 架
            e = d.energy_ratio
            bar_w = int(100 * e)
            bar_color = m["bar_high"] if e > 0.5 else (
                m["bar_mid"] if e > 0.2 else m["bar_low"])
            state_name = {0: "待命", 1: "取货", 2: "送货",
                          3: "返回", 4: "充电"}.get(d.state, "?")
            pygame.draw.rect(screen, m["drone_bar_bg"],
                             (r.left + 20, y + 3, 100, 8))
            pygame.draw.rect(screen, bar_color, (r.left + 20, y + 3, bar_w, 8))
            screen.blit(small.render(f"#{i+1} {state_name}", True, m["text"]),
                        (r.left + 130, y))
            y += 18

        # 底部提示
        screen.blit(small.render("点面板外关闭", True, m["hint"]),
                    (r.left + 14, r.bottom - 24))