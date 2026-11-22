# MOD 开发手册（详细版）

> 快速上手看 [Mods.md](Mods.md)（8 行代码一个 mod）；本文是完整手册：
> 机制原理、API 全参考、sim 指令速查、事件流、mixin 深度、完整示例、排障表。
> 快速入门阶段的数字化要求：`mods/<名字>/mod.json` + `main.py`，两个文件就能跑。

---

## 1. 机制总览

StellarLoom 的 mod 系统（M6.27）由两块拼成：

| 形态 | 做什么 | 机制 |
|---|---|---|
| **A. mixin 补丁** | 修改现有代码行为（改速度、加逻辑、换实现） | 运行时 monkey-patch，只动内存 |
| **B. API 扩展** | 加新内容（物品/配方/钩子/交互） | `stellarloom.api.ModContext` 公开接口 |

共同原则（设计铁律）：

- **非永久**：mixin 和内容注册都只活在内存里。卸载/重载自动还原，
  源码（`stellarloom/` 下的 .py）一个字都不改。
- **失败隔离**：单个 mod 出任何错（清单坏、语法错、on_load 抛异常），
  只影响它自己——记入加载失败列表，游戏继续跑，玩家收到一条提示。
- **确定性**：mod 按目录名字典序加载（`content` 在 `stat_mixin` 前）。
  同一方法被多个 mod patch 时，后加载的包裹在外层、先执行。

### 加载流程（Game 构造时自动执行；M13 起走 bootstrap 分步加载界面）

```
main.py → create_screen() → bootstrap.create_game(screen)
  └─ LoadingScreen（大步骤条：字体/世界生成/渲染视图/界面面板/加载模组/主菜单）
  └─ Game.__init__（6 个 _stage() 分步；mods 阶段逐个 mod 报进度）
       └─ load_mods(progress=cb)      # stellarloom/mod/__init__.py
            └─ 扫描 mods/*/mod.json + mods/*.slmmod（没有 mod.json 的目录跳过）
                 └─ 逐个 _load_one()
                      ├─ 解析 mod.json（坏 → failed，跳过）
                      ├─ 构造 ModContext（注入 game / sim）
                      ├─ import mixins 文件（M13：先于 main，@Mixin 自动收集）
                      ├─ import main（默认 main.py，可用 "main" 改；
                      │   语法错/import 错 → failed，清 sys.modules）
                      └─ 调 on_load(ctx)（抛错 → 回滚该 ctx 已注册的一切 → failed）
```

Game 挂 `self.mod_mgr`（`ModManager`）：`ctxs`（成功列表）、`failed`
（失败列表 [(名字, 错误)]）。`on_step`/`on_event` 由 Game 每帧转发
（只在世界非暂停时；暂停/主菜单时不推进）。

---

## 2. 目录结构与 mod.json

```
mods/
  example_speed_belt/        ← 一个 mod 就是这样一个目录（模板，可复印）
    mod.json                 元数据（必需，文件名固定）
    main.py                  逻辑入口（可选）
    config.json              作者默认配置（可选，M6.29）
    README.md                你的说明（加载器忽略）
mods/config/<名字>.json      用户配置（M6.29，运行时 save_config 写入，
                             独立于 mod 包，卸载不清、重启保持）
mods/.disabled              禁用名单（模组管理页写，一个 mod 名一行）
```

`mod.json` 全字段：

```json
{
  "name": "my_mod",            // 必需，非空。也用于内部模块名（mod_<name>_main）
  "version": "1.0",            // 可选，默认 "0.0"
  "description": "一句话说明",  // 可选，加载日志里显示
  "dependencies": {            // 可选（M6.29）：依赖的其他 mod 名字 → 版本要求
    "gregtech_extra": ">=1.0"  // 版本表达式：>  >=  ==  <  <=；裸数字=精确；
    // "base_mod": ""          // 空串 / 省字段 = 任意版本（只要装了就行）
  },
  "main": "boot.py",           // 可选（M13）：逻辑入口文件，默认 "main.py"；
                               // 显式指定但文件不存在 → 加载失败
  "mixins": ["mx/a.py"]        // 可选（M13）：mixin 文件列表，main 之前逐个加载，
                               // 每个文件顶层代码会执行，@Mixin 类自动收集应用
}
```

