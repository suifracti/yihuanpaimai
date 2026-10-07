# Native自动观察：交付时序合同设计（待确认）

本轮只审查和设计。建议实施 `wgc-delivery-v1`，目标是从大厅一次启动，持续观察对局，
自动识别稳定结算并收页，返回后由既有生命周期进入下一局。它是完整自动流程的采集合同，
不是仅存证据模式；没有实施或取得新实机通过。原严格合同保留。

## 1. 当前门禁追溯

| 用途 | 当前入口／判断 | 真正能证明／不能证明 |
|---|---|---|
| 指定窗口身份 | `BackgroundObservationPolicy.IsSameObservationTarget/MatchesObservationTargetIdentity`；`WgcCapture.ReadBack`；`WarehouseEvidenceLease.SameLease/UpdateContext` | HWND、PID、创建令牌、监控generation固定；来源和裁切来自该窗口。不能单独证明游戏处于结算 |
| 局次／回调归属 | `app/main.py:_native_observation_event/_maybe_trigger_native_warehouse_capture`、CurrentMatch及pipeline代际；Engine `_retire_match_for_lobby`；SOURCE会话/record/generation/nonce | 结果属于已建立的局代际、旧回调拒绝。局代际还必须由视觉生命周期建立，不能用窗口PID代替 |
| 请求后来源、清除旧池帧 | `RequestFrameSelector.Select`：`source > request`，正数，`source <= comparison`；`WgcCapture.CaptureAfterRequest`固定截止 | 以来源QPC为可信时钟时排除请求前合成帧。不是应用内容提交证明；未来反例使这个假设不能支撑可用性 |
| 读回／队列近期 | `ContinuousWgcCapture.Validate`；Host读取及出队前 `BackgroundReadbackRejection`：递增、非未来、年龄≤2s | 原来主要以来源年龄限制积压，并非纯本地排队时间；序号递增并不等于图像新渲染 |
| 慢识别后的发布与观察租约 | Host `BackgroundPublicationRejection/PrepareObservationPublication`：≤31s；Main `_native_source_frame_rejection/_native_background_source_current/_native_accept_observation_locked`及watchdog | 限制结果使用时间，核对序号/目标/事实修订；31s源于30s SendFrame期限，不是来源时钟误差容差 |
| 原页保存及滚动授权 | `WarehouseEvidenceLease.Request/TryPublish/ScrollDown`；Python `_accept_source/_source_is_current`、DUPLICATE_PAGE校验 | 原来源晚于请求、递增、年龄≤2s；还要求frame/worker同序号同hash、映射、nonce、租约及保存ACK。源码仍在SendFrame完整结果之后TryPublish，保存与慢OCR有耦合 |
| 应用内容更新 | 既有场景、轮次、当前帧OCR、仓库视口观察；没有独立的游戏内容提交事件 | 场景/轮次/视口变化可作为业务推进证据。时间戳递增、出池、回调、像素不同都不能单独证明游戏已提交新内容 |
| 页面稳定 | `NativeWarehouseAutoCapture._page(WAIT_STABLE)`和DUPLICATE_PAGE支持：250ms间隔、相同/已有stationary proof、可判滑块和纹理 | 稳定的是被观察的相同视口，不是完整仓库、独立物品身份场景或实时渲染证明 |
| 翻页确实发生 | `_page(WAIT_MOVED)`：`_scrollbar_progress`实际向下 + `align_warehouse_segments`向下图像位移和重叠 | 只在轨道/滑块尺寸/映射一致且两项均有证据时成立。窗口消息送达不能证明滚动 |
| 物品身份／数量 | 既有候选、逐实例确认、品质/占格边界、`warehouse_physical_ledger`、`warehouse_coverage_ledger` | 资料目录/框数不能确定身份或总数；局内手动滚动不能用视口坐标直接累计 |
| 价格及正式记账 | `vision_pipeline._update_settlement_stability`：终值外观、成交/总值/收益稳定签名及既有冻结/归档；Engine `_persist_history`、正式确认入口 | 合格来源不是冻结条件，冻结不是原页捕获条件。页面稳定不能替代账单终值，提前保存不提前记账 |

“来源时间不得晚于当前QPC”的依据分别是：

