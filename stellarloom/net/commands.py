"""M15b 指令白名单：客户端允许远程调用的 sim 方法。

白名单即安全边界——不在表里的方法（如 step/activate_world/snapshot）
不允许从网络触发。参数只做基本类型检查（服务端方法自身做业务校验）。
"""

from __future__ import annotations

# name → 是否带行星作用域（world 参数来自客户端镜像的 world_index）
COMMANDS: dict[str, bool] = {
    # 建造 / 拆除
    "place_building": True,
    "place_tower": True,
    "place_pad": True,
    "place_engine": True,
    "lay_belt_line": True,
    "place_inserter": True,
    "remove_building": True,
    "set_overlay_filter": True,
    "manual_mine": True,
    # 容器 / 机器 / 科研 / 塔（M15a 指令层）
    "set_machine_recipe": True,
    "machine_take_input": True,
    "machine_add_input": True,
    "machine_take_outputs": True,
    "container_take": True,
    "container_put": True,
    "chest_take": True,
    "chest_put": True,
    "lab_set_mode": True,
    "lab_set_recipe": True,
    "lab_take_item": True,
    "lab_add_item": True,
    "lab_take_outputs": True,
    "set_tower_filter": True,
    # 生产 / 科技
    "do_craft": False,
    "cancel_craft": False,
    "manual_research": False,
    "start_research": False,
    # 星际
    "set_pad_mode": True,
    "set_pad_target": True,
    "set_orbit_a_ratio": True,
    "shift_orbit_phase": True,
}

# 参数值允许的类型（JSON 域）
_ARG_TYPES = (str, int, float, bool, type(None))


def validate(name: str, args, kwargs) -> str | None:
    """返回 None 表示合法；否则返回拒绝原因。"""
    if name not in COMMANDS:
        return f"指令 {name!r} 不在白名单"
    if not isinstance(args, (list, tuple)) or len(args) > 8:
        return "args 非法"
    if not isinstance(kwargs, dict) or len(kwargs) > 8:
        return "kwargs 非法"
    for v in list(args) + list(kwargs.values()):
        if isinstance(v, _ARG_TYPES):
            continue
        # 允许数字/字符串键的浅 dict（返回型参数如 outputs 不会出现在入参，
        # 但 container_put 等目前也只收标量——这里只留一道兜底门）
        if isinstance(v, (list, tuple)) and len(v) <= 32 and all(
                isinstance(x, _ARG_TYPES) for x in v):
            continue
        return f"参数类型不允许: {type(v).__name__}"
    return None