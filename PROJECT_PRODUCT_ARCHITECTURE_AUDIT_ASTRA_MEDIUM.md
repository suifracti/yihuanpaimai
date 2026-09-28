# Executive Product Verdict

项目处于“已有可复用的 Python 拍卖助手、已有 Native 安全与帧传输组件，但尚未把可信实时画面、同局事实和现有 HUD 接成一局可持续使用的产品”的阶段；当前最大缺口是产品接线与生命周期语义，同时仍存在真实采集和识别完整性的能力缺口。

审计日期：2026-09-22。角色：第三位独立产品／架构审计者。本文是候选路径与裁决材料，不是 Master Plan，不沿用既定 Phase 的优先级。

仓库只读快照：`D:/yihuanpaimai`，分支 `codex/consolidate-workspace`，HEAD `cb86697c976a0658f5e301f5e199b269f26a14e6`，工作区 dirty。当前能力判断包含未提交源码，不能把 HEAD 单独当作这些能力的完整版本。未 reset、clean、stash、merge、rebase、构建、测试或操作游戏；除本报告外未写入文件。未读取另外两位模型的报告，也未读取仓库 `PROJECT_STATE_FOR_ASTRA.md`。定位主源时曾返回历史同名文件路径，但未打开 Raw／Archive 内容，后续读取均限定精确路径。

证据分层：以下“源码确认”表示调用关系或实现存在；“既有运行记录”只支持记录所述场景；“判断／建议”是独立产品分析。没有把本轮静态阅读写成 live PASS。

本报告采用的定位索引（仓库路径均相对本报告）：

| 索引 | 来源与用途 |
|---|---|
| D1 | [Obsidian 根规则](D:/ObsidianLiveSyncTestVault/AGENTS.md)、[通用规则](D:/ObsidianLiveSyncTestVault/99-系统与后台/AI/所有项目通用工作规则.md)、仓库 AGENTS.md：只读边界、最小充分验证、唯一仓库 |
| D2 | [README](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/README.md)、[Handoff](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Handoff.md)、[Decisions](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Decisions.md)：产品目标和历史通过范围 |
| D3 | [Feature Truth Matrix](<D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Feature Truth Matrix.md>)、[Feature Correctness Audit](<D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Feature Correctness Audit.md>)、[Architecture V2 Spike](<D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Architecture V2 Spike.md>)：指定历史主源；不继承其中路线裁决 |
| S1 | `app/main.py:1530,2887,3497,3690,3921,4420,4524,4577`，`app/vision_worker_loop.py`：当前产品、识别子进程、事实同步、HUD 与启动 |
| S2 | `core/game_frame_capture.py`、`core/window_capture.py:158`、`core/window_tracker.py`、`core/roi_scaler.py`：Python 客户区采集和 ROI |
| S3 | `core/current_match.py`、`core/live_match_transport.py`、`core/live_match_control.py`、`core/live_shadow.py`、`core/auto_archiver.py`：事实、控制、估值和历史边界 |
| S4 | `architecture/v2/host/wgc_live_harness/Program.cs:113`、`WgcCapture.cs:61,100`：真实 WGC 入口及固定 geometry |
| S5 | `architecture/v2/host/engine_v22/nte_engine_v22.py:341,377,451,646,768,798,811,898`：真实视觉适配器、投影、恢复、队列及 ACK |
| S6 | `architecture/v2/host/NteHost/Program.cs`、`SupervisorSession.cs:849`、`MmfFrameRingWriter.cs`：场景驱动 Host 与 MMF 传输 |
| S7 | `architecture/v2/integration/NteHost.Integration/IntegrationCoordinator.cs`、`WindowMonitorObservationSource.cs`、`host/NteHost.WindowMonitor/WindowMonitor.cs:860`：窗口、安全、冻结的 Native 组合 |
| S8 | `app/warehouse_capture_host.py:2058`、`core/warehouse_capture_session.py:95,131`、`core/warehouse_capture_production.py`、`core/warehouse_wheel_driver.py:200`、`app/main.py:252`：现有 Python 滚仓执行路径 |
| E1 | `build/goal-luna/native-bridge/real-window/integration-live.json`：真实目标观察＋fake 输入的既有运行记录 |
| E2 | `build/goal-luna/native-bridge/real-window-v2-3/wgc-mmf-result.json`：WGC 固定尺寸失败的既有运行记录 |
| E3 | `build/goal-luna/frames/candidate-final/host-result.json`：回放 fixture 经 MMF 到真实视觉 Engine 的既有运行记录；不是本轮执行 |

# What The Product Actually Is

最终产品是一套跟随真实《异环》拍卖生命周期的决策助手。用户不应为了使用它成为日志操作员、逐件录入员或 AI 消息转发员。

| 用户过程 | 最终应承担的责任 |
|---|---|
| 启动／选择窗口 | 识别真实游戏及窗口生命周期，说明未找到、暂停、恢复、画面失效；不误把其他窗口当游戏 |
| 大厅／加载／开局 | 识别场景和进入方向，建立当前局；回大世界标为中断；下一局重新建立事实边界 |
| 正在竞拍 | 同局记录左侧四席与各回合可见出价、中间全部可见情报、右侧已显露藏品信息；未知与确认分开 |
| 仓库观察 | 自动覆盖滚动区域，保存原图、跨页配准、物理去重；品质格、完整尺寸、身份是不同事实 |
| 估值与建议 | 将可信事实交给保留的 v0.6 六品质求解逻辑，明确正式／部分支持／仅记录；不凭缺失信息硬给报价 |
| 必要输入 | 为采集服务的受限滚动／详情点击；失焦、用户接管、旧凭据、过期场景一律禁止；不自动出价 |
| 结算 | 优先保全原图，70 秒后或更早游戏截止停止新增主动采集，余下离线处理；金额、赢家、归属各自有证据 |
| 历史／下一局 | DRAFT 与 FINALIZED 分开，历史可追溯、可复核；赛后信息不改写事前预测；下一局不继承上局事实 |
| UI／HUD | 同一事实权威的两个投影，优先显示当局决策、信息新鲜度和缺口；支持少量人工纠正而非逐件补录 |

这是长期目标，不代表首版必须一次实现所有自动化。D2 已允许先完成可用隔离试用，再优化逐件匹配；缩小首版承诺不会自动关闭完整识别等未完成边界。