**拆文件建议（M13）**：大 mod 建议把 @Mixin 补丁拆到 `mx/` 目录、入口
`main` 只做装配——加载顺序保证 **mixins 全部先于 main 执行**，main 里可以
直接依赖 mixin 文件里定义好的补丁/工具。文件缺失/路径穿越（`../`）会被
拒绝并记入 failed，不影响其它 mod。打包成 `.slmmod` 时这些字段原样生效。

依赖语义（M6.29）：
- 加载按依赖**拓扑序**（依赖者后加载），不再依赖目录名字母排序。
- 缺依赖 / 版本不满足 / 依赖模块加载失败 / 形成依赖环 → 该 mod 记入
  `failed`（模组管理页显示原因），其余 mod 照常加载，游戏不崩。
- 被禁用的 mod 视同"没加载"，依赖它的 mod 会以"缺少依赖"失败。

注意：`name` 里别用空格/中文怪字符——它会拼进 `sys.modules` 的键
（`mod_<name>_main`），虽说不崩，但保持纯字母数字最省心。

---

## 3. 生命周期钩子

`main.py` 可选定义两个钩子：

```python
def on_load(ctx):
    """加载成功、ctx 可用。在这里注册一切。抛异常 = 该 mod 判失败并整体回滚。"""
    ...

def on_unload(ctx):
    """卸载/重载前调用（可选）。mixin 与内容注册的还原由系统自动做，
    这里只处理你自己的外部资源（如临时文件）。"""
    ...
```

几个必须知道的时机细节：

- `main.py` 的**模块级代码会在 import 时执行**——此时 `ctx` 还不存在。
  不要试图在模块级调用 `ctx.*`；模块级只写辅助函数/常量。
- `on_load` 抛错时，该 mod 之前已做的 `ctx.mixin` / `ctx.add_*` 会被全部
  回滚（补丁还原、注册撤销），不残留。
- `load_all()` 每次先 `unload()` 旧的——**重复加载天然幂等**
  （热更新场景：重启游戏或手动 `load_mods()` 再扫一遍即可）。
- 卸载顺序是加载的逆序（后加载的先卸载）。

---

## 4. API 参考（ModContext）

`on_load(ctx)` 拿到的 `ctx` 提供全部能力。逐个全文档：

### 4.1 ctx.log(msg)

带 `[mod <名字>]` 前缀的调试输出，控制台可见。

```python
ctx.log(f"背包物品数: {len(ctx.sim.inventory)}")
```

### 4.2 ctx.toast(text, secs=2.0)

游戏内提示（屏幕中央 toast）。无 UI 环境（headless）自动忽略。

```python
ctx.toast("mod 生效！", 3.0)
```

### 4.3 ctx.sim（属性）

服务器端 `Simulation` 引用（M6.24 分层后**所有逻辑都在 sim**）。
可以读状态，可以调指令 API，但请只走公开方法——直接改内部 dict
（如 `ctx.sim.inventory[1] += 5`）虽然"能跑"，但绕过扣料/上限检查，
存档可能不干净。指令 API 全表见第 5 节。

```python
sim = ctx.sim
print(sim.world_index, len(sim.inventory))
r = sim.place_building(101, 20, 20, 0)   # 101 = 传送带（C.B_BELT）
```

`ctx.sim` 在 `on_load` 里才可用（此前未注入）。

### 4.4 ctx.mixin(target, method, wrapper, wrap="before")

运行时补丁。**全开放**：target 可以是任何可 import 类。

| wrap | wrapper 签名 | 行为 |
|---|---|---|
| `"before"` | `(self, *args, **kw)` | 原方法前跑；返回 `None` 不干预；返回 `(args, kwargs)` **替换调用参数** |
| `"after"` | `(self, result, *args, **kw)` | 原方法后跑；返回 `None` 保留结果；返回其它值**覆盖返回值** |
| `"replace"` | `(self, *args, **kw)` | 全权接管，**不再调用原方法** |

- `target` 用点分路径：`"stellarloom.sim.sim.Simulation"`（模块.类）。
- wrapper 的参数列表必须与目标方法的签名对应（含 `self`；用 `**kw`
  兜底多余关键字参数最稳）。别忘目标方法的每个位置参数——比如
  `Simulation.place_building(self, btype, gx, gy, rot)` 的 after wrapper
  是 `(self, result, btype, gx, gy, rot, **kw)`，少一个就 TypeError。
