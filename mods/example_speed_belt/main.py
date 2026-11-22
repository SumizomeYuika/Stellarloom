"""示例 mod：传送带双倍速。

教学点：mixin wrap="before" 返回 (args, kwargs) 替换调用参数——
BeltNetwork.update 第一行是 speed = C.BELT_SPEED * dt，把 dt 翻倍
即可整体提速，一行改动、零源码修改、卸载自动还原。
"""


def on_load(ctx):
    ctx.toast("示例 mod：传送带 ×2 已启用", 2.0)
    ctx.log("传送带双倍速已生效")

    def double_speed(self, dt):
        return ((dt * 2.0,), {})   # 替换 update(dt) 的 dt 参数

    ctx.mixin("stellarloom.logistics.belts.BeltNetwork", "update",
              double_speed, wrap="before")


def on_unload(ctx):
    ctx.toast("示例 mod 已卸载：传送带还原原速", 2.0)
    ctx.log("传送带已还原（mixin 由系统自动还原）")