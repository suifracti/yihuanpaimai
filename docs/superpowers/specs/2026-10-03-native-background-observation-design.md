# Native 持续后台只读识别设计

日期：2026-10-03。状态：用户已明确“批准按此设计实施”；正式链路已接入，新增差异的最小离线检查通过。随后一次授权后台QA取得1张真实帧，第2次读回未满足请求后新帧条件，整体未通过。
来源：用户要求“加一个在后台也能采集”，并选择“接入正式助手的持续后台识别模式，先确认设计”。
基线：产品 v0.68-alpha，HEAD 7e98c93，保留当前全部 dirty/untracked 成果。

## 目标与方案

在现有正式助手增加显式“后台只读识别”选项：异环窗口仍存在、未隐藏/最小化且映射可靠时，可以失焦或被其他窗口覆盖，继续从该指定窗口客户区读取新帧，更新当前局观察和识别结果。
这是正式助手的持续观察能力；不能以只修改 build 下 QA 的前台检查代替交付。

推荐复用单一 Native WGC / Host / Engine / Main 管线，并为当前观察会话固定窗口模式。
不另建截图进程、截图轮询器或第二个识别管线。不采用整体删除 IsTargetForeground 条件的做法：该条件目前同时参与帧接收、建议、内部命令及仓库 SOURCE 资格，须按用途拆分。

## 用户操作与固定会话模式

- 原 Native profile 仍为 `native-readonly-v1`，继续报告 `inputActions=false`、`formalHistoryWriter=false`。不以新 profile 名绕过 Main 现有禁止游戏输入的判断。
- 配置拟用 `app.observationWindowMode`：`foreground` 默认、`background-readonly` 显式选择。Host 启动参数对应 `--observation-window-mode`，未知值拒绝。
- 主窗口现有识别状态/开始观察区域增加一个“后台只读识别”选项及实际模式状态。用户选择后点击现有开始/恢复入口；可以让游戏留在后台，不用助手抢前台。
- 模式在启动时固定，运行中不能热切换；需用户先停止再选择新模式并显式开始。不自动重启、恢复原租约或刷新结算预算。
- 默认前台模式保留现有失焦终止行为。后台模式只有失焦不终止观察，也不发送终止式 PAUSED。

## 采集资格与失效

共同要求：原 HWND、PID、进程实例与观察代次匹配；仅 `htgame.exe/UnrealWindow`；窗口可见、未最小化；客户区≤1920×1080；固定客户区映射可证明；会话未停止。
后台模式只免除“该窗口必须当前为前台”这一项，不假报 `isTargetForeground=true`。

复用 WgcWindowCapture 与新鲜映射 getter。目标或客户区失效、隐藏/最小化、尺寸/裁切关系变化、捕获失败、来源停滞或过期时按现有终止式 PAUSED/ERROR 结束，撤销 Main 观察/建议许可及 SOURCE，保留已写证据，需用户显式恢复。
不自动恢复窗口、不重绑另一 HWND、不缩放或重建映射继续，不调用屏幕权限申请/选择器或自动确认提示；出现权限拒绝即停止。新权限提示出现时停止现场验收，不规避或继续取帧。

后台业务 FRAME 需真实 `SystemRelativeTime` 来源时间严格递增，读回时来源年龄≤2秒且不晚于读回。
结果发布前再次核对同目标与映射；Main 的处理/建议许可按真实来源时间和既有31秒处理期限核对，接收迟到结果不能重新刷新同一原帧的有效期。
相同像素不增加独立身份/跨页支持，不降低现有确认门槛。没有新游戏内容时不能凭新合成时间声称内容更新。
独立 SOURCE 仍保留请求后新帧、≤2秒来源年龄及原有严格去重要求。

## Main 接线与控制边界

Host 新增仅供只读观察使用的目标资格；Main 将 `_native_target_instance` 的身份与前台要求拆开，按已确认的当前会话模式用于 FRAME、建议许可、异步回执、同局 DRAFT 与 SOURCE scope。
不能全局删除原前台限制。身份/会话/局/轮次/修订/序号及旧任务失效检查保留。

现有内部 `match.apply_control` 和 `warehouse.instance_decision` 可按同一后台只读目标资格运行，仍限原 allowlist；它们是助手/Engine 内部的人工事实和复核命令。
真实游戏输入仍由独立门禁限制，Native profile 继续禁止；后台模式不添加点击、滚轮、出价、交易、全局鼠标键盘或窗口激活。

