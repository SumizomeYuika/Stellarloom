# StellarLoom-PG 当前状态（2026-11-27）

> 随本次提交同步：截至本次推送的项目进度一览。详细节点见 Roadmap.md，债务见 TechDebt.md。

## 已完成的里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M5b | 星际运输船队（跨行星物流） | ✅ |
| M6 | 行星工程 + 星系视图 | ✅ |
| M6.27–M6.32 | mod 平台（mixin 三类 wrap / 注解 @Mixin / 依赖拓扑 / 统一 config / 面板窗口化 / 主菜单） | ✅ |
| M7 | 物品注册表（命名空间 id） | ✅ |
| M8 | 建筑注册表 | ✅ |
| M9 | 真电网（8 格分区并查集 + kW 单位 + 戴森/注电摊派） | ✅ |
| M10 | 分拣器三段式机械臂（头/连接部/尾，纯视觉跨格） | ✅ |
| M11 | 技术债补丁：分拣器冷却存档 / 无人机不丢货 / 派工距离电量 / next_lane 校验 | ✅ |
| M12 | `.slmmod` 单文件分发（魔数+ZIP+manifest 验签，依赖编译缓存） | ✅ |
| M13 | 启动加载界面（大步骤进度条 + 当前项 + 子进度） | ✅ |
| M13.1 | 无显示环境自检垫层 `_shim_display.py` | ✅ |
| M13.2 | 无电开局：长按手动采矿 + 手搓科研包 + 手动研究 | ✅ |
| M13.3 | 分拣器过滤 UI（拆除按钮 + 方向提示） | ✅ |
| M14a | 液体地基：每格独立液量 + 压差限速 + 泵单向加压（不做整段共享） | ✅ |
| M15a | 联机前置：UI 面板全部改走 sim 指令，事件/脏格 fan-out | ✅ |
| M15b | 联机骨架：权威服务端（20Hz）+ 镜像客户端，TCP 单通道 | ✅ |
| M15c | 服务端完善：自动打包器 build_server + mod 加载 + headless 校验 | ✅ |
| M15d | 联机完善：@EnvType 侧标 + mod 出错即崩（crash_guard 兜底）+ 按玩家分背包 | ✅ |

## 光影 mod（shaderbridge）现状

- **管线**：Windows 桌面 GL **compatibility profile** 直编（PyOpenGL + WGL 离屏上下文），
  转译器已降级为极简预处理（版号归一 + 剥 precision，零结构重写）。
- **已修掉的坑**：glVertexAttribPointer 指针偏移（c_void_p）/ depthtex0 每帧清理 +
  shadowtex0 独立 / drawbuffers 紧凑映射 / colortex 下标=附件下标 /
  全屏四边形补 UV（黑屏决定性根因）/ glslmacro 构造函数式宏值 + U 后缀字面量。
- **实测**（Intel UHD，真实窗口）：cm（目录）34/34 pass 0 失败，mean=6.32，~28ms/帧；
  春眠 261014（**zip 直读不落盘**）28/28 pass 0 失败，mean=211.0，~52ms/帧。
- 首帧读回 mean<5 自动降级 pygame 原生绘制；无包降级正常。
- **剩余风险**：zip 只测过根级 `shaders/` 前缀（嵌套 `foo/shaders/` 未实测）；
  cm 的 mean 贴近降级阈值；gl_Normal 未喂数据（默认 (0,0,1)）；天空/TAAU 上采样契约未对齐。

## 联机现状（M15b/c/d）

- 服务端：权威 20Hz 定步长，控制台 status/players/kick/say/save/hash/stop；
  `tools/build_server.py` 自动打包（AST 闭包检查，逻辑层禁 pygame），
  打包后 `run_server.py` 可带 gregtech 全套 mod 启动。
- 客户端：`python main.py --join HOST[:PORT]` 或主菜单入口；断线自动回退单机。
- 数据：按玩家分背包（players[pid] 独立 inventory + CraftQueue），
  世界/科技/戴森球共享；存档 v14（v13 迁移）。
- mod 校验：握手 `hello_ack.mods` 清单比对，缺内容 mod 仅警告。
- **已知边界**：带物品/无人机位置只在关键帧间跳变（实体流未做）；
  事件/toast 全局广播（未按玩家路由）；无 AOI 订阅/ghost 预览/重连 token。

## 报错显示

- Java 风格栈（`stellarloom/core/errfmt.py`）：`at 模块.类.方法:行号`，
  不含文件路径，支持 Caused by 链、mod 入口名美化（mod_foo_main → foo）。
- crash_guard mod 崩溃页/报告同格式；未捕获异常全局 hook 在 main.py 与服务端入口。

## 自检

- 全套 **37 项 `tools/_*check.py` 全绿**（含新增 _errfmtcheck/_envcheck/
  _modcrashcheck/_playerscheck/_fluidcheck/_cmdcheck/_netcheck/_servercheck）。
- shaderbridge devtools：_glcheck/_worldcheck/_uniformcheck/_escheck/_chaincheck 全过。

## 下一步候选

- 联机：实体流（带物品/无人机插值）、AOI 视野订阅、断线重连 token、事件按玩家路由。
- 光影：gl_Normal 数据、TAAU 上采样契约、zip 嵌套前缀、packscan world 变体覆盖修复。
- 玩法：M14b 石油链（原油矿→抽油机→炼油厂→燃油发电）、M14c 塑料→高级电路板。