- **官方定义**：[SystemRelativeTime](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime?view=winrt-26100)为合成器渲染帧的QPC时间。所查文档没有getter时当前QPC上界的明文保证，也没有未来值合法性的保证。
- **原实现假设**：把该值当作已完成来源事件时间，用于请求后、未来拒绝和年龄运算；`RequestFrameSelector`、后台策略及SOURCE/GUI将此假设具体化。
- **用户明确约束**：后续多轮已明确要求保留严格门禁、不接受未来/旧帧、不等追上、不设容差。它是当前严格模式的已授权合同，不能因发现实现假设就直接删除。本次用户要求审查并提出新合同；仍须确认后才实施。

游戏及自建DXGI同帧六路一致反例，已排除这些样本的投影/ABI差异和换算错误。
自建第1次“来源晚于请求、内容仍为编号0”，是来源事件早于编号1提交的正常因果；
静止画面或尚未提交新内容都不应强制改变像素。原严格模式也不保证应用内容最新。

## 2. 推荐合同：近期交付 + 独立业务证据

新增独立启动选择 `captureFreshnessPolicy=wgc-delivery-v1`，原选择为 `wgc-origin-strict-v1`。
两个选择都使用现有HWND WGC、独占采集线程、最多一张待处理最新帧、串行Engine和现有生命周期。
这不是另一个对局状态机，也不要求每局点击或武装。

### 2.1 请求边界与有界清池

1. WGC owner收到请求，冻结本地QPC请求及原截止；停止/窗口/映射检查保持。
2. 丢弃请求前的pending latest，记录当时捕获序号；在同一owner线程清除池中已有帧。
   当前池为2缓冲：清池最多3次TryGetNextFrame（含确认null的一次）；每个非空均释放。
   第3次仍非空则该请求 `POOL_BOUNDARY_UNPROVEN`，不无限清池、不重发请求。
3. 记录一次null及其本地时刻为“该池在边界时为空”的证明。之后取得的下一非空帧才作为候选。
   它证明边界后的池交付，**不证明边界后渲染或应用提交**。
4. FrameArrived仅作唤醒提示；不以事件次数配对帧，也不把旧AutoResetEvent信号当作新帧。
   等待切片仍≤50ms并受原绝对期限限制；迟到、取消、身份/映射变更均释放并拒绝。
5. 每次交付赋予 `(observationSessionId,poolEpoch,acquisitionSequence)` 的捕获ID，记录
   request/dequeue前后/getter前后/原比较/readback前后/传输/处理/保存时刻、frequency和raw ticks。
   捕获ID是owner分配的交付身份，不是全局独立场景ID；COM地址可能复用，不用它替代ID。

[TryGetNextFrame的null合同](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframepool.trygetnextframe?view=winrt-26100)支撑池空边界。
[FrameArrived](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframepool.framearrived?view=winrt-26100)描述帧入池通知，
没有给予该通知“游戏已新提交”的含义。

### 2.2 原始来源及资格分开

- 原始 `SystemRelativeTime` Duration、换算值和**首次冻结比较时**的状态始终保留。
  状态至少区分 `CONSISTENT_AT_READ/FUTURE_AT_READ/NONPOSITIVE/STALLED_OR_REORDERED/CHANGED_ON_SAME_FRAME`。
  `CONSISTENT_AT_READ`也不升级成“官方保证真实显示完成”。未来标记不会被后续GPU读回消除。
- 分别输出 `originStrictQualified`、`deliveryQualified`、`sourceMarkerProgress` 和视觉业务proof引用。
  未来帧 `originStrictQualified=false`；在新合同下可能 `deliveryQualified=true`，
  这是明确不同的资格，不把未知来源年龄写成严格通过，也不把负数年龄clamp成0。
- 自动动作／正式数据还要求来源getter在同帧一致、正值，并相对本池已消费/清除的最高来源marker推进。
  这里只将原值作为额外的**生产者顺序marker**，不与request/current QPC作绝对年龄运算。
  marker递增不是官方业务新鲜度保证；相同值可保留静止观察，但不当作新稳定支持或新页面。
  值后退、同帧变化或无法取得时停止动作资格，不能靠另取较小值放行。
- `deliveryAgeMs = localNow - readbackCompleted`，`queueAgeMs`、`processingLagMs`独立。
  最长2s的读回/待处理使用限制及31s结果上限沿用原有数值，但重新明确为**本地工作/使用期限**，
  不是对异常來源的容差；所有期限写明起点，SOURCE仍用原5s请求期限及绝对70s总期限。
  负本地间隔、频率/换算不一致、时序颠倒或资格缺失直接拒绝。