## 本机事件与兼容

Main 的 launch 配置是模式权威。Host 在 STARTING/READY/FRAME 本机观察事件中明确回传窗口模式，并附真实来源时间；Main 核对与启动配置一致。
后台模式缺支持回执、未知模式或来源字段时拒绝，不能静默接受旧 Host 或退回其他截图方式。
默认前台模式兼容既有前台事件；`MMF/Named Pipe 1.0`、Engine FRAME 固定布局、冻结结算数学及业务字段不变。

## 仓库复核与数据

后台模式允许用户在普通 Main 中显式准备、确认、采页、完成或取消，复用现有 SOURCE/coordinator/intake，不要求新增 HUD 免激活模式。
SOURCE 资格必须仍有真实 SETTLEMENT、已存本局 DRAFT、实际 worker 序列/像素回执和当前 scope；后台普通帧不能伪造冻结结算。
只有原会话的只读模式允许后台 SOURCE；人工点击仍是一页一次，不能因开启持续识别而自动申请 SOURCE。

16原帧、首次 Host SETTLEMENT 起70秒绝对截止、单待请求/未ACK、Host128MiB失败预留、intake64MiB实际PNG、尺寸、去重及停止即时撤租约均保留。模式选择不延长截止或重置同局预算。
后台换局仍保存旧 DRAFT、拒绝退役局/旧 generation，迟到页不写新局；人工决定不被覆盖。正式历史及标签权限不扩展。

持续观察不新增逐帧原图保存或提高采集频率。后台会话的纯诊断日志采取有限保留，不能无限增长；只限定本次新后台会话的日志，不清理历史证据、原图、DRAFT 或 data 素材，也不增加备份体系。

## 实施范围与最小验证

主要涉及 `app/native_observation.py` 的启动模式；`NativeObservationService.cs` 的观察/控制资格及来源时间；`app/main.py` 的模式确认、目标资格和 Main 消费；现有主窗口的选项/状态；SOURCE 文案与同 scope 资格。
WgcWindowCapture 不另写捕获算法；WarehouseEvidenceLease 不放宽预算、停止或映射门禁。

批准后只验证新差异：同一失焦目标在默认模式拒绝、后台模式可沿真实 Main/Host 组件接受只读帧和显式内部/SOURCE 请求；同模式的错误实例/会话、最小化/映射失效/旧源及迟到结果拒绝，游戏输入始终不可达。扩展现有行为用例，不复制旧矩阵或用实现输出生成期望。
日志限额只需一次人工小额度检查，证明诊断留存有限且业务帧不因日志轮转丢失；不跑多小时长稳。

旧 3次/8秒/10秒 QA 的计数、截止及实际退出证据继续复用；为后台资格补一个针对性差分，不重跑旧包。
实机仍另等用户明确要求一次后台采帧，最多3次显式调用、失败也计数、8秒停止工作、10秒核实退出；条件不符或权限提示即停止。后台 WGC、新场景识别、生产 SOURCE 与完整拍卖分别报告。

## 文档依据与局限

[CreateForWindow](https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow) 绑定指定 HWND，未规定必须前台；[微软 WGC 遮挡说明](https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/ui-automation) 支持被遮挡的窗口表面。
[SystemRelativeTime](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime?view=winrt-26100) 是合成器渲染的 QPC 时刻；它本身不能证明游戏内容变化。
这些资料不能保证异环失焦后一定继续渲染；最小化、隐藏或游戏暂停渲染不属于本模式成功承诺，实际仍由新帧与映射证据判定。

## 当前交付与证据

产品标记仍为 v0.68-alpha，HEAD 仍为 7e98c93；源码未提交，原 dirty/untracked 成果保留。后台模式实施及下述唯一现场采集使用 `build/native-observation/WgcLiveHarness.exe`，当时 DLL SHA256 为 `5bfa8f6eae9954e6084f00f8642b60db0a9a288d59d80f3f2899e52e64306d75`；随后请求帧选择修复的当前产物与验证另见末节。未重新打包发布。

