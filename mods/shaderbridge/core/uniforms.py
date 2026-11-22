"""OptiFine / Iris uniform 供给：把星织的相机与时间状态变成 shader 能用的量。

这是"假 gbuffer 也能让光影包看着像样"的关键一层。包里假设的是一套
MC 三维世界（视图矩阵、投影矩阵、太阳方向、阴影贴图），星织一个都没有，
所以这里做两类事：

1. **真数值**：能算准的都算准——视口尺寸、时间、相机平移（转成视图矩阵）、
   太阳角度（星织有昼夜循环就取它，没有就用真实时间）。
2. **合理默认**：算不准的给一套能出图的值。比如阴影贴图矩阵用一个
   正交投影覆盖当前视野，深度范围按看得见的格数估。

投影设计：星织是俯视 2D，我用**正射投影**——这跟 MC 的透视投影不同，
但正射才是这个游戏的正确视觉模型。z 从 -1 到 +1 映射到我们堆叠的
0..0.6 层高，深度精度足够区分地面/建筑/物品三层。

重要：投影矩阵是列主序（GL 约定），m[col*4+row]。
"""

import math


def ortho(l, r, b, t, n, f):
    """正射投影矩阵（列主序）。"""
    return [
        2.0 / (r - l), 0.0, 0.0, 0.0,
        0.0, 2.0 / (t - b), 0.0, 0.0,
        0.0, 0.0, -2.0 / (f - n), 0.0,
        -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n), 1.0,
    ]


def identity():
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def translate(x, y, z):
    m = identity()
    m[12], m[13], m[14] = x, y, z
    return m


def inverse_ortho(l, r, b, t, n, f):
    """ortho 的逆，用于 gbufferProjectionInverse。"""
    return [
        (r - l) / 2.0, 0.0, 0.0, 0.0,
        0.0, (t - b) / 2.0, 0.0, 0.0,
        0.0, 0.0, -(f - n) / 2.0, 0.0,
        (r + l) / 2.0, (t + b) / 2.0, -(f + n) / 2.0, 1.0,
    ]


def _mul4(a, b):
    """两个列主序 mat4 相乘（a·b）。20 次乘加，不值得引外部库。"""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + r] * b[c * 4 + k]
            out[c * 4 + r] = s
    return out


