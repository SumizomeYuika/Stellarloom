#version 330 core
layout(location = 1) out vec4 slm_out1;
// Convention: entry files stay pure ASCII (comments included), UTF-8 without BOM, LF endings.
// Legacy OptiFine decodes entries with the JVM default charset (GBK on zh-CN Windows) while include
// files are ASCII, and LWJGL 2 truncates each char to its low 8 bits; non-ASCII comments can turn
// into newlines or quotes and break GLSL parsing. Chinese docs go in shared program/lib or AGENTS.md.

// Bloom 上采样回卷 pass: composite_bloom_upsample（composite9~12 入口，入口定义 2 = 目标 tile 3~0）
// 金字塔自粗向细逐级合并：tile 2 = 本级原始内容 × 级权重 + 上一 pass 已合并粗级的
// tent 放大 2 倍相加（bloomUpsampleTile），粗级模糊经逐级 tent 累积成连续衰减；每 pass 重写整个
// 图集包围盒（非 tile 像素复制回写、不 discard——2 0 兼写 colortex7 须区域整写），
// 跨 pass 保值、对 main/alt 翻转语义免疫、无需 flip.*；tile4 恒为原始下采样内容供 composite12 测光
// 2 == 0（composite12）：colortex7 唯一写入者，光栅 quad 自图集包围盒扩为「包围盒 ∪
// 天空 LUT 区域」的包围矩形、一 pass 兼管全部槽位（协议见 AGENTS.md 缓冲布局）。colortex1 的
// tile 逻辑对全部光栅像素照常执行——槽位区域与 tile0 在 uv 上重叠但两缓冲互不相干，outMisc 分支
// 不得干涉 outColor（否则 tile0 凿洞、final 放大后成屏幕黑矩形）：
//   - 天空 view LUT：日 / 月半区各 200×100 逐纹素重算（帧常量在 vsh 预计算经 varying 传入，
//     低于 SKY_LIGHT_MIN_HEIGHT 的非活动光源整半区写 0）
//   - 云层天空盒（1）：[0,256)² 八面体逐 texel getPlanarCloudsWorld 全量重算（与主天空
//     同一单真源；下行视线行星命中早退、只上半球付全额，≈ 天空 LUT 同级成本）——water 反射
//     未命中 SSR 侧经 sky.glsl 的 sampleCloudSkybox 单 fetch 消费的烘焙层，2026-10 接入；宏关时
//     该区域落入「其余透传」分支保值、消费侧同步编译剔除
//   - aerial 透视 LUT（1）：(460,0) 起 64×192（方向 64×48 × 距离 4 档纵向堆叠；
//     原址 (0,0) = 天空盒预留区左下角，2026-10 天空盒启用迁此）逐纹素重算
//    （lib/atmosphere/aerial.glsl 的 aerialLutTexel；帧常量复用天空 LUT 的 vsh varying、vsh 零新增；
//     宏关时该区域落入「其余透传」分支保值无害）→ composite_fog 消费
//   - 曝光槽位：tile4 对数平均测光 + 指数平滑写回
//   - 其余像素：包围盒内同位置读回透传（clear=false 跨帧保值），区域外光栅带写 0 免回读
// 云天空盒烘焙的帧数据（主导光源方向 / 直射辐照度 / 云高处透射率 / 天空环境基色）与通用全屏
// vsh 同名同式、在本 program vsh 段计算（见 VERTEX 段）
// DRAWBUFFERS 随输出不同下放入口文件（composite9~11 = 1、composite12 = 17），program 不携带
// vsh 把 quad 压缩到全图集包围盒（2 0 为上述并集包围矩形）；fsh 前半 / vsh 后半
//（云形状场的生成在 deferred 槽的 deferred_cloud_field、不涉本 pass）

// 全部常量集中声明，程序与其他 lib 文件不再自行定义
// lib 文件之间不互相 include，本文件由 program 直接引入（须在 lib/common/pipeline/varying_io.glsl 之前，
// remapLightmap 依赖这里的常量）；OptiFine/Iris 扫描 include 展开后的内容
//
// ---- 游戏内设置（2026-10 接入；布局 = shaders.properties 的 screen.* 段、文案 = shaders/lang/*.lang）----
// 三种形态：①开关 = 裸 #define 行（引擎改设置即注释 / 取消注释该行，删宏回退语义天然成立）；
// ②数值 = `#define NAME 值 // [值表]`（引擎回写值表中的 token，值表必须是本行的行尾注释、其后不得再有
// 其他文字——引擎正则只认行尾 [..]，说明文字一律挪到上一行注释）；③游戏内置指令 = camelCase const
//（shadowMapResolution 系 / sunPathRotation / ambientOcclusionLevel）——**唯一可用 const 形态挂值表的
// 设置**，自定义数值选项必须用 #define：引擎 const/option 预理会移除 / 改写数值型 const 声明（见下方
// 缓冲格式分区注），宏则按行回写、结构性免疫。值域换算类 / 结构不变式类常量（LUT 布局、位打包阈值、
// TAAU_KERNEL_BIAS 的 [4/3,√2) 窗等）不开放——开放项以「玩家观感旋钮」为限。诊断 A/B 档
//（1 / 1 / 1）不列入设置屏、留在源码手动切换

// ---- 通用 ----
const float TAU            = 6.28318530718;
const float PI             = TAU * 0.5;
const float GOLDEN_ANGLE    = 2.39996323;   // 黄金角（弧度）：黄金螺旋采样（阴影 PCF 等）
const float GOLDEN_RATIO    = 0.61803398875; // 黄金比例共轭 1/φ（春v2 同值）：temporal 噪声帧间相位偏移（noise.glsl）
const float ALPHA_CUTOUT   = 0.1;           // cutout 透贴裁剪阈值（引擎参考值不可用时的下限兜底）
const float ALPHA_TEST_REF_MAX = 1.0;       // 引擎参考值上限（防异常哨兵：Iris 实体 VERTEX_ALPHA 档参考值为
                                            // Float.MAX_VALUE 一类值，钳回 1.0 后只裁 a<1 像素而非整 draw 全灭）
// pass 侧 cutout 剔除的统一阈值（2026-10 全版本统一，BSL 式「properties 关引擎测试 + pass 消费
// alphaTestRef」）：引擎 uniform 钳到 [ALPHA_CUTOUT, ALPHA_TEST_REF_MAX]。两端兜底依据——Iris 在
// alphaTest.* = off 下 effective 测试 = ALWAYS、alphaTestRef 恒 0（override 取 ALWAYS 的 reference），
// 老 OptiFine（1.12-）不识别该 uniform 亦恒 0：均由下限回落 0.1 = 统一前行为；现代 OptiFine 的逐 draw
// 参考值（0.1 / cutout 0.5）原样生效 = 引擎语义。宏体引用 uniforms.glsl 的 alphaTestRef 声明（宏延迟
// 展开，各 program 的 constants 先于 uniforms 引入即满足）；shadow 阶段不消费本宏、恒 ALPHA_CUTOUT
// 引擎指令：原版平滑光照 AO 强度（缩放引擎烙进顶点色 rgb 的暗角，随 albedo 打包进 colortex4；0 = 关闭）
const float ambientOcclusionLevel = 1.0; // [0.0 0.5 1.0]
const float LIGHTMAP_MIN   = 1.0 / 32.0;    // 原版光照图坐标下限
const float LIGHTMAP_SPAN  = 15.0 / 16.0;   // 原版光照图有效跨度（上限 = MIN + SPAN = 31/32）

// ---- 缓冲格式 ----
// colortexNFormat 指令收进下方 /* */ 注释块（BSL / Complementary 同款生态标准形态：OptiFine / Iris
// 均从注释扫描指令，格式名〔RGBA16 等〕不进编译器）。2026-10 实机修复：旧形态为真实 const +
// 「const int RGBA16 = 0;」占位声明——引擎 const/option 预理会改写 / 移除数值型 const 声明，
// 占位被吃掉后 colortexNFormat 行悬挂未定义格式名（undefined variable RGBA16，gbuffers_water
// 等程序编译失败）；注释块内指令不参与编译，结构性免疫。colortexNClear 为 bool 字面量、编译
// 无害，保持真实 const（引擎从代码扫描，实测有效）
/*
const int colortex1Format = R11F_G11F_B10F; // bloom tile 图集（composite4~12 写）+ 云形状场槽位（deferred 写、图集右侧 r 通道，布局见 bloom.glsl 的 cloudFieldRect）：无符号 11/11/10、无 alpha，较 RGBA16F 带宽减半；COD 核小负瓣写入钳 0 无损
const int colortex3Format = RGBA16F; // TAA 历史缓冲：rgb = 上帧混合色（线性 HDR），a = 上帧最近片元线性深度（解遮挡置信）
const int colortex4Format = RGBA16;  // gbuffer: 打包 albedo + 打包高光贴图（位打包需无符号格式）
const int colortex5Format = RGBA16;  // gbuffer: 八面体观察空间法线 + 原始 lmcoord
const int colortex6Format = RGBA16F; // 场景主颜色：放 colortex6（= gbuffers 别名 gaux3）而非惯例的 colortex0——前向半透明 after 路径的手动合成须在 gbuffers 阶段采样主颜色背景，而 colortex0~3 采样单元在该阶段被游戏纹理占用（colortex0 即几何纹理 tex、实测采样返回图集内容），colortex0 全程未使用、不声明格式。须浮点格式：半透明合成背景为线性 HDR，旧「colortex4 副本」方案受 gbuffer 位打包的 RGBA16 格式约束会 [0,1] 截断亮背景（阳光下水面背景偏暗），副本机制已删
const int colortex7Format = RGBA16F; // 杂项数据（左下角杂项簇，布局见 SKYBOX_LUT_SIZE / SKYVIEW_LUT_* / AERIAL_LUT_ORIGIN_X）：云层天空盒 256×256（八面体，反射路径烘焙云）+ 天空 view LUT 200×200（日 / 月半区各 200×100）+ 曝光槽位 1 texel + aerial 透视 LUT 64×192（(460,0) 起）
const int colortex31Format = RGBA16F; // SR 超分运动矢量（SR mod 注入宏门控引用、未装 SR 时零引用零分配）：rg = 本帧→上帧位移（渲染分辨率归一 uv 域、无抖动采样位）、b = 实体层标记（gbuffers_entities 写 1，deferred_init 读回保留 / 其余写 0）。浮点格式（位移 ∈ [-1,1] 带符号、8bit 量化不可用）；默认 clear = true（帧头清 0 = 标记复位，防上帧实体标记跨帧残留）
*/
// Voxy 专用附件：关闭时连格式 / 清屏指令一起移除。







const bool colortex3Clear  = false;   // 历史跨帧存活；仅 composite_taa（composite3）读写（单程序独占 ping-pong，不依赖 flip.*）
const bool colortex7Clear = false;   // 槽位内容跨帧存活；composite12 唯一写入、光栅区域整写并透传非槽位像素（协议见 AGENTS.md / exposure.glsl）

// ---- 维度（world-1 下界 / world1 末地，2026-10 接入；NETHER / END 宏由各维度入口文件定义、
//      world0 不定义——模组自定义维度走根目录〔无入口文件〕= 引擎内建管线）----
// 极简档基线：两维度入口均不创建 shadow（阴影贴图不渲染）/ deferred（云形状场）两槽，程序侧由
// DIM_NO_SHADOW / DIM_NO_ATMOSPHERE 派生宏编译剔除对应采样与生成——天空 view LUT / aerial LUT /
// 云天空盒的生成（composite12）与消费（deferred_init 天空分支 / water 反射）全部无读写，天空
// 像素 = DIMENSION_SKY_COLOR 常量（末地之上另叠加主世界默认星盘——getStars 的 END 分支夜门
// 常开 / 星图全球，2026-10；下界纯常量）。**下界另恢复雾 pass（composite2 入口已建，2026-10）**：经
// FOG_UNIFIED_COLOR 走「统一雾色」档（见边界雾分区）——边界雾 / 空气透视恢复、雾色 = 常量而非
// 大气散射 LUT（下界无天光大气，LUT 亦不生成），末地维持无雾极简档（composite2 入口不创建）。
// 下界 has_skylight = false（lm.y 恒 0）；**末地 has_skylight 实际为 true**（原版末地 skylight = 15、
// 开阔地表 lm.y ≈ 1——「两维度 lm.y 恒 0」旧假设只对下界成立，2026-10 末地天光三轮反馈修正）⇒ 直射经
// DIM_NO_DIRECT_LIGHT 整段编译剔除照旧（末地无日月光源，剔除与 lm 无关）；末地天空环境项
// vSkyAmbient × lm.y⁴ 一直活着、经 END_SKY_AMBIENT 专用色供给（见下方光照分区的末地天光段），
// 下界该路径 lm 恒零自然退化；fixed_time 定格下日月 uniform 虽有值、无任何消费路径



// ---- 天空 / 大气（lib/atmosphere/atmosphere.glsl + sky.glsl）----
const float SKY_TEXTURE_BRIGHTNESS = 4.0; // 太阳 / 月亮贴图发光补偿（日月贴图程序 gbuffers_sky_tex，暂未链接）

// colortex7 左下角杂项簇布局（texel 域，锚定 texel (0,0) 角 = 屏幕左下）：云层天空盒占最角上
//（[0,256)² 整块，原 aerial 借住其左下角、2026-10 天空盒启用而迁走）、天空 view LUT 200×200
// 水平相邻、曝光 / 标记槽位在二者 4 texel 间隔 gutter 内（exposure.glsl）、aerial 透视 LUT 在
// sky-view 右侧水平续接（同锚缓冲底边）；固定 texel 布局假设缓冲 ≥ ~524×260（实际渲染分辨率
// 下限远高于此）
const int SKYBOX_LUT_SIZE      = 256; // 云层天空盒边长（八面体，写读 = sky.glsl 的 cloudSkyboxDir / sampleCloudSkybox；春雷 begin19 skybox_lut 同尺寸）：composite12 每 texel 全量 getPlanarCloudsWorld 重算（≈ 天空 LUT 同级成本，下行视线行星命中早退、只上半球付全额）、water 反射未命中 SSR 侧单 fetch 消费；烘焙成本嫌重减半本值（×1/4，布局常量自动跟随）
const int SKYVIEW_LUT_W        = 200; // 天空 view LUT 半区宽 = 视线-光源方位角参数化分辨率（春雷 skyViewLutSize 同值）
const int SKYVIEW_LUT_H        = 100; // 天空 view LUT 半区高 = 天顶角参数化分辨率；太阳（上半区）/ 月亮（下半区）纵向堆叠 = 200×200
const int SKYVIEW_LUT_ORIGIN_X = SKYBOX_LUT_SIZE + 4; // LUT 区域原点 x（texel）= 260：天空盒右侧 4 texel 间隔，区域锚定缓冲底边
const int AERIAL_LUT_ORIGIN_X  = SKYVIEW_LUT_ORIGIN_X + SKYVIEW_LUT_W; // aerial 透视 LUT 原点 x（texel）= 460：sky-view 右侧紧邻、同锚缓冲底边（原址 (0,0) = 天空盒预留区左下角，2026-10 天空盒启用迁此）
// 自适应曝光槽位（texel 域）：天空盒与 sky-view LUT 的 4 texel 间隔 gutter 内、缓冲底边。
// 写入端 composite12（exposure.glsl 的指数适应）；读取端 = composite_taa / final（直接乘）+
// deferred_init 背景快照编码 / water vsh 快照解码（成对消费、同帧读同一槽位值，见 lib/water/surface.glsl）；
// exposure.glsl 的 exposureTexel() 返回本常量（单一真源）
const ivec2 EXPOSURE_TEXEL = ivec2(SKYVIEW_LUT_ORIGIN_X - 2, 0);
// pass 顺序标记槽位（诊断，texel 域）：曝光槽右侧紧邻、LUT 左缘外 1 texel——gutter 内与现有槽位
// 结构性互斥、在 composite12 光栅矩形内（可被每帧复位）。机制见
// lib/common/pipeline/pass_order_marker.glsl
const ivec2 PASS_ORDER_MARKER_TEXEL = ivec2(SKYVIEW_LUT_ORIGIN_X - 1, 0);

// Chapman 解析单次散射（移植自 Shadertoy WcdSW4，MIT，John Payne 2024，https://www.shadertoy.com/view/WcdSW4 ）
// 密度模型为 r² 高斯 exp(-(r²-R²)/H²)，H 是大数值参数化、不是物理尺度高度——
// 有效尺度高度 = H²/(2R) ≈ Rayleigh 8.05km / Mie 1.54km / 臭氧 16.3km，即地球真实量级
const float EARTH_RADIUS = 6360e3;    // 行星半径（米）
const float SKY_NO_HIT   = 1e30;      // 视线未命中行星的哨兵距离（替代 inf：编译期 1/0 在部分驱动上未定义）
const float RAYLEIGH_SCALE_HEIGHT = 320000.0;                                 // Rayleigh 参数 H（有效 8.05km）
const vec3  RAYLEIGH_SCATTERING_COEFFICIENTS = vec3(6.384e-6, 12.00e-6, 28.74e-6); // 散射 = 消光（瑞利无吸收）
const float MIE_SCALE_HEIGHT = 140000.0;                                      // Mie 参数 H（有效 1.54km）
const vec3  MIE_SCATTERING_COEFFICIENTS = vec3(1.252e-6, 1.689e-6, 2.530e-6);
const vec3  MIE_EXTINCTION_COEFFICIENTS = MIE_SCATTERING_COEFFICIENTS * 1.11; // 消光 = 散射 × 1.11（气溶胶吸收 ~10%）
const float OZONE_SCALE_HEIGHT = 455000.0;                                    // 臭氧参数 H（有效 16.3km），纯吸收、日落修色
// 臭氧系数按 Chappius 吸收带真实截面定形（光谱数据 https://www.iup.physik.uni-bremen.de/gruppen/molspec/databases/referencespectra/o3spectra2011/index.html ，
// 截面与浓度取法参考 Shadertoy『Scattering with Ozone』reinsteam 2017），锚定垂直 τ550 ≈ 0.04。
// WcdSW4 原系数光谱形状相反（R>G）：地平线长路径红衰减过快、日出天空发黄，故弃用重定
const vec3  OZONE_EXTINCTION_COEFFICIENTS = vec3(1.021e-6, 2.474e-6, 1.015e-7);
const vec3  SOLAR_IRRADIANCE = vec3(236.8, 206.4, 204.9);                     // 大气顶太阳辐照度（相对单位）
const vec3  MOON_IRRADIANCE  = SOLAR_IRRADIANCE * 5.0e-4; // 大气顶月亮辐照度（春雷同值 ~1/2000：真实满月 ~1/40万，游戏取值保夜景可见）
const float SKY_BRIGHTNESS   = 1.0;  // 天空色整体缩放：对齐 albedo 0~1 的画面量级（进游戏后校准）
// LUT 非活动半区阈值：光源低于此高度（约 -8.6°）后散射已衰减 7 个数量级不可见，生成端整半区写 0、
// 采样端以同一常量门控跳过 fetch——不变式「采样端跳过 ⊆ 生成端写黑」由共用本常量保证，勿在采样端写独立数值
const float SKY_LIGHT_MIN_HEIGHT = -0.15;
const float SKYVIEW_LUT_VALID_MARKER = 0.625; // LUT alpha 有效标记（RGBA16F 精确值），区别于清零 / 旧版 alpha=1 / 未初始化内容
// float32 数值防护：erfcx 负参量分支 exp(b²) 的 b 可达 r/H ~ 45 → 溢出 Inf（夜晚 / 下视 NaN 的根源）；
// airMass 上限刻意远高于 exp 归零所需——上限偏低时 energyIntegralRatio 的 ~1/tauS 残尾成为夜空亮度地板
//（1e9 时 ~2e-4 luma，经夜间自动曝光放大成可见辉光；1e15 压至曝光上限内不可见），白天主段 airMass < 1e6 不触及
const float SKY_ERFCX_EXP_MAX = 80.0; // erfcx 负支 exp 上限：2·e^80 ≈ 1.1e35 有限，对应光学深度早已全遮蔽、钳顶无损
const float SKY_AIRMASS_MAX   = 1e15; // airMass 钳制上限：τ = βmax·1e15 → exp(-τ) = 0；兼杀下视掠射闭式相消的负值 / NaN
// 地平线方向钳制（春雷 CLAMP_TO_HORIZON / ClampDirToHorizon 同款）：地平线以下的天空求值方向
//（LUT 下半区纹素；未来反射的向下采样）在散射路径上钳到与地球正好相切的观察者地平线切线、钳后
// 射线一律按未命中求值——不钳时这些方向是行星命中路径、天光趋黑，钳后取地平线辉光色（暮光带
// 向下延展）；相位函数仍按未钳制方向求值、角向明暗保留。机制与数值防护见 atmosphere.glsl 的
// clampDirectionToHorizon 头注。删除本宏 = 回退逐方向直达路径（地平线以下恢复行星命中求值）
// Mie 相函数 = HG(g1) 与 Draine(g2, a) 按权重 w 混合（Shadertoy 原调参，前向峰 + 适度后向）
const float MIE_PHASE_G1 = 0.862;              // HG 主叶前向强度
const float MIE_PHASE_G2 = 0.5069161813017329; // Draine 次叶
const float MIE_PHASE_A  = 250.0;              // Draine 各向异性因子
const float MIE_PHASE_W  = 0.24075857115188248; // 混合权重

// 各向同性环境场多次散射（skyAmbientField / atmosphericRadiance MS 项，机制见 atmosphere.glsl 头注释）：
// 正午 MS 增幅实测——天光辐照度 ×1.07/×1.12/×1.26（R/G/B）、天顶 ×1.10~1.17、反日侧暮光地平线 ×1.6~1.7；夜空地板不抬高
const float SKY_MS_STRENGTH     = 1.0; // MS 整体强度（0 = 退回纯单次散射）；嫌暮光弧 / 地平线抬升弱可上调，参考 1.0~2.0
const int   SKY_MS_QUAD_BANDS    = 8;   // 球面求积环带数（Δcosθ 等间距 = 等立体角；最内环带 θ ≈ 29° 避开 Mie 窄前向峰）
const int   SKY_MS_QUAD_AZIMUTHS = 6;   // 每环带方位节点数（带间黄金角错位防与光源几何对齐）；× BANDS = 48 节点
const float SKY_MS_CAPTURE_MAX   = 0.9; // 截获比 ρ 钳顶（海平面实测 ≤ ~0.30，防极端海拔撑爆几何级数分母）

// ---- 太阳盘（sky.glsl getSunDisk，deferred_init 天空分支解析叠加）----
// LUT 半区 200×100 的纹素角尺寸远大于 ~1° 视角圆盘、装不下，太阳盘只能解析绘制；亮度与
// 地面直射光同源（SOLAR_IRRADIANCE × 沿视线透射率），日落红化 / 雨天衰减与场景阳光色自动一致。
// 遮挡 = planetHitDistance（与 LUT 生成端同一行星几何），太阳沉没即圆盘下缘被地平线硬切
// 视角半径（弧度）≈ 1.08°：约 4 倍真实太阳（0.267°），全角 ~2.2°，按反馈连续放大；嫌大回抬此值
const float SUN_DISK_SOFTEN     = 0.0015; // 边缘软化宽度（弧度）≈ 0.086°：约一渲染纹素（1080p/70°FOV 一像素 ~0.065°、1 S=0.7 渲染纹素 ~0.093°），抗锯齿过渡带交由 TAA 时间累积抹平
// 亮度定标：正午 E ≈ 237 × T ≈ 0.87 × 450 ≈ 9×10⁴ 已越过 RGBA16F 上限、盘心钳至 65504 纯白（AgX 本就滚落成白炽、视觉无损），bloom 泛光与日落红盘（未及钳、随本值线性）是主要观感来源；物理辐射亮度 E·T/Ω 会更高三个量级，故为视觉定标非能量定标；嫌亮 / 嫌暗调此值
const float SUN_DISK_RAIN_FADE  = 0.75;   // 雨天辐照度衰减（与 vDirectIrradiance 的 (1 − 0.75·rain) 同系数）：阴天太阳随直射光一起淡出（云层遮挡由绘制顺序天然给出）

// ---- 月亮盘 / 星盘（sky.glsl getMoonDisk / getStars，deferred_init 天空分支在太阳盘之后、云合成
//      之前解析叠加；water 反射未命中 SSR 侧经 waterSkyReflection 同序消费）----
// 与太阳盘同纪律：LUT 纹素角尺寸装不下圆盘 / 星点的高频内容，只能解析绘制；先于云叠加 = 云遮挡。
// 开关宏与数值常量分离（1 同纪律）
// 月盘满月圆盘（无月相 / 贴图）：亮度 = MOON_IRRADIANCE × 沿视线透射率 × 增益——色度与地面月光
// 同源（月下场景直射色与月盘自动一致，月出红化物理呈现）；不乘 nightFactor 时间门（几何可见性
// 交给 planetHitDistance 地平线遮挡，太阳盘同款）；雨天随月光同系数淡出
const float MOON_DISK_RADIUS     = 0.0188; // 视角半径（弧度）≈ 1.08°：与 0.0188 同值（vanilla 日月同视觉大小），独立常量留单独调径
const float MOON_DISK_SOFTEN     = 0.0015; // 边缘软化宽度（弧度）：与 SUN_DISK_SOFTEN 同值，约一渲染纹素、过渡带交 TAA
// 视觉增益定标：月盘 ≈ 0.118 × 透射率 × 本值 ≈ 线性域 ~25——物理满月辐射亮度比太阳暗 ~9 个数量级
//（MOON_IRRADIANCE 是为夜景可见的游戏取值），月盘亮度是视觉定标非能量定标（450.0 450
// 同思路）；25 经夜曝光适应（上限 18×）≈ AgX 白亮盘 + 温和 bloom，嫌亮 / 嫌暗调本值
const float MOON_DISK_RAIN_FADE  = 0.75;   // 雨天衰减：与 SUN_DISK_RAIN_FADE / vDirectIrradiance 同系数

// 星盘：立方体网格 hash 点星，星图与月固连（绕世界 Z 旋回月亮相位——星月同升落、相对位置恒定，
// 机制见 sky.glsl getStars 头注）；夜间按太阳高度渐显（日月相对 ⇒ 即月升门）、雨天淡出；星星不随
// 主导光源阴影门控（恒星无对应遮蔽信息，桥影挡月光不挡星光——water 反射侧同纪律）。末地（2026-10
// 星盘接入）：夜门经 END 分支常开、planetHit 切割剔除（星图覆盖全球虚空）、星点叠在 DIMENSION_SKY_COLOR
// 之上——星盘实现单真源、主世界档逐位不变
const float STARS_GRID_SCALE    = 60.0;  // 网格密度（星图坐标 × 本值取整分格）：单元角尺寸 ≈ 1/本值 rad ≈ 0.95°
// 占格率（hash 门）：天球 ~4π·N² ≈ 45000 格、半球可见 ≈ 22000 × 本值 ≈ 3300 颗（vanilla 星空 ~1500 颗量级）；抬密调本值
const float STARS_FALLOFF       = 8.0;   // 点径衰减斜率（× 网格域距离）：星半径 ≈ 1/本值 单元 = 0.125 单元 ≈ 0.12° ≈ 1.3 渲染纹素（1 S=0.7 / 1080p）——2026-10 按反馈「星星太大」自 0.25 单元缩半；更小会亚像素闪烁（TAA 吸收一部分），再嫌大抬本值；星点格内偏移已钳 [0.25,0.75]，星形完整不出格
// 星点亮度定标（线性域峰值）：夜空 LUT ~1e-3~1e-2、被月光照亮的夜云 ~0.1 量级——本值使星点经夜曝光适应
//（上限 18×）后清晰可见、但透过云的预乘合成（star × cloud.a）后与云亮度同量级，云遮星观感成立。首版 1.6
// 被反馈「星星就好像覆盖了云」（透过薄云仍是白点）降至本档；嫌暗回抬、再现刺穿感回降
const float STARS_TWINKLE_SPEED = 2.0;   // 闪烁速度（Hz）
const float STARS_TWINKLE_DEPTH = 0.5;   // 闪烁深度（亮度摆幅比例，0 = 不闪）
const float STARS_RAIN_FADE     = 1.0;   // 雨天淡出系数（云层遮星，1 = 雨夜全无星）
const float STARS_FADE_LOW      = -0.25; // 夜门下沿（太阳世界高度）：低于此（约 -14.5°，深暮光后）满星
const float STARS_FADE_HIGH     = -0.05; // 夜门上沿：高于此（日落线附近、天空尚亮）无星

// ---- 云（2D 平面云，lib/atmosphere/clouds.glsl；方案移植自春v2 clouds2D，2D 云原作者 Coldnight冷夜）----
// 单层解析云：云壳求交（与大气共用 EARTH_RADIUS）+ 角坐标 6 octave simplex fbm（各 octave 差速
// 演变）+ Klein-Nishina 前向散射相位照明，alpha = 密度 × 距离衰减；画在 deferred_init 天空分支
//（TAA 之前）。常量名对齐春v2 便于对照调参（多数同值，差异处注明「本包适配」）；光照全部来自
// 通用全屏 vsh 帧数据 varying——昼夜切换黑过渡 / 雨天直射 ×0.25 / 环境去饱和自动跟进。
// 开关宏与数值常量分离（预处理 #if 不支持浮点比较，1 同款纪律）；下界 / 末地经
// DIM_NO_ATMOSPHERE 整体不定义（维度极简档无大气——云天空盒烘焙〔composite12〕与天空分支云
// 合成一并编译剔除，clouds.glsl 本体亦有同宏守卫）
// fbm 前微扰 warp 场用 simplex（1 次 simplex = 3 hash）替代春v2 的 worley（3×3 邻域 = 9 hash）——
// warp 职责只是打碎团块感的平滑位移场、任何低频噪声都胜任；位移场从胞状距离变梯度场，云的破碎
// 纹理风格会变（统计等价）。A/B 回退点：删本宏定义即回 worley 版（cloudWarp 内 #else 分支，
// 已带平方距离比较 + 循环外单次 sqrt 的降耗版）
const float CLOUDS_2D_HEIGHT        = 8000.0;  // 云层海拔（米，春v2 同值）：高处大片层云观感 + 角坐标数值域有界；与 vCloudTransmittance 半径共用（同一常量）
// 覆盖率（春v2 0.45、按反馈上调）：coverage 重映射阈值，抬 = 云更多更整片
const float CLOUDS_2D_COVERAGE_RAIN = 0.85;    // 雨天覆盖率（本包适配：春v2 雨天只减密度、阴天感由其体素云层承担，本包无底层故抬 coverage 成阴天）
const float CLOUDS_2D_DENSITY       = 1.0;     // 密度直乘（春v2 同值）：不透明度 = 密度（云存在度遮挡，2026-10 去距离衰减——晨昏交接带云不可见修复，见 clouds.glsl）的主旋钮
const float CLOUDS_2D_RAIN_FADE     = 0.66;    // 雨天密度衰减（春v2 同值）：阴天变薄云
const float CLOUDS_2D_SCALE         = 300.0;   // 噪声角域频率（春v2 同值）：一个噪声周期 ≈ 云壳半径 / 300 ≈ 21 km，一团云 ≈ 半周期
const float CLOUDS_2D_SPEED         = 0.01;    // 噪声域时间速度（春v2 同值）：低频层平移 + 各 octave ×1.1 差速——云在漂移之外持续自演变
const float CLOUDS_2D_PHASE_G       = 0.25;    // KN 相位前向不对称度（春v2 同值）：银边强度与集中度的权衡
const float CLOUDS_2D_PHASE_E       = 1.879;   // KN 相位 e 参数（本包优化）：由 PHASE_G 经牛顿迭代离线解出（残差方程 1/e − 2/ln(2e+1) + 1 = g，g = 0.25 → e ≈ 1.879）——与 PHASE_G 成对维护、改 g 须重解；春v2 逐像素 8 次迭代运行时求解，折叠后免 9 次超越函数
const float CLOUDS_2D_PHASE_LOGTERM = 1.560;   // ln(2e+1)（本包优化）：同上离线解出、与 PHASE_E 成对
const float CLOUDS_2D_LIGHT_DRIFT   = 4000.0;  // 伪自阴影的光源侧偏移距离（米，本包扩展）：相对噪声周期（云壳半径 / SCALE ≈ 21 km）取数 km——偏移落在云边缘另一侧才有明暗差；sunPathRotation −30° 下正午仰角 ≈ 60°、水平投影 ≈ 0.5，调制减弱而非消失（仅太阳真正近天顶才趋零）
const float CLOUDS_2D_SHADOW_GAIN   = 3.5;     // 密度差 → 明暗映射增益（本包扩展）：大 = 边缘阴影更锐；探针场化到 2 octave + bilinear 后调制趋平滑，嫌淡先抬此值
const float CLOUDS_2D_SHADOW_STRENGTH = 0.45;  // 伪自阴影幅度（本包扩展）：直射项 × [1−S, 1+S]——0.35 偏淡 / 0.6 偏重，0.45 折中档；0 = 关闭
// 云形状场（colortex1 图集右侧槽位、布局矩形见 bloom.glsl 的 cloudFieldRect）：世界锚定的低频云
// 形状（warp + 前 FIELD_OCTAVES 个 octave 的 fbm 经 cloudShape），窗口跟相机、内容为绝对世界
// 坐标的确定函数。deferred 槽生成（program/deferred_cloud_field）、deferred1（deferred_init）同帧
// 消费、零滞后——引擎的缓冲 clear 在 gbuffers 后、deferred 链前，场的写入在 clear 后、消费在下一
// clear 前，时序天然自洽（colortex1Clear 无需置 false）；bloom 图集自 composite4 起每帧全量重写、
// 与场槽位区域互斥（布局由 cloudFieldRect 结构性保证）互不干扰
const int   CLOUDS_2D_FIELD_RES     = 128;     // 场边长（texel）：128² × 9 hash ≈ 0.15M/帧生成成本
const float CLOUDS_2D_FIELD_WORLD   = 524288.0; // 窗口边长（米，512 km）：texel 4096 m ≤ 场最高 octave（第 2 个，角频率 750）周期 8.48 km 的一半（Nyquist）；半窗口 256 km > 云远界 CLOUDS_2D_FAR_MELT_END + LIGHT_DRIFT（240 + 4 km，2026-10 自 fade 早退界 ~221 km 改锚）——伪自阴影探针域恒在窗口内、bilinear 边缘永不被触达
const int   CLOUDS_2D_FIELD_OCTAVES = 2;       // 场 octave 数：探针 / 云影只需低频明暗，2 octave 是 4 km texel 的 Nyquist 上限（第 3 个 octave 周期 3.4 km 需 ≤1.7 km texel）；frequency / weight / time 序列与 cloudSimplexFbm 严格一致（改动须两处联动）
const float CLOUDS_2D_SKY_MIX       = 0.2;     // 光照的天空环境占比（春v2 同值；春v2 兼作层合成强度，本包无体素云底层、整层全强度合成，此常量只管光照混合）
const float CLOUDS_2D_FAR_MELT_END  = 240000.0; // 云远界融边终点（米，本包扩展 2026-10）：不透明度在 [终点−32000, 终点] smoothstep 融到 0——保 colortex1 云形状场半窗口不变式（探针 ≤ 终点 + LIGHT_DRIFT = 244 km < 256 km）；对应仰角 ≲ 2° 的地平线带、边界雾满档接管（1 关闭时为柔和溶接）。曾为 CLOUDS_2D_FADE_DISTANCE 24000 的 exp 距离衰减（春v2 同值、中低仰角云随距离变薄）——晨昏交接带云不可见实测根因之一，按反馈移除
// 云亮度：实际 = 1.0（玩家倍率，值表 1.0 缺省）× CLOUDS_2D_BRIGHTNESS_BASE（定标基值）。
// 基值承载 2026-10 按反馈的定档观感（两轮 1.0 → 0.8 → 0.6）：引擎按玩家保存档回写 #define 行，文件侧宏
// 默认值不可靠，定标收进引擎不回写的 const——玩家选项 1.0 × 基值 0.6 = 旧 0.6 档亮度。历史定标参考：春v2
// 3.5 按其 sunColor 量级；本包直射辐照度 ≈ 236、白地形 E/π ≈ 75，旧无基值 1.0 → 正午云与白地形同量级
const float CLOUDS_2D_BRIGHTNESS_BASE = 0.6; // 定标基值（非玩家旋钮，不进值表 / screen）；嫌亮暗只调它，勿动玩家档位
// 云层天空盒（colortex7 [0,SKYBOX_LUT_SIZE)² 八面体、写读映射对 = sky.glsl 的 cloudSkyboxDir /
// sampleCloudSkybox）：composite12 帧末逐 texel getPlanarCloudsWorld 全量重算（与主天空同一
// 单真源，rgb = 未预乘云色 / a = 不透明度）、water 反射未命中 SSR 侧按反射方向单 fetch 标准
// alpha 合成（2026-10 契约）
//——2026-09「反射不硬算云」的烘焙路线落地。已知取舍：云纹角分辨率 ~0.8°/texel（远粗于主天空
// 逐像素，经水波扰动 + TAA 后可接受）、内容滞后一帧且相机锚定晚一帧（云纹尺度数百米、帧间
// 相机位移厘米级，不可见）、八面体接缝 bilinear 串色（低频云不可分辨）；天空色 / 太阳盘不进
// 烘焙——前者反射侧仍直采 sky-view LUT（免双重重采样），后者 256² 纹素装不下 ~2.2° 圆盘的解析
// 锐度、反射侧仍走 getSunDisk（云在其后合成、镜中日盘同被云遮挡）

