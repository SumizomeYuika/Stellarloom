# 星织：无尽沙盒 · StellarLoom-PG

2D 开放沙盒自动化工厂。Python 3.11 + pygame + numpy。目标平台：Pydroid3（Android）。

## 跑起来

```bash
pip install -r requirements.txt
python main.py
```

## 操作

**触屏**：

| 手势 | 作用 |
|---|---|
| 单指点按 | 放置建筑 / 拆除模式下拆除 |
| 单指拖拽 | 移动相机 |
| 双指捏合 | 缩放 |
| 底栏（10 格） | 选建筑；点已选的建筑 = 取消选择 |
| 顶栏右起 | 暂停 / 方向 / 拆除 / 查看 / 科技 / 轨道 / 存 / 读 / 菜单（存、读打开多存档面板；菜单回主菜单） |

查看模式下点按不放建筑，只开塔面板。

**键鼠**：

| 键 | 作用 |
|---|---|
| WASD / 方向键 | 平移相机 |
| 滚轮 | 缩放 |
| 1-0 | 选建筑（0 = 科研站）|
| R | 旋转方向 |
| 左键 | 放置 |
| 右键 | 拆建筑；点矿脉 = 手动采矿 |
| 空格 | 暂停 |
| **F5** | **快速存档**（存到当前槽，默认存档 1） |
| **F9** | **打开读档面板** |
| Esc | 取消两点选择 / 退出 |

## 自动化链路

采矿机 → 传送带 → 分拣器 → 熔炉（矿→铁板）→ 分拣器 → 科研站（产研究点）/ 制造台（铁板→齿轮、电路板）

分拣器只在目标能收货时才抓，目标满了不堵。

电力不够时所有机器减速。白天太阳能、全天风力。
行星公转（每颗行星周期不同）：离星越近太阳能越强（±25%～±35% 相位起伏），顶栏显示当前光照倍率，
「轨道」面板看行星位置。**M5a 星际**：双行星（故乡星/余烬星），每颗行星是独立地图——
网格、建筑、物流、相机各管各的；科技树、背包、戴森云全星系共享（研究一次到处能用）。
轨道面板点其他行星圆点即可前往。

## 科技树

8 个科技，初始只解锁 传送带 / 采矿机 / 熔炉 / 科研站。

科研站吃铁板产研究点，点顶栏「科技」开面板选研究项。锁定建筑底栏显示 🔒 且放不下去。

## 存档

- 手动：顶栏「存」「读」打开**多存档面板**（6 个槽位，每槽独立）；
  F5 = 快速存档到当前槽（点槽存过后自动设为当前），F9 = 打开读档面板
- 读档面板底部还能读「最新自动存档」和旧版 `save.slm`（多存档之前的进度）
- 自动：每 120 秒一次，`autosave_0..2` 三槽轮转（不占手动槽位）
- 位置：项目根目录 `saves/`，格式 `SLM1` + zlib 压缩 JSON
- 传送带物品浮点位置、无人机状态、科技进度全部精确还原
- 存档 v10：多行星各自一个 `worlds[i]`（网格/建筑/物流/轨道/相机各管各），
  当前在哪颗星由 `world_index` 记录，读档后回到那颗星

## 压测

```bash
python tools/bench.py --preset small   # 10 条带 1000 物品，先验证
python tools/bench.py --preset 10k     # 40 条带 10000 物品 500 无人机
python tools/bench.py --preset 30k     # 60 条带 30000 物品 1500 无人机
```

输出 update / sync / render 三段 avg | p95 | worst 和 60/30fps 判定。
实测数据（x86 本机）见 `Docs/TechDebt.md` 第 8 条：优化后 10k ≈91fps 上限（60fps PASS），
30k ≈29fps（性能优化 M6.19 后）。

> Windows 控制台注意：自检/bench 脚本输出含 ✓ 等 Unicode 字符，GBK 控制台下会
> 抛 `UnicodeEncodeError` 误报失败。跑前先 `$env:PYTHONIOENCODING='utf-8'`。

存档往返自检（不需要 pygame）：

```bash
python tools/_savecheck.py
```

改存档/行星结构跑 `tools/_multiworldcheck.py`（多行星独立 + 切换 + v10 迁移）。

## UI 定义（JSON）

