"""机器系统自检：内置储存、配方切换、拒收非配方物品、产物槽满停工。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellarloom import config as C
from stellarloom.production.machines import Machine, MachineNetwork
from stellarloom.world.grid import WorldGrid


def main():
    fails = []

    # 1. 放下去是空壳 + 拒收非配方原料
    m = Machine(0, 0, C.B_FURNACE)
    if m.recipe_id is not None:
        fails.append("机器放下时不该自带配方")
        print(f"[1] !! 默认配方={m.recipe_id} (期望 None)")
    empty_feed = m.feed(C.I_IRON_ORE)
    print(f"[1] 空壳喂矿={empty_feed} (期望 False)")
    if empty_feed:
        fails.append("空壳机器还在收物品")

    m.set_recipe("iron_plate")
    ok_feed = m.feed(C.I_IRON_ORE)
    bad_feed = m.feed(C.I_GEAR)  # 齿轮不是熔炉配方原料
    print(f"[1b] 设配方后收矿石={ok_feed} 收齿轮={bad_feed} inputs={m.inputs}")
    if not ok_feed or bad_feed:
        fails.append("拒收非配方物品失败")

    # 2. 清空配方 → 一律拒收
    m.set_recipe(None)
    rejected = m.feed(C.I_IRON_ORE)
    print(f"[2] 无配方喂矿={rejected} (期望 False)")
    if rejected:
        fails.append("未设配方仍吸收物品")

    # 3. 生产：喂够料 → 产物进 outputs
    m.set_recipe("iron_plate")
    for _ in range(3):
        m.feed(C.I_IRON_ORE)
    m.update(0.0, 1.0)
    m.update(2.0, 1.0)  # 超过 duration
    print(f"[3] 生产后 outputs={m.outputs} inputs={m.inputs}")
    if m.outputs.get(C.I_IRON_PLATE, 0) != 1:
        fails.append("生产产物没进产物槽")
    if m.inputs.get(C.I_IRON_ORE, 0) != 2:
        fails.append("原料消耗数量不对")

    # 4. 产物槽满 → 停止生产，不吞原料
    m.outputs[C.I_IRON_PLATE] = C.MACHINE_OUTPUT_CAP
    m.update(0.0, 1.0)
    before = dict(m.inputs)
    m.update(10.0, 1.0)
    print(f"[4] 产物满时 inputs {before}->{m.inputs} (应不变)")
    if m.inputs != before:
        fails.append("产物满时仍在吞原料")

    # 5. 原料容量上限：满了 feed 返回 False（堵住分拣器）
    m2 = Machine(1, 1, C.B_FURNACE)
    m2.set_recipe("iron_plate")
    fed = 0
    for _ in range(C.MACHINE_INPUT_CAP + 5):
        if m2.feed(C.I_IRON_ORE):
            fed += 1
    print(f"[5] 连续喂 {C.MACHINE_INPUT_CAP + 5} 次，成功 {fed} 次 "
          f"inputs={m2.inputs} (期望 ≤{C.MACHINE_INPUT_CAP})")
    if fed > C.MACHINE_INPUT_CAP:
        fails.append("原料容量上限失效")

    # 6. 配方切换：不匹配的原料被清掉
    m3 = Machine(2, 2, C.B_ASSEMBLER)
    m3.set_recipe("gear")
    m3.inputs = {C.I_IRON_PLATE: 5}
    m3.set_recipe("circuit")  # 也需要铁板，保留
    kept = dict(m3.inputs)
    m3.set_recipe("gear")
    print(f"[6] 切到 circuit 后 inputs={kept}，切回 gear 后={m3.inputs}")
    if kept.get(C.I_IRON_PLATE, 0) != 5:
        fails.append("切换配方时该保留的原料被清掉")

    # 7. available_recipes 按建筑过滤（期望值直接从 config 推导，别再写死）
    fr = Machine(3, 3, C.B_FURNACE).available_recipes()
    asm = Machine(4, 4, C.B_ASSEMBLER).available_recipes()
    exp_fr = {rid for rid, r in C.RECIPES.items()
              if r[3] and C.B_FURNACE in r[3]}
    exp_asm = {rid for rid, r in C.RECIPES.items()
               if r[3] and C.B_ASSEMBLER in r[3]}
    print(f"[7] 熔炉可选={fr} 制造台可选={asm}")
    if set(fr) != exp_fr:
        fails.append("熔炉配方列表不对")
    if set(asm) != exp_asm:
        fails.append("制造台配方列表不对")
    # 手搓配方（allows=None）绝不能出现在机器可选列表里
    hand = {rid for rid, r in C.RECIPES.items() if r[3] is None}
    if hand & (set(fr) | set(asm)):
        fails.append("手搓配方漏进机器可选列表")

    # 8. take_output 指定种类
    m4 = Machine(5, 5, C.B_ASSEMBLER)
    m4.outputs = {C.I_GEAR: 2, C.I_CIRCUIT: 1}
    got = m4.take_output(C.I_CIRCUIT)
    print(f"[8] take_output(circuit)={got} 剩余={m4.outputs}")
    if got != C.I_CIRCUIT:
        fails.append("指定种类取产物失败")

    # 9. 网络 sync 能建出机器
    g = WorldGrid()
    g.place(10, 10, C.B_FURNACE, 0)
    g.place(11, 11, C.B_ASSEMBLER, 0)
    net = MachineNetwork(g)
    net.sync()
    print(f"[9] sync 机器数={len(net.machines)} get_machine(10,10)={net.get_machine(10, 10) is not None}")
    if len(net.machines) != 2:
        fails.append("MachineNetwork.sync 建机器数量不对")

    print()
    if fails:
        print("FAIL:", "; ".join(fails))
        return 1
    print("PASS 机器系统全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())