// ---- 边界雾（lib/atmosphere/fog.glsl，接入 = composite_fog / composite2 槽；距离 / 天顶角双因子、雾色取天空 LUT）----
// 渲染边界处的融接雾：远处地形 / 水面 / 天空溶进地平线色、视距边缘无接缝；非物理雾（无光照
// 方向性 / 高度衰减，纯边界融接）。开关宏与数值常量分离（1 同纪律）；删宏 = fog.glsl 编译为空 +
// composite_fog 整 pass 透传旁路（colortex6 同位置 fetch 原样写回——discard 会因引擎缓冲翻转
// 黑屏，见 composite_fog.glsl）；末地经 DIM_NO_ATMOSPHERE 不定义（无雾极简档、composite2 入口
// 不创建），**下界经 FOG_UNIFIED_COLOR 恢复定义并走统一雾色分支**（2026-10，见下方统一雾分区）
const float BOUNDARY_FOG_START  = 0.70; // 雾起始距离（×far）：约 0.7 倍视距外起雾
const float BOUNDARY_FOG_END    = 0.90; // 雾满强距离（×far）：0.9·far 外距离因子饱和为 1
const float BOUNDARY_FOG_ZENITH = 0.40; // 天顶淡出上沿（视线世界 y = sin 仰角，初值 0.5）：0（地平线）满雾 → 0.4（仰角约 23.6°）零雾——雾带只贴地平线、抬头即散（2026-09 按反馈下调）；统一雾档不消费（见下）

// ---- 下界统一雾（FOG_UNIFIED_COLOR，2026-10；fog.glsl 边界雾 + aerial.glsl 空气透视的统一雾色分支）----
// 下界 has_skylight = false、无天光大气——雾不取大气散射 LUT（LUT 本维度不生成、无值可采），
// 两段雾统一 **mix 向单一雾色**（原版下界式融接）：边界雾 = 纯距离因子（天顶角因子弃用——那是
// 主世界为「抬头护天空」而设，下界封闭无天可护；天空像素本就是雾色常量、雾化幂等，任何仰角的
// 融接结构性无缝）；空气透视 = 均匀介质解析式 T = exp(−σ·d) / S = 雾色 × (1−T)，无 LUT、无方向
// 依赖、无 lutValid 依赖（首帧即正确）。雾色与 DIMENSION_SKY_COLOR 同值单真源：远处地形溶进
// 天色 = 渲染边界与天空缝隙结构性不可见；要分离观感时拆常量并同步评估「天色 ≠ 雾色」的天空缝





// ---- 大气散射雾 / 空气透视（lib/atmosphere/aerial.glsl；生成端挂 composite12 天空 LUT 重算 pass、
//      消费端在 composite_fog（composite2）边界雾之前；设计全文见 plans/地表大气散射方案.md）----
// 「表面 × 路径透射率 + 路径内散射」的物理式空气透视（aerial perspective）：
//   finalColor = surface × T(viewDir, dist) + S(viewDir, dist)——S/T 由 Chapman 解析核心
//   （atmosphere.glsl 的 atmosphericRadiance 原生支持有限路径长度 t，透射率经 out 参数带回）按
//   「方向 × 距离档」小 LUT 供给，零新 pass / 缓冲 / 纹理资产。三条不变式：
//   ①放大距离、不放大密度（inscatter(∞) 渐近 = 天空色，密度域调制会造「浓版天空」≠ 屏幕 sky-view
//     LUT 值、地平线处地形与天空色差缝）——SCALE 是纯距离域旋钮、雨天加浓同样走距离域乘子；
//   ②∞ 档存 t = SKY_NO_HIT 的求值 = 同参数天空 LUT 值（地平线以上方向结构性融接）；
//   ③天空像素不施加（depth >= 1 跳过，渐近一致性只在几何侧成立）。与边界雾两段式分工：aerial 管
//   中近距物理空气感（方向性 / 色彩 / 曙暮光分层），boundary 兜 0.7~0.9·far 渲染边界硬融接。
//   MC 视距内真实大气几乎不可见（水平 500 m 路径 Rayleigh τ ≈ 0.006 → inscatter ~0.6% 天空亮度），
//   观感强度靠等效距离放大。近场起始门（AERIAL_FOG_START / END，2026-09 按反馈接入）：约 far/6
//   内无雾、效果域 smoothstep 自零渐入至 0.7·far（= BOUNDARY_FOG_START 接力锚）全强——近场空气感
//   弃用、远端强度不受影响。开关宏与数值常量分离（1 同纪律）；末地经 DIM_NO_ATMOSPHERE 不定义
//（无雾极简档），**下界经 FOG_UNIFIED_COLOR 恢复并走统一雾色分支（2026-10）**：applyAerialPerspective
//   换解析式 T = exp(−σ·d) / S = NETHER_FOG_COLOR × (1−T)（常量见边界雾分区的下界统一雾段），
//   **aerial LUT 生成端（composite12 区域分支）在统一雾档不编译**——生成了也无采样端、白付
//   天空 LUT 一成半~三成成本
// LUT 布局（texel 域）：colortex7 原点 (AERIAL_LUT_ORIGIN_X, 0) = (460, 0)——sky-view LUT 右侧
// 水平续接、同锚缓冲底边（原址 (0,0) = 天空盒预留区左下角，2026-10 八面体云层天空盒启用、
// [0,256)² 整块归还天空盒而迁此）；与天空盒 [0,256)² / 曝光 (258,0) / 标记 (259,0) / sky-view
//（x ∈ [260,460)）均不重叠
const int   AERIAL_LUT_W      = 64;  // 方位分辨率（texel）：aerial 是低频量、被距离维插值与 TAA 时间累积双重平滑，低于 sky-view 的 200；Mie 前向峰在 sqrt 参数化下光源侧 ~13 texel、bilinear + TAA 足够
const int   AERIAL_LUT_H      = 48;  // 天顶分辨率（texel）：方向参数化与 sky-view 互逆组共用（双段 sqrt 向地平线集中），分辨率独立
const int   AERIAL_LUT_SLICES = 4;   // 距离档数（y 向堆叠）：前 3 档有限等效距离 + 末档 ∞（天空渐近，不变式②）
const float AERIAL_DIST_SLICES[3] = float[3](1024.0, 4096.0, 16384.0); // 距离档位（等效米）：插值按线性距离权重（inscatter 未饱和段近似线性于 t，log 域 lerp 档间中点有 ~25% 系统性偏差）；**档 0 以下不设起始阈值、向相机线性归零**（短路径 inscatter ∝ t 的线性外推——整段早退跳过会在起始距离环留世界系固定的亮度阶，2026-09 实测可见后移除）；末段向 ∞ 档按 1 − S2/t 收尾（无穷远作线性端点 w 恒 0、直接跳档是档 2 距离环上的不连续）。SCALE = 64/9 下档位映射真距 144 / 576 / 2304 格（far 内到不了档 2、晴天不触末段）
// 观感强度主旋钮：等效距离放大倍数（真距 × 本值 = LUT 距离域）——中短距 inscatter ∝ t、缩放即强度
//（2026-09 两轮反馈自 64 连降至 64/9：64 时 far 端 ~70%+ 过浓、64/3 仍偏浓；64/9 后 144 格 ~2% / 576 格
// ~8% / far ~9%，远景边界由边界雾主导）。要中距离就明显可回抬（每 ×2 强度约翻倍）。改它不动档位表
//（档位是 LUT 的骨头、SCALE 只决定多远落哪档）。默认 7.111111 = 64/9 的十进制精确值（开放游戏内设置：
// 值表须单 token 可解析浮点，分数式 64.0/9.0 不能进值表——引擎滑杆定位按 float 解析；差 < 2e-5 逐位无感），
// 值表按 ÷2 / ×2 阶梯给档
const float AERIAL_RAIN_BOOST = 2.0;  // 雨天加浓：距离域乘子 (1 + 本值 × rainStrength)——保渐近不变式①（密度域调制禁用）
const float AERIAL_FOG_START  = 1.0 / 6.0; // 起始距离（×far，2026-09 按反馈接入；2026-10 按反馈自 far/3 拉近至 far/6——中近距看不出来雾）：约 far/6 内无雾——applyAerialPerspective 的**效果域** smoothstep 门（LUT 路径仍无阈值、档 0 以下线性归零见上条），fade 乘在「原表面 vs 雾化结果」的 mix 上；起点系数恒 0 且零斜率（C1）、环内外值同为 0，与首代「早退 = 0 / 环外立刻满档 LUT[S0]」的值阶环不同构，起始距离环结构性不可见；门内像素恒等早退、零 fetch
const float AERIAL_FOG_END    = 0.70;      // 渐满距离（×far）：此处起 aerial 全强（远端强度与门前逐位相同——SCALE 两轮反馈的调定不受门影响）；与 BOUNDARY_FOG_START 同值的接力锚（aerial 渐满即 boundary 开始融接），独立常量、改动须成对评估

// ---- 信标光柱（gbuffers_beacon，春雷同值）----
const float ALPHA_BEACON_CORE    = 254.1 / 255.0; // 不透明核心判定阈值（a >= 此值整像素写 gbuffer）
const float BEACON_CORE_EMISSIVE = 240.0 / 255.0; // 核心自发光强度（写入 specular.a，labPBR emissive）

// ---- 物品标记（colortex4 打包 albedo 的 a 通道 8bit 槽位）----
// a 通道在 cutout 判定后职责已尽、复用为物品类型标记，随 pack4x8To2x16 一同压缩（读取端
// unpack2x16To4x8(...).a × 255 判定）；编号对齐春雷 objectMarker 系（251 起），253~255 预留显式标记扩展



const float MATERIAL_NONE       = 0.0;           // 无标记；texcolor 经半透明混合的程序（entityColor / 手动合成）混合只影响 rgb，a 整像素置空
const float MATERIAL_VEGETATION = 251.0 / 255.0; // 植被：block.properties 显式列表 → mc_Entity → vsh 判定（春v2 IDMapping 同款五族，见 material.glsl 的 isVegetationId）；252 空缺、253~255 预留

// ---- block.properties 自定义方块 ID（mc_Entity.x；未定义方块 = -1）----
// ID 数值与 shaders/block.properties 成对维护（两文件无法互相引用，增改须两端同步）。
// **block.properties 恒纯 ASCII、零注释行**：Iris 加载前先用 C 预处理器（JCPP）过一遍 properties，
// # 开头的行按预处理指令解析、非 ASCII 字节直接 Bad token 抛异常，整份 ID 图随加载一起丢失
//（mc_Entity 全 -1、显式标记静默失效——Iris 1.10.9 实测踩坑；GLSL 文件的中文注释在 // 注释内、不受影响）。
// 说明文字写在本注释与 AGENTS.md，不写进 properties 本体。
// **方块名按版本分支 `#if MC_VERSION >= 11300`（春v2 同款列表照抄）**：1.13 扁平化改名（矮草 grass →
// 1.20.3 short_grass，两名并列同 ID、引擎忽略未知名）；双高植物上下半用 `name:half=lower/upper`
// blockstate 属性匹配拆开（不识别属性匹配的老加载器该行整体落空、高草回落空标记——SSS 缺失不破图）；
// 1.12− 双高植物共用 double_plant 一个 ID（整族含向日葵 / 丁香等花，老版本粒度限制）。老分支水双写
// 裸名 + 命名空间名：1.7 时代 properties 原生裸名，命名空间前缀为后加，老解析器二者择一命中、不认的
// 那个跳过，双写覆盖两种解析行为；GLSL 侧 ID 数值两分支一致、常量无分支
// 植被五族（春v2 materialIdMapper 的 IDMapping 同款，消费见 material.glsl 的 isVegetationId——
// switch case 字面量与本段说明成对维护）：
//   31 = 矮草 / 花 / 农作物（短植物）；10175 / 11175 = 双高植物下 / 上半（tall_grass 等，含上下两半
//   ——高矮草由此区分）；18 = 树叶 / 藤蔓 / 海草；10176 = 其他植物 / 片状物（苗 / 蘑菇 / 甘蔗 / 藻类等）
//   ——五族在春v2 各自驱动摇晃 / 阴影差异，本包统一映射 MATERIAL_VEGETATION（SSS 单档、无 waving）；
//   草方块 grass_block 不在列表（整方块无薄片透光，天然空标记无 SSS，勿加入）
const float BLOCK_WATER = 8.0; // 水 → shadow pass 焦散透射（春v2 同 ID：`water flowing_water`；消费在 program/shadow.glsl 的 shadowcolor0 写入侧，非 gbuffer a 通道标记——机制见「阴影贴图」水焦散条与 lib/lighting/caustics.glsl）

// ---- 植物晃动（lib/common/pipeline/waving.glsl，宏 1；方案移植自春v2 lib/wavingPlants.glsl，
//      其头注归属：搜狐畅游引擎部「渲染TA实战：模型草美术效果分享」zhuanlan.zhihu.com/p/609035535）----
// 判定复用 block.properties 五族（与 isVegetationId 同一列表）：31 / 10175 / 11175 / 18 四族晃动
//（各族幅度与顶点覆盖见 plantWavingParams——矮草与双高植物下半仅上顶点〔根部钉地〕、双高植物上半全顶点、
// 树叶全顶点含竖直分量）、10176 其他植物不晃（只吃 SSS）；gbuffers_opaque〔terrain〕与 shadow 两侧
// 同一函数、同一世界锚定 → 贴图阴影随几何同步晃；删宏 = 两侧一起停晃、逐位回到静止几何
const float WAVING_RATE             = 1.0;  // 晃动速率（时间轴倍率；春v2 默认档）
// 三族幅度倍率（游戏内设置）：矮草 / 花 / 苗（31 族，仅上顶点、仅水平）
// 双高植物（10175 仅上顶点 / 11175 全顶点，仅水平）幅度倍率
// 树叶 / 藤蔓（18 族全顶点、含竖直）幅度倍率
const float WAVING_NOISE_SCALE      = 1.0;  // 风场噪声尺度倍率（大 = 风团更大、空间相位更平滑）
const float WAVING_DISTANCE         = 60.0; // 晃动距离上限（格，春v2 同值——远处晃动亚像素化无意义且费顶点）
const float WAVING_FADE_RANGE       = 10.0; // 距离淡出带宽（本包平滑化；春v2 为硬门——按「距玩家世界距离」
                                            // 淡出，gbuffers / shadow 两侧同式同 cameraPosition、淡出同步无错位）
const mat2 WAVING_GUST_ROT = mat2(0.900447, -0.434966, 0.434966, 0.900447); // 阵风带朝向旋转（列主序，= 春v2 rotate2D(xz, +0.45) 逐位一致，与 CAUSTICS_ROT 互为转置〔角向相反〕）；三角值预算、编译期折叠（纪律同 CAUSTICS_ROT）
const float WAVING_GUST_SPEED = 12.0; // 阵风带平移速度（平移坐标 格/s——快摆幅度 mask 在世界中的推进速度；旋转系 x 经 ×3 拉伸，世界系沿旋转 x 的表观速度 = 值 ÷3。春v2 默认 32，调慢为缓行观感）

// ---- Bloom（lib/post/bloom.glsl，无阈值，整幅 HDR 直接进金字塔）----
// 泛光合成强度（tonemap 前线性域加法）
const float BLOOM_UW_STRENGTH_MULT = 10.0; // 水下泛光增益（2026-10 按反馈接入，final 消费）：isEyeInWater == 1 时 0.075 整体乘本值——水下雾把高对比亮部（Snell 窗内的天空 / 日盘、焦散亮网）包进低亮介质、泛光观感偏弱，抬档补介质感。**1.5 → 2.5 → 4.0 三档实机无感**（bloom 是 tonemap 前线性域加法，水下画面无 HDR 峰、金字塔内容为低对比雾色场，+30% 量级的加法经 AgX 压缩后不可辨），10.0 起加法量 ≈ 0.75 × 模糊场、与画面同量级才有可见的乳白介质感；只乘水下、水上逐位不变，1.0 = 无增益，嫌过冲在 4~10 间回调
const float BLOOM_BLUR_STEP = 2.0; // 下采样 tap 步长（源纹素数，春雷同值）：总模糊半径由回卷链逐级累积，单级无需大步长（步长 4 会跨步混叠给图集带入网格）
const float BLOOM_WEIGHTS[5] = float[5](1.0, 0.75, 0.55, 0.40, 0.30); // 各级权重（tile0 最锐 → tile4 最宽），上采样回卷相加时施加（bloomUpsampleTile）
const float BLOOM_WEIGHT_SUM = 3.0; // ΣBLOOM_WEIGHTS；getBloom 归一化，修改权重时同步更新

// ---- Tonemap（lib/post/tonemap.glsl；算子族自春雷 lib/post/simple_tonemap.glsl 移植）----
// 算子选择（游戏内设置，2026-10）：0 = AgX（默认，接入史实与现状逐位一致）1 = Filmic 2 = ACES
// 3 = Hable（= Uncharted 2 filmic，John Hable）。分派在 tonemap.glsl 的 applyTonemap（#if 编译
// 期裁剪、单算子进产物），其余管线（曝光 / 1 / bloom / linearToSrgb）不动。类目录形数值选项
// 不进 sliders——按钮形态逐档点名，滑杆的连续量语义不适用（本包数值选项全进 sliders 纪律的唯一
// 例外）。已知取舍：RCAS_SURROGATE_K 的代理曲线按 agx 灰阶定标，其他算子下 lobe 统计为近似
//（lobe 只依赖邻域单调统计量，代理域差仅轻微影响自适应增益）；调参史：三算子 ADDITIVE 预缩放
// 取春雷同值（其按自身曝光链定标，本包曝光链同源量级）
const float AGX_ADDITIVE = 0.6;       // AgX 曲线预缩放（与曝光系数各司其职：曝光在 tonemap 前整体乘；春雷同值）
const float min_ev       = -12.47393; // AgX log2 窗口下界
const float max_ev       = 4.026069;  // AgX log2 窗口上界
const float ACES_ADDITIVE    = 1.25;  // ACES 曲线预缩放（春雷同值）
const float FILMIC_ADDITIVE  = 0.2;   // Filmic 曲线预缩放（春雷同值）
const float HABLE_ADDITIVE   = 2.0;   // Hable 曲线预缩放（春雷 UNCHARTED2_ADDITIVE 同值）
const float HABLE_WHITE_POINT = 16.29; // Hable 白位点（whiteScale 归一，春雷同值）

// ---- 色彩滤镜（final，tonemap 前线性域：亮度增益 → 对比度 → 饱和度；2026-10 接入）----
// 施加点在曝光之后（自动曝光测光在 composite12、观感旋钮不被曝光反噬）、1 之后（锐化统计
// 不吃滤镜），三值 1.0 = 逐位直通。饱和度向 Rec.709 luma 收放（weather 降饱和同式，>1 时低通道
// 负过冲由 applyTonemap 入口钳非负）；对比度绕线性域 18% 中灰枢轴（不挪自动曝光锚定的中间调，
// >1 时暗端同样经入口钳）。亮度是纯线性增益、与自动曝光量级解耦（曝光乘在滤镜之前）
const float COLOR_CONTRAST_PIVOT = 0.18; // 对比度枢轴 = 线性域中灰（18%），不进设置

// ---- 1（lib/common/utils/filters.glsl rcasLobe + final 锐化，春雷同款：FSR1 Robust CAS）----
// 预处理 #if 不支持浮点比较，开关宏与数值常量分离（1 同纪律）
// 1 总开关（游戏内设置）：删本行 = final 的 1 段整体编译剔除（含 depth 与 4 次邻域 fetch）、
// 逐位回退接入前管线——调大 0.5 只压增益不省采样，低配关闭用本开关；
// SR 超分接管（SR_UPSCALE）时 final 侧消费点条件自动跳过（SR 算法族自带锐化、1 是给内置
// TAA/1 软感补的末级锐化，叠加过锐——跳过在 final.glsl 消费点而非本处 #undef：旧版 OptiFine
// 扫描器对失活分支也执行 #undef、会把本用户选项从设置里抹掉）；SR 生效期间本开关与档位不生效
// 锐化档位（stops）：0.0 最锐、每 +1.0 增益减半——TAA / 1 时间累积软感的末级补锐；
// 2026-10-11：按模糊反馈，默认由 1.0 降至 0.5（lobe 强度 ×sqrt(2)）；不提高历史采样锐度。
// 嫌锐度过强抬本值、嫌软降本值；1 重建核由 TAAU_KERNEL_BIAS 控制
// 噪声抑制（春雷同款默认开，游戏内设置）：邻域亮度波动大处压低锐化增益、不放大噪声 / 颗粒；
// 删本行 = 分支编译剔除、回退纯 1
const float RCAS_SURROGATE_K = 1.0; // lobe 统计的感知域代理曲线锚点（Reinhard x/(x+k)）：按 agx 灰阶三点定标（输入 0.18 / 1 / 10 → agx ≈ 0.16 / 0.55 / ~1.0，k=1 时 surrogate ≈ 0.15 / 0.50 / 0.91，中暗部贴合最紧）——代理只喂限幅 / 去噪统计（lobe 只依赖邻域单调统计量），域差仅轻微影响自适应增益；final 消费

// ---- 自动曝光（lib/post/exposure.glsl，亮度算法春雷同值）----
const float AUTO_EXPOSURE_RATE          = 2.0;     // 适应速度（1/s）：mix 因子 1 - exp(-frameTime * RATE)，帧率无关
const float AUTO_EXPOSURE_KEY_VALUE      = 0.18;    // 目标亮度（18% 灰 key），targetExposure = KEY / max(avgLum, BASE)
// 基础亮度地板：avgLum 直除前先抬到此下限，曝光上限 = KEY / 此值 = 18——无地板时深夜对数平均低至
// 1e-3、曝光冲到 90~720 倍把夜晚拉成白天。亮场景不受影响；嫌夜亮调大本值、嫌夜黑调小（有效旋钮是它，
// 不是 MIN_LUMINANCE）
const float AUTO_EXPOSURE_MIN_LUMINANCE  = 0.00025; // log(0) 防护；曝光上限已由 BASE 收口，本值仅作半精度绝对后备（KEY / 此值 = 720）
const int EXPOSURE_SAMPLE_COUNT = 16;              // 测光采样数：槽位 fragment 的测光成本与分辨率解耦（全遍历在 4K 下 2000+ fetch）
// 均匀随机采样核：4×4 抖动网格（每单元一个随机点），全域覆盖、无聚集，读取端映射回 tile4；固定核保证帧间稳定
const vec2 EXPOSURE_SAMPLE_KERNEL[16] = vec2[16](
    vec2(0.063, 0.061), vec2(0.302, 0.106), vec2(0.574, 0.038), vec2(0.811, 0.152),
    vec2(0.148, 0.306), vec2(0.421, 0.273), vec2(0.687, 0.342), vec2(0.934, 0.289),
    vec2(0.091, 0.537), vec2(0.356, 0.618), vec2(0.609, 0.555), vec2(0.873, 0.641),
    vec2(0.219, 0.766), vec2(0.473, 0.824), vec2(0.742, 0.779), vec2(0.951, 0.898)
);

// ---- TAA（lib/common/utils/noise.glsl + lib/post/taa.glsl）----
// 内置 TAA / 1 常量混合基线（2026-10-11）：有效历史固定注入 3% 当前帧。
// 默认唯一深度区间拒绝历史；固定TAAU另放宽颜色。关区间宏时为纯颜色档。
// 删除本宏切换自适应混合（速度 / 相位 / Karis / 手部下限），共用同一深度区间。

// TAA 诊断 A/B 档：源码手动改值，不列入游戏菜单；SR 接管时自动旁路。
// 0 = 正常；1 = 深度置信（红拒绝 / 绿接受，区间档显示 min/max 置信）；2 = 最终当前帧权重（白 = 1）；
// 3 = 总历史钳制改变量；4 = 极值硬盒改变量；5 = 方差盒软修正改变量。
// 三者均为 Reinhard-YCoCg 域距离 × TAA_DEBUG_CLIP_GAIN（白色可能饱和）。
// 诊断标量写 colortex6 闲置 alpha；RGB / 历史 / 测光保持正常，final 绕过后处理显示。
const float TAA_DEBUG_CLIP_GAIN = 16.0;

// 2026-10-14 1 高反差闪烁 A/B：历史用原始九点极值，当前色仍用相位去振铃盒。
// 删除本宏恢复原先共用边界；仅源码诊断，不列入菜单。原生 TAA 不受影响。

// 2026-10-14 debug 4 与闪烁重合后的 A/B：仅历史硬盒改为逐分量 clamp。
// 删除此宏恢复径向硬裁剪；原生 TAA 与方差盒仍走原裁剪。

// 高反差历史盒小幅余量 A/B：平坦区为零，只影响历史，不改重建去振铃。
// 工作域为曝光归一化 Reinhard-YCoCg；删宏回上一轮严格边界。
const float TAAU_HISTORY_MARGIN_SCALE = 0.03;
const float TAAU_HISTORY_MARGIN_FLOOR = 0.003;
const float TAAU_HISTORY_MARGIN_MAX = 0.02;

// ITT3.2 历史 3x3 深度 min/max 拒绝思想，转换为本包上一帧线性观察深度域。
// 所有内置 TAA 档共用唯一深度确认，中心先归约、接受后早退。
// 原生 / 1x 为 3x3；1 按 ceil(1/S) 扩圈（0.5~0.9 档 5x5），1~25 次读取。
// 仅固定 1 放宽颜色；删宏为不读历史深度的纯颜色档，不新增附件。
const float TAAU_DEPTH_RANGE_TOLERANCE = 0.01; // 区间外相对深度 1% 接受、2% 完全拒绝
const float TAAU_DEPTH_COLOR_GAMMA = 2.0; // 2026-10-15 可信历史扩张系数从 4.0 降至 2.0，收紧颜色 clip
const float TAAU_DEPTH_COLOR_Y_HEADROOM = 0.001; // Reinhard 亮度上界防逆映射放大

// 1 轻量重建与历史修正（2026-10）：不新增元数据缓冲。
// 下列速度 / 深度 / Karis 参数在 1 下仅为旧自适应回退或诊断保留。
const ivec2 taaCrossOffsets[4] = ivec2[4](ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1));
const float TAA_MOTION_LOW = 0.5; // 目标像素 / 帧；低速不启用偏心拒绝
const float TAA_MOTION_HIGH = 8.0;
const float TAA_RECTIFY_STABLE = 0.35; // 仅方差盒软修正；样本极值盒仍硬约束
const float TAA_RECTIFY_CHANGE_LOW = 0.05; // Reinhard-YCoCg 域颜色差异
const float TAA_RECTIFY_CHANGE_HIGH = 0.25;
// 自适应档仅可信低速高反差区域提高方差gamma；固定TAAU的深度验证放宽见上方。
const float TAAU_EDGE_CONTRAST_LOW = 0.08; // 曝光归一化 Reinhard 亮度跨度
const float TAAU_EDGE_CONTRAST_HIGH = 0.25;
const float TAAU_EDGE_CLIP_GAMMA = 2.0; // 2026-10-15 高反差边缘系数从 3.0 降至 2.0，与基础 / 深度可信档统一
const float TAAU_STAT_WEIGHT = 1.5; // exp2 距离统计权重，九样本与重建共享
const float TAAU_CONFIDENCE_POWER = 1.0; // 九样本正权重置信度；原生档置信度恒为 1
const float TAA_JITTER_SCALE = 1.0;  // jitter 幅度缩放（1.0 = 满幅 ±0.5 渲染纹素，即 1 纹素跨度；降低可换锐度）
// Halton(2,3) 8 相位序列（索引 1~8 减 0.5），每 8 帧循环。
// 2026-10-15 按用户要求由 32 相位缩短至 8；保留像素域幅度与投影 / 去抖关系。
// 查表纯 GLSL 实现，不依赖 properties 自定义 uniform（旧版 OptiFine 兼容）。
const vec2 TAA_JITTER_SAMPLES[8] = vec2[8](
    vec2( 0.0,    -0.16666667), vec2(-0.25,    0.16666667),
    vec2( 0.25,   -0.38888889), vec2(-0.375,  -0.05555556),
    vec2( 0.125,   0.27777778), vec2(-0.125,  -0.27777778),
    vec2( 0.375,   0.05555556), vec2(-0.4375,  0.38888889)
);
const float TAA_HISTORY_SHARPNESS   = 0.6; // 历史 Catmull-Rom 锐化系数（2026-10-15 从 0.65 下调至 0.5 后按反馈回调至 0.6）
const float TAA_CLIP_GAMMA          = 2.0;  // 方差钳制 γ 基础值（深度置信度高时用）：拉宽 μ±γσ 盒 = 提高历史通过率、少被截向当前邻域（输出更贴稳定的历史）；与样本极值盒交配合有天然上界——γ 放宽到超出双峰 σ 后 binding 侧落到极值盒、历史最多放宽到邻域真实样本，鬼影风险不随 γ 无限增长。自 1.75 抬（2026-10 远处物体闪烁 / 反射噪点反馈）：远物邻域统计双峰 σ 窄、历史被截即 Karis 失效（clipDistance=0 不再压注入）→ 恒定注入闪烁，抬 γ 让历史更常稳居盒内、Karis 防闪随之激活（双重收益）
const float TAA_CLIP_DISTANCE_GAIN  = 5.0;  // Karis 距离防闪增益（Kappa / Photon 同式同值）：历史稳居钳制盒内时把当前帧权重压向 0——恒定注入相位漂移的当前帧样本是静止细节闪烁的主源；工作域已含曝光归一化，距离不再乘曝光
const float TAA_OFFCENTER_REJECTION = 0.15; // 偏心拒绝强度（Zombye，Kappa / Photon / c13 同族取 0.25）：重投影落点偏离纹素中心（=有运动）时按比例抬高当前帧权重，削运动拖影 / 运动糊；自 0.25 下调——运动中的逐像素抬权幅度即逐像素注入方差，是移动 shimmer 的放大器，下调换边缘稳定（代价同 TAA_BLEND_MOTION）
// 1 下为有效历史的固定当前帧权重；旧自适应档含后续调制。
const float TAA_BLEND_BASE          = 0.03; // 当前帧基础权重（历史权重 0.97；原生档专用，1 见 TAAU_BLEND_BASE）。自 0.05 降（2026-10 远处物体闪烁 / 反射噪点反馈）：base 是静止区被截历史（Karis 失效）时的恒定注入下限，远处高频细节每帧注入的相位噪声即闪烁残余，降注入拉长时间累积窗换稳态；代价 = 运动后 / 解遮挡后收敛变慢（运动侧由 MOTION / DISOCCCLUSION 项单独补偿、不受影响），嫌拖影回抬
const float TAA_BLEND_MOTION        = 0.012; // 每像素速度的当前帧权重增量（运动收敛）；自 0.02 下调——移动时锯齿 / 抖动反馈：运动中当前帧注入越少、时间累积窗越长、边缘越稳；代价是无逐物体速度的动态实体拖影收敛变慢（方差钳制兜底），嫌拖影回抬
const float TAA_BLEND_DISOCCCLUSION = 0.4;  // 独立解遮挡更新下限系数；完全失配时强制当前帧 1.0
const float TAA_BLEND_MIN           = 0.01; // 当前帧权重下限（历史权重上限 0.99）；置信度 / Karis 防闪在其后施加、允许压破下限（下限防的是「无信息时不信任历史」，防闪是「有信息时明确信任历史」）。自 0.02 降（2026-10 同批反馈）：SSR 反射等过程噪声源（bayer 相位翻转的命中判定）靠历史主导平均，下限即其稳态噪声地板
const float TAA_BLEND_HAND_MIN      = 0.1;  // 手部当前帧权重下限（防手部拖影）
const float TAA_HAND_DEPTH          = 0.56; // NDC 深度阈值：小于此值视为手（BSL / Photon 同值）：TAA 手部路径判定 + 屏幕空间追踪阴影的遮挡者排除（shadow.glsl）——两处消费者成对维护
const float TAA_DEPTH_SENTINEL      = 65504.0; // 半精度上限：锚点深度上限 / 天空哨兵；历史几何区间排除此值，天空按邻域存在性

// ---- 1 时域上采样（子区域渲染 + composite_taa 解析上采样；关闭使用原生十字统计）----
// 机制 = c13 / Bliss 子区域缩放 + Photon / Kappa「TAA pass 即上采样器」（全貌见 AGENTS.md）：
// 几何渲染进左下 [0,S]² 子区域、像素成本 ×S²，composite_taa 上采样恢复全屏——bloom 链及之后零适配。
// jitter 有效幅度恒为 ±0.5 渲染纹素（注入在子区域缩放之后的 NDC 域，c13 / Kappa / Photon 三家同语义），
// 解析端在 buffer 域完整补偿 jitter（uv·S + jitterUV），与光栅注入互逆。颜色重建与深度搜索
// 共用该源位置；选出的深度锚点再完整去抖还原到无抖动视场，不以半补偿掩盖坐标错位。
// 预处理 #if 不支持浮点比较，开关宏与数值常量分离
// 渲染比例 S（像素成本 ×S²：0.75 → ×0.5625、0.7 → ×0.49、0.5 → ×0.25）；完整补抖 + 置信度门控 + 8 相位
// 修复后 0.5 可用，仍嫌软回 0.75；<0.5 不建议（目标像素网格更稀、上采样核欠采样）
const float TAAU_KERNEL_BIAS = 1.35; // 3x3 径向支撑：必须在 [4/3,sqrt(2)) 内，换中心时外侧权重为零
// 固定档通过深度验证时采用本值；区间拒绝另抬至1，不受速度 / 相位 / Karis 调制。
const float TAAU_BLEND_BASE = 0.03; // 1 当前帧基础权重（与原生档 TAA_BLEND_BASE 同值同调，2026-10 自 0.05 降——远处闪烁 / 反射噪点反馈，见其注释）：当前帧样本是相位噪声的注入端、base 即注入下限——历史权重 0.97，静止细节更依赖时间累积（配合相位置信度与历史防闪）；出现拖影 / 收敛慢回抬 0.08~0.12

