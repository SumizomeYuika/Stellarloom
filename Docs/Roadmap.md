# 进度与下一步 Roadmap

更新时间：2026-11-01

## 已完成

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 环形卷绕网格 + chunk 预渲染 + 相机 + 触屏输入 | 完成 |
| M1 | 传送带 lane + 采矿机 + 熔炉 + 电力 + 分拣器 | 完成 |
| M2 | 物流塔（供应/请求）+ 真实无人机实体 + 塔面板 | 完成 |
| M3 | 科研站 + 科技树（8 科技）+ 建筑解锁锁表 | 完成 |
| M4 | 存档系统（.slm / zlib / F5 F9 / 三槽轮转 / 版本迁移） | 完成 |
| 基建 | bench 压测脚本 + 三个自检脚本 + TechDebt/ArtAssets 文档 | 完成 |
| M4.5 | 机器面板 + 内置储存 + 可设配方 + 科技树全屏页 | 完成 |
| M5 | 多矿种（铁/铜/石）+ 建筑物品化 + 手搓合成 + 科研包 + 存档 v4 | 完成 |
| M5.5 | 分拣器过滤（查看模式点分拣器选物品）+ 存档 v5 | 完成 |
| M6 | 箱子容器 + 全机器手动存取（机器/矿机/箱子面板）+ 存档 v6 | 完成 |
| M6.5 | 合成面板改版（560×620 两栏先选后显）+ 手搓耗时队列 + 补手搓兜底 | 完成 |
| M6.6 | 统一配方（删 hand_/mk_ 双套，一物品一配方，全部可自动化）+ belt 一份出 3 + `HAND_CRAFT_TIME_MULT` | 完成 |
| M6.7 | M2 补齐：红科研（能量矩阵 / 硅石）+ 科技树扩到 11 条 + 科研包按科技分流 | 完成 |
| M6.8 | M4 戴森云：太阳帆发射器 + 3 条轨道 + 帆群发电 + 轨道图面板 + 存档 v7 | 完成 |
| M6.9 | 手搓队列 bug：新任务顶掉旧任务 → 改成真队列（多任务排队 + 跨任务不吞时间） | 完成 |
| M6.10 | 底栏建筑分类制：只显示 6 大类，点开弹出具体建筑子条 | 完成 |
| M6.11 | 科研站双模式（研究/制造）+ 矩阵垄断 + 研究队列 + 右上角成就弹窗 + 存档 v8 | 完成 |
| M6.12 | 底栏分类统一展开+展开即高亮；合成栏显示全部配方（不可手搓标明可用机器）；机器面板改产物选配方 | 完成 |
| M6.13 | 修分拣器 带子→带子 把来源带堵死/丢物品：目标带满不再抓 + 投递失败按原位置放回 | 完成 |
| M6.14 | 矿脉无限：`grid.mine()` 不再递减储量，矿格永不枯竭 | 完成 |
| M6.15 | 制造台面板显示全部配方（未解锁标🔒拦截）+ 传送带 rebuild 转角物品错位修复 | 完成 |
| M6.16 | 自动化死锁：电磁矩阵不再吃电路板，制造台/科研站改吃铜线，电路板保留 circuit1 科技锁 | 完成 |
| M6.17 | 机器配方面板加大 + 三列表格排列，配方再多也不顶穿底部 | 完成 |
| M6.18 | 轨道系统最小版：行星公转 + 太阳能随相位起伏（±25%）+ 轨道面板行星展示 + 存档 v9 | 完成 |
| M6.19 | 性能优化：分拣器坐标集合（代数失效）+ 物品渲染向量化 + sprite blit | 完成 |
| M5a | 星际骨架：双行星（独立网格/网络/轨道/相机）+ 轨道面板切星 + 存档 v10 | 完成 |
| M6.20 | 多存档：6 槽位面板 + F5 快速存档 + 读旧档/自动档入口 | 完成 |
| M6.22 | UI 定义化：控件级 JSON 定义（`defs/*.json`）+ 加载器，存档面板/顶栏示范迁移 | 完成 |
| M6.24 | 架构分层：服务器端 `sim` 包（headless 零 pygame）+ 前端瘦身 Game | 完成 |
| M6.25 | 主菜单：启动封面 + 新游戏/继续/读档/退出，顶栏"菜单"按钮 | 完成 |
| M6.26 | 面板 JSON 化推进 + 全局主题皮肤化（filter/bag/lab/tower 迁 defs，theme.json 兜底） | 完成 |
| M6.27 | MOD 支持：mods/ 加载器 + mixin 补丁（before/after/replace，非永久）+ API 暴露（内容扩展/钩子） | 完成 |
| M6.28 | 五项 UI/数据大改：配方 JSON 化（启动加载）+ 面板窗口化（标题栏梯形+可拖动）+ 机器配方选择器 + 科技树树状图 + 模组管理页（仿 minecraft） | 完成 |
| M6.29 | MOD 配置与依赖：统一 config 存/写（作者默认 + 用户覆盖 + save_config）+ mod.json dependencies（拓扑序/版本门禁/环检测）；科技树连线重构零穿节点；UI 重叠/超框全面审计 | 完成 |
| M6.30 | Minecraft 风格注解 mixin：@Mixin/@Inject(at=HEAD/RETURN, cancellable)/@Overwrite + CallbackInfo，加载 main.py 自动收集注册 | 完成 |
| M7 | MC 风格物品注册表：命名空间名字（原版 stellarloom:）+ 启动动态分配数字 id + 存档/配方 JSON 名字化持久化，mod 名字注册与数字兼容 | 完成 |
| M8 | 建筑注册表收口：B_* 进注册表（stellarloom:belt 等）+ ctx.add_building 名字注册动态分配（100+，避开存量硬编码段）+ BUILD_ITEM 联动 + 配方 machines 名字解析 | 完成 |
| M5b | 星际物流：发射台（3×3 供/求双模式）+ 运输船舰队（恒星级别）+ 发射窗口（相位对齐/预测）+ 科技 interstellar1 + 存档 v12 | 完成 |
| M6.31 | 真实行星参数：开普勒椭圆轨道（真实半长轴/偏心率/近点辐角）+ 周期由 T=a^1.5 算出 + 日照 1/r² + 轨道面板真实椭圆 + 窗口预测改数值解 | 完成 |
| M6 | 行星工程：行星引擎（3×3）+ 轨道半径/相位调整 + 温度与太阳能降效联动 + 科技 engine1 + 存档兼容 | 完成 |
| M6.32 | 星系视图（全屏界面）：缩到最小继续缩小（顶部进度条）进入 + 放大/ESC/返回地图 + 轨道只做戴森（点环设发射目标） | 完成 |
| M9 | 真电网：电力塔分区（8 格并网）+ 逐网供电比 + 真实单位 kW/MW + 戴森/旧 mod 注电摊派 + 无塔兼容旧全球网 | 完成 |
| M10 | 分拣器三段式机械臂：尾（来源格）/连接部/头（目标格）+ 摆动动画 + 机器格隐藏 + 底座不盖传送带 | 完成 |

## 关键修复记录

- **读档背包分裂（M6.26）**：读档后"背包显示有、放置提示没有"。根因：M6.24
  分层后 `load_into` 仍用 `game.inventory = {...}` 换引用，而前端 Game/底栏/
  手搓队列都持旧引用 → 显示旧背包、扣款走新背包。修法：背包恢复改就地
  `clear()+update()`。铁律：**存档恢复一律就地更新，禁止换容器引用**。
  详见 TechDebt #38。
- **面板手势穿透（M6.23）**：存档/轨道/箱子/科研站/机器/物流塔面板打开时，
  拖动会把后面的地图拖走（捏合缩放、滚轮同理只拦了少数面板）。修法：
  任何面板打开时地图手势一律不生效，滚动类面板（手搓/科技）仍优先滚动列表。
  `_uicheck` 加 `check_drag_block` 回归（9 面板 × 拖动/捏合）。详见 TechDebt #35。
- **缩放错位（M6.21）**：`ChunkRenderer` 用整数格距 `round(24*zoom)` 渲染，
  `Camera` 用浮点 `24*zoom` 换算 → zoom=0.6/2.2 时格子渲染与点按位置逐格累积错位
  （20 格差 8px）。修法：全链路统一 `Camera.tile_px` 整数格距一个事实源，
  渲染/拾取/物品/锚点全部走它。详见 TechDebt #33。
- **开局三重死锁**：无发电设备 + 分拣器被锁 + 没铁板没研究点，闭环锁死。
  修法：`POWER_GEN` 加 `B_CORE: 8.0`（M9 换算后为 160 kW）；`TECH_UNLOCK_BUILDING` 移除 `B_INSERTER`。
- **分拣器切断传送带**：分拣器原占独立建筑格，插在带子中间会把 lane 切成两段，物品全卡上半段。
  修法：改成 overlay 叠加层（`grid.overlay` / `grid.overlay_dir`），叠在带子上不切断，`remove()` 时级联清除。
- **无人机翻倍**：读档时 `towers.sync()` 会自动 spawn，又追加存档里的，导致翻倍。已在 `load_into` 清空。
- **Pydroid3 权限坑**：root cp 后文件归 root，Pydroid3 读不到 → `ImportError (unknown location)`。
  每次同步必须 `chown -R u0_a351:u0_a351` + 目录 777 / 文件 666。
- **机器无储存 + 配方写死**：原实现每台机器只有一个 `output` 单值槽，配方由建筑类型固定，
  玩家没法选、也没地方囤料。已重写：`inputs`/`outputs` 双 dict（各 10/种上限），
  配方可在面板里切换（含"无配方"），未设配方或非配方物品一律拒收 → 分拣器自动堵住。
- **机器默认是空壳**：去掉 `DEFAULT_RECIPE`，`machine.recipe_id` 初始为 `None`。
  放下熔炉/制造台会自动弹面板让玩家指定配方；没指定前不收任何物品，地图上画灰框提示。
  circuit1 研究完成也不再自动改配方，只发 toast 提示。

## 自检脚本

| 脚本 | 作用 |
|---|---|
| `tools/_startcheck.py` | 开局无死锁：初始解锁里有发电、有分拣器、供电 ≥ 最小产线、**科技闭包可达（防科技环死锁）** |
| `tools/_deadlockcheck.py` | 开局可达性闭包：背包+徒手挖矿 → 能造 → 能建 → 能研究，迭代到不动点。**语义：手搓永远可行，科技锁只锁机器自动化路径**，报不可达科技/建筑/科研包 + 无法自动化的配方 |
| `tools/_savecheck.py` | 存档往返一致性 + v1/v2/v3 老档 → 当前版三条迁移链实测（断言读 `SAVE_VERSION`，不需 pygame） |
| `tools/_insertercheck.py` | 分拣器 overlay 行为（不切断 / 能抓货 / 级联删 / 计数 / **过滤混矿带**） |
| `tools/_machinecheck.py` | 机器系统（拒收非配方 / 无配方拒收 / 产物满停工 / 容量上限 / 配方切换） |
| `tools/_buildcostcheck.py` | 建筑物品化（缺料不能放 / 扣料 / 拆除返还 / 开局库存够 / **配方 id 无 hand_/mk_ 前缀** / **一个物品只有一个配方（统一配方）** / **所有配方都能自动化（allows 非空）** / **`HAND_CRAFT_TIME_MULT > 1`（手搓比机器慢）**） |
| `tools/_craftcheck.py` | 统一配方链从空背包闭环到最小产线（不死锁），含**无残留可自动化缺失**校验 |
| `tools/_sciencecheck.py` | 科研包：电磁矩阵/能量矩阵产线、科研站只吃包、吃够完成科技、没研究不烧包 |
| `tools/_dysoncheck.py` | **戴森云（M4）**：太阳帆/发射器/二级矩阵配方齐备、发射器物品↔建筑↔科技锁三件套、轨道按科技解锁与容量封顶、帆数×单帆功率发电、`sail1` 效率加成、发射器囤帆上限与定时发射、戴森云存档往返 |
| `tools/_uicheck.py` | 桩 pygame 集成：Game 初始化 / 放置扣料 / 手搓队列耗时 / **合成面板先选后算** / 矿种 / 过滤面板开合与端到端 / **箱子放置+拆箱退货 / 机器面板手动存取 / 矿机面板全取 / 科技树树状图（分层/描述/研究/平移）** |
| `tools/_storagecheck.py` | 容器与手动存取：箱子混装上限、分拣器进出箱子、矿机 50 格满停挖不丢矿、机器手动放料按配方过滤、产物只能整体取（无 `add_output`）、箱子→熔炉过滤链 |
| `tools/_beltcheck.py` | 传送带 4 方向 lane 构建 + 物品流动 + 拐弯分 lane + 反向铺设 + 闭环整圈 |
| `tools/_wrapcheck.py` | 跨卷绕界 lane 重建保物品 + 物流塔只抓相邻格（不隔空吸货） |
| `tools/_statecheck.py` | 塔 3×3 占地不可侵占 / 塔与塔不重叠 / 机器面板点击区不残留 |
| `tools/_flowcheck.py` | 分拣器投递失败不吞货 / 无人机跨卷绕能到达 / 逆流带子能接矿 |
| `tools/_orbitcheck.py` | 行星轨道（M6.18）：公转推进与取模 / 太阳能倍率范围与 PowerGrid 集成 / 存档往返 / v8→v9 迁移 |
| `tools/_profile.py` | 各 update/sync 段分项计时，定位性能瓶颈 |
| `tools/bench.py` | 三段计时压测，`--preset small|10k|30k` |

