# 技术债清单 TechDebt

记录已知的偷懒、妥协、假实现。每条都写清：是什么、为什么这么干、代价、什么时候该还。

优先级：P0 会让游戏崩/卡死，P1 影响玩法正确性，P2 影响观感/扩展性。

---

## 1. 全球电网是假的（P1，**M9 已还**）

**现状**：`stellarloom/power/grid_power.py` 里 `PowerGrid` 整张地图只有一张网。
全图 `count_building(B_SOLAR)` 发电总和 ÷ 全图耗电总和 = `speed_factor`，直接当所有机器和传送带的速度倍率。

**为什么这么干**：M1 只求"电不够就变慢"这个手感，分电网要做连通性搜索、电线杆、电池缓冲，会拖垮当时的进度。

**代价**：
- 你在图左上角放太阳能板，图右下角的熔炉立刻受益，中间一根线都不用连。玩家无法理解为什么。
- 无法做 Factorio 式"电网隔离"玩法：断电区域停机、手动拉线救援、电网优先级。
- 昼夜切换时全球同时降速，太阳能阵列和风力无法做区域互补。
- 存档只存 `power.time`，没有电网结构，将来做真电网必须加迁移。

**还债方案**：电线杆（B_POLE）+ 电池（B_BATTERY）+ 每座建筑记录所属电网 id。某格放建筑后做一次 BFS 认领连通的电线杆。这一步必须等 M6。

**追加（开局核心供电）**：为了解开局死锁，`POWER_GEN` 里给 `B_CORE` 加了 8.0 恒定发电。这让"全球一张网"的荒诞感更强了——核心在出生点，却给整张 512×512 地图供电。M6 做真电网时，核心应该改成**有限半径供电**（比如 15 格），玩家必须靠电线杆把电送出去。

**已还（M9 真电网，见 #48）**：核心现在是 160 kW 的普通电网节点，靠 8 格邻接
（电力塔可接力）供电；按连通分量分区、逐网算比例；单位改成 kW/MW。
~~全图一根塔都没有时仍退回旧全球电网~~（M14b 已废除：那一层兼容等于把分区藏起来，
玩家铺了风车却永远只看到"一张网"）。现在**没有塔也照样按 8 格分区**。

---

## 2. 建筑全是代码画的色块（P2）

**现状**：`stellarloom/render/layers.py` 里每个建筑都是 `pygame.draw.rect/polygon/circle` 手绘像素图案。传送带是深底+亮线+箭头，熔炉是红底+三条通风口，塔是 3×3 放大框+箭头，等等。

**为什么这么干**：没有美术资源。用程序化绘制能保证任意缩放（0.25x–4x）都不糊，且改配色一行代码。

**代价**：
- 完全没有"地平线/俯视"的材质质感，看起来像原型机。
- 每格都要跑 draw 调用，chunk 预渲染缓解了大部分，但 `tile_px` 变化时会重建整个缓存。
- 塔用 `rect.inflate` 画到 3×3，跨 chunk 边缘会被邻块覆盖裁掉（**已知渲染 bug**，见第 4 条）。

**还债方案**：M9 换 sprite。先按 `Docs/ArtAssets.md` 出图，再在 `_build` 里改成 `blit`，`tile_px < 8` 时回退到现在的程序化绘制（远景不需要细节）。

---

## 3. ~~只有一种矿~~（P1，**M5 已关闭**）

**已解决**：M5 落地 `grid.ore_type` int8 数组 + 铁/铜/石三种矿，`mine()` 返回物品 ID，
采矿机和手动右键都按脚下矿种给矿，`layers._draw_ore` 按 `ORE_COLORS` 分色。
存档升 v4，老档按"全是铁矿"回填。

**残留**（拆出来当新条目看待，别以为这条彻底没了）：
- 煤 / 油 / 铀还没有，所以二级科研包（能量矩阵）做不了，见 M6。
- 矿脉还是随机游走撒的，没有"矿脉必须成片、必须够大"的保底逻辑。
- 每种矿的储量参数共用一套（200–1000），没有按稀有度分级。

---

## 3.1 ~~分拣器没有过滤~~（P1，**M5.5 已关闭**）

**已解决**：`grid.overlay_filter` int32 数组，0=不限、其余=只抓该物品。
`InserterNetwork` 抓货时先跟目标需求取交集，非过滤物品留在带子上让下游分拣器去抓。
查看模式点分拣器弹 `ui/filter_panel.py` 选物品，分拣器左上角画过滤物品颜色小圆点。
存档升 v5，v4→v5 迁移全填 0。

**残留**：
- 只能设一种物品过滤，没有"黑名单"（只收 X / 只不收 X）。
- 物流塔的 `filter` 字段仍和分拣器过滤各管一套，没统一成一套物品过滤器。

---

## 4. 塔在 chunk 边界被裁掉（P2，视觉 bug）

**现状**：`layers.py::_draw_tower` 用 `rect.inflate(tile_px*2, tile_px*2)` 把 3×3 大图直接画在中心格所属的 chunk surface 上。超出该 chunk 的部分直接被裁掉，相邻 chunk 里没有补画。

**代价**：塔建在 32 格 chunk 边界附近（比如 x=31）时，右半边显示不全。

**还债方案**：把塔从静态 chunk 层拿出来，放到 `_draw_machine_status` 那类动态层里逐帧画（塔数量不多，几十座，性能无所谓）。

---

## 5. 存档不含分拣器冷却（P3，**M11 已还**）

**现状**：`savefile.py::load_into` 结尾 `game.inserters.cooldowns.clear()`。读档后所有分拣器冷却归零，可以立刻抓一次。

**代价**：读档瞬间可能多抓一圈物品（1 秒冷却的误差）。可接受。

**还债方案**：真要修就往 dump 里加 `cooldowns` 的 `{f"{x},{y}": cd}`，load 时还原。不急。

**已还（M11）**：每个行星 dump 增加 `inserters: [{x, y, cd}]`（只存 cd>0），
load 时按坐标还原；旧档缺字段 → 空，等价旧行为。`_savecheck` 验证 0.40s 冷却读档后
仍是 0.40s（±0.05）。

---

## 6. 无人机送货溢出直接丢（P2，**M11 已还**）

**现状**：`drones.py` 的 `S_DELIVER` 分支里 `leftover = t.add_item(...)` 之后 `self.cargo = None`，`leftover` 算出来但**没人用**——请求塔满了，多出来的货凭空消失。

**代价**：物流塔满载时无人机白跑还吞货，玩家会看到库存对不上。

**还债方案**：`leftover > 0` 时飞回母塔前先把剩余塞回母塔或扔回最近传送带；实在没地方就原地待机等库存空出来（不要瞬移）。

**已还（M11）**：请求塔满时无人机**留在塔旁等空间**（`DRONE_WAIT_TIMEOUT=15s`），
期间货一直在手上；超时则带货回母塔卸，母塔也满就停在塔上边充电边等——
任何情况下都不再把 `leftover` 丢掉。`_flowcheck` 新增 [E][F][G] 三段验证：
等 1s 不丢货、超时后母塔收到全部 2 件、两塔都满时货仍在手上。

---

## 7. 无人机派工不看距离上限（P2，**M11 已还**）

**现状**：`drones.assign_tasks` 里 `min(idle_drones, key=离请求塔曼哈顿距离)` 挑无人机，但其实**任何塔的无人机都会去任何请求塔**，不看 `C.TOWER_RANGE = 30`，也不看电量够不够飞完全程。

**代价**：`TOWER_RANGE` 是死常数，没有任何代码用。无人机可能从图的一头飞到另一头，半路电量过 0 后减速爬行（`speed * 0.3`），体验很差。玩家也没法靠"建近一点"做优化。

**还债方案**：派工前算 `dist / (DRONE_SPEED) * DRONE_ENERGY_PER_CELL > energy` 就跳过这台；同时把 TOWER_RANGE 真正接进调度。

**已还（M11）**：`assign_tasks` 现在只考虑**距请求塔 ≤ TOWER_RANGE** 的供应塔（近的优先），
并逐台检查 `家→供应→请求→家` 全程电量（含 `DRONE_RESERVE_ENERGY=5`），
不够就不派。`_flowcheck` [H][I][J] 验证：48 格远不派、25 格派 1 架、
电量 20（全程需 50）不派。

---

## 8. 生产/研究/物流三网各自全图扫描（P3，性能）

**现状**：`machines.sync`、`labs.sync`、`towers.sync`、`inserters.update`、`_miners_update` 全都是 `np.nonzero(g.building == X)` 全图扫。512×512 每次扫 26 万格 × 5 处。`sync` 只在建筑变化时调，还好；但 `inserters.update` 和 `_miners_update` 是**每帧**。

**代价**：这是 `tools/bench.py` 要量的主要开销之一。手机 ARM 上可能顶不住。

**还债方案**：按 bench 结果决定。做法是维护一个"分拣器坐标集合"和"采矿机坐标集合"，`grid.place/remove` 时增量更新，`update` 只遍历集合。

### 实测数据（`tools/_profile.py`，2026-10-31，3 万物品 / 750 塔 / 1500 无人机）

分段耗时（x86 本机，ARM 大概 ×3-5）：

| 段 | ms/帧 | 备注 |
|---|---|---|
| `towers.update` | **2.16** | 已优化，原 2.97；正确性修复后从 1.46 升到 2.16（见下） |
| `inserters.update` | 0.91 | 每帧全图扫 overlay |
| `power.update` | 0.58 | |
| `drones.update` | 0.48 | |
| `belts.update` | 0.15 | 向量化，很便宜 |
| `machines/labs.update` | 0.00 | |
| `machines.sync` | 1.77 | 只在建筑变化时调 |
| `towers.sync` | 1.41 | 只在建筑变化时调 |
| `belts.rebuild` | **42** | 只在建筑变化时调，但一次就是 40ms 卡顿 |

**已做的优化（M5.5 附带）**：
- `_adjacent_belt_cells` 从生成器改成缓存列表（233 塔 × 16 次/帧 → 一次建好复用）。
- `_push_to_belts` 嵌套顺序反转（原来物品在外层、格子在内层，每件物品重扫 16 格）。
- `get_tower` 从 O(塔数) 线性扫改成 3×3 中心反查（最多 9 次 dict 查）。
- 3 万物品下 `update` 从 11.73ms → **9.32ms**（-21%）。

**确认可接受、暂不优化**：
- `belts.rebuild` 39ms 只在放置/拆除建筑时触发一次，不是每帧，玩家可感知为"放东西时小卡一下"。真要修得改成增量重建。
- `np.delete` 在塔抓货时重建整个 lane 数组，但抓货频率受 0.5s 派工节流限制，不在热点。

**2026-11-01 bug 检查轮次的性能影响**：
- `towers._pull_from_belts` 修了"隔空吸货"后必须检查物品位置，从"遍历整条 lane 找第一个"
  改成 `searchsorted` 二分区间。二分版本 towers.update 2.16ms（10k 场景），比修复前 1.46ms 慢 0.7ms，
  但比第一版逐物品 `for` 扫描的 8.3ms 好得多。这 0.7ms 是正确性的代价，接受。
- `belts.rebuild` 修"向左/向上 lane 碎"时踩了个自己挖的坑，记下来避免重犯：
  第一版 `_trace_head` 沿反方向回溯找入口，对**首尾相接的闭环带子**（横穿整张地图、
  卷绕后自己接上自己）永远找不到"上游没有同向带子"的格，会绕满 w*h 次。
  26 万格时 `rebuild` 从 40ms 直接爆到 **8 秒**，连 `bench 10k` 都被拖成 10 FPS。
  第二版改成**两轮扫描 + 向量化入口判断**：先用 numpy 一次算出所有"上游不是同向带子"的真入口，
  只从这些格 trace；剩下的必然是闭环，随便挑起点 trace 即可。每格最多访问两次，整体 O(n)。
  修完 10k 场景 42ms（原来 39.8ms，多出的 2ms 是入口向量化判断），30k 场景 94ms（线性，正常）。

### bench 实测（2026-11-02，x86 本机 Python 3.13，ARM 大概 ×3-5）

| preset | update avg | render avg | TOTAL avg / p95 | 60fps | 30fps | FPS 上限 |
|---|---|---|---|---|---|---|
| small（1k 物品 50 机） | 1.59ms | 0.80ms | 2.60 / 4.21ms | PASS | PASS | ≈385 |
| 10k（500 机） | 7.23ms | 9.38ms | 18.12 / 29.12ms | FAIL | PASS | ≈55 |
| 30k（1500 机） | 18.05ms | 26.81ms | 52.37 / 64.76ms | FAIL | FAIL | ≈19 |

结论：10k 规模本机刚过 30fps 线、手机 ARM 上必跌穿；30k 本机也只有 19 FPS。
**render 首次成为和 update 同级的大头**（30k 下 26.8ms > update 18.1ms），
物品/无人机逐圆点绘制的开销不能再无视。10k 的 sync worst 98ms / 30k 的 sync worst 469ms
是 belts.rebuild 全量重建的尖刺，确认"放东西大卡顿"在大规模下不可接受。

### M6.19 性能优化（2026-11-02，已做）