- MMF `captureTimestampNs`仍表示原有本地读回时刻；不写入替换来源值，不改冻结MMF布局。
  新模式不沿用旧 `freshnessMs` 的来源年龄含义，明确发送 `deliveryAgeMs/resultLagMs`。

**不能排除**：WGC/DWM/驱动上游迟交、缓存内容再次交付、游戏停更而表面仍可被合成、
后台停止渲染、顺序重放旧画面，以及与真实扫描显示之间的延迟。池空边界只清掉可见的本地池，
不清除不可见的上游队列。本地刚读到不能叫刚渲染。
新合同主要防程序自身排队和串局，并以业务推进校验降低缓存风险；没有上游绝对渲染年龄的硬保证。

### 2.3 生命周期和内容推进

复用本局DRAFT/结算/离开/下一局状态，不用单个“SETTLEMENT”标签凭空建立当前局。
从大厅启动后持续处理实际本帧场景、对局/轮次及已有计时/报价等视觉观察；
建立当前局后，才允许本局 `IN_AUCTION -> SETTLEMENT` 的自动收页。
计时、报价或手动视口变化可支持内容推进，但不要求每帧像素改变。
只接受本帧直接读到的证据，不能使用pipeline缓存timer、previous_scene或LATEST_PAYLOAD补动作资格。
缺少明确当前局或未观察到进入本局的有效链时可继续观察，自动收页不启动，记录缺失原因；
不能为了完成率把启动时孤立的旧结算画面分配成新局。

现有 `process_early_warehouse_frame`在部分分支依赖previous_scene；新模式的动作判断必须额外
核对当前原页结算标题、网格、顶端，不能只放行这个继承标签。
这会产生拒绝/部分结果，不以后台模式猜测画面仍然有效。

跨局由现有 `_retire_match_for_lobby/begin_next_match`和局代际回执完成。
代际确认后owner撤销旧SOURCE和最新待处理资格，记录新的清池边界；不把旧页重绑新record。
过渡帧用原transport sequence与既有Engine转换回执对应；未收到新作用域回执的原页不先记到下一局。
已取出的旧局图像/识别任务保留原捕获ID，结果提交前再次校验代际，旧回调不得复活。
真实场景离开结算会即时撤销收页动作租约；这不是另一套生命周期。

## 3. 各环节能否使用未来来源帧

此表的“可用”都要求**新模式已明确选择**，窗口、映射、原帧身份和本地期限合格。
任何地方都不将它称为严格来源通过。

| 环节 | 新合同的使用条件 | 不足时 |
|---|---|---|
| 持续观察／生命周期 | delivery proof完整，捕获ID新、序号有序，当前目标/会话正确；实际本帧场景及现有局代际转换可核对 | 不提交迟到当前状态；保留最后成功时间并显示空档。没有新交付到原期限即暂停/停止，不静默重启 |
| 网格／物品框等几何候选 | 可从该原帧做视口内候选，记录capturePolicy及源异常；不改物品资料主表或人工标签 | 纹理/网格/品质块未知保留；未证明跨视口对应不累计数量或总价 |
| 保存原页 | 当前SOURCE作用域及边界成立，独占frame读回，原像素/hash绑定，保存前后目标/映射/停止/截止校验 | 原图保留但标CANDIDATE/REJECTED，不能直接算稳定页；保存失败/取消不发布SOURCE |
| 稳定页／重复支持 | 两次不同合格交付ID、两个独立请求边界、来源marker推进；至少既有250ms的本地观察间隔；结算标题和相同视口/滑块，已有stationary proof | 同一个ID或仅重用旧文件不支持稳定；静止像素允许，身份独立场景数不增加 |
| 自动开始与每次滚动 | 本局一次+上述场景链+同帧结算/仓库/TOP或NO_SCROLL；先保存、稳定、ACK；最新交付≤2s且scene/仓库关键ROI与授权页仍相符；作用域未退役 | 不明确就不发消息，保留部分结果；用户局内手动滚动不启动自动翻页 |
| 滚动效果及继续 | 滚后请求边界在消息返回之后，捕获ID新；图像向下位移/重叠+滑块向下变化均成立，再做稳定验证 | 相同页、仅ACK、单项变化、滑块UNKNOWN、方向相反均结束；BOTTOM/NO_SCROLL与无进展分别报告 |
| 正式物品身份 | 页面业务proof及作用域合格后，仍走既有逐实例图像/名称/品质/占格和身份确认条件，结果绑定原图和捕获ID | 不能以来源异常的新合同替代身份确认；候选目录不自动变身份，品质未知继续未知 |
| 数量／物品价格 | 确认实例去重、物理布局/重叠和覆盖账本成立；已确认部分可以明确显示，但不补未知；单页有效证据保留 | partial不宣称全仓数量/总价，框数和候选数不作总数 |
| 成交/总值/收益及正式历史 | 本局结算业务证据合格，原终值外观/稳定金额签名/冻结/归档条件全部成立；同一capture ID最多参加一次稳定计数；保留新policy出处 | 账单未冻结的提前原页仅为本局材料。异常/迟到或作用域不明不记账，不伪造冻结、身份或金额 |