改完任何 config / 解锁表 / 配方，先跑 `_startcheck.py` + `_deadlockcheck.py` + `_insertercheck.py` + `_machinecheck.py`
+ `_buildcostcheck.py` + `_craftcheck.py` + `_sciencecheck.py`。
改戴森云 / 轨道 / 太阳帆 / 发射器，必须跑 `_dysoncheck.py`。
改科技锁（`RECIPE_TECH`）或科研包配方（`TECH_PACK_RECIPE`），**必须**跑 `_deadlockcheck.py`。
改传送带 / 物流塔 / 物品流转，必须再跑 `_beltcheck.py` + `_wrapcheck.py` + `_flowcheck.py`；
改建筑放置 / UI 面板，必须再跑 `_statecheck.py` + `_uicheck.py`。
改箱子 / 采矿机暂存 / 机器手动存取（`production/storage.py`、`chests.py`、`miners.py`、
`machines.add_input|take_input|take_all_outputs`），必须再跑 `_storagecheck.py` + `_uicheck.py`。
改行星轨道 / 电力（`world/orbit.py`、`power/grid_power.py`），必须跑 `_orbitcheck.py`（新增）。
改存档结构，必须再跑 `_savecheck.py`（迁移链断言读 `SAVE_VERSION`，升版不用手改）。
新增/修改任何配方（`RECIPES`），必须跑 `_buildcostcheck.py`：
它第 6、6b、7、8 项会强制校验「配方 id 不得带 `hand_`/`mk_` 前缀（统一配方）」
「一个物品只能有一个配方」「所有配方的 `allows` 非空（必须能自动化）」
「`HAND_CRAFT_TIME_MULT > 1`」。**M6.6 起没有"只能机器做"的物品**，
`MACHINE_ONLY_ITEMS` 已删除。改配方 id 必须同步 `LEGACY_RECIPE_ALIAS`，否则老存档变哑巴。

## M5 已完成（多矿种 + 建筑物品化 + 科研包）
> 注：本节描述的是 M5 当时的状态。`hand_*`/`mk_*` 双套配方、`allows=None` 手搓、
> "手搓比工厂贵"这三条**已被 M6.6 统一配方推翻**，看 M6.6 节为准。

实际落地（和最初计划有出入的地方已就地调整）：

1. **多矿种**：`grid.ore_type` int8 数组，分区撒矿（中心铁 / 中环铜石 / 外环石铜）；
   `mine()` 返回物品 ID；采矿机和手动右键都按矿种给矿；`layers._draw_ore` 按 `ORE_COLORS` 分色。
2. **物品**：新增铜矿石/铜板/石矿/石材/铜线/磁铁/电磁矩阵，以及 10 个建筑物物品（101~110）。
3. **配方表**：`RECIPES` 结构改成 dict（`{in:..,out:..,time,allows}`），`allows=None` 表示手搓配方。
   熔炉 4 配方、制造台 4 物品配方 + 10 个 `mk_*` 建筑配方（DSP 原版价格）+ 7 个 `hand_*` 手搓配方。
4. **建筑物品化**：`BUILD_ITEM` 映射 + `STARTING_ITEMS` 开局库存；放置扣物品、缺料 toast、
   拆除全额返还；底栏按钮右下角显示库存角标（0 红底）；新增背包面板。
5. **手搓**：`ui/craft_panel.CraftPanel`，只列 `allows=None` 配方，×1/×10 按钮，材料不够灰掉。
6. **科研包**：`LabNetwork.stored` 改 dict；科研站只收当前科技需要的科研包；每 `LAB_CONSUME_INTERVAL`
   吃一个包给当前科技 +1；没在研究就只囤不烧。`TechTree` 去掉研究点积累，`TECH_TREE` 数字直接是
   需要的科研包数；全部科技挂一级电磁矩阵按成本分级。
7. **防死锁取舍**：为了让开局能自建制造台，`TECH_UNLOCK_BUILDING` 只剩两座物流塔受科技锁，
   其余建筑靠「物品门槛」gating（缺料底栏显示红 0）。手搓价一律高于工厂价，避免玩家绕过工厂。
8. **存档 v4**：新增 `ore_type` 数组、`inventory` dict、`lab.stored` dict；v3→v4 迁移全填铁矿/
   转背包/转电磁矩阵/清研究点。`SAVE_VERSION=4`。

## M5.5 已完成（分拣器过滤）

1. **数据结构**：`grid.overlay_filter` int32 数组（0=不限，其余=只抓该物品）。
   `place_overlay`/`remove_overlay`/`remove` 三处都清 0，不会残留。
2. **物流逻辑**：`InserterNetwork.update` 读过滤值，先和目标需求取交集，再抓货；
   `_grab`/`_grab_from_belt` 都加 `flt` 参数，非过滤物品放过让下游分拣器去抓。
3. **UI**：`ui/filter_panel.py`，查看模式下点分拣器打开，点"不限"清过滤，
   点物品格设为过滤。非查看模式不打开，避免抢传送带铺设的点击。
4. **可视化**：分拣器左上角画被过滤物品颜色的小圆点，一眼看出设置了啥。
5. **存档 v5**：`SAVE_VERSION=5`，新增 `overlay_filter` 数组，v4→v5 迁移全填 0。
6. **测试**：`_insertercheck` 加过滤混矿带 + 拆除清理 2 项；新增 `_uicheck.py`
   桩 pygame 集成测试 8 项（含过滤面板开合、写值、端到端）。

## M6 已完成（碳/物流容器 + 手动存取）
1. **箱子** `B_CHEST=12`（快捷键 8）：纯容器，每种物品堆 `CHEST_STACK=50`，不分输入输出，
   分拣器可双向搬。拆箱子退内容物。
2. **矿机缓冲** `MINER_BUFFER_CAP=50` 混装，先吐后挖，满了停挖不丢矿。
3. **机器手动存取**：`machines.add_input` 按配方过滤、`take_input` / `take_all_outputs`
   （没有 `add_output`，产物只能整体取，防手搓刷料）。
4. **UI**：`ui/storage_panel.py`（箱子/矿机通用）、机器面板加手动存取区。
5. **存档 v6**：`SAVE_VERSION=6`，存 `chests` / 矿机缓冲 / 机器 inputs+outputs。

## M6.5 已完成（合成面板改版 + 手搓兜底）
1. **面板 560×620 两栏**：左滚动产物列表（材料够高亮、不够灰显但仍可点开看缺什么），
   右原料明细 + 可做次数 + 做1/做10/取消。
2. **手搓耗时**：`CraftJob` 队列，点制作**当场扣料**再排队，`update` 用 `while` 消化 dt
   （低帧率一帧补多件不吞时间），面板关掉照跑，完成弹 toast。
3. **顺手修的真 bug**：桌面端 `_on_mouse_down` 没处理手搓/背包/过滤面板，
   面板开着点一下就穿透到世界放建筑（触屏走 `_handle_gesture` 所以只有桌面端中招）。
4. 补 9 条 `hand_*` 兜底（**M6.6 已全部并入统一配方，见下**）。

## M6.6 已完成（统一配方，当前最新）
1. **一个物品 = 一个配方**：`RECIPES` 重写为 18 条统一配方，id 无前缀，删光 `hand_*`/`mk_*`，
   删 `MACHINE_ONLY_ITEMS`。`allows` 全部非空 ⇒ **所有物品都能自动化**。
2. **`belt` 一份料出 3 条**：铁板 2 + 齿轮 1 → 带子 3（DSP 原版比例）。
3. **手搓慢而不是贵**：`HAND_CRAFT_TIME_MULT = 2.5`，手搓与机器同 ins/outs，
   耗时 = `dur × 2.5`。合成面板详情行显示 `手搓 X s/次（机器 Y s）`。
4. **科技锁收窄**：`RECIPE_TECH` 只锁"能不能用机器自动做"，不锁手搓。
   合成面板不再按 `allows` 过滤，`available_recipes` 过滤改 `not allows`。
5. **存档兼容不升版**：`SAVE_VERSION` 仍为 6，新增 `LEGACY_RECIPE_ALIAS`（28 条），
   `load` 时翻译旧 id，查不到就置 `None`（机器空转不崩）。
6. **自检重写**：`_buildcostcheck` 新增配方唯一性/全自动化/耗时倍率三项硬校验，
   `_deadlockcheck` 改语义为"手搓永远可行"，其余脚本同步改新 id。

## M6.7 已完成（M2 补齐：红科研）
1. **二级科研包**：新增物品 `I_SCIENCE_RED=12`（能量矩阵）和 `I_GRAIN=14`（硅石）。
   - `grain`：熔炉，石矿×2 → 硅石×1（1.0s）
   - `science_red`：制造台，磁铁×2 + 电路板×3 + 硅石×2 → 能量矩阵×1（5.0s）
2. **科技树扩到 11 条**：原 7 条蓝科技不变，新增 4 条红科技 ——
   `dyson1`（戴森云 I，前置 power1）/ `sail1` / `dyson2`（前置 dyson1+speed1）/ `speed3`（前置 speed2+dyson1）。
3. **科研包按科技分流**：`TECH_PACK_RECIPE` 前 7 条 → `science_blue`，后 4 条 → `science_red`。
   新增 `TECH_PACK_ITEM` 记录每种包的物品 ID。
4. **科研站囤包策略修正**：`_wanted_packs()` 在**没在研究时**返回所有科研包种类（蓝+红），
   这样玩家能提前把红囤进科研站，研究红科技时不用等分拣器现搬。
   原来只收蓝包，切红科技会卡一段空窗。
5. **科技面板文案动态化**：卡片和进度条不再写死"电磁矩阵"，改按该科技的科研包显示，
   否则 11 张卡全说"需要 N 个电磁矩阵"会让人误会。

## M6.8 已完成（M4 戴森云）
1. **太阳帆发射器** `B_EMITTER=13`（快捷键 `E`）：普通 1 格建筑，`allows=(B_ASSEMBLER,)`，
   配方 铁板8+电路板6+石材6+齿轮4 → 1 台（5.0s）。科技锁 `dyson1`。
   耗电 1.5/s。靠分拣器喂**太阳帆**进内置储存（上限 30），不接收其它物品。
2. **太阳帆** `I_SOLAR_SAIL=13`：制造台 硅石×2+铜线×2 → 帆×2（2.0s）。
3. **轨道**：`DYSON_ORBITS=3`（内/中/外），容量 60/120/200。
   - `dyson1` 解锁内轨，`dyson2` 解锁全部三条。
   - 发射器每 1.2s 自动打 1 片到**最空的已解锁轨道**，轨道满了就不再打（不丢帆，囤在发射器里）。
4. **发电**：总功率 = 帆数 × `DYSON_SAIL_POWER(12 kW)` × 效率加成（`sail1` 给 ×1.5）。
   直接计入 `PowerGrid.update` 的 supply，**不占地面格子、不受昼夜影响**。
5. **轨道图面板** `ui/orbit_panel.py`：顶栏「轨道」按钮 / 快捷键 `O`。
   同心轨道 + 中心恒星 + 帆点位（按角度均分，随轨道自转）+ 每轨载量 + 总发电统计 + 说明文字。
   面板不暂停游戏。
6. **存档 v7**：新增 `dyson` 段（`orbit_count` / `orbit_angle` / 发射器列表含 store+timer+launched）。
   v6→v7 迁移补空结构。发射器建筑本身在网格里，读档后 `sync()` 重建对象。
7. **底栏自适应两行**：建筑从 11 种涨到 12 种，底栏自动折成两行（每行 6 个，居中排），
   底栏高度比例从 0.14 提到 0.22，按钮不被压扁。顶栏按钮从 9 个增到 10 个。