# Current User-Visible Product

当前日常源码入口仍是 `app/run.bat → app/main.py`。产品外壳已有 Main/HUD、手动字段、截图、结算复核、历史、独立 Node 求解进程和识别子进程，并非只有技术 demo。Python 外壳内已使用 WebView2／pythonnet 相关路径，“尚未 V2-4”不能解释为“没有可用 UI”。[S1–S3]

主要现有链路为：

`Python 客户区 capture → run_vision_capture_loop → NTEVisionPipeline → LiveMatchSession / LiveMatchControl → sync_vision_to_current_match → HUD payload + versioned visionState → WebSocket receiver → Main/HUD / solver`。

结算另走 `AutoArchiver → CanonicalHistoryStore`，不是只存 OCR JSON。主窗口与 worker 虽各持对象，但已存在版本化快照与手动控制回执；不能把任何多对象存在都简单判为两套无约束真值。[S1,S3]

D3 记录了限定素材下的字段保护、单局连续性、结算归档、隔离试用等通过范围。对 `app/main.py`、`app/vision_worker_loop.py`、`core/current_match.py`、`core/live_match_transport.py`、`core/live_shadow.py`、`core/vision_pipeline.py` 与 `763fb57` 的定向 Git 比较未见差异，因而这些未改路径可继续引用旧范围；这不是对当前包装和真实对局的新验收。

尚不能宣称用户每天开游戏即可可靠使用：真实连续识别、及时显示、未见对局泛化、完整滚仓／去重、真实归属闭环没有同等证据；当前发布包是否包含源码能力也未核实。仓库 README 仍含早期“P4/P5 未开始”等断点，应视为陈旧摘要，不以其重新冻结产品路线。

# Current Native/V2 Stack

Native 栈有三个不同的“可达”，必须分开：

1. 窗口与安全：WindowMonitor、InputSafetyGuard、FreezeCoordinator、IntegrationCoordinator 已有组件和组合；E1 证明真实游戏前台→失焦→返回时 fake 动作门禁，`realInputExecuted=false`。它没有证明现有产品所有输入已由 Native 仲裁。
2. 回放帧与真实业务 Engine：E3 的 fixture 经 Host/MMF 到 `engine_v22`，真实 OCR 预加载并返回 `SETTLEMENT`；单帧 `processingMs=4030.5165`，出价为空。该记录证明传输和真实视觉调用，不证明实时出价或一局完整性，也不是 P95。
3. 真实 WGC：S4 有 WGC→D3D11 readback→MMF 代码，但硬编码启动 `engine_frame_probe.py`。E2 因 `1922x1112` 超过固定 `1920x1080` 能力而停止；没有有效 WGC 帧进入该次传输。Handoff 的后续缩窗只是环境调整，不能代替捕获成功。

`NteHost/Program.cs` 仍是 scenario 驱动程序。`SupervisorSession.SendFrame` 顺序等待 ACK 和 perception；WGC harness 再进入下一次 capture。它还不是采集、控制与业务持续独立运行的产品宿主。[S4–S6]

| V2 工作 | 独立分类 | 原因 |
|---|---|---|
| V2-0 必需的 framing、session、ownership、版本验证 | MVP_HARD_DEPENDENCY（选择 Native bridge 时） | 跨进程不能省；不要求扩大为通用平台协议 |
| V2-0 超前 capability 扩展、未消费消息体系 | ARCHITECTURE_ONLY | 没有当前用户路径消费的设计不带来首版价值 |
| V2-1 Engine 存活检查、失效关闭、资源回收 | MVP_HARD_DEPENDENCY（Native bridge） | 崩溃不能继续显示旧结果为当前结果 |
| V2-1 无感业务恢复、完整重启矩阵 | MVP_HELPFUL | 首版可明确暂停并重新确认当前局；禁止盲目恢复 |
| V2-2 窗口身份／生命周期 | MVP_HARD_DEPENDENCY | 必须知道帧属于哪个目标；实现语言不是硬依赖 |
| V2-2 B/C 输入与冻结完整接线 | MVP_HELPFUL（纯观察首版）；启用输入即 MVP_HARD_DEPENDENCY | 无输入可先使用；有输入绝不能旁路门禁 |
| V2-3 可信目标帧、客户区 geometry、新鲜度 | MVP_HARD_DEPENDENCY | 拍卖事实必须来自正确实时画面；WGC 这项技术本身可替代 |
| V2-3 高 FPS、更多格式／任意分辨率、极限零拷贝 | POST_MVP | 先支持明确窗口配置，按实际瓶颈优化 |
| V2-4 Native WebView2／Overlay 宿主迁移 | MVP_HELPFUL | 已有 HUD；只有旧外壳存在无法局部处理的实用阻塞才提升优先级 |
| V2-5 真正产品端到端闭环 | MVP_HARD_DEPENDENCY | 应提前作为纵向目标，不等待迁移完成 |
| V2-5 全面删除 Python 胶水、目录与语言纯化 | ARCHITECTURE_ONLY | 与首版是否能打一局没有必然关系 |

# Are There Two Disconnected Stacks?

**PARTIAL。两条栈共用部分 Python 业务模块，但运行入口、状态编排和 UI 消费尚未接通。**

旧产品栈已有用户操作、事实治理、生命周期、归档与求解；新 Native 栈已有 OS 权威、进程协议、帧环和实验 Engine。对 app/core 的定向检索未找到 Native Host、MMF 或 PERCEPTION_RESULT 的消费路径，实际捕获仍是 WindowCaptureManager。[S1,S2,S4–S7]

重复职责包括窗口发现、采集、worker 生命周期、CurrentMatch 构建、事实投影和历史持久化。最危险的重复不是代码数量，而是 bridge 后可能同时启动两个识别 owner、两个历史写入者或两条输入路径。

真正缺的 bridge 是：产品启动选择单一 worker → Native 目标／帧状态 → 有明确帧和对局身份的观察 → 复用既有业务归一化与会话控制 → 完整 CurrentMatch 投影 → 当前 Main/HUD、solver 与人工控制回执。仅把 `PERCEPTION_RESULT.bids` 转成 WebSocket 不能覆盖这条链。