“正式可用”是确认后的新业务合同：delivery + 当前局证据 + 页/身份/账单资格的组合。
不是 `originTimingUnknown => pass`；必须有每项正面proof及明确policy。
保存页可在收页结束后识别，原页的期限在取得/保存时验证，不因离线处理晚了而改写其捕获时间。
慢OCR输出只在当前相同局/轮次/视口及相关ROI仍有新的合格支持时成为当前建议；
不相关或已退出的结果是该局历史观察。后续支持引用新的捕获ID，不更新旧帧时间戳或重复增加计数。

自动滚动前复用**已经在持续采集中的最新交付**核对scene/仓库固定ROI hash及资格；
只保存最新ROI摘要，不额外持有一张BGRA，也不增加“免费”显式取帧。
来源支持页照旧消耗既有保存/请求预算。若最新ROI已变或不可证明，则不滚动。
从视觉核对到实际窗口消息之间仍有不可原子消除的竞态；原严格模式也存在此间隔。
停止令牌、当前窗口及映射在send前再检查，不能承诺原子锁住游戏场景。

## 4. SOURCE从慢识别中解耦，保留所有权

目前Host先SendFrame等完整PERCEPTION_RESULT，再拿worker hash执行TryPublish；
4.68s识别可能让2s原页资格过期。只替换选择器不能完成产品目标。

新模式SOURCE使用 `native-warehouse-source.v2`：由当前租约向原WGC owner发有界请求，
先取得合格交付、复制出该活帧的客户区不可变像素、在期限内保存，再向同一Python收页协调器回执。
该v2原页资格以captureId、lease/nonce/作用域、delivery proof、像素/BMP双hash及写盘前后复核为依据，
**不虚构worker确认，不等待完整OCR**。旧v1严格路径继续要求原worker绑定。
后续识别必须从该已保存原页读取并核对hash，将结果关联该captureId/旧局scope，不能用另一张FRAME补hash或身份。
原页→稳定/滑块→窗口滚动在原协调器内，逐物品识别在收页结束后；不占结算收页时间。
普通FRAME仍串行处理、使用现有Engine queue和MMF ACK释放；SOURCE只仲裁owner，不抢正在读取的MMF槽。

所有权仍为：WGC活帧在owner读回完成后释放；pending latest最多1张，替换丢弃；
业务处理图像独立不可变；MMF槽在正确ACK前不覆盖；SOURCE保存时持有该不可变像素，写盘后释放。
沿用4份私有BGRA上限及原字节上限；新增proof/ROI摘要有界，不增全帧长队列或无限录像。
阻塞GPU/IO的停止仍需现有进程退出核实及不确认提示，不能承诺可取消API可强行中断任意驱动调用。

Engine必须在提交事实之前知道所选合同：
启动元数据冻结policy；每FRAME以captureId/transport sequence/像素hash绑定有界proof。
优先保持MMF布局：Host在发布槽前原子写该槽的proof sidecar（最多2份，单份≤16KiB），
Engine在复制槽及发ACK前一起读取、核对并复制proof；ACK之后才可复用该槽的sidecar。
不存在proof、模式不匹配、seq/hash不匹配或本地排队超期时，不能进入正式事实处理。
这项旁路合同需要Host/Engine同时确认能力；旧Engine不支持就拒绝启动，不默默缺省。
即便Host在后续发布时发现失效，也不能只让GUI拒绝却保留Engine已经提交的不合格事实。
实现时把提交前代际/取消检查沿用到该proof，不改变既有对局转换逻辑。

## 5. 模式隔离、启动和停止