8. **拆除返还**：拆发射器时把储存里的太阳帆退回背包（和箱子/矿机/机器一致）。
9. **新增自检** `_dysoncheck.py`（6 大项）：配方齐备与原料来源、物品↔建筑↔科技锁三件套、
   轨道按科技解锁 + 容量封顶 + 满了不能再打、发电公式与 `sail1` 加成、发射器储存上限与定时发射、
   戴森云存档往返。

## M6.9 已完成（手搓队列 bug：新任务顶掉旧任务）
1. **bug**：`CraftPanel` 只有一个 `self.job`，`start()` 里如果新配方 id 与当前任务不同，
   直接 `self.job = CraftJob(...)` 把旧任务连进度一起丢掉——材料已经扣了，产出没了，纯亏。
2. **改法**：`self.job`（单任务）→ `self.jobs`（有序列表）。
   - `start()` 追加到队尾；队尾如果已经是同一配方则累加 `left`，不刷重复行。
   - `update()` 只推进 `jobs[0]`，做完 `pop(0)` 后把**超出 dur 的剩余时间**接着喂下一个任务
     （`remaining = job.elapsed`），一帧内能跨多个任务，不吞时间。
   - `cancel()` 清空整个队列（按钮文案随队列长度变成「取消全部排队」）。
   - `self.job` 保留成只读 property 指向 `jobs[0]`，兼容 `game.py` 的完成 toast 和旧自检。
3. **面板显示**：队首进度条 + 第二行「排队 N 项：铜板×3 → …」，面板正文区下移 14px。
4. **自检**：`_uicheck.check_craft_queue()`，连排两个不同配方、验证旧任务进度不被改、
   同配方合并、全程产出正确、大 dt 跨任务不吞时间、取消清空队列。

## M6.10 已完成（底栏建筑分类制）
1. **动机**：建筑涨到 12 种，一行塞不下，手机上一格不到 40px；两行占屏又太狠。
2. **改法**：底栏只显示 6 个大类（物流带 / 生产 / 电力 / 物流塔 / 存储 / 科研·戴森），
   点大类从底栏正上方弹出一条子按钮，选具体建筑。
   - `touch_ui.CATEGORIES` 是唯一真相；`TOOLBAR` 由它展开生成（顺序固定，快捷键/校验都读它）。
   - 单个建筑的分类（存储）点了直接选中，不弹子条。
   - 再点一次已展开的大类 = 收起；点子建筑选中后自动收起父条（选中态仍高亮父大类）。
   - 展开的子条算进 `in_bars()`，点上去不会穿透到世界放建筑。
   - 键盘快捷键（1-9/0/L/E）选中建筑后，底栏自动展开它所在大类（`sync_open_category`）。
3. **底栏高度**：从两行的 0.22 降回单行 0.14，子条另占 0.10，只在展开时占用。
4. **自检**：`_uicheck.check_category_toolbar()`——大类数量与底栏按钮数一致、
   全部可建造建筑都被归类且不重复（`B_CORE` 不可建，排除）、默认收起、
   多建筑大类点开正确展开、子按钮区算 UI 区、点子建筑选中、再点取消收起、单建筑大类直接选中。

## M6.11 已完成（科研站双模式 + 研究队列 + 成就弹窗）
1. **动机**：科研站以前只会吃包，矩阵却由制造台造，玩家没法管研究节奏；科技一次只能研一个，
   换目标还得手动点；研究完成只有一行居中 toast，不够"里程碑感"。
2. **矩阵垄断**：`science_blue` / `science_red` 的 `allows` 从 `(B_ASSEMBLER,)` 改成 `(B_LAB,)`——
   所有矩阵只能由科研站制造，制造台面板不再列出，手搓面板用 `HANDCRAFT_BLACKLIST` 挡掉。
3. **科研站双模式**（`LabNetwork` 的 lab dict 扩展）：
   - `research`（默认）：只输入，吃当前科技需要的科研包，喂料/消耗逻辑同以前，不产出任何东西。
   - `produce`：选一种矩阵配方（`LAB_PRODUCE_RECIPES` 二选一），原料进、产物出，
     内部跑和 `Machine` 一样的配方计时逻辑（`_produce_update`）。
   - 分拣器双向打通：`feed` / `acceptable` 按模式分派，`grab` 让制造模式产物能被分拣器搬走，
     `put_back` 投递失败放回 `outputs`。
4. **研究队列**（`TechTree`）：`queue` 列表 + `can_queue`（前置在 researched/current/队列里即可排队）
   + `start`（没在研就开研，否则入队）+ `add_pack_progress`（完成自动接队首）。
   科技面板卡片支持"排队中"状态与队列预览。
5. **成就弹窗**（`ui/achievement.py`）：右上角 Minecraft 式滑入卡片，堆叠 5 条、4 秒淡出。
   `game._update` 每帧对比 `researched` 差集推送，队列自动接续完成也会弹。
6. **面板**：新增 `ui/lab_panel.py`，点科研站打开，顶部切模式、制造模式选配方、手动存取/全取产物。
7. **存档 v8**：lab 增加 `mode/recipe/inputs/outputs/progress`，科技增加 `queue`；v7→v8 迁移补齐默认值。
8. **自检**：`_uicheck.check_lab_panel()`（点开→切制造→选配方→喂料→产出→全取→切回研究）、
   `_uicheck.check_tech_queue()`（连排多科技→前置校验→完成自动接下一个）；
   `_sciencecheck` 第 1/7 项改判科研站，并新增第 8 项制造模式产出矩阵。

## M6.12 已完成（底栏统一展开 + 合成栏全量配方 + 机器面板产物选配方）
1. **底栏分类**：去掉"单建筑大类直接选中省一步"，**所有大类都展开**（哪怕只有一种建筑），
   行为统一；大类高亮条件加上"正展开"，所以只要展开就亮。
   注：M6.10 当初的"单建筑直接选中"作废，`_uicheck.check_category_toolbar` 已改成期待展开。
2. **合成栏全量配方**：`craft_panel._catalog` 不再过滤 `HANDCRAFT_BLACKLIST`——
   所有配方都列出来方便玩家查配方/知道去哪台机器造。选中不可手搓的配方时：
   右栏显示"该配方只能由机器制造，不能手搓"，**不给做1/做10按钮**。
   所有配方都显示一行"该配方可用于：<建筑名>"（读 `RECIPES[rid][3]` 的 allows）。
   左栏对不可手搓的配方右侧标签显示可用机器名，而不是可做次数。
3. **机器面板改产物选配方**：熔炉/制造台的配方选择从"一整行完整配方文本"改成
   **只列产物**（色块 + 产物名 + 耗时），选中 = 设该配方；选中后下方才显示原料槽。
   与手搓面板"先选产物、再显示原料"一致。

## M6.13 已完成（分拣器 带子→带子 堵死/丢物品修复）
**现象**：传送带→分拣器→传送带，来源带堵在分拣器前一格，后面全不走。

**根因（两条，一条致命一条隐形）**：
1. `InserterNetwork._acceptable_items()` 对目标传送带只判断"这格有 lane"就返回 `{-1}`（能收任意物品），
   完全不管这格塞不塞得进。目标带一满，分拣器仍然每帧去抓，抓到后 `_deliver` 的
   `try_insert` 失败，再 `_put_back` 放回——放回时用的是 `try_insert`（按**格头** pos=ci 插），
   而抓出来的物品原本在格内更靠后的位置。两个后果：
   - 物品被"拽回格头"，队首永远到不了格尾，上游全堵住（**看起来就是来源带堵在分拣器处**）；
   - 格头与上游邻居间距不够时放回失败 → 物品直接**凭空消失**（30 秒能丢 250+ 个）。
2. 投递失败后不设冷却，于是每帧都重复这套抓-放，放大了上面的问题。

**改法**：
- `BeltNetwork.has_space(x,y)`：不实际插入地预判这格还有没有位置（间距逻辑与 `try_insert` 一致）。
- `_acceptable_items` 的传送带分支改成"有位置才返回 `{-1}`，没位置返回空集"，分拣器直接不抓。
- `_grab_from_belt` 现在返回 `(item, ('belt', lane_idx, pos))`，记住精确位置；
  `_put_back` 走新增的 `BeltNetwork.insert_at(lane_idx, pos, item)` 按**原位置**插回
  （刚取出的槽位必然空，不查间距），彻底杜绝消失和拽回格头。

**自检**：`_insertercheck` 新增第 11 项 `check_belt_to_belt()`——源带向右 7 格 + 分拣器叠在末格 +
目标带向下拐弯 7 格，持续供料 30 秒后断言：①物品丢失=0；②源带队首顶到 `length`（不是被钉在格头）；
③再过 1 秒源带物品数量和位置纹丝不动（无抓放抖动）。

**铁律**：改分拣器抓取/投递逻辑，必须跑 `_insertercheck.py` 全部 11 项；
任何"抓出来再放回"的路径都必须能按原位还原，绝不允许"放不回就丢弃"。

## M6.14 已完成（矿脉无限）
- `WorldGrid.mine()` **不再递减** `self.ore`，挖完不置 `ore_type=ORE_NONE`，矿格永久可挖。
- `self.ore` 现在只是"这格有没有矿"的标记 + 渲染用数值，存档照旧往返，但不再当有限储量。
- 采矿机 (`miners.py`) 只判断 `g.ore[y,x] > 0`，天然变成无限产出，不用改。
- 注意：**老存档里已经被挖空的格子（ore=0 / ore_type=NONE）回不来**，类型信息已丢；新开档/未挖空的矿格永久无限。
- 自检：`_flowcheck` 新增第 4 项 `check_infinite_ore()`——同格连挖 5000 次，矿种不变、储量标记仍 >0。

## M6.15 已完成（制造台配方显示 + 传送带 rebuild 转角错位修复）

**问题一：制造台没有电路板配方。**

- 根因不是配方缺失：`circuit` 配方存在且 `allows=(B_ASSEMBLER,)`，但 `RECIPE_TECH={"circuit":"circuit1"}` 让 `available_recipes(researched)` 在未研究该科技时把配方整个过滤掉，面板里看不到。
- 改法（对齐 M6.12 合成栏"显示全部配方"原则）：`machine_panel.draw()` 改 `available_recipes(None)` 显示该机器全部配方，自己查 `C.RECIPE_TECH` 判断锁定；锁定行显示灰块 + `🔒 产物名 需 科技名`；`hit()` 对未解锁配方点了不切换；「无配方」单独处理。
- 自检：`_uicheck.check_machine_locked_recipe()`——制造台面板列出电路板、点击后 recipe 保持 None。

**问题二：每次放新东西传送带物品异常更新（转角飞出去）。**

- 根因：`BeltNetwork.rebuild()`→`_restore_items()` 用 `int(gx)` 取整猜格子，但 snapshot 坐标是 `x0+dir*pos+0.5`（格心偏移半格），转角处两条正交 lane 交界，同一坐标会落在多条 lane 的投影范围，取到哪条取决于字典序 → 物品被投影到隔壁格子甚至另一条 lane。
- 改法：重写 `_restore_items()` 为按 lane 轴向精确投影：对每个 snapshot 坐标遍历 lane，按方向反解 `pos`（右：`gx-x0-0.5`，左：`x0-gx+0.5`，下：`gy-y0-0.5`，上：`y0-gy+0.5`），垂直方向偏差 ≤0.6 过滤归属，`-0.5<=pos<length+0.5` 命中，`frac` 截断到 `[0,0.999)`；找不到归属（带子被拆）就地丢弃。
- 自检：`_beltcheck.check_rebuild_preserves_positions()`——水平带 + 转角垂直带，rebuild 前后各 lane positions 逐位一致（`[5.0,5.25,5.5,5.75,6.0]`）。

## M6.16 已完成（自动化死锁：电磁矩阵↔电路板环）

**用户报**：矩阵制造需要电路板，电路板需要科技，科技需要研究矩阵。

**根因**（就是第 16 条 TechDebt 坑的"自动化版"）：
```
科研站造电磁矩阵(science_blue) → 原料电路板
电路板自动化被 circuit1(RECIPE_TECH) 锁住
研究 circuit1 → 又要吃电磁矩阵
```
这是个**真环**：自动化产线永远推不动。手搓能硬绕（M6.6 起手搓不受科技锁），但玩家要的是全自动产线不靠手搓。