// ---- SR 超分模组接管（配置 = shaders/superresolution.v3.json，Schema V3；接口文档
//      sr.187j3x1-114514.org——仅 Iris + SR mod + 配置有效时注入下列宏，未装 / 用户关闭 = 全部未定义）----
// SR_UPSCALE 为本包侧总门（一切 SR 专属代码的唯一开关；删除接入时回收本段 + superresolution.v3.json）。
// 接管四件事：
//   ① 渲染比例：派生 0.7（SR 接管 = SR 的 SR_RENDER_SCALE_FACTOR〔编译期宏，
//      比例档切换触发热重载〕、否则镜像内置 1 的 0.7 选项值），子区域机制消费点
//      （applyTAAJitter 缩放 / applyJitter / applyInverseJitter / outsideRenderRegion /
//      FULLSCREEN_RENDER_REGION / 材质 mip 梯度 / 1 重建 / water 折射 regionMax / SSR 域界）
//      统一消费派生名——**不再 #undef / 重定义 0.7 本名**（2026-10-12 低版本修复：旧版
//      OptiFine 选项扫描器对失活分支也执行 #undef/#define，无 SR 时也会把 0.7 选项的
//      值跟踪 / 改值行绑定劫持到 SR 行上——游戏内调 0.7 无效的根源；现选项本名只出现在
//      唯一的选项 #define 行，扫描器无从改错行）；「无手抖动档位不更新」的 SR_SCALED_WIDTH 族
//      禁止进 shaders.properties / 代码（0.7 亦非选项、不进）。1 门控放行为
//      「1 || SR_UPSCALE」——1 关闭 + SR 开启时子区域机制照常工作（final 深度映射原在此列、
//      2026-10 起随 1 在 SR 下整段剔除而回到纯 #ifdef 1，见下方 ④）；游戏内 0.7
//      选项在 SR 生效期间被 EFFECTIVE 旁路（改档无效，调 SR 侧）
//   ② jitter：noise.glsl 的 taaJitterSample 换用 SRJitterOffset uniform（mod 生成的相位序列，
//      与 Halton 表同一「渲染分辨率像素域」约定，applyTAAJitter / vJitter 全链自动跟进）。算法不
//      支持 jitter 时该 uniform = 0 = 不抖（此时本包 TAA 已旁路、自抖无解析端，宁可不抖）
//   ③ 抗锯齿 / 上采样：SR 算法族（FSR2 / DLSS / XeSS…）自带时域累积，composite_taa（composite3）
//      整 pass 透传旁路（colortex3 历史停写）；SR 在 composite3 前触发点读 colortex6（雾后线性
//      HDR）+ 深度（原版 noTranslucentDepthtex；VOXY 的 autotex20 合并独立 LOD 位置）+ colortex31
//      运动矢量、写回全屏 upscaled 色彩
//   ④ 末级锐化：final 的 1 段在消费点条件跳过（SR 算法族自带锐化，1 是给内置 TAA/1
//      软感补的末级锐化、叠加过锐）——1 宏本身不动（用户选项，跳过位置与缘由见其段注释）
// 运动矢量（写入端见 deferred_init / gbuffers_opaque_entities，取值实现 space.glsl 的
//   srSceneMotionVector / srEntityMotionVector）：colortex31 由 deferred_init（三维度共用的
//   deferred1 入口）写「相机重投影」底层 + gbuffers_entities 的 at_velocity 实体层（b 标记读回
//   保留）；用户关闭 SR 的 Iris at_velocity 扩展时 SR_ENTITY_VELOCITY 不定义、实体走相机 MV
// 名义渲染比例（非选项、不进 shaders.properties）。Voxy JSON 用字面值建立整数视口；
// SR 投影 / 重建改由 noise.glsl 的 renderRegionScale() 读取 SRScaledViewportSize，避免小数尺寸失配。
// SR 接管 = SR 档位；
// 否则镜像 0.7 选项值（1 删宏时选项行随之消失、本宏不定义——消费点全在
//「1 || SR_UPSCALE」门内，未定义即无消费，任何漏网引用会在编译期暴露）

// ---- 光照（lib/lighting/lighting.glsl，直接光物理化——春雷 shading.glsl 同构）----
// 统一时间系统（fullscreen_vsh 一次算好经 varying 传入；春v2 isNoon/isNight、春雷 isDay/isNight 同构）：
// 太阳 / 月亮各自世界高度的线性门。MC 日月恰好相对、两门永不同时为正——门控加权和即「按光源选边 +
// 切换瞬间（光源过地平线）双 0 黑过渡」，替代会提前混入太阳辐照度被透射率染红的旧昼夜 mix；
// 月亮门斜率倍陡：低角度月亮透射率已深红，门快速关闭把红月落压成暗过渡，太阳侧保留物理红化（红日出是预期）
const float TIME_NOON_RAMP  = 20.0; // 太阳直射门斜率（春v2 同值；20 = 高度 0→0.05 约 2.9° 淡入）
const float TIME_NIGHT_RAMP = 40.0; // 月亮直射门斜率（春v2 同值；40 = 0→0.025 约 1.4° 淡入）
// 直射 = albedo/π × (noon×SOLAR + night×MOON_IRRADIANCE) × solarTransmittance × NdotL × 阴影可见性；
// 大气顶辐照度与天空 LUT 同源（sky:direct 亮度比物理一致，量级随 SKY_BRIGHTNESS 统调）；环境 / 方块光同为辐照度形式
const float SKY_AMBIENT_BRIGHTNESS = 4.5; // 天空环境辐照度 = LUT 天顶色 × 本系数（vSkyAmbient 主路径）：半球换算 ≈ π × 1.7（余弦加权天光平均 / 天顶的正午比值）；统调天光亮度的主旋钮（2026-10 按反馈自 3.0 ×1.5 上调——漫反射天光整体提亮，回 3.0 逐位还原；自动曝光会吸收一部分全局增益，仍嫌暗继续 ×1.3~1.5 阶梯抬）
const vec3 DAY_SKY_AMBIENT   = vec3(6.4, 8.9, 17.6);     // 仅 LUT 无效回退路径生效（vSkyAmbient 回退 / sky.glsl fallbackSkyColor）；≈ π × 余弦加权天光平均；不随 SKY_AMBIENT_BRIGHTNESS 联动——本值同时是首帧渲染天空的回退色，随旋钮放大会闪首帧天空，旋钮抬后只影响首帧 / 缓冲重建帧（略暗于稳态、交 TAA / 曝光适应吸收）
const vec3 NIGHT_SKY_AMBIENT = DAY_SKY_AMBIENT * 5.0e-4; // 夜晚回退值 = 月亮辐照度比；正常路径只抬 MOON_IRRADIANCE 单旋钮
const vec3 TORCHLIGHT_COLOR  = vec3(1.00, 0.52, 0.20) * PI; // 方块光辐照度（π × 旧 albedo 直乘时代的量级，行为不变）
const float TORCHLIGHT_NEAR_SCALE  = 1.30; // 方块光近距离幂曲线主量级（lm.x⁴ 直乘系数）——shadeSurface 与前向简单半透明共用同式
const float TORCHLIGHT_FLOOR_SCALE = 0.02; // 方块光线性小地板（原始 lm.x 直乘，近距渐灭不断黑）
// 前向轻量着色亮度倍率（乘在 forwardLightmapShade 整体、单真源覆盖其全部调用方 = gbuffers_translucent
// 的玻璃等非水分支 + gbuffers_translucent_simple 的「deferred 之后」两档——雨雪 / hand_water / 粒子）：
// 这些路径无直射项（无阴影 / 法线，只有天光 + 方块光，阳光下显著暗于受光地形），2026-10 按反馈
//「玻璃 / 雨雾有些暗」整体提亮；forwardEntityShade（实体 after 路径、自带直射项）不受本倍率影响，
// shadeWaterSurface 的雾色亮度另有 WATER_FOG_BRIGHTNESS 族。已知取舍 = 倍率全天候生效：夜间直射
// 缺项本不存在，同比放大后玻璃 / 雨雪会亮过夜间地形一截，嫌夜间过亮改按 lm.y 分档加权（扩展点）；
// 改 1.0 逐位回退
const float FORWARD_LIGHTMAP_BRIGHTNESS = 3.0; // 前向轻量着色亮度主旋钮（3.0 = 2026-10 第二轮回抬，首版 2.0 嫌不够）
// 全黑环境兜底（gameplay 地板，刻意低于物理夜天光），避免纯黑不可见；下界 / 末地按维度分支取
//「维度环境地板」——下界无天光（has_skylight = false、lm.y 恒 0），本值即全部环境光；末地开阔处
// 环境光由 END_SKY_AMBIENT × lm.y⁴ 承担（见下条），本值兜檐下 / 岛内暗角。**两维度地板量级史
//（2026-10 两轮反馈）**：首档暖红 (0.055, 0.020, 0.014) / 冷紫 (0.020, 0.018, 0.030) 常亮不受 lm
// 调制，暗环境被自动曝光〔上限 18×〕放大成整屏泛红「岩浆余温」辉光 / 冷紫辉光（亮橙裂纹 albedo
// 上最显眼），曾按反馈整体归零（暗处回归原版纯黑、方块光 / 岩浆光照常）；同日二轮按反馈「无光
// 处避免纯黑」重新接入——量级压至主世界地板同档（亮度 ≈ 0.004，约首档的 1/7 与 1/5）、色相沿用
// 各维度原色：18× 曝光满档下典型 albedo 输出 sRGB ~0.1 的暗灰、可见而不辉光。嫌暗整体 ×N 回抬
//（亮度超过 ~0.02 量级将重现整屏辉光），旧档数值见 git 历史


const vec3 MIN_AMBIENT       = vec3(0.0035, 0.0040, 0.0055); // 主世界








// 直射天光门（2026-10）：天光可见度 lm.y（remapLightmap 后 0~1）经 smoothstep(LOW→HIGH) 映 0~1、
// 再 pow4 整形（三消费点各以「平方再平方」连乘实现、同 lmPow4 纪律免 pow 调用——窄窗内 smoothstep
// 起坡陡、过渡带观感硬，pow4 把爬升推向窗上沿、暗侧平缓趋零；调指数 = 增删连乘行）后乘进直射项
//（shadeSurface / forwardEntityShade / shadeWaterSurface 的 directIrradiance 族三消费点同窗同形）——
// 洞穴 / 深室内天光 ≈ 0，阴影贴图超距按全亮 + SS 追踪背光面 / 出屏放行的直射泄漏由此兜底归零。窗口
// [0.05, 0.10] 只切最深数档：vanilla 天光 16 级量化（1/15 ≈ 0.067 落窗内 → pow4 后 ~0.5% 直射、
// ≥ 2 级满额），树冠 / 檐下经传播衰减仍在 0.5 以上、不触窗。环境 / 方块光不门（各自已随 lm 幂曲线收敛）
const float DIRECT_SKYLIGHT_GATE_LOW  = 0.05; // 天光门下沿：≤ 此值直射归零
const float DIRECT_SKYLIGHT_GATE_HIGH = 0.10; // 天光门上沿：≥ 此值直射满额
// 直射 GGX 高光（2026-10，春雷 specularBrdfAnalytic 谱系）：shadeSurface 直射分支内加性叠加
// Schlick F × GGX D × Smith 相关 V 的单次散射镜面项（× NdotL × 阴影可见性 × 辐照度 × 天光门——与
// 漫反射直射项同源同门）。**不含春雷的多散射能量补偿**（其 msEnergy 需 BRDF albedo LUT 独立供给，
// 低配定位砍除：粗糙面高光略暗于全量档、光滑面无差）。输入 = colortex4.ba 解包的 labPBR 高光贴图
//（gbuffers 阶段已采样打包，读取端零新增 fetch）：r 感知光滑度 → α = (1−r)²、g 线性金属度 →
// F0 = mix(0.04, albedo, g)（金属高光取 albedo 着色；**diffuse 不做金属度衰减**——按需后接）；
// 无 specular 的资源包 r/g 恒 0 → α = 1 全粗糙 + 电解质 F0 0.04 = 全方块 ~4% 微弱菲涅尔泽光
//（与漫反射同量级），labPBR 资源包光滑面出太阳耀斑。只在直射确有贡献像素求值（零贡献门控复用，
// ~40 ALU、无新增采样）；删宏 = 整段编译剔除逐位回退
// 高光总强度（观感旋钮；1.0 = 物理量级——F0 4% 与漫反射同源亮度，0 = 视觉等价关但计算照跑，彻底关闭删上方宏）
const float SPECULAR_ALPHA_MIN       = 0.002; // GGX α 下限：镜面级光滑（r→1）防 D 分母爆炸（春雷 getPbrAlpha 同值）

// ---- 次表面散射（SSS，lib/lighting/lighting.glsl + shadow.glsl，春v2 deferred5 同构）----
// 薄叶透光近似（wrap 漫反射）：归一化强度 [0,1] 线性缩放两处——cosTheta wrap 重映射量（把明暗界
// 拓宽到背光侧，植被整株近均匀受光、明暗只由阴影贴图区分）与阴影 PCF 软化半径（tap 越出叶片自身
// 阴影边界使背光薄叶漏光、阴影边变软）；同一强度驱动，两处 _MAX 为档位锚点非独立旋钮。
// 强度来源 colortex4 标记（gbuffer_data.glsl 的 materialSSSStrength）
// 植被 SSS 强度 [0,1]，唯一调效旋钮（0 = 关闭、退化为 max(ndl, 0)；1 = 全档）
const float SSS_WRAP_MAX            = 2.0;  // 强度 1.0 全档的 wrap 量：ndl = 0 → 2/3、ndl = -0.5 → 0.5（默认 0.5 档再减半——温和背光辉光；春v2 plants 的 20 为近全透光档，故取保守量级）
const float SSS_SOFT_RADIUS_MAX     = 1.0;  // 强度 1.0 全档的阴影软化半径（texel）——过大会沿墙缘漏光，进游戏按需微调

// ---- 阴影（program/shadow.glsl 写入端 + lib/lighting/shadow.glsl 采样端）----
// 引擎指令前六条（shadowMapResolution 系 / sunPathRotation / shadowHardwareFiltering0 / noiseTextureResolution）由 OptiFine/Iris 扫描。
// 其中 shadowMapResolution / shadowDistance / sunPathRotation / ambientOcclusionLevel（通用区）已开放游戏内设置——
// 游戏内置 camelCase 指令是唯一可挂值表的 const 形态（行尾 [..] 由引擎回写），其余值不开放
// 阴影贴图边长（texel）；128m 距离下每米 8 texel，中心区经扭曲再放大约 6.7 倍
const int shadowMapResolution = 2048; // [1024 2048 4096]
// 阴影覆盖半径（米）；采样端超出即返回 1 全亮（贴图覆盖外无阴影，lib/lighting/shadow.glsl）——SS 追踪的
// 接管锚点全部按 ×D 表达、随本值自动缩放
const float shadowDistance = 128.0; // [64.0 96.0 128.0 192.0 256.0]
// 超出 shadowDistance 的几何不进阴影渲染（省填充率——超距采样本就按全亮）；与 shadowDistance 成对语义、不开放
const float shadowDistanceRenderMul  = 1.0;
// 太阳轨迹倾角（度，春雷同值）：正午太阳不过天顶、影子不退化；天空与光照方向自动一致
const float sunPathRotation = -30.0; // [-40.0 -30.0 -20.0 -10.0 0.0 10.0 20.0 30.0 40.0]
const bool  shadowHardwareFiltering0 = true;   // 仅 shadowtex0 开硬件深度比较（sampler2DShadow）；shadowtex1 保持 sampler2D 裸深度（仅不透明几何）——彩色阴影遮挡分离与未来 PCSS blocker search 共用的后路（春v2 同布置）
const int   noiseTextureResolution   = 256;    // 引擎程序化噪声纹理边长（texel），OptiFine 默认档；水焦散波场（lib/lighting/caustics.glsl）唯一消费者。参考：BSL 同参数族取 512（texel 密度翻倍更平滑、采样带宽翻倍），春v2 经 texture.*.noisetex 换自备 128 模糊纹理——本包不引资产、用引擎生成档
const float SHADOW_DISTORT_FACTOR = 0.85;  // 线性扭曲强度（春v2/BSL/Kappa 同族）：中心 factor = 0.15、纹素密度放大约 6.7 倍，边缘不缩放
const float SHADOW_DEPTH_SCALE    = 0.2;   // shadow clip z 压缩（BSL/Photon/Kappa 同值）：写读两侧对称，配合常数 bias 抑制痤疮
const int   SHADOW_PCF_SAMPLES         = 12;   // 黄金螺旋 tap 高档（硬件比较 2×2，等效 48 次深度比较）：大盘专用——半径超 SHADOW_PCF_LOW_TIER_TEXELS 的像素（SSS 软化 / 雨天 / 远距），密度不足会噪
const int   SHADOW_PCF_SAMPLES_LOW     = 6;    // 黄金螺旋 tap 低档（等效 24 次比较）：小盘专用——噪声取决于 tap 密度（tap 数 ÷ 盘面积），24 次对 π·2.5² ≈ 20 texel 的盘仍过采样、砍半无感；两档共用 SHADOW_PCF_DIRS 表，仅径向归一化分母随档变化
const float SHADOW_PCF_LOW_TIER_TEXELS = 2.5;  // 低档分界盘半径（texel）：多数像素（近处 / 晴天 / 非 SSS）落低档
// 黄金螺旋基准方向 (cos(i·GA), sin(i·GA))：采样端 sincos 外提后逐 tap 只剩 mat2 旋转乘查表
// （角度恒等 theta_i = i·GA + φ 与原式逐位相同）。以高档 SHADOW_PCF_SAMPLES 定长、两档共用
// （黄金螺旋前缀仍均匀）；改高档 tap 数须同步本表条目
const vec2 SHADOW_PCF_DIRS[SHADOW_PCF_SAMPLES] = vec2[SHADOW_PCF_SAMPLES](
    vec2( 1.000000000,  0.000000000),
    vec2(-0.737368878,  0.675490294),
    vec2( 0.087425725, -0.996171041),
    vec2( 0.608438860,  0.793600752),
    vec2(-0.984713485, -0.174181950),
    vec2( 0.843755295, -0.536728053),
    vec2(-0.259604305,  0.965715074),
    vec2(-0.460907025, -0.887448429),
    vec2( 0.939321296,  0.343038631),
    vec2(-0.924345556,  0.381556408),
    vec2( 0.423845995, -0.905734273),
    vec2( 0.299283864,  0.954164120)
);
const float SHADOW_RADIUS_BASE    = 0.25;   // 基础软半径（texel）
const float SHADOW_RADIUS_DIST    = 2.0;   // 随相机距离增长的半径上限（texel）
const float SHADOW_BIAS_NORMAL    = 0.05;  // normal offset 基数（世界单位，随距离 / 坡度放大，春v2 同思路）
const float SHADOW_BIAS_DEPTH     = 0.00005;// 压缩后深度域常数 bias（进游戏按痤疮 / 悬空影微调）

// ---- 水焦散（program/shadow.glsl 写入 shadowcolor0 + lib/lighting/caustics.glsl 图案 + lib/lighting/shadow.glsl 彩色阴影分支消费）----
// 春v2 computeCausticsWithDispersion 纯色移植（色散分支删）：世界坐标经 缩放 → 旋转 → 压扁 → 时间
// 平移 后采样 noisetex 双通道，(1-g) × mix(r, 1, MOD) 组合、pow 提对比成焦散网——零差分 / 零 fbm。
// 2026-10 噪声 3D 化（SEUS 3D-from-2D、z 维 = 时间演化 CAUSTICS_EVOLVE——平移的同时图案换形、
// 根治刚性平移感；与水波高度场 lib/water/waves.glsl waterNoise3D 同构造）：双通道 × 层间插值 = 4 fetch
//（原 2D 单 fetch 为 1）；压扁使波纹沿旋转后 x 拉长成条带状涟漪。**shadowcolor0 为 RGBA8、值域上限 1**：
// rgb = 生物群系水色 tint × 网强度（网谷 CAUSTICS_BASE → 波前 1.0）、a 通道 = SHADOW_COLOR_WATER_A
// 水标记（其余透射几何恒 1.0）；读取端识别标记后 ×2.0 重建 >1 的 HDR 焦点
//（春v2 color.a = 0.5 同款标记思路；下游 colortex6 线性域无截断）。删 1 宏 = 水回退
// 原透射色路径（纹理色 tint、a = 1 无标记，读取端水分支自动失效），varying 一并编译剔除
const float CAUSTICS_SCALE = 0.006; // 缩放：世界块 → noisetex uv。texel ≈ 0.65 块（春v2 CAUSTICS_FREQ 0.03 × 128³ 噪声的等效密度折算到 256 noisetex 为 0.015 / texel 0.26 块；2026-10 按反馈两轮调稀：×2/3 至 0.010 仍嫌密、再至 0.006——累计放大 2.5 倍）；网嫌大嫌密调本值——**改本值须同比缩 CAUSTICS_DRIFT（噪声域速度），否则世界系滚动速度随密度联动**
const mat2  CAUSTICS_ROT   = mat2(0.900447, 0.434966, -0.434966, 0.900447); // 旋转（列主序，与春v2 rotate2D(xz, -0.45) 逐位一致：其矩阵形 [[c,-s],[s,c]] 配负角净效果 = 逆时针 0.45 rad）；三角值预算、编译期折叠免运行时 sincos。**改本矩阵的转角方向会连带翻转水流轴向（与 DRIFT 符号共同决定世界系流向），与春v2 对齐时勿只改角度不改符号**
const float CAUSTICS_SQUASH = 4.0; // 压扁：噪声 y 向频率 ×4 → 波纹沿旋转后 x 拉长成条带状涟漪（春v2 z×4 同值）；条带拉长比主旋钮
const vec2  CAUSTICS_DRIFT = vec2(0.0, 0.020); // 时间平移速度（uv/秒，沿旋转系压扁轴；caustics.glsl 侧 -= 与春v2 `sampleUV -=` 同号——图案沿压扁轴正向滚动）：世界速度 = 本值 / CAUSTICS_SCALE ≈ 3.3 块/秒（春v2 CAUSTICS_SPEED 0.13 折算）——2026-10 两轮调稀密度时同比缩放（0.065 → 0.0433 → 0.026）保持世界流速不变；2026-10-08 按反馈放缓：减半档 0.013（≈2.2 块/秒）实测过慢回退，取 0.020 温和档
const float CAUSTICS_EVOLVE = 0.8;  // 三维噪声 z 维演化速度（lattice 格/秒，2026-10 焦散 3D 化接入）：z 走 1 格 = 图案换一副不相关的网——DRIFT 平移的同时形态沿 z 连续换形（与水波高度场的 z 维同职责），根治「刚性平移感」；波形侧同构造 z 速率 ≈ 0.675（WAVE_SPEED 1.5 折算），初档取同量级；2026-10-08 按反馈 0.6 → 0.8 加快形态变化，DRIFT 平移速度不动。嫌变得快降本值、嫌图案死板抬
const float CAUSTICS_MOD   = 0.8;  // 次级通道调制权重：web = (1-n.g) × mix(n.r, 1, 本值)（春v2 同值）；嫌网碎抬 → 次级调制更弱、图案更由主通道独挑
const float CAUSTICS_POWER = 3.0;  // pow 收网对比度（春v2 同值）：网稀嫌淡降、嫌网满抬
const float CAUSTICS_TILT  = 0.2;  // 采样平面 y 斜置系数（BSL 同值）：xz − y·TILT——流动水面不同高度错开图案平面，跌水 / 阶梯水免竖直条纹
const float CAUSTICS_BASE  = 0.22; // 存储背景（网谷）：读取端默认 ×BOOST 后 = 0.44×tint
const float SHADOW_COLOR_WATER_A    = 0.5;  // shadowcolor0.a 水标记值（RGBA8 量化 128/255；非水几何恒写 1.0）
const float SHADOW_COLOR_WATER_TEST = 0.75; // 读取端水标记判定阈（texelFetch 精确纹素，0.5 与 1.0 的中点）
// 读取端 HDR 重建系数：vis = 存储 rgb × 本值——默认网谷 = 0.44×tint、波前 = 2.0×tint（直射光水下焦点亮度；
// 春v2 BRI_MIN/MAX 1.0→4.0 档两端折算，低配定位取收敛值）。实机 PCF 盘平均 + TAA 时间累积会再抹平一档。
// **人眼在水下时整体乘渲染点 lm.y 的 pow2**（焦散水深门，2026-10 按反馈——人在水下时水越深焦散越浅：
// lm.y = 天光级、水下随水深逐格衰减即水深代理；线性首档经 AgX 后不可辨、pow4 首档水下太黑，pow2 折中；
// 水上恒 1 原观感不变，见 shadow.glsl「焦散水深门」段）
// 2026-10-08 按反馈调浅：默认 2.8 → 2.0；保留旧档供玩家选择。

// ---- 屏幕空间追踪阴影（lib/lighting/shadow.glsl screenSpaceShadowVisibility + lighting.glsl 接入，方案见 plans/屏幕空间追踪阴影方案.md）----
// 沿主光源方向对 depthtex1 世界空间 ray march，一档追踪兼两职：近景补接触细节（normal offset /
// PCF 模糊吃掉的小影），远景接管（贴图 0.9D→D 淡出后为唯一阴影源，视距远超 shadowDistance）。
// 机制春v2 谱系（screenSpaceShadow.glsl + deferred5 调用点）、公式自研重写；与贴图可见性取 min
// 只加暗，temporalBayer64 抖动起点相位、composite_taa 时间累积收敛（与 PCF 同一收敛机制）。
// 适用范围：近景（< NEAR_BOUNDARY·D）只 trace 向光非 SSS（保薄叶透光）；远景向光或 SSS 均可，
// SSS 结果在 NEAR_BOUNDARY→HANDOVER 从 1.0 渐入全效——HANDOVER 同时是贴图淡出窗起点，
// 0.7 / 0.9 / 1.0 三锚点交接链。开关宏与数值常量分离（1 同纪律）；命名不缩写 SSS
//（本包语境已被次表面散射占用）
const int   SHADOW_SS_STEPS          = 8;    // 步数：temporalBayer64 64 相位 × TAA 补采样密度（Photon 10 / Bliss·Kappa 16 / 春v2 5，居中）；步序同时是命中软化分档（N 越大帧内梯度越细）；极低配降 6
const int   SHADOW_SS_CONTACT_STEPS  = 3;    // 接触死区步数 K：命中步序 i ≤ K 不软化、整像素全影——近端 trace 的职责是把贴图被 normal offset 浮空带（SHADOW_BIAS_NORMAL 0.05 格起、掠射背光放大至 ~0.11 格）与 PCF 模糊吃掉的接触影满强度补回，软化补不上；两者合计的接缝带至 ~17 cm，K=2〔死区 ~10 cm〕实测补不满、抬到 3（死区 ≈ (K+1)×步长 ≈ 20 cm 覆盖，随 trace 长度自动缩放）；再抬的代价 = 软化段最大深度变浅（(N−1−K)/N）、接管区全影范围扩大
// 起点偏移：5 格近端与 shadowDistance 锚点；D 外平方根增长，保留薄遮挡。
const float SHADOW_SS_START_BIAS_NEAR = 0.01;
const float SHADOW_SS_START_BIAS_FAR  = 0.03;
// D24 误差按距离平方估计；推移量限于 FAR 偏移，避免精度保护抹掉薄遮挡。
const float SHADOW_SS_DEPTH_BIAS_ULPS = 2.0;
const float SHADOW_SS_LENGTH_NEAR    = 0.4;  // 近距追踪长度（格，dist ≤ 5 格锚点）：接触阴影主尺度（楼梯棱 / 草根）；长度同时定软化段深浅——死区外命中返回 (i−K)/N，抬长 = 同一遮挡落更早步序 = 更深
const float SHADOW_SS_LENGTH_FAR     = 10.0; // shadowDistance 处长度（格，D 外继续线性增长）：远景接管的山体尺度；嫌远景噪声 / 肥影先降此值、嫌步序软化后接管影整体偏浅则抬此值
const float SHADOW_SS_THICKNESS_NEAR = 0.1;  // 命中窗 3D 距离基数（格）：近中景紧窗防薄几何自命中
const float SHADOW_SS_THICKNESS_FAR  = 10.0; // D 处命中窗（格，D 外按距离比例线性增长）：接管区容表面起伏 + 步距透视放大；自春v2 的 20 收紧——本包无雾，远场掠射退化（径向序对海拔二阶不敏感、命中退化为噪声翻转）直接可见，肥窗放大边界描黑
const float SHADOW_SS_EDGE_START     = 0.75; // 渲染边界淡出起点（×far，相机远平面 ≈ 渲染半径）：远边界掠射带的命中判定退化为噪声、经 TAA 平均成沿边界的渐变描黑——自此处向边界淡出（修复实测问题）
const float SHADOW_SS_EDGE_END       = 0.9;  // 渲染边界淡出终点（×far）：边界带回退无影（本效果接入前的原状态，优于描黑）；接管主体 0.9D → EDGE_START·far 不受影响，嫌边界仍有暗带先抬 START
const float SHADOW_SS_NEAR_BOUNDARY  = 0.7;  // 近/远景分界（×D）：近景不 trace SSS（保透光观感）、远景 trace（保接管，树冠在 0.9D 外必须有影）
const float SHADOW_SS_HANDOVER      = 0.9;  // 接管窗起点（×D）：SSS 渐入终点 = 贴图淡出起点，交接链三锚点（0.7 / 0.9 / 1.0）
const float SHADOW_SS_GATE          = 0.01; // 贴图可见性门（最大通道）：全影像素不 trace——最便宜的性能门（春v2 早退同款）；D 外贴图恒 1、门自然放行
// 整体不透明度（0~1）：接触影 / 接管影轻重的第一调效位
const float SHADOW_SS_FAR_SCALE     = 1.0;  // D 外整体缩放（春v2 取 0.9 微减弱接管区噪声观感，默认不采纳）

// ---- 水面（lib/water/*〔2026-10 自 lib/lighting/water.glsl 按功能拆分：waves / fog / ssr / reflection / surface〕；接入 = gbuffers_translucent〔water 入口〕+ composite_fog 水下雾）----
// 前向水面框架（方案移植自春v2 lib/water/*，前向组合式样见其 gbuffers_water / deferred21）：水面恒
// deferred 后绘制，程序保持引擎混合（2026-10 回归修复：水输出整像素最终色 + alpha 1.0，ROP
// srcAlpha/1−srcAlpha 下 = 精确替换、与关混合直写逐位等价；同 draw 玻璃等半透明直通 alpha、ROP
// 原子叠层——曾整 draw 关混合迫使玻璃手动 mix，同 draw 重叠片段读改写竞态 = 玻璃叠玻璃 / 玻璃与
// 水交叠逐帧闪烁）——折射背景 = gaux1 背景快照位移采样 + depthtex1
//（仅不透明）背景深度，水雾 = 彩色吸收 + 满深 mix 雾色（雾基色只取顶点色、不含纹理色），反射 =
// 屏幕 SSR（未命中回退天空 LUT + 解析太阳盘 + **烘焙云层天空盒**——colortex7 八面体槽位单 fetch
// 预乘合成、反射路径不重算云，2026-10 接入）经 Fresnel 混合。**水波法线不走局部 TBN**
//（春v2 deferred21 路线）：波形高度场按世界 xz 求值，法线 = 世界系三点高度差分叉积——与纹理坐标 /
// 几何导数无关，折射与反射共用同一世界法线。玻璃等同 draw 的其余半透明方块经 mc_Entity（block.8）
// 运行时分流、走轻量光照 + ROP 直通。开关宏与数值常量分离（1 同纪律）；删 1 =
// 上下两个方向的吸收雾整体编译剔除（纯清水：折射 + 反射仍在）。常量名对齐春v2 便于对照调参
const vec3  WATER_FOG_COLOR        = vec3(0.20, 0.83, 0.80); // 雾基色（水上透过水面的深水雾与水下整屏雾两路共用；春v2 默认档 0.20/0.75/0.90，2026-10 调参往返：两轮改绿至 0.20/0.85/0.75 过浓 → 回青蓝档 → 再改绿一档至此——BIOME_MIX 归零后纯色绿感比 biome 时代同数值更重，调参以实机为准）；归一化 [0,1] 域：吸收系数 = 1 − 基色。曾短暂与水下路分离、旋即按反馈合并回单值；2026-10-08 按截图略偏绿：0.20/0.80/0.85 → 0.20/0.83/0.80，保留青色、不回浓绿档
const float WATER_FOG_BIOME_MIX   = 0.0;  // 生物群系水色（水几何顶点色）混入雾基色的权重：默认水 tint 相当蓝（线性域 B ≈ 0.76 vs G ≈ 0.19），0.5 混入会把调好的绿色稀释成蓝——「改绿了看着还是蓝」的实测根因，2026-10 归零（雾色所见即所得 = 纯常量色）；代价是沼泽绿水与普通水同色，想找回生物群系差异回抬本值（≤ 0.1 才能保住 G 主导）
const float WATER_FOG_SUN_SCALE   = 0.125; // 直射辐照度对雾色亮度的系数（春v2 fogColor 的 sunColor × 0.125 同值）：去饱太阳色调制直射贡献
// 水下雾独立太阳项系数（2026-10-08）：0.125 → 0.10，降低白太阳项对雾的抬亮；水上档不动。
const float WATER_UW_SUN_SCALE    = 0.10;
const float WATER_FOG_SKY_SCALE   = 0.10; // 天空环境（vSkyAmbient）对雾色亮度的系数（本包适配：春v2 无此项）——**水上路**；水下走 WATER_UW_SKY_SCALE（2026-10 分离）
const float WATER_UW_SKY_SCALE    = 0.30; // 天空环境项系数——**水下路**（2026-10 按反馈「水下雾偏白偏灰」分离抬档）：白天的雾色由半去饱和白太阳项主导（≈236×0.125 ≈ 29.5）vs 天空蓝项仅 ≈ skyAmbient×0.1，蓝项占比过低 = 雾发白发灰的根因之一；水下抬至 0.30 把雾色拉回青蓝。水上路多轮调参收敛、不随动；嫌还白继续抬本值
const float WATER_FOG_BRIGHTNESS  = 1.0 / 24.0; // 水上雾色亮度总旋钮（2026-09 两轮反馈下调：原档满照雾色正午量级偏亮、实机观感「像自发光」，先 ×1/3 再 ×1/3——累计 1/9；2026-10 两轮续降：1/18 再 ×3/4 至 1/24）：乘在 waterFogLitColor 三项之和（直射 + 天空 + MIN_AMBIENT 地板）上；2026-10 与水下路分离（水下走 WATER_UW_FOG_BRIGHTNESS）；嫌淡按倍率回抬（观感近线性）
const float WATER_MIST_VISIBILITY = 12.0; // 满雾水深（格，春v2 同值）：水深超过此值背景完全变雾色
const float WATER_FOG_TRANSMIT    = 0.5;  // 水深吸收斜率（春v2 WATER_FOG_TRANSMIT 同值）：exp(−(1−基色)·深·本值)，红通道衰减快 → 深水偏蓝
// 水下雾满强视距（格，composite_fog 水下分支）：春v2 UNDERWATER_FOG_MIST 50 偏清、按 MC 观感收紧至 24；
// 2026-10 三轮按反馈回抬降浓度——24 → 36 → 48 → 64（中点 12 格遮盖权重 39% → 28% → 22% → 17%，嫌还浓继续抬）
const float WATER_UW_TRANSMIT     = 0.28; // 水下距离吸收斜率（composite_fog 水下分支；与 WATER_FOG_TRANSMIT 分离独立调；2026-10 随 VISIBILITY 三轮同步下调：0.5 → 0.4 → 0.33 → 0.28）
const float WATER_UW_FOG_BRIGHTNESS = 1.0 / 18.0; // 水下雾色亮度旋钮（结构同 WATER_FOG_BRIGHTNESS、作用 waterFogLitColor 三项之和；基色两路共用 WATER_FOG_COLOR）：分离时取 2026-09 两轮反馈的收敛值 1/9，水上路的续降不波及水下；2026-10-08 按反馈 1/9 → 1/15，雾色整体降低 40%（直接观视与水下 SSR 命中雾同源）；同日按截图再至 1/18（比 1/15 再降约 17%）
// 水下物体额外彩色吸收（2026-10-08）：仅眼睛在水下且 1 开启时生效。
// 深度代理 = 1 − lm.y²（与焦散天光 pow2 门互补），独立于眼到物体的距离雾；
// exp(−(1−WATER_FOG_COLOR)·代理·本值)，红光比蓝光衰减快，近处深水物体也呈水色。
// 0 = 关闭；不判物体是否在水中，水下看低天光岸壁 / 洞穴亦会偏色（按反馈接受的近似）。
const float WATER_UW_SURFACE_ABSORPTION = 2.0;
// 双重吸收后的水下物体亮度补偿（2026-10-08）：只乘物体着色，不提亮雾，不改指数吸收强度。
// 1.0 = 无补偿；地形 / 实体 / 简单半透明共用，1 关闭或眼睛出水时不生效。
const float WATER_UW_SURFACE_BRIGHTNESS = 1.35;
// 水下雾环境光门（2026-10「无光水下雾依然很亮」修复；首版「线性 × 无地板」两轮调参后整形）：
// eyeBrightnessSmooth 的**天光分量**（0..240）归一后经「幂 + 地板」整形乘进 waterFogLitColor 整体
// ——雾色光照的 vDirectIrradiance / vSkyAmbient 是帧级 varying（海平面天空条件、无位置信息）、
// MIN_AMBIENT 是常数地板，洞窟 / 深水 / 桥影下眼位天光衰减到 0 时三项照付 = 无光水下雾恒亮的
// 根源；天光分量承载位置遮挡（天光级夜间不降、昼夜量级由 varying 自带）。**方块光分量不参与**
//（2026-10 按反馈剔除——火把 / 海晶灯的暖色雾照未建模，max 混入只会让光源旁雾色凭空偏亮；
// 方块光暖色贡献为扩展点、接入时单建一项）
const float WATER_UW_ENV_LIGHT_SCALE = 1.0 / 240.0; // 单位换算（0..240 光照级 → 0..1），非调参旋钮
const float WATER_UW_ENV_POWER = 2.5;  // 感知线性化幂（首版线性门：雾色是 HDR，线性缩放经 AgX 压缩后高段不敏感——亮度骤变全挤在极低光照段、中段几乎看不出变化；pow 把变化摊到全量程，2.5 为按该压缩形状的收敛值）
const float WATER_UW_ENV_FLOOR = 0.001; // 亮度地板（首版归零档实测：环境光到最小值时雾彻底消失、水看起来像空气——保住最低能见度的暗雾；0.2 → 0.1 → 0.01 → 0.001 四档按反馈嫌亮续降，近归零、仅防整支消失，归零即回无地板档）
// ---- 波面漫反射起伏（2026-10 接入，「水面光照平」的拟合——起伏只调制雾色光照的直射项；零 march、
// 零新采样，见 lib/water/surface.glsl 水雾段。曾同期接入的水体 SSS〔逆光透射相位，GDC 2011 fake
// translucency 谱系〕两轮调参后逆光对齐带观感仍不自然、按反馈整体移除，git 历史含完整形态）----
const float WATER_DIFFUSE_STRENGTH = 1.0;  // 波面漫反射起伏权重（0 = 无起伏回退档、雾色只剩平稳环境底）：直射项乘 mix(1, N·L^power, 本值)；旧档（春v2 lightFactor：三项和整体 × mix(1, N·L, 0.5)）把天空环境 / 地板一并压平，且波面法线倾角 ~24° 下正午 N·L 实际波动仅 ±3%——水面「光照平」的根源
const float WATER_DIFFUSE_POWER    = 3.0;  // 起伏对比锐度（pow 指数）：迎光 / 背光波面的雾色明暗比，N·L∈[0.9,1] 经 ^3 → 太阳项波动 ~27%（旧档 ~10 倍）；嫌平淡抬本值
// ---- 波形 / 视差 / 折射 / 反射（1 之外的水面效果常量，gbuffers_translucent 消费）----
const float WAVE_SPEED            = 1.5;  // 波形时间速度倍率（春v2 默认档）
const float WAVE_FREQUENCY        = 1.0;  // 世界 xz → 波形域频率（春v2 同值）：特征尺度 ~2.9 格
// 波幅档位（春v2 同值；type1 以 pow(本值, 1.35) 混入高度 = 法线坡度的实际旋钮；再乘掠视角衰减
//〔|dot(视线, 水面几何法线)| 线性——见下方注记，俯视全幅、掠视趋平〕）
// 2026-10-08 恢复低频粗糙度 mask：波团疏密变化；每水像素共享两次采样。删宏回均匀波幅。
// 2026-10-08 按反馈暂时关闭（游戏内 WATER 子屏仍可重新打开，或取消下行注释恢复默认开启）。
//#define WAVE_ROUGHNESS_MASK
// 足迹过滤仅法线侧：保留第一 octave，不恢复远距整波幅淡出。
const float WAVE_FILTER_LOW = 0.35; // 高频 octave 噪声域像素足迹
const float WAVE_FILTER_HIGH = 0.85;
const float WAVE_FILTER_NORMAL_SCALE = 0.35;
const float WAVE_FILTER_NORMAL_MAX = 0.5; // 差分上限（格），避免远水全平
const float WATER_SSR_CONFIDENCE_START = 0.65; // 原验证带内最后 35% 连续转天空，不扩大接受域
const float WAVE_NORMAL_EPS       = 0.05; // 世界差分步长 ε（格，春v2 getWaveNormalDH 同值）：三点高度差分的水平间距
//（曾有的 WAVE_FADE_START/END 波形距离淡出〔24→64 格到平水面〕已按反馈移除——2026-10 嫌远水太平，
// 远水按像素足迹过滤第二层高频，保留基础波与平均高度；剩余噪声交 TAA 累积。同月二次改版：换成
// 掠视角衰减——波幅混入系数直接乘 |dot(视线, 水面几何法线)|〔水平水 = sin 仰角；点乘 1 完全粗糙 /
// 0 完全平坦，无整形窗——首版 smoothstep 窗 WAVE_GRAZE_LOW/HIGH 0.05/0.35 旋即按反馈简化为
// 裸点乘线性档，git 历史含完整形态〕，shadeWaterSurface 消费：掠视〔波特征被 1/仰角透视放大到
// 亚像素的闪烁带〕趋平水、俯视全波幅，按视角压平不误杀高处俯视的远水。与 WAVE_FILTER_* 足迹
// 过滤叠加分工：足迹过滤砍高频 octave（按像素采样密度）、掠视角衰减砍整支波幅（按视角），两者
// 独立生效。衰减 0 时高度恒 1（平水基准）——法线恒 up、视差 g0 = 0 自然跳过，整支波形消费随
// 系数一致收敛）
// 掠视角衰减玩家旋钮（2026-10 接入设置屏）：开关宏 + 嵌套强度（1 /
// 1.0 同款形态——父开关关闭即强度自动隐藏、无悬挂）；删 1 定义 =
// 衰减整段编译剔除、全视角全波幅（逐位回退）。强度语义：1 = 裸点乘线性（掠视完全平坦，默认档
// = 接入时行为）、中间值经 mix(1, |dot|, 强度) 内插（0.5 = 掠视水保留一半波幅）；0 档由开关
// 承担、值表不含 0
// 水面「水平面假设」族共用的几何面水平度门（|世界几何法线 · up|，导数法线由 gbuffers_translucent
// 先于 discard 求好传入），低于本值（陡坡流动水 / 瀑布竖直流面）触发两处跳过：①「未抖动视线 ∩
// 水平面」的去抖替换——水平面假设在竖直流面上把水面点横向搬离真实几何几格，波形采样无锚定无感、
// 但 SSR march 起点随 viewPos 前移 = 反射从错误位置发出（2026-10 修复）；②WAVE_PARALLAX 视差段
//（隐式面 = 水平面下方波高场）——竖直面无意义，且 |视线.y| ≈ 0 的一阶解饱和于 ±MAX_SHIFT、着色
// 点 / SSR 起点沿视线在流面两侧整幅漂移（2026-10 竖直面修复接入）。0.5 ≈ 45° 坡度分界，水平静水
//（= 1）两处恒生效、行为不变
const float WATER_DEJIT_MIN_UPNESS = 0.5;