- 同一方法多 mod 混编：后加载的 wrap 套在外面先执行；卸载逆序还原，
  不会留下半解开的链。
- 常见目标速查（都是真实路径）：

| 想改什么 | target | method |
|---|---|---|
| 放置建筑 | `stellarloom.sim.sim` `.Simulation` | `place_building` |
| 传送带速度 | `stellarloom.logistics.belts` `.BeltNetwork` | `update` |
| 手搓队列推进 | `stellarloom.sim.craft_queue` `.CraftQueue` | `update` |
| 研究推进 | `stellarloom.tech.labs` `.LabNetwork` | `update`（签名以源码为准） |
| 建造/拆除 | `stellarloom.sim.sim` `.Simulation` | `remove_building` |

#### Minecraft 风格（M7 推荐）：@Mixin / @Inject / @Overwrite

不想手搓 wrapper 签名？用注解式，格式照 Minecraft/Fabric 抄：

```python
from stellarloom.api import Mixin, Inject, At, Overwrite, CallbackInfo

@Mixin("stellarloom.sim.sim.Simulation")     # 目标：点分路径或类对象
class SimPatches:
    @Inject(method="place_building", at=At.HEAD, cancellable=True)
    def block_spot(self, btype, gx, gy, rot, cir: CallbackInfo):
        if gx == 77 and gy == 77:
            cir.cancel()                 # 跳过原方法
            cir.set_return("blocked")    # 取消时的返回值

    @Inject(method="place_building", at=At.RETURN)
    def annotate(self, btype, gx, gy, rot, cir):
        if cir.get_return() == "ok":
            cir.set_return("ok_loud")    # 覆盖原返回值

    @Overwrite(method="remove_building")
    def my_remove(self, gx, gy):
        return (False, "no")             # 全权替换原方法
```

规则：
- `@Mixin(目标)` 标在类上；`目标` 是点分路径字符串或类对象（如
  `from stellarloom.sim.sim import Simulation; @Mixin(Simulation)`）。
- 类里的 `@Inject` / `@Overwrite` 方法**加载 main.py 时自动注册**（on_load
  之前生效），不用手动调用；`on_load` 里也可 `ctx.apply_mixin_class(cls)`
  补注册（重复注册自动跳过）。
- `@Inject`：
  - `at=At.HEAD`：进原方法前。`cancellable=True` 时 `cir.cancel()` 跳过
    原方法（返回值用 `cir.set_return(v)` 指定）；改 `cir.args[i]` 可换参。
  - `at=At.RETURN`（或 `At.TAIL`）：原方法正常返回后，读/改
    `cir.return_value`（`cir.get_return()` / `cir.set_return(v)`）。
- 注入函数签名固定 `(self, *原方法位置参数, cir)`——**不接收关键字参数**
  （原方法的 `**kw` 由包装器原样透传给原方法）。`CallbackInfo`
  camelCase 别名齐活：`isCancelled / setReturnValue / getReturnValue`。
- `@Overwrite(method=...)`：签名与原方法一致，全权替换。
- 卸载/重载自动还原全部注入（与函数式 mixin 同一套还原链）；
  写错目标类/方法 → 该 mod 加载失败并显示具体原因，不影响其它 mod。
- **没做的**（往前走一步再补）：`@Redirect / @ModifyArg / @Shadow` 等进阶
  注解——HEAD/RETURN + Overwrite + 换参已覆盖九成改机需求。

### 4.5 ctx.add_item(item, name=None, color=None)（M7 物品注册表）

把一种新物品注册进 **MC 风格注册表**——存档/配方/管理页用名字
（`<你的mod名>:<物品名>`），数字 id 由注册表自动分配，你不用管了。

```python
ctx.add_item("magicmod:magic_ingot", "魔法锭", "#A06040")   # 推荐：名字注册
ctx.add_item("magicmod:magic_bar", "魔法锭条", "#CC88FF")
ctx.add_item(400, "特制煤块", "#BB77FF")                     # 旧式：数字固定段
```