**改法**（全部在 config.py）：
1. `science_blue`：`磁铁×1 + 电路板×1` → **`磁铁×1 + 铜线×2`**。电磁矩阵不再依赖电路板，蓝包靠熔炉(磁铁)+制造台(铜线)就能全自动生产。
2. `assembler`（制造台）：`铁板×4 + 齿轮×8 + 电路板×4` → **`铁板×4 + 齿轮×4 + 铜线×4`**。制造台是自动化链入口，必须开局就能造（否则又回到"开局要制造台→制造台要电路板→电路板要科技"的坑）。
3. `lab`（科研站）：`铁板×8 + 石材×4 + 电路板×4 + 磁铁×4` → **`铁板×8 + 石材×4 + 铜线×4 + 磁铁×4`**。研究中心建筑同样不能依赖被锁原料。

**断环后**：`circuit1`（电子学 I）依然锁电路板配方（保持"科技解锁新配方"的意义），但现在研究它不需要电路板，环就断了——先自动化蓝包 → 研究出电子学 → 电路板再进产业链。红包（能量矩阵）继续吃电路板，体现"红科技更高级"。

- **新增自检**：`_deadlockcheck` 第 6 项「科技锁→科研包→被锁配方 自动化环」——被 `RECIPE_TECH` 锁住的配方，其产物不得出现在该科技科研包配方的原料里。回归：`circuit 被 circuit1 锁 + science_blue 吃电路板` 曾触发这项 FAIL，改成吃铜线后突破。

## M6.17 已完成（机器配方面板加大 + 三列表格）

**用户报**：配方选择页面配方多了会出问题。

**根因**：机器面板 380×470 小尺寸，配方按行**垂直**排（每行 26px）。制造台 16 个配方 + 「无」= 17 行 × 26px = 442px，光配方区就顶穿面板底部，直接把下面的生产进度/原料槽/产物槽全盖住。

**改法**（`machine_panel.py`）：
1. 面板尺寸 380×470 → **560×600**（宽 94%、高 90% 屏，跟合成面板接近全屏的风格一致）。
2. 配方从竖直列表改成 **3 列网格**（`_draw_recipe_cell`）：每个格子 34px 高、两行显示——第一行产物色块+名称（长名截断），第二行未锁定显示耗时、锁定显示 `🔒 科技名`。制造台 17 格 = 6 行 ≈ 228px，加面板高度 600px 完全放得下。
3. 「无」选项也进网格第一位，行为不变（点了清空配方）。

**自检**：`_uicheck.check_machine_locked_recipe()` 新增断言——所有配方格 `rect.bottom` 不得超出面板底部 30px 内，防止以后配方再加回来又爆版。

## M6.18 已完成（轨道系统最小版：行星公转）

> 注：M6.31 已把这一节的"正弦近似 / 手填周期"升级为**真实开普勒轨道**
> （真实半长轴/偏心率 → 周期由开普勒第三定律算出 → 日照 1/r²），
> 见下文「M6.31 已完成」。本节保留为当时的实现记录。

**动机**：三份文档（接力提示 / 意见2 / 星织md）一致指出"星织"的骨架——轨道、多行星、行星工程——完全缺席。
M6.18 是骨架第一块：一颗行星公转，把"轨道"这个词在游戏里立起来，给 M5 星际铺地基。

1. **`world/orbit.py` 新增 `PlanetOrbit`**：状态只有 `angle`（度，0 = 近日点），
   `update(dt)` 按 `PLANET_ORBIT_PERIOD`（600s = 10 分钟一圈）推进并取模 360。
   参数可在构造时覆盖（period / eccentricity），以后每颗行星一个实例就是 M5 多行星的地基。
2. **太阳能随相位起伏**：`solar_factor() = 1 + eccentricity × cos(angle)`，
   近日点 ×1.25、远日点 ×0.75（±25%）。`PowerGrid.update` 的太阳能发电 × 该倍率（`power.planet` 注入）。
   只影响太阳能，不影响核心/风力/戴森云；行星为 None 时倍率 = 1（自检和旧路径不回归）。
3. **轨道面板**：`OrbitPanel.show` 增加 planet 参数；戴森云三轨外画第四圈行星轨道，
   行星点位随角度公转；顶部统计加一行「行星 X° · 公转一圈 Ns · 当前光照 ×f」；底部说明补行星句式。
4. **顶栏**：主 HUD 状态行恒显示「光照 ×f」，不打开面板也能看到相位效果。
5. **存档 v9**：新增 `planet` 段（angle / period / eccentricity）。v8→v9 迁移补默认
   （angle 0 近日点）。**注意**：v7→v8 分支原本 `return data` 提前返回，会跳过 v8→v9，
   已改成 `v = 8` 级联继续走（_savecheck 迁移链 v1→v9 实测通过）。
6. **新自检 `tools/_orbitcheck.py`**（5 大项）：常量健全、公转推进/取模、
   太阳能倍率范围与 PowerGrid 集成（无行星不回归）、存档往返、v8→v9 迁移。

**设计定案**：
- 行星公转只对"太阳能"生效——风力和戴森云本来就是全时能源，这是"太阳能要挑时机"的玩法差异。
- 相位信息是全局太阳常数，不是昼夜（昼夜 120s 正弦照旧，两者相乘）。
- 老档迁移默认角度 0（近日点）会短暂让太阳能偏高，属预期，玩家下次保存后即按实际相位走。

**下一步：M5（星际 / 多行星 / 运输船）**：orbit.py 已经支持多实例，M5 就是
"第 N 颗行星 = 第 N 个 PlanetOrbit + 独立 WorldGrid + 运输船"。见下文下一步。

## M6.19 已完成（性能优化：还 TechDebt #8）

**动机**：bench 数据（10k ≈55fps / 30k ≈19fps）显示每帧全图扫描和逐物品绘制撑不住
手机 ARM。这轮只做零风险优化，细节和踩坑记录在 TechDebt #8 的 M6.19 小节。

1. **分拣器坐标集合（代数失效）**：`inserters.update` 原来每帧 `np.nonzero(overlay)`
   扫 26 万格。改成 `InserterNetwork.cells` 惰性集合，`grid.overlay_gen` 在放/拆
   overlay 时 +1，集合代数不匹配就重建；读档后 `overlay_gen += 1` + `invalidate()`。
   `_draw_machine_status` 的分拣器箭头也复用同一集合。实测 empty 扫描 0.62 → **0.007ms**。
2. **物品渲染向量化**：`_draw_items` 从"逐物品 world_to_screen + 逐格 draw.circle"
   改成"每条 lane 一次 numpy 批量算屏幕坐标 + 可见掩码 + 预渲染 sprite blit，
   Python 循环只跑屏内物品"。30k 物品实测 **17-18ms → 3-4ms（4.4-5.9x）**。
3. **无人机 sprite blit**（1.0x，纯统一写法）。power.update 试过 `np.bincount` 反而
   慢 6 倍已回退（详见 TechDebt #8 踩坑记录）。

**自检**：17 个自检全绿（新增 `_multiworldcheck`）+ 真实 Game 读档/30 帧渲染/存档往返冒烟通过。

**结果**：bench 10k TOTAL 18.1 → 11.0ms（FPS ≈91，60fps 转 PASS）；30k 52.4 → 35.1ms
（FPS ≈29）。剩余大头：`belts.rebuild` 40-90ms 尖刺（只在放/拆建筑时触发，改增量风险高，
留到最后）和 towers.update 1.8ms。

## M5a 已完成（星际骨架：双行星 + 行星切换）

见 TechDebt #31 全记录。要点：
1. **多行星**：`world/planets.py` 定义 2 颗行星（故乡星/余烬星，seed/周期/偏心率不同）；
   `core/worldstate.py` `WorldState` 把"一颗行星"包成 独立网格 + 全套网络 + 轨道 + 相机。
   `Game.worlds` 持有全部，`Game._activate_world(i)` 把组件挂回同名属性（其余代码零改动）。
2. **行星切换**：轨道面板每颗行星一个圆点（位置随公转相位动），点非当前行星的前往；
   当前行星白圈高亮；HUD 状态栏带头显示「行星 名字」。切星关掉所有面板 + toast。
3. **科技/背包/戴森云跨行星共享**（恒星级/玩家级）；戴森云发射器只在当前行星工作。
4. **存档 v10**：`worlds` 数组 + `world_index`；v9→v10 迁移把平铺结构打包进 `worlds[0]`。
   真实 v8 存档实测读回：主星 141 格建筑/393 物品保留，切星往返一致。
5. 新自检 `_multiworldcheck.py`（17 项）。

**已定 M5 范围**：本轮故意不做运输船（星际物流）——行星间目前只能"人过去 + 背包手搬"，
运输船 + 发射窗口预测 UI 是 M5b（见下）。

## M6.20 已完成（多存档槽位）

见 TechDebt #32 全记录。要点：
1. **6 个固定槽位**（`slot_1..6.slm`，不占自动档）：顶栏「存」「读」打开存档面板，
   每槽显示 时间/行星/物品数/版本（`slot_meta` 只解压读摘要，不重建游戏）。
2. **F5 快速存档**：存到 `current_slot`（点过哪个槽存过就切到那）；F9 打开读档面板。
3. **迁移保护**：读面板底部有「读最新自动存档」和「读旧档 save.slm」两个入口——
   多存档上线前的进度不会被"弄丢"，读完手动存槽即完成迁移。
4. 读档收尾统一到 `_load_game(name)`，槽位/自动档/旧档三个入口共用。
5. 自检：`_savecheck` 加多存档段（两槽独立不被污染/摘要/空槽/自动档文件），
   `_uicheck` 加 `check_save_panel`（面板存/读/快速存档/空槽行为）。

## M6.22 已完成（UI 定义化：控件级 JSON）

见 TechDebt #34 全记录。要点：
1. **机制**：`ui/uidef.py` —— JSON 控件定义加载器。`defs/*.json` 里以控件为单位
   描述 UI：`meta`（主题色/常数）+ `controls`（label/button/list 控件：位置锚点、
   字号、颜色、文案）+ 可选 `buttons`（顶栏这种 {action,text} 序列）。
   颜色统一 `#RRGGBB[AA]`；位置支持 tl/tr 锚点、负坐标（距右/下缘）、负尺寸。
   运行时 `draw_controls / hit_control` 一个入口画/命中，业务只传 overrides
   （动态文案/显隐/高亮）。**改 JSON 不改代码**（自检 2 实测改 x:10→100 生效）。
2. **示范迁移 1 —— 存档面板**：外观（面板底色/边框/掩膜/按钮/行/标题/底部捷径）
   全部来自 `defs/save_panel.json`；槽位动态列表按 defs 模板参数渲染。
3. **示范迁移 2 —— 顶栏按钮**：`defs/touch_top.json` 定义 10 个按钮的顺序/文案，
   布局参数（间距/宽度比/边距）在 meta；增删/改序按钮只动 JSON。
4. **新自检 `_uidefcheck.py`**（全套 18 项）：加载器单元（锚点/颜色/错误路径）、
   临时 JSON 改文件生效、存档面板 JSON 绘制与命中、顶栏顺序/动态文案。
5. 其余面板（存储/机器/科技/合成/轨道等）按同一机制**逐个迁移**，见 TechDebt #34
   迁移清单——不一次全改，防回归。

## M6.24 已完成（架构分层：服务器端 sim + 前端渲染）

见 TechDebt #36 全记录。要点：
1. **服务器端 `stellarloom/sim/`**（headless、**零 pygame**）：`Simulation` 类持有
   全部可玩状态（行星世界/科技/戴森云/背包/手搓队列），`step(dt)` 推进所有模拟，
   指令 API（放置/拆除/铺带/放分拣器/手搓/过滤/切星/存读档）接收前端输入，
   事件流（toast/成就/脏格子）供前端帧末拉取。
2. **前端 `core.Game` 瘦身**：只做 渲染 + 输入翻译 + UI；逻辑状态的属主换成
   `sim`（Game 引用 sim 的同名对象）。`_update` 的逻辑段 = `sim.step` + 事件消费。
3. **物理移出逻辑层**：`Camera` 摘掉 pygame 依赖（pan 键常量本地化）；
   `ChunkRenderer`（纯渲染缓存）移出 `WorldState`，前端按行星并行持有。
   `core/__init__` 改懒加载 `Game`——headless 链永不触 pygame（子进程断言过）。
4. **headless 运行器**：`python -m stellarloom.sim.headless [存档] [tick]`——
   无图形跑模拟（真实档 2435 tick/s），服务器端可独立测试/基准。
5. **新自检 `_simcheck.py`**（第 19 项）：零 pygame 断言 / headless 推进 /
   指令闭环（放置→拆除退款守恒）/ Game-sim 同源 / 存读档往返。