- 默认仍为原严格模式。新模式启动前显式选择一次；READY确认policy、协议版本、候选身份和目标，运行中不可切换。
  windowMode与capturePolicy独立：后台只读本身不输入；结算自动收页选项仅授权指定窗口WM_MOUSEWHEEL。
- 旧 `RequestFrameSelector`、严格策略及SOURCE v1不删除或改语义。
  新模式独立selection/policy/proof校验，缺能力/缺proof停止；严格模式失败不自动降级。
- 主目录继续使用同一Native启动入口，`max-frames=0`既有持续观察，不沿用QA的有限帧数。
  120ms间隔是采集调度目标，不承诺OCR每120ms完成；模型/配置预备完成后才显示可开始。
  只保留既有选定原帧/情报证据和有界结算页，不保存每个采集帧；短暂情报可能被latest策略跳过，必须报告观察空档。
- 开始观察后大厅→对局→结算自动一次→保留完整或partial材料→返回/下一局，沿用本局已尝试落盘。
  单次≤16张来源、≤32次来源请求、绝对70s（从本局首次有效结算观察起，任何请求不重置）；
  原RAW128MiB/PNG64MiB及停止条件保留，支持帧也按既有规则计预算。
- “停止当前收页”撤销当前SOURCE，本局不重试，持续只读观察下一局；
  “关闭结算自动收页”撤销当前收页并禁止以后自动触发；“停止观察”立即撤销全部动作和回调资格。
  Host/Engine退出立即显示原因、最后成功观察时刻、当前局和部分材料，不静默重启。
- 回退：停止当前观察和输入租约，保留旧局证据，选择原严格模式后由用户正常开始新会话。
  新旧模式的证据不能冒充相同资格；在新证据索引/处理记录附policy和proof引用，原正式物品/账单schema不顺带重构。

## 6. 最小修改范围（确认后实施）

| 范围 | 文件及增量 |
|---|---|
| 有界交付选择与proof | 新 `architecture/v2/host/wgc_live_harness/DeliveredFrameSelector.cs`、`CaptureDeliveryProof.cs`；`WgcCapture.cs`新增明确policy入口，原严格入口保留 |
| 独占owner/队列 | `ContinuousWgcCapture.cs`、`LatestCapturePump.cs`：policy、清池边界、scope撤销、最新ROI摘要；保持原latest/stop机制 |
| Host发布/独立SOURCE | `NativeObservationService.cs`、`WarehouseEvidenceLease.cs`：v2租约、owner保存路径、局次/ROI/滚动授权、双时间资格日志；复用 `WarehouseWindowScroll` |
| MMF及Engine绑定 | `NteHost/SupervisorSession.cs`和`engine_v22/nte_engine_v22.py`：发布槽proof、ACK前复制核对、提交前本地期限/代际检查和policy出处；不改冻结MMF布局 |
| Python消费与UI | `app/native_observation.py`、`app/main.py`、`app/native_warehouse_source.py`、`app/native_warehouse_intake.py`、`app/native_warehouse_auto_capture.py`：v2 proof、delivery/result期限、原触发/稳定/滚动路径、当前ROI复核 |
| 选择与提示 | `app/main_window.py`、`core/main_window.html/js`、配置默认项与启动工具：启动前policy、能力拒绝、停止/空档/源异常显示；不新增局生命周期 |
| 证据索引及定向用例 | capture proof作为绑定原页的旁路元数据；扩展既有Native测试入口。若已有证据schema不能附proof，使用独立绑定索引，不修改正式物品资料表 |

不修改 `core/warehouse_vision.py`、拆件算法、候选资料或人工标签；算法确认、跨视口数量隔离、
项链/卡丁车、57px周期和品质块未知边界保持。实现前重新核对dirty基线，不覆盖其他任务成果。

## 7. 有界验证及实施判据

本轮不运行这些验证，只列确认后需要证明的具体行为：

1. **选择差异与原模式不变**：将既有原始未来数值作为输入；旧模式继续拒绝，
   新模式仅在独立池空边界和有序交付/readback proof齐备时接纳交付；originStrictQualified仍false。
   无边界、读回前后时序颠倒、同ID/旧scope、deadline/stop分别不能触发自动流程；不复制实现生成期望。
2. **慢OCR与SOURCE**：复用现有pipeline慢处理夹具，串行识别阻塞5s时采集替换仍有界，
   SOURCE在其固定5s期限内保存回执；槽/proof在正确ACK前不覆盖，错误hash/seq不提交事实；
   观察空档、替换数、存活内存和取消/实际退出都有日志。只测此新增旁路，不重跑旧矩阵。