建议优先接现有产品，但应先决定一个业务 owner。可以让 Native frame provider 供给现有 worker，也可以让 `engine_v22` 复用现有 worker 编排后取代它；不能二者同时生产事实。完全迁移外壳后再接不会自动解决字段、归属和跨局语义。[判断]

# Capability vs Wiring Gap

| Area | Capability exists | Wired into product | Main gap |
|---|---|---|---|
| 游戏窗口与焦点 | Python tracker；Native monitor＋真实目标 fake-input 记录 | Python 是；Native 否 | 接线：统一目标身份和生命周期来源 |
| 真实 capture | Python PrintWindow/client mss；WGC readback 源码 | Python 是；WGC 否 | 两者都有：WGC 有效帧未证、外框到客户区需处理 |
| MMF／ACK | writer、reader、slot token；fixture 运行记录 | 否 | 接线：进入持续产品 worker；保留所有权约束 |
| 帧 freshness | 有 timestamp、sequence 和有界 queue | 没有完整 WGC→HUD 证据 | 能力：原始帧年龄、积压淘汰、失效 UI 和接收门禁 |
| 场景／出价／情报 | 旧 pipeline 和 parser | 旧产品是；新 Engine 仅部分 | 接线：字段归一化；能力：未见对局及时性／正确性 |
| 右侧藏品／品质／身份 | 几何、品质、图鉴、候选与确认组件 | 旧产品部分；新投影不足 | 能力：泛化、逐件确认；接线：证据与状态投影 |
| 全仓滚动与跨页 | Python host、driver、ledger、配准等组件 | Python 执行入口存在，完整效果未证 | 两者都有；并非只有 Native 滚轮才能开始任何仓库观察 |
| 安全输入／freeze | Python guard；Native A/B/C 组合 | Python 路径存在；Native 未接 | 接线：所有执行汇入唯一仲裁；真实输入边界仍未验 |
| CurrentMatch／人工保护 | 已有业务 owner、版本与字段保护 | 旧产品是；新 Engine 是独立简化实例 | 接线：单一权威、manual revision、会话与回合转换 |
| 估值／建议 | 持久 Node＋v0.6 数学核心、准入 | 旧产品是；新 Engine 否 | 接线：可信实时事实进入既有 solver；缺数据不能硬算 |
| 结算／历史 | AutoArchiver、CanonicalHistoryStore、复核 | 旧产品是；新 Engine 仅隔离 DRAFT | 接线：正式生命周期与历史归属；能力：未完成赢家／全仓边界 |
| 下一局／恢复 | LiveMatchSession、LiveMatchControl | 旧产品是；新 Engine 未复用 | 接线：窗口 generation≠业务 match；拒绝晚到结果 |
| UI／HUD | 已有 Python 宿主和 HTML/JS UI | 旧产品是 | 接线：消费新 worker；非必须重新造 Native UI |
| 疑难详情点击恢复 | 旧主源明确未实现，本轮未见完成入口 | 否 | missing capability；首版可暂不自动执行 |

# First Usable Version Definition

**候选首版：在明确支持的一种窗口配置下，从现有入口启动、可连续陪用户打一局并进入下一局的“观察优先拍卖助手”。** 它自动整理当前四席出价和可见情报，在有充分事实时给出既有估值／建议，显示右侧可见物品的已知与未知，允许少量人工确认；不要求用户操作 harness 或逐件补录。

核心价值必须发生在竞拍过程中：用户能少看漏一次出价／情报、及时看到有依据的估值或知道为什么暂不能估值。只显示连接成功、帧计数、OCR 文本文件不合格。若实战绝大部分时间没有及时事实、没有可用建议，只剩等待提示，也不合格。

| 首版处理 | 明确边界 |
|---|---|
| 自动 | 窗口识别、持续画面、可见出价／情报更新、正确场景和同局合并、符合条件的求解、HUD 同步 |
| 半自动／确认 | 开局归属不明确时确认；少量关键字段修正；结算确认；恢复或下一局边界不确定时确认 |
| 暂时只显示 | 部分可见仓库、品质格、候选身份、覆盖缺口；必须与整仓完成分开 |
| 暂不自动输入 | 所有滚动／详情／点击／出价；用户正常游戏操作产生的新页面可被动观察 |
| 暂不正式历史 | 可用现有隔离根保存原图和 DRAFT；不进正式历史统计／训练，不另建第二种历史格式 |
| 暂缺允许 | 全仓自动覆盖、疑难详情恢复、自动归属正例、跨电脑导出验收、无 goldAvg 正式估价；缺失显式展示 |

“手动确认”不是要求每帧点击或每件录入。若某项在每局重复造成大量人工负担，就不能再作为首版可用性借口。完整仓库自动化与正常使用不逐件补录仍是后续产品承诺，D3 的未完成状态继续保留。

# Distance From Current State To First Usable

不是从零重写助手，也不是“再加一个 WGC 类”即可。至少有三道实质门槛：

1. **实时输入边界**：真实目标的客户区像素、正确时间与 target/capture generation 持续成立；当前 E2 连 first real WGC frame 都未证明。
2. **业务接线边界**：新帧必须进入旧产品完整语义。S5 直接遍历 FACT_KEYS，旧链却显式将 `round→roundNo`、`currentLeaderBid→leaderBid`、结算子字段等转换。S5 没有旧 LiveMatchSession 的退局换局编排，命令也主要是测试／snapshot，不能当现有人工控制的替代品。
3. **实用反馈边界**：同局可信事实到 HUD／solver 及时可见，结算退出后下一局不串。E3 的 4.03 秒结算帧不能证明出价显示时效；原有历史 OCR 高耗时也提示换 capture 不等于解决推理瓶颈。

未知的主要工作量在真实画面与识别泛化，而非协议代码行数。本轮没有足够依据估算几天完成或完成百分比。候选路径应让第一轮实际使用尽早暴露这部分未知。

# From First Frame To First Match