6. 手搓队列从 `ui/craft_panel.py` 抽到 `sim/craft_queue.py`（CraftQueue），
   面板纯显示。全套 **19 项自检全绿**，真实存档 headless 读档通过。

## M6.25 已完成（主菜单）

见 TechDebt #37 全记录。要点：
1. **启动即主菜单**：世界在背后生成（暂停态的活动背景），菜单是顶层的半透明
   封面。按钮：开始新游戏 / 继续游戏 / 读档 / 退出。
2. **外观走 UI 定义层**（`defs/main_menu.json`）：标题用新增 `cc`（居中）锚点，
   "继续游戏"用新增 `disabled` 态（无自动档时灰置不响应）——先给 uidef 加了
   `cc` 锚点 + disabled override 两个通用能力。
3. **新游戏 = 重建 sim**：`_start_new_game()` 新建 `Simulation` 并保留存档目录
   （只重置世界，**存档文件一律不动**）。
4. **继续游戏 = 读最新自动档**：无档时按钮灰置；"读档"进多存档面板。
5. **菜单是最强拦截层**：点按/拖动/捏合/滚轮全部被菜单吃（M6.23 面板拦截清单
   补齐菜单一项）；菜单打开时世界模拟暂停（等同暂停键）。
6. 顶栏新增「菜单」按钮（`touch_top.json` 末尾 = 最左侧），随时回主菜单。
7. **新自检 `_menuecheck.py`**（第 20 项）：定义加载/命中/禁用态/菜单拦截世界/
   关闭恢复/顶栏入口/新游戏重建/继续游戏读档/ESC。全套 **20 项自检全绿**，
   640×480 与 720p/竖屏布局均不越界。

## M6.26 已完成（面板 JSON 化推进 + 全局主题皮肤化）

TechDebt #34 迁移清单推进：
1. **uidef 两处升级**：
   - `load_def` 合并 `defs/theme.json` 的 meta 作为**全局兜底**（面板自己的
     meta 优先）——改 theme.json 一处、全面板换色，皮肤化的地基。
   - `overrides["color"]`：单控件换色（塔标题 供应绿/请求橙 动态色用）。
2. **四个面板迁到 defs JSON**（外观/配色/静态文案/布局参数全下沉）：
   - `filter_panel.json`（标题/当前/不限按钮/3 列网格模板）
   - `bag_panel.json`（标题/两列条目模板）
   - `lab_panel.json`（标题/研究·制造模式按钮——切换走 hit_control + active）
   - `tower_panel.json`（标题动态文案+颜色、库存标签）
   动态内容（物品行、配方行、无人机条、进度条）仍业务画，但颜色全取
   meta_c——主题色一处换，四个面板跟着变。`_uidefcheck` 加 [5] 段：
   主题兜底/面板覆盖/color override/四面板 draw 冒烟。
3. 面板公开接口（show/draw/hit/open）零变化，调用方一个没改；
   唯一测试适配：`_uicheck` lab 用例的模式按钮从 `_btn` 找改成 defs rect + hit。
4. 全套 **20 项自检全绿**，零回归。

## M6.27 已完成（MOD 支持：mixin 非永久补丁 + API 暴露）

用户点题两种形态都落地（用户拍板：mixin **全开放**、内容扩展 API 一起做）：

1. **目录与加载**：`mods/<名字>/`（mod.json 元数据 + main.py 入口），Game 构造时
   扫描加载。失败隔离：坏清单/语法错/on_load 抛错 → 该 mod 记 `failed` 并
   UI toast 提示，其余 mod 照常，游戏不崩。按目录名排序，确定性。
2. **mixin（非永久）**：`ctx.mixin(target, method, wrapper, wrap)`——运行时
   monkey-patch 只动内存、源码零改动；before（可替换参数）/after（可覆盖
   返回值）/replace（全权接管）三类；加载器记住原方法，卸载/重载逆序还原。
   全开放：任何类任何方法可 patch（用户选择），加载器只保证单 mod 隔离。
3. **API 暴露**（`stellarloom/api.py`）：ModContext——`sim` 引用（只读查询+
   指令 API）、`add_item`/`add_recipe`（配方 4 元组格式与原版一致，手搓/机器
   自动可见，id 冲突拒绝）、`on_step`/`on_event` 钩子（Game 每步进/事件流
   转发）、`log`/`toast`。内容注册随卸载撤销（重载幂等）。
4. **实现细节**：`fab` 失败的 main.py 必须清掉 sys.modules 半成品（否则二次
   加载误判成功）；卸载按注册逆序（patch 后 add_recipe 顺序无关，各自还原）。
5. **自检 `_modcheck.py`（第 21 项）**：加载隔离 / 三类 wrap 生效 / 内容注册
   与冲突拒绝 / 手搓闭环（mod 配方可 do_craft）/ on_step·on_event / 卸载还原
   （patch + 内容注册）/ 重载幂等 / 真实 Game 挂载。**全套 21 项全绿**。
6. **开发者文档**：`Docs/Mods.md`（目录结构 + ctx 能力全览 + 注意事项）。
7. **开箱示例 mod**：`mods/example_speed_belt/`（传送带 ×2，mixin before
   换参一行改动 + 自带教学 README，可直接复印改造成自己的 mod）。

## M6.28 已完成（配方 JSON + 窗口化 + 配方选择器 + 科技树 + 模组管理）

五项一起落地，全套 21 项自检全绿：

1. **配方 JSON 化**：内置 23 条配方从 `config.py` 迁到 `stellarloom/data/recipes.json`
   （启动时 `import config` 即加载，格式保持 4 元组 `(inputs, outputs, dur,
   machines)` 零改动消费者）。`data/__init__.py` 加载时校验：缺字段 / 数量非法 /
   引用了未注册物品 id → 启动即报 ValueError（与 UI defs 同铁律）。mod 的
   `ctx.add_recipe` 注入同一 dict，两者天然统一。
2. **面板窗口化**：`uidef.draw_window` 统一画「底 + 圆角边框 + 左上角等腰梯形
   标题栏」（h 由 theme.titlebar_h 兜底 26，外观仍在各面板 JSON）。`ui/window.py`
   WindowMgr 提供拖标题栏移动（触屏 Tap→Drag→抬起 / 鼠标左键拖），Game 手势
   接入，浮窗面板（orbit/save/storage/lab/machine/tower/filter/bag）全部可拖，
   位置限幅不飞出屏外；craft/tech 两张全屏页不参与。
3. **机器配方选择器**：MachinePanel 主界面瘦身为「当前配方卡 + [点击选择配方]」，
   点击打开选择器页（按机器类型 + 已解锁过滤，同合成面板风格的行列表：产物 →
   原料 → 耗时，未解锁标 🔒 点不动、当前配方 √ 高亮），选中即切回主界面。
4. **科技树树状图**：TechPanel 重写为有向树（X = 前置链深度、Y = 层内堆叠，
   父→子折线相连），拖动/滚轮平移视角，点节点展开底部描述条（需要科研包 /
   前置 / 解锁内容 / 未解锁色态），描述条 [开始研究]/[排队研究] 按钮。
5. **模组管理页**（仿 minecraft）：主菜单加「模组」按钮 → 全屏遮罩页列出
   `mods/` 所有 mod（名称/版本/描述/状态：已加载/加载失败原因/已禁用），每行
   [禁用]/[启用] 开关——写 `mods/.disabled` 名单并热重载其余 mod，即时生效。
   ModManager 新增 `available()/status_of()/set_disabled()`。返回主菜单继续。

**测试基线修正**：`_uicheck.new_game` 现在先 `mod_mgr.unload()` 卸掉真实
mods/（玩家 mod 的 mixin——如 gregtech 系列 replace `MachineNetwork.sync`——
会污染进程内类状态，连跑用例互相踩）；`_uicheck` 增科技树用例 + 机器面板
「已解锁选配方生效」断言；`_modcheck` 增禁用名单/.disabled 持久化/面板冒烟用例。

## M6.29 已完成（MOD 统一配置 + 依赖关系 + 科技树连线修复 + UI 全面审计）

1. **统一 config 存/写**：mod 包内 `config.json`（作者默认，随 mod 分发）⊕
   用户 `mods/config/<名字>.json`（运行时 `ctx.save_config()` 写入，独立于
   mod 包，卸载/重载不清、重启保持）→ 合并结果即 `ctx.cfg`。
   API：`ctx.cfg`（dict，可读可改）/ `cfg_get(key, default)` / `cfg_set(key, v)`
   / `save_config()` / `config_path`；保存时非 JSON 类型自动容错转字符串。
   作者默认坏 JSON / 用户配置坏 JSON → 该 mod 记 failed，其余照常。
2. **依赖关系**：`mod.json` 可选 `dependencies`（`{"mod名": "版本表达式"}`，
   支持 `> >= == < <=`，裸数字=精确、空串=任意版本）。按依赖**拓扑序**加载
   （不再靠目录名字母序）；缺依赖 / 版本不满足 / 依赖者加载失败 / 依赖环 →
   该 mod failed 并跳过；禁用某 mod 会使依赖它的 mod 以"缺少依赖"失败。
   模组管理页右栏显示依赖列表与配置状态。
3. **科技树连线重构（修"连线绕成一坨"）**：根因是"最长前置链"分层让父子
   深度差 ≥ 2，中线必落进中间整列节点。改 **BFS 最短路径分层 + 父子严格
   递增修正 + 每子只画一条"最深父"主路径线**——三段线全走 52px 列空隙。
   实测：原版 11 科技（8 线）与 **gregtech 30 项科技（27 线）均 0 处穿节点**。
4. **UI 重叠/超框全面审计**：写"探针字体"审计脚本（render 产出唯一色块、
   按颜色反查每个文字的真实渲染矩形，判定重叠与越界）——在 1280×720 /
   竖屏 720×1280 / 600×900 / 1920×1080 四种尺寸下，13 个面板 + 配方选择器
   全部干净（含真实 mods 加载时）。

**测试**：`_modcheck` 增 [9] 统一 config（合并/落盘/坏文件隔离）与 [10] 依赖
（拓扑序/版本门禁/缺依赖/环/禁用传导/版本比较单测）；全套 **21 项自检全绿**。

## M6.30 已完成（Minecraft 风格注解 mixin）

mod 的 mixin 写法升级为 Minecraft/Fabric 风格——类注解 + 方法注解，加载
main.py 时自动收集注册（on_load 之前生效），无需手动调用：

```python
from stellarloom.api import Mixin, Inject, At, Overwrite

@Mixin("stellarloom.sim.sim.Simulation")   # 目标：点分路径或类对象
class SimPatches:
    @Inject(method="place_building", at=At.HEAD, cancellable=True)
    def block_spot(self, btype, gx, gy, rot, cir):
        cir.cancel(); cir.set_return("blocked")   # 跳过原方法

    @Inject(method="place_building", at=At.RETURN)
    def annotate(self, btype, gx, gy, rot, cir):
        cir.set_return(cir.get_return() + "_loud")  # 覆盖返回值
```

- `CallbackInfo`（camelCase 别名齐活：`isCancelled/setReturnValue/
  getReturnValue`）；HEAD 改 `cir.args[i]` 可换参；`@Overwrite(method=...)`
  全权替换。
- 与原 `ctx.mixin()` 函数式接口**共存**：同一还原链、同一失败隔离
  （写错目标类/方法 → 该 mod 加载失败并显示原因）；重复注册按注入函数
  id 去重，卸载/重载可重新应用。
- `ctx.mixin()` 的 target 顺带支持传类对象（不必转点分字符串）。

**测试**：`_modcheck` 增 [11] 注解 mixin（@Mixin 字符串/类对象 target、
HEAD cancel、RETURN 覆盖、Overwrite、自动收集、卸载还原、坏目标失败隔离）；
全套 **21 项自检全绿**。

## M7 已完成（MC 风格物品注册表：命名空间 + 动态分配 + 持久化名字化）

1. **注册表**（新增 `stellarloom/registry.py` `ItemRegistry`）：名字 ↔ 数字 id
   双向表。原版命名空间固定 **`stellarloom:`**（`stellarloom:iron_ore`）；
   mod 用自己目录名。名字 = 持久化/交互表示；数字 = 运行时内部表示——
   inventory dict、机器槽、渲染查色这些 int 键**消费方零改动**。
2. **启动动态分配**：`ctx.add_item("mymod:foo", ...)` 名字注册 → 自动分配
   id（从 16 起，跳开原版固定段 1–15 / 101–114）；旧式数字
   `ctx.add_item(300, ...)` → 固定段兼容（键 `mymod:item300`，旧档可反查）。
