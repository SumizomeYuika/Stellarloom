"""字体加载：中文字体多路径回退。

pygame 默认字体不含中文，必须显式加载系统 CJK 字体。
不同平台路径不同，按优先级依次尝试。
"""

from __future__ import annotations

import os

import pygame

# 按优先级排列。Android 的 .ttc 需要 index，pygame 支持传 index 参数。
CJK_CANDIDATES = [
    # Android
    ("/system/fonts/NotoSansCJK-Regular.ttc", 0),
    ("/system/fonts/NotoSerifCJK-Regular.ttc", 0),
    # Windows
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", 0),
    # Linux
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
]


class FontBook:
    """按字号缓存字体对象，避免每帧新建。"""

    def __init__(self):
        self.path, self.index = self._find()
        self._cache: dict[int, pygame.font.Font] = {}

    def _find(self):
        for path, index in CJK_CANDIDATES:
            if os.path.exists(path):
                try:
                    f = pygame.font.Font(path, 20)
                    # 尝试渲染中文，字形缺失时 pygame 返回的是空白/方块，
                    # 这里只能靠路径信任，做不到精确校验
                    f.render("测试", True, (255, 255, 255))
                    return path, index
                except (OSError, pygame.error):
                    continue
        return None, 0

    def get(self, size: int) -> pygame.font.Font:
        f = self._cache.get(size)
        if f is not None:
            return f
        if self.path:
            try:
                f = pygame.font.Font(self.path, size)
            except (OSError, pygame.error):
                f = pygame.font.Font(None, size)
        else:
            f = pygame.font.Font(None, size)
        self._cache[size] = f
        return f

    @property
    def ok(self) -> bool:
        return self.path is not None