| 层次 | 当前依据／缺口 | First Usable 硬依赖 |
|---|---|---|
| 1. first real frame | Python 能力存在；WGC E2 失败，fixture 不算真实 WGC | 是，正确客户区且内容可识别 |
| 2. continuous frames | WGC harness 有有限循环，SendFrame 等结果后才继续 | 是，持续有新观察，不能以有循环等同连续服务 |
| 3. frame freshness | WGC timestamp 在 readback 后取 NowNs；Engine 用处理时 UTC 当 captured_at；未见年龄淘汰 | 是，不能把旧池帧／排队帧包装为刚发生 |
| 4. scene state | 旧 pipeline 有场景判断与路由 | 是，未知／加载不能沿用当前出价为有效 |
| 5. bids/intel/items | 旧能力较多；新输出只是部分字段，重身份关闭 | 出价／关键情报是；物品允许已知部分＋缺口 |
| 6. projection into HUD | 当前 HUD 不消费新协议 | 是，用户必须在正常界面获得价值 |
| 7. current match state | 两边均构建 CurrentMatch，旧合并语义更完整 | 是，必须唯一业务权威与人工覆盖回执 |
| 8. lifecycle | 旧 LiveMatchSession 有退出换局；新 Engine 只恢复 sidecar | 是，至少可靠退出／中断／下一局；不确定可确认 |
| 9. settlement | 旧链有解析、复核和保存 | 最小边界是：停止当局建议、保全已采证据并可结束；完整自动结算不是 |
| 10. history | 旧正式链，新隔离 DRAFT | 正式历史写入不是；任何启用写入的正确性是 |
| 11. input | Python 路径与 Native 安全组合并存 | 纯观察首版不是；一旦启用则安全接线为硬依赖 |

有界队列只限制资源，不证明新鲜度。S5 队列满时丢新帧而保留旧工作；S6 顺序等待还会把推理耗时带回采集节奏。这是把 harness 改为持续产品时必须重新选择的调度语义，不是要求重做整个 MMF。

# MVP Hard Dependencies

最关键的三项：

1. **可信且新鲜的目标帧链**：明确支持窗口 geometry，确认像素来自正确客户区，带原始时间／目标身份，有界积压和失效提示。
2. **单一 CurrentMatch 的产品 bridge**：复用事实归一化、场景、回合、人工保护和生命周期，将完整必要状态接入现有 HUD／solver；拒绝跨局与旧版本结果。
3. **真实一局的决策价值闭环**：及时出价／情报、有条件估值、异常暂停、结算退出、下一局干净开始；所有输入和历史副作用受首版模式硬限制。

“Native 全迁移”不是这三项的同义词。只读首版仍必须关闭既有 Python 输入路径：S8 的生产 driver flag 实际为 True，`maybe_trigger_auto_warehouse_capture` 可调用 prepare/confirm，不能因为新 WGC harness 没有 SendInput 就推断整个助手没有输入。

# MVP Non-Dependencies

- 全仓自动滚动、每件身份全确证、疑难详情自动打开／关闭：首版可被动观察、列缺口；不可宣称完整识别。
- 自动获胜归属与正式历史学习：首版可保存隔离 DRAFT；不能据此抹掉长期交付边界。
- 自动输入、自动出价：前者可暂缓，后者不应加入当前产品目标。
- Native WebView2 外壳、DirectComposition 所有权迁移和移除全部 pythonnet。
- 任意分辨率、4K、多电脑发布、无边界二维完备求解。
- 无 goldAvg 仍强行正式估值、实验概率策略转正、新一轮 NCC benchmark。
- 预先填满全套长稳与验收矩阵；但“整局持续可用”的直接证据不能省。

# Architecture Work That Can Wait

保留既有 Native A/B/C、协议与 supervisor 成果，不回滚、不重新造轮子。把后续工作限制在所选产品链所需的 adapter、target/frame identity 和失效传播。

可以等：外壳语言迁移、全系统无感恢复、通用多分辨率协商、多个 Engine 插件、全链零拷贝、通用命令平台、广泛目录重排。先固定支持 geometry 并不意味着允许随意压缩或拉伸输入：客户区坐标映射和 ROI 正确性仍必须明确。

S4 当前把窗口外框直接交给视觉，而旧 S2 提供客户区。Handoff 的缩窗方案改变了客户区尺寸／比例；即使下一次传输通过，也不能据此认为 ROI 无需处理。最小方案可选择支持的无边框配置或显式裁出客户区，不必先做任意尺寸协议扩展。[判断]

# Safety / Correctness That Cannot Wait

| 不变量 | 首版最低要求 | 可延后的工程完善 |
|---|---|---|
| 输入不越权 | 观察模式执行端拒绝所有游戏输入；启用时唯一安全路径，失焦／接管后禁止且不自动 rearm | 更多输入类型和复杂恢复 UX |
| stale arm/ticket | 凭据绑定目标身份、focus epoch、扫描会话／generation、有效期，一次消费 | 通用凭据框架 |
| 会话隔离 | OS window generation、capture generation、Engine generation、业务 matchId 分开；旧队列、旧求解结果、旧命令不得写新局 | 无感跨进程恢复所有业务状态 |
| frame ownership | 私有拷贝完成后才 ACK，或持有 slot 到读取完成；ACK 必须精确匹配当前 token | 端到端零拷贝 |
| stale frame | 保留真实采集时间，处理前／发布前检验，UI 区分上次可信与当前可用；失去目标及时撤销当前建议资格 | 全量延迟仪表盘 |
| 金额正确 | 单位、席位、回合、字段类型和事实 revision 正确；缺失不是零；过期建议失效 | 更丰富趋势展示 |
| 物品归属正确 | 同一物理物品不重复入账；unknown 不当本人已获得；winner 不从价相等推断 | 完整自动获胜流程 |
| 图鉴 authority | 非空名称必须有正确 ID 与独立来源；候选不能自动升级，geometry／品质／身份分开 | 更大模板覆盖 |
| 历史正确 | 隔离数据根；DRAFT 不参与正式统计／学习；单局不重复；保存失败必须可见 | 第二台机器验收和更多导出选项 |
| 事前／事后隔离 | 预测绑定当时可见事实；结算不能回填为事前已知 | 自动模型迭代 |

S5 的 sidecar 恢复读取 prior match/context，并不等于知道当前真实游戏仍是同一局；更不能把 `businessReady=true` 当作当前局已完成 resync。桥接前须明确“恢复旧草稿”与“继续当前 live 局”的不同条件。

# Overengineering Audit

已有价值应保留：真实窗口身份、focus flap 防护、输入最终门禁、多冻结原因、slot 所有权、来源与历史权威。这些保护真实用户，不是过度工程化。

过度工程化风险来自开发顺序和完成定义：