3. **持久化名字化（存档 v11）**：savefile 的物品字段（背包/机器/矿机/箱子/
   塔/科研/无人机/传送带物品）全部存 `命名空间:名字`；v10 及更老数字档
   读档时数字直通可反查；未知名字（mod 卸载）汇总为 -1 显示 "?"。
   迁移链 v1→v11 测试齐全。
4. **配方 JSON / add_recipe 名字化**：`recipes.json` 与 `ctx.add_recipe`
   的原料/产物用名字（数字仍兼容）——顺带解决 TechDebt #41 的"裸数字
   不可读"遗留。
5. **边界（诚实）**：网格地块数组（building/overlay/ore）与建筑类型 B_*
   暂保持数字（非物品清单）；`overlay_filter` 也保持数字（UI 用注册表
   显示名）。见 TechDebt #42。

**测试**：`_savecheck` 增"M7 存档名字键 + 旧数字档兼容 + 迁移链"；
`_multiworldcheck` 增"迁移后物品键是名字"；`_modcheck` 增 [12] 注册表
（动态分配/固定段/视图同步/名字配方/存档名字化/冲突拒绝/卸载还原）。
全套 **21 项自检全绿**。

## M8 已完成（建筑注册表收口：建筑类型也进 MC 风格注册表）

1. registry.py 新增 `BuildingRegistry`：名字 ↔ 数字 id。原版建筑固定段
   1-15（`stellarloom:belt` … `stellarloom:planet_engine`）；**动态段从 100 起**，避开原版与存量
   mod 硬编码段（重工 20-23、星海 30-37）——新老建筑永不撞号。
2. config.py：B_* 常量改由注册表生成（值不变）；`BUILDING_NAMES` 变
   注册表实时视图（mod 注册后 UI 立即可见，消费方零改动）。
3. `ctx.add_building(btype, name=None, item=None)`（M8 新 API）：
   - 名字注册（"mymod:foundry"）→ 动态分配 id（≥100）；
   - int 旧式 → 固定注册，键 `mod名:b<id>`（给存量硬编码段登记显示名）；
   - `item=` 建筑物品名/数字 → 自动注册 `BUILD_ITEM[btype]` 联动
     （底栏取物 / 放置消耗 / 拆除返还直接生效）。
4. `ctx.add_recipe` 与 `recipes.json` 的 machines 解析建筑**名字**
   （原版/新 mod 同源），未注册建筑拒绝。
5. **边界**：网格地块数组与存档仍存数字建筑 id（#42 同款理由）；
   存量 mod（gregtech_*）硬编码建筑段不进注册表、照常运行。

**测试**：`_modcheck` 增 [13] 建筑注册表（动态分配 ≥100 / 视图同步 /
BUILD_ITEM 联动 / 固定段兼容 / machines 名字解析 / 未知机器拒绝 /
卸载还原）。全套 **21 项自检全绿**。

## M5b 已完成（星际物流：发射台 + 运输船 + 发射窗口）
见 TechDebt #44 全记录。要点：
1. **发射台**（`logistics/pads.py`，3×3，网格只记中心格）：
   - 两种模式：`supply` 供货（相邻带子吸货，装船发出）/ `request` 要货（卸货后往相邻带子吐）。
   - 放置检查同塔：3×3 全空且不与其它 3×3 大件（塔/发射台）重叠；拆除退库存/退建筑物品/撤船。
   - 每座供货台自动配 1 条运输船；模式切换实时增删船。
2. **运输船舰队**（`Fleet`，挂在 Simulation 上，恒星级跨行星）：
   - 状态机 `docked → outbound → inbound → docked`；坐标记 `(world_index, pad_x, pad_y)`。
   - 装货上限 `SHIP_CARGO_CAP=20`，飞行时长随相位差（`SHIP_FLIGHT_BASE × 0.6~1.4`）。
   - 目标台满仓 / 目标被拆 → 剩货原路带回，母台卸货；母台被拆 → 船一并清掉。
3. **发射窗口（相位对齐）**：
   - 两颗行星相位差（取小角）≤ `SHIP_WINDOW_ANGLE=30°` 才能发射，窗口随公转自然开合。
   - `pads.window_wait()` 算下一次窗口剩余秒数（同周期 → 无窗口），发射台面板实时显示。
     （M6.31 起改用真实轨道数值解，见下。）
4. **科技/配方**：新科技 `interstellar1`（40 红瓶，前置 drones1+dyson1）解锁发射台；
   配方 `launch_pad`（铁板12+电路8+齿轮6+铜线4，制造台 8 秒）；物品 `stellarloom:launch_pad`。
5. **UI**：底栏「物流塔」类新增发射台；点发射台开 `pad_panel`（模式切换 / 目标行星 / 窗口倒计时 /
   船状态 / 库存）；轨道面板画在途船（按航程插值在两行星连线上）并显示到下一颗星的下个窗口。
6. **存档 v12**：每行星 `pads[]` + 顶层 `ships[]`（含在途船状态/货物）；v11→v12 迁移补空表。
7. **测试**：新自检 `tools/_shipcheck.py`（8 段），全套 **22 项自检全绿**。

## M6.31 已完成（真实行星参数：开普勒轨道、真实周期、1/r² 日照）

见 TechDebt #45 全记录。要点：
1. **真实数据表**：`world/planets.py` 的 `PlanetDef` 改为真实轨道参数——
   `a_au`（半长轴 AU）、`eccentricity`（真实偏心率）、`arg_peri`（近点辐角）。
   故乡星 = 地球参数（a=1.00000, e=0.01671），余烬星 = 火星参数（a=1.52371, e=0.09339）。
   公转周期不再手填：`orbit_period` 属性按开普勒第三定律 `T(年)=a^1.5` 自动换算
   （地球 600s、火星 1128.5s；均为 1 年 = `SECONDS_PER_YEAR=600` 秒）。
2. **开普勒运动**：新模块 `world/kepler.py`（牛顿法解开普勒方程、真/平近点角互转、
   椭圆半径、`period_seconds/period_days`、`semi_major_from_period`、`orbit_points`）。
   `PlanetOrbit` 内部以**平近点角**推进（匀速），对外给真近点角 `angle` 与日心距
   `radius_au`——近日点快、远日点慢，轨道是椭圆而不是圆。
3. **日照真实**：`solar_factor() = 1/r²`（1 AU = 1.0）。地球 ±3.4% 小幅起伏，
   火星 0.36~0.52 大幅偏弱——行星间能源差异第一次有了物理依据。
4. **轨道面板**：按真实半长轴比例画**椭圆**（近点辐角旋转），行星点在真近点角处；
   顶部显示「真近点角 · 距恒星 AU · 日照 ×」，底部显示「半长轴 / 偏心率 / 真实周期（地球日）」。
   点行星切换的命中判定与绘制共用 `_planet_xy()` 一套坐标。
5. **所有行星都公转**：`sim.step` 里遍历 `worlds` 推进（不再只转当前行星），
   否则切星后相位冻结、发射窗口预测失真。
6. **发射窗口预测**：真实轨道没有解析解，`pads.window_wait/hold` 改为
   「相对平近点角每步 5° 粗扫 + 25 次二分」数值解（实测 0.11 ms/次，边界精确到 30.0°）。
7. **存档**：planet 段新增 `mean_angle / a_au / arg_peri`（版本仍 v12，向后兼容）；
   老档只有 `angle/period/ecc` 时按周期反推半长轴，行为不变。
8. **测试**：`_orbitcheck` 重写为真实物理断言（开普勒第三定律/方程互逆/椭圆近日远日/
   1/r² 日照/存档往返/老档兼容）；`_shipcheck` 窗口对照改为开普勒数值积分；
   `_multiworldcheck` 用面板 `_planet_xy` 命中。全套 **22 项全绿**。

## M6 已完成（行星工程：行星引擎 + 变轨 + 温度联动）

见 TechDebt #46 全记录。要点：
1. **行星引擎**（`B_PLANET_ENGINE=15`，3×3，网格只记中心格）：科技 `engine1`
   （行星工程 I，80 红瓶，前置 interstellar1 + dyson2）解锁；配方
   `planet_engine`（铁板24+电路16+齿轮12+铜线12+石材12，12 秒）；耗电 40 kW/s。
   放置检查同塔/发射台（3×3 全空且不与其它 3×3 大件重叠），拆除退建筑物品。
2. **变轨**（`sim.set_orbit_a_ratio / nudge_orbit_a / shift_orbit_phase`）：
   - 半长轴范围原始值的 **60%~180%**（`ENGINE_A_MIN_RATIO/MAX`）；
   - 改 a 后周期按开普勒第三定律自动重算（推远更慢），日照 1/r²、温度随之变；
   - 相位按 `ENGINE_PHASE_STEP=15°` 一档平移平近点角，发射窗口立即改变；
   - **必须通电**：引擎存在且电网供电比例 ≥ `ENGINE_POWER_MIN_RATIO=0.5`，
     否则按钮不生效（防止"没电还想推星球"）。
3. **温度联动**：平衡温度 `T = 288 K × r^-0.5`（地球 1 AU ≈ 15°C，火星 ≈ -40°C）。
   超过 `ENGINE_TEMP_SAFE_C=35°C` 后太阳能效率每度 -0.5%，下限 0.35——
   推近恒星亮度涨、效率跌，存在收益递减；推远则几乎不发电。
4. **UI**：底栏新增「行星」类；3×3 ghost 预览；点引擎任意格开 `engine_panel`
   （状态/半长轴/周期/日心距/光照/温度/效率 + 半径 ±10% + 相位 ±15°）；
   HUD 有引擎时显示「轨道 ×ratio（缺电）」。
5. **存档**：不加字段（planet 段已有 a/period/mean_angle，建筑 id 走 grid），
   版本仍 v12，读写实测往返一致。
6. **测试**：新自检 `tools/_enginecheck.py`（10 段：注册/科技门禁/放置拆除/
   电网需求/断电不变轨/半径与周期/相位/温度降效/电网集成/存档/面板），
   全套 **23 项自检全绿**。

## M6.32 已完成（星系视图与缩放衔接；轨道只做戴森）

见 TechDebt #47 全记录。要点：
1. **缩到最小继续缩小 → 星系视图（全屏界面）**：滚轮 / 鼠标 4·5 键 / 双指捏合统一走
   `Game._zoom_by`；相机到 `ZOOM_MIN` 后继续缩小攒 `_zoom_pull`（0~1），
   屏幕顶部显示进度条「继续缩小进入星系视图 N%」，满 100% 切到全屏星系视图
   （整屏星空背景，不画地表、不带弹窗外框，每帧照常翻页）；进度**粘性**（不自己掉），
   3 次滚轮或几次捏合就满，也可**直接点进度条**进入。
2. **回地图**：星系视图里放大（滚轮上 / 捏合放大）、ESC 或点「返回地图」退出，
   缩放保持不变；整屏切回地表。
3. **轨道只做戴森**：底部说明去掉行星轨道参数，改为「点轨道环指定发射目标轨道」；
   `DysonNetwork.target_orbit` + `set_target_orbit()`（点同一环取消、只认已解锁环）；
   发射优先玩家指定轨道，满了回落"自动选最空"；目标环黄色高亮 +「◀目标」。
4. **导航保留**：点行星圆点仍然切换行星。
5. **存档**：dyson 段新增 `target_orbit`（老档缺字段 → 自动），版本仍 v12。
6. **测试**：新自检 `tools/_viewcheck.py`（8 段），全套 **24 项自检全绿**。

## M9 已完成（真电网：电力塔分区 + 真实单位）

见 TechDebt #48 全记录。要点：
1. **单位换成 kW**：制造台 40 kW、太阳能 60 kW、核心 160 kW、行星引擎 800 kW、
   戴森帆 240 kW；显示自动 kW/MW。旧"抽象单位"×20 = kW（`POWER_LEGACY_SCALE`）。
2. **电力塔**（建筑 16 / 物品 115 / 3 铁板 + 4 铜线）：1×1、无耗电，底栏「电力」类可造。
3. **分区**：电力节点（发电/耗电/分拣器叠加层/塔）距离 ≤8 格即并网，并查集连通；
   每网独立算供/需/比例，`factor_at(x,y)` 供机器、科研站、发射器、行星引擎取自己网的比例。
4. **摊派**：戴森云与旧 mod 注电按各网需求比例分；无负载的网不占电。
5. **兼容**：~~全图没有一根电力塔时退回旧全球电网~~ —— **M14b 已废除**，
   现在无塔也按 8 格分区（见下）；`power.last_supply += x` 的旧 mod 写法仍按 ×20 记全局注电。
6. **测试**：新自检 `tools/_powercheck.py`（10 段），全套 **25 项自检全绿**。