// ---- 水面视差（1；着色点沿视线 march 到波高场隐式面，迭代与守卫见 lib/water/surface.glsl）----
// 开关宏与数值常量分离（1 / 1 同纪律）：删 1 宏 = 视差段编译剔除，水面回
// 平几何着色（法线 / SSR 起点 / 水深全部锚回未位移位置）
const float WAVE_PARALLAX_HEIGHT     = 1.0;  // 视差幅度系数（竖向位移〔格〕= (波高 − 1) × 本值）：波高以 1 为平水基准、恒 ≤ 1 ⇒ 隐式面在几何水面以下（波谷下探、波峰贴面）；默认 0.2 0.2 档波高摆幅 ~0.11 ⇒ 实际最大下探 ≈ 0.11 格，嫌弱抬本值（波高档抬大时位移随字段全域等比放大）
const float WAVE_PARALLAX_MAX_SHIFT  = 0.75; // 沿视线位移上限（格）：一阶解 t = 高差 / |视线.y| 在掠射时发散、于此饱和（波形距离淡出移除后远水掠射会进饱和带，位移有界、亚像素尺度不可见），上限兜 SSR 起点 / 水深换算不跑飞

// 折射位移强度（像素域 × 视口高 /(距离 + 0.5)，春v2 WAVE_REFRACTION_INTENSITY 的分辨率无关改写）：
// 波扰动法线 xy 推背景采样位
const float WATER_REFRACTION_MAX  = 0.03; // 折射位移上限（× 视口高像素）：防近距 / 强法线把背景拉穿屏
// 水面背景快照（colortex4，deferred_init 编码 / water 解码）的编码余量：存储值 = 场景色 × 曝光 ÷ 本值
//（曝光归一化后场景动态范围 ~1e-3~30，÷16 装进 RGBA16 的 [0,1]——旧「colortex4 场景副本」方案被删的
// 根因即裸存 HDR 被 [0,1] 硬截断；两端同帧读同一曝光槽位、解码精确还原，仅 > 16/exposure 的极亮背景
//〔快照内直射白面 / 日盘〕轻微滚降——经水雾吸收 / Fresnel 后不可见）。抬大 = 高光端更早滚落、压小 =
// 暗部量化变粗；16 为「白天雪地直射 ~60 保留 / 夜晚暗部 ~1.4e-5 量化低于噪声地板」的收敛值
const float WATER_BG_SNAPSHOT_HEADROOM = 16.0;
const float WATER_REFRAT_IOR      = 1.2;  // 水折射率（春v2 同值）：水下视角的 Fresnel 折射角换算与全内反射判定
const float WATER_F0              = 0.02; // 水面 Fresnel 基准反射率（春v2 同值，(1−1.33/2.33)² 量级）
// 水下 TIR 未命中回退色的压暗系数（2026-10 按反馈接入，shadeWaterSurface 的 miss 分支消费）：水下
// 仰视水面的镜面带 SSR miss 时回退 waterSkyReflection(向下方向)——LUT 下半区按 1
// 全部存的是**钳到切线的地平线辉光**（太阳侧含 Mie 前向峰，是 LUT 全图最亮区域），云盒八面体边缘
// bilinear 还会串进少量云纹理 ⇒ 回退量级反超直接可见的天空，镜面带观感「比天空还亮」。物理上该处
// 应为被水下雾吸收后的**深水镜像**（水体另一侧的雾色，近似扩展点），辉光兜底量级过高。本值乘在
// 回退色整体（LUT 辉光 + 边缘串色云）；**只压 miss 回退**——SSR 命中的镜像水下几何是真实内容、本就
// 不亮，Fresnel 反射权重是物理量亦不动（2026-10 首试曾缩放水下 fresnel、按反馈回退——压权重会把
// 折射背景同步顶出来，错因不在遮罩强度）。1.0 = 回退原档
const float WATER_UW_REFL_DIM    = 0.2;
// 水下 TIR 回退的色调加权（与 DIM 配套、亮度 / 色相分离）：DIM 纯亮度缩放后回退随 LUT 辉光的
// 灰白散射走、饱和度低观感发灰——本 vec3 仿水体吸收的通道差（红快蓝慢）把色相拉向蓝青；分量
// 全 1 = 回退中性灰（删色偏基准档）。嫌青得不够浓压低 r / 抬高 b，嫌发绿抬 r 压 b
const vec3  WATER_UW_REFL_TINT   = vec3(0.75, 0.95, 1.0);
// 水反天空回退的天光门（2026-10「暗处水面反射天空盒爆亮」修复，shadeWaterSurface 的 miss 分支
// 消费）：LUT 天空 + 云天空盒是天空条件的帧级内容、对「该水面是否敞向天空」一无所知，按水顶点
// lm.y 门控。两级整形（首版线性 clamp 两轮调参）：①下界重映射——水上暗处（屋檐 / 桥下 / 洞口）
// 的水面 lm.y 常停在 0.1~0.3 的残余天光而非真 0，天空盒是 HDR、线性门下 10~30% 的亮度经 AgX 后
// 依旧明晃晃 ⇒ [LOW, 1] 重映射到 [0, 1] 把残余段压死；②感知域回线性——lm 光照级是感知域刻度
//（光照贴图语义），被门控的回退色是线性域 HDR，乘前过 srgbToLinear 同值的幂回到线性域
const float WATER_REFL_SKY_GATE_LOW   = 0.1;  // 重映射下界：低于此天光级的天空回退整支归零
const float WATER_REFL_SKY_GATE_GAMMA = 2.2;  // 感知域 → 线性域幂（srgbToLinear 同值）
// SSR = 2D SSPT 屏幕域 march（春雷 sstTrace 移植，机制见 lib/water/ssr.glsl「屏幕空间反射」段）
// 2026-10-07：步距减半（20 → 40）实测改善反射发虚，保留密度并优化精修重复读取 / 无效验证。
const float WATER_SSR_SHORT_EDGE_STEPS = 40.0; // SSR 步距定标（单一整体调节变量）：步距（buffer 纹素）= 实际渲染区域最短边 ÷ 本值（含 1 / SR 比例）——1080p 基准 → 27 px/步（旧 20 档为 54 px/步；角度自适应见下方开关）；抬大步距变小（更密更贵）、压小步距变大（更省更粗）。march **不限步数**、走完可见段到屏幕 / 视锥边缘为止；步距随分辨率等比 ⇒ 最坏步数 ≈ 对角线 ÷ 步距 ≈ 2.3 × 本值 ≈ 92（射线与步距统一随实际渲染比例缩放），与分辨率 / 渲染比例无关；temporalBayer64 64 相位 × TAA 时间累积收敛缝隙
// 角度自适应步距 A/B（2026-10-07）：掠视保持基准，较正视最多放粗 25%。
// 角度只用调用方的稳定面法线；不依赖动画波面法线，避免步距随波场逐帧摆动。
// 注释开关只关闭角度自适应；与短段最低采样开关均关闭时回固定 40 档。仅源码诊断，不列设置。
const float WATER_SSR_STRIDE_ANGLE_LOW = 0.45;
const float WATER_SSR_STRIDE_ANGLE_HIGH = 0.85;
const float WATER_SSR_STRIDE_MAX_EXTRA = 0.25;
// 短屏幕段最低采样 A/B（2026-10-07）：最多以段长 / 3 作为步距，长段不变。
// 减少短段只采 1~2 点的相位漏采；仅增加短段采样预算，命中 / 拒收仍即时终结。
// 注释本开关 = 回到上一轮仅角度自适应的方案，不影响其他开关。
const float WATER_SSR_SHORT_SEGMENT_MIN_STEPS = 3.0;
const float WATER_SSR_HIT_TOLERANCE = 0.1; // 命中验证松弛量（格，waterSsrHitConfidence）：场景视深须落在「交点射线深 ±（整步跨度 × BIAS + 本值）」带内才判真命中（2026-10 调序起验证在精修交点纹素上做、分子与带宽分置，见 ssr.glsl）；春雷原档 0.05，按反馈多轮调参（0.05 → 0.2 → 0.4 → 回落 0.1 折中）——过紧时命中判定在阈值边缘随 dither 相位逐帧翻转，命中取场景色 / miss 取天空色的闪变即反射噪点，抬宽容度使命中稳定、噪点收敛；代价 = 前景剪影拉伸伪命中的接受度变大（嫌边缘拉丝回降）
const float WATER_SSR_HIT_BIAS = 1.0; // 命中验证步长项倍率：带宽 = 整步跨度（上一步 → 候选步的射线深差）× 本值 + TOLERANCE——2026-10 调序起分子与带宽分置（见 ssr.glsl）：分子 = 精修交点穿透深 ≤ 1/16 步长跨度 ⇒ 真命中 residual ≤ 1/(16·本值) 恒满置信（旧序分子 = 候选过冲随 bayer 相位均匀分布 ⇒ confidence 逐帧翻转的噪点根源），带宽维持整步 = 与旧序同宽容度、剪影拒收阈值不变（曾试收敛区间〔1/16 步长〕作带宽的更严档被否——对掠射打到岸线 / 剪影边缘等深度不连续处的真命中过严）；掠射大步长下步长项主导带宽、倍率使容忍随步长放宽，近段步短仍由固定项主导
const float WATER_SSR_DIR_MIN_DOT = 0.94; // SSR 命中方向一致性下限（2026-10 接入，cos 域）：dot(起点 → 碰撞点, 步进方向) 低于本值 → 信任因子 smoothstep 归零（waterSsrDirectionTrust，乘进命中 confidence = 因子 0 即验证失败、march 终结走天空回退）——真命中的夹角仅来自深度量化 / 纹素足迹 / refine 残留（~1-5°，重建点必在射线路径近旁），伪命中（剪影 / 深度跳变、表面不在路径上）夹角无界；0.94 ≈ 20° 起步，嫌误拒（掠射极端几何）降到 0.90（≈26°）、嫌伪命中漏过抬到 0.97（≈14°）。**首步候选（i == 0）豁免方向验证**（2026-10「折角天空线」实机修复，见 ssr.glsl march 内注）：起步即碰撞类命中的「起点 → 碰撞点」基线趋零、方位无意义地无界，全置信误杀成沿折角的直线天空色（实机 A/B 确认恒信任后消失）；豁免后仍受深度带验证把关，i ≥ 1 中远途候选方向验证照常
// 方向信任因子总开关：删定义 = waterSsrDirectionTrust 恒 1（**全程**恒信任、含 i ≥ 1，方向验证
// 整段旁路、深度带验证照常）——诊断 A/B 档（2026-10 折角天空线排查用，已定位首步豁免修复、默认
// 恢复启用）；恢复恒信任排查时删下一行定义即可
//（Fresnel 低值免 march 门槛 WATER_SSR_MIN_FRESNEL 已按反馈删除，2026-10——离法线 ~53° 锥内有屏内命中点的
// 反射被确定性误杀成天空回退（HDR 天色在近法线小 Fresnel 权重下仍可见），改为恒 march、出屏 miss 交天空回退
// 自然处理，见 lib/water/surface.glsl shadeWaterSurface 反射段注，git 历史含完整形态）
//（屏幕边缘向天空回退淡出 WATER_SSR_EDGE_FADE 已按反馈删除，2026-10——带宽观感过宽：命中整段取快照色、出屏即 miss 硬切，git 历史含完整形态）
//（反射方向地平线钳制常量 WATER_REFL_MIN_UP 已按反馈删除，2026-10——反射向量背向顶点法线时改为整支
// 回退顶点法线（水平面 up）反射方向，见 lib/water/surface.glsl shadeWaterSurface 内「背向回退」段注）
const float WATER_GLINT_EXP       = 512.0; // 太阳 / 月亮镜面高光锐度（pow 指数）：主导光源方向的波面亮斑
// 高光亮度（× vDirectIrradiance）：峰值 ≈ 直射辐照度量级、经 AgX 滚落成波光

// ---- 雨天地表湿滑（`1`，2026-10；lib/common/pipeline/wetness.glsl 湿度场 + gbuffers_opaque
//      湿面法线压平 + program/deferred_ssr〔deferred2 槽〕SSR 混合）----
// 湿滑程度 = 露天 lmcoord.y 门 × 水坑噪声 × 朝上度权重（2026-10 按反馈「方块侧面没有雨天湿滑效果」
// 接入侧面：反射可见度随世界法线朝上度单调增——越朝上的面水膜越厚，侧面半权、底面〔雨打不到〕无湿）
// × rainStrength——gbuffer 压平侧与 deferred2 消费侧
// 同一函数（terrainWetness）、同一输入（绝对世界 xz / 原始 lm.y / 世界法线 y）单真源求值，法线压平量与
// SSR 可见度结构性一致。SSR 可见度 = 湿度 × 水面 Fresnel 近似（waterFresnel 水上档），march / 天空回退 /
// 命中段雾全链复用水面反射件（lib/water/ssr.glsl + reflection.glsl）。开关宏与数值常量分离（1 同纪律）；
// 删宏 = 压平段与反射段整体编译剔除、deferred2 透传旁路（colortex6 原样写回——composite_fog 旁路同款
// 翻转纪律，不可 discard）
const float WET_SKY_LM_LOW   = 0.90; // 露天判定下沿（原始 lmcoord.y 的 smoothstep 窗，0.90→0.95 映 0→1）：天光 14 级起坡、15 级满湿——檐下 / 树冠下经光照传播衰减不触窗、天然无湿；gbuffer 侧 vLmcoord.y 与 deferred2 侧 colortex5.a 同域（原始值、不经 remapLightmap）
const float WET_SKY_LM_HIGH  = 0.95; // 上沿：满湿锚点（用户规格 0.9~0.95）；窗口收窄 / 放宽两端联动
const float WET_NOISE_LOW    = 0.0;  // 水坑噪声门下沿：噪声 ∈ [本值, WET_NOISE_HIGH] 经 smoothstep 映 [WET_NOISE_FLOOR, 1]，映射结果整体 pow2（wetness.glsl 内连乘实现）——边缘收紧成圆形水坑、中低值压死
const float WET_NOISE_HIGH   = 0.7;  // 上沿（2026-10 按反馈自 0.4 抬高并配 pow2）——双 octave 值噪声均值 ~0.5，0.7 门 + pow2 = 只有噪声峰值区成湿（稀疏水坑档）、噪声中低值 pow2 后趋地板 = 干地；嫌水坑多降本值、嫌少抬
const float WET_NOISE_FLOOR  = 0.1;  // 映射输出下沿（2026-10 按反馈接入，原 0.0）——干地湿度地板：映射域 [0.1, 1] 而非 [0, 1]，pow2 后地板 = 0.01（1% 湿）——恒低于 WET_SSR_MIN_WETNESS（0.01 < 0.03）不触发 SSR / 免 march，仅保留「雨后微潮」的极弱湿润感（法线压平 1% 不可辨）；0.0 = 回全干地板档
const float WET_NOISE_SCALE  = 1.0 / 1024.0; // 世界 xz → noisetex uv（基 octave 周期 1024 格 ≈ 水坑团块尺度；2026-10 按反馈「噪声太密」三轮放大：16 → 48 → 480 → 1024；REPEAT 寻址天然抗大世界坐标精度衰减——程序化 hash 直算在 ~1e4 后精度劣化，noise.glsl 头注同限）
const float WET_NOISE_OCTAVE2_SCALE = 2.63; // 次 octave 频率倍率（权重 1/3）：破 16 格平铺感
const float WET_TOP_NORMAL_LOW  = -1.0; // 朝上度权重窗（世界法线 y 的 smoothstep 下沿；2026-10 按反馈自 0.6 拉宽——旧「顶面判定窗」把侧面恒门为 0 湿 = 方块侧面无湿滑效果的根因）：湿度（法线压平量与 SSR 反射可见度的共同来源）随朝上度单调增——顶面 1 满档 / 侧面 0.5 半档（平滑窗中点）/ 底面 0（雨打不到朝下的面），同一水坑噪声锚点下顶面恒 ≥ 侧面（用户规格「越朝上可见度越高」）；MC 地形轴对齐三档即全部取值，labPBR 法线贴图的中间值平滑过渡。顶面行为与旧窗逐位一致（gbuffer 侧几何法线 y=1 两窗同给满档）；gbuffer 侧取导数几何法线、deferred2 侧取解包法线（已含压平），无 normal 贴图时两侧逐位一致。嫌侧面湿感强 / 弱改 LOW（越接近 0 侧面越干，回 0.6 档 = 侧面全干）
const float WET_TOP_NORMAL_HIGH = 1.0;  // 上沿（= 顶面满湿锚点，恒为 1）
const float WET_SSR_MIN_WETNESS = 0.03; // 免 march 湿度门槛（**只看湿度、与视角 / Fresnel 无关**，2026-10 按反馈自 WET_SSR_MIN_WEIGHT〔湿度 × Fresnel 门槛〕更名改判：旧门槛下 Schlick F0 0.02 使眼点正下方 ~53° 俯视锥——地面投影为以脚下为圆心、半径 ≈ 1.34 × 相机离地高度的硬边干圈，越高越大——整片跳过；Fresnel 现只进 mix 权重）：干地地板（WET_NOISE_FLOOR pow2 = 0.01）恒在门下、微潮免 march；0.0 = 恒 march

// 跨阶段 varying 声明宏（对应春雷 pipeline/varying_io.glsl）

// 顶点阶段展开为 out，片段阶段展开为 in，varying 只需声明一次

// 全部 uniform 声明集中于此，由 program 文件 include

uniform sampler2D tex; // 采样纹理统一命名 tex
uniform sampler2D noisetex; // 引擎程序化噪声纹理（边长 = constants.glsl 的 noiseTextureResolution，线性滤波、REPEAT 寻址）：水焦散波场（lib/lighting/caustics.glsl）

uniform sampler2D normals;  // 法线贴图（labPBR 约定，rgb 存切线空间法线，读取端 *2-1 后经 TBN 变换，不翻 Y）
uniform sampler2D specular; // 高光贴图（labPBR 约定，r = smoothness，g = F0，b = porosity/SSS，a = emissive）

uniform sampler2D colortex1; // bloom tile 图集（composite4~8 下采样、composite9~12 上采样回卷，tile0 终态 = 合并后的完整泛光，final 消费 tile0、composite12 测光读 tile4）+ 云形状场槽位（图集右侧 r 通道，布局见 bloom.glsl 的 cloudFieldRect——deferred 槽生成、deferred_init 伪自阴影探针读，见 clouds.glsl）。gbuffers 阶段不可采样（同上）
uniform sampler2D colortex3; // TAA 历史缓冲（clear = false）：rgb = 上帧混合色，a = 上帧最近片元线性深度；仅 composite_taa 读写。gbuffers 阶段不可采样（同上）
uniform sampler2D colortex4; // gbuffer: rg = 打包 albedo（4x8→2x16），ba = 打包高光贴图 RGBA；deferred_init 解包消费后整面覆写为**曝光归一化背景快照**（编码式见 constants.glsl 的 WATER_BG_SNAPSHOT_HEADROOM——RGBA16 [0,1] 域装下 HDR，water 折射 / SSR 位移采样的稳定背景）。**gbuffers 阶段读须用别名 gaux1**
uniform sampler2D colortex5; // gbuffer: rg = 八面体观察空间法线，ba = 原始 lmcoord；光照接入后读取。**gbuffers 阶段读须用别名 gaux2**
uniform sampler2D colortex6; // 场景主颜色缓冲（RGBA16F），deferred_init 初始化、前向半透明 after 路径合成（2026-10 兼容性标准化：**全部 colortex6 写入者输出 (色, alpha) 交硬件 alpha 混合直写〔时机两可族经 per-buffer 行、water 族经引擎默认半透明混合〕、gbuffers 阶段无任何 fetch**——gaux3 手动合成全面废止，读正在写的附件在个别驱动未定义）、composite_taa 抗锯齿，final 读取后直接输出屏幕（不再写回）。放 colortex6 而非惯例的 colortex0 的历史缘由：colortex0~3 的采样单元在 gbuffers 阶段被游戏纹理 / 深度绑定占用（colortex0 即几何纹理 tex，实测采样返回纹理图集内容——water 曾因此把图集画上屏幕），colortex0 全程未使用

// gaux1~4 = colortex4~7 的采样别名（gbuffers 阶段读缓冲的规范名——deferred / composite / final 阶段
// 两者同单元等价、均可用；gbuffers 程序一律用 gaux 名，见各 colortex 注释）
uniform sampler2D gaux1; // = colortex4：帧内两阶段——before-deferred 手动合成类（color / beacon 外壳）读 gbuffer 背景包装；deferred_init 之后 = 曝光归一化背景快照（water 折射 / SSR 采样 × vBgDecodeScale 解码）
uniform sampler2D gaux2; // = colortex5
uniform sampler2D gaux3; // = colortex6：场景主颜色（**gbuffers 阶段已无读者**——2026-10 兼容性标准化：所有写 colortex6 的 gbuffer 一律 (色, alpha) 直通 + 硬件混合〔时机两可族 per-buffer 行 / water 族引擎默认〕，读正在写的附件废止；声明保留为 gaux 别名族完整性的文档位，composite 阶段读主颜色用 colortex6 名）
uniform sampler2D gaux4; // = colortex7：杂项簇（pass 顺序标记、天空 LUT 探针——ambient.glsl / pass_order_marker.glsl 经本名采样，gbuffers vsh 消费）

uniform sampler2D colortex7; // 杂项数据缓冲（clear = false，左下角杂项簇）：云层天空盒 256×256（八面体烘焙云，composite12 写 / water 反射经 gaux4 读）+ 曝光槽位 1 texel（exposure.glsl 的 exposureTexel）= 自适应曝光（composite12 写、composite_taa 与 final 读）、天空 view LUT 200×200（太阳半区 + 月亮半区，deferred_init 读）、aerial 透视 LUT 64×192（(460,0) 起，composite_fog 读）

uniform sampler2D depthtex0; // 深度缓冲（全部几何）；deferred 时刻除不透明外可能已含 deferred 前绘制的 textured 族（粒子 / 闪电）深度，天空判定须用 depthtex1；composite 时刻含半透明与手，TAA 重投影取十字最近片元
uniform sampler2D depthtex1; // 深度缓冲（仅不透明几何，含手部；粒子等非不透明写入被排除）：deferred_init 天空判定 / 光照位置重建用

// ---- SR 超分模组（superresolution.v3.json；SR_UPSCALE 由 constants.glsl 依 mod 注入宏派生，
//      须先于本文件引入——各 program 的既有引入序已满足）----




uniform vec4 entityColor; // 实体着色（受伤红闪等），rgb 为目标色，a 为混合权重；仅 gbuffers_opaque_entities 使用

// 引擎 alpha test 参考值（OptiFine 文档的标准消费式 = if (color.a < alphaTestRef) discard;），逐 draw
// 更新。Iris 在 alphaTest.* = off 下恒 0（off 映射 ALWAYS、取其 reference 0），老 OptiFine（1.12-）不
// 识别该 uniform 亦恒 0——pass 侧统一经 constants.glsl 的 (clamp(alphaTestRef, ALPHA_CUTOUT, ALPHA_TEST_REF_MAX)) 钳制消费（下限 ALPHA_CUTOUT
// 兜底），全版本一致；shadow 阶段不消费（恒 ALPHA_CUTOUT）
uniform float alphaTestRef;

uniform float viewWidth;  // 视口宽度（像素）；lib/post/bloom.glsl 计算 colortex6 源纹素尺寸
uniform float viewHeight; // 视口高度（像素）；同上
uniform float far;        // 相机远平面（≈ 渲染半径 × √2 + 余量）：屏幕空间追踪阴影的渲染边界淡出锚点（shadow.glsl；GLSL 330 非保留字，各参考包通用名）
uniform float frameTime;  // 帧间隔（秒）；自动曝光时间适应
uniform float frameTimeCounter; // 游戏时间累计（秒，世界加载起算）；云层风场动画时基（lib/atmosphere/clouds.glsl）
uniform int frameCounter; // 帧序号；TAA jitter 相位（frameCounter & 7）与首帧守卫

// ---- TAA 重投影（lib/common/utils/noise.glsl + lib/post/taa.glsl + utils/space.glsl 上一帧换算）----
uniform vec3 cameraPosition;         // 本帧相机世界坐标
uniform vec3 previousCameraPosition; // 上帧相机世界坐标
uniform mat4 gbufferProjection;         // 视图 -> 裁剪（当前帧，正向投影）：屏幕空间追踪阴影的每步射线投影（shadow.glsl）
uniform mat4 gbufferProjectionInverse;  // 裁剪 -> 视图（当前帧）：TAA 深度重建；屏幕空间追踪阴影的场景点重建共用
uniform mat4 gbufferPreviousModelView;  // 视图 -> 世界（上帧）：TAA 重投影
uniform mat4 gbufferPreviousProjection; // 世界 -> 裁剪（上帧）：TAA 重投影

// 以下为天空 / 光照效果库所需：天空（lib/atmosphere/）与光照（lib/lighting/）均已接入 deferred_init
uniform mat4 gbufferModelView;       // 世界空间 -> 视图空间（3x3 部分把世界方向转观察方向：植物晃动偏移 gbuffers 侧转观察系，lib/common/pipeline/waving.glsl）
uniform mat4 gbufferModelViewInverse; // 视图空间 -> 世界空间（viewToWorldDirection / viewToRelativeWorld 共用）

uniform vec3 sunPosition;         // 太阳方向（视图空间，长度为到太阳的距离）
uniform vec3 moonPosition;        // 月亮方向（视图空间，同上；与太阳恰好相对——白天沉于地平线下、月亮半区自然归零）；天空 LUT 月亮半区光源
uniform vec3 shadowLightPosition; // 当前主导光源（白天太阳 / 夜晚月亮，视图空间）

uniform float sunAngle;     // 太阳角度 [0,1)，0 = 日出，0.25 = 正午，0.5 = 日落，0.75 = 午夜
uniform float rainStrength; // 雨强度 [0,1]
uniform int isEyeInWater;   // 0 = 大气中 / 1 = 水中 / 2 = 熔岩中（水下效果扩展点）
uniform ivec2 eyeBrightnessSmooth; // 眼位光照级的引擎平滑值（x = 方块光 / y = 天光，各 0..240、进出光照平滑过渡）：水下雾亮度随环境光调制（lib/water/fog.glsl 的 waterUwEnvLight）

// ---- 阴影贴图（program/shadow.glsl 写入 + lib/lighting/shadow.glsl 采样）----
uniform mat4 shadowModelView; // 相对世界（当帧相机为原点、与 gbufferModelView 同源空间）-> shadow 视图
uniform mat4 shadowProjection; // shadow 视图 -> shadow 裁剪（正交）
uniform mat4 shadowModelViewInverse; // shadow 视图 -> 相对世界：shadow vsh 水面 / 植物晃动的绝对世界坐标重建（焦散图案世界锚定，BSL / 春v2 同款逆链）
// shadowtex0 开硬件比较（constants.glsl 的 shadowHardwareFiltering0）、声明为 sampler2DShadow：
// 比较采样即深度比较 + 2×2 双线性插值，一次采样顶手动 4 次比较（GLSL 330 的 textureLod
// 重载同样走硬件比较滤波，采样端显式 LOD 0 免隐式导数）
uniform sampler2DShadow shadowtex0; // 全几何深度（含半透明）：基础可见性 PCF
// shadowtex1 不开硬件比较、保持 sampler2D 裸读（仅不透明几何）——彩色阴影遮挡分离与
// 未来 PCSS blocker search 共用的后路（春v2 同布置）
uniform sampler2D shadowtex1;   // 仅不透明深度（裸值）
uniform sampler2D shadowcolor0; // shadow pass 透射色（sRGB albedo，program/shadow.glsl 写入）；RGBA8：水面像素写 焦散×tint（rgb ≤1）+ a 通道水标记（SHADOW_COLOR_WATER_A，读取端 ×2.0 重建 HDR）











// 通用采样 / 滤波工具库：函数全部显式传参、不引用 uniforms（唯一常量例外：rcasLobe 的去噪
// 分支由 constants.glsl 的 1 宏门控，接入方须在 constants 之后 include 方可启用），
// 由 program 按需平铺 include（lib 之间不互相 include 的约定不变）

// smoothstep 加权双线性（iq: Texture - Better Filtering，春雷同款）：
// 单次采样、仅多几个 ALU，把双线性的线性插值权重换成 3t²-2t³ 平滑曲线，观感接近 bicubic
// https://www.shadertoy.com/view/XsfGDn
//
// ---- 上游许可（该 shader 代码头自带的 MIT 声明，原样保留；依 MIT 条款：版权与许可声明须随
//      副本保留。lib/water/waves.glsl 的 waterNoiseTexel 与 lib/lighting/caustics.glsl 的
//      causticsNoiseTexel 为同一实现的就地镜像，同受本声明覆盖）----
//
// The MIT License
// Copyright © 2013 Inigo Quilez
// https://www.youtube.com/c/InigoQuilez
// https://iquilezles.org/
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
//
// 上游自述：This is the implementation for my article "improved texture interpolation"
// https://iquilezles.org/articles/texture
vec3 textureNice(sampler2D src, vec2 uv) {
    vec2 resolution = vec2(textureSize(src, 0));
    uv = uv * resolution + 0.5;
    vec2 iuv = floor(uv);
    vec2 fuv = fract(uv);
    uv = iuv + fuv * fuv * (3.0 - 2.0 * fuv);
    uv = (uv - 0.5) / resolution;
    return texture(src, uv).rgb;
}