- 第一个参数是**名字**（含 `:`；不带则自动补 `<mod名>:`）；传 **int** 是
  旧式兼容——固定注册为 `<mod名>:item400`，旧存档里的数字 400 可反查。
- 数字 id 是"运行时内部表示"：`ctx.sim.inventory`、机器槽、渲染查色都走它；
  **存档和配方 JSON 用名字**（`stellarloom:iron_ore`），mod 卸载后字典里
  不残留数字。
- 名字/固定 id 撞车 → 拒绝并让该 mod 失败（`add_item` 两次同物品 =
  mod bug）。
- `color` 只接受 `"#RRGGBB"` 或 `"#RRGGBBAA"`；不给颜色 → 默认灰。
- 注册后手搓/机器面板看到物品名（`C.ITEM_NAMES` 实时视图，UI 零改动）；
  **不进底栏分类**（CATEGORIES 静态），展示侧暂缺。

### 4.6 ctx.add_recipe(rid, inputs, outputs, dur, machines=())

注册配方，**手搓面板和机器面板自动可见**。内置 23 条配方在
`stellarloom/data/recipes.json`（M7 起用名字存储，启动加载），格式与此
完全一致——mod 注入的是同一个 `C.RECIPES` dict，玩家配方与内置配方同源。

```python
ctx.add_recipe("magic_bar",
               inputs={"magicmod:magic_ingot": 2, "stellarloom:iron_plate": 1},
               outputs={"magicmod:magic_bar": 1},   # 原料/产物支持名字或数字
               dur=1.0,                             # 单件耗时（秒）
               machines=())                         # 可选：能造的机器 id 元组
```

- `rid` 是配方 id（字符串），冲突拒绝。
- 原料/产物键 = 物品**名字**（`命名空间:名`）或数字（兼容老写法）；
  所有物品必须先 `add_item` 注册，否则拒绝。
- `machines` 示例：`(C.B_FURNACE,)` = 只有熔炉能造（机器面板过滤用）；
  空元组 = 只提示手搓（自动化的"该配方可用于 XXX"提示不显示）。
  `C.B_ASSEMBLER`/`C.B_LAB` 等建筑 id 可用；M8 起也能写建筑**名字**
  （`("mymod:foundry",)`，你注册的建筑直接可当机器）。引用未注册建筑 → 拒绝。
- 配方存的是 4 元组 `(原料, 产物, 耗时, machines)`——与内置配方同格式，
  别改字段数（`craft_panel` 依赖解包 4 个）。

### 4.7 ctx.add_building(btype, name=None, item=None)（M8 建筑注册表）

把一种**建筑类型**注册进建筑注册表（M8）：名字 ↔ 数字 id，返回数字 id
（放在网格数组 / mixin 里当 btype 用）。

```python
foundry = ctx.add_building("mymod:foundry", "铸造厂")     # 名字注册，id ≥100
old = ctx.add_building(90, "老式机器")                     # 旧式：固定 id 兼容
ctx.add_building("mymod:smelter", "熔炼塔",
                 item="mymod:foundry_kit")                # 联动建筑物品
```

- 第一个参数是**名字**（含 `:`；不带则补 `<mod名>:`）→ 动态分配数字 id
  （从 100 起，避开原版 1-15 与存量 mod 硬编码段 20-23/30-37）；传 int
  是旧式兼容——固定注册为 `<mod名>:b<id>`（给存量硬编码段登记显示名）。
- `item=` 传对应的**建筑物品**（名字或数字）→ 自动注册
  `BUILD_ITEM[btype]` 联动：底栏取物 / 放置消耗 / 拆除返还直接生效。
- `BUILDING_NAMES` 是注册表实时视图——注册后 UI 立刻显示你的建筑名。
- **存量 mod（gregtech_*）硬编码的建筑数字不进注册表、照常运行**；
  想把它们也显示成中文名，用 `add_building(30, "聚变反应堆")` 登记即可
  （固定段注册，值不变）。

### 4.7b 电力（M9 真电网，单位 kW）

- `C.POWER_USAGE[btype]` / `C.POWER_GEN[btype]` 的值是 **kW**（原版：制造台 40、
  太阳能 60、核心 160）。**mod 注册的值按旧抽象单位处理，运行时自动 ×20**
  （`POWER_LEGACY_SCALE`），所以存量 mod 的数值不用改。