- 长期把 OS 组件、scenario harness、审计签字作为终点，产品入口没有消费成果。WGC 与真实 Engine 已分别投入，但仍未形成用户可见链，最能说明接线优先级被压后。
- 把旧 Phase 的“只允许下一步、完成即交 reviewer”永久化，每个小函数都需用户转述；阻断了一次完成有界产品切片的自主性。
- 用 control-plane microbench 推断端到端价值。真实 fixture Engine 单帧约 4 秒，IPC 再快也没有证明竞拍结果及时。
- 以全套 verifier／manifest／多轮外审弥补没有真实产品使用。D3 已反复澄清组件不等于产品，不能再增加一层表格当作解决方案。
- 所有未完成项都写成 V2 migration target，容易让纯业务问题被误解为必须迁移后才可处理。round mapping、归属、缺失估价并不由换 UI 宿主解决。
- 固定 transport geometry 是合理的早期范围控制；若为继续维护它而长期要求用户非标准缩窗、阻断客户区帧接入，就会成为契约服务实现而非服务产品。

本轮不依据 Evidence 数量或工具数量宣布冗余；上述判断依据是否被实际产品消费、是否回答独立风险。未细读的 verifier 不能逐个判为无用。

# Work To STOP

- **STOP** 把 V2-4 完成作为首次接现有 HUD 的默认前置条件；只有明确旧 UI 阻塞才恢复此依赖。
- **STOP** 扩展尚无产品消费者的协议和能力协商。
- **STOP** 用 first frame、businessReady 或 productionReachable 一个布尔值代表“整局可用”。
- **STOP** 无新风险情况下重跑 A/B/C、重做回放与冻结包、重复人工焦点切换。
- **STOP** 每个小修复必经多模型循环 review，以及让用户在模型之间搬运常规 patch 信息。
- **STOP** 为首版追加 NCC 优化、实验红分布、无边界二维完备性研究；已有实验保留隔离。
- **STOP** 新增第二套业务事实／历史 owner；禁止直接把 Engine 隔离草稿当正式历史。
- **STOP** 把 clean worktree、证据计数或旧报告重新排版设为一个交付 Phase。
- **STOP** 为证明缩窗有效再次只验尺寸；下一项新证据应直达正确客户区像素及其被产品消费的意义。

# Dirty Worktree Assessment

dirty 不是先清理的理由。本轮读取的 diff 主要集中于 Native 桥梁和目录迁移；app/core 受查生产源码无本地 tracked diff，仅发现 core 内未跟踪快捷方式。新增目录未提交，所以 HEAD 不含完整候选能力。

| 内容 | 产品价值分类 | 安全收口建议（本轮不执行） |
|---|---|---|
| RawEventQueue／WindowMonitor revision fence，Integration observation source／gap 处理 | 有效安全能力；Native 接线相关 | 连同调用方作为同一可追溯变更收口；复用既有受控／真实 fake 记录，新增变动只测受影响门禁 |
| MmfFrameRingWriter、Host framepipe、engine_v22 | 当前 Critical Path 的可复用部分 | 保留；标为回放真实视觉 adapter，不标完整 live Engine；先确认业务 owner，再决定复用边界 |
| wgc_live_harness、engine_frame_probe | 必需 capture 的 spike／harness，未完成 live 帧证明 | 保留失败状态；不要为了提交把它包装为已完成生产能力 |
| controlled/live integration harness 与 verifier 改动 | 安全证据支撑 | 保留限定证据，勿扩张成每次开发必跑的套件 |
| 工具路径修改、dotnet_env、README/docs 路径说明、.gitignore | 迁移维护 | 就近核对入口与路径；部分工具仍硬编码 D 路径，随相关工作修，不开全仓重构 |
| spikes、tools 下 DLL／runtimes | 实验／运行依赖候选 | 本轮未穷尽使用关系，不按名字删除，也不批量提交二进制 |
| build 下 raw、产物、运行环境 | 既有运行材料／开发环境，非产品新增功能 | 保留 `repro-venv`；不纳入源码提交、不复制备份，不为 dirty 重新生成 |
| .workbuddy-ai、其他规划／报告、core 快捷方式、整理脚本 | 非当前产品桥梁；其中报告按独立性要求未读 | 由原作者后续收口；不臆测内容、不 stage-all、不删除 |

后续 coding agent 在唯一仓库按逻辑依赖提交有效源码，记录“哪些既有证据适用、哪些仍未知”即可。无需先用一个大 Phase 消除所有 dirty，也不要把其他审计者并行生成的文件收入自己的提交。

# Route A — Architecture First

先完成 WGC 持续捕获、Native WebView2／Overlay、Host 生命周期和 Engine 业务迁移，再连接全部用户流程。

收益：最终 OS 所有权集中，较少保留临时跨宿主 adapter；适合已有证据证明 Python 外壳本身严重妨碍日常使用、且难以局部修复的情况。

代价：把 UI 宿主、采集、状态、恢复与业务接线同时置于首次真实使用之前。语义缺口不会自动消失，反而更晚发现；现有产品价值不能提前检验。新 Native UI 同样要验证人工编辑、版本回执、失效投影。

安全：长期容易集中仲裁，但迁移期间仍有旧 Python 输入路径，不能默认安全已经统一。真正切换仍需对所有实际执行入口负责。

裁决条件：若明确旧外壳崩溃／阻塞是首版无法使用的最早根因，A 的额外成本可能必要。本轮代码与限定记录不足以得出“必须先彻底移除 pythonnet”。

# Route B — Product Bridge First

只补可信 capture／持续帧／失效传播所需 Native 能力，复用已有 Python 业务和 HUD，以观察模式形成第一版，之后按真实缺陷继续迁移。

最小架构边界：Native 负责目标／帧；现有业务编排负责 CurrentMatch 和事实归一化；现有 UI 只消费投影。`engine_v22` 可作为承载壳，但必须复用完整业务编排，不继续独立复制规则。S5 当前简化 projection 不足以作为这个合同。

收益：较早验证用户真正看得到的价值，复用旧 solver、场景、人工保护与历史框架；可在不启用输入的条件下开始 live 使用。

风险：临时 adapter 可能固化、双 owner／双 worker／双历史写入可能出现，必须通过单入口选择和明确 ownership 防止。过渡应按替换完成的接口删除旧 caller，不无限期维护两套互相同步的事实。

