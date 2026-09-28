# 异环拍卖助手｜完整项目状态包（Astra）

审计日期：2026-09-22  
审计仓库：D:/yihuanpaimai  
审计方式：读取 Obsidian 当前主源、当前工作区 Git 状态、相关源码、已有运行证据；未修改现有代码，未运行全量测试。

## 先看结论

这是一个面向《异环》（Neverness to Everness）拍卖玩法的截图识别、情报整理、仓库识别、估值、历史记录和可控自动化辅助工具。长期产品目标远大于当前 V2 迁移状态。

当前真实状态不是“完整产品已完成”，也不是“V2 全部完成”：

- 旧 Python 产品和业务核心存在，包含视觉、OCR、CurrentMatch、Canonical MatchRecord v7、历史、导出、HUD/WebView2 和 v0.6 估值核心；整体仍是 PARTIAL。
- V2-0 协议、V2-1 Host/supervisor、V2-2 A/B/C 以及 Integration 安全边界已有范围性通过证据。
- 真实 HTGame.exe / UnrealWindow 的观察与 focus gate 已通过：窗口身份建立，失焦立即 fail-closed，恢复不会自动复用旧 arm/ticket，失焦 raw input delta 为 0；这只是安全观察门，不等于真实 SendInput 或完整生产接管。
- V2-3 的真实 WGC 首帧还没有取得。当前执行断点是：
  CURRENT_EXECUTION_POINT = V2-3 / WGC frame pool + first real frame
- 之前的 1922×1112 固定几何阻塞已通过环境调整解除：Win32 只读检查得到当前真实客户区 1880×1040，外框 1896×1079；V2-0 geometry contract 没有修改。但调整后尚未重新执行真实 WGC → MMF → Engine → ACK。
- 本状态包不能把受控窗口、回放图片、fake actuator 或旧 G2 帧传输证据升级成真实游戏生产通过。

### 事实级别与标记

- DONE：在明确范围内有可复用证据，且不是只存在计划。
- PARTIAL：组件或局部业务链已存在，但生产边界、真实素材或完整生命周期仍缺。
- COMPONENT_READY：组件已实现或就绪，但没有接入生产路径。
- OFFLINE_ONLY：只在回放、离线、fake 或确定性探针中成立。
- HARNESS_ONLY：只在独立 harness/probe 中存在，尚未接入正式入口。
- NOT_MEASURED：没有可信测量，不用邻近数字代替。
- UNFINISHED：明确未完成。
- BLOCKED：当前阶段被一个已定位的门禁阻塞。
- DOC_REPO_MISMATCH：文档当前陈述与仓库可核对事实不一致。
- REPO_AHEAD_OF_DOCS：工作区已有实现或后续证据，但对应文档仍是旧时点快照。

## 1. 项目一句话定义

异环拍卖助手观察《异环》的拍卖生命周期，采集游戏画面和证据，识别四席出价、中间情报、右侧藏品/结算仓库和场景状态，结合图鉴与六品质估值核心给出可追溯的辅助判断，保存对局历史并提供 HUD/UI；Native Host 负责 Windows 窗口、焦点、输入安全、截图和进程边界，Python Engine 负责 OCR、视觉、图鉴、业务事实、估值、历史和导出。

## 2. 最终产品目标

### 2.1 长期想做到什么

产品最终要覆盖一个可日常使用的完整拍卖工作流：

- 游戏生命周期：大世界、都市大亨/大厅、加载、局内拍卖、结算、返回、大厅、消耗道具补货和下一局；加载回大世界视为中断。
- 视觉识别：顶栏回合/倒计时，左侧四席每回合可见出价和玩家身份，中间全部可见情报，右侧已显露藏品/结算内容。
- 仓库：自动滚动覆盖有限时窗口，全仓原图保全，多页/滚动物理去重、跨页拼接、几何覆盖、品质、尺寸、轮廓和具体身份分层表达；疑难物品允许左键打开详情后采集并关闭恢复。
- 图鉴和身份：以本项目官方/用户核验的 catalog 与 source card 为权威；未确认身份保持 null，不以形状绰号、竞品图鉴、占位名或默认值冒充事实。
- 情报和估值：免费情报独立业务链，六品质联合估值、保本/目标利润/追价口径分离，保留 v0.6 数学核心和 Historical Shadow；未知值不强行填成 0 或虚构报价。
- 对局与历史：CurrentMatch 是当前局事实权威；手动、OCR、回放共用业务 Core；DRAFT 到 FINALIZED 有门禁，winner/acquired/settlement 各自需要独立证据；CanonicalHistoryStore、Summary、Export、manifest、原图和 evidence 可回溯。
- 交互和自动化：简洁常驻 HUD，手动/自动状态同步；在焦点、身份、generation、focus epoch、freeze 和一次性 ticket 均满足时才允许未来的安全输入；用户接管、失焦、身份变化和事件缺口必须 fail-closed。
- 工程化：Native Host 与 Python Engine 分进程，Named Pipe 控制面、固定 MMF 数据面、supervisor/恢复、只读 Engine 映射、可复算 evidence 和最终打包发布。