- 电网按连通分区：电力塔（原版建筑 16）和电力节点在 **8 格内**并网，
  `power.factor_at(x, y)` 返回该格所在网的供电比（0~1）；机器/科研站/发射器
  已经逐网取比例，mod 自己的建筑若要限速，用它即可。
- 旧写法 `power.last_supply += 注电` 仍兼容：增量按 ×20 记成**全局注电**，
  再按各网需求比例摊派（gregtech_extra 的聚变反应堆就是这么接的）。
- **一律分区**（M14b）：没有"没铺电力塔就全球一张网"的兜底了。8 格内自动并网、
  超了分网，想跨远必须铺电力塔。写自检时若要绕开电网拓扑（测配方/机器而已），
  用官方测试钩子 `sim.power.force_ratio = 1.0`。

### 4.8 ctx.cfg / cfg_get / cfg_set / save_config（M6.29 统一配置）

**数据流**：加载时 = 作者 `config.json`（默认）⊕ 用户 `mods/config/<名字>.json`
（用户覆盖作者）→ 合并结果就是 `ctx.cfg`。on_load 里即可读；改动不自动
落盘，要保存就显式调 `save_config()`。

```python
# 读取（三种等价的读法）
speed = ctx.cfg_get("belt_speed", 1.0)     # 有默认值的读
speed = ctx.cfg.get("belt_speed", 1.0)     # 直接 dict 读
boost = ctx.cfg["boost"]                   # 直接下标读

# 修改
ctx.cfg_set("boost", 2.5)                  # 或 ctx.cfg["boost"] = 2.5

# 保存到 mods/config/<名字>.json（用户配置，重启保持）
ctx.save_config()
```

- `ctx.cfg` 返回**运行时合并 dict**（可读可改）；`save_config` 把整个写盘。
- 作者默认值放 mod 包内 `config.json`（随 mod 分发，模板值）；**别让玩家改
  它**——玩家改动全走 `mods/config/<名字>.json`，作者默认保持只读参照。
- `save_config` 对非 JSON 类型（tuple/set/任意对象）自动容错转字符串，
  不会炸。
- 模组管理页右栏会显示"配置"状态（作者默认有无 / 用户配置是否已保存）。
- 卸载 / 重载**不清除**用户配置；想重置某个 mod 配置，删掉
  `mods/config/<名字>.json` 即可回到作者默认。

### 4.9 ctx.on_step(fn) / ctx.on_event(fn)

```python
def tick(dt):
    pass                      # 每服务器步进调一次，dt 秒
ctx.on_step(tick)

def on_ev(ev):
    kind, *payload = ev       # ev = ("toast", "文字", 2.0) 之类
    pass
ctx.on_event(on_ev)
```

- `on_step` 只在世界推进时触发（暂停、主菜单时不调）。**别在里面干重活**
  ——每帧跑，攒着不如在 mixin 里做批量逻辑。
- `on_event` 收到的是 sim 事件流单条（kind 清单见第 6 节）。

### 4.9b 液体（M14）

液体是**独立 id 段**（0 = 空），不进背包、不上传送带、不进分拣器过滤列表。

```python
fid = ctx.add_fluid("mymod:sludge", "淤泥", "#556644")   # → 数字 id

# 纯液体配方：原料/产物字典留空，液体用名字 + 数量（float）
ctx.add_recipe("mymod:distill", {}, {}, 2.0, machines=(C.B_ASSEMBLER,),
               fluid_inputs={"mymod:sludge": 10.0},
               fluid_outputs={"stellarloom:petroleum": 5.0})

# 混搭（物品 + 液体同一条配方）
ctx.add_recipe("mymod:resin", {"stellarloom:stone": 2},
               {"stellarloom:gear": 1}, 3.0, machines=(C.B_ASSEMBLER,),
               fluid_inputs={"stellarloom:petroleum": 20.0})
```

- 机器**自动接管道**：四邻里只要有管道/储液罐，就按 `FLUID_MACHINE_DRAW=30/s`
  抽原料液、按 `FLUID_MACHINE_PUSH=30/s` 排产物液；内部每种液体上限
  `MACHINE_FLUID_CAP=100`。不需要分拣器，也不需要额外"液体入口"建筑。