// 4-tap 对角 tent 上采样核（下采样 13-tap 核的上采样对位工具）：center 处 4 个对角双线性 tap
// 平均——逐级 2 倍上采样无伪影、大倍率放大不出现菱形网格；center / tapStep 为源纹理归一化坐标，
// clampRect 同 downsample13Tap（tap 越界钳回边缘）
vec3 tentFilter4(sampler2D src, vec2 center, vec2 tapStep, vec4 clampRect) {
    vec3 result = vec3(0.0);
    result += texture(src, clamp(center + tapStep * vec2(-1.0, -1.0), clampRect.xy, clampRect.zw)).rgb;
    result += texture(src, clamp(center + tapStep * vec2( 1.0, -1.0), clampRect.xy, clampRect.zw)).rgb;
    result += texture(src, clamp(center + tapStep * vec2(-1.0,  1.0), clampRect.xy, clampRect.zw)).rgb;
    result += texture(src, clamp(center + tapStep * vec2( 1.0,  1.0), clampRect.xy, clampRect.zw)).rgb;
    return result * 0.25;
}

// 13-tap 下采样核（tap 布局：COD: Advanced Warfare；权重：春雷那套，见其 filters.glsl）：
// tap 步长由调用方给定（源纹素数 × 源纹素尺寸），配合双线性中点采样，每级覆盖 = ±2×步长纹素
// center / tapStep 为源纹理归一化坐标；clampRect = (min.xy, max.xy) 源区域半纹素内缩后的钳制范围，tap 越界钳回边缘
// https://www.iryoku.com/next-generation-post-processing-in-call-of-duty-advanced-warfare/
// 权重与原版 COD 的 1/32、1/16、1/8 幂分数不同（角 / 边降、中心与对角抬，3×3 主体 0.52 / 对角 0.48，
// 分布略窄），十进制合计精确 = 1.000——消费端不做二次归一化，float 求和漂移 ~1e-7 对 bloom 不可见
const vec2  downsample13Offsets[13] = vec2[13](
    vec2(-2.0,  2.0), vec2(0.0,  2.0), vec2( 2.0,  2.0),
    vec2(-2.0,  0.0), vec2(0.0,  0.0), vec2( 2.0,  0.0),
    vec2(-2.0, -2.0), vec2(0.0, -2.0), vec2( 2.0, -2.0),
    vec2(-1.0,  1.0), vec2(1.0,  1.0), vec2(-1.0, -1.0), vec2(1.0, -1.0)
);
const float downsample13Weights[13] = float[13](
    0.010,  0.070, 0.010,
    0.070,  0.200, 0.070,
    0.010,  0.070, 0.010,
    0.120,  0.120, 0.120,  0.120
);

vec3 downsample13Tap(sampler2D src, vec2 center, vec2 tapStep, vec4 clampRect) {
    vec3 result = vec3(0.0);
    for (int i = 0; i < 13; i++) {
        vec2 uv = clamp(center + tapStep * downsample13Offsets[i], clampRect.xy, clampRect.zw);
        result += texture(src, uv).rgb * downsample13Weights[i];
    }
    return result;
}

// 5-tap 锐化 Catmull-Rom 重采样（春v2 同款，Jimenez 快速重采样把 4×4 双三次压成 5 tap）：
// 4 角 + 十字中心共 5 次显式 Lod0 双线性 tap，返回 rgba 全通道（TAA 历史：a = 上帧深度随同一组
// 权重一趟带回，免独立采样）；sharpenAmount 为锐化强度（0 = 标准 Catmull-Rom，1 = 最锐），
// texSize 显式传入，函数保持无依赖
vec4 catmullRom5(sampler2D src, vec2 uv, vec2 texSize, float sharpenAmount) {
    vec2 position = uv * texSize;
    vec2 centerPosition = floor(position - 0.5) + 0.5;
    vec2 f = position - centerPosition;
    vec2 f2 = f * f;
    vec2 f3 = f2 * f;

    float c = sharpenAmount; // 不能写成 const：参数初始化 const 违反 GLSL 规范，NVIDIA 前端在 vsh 解析时直接 C1059
    vec2 w0 =        -c  * f3 +  2.0 * c         * f2 - c * f;
    vec2 w1 =  (2.0 - c) * f3 - (3.0 - c)        * f2         + 1.0;
    vec2 w2 = -(2.0 - c) * f3 + (3.0 -  2.0 * c) * f2 + c * f;
    vec2 w3 =         c  * f3 -                 c * f2;

    vec2 w12 = w1 + w2;
    vec2 tc12 = (centerPosition + w2 / w12) / texSize;
    vec2 tc0 = (centerPosition - 1.0) / texSize;
    vec2 tc3 = (centerPosition + 2.0) / texSize;

    // rgb 与源 a 通道用同一组权重累计，末尾按权重和归一（负瓣可使个别通道轻微过冲，无碍）
    vec4 result = vec4(0.0);
    float weightSum = 0.0;

    result += textureLod(src, vec2(tc12.x, tc0.y), 0.0) * (w12.x * w0.y);
    weightSum += w12.x * w0.y;
    result += textureLod(src, vec2(tc0.x,  tc12.y), 0.0) * (w0.x * w12.y);
    weightSum += w0.x * w12.y;
    result += textureLod(src, vec2(tc12.x, tc12.y), 0.0) * (w12.x * w12.y);
    weightSum += w12.x * w12.y;
    result += textureLod(src, vec2(tc3.x,  tc12.y), 0.0) * (w3.x * w12.y);
    weightSum += w3.x * w12.y;
    result += textureLod(src, vec2(tc12.x, tc3.y), 0.0) * (w12.x * w3.y);
    weightSum += w12.x * w3.y;

    return result / weightSum;
}

// 上游许可（AMD FidelityFX FSR1，随所引 SDK 文件发布、依 MIT 条款原样保留于下；
// rcasLobe 为其实质部分的适配拆分）：
//
// MIT License
//
// Copyright (c) 2023 Advanced Micro Devices, Inc. All rights reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// 1 锐化增益（AMD FidelityFX FSR1 Robust Contrast Adaptive Sharpening，移植自春雷
// filters.glsl 的 RcasFilter——FSR3 SDK fsr1 头版本、含 lowerLimiterMultiplier 稳健限幅：
// https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/main/Kits/FidelityFX/upscalers/fsr3/include/gpu/fsr1/ffx_fsr1.h）
// 本函数只返回自适应增益 lobe（春雷原式与输出组合的拆分：lobe 是线性组合系数，统计域与组合域
// 由此解耦——调用方可「感知域取增益、自身工作域做组合 + 单次 tonemap」，省去邻域逐 tap 过
// tonemap 的成本），输出组合 = (lobe·(b+d+f+h) + e) / (4·lobe + 1)，由调用方施加
// b / d / e / f / h = 十字邻域（上 / 左 / 中 / 右 / 下，FSR1 记法），须为单调压到 [0,1] 的
// 感知域值——限幅公式按该域设计（hitMax 以 1 为白点），HDR 线性直入时 >1 通道限幅失效、
// 亮区静默不锐化；sharpnessStops：0.0 最锐、每 +1.0 增益减半（exp2 衰减，强度常量
// 0.5 在 constants.glsl）
// 1（constants.glsl 可选宏、本文件唯一常量依赖）：邻域亮度波动大处压低增益，
// 不放大噪声 / 颗粒（春雷同款默认开）；未定义时分支编译剔除、回退纯 1
float rcasLobe(vec3 b, vec3 d, vec3 e, vec3 f, vec3 h, float sharpnessStops) {
    const float rcasLimit = 0.25 - 1.0 / 16.0;
    float sharpness = exp2(-sharpnessStops);

    float bL = b.b * 0.5 + (b.r * 0.5 + b.g);
    float dL = d.b * 0.5 + (d.r * 0.5 + d.g);
    float eL = e.b * 0.5 + (e.r * 0.5 + e.g);
    float fL = f.b * 0.5 + (f.r * 0.5 + f.g);
    float hL = h.b * 0.5 + (h.r * 0.5 + h.g);

    float nz = 0.25 * (bL + dL + fL + hL) - eL;
    nz = clamp(abs(nz) / max(max(max(bL, dL), max(eL, fL)) - min(min(min(bL, dL), min(eL, fL)), hL), 1e-6), 0.0, 1.0);
    nz = -0.5 * nz + 1.0;

    vec3 mn4 = min(min(b, d), min(f, h));
    vec3 mx4 = max(max(b, d), max(f, h));

    float lowerLimiterMultiplier = clamp(eL / max(min(min(min(bL, dL), fL), hL), 1e-6), 0.0, 1.0);
    vec3 hitMin = mn4 / max(4.0 * mx4, vec3(1e-6)) * lowerLimiterMultiplier;
    vec3 hitMax = (vec3(1.0) - mx4) / min(4.0 * mn4 - vec3(4.0), vec3(-1e-6));

    vec3 lobeRgb = max(-hitMin, hitMax);
    float lobe = max(-rcasLimit, min(max(max(lobeRgb.r, lobeRgb.g), lobeRgb.b), 0.0)) * sharpness;

    lobe *= nz;

    return lobe;
}

// 颜色空间转换工具（对应春雷 utils/color.glsl），由 program 按需平铺引入，无外部依赖

// sRGB → 线性（gamma 2.2 的六阶多项式拟合，端点约束）：替代 pow 的 6 次超越运算（低配 GPU 超越
// 函数多为 1/4 速率；本函数是光照路径最热 ALU 段——每几何像素 albedo 转换 + 彩色阴影透射色）。
// x²·(多项式) 形式结构性匹配 2.2 次幂近零平切线（带一次项的三次式会在 sRGB < ~0.03 翻负、黑位
// 挤压）；sRGB ≥ 0.05 相对误差 ≤ 2.4%、中段 ≤ 0.2%，观感与 pow 2.2 一致；写读两侧共用、误差对称
vec3 srgbToLinear(vec3 color) {
    return color * color * (0.489745929
                           + color * (1.603340030
                                     + color * (-2.710998662
                                               + color * (2.503631982 - 0.885719277 * color))));
}

// 线性 → sRGB（gamma 1/2.2）；final 输出前的 gamma 矫正。保持 pow：全管线仅 final 每像素一次
//（非热点，sqrt 链近似不是净收益）
vec3 linearToSrgb(vec3 color) {
    return pow(color, vec3(1.0 / 2.2));
}

// Rec.709 相对亮度（春雷 RGBToLuma 同款）
float rgbToLuma(vec3 linearRgb) {
    return dot(linearRgb, vec3(0.2126, 0.7152, 0.0722));
}

// RGB → YCoCg 去相关变换，与 yCoCgToRgb 精确互逆；亮度域统计 / 逐通道去相关钳制用
//（TAA 方差钳制已用，denoise / SSR 方差估计等同用）
vec3 rgbToYCoCg(vec3 color) {
    return vec3(
        color.x * 0.25 + color.y * 0.5  + color.z * 0.25,
        color.x * 0.5  - color.z * 0.5,
       -color.x * 0.25 + color.y * 0.5  - color.z * 0.25
    );
}

vec3 yCoCgToRgb(vec3 color) {
    float yLessCg = color.x - color.z;
    return vec3(yLessCg + color.y, color.x + color.z, yLessCg - color.y);
}

// 坐标空间构造工具（对应春雷 utils/space.glsl 的 TBN 部分）
// TBN 部分仅片段阶段可用（dFdx / dFdy）；坐标换算任意阶段可用
// 依赖由接入的 program 先行 include（lib 文件不嵌套）：uniforms.glsl（投影 / 视图矩阵，
//   含 previous 系与 cameraPosition 系；阴影换算另需 shadowProjection / shadowModelView）、
//   constants.glsl（阴影扭曲 / 压缩常量——仅阴影换算部分需要）

// ---------------- 坐标换算（任意阶段） ----------------

// 线性重映射 + 饱和钳制：x ∈ [e0, e1] → [v0, v1]，域外按端值饱和。屏幕空间追踪阴影的距离
// remap 族（追踪长度 / 起点偏移 / 厚度曲线 / 贴图淡出窗，shadow.glsl）与 SSS 渐入（lighting.glsl）
float remapSaturate(float x, float e0, float e1, float v0, float v1) {
    float t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
    return v0 + t * (v1 - v0);
}

// 屏幕空间 [0,1] -> 观察空间位置：xy = uv、z = 深度缓冲原始值，*2-1 转 NDC 与透视除法都在
// 函数内完成（杜绝只转 xy 漏转 depth 的重建错位）；z 取 1 时落在远平面（天空视线）。
// TAA 深度重建与 deferred_init 天空视线 / 几何 viewPos 共用
vec3 screenToView(vec3 screenPos) {
    vec4 viewPos = gbufferProjectionInverse * vec4(screenPos * 2.0 - 1.0, 1.0);
    return viewPos.xyz / viewPos.w;
}

// screenToView 的典则透视闭式（shadow.glsl 屏幕空间追踪的步内场化同款公式，与 screenToView
// 代数恒等——tools/sim_canonical_viewpos_verify.py 数值验证机器精度级）：gbufferProjection 恒为
// 典则对称透视矩阵（OptiFine / Iris 注入，clip.w = -view.z）——viewZ = -projD/(ndcZ + projC)
// 一次除、view.xy = ndc.xy·projXY·(-viewZ)，免每像素 mat4 乘 + 3 div；矩阵结构若变则回退
// screenToView。逐像素全屏重建的热路径（composite_fog 边界雾）消费；入参 uv / depth 语义与
// screenToView(vec3(uv, depth)) 完全一致（z = 1 落远平面、未归一化方向的调用方照用）
vec3 screenToViewCanonical(vec2 uv, float depth) {
    float projC = gbufferProjection[2].z;
    float projD = gbufferProjection[3].z;
    vec2 projXY = 1.0 / vec2(gbufferProjection[0].x, gbufferProjection[1].y);

    vec2 ndc = uv * 2.0 - 1.0;
    float viewZ = -projD / (depth * 2.0 - 1.0 + projC);
    return vec3(ndc * projXY * (-viewZ), viewZ);
}

// 观察空间方向 -> 世界空间方向（纯旋转、不要求归一化，长度保持）
// 天空色（sky.glsl）与光照方向换算（lighting.glsl）共用
vec3 viewToWorldDirection(vec3 dirView) {
    return mat3(gbufferModelViewInverse) * dirView;
}

// 观察空间位置 -> 玩家相对世界空间（世界轴向；绝对世界坐标 = 结果 + cameraPosition）。
// 完整逆视图含平移：旧版原点可在脚部，新版可与实际眼点相差视角晃动；
// 实际眼点在此空间为 gbufferModelViewInverse[3].xyz，不保证是零点。
// 位置用于阴影 / TAA 重投影；视向量必须由观察位置仅旋转获得，不能直接归一化本结果。
// 保持相对坐标可避开大世界坐标的 float 精度损失：SSR / SSAO 等共用
vec3 viewToRelativeWorld(vec3 viewPos) {
    return (gbufferModelViewInverse * vec4(viewPos, 1.0)).xyz;
}

// 相对世界空间 -> 上一帧屏幕 uv（重投影链第二段）：cameraDelta 为当帧 -> 上帧相机位移，
// 一般传 cameraPosition - previousCameraPosition，手部等随相机几何传 vec3(0.0) 清零平移；
// 返回无抖动坐标，与 jitter 的衔接由调用方处理
vec2 relativeWorldToPreviousScreen(vec3 relativeWorldPos, vec3 cameraDelta) {
    vec4 prevClip = gbufferPreviousProjection * gbufferPreviousModelView
                  * vec4(relativeWorldPos + cameraDelta, 1.0);
    return prevClip.xy / prevClip.w * 0.5 + 0.5;
}

// 观察空间方向 -> 上一帧屏幕 uv：无穷远几何（天空）重投影——w = 0 平移自动失效、仅相机旋转
// 生效；输入不要求归一化
vec2 viewDirectionToPreviousScreen(vec3 dirView) {
    vec4 prevClip = gbufferPreviousProjection * gbufferPreviousModelView
                  * vec4(viewToWorldDirection(dirView), 0.0);
    return prevClip.xy / prevClip.w * 0.5 + 0.5;
}

// ---------------- SR 超分运动矢量（SR mod，superresolution.v3.json；constants.glsl 的
// SR_UPSCALE / SR_ENTITY_VELOCITY 须先行引入）----------------
// 域约定：入参 uv 一律为「无抖动全视场 uv」（= 子区域 buffer uv 经 applyInverseJitter 归一——
// 子区域渲染下全视场 uv 即渲染分辨率归一 uv，SR 的 MV 域定义）；返回 prev − cur。
// 上帧的子区域缩放与本帧互逆（buffer uv = 全视场 uv·S + jitter），故两侧全视场 uv 之差 =
// 渲染分辨率域 MV、无额外换算。prevClip.w <= 0（上帧相机背后 / 出视锥）置 0：该像素上帧
// 不存在、位移无意义，交超分算法的解遮挡检测处置




























// ---------------- 阴影屏幕换算（写读两侧同一实现，任意阶段可用） ----------------

// 线性扭曲因子：中心（d = 0）为 1 - SHADOW_DISTORT_FACTOR = 0.15，纹素密度放大约 6.7 倍；边缘（d = 1）为 1 不缩放
float shadowDistortFactor(vec2 ndcXY) {
    return length(ndcXY) * SHADOW_DISTORT_FACTOR + (1.0 - SHADOW_DISTORT_FACTOR);
}

// 扭曲 shadow NDC xy（正交投影 w = 1，clip 与 NDC 同值）；写入端 program/shadow.glsl 与
// 读取端 lib/lighting/shadow.glsl 共用本实现——对称性由共用结构性保证（原本分居写读两文件、须逐字符对称）
vec2 shadowDistort(vec2 ndcXY) {
    return ndcXY / shadowDistortFactor(ndcXY);
}

// 相对世界空间 -> shadow 屏幕 [0,1]：xy 扭曲、z 压缩——与 program/shadow.glsl 写侧逐字符对称
//（读取端比写侧多一步 NDC -> [0,1] 映射）；distortFactor 输出未扭曲 NDC 处的局部放大补偿
//（PCF 半径 / 未来 blocker search 用）
vec3 relativeWorldToShadowScreen(vec3 relativeWorldPos, out float distortFactor) {
    vec4 clipPos = shadowProjection * shadowModelView * vec4(relativeWorldPos, 1.0);
    vec3 ndcPos = clipPos.xyz; // 正交 w = 1
    distortFactor = shadowDistortFactor(ndcPos.xy);
    return vec3(shadowDistort(ndcPos.xy), ndcPos.z * SHADOW_DEPTH_SCALE) * 0.5 + 0.5;
}


// ---------------- cotangent frame（仅片段阶段） ----------------

// 由预求好的位置屏幕导数 cross / normalize 出几何法线（观察空间，逐像素面法线）：
// 导数已由调用方在 discard 前集中求好，本函数与 calculateTBN 因此可推迟到 discard 之后
vec3 geomNormalFromDerivatives(vec3 dp1, vec3 dp2) {
    return normalize(cross(dp1, dp2));
}

// 屏幕空间导数求几何法线（观察空间，逐像素面法线）
vec3 calculateGeomNormal(vec3 viewPos) {
    return geomNormalFromDerivatives(dFdx(viewPos), dFdy(viewPos));
}

// cotangent frame：由观察空间位置与 UV 的屏幕导数构造 TBN（春雷 / 春v2 同款）。导数由调用方
// 先于 discard 集中求好传入（discard 后 quad 内幸存像素的导数未定义），TBN 构造与后续法线
// 采样得以推迟到 discard 之后；任意贴图向量经 mat3(T, B, N) 左乘即观察空间向量
mat3 calculateTBN(vec3 dp1, vec3 dp2, vec2 duv1, vec2 duv2) {
    vec3 n = geomNormalFromDerivatives(dp1, dp2);

    vec3 dp2perp = cross(dp2, n);
    vec3 dp1perp = cross(n, dp1);

    vec3 t = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 b = dp2perp * duv1.y + dp1perp * duv2.y;

    float invmax = inversesqrt(max(dot(t, t), dot(b, b)));
    return mat3(t * invmax, b * invmax, n);
}


// 噪声 / 抖动 / TAA jitter 工具（通用，与具体效果解耦）
// 依赖由接入的 program 先行 include（lib 文件不嵌套 include）：
//   lib/common/globals/constants.glsl（GOLDEN_RATIO / TAA_JITTER_SAMPLES / TAA_JITTER_SCALE /
//     子区域机制开启时的 0.7）、
//   lib/common/globals/uniforms.glsl（frameCounter / viewWidth / viewHeight）

// ---------------- 噪声 ----------------

// 2x2 bayer 有序抖动基矩阵（robobo1221 构造，春v2 noise.glsl 同款）
float bayer2(vec2 a) {
    a = floor(a);
    return fract(dot(a, vec2(0.5, a.y * 0.75)));
}

// 逐级递归翻倍矩阵尺寸（(a)  (bayer2(0.5 * (a)) * 0.25 + bayer2(a)) = 4x4 ... (a) ((a) ((a) ((a)  ((a)  (bayer2(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a)) = 64x64）：低两级图案平铺、乘 0.25 权重叠加进当前级

// temporal bayer 时域噪声（春v2 同款）：单帧为 (a) ((a) ((a) ((a)  ((a)  (bayer2(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a)) 空间低频图案（相邻像素值相近——TAA 方差
// 钳制的邻域统计不被高频噪声抬高方差，故弃用单帧高频的 IGN），帧间按 golden ratio 步进相位、
// 与 (a) ((a) ((a) ((a)  ((a)  (bayer2(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a))(0.5 * (a)) * 0.25 + bayer2(a)) 的 64 相位对齐——64 帧遍历 [0,1) 的 64 个均匀错开相位，时间累积等价 64 相位超采样；
// 用于时域旋转 / 抖动采样图案（阴影 PCF 采样盘），composite_taa 时间累积解析成收敛结果
float temporalBayer64(vec2 pixelPos) {
    return fract(((((((((((bayer2(0.5 * (0.5 * (0.5 * (0.5 * (0.5 * (pixelPos)))))) * 0.25 + bayer2(0.5 * (0.5 * (0.5 * (0.5 * (pixelPos))))))) * 0.25 + bayer2(0.5 * (0.5 * (0.5 * (pixelPos)))))) * 0.25 + bayer2(0.5 * (0.5 * (pixelPos))))) * 0.25 + bayer2(0.5 * (pixelPos)))) * 0.25 + bayer2(pixelPos))) + float(frameCounter % 64) * GOLDEN_RATIO);
}

// ---------------- simplex / worley 噪声基元（程序化图案——云；结构移植自春v2 noise.glsl） ----------------
// hash 为本包替换的无 sin 浮点 hash（Dave Hoskins 构造，纯乘加 + fract、零超越函数——多数 GPU
// 的 sin 走 SFU / 多周期展开、吞吐低于常规 ALU，且纯 IEEE 运算跨驱动位确定、比 sin 更利于 TAA
// 时间累积）。替换春v2 sin-dot 系的代价：云图案整体更换（统计等价、观感需 A/B）。输入坐标须
// ~1e4 量级内有界——消费方为角域坐标（云 = 世界 xz / 云壳半径，octave 放大后 ~10³~10⁴），该量级
// 内精度无损；更大坐标域须换整数 hash（扩展点）

// rand2 / hash13 / hash33 源自 "Hash without Sine"（https://www.shadertoy.com/view/4djSRW），
// 其随代码发布的 MIT 声明原样保留于下（依 MIT 条款：版权与许可声明须随副本保留）：
//
// MIT License
//
// Copyright (c) 2014 David Hoskins
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// [0,1)² hash（worley 特征点等）
vec2 rand2(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}

// simplex 梯度向量（[-1,1]，rand2 同款 hash ×2−1）
vec2 hash22(vec2 p) {
    return -1.0 + 2.0 * rand2(p);
}

// [0,1) / [0,1)³ 3D hash（rand2 同族，星盘点星消费——sky.glsl getStars 的立方体网格
// 分格；星图坐标有界 [−1,1]³ × 网格密度 ~60，精度域内无忧）
float hash13(vec3 p3) {
    p3 = fract(p3 * 0.1031);
    p3 += dot(p3, p3.zyx + 31.32);
    return fract((p3.x + p3.y) * p3.z);
}

vec3 hash33(vec3 p3) {
    p3 = fract(p3 * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yxz + 33.33);
    return fract((p3.xxy + p3.yxx) * p3.zyx);
}

// 解析 simplex 噪声（[-1,1]，IQ / Gustavson 构造）
float simplex2d(vec2 p) {
    const float K1 = 0.366025404;
    const float K2 = 0.211324865;

    vec2 i = floor(p + (p.x + p.y) * K1);
    vec2 a = p - (i - (i.x + i.y) * K2);
    vec2 o = (a.x < a.y) ? vec2(0.0, 1.0) : vec2(1.0, 0.0);
    vec2 b = a - o + K2;
    vec2 c = a - 1.0 + 2.0 * K2;
    vec3 h = max(0.5 - vec3(dot(a, a), dot(b, b), dot(c, c)), 0.0);
    vec3 n = h * h * h * h * vec3(dot(a, hash22(i)), dot(b, hash22(i + o)), dot(c, hash22(i + 1.0)));
    return dot(vec3(70.0), n);
}

// ---------------- TAA jitter（对应春雷 lib/common/utils/stochastic.glsl 的 jitter 部分） ----------------
// 由 gbuffer 类 program 的 vsh 与通用全屏 vsh（program/fullscreen_vsh.glsl，其 vJitter 即
// taaJitterUV 的 vsh 侧一次算好）按需平铺引入

// 当前帧抖动相位（像素域 [-0.5, 0.5] × TAA_JITTER_SCALE，Halton(2,3) 8 相位查表）。
// SR 超分接管时（SR_UPSCALE，constants.glsl）换用 SR mod 的 SRJitterOffset（mod 生成的相位
// 序列、渲染分辨率像素域 = 本函数的像素域约定）——下游 applyTAAJitter / applyJitter / vJitter
// 全链自动跟进；算法不支持 jitter 时该 uniform 恒 0 = 不抖（本包 TAA 已旁路，自抖无解析端）
vec2 taaJitterSample() {

    return TAA_JITTER_SAMPLES[frameCounter & 7] * TAA_JITTER_SCALE;
}

// 渲染区域逐轴比例。SR 的尺寸由模组按整数截断，不能用名义比例重建像素网格：
// 平衡 / 质量档的宽高余数不同；投影、去抖、深度、运动矢量必须共享实际尺寸。
// 1 保持既有比例；无超分返回全视口。依赖 uniforms.glsl（先于本文件平铺引入）。
vec2 renderRegionSize() {

    return vec2(viewWidth, viewHeight) * 0.7;

}

vec2 renderRegionScale() {

    return vec2(0.7);

}

// 当前帧抖动（uv 域）
vec2 taaJitterUV() {
    return taaJitterSample() / vec2(viewWidth, viewHeight);
}

// vsh 注入：clip 空间平移（1 px = 2/res NDC，乘 w 保透视）。1 / SR_UPSCALE：先缩放进左下
// [0,S]² 子区域再叠 jitter——注意 jitter 在子区域缩放**之后**的 NDC 域注入，NDC→viewport 换算按整块 buffer，
// 有效位移 = ±0.5 **渲染纹素**（buffer 纹素 = 子区域内渲染纹素，与 S 无关；c13 / Kappa / Photon
// 三家同语义；SR 接管时 S = SR_RENDER_SCALE_FACTOR、jitter = SRJitterOffset，同一注入式）。
// 解析端（composite_taa）的去抖补偿须在同一 buffer 纹素域等量施加，见 taa.glsl
vec4 applyTAAJitter(vec4 clipPos) {
    vec2 regionScale = renderRegionScale();
    clipPos.xy = clipPos.xy * regionScale + (regionScale - 1.0) * clipPos.w;
    clipPos.xy += taaJitterSample() * (2.0 / vec2(viewWidth, viewHeight)) * clipPos.w;
    return clipPos;
}

// uv 域补偿对：无抖动全视场 uv <-> buffer uv 互转（几何已 +jitter；屏幕空间追踪阴影 / 未来 SSR /
// SSAO 等的采样一致性用，春雷同款 + 1 补全）。1 / SR_UPSCALE：几何先缩进左下 [0,S]² 子区域
// 再叠 jitter，buffer uv = 全视场 uv·S + jitter——与 deferred_init 去抖基底 (像素uv − vJitter)/S
// 严格互逆；不补 ×S 时补偿随 S 缩水（S=0.5 只剩 1/4）、采样错位 ~0.375 渲染纹素（1 糊/闪同因）。
// applyJitter 消费方 = 屏幕空间追踪阴影〔仿射系数探针反解〕+ 水面 SSR〔2D SSPT 端点折叠，
// 2026-10 起〕；applyInverseJitter 的 jitter 参数版 = 各 pass 位置重建基底（见函数注）
vec2 applyJitter(vec2 uv) {
    uv *= renderRegionScale();
    return uv + taaJitterUV();
}

// 去抖重载（jitter 参数版 = 在树热路径）：入参 jitterUv 为调用方已持值——通用全屏 vsh 的 vJitter
// varying / 前向 program vsh 的同名 varying / 调用点局部 jitter，免 taaJitterUV 的每像素 Halton 表
// 动态索引 + 除法重算（2026-09 性能纪律，原各 pass 内联手抄本式、2026-10 收敛回本函数）。
// 消费方：deferred_init / composite_fog 的位置重建基底、lib/water/surface.glsl 的去抖 / 折射 /
// 命中点换算、lib/post/taa.glsl 的重投影锚点——「buffer uv → 无抖动全视场 uv」全树单真源
//（SR 接管时 S / jitter 两源均由 SR 供给，本函数域约定不变）
vec2 applyInverseJitter(vec2 uv, vec2 jitterUv) {
    return (uv - jitterUv) / renderRegionScale();

}

// 便捷版（自算 jitter）：非热路径 / 无 varying 可持时用；与参数版同一实现
vec2 applyInverseJitter(vec2 uv) {
    return applyInverseJitter(uv, taaJitterUV());
}

// ---------------- 1 渲染子区域外片元剔除（仅片段阶段；SR_UPSCALE 复用同一机制、S = SR 比例） ----------------
// GPU 多边形裁剪按全屏 NDC、不知子区域边界——视锥外近带（NDC xy ∈ [1, 2/S−1]，S=0.75 时
// [1, 1.67]：缩放式 NDC' = NDC·S + S−1 在裁剪立方 NDC' = 1 处反解的上限；负侧贴齐 −1、无对应带）
// 几何缩放后落进子区域外、白跑 fsh（正确性由读端钳边免疫，纯性能剔除；kappa / photon / FSR2 同款）。调用纪律：
// **置于集中屏幕导数之后、一切纹理采样之前**（discard 后幸存像素导数未定义，与 cutout discard
// 同一纪律）。ceil + 1 texel 容差吸收非整渲染分辨率的半像素边界、宁可少剔不误杀；1 关闭时
// 恒 false 零成本。#ifdef 1 守卫——gl_FragCoord 为片段专属输入而本文件亦被 vsh 编译
bool outsideRenderRegion() {
    vec2 limit = ceil(renderRegionSize()) + 1.0;
    return any(greaterThan(gl_FragCoord.xy, limit)) || any(lessThan(gl_FragCoord.xy, vec2(-1.0)));

}

// 数据打包 / 编码工具（对应春雷 utils/packing.glsl：位打包与八面体编码同文件）
// 位打包输出粒度 1/65535，必须存入 16bit 无符号规范化格式（RGBA16），不可用浮点格式
// 八面体映射为单位向量 ↔ 二维 [0,1] 的通用编码，不限法线用途（天空方向、环境采样方向等皆可）
// 标识符避开 GLSL 保留字（packed / filter / sample 等）

// ============================== 位打包（int 位运算，值域 [0,1]） ==============================

// 两个 8bit 值打包进一个 16bit 通道
float pack2x8To16(float a, float b) {
    int ai = int(clamp(a, 0.0, 1.0) * 255.0);
    int bi = int(clamp(b, 0.0, 1.0) * 255.0);
    return float((ai << 8) | bi) / 65535.0;
}

vec2 unpack16To2x8(float data) {
    int p = int(data * 65535.0);
    return vec2(float((p >> 8) & 255), float(p & 255)) / 255.0;
}

// 四个 8bit 值打包进两个 16bit 通道
vec2 pack4x8To2x16(vec4 abcd) {
    ivec4 quantized = ivec4(clamp(abcd, 0.0, 1.0) * 255.0);
    int combined1 = (quantized.x << 8) | quantized.y;
    int combined2 = (quantized.z << 8) | quantized.w;
    return vec2(float(combined1), float(combined2)) / 65535.0;
}

vec4 unpack2x16To4x8(vec2 data) {
    ivec2 combined = ivec2(data * 65535.0);
    ivec4 unpacked;
    unpacked.x = (combined.x >> 8) & 0xFF;
    unpacked.y = combined.x & 0xFF;
    unpacked.z = (combined.y >> 8) & 0xFF;
    unpacked.w = combined.y & 0xFF;
    return vec4(unpacked) / 255.0;
}

// ============================== 八面体编码（单位向量 ↔ 二维 [0,1]） ==============================

// 将向量折叠回八面体菱形区域
vec2 octWrap(vec2 v) {
    vec2 w = 1.0 - abs(v.yx);
    if (v.x < 0.0) w.x = -w.x;
    if (v.y < 0.0) w.y = -w.y;
    return w;
}

// 三维单位向量 -> 二维八面体坐标
vec2 encodeOctahedral(vec3 direction) {
    float length_ = length(direction);
    if (length_ < 1e-8) {
        // 零向量没有方向，退化为 +Z 的八面体坐标
        return vec2(0.5);
    }

    direction /= length_;

    vec2 p = direction.xy / (abs(direction.x) + abs(direction.y) + abs(direction.z));
    if (direction.z < 0.0) {
        p = octWrap(p);
    }

    return p * 0.5 + 0.5;
}

// 二维八面体坐标 -> 三维单位向量
vec3 decodeOctahedral(vec2 oct) {
    oct = clamp(oct, 0.0, 1.0);

    vec2 p = oct * 2.0 - 1.0;
    vec3 v = vec3(p, 1.0 - abs(p.x) - abs(p.y));
    if (v.z < 0.0) {
        v.xy = octWrap(v.xy);
    }

    return normalize(v);
}

// Bloom 工具库：tile 图集布局、链式下采样、渐进上采样回卷与合并入口
// 依赖先行 include：lib/common/globals/constants.glsl（BLOOM_*）、lib/common/globals/uniforms.glsl（colortex6 / colortex1、
// viewWidth / viewHeight）、lib/common/utils/filters.glsl（tentFilter4 / downsample13Tap）
//
// 图集布局（缓冲归一化坐标，全尺寸 colortex1，不用 size.buffer——低版本 OptiFine 不支持）：
//   tile0 = 左上 1/4×1/4（屏幕 1/4 分辨率起步，c13 同款；砍掉 1/2 级省最大头开销），
//   tile1~4 在其右侧纵向堆叠（边长 1/8、1/16、1/32、1/64），图集仅占缓冲 ~10% 面积
//   tile 间隔 4 texel，吸收采样半径与奇数分辨率下的分数纹素边界，防串色
//   每个 tile 都覆盖整个场景（边长逐级减半），所有矩形计算不假设缓冲实际分辨率（textureSize 运行时推导）
//
// 双链金字塔（COD AW 式，下采样 composite4~8 + 上采样回卷 composite9~12）：
//   下采样：tile k = 13-tap 高斯取自上一级（tile0 取自 colortex6），各 tile 存原始金字塔
//   上采样：tile k = 本级原始内容 × 级权重 + 上一 pass 已合并 tile k+1 的 tent 放大 2 倍相加，
//           粗级模糊经逐级 tent 累积成连续衰减——单次大倍率双线性放大的菱形网格、
//           离散半径直接叠加的环状过渡（网格感 / 空隙感）在此结构下不再产生

const int BLOOM_TILE_COUNT = 5; // 金字塔级数：1/4 ~ 1/64

// 返回 tile k 的矩形：xy = 原点、zw = 边长（缓冲归一化）
vec4 bloomTileRect(int k) {
    vec2 gap = 4.0 / vec2(textureSize(colortex1, 0));
    float size = exp2(-float(k + 2));
    if (k == 0) return vec4(0.0, 0.0, size, size);

    // Σ(i=1..k-1) 2^-(i+2) = 0.25 × (1 - 2^-(k-1))，避免每像素小循环
    float level = float(k - 1);
    vec2 origin = vec2(
        0.25 + gap.x,
        0.25 * (1.0 - exp2(-level)) + level * gap.y
    );
    return vec4(origin, size, size);
}
// 图集包围盒右上角（缓冲归一化）：composite_bloom_upsample 的 vsh 光栅压缩与
// composite12 的 fsh 包围盒判定（colortex7 透传 / 写 0 分支）共用
vec2 bloomTileRectMax() {
    vec2 rectMax = vec2(0.0);
    for (int k = 0; k < BLOOM_TILE_COUNT; k++) {
        vec4 rect = bloomTileRect(k);
        rectMax = max(rectMax, rect.xy + rect.zw);
    }
    return rectMax;
}