| 项 | 改法 | 实测 |
|---|---|---|
| `inserters.update` 全图扫描 | **坐标集合 + grid.overlay_gen 代数失效**：放/拆 overlay 时 `gen += 1`，update 只遍历集合，读档后 `overlay_gen += 1` + `inserters.invalidate()` | profile 10k：0.62ms → **0.007ms**（真工厂里分拣器越多省得越多） |
| `_draw_items` 逐格 draw.circle | **numpy 向量化变换 + 可见掩码 + sprite blit**：每条 lane 一次批量算屏幕坐标，Python 循环只跑屏内物品 | 30k 物品实测 **17-18ms → 3-4ms（4.4-5.9x）**，三种缩放下一致 |
| `_draw_machine_status` 分拣器箭头全图扫 | 复用 inserters.cells 集合 | 顺手省一次每帧扫描 |
| `_draw_drones` | 三角 sprite blit | 1.0x（无人机本就不是热点，纯粹统一写法） |

**踩坑记录（重要）**：
- `np.bincount(g.building.ravel())` 做建筑计数反而比 11 次 `count_nonzero` 慢 6 倍
  （逐元素小表自增比向量化比较慢），已回退 power.update——别用 bincount 当万能计数。
- 曾用 `grid.on_overlay_changed` 回调让 inserters 失效，但自检脚本直接构造网络、不接回调，
  导致缓存永远过期（_storagecheck 当场抓出）。改成**代数计数器**（谁用都正确），
  教训：缓存失效别依赖外部接线，用数据本身的版本号。

**bench 复核（同 x86 本机）**：10k TOTAL 18.1 → **11.0ms**（FPS 上限 ≈91，60fps 从 FAIL 转 PASS）；
30k TOTAL 52.4 → **35.1ms**（FPS 上限 ≈29）。注意 bench 的 render 段是它自己画的圆，不走
`_draw_items`，所以 bench 数字只体现 update 层的收益；物品渲染收益看上面 4.4-5.9x 的实测。

**下一步该做的（如果还要压）**：
1. `belts.rebuild` 改增量（只重建受影响的 lane，不动全图）—— 40-90ms 尖刺只在放/拆时
   触发一次，是"放东西小卡"的元凶，但改增量风险高（物品快照/还原、闭环 lane），留到最后。
2. `machines.sync` / `towers.sync` / `labs.sync` 只在建筑变化时调，非每帧，暂不动。
3. bench.py 的 render 段是模拟绘制（非游戏路径），30k render 19.7ms 不能代表真实
   渲染开销，真实物品渲染已向量化（见上表）——要的话把 bench 改成走真实 Game 渲染。

---

## 9. 传送带 lane 的 next_lane 只在 rebuild 时算（P2，**M11 已还**）

**现状**：`belts.rebuild` 会重算 `next_lane`。但存档读回时 `load_into` 直接恢复 `bd["next_lane"]`，不做校验。

**代价**：理论上不会出问题（存档里的拓扑和格子是配套的），但如果手改存档或将来加入传送带交叉/隧道，可能断链。属于"格式脆弱"。

**还债方案**：读档后调一次 `rebuild()`（会走 `_snapshot_items` 保留物品），代价是掉一次浮点精度风险。目前**不做**，因为快照往返本身就是精度风险。

**已还（M11）**：新增 `BeltNetwork.validate_links()`——读档恢复 lane 后按
「末格方向 + 下一格」**只重算连接、不碰物品位置**，坏下标（旧档/手改档）会被
修成正确 lane 或 -1，也不再依赖存档里的 `next_lane` 字段。`_beltcheck` 新增
「next_lane 校验修复」验证 999/-5 两个坏值被修正。

---

## 10. 触屏和键鼠共存靠"见过触屏就永久屏蔽鼠标"（P3）

**现状**：`game.py` 里 `self.touch.ever_touched` 一旦为 True，所有 `MOUSEBUTTONDOWN` 永久忽略。

**代价**：Android 上接了物理鼠标也点不动按钮（触屏优先）。桌面上永远不会有这个问题。

**还债方案**：按 `e.touch` 属性区分而不是全局开关。但 Pydroid3 的 SDL 不一定给这个属性，需要实测。

---

## 11. ~~传送带向左/向上方向 lane 全碎~~（P0，**已修复**）

**原来的 bug**：`belts.rebuild` 用 `np.nonzero(g.building == C.B_BELT)` 按**行主序**枚举带子格，
每扫到一个未访问格就从这个格开始 `_trace_lane` 顺着方向往下走。
向左（d=2）和向上（d=3）的带子，行主序遍历时**先碰到的是出口端**，
从出口端顺着方向走一步就出界，于是每条 lane 只有 **1 格**。

**后果**：一条 8 格向左的带子会被切成 8 条独立 lane，物品每格换一次 lane，
`next_lane` 全断，末端物品永远到不了头，分拣器和物流塔的 `cell_index` 也全错。

**为什么一直没发现**：向右（d=0）x 最小正好是入口、向下（d=1）y 最小正好是入口，
这两个方向侥幸正确。而玩家铺带子最常用这两个方向。

**修法**：两轮扫描 —— 先用 numpy 向量化算出所有"上游不是同向带子"的**真入口**，
只从这些格开始 `_trace_lane`；剩下的必然是首尾相接的闭环（没有任何入口），
第二轮随便挑起点 trace 即可。每格最多访问两次，整体 O(n)。

**注意坑**：一开始写的是"从任意格沿反方向回溯找入口"，但闭环带子（横穿整张地图、
卷绕后自己接上自己）根本没有入口，回溯会绕满 w*h 次，26 万格时 rebuild 爆到 8 秒。
现在改成两轮扫描彻底避开回溯。回归测试见 `tools/_beltcheck.py`
（4 方向 + 拐弯 + 反向铺设 + **闭环整圈**）。

---

## 12. ~~供应塔隔空吸货~~（P1，**已修复**）

**原来的 bug**：`towers._pull_from_belts` 里遍历**整条 lane** 找第一个能收的物品，
完全不看物品当前在 lane 上的位置。只要塔的 3×3 外圈挨着某条带子的任意一格，
这条带子上离塔 20 格远的物品也会被瞬间吸进塔。

**后果**：供应链看起来"通了"但是假的。物品没有走完带子就被抽走，
玩家设计的传送带长度、分拣器位置全部失效，而且从画面上看不出货是在哪儿消失的。

**修法**：用 `np.searchsorted` 在有序的 `lane.positions` 上二分出
`[ci, ci+1)` 区间，只抓此刻真的流到本格上的物品。回归测试见 `tools/_wrapcheck.py`。

---

## 13. ~~分拣器投递失败吞货~~（P1，**已修复**）

**原来的 bug**：`inserters.update` 抓到物品后如果 `_deliver` 失败，
回退路径是 `self.belts.try_insert(sx, sy, item)` —— 但 `sx, sy` 是**源格**，
源格通常是一台机器（没有传送带），`try_insert` 直接返回 False，物品凭空消失。

**后果**：目标带子刚好塞满的那一瞬间，机器产物被分拣器吞掉。高频运转时这是真丢货。

**修法**：`_grab` 现在返回 `(item, 来源机器或None)`，投递失败走 `_put_back`：
从机器抓的退回机器产物槽，从带子抓的退回带子，都失败才认栽。
回归测试见 `tools/_flowcheck.py`。

---

## 14. ~~塔的 3×3 占地可以被侵占~~（P1，**已修复**）

**原来的 bug**：塔只在**中心格**写 `building`，其余 8 格是空的，
而 `grid.can_place` 只查单格。所以传送带能直接穿过塔身，熔炉能压在塔边上。
另外 `TowerNetwork.can_place` 只查自己 3×3 格空，两座塔中心隔 2 格时占地会重叠。

**后果**：塔内部格子上有带子/建筑后，`_adjacent_belt_cells` 的交换逻辑和视觉都乱套；
两塔重叠时 `get_tower` 反查会随机命中。

**修法**：`grid.can_place` 增加 3×3 邻域塔中心检查（普通建筑不侵占塔占地），
`TowerNetwork.can_place` 增加切比雪夫距离 >= 3 的塔塔不重叠检查。
回归测试见 `tools/_statecheck.py`。

---

## 15. ~~机器面板跨机器残留配方点击区~~（P2，**已修复**）

**原来的 bug**：`MachinePanel.show` 不清 `_recipe_rects`，只在 `draw` 里清。
换机器后如果点击发生在下一次 `draw` 之前（触屏快速连点很常见），
会拿上一台机器的配方行去设置新机器的配方 —— 甚至给熔炉设制造台的配方。

**修法**：`show` 里立刻 `_recipe_rects.clear()`。回归测试见 `tools/_statecheck.py`。

---

## 16. ~~开局完美死锁：电路板科技环~~（P0，**已修复**）

**原来的 bug**（本轮查出来的，比前面几条都严重）：

```
任何科技    → 需要科研站
科研站      → mk_lab 配方需要 电路板×4
电路板      → circuit 配方被 RECIPE_TECH["circuit"]="circuit1" 锁住
circuit1     → 需要电磁矩阵才能研究
电磁矩阵    → science_blue = 磁铁×1 + 电路板×1
```

这是一条**闭合的死循环**：玩家从开局背包出发，能造铁板/齿轮/传送带/分拣器/
熔炉/采矿机/制造台/风力，但**永远造不出电路板**，因此永远建不了科研站、
永远造不出电磁矩阵、7 个科技一个都研究不了。太阳能（mk_solar 也要电路板）
同样永不可造。

**为什么一直没发现**：`_startcheck` 只检查"手搓链能不能通""有没有发电"，
是静态检查，完全没有模拟科技锁与科研包之间的依赖关系。
`_craftcheck` 也只测手搓链，不测科技闭包。

**修法**：
1. 补 `hand_circuit` 手搓配方（铁板3+铜板2 → 电路板1，比工厂价贵约 3 倍，
   遵守"手搓一律比工厂贵"的既有原则），打破死锁。
2. 新增 `tools/_deadlockcheck.py` 做**可达性闭包**：从开局背包 + 徒手可挖的矿
   出发，反复问"能造什么 → 能建什么 → 能研究什么"，直到不再变化。
   任何科技最终不可达就是死锁，并打印缺哪些原料。
3. 把同样的闭包检查内联进 `_startcheck.py` 第 6 项，保证改配方/科技表时立刻能刷出来。

**教训**：科技锁（`RECIPE_TECH`）和科研包配方（`TECH_PACK_RECIPE`）是两张独立的表，
它们之间的环**只能靠闭包迭代发现**，静态检查扫不出来。以后新增任何
`RECIPE_TECH` 条目，必须跑 `_deadlockcheck.py`。

---

## 17. ~~容器建筑 + 全机器手动存取~~（M6，**已实现**）

**需求**：加箱子；所有机器的输入暂存格可手动放入/取出；输出格可取出不可放入、且只能整体取空；采矿机默认 50 个暂存格。

**设计定案**（后续维护必须遵守）：

- **箱子 = 纯容器**：`ChestNetwork`，每格 `store: dict[item,int]`，`CHEST_STACK=50`（每种），没有"输入/输出"之分，分拣器**双向**可搬。
- **采矿机暂存 = 50 总上限混装**：`MinerNetwork`，`buffer: dict`，`MINER_BUFFER_CAP=50`（所有矿加起来 50，不是每种 50）。
- **机器输入格**：手动放料走 `Machine.add_input`，**仍按配方 need 过滤**（熔炉塞不进齿轮）；`take_input(count=None)` 全取。
- **机器输出格**：只有 `take_all_outputs()`，**故意不提供 `add_output`**——产物必须由生产逻辑写，玩家不能凭空造产物。`_storagecheck` 第 5 项用 `hasattr(m,'add_output')` 断言为 False 锁死这条。
- **拆带容器的建筑必须把内容物退回背包**（`game._remove_or_mine`）：箱子退 `store`、矿机退 `buffer`、机器退 `inputs+outputs`。不这么做玩家拆一下东西就蒸发了。
- 通用语义抽到 `production/storage.py`（`total/space/add/take`，支持 `per_cap` 和 `total_cap` 两种上限），三个网络共用。

**期间踩到的真 bug**：`Inserters._grab` 抓箱子时原来用 `peek_item(flt)` 只拿"第一个有货的物品"，目标不收就直接放弃。后果：箱子里有齿轮（挡在前面）+ 铁矿石，熔炉要铁矿石，结果分拣器永远抓不出来 → 铁矿石在箱子里烂掉。改为**遍历 `store` 找目标 acceptable 的物品**。

**存档**：`SAVE_VERSION` 5→6，`dump/load` 加 `miners(buffer)`/`chests(store)`，`_migrate` v5→v6 补空表（建筑在网格里，sync 重建对象，Store 为空）。手机端 v5 老档首读自动迁移，迁移后箱子里没东西属预期。

**测试**：新增 `tools/_storagecheck.py`（6 项）+ `_uicheck.py` 3 个端到端用例（放箱子扣料/自动开面板/拆箱退货、机器面板手动存取、矿机面板全取）。`_savecheck` 迁移链断言改成动态读 `SAVE_VERSION`，避免以后升版又要手改。

---

## 18. ~~手搓面板太小 + 手搓瞬间完成 + 科研站造不出来~~（M6.5，**已实现**）

**用户报的三个问题**：

1. 合成面板太小（440×480），一屏看不全。
2. 面板把所有配方连原料一股脑全列出来，眼睛看不过来 —— 应该**先选产物、才显示原料**。
3. **手搓没有耗时**，点一下瞬间完成，等于免费瞬移，破坏了"手搓比机器慢"的经济前提。

**加上用户自己分析出来的第四个问题（更严重）**：

> 开局要研究站需要制造台，制造台需要齿轮，齿轮又需要制造台

实测确认：科研站 `mk_lab` 只有机器配方，太阳能/风力/供应塔/请求塔同样只有 `mk_*`；
铜板/石材/磁铁/铜线也**没有任何手搓配方**。也就是说熔炉和制造台没铺起来的阶段，
玩家连一块铜板都做不出来，直接被卡死。