- 液体量是 **float**（不是整数个数）；`C.FLUID_NAMES` / `C.FLUID_COLORS` 是运行时视图。
- 管网规则（玩家侧一致）：一格一种液体，不同液体互不流动；泵是无视压差的单向加压器。
- `ctx.sim.fluid_at(x, y) -> (fid, 量, 容量)`，`ctx.sim.pipes` 是完整 `FluidNetwork`
  （`amount_at` / `fid_at` / `total_of(fid)` / `fill_at` 都能调）。
- `recipes.json` 也支持同样的字段：`"fluid_inputs": {"stellarloom:crude_oil": 100}`。

### 4.10 卸载时自动发生的事

- 所有 `mixin` 补丁逆序还原为原方法。
- 所有 `add_item` / `add_recipe` / **`add_fluid`** 注册被撤销（只清自己注册的）。
- **例外**：存档里已存在的 mod 物品 id 不会被抹掉——读回旧档后该 id
  显示为 "?"。这是"内容注册随卸载撤、存档数据永远在"的设计取舍。

---

## 5. sim 指令 API 速查（ctx.sim 上可调）

| 方法 | 签名 | 返回 | 说明 |
|---|---|---|---|
| `step` | `(dt)` | — | 推进一帧模拟（mod 一般不需要直接调） |
| `place_building` | `(btype, gx, gy, direction=0)` | `"ok" / "locked" / "no_place" / "no_item"` | 放单格建筑（含扣料、科技锁校验、网络 sync） |
| `place_tower` | `(btype, gx, gy, direction=0)` | 同上（`"no_place"` 时含 3×3 范围） | 放物流塔（3×3，记中心格） |
| `lay_belt_line` | `(sx, sy, ex, ey, last_dir=0)` | `bool` | 铺 L 形传送带，中途缺料止步 |
| `place_inserter` | `(mx, my, d)` | `str` | 放分拣器（叠在传送带上的 overlay） |
| `set_overlay_filter` | `(gx, gy, choice)` | — | 设分拣器过滤（0 = 不限） |
| `remove_building` | `(gx, gy)` | `(bool, 退还物品id或None)` | 拆建筑并退料 |
| `do_craft` | `(rid, times)` | `int`（实际排进队列数） | 手搓排队（材料当场扣） |
| `cancel_craft` | `()` | — | 取消手搓当前任务 |
| `switch_planet` | `(i)` | — | 切行星（前端相机跟随由 Game 管） |
| `ensure_world` / `activate_world` | `(i)` | — | 多行星内部操作，一般用不到 |
| `pop_events` / `take_dirty_cells` | `()` | 列表 | 事件流 / 脏格（Game 消费，mod 用第 6 节钩子即可） |
| `subscribe_events(fn)` / `subscribe_dirty(fn)` | `(fn)` | 取消函数 | M15a：旁路订阅（联机层用，不抢本地队列） |
| `with_world(i)` | `(i)` | 上下文管理器 | M15a：临时切行星执行指令，退出还原 |
| `set_machine_recipe` | `(gx, gy, rid 或 None)` | `"ok"/"no_machine"/"no_recipe"/"locked"` | 设机器配方（校验机型+科技） |
| `machine_take_input` / `machine_add_input` | `(gx, gy, item, count=None)` | `int` | 机器原料槽取/放（放料自动扣背包） |
| `machine_take_outputs` | `(gx, gy)` | `dict[int,int]` | 取机器全部产物到背包 |
| `container_at` | `(gx, gy)` | `(kind, obj)` | 该格容器：chest/miner/emitter |
| `container_take` / `container_put` | `(gx, gy, item, count=None)` | `int` | 箱子/采矿机/发射器统一取放 |
| `lab_set_mode` / `lab_set_recipe` | `(gx, gy, mode/rid)` | `str` | 科研站模式/配方 |
| `lab_take_item` / `lab_add_item` / `lab_take_outputs` | `(gx, gy, …)` | `int` / `dict` | 科研站取放 |
| `set_tower_filter` | `(gx, gy, item 或 None)` | `str` | 塔过滤 |
| `start_research` | `(tech_id)` | `(bool, str)` | 排研究队列（can_queue 语义，允许预排） |

