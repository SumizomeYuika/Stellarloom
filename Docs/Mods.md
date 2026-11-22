# MOD 开发指南（M6.27）

> 这是快速入门（8 行代码一个 mod）。完整手册（机制原理 / API 全参考 / sim
> 指令速查 / 事件流 / mixin 深度 / 排障表）见 **[ModDev.md](ModDev.md)**。

mod = 一个放在 `mods/<名字>/` 的目录，启动时自动加载
（Game 构造时扫描；失败隔离——单个 mod 坏了只提示，不影响游戏）。

M6.29 起还支持：
- **配置**：mod 包内 `config.json` 是作者默认；运行期 `ctx.cfg` 读写、
  `ctx.save_config()` 把用户配置存到 `mods/config/<名字>.json`（重启保持）。
- **依赖**：`mod.json` 里写 `"dependencies": {"别的mod名字": ">=1.0"}`，
  按依赖顺序加载；缺依赖/版本不满足/依赖环 → 该 mod 加载失败并显示原因。

M7 起 mixin 支持 **Minecraft 风格注解**：`@Mixin(目标类)` + `@Inject(method=...,
at="HEAD"/"RETURN", cancellable=True)` + `@Overwrite(method=...)`，回调收
`cir: CallbackInfo`（`cir.cancel()` / `cir.set_return(v)` / `cir.return_value`）。
详细见 ModDev.md 4.4。

M7 物品走 **MC 风格注册表**：`ctx.add_item("mod名:物品名", ...)` 名字注册、
数字 id 启动时动态分配；存档/配方 JSON 全部存 `命名空间:名字`
（原版命名空间 `stellarloom:`）。旧式数字 `add_item(300, ...)` 仍兼容。
详细见 ModDev.md 4.5/4.6。

M8 建筑走**建筑注册表**：`ctx.add_building("mod名:建筑名", "显示名",
item="mod名:建筑物品名")` 注册建筑类型（数字 id 动态分配 ≥100，避开
存量 mod 硬编码段），`BUILD_ITEM` 联动自动生效；配方 `machines` 可写
建筑名字。旧式 `add_building(数字, ...)` 仍兼容。详细见 ModDev.md 4.7。

## 目录结构

```
mods/my_mod/
  mod.json      元数据（必须有 name；可选 version/description/dependencies）
  main.py       逻辑入口（可选；可定义 on_load / on_unload）
  config.json   作者默认配置（可选，M6.29）
```

`mod.json`：

```json
{
  "name": "my_mod",
  "version": "1.0",
  "description": "加一种新锭"
}
```

## ctx 能力一览（main.py 的 on_load(ctx) 里用）

```python
def on_load(ctx):
    # --- 交互 ---
    ctx.log("启动")                 # 带 [mod 名字] 前缀的调试输出
    ctx.toast("mod 已加载", 2.0)    # 游戏内提示

    # --- 服务器访问（M6.24 分层后一切逻辑都在 sim） ---
    sim = ctx.sim                   # Simulation：只读查询 + 指令 API
    sim.place_building(101, 20, 20, 0)     # 放传送带
    print(sim._count(5))                     # 查询（下划线是私有，mod 自己负责）

    # --- mixin：运行时补丁（非永久，卸载/重载自动还原） ---
    def before_place(self, btype, gx, gy, rot, **kw):
        return None                # 返回 (args, kwargs) 可替换调用参数
    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              before_place, wrap="before")

    def after_place(self, result, btype, gx, gy, rot, **kw):
        return result              # 返回非 None 覆盖返回值
    ctx.mixin("stellarloom.sim.sim.Simulation", "place_building",
              after_place, wrap="after")

    def replace_update(self, dt):
        pass                       # replace：全权接管，不再调原方法
    ctx.mixin("stellarloom.sim.craft_queue.CraftQueue", "update",
              replace_update, wrap="replace")

    # --- 内容扩展 ---
    ctx.add_item(300, "特制煤块", "#A06040")          # id 冲突会拒绝
    ctx.add_recipe("magic_bar", {300: 2}, {301: 1}, 1.0,
                   machines=(102,))                   # machines=可造机器建筑 id，空=只有手搓
    # 注册后手搓面板/机器面板自动可见（配方是 4 元组格式）

    # --- 钩子 ---
    def on_step(dt): ...
    def on_event(ev): ...          # ev = (kind, *payload)，如 ("toast", "文字", 2.0)
    ctx.on_step(on_step)
    ctx.on_event(on_event)

def on_unload(ctx):
    pass   # 卸载时调用；mixin 与内容注册的撤销由系统自动完成
```

## wrap 语义速记

| wrap | wrapper 签名 | 说明 |
|---|---|---|
| before | `(self, *args, **kw)` | 原方法前跑；返回 `(args, kwargs)` 可替换参数，`None` 不干预 |
| after  | `(self, result, *args, **kw)` | 原方法后跑；返回非 None 覆盖返回值 |
| replace| `(self, *args, **kw)` | 全权接管，不再调用原方法 |

wrapper 与目标方法的参数一一对应（target 的方法是什么签名就用什么签名）。

## 注意事项

- mixin 目标用点分路径（`模块.类` → `stellarloom.sim.sim.Simulation`）；
  目标类的模块必须能被 import（游戏里的类都可以）。
- M6.27 的 mixin 是**全开放**模式：可以动任何类。改坏了它自己负责——
  加载器只保证单 mod 崩溃不影响游戏（on_load 抛错 → 该 mod 判失败并回滚）。
- 内容注册（物品/配方）随卸载撤销；**存档里的 mod 物品 id 不会**——
  卸载 mod 后旧档里对应 id 会显示为 "?"（mod 物品建议用 1000+ 的自定义 id 段）。
- 存档版本不含 mod 信息；读档时 mod 物品以 int id 存，与 mod 是否在场无关。
- Pydroid3：把 mod 目录放进项目根 `mods/` 即可，无需配置。

## 开箱示例

`mods/example_speed_belt/` —— 传送带双倍速 mod（8 行代码 + 教学 README）。
复制该目录改个名字就是自己的第一个 mod：它演示了 mixin before 的
"替换调用参数"用法——`BeltNetwork.update` 第一行 `speed = C.BELT_SPEED * dt`，
把 `dt` 翻倍即可整体提速，卸载自动还原。