安全：第一版执行端关闭所有游戏输入，随后启用滚仓时再让 Native A/B/C 控制所有实际动作；不得让旧 Python driver 成为失败后的自动 fallback。

裁决条件：旧 UI 能承载首版、现有业务可通过较窄接缝复用，B 更有利于尽早使用。本轮支持把 B 作为优先候选，但其 bridge 工作量和实时性能仍待实际产品切片验证。

# Optional Route C

**条件式 C：旧产品 capture 先行。** 暂不等待 WGC，用现有 Python capture 和现有 HUD 实现同一观察首版；仅当一次针对性真实观察证明正确客户区、无遮挡污染、可接受新鲜度且不会阻塞 UI 时才采用。

优势是减少新接线；风险是 PrintWindow 阻塞、mss 遮挡／捕获失真和后续再次换源。C 是可选短路，不是第三套长期架构。当前没有足够证据直接判 C 可行，也不应为它启动另一轮完整 benchmark。若最小观察已经显示旧 capture 是根因，立即回 B，不继续补丁堆叠。

# Route Tradeoff Matrix

| 维度 | A：Architecture First | B：Product Bridge First | 条件式 C |
|---|---|---|---|
| time-to-usable | 首次价值等待外壳与多层迁移 | 首次价值主要等待帧、业务接线和整局闭环 | 旧 capture 合格时可能最短；不合格则没有优势 |
| technical risk | 多层同时改变，故障定位范围更大 | 跨宿主 adapter 与版本／会话映射 | 旧 capture 的阻塞、遮挡及新鲜度 |
| rewrite risk | 可能重造旧 UI 与业务编排，较晚发现需求不符 | adapter 会有替换成本；可保留业务规则与 UI | 后续换 capture；若重写旧底层则成本失控 |
| product value | 较晚获得真实一局反馈 | 较早验证出价／情报／估值是否有用 | 能最快复用已有能力，条件限制较强 |
| safety | 最终集中；迁移期间仍需关闭旧旁路 | 先无输入，后唯一 Native 仲裁；不能双入口 | 先无输入；现有 Python 输入同样必须关闭 |
| future migration cost | 前置支付宿主迁移成本 | 延后支付 UI 迁移和有限 adapter 替换 | 延后 capture＋Native 接线，存在重复投入 |
| 主要未决事实 | Python 外壳是否已构成不可绕过 blocker | 窄 bridge 可复用程度、WGC 持续帧及推理时效 | 真实旧 capture 是否满足首版合同 |

不按分数裁决。A 的必要性应由具体外壳缺陷支撑，B 的可行性应由完整事实投影证明，C 的资格应由真实捕获边界证明。

# Critical Path Candidate

以下 6 节点是以 B 为主的候选依赖顺序，不是重新命名 V2 的长 Phase。实现中可把相邻节点合并交付，但不能把每个函数拆成审批关卡。

## 1. 把一个真实目标变成可信持续帧源

- **当前状态**：WGC 源码在 harness，固定尺寸失败；旧 capture 已有产品调用。
- **为什么是 Hard Dependency**：没有正确且新鲜的像素，后续事实没有依据。
- **产品价值**：用户启动后能知道当前游戏画面是否真正可用。
- **最小实现**：选择一种支持窗口配置，明确外框／客户区映射；复用 MMF，带 target/capture generation 与真实采集时间；失效停止发布当前事实，有界调度最新帧。不要让 SendFrame 等 OCR 成为采集控制循环的唯一节奏。
- **最小验证**：复用 fixture 的传输证据；只针对新增 geometry 和持续性读取真实目标一小段包含可见变化的帧，核对客户区内容、时间与正常资源释放。帧率不作为代替内容的标准。
- **不做什么**：任意分辨率、全格式、极限 FPS、全面零拷贝、新一轮 A/B benchmark。
- **通过后用户离真实使用近了什么**：识别输入成为当前游戏的有效画面，不再靠离线 fixture。

## 2. 将唯一业务 worker 接回当前 Main/HUD

- **当前状态**：旧 worker 有完整产品编排，新 Engine 仅简化事实与隔离草稿。
- **为什么是 Hard Dependency**：用户看不到、不能纠正的 Engine 结果不是助手。
- **产品价值**：当前 UI 实时显示场景、出价、情报、可见物品与明确缺口。
- **最小实现**：确定唯一 CurrentMatch owner；让 Native frame source 进入旧编排，或让新 Engine 复用同一编排；复用字段转换、versioned snapshot 和 manual control 回执。产品入口只启动一个 worker；观察 profile 在执行端拒绝所有输入，关闭旧自动滚仓触发及正式历史写入。
- **最小验证**：一段已有带独立标注的业务序列经过实际 bridge，检查回合映射、席位金额、一次人工保护、HUD 可见投影及零输入。不可仅比较两份由同一 adapter 生成的 JSON。
- **不做什么**：重写 Native UI、新建第二种历史格式、导入 app/main.py 后任由其副作用同时启动旧 worker。
- **通过后用户离真实使用近了什么**：正常入口有真正更新的助手画面，用户不再需要 harness。

## 3. 建立跨帧、跨场景、跨局的提交门禁

- **当前状态**：旧 session/control 有可复用逻辑；新 Engine 缺完整换局编排，sidecar 恢复不验证 live 局身份。
- **为什么是 Hard Dependency**：串局、旧金额、迟到人工编辑会把辅助变成误导。
- **产品价值**：短暂失焦不丢局，明确退出后不把上局信息带到下一局。
- **最小实现**：目标／capture／Engine／match／facts revision 分层绑定；在结果提交与求解发布时拒绝过期；复用 LiveMatchSession，未知恢复等待确认。显示暂停、过期、待确认，并只保留标明时间的旧事实。
- **最小验证**：现有生命周期用例扩展一个“晚到旧帧／旧 solver 结果＋下一局”反例；一次 worker 断开重连确认旧快照不冒充已恢复。若修改边界未影响 Native 输入，复用 A/B/C 旧证据。
- **不做什么**：无感恢复全部状态、完整崩溃矩阵、多小时故障注入。
- **通过后用户离真实使用近了什么**：可以持续开着助手，不必每局清数据库或重启规避污染。

## 4. 让实时事实产生及时、诚实的决策帮助