**M15a 铁律**：任何改变游戏状态的操作都必须经过 `sim` 指令。UI 面板已全部改走指令
（`_cmdcheck` 会静态扫描 `stellarloom/ui/*.py` 拦截回退），联机时把面板的 `sim` 换成
远程代理即可，面板代码零改动。

只读速查：`sim.inventory`（dict int→int，**同源引用**，M6.26 后读档也保同源）、
`sim.tech` / `sim.dyson` / `sim.worlds` / `sim.craft` / `sim.world_index`；
世界内 `sim.worlds[i].grid`（`get(x,y)` 查格子）、`machines`/`miners`/`chests`/
`labs`/`towers` 各网络（M6.24 同源状态对象）。查询随意、改写谨慎（走指令）。

---

## 6. 事件流（on_event 收到什么）

当前 sim 会 `emit` 的全部 kind（`on_event` 的 `ev` 首元素）：

| kind | payload | 触发时机 |
|---|---|---|
| `"toast"` | `(text: str, secs: float)` | 手搓完成、材料不足等提示 |
| `"achievement"` | `(title: str, desc: str)` | 研究完成等成就 |

想看更多粒度的事件（比如"建筑被放置"），mixin `after place_building`
照样能拿到，不用等框架加事件——全开放的意义就在这。

---

## 7. 完整示例：加一种"幻想锭"

```python
# mods/magic_bar/main.py
def on_load(ctx):
    ctx.toast("幻想锭 mod 已加载", 2.0)

    # 1) 新物品：幻想锭 + 它的原料特制煤块
    ctx.add_item(1001, "特制煤块", "#A06040")
    ctx.add_item(1002, "幻想锭",   "#C0A8FF")

    # 2) 配方：2 煤块 → 1 锭（手搓 1.5 秒；熔炉也能自动化）
    ctx.add_recipe("magic_ingot",
                   inputs={1001: 2}, outputs={1002: 1},
                   dur=1.5, machines=(104,))     # 104 = C.B_FURNACE

    # 3) 开局送 10 个煤块当见面礼（走指令怕没有对应 API——
    #    直接改背包同源 dict 是可接受的 mod 行为，注明即可）
    sim = ctx.sim
    sim.inventory[1001] = sim.inventory.get(1001, 0) + 10

    # 4) 想顺手动"行为"（做提速、加限制、改掉落）就用 mixin：
    #    target/method 速查见第 4.4 节表格；完整可跑的 mixin 示例
    #    看 mods/example_speed_belt/（传送带双倍速，before 换 dt 参数）。

def on_unload(ctx):
    ctx.toast("幻想锭 mod 已卸载", 2.0)
```

对照检查：`do_craft("magic_ingot", 1)` 可排队；背包显示"特制煤块 ×10"；
熔炉面板列出配方"特制煤块 ×2 → 幻想锭 ×1"。

---

## 8. 调试与排障

### 8.1 怎么看加载情况

- 控制台：`[mod] 加载 <name> v1.0 —— <desc>` 成功、`[mod] 加载失败 ...`。
- 游戏内：失败会 toast（`mod <x> 加载失败：...`）。
- 代码里：`game.mod_mgr.ctxs` / `game.mod_mgr.failed`。

### 8.2 常见错误对照表

| 症状 | 原因 | 修法 |
|---|---|---|
| `mixin target 无法 import: ...` | target 的模块路径拼错 | 用 `pydoc`/importlib 试；路径必须是可 import 的模块.类 |
| `TypeError: wrapper() takes N positional arguments but M were given` | wrapper 参数没对全目标方法签名 | 数清目标方法的参数 + `self`（after 还要加 `result`）|
| `mod.json 缺 name` | 清单不完整 | 补 `"name"` |
| 二次加载"成功"但逻辑没变 | 上一轮 import 失败残留半成品模块 | 重启；新代码已自动清理（加载器卸载时清 `sys.modules` 半成品） |
| `add_item: id 300 已被占用` | 撞了内置/别的 mod 的 id | 换 1000+ 段 |
| `add_recipe: 物品 X 未注册` | 配方引用未注册物品 | 先 `add_item` 再 `add_recipe` |
| 面板没显示新配方 | 手搓/机器面板的目录在构造时建 | 重启游戏（热更新未支持）|
| 存档里 mod 物品显示 "?" | 卸载了注册该物品的 mod | 预期行为：换回 mod 或接受残留 |