// colortex7 需要跨帧保值的完整预留区域：云层天空盒 + sky-view LUT + 曝光 gutter（+ aerial LUT）。
// composite12 的 outMisc 必须覆盖此范围，不能只覆盖 Bloom 图集包围盒。
vec2 bloomMiscRectMax() {
    vec2 miscSize = vec2(textureSize(colortex7, 0));
    vec2 skyboxMax = vec2(float(SKYBOX_LUT_SIZE)) / miscSize;
    vec2 skyViewMax = vec2(
        float(SKYVIEW_LUT_ORIGIN_X + SKYVIEW_LUT_W),
        float(2 * SKYVIEW_LUT_H)
    ) / miscSize;
    vec2 rectMax = max(skyboxMax, skyViewMax);
    // aerial LUT（原点 (AERIAL_LUT_ORIGIN_X, 0) = sky-view 右侧续接，见 constants.glsl 布局注释；
    // 2026-10 自天空盒预留区左下角 (0,0) 迁此——[0,256)² 整块归云层天空盒独占）
    rectMax = max(rectMax, vec2(float(AERIAL_LUT_ORIGIN_X + AERIAL_LUT_W),
                                float(AERIAL_LUT_H * AERIAL_LUT_SLICES)) / miscSize);
    return rectMax;
}

// 云形状场槽位矩形（colortex1，texel 域、整数对齐）：图集包围盒右侧 4 texel 间隔、底边锚定——
// 与全部 tile 矩形互斥由布局结构性保证（tile0 左下 1/4 域、tile1~4 右侧列均止于包围盒右缘），
// bloom 链（composite4~12 只写图集区域）与场的写入者（deferred）区域互斥互不干扰。写入端
//（deferred_cloud_field 的 fsh / vsh quad 压缩）与读取端（clouds.glsl 的 sampleCloudField）共用
// 本矩形——texel i 中心 ↔ local = (i + 0.5) / RES 的互逆映射由此结构性对齐
vec4 cloudFieldRect() {
    vec2 bufSize = vec2(textureSize(colortex1, 0));
    vec2 origin = ceil(bloomTileRectMax() * bufSize) + 4.0;
    return vec4(origin, vec2(CLOUDS_2D_FIELD_RES));
}
// 计算第 k 级 tile 的下采样结果（tileLocal = tile 内容归一化坐标，像素中心即源 2×2 区域中心）
// k = 0 直接从 colortex6 全屏取，k > 0 从上一级 tile 取（链式）
vec3 bloomDownsampleTile(int k, vec2 tileLocal) {
    if (k == 0) {
        vec2 srcTexel = 1.0 / vec2(viewWidth, viewHeight);
        vec4 clampRect = vec4(srcTexel * 0.5, 1.0 - srcTexel * 0.5);
        return downsample13Tap(colortex6, tileLocal, BLOOM_BLUR_STEP * srcTexel, clampRect);
    }
    vec4 srcRect = bloomTileRect(k - 1);
    vec2 bufTexel = 1.0 / vec2(textureSize(colortex1, 0));
    vec2 srcCenter = srcRect.xy + tileLocal * srcRect.zw;
    vec4 clampRect = vec4(srcRect.xy + bufTexel * 0.5, srcRect.xy + srcRect.zw - bufTexel * 0.5);
    return downsample13Tap(colortex1, srcCenter, BLOOM_BLUR_STEP * bufTexel, clampRect);
}

// 计算第 k 级 tile 的金字塔合并结果（composite_bloom_upsample 调用，k = 0~3 目标级，
// tileLocal = 目标 tile 内容归一化坐标，目标纹素中心自然落在源 2×2 区域的子纹素位置）：
// 本级原始内容乘级权重 + 上一 pass 已合并 tile k+1 的 tentFilter4 放大 2 倍相加；
// k = 3 的源 tile4 是唯一未经合并的原始级，乘末级权重后并入。
// 权重在相加处逐级施加（tile0 由此累积全部级权重，getBloom 统一除以权重和归一）
vec3 bloomUpsampleTile(int k, vec2 tileLocal, ivec2 pixel) {
    vec4 rect = bloomTileRect(k);
    vec4 srcRect = bloomTileRect(k + 1);
    vec2 bufTexel = 1.0 / vec2(textureSize(colortex1, 0));
    vec2 srcCenter = srcRect.xy + tileLocal * srcRect.zw;
    vec4 clampRect = vec4(srcRect.xy + bufTexel * 0.5, srcRect.xy + srcRect.zw - bufTexel * 0.5);
    vec3 coarse = tentFilter4(colortex1, srcCenter, bufTexel, clampRect);
    if (k == BLOOM_TILE_COUNT - 2) coarse *= BLOOM_WEIGHTS[BLOOM_TILE_COUNT - 1];
    vec3 fine = texelFetch(colortex1, pixel, 0).rgb;
    return fine * BLOOM_WEIGHTS[k] + coarse;
}

// 合并入口（final 调用）：回卷链已把全部级合并进 tile0，此处仅 tent 放大 4 倍（单级 4 倍 + tent
// 无网格伪影）；除以权重和归一，返回与场景同量级的泛光颜色
vec3 getBloom(vec2 screenUv) {
    vec2 bufTexel = 1.0 / vec2(textureSize(colortex1, 0));
    vec2 uv = clamp(screenUv * 0.25, bufTexel * 0.5, vec2(0.25) - bufTexel * 0.5);
    return textureLod(colortex1, uv, 0.0).rgb / BLOOM_WEIGHT_SUM;
}
// 自动曝光工具库：亮度算法参考春雷（tile4 对数平均 + 0.18 key 直除 + 地板 + 曝光域指数适应），
// pass 设计参考春v2（寄生 bloom 链测光、单像素存储、写入区域透传保值，无 flip.* 依赖）
// 依赖先行 include：constants.glsl（AUTO_EXPOSURE_*）、uniforms.glsl（colortex1 / colortex7 /
// frameTime）、lib/post/bloom.glsl（bloomTileRect / BLOOM_TILE_COUNT）、utils/color.glsl（rgbToLuma）

// colortex7 曝光槽位（杂项簇第一个槽）：天空盒与天空 LUT 的 4 texel 间隔 gutter 内、缓冲底边
//（固定 texel (258, 0)，与两区域任何分辨率下不相交——原「图集 tile 间隔」方案位置随分辨率浮动、
// 常见分辨率下会落进 LUT 区域故迁址）；槽位常量 EXPOSURE_TEXEL 在 constants.glsl（water vsh 快照
// 解码不经本文件直读槽位、须共享位置），写入端 composite12 与全部读取端经本函数取值、位置恒一致
ivec2 exposureTexel() {
    return EXPOSURE_TEXEL;
}

// 场景平均亮度（对数平均，春雷同款）：bloom 最粗 tile4（1/64 分辨率低频）上固定 16 点抖动网格核
// 采样（tile4 每纹素已聚合 ~64² 屏幕像素、内容极低频，16 点估计充分；测光成本与分辨率解耦、
// 固定核帧间稳定）；对数域平均抑制高光算术级主导；测量语义 = 未乘曝光、未加 bloom 的线性场景
float sceneAverageLuminance() {
    ivec2 atlasSize = textureSize(colortex1, 0);
    vec4 rect = bloomTileRect(BLOOM_TILE_COUNT - 1);
    ivec2 origin = ivec2(rect.xy * vec2(atlasSize));
    ivec2 extent = max(ivec2(rect.zw * vec2(atlasSize)), ivec2(1));

    float logLumSum = 0.0;
    for (int i = 0; i < EXPOSURE_SAMPLE_COUNT; i++) {
        ivec2 p = origin + clamp(ivec2(vec2(EXPOSURE_SAMPLE_KERNEL[i]) * vec2(extent)), ivec2(0), extent - 1);
        vec3 c = max(texelFetch(colortex1, p, 0).rgb, vec3(0.0));
        logLumSum += log(rgbToLuma(c) + AUTO_EXPOSURE_MIN_LUMINANCE);
    }
    return exp(logLumSum / float(EXPOSURE_SAMPLE_COUNT));
}

// 目标曝光（春雷 key value 直除 + 基础亮度地板）：avgLum 先抬到 0.01
// 再直除——纯黑 / 深夜场景的对数平均远低于地板，曝光封顶在 KEY / BASE，夜晚 / 暗室不再被
// 放大成白天；亮场景 avgLum >> 地板，直除行为不变
float targetExposure(float avgLum) {
    return clamp(AUTO_EXPOSURE_KEY_VALUE / max(avgLum, 0.01), 1e-7, 1e7);
}

// 时间适应（春雷同款指数平滑、帧率无关）：曝光域平滑 = 亮度等比变化时按 EV stop 均匀收敛，
// 符合人眼明暗适应；prev <= 0（首帧 / clear color）直接取目标
float adaptedExposure(float target) {
    float prev = texelFetch(colortex7, exposureTexel(), 0).r;
    if (prev <= 0.0) return target;
    return mix(prev, target, 1.0 - exp(-frameTime * AUTO_EXPOSURE_RATE));
}

// 读取端（composite_taa 钳制域归一化乘上一帧值 / final 应用本帧值）：已适应的曝光系数
float readAdaptedExposure() {
    return texelFetch(colortex7, exposureTexel(), 0).r;
}

// 本文件核心（airMass / erfcx / 相位函数族 / energyIntegralRatio / planetHitDistance 等）移植自
// 下列上游作品，其随代码发布的 MIT 声明原样保留于下（依 MIT 条款：版权与许可声明须随副本保留）：
//
// MIT License
//
// Copyright (c) 2024 John Payne
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// 大气物理核心：Chapman 闭式光学深度 + 保能量单次散射 + 各向同性环境场多次散射（零 raymarch）
// 移植自 Shadertoy WcdSW4（MIT，John Payne 2024）https://www.shadertoy.com/view/WcdSW4 ，五处适配：
//   1. inf 改 SKY_NO_HIT = 1e30 哨兵（编译期 1/0 在部分驱动上未定义）
//   2. 视线对准太阳的 (e^-tauS - e^-(tauSp+tauV)) / (tauSp+tauV-tauS) 0/0——energyIntegralRatio 泰勒保形
//   3. r²-R² 改 (r-R)(r+R) 防消劫（换小尺度参数时原式有 ~10% 亮度抖动）
//   4. float32 溢出防护：erfcx 负支 exp 上限 + airMass 钳制（原式 |b| 可达 r/H ~ 45，exp(b²) 溢出
//      Inf——夜晚 / 下视路径 NaN 的根源；上限取值的依据见 constants.glsl 的 SKY_ERFCX_EXP_MAX / SKY_AIRMASS_MAX）
//   5. 臭氧系数弃用原作调参、按 Chappius 吸收带真实截面重定（原系数光谱形状 R>G 与真实相反、
//      日出天空发黄）——数值与来源见 constants.glsl
// 夜侧无需特判：太阳沉入地平线后 tauS 随 airMass 饱和、天空自然归零（曙暮光带自然呈现）
// 多次散射：二阶起近似为「各向同性环境辐射场」（Hillaire 2020 / Wrenninge 多阶近似的最低档）——
//   环境场量级 = 一阶散射天光球面方向平均 L̄₁（skyAmbientField 的 48 节点环带求积）× 截获比几何级数
//   1/(1-ρ)；视线端 MS 项 = ambientCapture × 环境场，路径量全部复用单次散射已算的 airMass。
//   数值验证：正午天光辐照度 ×1.07~1.26、天顶 ×1.10~1.17、反日侧暮光地平线 ×1.6~1.7、夜空地板不抬高
// 依赖由接入的 program 先行 include：constants.glsl（大气常量、PI）

// 缩放互补误差函数 e^(x^2) * erfc(x)，任意符号参量的有理逼近（Shadertoy 原式；六系数连乘
// 折叠为单次除法——各因子 O(1) 无溢出，与原式最大相对差 7e-7；erfcx 是 LUT 生成端每 texel
// 最高频的函数）。负参量分支 exp 上限钳制 SKY_ERFCX_EXP_MAX：|b| 可达 r/H ~ 45，exp(b²) 溢出
// Inf 即夜晚 / 下视 NaN 的根源；真值超过 e^80 的光学深度早已全遮蔽，钳顶无损
float erfcx(float x) {
    float t  = abs(x);
    float t2 = t * t;
    float num = 0.56418958354775629
              * (t2 + 2.71078540045147805 * t + 5.80755613130301624)
              * (t2 + 3.47469513777439592 * t + 12.07402036406381411)
              * (t2 + 4.00561509202259545 * t + 9.30596659485887898)
              * (t2 + 5.16722705817812584 * t + 9.1266167673673262)
              * (t2 + 5.95908795446633271 * t + 9.19435612886969243);
    float den = (t + 2.06955023132914151)
              * (t2 + 3.47954057099518960 * t + 12.06166887286239555)
              * (t2 + 3.72068443960225092 * t + 8.44319781003968454)
              * (t2 + 3.90225704029924078 * t + 6.36161630953880464)
              * (t2 + 4.03296893109262491 * t + 5.13578530585681539)
              * (t2 + 4.11240942957450885 * t + 4.48640329523408675);
    float y = num / den;

    if (x < 0.0)
        return 2.0 * exp(min(t2, SKY_ERFCX_EXP_MAX)) - y;
    else
        return y;
}

// 指数大气单条光路的闭式光学深度（Chapman 函数）
// r 路径起点距地心、z 路径方向对天顶的余弦、t 路径长度（SKY_NO_HIT = 到大气顶无穷远）、H 尺度高度
// 密度模型与有效尺度高度说明见 constants.glsl。返回值钳制 [0, SKY_AIRMASS_MAX]：下视掠射分支
// 两支 erfcx 巨值相消在 float32 下是符号不定的垃圾（钳制收敛到边界）；钳顶取值的依据见 constants.glsl
float airMass(float r, float z, float t, float H) {
    float a = 0.5 * sqrt(PI) * H * exp(-(r - EARTH_RADIUS) * (r + EARTH_RADIUS) / (H * H));
    float b = r * z / H;

    if (t > 1e29) // 哨兵即无穷远（调用方只传 SKY_NO_HIT 或有限行星命中距离）
        return clamp(a * erfcx(b), 0.0, SKY_AIRMASS_MAX);

    float c = t / H + b;
    float d = exp(min(b * b - c * c, SKY_ERFCX_EXP_MAX));

    if (z >= 0.0 || t + r * z >= 0.0)
        return clamp(a * (erfcx(b) - d * erfcx(c)), 0.0, SKY_AIRMASS_MAX);
    else
        return clamp(a * (d * erfcx(-c) - erfcx(-b)), 0.0, SKY_AIRMASS_MAX);
}

// (e^-a - e^-b) / (b - a) 的保形实现：b -> a（视线对准太阳）时极限为 e^-a
// 小 |x| 走泰勒 1 - x/2，免分子分母同归零的 0/0 与消劫
float energyIntegralRatio(float a, float b) {
    float x = b - a;
    if (abs(x) < 1e-4)
        return exp(-a) * (1.0 - x * 0.5);
    return (exp(-a) - exp(-b)) / x;
}

// Rayleigh 相函数（前后对称）
float rayleighPhase(float mu) {
    return 3.0 / (16.0 * PI) * (1.0 + mu * mu);
}

// Henyey-Greenstein 单叶（分母幂 1.5 写作 d·sqrt(d)——与 pow 等价且免 exp2/log2，d > 0 恒成立）
float henyeyGreensteinPhase(float mu) {
    float d = 1.0 + MIE_PHASE_G1 * MIE_PHASE_G1 - 2.0 * MIE_PHASE_G1 * mu;
    return 1.0 / (4.0 * PI) * (1.0 - MIE_PHASE_G1 * MIE_PHASE_G1) / (d * sqrt(d));
}

// Draine 相函数（HG 的各向异性修正，较强后向瓣；幂 1.5 同样写作 d·sqrt(d)）
float drainePhase(float mu) {
    float d = 1.0 + MIE_PHASE_G2 * MIE_PHASE_G2 - 2.0 * MIE_PHASE_G2 * mu;
    return (1.0 - MIE_PHASE_G2 * MIE_PHASE_G2) * (1.0 + MIE_PHASE_A * mu * mu)
         / (4.0 * (1.0 + (MIE_PHASE_A * (1.0 + 2.0 * MIE_PHASE_G2 * MIE_PHASE_G2)) / 3.0) * PI * d * sqrt(d));
}

// Mie 相函数：HG(g1) 与 Draine(g2, a) 按权重 w 混合（Shadertoy 原调参；g / a 参数由
// constants.glsl 的 MIE_PHASE_* 常量内嵌进两相函数，调用点单参）
float miePhase(float mu) {
    return mix(henyeyGreensteinPhase(mu),
               drainePhase(mu),
               MIE_PHASE_W);
}

// 视线与行星球面相交距离，未命中返回 SKY_NO_HIT
// r 起点距地心、z 视线天顶余弦（下视且相交时返回正距离，上视与掠射恒未命中）
float planetHitDistance(float r, float z) {
    // r²z² - (r²-R²)：把接近地表时的大数相减改写为 (r-R)(r+R)，
    // 避免地平线附近判别式在 float32 下丢失有效位。
    float altitudeTerm = (r - EARTH_RADIUS) * (r + EARTH_RADIUS);
    float d = r * r * z * z - altitudeTerm;
    if (d < 0.0)
        return SKY_NO_HIT;

    float root = sqrt(d);
    float t1 =  root - r * z;
    float t2 = -root - r * z;
    t1 = t1 < 0.0 ? SKY_NO_HIT : t1;
    t2 = t2 < 0.0 ? SKY_NO_HIT : t2;
    return min(t1, t2);
}

// 地平线方向钳制（春雷 ClampDirToHorizon 同款、+Y 天顶系简化式）：低于观察者地平线的方向投影到
// 水平面后重抬到与地球（EARTH_RADIUS）正好相切的观察者地平线切线仰角——方位保留、只抬高度；
// 天底方向（水平分量近零）方位退化取 +X 基准（与 sky.glsl skyViewLutAzimuthParam 的退化基准一致）。
// out clamped 标记方向被钳制：精确切线使 planetHitDistance 判别式在精确数学下 = 0、float 舍入噪声
// 令命中判定掷硬币（海拔 <= 0 的水平钳制分支更会 t = 0 → airMass = 0 → 黑纹素），调用方对钳后
// 射线一律按未命中处理（切线与地表仅切于一点、继续走向大气顶）。消费纪律：散射路径
//（airMass / tauSp 端点几何）用返回值，相位函数用原方向（mu 的角向变化是地平线
// 以下天空的明暗来源）；观察者位于地表及以下时切线不存在、退化为钳到水平
vec3 clampDirectionToHorizon(float observerRadius, vec3 dirWorld, out bool clamped) {
    float horizonCos = observerRadius > EARTH_RADIUS
        ? -sqrt(max((observerRadius - EARTH_RADIUS) * (observerRadius + EARTH_RADIUS), 0.0)) / observerRadius
        : 0.0;

    clamped = dirWorld.y < horizonCos;
    if (!clamped)
        return dirWorld;

    vec2 horizontal = dirWorld.xz;
    float hLen = length(horizontal);
    horizontal = hLen < 1e-4 ? vec2(1.0, 0.0) : horizontal / hLen;
    float horizonSin = sqrt(max(1.0 - horizonCos * horizonCos, 0.0));
    return vec3(horizontal.x * horizonSin, horizonCos, horizontal.y * horizonSin);
}

// 起点沿给定方向到大气顶的 RGB 消光光学深度；球对称大气只依赖起点半径与方向天顶余弦。
// composite12 的 LUT 生成端在 vsh 中对太阳 / 月亮各算一次，经 varying 传入全部 LUT texel；
// 表面直射光的 solarTransmittance 同样复用，避免三套系数表达式漂移。
vec3 opticalDepthToSpace(float r, float z) {
    return RAYLEIGH_SCATTERING_COEFFICIENTS  * airMass(r, z, SKY_NO_HIT, RAYLEIGH_SCALE_HEIGHT)
         + MIE_EXTINCTION_COEFFICIENTS       * airMass(r, z, SKY_NO_HIT, MIE_SCALE_HEIGHT)
         + OZONE_EXTINCTION_COEFFICIENTS     * airMass(r, z, SKY_NO_HIT, OZONE_SCALE_HEIGHT);
}

// 各向同性辐射场沿视线路径的散射截获比：散射反照率 × (1 - e^(-tauV))，即一束各向同性
// 辐射沿该视线穿行时被再散射出的份额（多次散射视线端的核心量）
// 分母 max 防御 t = 0 的地面垂直下视线（三介质 airMass 同时归零的 0/0）；rayleighView +
// mieView <= tauV 恒成立（臭氧纯吸收、Mie 消光 >= 散射），结果恒 ∈ [0,1]，tauV 巨大时
// exp 归零、退化为散射反照率
vec3 ambientCapture(vec3 rayleighView, vec3 mieView, vec3 tauV) {
    vec3 scatterAlbedo = (rayleighView + mieView) / max(tauV, vec3(1e-8));
    return scatterAlbedo * (vec3(1.0) - exp(-tauV));
}

// 单次散射天光（线性 HDR，未乘 SKY_BRIGHTNESS）——多次散射环境场 skyAmbientField 的求积
// 也调用本函数（不得改调含 MS 的 atmosphericRadiance：环境场会把 MS 再折进自身、双计）
// out viewCapture = 本视线的各向同性散射截获比（atmosphericRadiance 的 MS 项与 skyAmbientField
// 的截获比 ρ 统计共用一份 airMass，免二次求值）
// direction 与 phaseDirection 分离（春雷 GetSkyView 的 rayDir / phaseDir 同款语义）：direction 走
// 散射路径（airMass / tauSp 端点几何，地平线钳制时传钳后方向）、phaseDirection 只进相函数 mu（传
// 未钳制的原始方向，保地平线以下的角向明暗）；不钳制的调用方两参传同一方向即逐位等价
// origin 相机地心系位置、direction 视线方向（世界系，须归一化）、lightDirection 光源方向（同系归一化，太阳 / 月亮通用）、
// t 视线路径长度（SKY_NO_HIT = 到大气顶无穷远；天空 LUT 传行星命中距离、aerial LUT 传有限等效
// 距离——含 tauSp 端点几何的有限路径积分原生支持）、lightOpticalDepth 为起点沿光源方向到大气顶的
// 消光（LUT 生成端在 vsh 中预计算）、irradiance 大气顶光源辐照度（SOLAR_IRRADIANCE / MOON_IRRADIANCE）
// out viewCapture = 本视线的各向同性散射截获比（atmosphericRadiance 的 MS 项与 skyAmbientField 的
// 截获比 ρ 统计共用一份 airMass，免二次求值）；out viewTransmittance = exp(−tauV) 视线路径透射率
//（aerial LUT 的表面衰减项；tauV 只依赖 origin/direction/t、与光源无关，多光源调用返回同值）
vec3 atmosphericRadianceSingle(vec3 origin, vec3 direction, vec3 phaseDirection, vec3 lightDirection,
                               vec3 lightOpticalDepth, float t, vec3 irradiance,
                               out vec3 viewCapture, out vec3 viewTransmittance) {
    vec3  zenith = normalize(origin);
    float r   = length(origin);
    float z   = dot(direction, zenith);
    float zS  = dot(lightDirection, zenith);
    float mu  = dot(lightDirection, phaseDirection);
    float muRay = dot(lightDirection, direction);

    // 视线路径（相机 -> t）的各介质 air mass：散射项与消光项共用（Rayleigh 散射 = 消光，Mie 消光 = 散射 × 1.11）
    vec3 rayleighView = RAYLEIGH_SCATTERING_COEFFICIENTS  * airMass(r, z, t, RAYLEIGH_SCALE_HEIGHT);
    vec3 mieView      = MIE_SCATTERING_COEFFICIENTS       * airMass(r, z, t, MIE_SCALE_HEIGHT);
    vec3 ozoneView    = OZONE_EXTINCTION_COEFFICIENTS     * airMass(r, z, t, OZONE_SCALE_HEIGHT);
    vec3 tauV = rayleighView + mieView * 1.11 + ozoneView;

    // 起点沿光源方向到大气顶的消光（日落红化的来源）；同一半区所有 texel 共用 vsh 预计算值。
    vec3 tauS = lightOpticalDepth;

    // 视线终点沿太阳方向到大气顶的消光，天空射线（未命中）取 0；zSp 端点几何跟射线方向
    //（muRay 而非相位 mu——dot(lightDir, P̂) 的几何关系属于路径，不属于角分布）。
    // rP 钳贴地：aerial LUT 的等效路径是「沿视线方向走 t_eff 米」（放大语义），下视远距时虚拟
    // 终点半径会低于 EARTH_RADIUS（虚拟钻地）——钳到地表使 tauSp 取贴地端点（下视远处的端点
    // 消光，日落俯视时「山下雾暗、山上雾亮」分层的来源）；天空 LUT 的行星命中路径终点本就在
    // 地表附近、本钳制为无操作
    vec3 tauSp = vec3(0.0);
    if (t < 1e29) {
        float rP  = sqrt(t * t + 2.0 * z * r * t + r * r);
        rP = max(rP, EARTH_RADIUS);
        float zSp = (zS * r + muRay * t) / rP;
        tauSp = opticalDepthToSpace(rP, zSp);
    }

    // 保能量单次散射：视线路径上「被照亮部分」的加权（0/0 保形见 energyIntegralRatio）
    vec3 scatter;
    scatter.r = energyIntegralRatio(tauS.r, tauSp.r + tauV.r);
    scatter.g = energyIntegralRatio(tauS.g, tauSp.g + tauV.g);
    scatter.b = energyIntegralRatio(tauS.b, tauSp.b + tauV.b);

    viewCapture = ambientCapture(rayleighView, mieView, tauV);
    viewTransmittance = exp(-tauV);
    return irradiance * (rayleighView * rayleighPhase(mu) + mieView * miePhase(mu)) * scatter;
}

// 各向同性环境场（多次散射源项）：一阶天光球面平均 L̄₁ × 截获比几何级数 1/(1-ρ)，
// 调用端直接乘 ambientCapture 即得视线 MS 项；composite12 的 vsh 每帧每光源一次（48 节点 × ~10
// airMass，相对 40k LUT texel 可忽略）、经 varying 传入。求积节点锚定光源方向（等立体角环带、
// 带间黄金角错位）：太阳移动时节点图案随光源整体旋转，不随太阳位置错相跳变（残余为 ±10% 静态
// 偏差，进游戏并入 SKY_MS_STRENGTH 校准）；夜侧 L̄₁ 继承 tauS 饱和归零、MS 随光源熄灭。
// observerRadius / lightOpticalDepth 由 composite12 vsh 预计算（与 LUT 生成端同源）
vec3 skyAmbientField(float observerRadius, vec3 lightWorld,
                     vec3 lightOpticalDepth, vec3 irradiance) {
    // 光源锚定正交基（光源近天顶时换基准轴，免叉积退化）
    vec3 axisU = normalize(cross(abs(lightWorld.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0),
                                 lightWorld));
    vec3 axisV = cross(lightWorld, axisU);
    vec3 origin = vec3(0.0, observerRadius, 0.0);

    vec3 fieldSum   = vec3(0.0);
    vec3 captureSum = vec3(0.0);
    for (int band = 0; band < SKY_MS_QUAD_BANDS; band++) {
        // 等立体角环带：Δcosθ = 2 / 环带数，环带中心 cosθ ∈ (2band+1)/BANDS 关于 0 对称
        float cosTheta = 1.0 - (float(band) + 0.5) * (2.0 / float(SKY_MS_QUAD_BANDS));
        float sinTheta = sqrt(max(1.0 - cosTheta * cosTheta, 0.0));
        for (int j = 0; j < SKY_MS_QUAD_AZIMUTHS; j++) {
            float phi = (float(j) + 0.5) * (TAU / float(SKY_MS_QUAD_AZIMUTHS))
                      + float(band) * GOLDEN_ANGLE;
            vec3 dir = lightWorld * cosTheta
                     + (axisU * cos(phi) + axisV * sin(phi)) * sinTheta;
            float t = planetHitDistance(observerRadius, dir.y);
            vec3 capture;
            vec3 captureTrans; // 透射率 out 占位（环境场只消费 capture）
            // 求积方向两参同值（环境场是球面平均的物理量，不钳制——地平线下的暗贡献本就应计入）
            fieldSum += atmosphericRadianceSingle(origin, dir, dir, lightWorld, lightOpticalDepth,
                                                  t, irradiance, capture, captureTrans);
            captureSum += capture;
        }
    }
    float weight = 1.0 / float(SKY_MS_QUAD_BANDS * SKY_MS_QUAD_AZIMUTHS);
    vec3 rho = clamp(captureSum * weight, vec3(0.0), vec3(SKY_MS_CAPTURE_MAX));
    return fieldSum * weight / (vec3(1.0) - rho);
}

// 单次 + 多次散射天光（线性 HDR，未乘 SKY_BRIGHTNESS）：单次散射 + 各向同性环境场沿视线
// 的再散射（ambientCapture × ambientField × SKY_MS_STRENGTH，强度 0 = 退回纯单次散射）；
// ambientField = skyAmbientField 的预计算值（vsh 每帧每光源一次、经 varying 传入），
// direction / phaseDirection 的分离语义与 atmosphericRadianceSingle 一致（钳制路径 + 未钳制相位）；
// out viewTransmittance = 视线路径透射率（aerial LUT 消费，透传自 atmosphericRadianceSingle）
vec3 atmosphericRadiance(vec3 origin, vec3 direction, vec3 phaseDirection, vec3 lightDirection,
                         vec3 lightOpticalDepth, float t, vec3 irradiance,
                         vec3 ambientField, out vec3 viewTransmittance) {
    vec3 viewCapture;
    vec3 single = atmosphericRadianceSingle(origin, direction, phaseDirection, lightDirection,
                                            lightOpticalDepth, t, irradiance, viewCapture, viewTransmittance);
    return single + viewCapture * ambientField * SKY_MS_STRENGTH;
}

// 太阳直射透过率（0~1，天顶白、地平线偏红、地平线下归零）：直射辐照度 = 大气顶辐照度 × 本函数；
// deferred_init 取 vsh 相机高度近似调用（经 vDirectTransmittance varying），逐表面点路径保留此入口
vec3 solarTransmittance(vec3 origin, vec3 direction) {
    vec3  zenith = normalize(origin);
    float r = length(origin);
    float z = dot(zenith, direction);

    return exp(-opticalDepthToSpace(r, z));
}

// 天空颜色（线性 HDR）——Chapman 解析大气 + 环境场多次散射（atmosphere.glsl）的管线封装
// deferred_init 天空像素（depth >= 1）经 sky-view LUT 采样；同一物理核心供直射光着色 /
// 环境光 / 未来水面反射复用。当前太阳 + 月亮双光源、晴天（MC 日月恰好相对；月亮辐照度 = 太阳
// × 1/2000；雨天为扩展点）。日月盘 / 星盘为解析绘制（getSunDisk(World) / getMoonDisk(World) /
// getStars——世界系核心直入、视图薄壳供水反射路径，2026-10 天空分支世界方向单次化；LUT 纹素
// 角尺寸装不下这类高频内容），不进 LUT
//
// sky-view LUT（移植自春雷 Hillaire 非线性参数化，Sébastien Hillaire, EGSR 2020）：每帧在
// colortex7 左下角 200×200 重算（日 / 月半区各 200×100 ≈ 2% 屏幕成本），替代逐像素解析求值；
// 采样端只做一次双线性。球对称大气 + 单光源下天空色由 (视线天顶余弦, 视线-光源水平投影夹角
// 余弦) 完全决定——精确 2D 表示、每光源独占一个半区：
//   a ∈ [0,1] 方位角（sqrt 使纹素向光源侧集中，分辨率 SKYVIEW_LUT_W = 200）、
//   v ∈ [0,1] 天顶角（上 / 下半段各一段 sqrt 使纹素向地平线集中，分辨率 SKYVIEW_LUT_H = 100）、
//   参数域线性映射首末纹素中心（半纹素内缩）：采样不越区域边界、与相邻槽位不串色
// 依赖由接入的 program 先行 include：uniforms.glsl（sunPosition / moonPosition / colortex7 的
//   gaux4 别名——本文件采样一律走 gaux 名，gbuffers 阶段亦可同样采样 /
//   cameraPosition / rainStrength / frameTimeCounter——getStars 闪烁）、constants.glsl（TAU、
//   大气常量、SKYVIEW_*、SKYBOX_LUT_SIZE、SUN_DISK_* / MOON_DISK_* / STARS_*）、
//   utils/space.glsl（viewToWorldDirection）、utils/packing.glsl
//   （encode/decodeOctahedral——云层天空盒映射对）、utils/noise.glsl（hash13 / hash33——
//   getStars 立方体网格分格）、atmosphere.glsl（物理核心，仅解析路径与
//   LUT 生成端使用 + 日月盘 / 星盘的 planetHitDistance / opticalDepthToSpace）
// sunDirectionWorld / moonDirectionWorld 供 composite12 LUT 生成端顶点阶段调用；
// 采样端 getSkyColor 的光源方向与地平线几何为显式参数（调用方从 vsh 帧数据 varying 传入）

// 太阳方向（世界系 = 玩家对齐系，+Y 朝上）
vec3 sunDirectionWorld() {
    return normalize(viewToWorldDirection(sunPosition));
}

// 月亮方向（世界系；与太阳恰好相对——白天沉入地平线后，月亮半区按阈值写 0）
vec3 moonDirectionWorld() {
    return normalize(viewToWorldDirection(moonPosition));
}

// ---------- sky-view LUT 槽位几何（colortex7 左下角杂项簇） ----------

// LUT 全区域矩形（缓冲归一化坐标，xy = 原点、zw = 边长）：锚定缓冲底边（texel y ∈ [0, 200)）、
// 云层天空盒右侧（SKYVIEW_LUT_ORIGIN_X）；composite12 的 vsh 光栅包围盒扩展与采样端共用
vec4 skyViewLutRegionRect() {
    vec2 texel = 1.0 / vec2(textureSize(gaux4, 0));
    vec2 origin = vec2(float(SKYVIEW_LUT_ORIGIN_X), 0.0) * texel;
    vec2 size = vec2(float(SKYVIEW_LUT_W), float(2 * SKYVIEW_LUT_H)) * texel;
    return vec4(origin, size);
}

// 太阳半区矩形（区域上半 = uv y ∈ [100/H, 200/H] = 缓冲底边上方 100~200 texel 行，
// 即 fsh 判定 pixel.y ∈ [100, 200) 的那一段）
vec4 skyViewLutSunRect() {
    vec4 region = skyViewLutRegionRect();
    return vec4(region.xy + vec2(0.0, region.w * 0.5), vec2(region.z, region.w * 0.5));
}

// 月亮半区矩形（区域下半 = uv y ∈ [0, 100/H]，最贴缓冲底边，即 fsh 判定 pixel.y ∈ [0, 100) 的那一段）
vec4 skyViewLutMoonRect() {
    vec4 region = skyViewLutRegionRect();
    return vec4(region.xy, vec2(region.z, region.w * 0.5));
}

// 参数域 [0,1] → 纹素中心域（首末纹素中心对齐的半纹素内缩，春雷 utils/math.glsl 同式）
float lutParamToTexelCenter(float p, float resolution) {
    return p * (resolution - 1.0) / resolution + 0.5 / resolution;
}

// ---------- 采样端 ----------

// 世界系方向（归一化）→ LUT 天顶参数 v ∈ [0,1]（0 = 天顶、0.5 = 地平线、1 = 天底），与生成端
// skyViewLutTexel 严格互逆；只依赖 dirWorld.y 与地平线几何——日 / 月两半区共用一次求值。
// horizon 为观察者地平线几何 (cosBeta, beta, zenithHorizon)，由 vsh 帧数据传入
float skyViewLutZenithParam(vec3 dirWorld, vec3 horizon) {
    float vzc = clamp(dirWorld.y, -1.0, 1.0);
    float vzcAngle = acos(vzc);
    if (vzc >= -horizon.x) {
        float t = 1.0 - vzcAngle / horizon.z;
        return (1.0 - sqrt(clamp(t, 0.0, 1.0))) * 0.5;
    } else {
        float t = (vzcAngle - horizon.z) / horizon.y;
        return sqrt(clamp(t, 0.0, 1.0)) * 0.5 + 0.5;
    }
}