### 2.2 当前已经做到什么

- Python 业务主链的许多组件已存在，部分有 L3/L4 证据。
- V2-0 固定协议和 V2-1 supervisor 已完成实验性基础。
- V2-2 A/B/C 和 Integration 已形成窗口身份、焦点、输入安全、freeze 和 stale credential 的 fail-closed 链。
- 真实《异环》窗口的观察安全门已通过一次实际前台 → Alt-Tab 失焦 → 返回序列。
- 回放图片已经证明一条真实 Host/Engine/MMF/FRAME_READY/FRAME_ACK 的纵向帧传输路径；这不是 WGC 实时游戏证据。

### 2.3 暂时明确不做

当前状态包不授权或不宣称以下内容完成：

- 真实 SendInput、自动出价、购买、出售或完整拍卖自动化。
- WGC 之外的 V2-3 扩展、V2-4 CoreWebView2 迁移、Overlay、OCR/warehouse/solver/history 的新一轮重构。
- 真实一局 E2E、三局未调参留出验证、游戏重启/HWND 重建完整矩阵、长稳、跨电脑发布。
- 将 PR-B 红装推断、PR-C 概率策略实验变成正式算法。
- 以固定格价、未知 PMF、默认值、结算反推或竞品 catalog 替代正式事实。

## 3. 当前真实 Git 状态

### 3.1 基线

| 项目 | 当前事实 |
|---|---|
| repo | D:/yihuanpaimai |
| branch | codex/consolidate-workspace |
| HEAD | cb86697c976a0658f5e301f5e199b269f26a14e6 |
| HEAD message | feat(v2-2): add offline Integration I1 safety chain |
| worktree | DIRTY；本次审计不清理、不 reset、不 stash |
| 当前产品版本 | core/version.py 为 v0.68-alpha，Canonical schema version 为 7 |

HEAD 之前的相关提交链为：V2-0 contracts pass（23ea3d2）、V2-1 host supervisor（a9b52c6）、V2-2A window/focus monitor（f3807fa 及后续修正）、V2-2B 输入安全（b1334c6）、V2-2C freeze coordinator（878435e），最后合入 I1 离线集成的 cb86697。

### 3.2 dirty worktree

生成本文件前的只读 status 显示：tracked 文件有 34 个修改；另有大量 untracked 文件/目录。主要来源如下：