- **当前状态**：旧 solver 存在；新 Engine 没接；单帧运行数据不能证明竞拍时效。
- **为什么是 Hard Dependency**：只有画面和 JSON 不足以形成拍卖助手价值。
- **产品价值**：四席关键出价与已读情报及时显示，有条件时产生估值和建议。
- **最小实现**：复用现有 v0.6／Node 求解 owner与准入；关键出价／情报优先，重身份异步；结果绑定事实 revision。缺 goldAvg 等必要条件时解释缺失，不能填经验值。只修实际造成错数、漏关键事实或明显滞后的最早瓶颈。
- **最小验证**：在同一产品切片中记录采集→事实→显示的少量实际时间点与金额；用已有独立正确输入检查 solver 数值。没有足够样本不声称 P95 达标；旧三项 P95 标准继续保留，不用传输 ACK 时间替代。
- **不做什么**：新估值模型、红分布转正、先做完整性能平台、以盲目调阈值掩盖错数。
- **通过后用户离真实使用近了什么**：竞拍当下获得可据以判断的信息，而不是赛后看日志。

## 5. 接好结算退出和下一局的最小闭环

- **当前状态**：旧归档／复核链存在；新 Engine 只写 DRAFT。
- **为什么是 Hard Dependency**：日常使用必须能结束一局、保留所采证据并继续，不能卡在结算或把旧建议继续当当前有效。
- **产品价值**：本局资料可回看，缺口清楚，下一局自动或确认后干净开始。
- **最小实现**：结算时使竞拍建议失效；复用现有保存与复核，首版仅隔离原图／DRAFT、保存失败可见；已采页面保留并标部分覆盖。无法证明赢家、成本、物品归属则保持未知；不加入正式学习。
- **最小验证**：已有结算→退出→下一局序列经过同一个 bridge，核对单局 ID、无重复草稿、下一局不继承金额／物品、保存错误有反馈。未改的导出／图鉴能力无需重测。
- **不做什么**：70 秒自动全仓、疑难点击、胜者名单全自动、跨电脑发布验收。
- **通过后用户离真实使用近了什么**：用户能打一局再打一局，不靠人工收拾状态。

## 6. 通过真实产品入口验证一局是否值得保留开启

- **当前状态**：当前只有分层证据，缺所选观察首版完整 live 使用证据。
- **为什么是 Hard Dependency**：First Usable 必须是用户真能使用的版本，不能只由同源测试推导。
- **产品价值**：确定实际使用负担、正确性与时效，而非猜测下一阶段。
- **最小实现**：提供一个明确版本／配置的启动入口和停止入口；不要求用户指定 engine 路径；若采用打包交付，只验证本次实际交付入口。一次列清需要用户的操作。
- **最小验证**：用户在正常玩法中打一局并进入下一局起点；旁路记录必要时间与错误，不安排额外全套桌面矩阵。检查是否真正提供可用出价／情报／条件估值、无输入、无正式历史污染、结束与新局正确。失败定位最早根因，只重跑受影响段；修 parser 后所用对局成为开发素材，不再宣称未见泛化证据。
- **不做什么**：用一局宣称完整识别／正式发布；取消既有三局未调参验收边界；自动附加冻结包、长稳和循环外审。
- **通过后用户离真实使用近了什么**：获得一版可以保留开启的受限观察助手；后续优先级有真实使用依据。

首版之后的明确扩展方向是受限安全输入→限时全仓与跨页账本→疑难身份→正式历史完整闭环；这不是本候选路径的追加硬依赖。若最终规划决定首版必须包含自动全仓，则必须把 Native 唯一输入仲裁、倒计时截止与去重质量提升为前置，并承认 time-to-usable 会增加。

# Testing Strategy

本轮只核对来源、调用关系与差异，没有运行测试。后续每次验证先回答：本次改动可能破坏什么，已有证据缺什么，哪个最小观察可以回答。

- 复用未改变的旧业务通过范围，保留原素材、版本、条件；不能升级为当前 live PASS。
- 所选 bridge 的新增风险集中在 geometry、owner、字段转换、freshness、manual revision、下一局、输入旁路和写入路径；对此做针对性行为检查。
- 一个已有行为用例能涵盖根因就扩展它；不复制实现生成期望，不新增固定源码结构断言。
- MMF 传输、OCR 正确性、HUD 显示、历史资格分别判定；ACK 提前释放只证明内存已安全拷贝，不证明业务结果有效。
- 真实操作只用于离线无法证明的窗口像素、实际显示时效和整局使用负担，集中一次告知用户；不要重复占用桌面。
- 已保存 raw 足够时离线修判定器，不要求用户重演。连续同因失败无新信息时停止盲试。
- 原“至少三局未参与调参”和性能门槛保留为相应完整／发布验收的未完成边界。候选首版范围更小，不伪称这些边界已通过；需要改变最终验收承诺时交最终规划者与用户裁决。

# Agent Collaboration Strategy

| 角色 | 合理职责 | 不应承担 |
|---|---|---|
| 高能力规划模型 | 一次裁决首版范围、Route A/B/C、owner、不可妥协边界；改变路线或产品承诺时再介入 | 每个函数、每个测试的默认审批 |
| local coding agent | 在一个有用户价值的纵向切片内定位、修改、最小验证、修复自身引入缺陷、交付可用入口；维护简短断点 | 自行升级实验为正式、扩大自动输入范围、改变历史／图鉴 authority |
| independent reviewer | 对一次有界交付的实际行为风险做独立审查；指出可定位后果与反例 | 以风格、计数、clean manifest 反复重开已闭合验收 |
| Obsidian | 保存当前交接、长期决定与事实边界；链接精确产物，避免按模型建立平行计划 | 驱动每个微小函数的流程引擎 |
| 用户 | 一次确认产品取舍；完成必要真实游戏操作；反馈是否值得日常开启 | 在 AI 之间复制常规日志、patch、测试结果 |

任务粒度建议是“一个端到端用户可感知切片”，例如“Native 帧进入现有 HUD 且旧回合结果不更新新局”，包含其实现、局部修复与验证。编码代理可自主修 adapter、字段映射、异常处理、已明确契约下的缺陷；无需每修一处找最高模型。