// 世界系方向 → LUT 方位参数 a ∈ [0,1]：a = sqrt((1 - lvCos) / 2)，sqrt 使纹素向光源侧集中；
// 与生成端互逆；vzSin / szSin → 0 时方位退化（天顶色与方位无关，取 +X 基准无害）
float skyViewLutAzimuthParam(vec3 dirWorld, vec3 lightWorld) {
    float vzc = clamp(dirWorld.y, -1.0, 1.0);
    float vzSin = sqrt(max(1.0 - vzc * vzc, 0.0));
    float szCos = clamp(lightWorld.y, -1.0, 1.0);
    float szSin = sqrt(max(1.0 - szCos * szCos, 0.0));
    vec2 viewHoriz = vzSin > 1e-4 ? dirWorld.xz / vzSin : vec2(1.0, 0.0);
    vec2 lightHoriz = szSin > 1e-4 ? lightWorld.xz / szSin : vec2(1.0, 0.0);
    return sqrt(clamp((1.0 - dot(viewHoriz, lightHoriz)) * 0.5, 0.0, 1.0));
}

// 半区采样：参数 → 半纹素内缩局部 uv → 缓冲 uv 双线性（日 / 月半区共用）。textureLod 0 显式
// 指定（colortex7 无 mip，免隐式导数）；有效性校验已上移 vsh 探针，采样端不逐像素检查
vec3 sampleSkyViewLutHalf(vec4 rect, vec2 param) {
    vec2 localUv = vec2(lutParamToTexelCenter(param.x, float(SKYVIEW_LUT_W)),
                        lutParamToTexelCenter(param.y, float(SKYVIEW_LUT_H)));
    return textureLod(gaux4, rect.xy + localUv * rect.zw, 0.0).rgb;
}

// LUT 尚未生成或缓冲重建时的轻量天空：只在首帧 / 无效槽位使用，不替代正常 Chapman 天空。
vec3 fallbackSkyColor(vec3 dirWorld, vec3 sunDirWorld) {
    float day = smoothstep(-0.10, 0.25, sunDirWorld.y);
    vec3 ambientRadiance = mix(NIGHT_SKY_AMBIENT, DAY_SKY_AMBIENT, day) / PI;
    float hemisphere = mix(0.18, 1.0, smoothstep(-0.15, 0.55, dirWorld.y));
    return ambientRadiance * (0.45 * SKY_BRIGHTNESS * hemisphere);
}

// 天空色采样：世界系核心（dirWorld 须已归一化）——已持世界系归一方向的调用方（fog.glsl 的
// boundaryFogColor）直入本函数，免「世界→视图→世界」mat3 往返与重复 normalize（2026-09 拆出）；
// 机制注释见下方 getSkyColor 包装（两入口同一实现 = 采样链单真源）
vec3 getSkyColorWorld(vec3 dirWorld, vec3 sunDirWorld, vec3 moonDirWorld, vec3 horizon, bool lutValid) {
    float zenithParam = skyViewLutZenithParam(dirWorld, horizon);

    vec3 color = vec3(0.0);
    if (sunDirWorld.y > SKY_LIGHT_MIN_HEIGHT)
        color += sampleSkyViewLutHalf(skyViewLutSunRect(),
                                      vec2(skyViewLutAzimuthParam(dirWorld, sunDirWorld), zenithParam));
    if (moonDirWorld.y > SKY_LIGHT_MIN_HEIGHT)
        color += sampleSkyViewLutHalf(skyViewLutMoonRect(),
                                      vec2(skyViewLutAzimuthParam(dirWorld, moonDirWorld), zenithParam));
    return lutValid ? color : fallbackSkyColor(dirWorld, sunDirWorld);
}

// 天空色采样入口（视图系方向的归一化薄壳，转世界系后委托 getSkyColorWorld）：现有消费方
//（deferred_init 天空分支 / fog 雾色 / water 反射）均持世界系方向直入核心（2026-10 天空分支
// 世界方向单次化），本壳留作未来视图系调用方的入口
// dirView 视图空间方向（不要求归一化）；光源方向 / horizon / lutValid 均由调用方从 vsh 帧数据
// 传入；返回线性 HDR，SKY_BRIGHTNESS 已在生成端乘入。日 / 月两半区和式（春雷同构），非活动半区
//（光源低于 SKY_LIGHT_MIN_HEIGHT、生成端整区写 0）以同一常量门控跳过参数化与 fetch——不变式
//「采样端跳过 ⊆ 生成端写黑」由两侧共用常量保证；LUT 内容滞后一帧（composite12 在 deferred 后执行）
vec3 getSkyColor(vec3 dirView, vec3 sunDirWorld, vec3 moonDirWorld, vec3 horizon, bool lutValid) {
    return getSkyColorWorld(normalize(viewToWorldDirection(dirView)),
                            sunDirWorld, moonDirWorld, horizon, lutValid);
}

// ---------- 云层天空盒（八面体，1 门控；colortex7 [0,SKYBOX_LUT_SIZE)² 原点 (0,0)） ----------

// 反射路径的烘焙云层（2026-09「反射不硬算云」的替代路线落地，2026-10）：composite12 每 texel
// 全量 getPlanarCloudsWorld 求值写入（rgb = 未预乘云色、a = 不透明度，2026-10 契约——标准
// alpha 合成 mix(天空, 云色, 不透明度)，云色暗时呈暗剪影），消费端（water 的
// waterSkyReflection）按反射方向单 fetch。天空本体不进烘焙（sky-view LUT 反射侧直采更清晰、
// 免八面体重采样），太阳盘不进烘焙（256² 纹素角尺寸 ~0.8° 装不下 ~2.2° 圆盘的解析锐度——
// 消费侧仍走 getSunDisk，云在其后合成、镜中日盘同被云遮挡）。映射对 = packing.glsl 的
// encode/decodeOctahedral（单真源）+ lutParamToTexelCenter 半纹素内缩（与 sky-view LUT 同纪律：
// bilinear 永不越出槽位区域）；生成端 cloudSkyboxDir 与采样端 sampleCloudSkybox 互逆、成对维护


// 生成端逆映射：天空盒纹素 local ∈ [0,SIZE)² → 世界系方向（composite12 云天空盒分支逐 texel
// 调用，方向交 getPlanarCloudsWorld 求值）
vec3 cloudSkyboxDir(ivec2 local) {
    vec2 oct = (vec2(local) + 0.5) / float(SKYBOX_LUT_SIZE);
    return decodeOctahedral(oct);
}

// 采样端：世界系方向（归一化）→ 天空盒 bilinear fetch，返回 (未预乘云色 rgb, 不透明度 a)。
// 内容为上帧 composite12 烘焙（滞后一帧与 sky-view LUT 同批）；八面体接缝处 bilinear 会混到
// 球面上相距甚远的两 texel（低频云不可分辨，gbuffer 八面体法线同款取舍）
vec4 sampleCloudSkybox(vec3 dirWorld) {
    vec2 texel = 1.0 / vec2(textureSize(gaux4, 0));
    vec2 oct = encodeOctahedral(dirWorld);
    vec2 localUv = vec2(lutParamToTexelCenter(oct.x, float(SKYBOX_LUT_SIZE)),
                        lutParamToTexelCenter(oct.y, float(SKYBOX_LUT_SIZE)));
    return textureLod(gaux4, localUv * vec2(float(SKYBOX_LUT_SIZE)) * texel, 0.0);
}

// 太阳盘（线性 HDR，deferred_init 天空分支在 getSkyColor 之后、云合成之前解析叠加——LUT 纹素
// 角尺寸远大于圆盘、只能解析绘制；先于云叠加 = 云 alpha 遮挡太阳）。颜色与地面直射光同源同式：
// SOLAR_IRRADIANCE × 沿视线大气透射率（视线对准太阳时与 vDirectTransmittance 同一条 opticalDepth-
// ToSpace 路径，日落红化与场景阳光色一致）× 雨天衰减（与 vDirectIrradiance 同系数）。origin 取
// 相机海拔近似（球对称大气下与水平位置无关，与通用全屏 vsh 的地平线几何同款 r 式）
// 地平线遮挡 = planetHitDistance：视线与地球相交即地表以下、无太阳——太阳沉没时圆盘下缘视线
// 陆续穿地被硬切，掠射带透射率已自然衰减到黑、切割处无亮度跳变；不乘 vNoonFactor 时间门（那是
// 光照切换黑过渡的语义，在高度 0→0.05 提前熄灭直射光——几何可见性交给本遮挡判定，红日出完整
// 呈现）。角距离在 1−cos 域度量（mu ≈ 0.99998 时 cos 域差仅 ~1e-5、逼近 float32 精度，1−cos 保
// 留相对精度）；远离圆盘的视线于角距离早退——绝大多数天空像素只付 1 dot（世界方向由调用方与
// LUT / 月盘 / 星盘 / 云共享一次归一，2026-10 天空分支世界方向单次化）
// dirWorld 世界系归一化视线；sunDirWorld 世界系归一化
vec3 getSunDiskWorld(vec3 dirWorld, vec3 sunDirWorld) {
    float mu = dot(dirWorld, sunDirWorld);

    // 1−cos 域边界：盘芯（全亮）与盘外（全黑），常数折叠一次
    float edgeInner = 1.0 - cos(0.0188);
    float edgeOuter = 1.0 - cos(0.0188 + SUN_DISK_SOFTEN);
    float d = 1.0 - mu;
    if (d > edgeOuter)
        return vec3(0.0);

    float r = EARTH_RADIUS + max(cameraPosition.y, 1.0);
    if (planetHitDistance(r, dirWorld.y) < 1e29)
        return vec3(0.0); // 视线打到地面（含掠地平线下沿）——地表以下无太阳

    float disk = 1.0 - smoothstep(edgeInner, edgeOuter, d);
    vec3 transmittance = exp(-opticalDepthToSpace(r, dirWorld.y));
    return SOLAR_IRRADIANCE * transmittance * (450.0 * disk)
         * (1.0 - SUN_DISK_RAIN_FADE * rainStrength);
}

// 视图系薄壳（消费方 = water 反射的 waterSkyReflection，持反射观察系方向）：归一化转世界系后
// 委托 getSunDiskWorld；dirView 不要求归一化
vec3 getSunDisk(vec3 dirView, vec3 sunDirWorld) {
    return getSunDiskWorld(normalize(viewToWorldDirection(dirView)), sunDirWorld);
}

// 月亮盘（线性 HDR，满月圆盘、无月相 / 贴图）：与 getSunDisk 同构同纪律——太阳盘条目所述机制
// 全量适用（1−cos 域角距离 + 远盘早退、planetHitDistance 地平线硬切、沿视线透射率红化、雨衰）。
// 亮度 = MOON_IRRADIANCE × 透射率 × 视觉增益（250.0）：色度与地面月光同源——
// 月下场景直射色与月盘自动一致，月出红化物理呈现；不乘 nightFactor 时间门（几何可见性交给
// planetHitDistance，太阳盘同款——红月出完整呈现）。白天月亮在地平线下（日月恰好相对）、
// 被地平线遮挡整段早退，零成本。世界系核心（dirWorld 须已归一化——deferred_init 共享方向直入，
// 2026-10 天空分支世界方向单次化）+ 视图薄壳（消费方 = water 反射路径）
vec3 getMoonDiskWorld(vec3 dirWorld, vec3 moonDirWorld) {
    float mu = dot(dirWorld, moonDirWorld);

    float edgeInner = 1.0 - cos(MOON_DISK_RADIUS);
    float edgeOuter = 1.0 - cos(MOON_DISK_RADIUS + MOON_DISK_SOFTEN);
    float d = 1.0 - mu;
    if (d > edgeOuter)
        return vec3(0.0);

    float r = EARTH_RADIUS + max(cameraPosition.y, 1.0);
    if (planetHitDistance(r, dirWorld.y) < 1e29)
        return vec3(0.0); // 视线打到地面——地表以下无月亮

    float disk = 1.0 - smoothstep(edgeInner, edgeOuter, d);
    vec3 transmittance = exp(-opticalDepthToSpace(r, dirWorld.y));
    return MOON_IRRADIANCE * transmittance * (250.0 * disk)
         * (1.0 - MOON_DISK_RAIN_FADE * rainStrength);
}

vec3 getMoonDisk(vec3 dirView, vec3 moonDirWorld) {
    return getMoonDiskWorld(normalize(viewToWorldDirection(dirView)), moonDirWorld);
}

// 星盘（线性 HDR，立方体网格 hash 点星——零贴图资产 / 零新缓冲）：星图与月固连——视线方向绕
// 世界 Z 把月亮 xy 相位旋回 +X 后作 hash 输入（旋转由月亮方向 xy 归一构造、零超越函数），
// 任意天球姿态下「星-月夹角恒定」结构性成立：星星随月东升西落、相对位置不动（天球旋转相位由
// 月亮方向锚定推导，无须知道轨道倾角 / sunAngle；MC 日月恰好相对 ⇒ 亦与太阳同步）。夜门 =
// 太阳高度 smoothstep 渐显（白天 / 暮光前段于门处整段早退、只付 1 dot）；地平线以下视线打到
// 行星无星（日月盘同款判定，置于 hash 门之后——仅稀疏幸存格子付 planetHit）；雨天淡出。
// 星星不随主导光源阴影门控（恒星无对应遮蔽信息，桥影挡月光不挡星光）。仅 deferred_init 主天空
// 消费——世界系入参（dirWorld 由调用方与 LUT / 日月盘 / 云共享一次归一，2026-10 天空分支世界
// 方向单次化）；water 反射不渲染星盘（2026-10 按反馈：星点经波面法线搅碎 + Fresnel 低透过率后
// 不可辨）。
// 末地消费（2026-10 星盘接入末地）：deferred_init 极简档内 #if defined(END) && defined(1)
// 同源调用——夜门常开（末地 fixed_time 定格正午、太阳高度门恒关，而末地是无昼夜循环的暗夜虚空）
// + planetHit 切割剔除（虚空世界无地平线语义、星图覆盖全球——否则眼平面把虚空天空硬切成
// 有星 / 无星两半）；主世界档逐位不变，下界不接入（封闭洞窟无天）
// 早退链：夜门 → 旋转 → hash 门（1 − 0.15 的格子直接 return）→
// planetHit → 点星；绝大多数夜空像素只付 1 dot + 4 mul + 1 hash
vec3 getStars(vec3 dirWorld, vec3 sunDirWorld, vec3 moonDirWorld) {

    float nightGate = 1.0 - smoothstep(STARS_FADE_LOW, STARS_FADE_HIGH, sunDirWorld.y);
    if (nightGate <= 0.0)
        return vec3(0.0);

    // 星图方向：绕世界 Z 旋回月亮相位（R(−θ)，θ = atan2(m.y, m.x)——cosθ/sinθ 由归一 xy 直接
    // 给出，免 atan）；月轨倾角 30° 下 |moon.xy| ≥ 0.5 恒远离退化，守卫仅防御性
    vec2 anchor = moonDirWorld.xy;
    float anchorLen = length(anchor);
    vec2 rot = anchorLen > 1e-4 ? anchor / anchorLen : vec2(1.0, 0.0);
    vec3 starDir = vec3(dirWorld.x * rot.x + dirWorld.y * rot.y,
                        -dirWorld.x * rot.y + dirWorld.y * rot.x,
                        dirWorld.z);

    // 立方体网格分格：格 hash 门稀疏化 + 格内随机偏移点星（偏移钳 [0.25,0.75] 星形完整不出格）
    vec3 sp = starDir * STARS_GRID_SCALE;
    vec3 cell = floor(sp);
    float cellRand = hash13(cell);
    if (cellRand > 0.15)
        return vec3(0.0);

    float r = EARTH_RADIUS + max(cameraPosition.y, 1.0);
    if (planetHitDistance(r, dirWorld.y) < 1e29)
        return vec3(0.0); // 地平线以下——地表背面无星

    vec3 h3 = hash33(cell);
    float d = length(sp - cell - (vec3(0.25) + 0.5 * h3));
    float point = clamp(1.0 - d * STARS_FALLOFF, 0.0, 1.0);
    point *= point; // 平方衰减：中心亮、边缘速灭（亚像素过渡交 TAA）

    // 亮度：幂分布（多数暗星少数亮星）+ 正弦闪烁（逐星相位 h3.y）
    float magnitude = 0.2 + 0.8 * h3.z * h3.z;
    float twinkle = 1.0 - STARS_TWINKLE_DEPTH
                  * (0.5 + 0.5 * sin(frameTimeCounter * STARS_TWINKLE_SPEED * TAU + h3.y * TAU));
    return vec3(0.3 * magnitude * point * twinkle * nightGate
              * (1.0 - STARS_RAIN_FADE * rainStrength));
}

// ---------- 生成端（composite_bloom_upsample / composite12） ----------

// 解析天色（世界系方向直接求值 Chapman + 环境场 MS）：LUT 生成核心，也是解析路径的完整保留。
// observerRadius / lightOpticalDepth / ambientField（atmosphere.glsl 的 skyAmbientField）由
// composite12 vsh 每帧预计算，避免每个 LUT texel 重复相机半径、光源路径 Chapman 与 48 节点求积
// 1（春雷 GetSkyView 同位语义）：地平线以下方向的散射路径钳到与地球正好相切的
// 观察者地平线切线、钳后射线一律按未命中求值（机制与刀锋数值防护见 atmosphere.glsl 的
// clampDirectionToHorizon 头注）；相位透传未钳制的 dirWorld——Rayleigh / Mie 的 mu 保角向变化，
// 地平线以下的 LUT 行因此 = 地平线辉光 × 按真实方向的相位调制，采样端（getSkyColor）零改动
vec3 skyRadianceAnalytic(float observerRadius, vec3 dirWorld, vec3 lightWorld,
                         vec3 lightOpticalDepth, vec3 irradiance, vec3 ambientField) {
    vec3 origin = vec3(0.0, observerRadius, 0.0);
    vec3 rayDir = dirWorld;
    float t;
    bool clampedToHorizon;
    rayDir = clampDirectionToHorizon(observerRadius, dirWorld, clampedToHorizon);
    t = clampedToHorizon ? SKY_NO_HIT : planetHitDistance(observerRadius, rayDir.y);

    vec3 transmittance; // 视线路径透射率 out 占位（天空色只消费散射项）
    return atmosphericRadiance(origin, rayDir, dirWorld, lightWorld, lightOpticalDepth, t, irradiance,
                               ambientField, transmittance)
         * SKY_BRIGHTNESS;
}

// 生成端共用的局部系方向逆映射：纹素中心参数 (azimuthParam, zenithParam) → 局部系方向——
// 「光源水平投影 = +X、光源位于 XY 平面内」的局部系构造（球对称大气的散射只依赖 (vzc, szCos,
// mu)，与真实方位仅差绕天顶旋转、结果等价）。sky-view 半区（下方 skyViewLutTexel）与 aerial LUT
//（aerial.glsl 的 aerialLutTexel，须于本文件之后引入）共用本函数——逆映射公式单真源（曾两处
// 成对维护，2026-10 收敛）；与采样端 skyViewLutAzimuthParam / skyViewLutZenithParam 互逆
vec3 skyViewLutLocalDirection(float azimuthParam, float zenithParam, vec3 horizon) {
    float beta = horizon.y;
    float zenithHorizon = horizon.z;

    float vzc;
    if (zenithParam < 0.5) {
        float q = 1.0 - 2.0 * zenithParam;
        vzc = cos(zenithHorizon * (1.0 - q * q));
    } else {
        float q = 2.0 * zenithParam - 1.0;
        vzc = cos(zenithHorizon + beta * (q * q));
    }
    float vzSin = sqrt(max(1.0 - vzc * vzc, 0.0));

    float lvCos = 1.0 - 2.0 * azimuthParam * azimuthParam;
    float lvSin = sqrt(max(1.0 - lvCos * lvCos, 0.0));

    return vec3(vzSin * lvCos, vzc, vzSin * lvSin);
}

// 半区 texel → 天色：local.x ∈ [0, SKYVIEW_LUT_W)（a = 0 在光源侧）、local.y ∈ [0, SKYVIEW_LUT_H)
//（j = 0 为天顶行——半区靠缓冲底边的行，与采样端 y 映射互逆）；ambientField 为 vsh 预计算的
// 多次散射环境场（透传给 skyRadianceAnalytic）
vec3 skyViewLutTexel(ivec2 local, float observerRadius, vec3 horizon,
                     vec3 lightWorld, vec3 lightOpticalDepth, vec3 irradiance,
                     vec3 ambientField) {
    // 纹素中心参数（采样端 skyViewLutAzimuthParam / skyViewLutZenithParam 的逆映射）
    float azimuthParam = float(local.x) / float(SKYVIEW_LUT_W - 1);
    float zenithParam = float(local.y) / float(SKYVIEW_LUT_H - 1);

    float szCos = clamp(lightWorld.y, -1.0, 1.0);
    float szSin = sqrt(max(1.0 - szCos * szCos, 0.0));

    vec3 localLight = vec3(szSin, szCos, 0.0);
    return skyRadianceAnalytic(observerRadius,
                               skyViewLutLocalDirection(azimuthParam, zenithParam, horizon),
                               localLight, lightOpticalDepth, irradiance, ambientField);
}

// 大气散射雾 / 空气透视（aerial perspective，宏 1 门控；设计全文见
// plans/地表大气散射方案.md）
// 物理式空气透视：finalColor = surface × T(viewDir, dist) + S(viewDir, dist)——S = 相机→表面
// 路径上大气再散射进视线的光（inscatter，加光项）、T = 同一路径透射率（表面衰减项）；观感上仍是
// 「远处 mix 向天光色」，但雾色随方向 × 距离 × 时刻连续变化：逆光发白（Mie 前向峰）、顺光偏蓝、
// 抬头散去、日落时山下暗山上亮（路径末端进入地球阴影）——正是边界雾「无光照方向性 / 无高度衰减」
// 已知限制要补的东西。与边界雾两段式分工（非替代）：aerial 管中近距物理空气感，boundary 兜
// 0.7~0.9·far 渲染边界硬融接（MC 视距内物理融合度上限低——水平 inscatter 渐近到天空色需数百 km
// 等效路径，far 端硬融接不可能由物理路径独立完成）。
// 供给形态 = 小 LUT（Hillaire 2020 aerial LUT 思想、地面玩家海拔近似恒定砍一维、Chapman 解析生成
// 砍 march）：colortex7 原点 (AERIAL_LUT_ORIGIN_X, 0) = (460, 0)——sky-view LUT 右侧水平续接、
// 同锚缓冲底边（原址天空盒预留区左下角 (0,0)，2026-10 八面体云层天空盒启用、[0,256)² 整块归还
// 天空盒而迁此）；区域 AERIAL_LUT_W × (AERIAL_LUT_H × AERIAL_LUT_SLICES) 纵向堆叠（方向 64×48
// × 距离 4 档）。RGBA16F：rgb = inscatter
//（含 MS 项、已乘 SKY_BRIGHTNESS、双光源和式），a = 透射率绿通道（标量，chromatic 透射为扩展点）。
// 生成端 = composite12（composite_bloom_upsample 2 0）天空 LUT 重算 pass 的区域分支，
// 帧常量（observerRadius / horizon / 日月方向 / tauS / ambientField）复用天空 LUT 的 vsh varying、
// vsh 零新增；有效性 / 滞后一帧与天空 LUT 同源同批（同 pass 写入、vSkyLutValid 共用探针）。
// 消费端 = composite_fog（composite2）几何分支、applyBoundaryFog 之前；距离 / 方向与边界雾共用
// depthtex0 去抖重建。第二消费方 = water 反射命中段（lib/water/reflection.glsl 的 waterReflectionHitFog，2026-10：
// SSR 命中色取自无雾快照，命中段经 applyAerialPerspective 以「折线全长 × 段方向」的虚拟视位置施加
// ——见其头注）。起始门（AERIAL_FOG_START / END）：约 far/6 内无雾、效果域 smoothstep 自零
// 渐入至 0.7·far 全强（见 applyAerialPerspective）。三条不变式（违反即地平线接缝 / double-scatter，机制见 constants.glsl
// AERIAL 分区与方案 §2）：①放大距离不放大密度（渐近 = 天空色）、雨天走距离域乘子；②∞ 档 =
// t = SKY_NO_HIT 的求值（地平线以上方向与 sky LUT 同参数同值，结构性融接）；③天空像素不施加
//（调用方 depth >= 1 分支在外）。删宏 = aerial 段编译剔除、composite12 该区域落入透传分支保值、
// composite_fog 回退纯边界雾——开关 / 数值分离纪律同 1 / 1
// **下界统一雾档（FOG_UNIFIED_COLOR，2026-10）**：1 经 FOG_UNIFIED_COLOR 恢复
// 定义（末地不定义、无雾极简档照旧），但雾不取 LUT——LUT 生成端（composite12 区域分支）与
// 本文件的生成 / 采样助手（aerialLutTexel / aerialLutFetch / sampleAerialLut）在统一档全部编译
// 剔除，applyAerialPerspective 换**均匀介质解析式**：T = exp(−σ·d)、S = NETHER_FOG_COLOR × (1−T)
//（与「mix 向统一雾色」严格等价、d→∞ 渐近雾色 = 天色常量——主世界三不变式的「渐近 = 天空色」
// 在此结构性成立），无方向依赖 / 无 lutValid 依赖（首帧即正确）；起始门纪律同主世界
//（C1 smoothstep 渐入、fade 乘「原表面 vs 雾化结果」的 mix），常量 σ / 起止见 constants.glsl
// 边界雾分区的下界统一雾段（NETHER_AERIAL_*）。入参签名两档一致（LUT 档帧数据参数在统一档
// 为死参），消费点（composite_fog / waterReflectionHitFog）零改动
// 依赖由接入的 program 先行 include：constants.glsl（AERIAL_*、SKY_LIGHT_MIN_HEIGHT、
//   SKY_BRIGHTNESS、SKY_NO_HIT、SOLAR / MOON_IRRADIANCE；统一档另 NETHER_FOG_COLOR / NETHER_AERIAL_*）、
//   uniforms.glsl（gaux4 = colortex7 / isEyeInWater / rainStrength / far——起始门）、
//   atmosphere.glsl（atmosphericRadiance，仅 LUT 档）、sky.glsl（skyViewLutZenithParam /
//   skyViewLutAzimuthParam / lutParamToTexelCenter / skyViewLutLocalDirection——方向参数化互逆组
//   与生成端局部方向的单真源复用；仅 LUT 档）、utils/space.glsl（viewToWorldDirection，仅 applyAerialPerspective 的 LUT 档）



// ---------------- 生成端（composite12 / composite_bloom_upsample 2 0） ----------------

// aerial LUT texel → (inscatter × SKY_BRIGHTNESS, 透射率)：localPos.x ∈ [0, AERIAL_LUT_W) 方位、
// localPos.y ∈ [0, AERIAL_LUT_H × SLICES)（天顶行 = y % H、距离档 = y / H，档 0~2 有限等效距离、
// 末档 ∞）。方向反参数化经 sky.glsl 的 skyViewLutLocalDirection 单真源（「光源水平投影 = +X、光源
// 位于 XY 平面内」的局部系构造——球对称大气的散射只依赖 (vzc, szCos, mu)，与真实方位仅差绕天顶
// 旋转）、分辨率独立；公式曾与 skyViewLutTexel 成对维护、2026-10 收敛。方向不做地平线钳制（aerial
// 是真实视线的有限路径
// 几何，含下视；下视远距的虚拟钻地由 atmosphericRadianceSingle 内 rP 钳贴地防护）。方位锚 =
// 主导光源（与采样端同一判定）：交接发生在主导者沉入 SKY_LIGHT_MIN_HEIGHT 时、另一侧已接棒，
// LUT 值本身连续（同物理），参数化重排经 TAA 吸收。双光源和式（散射积分对光源线性、不分半区），
// 各光源低于阈值跳过求值（与天空 LUT 非活动半区写黑同一纪律）；次光源 = 锚的反向（MC 日月恰好
// 相对）。tauS / ambientField 为 composite12 vsh 预计算的同名帧数据（与天空 LUT 生成端同源）
vec4 aerialLutTexel(ivec2 localPos, float observerRadius, vec3 horizon,
                    vec3 sunDirection, vec3 sunOpticalDepth, vec3 sunAmbientField,
                    vec3 moonDirection, vec3 moonOpticalDepth, vec3 moonAmbientField) {
    int slice = localPos.y / AERIAL_LUT_H;
    int row   = localPos.y - slice * AERIAL_LUT_H;

    // 纹素中心参数（采样端 skyViewLutAzimuthParam / skyViewLutZenithParam 的逆映射，经 sky.glsl
    // 的 skyViewLutLocalDirection 单真源——公式曾与 skyViewLutTexel 成对维护、2026-10 收敛）

    // 方位锚 = 主导光源（采样端 sampleAerialLut 同一判定，两端联动）；局部系构造同 skyViewLutTexel
    bool sunAnchored = sunDirection.y > SKY_LIGHT_MIN_HEIGHT;
    vec3 anchorWorld = sunAnchored ? sunDirection : moonDirection;
    float szCos = clamp(anchorWorld.y, -1.0, 1.0);
    float szSin = sqrt(max(1.0 - szCos * szCos, 0.0));
    vec3 localAnchor = vec3(szSin, szCos, 0.0);
    vec3 localSun  = sunAnchored ?  localAnchor : -localAnchor; // 次光源 = 锚的反向（日月恰好相对）
    vec3 localMoon = sunAnchored ? -localAnchor :  localAnchor;

    // 距离档：末档 ∞（天空渐近、与 sky LUT 同构——不变式②）；有限档为等效路径米数
    float t = slice < AERIAL_LUT_SLICES - 1 ? AERIAL_DIST_SLICES[slice] : SKY_NO_HIT;

    vec3 origin = vec3(0.0, observerRadius, 0.0);
    vec3 dirLocal = skyViewLutLocalDirection(float(localPos.x) / float(AERIAL_LUT_W - 1),
                                             float(row) / float(AERIAL_LUT_H - 1),
                                             horizon);
    vec3 inscatter = vec3(0.0);
    // 透射率与光源无关（tauV 只依赖 origin/direction/t），任一活动光源的调用带回即可；
    // 日月恰好相对、双侧同时低于阈值的构型不存在，防御初值 1（无衰减）仅兜底
    vec3 transmittance = vec3(1.0);
    if (sunDirection.y > SKY_LIGHT_MIN_HEIGHT) {
        inscatter += atmosphericRadiance(origin, dirLocal, dirLocal, localSun,
                                         sunOpticalDepth, t, SOLAR_IRRADIANCE,
                                         sunAmbientField, transmittance);
    }
    if (moonDirection.y > SKY_LIGHT_MIN_HEIGHT) {
        vec3 transMoon;
        inscatter += atmosphericRadiance(origin, dirLocal, dirLocal, localMoon,
                                         moonOpticalDepth, t, MOON_IRRADIANCE,
                                         moonAmbientField, transMoon);
        if (sunDirection.y <= SKY_LIGHT_MIN_HEIGHT) transmittance = transMoon; // 日光分支未跑才取月侧带回
    }
    return vec4(inscatter * SKY_BRIGHTNESS, transmittance.g);
}

// ---------------- 采样端（composite_fog 几何分支） ----------------

// 单档 fetch：方向参数 → 半纹素内缩局部 uv（lutParamToTexelCenter 同款纪律——相邻 texel 是同
// 方向不同距离，防跨档条带串色）→ 切片平移 → 缓冲 uv 双线性。textureLod 0 显式（colortex7 无 mip）；
// 采样位置的去抖方向已含当前帧 jitter 相位（与 deferred_init 天空采样同构，facet 交由 TAA 抹平）
vec4 aerialLutFetch(vec2 param, int slice) {
    vec2 texel = 1.0 / vec2(textureSize(gaux4, 0));
    vec2 localUv = vec2(lutParamToTexelCenter(param.x, float(AERIAL_LUT_W)),
                        lutParamToTexelCenter(param.y, float(AERIAL_LUT_H)));
    vec2 rectOrigin = vec2(float(AERIAL_LUT_ORIGIN_X), float(slice * AERIAL_LUT_H)) * texel;
    vec2 rectSize = vec2(float(AERIAL_LUT_W), float(AERIAL_LUT_H)) * texel;
    return textureLod(gaux4, rectOrigin + localUv * rectSize, 0.0);
}

// 世界方向（归一化）+ 等效路径距离 → vec4(inscatter, 透射率)；tEff = 真距 × 7.111111 ×
// 雨天乘子（调用方算好）。档间按线性距离权重 lerp（inscatter 未饱和段近似线性于 t）；tEff 超过
// 档 2 后向 ∞ 档按 w = 1 − S2/t 收尾：无穷远无法作线性 lerp 端点（无穷分母 w 恒 0），直接跳 ∞ 档
// 会在档 2 距离环上留不连续；w 在 t = S2 处 0（与 slice2 段连续）、t → ∞ 收敛 1（渐近不变式），
// 剩余路径比例的物理直觉。档 0 以下向相机线性归零（见函数内注释）
vec4 sampleAerialLut(vec3 dirWorld, float tEff, vec3 sunDirWorld, vec3 moonDirWorld, vec3 horizon) {
    // 方位锚与生成端同一判定（两端联动）；参数函数复用 sky 的互逆组（分辨率无关、单真源）
    vec3 anchorLight = sunDirWorld.y > SKY_LIGHT_MIN_HEIGHT ? sunDirWorld : moonDirWorld;
    vec2 param = vec2(skyViewLutAzimuthParam(dirWorld, anchorLight),
                      skyViewLutZenithParam(dirWorld, horizon));

    if (tEff < AERIAL_DIST_SLICES[0]) {
        // 档 0 以下：LUT 层无起始阈值、向相机原点线性归零（t = 0 时 inscatter 0 / 透射率 1）——
        // 起始门在 applyAerialPerspective 的效果域（far/6），小 far 时渐入带前段仍落入本分支。
        // 首代「tEff < 档 0 整段跳过」在起始距离环上留一档 LUT[S0] 的亮度阶（世界系固定环、随
        // 地形移动，平滑地面上可见，2026-09 按反馈移除）；短路径 inscatter ∝ t、1−T ∝ t，线性
        // 外推即物理一阶近似；单 fetch（无档间 lerp）
        vec4 s0 = aerialLutFetch(param, 0);
        float w = tEff / AERIAL_DIST_SLICES[0];
        return vec4(s0.rgb * w, mix(1.0, s0.a, w));
    }
    if (tEff >= AERIAL_DIST_SLICES[2]) {
        float w = clamp(1.0 - AERIAL_DIST_SLICES[2] / tEff, 0.0, 1.0);
        return mix(aerialLutFetch(param, 2), aerialLutFetch(param, AERIAL_LUT_SLICES - 1), w);
    }
    if (tEff < AERIAL_DIST_SLICES[1]) {
        float w = (tEff - AERIAL_DIST_SLICES[0]) / (AERIAL_DIST_SLICES[1] - AERIAL_DIST_SLICES[0]);
        return mix(aerialLutFetch(param, 0), aerialLutFetch(param, 1), w);
    }
    float w = (tEff - AERIAL_DIST_SLICES[1]) / (AERIAL_DIST_SLICES[2] - AERIAL_DIST_SLICES[1]);
    return mix(aerialLutFetch(param, 1), aerialLutFetch(param, 2), w);
}