**修法**：

- **面板改版**：尺寸提到 560×620（宽 94%、高 90% 屏），左右两栏。
  左栏是可滚动的产物列表（材料够的高亮、不够的灰掉但**仍可点开看缺什么**，
  右侧显示该产物当前材料能做几个）；右栏是选中产物的原料明细 + 耗时可做次数 + 做1/做10/取消。
- **手搓耗时**：新增 `CraftJob` 队列。点做1/做10 时**当场扣材料**再排队，
  每件按配方的 `dur` 秒逐个产出；`CraftPanel.update` 用 `while` 消化 dt，
  低帧率一帧能补多件不吞时间。面板关掉也照跑（挂在 `Game._update` 里）。
- **补全手搓兜底**：新增 `hand_copper_plate` / `hand_stone_brick` / `hand_magnet` /
  `hand_copper_wire` / `hand_solar` / `hand_wind` / `hand_tower_s` / `hand_tower_r` /
  `hand_lab`。全部按"手搓比工厂贵约 2~3 倍"定价，实测手搓价均 ≥ 工厂价。
- 新增 `MACHINE_ONLY_ITEMS = {I_SCIENCE_BLUE}`，明确"只有科研包必须机器造"，
  其余一切（含所有建筑）都有手搓路。

**顺手修的真 bug**：`_on_mouse_down`（桌面端鼠标点击）**完全没有**处理手搓面板、
背包面板、过滤面板 —— 面板开着点一下就穿透到世界里放建筑。触屏走的是
`_handle_gesture`，那套是完整的，所以只有桌面端会中招。

**新增自检**：`_buildcostcheck` 加第 7、8 项 —— 所有建筑必须有手搓兜底、
除 `MACHINE_ONLY_ITEMS` 外所有物品必须有手搓来源（以后加配方忘了兜底会立刻报）。
`_uicheck` 加"合成面板先选后算"用例（面板尺寸 / 初始不选 / 产品列表有科研站 /
点击选中 / 出现制作按钮 / 排队扣料 / 推进耗时出成品）。

---
## 19. ~~双套配方（hand_/mk_）导致规则分裂~~（M6.6，**已实现**）

**背景**：第 18 条的\"补手搓兜底\"是打补丁 —— 每个物品可能存在 `mk_x`（工厂）和
`hand_x`（手搓）**两条**配方，ins/outs/dur 各自独立。你直接推翻了这套：
> 传送带一次造 3 个（一份原料），所有东西都能自动化，统一手搓和机器配方，不做区分。

双套配方的实际害处：
- **同一物品两份真相**：改一个价格要改两处，忘一处就出现\"手搓比工厂便宜\"的漏洞。
- **`MACHINE_ONLY_ITEMS` 是个例外表**：例外表一出现就意味着规则不统一。
- **产物列表要按来源分叉**：合成面板得过滤 `allows is None` 才知道哪些能手搓，
  漏一个物品玩家就报\"造不了 X\"。
- **配比僵化**：`belt` 一份料出 1 条，铺产线要搓到手指断。

**改法**：
1. **`RECIPES` 表彻底重写** —— 删掉全部 `hand_*` / `mk_*`，合并为 18 条统一配方，
   id 无前缀（`iron_plate` / `gear` / `belt` / `inserter` / `miner` / `furnace` /
   `assembler` / `solar` / `wind` / `tower_s` / `tower_r` / `lab` / `chest` …）。
   **一个物品 = 一个配方**，`allows` 全部非空 ⇒ 全部可自动化。
   删除 `MACHINE_ONLY_ITEMS`。
2. **`belt` 一份料出 3 条**：铁板 2 + 齿轮 1 → 带子 3（DSP 原版比例）。
3. **\"手搓更贵\"改成\"手搓更慢\"**：新增 `HAND_CRAFT_TIME_MULT = 2.5`。
   手搓与机器 **同 ins / 同 outs**，手搓耗时 = `dur × 2.5`。
   第 18 条的\"手搓价 2~3 倍\"模型作废 —— 涨价那套会让手搓变成纯惩罚，
   而时间成本更符合\"你懒得铺产线就慢慢等\"的直觉。
4. **科技锁语义收窄**：`RECIPE_TECH` 不再锁\"能不能做\"，只锁\"能不能用机器自动做\"。
   `available_recipes` 过滤的是机器面板的列表（`not allows` 判断），
   合成面板不再过滤 allows —— 手搓永远可行，科技只买效率。
5. **存档兼容不升版本**：`SAVE_VERSION` 保持 6，新增
   `LEGACY_RECIPE_ALIAS`（28 条旧 id → 新 id，`hand_*` / `mk_*` 全覆盖）。
   `savefile.load` 里 `rid = C.LEGACY_RECIPE_ALIAS.get(rid, rid)`，
   翻译后若不在 `RECIPES` 就置 `None`（机器空转，不崩）。
   手机上的 v6 旧档首读自动迁移，不需要写迁移链。

**关键实现点**（`craft_panel.py`）：
- 新增 `_hand_dur(rid)`，`update` / `start` / 进度条 / 详情耗时**四处**统一走它，
  漏一处就会出现\"显示 4 秒实际 10 秒\"的对不上。
- `_catalog` 不再过滤 allows —— 全部配方都是候选产物。
- 详情行显示 `手搓 X.X s/次（机器 Y.Y s）`，玩家一眼看出值不值得铺线。

**自检同步重写**（这套断言是规则唯一性的保险）：
- `_buildcostcheck`：删手搓价格校验；新增 [6] 无 `hand_`/`mk_` 残留 id、
  [6b] 无多配方物品、[7] 全部配方可自动化、[8] `HAND_CRAFT_TIME_MULT > 1`。
- `_deadlockcheck`：可达性改为\"手搓永远可行，科技锁只锁机器自动化路径\"，
  新增 `machine_ok` 集合；[4] 改成状态报告；新增 [5]\"没科技锁却无法自动化 = 设计漏了\"。
- `_startcheck`：手搓链改为按依赖序的 12 步链，科技闭包不再按 allows 过滤。
- `_craftcheck`：全部改新 id 并补铜矿/石矿投入；新增 [9] 无可自动化缺失。
- `_uicheck`：`check_craft` 用 `iron_plate` 1:1 配方 + 动态 hdur 断言（10 矿排 10 次）；
  `check_craft_panel_ui` 的 lab 耗时改 `dur × HAND_CRAFT_TIME_MULT`。

**以后加配方的铁律**：
- 一个物品只能有一条配方，id **禁止** `hand_` / `mk_` 前缀。
- `allows` 必须非空（必须能自动化），否则 `_buildcostcheck[7]` 报错。
- 改 id 必须同步 `LEGACY_RECIPE_ALIAS`，否则老存档里的机器变哑巴。

---

## 20. ~~红科研空转 + 戴森云从零搭~~（M6.7 / M6.8，**已实现**）

**背景**：用户给的里程碑计划里，M2 写的是"蓝红科研"，M4 是"戴森云"。
但实际代码里 11 条科技全吃 `science_blue`，红包（能量矩阵）根本不存在，
戴森云一行代码都没有。这俩必须一起做——戴森云的 4 条科技门槛
（`dyson1`/`sail1`/`dyson2`/`speed3`）天然是红包的食物。

**M6.7 红科研的关键决策**：
- 红包不能凭空出现，必须有完整产业链：石矿 →(`grain` 熔炉)→ 硅石 →
  (`science_red` 制造台，配磁铁 2 + 电路板 3 + 硅石 2)→ 能量矩阵。
  硅石是新物品 `I_GRAIN=14`，单独占一条配方，不许塞进石矿。
- **科研站囤包策略改了**：`labs._wanted_packs` 原先只返回当前研究的科技所需
  的科研包种类，切换科技时会把已经囤好的另一种包卡在机器里。现在 **未研究时
  返回 `TECH_PACK_ITEM` 全部值**（蓝+红都收），研究时才收当前科技的包。
  玩家因此可以提前囤红包，不用等科技面板解锁。
- 科技面板文案全部动态化（`_pack_name()`），标题按当前科技显示"蓝:电磁矩阵
  红:能量矩阵"，卡片和进度条都跟着变。以前硬写"电磁矩阵"的地方全删了。

**M6.8 戴森云的关键决策**：
- **轨道帆数是全局状态，放 `DysonNetwork`，不放发射器**。多个发射器共享同一组
  轨道，容量是全局面板式的（内轨 60 / 中轨 120 / 外轨 200）。如果把帆数记在
  发射器身上，拆一个发射器飞走的帆就凭空消失了。
- **发射器复用 `StoragePanel`**（容器接口 `space`/`add_item`/`take_item`），
  不新写一套存取 UI。它只认 `I_SOLAR_SAIL` 一种东西，`_acceptable_items` 里
  白名单卡死，分拣器喂别的东西会被拒收。
- **发射器满了就囤着**，`EMITTER_STORE_CAP=30`，轨道满了不丢帆，等玩家研究
  `dyson2` 解锁新轨道后自动接着打。这条是设计上最容易被写错的地方——早期版本
  一满就直接 `return` 丢货。
- **发电计入 `PowerGrid.supply`，不占格子、不分昼夜**。按 `帆数 × 12kW ×
  效率` 算，`sail1` 给 ×1.5。它和太阳能板走的是同一路 supply 汇总，不是
  独立电网。
- **底栏两行自适应**：`TOOLBAR` 从 10 个建筑涨到 12 个，一行塞不下（手机上
  每格不到 40px）。`touch_ui` 加了 `rows = 2 if len(TOOLBAR) > 8`，每行居中，
  `BOTTOM_BAR_H_RATIO_2ROW = 0.22`（原来是 0.14）。以后再加建筑不用改布局逻辑。
- **存档升 v7**，`dyson` 段含 `orbit_count`/`orbit_angle`/`emitters`。
  `dump`/`load_from` 里访问 `game.dyson` 一律 `getattr(game, "dyson", None)`，
  因为 `_savecheck` 的 `FakeGame` 没有这个属性——**新增子系统后存档代码必须
  保持容错风格，否则自检直接炸**。这是踩过的坑。

**`_dysoncheck.py` 的断言教训**：第一版报"`grain` 的原料石矿没有产出来源"，
错在忘 `ORE_TO_ITEM.values()` 里的矿是直接挖的、不需要配方。现在断言里有
矿石豁免。以后写"原料可达性"检查统一走这个豁免表。

**以后加戴森云相关内容的铁律**：
- 帆数是全局的，任何新建筑都别自己存帆数。
- 发射器只收 `I_SOLAR_SAIL`，别为了省事放开白名单。
- 加新轨道必须同时改 `ORBIT_NAMES` / `ORBIT_RADIUS` / `ORBIT_CAP` 三张表，
  以及 `DysonNetwork.unlocked_orbits()` 的科技映射。
- 改戴森云必跑 `_dysoncheck.py`。

---

## 21. ~~手搓队列新任务顶掉旧任务~~（M6.9，**已实现**）

**bug**：`CraftPanel` 只有一个 `self.job`。`start()` 里判定"当前任务配方和新的不一样"
就 `self.job = CraftJob(...)` 直接覆盖——旧任务的进度没了、材料已经扣了、产出永远拿不到。
玩家搓铁板搓到一半点铜板，铁板的矿就白扔了。

**改法**：
- `self.job`（单任务）→ `self.jobs`（有序列表）。`self.job` 留成只读 property 指向 `jobs[0]`，
  这样 `game.py` 的完成 toast 和旧自检一行都不用改。
- `start()` 追加队尾；队尾同配方则累加 `left`，不刷重复行。
- `update()` 只推进 `jobs[0]`，做完 `pop(0)` 后 `remaining = job.elapsed` 把溢出时间
  喂给下一个任务。**这条最容易漏**：手机上从后台切回来 dt 可能好几秒，不传下去就白吞。
- `cancel()` 清空全部（按钮文案随长度变「取消全部排队」）。
- 面板队首下面加一行「排队 N 项：铜板×3 → …」，正文区下移 14px。

**铁律**：
- `jobs` 是唯一真相，别在外面对着 `job` 赋值。
- 动了队列逻辑必须跑 `_uicheck.check_craft_queue()`（覆盖不同配方连排、进度不归零、
  同配方合并、全推完数量、大 dt 跨任务、取消清空）。

---

## 22. ~~底栏 12 个建筑挤爆手机屏~~（M6.10，**已实现**）

**问题**：建筑涨到 12 种，底栏要么一行挤成 40px 一格的按钮（手机上点不中），
要么折两行把屏幕吃掉 0.22 的高度。玩家真正常用的就那三四个。

**改法**：底栏只放 6 个大类，点大类从底栏正上方弹一条子按钮，选具体建筑。
- `CATEGORIES` 是唯一真相，`TOOLBAR` 由它展开生成——加建筑只要塞进某个大类，别处不用改。
- 单建筑分类（存储）点了直接选中，不弹子条，省一步。
- 展开子条算进 `in_bars()`，否则点下去会穿透到世界把建筑放到屏幕底下。
- 键盘快捷键选中后调 `sync_open_category()` 自动展开所在大类，桌面上不迷糊。
- 底栏高度从两行的 0.22 降回单行 0.14。

**铁律**：
- 新增建筑必须加进某个大类，否则 `_uicheck.check_category_toolbar()` 报「分类对不上」。
- `B_CORE` 是出生点核心，不可建造，**不进分类**，自检里已排除。
- 别在别处硬编码建筑顺序，一律读 `TOOLBAR` / `CATEGORIES`。

---