3. **业务闭环离线事件流**：一条大厅→对局（含正常手动视口变化）→稳定结算→移动/滑块→到底→大厅→下一局序列。
   同局只触发一次，局内0自动滚动，下一局正常复用；旧回调/退出结算/停止立即阻止继续发消息。
   每个阶段的支持ID独立，重复页不能证明进展，金额冻结前原页不得进入正式记账。
4. **拒绝分支定向检查**：同一旧页重复交付、只有图片动、只有滑块动、滑块未知、场景缓存及最新ROI变化，
   验证动作为0或停止partial。两份相同静止像素但不同有效交付可支持稳定，不能增加身份场景数/物品数。
5. **真实验证另授权一次**：程序/模型先准备，从大厅开始一次完整链路，单次收页16/32/70及原停止条件；
   记录启动/观察空档/自动触发/保存/真实位移与滑块/结束原因。返回后只观察当轮实际发生的下一局，
   未发生就标未验，失败不自动补采，不再追加时间戳诊断轮次。若先需要有界入口核对，仍为3次/8s/10s且需另明确授权。

若清池边界无法在固定次数内成立、实际WGC不交付、场景链/当前ROI无法证明，或者窗口消息没有实际滚动，
这轮自动流程判失败并保留partial，不扩大预算。若WGC只因源时间未来而被新合同挡住，
先检查policy/元数据旧消费路径遗漏，不自动加容差。

## 8. 自动流程的替代路径与取舍

当前已有反例不足以否定HWND WGC的图像可用性，推荐先实现上述合同。若其交付/业务proof在实际条件无法成立：

| 替代 | 指定窗口／后台 | 来源及时间证明 | 权限、隐私、代价 |
|---|---|---|---|
| 指定HWND的PrintWindow客户区，接同一自动生命周期 | 可不激活；目标必须实际响应，GPU游戏兼容性未证实 | 调用起止、本地像素读完和视觉推进可记录；没有真实游戏Present/来源年龄，仍需交付业务合同 | 无需游戏注入；只指定客户区，不采桌面；同步可能阻塞，需独立有界worker取消。中等工作量，失败不能改全桌面截取 |
| DXGI producer capture（参考OBS Game Capture的特定窗口路径） | 核对进程实例与swapchain OutputWindow，只匹配指定窗口；后台仅在游戏仍渲染时有效，停渲染就暂停，不强抢前台 | 在生产者Present处记录请求序号、纹理身份、提交区间与GPU copy完成；可证明请求后生产者呈现/复制序列，仍不证明扫描显示完成，像素也允许静止 | 需进入游戏进程/图形hook及相应权限、游戏兼容许可；不能假定异环或其保护机制允许。GPU共享纹理/环形槽/取消/重新绑定工程较大，覆盖层和多swapchain需隔离。另确认架构后才开发，不绕保护/改驱动 |

[PrintWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow)由目标程序响应渲染且同步可阻塞，
不是已证明可用的异环方案。它不比WGC多提供绝对渲染年龄保证。
[OBS官方Game Capture](https://obsproject.com/kb/game-capture-source)有specific-window模式；
[D3D11共享纹理实现](https://github.com/obsproject/obs-studio/blob/master/plugins/win-capture/graphics-hook/d3d11-capture.cpp)说明技术路径。
生产者请求/QPC/GPU完成合同是本项目需要另设计的增量，不是OBS现成日志已证明的能力。
GPU事件完成可采用[End/GetData事件查询](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11devicecontext-end)等有界检查，
其完成是GPU命令证据，不改写成物理显示完成。

不将WGC捕获另一个缩略图窗口、桌面裁切或修改系统/驱动当成隐式回退。
人工截图和等待上游均不是此设计的最终产品方案。

## 确认范围

建议确认上面的 `wgc-delivery-v1`：允许来源绝对时间异常的帧，在独立交付和业务证据全部合格时
参与完整自动观察、原页保存、受控滚动及既有正式确认流程；明确放弃“来源绝对时间≤当前QPC、
来源绝对年龄和请求后合成时间已被证明”的保证，保留全部原值和严格模式。
不允许来源资格不足而绕过页/身份/金额条件；不授权本轮实机、新的输入类型、hook、系统/驱动改动或对外提交。
确认后实施上述增量并做相关离线检查，再另安排已经准备好的完整生命周期实测。