只有以下情况 STOP 并升级：需要放宽安全／事实准入；需要新增真实输入或正式数据写入授权；发现原需求互相冲突；不能确认待修改 dirty 文件归属；实际证据表明所选路线的关键前提不成立。缺用户实体操作时列出一次完整操作需求，并继续独立工作；不可无人值守反复等待游戏事件。

同一切片用仓库 diff、同一 Handoff 和报告路径交接。若已获协调授权，可由工具传递进展，不要求用户重复粘贴；并行只用于互不冲突的文件／任务，不重复测同一性质。本轮未启动其他 agent，以保持第三视角独立。

# Top 5 Risks To First Usable Version

1. **把局部 Engine 投影当完整产品事实**：同名字段遍历遗漏 round／结算转换、缺手动命令与换局，导致接上 HUD 后反而失去已有正确性。[S1,S3,S5]
2. **显示的事实已经过期**：readback 后打时间、处理时重设 captured_at、队列保旧、同步等待推理；快速 ACK 无法保证用户及时看到金额。[S4–S6]
3. **单局假成功掩盖跨局污染**：新 Engine 持续恢复相同草稿而无当前 live 局身份确认，上一局观察／solver 结果进入下一局。[S5；静态风险，未声称已发生 live 事故]
4. **观察首版意外触发旧滚仓或写历史**：Python driver 实际开启，旧主循环已有自动 prepare/confirm；只关闭新 Native 输入不足够。[S8]
5. **继续迁移而不交付，或过早把受限首版叫完整产品**：完整仓库／身份和未见对局效果仍未闭合；A 可能拖迟反馈，B 若忽略范围说明也会造成错误期待。[D2,D3]

# Questions / Unknowns

- 真实 WGC 在明确支持的客户区配置下能否持续给出正确帧？E2 之后只有环境调整声明，本轮没有新增 live 证据。
- 当前最早可用性瓶颈到底是 capture、OCR、事实编排还是 UI？E3 不足以判定各阶段占比；不要仅凭架构 spike 的 microbench 裁决。
- 最小 bridge 应供帧给旧 worker，还是把旧编排移入 engine_v22？需要按副作用与复用边界判断，不能让简化投影继续成为第二套业务实现。
- 用户是否接受首版以出价／情报／有条件估值为中心、仓库部分可见、无输入和仅隔离草稿？这是候选定义，不冒充用户已接受的新长期决定。
- 第一版日常使用的时效承诺如何与已有三个 P95 门槛衔接？不应为了赶首版偷偷改标准，也不应先建大型 benchmark 才看实际体验。
- 主源所述身份／全仓质量在未见对局的表现仍未知；本轮没有重审图鉴全集或完整视觉精度。
- Dirty 新增实现的正式接受状态、当前可交付启动包和依赖组合尚未核实；源码存在与可启动交付物分开。
- E1 的 productionReachable 指真实窗口被 harness 触达；E3 指 fixture 到真实 Engine。二者都不等于 app/main.py 的 Native 产品调用已成立。

# Advice To Final Planner

Astra Pro 应裁决四件事：首版价值范围；A/B/C 的前提是否成立；唯一业务 owner 与桥接边界；是否在首版启用任何输入／正式历史。然后把这些裁决交给一个可自主完成纵向切片的执行者，而不是生成几十个小 Phase。

不能被历史 Phase 掩盖的事实：旧产品并不空白；WGC 真实帧尚未证明；真实视觉 Engine 已可处理 fixture 但不等于 live；Native 安全没有进入所有产品输入；新 Engine 的事实／生命周期比旧链窄；全仓、身份、估值缺失规则不会由 V2-4 自动解决。

不要重新做：A/B/C 已接受且未受影响的验证；旧 solver 数学核心；已存在的人工保护／Canonical 历史框架；没有收益的新 NCC 实验；目录合并；另开恢复仓库；为三位模型意见一致再重跑一次全部测试。

建议把三份独立报告统一交给 Astra Pro 对照证据与分歧。分歧由“哪个前提能用最小事实裁决”解决，而非按模型投票；不用为了形成统一叙事改写任何独立报告的原判断。本文优先候选为 B，保留 C 的条件式短路及 A 在真实 UI 阻塞成立时的合理性。

# FOR_FINAL_ASTRA_PRO

1. 当前是成熟度不均的 Python 助手＋Native 组件，缺一条可信实时产品链。
2. 两栈为 PARTIAL 连接：共用业务模块，不共用完整运行编排与产品消费。
3. WGC live harness 接像素 probe；engine_v22 接真实视觉，但二者和 HUD 尚未形成完整一条链。
4. 真实 WGC 当前记录仍是 geometry FAIL；缩窗不是 first-frame PASS。
5. fixture 的 productionReachable／businessReady 不能等价于真实日常入口可用。
6. 新 Engine 遍历同名 FACT_KEYS，不能替代旧 round、leader、结算转换和生命周期。
7. 首版优先候选：无输入、隔离 DRAFT、可连续一局与下一局的观察助手。
8. 三大硬依赖：可信新鲜帧；单一 CurrentMatch bridge；真实竞拍决策价值与生命周期闭环。
9. Critical Path：持续客户区帧→现有 HUD bridge→跨帧跨局门禁→及时事实／估值→结算退出下一局→真实入口一局验证。
10. Route A/B 核心分歧是先迁外壳还是先验证产品价值，不是安全要不要做。
11. B 是优先候选；C 仅在旧 capture 满足真实合同后短路；A 需具体旧 UI blocker 支撑。
12. 观察模式必须关闭旧 Python 输入；driver flag 实际为 True，不能只看 Native dry-run。
13. frame ownership、freshness、金额、归属、catalog authority 和跨局隔离不可简化。
14. 有界队列和早 ACK 不证明实时性；S5/S6 当前仍有保旧帧与同步等待问题。
15. Native WebView2、广泛协议扩展和极限零拷贝可延后。
16. 全仓／身份仍是实际能力缺口，不能把所有剩余工作说成只有 wiring。
17. Dirty 含有价值的 bridge 与安全改动，按逻辑收口，不先 clean 或整仓重做。
18. 最大过度工程化风险是组件验收／多轮审批继续替代用户入口交付。
19. 保留旧证据范围与正式未完成边界，不因换模型／新 hash 重测，不把一局试用升级正式发布。
20. 三份独立报告应交给 Astra Pro 对照裁决；不要让用户继续承担日常消息搬运。