主窗口已有默认关闭的“后台只读识别”；运行中不可更改，选择不触发自动启动或重启。后台 STARTING 必须回报模式，READY 必须确认目标并冻结身份，FRAME 继续核对模式、实例及源时间。缺少支持时发送 `native_stop`，不会默退前台或伪报 foreground。过期后台观察也不能继续发内部修改或打开仓库来源资格。

后台新会话的 Bridge 四种诊断文本各8MiB，Host Trace 8MiB，Engine 两种诊断文本各8MiB，Main诊断8MiB，合计最多64MiB；大行可舍弃、满额只覆盖本会话对应诊断文本。原图、SOURCE、DRAFT、历史及旧会话文件不由此限额清理。Bridge 诊断写盘不阻断业务回调。

- Host 本次编译0警告0错误：[build日志](../../../build/native-background-20261003/host-build.log)。
- 实际 Main 接收/内部资格的4项定向行为检查通过：[结果](../../../build/native-background-20261003/main-behavior.json)。失焦差分、Host确认、错误实例/会话/来源、源期限、输入禁用、默认关闭及运行中拒绝切换均为隔离假帧/假时钟证据。
- 实际编译 Host 的17项纯策略和 TraceLog 小限额断言通过：[结果](../../../build/native-background-20261003/policy-check-result.json)。客户区查询不可用的纯反例不能冒充新鲜映射全链实测。
- Bridge 假启动参数、日志舍弃时3个业务回调仍到达、Bridge与Engine小限额留存通过：[结果](../../../build/native-background-20261003/bridge-diagnostics-check.json)。其中3个回调均为假 FRAME，实际启动进程/查询窗口/WGC均为0。
- 有界 QA 后台纯资格入口通过：[结果](../../../build/warehouse-recognition-20261002/bounded-wgc-qa/eligibility-e4beb6f719/controller-result.json)。0显式取帧/0接受，真实WGC未加载，实际子进程退出340.519ms；Worker编译0警告0错误。旧 `offline-68a10fb66b` 的计数、截止和退出矩阵未重跑；新增模式不改该控制循环，旧证据继续用于其原范围。

Python相关入口与前端脚本语法通过。后台模式实施阶段 WgcCapture 与 WarehouseEvidenceLease 保持此前checkpoint的源码哈希；原停止即时撤销、映射反例及正常对照的旧证据保留。随后仅 WgcCapture 新增请求帧选择入口，见末节；WarehouseEvidenceLease 未改，不重复运行旧矩阵。

实施阶段实际WGC尝试/接受为0；此前 `live-75299687b3` 因前台资格拒绝、0尝试/0接受的事实保留。用户随后明确“准备好，后台采帧一次”，最新 [live-ec83924c9e结果](../../../build/warehouse-recognition-20261002/bounded-wgc-qa/live-ec83924c9e/controller-result.json) 固定异环PID17568/HWND11537932/FILETIME134354304237487801，在非前台状态2次显式尝试、2次读回，保存并接受1张1920×1080真实客户区帧。身份与各新鲜映射检查通过，首帧来源270851607582800ns，比请求晚1.3599ms，读回帧龄21.7936ms。

第2帧来源比本次请求早13.5739ms，被 `readback:source-not-after-request` 拒绝并结束；其来源比第1帧递增38.2353ms，不能把此拒绝直接描述成游戏停帧。实际1336.563ms确认退出，3次/8秒/10秒限制满足，无补采。整体passed=false，已有单帧后台WGC证据不能提升为完整有界验收通过。

唯一接受帧实际是拍卖大厅，未见仓库网格/滚动条；仓库识别未执行，物品候选数和总数不作推断。正式助手持续后台观察、生产SOURCE租约、仓库识别、HUD免激活与完整拍卖流程仍未通过实机验收。本次不改采集算法、正式历史或标签，不输入/激活游戏，不采桌面，不重跑旧矩阵。

下一步依据真实拒绝处理请求后新帧选择问题；这次授权已用完，当前不补采。后续仓库识别还需用户手动停在拍卖结束后的稳定结算仓库页并另明确授权一次采帧：右侧网格和滚动条完整可见、鼠标移开、窗口未最小化、客户区不超过1920×1080。允许失焦/覆盖，不由助手改变前台；3次/8秒/10秒边界和异常即停仍保留。

## 请求后新帧选择修复