## 23. ~~科研站只能吃包不能造矩阵 + 科技不能排队 + 完成提示太弱~~（M6.11，**已实现**）

**问题**：科研站名义上是科研建筑，实际只会吃包；矩阵由制造台造，跟"科研"没关系。
科技一次只能研一个，想换目标必须手动点；研究完成只有一行居中 toast，容易被忽略。

**改法**：
- 矩阵垄断：`science_blue` / `science_red` 的 `allows` 改成 `(B_LAB,)`。制造台面板不再列矩阵，
  手搓面板用 `C.HANDCRAFT_BLACKLIST` 过滤。**矩阵只能由科研站制造**。
- 科研站 lab dict 扩成双模式：`research`（只输入、吃包推进当前研究项）/
  `produce`（选一种矩阵配方，原料进、矩阵出）。生产逻辑照抄 `Machine` 的配方计时。
- 分拣器打通制造模式：`acceptable` 按模式返回可收物、`grab` 能从 `outputs` 搬产物、
  `put_back` 投递失败放回科研站。四个接口都别只改一半，否则产物要么搬不出来要么蒸发。
- `TechTree` 加 `queue`：`can_queue` 让"前置在 current/队列里"也算满足，`start` 在研时自动入队，
  `add_pack_progress` 完成自动接队首。
- `ui/achievement.py` 右上角成就弹窗；`game._update` 每帧对比 `researched` 差集推送。

**坑（踩过）**：
- `_update` 里以前 `prev = set(researched)` 是在 `labs.update()` **之后**取的，差集永远为空，
  老代码那个"circuit1 解锁提示"其实从没触发过。现在提前到系统 update 之前取。
- lab dict 被存档/自检直接按 dict 下标访问（`lab["stored"]`、`lab["timer"]`），
  所以改造必须**保持 lab 是 dict**，不能换成对象，否则 `_savecheck` 全崩。新字段一律 `.get` 兜底。

**铁律**：
- 改矩阵归属必须同时跑 `_sciencecheck`（判科研站）、`_deadlockcheck`（可自动化）、`_buildcostcheck`（allows 非空）。
- 动 `LabNetwork` 的分拣器接口必须跑 `_uicheck.check_lab_panel()`。
- 动研究队列必须跑 `_uicheck.check_tech_queue()`。
- 改 lab/tech 存档字段必须升 `SAVE_VERSION` 并补迁移，`_savecheck` 迁移链要 PASS。

---

## 24. ~~底栏单建筑大类不展开 / 合成栏藏配方 / 机器面板配方太啰嗦~~（M6.12，**已实现**）

**问题**：
- 底栏"存储"只有一个箱子，点了直接选中不展开，跟其他大类行为不一致；展开大类也不高亮。
- 合成栏把不能手搓的配方（矩阵）整个藏掉了，玩家看不到配方也不知道去哪个机器造。
- 熔炉/制造台选配方是"一整行完整配方文本"，长、挤、看不快。

**改法**：
- 底栏：所有大类一律展开；高亮条件 = `选中建筑属于该大类 or cat_open == 该大类`。
- 合成栏：目录不再过滤黑名单，全部配方都列；选到不可手搓的显示"只能由机器制造，不能手搓"
  且**不给制作按钮**；所有配方都显示"该配方可用于：<建筑名>"；左栏不可手搓的显示机器名标签。
- 机器面板：配方行改成**只显示产物**（色块 + 名称 + 耗时），点击 = 设配方，选中后才显示原料槽。

**铁律**：
- 新增"不能手搓"的配方只需加进 `C.HANDCRAFT_BLACKLIST`，合成栏会自动禁用按钮但仍显示。
- 改底栏分类行为必须跑 `_uicheck.check_category_toolbar()`（现期待"所有大类都展开"）。
- 改合成栏显示逻辑必须跑 `_uicheck.check_craft_show_all()`。

---

## 25. ~~分拣器带子→带子把来源带堵死 + 丢物品~~（M6.13，**已实现**）

**问题**：目标传送带塞满后，分拣器仍然每帧抓取，投递失败后用 `try_insert`（按格头）放回，
把物品从格内原位置拽回格头 → 来源带队首永远到不了格尾、上游堵死；格头间距冲突时放回失败 → 物品凭空消失。

**改法**：`BeltNetwork.has_space()` 预判目标格有没有位置；没位置 `_acceptable_items` 返回空集，分拣器不抓；
`_grab_from_belt` 记住精确位置，`_put_back` 用 `BeltNetwork.insert_at()` 按原位插回。

**铁律**：
- 任何"先取出、失败再放回"的逻辑，必须能按**原位置**还原，禁止"放不回就丢"。
- 改 `inserters.py` 的 `_grab/_deliver/_put_back/_acceptable_items` 必须跑 `_insertercheck.py`（含 `check_belt_to_belt`）。
- 传送带目标格是否有空位，统一走 `BeltNetwork.has_space()`，别再手写近似判断。

---

## 26. 矿脉改无限后 `ore` 数组语义变了（M6.14，**已确定**）

- `self.ore` 不再是"有限储量"，只是"有没有矿"的标记 + 渲染数值，`mine()` 不递减。
- 新增任何依赖"剩余矿量"的玩法（产量随储量衰减、矿脉枯竭动画等）必须先推翻这条设定，别偷偷读 `ore` 数值当储量用。
- 老存档已挖空的格子没有类型信息，无法复活；要恢复只能重开或手动补 `ore_type`。

---

## 27. ~~制造台面板藏未解锁配方 + 传送带 rebuild 转角物品错位~~（M6.15，**已实现**）

**问题一**：`machine_panel.draw()` 原来调 `m.available_recipes(self.researched)`，未解锁的 `circuit` 被 `RECIPE_TECH` 过滤掉，面板看不到配方（跟 M6.12 合成栏"显示全部配方"原则矛盾）。

**问题二**：`belts._restore_items()` 用 `int(gx)` 取整猜格子，snapshot 坐标带 +0.5 格心偏移，转角处正交 lane 交界的一个坐标同时落在多条 lane 投影范围，取到哪条靠字典序 → 物品投影到隔壁格子/另一条 lane，表现为「转角飞出去/挤成一坨」。

**改法**：
- 面板层：`available_recipes(None)` 显示全部 + 自己查 `RECIPE_TECH` 标 🔒 + `hit()` 拦截未解锁点击。
- 恢复层：按 lane 轴向精确反解 pos（方向匹配 + 垂直偏差 ≤0.6 过滤归属 + `-0.5<=pos<length+0.5` 命中），不再用取整猜格子。

**铁律**：
- 机器面板"显示什么配方"是 UI 层的职责，逻辑层过滤（`available_recipes(researched)`）和显示层（🔒拦截）要分开；别用"把配方藏起来"代替"标锁禁用"。
- 改 `belts._restore_items` / `_snapshot_items` 必须跑 `_beltcheck.py`（含 `check_rebuild_preserves_positions`）；改 `machine_panel` 必须跑 `_uicheck.py`（含 `check_machine_locked_recipe`）。

---

## 28. ~~自动化死锁：电磁矩阵要吃被科技锁住的电路板~~（M6.16，**已实现**）

**问题**：`science_blue`（电磁矩阵）原料含电路板，而电路板配方被 `circuit1`（电子学 I）用 `RECIPE_TECH` 锁着。要研究 `circuit1` 必须吃电磁矩阵 → 蓝包制造台要电路板 → 电路板自动化要科技 → 自动产线死环。手搓能绕（M6.6 起手搓无科技锁），但全自动产线永远建不起来。

**改法**：
- `science_blue`：`磁铁×1 + 电路板×1` → `磁铁×1 + 铜线×2`。
- `assembler`：`铁板×4 + 齿轮×8 + 电路板×4` → `铁板×4 + 齿轮×4 + 铜线×4`。
- `lab`：`铁板×8 + 石材×4 + 电路板×4 + 磁铁×4` → `铁板×8 + 石材×4 + 铜线×4 + 磁铁×4`。
- `circuit1` 保留解锁电路板配方的意义不变；红包（science_red）继续吃电路板——红圈更高级。

**铁律**：
- `RECIPE_TECH` 锁住的配方，其产物**不得**出现在「研究该科技所需的科研包配方」的原料里。`_deadlockcheck` 第 6 项固化这条，改科技/配方表必跑。
- 开局能造的机器（制造台/科研站）永远别依赖被科技锁的原料，否则又是"建机器→要锁料→研究不了"的连环坑。
- 加的检查项（tech lock → pack → locked recipe 环）靠 `_deadlockcheck`，别只靠 `_startcheck` 的手搓链（它测的是静态链，不是自动化闭包）。

---

## 29. ~~机器配方面板配方多了顶穿底部~~（M6.17，**已实现**）

**问题**：机器面板 380×470，配方按行垂直排（26px/行）。制造台 16 配方 +「无」= 17 行 × 26px = 442px，光配方区就顶穿面板，盖住生产进度/原料槽/产物槽。

**改法**：面板加大到 560×600，配方改 3 列网格（34px/格、两行显示：产物名 + 耗时/🔒科技名），长产物名截断。

**铁律**：
- 机器/科研站面板的配方列表一律用网格布局，别退回单列竖排——配方会随物品越来越多。
- 改面板布局必跑 `_uicheck`（`check_machine_locked_recipe` 里固化了"配方格不得顶出面板底部"断言）。
- stub pygame 的 `font.render().get_width()` 返回 MagicMock，跟数字比大小前要 `isinstance(tw, int)` 保护，否则 `_uicheck` 直接炸。

---

## 30. ~~轨道一片空白（行星不公转）~~（M6.18，**已实现**）

**问题**：最初方案三大卖点之一——轨道与行星工程——完全缺席：行星不公转、
太阳能恒定、轨道面板只管戴森云帆。玩家看不到"行星在头顶转"，"星织"叫不响。

**改法**（最小版，故意不做大的）：
1. `world/orbit.py` 新增 `PlanetOrbit`：`angle` 唯一状态，600s 一圈，`solar_factor()` 正弦近似
   1 ± 0.25。`PowerGrid` 太阳能乘该倍率；`OrbitPanel` 画外圈行星轨道 + 行星点位；
   顶栏 HUD 恒显「光照 ×f」。（**M6.31 已升级为真实开普勒参数 + 1/r²，见 #45**）
2. 存档 v9 存 `planet` 段（angle/period/eccentricity），v8→v9 迁移补默认角度 0。

**过程坑（记牢）**：v7→v8 迁移分支原本 `return data` 提前返回，加 v8→v9 时如果不改成
`v = 8` 级联，v7 老档永远到不了 v9。改存档版本链时**检查每个旧分支是否 return**。

**铁律**：
- 行星相位只调制太阳能，不碰核心/风力/戴森云；太阳能 = 昼夜正弦 × 行星倍率。
- 加新行星 = 新建 `PlanetOrbit` 实例，别在 PlanetOrbit 里写死单例。
- 改 `orbit.py` / `grid_power.py` 必须跑 `_orbitcheck.py`；改存档结构跑 `_savecheck.py`。
- 顶部 HUD 状态行是 `game._draw_ui` 拼的，别在外面硬编码重复它。

---

## 31. 多行星已是骨架，但行星间没有物流（M5 星际，**已实现**：M5a 骨架 + M5b 运输船）

**M5a 已落地（2026-11-02）**：
1. `world/planets.py` `PlanetDef` + `PLANETS`（2 颗：故乡星 seed42 / 余烬星 seed7，各自周期/偏心率/相位）。
2. `core/worldstate.py` `WorldState`：一颗行星 = 独立 `WorldGrid` + 全套网络
   （带/机/分拣器/塔/无人机/科研/电网）+ 自己的 `PlanetOrbit` + 相机。
   `Game.worlds` 持有全部行星，`Game._activate_world(i)` 把组件挂回同名属性，
   其余代码零改动；`_switch_planet(i)` 关面板 + 切星 + toast。
3. 轨道面板多行星：每颗行星一个圆点（角度 = 公转相位），点非当前行星圆点前往，
   当前行星白圈高亮；HUD 状态栏带头显示「行星 名字」。
4. 存档 v10：`worlds` 数组（每行星 planet/grid/belts/.../camera/power）+ `world_index`；
   `dyson`/`tech`/`stats` 恒星级/玩家级留顶层。v9→v10 迁移把平铺结构打包进 `worlds[0]`。
5. `_savecheck` 升级：FakeGame 加 `worlds=[self]`，`_downgrade` 先把 worlds 提回平铺再降级；
   新增 `_multiworldcheck.py`（17 项：构造/独立/切换/往返/v9 迁移/面板点击/HUD）。

**设计定案**：
- 科技树、背包、戴森云**跨行星共享**（研究一次全星系生效；帆是恒星级）。
- 戴森云发射器只在当前激活行星工作（`_activate_world` 里 `dyson.grid = ws.grid`），帆照转。
- 每行星有自己的核心（殖民地自带一台），保证切过去开局有电、不空转。
- 切星时 `_belts_dirty` 未消费的 rebuild 先做掉再切（rebuild 幂等无害）。

**还没还的（M5b 及以后）**：
- ~~**运输船/跨行星物流**~~：**M5b 已关闭**（2026-11-11）——发射台 + 运输船 +
  发射窗口，详见 #44；行星间不再只能靠背包手搬。
- 矿种偏重：副行星只是 seed 不同导致分布不同，矿种仍随机生成。
  要"铜多铁少"做差异化矿藏表还得改 `WorldGrid` 生成逻辑。
- `_ensure_world(i)` 已支持动态生成第 3+ 颗行星（存档里比配置多时自动补），未暴露 UI。

