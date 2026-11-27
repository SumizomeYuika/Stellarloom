"""世界层 GL 四边面批量绘制：把星织的格子数据变成 gbuffer 顶点。

设计取舍（用户已确认）：
- 星织是俯视 2D，没有真三维。这里给每格画**一个朝向 +Z 的四边面**，
  高度按"层"堆叠：地面层 z=0，建筑层 z=0.35，液体层 z=0.15，物品层 z=0.6。
  这样 gbuffer 的深度通道里有真实的远近关系，TAA / SSR / 雾才有东西可算。
- 法线统一朝上 (0,0,1)。虽然物理上不对，但包里所有光照都把"朝上的面"
  当主受光面处理，视觉上最接近。
- 世界是环形卷绕的（星织 camera 用 % world_pw 卷绕），所以要把每格
  在 ±1 个世界宽高内重复三次，保证屏幕边缘不出现空洞。

顶点布局（20 float / 顶点，6 顶点 / 格）。compatibility profile 下
内建属性走 **client-state 固定管线指针**（绘制时现场设置，见
passes.FullscreenQuad.draw_geometry），VAO 里只保留唯一的 generic
属性 mc_Entity（偏移 64，attrib 4，由 GEO_ATTRS 绑定）：

  字节 0   gl_Vertex          vec4  (x, y, z, 1)     世界坐标（相机相对）
  字节 16  gl_MultiTexCoord0  vec4  (u, v, 0, 0)     格子内部 UV
  字节 32  gl_Color           vec4  (r, g, b, a)     albedo * 顶点色
  字节 48  gl_MultiTexCoord1  vec4  (u, v, 0, 1)     原始 lmcoord（经
                                                     gl_TextureMatrix[1] 变换）
  字节 64  mc_Entity          vec4  (id, 0, 0, 0)    方块 id；给 -1 →
                                                     不命中任何植被族

共 20 float / 顶点，6 顶点 / 格 → 一屏 4000 格约 480K float。
mc_Entity 给 -1 是故意的：包里 WAVING_PLANTS 靠 isVegetationId(mc_Entity.x)
判定，-1 永不命中 → 星织的方格不会被"风吹"歪。那条分支在函数里就返回了，
零开销。

性能：整块 VBO 每帧重填。glBufferData 走 driver 的 orphaning 路径，不阻塞。
"""

import ctypes

from . import glapi

FLOATS_PER_VERT = 20
VERTS_PER_CELL = 6

# 层高（世界单位，格子边长 = 1）
Z_GROUND = 0.0
Z_FLUID = 0.15
Z_BUILDING = 0.35
Z_ITEM = 0.60