class UniformState:
    """一帧的 uniform 快照。每帧 update() 一次，各 pass 按需取用。"""

    def __init__(self):
        self.view_w = 1.0
        self.view_h = 1.0
        self.frame_counter = 0
        self.frame_time = 0.016
        self.frame_time_counter = 0.0
        self.sun_angle = 0.25          # 0=日出 0.25=正午 0.5=日落 0.75=午夜
        self.rain_strength = 0.0
        self.is_eye_in_water = 0
        self.eye_brightness = (240, 240)
        self.camera_position = (0.0, 0.0, 0.0)
        self.previous_camera_position = (0.0, 0.0, 0.0)
        self.far = 256.0
        self.alpha_test_ref = 0.1
        self.sun_position = (0.0, 0.0, 100.0)
        self.moon_position = (0.0, 0.0, -100.0)
        self.shadow_light_position = (0.0, 0.0, 100.0)
        self.gbuffer_projection = identity()
        self.gbuffer_projection_inverse = identity()
        self.gbuffer_model_view = identity()
        self.gbuffer_model_view_inverse = identity()
        self.gbuffer_previous_model_view = identity()
        self.gbuffer_previous_projection = identity()
        self.shadow_model_view = identity()
        self.shadow_projection = identity()
        self.entity_color = (1.0, 1.0, 1.0, 0.0)
        self.held_item_id = 0
        self.noise_size = 64
        self.sun_path_rotation = 0.0
        self.atlas_size = (256, 256)
        self._extras = {}

    # ------------------------------------------------------------ 更新
    def update(self, camera, screen_size, world_pixels, dt, elapsed,
               grid=None, extra=None):
        """从星织的 Camera 与时间推进本帧 uniform。

        camera: 星织 Camera（有 x/y/zoom，单位是**世界像素**）
        screen_size: (w, h)
        world_pixels: (pw, ph) 世界像素尺寸
        dt / elapsed: 秒
        """
        sw, sh = screen_size
        self.view_w = float(sw)
        self.view_h = float(sh)
        self.frame_time = max(0.0, min(0.25, float(dt)))
        self.frame_time_counter = float(elapsed)
        self.frame_counter = int(self.frame_counter + 1) & 0x7FFFFFFF

        # 相机位置：星织像素 -> 格单位。世界像素换算用固定 TILE，
        # 视口覆盖格数要用缩放后的 tile_px——这两个不是同一个量。
        tile = self._world_tile()
        tp = max(1, int(round(tile * camera.zoom)))
        cx = camera.x / tile
        cy = camera.y / tile
        self.previous_camera_position = self.camera_position
        self.camera_position = (cx, cy, 0.0)

        # 视口覆盖的格数（正射投影的范围）
        half_w = sw / tp / 2.0
        half_h = sh / tp / 2.0
        # 留 8% 余量，避免边缘抖动露白
        half_w *= 1.08
        half_h *= 1.08
        self.far = max(half_w, half_h) * 4.0

        self.gbuffer_projection = ortho(-half_w, half_w, -half_h, half_h,
                                       -1.0, 1.0)
        self.gbuffer_projection_inverse = inverse_ortho(
            -half_w, half_w, -half_h, half_h, -1.0, 1.0)

        # 模型视图：星织相机 x/y 已在 world_gl 里相对化，所以视图矩阵是单位阵。
        # 保留接口是因为阴影 pass 要真实平移。
        self.gbuffer_model_view = identity()
        self.gbuffer_model_view_inverse = identity()
        self.gbuffer_previous_model_view = identity()
        self.gbuffer_previous_projection = self.gbuffer_projection
        # slm_mvp：几何 pass 用 proj*mv；全屏 pass 由 apply() 覆盖成单位阵
        self.mvp = _mul4(self.gbuffer_projection,
                         self.gbuffer_model_view)

        # 阴影：用一份覆盖当前视野的正交投影（俯视光方向下阴影没意义，
        # 但包里如果做屏幕空间阴影就有东西可算）
        ext = max(half_w, half_h) * 1.5
        self.shadow_projection = ortho(-ext, ext, -ext, ext, -ext, ext)
        self.shadow_model_view = identity()

        # 太阳方向：星织有昼夜就取，没有就用真实时钟。
        self.sun_angle = self._sun_angle_from_clock(elapsed, extra)
        ang = (self.sun_angle - 0.25) * math.tau    # 正午为 0
        r = 100.0
        # 视图空间：+X 东，+Y 上，+Z 朝镜头。太阳在 XY 平面绕圈。
        sx = math.sin(ang) * r
        sy = math.cos(ang) * r
        self.sun_position = (sx, sy, 0.0)
        self.moon_position = (-sx, -sy, 0.0)
        # 主导光源：太阳在地平线上用太阳，否则用月亮
        self.shadow_light_position = (
            self.sun_position if math.cos(ang) > 0 else self.moon_position)

        if grid is not None:
            self.atlas_size = (max(256, grid.w * 4), max(256, grid.h * 4))
        if extra:
            self._extras.update(extra)

    @staticmethod
    def _sun_angle_from_clock(elapsed, extra):
        """星织没有真太阳，用游戏时钟推一个稳定循环。

        周期 600 秒（10 分钟一个昼夜），从正午起算。extra 里如果有
        'day_time'（0..1）就优先用它——将来宿主游戏接昼夜系统时直接对接。
        """
        if extra:
            dt = extra.get("day_time")
            if isinstance(dt, (int, float)):
                return float(dt) % 1.0
        period = 600.0
        phase = (elapsed / period) % 1.0
        # elapsed=0 时是正午（0.25）
        return (0.25 + phase) % 1.0

    @staticmethod
    def _world_tile():
        """格子边长（世界像素）。与 stellarloom.config.TILE 一致；
        拿不到 config 时退回 24（星织的固定值）。"""
        try:
            from stellarloom import config as C
            return float(C.TILE)
        except Exception:
            return 24.0

    # ------------------------------------------------------------ 应用
    def apply(self, prog, buffers=None, geometry=False):
        """把本帧状态写进一个已 use 的 program。返回成功设置的 uniform 名列表。

        geometry=True 表示这条 pass 画真实几何（gbuffers 族），
        slm_mvp 用 proj*mv；否则是后处理全屏四边形，slm_mvp 必须是单位阵。
        """
        done = []
        p = prog

        def s(fn, *a):
            try:
                if fn(*a):
                    done.append(a[0])
            except Exception:
                pass

        # ---- slm_* 兼容矩阵：转译器把 gl_ModelViewProjectionMatrix 等
        # 换成了这些名字，不设置的话顶点全塌成原点。
        s(p.set_mat4, "slm_proj", self.gbuffer_projection)
        s(p.set_mat4, "slm_mv", self.gbuffer_model_view)
        s(p.set_mat4, "slm_mvp", self.mvp if geometry else identity())
        s(p.set_mat4, "slm_texmat0", identity())
        # 光照贴图坐标变换：原版把 [0,1] 的 lmcoord 映射到图集里的位置。
        # 我们全给 1.0（lmcoord 已经是最终值），保持恒等。
        s(p.set_mat4, "slm_texmat1", identity())
        s(p.set_vec4, "slm_color", 1.0, 1.0, 1.0, 1.0)
        # mat3 法线矩阵：单位阵（不需要法线变换）
        s(p.set_mat3, "slm_normal", [1.0, 0.0, 0.0,
                                     0.0, 1.0, 0.0,
                                     0.0, 0.0, 1.0])

        s(p.set_float, "viewWidth", self.view_w)
        s(p.set_float, "viewHeight", self.view_h)
        s(p.set_float, "frameTime", self.frame_time)
        s(p.set_float, "frameTimeCounter", self.frame_time_counter)
        s(p.set_int, "frameCounter", self.frame_counter)
        s(p.set_float, "sunAngle", self.sun_angle)
        s(p.set_float, "rainStrength", self.rain_strength)
        s(p.set_int, "isEyeInWater", self.is_eye_in_water)
        s(p.set_ivec2, "eyeBrightnessSmooth", *self.eye_brightness)
        s(p.set_vec3, "cameraPosition", *self.camera_position)
        s(p.set_vec3, "previousCameraPosition", *self.previous_camera_position)
        s(p.set_float, "far", self.far)
        s(p.set_float, "alphaTestRef", self.alpha_test_ref)
        s(p.set_vec3, "sunPosition", *self.sun_position)
        s(p.set_vec3, "moonPosition", *self.moon_position)
        s(p.set_vec3, "shadowLightPosition", *self.shadow_light_position)
        s(p.set_mat4, "gbufferProjection", self.gbuffer_projection)
        s(p.set_mat4, "gbufferProjectionInverse",
          self.gbuffer_projection_inverse)
        s(p.set_mat4, "gbufferModelView", self.gbuffer_model_view)
        s(p.set_mat4, "gbufferModelViewInverse",
          self.gbuffer_model_view_inverse)
        s(p.set_mat4, "gbufferPreviousModelView",
          self.gbuffer_previous_model_view)
        s(p.set_mat4, "gbufferPreviousProjection",
          self.gbuffer_previous_projection)
        s(p.set_mat4, "shadowModelView", self.shadow_model_view)
        s(p.set_mat4, "shadowProjection", self.shadow_projection)
        s(p.set_vec4, "entityColor", *self.entity_color)
        s(p.set_int, "heldItemId", self.held_item_id)
        s(p.set_float, "noiseTextureResolution", self.noise_size)
        s(p.set_float, "sunPathRotation", self.sun_path_rotation)
        s(p.set_vec2, "atlasSize", *self.atlas_size)
        # 常见但包里不一定要的
        s(p.set_vec2, "viewSize", self.view_w, self.view_h)
        s(p.set_vec2, "texelSize", 1.0 / self.view_w, 1.0 / self.view_h)
        return done

    def extra(self, name, default=None):
        return self._extras.get(name, default)

    def summary(self):
        return {
            "view": (self.view_w, self.view_h),
            "frame": self.frame_counter,
            "sun_angle": round(self.sun_angle, 3),
            "camera": tuple(round(v, 2) for v in self.camera_position),
            "far": round(self.far, 1),
        }