**铁律**：
- 往 `WorldState` 加字段（比如未来的行星基础设施）必须同步：构造 + `dump` 的 worlds 循环 +
  `_load_world` + `_savecheck` 的降级字段表 + `_multiworldcheck`。
- 行星切换只准经过 `_activate_world`，别在别处直接改 `self.grid`。
- 改存档结构跑 `_savecheck.py`，改行星世界跑 `_multiworldcheck.py`。

---

## 32. ~~单存档虐玩家~~（M6.20，**已实现**）

**问题**：只有单存档（`save.slm`）+ 自动档轮转。想留"这一刻的工厂"另开新档
只能手动拷文件，误存就把旧档覆盖了。

**改法**（最小版，不动存档 schema，纯文件层）：
1. `SaveManager` 加 6 个固定槽位 `slot_1.slm .. slot_6.slm`：
   `slot_file/slot_label/slot_list/slot_meta/latest_autosave`。
   `slot_list()` 一次返回 6 槽展示信息（mtime/行星名/物品数/版本/损坏标记），
   面板打开时调一次；行星名按 `worlds[world_index]` → `PLANETS[i].name` 推断
   （存档里没存行星名，避免 v11 升级）。
2. `ui/save_panel.py` `SavePanel`：存/读两种模式，每槽一行（时间/行星/物品数 +
   覆盖/读取按钮）；读模式底部两条捷径：读最新自动档（哨兵 i=-1）、
   读旧版 `save.slm`（哨兵 i=-2，防老玩家进度"消失"）。
3. `Game`：顶栏「存」「读」打开面板；`current_slot` 记住 F5 快速存档目标槽；
   F5 直接存（不弹面板），F9 打开读面板。`_do_load` 拆成 `_load_game(name)` +
   `_save_slot/_load_slot/_quick_save/_open_*_panel`。
4. 自动存档仍走 `autosave_0..2` 轮转，不占手动槽位。

**设计定案**：
- 固定 6 槽、无重命名（手机没键盘输入）；存档文件名 slot_N.slm，显示名"存档 N"。
- 快速存档 F5 的目标 = `current_slot`：点哪个槽存过就把当前槽切到那，符合直觉。
- 旧档入口只读 `save.slm`，玩家读完后手动存到槽位即完成迁移，文件不自动动。

**坑**：`SavePanel._rows` 是 draw 时才填充的（和 StoragePanel 一致），
桩测试必须 `draw` 后再 `hit`，否则拿到空列表 IndexError。

**铁律**：
- 读档收尾（关面板/清选中/科技回退检查）只准在 `_load_game` 里，别在各处复制。
- 加槽位数量改 `SAVE_SLOT_COUNT`；改 `slot_list` 字段要同步 `_savecheck`
  的多存档段和 `_uicheck` 的 `check_save_panel`。
- 读档入口永远保留哨兵 `-2`（save.slm），别手滑删掉，老玩家进度靠它。

---

## 33. 缩放错位 + 存档面板关闭按钮（M6.21，**已修复**）

**问题 1（缩放后格子与实际渲染位置不同）**：
`ChunkRenderer.draw` 用 `tile_px = max(1, int(round(24*zoom)))` 的**整数格距**画格子，
而 `Camera.world_to_screen/screen_to_world` 用**浮点** `24*zoom` 换算。
`round(14.4)=14 ≠ 14.4`，格距差在渲染与拾取两侧逐格累积：
zoom=0.6 时屏中心外 20 格错位 8px，zoom=2.2 错位 4px（默认 0.75/1.0 只是
碰巧合入后恰好相等）。游戏里表现为：缩放到某些档位，格子/物品画的位置
和点按/放置的实际格子对不上。

**改法**：全链路统一到"整数格距"这一个事实源——
1. `Camera.tile_px` 改为 `max(1, int(round(C.TILE * zoom)))`（与渲染同式），
   `world_to_screen` = `中心 + (世界像素差 / C.TILE) * tile_px`，
   `screen_to_world` 反算用 `/ tile_px * C.TILE`（拾取/放置/缩放锚点全部走这条）。
2. `_draw_items` 的向量化换算由 `ddx * zoom` 改为 `ddx / C.TILE * tile_px`，
   物品与格子共用同一套整数格距。
3. `_draw_machine_status` / `_draw_ghost` / sprite 半径等消费 `tile_px` 的地方
   自动跟着变整数，无需逐个改。

**问题 2（存档面板关闭按钮点了没反应）**：`SavePanel.draw` 里局部画了个
`close_rect`，但 `hit()` 没有它——抄 `OrbitPanel` 时的遗漏，点击被"面板内
一律消费"吞掉。`_close_rect` 提升为字段 + `hit` 检查。顺带自查：其他面板
（OrbitPanel）的关闭按钮是好的。

**验证**：zoom 0.6/0.75/1.0/2.2 下 camera 与渲染公式偏差 0.000px；
`screen_to_grid(world_to_screen(格中心))` 闭环；缩放档切换 20 帧不崩；
0.6x 与 2.2x 下同一格放置/拆除落点一致。17 项自检全绿。

**铁律**：
- "格子的像素尺寸"只准由 `Camera.tile_px` 决定，别在渲染/拾取处再写
  `int(round(C.TILE * zoom))` 或 `C.TILE * zoom` 的变体——两套格距就是错位根源。
- 面板里有按钮就先有字段（`_close_rect`），`draw` 画、`hit` 验同一份 rect；
  draw 局部变量画、hit 找不到 = 必然出现"点了没反应"。
- 改相机换算后必跑全套自检（`_wrapcheck` 卷绕、`_uicheck` 桩 UI、
  `_multiworldcheck` 面板绘制都依赖 camera）。

---

## 34. UI 定义化：控件级 JSON（M6.22，**机制已落地，面板逐个迁**）

**问题**：所有面板的外观（标题/颜色/尺寸/文案/按钮布局）硬编码在 Python 里。
改文案要改代码、换主题要到处改色值、玩家想自定义布局更是无从谈起。

**机制**（`ui/uidef.py` + `ui/defs/*.json`）：
- JSON 以控件为单位描述 UI：`meta`（主题色 `#RRGGBB[AA]` / 常数）+ `controls`
  （type: `label` / `button` / `list`）+ 可选 `buttons`（{action,text} 序列）。
- 控件定位：`x/y/w/h` + `anchor`（tl / tr）；负坐标 = 距右/下缘；负宽高 = 相对
  对侧边缘延伸。字号数字直用（字体表取）。
- 运行时一个入口：`draw_controls(screen, defs, panel_rect, fonts, overrides)`
  统一画静态控件（业务传 `overrides`：动态文案/显隐/高亮）；`hit_control` 统一
  命中（只查 button）。`list` 是动态列表模板——行参数在 JSON，行内容业务画。
- 加载失败（缺文件/坏 JSON/未知 type/缺 w/h）一律 `ValueError`，启动即报，不静默。

**已迁移示范**：
1. `save_panel.json` —— 存档面板全部外观 + 底部两条捷径按钮 + slots 行模板。
2. `touch_top.json` —— 顶栏 10 按钮的顺序/文案/布局参数；增删/改序只动 JSON
   （动态文案如"暂停/继续"、"方向→"仍由代码覆盖）。
3. `main_menu.json`（M6.25）—— 主菜单标题/按钮/配色（新增 `cc` 居中锚点 +
   `disabled` 禁用态两个通用件）。
4. M6.26：`filter_panel` / `bag_panel` / `lab_panel` / `tower_panel` 四个面板
   迁 defs（配色/静态文案/布局参数下沉，动态行仍业务画但颜色全取 meta_c）。
   同时落地 **`defs/theme.json` 全局皮肤**：load_def 把主题 meta 当兜底合并
   （面板 meta 优先），改 theme.json 一处换全面板色；uidef 加
   `overrides["color"]` 支持单控件动态换色（塔标题绿/橙）。

**迁移清单（未完成，随里程碑逐个迁，每个面板迁完跑全套）**：
- [x] filter_panel（M6.26）
- [x] bag_panel（M6.26）
- [x] lab_panel（M6.26）
- [x] tower_panel（M6.26）
- [x] 全局配色抽到 `defs/theme.json`（皮肤化：一份 meta 全面板换色）——
  机制已落地；存量面板可逐步把自有 meta 清成"只留覆盖键"（不阻塞）
- [x] storage_panel（M6.28 窗口化时补 defs）
- [x] machine_panel（M6.28：配方选择器改造时迁 defs，配方列表外观随主界面瘦身重画）
- [x] tech_panel（M6.28：树状图重写，全屏页保留自有样式未用 draw_window）
- [x] orbit_panel（M6.28 窗口化时补 defs）
- [ ] craft_panel（手搓全屏页：进度条/左列表/右明细，未迁移——M6.28 明确不参与窗口化）
- [ ] TouchUI 底栏/子按钮配色（顶栏已迁，底栏是 CATEGORIES 动态生成）

**M6.28 窗口化说明**：浮窗面板（orbit/save/storage/lab/machine/tower/filter/
bag）已全部走 `uidef.draw_window`（底/边框/左上角等腰梯形标题栏统一画，
titlebar_h 主题兜底 26），标题栏 = 拖动手柄（ui/window.py + Game 手势）。
craft/tech 两张全屏页不画标题栏、不参与拖动（内部布局基于全屏坐标系，
强行窗口化收益低）。

**自检**：`_uidefcheck.py`（第 18 项，全套必跑）——加载器单元、临时 JSON
改文件生效、存档面板 JSON 绘制/命中、顶栏顺序/动态文案。

**铁律**：
- 新面板一律优先 JSON 定义外观（先有 defs 再写代码）；老面板迁移时保持
  公开接口（show/draw/hit/open）不变，避免连锁改调用方。
- 颜色只写 `#RRGGBB[AA]` 进 JSON；Python 代码里不许再散落面板色值。
- 动态数据（行列表、库存角标、锁定 🔒）留在代码，JSON 只管静态外观与模板参数。
- 改 defs 结构要同步 `_uidefcheck`（锚点/错误路径断言）和对应面板自检。

---

## 35. 面板打开时手势穿透到地图（M6.23，**已修复**）

**问题**：部分面板打开时，触屏拖动会直接滑后面的地图（相机移动），双指捏合
会缩放世界——面板像是透明的。`_handle_gesture` 的 DragEvent / PinchEvent /
MOUSEWHEEL 分支只拦截了少数面板：
- DragEvent 只拦 手搓（滚动）/ 背包 / 过滤 / 科技（滚动）——**存档、轨道、
  箱子、科研站、机器、物流塔 6 个面板穿透**（实测相机被拖走）；
- PinchEvent 只拦 科技——其余全穿透（含手搓，实测缩放）；
- MOUSEWHEEL 只拦 手搓/科技——其余面板开着滚轮也缩放世界。

**改法**（一处规则三处用）：任何面板打开时，地图手势（拖动/捏合/滚轮）一律
不生效；有滚动能力的面板（手搓/科技）仍然优先滚动列表。
- DragEvent：在手搓/背包/过滤/科技分支后追加"其余 6 面板 open → return"。
- PinchEvent：全部面板 open → return（含手搓/科技）。
- MOUSEWHEEL：手搓/科技滚动后，其余面板 open → continue（不缩放）。

**自检**：`_uicheck` 新增 `check_drag_block`——9 个面板（存档/轨道/箱子/背包/
手搓/科技/科研站/机器/过滤）逐一打开后发 DragEvent + PinchEvent，断言相机
坐标与缩放都不变；并对每个面板先断言"确实打开"（防假绿）。塔面板因科技锁
无法在桩下打开，其拦截路径与机器面板同一分支，由机器覆盖。

**铁律**：
- 新面板接入 `_handle_gesture` 的三处拦截清单（拖动外漏清单在
  DragEvent 分支、捏合在 PinchEvent 分支、滚轮在 MOUSEWHEEL 分支）——
  漏一处就是"面板像透明的"。
- 面板新增滚动能力（scroll_by）时，在 DragEvent/Pinchevent 分支对应该给
  scroll_by 而不是直接 return。
- 手势回归测试跑 `_uicheck`（check_drag_block 必须过）。

---

## 36. 架构分层：服务器端 sim + 前端渲染（M6.24，**已落地**）

**目标**（用户指示，类 Minecraft C/S）：单独提取服务器端做计算，前端游戏只负责
渲染。本仓库落地为**进程内分层**：逻辑与渲染同进程但硬隔离——服务器端零图形依赖。

**分层**：
```
stellarloom/sim/           服务器端（headless，零 pygame）
  sim.py       Simulation：世界集合/科技/戴森云/背包/手搓队列
               step(dt) 推进 + 指令 API + 事件流（toast/成就/脏格子）
  craft_queue.py  手搓队列（从 ui/craft_panel 抽出）
  headless.py   python -m stellarloom.sim.headless [存档] [tick] 无图形跑模拟
stellarloom/                前端
  core/game.py  Game：渲染 + 输入翻译成 sim 指令 + UI；不再持有逻辑状态属主
  render/ui/input/          渲染/面板/手势
```

**关键动作**：
1. `Camera` 摘掉 pygame（pan 键常量本地化）——数值相机，逻辑层可用。
2. `ChunkRenderer` 移出 `WorldState`（纯渲染缓存），前端 `_chunk_views` 按行星持有。
3. `core/__init__.py` 懒加载 `Game`（PEP 562）——headless 链永不触 pygame。
4. `Simulation` 指令：place_building / place_tower / lay_belt_line /
   place_inserter / remove_building / set_overlay_filter / do_craft /
   cancel_craft / switch_planet；事件：`pop_events()`、`take_dirty_cells()`。