UI 外观以控件为单位定义在 `stellarloom/ui/defs/*.json`：
`meta` 主题色（`#RRGGBB`）+ `controls` 控件（label/button/list）+ 可选
`buttons` 按钮序列；位置支持 tl/tr 锚点、负坐标（右/下缘）、动态显隐/文案。
改 JSON（改文案、颜色、尺寸、按钮顺序）不用动代码——`ui/uidef.py` 加载器 +
`draw_controls / hit_control` 统一画/命中，业务只传动态数据。

已迁移：存档面板（`save_panel.json`）、顶栏按钮（`touch_top.json`）。
其余面板按 `Docs/TechDebt.md` #34 迁移清单逐个跟进。

## 操作

- **主菜单（M6.25）**：启动即主菜单——开始新游戏 / 继续游戏（读最新自动档）/
  读档（多存档面板）/ 退出。顶栏最左「菜单」按钮随时回主菜单。

## 架构（M6.24：服务器端 / 前端分层，类 Minecraft C/S）

```
stellarloom/sim/    服务器端：全部游戏逻辑，headless、零 pygame
  sim.py            Simulation：世界/科技/戴森云/背包/手搓/存读档
  craft_queue.py    手搓队列（玩家级逻辑）
  headless.py       无图形运行器
stellarloom/        前端：渲染 + 输入翻译 + UI（core.Game 只做这些）
```

- 前端把输入翻译成 **sim 指令**（放置/拆除/手搓/切星…），`sim.step(dt)` 推进
  模拟，事件流（toast/成就/脏格子）由前端帧末拉取。
- 服务器端不 import pygame——可在无图形环境独立跑、测试、基准：

```bash
python -m stellarloom.sim.headless            # 新游戏跑 600 tick
python -m stellarloom.sim.headless save.slm 120   # 读真实存档跑 120 tick
```

- 分层自检：`python tools/_simcheck.py`（含"sim 链零 pygame"子进程断言）。

### 无显示环境下跑自检（手机/沙箱必看）

`pygame.display.set_mode()` 在**没有 Android Activity 上下文**的环境里必然失败
（Pydroid 的 SDL2 是定制版，报 `did you include SDL_main.h...`）。想在 adb shell、
Linux 沙箱、CI 里跑显示类自检，用垫层：

```bash
python3 tools/_shim_display.py tools/_simcheck.py    # 单跑
```

垫层把 `set_mode` 换成普通 Surface、`flip/update` 变 noop、`Clock` 换假时钟、
`event.get` 返回空、`key.get_pressed` 返回全松。**全部 33 个自检脚本在垫层下
PASS**（详见 `Docs/Roadmap.md` M13.1）。生产代码不许 import 它。

## 联机（M15b/c）

```bash
# 专用服务端（自动打包，只依赖 Python + numpy，不需要 pygame）
python tools/build_server.py --out dist/server --pack-mods --zip
python dist/server/run_server.py --port 27715 [--save save.slm] [--autosave 120]

# 客户端加入（Pydroid / PC 都行）
python main.py --join <服务端IP>[:27715] --name 昵称
```

- 服务端权威跑模拟（20Hz），客户端只发指令、收快照/事件/脏格；断线自动回退单机。
- 服务端控制台：`status / players / kick / say / save / hash / stop`。
- mod：服务端加载 `mods/`（联机的逻辑 mod 必须装在服务端），握手时客户端比对
  mod 清单，缺内容 mod 只警告不拒绝。
- `run_server.py --headless-check 300` 输出状态哈希（两次运行必须一致，CI 回归）。

## 文档

- `Docs/Mods.md` — MOD 快速入门（M6.27）
- `Docs/ModDev.md` — MOD 开发手册（详细版：API 全参考 / sim 指令速查 / mixin 深度 / 排障）
- `Docs/TechDebt.md` — 已知技术债（全球电网、色块占位、单一矿种等）
- `Docs/ArtAssets.md` — M9 所需全部美术资源清单和出图 prompt

数据与配置：
- `stellarloom/data/recipes.json` — 23 条内置配方（M6.28 起 JSON 存储，启动加载，
  格式 `{ "rid": {"inputs": {"物品id": 数量}, "outputs": ..., "dur": 秒,
  "machines": [建筑id]} }`；物品/建筑数字 id 见 `config.py` 顶部 `I_*`/`B_*`）
- `stellarloom/ui/defs/*.json` — 面板外观（uidef 机制）+ `theme.json` 全局皮肤