# 美术资源清单 ArtAssets

M9 打磨阶段需要把所有程序化色块换成 sprite。本文件是完整的清单、规格、AI 出图 prompt。

## 总规格

- 基准格：24×24 px（`C.TILE`）。1x 缩放 = 24 px/格。
- 缩放范围 0.25x–4x。sprite 用**最近邻**放大（`pygame.transform.scale`，不要 smoothscale），保持像素硬边。
- 为 4x 显示不糊，建议实际出图 **96×96**（4 倍），运行时 `scale` 到目标 tile_px。
- 所有 sprite 一律 **透明背景 PNG**（RGBA），建筑本体不占满格时四周留透明。
- 风格：干净的矢量/像素混合，深色工业风，同 Factorio 的俯视 + 轻微立体感；主色调偏冷（灰蓝/暗红/青绿）。
- 光照方向：左上打光，右下投影（统一，否则拼一起会乱）。

## 建筑 sprite（单格）

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `belt.png` | 96×96 | 传送带本体（会自动四向旋转） |
| `belt_arrow.png` | 96×96 | 传送带箭头叠加层（四向） |
| `miner.png` | 96×96 | 采矿机，四向钻头 |
| `furnace.png` | 96×96 | 熔炉，红热口发橙光 |
| `assembler.png` | 96×96 | 制造台，蓝色，顶部机械臂 |
| `inserter.png` | 96×96 | 分拣器，四向，黄色机械臂 |
| `solar.png` | 96×96 | 太阳能板，深蓝+网格纹 |
| `wind.png` | 96×96 | 风力涡轮，浅青，三叶（做 4 帧旋转动画可选） |
| `lab.png` | 96×96 | 科研站，紫色，圆顶+天线 |
| `core.png` | 96×96 | 出生核心，白色发光，不可拆 |

## 多格建筑（3×3）

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `tower_supply.png` | 288×288 | 供应塔（绿色），占地 3×3，顶部有停机坪 |
| `tower_request.png` | 288×288 | 请求塔（橙色），同上 |

> 多格 sprite 必须整体渲染或在动态层画，**不能塞进 chunk 静态缓存**（见 TechDebt #4）。

## 物品图标（传送带上 / 库存面板）

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `item_iron_ore.png` | 24×24 | 铁矿石，橙色碎块 |
| `item_iron_plate.png` | 24×24 | 铁板，银白金属板 |
| `item_gear.png` | 24×24 | 齿轮，灰色 |
| `item_circuit.png` | 24×24 | 电路板，绿色 PCB |
| M5 新增 | 24×24 | `item_copper_ore` / `item_copper_plate` / `item_coal` / `item_stone` / `item_steel` / `item_wire` |

## 无人机

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `drone.png` | 48×48 | 俯视四旋翼，颜色需在代码里按电量 tint（出白色本体，代码 multiply 颜色） |
| `drone_cargo.png` | 48×48 | 带货物吊舱版本（可选叠加） |

## 特效 / UI

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `ghost_ok.png` | 96×96 | 可放置预览框（绿） |
| `ghost_bad.png` | 96×96 | 不可放置预览框（红） |
| `select_ring.png` | 128×128 | 选中高亮环 |
| `toast_bg.png` | 四边 9-patch | 提示条背景 |
| `panel_bg.png` | 9-patch | 面板背景（塔/科技） |
| `btn_normal.png` | 9-patch | 按钮常态 |
| `btn_active.png` | 9-patch | 按钮选中/激活 |
| `icon_lock.png` | 32×32 | 科技未解锁的锁图标（现在用 emoji 🔒，手机上可能没字形） |

## 地面 / 环境

| 文件名 | 尺寸 | 说明 |
|---|---|---|
| `tile_ground.png` | 96×96 | 基础地面，可 4 变体拼接消除重复感 |
| `ore_patch.png` | 96×96 | 矿脉底色（叠在地面上，代码现在用散点圆） |
| `ore_glint.png` | 96×96 | 矿脉闪点叠加 |

## AI 出图 prompt（可直接丢给文生图）

**统一起手式**（追加在每个 prompt 前）：

```
top-down view, game asset sprite, transparent background, clean industrial
sci-fi style, cool palette, left-top lighting, no text, no shadow on background,
pixel-sharp edges, PNG RGBA
```

示例：
- 传送带：`+ conveyor belt segment, dark steel frame, glowing blue guide rails, centered arrow pointing right`
- 熔炉：`+ industrial smelting furnace, dark red metal body, glowing orange vent slots, small chimney`
- 供应塔：`+ 3x3 logistics tower footprint, green octagonal base, four drone landing pads at corners, upward arrow emblem`
- 请求塔：`+ 3x3 logistics tower footprint, orange octagonal base, four drone landing pads at corners, downward arrow emblem`
- 电路板物品：`+ tiny green PCB chip icon, gold traces, 24x24`

## 接入步骤（M9 时做）

1. 资源放 `assets/`，`render/layers.py` 加 `SpriteBook`（按 `tile_px` 缓存 `pygame.transform.scale`）。
2. `_build` 里每个 `_draw_xxx` 换成 `surf.blit(sprite, rect)`；`tile_px < 8` 保留程序化绘制（远景不糊就够）。
3. 传送带箭头、分拣器方向、采矿机钻头做成独立叠加层，按 `grid.direction` 旋转。
4. 塔改到动态层逐帧画（同时解决 TechDebt #4）。
5. 物品图标替换 `_draw_items` 里的 `pygame.draw.circle`。
6. 无人机本体出白色，代码 `pygame.Surface.fill(color, special_flags=BLEND_MULT)` tint。

## 最低可交付集（如果只做一半）

优先做这 6 个，观感提升 80%：
`belt.png`、`furnace.png`、`assembler.png`、`miner.png`、`tower_supply.png`、`tower_request.png`。