5. Game 只转发：`_place_or_harvest` 等 UI 分支保留，落地动作全在 sim。
   手搓/拆除/退款/容器退货/研究判定都在服务器。
6. 存档属主 = sim（`SaveManager` 存 `Simulation`）；前端 `_load_game` 读档后
   重新挂载组件 + 清空全部 chunk 视图。

**自检**：`_simcheck.py`（第 19 项，全套必跑）——干净解释器子进程断言
`import sim 后 sys.modules 无 pygame`；headless 600 tick；指令闭环（放置扣料/
拆除退款守恒）；Game-sim 同引用；存读档往返。全套 19 项全绿；真实档
`save.slm` headless 读档跑通（2435 tick/s）。

**铁律**：
- **服务器端零 pygame 是硬红线**：sim 及其依赖链里不许出现 pygame。
  新项目文件先自查：`python -c "import <mod>; assert 'pygame' not in sys.modules"`。
- 改逻辑先想它属于 sim：新玩法/新机制的状态与推进放 `Simulation`（或它拥有的
  WorldState/网络），前端只调指令。**禁止前端直接改 sim 状态**（如
  `game.inventory` 是引用，测试里也只能原地 `clear()+update()`，不能换引用）。
- `Game` 里残留的"前端直写逻辑"（如面板对网络对象的写入）逐步收敛成指令
  （见下方待办），不阻塞本期。
- 自检里沿用 `g.inventory[...] = v` 下标赋值是原地操作（同引用，允许）；
  换引用（`g.inventory = {}`）会断 sim 同源，一律改 `clear()+update()`。

**待办（后续轮次）**：
- [ ] UI 面板对 sim 状态的直写（storage/machine/lab 面板点按钮改网络对象）
      收敛为 sim 指令（面板 API 化，逻辑留在服务器）。
- [ ] sim 指令加防错返回（place 系列已返回码；面板类操作陆续补）。
- [ ] （远景）真要跨进程：把 Simulation 的输入/事件序列化成协议即可
      （进程内 API 已把边界画清，接口就是协议面）。

---

## 37. 主菜单（M6.25，**已实现**）

**需求**：游戏有启动封面，能 开始新游戏 / 继续游戏 / 读档 / 退出。安卓 Pydroid3
上手势/返回都要顺手。

**实现**：
1. **外观 JSON 化**：`ui/defs/main_menu.json`（标题 cc 居中 + 4 按钮贴底 +
   footer）。先给 UI 定义层补了两个通用能力（对后续面板都有用）：
   - `anchor "cc"`：控件相对面板中心定位（`rect` 中心对齐 / `label_pos` 居中）。
     **注意：anchor 写在 rect（或平铺字段）内部**，UiCtrl 只从 rect 读锚点。
   - `overrides["disabled"]`：按钮/文案灰置（muted 色）+ `hit_control` 跳过，
     是"这里能点但不该响应"（无档时的"继续游戏"）。
2. **生命周期**：`Game.__init__` 末尾 `_open_menu()`（启动即主菜单，世界在背后
   暂停生成）。顶栏 `touch_top.json` 末尾新增「菜单」按钮（最左），
   `_apply_ui_action("menu")` 关掉全部面板再开菜单。
3. **菜单 = 最强拦截层**：TapEvent 在 `_handle_gesture` 最前吃、DragEvent /
   PinchEvent / MOUSEWHEEL 拦截清单全部加 `menu.open`（M6.23 面板拦截规则），
   `_update` 里 `not paused and not menu.open` 才 `sim.step`。
   `_on_key` 菜单开着只认 ESC。
4. **四个动作**：
   - 新游戏 `_start_new_game()`：**重建 `Simulation`**，前端重挂（
     `self.sim.saves = self.saves` 保留存档目录，**存档文件一律不动**）。
   - 继续 `_on_menu_action("continue")`：读 `latest_autosave()`，无档则灰置。
   - 读档：关菜单 → `_open_load_panel()`（多存档面板接管）。
   - 退出：`running = False`。
5. **自检 `_menuecheck.py`**（第 20 项，全套必跑）：定义加载（cc 居中/按钮
   排开）、命中/失中、禁用态、菜单拦截（点按/拖动/捏合/暂停）、关闭恢复
   （面板开着不许拖是 M6.23 规则，测试里要先关面板）、顶栏入口、新游戏重建
   （sim 换新对象 + 世界清零 + 存档文件保留）、继续读档（真实造 autosave 再
   拆除，验证读档恢复）、ESC。多分辨率（640×480 / 720p / 竖屏）布局不越界。

**铁律（新增）**：
- **"新游戏"只允许重建 sim，绝不允许删/覆盖存档文件**（玩家存档是红线）。
- 主菜单开着 = 模拟暂停 + 手势全拦——任何新面板/覆盖层都要遵守 M6.23 清单
  （拖动/捏合/滚轮拦截位各一处，漏一个就穿透）。
- 测试直达游戏态要显式 `g.menu.open = False`（Game 构造默认进主菜单）。
- anchor 写 rect 内（UiCtrl 只读 rect）；`disabled` 只做灰置+不响应，
  不改变按钮 rect（命中区还在）。

**待办**：
- [ ] 主菜单背景可以加"星图/旋转行星"装饰（当前是暂停的世界画面，够用）。
- [ ] 设置项（分辨率/音量/灵敏度）进主菜单——Pydroid3 上可选项少，暂不急。

---

## 38. 读档换引用撕裂背包（**已修复**，M6.24 分层引入的回归）

**症状**（用户报）：存档里/背包里明明有该物品，使用时却提示"X 不够（有 0，要 1）"。
实测：读档后 `Game.inventory is sim.inventory == False`——底栏/背包面板显示旧背包
（开局物品），放置等扣款走 sim 新背包（存档内容），两边对不上。

**根因**：M6.24 前 `Game` 是背包的唯一属主，`load_into` 用
`game.inventory = {int(k): v ...}` **替换引用**没人在意；M6.24 分层后
`Simulation` 成了属主，前端 `Game.inventory` / `ui.stock` / `craft_queue.inv`
在构造时复制了**同一个 dict 的引用**。读档时 load_into 换新 dict，所有旧引用还
指着开局背包——"显示有、扣没有"的分裂就这么来的（craft 队列同样分裂：
手搓材料显示/扣款不一致）。

**修法**（最小）：`savefile.load_into` 的背包恢复改成**就地更新**：

```python
game.inventory.clear()
game.inventory.update(items)   # 不换引用，所有持有方一次同步
```

**自检**：全套 20 项全绿；真实档 headless 读档后 `craft.inv is inventory == True`、
手搓可正常排队；复现脚本（读档后放熔炉）从 BUG 复现 → 修复生效；临时脚本已删。

**铁律（新增）**：
- **存档恢复一律就地更新，禁止换容器引用**（dict/list 先 `clear()` 再
  `update()`/`extend()`）。分层后任何对象都可能被多处复制引用。
- 测试断言"视图与真源同引用"（如 `g.inventory is g.sim.inventory`）应成为
  读档用例的标准体检项（_simcheck [4] 已覆盖同引用）。

---

## 40. MOD 支持（M6.27，**已实现**）

**内容**：mods/ 加载器 + mixin（运行时非永久补丁）+ API 暴露（`stellarloom/api.py`）。
详见 `Docs/Mods.md`（开发者文档）。用户拍板：mixin **全开放**（任意类可 patch）、
内容扩展 API 本轮做。

**已知取舍**：
- mixin 全开放 = 无沙盒。mod 可以 patch 任何方法（含存读档、科技树），改坏了
  它自己负责；加载器只做失败隔离（单 mod 抛错 → 该 mod 失败，游戏不崩）。
- 内容注册（物品/配方）随卸载撤销，但 **存档里 mod 物品 int id 不会**——
  卸载后旧档对应 id 显示 "?"。文档已让 mod 作者用 1000+ 自留段。
- 事件钩子只转发"服务器事件流"（toast/achievement 等）；更细粒度的事件
  （建筑放置回调等）可自己 mixin after place_building，无需框架支持。
- 热重载 / headless 加载 mod 均未做（后续可选）。
- 动态注册的物品不进底栏 CATEGORIES 分类（手搓/机器已可见，展示分类待补）。

**M6.28 补充**：主菜单「模组」管理页（仿 minecraft）已实现——列出 mods/ 全部
mod，状态（已加载/失败原因/已禁用）+ 每行 [禁用]/[启用] 即时生效（写
`mods/.disabled` 名单并热重载）。禁用名单的取舍：改动立即写盘但只有 next
加载生效（重载已即时）；`.disabled` 里手误禁用的 mod 重启后仍跳过，删除该
文件即可恢复全部。

**测试铁律（M6.28 追加）**：自检构造 Game 后必须先 `mod_mgr.unload()` 卸掉
真实 mods/ 目录——玩家 mod 的 mixin（如 gregtech 系列 replace
`MachineNetwork.sync`）会在进程内永久污染类状态，连跑多个用例互相踩
（症状：后续用例"熔炉没建起来"）。`_uicheck.new_game` 已内置；新写自检照抄。

**自检**：`tools/_modcheck.py`（第 21 项）11 段：加载隔离 / 三类 wrap / 内容
扩展+冲突拒绝 / 钩子 / 卸载还原（patch+注册）/ 重载幂等 / 真实 Game 挂载 /
模组管理（available/status/禁用热重载/.disabled 持久化/面板冒烟）/ 统一 config
（合并/落盘/坏文件隔离）/ 依赖关系（拓扑序/版本门禁/缺依赖/环/禁用传导）/
注解式 mixin（@Mixin 字符串与类对象 target、HEAD cancel、RETURN 覆盖、
Overwrite、自动收集、卸载还原、坏目标失败隔离）。

**M7（注解 mixin）边界**：只有 `@Inject(HEAD/RETURN)` 与 `@Overwrite`——没有
`@Redirect / @ModifyArg / @Shadow` 等进阶注解；注入函数不接收关键字参数
（原方法的 `**kw` 由包装器透传）；同方法多个注入按类体定义顺序依序包装
（后注册先执行），卸载逆序还原。

**M6.29 补充**：
- **统一 config**：作者 `config.json`（默认，随 mod 分发）⊕ 用户
  `mods/config/<名字>.json`（`ctx.save_config()` 写入）→ `ctx.cfg` 运行时合并
  dict。边界：没有"配置热重载"——on_load 读一次，运行中改配置要自己调
  save_config + 自己处理生效时机；无 UI 编辑控件（模组管理页只显示状态）。
- **依赖**：mod.json `dependencies`（version 表达式 `> >= == < <=`，裸数字=
  精确、空串=任意）。已知取舍：依赖按 mod.json 的 **name** 匹配（不是目录名），
  改名即断链；版本只做数值段比较（`1.0.0-alpha` 按 1.0.0 比）；被禁用 mod
  视同"没加载"，依赖者以"缺少依赖"失败（不再额外报"被禁用"）。

---

## 41. 配方数据 JSON 化（M6.28，**已实现**）

**问题**：23 条内置配方硬编码在 `config.py` 的 `RECIPES` dict——改配方要动代码，
模组玩家想加/改配方只能靠 `ctx.add_recipe`（代码），数据与代码不分家。

**改法**：配方迁到 `stellarloom/data/recipes.json`（物品/建筑用数字 id，见 config
`I_*`/`B_*`），`config.py` 里 `RECIPES = load_recipes()` 启动即加载，**格式保持
4 元组 `(inputs, outputs, dur, machines)`，全部消费者零改动**。`data/__init__.py`
加载时校验（缺字段/数量非法/物品 id 未注册 → ValueError 启动即报）。mod 的
`ctx.add_recipe` 注入同一个 dict——内置/玩家共用一套配方数据源。

**遗留（M7 已清）**：M6.28 遗留的"recipes.json 全是裸数字、不可读"问题——
M7 物品注册表落地后，配方 JSON 已改存 **命名空间名字**
（`"stellarloom:iron_ore"`，machines 用 `"stellarloom:furnace"`），裸数字
与数字字符串仍兼容读取。mod 配方走代码 `add_recipe`（天然动态），
mod 内 JSON 配方声明仍未做（后续可选）。

---

## 42. 物品注册表（M7，**已实现**）：MC 风格命名空间 + 动态分配 + 存档名字化

**问题**：物品/建筑/配方全靠"硬编码数字 id"（config.py I_* / B_* 常量、
配方 JSON、存档全是数字）——mod 注册要自己抢数字段（300、1001+），存档
数字 id 跨版本会漂移，配方 JSON 人不可读。

**改法**：
- 新增 `stellarloom/registry.py` `ItemRegistry`：**名字 ↔ 数字 id** 双向表。
  原版固定命名空间 `stellarloom:`（铁矿石 = `stellarloom:iron_ore`）；
  mod 用自己目录名作命名空间。名字 = 持久化/交互表示（存档、配方 JSON、
  mod API）；数字 = 运行时内部表示（inventory dict、机器槽、渲染查色，
  **消费方零改动**）。
- **动态分配**：`ctx.add_item("mymod:magic_ingot", ...)` 新式名字注册 →
  注册表自动分配 id（从 15 起，跳开原版固定段）；旧式 `ctx.add_item(300,...)`
  数字注册 → 固定段兼容（键 `mymod:item300`），旧存档数字可反查。
- **存档 v11 名字化**：`savefile.py` 的物品字段（stats.inventory、机器
  inputs/outputs、矿机 buffer、箱子 store、塔 inventory/filter、科研站、
  无人机 cargo/task_item、传送带 items）全部存名字；v10 及更老的数字档
  读档时数字直通（同进程分配表可反查），未知名字 → 汇总 -1 显示 "?"。
