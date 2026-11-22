"""世界层顶点生成的自检：不碰 GL，纯 numpy 校验坐标与数量。

跑法：python3 devtools/_worldcheck.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.dirname(os.path.dirname(ROOT))     # mods/shaderbridge -> 游戏根
sys.path.insert(0, ROOT)
sys.path.insert(0, GAME)

import numpy as np                                  # noqa: E402

from stellarloom import config as C                  # noqa: E402
from stellarloom.world.grid import WorldGrid         # noqa: E402
from stellarloom.render.camera import Camera         # noqa: E402

from core import world_gl                            # noqa: E402


class FakeQuad:
    geo_count = 0
    geo_vao = 0
    geo_vbo = 0


class FakeGeo(world_gl.WorldGeometry):
    """只测顶点生成，把上传拦下来。"""

    def __init__(self):
        self.api = None
        self.quad = FakeQuad()
        self.vbo = 0
        self.capacity = 0
        self.count = 0
        self.cells = 0
        self.last_data = None

    def _upload(self, data):
        self.last_data = data


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    return cond


def main():
    ok = True
    g = WorldGrid(64, 64, seed=7)
    # 相机默认在世界中心 (32,32)，建筑要放在视野内才测得出来
    g.building[32, 30] = C.B_BELT
    g.building[32, 31] = C.B_MINER
    g.ore[30, 32] = 100
    g.ore_type[30, 32] = 0
    g.overlay[34, 34] = 1

    cam = Camera(64 * C.TILE, 64 * C.TILE)
    cam.zoom = 0.75
    geo = FakeGeo()

    print("== 小屏（800x600），世界 64x64 ==")
    n = geo.build(g, cam, (800, 600))
    data = geo.last_data
    ok &= check(data is not None, "生成了顶点数据")
    if data is None:
        return 1

    print("  顶点数 %d，格数 %d，浮点/顶点 %d"
          % (data.shape[0], n, data.shape[1]))
    ok &= check(data.shape[1] == world_gl.FLOATS_PER_VERT,
                "每顶点 float 数 = %d" % world_gl.FLOATS_PER_VERT)
    ok &= check(data.shape[0] == n * world_gl.VERTS_PER_CELL,
                "顶点数 = 格数 × 6")

    # 布局（FLOATS_PER_VERT=20）：
    #   0:4  slm_vertex (x,y,z,w)
    #   4:8  slm_uv0    (u,v,0,0)
    #   8:12 slm_color  (r,g,b,a)
    #   12:16 slm_uv1   (u,v,0,1)   ← lmcoord
    #   16:20 mc_Entity (id,0,0,0)
    pos = data[:, 0:4]
    print("  位置范围 x[%.2f, %.2f] y[%.2f, %.2f] z[%.2f, %.2f]"
          % (pos[:, 0].min(), pos[:, 0].max(),
             pos[:, 1].min(), pos[:, 1].max(),
             pos[:, 2].min(), pos[:, 2].max()))
    ok &= check(np.allclose(pos[:, 3], 1.0), "slm_vertex.w 全为 1")
    # 相机在中心，世界只有 64 格宽，屏幕 800/18≈44 格宽，所以坐标不会太离谱
    ok &= check(abs(pos[:, 0]).max() < 40, "x 在 ±40 格内（相机相对）")
    ok &= check(abs(pos[:, 1]).max() < 40, "y 在 ±40 格内")

    zs = np.unique(pos[:, 2])
    print("  出现的 z 层: %s" % zs.tolist())
    ok &= check(world_gl.Z_GROUND in zs, "地面层存在")
    ok &= check(any(abs(z - world_gl.Z_BUILDING) < 1e-5 for z in zs),
                "建筑层 z=%.2f 存在" % world_gl.Z_BUILDING)
    ok &= check(any(abs(z - world_gl.Z_ITEM) < 1e-5 for z in zs),
                "物品层 z=%.2f 存在" % world_gl.Z_ITEM)
    # 建筑段颜色应来自 BUILDING_COLORS，且不等于地面色
    bmask = np.abs(pos[:, 2] - world_gl.Z_BUILDING) < 1e-5
    if bmask.any():
        belt_rgb = np.array([c / 255.0 for c in C.C_BELT])
        miner_rgb = np.array([c / 255.0 for c in C.C_MINER])
        got = data[bmask][:, 8:11]
        hit = np.isclose(got, belt_rgb, atol=1e-6).all(-1).any() or \
            np.isclose(got, miner_rgb, atol=1e-6).all(-1).any()
        ok &= check(hit, "建筑顶点色 = C_BELT 或 C_MINER")
        print("  建筑顶点数 %d，样例色 %s" % (bmask.sum(),
                                            np.round(got[:2], 4).tolist()))

    # mc_Entity 必须全 -1（mx 分量），否则会被植被判定命中、被风吹歪
    ent = data[:, 16:20]
    ok &= check(np.allclose(ent[:, 0], -1.0), "mc_Entity.x 全为 -1（不命中植被）")
    ok &= check(np.allclose(ent[:, 1:], 0.0), "mc_Entity.yzw 全为 0")

    # lmcoord（slm_uv1）必须在 [0,1] 且 w=1
    lm = data[:, 12:16]
    ok &= check(lm[:, :2].min() >= 0.0 and lm[:, :2].max() <= 1.0,
                "lmcoord xy 在 [0,1]")
    ok &= check(np.allclose(lm[:, 3], 1.0), "lmcoord w 全为 1")

    # UV 必须在 [0,1]
    uv = data[:, 4:6]
    ok &= check(uv.min() >= 0.0 and uv.max() <= 1.0, "UV 在 [0,1]")

    # alpha 通道
    ok &= check(np.allclose(data[:, 11], 1.0), "albedo alpha 全为 1")

    print("\n== 世界比屏幕小（64 格世界，2000x1500 屏幕）==")
    cam2 = Camera(64 * C.TILE, 64 * C.TILE)
    cam2.zoom = 1.0
    geo2 = FakeGeo()
    n2 = geo2.build(g, cam2, (2000, 1500))
    d2 = geo2.last_data
    ok &= check(d2 is not None, "大屏也生成了顶点")
    if d2 is not None:
        p2 = d2[:, 0:2]
        print("  格数 %d，x[%.1f,%.1f] y[%.1f,%.1f]"
              % (n2, p2[:, 0].min(), p2[:, 0].max(),
                 p2[:, 1].min(), p2[:, 1].max()))
        # 屏幕 2000/24≈83 格宽 > 世界 64 格 → 必须靠卷绕重复铺满
        ok &= check(n2 >= 64 * 64, "格数 ≥ 世界面积（卷绕重复生效）")
        spanx = p2[:, 0].max() - p2[:, 0].min()
        ok &= check(spanx >= 64, "x 跨度覆盖整个世界（%.1f 格）" % spanx)

    print("\n== 空世界 ==")
    g3 = WorldGrid(16, 16, seed=1)
    geo3 = FakeGeo()
    n3 = geo3.build(g3, Camera(16 * C.TILE, 16 * C.TILE), (400, 300))
    ok &= check(geo3.last_data is not None and n3 > 0,
                "空世界也画地面（%d 格）" % n3)

    print("\n" + ("全部通过" if ok else "有失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())