// 总入口：color 就地施加空气透视（surface × T + S）。viewPos 为去抖重建的观察空间位置（几何
// 像素）；天空像素由调用方分支在外（不变式③）。早退链 = 水下（与边界雾同一纪律）→ LUT 无效
//（首帧 / 缓冲重建，跳过 = 恒等；统一档无此依赖）→ 近距（fade = 0，公式值恰为 0 的恒等跳过、
// 零 fetch）。**起始距离门（2026-09 按反馈接入；2026-10 按反馈自 far/3 拉近至 far/6——中近距
// 看不出来雾）**：AERIAL_FOG_START（far/6）内无雾、smoothstep 至 AERIAL_FOG_END（0.7·far =
// BOUNDARY_FOG_START 接力锚）全强——fade 乘在「原表面 vs 雾化结果」的 mix 上（T / S 随 fade
// 同步缩放，半 fade = 部分雾）；smoothstep 起点系数恒 0 且零斜率（C1）、环内外值同为 0——与
// 首代「早退 = 0 / 环外立刻满档 LUT[S0]」的值阶环不同构（sampleAerialLut 内注释的教训），
// 起始距离环结构性不可见；渐满点后远端强度与门前逐位相同（SCALE 调定的观感不受影响）。
// 渐入带内几何像素成本 = 档 0 以下 1 fetch、档间 lerp 2 fetch + 1 smoothstep（统一档 = 1 exp + 1 mix）
void applyAerialPerspective(inout vec3 color, vec3 viewPos,
                            vec3 sunDirWorld, vec3 moonDirWorld, vec3 horizon, bool lutValid) {
    if (isEyeInWater != 0 || !lutValid) return;

    float distWorld = length(viewPos);
    // 起始门系数：效果域（非 tEff 偏移——不动档位映射与渐近不变式②，远端强度不变）
    float fade = smoothstep(far * AERIAL_FOG_START, far * AERIAL_FOG_END, distWorld);
    if (fade <= 0.0) return;

    // 等效路径 = 真距 × 放大 × 雨天加浓（距离域乘子，保渐近不变式①——密度域调制禁用）
    float tEff = distWorld * 7.111111 * (1.0 + AERIAL_RAIN_BOOST * rainStrength);

    vec4 aerial = sampleAerialLut(normalize(viewToWorldDirection(viewPos)), tEff,
                                  sunDirWorld, moonDirWorld, horizon);
    color = mix(color, color * aerial.a + aerial.rgb, fade);
}


















// 帧数据取值实现（skyAmbientColor / frameDirectIrradiance / observerHorizonGeometry）+ 前向简单
// 光照（forwardLightmapShade / forwardEntityShade，含单 tap 硬阴影读取端 shadowTex1HardVisibility）
// ——skyAmbientColor 由通用全屏 vsh（fullscreen_vsh）与前向 program（gbuffers_translucent_simple）
// 各自的 vsh 共用：colortex7 天空 LUT 两半区天顶行探针 fetch 双重职责——rgb = 各光源天顶色精确值
//（球对称大气下天顶色与方位无关）、alpha = 有效性标记；有效取 (太阳 + 月亮) × SKY_AMBIENT_BRIGHTNESS
//（与 getSkyColor 天顶采样同式、非活动半区写黑自动零贡献，色调 / 幅度随 LUT 自动跟进：昼夜 / 曙暮光 /
// 海拔 / MS，与渲染天空同源同帧滞后），无效回退常量昼夜 mix；雨天去饱和最后并入。lutValid out 参数即
// vSkyLutValid 的判定源（不消费的调用方丢弃）。frameDirectIrradiance / observerHorizonGeometry 是
// vDirectIrradiance / vHorizon 两帧数据的取值实现——通用全屏 vsh 与「自带 vsh 输出同名 varying」的
// 前向 program（gbuffers_translucent / gbuffers_opaque_entities）及 composite12 的 LUT 生成端 /
// 云烘焙帧数据此前在各 vsh 手抄同式（「同名同式」靠人肉成对维护），2026-10 收敛为单真源、由共用
// 结构性保证
// 依赖先行 include：lib/common/globals/uniforms.glsl（colortex7 / frameCounter / sunAngle /
//   rainStrength / cameraPosition——observerHorizonGeometry；shadowTex1HardVisibility 另消费
//   shadowtex1；forwardEntityShade 另消费 shadowDistance）+ lib/common/globals/constants.glsl
//   （TAU / SKYVIEW_* / SKYVIEW_LUT_VALID_MARKER / SKY_AMBIENT_BRIGHTNESS / 昼夜回退常量 /
//   TORCHLIGHT_* / MIN_AMBIENT / FORWARD_LIGHTMAP_BRIGHTNESS（forwardLightmapShade 亮度倍率）/
//   PI / EARTH_RADIUS / TIME_NOON_RAMP / TIME_NIGHT_RAMP /
//   SOLAR_IRRADIANCE / MOON_IRRADIANCE——帧数据两函数；末地另需 END_SKY_AMBIENT（skyAmbientColor
//   的 END 早退）；forwardEntityShade / shadowTex1HardVisibility 另需 SHADOW_BIAS_* /
//   shadowMapResolution）+ utils/space.glsl（relativeWorldToShadowScreen——shadowTex1HardVisibility /
//   forwardEntityShade；viewToWorldDirection / viewToRelativeWorld 仅 forwardEntityShade）
//   ——现有全部消费方（含通用全屏 vsh 与 lib/water/surface.glsl 的接入方）的平铺顺序均已满足

// 返回天空环境辐照度基色；lutValid = 探针判定的 LUT 有效性（0/1）
vec3 skyAmbientColor(out float lutValid) {








    // 探针取各半区角 texel（太阳半区天顶行 (260,100)、月亮半区天顶行 (260,0)）——无效内容在整片
    // 区域同现、单 texel 探针足以拦截；NaN 对比较返回 false、同样落入无效分支。
    // gaux4 = colortex7 的采样别名——本函数的消费者含 gbuffers vsh（前向 program），gbuffers
    // 阶段读缓冲须用 gaux 名（deferred / composite 阶段两者同单元等价）
    vec4 skySunProbe  = texelFetch(gaux4, ivec2(SKYVIEW_LUT_ORIGIN_X, SKYVIEW_LUT_H), 0);
    vec4 skyMoonProbe = texelFetch(gaux4, ivec2(SKYVIEW_LUT_ORIGIN_X, 0), 0);
    bool skyLutValid = frameCounter > 0
                && abs(skySunProbe.a - SKYVIEW_LUT_VALID_MARKER) < 1e-3
                && abs(skyMoonProbe.a - SKYVIEW_LUT_VALID_MARKER) < 1e-3
                && all(lessThan(abs(skySunProbe.rgb), vec3(65000.0)))
                && all(lessThan(abs(skyMoonProbe.rgb), vec3(65000.0)));
    lutValid = skyLutValid ? 1.0 : 0.0;

    // 无效回退：常量昼夜 mix，权重 = 太阳高度慢族门（过渡窗比直射门宽、晨昏环境不断黑）
    float dayFactor = smoothstep(-0.10, 0.25, sin(sunAngle * TAU));
    vec3 ambient = mix(NIGHT_SKY_AMBIENT, DAY_SKY_AMBIENT, dayFactor);
    if (skyLutValid) {
        ambient = (skySunProbe.rgb + skyMoonProbe.rgb) * SKY_AMBIENT_BRIGHTNESS;
    }
    // 雨天去饱和：向亮度单色略偏冷 mix（幂雨天空灰蓝）
    return mix(ambient, vec3(dot(ambient, vec3(0.3333))) * vec3(0.90, 0.95, 1.05), rainStrength);
}

// 统一时间系统的门控加权和直射辐照度（vDirectIrradiance 的取值实现，任意阶段可用——vsh 意图）：
// 太阳 / 月亮各自世界高度的线性门（日月恰好相对、两门永不同时为正，门控加权和即「按光源选边 +
// 切换瞬间双 0 黑过渡」；晨昏主光源切换的阴影跳变由本黑过渡吸收）+ 雨天衰减。入参 = 两光源世界
// 高度（sunHeight 恒取 sin(sunAngle·TAU) 的时间门高度、moonHeight 取月亮世界方向 y——与
// fullscreen_vsh 的 vSunHeight / vMoonHeight 同源）。消费方：通用全屏 vsh、gbuffers_translucent /
// gbuffers_opaque_entities 的自带 vsh、composite12 云天空盒烘焙帧数据（此前四处手抄同式）
vec3 frameDirectIrradiance(float sunHeight, float moonHeight) {
    float noonFactor  = clamp(sunHeight  * TIME_NOON_RAMP,  0.0, 1.0);
    float nightFactor = clamp(moonHeight * TIME_NIGHT_RAMP, 0.0, 1.0);
    return (noonFactor * SOLAR_IRRADIANCE + nightFactor * MOON_IRRADIANCE)
         * (1.0 - 0.75 * rainStrength);
}

// 观察者地平线几何 (cosBeta, beta, zenithHorizon)：beta = 地平线到天底的角跨度、zenithHorizon =
// 天顶到地平线的角跨度（与 sky.glsl 生成端 skyViewLutTexel 同式——观察者半径取相机 / 玩家海拔
// 近似）。消费方：通用全屏 vsh（vHorizon）、gbuffers_translucent 的自带 vsh、composite12 LUT
// 生成端（vSkyHorizon——此前三处手抄同式）；采样端经帧数据 varying 透传，不重复求值
vec3 observerHorizonGeometry() {
    float r = EARTH_RADIUS + max(cameraPosition.y, 1.0);
    float altitudeTerm = max((r - EARTH_RADIUS) * (r + EARTH_RADIUS), 0.0);
    float cosBeta = sqrt(altitudeTerm) / r;
    float beta = acos(cosBeta);
    return vec3(cosBeta, beta, PI - beta);
}

// 水下物体彩色吸收与独立亮度补偿（地形 / 前向实体 / 简单半透明共用单真源）。
// lmSky 为 remapLightmap 后的物体天光级，不是眼位 eyeBrightnessSmooth；
// 与焦散 pow2 天光门互补：满天光无额外吸收，深水低天光更偏蓝青。
// 只调物体最终着色，不调雾色；composite_fog 的眼到物体距离吸收保留，二者分工。
// 依赖 constants（1 / WATER_FOG_COLOR / WATER_UW_SURFACE_ABSORPTION /
// WATER_UW_SURFACE_BRIGHTNESS），返回有效颜色倍率（含补偿，不是纯透射率）。
// 与 uniforms（isEyeInWater），均由 program 先行平铺 include。
vec3 underwaterSurfaceColorScale(float lmSky) {
    if (isEyeInWater == 1) {
        float skyLight = clamp(lmSky, 0.0, 1.0);
        float absorption = (1.0 - skyLight * skyLight) * WATER_UW_SURFACE_ABSORPTION;
        return exp(-(vec3(1.0) - WATER_FOG_COLOR) * absorption) * WATER_UW_SURFACE_BRIGHTNESS;
    }
    return vec3(1.0);
}

// 前向简单光照（光照图轻量着色）：前向半透明的「deferred 之后」路径消费——各项与
// shadeSurface 的环境 / 方块光项逐项同源（辐照度形式），无直射 / 阴影 / 法线（阳光下略暗于
// 受光地形，春v2 同取舍；夜视项不接——shadeSurface 亦无、避免与地形观感分叉，接的话两侧成对
// 加）。lm 为 remapLightmap 后的值；半球项取 1 = 向上表面档（粒子 / 雨雪无法线，最亮参考档与受光
// 地面衔接）。整体 × FORWARD_LIGHTMAP_BRIGHTNESS（constants.glsl，2026-10 按反馈「玻璃 / 雨雾
// 有些暗」接入——无直射项路径的观感提亮旋钮，覆盖本函数全部调用方：玻璃等非水分支 + 简单半透明
// 两档；forwardEntityShade 不受影响）
vec3 forwardLightmapShade(vec3 albedoLinear, vec2 lm, vec3 skyAmbient) {
    vec2 lmPow4 = lm * lm; // 两分量平方再平方、免 pow 调用
    lmPow4 *= lmPow4;
    vec3 irradiance = skyAmbient * lmPow4.y
                    + TORCHLIGHT_COLOR * (lmPow4.x * TORCHLIGHT_NEAR_SCALE + lm.x * TORCHLIGHT_FLOOR_SCALE)
                    + MIN_AMBIENT;
    return (albedoLinear / PI) * irradiance * FORWARD_LIGHTMAP_BRIGHTNESS
         * underwaterSurfaceColorScale(lm.y);
}


// shadowtex1 单 tap 硬判定可见性（最简档，2026-10 自两处复制收敛为单真源）：水面直射门控
//（lib/water/surface.glsl 的 shadeWaterSurface）与实体前向直射（下方 forwardEntityShade）共用的
// 读取端——「同款最简档」由单真源结构性保证。shadowOrigin 为相对世界系采样起点（**已含调用方的
// normal offset**——两消费方的 offset 形式各异：水面按世界 up 固定小偏移、实体按坡度缩放，语义
// 差异留在调用方）；tex1 只含不透明几何（水面 / 玻璃等半透明遮挡不细究、按全亮放行），出屏 /
// 超距门控同样在调用方（本函数只管「shadow 屏幕坐标 → 精确纹素 step 比较」，出屏按全亮——贴图
// 覆盖外无内容）。不复用 sampleShadowVisibility（6~12 tap PCF + 彩色阴影 + SS trace 对前向逐像素
// 过重；软影 / 彩影为升级点，include shadow.glsl 换调用即得）。硬边无软化、交 TAA 时间累积
float shadowTex1HardVisibility(vec3 shadowOrigin) {
    float distortFactor;
    vec3 shadowPos = relativeWorldToShadowScreen(shadowOrigin, distortFactor);
    if (any(notEqual(clamp(shadowPos.xy, 0.0, 1.0), shadowPos.xy))) return 1.0; // 出屏：贴图外无内容
    ivec2 texel = clamp(ivec2(shadowPos.xy * float(shadowMapResolution)),
                        ivec2(0), ivec2(shadowMapResolution - 1));
    return step(shadowPos.z - SHADOW_BIAS_DEPTH, texelFetch(shadowtex1, texel, 0).r);
}

// 前向简单光照（直射 + 天光档，2026-10 接入）：实体「deferred 之后」分支（gbuffers_opaque_entities）
// 专供——粒子 / 雨雪等无法线几何不适用（仍走 forwardLightmapShade 的半球 = 1 最亮档）。三项与
// shadeSurface 逐项同源（辐照度形式，实体无 SSS 标记〔半透明混合类纪律〕恒 max(ndl, 0)）：
//   直射 = directIrradiance × directTransmittance × NdotL × 阴影可见性（帧数据由接入方 vsh 输出，
//         与通用全屏 vsh 同名同式——Iris 拆分实体绘制时「前 deferred 实体（延迟光照）」与
//         「后 deferred 实体（本函数）」同屏，日落红化 / 量级一致才不穿帮）
//   天光 = skyAmbient × lm.y⁴ × 半球近似（shadeSurface 同式）；方块光 / 地板与 forwardLightmapShade 同式
// 阴影可见性 = **shadowtex1 单 tap 最简硬判定**（水面直射门控同款，lib/water/surface.glsl——
// 不复用 sampleShadowVisibility：6~12 tap PCF + 彩色阴影三分支 + SS trace 对前向逐像素过重；
// 软影 / 彩色阴影是升级点，include shadow.glsl 换调用即得）。tex1 只含不透明几何：半透明实体
// 多不在其中（水同款），在其中的实体由 normal offset（sampleShadowVisibility 同式斜率缩放）+
// SHADOW_BIAS_DEPTH 防自阴影痤疮；玻璃等透射遮挡不细究（按全亮放行）；超 shadowDistance / 出屏
// 按全亮。硬边无软化、交 TAA 时间累积。lm 为 remapLightmap 后的值；normalView 观察空间法线
//（gbufferViewNormal 出口——导数法线或 labPBR 贴图法线，未过 gbuffer 编解码往返故入口就地归一）
vec3 forwardEntityShade(vec3 albedoLinear, vec3 normalView, vec2 lm, vec3 viewPos,
                        vec3 lightDirWorld, vec3 directIrradiance, vec3 directTransmittance,
                        vec3 skyAmbient) {
    vec3 normalWorld = normalize(viewToWorldDirection(normalView)); // mat3 纯旋转，但入口未保证单位长

    vec3 relativeWorldPos = viewToRelativeWorld(viewPos);
    // 与延迟地形 / 水面一致：实际眼点距离，不是玩家相对原点距离。
    float distWorld = length(viewPos);

    // 直射可见性（单 tap；背光面 ndl ≤ 0 直射本就为 0、免 fetch）：normal offset 取
    // sampleShadowVisibility 同式斜率缩放（距离 + 背光坡度放大），起点构造后交单 tap 读取端
    float ndl = dot(normalWorld, lightDirWorld);
    float sunVis = 1.0;
    if (ndl > 0.0 && distWorld <= shadowDistance) {
        vec3 shadowOrigin = relativeWorldPos
                          + normalWorld * (SHADOW_BIAS_NORMAL * (1.0 + distWorld * 0.01)
                                           * (2.0 - clamp(ndl, 0.0, 1.0)));
        sunVis = shadowTex1HardVisibility(shadowOrigin);
    }
    // 无阴影贴图但保留直射（DIM_NO_SHADOW 单独成立时）：sunVis 恒 1——现无维度落在该组合
    //（下界 / 末地直射已被 DIM_NO_DIRECT_LIGHT 整段剔除，见下方 #else）

    // 天光门（shadeSurface 同窗同式含 pow4 整形，constants.glsl 直射天光门分区）：实体在洞穴 /
    // 深室内与地形同门不吃直射，Iris 拆分绘制时前后 deferred 实体行为一致
    float skyGate = smoothstep(DIRECT_SKYLIGHT_GATE_LOW, DIRECT_SKYLIGHT_GATE_HIGH, lm.y);
    skyGate *= skyGate;
    skyGate *= skyGate;
    vec3 directTerm = directIrradiance * directTransmittance * skyGate * (max(ndl, 0.0) * sunVis);





    vec2 lmPow4 = lm * lm;
    lmPow4 *= lmPow4;
    float hemisphere = 0.6 + 0.4 * clamp(normalWorld.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 irradiance = directTerm
                    + skyAmbient * (lmPow4.y * hemisphere)
                    + TORCHLIGHT_COLOR * (lmPow4.x * TORCHLIGHT_NEAR_SCALE + lm.x * TORCHLIGHT_FLOOR_SCALE)
                    + MIN_AMBIENT;
    return (albedoLinear / PI) * irradiance * underwaterSurfaceColorScale(lm.y);
}


// 2D 平面云——单层解析云，方案移植自春v2 的 clouds2D（2D 云原作者 Coldnight冷夜，见春v2
// clouds2D.glsl 头注；KN 相位函数原作者 Jessie / Luna）。本包适配点（各注释内详述）：
//   ① 光照经通用全屏 vsh 帧数据 varying 供光（春v2 的 sunColor / skyColor / isNight 减半不移植
//     ——昼夜切换黑过渡、雨天直射 ×0.25、环境去饱和由 varying 自动跟进）；
//   ② 云壳半径接本包 EARTH_RADIUS（与大气曲率一致）；直射透射率用 vCloudTransmittance
//     （云层海拔处求值，日落时云比地面晚变红）；
//   ③ 角坐标世界锚定（+ cameraPosition.xz，春v2 原版无此项——其云随相机水平平移，有体素云
//     底层兜底运动感；本包无底层，飞行会暴露该行为）；
//   ④ 雨天抬 coverage 成阴天 + 密度衰减（春v2 原版只减密度、阴天感由其体素云层承担）。
// 首版自研方案（弦长 Beer + 伪自阴影 + 银边 pow）实机观感不佳、按反馈整体替换，调研与
// 设计存档见 plans/平面云方案.md
//
// 性能（本包三次优化，相对春v2 原版）：KN 相位的 e 牛顿迭代常量折叠（g 与 e / ln(2e+1) 在
//   constants.glsl 成对维护，免每云像素 9 次超越函数）；hash 族换无 sin 浮点 hash（noise.glsl，
//   图案更换统计等价、待实机 A/B）；
//   warp 场 worley → simplex（9 hash → 3，开关宏 1、A/B 回退点）；
//   伪自阴影探针场化——cloudFieldShape / sampleCloudField（colortex1 云形状场槽位，deferred 槽
//   每帧生成 128²×9 hash、deferred1 同帧消费；云像素探针 9 hash 内联求值 → 2 次 bilinear fetch；
//   场 2 octave 为 4 km texel 的 Nyquist 上限，调制趋平滑由 SHADOW_GAIN 补偿）。
//   云像素噪声路径：~126 次 sin + 9 次 log（春v2 原版）→ 36 hash（二次优化后）→ 21 hash + 2 场
//   fetch（warp simplex 化 −6、探针场化 −9）；晴天空像素 27 → 21 hash
//
// 结构：云壳求交（云下仰视穿出 / 云上俯视云顶 / 行星遮挡统一处理）→ 角坐标（交点 xz ÷ 云壳
// 半径——数值域有界使 hash 输入坐标有界；远交点在角域自然压缩 = Kappa 距离压缩的解析等价，
// 地平线不闪）→ warp 微扰 + 6 octave simplex fbm（各 octave 差速演变）→ coverage 重映射 /
//   smoothstep 二次锐化 → 不透明度 = 密度（云存在度遮挡）→ KN 前向散射相位照明。合成契约 =
//   标准 alpha：最终色 mix(天空, 云色, 不透明度)——云色暗（如晨昏交接带直射黑过渡中）时呈
//   暗剪影而非透明（2026-10 修复；曾为「预乘散射 + 透射率」且不透明度随 exp 距离衰减溶进地平线，
//   两效应叠加使交接带云只剩轻微调暗背景的透明纱、观感「没有云」，git 历史含完整形态）。两个
//   消费方：deferred_init 天空分支（TAA 之前）逐像素直接求值、mix 合成；
//   composite12 云层天空盒烘焙（getPlanarCloudsWorld，2026-10）逐 texel 全量重算写 colortex7
//   八面体槽位 [0,256)²、water 反射未命中 SSR 侧经 sky.glsl 的 sampleCloudSkybox 单 fetch 消费
//   ——「反射不重算云」的烘焙路线，主天空不降档。
//
// 依赖由接入的 program 先行 include（lib 文件不嵌套）：constants.glsl（CLOUDS_2D_* /
//   EARTH_RADIUS）、uniforms.glsl（cameraPosition / frameTimeCounter / rainStrength / colortex1——
//   云形状场采样）、lib/post/bloom.glsl（cloudFieldRect 场槽位矩形）、utils/noise.glsl
//   （rand2 / simplex2d；原视图壳的 utils/space.glsl 依赖已随其删除移除，2026-10）。
//   仅片段阶段（与 deferred_init / deferred_cloud_field 调用点约定一致）

// 1 外层守卫（2026-10 维度极简档）：CLOUDS_2D_* 常量族在 constants.glsl 的同宏分区内，
// 宏关时（下界 / 末地经 DIM_NO_ATMOSPHERE 不定义）本文件须整体编译为空——deferred_init 等
// 接入方仍平铺 include 本文件（调用点各自的 #ifdef 1 门控不变），与 fog.glsl /
// aerial.glsl 的同款自守卫纪律对齐


// 射线-球求交（球心 = 原点，即行星中心系），返回 (近根, 远根)、无交时近根 < 0
vec2 cloudRaySphere(vec3 origin, vec3 dir, float radius) {
    float b = dot(origin, dir);
    float c = dot(origin, origin) - radius * radius;
    float disc = b * b - c;
    if (disc < 0.0) return vec2(-1.0);
    float sq = sqrt(disc);
    return vec2(-b - sq, -b + sq);
}

// worley 单层（3x3 邻域最近特征点距离，春v2 cloud2DWorley 同款）——warp 的回退档
//（1 关闭时使用）。平方距离比较、循环外单次 sqrt：min 与单调函数可交换、
// 胜者同格、结果等价（省 8 次 sqrt / 天空像素，低配 GPU sqrt 非全速率）
float cloudWorley(vec2 p) {
    vec2 cell = floor(p);
    vec2 localPos = fract(p);
    float minDistSq = 2.0; // 初值 > 3×3 邻域最近距离上界 (√2)² 即可，结果由 clamp 收口
    for (int j = -1; j <= 1; j++) {
        for (int k = -1; k <= 1; k++) {
            vec2 offset = vec2(k, j);
            vec2 v = offset + rand2(cell + offset) - localPos;
            minDistSq = min(minDistSq, dot(v, v));
        }
    }
    return clamp(sqrt(minDistSq), 0.0, 1.0);
}

// fbm 前的微扰 warp（打碎 simplex 的均匀团块感），主采样与云形状场生成端共用同一实现——位移场
// 在两端的逐点值严格一致（确定性函数 + 同帧常量）。默认 simplex（3 hash）替春v2 的 worley
//（9 hash）：warp 职责只是平滑位移场、任何低频噪声都胜任；位移场从胞状距离变梯度场，云的破碎
// 纹理风格会变（统计等价，A/B 回退点——删 constants.glsl 的 1 即回 worley）
vec2 cloudWarp(vec2 p) {
    float warp = simplex2d(p * CLOUDS_2D_SCALE) * 0.5 + 0.5;

    return p - (1.0 - warp) * 0.001;
}

// simplex fbm 核心（lacunarity 2.5 / gain 0.5，春v2 sampleCloud2D 同款）；time 各 octave ×1.1
// 差速——低频层平移快、高频层慢，云形在漂移之外持续自演变。入参须为 warp 微扰后的坐标（cloudWarp
// 在调用方施加）。octave 数参数化：主采样 6 档与云形状场生成端（CLOUDS_2D_FIELD_OCTAVES）共用
// 同一 frequency / weight / time 序列——「两端严格一致」由单真源结构性保证（曾两处复制成对维护、
// 注释明令「改动须两处联动」，2026-10 收敛）
float cloudSimplexFbmN(vec2 warpedP, int octaves) {
    float frequency = CLOUDS_2D_SCALE;
    float weight = 1.0;
    float time = CLOUDS_2D_SPEED * frameTimeCounter;

    float noise = 0.0;
    float totalWeight = 0.0;
    for (int i = 0; i < octaves; i++) {
        noise += (simplex2d(warpedP * frequency + time) * 0.5 + 0.5) * weight;
        totalWeight += weight;

        frequency *= 2.5;
        weight *= 0.5;
        time *= 1.1;
    }
    return noise / totalWeight;
}

// 主采样 fbm（6 octave 全频形状）
float cloudSimplexFbm(vec2 warpedP) {
    return cloudSimplexFbmN(warpedP, 6);
}

// 噪声 → [0,1] 形状：coverage 重映射 + smoothstep 二次锐化（春v2 同款链路）。密度乘子
// （DENSITY / 雨天衰减）由调用方施加——主采样与伪自阴影差分共用本映射，逐帧一致的乘子在差中
// 相消
float cloudShape(float noise) {
    float coverage = mix(0.55, CLOUDS_2D_COVERAGE_RAIN, rainStrength);
    float shape = clamp((noise - (1.0 - coverage)) / coverage, 0.0, 1.0);
    return smoothstep(0.0, 1.0, shape);
}

// 云形状场求值（生成端，deferred 槽的 deferred_cloud_field 逐 texel 调用）：世界锚定的低频云
// 形状（warp + 前 CLOUDS_2D_FIELD_OCTAVES 个 octave 的 fbm + cloudShape），入参为角域坐标
// p（= 世界 xz ÷ 云壳半径）。fbm 序列与主采样共用 cloudSimplexFbmN 单真源（同上注）；与主采样
// 全频形状共享同一低频场——场与主形状的空间相关性由此保证。返回 [0,1]
float cloudFieldShape(vec2 p) {
    return cloudShape(cloudSimplexFbmN(cloudWarp(p), CLOUDS_2D_FIELD_OCTAVES));
}

// 云形状场采样（消费端，deferred_init 探针 / 未来云影）：世界 xz → colortex1 场槽位 bilinear
//（矩形由 bloom.glsl 的 cloudFieldRect 与生成端共用——texel i 中心 ↔ local = (i + 0.5) / RES
// 严格互逆）。场由 deferred 槽（program/deferred_cloud_field）每帧生成、deferred1（本 pass）同帧
// 消费、零滞后；窗口跟相机（场内容为绝对世界坐标的确定函数，锚点只决定覆盖范围），生成与消费
// 同帧同 cameraPosition——无错位。采样点恒在窗口内：可见云域 ≤ fade 早退界 ~221 km < 半窗口
// 256 km，bilinear 不会读到槽位边缘外
float sampleCloudField(vec2 worldXz) {
    vec4 rect = cloudFieldRect();
    vec2 fieldSize = vec2(textureSize(colortex1, 0));
    vec2 local = (worldXz - cameraPosition.xz) / CLOUDS_2D_FIELD_WORLD + 0.5;
    vec2 fieldUv = (rect.xy + local * rect.zw) / fieldSize;
    return texture(colortex1, fieldUv).r;
}

// Klein-Nishina 前向散射相位 ×4π 并钳 [0,1]（春v2 phasefunc_KleinNishina 同式）。原版以 8 次
// 牛顿迭代逐像素自 g 反解 e——g 为编译期常量、e 与 ln(2e+1) 随之恒定，故离线解出常量折叠
//（g = 0.25 → e ≈ 1.879、ln(2e+1) ≈ 1.560，与 g 在 constants.glsl 成对维护；折叠后 ×4π / 2π
// 相消，一次 rcp + FMA）。前向峰 = 太阳方向薄云处的银边
float cloudPhase(float cosTheta) {
    return clamp(2.0 * CLOUDS_2D_PHASE_E /
                 ((CLOUDS_2D_PHASE_E * (1.0 - cosTheta) + 1.0) * CLOUDS_2D_PHASE_LOGTERM),
                 0.0, 1.0);
}

// 世界系核心（dirWorld 须已归一化）——两个消费方（composite12 的云层天空盒烘焙：八面体纹素
// 反解方向；deferred_init 天空分支：与 LUT / 日月盘 / 星盘共享一次归一的世界方向，2026-10 天空
// 分支世界方向单次化）直入，免「世界→视图→世界」往返（getSkyColor / getSkyColorWorld 拆分同款
// 纪律；原视图壳 getPlanarClouds 随最后一消费方转世界系直入而删，git 历史含完整形态）。帧数据
//（主光源世界方向 / 直射辐照度 / 云高处透射率 / 天空环境基色）由调用方从 vsh 帧数据 varying
// 传入；返回：rgb = 云自身颜色（未预乘 = lighting × 1.0 × CLOUDS_2D_BRIGHTNESS_BASE）、a = 不透明度
//（云存在度 = 密度直乘 × 远界融边，2026-10 起不含中低仰角距离衰减）——消费端一律标准 alpha
// 合成：最终 color = mix(skyColor, cloud.rgb, cloud.a)
vec4 getPlanarCloudsWorld(vec3 dirWorld, vec3 lightDirWorld, vec3 directIrradiance,
                          vec3 cloudTransmittance, vec3 skyAmbient) {
    vec3 dir = dirWorld;
    vec3 origin = vec3(0.0, EARTH_RADIUS + cameraPosition.y, 0.0); // 行星中心系相机位置（球心 = 原点）
    float cloudRadius = EARTH_RADIUS + CLOUDS_2D_HEIGHT;

    // 行星遮挡（春v2 同款双守卫）：云下相机前向命中地面 → 无云（掠地平线下沿的数学交点在
    // 地球背面）；一般情形地面命中点先于云交点同样无云（云上俯视时地面恒在云后、不触发）
    vec2 earthHit = cloudRaySphere(origin, dir, EARTH_RADIUS);
    if (origin.y < cloudRadius && earthHit.x > 0.0) return vec4(0.0, 0.0, 0.0, 0.0);

    // 云壳求交：云下取远根（相机在云壳球内、仰视穿出云底）、云上取近根（俯视云顶）——统一处理
    vec2 cloudHit = cloudRaySphere(origin, dir, cloudRadius);
    float lenToCloud = origin.y < cloudRadius ? cloudHit.y : cloudHit.x;
    if (lenToCloud < 0.0 || (earthHit.x > 0.0 && earthHit.x < lenToCloud))
        return vec4(0.0, 0.0, 0.0, 0.0);

    // 角坐标：交点 xz ÷ 云壳半径（世界锚定）。有界数值域使 hash 输入坐标有界；同一除法让
    // 远交点在角域自然压缩——地平线方向噪声频率自动降低、不闪（Kappa 显式距离压缩的解析等价）
    vec2 worldXz = cameraPosition.xz + dir.xz * lenToCloud;
    vec2 p = worldXz / cloudRadius;

    // 形状密度：warp 微扰 + fbm + coverage 重映射 / 锐化（cloudShape）；雨天密度衰减在乘子处施加
    float shape = cloudShape(cloudSimplexFbm(cloudWarp(p)));
    float density = shape * CLOUDS_2D_DENSITY * (1.0 - CLOUDS_2D_RAIN_FADE * rainStrength);
    if (density < 1e-5) return vec4(0.0, 0.0, 0.0, 0.0);

    // 不透明度 = 密度（云存在度，2026-10 起不含 exp 距离衰减——旧「密度 × 距离衰减」令中低仰角
    // 云随距离变薄、地平线带溶成透明天；配合旧预乘合成在晨昏交接带〔直射黑过渡、云色近黑〕只剩
    // 轻微调暗背景的透明纱 = 「云不可见」实测根因。标准 alpha 合成下云色即所见表色）
    float opacity = clamp(density, 0.0, 1.0);
    // 远界融边（对应仰角 ≲ 2° 的地平线带、边界雾满档接管）：保 colortex1 云形状场半窗口不变式
    //——伪自阴影探针域 ≤ 融边终点 + LIGHT_DRIFT（244 km）< 半窗口 256 km，bilinear 边缘永不
    // 触达（旧不变式锚在 exp 距离衰减的 ~221 km 早退界上、随衰减移除后改锚此处，见 constants.glsl）
    opacity *= 1.0 - smoothstep(CLOUDS_2D_FAR_MELT_END - 32000.0, CLOUDS_2D_FAR_MELT_END, lenToCloud);

    // 伪自阴影（本包扩展，SEUS 同思路、零 raymarch）：同一低频场朝光源水平方向偏移 LIGHT_DRIFT
    // 米重采样求差——此处比太阳侧邻域稠密 = 朝阳边缘，更亮；反之处于邻域的阴影里，更暗。两端都
    // 从 colortex1 云形状场 bilinear 采样（差分同场天然无偏，替代原先逐像素 9 hash 内联降配求值
    // ——场由 deferred 槽每帧以 128²×9 hash 生成、本 pass 同帧消费，见 cloudFieldShape）；无云
    // 像素已在上行早退、不付场采样
    vec2 lightOffsetWorld = lightDirWorld.xz * CLOUDS_2D_LIGHT_DRIFT;
    float sunlit = clamp(0.5 + (sampleCloudField(worldXz)
                              - sampleCloudField(worldXz + lightOffsetWorld))
                              * CLOUDS_2D_SHADOW_GAIN,
                         0.0, 1.0);
    float shadowMod = 1.0 + (sunlit - 0.5) * 2.0 * CLOUDS_2D_SHADOW_STRENGTH;

    // 光照：直射（辐照度 × 云高处透射率 × KN 前向相位——太阳侧薄云银边 × 伪自阴影明暗）与
    // 天空环境按 SKY_MIX 混合（环境光各向同性、不吃阴影调制）；昼夜 / 雨天的幅度与色变全部
    // 由帧数据 varying 带来
    float phase = cloudPhase(dot(dir, lightDirWorld));
    vec3 lighting = mix(directIrradiance * cloudTransmittance * phase * shadowMod,
                        skyAmbient, CLOUDS_2D_SKY_MIX);
    vec3 cloudColor = lighting * (1.0 * CLOUDS_2D_BRIGHTNESS_BASE);
    return vec4(cloudColor, opacity);
}




in vec2 vTexCoord;














// ================================ FRAGMENT ================================



layout(location = 0) out vec4 outColor;

void main() {
    ivec2 pixel = ivec2(gl_FragCoord.xy);
    // 本 pass 只更新 2，其余 tile 与间隔都是同位置透传；无需逐像素遍历全部 tile。
    // 保留原矩形函数与含边界判定，奇数分辨率 / 4 texel gutter 的布局语义不变。
    vec4 targetRect = bloomTileRect(2);
    bool inTargetTile = all(greaterThanEqual(vTexCoord, targetRect.xy))
                     && all(lessThanEqual(vTexCoord, targetRect.xy + targetRect.zw));
    if (inTargetTile) {
        vec2 tileLocal = (vTexCoord - targetRect.xy) / targetRect.zw;
        outColor = vec4(bloomUpsampleTile(2, tileLocal, pixel), 1.0);
    }






































































    // 非目标 tile 的像素（其他级与间隔）复制回写：保持 main/alt 翻转下的完整图集；
    // colortex7 包围盒整写不可 discard，两路输出互不干涉
    if (!inTargetTile) outColor = texelFetch(colortex1, pixel, 0);
}


// ================================= VERTEX =================================











































/* DRAWBUFFERS:1 */