用户本轮授权仅定位、最小修复和定向离线验证，明确禁止再采游戏。旧现场结果仍为2次尝试/1张接受，第2次读回旧帧即停止，整体失败；不重写现场证据或降低新鲜度门槛。

### 帧池、时间与等待的关系

原 WGC 使用2缓冲的 `CreateFreeThreaded` 帧池，`FrameArrived` 只对一个 `AutoResetEvent` 发信号。`Capture` 原先先 `WaitOne`，再取队列下一帧。事件可在请求前已处于有信号状态，多次到帧也可能合并为一次唤醒；等待成功不能证明随后取出的帧晚于本次请求。[微软事件说明](https://learn.microsoft.com/en-us/dotnet/api/system.threading.autoresetevent)、[TryGetNextFrame 合同](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframepool.trygetnextframe?view=winrt-28000)

worker 的请求时间来自 `ProtocolClock.NowNs()`，基于 QPC；WGC 的 `SystemRelativeTime.Ticks * 100` 也是来源 QPC 纳秒。[微软来源时钟说明](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime?view=winrt-26100) 旧现场第2帧来源比第1帧晚38.2353ms，却比第2次请求早13.5739ms；这与队列中已有旧帧相符，不能据此断言游戏停帧或改用接收时间放行。

### 最小实现

- `RequestFrameSelector.cs`：固定请求时间，先取队列并检查来源；来源≤请求的未读回帧立即释放，继续检查队列；队列空才最多50ms一段等待。无效/未来来源、停止或截止直接失败，持有帧在异常路径释放。事件只提示可能有帧，不重置事件，也不依赖一次信号对应一帧。
- `WgcCapture.cs`：新增 `CaptureAfterRequest(timeoutMs, requestNs, absoluteWorkDeadlineNs, stopped)`；截止固定为 `min(requestNs + timeoutMs, absoluteWorkDeadlineNs)`，包含选择和读回前后检查。原读回映射/尺寸校验复用，普通持续 `Capture/FRAME` 不改变选择策略，生产 SOURCE/租约也未切换入口。
- 独立 QA `Worker.cs`：原始请求时间和总工作截止传给新入口，不兼容回退到旧 Capture。外层仍先扣尝试、最多3次、失败结束，读回后的来源必须严格晚于请求且递增；映射、新鲜度、重复像素和停止检查保留。`run_qa.py` 只增加读回前已释放队列帧的独立诊断字段，不改原控制循环。

排队帧元数据的检查/释放属于同一次显式 Capture 内的选择，不产生像素读回、候选或额外显式 Capture；按原设计分别报告尝试、读回、队列丢弃和接受数。截止不因排队帧释放、唤醒或日志重置。8秒禁止继续工作，父进程 Job 的8秒停止/10秒核实实际退出合同不变；不能保证 COM/GPU 调用可由线程内检查即时中断，也不能用发出终止请求代替退出证据。

### 定向验证与修改归属

新帧选择器已在实际编译 Host 上做一次纯托管定向验证，14项通过，覆盖合并信号、旧队列帧释放、请求/工作固定截止、停止和异常释放：[结果](../../../build/native-background-20261003/request-frame-selection/result.json)。Host 与 QA Worker 编译均0警告0错误：[Host日志](../../../build/native-background-20261003/request-frame-selection-host-build.log)、[Worker日志](../../../build/native-background-20261003/request-frame-selection-worker-build.log)。只检查 Python controller 语法；旧次数/截止/Job矩阵和后台策略矩阵不重跑。

当前 Host DLL SHA256为 `facdf391057219d7953541d29f35921d65898724c4e11848a00aafe1a1e6a8a4`。本轮游戏窗口查询、实际WGC尝试、真实帧均为0；纯托管帧不能作为实机通过证据。当前新入口的真实WGC效果、持续正式助手/SOURCE、仓库识别和完整拍卖仍未验证，需另一次明确实机授权。

采集对话没有修改 `core/warehouse_vision.py` 或相关算法测试。接手时这些文件已含未提交成果，已与“推进局内仓库离线识别”协调：该对话独占拆件算法及其测试修改，采集对话负责 Host/WGC/QA；其交付应只包含相对接手脏基线的新差异，不能覆盖原成果。采集与算法仍通过原仓库图像 API/槽位/裁图合同衔接，未改变识别阈值或物品身份规则。

`build/item_reference_audit_20261003` 首批只读核对时为候选目录25条、差异53条、证据89条，状态 `CANDIDATES_ONLY_NOT_APPLIED`。这些是资料记录数，不能当准确物品总数；后续明确授权的逐项裁定整合另见下节，不把首批新卡候选批量导入主表。

## 后续逐项资料整合与验收顺序

2026-10-03 用户明确授权读取 `adjudication/handoff_to_main.txt` 和 `decisions.json`，先列差异再按每项允许范围整合。[拟整合清单](../../../build/item_reference_audit_20261003/integration/planned_changes.md) 已先生成并展示，随后只应用15项几何裁定去重后的14主表行，以及M17、M41、R215的明确源卡尺寸，共34个字段；无梦果核C85的旧2×2/3格L形仍待确认、保持原样。

8项源文字/候选显示纠正仅整合为 [build候选显示层](../../../build/item_reference_audit_20261003/integration/source_display_candidates.json)，涉及19个定位字段，未由生产加载。`sourceTargetFile/sourceTargetPointer` 是原记录出处，不是写生产名称的许可；生产名称迁移、ID、别名、价格和人工标签均未改变。其余4项待确认、1项暂不采纳保留；原裁定阶段的“未应用”文件和证据不重写，不扩大收集或再次转交离线识别对话。

一次数据差异与实际几何加载器检查通过：[整合结果](../../../build/item_reference_audit_20261003/integration/integration_result.json)。14行均可进入几何候选，身份仍为 `CANDIDATE_ONLY`；无梦果核源绑定1×1与旧L档不合并。生产三个JSON的语义差异严格限定上述几何字段，visual目录与solver独立快照字节未变。没有运行图片识别、游戏采集或旧矩阵，拆件算法继续由“推进局内仓库离线识别”独占。

下一次用户另明确授权后，先对新请求帧入口做一次原3次/8秒/10秒预算内的真实验证；通过后才说明生产 FRAME/SOURCE 的接入方案、涉及文件及验证项。独立QA通过不代表生产已接入，目前两个生产入口仍未切换到新选择器。本轮不自动采帧。

## 候选几何隔离与算法增量整合：当前结果

上述资料应用是此前阶段的历史记录。随后只读消费路径核对发现：`CANDIDATE_ONLY` 是身份输出状态，不能阻止主表尺寸进入局内匹配、结算候选、几何索引或评分；正式v2布局还读取源卡manifest。用户已明确批准先隔离候选几何，再整合冻结算法，两步分别留证据。

第一步：依据 `planned_changes.json` 逐字段核对，34字段均等于本轮候选改值，无冲突；仅恢复这些字段的整合前值，其余字段和原有成果保留。[逐字段结果](../../../build/item_reference_audit_20261003/integration/geometry_isolation_result.json) 与 [正式消费入口定向检查](../../../build/item_reference_audit_20261003/integration/geometry_isolation_checks.json) 分开记录。三个正式资料文件字节均恢复到裁定前基线，既有独立视觉参考保留；不能为了恢复主表而抹去此前已验证的视觉参考几何。

候选保留于 [独立覆盖文件](../../../build/item_reference_audit_20261003/integration/source_geometry_candidates.json)。build下 `geometry_isolation.py offline` 必须显式提供覆盖、选择配置和build输出目录；配置须有实验ID、观察范围、profileId及精确源路径/SHA/bbox。无配置、错误源绑定或裸catalogId均拒绝。只把已选择profile应用到离线文档副本，不改正式文件或缓存；生产没有引用此入口，旧几何apply入口已停用。原8项显示纠字仍仅在build候选显示层，4待确认/1暂不采纳和C85旧L档保持。

五条消费路径仅作离线读取/筛选核对，没有运行游戏或process_frame。首次检查在物理注册表末端的路径大小写比较出现测量错误，保留失败日志；只修正并补查物理校验与覆盖读取，未重复前面的入口检查。候选使用资料来自后续 `adjudication/usage/candidate_usage_profiles.json`，不把声明性profile误当已经隔离的生产patch。

第二步：重新检查主目录dirty基线、冻结worktree、所继承测试和夹具，均符合交接；新增5文件不存在目标冲突。只应用相对dirty基线的 `warehouse-vision-incremental.patch`，没有使用相对HEAD整包diff。当前主目录算法 SHA256为 `4a73a396dc9e07b9f78e1d20863ba6a9d352200e1ec65b26f6e291f9e5bc5014`；公开API及身份门槛保持。[主目录整合结果](../../../build/offline-right-warehouse-20261003/main-integration-result.json) 记录继承文件保留情况，新增2个整合用例通过：[日志](../../../build/offline-right-warehouse-20261003/main-integration-focused-check.log)。仅使用既有护甲fixture及其半尺寸/右裁控制，不重复旧完整矩阵或两张已使用保留图。

项链/卡丁车拆件、57px纵向周期、品质块身份和真实占格未知仍保留，不能因护甲反例修复宣称仓库全部可用。新采集选择器仍为离线通过、真实未验，生产 FRAME/SOURCE 未接入。本轮实际游戏采帧0，未提交、发布或归档；冻结worktree和旧证据保留，后续算法仍由“推进局内仓库离线识别”按版本分工处理。


## 第二轮算法增量：主目录整合结果

本节更新上一节第一轮算法的当前状态，第一轮结果及冻结交付继续保留历史含义。第二轮仅应用相对第一轮冻结算法 `4a73a396…` 的独立增量，未使用相对HEAD的全部差异。当前算法 SHA256 为 `ff67a1224533f3c27c2cfeddb2494474c3a690ec43d0ac943f40a7ef80bf35c4`，新增行为用例、PNG夹具、来源说明和交付报告共4文件；两份仅支持旧4a基线的历史诊断工具没有整合。

核对当前基线、增量及目标路径后无内容冲突；ROI与visual资料字节哈希不同仅因换行格式，归一化文本一致，visual的JSON内容也一致，这两个文件未被替换。34个候选几何字段仍逐项等于before，正式资料、候选覆盖和第一轮继承文件保持。结果见 [第二轮主目录整合证据](../../../build/offline-right-warehouse-round2-20261003/main-integration-result.json)。

仅新增一次主目录已知项链/车夹具读取及几何检查，通过：[日志](../../../build/offline-right-warehouse-round2-20261003/main-integration-focused-check.log)。其余四个定向测试方法及六个相关离线输入复用第二轮冻结证据，没有重跑旧矩阵；六输入包含同源派生，独立未见图仍为0。

已知f564图中项链外观2×2框与车外观4×4框恢复，周期由56×57变为56×56；两框相对目视预期的X仍偏右2px，不能宣称像素精确或新场景全部修复。六品质块身份、数量及底下真实占格仍未知，结算35组件没有逐件全图真值，也没有新时序验收；候选/组件数均不是准确物品数。

新采集选择器仍为离线通过、真实未验，生产 FRAME/SOURCE 未切换到该选择器；本轮新游戏帧0，完整拍卖未验证。没有修改Host/WGC、生产主表、人工标签或正式历史，未提交、发布或归档。

## 后续真实窗口与项目自动收页：当前边界

本节更新上述冻结阶段的状态，旧交付保留历史含义。live-f357c8c232 对同一个后台异环1920×1080客户区显式尝试3次、接受2张新原帧、核实退出1.22716秒；第3次来源时间晚于查询后QPC而拒绝，整体未通过。两张是同一结算场景，不能计两个独立样本。原帧与一次隔离识别保留；白色1×2/1×1误合并随后由离线任务修复，以相对ff67增量整合到eef9968a…。对应主目录真实图单例通过；周期56×56，其他30框不变，物品身份、数量、全场准确率及X偏移仍未知或未解决。

用户明确批准 [Native自动翻页接入设计](2026-10-03-native-warehouse-auto-scroll-design.md)。现在 SOURCE 请求在候选Host中调用新选择器，显式“采集完整仓库”独立租约可发送限定窗口的滚动消息；普通持续 FRAME 无请求时仍使用原入口。此为代码接入和离线证据，不是生产实机通过。窗口消息不激活游戏、不移动系统鼠标、不使用全局输入，送达不证明游戏接受；无进展、停止、目标/映射改变及预算截止均保留部分材料并停止。新候选Host编译0警告0错误，新生产入口尚未读游戏或发送滚动，完整拍卖未验证。后续实机需另明确授权，先以原3/8/10预算定位时钟拒绝，不放宽门槛或重复旧矩阵。