- 配方 JSON / `ctx.add_recipe` 的原料产物支持名字（数字仍兼容）。

**边界（诚实）**：
- 网格地块数组（building / overlay / overlay_filter / ore）仍在存档里
  存数字——它们是"地块类型"不是物品清单，转名字成本高收益低；
  overlay_filter（分拣器过滤）也保持数字（UI 用注册表显示名）。
- 建筑类型（B_*）M8 已注册表化（见 #43）；存量 mod（gregtech_*）硬编码
  的数字建筑段（20-23 / 30-37）不进注册表、照常运行，动态分配从 100
  起避开它们。
- 读档时遇到"未注册名字"（mod 已卸载）→ 汇总成 -1（显示 "?" 一项），
  明细丢失；重新启用 mod 后老档物品不自动回来（与"内容注册随卸载撤"
  的设计方向一致）。

**测试**：`_savecheck` 增"M7 存档物品键名字化 + 旧数字档兼容 + 迁移链
v1/v2/v3→v11"；`_multiworldcheck` 增"迁移后物品键是名字"；`_modcheck`
注册表 API 用例（动态分配/固定段/冲突拒绝/卸载还原）。全套 21 项全绿。

---

## 43. 建筑注册表（M8，**已实现**）：建筑类型也进 MC 风格注册表

**问题**：M7 只注册表化了物品；建筑类型（B_*、mod 建筑）仍是硬编码数字
（原版 1-13 在 config，mod 自己定 20-23 / 30-37 直接拿去用；M5b 已扩到 14）——
mod 建筑没有名字入口，注册/显示/联动全靠手写。

**改法**：
- registry.py 新增 `BuildingRegistry`：名字 ↔ 数字 id（原版固定段 1-15
  （M5b 加发射台 14），
  键 `stellarloom:belt`；**动态段从 100 起**，避开原版与存量 mod 硬编码段）。
- config.py：B_* 常量改由注册表生成（值不变）；`BUILDING_NAMES` 变注册表
  实时视图（mod 注册立即可见，UI 零改动）。
- `ctx.add_building(btype, name=None, item=None)`（M8 新 API）：
  * 名字注册（`"mymod:foundry"`）→ 动态分配 id（≥100）；
  * int 旧式 → 固定注册，键 `mod名:b<id>`（给存量硬编码段登记显示名）；
  * `item=` 建筑物品名/数字 → 自动注册 `BUILD_ITEM[btype]` 联动
    （底栏取物 / 放置消耗 / 拆除返还直接生效）。
- `ctx.add_recipe` 的 `machines` 现在解析建筑**名字**（`("mymod:smelter",)`），
  数字照旧；`recipes.json` 的 machines 由注册表解析（原版/新 mod 同源）。

**剩余边界**：网格地块数组与存档仍存数字建筑 id（#42 同款理由）；
存量 mod 建筑（gregtech_* 硬编码段）未迁移进注册表（用户资产不动，
动态段已避开，不冲突）。

**测试**：`_modcheck` 增 [13]（动态分配 ≥100 / 视图同步 / BUILD_ITEM 联动 /
固定段兼容 / machines 名字解析 / 未知机器拒绝 / 卸载还原）。全套 21 项全绿。

---

## 44. 星际物流（M5b，**已实现**）：发射台 + 运输船 + 发射窗口

**问题**：M5a 有了多行星骨架，但行星间只能"玩家过去 + 背包手搬"，
没有自动物流；轨道系统的相位/公转只是视觉与太阳能系数，没有玩法出口。

**改法**：
- 新模块 `logistics/pads.py`：
  - `LaunchPad`：3×3（网格只记中心格），`mode=supply|request`，库存上限
    `PAD_STACK=50`，`target` 记目标行星。带子交换口逻辑与物流塔同款
    （供货台从外圈一圈传送带吸货，要货台往外圈吐货）。
  - `PadsNetwork`：每行星一个（挂 `WorldState.pads`），`sync()` 扫描网格、
    `can_place()` 保证 3×3 不重叠、拆台时清船。
  - `Ship`：恒星级实体，坐标 `(world_index, pad_x, pad_y)`，
    状态机 `docked → outbound → inbound → docked`，`cargo` 上限
    `SHIP_CARGO_CAP=20`；`progress()` 供 UI 画在途位置。
  - `Fleet`：挂 `Simulation.fleet`，`update(dt, worlds)` 跨全部行星跑：
    供货台有货 + 目标行星有要货台 + 窗口开 → 装货出发；
    到达卸货（装不下随船带回）；返航卸回母台；母台被拆 → 船清掉。
  - 发射窗口：`phase_diff ≤ SHIP_WINDOW_ANGLE(30°)` 才能发；
    `window_wait()` 解析解算下一次开窗秒数（同周期 → `inf` 无窗口），
    `window_hold()` 算窗口剩余时长。
- 建筑/物品/科技：`B_LAUNCH_PAD=14`、`I_LAUNCH_PAD_ITEM=113`
  （`stellarloom:launch_pad`）、配方 `launch_pad`（制造台）、
  新科技 `interstellar1`（40 红瓶，前置 drones1+dyson1）。
- UI：底栏「物流塔」类新增发射台；`pad_panel`（模式/目标行星/窗口倒计时/
  船状态/库存）；轨道面板画在途船（两行星连线按进度插值）+ 下个窗口预测。
- 存档 v12：每行星 `pads[]` + 顶层 `ships[]`（在途状态与货物）；
  v11→v12 补空表。

**剩余边界**：
- 发射台不过滤物品、不设优先级；目标行星内若有多个要货台，选第一个
  （`pads.py: _try_launch` 里的顺序遍历）——够用，暂不引入分拣面板。
- 非当前行星的带子网络不 tick（M5a 起就是"只跑当前行星"），
  所以远端发射台的带子取货暂停，但**库存发货照常**（舰队是恒星级）。
- 运输船不耗油、不损坏；每座供货台固定 1 条船。

**测试**：新自检 `tools/_shipcheck.py`（8 段：常量/窗口解析 vs 数值模拟/
放置与重叠/拆台清船/装货-飞行-卸货闭环/窗口关不发/满仓带回/存档往返含
在途船/模式切换/面板点击渲染）。全套 **22 项自检全绿**。

---

## 45. 真实行星参数（M6.31，**已实现**）：开普勒椭圆 + T=a^1.5 + 1/r² 日照

**问题**：M6.18 的轨道是"手感数值"——周期手填 600s/420s、偏心率 0.25/0.35，
日照用 `1 ± e·cosθ` 正弦近似；行星匀速转圆，和真实天体力学没有关系。
用户要求"按照真实行星参数计算轨道、周期等"。

**改法**：
- 新模块 `world/kepler.py`：真实太阳系数据表（水星/金星/地球/火星的 a、e、T）、
  开普勒方程牛顿解、真/平近点角互转、椭圆半径 `r=a(1-e²)/(1+e·cosν)`、
  `period_seconds(a)=a^1.5×SECONDS_PER_YEAR`、`period_days(a)=a^1.5×365.256`、
  `semi_major_from_period`（老档反推）、`orbit_points`（面板画椭圆）。
- `PlanetDef`：`orbit_period` 删除，改真实字段 `a_au / eccentricity / arg_peri`，
  `orbit_period` 变派生属性；故乡星=地球参数、余烬星=火星参数（`ref` 记录参考天体）。
- `PlanetOrbit`：内部状态改为**平近点角** `_M`（匀速推进），对外 `angle` 是真近点角
  （setter 反解 M，兼容测试/老档直接赋值）、`radius_au` 是日心距；
  `angle_after(dt)` 给窗口预测用；`solar_factor()=(1/r)²`。
- `sim.step`：遍历全部 `worlds` 推进行星（不是只转当前行星）。
- `pads.window_wait/hold`：真实轨道无解析解，改为"相对平近点角每步 5° 粗扫
  + 25 次二分"的数值解（同周期仍返回 inf），实测 0.11 ms/次。
- 轨道面板：按真实 AU 比例画椭圆轨道（近点辐角旋转）+ 行星点在真近点角处；
  顶部/底部显示真实参数（AU / 偏心率 / 地球日周期 / 相对日照）。

**数值验证**（`_orbitcheck`）：
- 地球 T=600s=365.26 地球日、火星 T=1128.5s=686.98 地球日、水星 87.97 地球日；
- 近日点 a(1-e)/远日点 a(1+e)（e=0.3 → 0.70/1.30 AU；地球 0.9833/1.0167）；
- 高偏心率下近日点真近点角推进快、远日点慢；
- 日照 = 1/r²，地球 0.967~1.034、火星 0.36~0.52；
- 存档往返全字段一致；老档（无 a_au）按周期反推、行为不变。

**剩余边界**：
- 只有轨道力学真实：自转/倾角、行星质量、引力摄动、轨道进动都没做（2D 平面游戏不需要）。
- 游戏时间尺度是 1 地球年 = 600 秒；真实周期按比例缩放，不是真实时间。
- 矿脉分布仍按 seed 随机，不随行星真实成分变化（TechDebt #31 残留）。
- 存档版本仍是 v12：planet 段新增字段向后兼容，没有强行升版本。

**测试**：`_orbitcheck` 重写（6 段）、`_shipcheck` 窗口对照改开普勒数值积分、
`_multiworldcheck` 面板命中共用 `_planet_xy`。全套 **22 项全绿**。

---

## 46. 行星工程（M6，**已实现**）：行星引擎 + 变轨 + 温度降效

**问题**：M6.31 之后轨道参数是真实了，但玩家只能"看"不能"动"——行星永远停在
初始 a/e 上，太阳能差异是命定的，星际窗口也只能干等。

**改法**（最小闭环）：
- 建筑 `planet_engine`（15，3×3）+ 物品（114）+ 配方 + 科技 `engine1`
  （80 红瓶，前置 interstellar1 + dyson2）——晚于星际物流，属于"行星级工程"。
- `Simulation`：`place_engine`（复用 pads.can_place 的大件重叠检查）、
  `engine_at`（3×3 反查中心）、`has_engine/engine_powered`、
  `set_orbit_a_ratio/nudge_orbit_a/shift_orbit_phase`。
- `PlanetOrbit`：`set_semi_major(a)` 重算周期（T=a^1.5）并保持当前相位、
  `shift_phase(deg)` 平移平近点角、`temperature_c()`（T=288K·r^-0.5）、
  `temperature_efficiency()`（>35°C 每度 -0.5%，下限 0.35）。
- `PowerGrid`：太阳能发电再乘温度效率——推太近会"光更强但板更烫"。
- UI：底栏「行星」类、3×3 ghost、`ui/engine_panel.py`（变轨控制台）、HUD 轨道倍率。

**数值验证**（`_enginecheck`）：
- 未研究不能放；3×3 反查/拆除退料；电网需求 +40。
- 断电时半径/相位都不动；通电后 ×1.5 → 周期 600→1102s、光照 1.03→0.46、
  温度 17→-36°C；clamp 到 0.60/1.80。
- 近轨道 102°C → 效率 0.67；远轨道 -57°C → 效率 1.00。
- 近/远轨道同一时刻发电对比（含降效）近轨道更高——收益递减但为正。
- 存档往返：a/period/mean_angle 一致，引擎建筑保留。

**剩余边界**：
- 只调 a 与相位，不改偏心率/近点辐角（真实变轨要两次点火，先不做）。
- 变轨是瞬时的（没有"引擎工作 N 分钟"的进度与耗电积分）。
- 温度只影响太阳能，不产生"过热损坏/需要散热器"的玩法。
- 引擎放在哪颗行星就调哪颗；别的行星的引擎要切过去操作。
- 存档仍 v12（planet 段字段早已存在，建筑走 grid，无需迁移）。

**测试**：新自检 `_enginecheck.py`（10 段），全套 **23 项全绿**。

---

## 47. 星系视图与缩放衔接（M6.32，**已实现**）：缩到最小继续缩 → 星系视图；轨道只做戴森

**问题**：星系视图（轨道面板）只能靠底栏按钮打开，和地图缩放两套操作割裂；
面板里还混着行星轨道参数（半长轴/偏心率/周期），而戴森轨道除了"看载量"
没有任何可操作项——配置注释里写了"点轨道选发射目标"，代码里根本没实现。

**改法**：
- **缩放衔接**：`Game._zoom_by(factor)` 统一缩放入口（滚轮 / 鼠标 4·5 键 /
  双指捏合都走它）。相机到 `ZOOM_MIN` 后继续缩小，把
  `max(ZOOM_PULL_MIN_STEP, -ln(factor)×ZOOM_PULL_RATE)` 记进 `_zoom_pull`（0~1）：
  顶部画进度条「继续缩小进入星系视图 N%（点这里也行）」，满 100% 自动打开；
  进度**粘性不回落**（避免"停手掉一半/慢慢缩永远到不了"），点进度条也能进。
- **回地图**：星系视图开着时放大（滚轮向上 / 捏合放大）或 ESC 关闭，
  相机保持当前缩放（进度清零，不会重复触发）。
- **轨道只做戴森**：面板底部去掉行星轨道参数行，换成"点轨道环指定发射目标轨道"；
  `DysonNetwork.target_orbit`（None = 自动选最空）+ `set_target_orbit()`
  （点同一环 = 取消，只接受已解锁环）；`_pick_orbit` 优先玩家指定，环满回落自动。
  目标环画成黄色高亮 + 标「◀目标」。
- **导航保留**：点行星圆点仍然切星（用户确认）。