class WorldGeometry:
    """把格子数据烘成顶点数组，并维护 VBO。"""

    def __init__(self, api, quad):
        self.api = api
        self.quad = quad
        self.vbo = 0
        self.capacity = 0        # 已分配的顶点数
        self.count = 0           # 当前有效顶点数
        self.cells = 0
        self._dirty = True       # 世界变了要重烘（建筑增删 → 置 True）
        self._last_key = None    # 上次烘焙的 (cam tile, zoom, size)
        self._setup()

    def mark_dirty(self):
        """外部钩子：世界内容变了（ChunkRenderer._build 被触发），下帧重烘。"""
        self._dirty = True

    def _setup(self):
        api = self.api
        vid = glapi.c_uint(0)
        api.glGenVertexArrays(1, glapi.byref(vid))
        self.quad.geo_vao = vid.value
        api.glBindVertexArray(self.quad.geo_vao)
        bid = glapi.c_uint(0)
        api.glGenBuffers(1, glapi.byref(bid))
        self.vbo = bid.value
        self.quad.geo_vbo = bid.value
        api.glBindBuffer(glapi.GL_ARRAY_BUFFER, self.vbo)
        stride = FLOATS_PER_VERT * 4
        # VAO 只持 mc_Entity（generic attrib 4，offset 64）；
        # gl_Vertex/gl_Color/gl_MultiTexCoord0/1 是固定管线内建属性，
        # 由 draw_geometry 里的 client-state 指针喂，不进 VAO。
        api.glEnableVertexAttribArray(4)
        api.glVertexAttribPointer(4, 4, glapi.GL_FLOAT, glapi.GL_FALSE,
                                  stride, ctypes.c_void_p(16 * 4))
        api.glBindVertexArray(0)

    # ---------------------------------------------------------- 顶点生成
    def build(self, grid, camera, screen_size, opts=None):
        """从格子数据生成顶点。返回写入的格数。

        grid: 星织 Grid（含 building/ore/direction/overlay 等 ndarray）
        camera: 星织 Camera
        screen_size: (w, h)
        opts: dict，可含 show_ore / show_fluid / show_items
        """
        import numpy as np
        from stellarloom import config as C

        # 几何缓存：相机没挪、缩放没变、世界没脏 → 直接复用上次烘的 VBO。
        # world.build 的 numpy 烘焙在 Intel 核显机上实测 ~9ms/帧，静止时
        # 全省掉。相机移动阈值取 1/64 格（肉眼不可见但插值平滑）。
        opts = opts or {}
        key = (round(camera.x / C.TILE * 64), round(camera.y / C.TILE * 64),
               round(camera.zoom * 256), tuple(screen_size))
        if not getattr(self, "_dirty", True) \
                and key == getattr(self, "_last_key", None) and self.count > 0:
            self.quad.geo_count = self.count
            return self.cells
        self._dirty = False
        self._last_key = key

        sw, sh = screen_size
        zoom = camera.zoom
        tile_px = max(1, int(round(C.TILE * zoom)))
        gw, gh = grid.w, grid.h

        # 屏幕覆盖的格范围（含 1 格余量）
        cam_cx = camera.x / C.TILE
        cam_cy = camera.y / C.TILE
        half_w = sw / tile_px / 2 + 1
        half_h = sh / tile_px / 2 + 1
        gx0 = int(cam_cx - half_w)
        gx1 = int(cam_cx + half_w) + 1
        gy0 = int(cam_cy - half_h)
        gy1 = int(cam_cy + half_h) + 1

        # 卷绕重复：gx 超出 [0,gw) 时靠 % gw 取格子，天然无缝。
        # 但不用 clamp 到世界内——那样屏幕比世界大时边缘会缺格。
        # 只限制"最多画一整个世界宽 + 余量"，防止小世界 + 高缩放下画几万格。
        max_span = gw + 4
        if gx1 - gx0 + 1 > max_span:
            gap = max_span // 2
            gx0 = int(cam_cx) - gap
            gx1 = gx0 + max_span - 1
        max_span = gh + 4
        if gy1 - gy0 + 1 > max_span:
            gap = max_span // 2
            gy0 = int(cam_cy) - gap
            gy1 = gy0 + max_span - 1
        w_cells = gx1 - gx0 + 1
        h_cells = gy1 - gy0 + 1
        if w_cells <= 0 or h_cells <= 0:
            self.count = 0
            self.quad.geo_count = 0
            return 0

        # 世界坐标：格子 (gx,gy) 中心 = (gx+0.5, gy+0.5)。
        # 相机在 (cam_cx, cam_cy)。送进 shader 的是"相机相对"世界坐标，
        # 与 MC 的 gbufferModelView 语义一致（相机在原点）。
        # 半格偏移让格子边界落在整数上，UV 也能对齐。
        xs = np.arange(gx0, gx1 + 1, dtype=np.int32)
        ys = np.arange(gy0, gy1 + 1, dtype=np.int32)
        gxi = (xs % gw).astype(np.int32)
        gyi = (ys % gh).astype(np.int32)

        b = grid.building[np.ix_(gyi, gxi)]
        ore = grid.ore[np.ix_(gyi, gxi)]
        ore_t = grid.ore_type[np.ix_(gyi, gxi)]
        ovl = grid.overlay[np.ix_(gyi, gxi)]

        # 颜色表：id -> (r,g,b)，做成 ndarray 查表
        max_bid = max(int(b.max(initial=0)), len(C.BUILDING_COLORS) + 8) + 2
        blut = np.zeros((max_bid, 3), dtype=np.float32)
        for bid, rgb in C.BUILDING_COLORS.items():
            if bid < max_bid:
                blut[bid] = [c / 255.0 for c in rgb]
        max_oid = max(int(ore_t.max(initial=0)), 4) + 2
        olut = np.zeros((max_oid, 3), dtype=np.float32)
        for oid, rgb in C.ORE_COLORS.items():
            if oid < max_oid:
                olut[oid] = [c / 255.0 for c in rgb]
        olut_fallback = np.array([c / 255.0 for c in C.ORE_FALLBACK_COLOR],
                                 dtype=np.float32)

        # ---- 地面层：每格一个面，底色偏暗（模拟地表）
        base = np.array([c / 255.0 for c in C.C_BG], dtype=np.float32)
        grid_col = base + 0.045           # 网格线稍微亮一点，让地面有纹理感
        has_b = b > 0
        has_ore = (ore > 0) & (~has_b)
        # 有建筑或矿的格子地面压暗一点（视觉上有落差）
        ground_rgb = np.where(has_b[:, :, None] | has_ore[:, :, None],
                              grid_col * 0.7, grid_col).astype(np.float32)

        quads = []

        def emit(layer_rgb, zlayer, alpha=1.0, uv_scale=1.0):
            """为一整张 (h,w) 的颜色图生成四边面。"""
            h, w = layer_rgb.shape[0], layer_rgb.shape[1]
            if h == 0 or w == 0:
                return
            # 世界坐标网格（相机相对）
            wx = (xs[None, :].astype(np.float32) - cam_cx)
            wy = (ys[:, None].astype(np.float32) - cam_cy)
            # 四角偏移（格子占 [gx,gx+1] 所以相对中心是 ±0.5）
            x0 = wx - 0.5
            x1 = wx + 0.5
            y0 = wy - 0.5
            y1 = wy + 0.5
            # 广播到 (h,w)
            X0 = np.broadcast_to(x0, (h, w))
            X1 = np.broadcast_to(x1, (h, w))
            Y0 = np.broadcast_to(y0, (h, w))
            Y1 = np.broadcast_to(y1, (h, w))
            Z = np.full((h, w), zlayer, dtype=np.float32)
            W = np.ones((h, w), dtype=np.float32)

            # 每一格 6 个顶点（两个三角）：左下、右下、左上 / 右下、右上、左上
            # 顺序保证 CCW 朝 +Z
            corner = np.stack([
                np.stack([X0, Y0, Z, W], -1),   # 0 左下
                np.stack([X1, Y0, Z, W], -1),   # 1 右下
                np.stack([X0, Y1, Z, W], -1),   # 2 左上
                np.stack([X1, Y0, Z, W], -1),
                np.stack([X1, Y1, Z, W], -1),
                np.stack([X0, Y1, Z, W], -1),
            ], axis=2)                       # (h,w,6,4)
            uv = np.array([[0, 0], [1, 0], [0, 1],
                           [1, 0], [1, 1], [0, 1]], dtype=np.float32)
            UV = np.broadcast_to(uv * uv_scale, (h, w, 6, 2))
            UV4 = np.concatenate([UV, np.zeros((h, w, 6, 2), dtype=np.float32)],
                                 axis=-1)     # slm_uv0 = (u, v, 0, 0)
            COL = np.broadcast_to(
                np.concatenate([layer_rgb,
                                np.full((h, w, 1), alpha, dtype=np.float32)],
                               axis=-1)[:, :, None, :], (h, w, 6, 4))
            # slm_uv1 = 原始 lmcoord (u, v, 0, 1)，经 slm_texmat1 变换
            # 方块光 0.85 / 天光 1.0：露天全亮，不出现洞里的黑块
            LM = np.zeros((h, w, 6, 4), dtype=np.float32)
            LM[:, :, :, 0] = 0.85
            LM[:, :, :, 1] = 1.0
            LM[:, :, :, 3] = 1.0
            # mc_Entity = (-1, 0, 0, 0)：不命中任何植被 ID，方格不会被风吹歪
            ENT = np.full((h, w, 6, 4), -1.0, dtype=np.float32)
            ENT[:, :, :, 1:] = 0.0

            buf = np.concatenate([corner.reshape(-1, 4),
                                  UV4.reshape(-1, 4),
                                  COL.reshape(-1, 4),
                                  LM.reshape(-1, 4),
                                  ENT.reshape(-1, 4)], axis=1)
            quads.append(buf.astype(np.float32))

        # 1) 地面（全格发面，是背景层）
        emit(ground_rgb, Z_GROUND)

        # 2) 矿脉层（只给有矿的格发面，浮 0.02 避免 z-fighting）
        if has_ore.any() and opts.get("show_ore", True):
            ot_flat = ore_t.astype(np.int32)
            valid = (ot_flat >= 0) & (ot_flat < max_oid)
            oc = np.empty((*ore.shape, 3), dtype=np.float32)
            oc[:] = olut_fallback
            oc[valid] = olut[ot_flat[valid]]
            _emit_masked(quads, xs, ys, cam_cx, cam_cy, has_ore,
                         oc[has_ore], Z_GROUND + 0.02)

        # 3) 建筑层
        if has_b.any():
            bi = np.clip(b, 0, max_bid - 1)
            _emit_masked(quads, xs, ys, cam_cx, cam_cy, has_b,
                         blut[bi][has_b], Z_BUILDING)

        # 4) 叠层（传送带上的物品标记等）用一个更高、更亮的薄面表示
        has_ov = ovl > 0
        if has_ov.any() and opts.get("show_items", True):
            oc = np.tile(np.array([1.0, 0.88, 0.45], dtype=np.float32),
                         (*ovl.shape, 1))
            _emit_masked(quads, xs, ys, cam_cx, cam_cy, has_ov,
                         oc[has_ov], Z_ITEM)

        # ---- 合并上传
        if not quads:
            self.count = 0
            self.quad.geo_count = 0
            return 0
        data = np.concatenate(quads, axis=0)
        self.count = data.shape[0]
        self.quad.geo_count = self.count
        self.cells = self.count // VERTS_PER_CELL
        self._upload(data)
        return self.cells

    def _upload(self, data):
        api = self.api
        api.glBindVertexArray(self.quad.geo_vao)
        api.glBindBuffer(glapi.GL_ARRAY_BUFFER, self.vbo)
        nbytes = data.nbytes
        ptr = data.ctypes.data_as(ctypes.c_void_p)
        # 容量不够就重新分配（用 STREAM_DRAW 因为每帧都换）
        if self.count > self.capacity:
            api.glBufferData(glapi.GL_ARRAY_BUFFER, nbytes, ptr,
                             glapi.GL_STREAM_DRAW)
            self.capacity = self.count
        else:
            api.glBufferSubData(glapi.GL_ARRAY_BUFFER, 0, nbytes, ptr)
        api.glBindVertexArray(0)

    def release(self):
        if self.vbo:
            self.api.glDeleteBuffers(1, glapi.byref(glapi.c_uint(self.vbo)))
            self.vbo = 0
            self.quad.geo_vbo = 0


