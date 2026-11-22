"""uniform 供给与投影矩阵的自检：不碰 GL。

跑法：python3 devtools/_uniformcheck.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.dirname(os.path.dirname(ROOT))
sys.path.insert(0, ROOT)
sys.path.insert(0, GAME)

from stellarloom import config as C                       # noqa: E402
from stellarloom.render.camera import Camera               # noqa: E402

from core import uniforms                                  # noqa: E402


class FakeProg:
    """记录所有 set_* 调用。"""

    def __init__(self):
        self.set = {}

    def set_float(self, n, v):
        self.set[n] = ("f", v)
        return True

    def set_int(self, n, v):
        self.set[n] = ("i", v)
        return True

    def set_vec2(self, n, x, y):
        self.set[n] = ("v2", (x, y))
        return True

    def set_vec3(self, n, x, y, z):
        self.set[n] = ("v3", (x, y, z))
        return True

    def set_vec4(self, n, x, y, z, w):
        self.set[n] = ("v4", (x, y, z, w))
        return True

    def set_mat4(self, n, m):
        self.set[n] = ("m4", list(m))
        return True

    def set_mat3(self, n, m):
        self.set[n] = ("m3", list(m))
        return True

    def set_ivec2(self, n, x, y):
        self.set[n] = ("iv2", (x, y))
        return True


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    return cond


def mul_vec4(m, v):
    """列主序矩阵乘列向量：结果[r] = Σ_c m[c*4+r] * v[c]。"""
    return [sum(m[c * 4 + r] * v[c] for c in range(4)) for r in range(4)]


def main():
    ok = True
    print("== 正射投影：角落映射到 NDC 边界 ==")
    l, r, b, t, n, f = -10.0, 10.0, -5.0, 5.0, -1.0, 1.0
    m = uniforms.ortho(l, r, b, t, n, f)
    # GL 约定：近平面映射到 z_ndc = +1，远平面映射到 -1
    got = mul_vec4(m, [l, b, n, 1.0])
    print("  左下近点 -> %s" % [round(x, 4) for x in got])
    ok &= check(abs(got[0] + 1) < 1e-6 and abs(got[1] + 1) < 1e-6
                and abs(got[2] - 1) < 1e-6, "映射到 (-1,-1,+1)")
    got = mul_vec4(m, [r, t, f, 1.0])
    print("  右上远点 -> %s" % [round(x, 4) for x in got])
    ok &= check(abs(got[0] - 1) < 1e-6 and abs(got[1] - 1) < 1e-6
                and abs(got[2] + 1) < 1e-6, "映射到 (1,1,-1)")
    # 中心 -> (0,0,0)
    got = mul_vec4(m, [(l + r) / 2, (b + t) / 2, (n + f) / 2, 1.0])
    ok &= check(all(abs(x) < 1e-6 for x in got[:3]), "中心映射到原点")

    print("\n== ProjectionInverse 确实是逆 ==")
    mi = uniforms.inverse_ortho(l, r, b, t, n, f)
    # 取几个 NDC 点，用逆矩阵还原到裁剪空间再正向投一次，应回到原 NDC
    for ndc in ((-1, -1, -1), (0.3, -0.7, 0.5), (1, 1, 1)):
        clip = mul_vec4(mi, [ndc[0], ndc[1], ndc[2], 1.0])
        back = mul_vec4(m, clip)
        err = max(abs(back[i] - ndc[i]) for i in range(3))
        ok &= check(err < 1e-6, "NDC %s 往返误差 %.2e" % (str(ndc), err))

    print("\n== 抖一层帧：uniform 应持续更新 ==")
    st = uniforms.UniformState()
    cam = Camera(1024 * C.TILE, 1024 * C.TILE)
    cam.zoom = 1.0
    st.update(cam, (1280, 720), (1024 * C.TILE, 1024 * C.TILE), 0.016, 0.0)
    s1 = st.summary()
    print("  帧 1: %s" % s1)
    ok &= check(st.frame_counter == 1, "frameCounter 从 0 增到 1")
    ok &= check(s1["view"] == (1280.0, 720.0), "viewWidth/Height 正确")

    st.update(cam, (1280, 720), (1024 * C.TILE, 1024 * C.TILE), 0.016, 0.016)
    ok &= check(st.frame_counter == 2, "frameCounter 递增")

    print("\n== 相机平移应改变 cameraPosition ==")
    before = st.camera_position
    cam.x = 200 * C.TILE          # 相机本来在中心 (512,512)，现在挪开
    st.update(cam, (1280, 720), (1024 * C.TILE, 1024 * C.TILE), 0.016, 0.032)
    print("  cameraPosition = %s，上一帧 = %s"
          % (st.camera_position, st.previous_camera_position))
    ok &= check(abs(st.camera_position[0] - 200.0) < 1e-6,
                "cameraPosition.x = 200 格")
    ok &= check(st.previous_camera_position == before,
                "previousCameraPosition 保留了上一帧 %s" % (before,))
    ok &= check(st.previous_camera_position != st.camera_position,
                "两帧位置确实不同")
    cam.x = 512 * C.TILE          # 还原，后面的测试依赖中心位置

    print("\n== 太阳角度与方向 ==")
    for t_elapsed, expect in ((0.0, 0.25), (150.0, 0.5), (300.0, 0.75),
                              (450.0, 0.0)):
        st.update(cam, (1280, 720), (1024 * C.TILE,) * 2, 0.016, t_elapsed)
        ok &= check(abs(st.sun_angle - expect) < 1e-6,
                    "elapsed=%.0f → sunAngle=%.2f（期望 %.2f）"
                    % (t_elapsed, st.sun_angle, expect))

    print("\n== sunPosition 与 sunAngle 一致 ==")
    st.update(cam, (1280, 720), (1024 * C.TILE,) * 2, 0.016, 0.0)
    sx, sy, sz = st.sun_position
    ok &= check(abs(sy - 100.0) < 1e-6, "正午太阳在 +Y（sy=%.1f）" % sy)
    st.update(cam, (1280, 720), (1024 * C.TILE,) * 2, 0.016, 300.0)
    sx, sy, sz = st.sun_position
    ok &= check(sy < 0, "午夜太阳在 -Y（sy=%.1f）" % sy)
    ok &= check(st.shadow_light_position == st.moon_position,
                "午夜主导光源切到月亮")

    print("\n== apply() 写进 program ==")
    st.update(cam, (800, 600), (1024 * C.TILE,) * 2, 0.02, 5.0)
    p = FakeProg()
    done = st.apply(p)
    print("  写入 %d 个 uniform" % len(done))
    ok &= check(len(done) > 20, "至少写了 20 个 uniform")
    ok &= check("gbufferProjection" in p.set, "写了 gbufferProjection")
    ok &= check("sunPosition" in p.set, "写了 sunPosition")
    ok &= check(p.set["viewWidth"][1] == 800.0, "viewWidth = 800")
    ok &= check(len(p.set["gbufferProjection"][1]) == 16,
                "投影矩阵有 16 个元素")

    print("\n== day_time 覆盖 ==")
    st2 = uniforms.UniformState()
    st2.update(cam, (800, 600), (1024 * C.TILE,) * 2, 0.02, 0.0,
               extra={"day_time": 0.6})
    ok &= check(abs(st2.sun_angle - 0.6) < 1e-6,
                "extra['day_time']=0.6 直通（得到 %.2f）" % st2.sun_angle)

    print("\n" + ("全部通过" if ok else "有失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())