### 电网强制分区（M14b 补正）

**问题**：M9 留了"没有电力塔 → 全球一张网"的旧档兼容。结果玩家铺了风车、没铺塔时
永远只看到一张网，分区系统等于被藏起来（用户拿旧档 slot_1 实测：2 台风力 + 0 座塔，
HUD 仍是 1 张网）。

**改法**：删掉 `_legacy` 分支，一律按 `POWER_LINK_RANGE=8` 连通分区——8 格内自动并网、
超了就是两张网，跨远必须铺电力塔。旧档读入后 `PowerGrid.starved_nets()` 统计
"有负载却没发电"的网，`Game._warn_power_partition()` 立刻提示
「电网已按 8 格分区：N 张网缺电（共 M 张），用电力塔把发电并过来」。

**实测旧档 slot_1**：分区后 6 张网——主厂 80 kW 发电 / 460 kW 需求（17%），
核心 160 kW 独占一网（1.00），另外 4 张网 0 供电。这正是"需要铺塔"的真实反馈。

**测试**：`_powercheck` [2] 改写成"无塔也分区"（孤立 0 / 3 格并网 1.0 / 30 格另成网），
`_enginecheck` 改成真铺 20 台风机（800 kW）驱动引擎，`_gt_*` 内容测试改用
`power.force_ratio` 官方钩子绕开拓扑；全套 **30 项自检全绿**。

## M10 已完成（分拣器三段式机械臂）

见 TechDebt #49 全记录。要点：
1. **静态底座**：分拣器格只画半格底座板 + 方向短杆 + 过滤点，传送带透出来。
2. **动态三段臂**：尾在来源格、连接部横跨本格、头在目标格；
   `Game._draw_inserters()` 每帧按 `overlay_dir` 和动画状态画在屏幕层。
3. **动画**：投递后去程 0.35s 带货、回程 0.35s 空手（纯视觉，不改抓取时序）。
4. **机器格隐藏**：头/尾落在机器格时不画，避免压在机器贴图上；
   缩放 <6px/格省略臂，只留底座。
5. **不改逻辑**：仍是 1 格 overlay、不改放置/存档；`_insertercheck` 扩到 19 段，
   全套 **25 项自检全绿**。

## M11 已完成（技术债补丁：#5/#6/#7/#9）

见 TechDebt #5/#6/#7/#9 的「已还」段。要点：
1. **#5 分拣器冷却进存档**：每行星 dump `inserters: [{x,y,cd}]`，读档恢复；
   旧档缺字段 → 空。`_savecheck` 验证 0.40s 往返。
2. **#6 无人机溢出不丢货**：请求塔满 → 原地等空间（15s），超时带货回母塔；
   母塔也满就停在塔上充电等。`_flowcheck` [E][F][G]。
3. **#7 派工看距离/电量**：供应塔必须 ≤ `TOWER_RANGE`，且无人机电量够飞
   `家→供应→请求→家` 全程（含 5 格电量预留）。`_flowcheck` [H][I][J]。
4. **#9 next_lane 读档校验**：新增 `BeltNetwork.validate_links()`，按格子方向
   只重算连接、不动物品位置；坏下标自动修正。`_beltcheck` 新增一段。
5. 全套 **25 项自检全绿**（内部段数增加，文件数不变）。

## M12 已完成（mod 单文件分发 .slmmod）

自创单文件格式：8 字节魔数 `SLMMOD\x01` + ZIP 容器 + `manifest.json`。
1. **打包 CLI** `tools/pack_mod.py`：目录 mod → `.slmmod`（自动收集代码/资源、
   生成 sha256 清单、api 版本）；`--lib` 收纯 py 依赖（目录/.whl/.py 直接入库），
   `--lib-src` 收需编译依赖的源码 `.tar.gz`；`--check` 打包后自检完整性。
2. **启动自动识别**：`mods/*.slmmod` 扫描 → 魔数/API 版本/逐文件 sha256 验签 →
   解压到 `mods/_cache/<名>__<版>__<hash8>/`（只解 manifest 声明文件，拒 `../` 穿越）→
   装依赖 → 复用现有加载器。缓存按 hash 复用；换版本自动重解压；旧缓存自动清理。
3. **依赖两套处理**：纯 Python 解进 `_lib/` 挂 sys.path（卸载摘除）；
   需编译源码首次加载自动 `pip install --no-index --no-deps --no-build-isolation
   --target _lib`（`--no-build-isolation` 关键：不联网拉构建依赖），无 pip 兜底
   `setup.py build_ext --inplace`；失败只记 failed，其余 mod 照常。游戏不联网。
4. **规则**：同名目录 mod 优先于包；`.disabled`/用户配置不受影响；
   `ctx.resource()`/`ctx.mod_dir` 读包内资源；`API_VERSION` 常量做版本门禁。
5. **附带修复**：渲染层 4 个建筑贴图方法（`_draw_tower`/`_draw_lab`/
   `_draw_launch_pad`/`_draw_planet_engine`）此前被误删，塔/实验台/发射台/引擎
   的 chunk 渲染会直接 AttributeError 崩掉；已按原风格补回（塔/引擎 3×3）。
6. **测试**：新自检 `tools/_packcheck.py`（7 段：打包加载/缓存命中/卸载清理/
   篡改拒载/穿越拒绝/同名优先/真实 pip 编译），全套 **26 项自检全绿**（29 个脚本）。

## M13 已完成（启动加载界面 + mod 拆文件入口）

1. **加载界面** `ui/loading.py`：标题 + 大步骤进度条（字体/世界生成/渲染视图/
   界面面板/加载模组/主菜单，共 6 格）+ 当前加载项文字 + 0~1 子进度条；
   每步 flip 并 pump 事件（Android 防 ANR），QUIT 可直接退出。
2. **分步构造**：`Game.__init__` 拆成 6 个 `_stage()`，可选注入 loader；
   `Game(screen)` 旧用法完全静默，全部既有自检不用改。入口改走
   `core/bootstrap.py::create_game(screen)`。
3. **mod 逐项进度**：`load_mods(progress=cb)`，`load_all` 在拓扑序加载每个
   mod 前回调 `(名字, 第几个, 总数)`，回调异常不影响加载。
4. **mod.json 拆文件入口**（新字段，目录/打包 mod 通用）：
   - `"main": "boot.py"`——自定义逻辑入口（默认 main.py；显式指定但缺失 → failed）；
   - `"mixins": ["mx/a.py", ...]`——mixin 文件列表，**全部先于 main 加载**，
     顶层代码执行 + `@Mixin` 类自动收集；文件缺失/路径穿越拒绝。
5. **测试**：新自检 `tools/_loadingcheck.py`（7 段：界面渲染/分步顺序/
   progress 回调/入口顺序与生效/坏入口拒绝/打包入口/静默兼容），
   全套 **27 项自检全绿**（30 个脚本）。

## M13.1 已完成（无显示环境自检垫层：33/33 全绿）

背景：新版 34 个自检脚本里有 13 个要 `pygame.display.set_mode()`。在**无显示环境**
（Linux 沙箱、纯 adb shell 调 Pydroid 的 python3.11）下，Pydroid 的 SDL2 是定制版，
必须挂在 Android Activity 的 JNI 上下文里，一律报
`pygame.error: Application didn't initialize properly, did you include SDL_main.h...`。
后果：新版最核心的成果（分层 / 多行星 / 星际物流 / MOD / 电网 / 视图）一半自检测不了。

解决：新增 `tools/_shim_display.py`（**测试垫层，生产代码不许 import**），
把 `pygame.display.set_mode` 换成返回普通 `pygame.Surface`、`flip/update/get_surface`
变 noop、`time.Clock` 换确定性假时钟、`event.get/poll` 返回空、`key.get_pressed`
返回全松开的假按键表、`mouse.get_pos/get_pressed` 返回定值。

用法：

```bash
python3 tools/_shim_display.py tools/_simcheck.py     # 跑单个
# 全套：
for f in tools/_*.py; do case $(basename $f) in _tmp*|_shim_display.py) continue;; esac
  python3 tools/_shim_display.py $f || echo "FAIL $f"; done
```

实测（Pydroid python3.11.4 + pygame 2.5.0，`LD_LIBRARY_PATH` 指 Pydroid 的 lib）：
**33 个脚本全 PASS，0 FAIL**。包括之前跑不了的 `_simcheck` / `_multiworldcheck` /
`_shipcheck` / `_modcheck` / `_insertercheck` / `_menuecheck` / `_viewcheck` /
`_uidefcheck` / `_packcheck` / `_enginecheck` / `_loadingcheck` / `_jadecheck` /
`_gt_smoke` / `_gt_extra_smoke`。

顺带修掉两个**真实失败**（不是环境问题）：

- `mods/新建文本文档.slmmod` 是 0 字节垃圾文件（打包测试残留），被 mod 扫描器当
  包加载报 `PackError: 不是 slmmod（太短）`，导致 `_gt_modcheck` / `_gt_extracheck`
  各挂 1 项。删除该文件后两者全绿。**教训：`mods/` 下不许留空文件/半成品。**

注意：垫层只能验证"逻辑与渲染状态"，测不出真窗口的东西（窗口尺寸/缩放后的实际
画面/触摸坐标 → 屏幕像素映射）。发布前仍需在 Pydroid App 内实跑一次。

## M13.2 已完成（无电开局：长按采矿 + 手搓科研包 + 手动研究）

设计变更：**出生点不再预置核心**（`PlanetDef.has_core` 全 False），开局一点电都没有。
新开局路径 = 长按矿格手动采矿 → 手搓铁板/铜板/磁铁/铜线/电磁矩阵 →
科技面板「手动研究」推第一个科技 → 解锁电力后铺太阳能/风力，再转自动化。

1. **手动采矿**：`GestureRecognizer.poll_longpress()` + `LongPressEvent`；
   长按成立后抖动阈值放宽到 `LONGPRESS_DRIFT=24px`（否则触屏微滑会被判成拖动）；
   `Game._tick_mining` 每帧按 `holding_pos()` 累加 `dt / MANUAL_MINE_SECONDS(1.2s)`，
   满了调 `sim.manual_mine()` 进背包并在矿格上方画进度条。
2. **`sim.world` 权威入口**：以前只有 `worlds` 列表，前端拼 `worlds[world_index]`；
   现在 `Simulation.world` 属性唯一权威。
3. **一级包可手搓**：`HANDCRAFT_BLACKLIST` 只剩 `science_red`——没电时科研站转不起来，
   「挖矿 → 手搓电磁矩阵 → 手动研究」是唯一开局推进路径（`_startcheck` 重写校验此链）。
4. **旧档兼容**：核心仍保留 160 kW 发电（`POWER_GEN[B_CORE]`），旧档摆下的核心照常供电。

## M13.3 已完成（分拣器过滤 UI：拆除按钮 + 方向提示）

1. 过滤面板新增「拆除分拣器」按钮（`FilterPanel.ACT_REMOVE`），删掉了"必须查看模式"
   才开面板的限制（手里拿分拣器时那格已被 overlay 占住，放不上去，直接给面板）。
2. 面板显示 `抓取方向：→ 东 / ↓ 南 / ← 西 / ↑ 北`，改过滤时能确认臂朝哪边。
3. 点物品即生效并刷新面板「当前」；`_try_open_panel` 不再因手持分拣器而封死入口。

**补正（本地修复）**：M13.3 把"手里拿传送带点分拣器格"也判给了过滤面板，与 M10
「带子可以从臂下穿过」冲突——那格建筑层是空的，这一击本该是放置。现在规则是
**该格放得下手里这个建筑 → 让给放置；放不下（已被占/查看模式/手持分拣器）→ 开面板**。
`_uicheck` 的「过滤面板开合」据此改写为 4 个分支（查看模式 / 手持分拣器 / 手持传送带
点空格 / 分拣器压带子）。

## M14a 已完成（液体地基：每格独立液量 + 压差限速 + 泵）

按用户要求**不做"整段瞬时共享"**（计划里的已知简化 8.1 被否掉）：每一格管道/储罐
自己存液量，相邻两格按压差限速互流，长管线要时间才灌满——压力是真实的一格格传的。

1. **数据模型** `logistics/pipes.py::FluidNetwork`：稀疏格表（`cells/index/amt/fid/cap/nb`），
   随 `grid.rev` 懒重建；不碰 512×512 数组，每帧只跑液体格。
2. **流量**：相邻格 `q = clip(Δ量×0.5, ±PIPE_FLOW_RATE×dt)`，再钳到"源存量/目标余量"；
   一律从高液位流向低液位。`PIPE_FLOW_RATE=60/s`，一格里外都守恒（自检校验 ±0.5）。