def _emit_masked(quads, xs, ys, cam_cx, cam_cy, mask, colors, z):
    """只为 mask 为真的格子发面，颜色按 mask 的展开顺序对应。"""
    import numpy as np
    iy, ix = np.nonzero(mask)
    if iy.size == 0:
        return
    wx = xs[ix].astype(np.float32) - cam_cx
    wy = ys[iy].astype(np.float32) - cam_cy
    n = wx.size
    X0 = wx - 0.5
    X1 = wx + 0.5
    Y0 = wy - 0.5
    Y1 = wy + 0.5
    Z = np.full(n, z, dtype=np.float32)
    W = np.ones(n, dtype=np.float32)

    corner = np.stack([
        np.stack([X0, Y0, Z, W], -1),
        np.stack([X1, Y0, Z, W], -1),
        np.stack([X0, Y1, Z, W], -1),
        np.stack([X1, Y0, Z, W], -1),
        np.stack([X1, Y1, Z, W], -1),
        np.stack([X0, Y1, Z, W], -1),
    ], axis=1)                     # (n,6,4)
    uv = np.array([[0, 0], [1, 0], [0, 1], [1, 0], [1, 1], [0, 1]],
                  dtype=np.float32)
    UV = np.broadcast_to(uv, (n, 6, 2))
    UV4 = np.concatenate([UV, np.zeros((n, 6, 2), dtype=np.float32)], axis=-1)
    col4 = np.concatenate([colors,
                           np.ones((n, 1), dtype=np.float32)], axis=1)
    COL = np.broadcast_to(col4[:, None, :], (n, 6, 4))
    LM = np.zeros((n, 6, 4), dtype=np.float32)
    LM[:, :, 0] = 0.85
    LM[:, :, 1] = 1.0
    LM[:, :, 3] = 1.0
    ENT = np.full((n, 6, 4), -1.0, dtype=np.float32)
    ENT[:, :, 1:] = 0.0
    buf = np.concatenate([corner.reshape(-1, 4), UV4.reshape(-1, 4),
                          COL.reshape(-1, 4), LM.reshape(-1, 4),
                          ENT.reshape(-1, 4)], axis=1)
    quads.append(buf.astype(np.float32))