### 8.3 性能纪律

- `on_step` 每帧跑：内部别做 O(格数) 的全图扫描。
- mixin 只包住目标方法，别在 wrapper 里写每格循环。
- 实测参考：belt update 是全 lanes 向量化（numpy），你的 wrapper 挤在它
  外层做成 Python 循环会把 60fps 拖到个位数——批量操作留给 sim 内部。

---

## 9. 发布与分发

- 整个 `mods/<名字>/` 目录打包 zip 即可（config.json 默认配置可一起带上）。
- 接收方解压到项目根 `mods/`（保留目录名）→ 重启游戏。
- `version` 字段用于识别；若依赖别的 mod，在 `mod.json` 写 `dependencies`
  （见第 2 节）——接收方缺依赖/版本不符时该 mod 会自动失败并在模组管理页
  显示原因，不会带病运行。

### 9.1 单文件分发（M12，`.slmmod`）

打包成**一个自创格式单文件**，接收方丢进 `mods/` 即自动识别加载：

```bash
python tools/pack_mod.py mods/my_mod -o my_mod.slmmod \
    --lib path/to/purepy_lib \          # 纯 Python 依赖（目录/.whl/.py）
    --lib-src path/to/src-1.0.tar.gz    # 需编译依赖的源码包（可多次）
```

格式：8 字节魔数 `SLMMOD\x01` + ZIP（内部 `manifest.json` 首位），含：
`api` 版本门禁、逐文件 sha256 清单、`libs`/`libs_src` 依赖声明。
游戏启动扫描 `mods/*.slmmod` → 验签 → 解压到 `mods/_cache/<名>__<版>__<hash8>/`
→ 装依赖 → 走和目录 mod 完全相同的加载器。

**依赖规则（重要）**：
- 纯 Python 依赖直接放包内 `libs/`，运行时解进 `_lib/` 自动挂 sys.path。
- 需编译依赖**只放源码** `libs_src/*.tar.gz`；首次加载自动
  `pip install --no-index --no-deps --no-build-isolation --target <_lib>`
  本地编译（无 pip 兜底 `setup.py build_ext --inplace`），产物缓存复用；
  失败只让该 mod 进 failed，其余照常。
- **游戏不联网**：依赖必须包内自带；声明依赖游戏内置库（如 numpy）只做
  版本比对，版本不够就加载失败并提示。
- 包内读资源：`ctx.resource("icon.png")`（resources/ 下）；
  `ctx.mod_dir` 可拿解压目录路径。

**边界规则**：同名目录 mod（`mods/<名字>/`）优先于同名包；用户在
`mods/.disabled` 与 `mods/config/` 的配置不受包影响；`mods/_cache/` 是
游戏维护的缓存（不要手改）。打包自检：`python tools/pack_mod.py <src>
-o x.slmmod --check`。

## 10. 现状边界（诚实清单）

- 依赖按 mod.json 的 **name** 匹配（不是目录名）——改名即断链；版本只做
  数值段比较（`1.0.0-alpha` 按 1.0.0 比）；被禁用的 mod 视同没加载，依赖者
  以"缺少依赖"失败。
- 配置无热重载：`ctx.cfg` 在 on_load 时合并定型，运行中改要自己
  `save_config()` + 自己决定生效时机；模组管理页只显示配置状态，没有编辑
  控件（改配置 = 手改 `mods/config/<名字>.json` 或让 mod 自己做 UI）。
- 热重载：没有运行中重扫；改代码要重启游戏（`load_mods()` 可手动重载）。
- headless 不加载 mod（`stellarloom.sim.headless` 只管模拟）。
- 内容注册不进底栏 CATEGORIES 分类。
- mixin 全开放 = 无沙盒：mod 能 patch `savefile`/`config` 等任何模块，
  包括把自己搞崩溃的姿势；加载器只保证"单 mod 崩溃不影响游戏"，不保证
  "mod 干坏事游戏还健康"。真实世界 mod 分发请自担风险书。