- V2-2/Integration 工作区修改：architecture/v2/host/NteHost.WindowMonitor、NteHost、window_monitor_harness、architecture/v2/integration、architecture/v2/input/verifier。
- 目录合并和工作规则：README.md、docs/README.md、docs/plans/2026-09-05-project-replan.md、AGENTS.md。
- 工作区工具修正：tools/audit_*.py、tools/v2/*.py、tools/verify_*.py、workspace consolidation 脚本。
- untracked 的当前 V2 试验代码：architecture/v2/host/NteHost/MmfFrameRingWriter.cs、architecture/v2/host/wgc_live_harness/、architecture/v2/host/engine_frame_probe/、architecture/v2/host/engine_v22/、WindowMonitorIntegrationObservation.cs、LiveIntegrationHarness.cs、ControlledIntegrationHarness.cs。
- untracked 的 reports、spikes、运行库 DLL、scripts 和 .workbuddy-ai/memory；build 下的日志/证据按项目规则保留在项目内，通常不纳入 Git。

因此 HEAD 不是当前工作区的全部源码。尤其是 WGC harness、实际帧生产者和 Engine adapter 尚未成为 HEAD 的提交内容。它们必须被视为当前工作区候选，不可引用为已合并正式功能。

本文件是本次任务唯一新增的状态文件；本次没有修改已有代码、文档主源或运行证据，也没有处理上述 dirty 内容。

### 3.3 文档与仓库交叉核对

| 标记 | 发现 | 解释 |
|---|---|---|
| DOC_REPO_MISMATCH | docs/README.md 的 2026-09-20 条目仍写“尚未启动实施”，但同一工作区已有 G0–G5 报告、真实 Integration evidence 和 V2-3 WGC harness。 | 这是文档索引的旧时点陈述，不作为当前状态依据；以 Obsidian Handoff、当前 evidence 和源码为准。 |
| REPO_AHEAD_OF_DOCS | Architecture V2 Spike 的历史结论仍把 WGC 写为 NOT_MEASURED；当前 worktree 已有新的 WGC live harness，并曾走到真实 HWND/item size 检查。 | 这是历史 spike 与后续工作包的时点差异，不代表 WGC 首帧已成功。 |
| REPO_AHEAD_OF_DOCS | Feature Truth Matrix 的旧审计快照仍统计真实 live game L5 为 0、C03 为 PARTIAL；随后 Handoff 增加了真实窗口 Integration 观察门证据。 | 只更新“观察/安全门”事实，不升级 C03 整体、真实输入或完整产品状态。 |
| 无当前冲突 | README 的总体 PARTIAL、Handoff 的 V2-3 geometry blocker/环境解除记录、当前 WGC 结果文件与源码相互一致。 | 旧报告和新 Handoff 必须按日期分层读取。 |

## 4. 当前架构

### 4.1 真实架构分层

    旧产品入口 app/main.py / app/main_window.py
        → 现有 Python 捕获、场景识别、OCR、视觉、业务状态和 HUD/WebView2
        → core/CurrentMatch、估值、历史、导出

    V2 Native Host（architecture/v2/host）
        → WindowMonitor / identity / foreground / lifecycle
        → 输入安全和 Freeze Coordinator
        → WGC/D3D11 capture（当前为独立 harness）
        → Protocol 1.0.0 Named Pipe 控制面
        → 固定 4-slot MMF 数据面
        → Python Engine（engine_ref mock、engine_v22 试验 adapter、engine_frame_probe）
        → 既有 Python vision/catalog/solver/history（尚未由 V2 正式入口完整接管）
        → 未来 UI/HUD/production cutover

### 4.2 各层职责和成熟度

| 层 | 权威职责 | 当前实现 | 当前成熟度 |
|---|---|---|---|
| Window/identity/lifecycle | HWND、PID、image、class、process instance、generation、foreground | NteHost.WindowMonitor、真实 HTGame 观察 evidence | DONE（真实观察门）；重启/HWND 重建真实场景未测 |
| Focus/input safety | focus epoch、TOCTOU、用户接管、freeze、一次性 arm/ticket、raw input 仲裁 | A/B/C、IntegrationCoordinator、CArbitratedRawInputBackend | DONE（fail-closed/假执行范围）；真实 SendInput 未执行 |
| Capture | 真实 HWND → WGC frame pool → BGRA8 readback | wgc_live_harness/WgcCapture.cs | HARNESS_ONLY；真实 WGC 首帧尚未取得 |
| Host supervisor | Python 子进程、pipe、generation、ready/restart | NteHost、SupervisorSession、JobObjectGuard | DONE（V2-1/试验验证）；尚未成为 app/main 默认宿主 |
| Protocol | protocol 1.0.0、HELLO、FRAME_READY、FRAME_ACK、错误和生命周期 | architecture/v2/contracts、NteHost.Protocol | DONE；geometry 不可协商 |
| MMF producer | 写 64-byte header、BGRA8 payload、锁槽、精确 ACK 释放 | MmfFrameRingWriter.cs，当前 untracked | COMPONENT_READY；回放链有证据，真实 WGC 未接通 |
| MMF consumer | read-only map、header/metadata/checksum、复制后 ACK | engine_v22、engine_frame_probe | DONE（回放/transport probe）；真实 WGC frame 未读 |
| Python business engine | OCR、视觉、catalog、CurrentMatch、solver、history | core/、engine_v22.py | PARTIAL；真实 WGC/正式 app 入口未闭合 |
| UI/HUD | WebView2/DirectComposition、战术 HUD、review/summary/export | app/、core/*.html/js、DirectCompositionHost | PARTIAL；V2-4 Native shell 未完成 |
| 证据/发布 | build evidence、原图、manifest、candidate、package | build/、docs/、tools/、app spec | PARTIAL；当前 V2 未形成 release |

### 4.3 权威边界

- 当前局事实：CurrentMatch；Main/HUD 只是投影，不得维护第二套业务真值。
- 历史：CanonicalHistoryStore；Summary 从已保存 MatchRecord 确定性派生。
- 视觉/事实来源：OCR、Manual、Replay 进入同一业务 Core；缺失不等于清空。
- 图鉴身份：本项目 catalog/source card 和合法 catalogId；竞品资料只能做调研，不能反向成为权威。
- Native Host：Windows 观察、焦点、输入、capture、子进程和 transport 边界。
- Python Engine：OCR、视觉、物品身份、估值、CurrentMatch、history 和导出。
- V2-0 contract：architecture/v2/contracts 是协议和 geometry 的权威；不能通过私有字段或缩放偷偷改变 fixed-v1。

## 5. 全功能地图

下表是完整产品地图，不把“已有组件”自动升格为“完整生产功能”。

### 5.1 Windows、传输和安全

| 功能 | 状态 | 真实边界 |
|---|---|---|
| 游戏窗口发现 | PARTIAL | WindowMonitor 能发现真实 htgame.exe/UnrealWindow；未接入正式 app/main V2 入口 |
| focus / lifecycle | DONE | 真实前台 → Alt-Tab → 返回已验证；游戏重启/HWND 重建真实场景未验证 |
| 输入安全 | PARTIAL | A/B/C、受控窗口和真实 focus gate fail-closed；真实 SendInput 未执行 |
| WGC capture | HARNESS_ONLY | WGC harness 存在；先前真实 HWND item size 超出 fixed-v1，环境已调整但没有 post-adjustment 首帧证据 |
| Host supervisor | DONE | V2-1 的启动、握手、退出、崩溃/恢复探针范围有证据；不是正式产品默认宿主 |
| Host↔Engine IPC | DONE | Named Pipe/协议/handshake/ready/recovery 有证据；真实 WGC 业务链未闭合 |
| MMF | DONE（回放范围） | fixed-v1 4-slot producer/consumer/ACK 已由回放 fixture 验证；真实 WGC 未写入 |
| HUD / UI | PARTIAL | 旧 Python UI、HUD、WebView2/DirectComposition 存在；V2-4 Native UI 未完成 |
| freeze coordinator | COMPONENT_READY | C 的离线/受控 coordinator 已通过；生产导入者为空，productionReachable=false |

### 5.2 拍卖、识图和仓库

| 功能 | 状态 | 真实边界 |
|---|---|---|
| 拍卖开始 / 加载 / 局内 / 结算 / 返回 | PARTIAL | vision/session FSM 有场景枚举和业务代码；完整真实游戏生命周期未 E2E |
| 左侧玩家出价 | PARTIAL | 四席/回合 OCR 与 bid observation 存在；重复 OCR/真实局全链仍有限制 |
| 中间情报 | PARTIAL | OCR、field_intel_status、intel evidence 存在；免费情报独立链未完全接通 |
| 右侧藏品/结算 | PARTIAL | settlement recognizer/grid/evidence 与 warehouse 组件存在；完整身份/全仓覆盖未通过 |
| 仓库识别 | PARTIAL | grid、occupancy、ledger、review、placement、auto confirmation 组件存在；canonical #4 未完成 |
| 多页 / 滚动 / 去重 | UNFINISHED | PR-D runtime guards 和 replay physical dedup 组件存在；真实限时全仓和跨页物理账本未闭合 |
| 品质 | PARTIAL | 底部品质出售默认勾选机制是唯一 Canonical PASS；整仓品质/出售实机链不等于该局部 PASS |
| 藏品身份 | PARTIAL | catalog_validator 已接入部分生产入口；全部入口覆盖和真实多页身份未证明 |
| 图鉴 | DONE（组件/快照范围） | visual catalog、manifest、source card registry 存在；快照完整性和全部生产入口仍有限制 |
| OCR | PARTIAL | RapidOCR/后处理/ROI 代码存在；实时 WGC 输入、P95 门槛和完整疑难详情流程未完成 |
| replay | DONE | 回放 source provenance、隔离运行和 transport/业务投影有证据；不得冒充真实游戏 |
| 截图 / evidence | PARTIAL | 回放、受控窗口、manifest/evidence 基础存在；真实 WGC 代表帧尚未保存 |

### 5.3 估值、归属、历史和自动化

| 功能 | 状态 | 真实边界 |
|---|---|---|
| 估值 | PARTIAL | v0.6 数学核心和正式/实验资格边界存在；goldAvg 正式估价和完整实机输入未完成 |
| 六品质联合 solver | COMPONENT_READY | 旧 v0.6 solver/Node 路径保留；未知/不完整输入必须 fail-closed，未完成完整真实产品门禁 |
| Historical Shadow | PARTIAL | live_shadow 和独立 shadow 组件存在；不能升级成正式报价或自动出价 owner |
| winner | PARTIAL | acquisition_authority 有精确名/fail-closed 规则；真实本人获胜实录未执行 |
| acquired | PARTIAL | 只接受独立证据，不从 leaderName、profit、价格关系或占位名推定 |
| settlement | PARTIAL | 结算识别/归档/复核组件和局部 L4 证据存在；胜者名单治理与真实完整结算仍缺 |
| History | DONE（存储组件） | CanonicalHistoryStore、锁、状态转换、隔离 history 有证据；完整真实对局覆盖未完成 |
| Summary | DONE（派生规则） | 应从 MatchRecord 派生；完整 UI/真实 winner 语义仍受上游状态限制 |
| Export | PARTIAL | 同机跨目录带图 manifest 13/13 往返证据；真正跨电脑未验证 |
| 自动归档 | DONE（组件范围） | auto_archiver/canonical store 存在；不能由组件存在推定完整归档闭环 |
| manual / auto | PARTIAL | manual/auto merge protection 已通过局部验收；完整自动拍卖没有生产资格 |
| input takeover | DONE（安全门） | 用户接管/失焦/旧 ticket 拒绝已验证；真实执行端保持禁用 |
| 真实一局 E2E | UNFINISHED | 没有合格的、未调参的真实完整一局证据 |
| 打包 / 发布 | PARTIAL | 旧 app spec/冻结运行证据存在；当前 V2 candidate 未形成正式发布包、tag 或 release |

### 5.4 Canonical / Matrix 总览

Feature Truth Matrix 的最近审计快照记录：

- Canonical 14：1 PASS / 7 PARTIAL / 6 UNFINISHED / 0 UNKNOWN。
- 核心正式主链 10：6 PASS / 4 PARTIAL。
- PR-A～PR-F（PR-D 拆为 runtime 与 freeze 两条）：3 PASS / 3 EXPERIMENTAL / 1 COMPONENT_READY。
- 总体计数：PASS 10、PARTIAL 11、UNFINISHED 6、EXPERIMENTAL 3、COMPONENT_READY 1。
- 真实 live game L5：该旧快照为 0；后续 Handoff 的真实窗口 Integration 只改变观察/安全门，不重写 Canonical 14 的总体状态。

Canonical 未完成边界中最影响产品路线的是：真实本人获胜全链仅 PARTIAL；真实键鼠接管仅 PARTIAL；全仓滚动/跨页去重、疑难详情、三局真实 E2E、连续稳定性、实时 P95、历史测试债仍 UNFINISHED；免费情报、导出、二维无上限摆放等仍 PARTIAL。

## 6. 历史上已经关闭、不要重复做的工作

下列结论有明确范围和证据，后续规划不应因为模型更换、executor 更换或想“再确认一次”而重跑同一重型验收：

| 已关闭范围 | 可复用证据 | 不要误解为 |
|---|---|---|
| V2-0 protocol contracts | tag architecture-v2-0-contracts-pass、architecture/v2/contracts、golden vectors/geometry parity；历史 46/46 contract 结果 | 不代表真实游戏已产帧 |
| V2-1 Host supervisor | tag architecture-v2-1-host-supervisor-pass、HostSupervisorVerifier 历史 28/28 | 不代表 app/main 已切到 Native Host |
| V2-2A | Handoff 记录的 accepted head 934ce47e3dec223a8046dbca35452de8774f857c | 不需重新验收整个窗口监视器 |
| V2-2B | accepted head b1334c6ac11a9873030ed67e7f6418b22f69ccc0；offline/limited live 的输入安全证据 | 不代表真实 SendInput 已执行 |
| V2-2C | accepted head 878435e96034caa130c622de0ab968162d65a595；27/27 native verifier 范围 | 不代表 freeze coordinator 已接入 production |
| I1 offline integration | build/workspace-consolidation/integration-summary.json、integration-raw.ndjson；11/11 fake 场景 | 不代表真实窗口/游戏 |
| 受控窗口 Integration | build/goal-luna/native-bridge/controlled-integration/integration-result.json；正常、失焦、身份变化拒绝且禁止时 raw delta=0 | 不代表真实游戏帧 |
| 真实窗口 Integration gate | build/goal-luna/native-bridge/real-window/integration-live.json；目标 8919338、focus flap、旧 ticket 无效、失焦 raw delta=0 | 不代表真实输入或完整拍卖 |
| 回放 Host→Engine→MMF 帧链 | build/goal-luna/frames/candidate-final/host-result.json、engine_mmf_probe.json、frame_records.ndjson；READY/字节校验/ACK/隔离业务投影 | 不代表 WGC 实时游戏帧 |
| G0–G5 最小交付范围 | docs/reports/luna-goal-progress.md、luna-goal-acceptance.md | 报告明确限定为回放、受控窗口、隔离 Engine |
| 旧 capture probe 语义解释 | spikes/architecture_v2_native_host/ScreenCaptureProbe.cs | 不要把 30/30 当作 WGC dropped frames |

因此不要重新跑：A/B/C 全套、focus flap、I1 全矩阵、V2-0/V2-1 全套、冻结包冒烟、全量 Python/.NET suite、游戏重启/HWND 重建矩阵或两小时长稳，除非将来出现新的实际改动或独立失败。

## 7. V2 迁移完整状态

| 阶段 | 目标 | 当前状态 | 已通过/未通过 | production 边界 | 是否可继续 |
|---|---|---|---|---|---|
| V2-0 | 锁定 Protocol 1.0.0、FrameHeaderV1、4-slot MMF geometry | DONE | contracts/golden/parity 已有证据 | contract 已冻结，不可在 V2-3 偷改 | 可继续 |
| V2-1 | Native Host 骨架、Named Pipe、supervisor、generation/recovery | DONE | supervisor、handshake、lifecycle、故障探针有证据 | 仍是实验宿主，未接 app/main | 可复用 |
| V2-2A | 窗口发现、identity、foreground、lifecycle | DONE（范围性） | controlled + real HTGame observation | real observation 已达 productionReachable=true（仅该门） | 已关闭，不重测 |
| V2-2B | 输入观察、安全执行和用户接管 | PARTIAL | fail-closed/focus gate 通过；真实执行未做 | realInputPathReachable=false、realInputExecuted=false | 后续可独立处理 |
| V2-2C | freeze、rearm、stale credential、仲裁 | DONE（offline/controlled） | 27/27 和 Integration 相关门通过 | freeze coordinator productionReachable=false | 可复用 |
| Integration I1 | A/B/C 组合为统一观察→协调→动作链 | DONE（offline/controlled） | 11/11 fake、controlled chain、真实观察门 | 不等于完整生产入口 | 已关闭 |
| 真实窗口 Integration | HTGame.exe / UnrealWindow 观察与 focus gate | DONE（观察安全门） | identity、前台、失焦、恢复、raw delta=0 | productionReachable=true 只指观察/门禁；无真实输入 | 已关闭 |
| V2-3 | WGC 原生 capture → MMF → Engine read → ACK | HARNESS_ONLY / NOT_MEASURED | item size 检查曾失败在 fixed geometry；环境已调整；真实首帧链未重跑 | 当前生产 reachability=false | 只允许继续最小首帧验证 |
| V2-4 | Native CoreWebView2/UI shell | UNFINISHED | 旧 app 有 WebView2；V2 shell/生存性未形成验收 | 不应提前切 production | 等 V2-3 |
| V2-5 | full-chain regression、旧 Python glue 清理和最终迁移 | UNFINISHED | 未开始 | 依赖 V2-3/V2-4/真实业务边界 | 不可提前宣称 |

## 8. 当前最新断点

### 8.1 已核实的真实窗口事实

来自 Handoff 和 build/goal-luna/native-bridge/real-window/integration-live.json：

- 目标：HTGame.exe / UnrealWindow / 标题“异环”。
- targetHwnd：8919338。
- targetPid：35860。
- processInstanceToken：134343738891157135。
- identity：可见、存活、image/class/title/HWND/PID/process instance 均建立。
- generation：1；focus epoch 经实际 focus flap 为 0 → 1 → 2。
- 游戏前台时 observation 正常，arm 可建立。
- Alt-Tab 失焦后检测到 FOCUS_LOST，发送许可关闭，旧 arm/ticket 失效，raw input delta=0。
- 切回游戏后检测到 focus gain，但保持 fail-closed；旧 arm/ticket 没有被复用，仍需显式重新 arm；raw input delta=0。
- 本轮及此前真实窗口评估没有执行真实 SendInput。
- realInputPathReachable=false；realInputExecuted=false。
- productionReachable=true 只适用于“真实目标窗口观察/Integration safety gate”这个窄范围，不适用于完整产品或真实输入。

### 8.2 当前 V2-3 的真实事实

- wgc_live_harness/WgcCapture.cs 已实现真实 HWND → GraphicsCaptureItem → D3D11 frame pool → BGRA8 staging readback 的最小候选路径；Program.cs 还准备了 MMF/Engine/ACK 检查和一张代表性 BMP。
- engine_frame_probe/engine_frame_probe.py 以 FILE_MAP_READ 打开 MMF，校验 FrameHeaderV1、FRAME_READY metadata、checksum、非零内容后发送 FRAME_ACK；它不做 OCR/vision/history。
- MmfFrameRingWriter.cs 已有 fixed-v1 producer：4 槽、精确 session/index/sequence ACK、禁止覆盖锁槽、固定 geometry fail-closed。
- 旧真实 WGC 运行证据 build/goal-luna/native-bridge/real-window-v2-3/wgc-mmf-result.json 的结果是：captured=0、published=0、dropped=0；最早阻断为真实 WGC item/窗口尺寸 1922×1112 超过 fixed 1920×1080，未进入 frame pool。因此 dropped=0 不是“WGC 没丢帧”的性能结论。
- 之后仅做了环境调整，没有改 protocol/geometry，也没有重跑 WGC：Win32 读到客户区 1880×1040、外框 1896×1079。1922×1112 是此前把外框/非客户区尺寸当成 capture geometry 的误判来源。
- 因此下面这条链目前仍未被真实《异环》画面证明：
  WGC frame pool → first frame → MMF write → FRAME_READY → Engine read → FRAME_ACK
- 没有真实 WGC PNG/BMP；受控窗口 PrintWindow PNG 和回放 fixture 不能替代它。

## 9. 当前 blockers

### 9.1 已解除

- fixed-v1 与此前 1922×1112 的尺寸冲突：通过环境调整把真实客户区降到 1880×1040，geometry contract 保持不变。
- 真实窗口未发现、identity 不完整、失焦后误放行、旧 ticket 复用、失焦 raw input 仍增长：均已有对应证据，不再是当前 blocker。

### 9.2 当前确认的 blocker

当前没有新的已确认代码 blocker。V2-3 的状态是“缺少调整后真实首帧证据”，不是“协议需要扩展”或“WGC 已失败”。下一次只需在当前环境执行一次最小 WGC 首帧链验证；若再次失败，只报告最早失败点。

### 9.3 未来风险（不是当前 blocker）

- WGC frame pool/WinRT/D3D11 readback 在当前实际窗口上的兼容性。
- WGC content size 动态变化、窗口模式变化与 capture lifecycle。
- MMF producer 与真实 Engine 之间的槽所有权、ACK 延迟和生成代次。
- 真实 Engine 接入既有 vision/current/history 后的业务 ready gate。
- UI/HUD 和 app/main 的 production cutover。

## 10. 技术债与已知风险

- Protocol 1.0.0 geometry 是 fixed-v1：slotCount=4、maxWidth=1920、maxHeight=1080、slotPayloadCapacityBytes=8294400、headerSizeBytes=64、slotSizeBytes=8294464、mapTotalSizeBytes=33177856。不能私加 geometry negotiation、私有 frame schema 或静默 resize。
- FrameHeaderV1 和 FRAME_READY 必须精确一致：bufferIndex、sequence、width、height、stride、pixelFormat=1(BGRA8)、bufferLength、captureTimestampNs、cornerChecksum。
- Sequence 是 generation-scoped monotonic；generation、session、HWND、process instance、focus epoch、C session 不可混用。
- MMF slot 只有收到精确 sessionId + bufferIndex + sequence 的 FRAME_ACK 后才能释放；不能覆盖未 ACK 槽，不能在 ACK 后继续异步读。
- capture geometry 必须明确客户区/外框语义；ROI/OCR/warehouse 坐标不能从错误的外框尺寸推导。
- stale arm/ticket、focus regain 自动复用、同 HWND 身份重建是高风险安全边界；当前 gate 已保护，但真实主动输入仍未开。
- OCR/warehouse 的跨页物理存在、分件、品质、identity、geometry 和人工确认语义不能合并为一个“识别成功”布尔值。
- catalog validator 只核对已接入入口的一部分；任何非空 canonicalName 必须有合法 catalogId、官方匹配和 source evidence。
- winner/acquired/settlement/history 的权威链必须保持独立证据；DRAFT 不等于 FINALIZED，赛后重识别不能改写事前快照。
- PR-B/PR-C 仍为 experimental；Historical Shadow 不能成为正式报价或自动出价 owner。
- app/main.py 仍是旧产品入口；V2 Native Host/Engine/WGC 目前没有正式接入它，当前候选代码也没有默认切换。
- dirty worktree 是真实交付风险：HEAD 不包含多个当前候选文件；后续提交必须按文件归属处理，不能 git add . 或把 build evidence 当源码。

## 11. 测试与证据策略

### 11.1 当前规则

- 使用最小充分验证：每次只证明本次改动实际可能破坏的行为。
- 已有 PASS 直接复用；不因为 executor、reviewer、commit 或目录变化重跑旧验收。
- 不机械叠加 unit、targeted、full suite、desktop、frozen package、long soak。
- 新失败只定位 earliest blocker；连续同因失败且没有新信息时停止盲试。
- fake、受控窗口、回放、真实游戏必须分账，不能把低等级证据升级成高等级生产结论。
- 本次状态重建只做只读检查；没有运行测试、build 或桌面验收。

### 11.2 可直接复用的 evidence

| Evidence | 可证明的范围 |
|---|---|
| Obsidian Handoff：A/B/C 与 Integration 各阶段记录 | 已接受的窗口身份、输入安全、freeze、offline/controlled Integration 边界 |
| build/goal-luna/native-bridge/real-window/integration-live.json | 一次真实 HTGame 窗口观察和前台/失焦/恢复安全门 |
| build/goal-luna/native-bridge/controlled-integration/integration-result.json | 受控窗口 Integration 顺序、拒绝和 raw delta=0 |
| build/goal-luna/frames/candidate-final/ | 回放 fixture 的真实 Host/Engine/MMF/READY/ACK/业务投影 |
| build/goal-luna/native-bridge/real-window-v2-3/wgc-mmf-result.json | WGC 旧运行的最早 geometry blocker；不是 dropped 性能结果 |
| architecture/v2/contracts/ | 固定协议和 data-plane contract |
| spikes/architecture_v2_native_host/ScreenCaptureProbe.cs | 旧 Samples=30/DroppedFrames=30 的计算语义 |
| Obsidian Feature Truth Matrix / Feature Correctness Audit | 业务能力状态快照；必须按 audited date 读取，不能覆盖后续 Handoff |

### 11.3 旧 30/30 的明确解释

旧 ScreenCaptureProbe 中 GDI PrintWindow 和 Native BitBlt 各自把同步 Win32 调用返回 false 计为 dropped，并固定运行 samples=30；WGC 分支明确返回 NOT_MEASURED、Samples=0、DroppedFrames=0。故“Samples=30 / DroppedFrames=30”表示旧同步 capture backend 的调用失败计数，不表示 WGC 没有取得 frame、frame-pool overwrite、consumer 没 ACK 或真实游戏画面黑屏。V2-3 必须使用自己的定义：成功 WGC capture、capture/readback error、MMF bufferUnavailable、Engine/ACK failure 分开计数。

## 12. 接下来所有合理候选工作

以下是候选，不是本状态包替上层模型做出的最终路线选择。

| 候选 | 依赖 | 最小退出条件 |
|---|---|---|
| V2-3 WGC 纵向链 | 当前客户区满足 fixed-v1；真实目标 HWND；既有 WGC/MMF/Engine probe | 一次真实游戏帧完成 WGC → BGRA8 → MMF → FRAME_READY → read-only Engine → checksum/metadata → FRAME_ACK；保存一张真实游戏帧 |
| V2-3 producer/consumer 稳固化 | 首帧成功后的真实 metadata/ACK 结果 | sequence 单调、不覆盖未 ACK 槽、ACK 后可复用、明确 captured/published/dropped 定义 |
| V2-4 Native WebView2 | V2-3 稳定、Engine 业务 ready、UI 边界确定 | Native shell/HUD 生存性有独立证据，仍保持默认关闭 |
| V2-5 full-chain | V2-3、V2-4、真实业务入口和恢复边界 | 真实窗口到业务状态、history/export 的一条纵向最小链；不等于完整十四项通过 |
| production wiring | V2-3/4 明确、app/main 与 Native Host 所有权决策 | 有明确开关、回退路径、状态权威和隔离数据，不把 harness 直接替换正式入口 |
| 真实输入 | focus/identity/generation/ticket/freeze 全部稳定且用户明确授权 | 单独安全门、可随时禁用；之前没有真实 SendInput 证据，不能顺带打开 |
| OCR / warehouse quality | 稳定真实帧和 ROI 坐标、catalog authority | 针对真实缺口做局部证据；不借 WGC 首帧宣称整仓识别完成 |
| 完整拍卖 E2E | 真实 capture、OCR、身份、估值、history、输入和用户配合 | 真实一局/后续三局资格单独验收，winner/acquired/settlement 证据完整 |
| UI/UX | 正式状态模型和 production wiring | HUD/详情/summary/export 与同一事实源一致 |
| packaging/release | 稳定入口、依赖、默认关闭策略、真实边界说明 | 一个可复算候选包；没有发布就不写 release 完成 |

### 可并行与必须串行

- 可并行：V2-3 首帧 transport 工作与不依赖真实窗口的离线 Engine/协议整理；UI 设计和候选文档也可独立。
- 必须串行：真实 WGC 首帧 → 真实 Engine read/ACK → 业务 ready/vision → production wiring → 真实输入 → 完整一局 E2E。
- 不应并行：在 WGC/identity/focus 尚未稳定时开启真实输入、OCR 大规模调参或完整拍卖自动化。

## 13. 给 Astra 的规划问题

请基于以上真实状态重新从产品最终目标倒推，设计一条不重复已完成工作、不过度测试、尽快形成可日常使用版本的完整实施路线。

规划必须回答：

- 总体路线；
- phase 划分；
- 每个 phase 的明确目标；
- dependency；
- exit criteria；
- 哪些事情不要做；
- 哪些旧工作直接复用；
- 哪些阶段可以并行；
- 哪些阶段必须串行；
- 最短可用产品路径；
- 最终完整产品路径；
- 风险最高的 5 个点；
- 下一步第一刀应该是什么。

特别要求：把“真实观察安全门已完成”“回放 MMF 帧链已完成”“真实 WGC 首帧尚未完成”“完整业务产品仍 PARTIAL”作为四个不同事实处理；不要把 harness PASS 当 production PASS，也不要重新要求已经 CLOSED 的 A/B/C、V2-0、V2-1、focus gate 或同一份旧 evidence。

## 证据索引（高密度）

### Obsidian 当前主源

- 根 AGENTS.md
- 99-系统与后台/AI/所有项目通用工作规则.md
- 03-项目与工程/异环拍卖助手/README.md
- 03-项目与工程/异环拍卖助手/Handoff.md
- 03-项目与工程/异环拍卖助手/Decisions.md
- 03-项目与工程/异环拍卖助手/Feature Truth Matrix.md
- 03-项目与工程/异环拍卖助手/Feature Correctness Audit.md
- 03-项目与工程/异环拍卖助手/Architecture V2 Spike.md

### 仓库关键入口

- D:/yihuanpaimai/app/main.py
- D:/yihuanpaimai/core/vision_pipeline.py
- D:/yihuanpaimai/core/current_match.py
- D:/yihuanpaimai/core/canonical_history_store.py
- D:/yihuanpaimai/core/auction_brain.py
- D:/yihuanpaimai/core/live_shadow.py
- D:/yihuanpaimai/architecture/v2/contracts/
- D:/yihuanpaimai/architecture/v2/host/
- D:/yihuanpaimai/architecture/v2/input/
- D:/yihuanpaimai/architecture/v2/integration/

本文件到此为止；不进入 V2-4，不修改 Feature Truth Matrix，不 merge/tag/release。