3. **泵** `B_FLUID_PUMP`：单向、**无视压差**（能把液体从低液位顶进高液位）、
   上限 `PUMP_FLOW_RATE=300/s`、耗电 20 kW（断电不搬）。输入口 = 本格−朝向，
   输出口 = 本格+朝向，泵格本身不是液体格 → 天然把管网分成两段。
4. **液体**独立注册表（id 1.. / 0=空）：1 原油、2 燃料油、3 石油气。**不进背包、
   不上传送带、不进分拣器过滤列表**（与物品数字段重叠但名字表完全独立）。
5. **建筑**（底栏新增「液体」分类）：管道（100/格）、储液罐（2500/格）、液体泵；
   三件都有手搓/机器配方。
6. **机器自动接管道**：配方含液体时（`C.RECIPE_FLUIDS` 旁挂表，不动 26 条既有 4 元组），
   机器每帧从四邻抽原料液（30/s）、把产物液排回管道（30/s），内部每种液体上限 100；
   缓冲满/抽不到就停工，不吞料。
7. **拆格泼液**：拆管道/储罐前把液体泼给四邻，泼不完才丢——拆一格满罐不再凭空蒸发 2500。
8. **渲染**：静态管道按四邻画直管/拐角/端帽（泵按朝向连两端）、储罐画罐壁刻度、
   泵画指向箭头；液面走动态层 `Game._draw_fluids()`（只遍历液体格 + 屏幕剔除，
   液柱从底部按 液量/容量 长，颜色取液体色）。
9. **存档 v13**：每行星 `pipe_fluid: [{x,y,f,a}]`，只存有液体的格；v12 旧档迁移补空表。
10. **测试**：新自检 `tools/_fluidcheck.py`（11 段：注册表/容量/压差/单向/混液/泵/
    机器/泼液/存档/渲染/隔离+mod API），全套 **30 项自检全绿**（`_jadecheck` 因卡死被删）。

**顺带修的两个 bug**：
- **合成面板 / 机器配方选择器划不动**：`scroll_by` 对每帧只有几像素的拖动手势做
  `dy // 22`，永远是 0；改成累积小数像素（并用 `int(a/w)` 向零截断，避免负方向 floor 震荡）。
  机器面板的配方选择器原来**完全没有滚动**，现在支持滚轮+拖动，并显示 `滚动 a-b/n`。
- **`Machine.update` 签名不能变**：mod 用 mixin 包了它，加第三个参数会让它们的
  `before` 钩子直接 `TypeError`；液体管网改由 `Machine.pipes` 注入。

## M14b 未启动（液体内容链）

原油矿脉 + 抽油机 + 炼油厂（原油→燃料油+石油气）+ 燃油发电机（烧燃料油发电），
以及 `fluid1` 科技锁。M14c：石油气→塑料→高级电路板。

## M15a 已完成（联机前置：指令层收口）

**问题**：三个网络协议方案独立评审时都指出同一件事——UI 面板在**绕过 sim 直接改状态**
（`machine.set_recipe` / `m.take_input` / `inventory.pop` / `tower.filter = …`）。
单机时看不出问题，联机时服务端完全不知道这些写操作，必然状态分裂。

**改法**：
1. **指令层**：新增 14 个 `Simulation` 指令（全部返回码风格，与放置指令一致）：
   `set_machine_recipe` / `machine_take_input` / `machine_add_input` /
   `machine_take_outputs` / `container_at` / `container_take` / `container_put` /
   `chest_take` / `chest_put` / `lab_set_mode` / `lab_set_recipe` / `lab_take_item` /
   `lab_add_item` / `lab_take_outputs` / `set_tower_filter` / `start_research`。
   校验都在服务端：机型/科技/配方三件套、背包余量、容器类型。
2. **面板全改走指令**：机器面板、科研站面板、存储面板（箱子/采矿机/发射器统一成
   `container_take/put`）、物流塔过滤、科技面板 [研究]。`Game.__init__` 统一注入
   `sim`（联机时换成远程代理，面板代码一行不用改）。
3. **事件/脏格 fan-out**：`subscribe_events()` / `subscribe_dirty()`，`emit`/`_mark_dirty`
   同时喂本地队列和订阅者——原来 `pop_events()` 是单消费者，服务端和渲染会互相抢。
4. **`with_world(i)` 上下文**：联机指令带行星作用域，进出自动还原 `world_index`/grid。

**测试**：新自检 `tools/_cmdcheck.py`（8 段：机器/容器/科研/塔/研究指令 + fan-out +
world 作用域 + **静态扫描 19 个 UI 文件确认零越权**），全套 **31 项自检全绿**。

## M15b 已完成（联机骨架：权威服务端 + 镜像客户端）

架构（沿用三方案评审推荐的 A→C 混合，TCP 单通道起步）：

1. **权威服务端** `stellarloom/net/server.py::NetServer`：独占跑
   `Simulation.step`（20Hz 定步长）；指令队列与 step 串行执行；事件/脏格 fan-out
   广播；关键帧 = 存档 dump（复用 v13 格式，~45 KB zlib）。
   独立入口：`python -m stellarloom.net.server --port 27715 [--save save.slm]
   [--autosave 120]`，控制台命令 status/save/players/stop。
2. **镜像客户端** `stellarloom/net/client.py`：`NetClient`（reader 线程收发，
   `poll()` 主线程消费）+ `RemoteSim` 代理——读属性穿透本地镜像 `Simulation`，
   白名单指令（`net/commands.py`：建造/容器/科研/星际 30 条）转发 CMD 并阻塞等
   ACK（LAN RTT 内 UI 停顿无感）。**Game.attach_net() 一行进入联机模式**，
   断线自动回退单机（镜像变本地权威）。
3. **帧协议** `net/protocol.py`：`SLMN` 魔数 + 长度前缀 + JSON，单帧上限 8 MiB；
   握手校验协议版本 + SAVE_VERSION；拒绝与错误 ACK 带原因。
4. **关键帧按需重建**：全量 dump 实测 ~210-270 ms/次，绝不能每秒盲发——策略是
   "有变化 ≥0.5s 一次（grid.rev/背包/科技签名驱动），带物品活着时 2s 兜底"，
   空闲时零开销。
5. **入口**：`python main.py --join HOST[:PORT] --name 昵称`；联机时本地读档/
   快速存档被禁用（提示"存档由服务端负责"）。

**测试**：新自检 `tools/_netcheck.py`（10 段：帧编解码 fuzz、白名单、握手、
双人建造同步、拒绝路径、容器指令+关键帧回流、事件/脏格扇出、聊天、断开收尾）+
真机 e2e（Game.attach_net 放置/面板设配方/放料/聊天/断线回退全通），
全套 **32 项自检全绿**。

**已知边界（M15c/d 候选）**：带物品/无人机位置只在关键帧间跳变（实体流未做）；
镜像整帧覆盖后 chunk 全清（可改增量）；无 ghost 预览与 AOI 订阅；无断线重连
token；面板开着时快照到达会被强制关闭（防陈旧引用）。

## M15c 已完成（服务端完善：自动打包 + mod 加载 + headless 校验）

1. **服务端 mod 加载**：`NetServer.load_mods()` 用与单机同一套 ModManager
   （失败隔离/依赖拓扑/配置合并），`_ServerGameShim` 只暴露 sim + toast 空壳；
   mod 的 `on_step` 钩子在每 tick 同步触发。**gregtech 联机可用**。
   握手 `hello_ack.mods` 带 [(名字, 版本)]，客户端比对：本地缺服务端 mod →
   toast「相关内容显示为占位」，本地多装 → 提示仅影响本机显示（不硬拒绝——
   逻辑全在服务端，客户端内容 mod 只是渲染素材）。
2. **自动打包器 `tools/build_server.py`**：从源码收集逻辑层包
   （sim/world/logistics/production/power/tech/save/mod/net/config/registry/api/
   data + core/worldstate + render/camera），**AST 静态依赖闭包检查**——
   出现 `import pygame` 或 import 到包外的 stellarloom 子模块直接构建失败，
   防止"逻辑层偷偷依赖渲染"回归。产物 `dist/server/`：`run_server.py` 入口 +
   VERSION.txt + README.txt，`--zip` 可打成压缩包，`--pack-mods` 带 mods
   （跳过 __pycache__/_cache/.disabled/config）。`--check-only` 只查不落盘（CI）。
3. **headless-check**：`run_server.py --headless-check 300` 不开 socket 纯跑逻辑，
   输出 `state_hash()`（世界建筑+背包+带位置 blake2b），**两次运行逐位一致**
   ——"服务端=权威逻辑"的最强回归；`hash` 控制台命令运行中随时可打。
4. **控制台扩展**：`kick <id|名>`、`say <文本>`、`hash`、`status/save/players/stop`。

**测试**：新自检 `tools/_servercheck.py`（6 段：闭包检查、打包产物、headless
确定性双跑、**打包服务端子进程真实 socket 联机**、mod 加载与卸载干净、
握手 mod 清单），全套 **33 项自检全绿**。

## M15d 已完成（联机完善：@EnvType + 崩溃策略 + 按玩家分背包）

1. **@EnvType 侧标**（`api.py`）：`@EnvType("client"/"server"/"both")` 可标 mixin
   类、注入方法、on_load；`load_mods(side=)` 按侧过滤——服务端跳过 jade/
   shaderbridge 这类纯 UI mod 与 gregtech 的 4 个 UI mixin（逻辑 mixin 保持
   both 照常装）。服务端不再因 mixin 到 UI 类而炸。
2. **mod 出错即崩**：加载器的失败隔离全部删除——mod.json 解析失败、main.py
   语法错、on_load 抛异常、mixin 目标不存在、依赖不满足/环、包校验失败一律
   raise，交给 crash_guard 写报告；`self.failed` 恒为空保留兼容。顺带修了两个
   被暴露的真问题：crash_guard 崩溃页在 dummy 驱动下死循环卡死、同进程第二个
   Game 加载 mod 撞全局注册表（_ACTIVE 单活跃管理器）。
3. **按玩家分背包**（SAVE_VERSION 13→14）：`Simulation.players[pid]` =
   独立 `inventory` + `CraftQueue`；`sim.inventory/craft` 变成当前玩家属性；
   `with_player(pid)` 上下文（仿 with_world）；服务端按 session player_id 执行
   指令，背包互不相干；科技/戴森球/世界保持共享。存档迁移：老档背包进
   `players["0"]`。关键帧全量广播、客户端只读自己背包（协议零新消息）。
4. **测试**：新增 `_envcheck` / `_modcrashcheck` / `_playerscheck`，
   全套 **36 项自检全绿**。
5. **已知边界**：事件/toast 全局广播（别人的"材料不够"你也会看到）——
   后续可按 player_id 路由过滤。

## 下一步：M5c 候选（未启动）
煤/油（TechDebt #1 的燃料部分）仍待还；星际侧可继续做：每台多船/运输船油耗/行星航线图。
`_ensure_world(i)` 已能动态生成第 3+ 颗行星，暴露 UI 即可。

## M5 及之后（未启动）
- **M5** 星际：多行星（每行星独立网格）✅（M5a）+ 运输船 ✅（M5b）+ 相位影响 + 发射窗口预测 UI ✅
- **M6** 行星工程：行星引擎 + 轨道半径/相位调整 + 太阳能与温度联动 ✅
- **M7** 无限沙盒：程序生成星系 + 星门 + 无限科技
- **M8** 真电网：电力塔 + 电网分区 + BFS 连通 ✅（M9 完成，还掉 TechDebt #1 的电网部分；电池/储能未做）
- **M9** 换 sprite 打磨（按 `Docs/ArtAssets.md`）

## 未解的技术债（详见 TechDebt.md）

1. ~~全球电网是假的~~（P1，M9 已还）
2. 建筑全是代码画色块（P2，M9）
3. ~~只有一种矿~~（P1，M5 已关闭，残留见煤/油）
3.1 ~~分拣器没有过滤~~（P1，M5.5 已关闭）
4. 塔在 chunk 边界被裁掉（P2，渲染 bug，随时可修）
5. ~~存档不含分拣器冷却~~（P3，M11 已还）
6. ~~无人机送货溢出直接丢~~（P2，M11 已还）
7. ~~无人机派工不看 TOWER_RANGE~~（P2，M11 已还）
8. 生产/研究/物流三网各自每帧全图扫描（P3，性能）
9. ~~传送带 next_lane 依赖存档不做校验~~（P2，M11 已还）
10. 触屏永久屏蔽鼠标（P3）