**行为验证**（`_viewcheck`，第 24 项自检）：
- 缩到最小再缩：进度 0→满，5 次滚轮进星系视图；刚好缩到最小那一下不攒进度。
- 放大 / ESC 回地图，缩放不变；进度粘性（停手 4 秒不掉）。
- 目标轨道：指定 → 发射全进该轨；再点取消；越界拒绝；目标满回落最空；
  点面板轨道环能设 / 取消（命中与绘制同坐标）；点行星仍切换。
- 存档：`target_orbit` 往返一致；老档缺字段默认自动。
- 全屏形态：4 尺寸（800×600~1920×1080）rect 铺满、星空铺底、顶部渐变、
  「返回地图」与 ESC 都能退回地表（探针 `BAD: none`）。

**边界**：
- 进度条只响应"缩到最小之后"的继续缩小，普通缩放不影响。
- 目标轨道是全局一个（所有发射器共用），不做每台独立目标。
- 星系视图是**全屏界面**（`Game._draw` 打开时直接整屏切走，不画地表/UI、
  不画遮罩/窗口边框、不能拖动窗口）——但**每帧必须照常 `display.flip()`**：
  早期实现早退时漏了翻页，导致"进入视图后整屏冻住、点什么都没反应、
  toast 也不消失"。缩放衔接触发的是界面开关，不是连续缩放渲染层。
- 没有"星系视图里手动拖太阳帆"，帆仍靠发射器自动打。

**测试**：新自检 `_viewcheck.py`（8 段），全套 **24 项全绿**。

---

## 48. 真电网（M9，**已实现**）：电力塔分区 + 逐网供电比 + 真实电力单位

**问题**（TechDebt #1）：整张 512×512 只有一张网——左上角的太阳能板给右下角的
熔炉供电，中间一根线都不用连；数字还是"抽象电"（核心 8、制造台 2）。

**改法**：
- **电力单位**：`POWER_GEN/POWER_USAGE` 全部改成 **kW**（旧抽象单位 ×20：
  制造台 40 kW、太阳能 60 kW、核心 160 kW、行星引擎 800 kW；戴森帆 240 kW）；
  新增 `fmt_power()`，≥1000 kW 显示为 MW。`POWER_LEGACY_SCALE=20` 用于 mod 旧数值。
- **电力塔**（新建筑 16 / 物品 115 / 配方 3 铁板+4 铜线）：1×1，无耗电。
- **分区**：`PowerGrid.rebuild()` 收集所有电力节点（发电/耗电/分拣器叠加层/
  电力塔），**距离 ≤ POWER_LINK_RANGE=8 格即并网**，并查集求连通分量；
  每个网独立算 gen/demand/ratio。`factor_at(x,y)` 给机器/科研站/发射器/行星引擎
  取各自网的供电比。
- **全局电**：戴森云与旧 mod 注电按各网需求比例摊派；无负载的网不占电。
- **一律分区（M14b 修正）**：~~全图一根电力塔都没有时退回旧全球电网~~ 已废除。
  现在即使一根塔都没有，8 格内的电力节点就并网、超了就分网；想跨远必须铺塔。
  读档时若发现"有负载却没发电"的网，会提示「N 张网缺电（共 M 张），用电力塔并过来」。
- **旧 API**：`power.last_supply += x`（gregtech_extra 的聚变注电）仍可用，
  setter 把增量按 ×20 换算进全局注电。
- **存档**：塔走 grid 数字 id，无需新字段。

**数值/行为验证**（`_powercheck`，第 25 项自检）：
- 制造台 40 kW / 太阳能 60 kW / 核心 160 kW；`fmt_power` 输出 "40 kW"/"1.50 MW"。
- 无塔也分区：孤零零一台制造台因子 0；旁边 3 格风车自动并网 → 1.0；
  30 格外的制造台另成一网且缺电 → 0；`starved_nets()` 报得出缺电网。
- 插塔后 A（风+制造台）比 1.0，远端 B（只有制造台）比 0.0，两张网不互相借电；
  把塔挪到 8 格内后网数 -1、两网合并。
- 戴森云 400 kW 摊到两张各 40 kW 需求的网 → 两边都 1.0。
- 分拣器叠加层计入需求（+4 kW）；有电制造台 progress 0.30、没电的 0.00。
- mod 建筑 5 旧单位 → 100 kW；存档往返后电网因子与塔都在。
- HUD 文本带 kW/MW 与网数。

**剩余边界**：
- 并网靠"8 格内相邻"，不是真正的拉线/连线图；建筑可以链式接电（每跳 ≤8 格）。
- 没有电池/储能，也没有电网优先级与手动开关。
- 核心 160 kW 仍是"节点"，靠 8 格邻接供电（不再全图无线）。
- 传送带/采矿机速度仍用**全局**比例（粗粒度；只有机器/科研/发射器/引擎逐网）。

**测试**：新自检 `_powercheck.py`（10 段），全套 **25 项自检全绿**。

---

## 49. 分拣器三段式机械臂（M10，**已实现**）：头 / 连接部 / 尾，纯视觉

**问题**：分拣器一直是一个半透明黄块 + 箭头，看不出机械臂在"抓"还是"放"，
和传送带/机器叠在一起时也分不清哪格是源、哪格是目标。

**改法**：
- **静态层**只画一小块底座板（半格、圆角）+ 指向目标的短杆 + 过滤色点，
  **不再铺满整格**，下面的传送带/地面直接透出来。
- **动态层** `Game._draw_inserters()` 每帧画三段：**尾部**（来源格底座+轴）、
  **连接部**（横跨本格到目标格的臂）、**头部**（目标格抓手）；
  抓手位置由 `inserter_hand(src, dst, phase)` 插值。
- **动画**：投递成功时记 `ins.anim = 2×INSERTER_SWING_TIME (0.7s)`、
  `ins.carry = 物品`；去程 0.35s 手从来源摆到目标（带货），回程 0.35s 空手回位。
  **纯视觉**：抓取/投递时序、冷却、存档都不变。
- **机器格不画**：头/尾所在格是机器（非空且非传送带）时该段隐藏
  （`arm_part_hidden`），避免机械臂压在熔炉/制造台贴图上。
- 缩放 <6px/格时省略动态臂，只留底座板，保证小地图不糊。

**边界**：
- **不改放置规则**：分拣器仍是 1 格 overlay，头/尾不占格、不挡机器/传送带；
  "占空间"只是视觉上跨三格。
- 不新增存档字段；读旧档后臂直接按现有 overlay_dir 重画。
- 动画只是回放，不产生延迟投递（不会因为动画丢物品/降吞吐）。

**测试**：`_insertercheck` 新增 [14]~[19]（手部插值/越界钳制、空/带不遮、
机器隐藏、投递后动画状态、半程到位、整程清理、三种缩放下渲染非空），
全套 **25 项自检全绿**。

---

## 50. mod 单文件分发 .slmmod（M12，**已实现**）

**问题**：目录 mod 分发（zip 目录）对"自带 Python 依赖库"的 mod 很痛苦——
纯 py 依赖要手动塞进 mods 目录、需编译的 C 扩展依赖直接没路（手机端装不了）。

**实现**（详见 Roadmap M12 与 ModDev 9.1）：
- 自创格式：8 字节魔数 `SLMMOD\x01` + ZIP（`manifest.json` 首位：api 版本、
  逐文件 sha256、`libs`/`libs_src` 声明）；打包 CLI `tools/pack_mod.py`。
- 加载：`mods/*.slmmod` 验签（魔数/API/全文件 hash，拒 `../` 穿越与未声明
  成员）→ 解压 `mods/_cache/<名>__<版>__<hash8>/`（hash 缓存，换版自动
  重解、旧缓存自动清理）→ 纯 py 依赖进 `_lib/` 挂 sys.path → 需编译源码
  首次自动 `pip install --no-index --no-deps --no-build-isolation
  --target _lib`，无 pip 兜底 `setup.py build_ext --inplace`；失败只记
  failed，其余 mod 照常；**游戏全程不联网**。
- 规则：同名目录 mod 优先；`.disabled`/用户配置不动；`API_VERSION` 门禁；
  `ctx.resource()`/`ctx.mod_dir`。
- **顺带修复**：渲染层 `_draw_tower`/`_draw_lab`/`_draw_launch_pad`/
  `_draw_planet_engine` 四个贴图方法此前被误删（塔/实验台/发射台/引擎的
  chunk 渲染必崩 AttributeError），按原风格补回；塔/引擎保持 3×3 大图。

**测试**：`tools/_packcheck.py` 7 段（打包加载/缓存命中/卸载清理/篡改拒载/
路径穿越拒绝/同名目录优先/真实 pip 编译），全套 **26 项自检全绿**
（29 个 check 脚本，含顺带恢复的 jade 渲染冒烟）。

---

## 51. 启动加载界面 + mod 拆文件入口（M13，**已实现**）

**问题**：启动时 `Game(...)` 一把梭：字体、世界生成、面板、mod 全部闷头跑，
低端机上黑屏好几秒；mod 也只能一个 main.py，补丁多了难维护。

**实现**（详见 Roadmap M13 与 ModDev §2）：
- `ui/loading.py::LoadingScreen`：大步骤进度条（6 格）+ 当前加载项 +
  子进度条；每步 flip + pump 事件防 ANR；QUIT 可退。
- `Game.__init__` 拆 6 个 `_stage()`，可选注入 loader（None = 静默，
  自检/headless 零影响）；入口改 `core/bootstrap.py::create_game`。
- `load_mods(progress=cb)` 逐 mod 回调 `(名字, 第几个, 总数)`。
- mod.json 新字段：`"main"`（自定义入口，缺失即 failed）与
  `"mixins"`（mixin 文件列表，全部先于 main 加载，@Mixin 自动收集；
  缺失/路径穿越拒绝）——目录 mod 与 .slmmod 通用。

**测试**：`tools/_loadingcheck.py` 7 段，全套 **27 项自检全绿**（30 个脚本）。

---

## 52. 显示类自检在无 Activity 环境全废（M13.1，**已解决**）

**问题**：Pydroid 的 SDL2 是定制版，`pygame.display.set_mode()` 必须挂 Android
Activity 的 JNI 上下文。在 adb shell / Linux 沙箱 / CI 里跑自检，13 个显示类脚本
一律报 `Application didn't initialize properly, did you include SDL_main.h...`。
`SDL_VIDEODRIVER=dummy/offscreen/software` 全都绕不过（试过）。而新版最核心的
成果——分层、多行星、星际物流、MOD、电网、视图——恰恰全在这 13 个里。

**解决**：`tools/_shim_display.py` 垫层（**仅测试用，生产代码不许 import**）。

| 被替换 | 替换为 |
|---|---|
| `display.set_mode` | 返回普通 `pygame.Surface` |
| `display.flip/update` | noop（flip 计数供断言） |
| `display.get_surface` | 上次 set_mode 的 Surface |
| `display.set_caption/icon` | noop |
| `time.Clock` | 确定性假时钟（tick 固定 16ms） |
| `event.get/poll` | `[]` / `None` |
| `key.get_pressed` | 全松开的假按键表（支持下标） |
| `mouse.get_pos/get_pressed` | `(0,0)` / `(0,0,0)` |

**实测**：Pydroid python3.11.4 + pygame 2.5.0，**33 个脚本全 PASS，0 FAIL**。

**顺带还掉的真实 bug**：`mods/新建文本文档.slmmod` 0 字节垃圾文件被 mod 扫描器
当包加载，`_gt_modcheck` / `_gt_extracheck` 各挂 1 项。删除后全绿。

**局限**：垫层测不出真窗口相关的一切（实际窗口尺寸、缩放后画面、触摸坐标 →
屏幕像素映射）。发版前必须在 Pydroid App 内实跑一次。

---

## 53. 液体系统（M14a，**已实现**）：每格独立液量 + 压差限速 + 泵

**设计取舍**：计划里原本想"整段瞬时共享"（最简单），用户 8.1 明确否掉——那样长管线
没有代价、泵也没意义。最终模型：**每格自己存液量**（管道 100 / 储罐 2500），相邻格
按压差限速互流（`PIPE_FLOW_RATE=60/s`），所以液体要一格格"渗"过去，压力是真的。

**泵**是唯一能逆压差的装置（300/s、单向、20 kW、断电不搬），也是唯一能sl切断管网的
元件（泵格不是液体格）——想"加压接力"就得铺泵，不铺就只能靠液位差自己流。

**混液**：一格只装一种液体；不同液体相邻时互不流动（不混、不销毁）。合并两段管网
只可能发生在拆泵之后，按"先到先得"保留，另一边溢出（很小概率，可接受）。

**已知简化（记为债）**：
1. **不能桶装**：液体进不了背包、上不了传送带/无人机/飞船 → 星际运液体暂不支持
   （后续可做"储罐 + 运输船"）。
2. **混液不按比例分离**：Factorio 0.15 会把混液按比例分回两条管，这里只靠机器消耗自净。
3. **没有管损/黏度差异**：所有液体同流速，只有颜色和配方不同。
4. **泵的进出口固定为朝向两端**：不支持侧进侧出/多口泵。

**测试**：`tools/_fluidcheck.py` 11 段；全套 **30 项自检全绿**。

---

## 不会还的债

- `main.py` 必须在顶层 `import pygame` 并初始化：Pydroid3 的 SDL 限制，不能懒加载。
- 存档槽位无重命名/缩略图：手机键盘输入不值得做，槽位有"时间+行星+物品数"摘要够认。
- 没有撤销：沙盒游戏可以接受，玩家自己重建。
