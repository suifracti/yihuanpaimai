# Native 结算自动收页：复用现有生命周期的最小接线设计

状态：用户已于 2026-10-04 确认实施，三个断点已接线并完成定向离线检查；真实时钟、滚动及完整拍卖未验。本轮未采游戏或发送输入。源码基线为
`codex/consolidate-workspace@50d6ae8`，前三组依次为 `bc343bd`、`93f072e`、`8fdc607`。
本设计取代 2026-10-03 自动翻页文档中的待确认“每局一次性武装”提议；不改变已经实施的窗口消息收页能力。

## 已有实现与三个实际断点

历史核对证据为 `build/git-history-review-20261003/result.json`，本次只核对相关当前代码，没有重查全仓或运行矩阵。

| 已有能力 | 当前入口与历史依据 | 本次处理 |
| --- | --- | --- |
| 本局一次、结算、仓库、顶端触发 | `app/main.py:279 maybe_trigger_auto_warehouse_capture`，历史 `3c7ec63` 已有；`b75754f` 加入只读拒绝 | 复用条件与 `_AUTO_CAPTURE_ATTEMPTED_KEYS`，增加有界 Native 分支 |
| 当前 Native 生命周期 | Engine `_advance_match_lifecycle/_retire_match_for_lobby`，`4791da2`；Host 离场继续观察 `330ecd4` | 不新增状态机，不复活旧 `AuctionSessionFSM` 采集入口 |
| 同局恢复／跨局切换 | `6dd440a/8416559/ab4929a` 的显式同局恢复；Worker 新 match ID 与代际切换 | 复用身份和退役逻辑，不增加自动重启或改绑窗口 |
| 收页与结尾处理 | `NativeWarehouseAutoCapture`、SOURCE 协调器、隔离 intake；本次已提交 `8fdc607` | 自动触发和手动入口调用同一协调器 |

断点一：旧自动触发首先调用 `_game_input_execution_allowed()`，Native 配置立即返回
`OBSERVATION_PROFILE_READONLY`；原有两个调用点是旧 WebSocket／旧图像处理路径。
Native 的 `_native_observation_event()` 接纳路径没有自动触发调用。

断点二：旧成功路径调用 `set_capture_safety_override(True)`，准备游戏前台及旧输入，不能直接复用于后台 Native。
不能通过删除全局只读门禁或恢复旧滚轮驱动来“接通”。

断点三：Host 当前传给 `WarehouseSourceContext.FrozenSettlement` 的值是
`settlementCollectionClosed && scene == SETTLEMENT`，`WarehouseEvidenceLease.Open/UpdateContext`
据此拒绝尚未业务收束的结算。业务收束可能等 `settlementReady` 或 45 秒。
仅在 Main 补调用会遭到 Host 拒绝，也不能用放宽 Main 健康检查掩盖这一点。

当前“采集完整仓库”仍是结算页一次点击再确认，只有翻页自动，结算触发没有自动接入。

## 最小接线与启动语义

复用用户已经启动的 Native 观察、现有结算识别与仓库轻量观察，不新开常驻截图通道。
启动观察前增加一个默认关闭的“结算自动收页”选项，固定于本次观察会话；一次启用后适用于该会话后续各局，
不要求每局手动武装或赶在 90 秒结算内点击。关闭选项即停止待触发能力及正在进行的收页。
该选项明确授权的能力仅为本局结算仓库的指定 HWND 滚动消息，不能转成其他游戏输入权限。
手动“采集完整仓库”和“停止采集”继续保留，并与自动触发共用运行互斥与本局一次记录。

在 `_native_observation_event()` **完成会话、时间、序号、目标、CurrentMatch 投影和帧接纳之后**，
以及 `_native_source_observation_notice()` 已检查原 SOURCE 边界之后，调用现有自动触发函数的 Native 分支。
拒绝、迟到、退役旧局或未接纳的事件不能触发；不用 `LATEST_PAYLOAD` 的旧值为新事件补资格。
不要以 Solver 局内建议租约为空判定结算不可采；结算有独立的仓库来源作用域。

Native 分支复用 `recordStableKey` 一次判断、运行互斥、`SETTLEMENT`、`warehousePresent is True`
及 `TOP/NO_SCROLL`。条件必须来自同一接纳帧及同一目标／局代际。
若 Native pipelineContext 已有本帧仓库／滚动条证据，直接复用；缺少时只从该帧已保存原图校验尺寸、
像素哈希与作用域后调用现有 `observe_warehouse_grid/observe_warehouse_scrollbar`，不另取帧，
不调用逐物品身份识别，也不读取旧帧代替当前证据。UNKNOWN、中间起步或目标不合格不启动、不轮询补采。

确认隔离草稿已经落盘后调用同一协调器 `prepare -> confirm`；首次草稿尚未保存时复用
`_persist_current_draft_now` 完成本局隔离草稿，不写正式历史。先在共同锁下确认键／作用域，再在开始前记录本局已尝试，
不执行旧 `captureSafetyOverride`。自动与手动启动都通过同一作用域校验，不能并发开启两份租约。
prepare 无资格不记作采集尝试；开始被拒、失败或用户停止后，同局不自动重试。
有界内部调度复用当前计时器和协调器，不再造任务队列或生命周期。

Host 将 **业务账单冻结** 与 **结算仓库来源可用** 两个已有职责分开：
`WarehouseSourceContext` 的资格改为当前 Worker 已观察的 SETTLEMENT、当前目标可用及映射有效，
OPEN 仍要求作用域、几何、租约、原预算和显式 `allowWindowScroll`。
Main 负责本帧网格与顶端起步，首张新 SOURCE 再独立核对 TOP/NO_SCROLL、保存和稳定证明后才允许滚动。
进入结算动画但没有合格仓库网格的帧不能触发。
同一候选能力必须在 Host 启动回执中明确确认“允许业务冻结前的结算仓库 SOURCE”；不以旧 Host 的通用滚动支持推断此能力。
缺少该确认时拒绝自动启动，避免验证到旧候选。复用现有能力回执，不引入新的像素传输协议。

保持 `settlementCollectionClosed` 的业务 FRAME 冻结发布逻辑、金额归档条件及继续观察下一局的行为。
最迟截止仍从 Host 首次 SETTLEMENT 观察起算，OPEN 或点击不能重置：最多 16 张来源、32 次来源请求、
原字节上限、单次绝对 70 秒。稳定支持帧也计入原来源上限，不另增“免费”取帧额度。
若已过截止、无法证明窗口或出现权限提示就结束，不等待重开、补采或用全局输入回退。

## 解除本局与下一局

Worker 看到大厅或 `AUCTION_LOADING/to_lobby` 时，复用 `_retire_match_for_lobby`：
保存本局已有事实，`begin_next_match`，清理人工覆盖及本局仓库工作作用域。
Main 接纳到局／代际变化后，原 SOURCE 协调器先撤销旧租约、计时器和旧回调资格，再让新局触发判定可用。
原图、覆盖清单与隔离结果归旧局；结束后异步识别不能进入下一局。

保留 Host 在结算后继续 WGC／场景观察的历史实现。其 `IN_AUCTION` 解除结算状态仍要求
Worker 给出不同的有效 match ID，场景标签本身不能复活旧局。
新局新 `recordStableKey` 自然获得一次机会；不要每次结算帧清空已尝试集合，也不要因观察恢复或窗口变化重开旧局机会。
同局已尝试键保留在当前 Main 运行期，包括显式同局观察恢复；旧事件不能触发重试。
重启进程后如需同局恢复，先从本局隔离收页清单恢复“已尝试”标记；不能仅凭集合内存为空重采。
标记绑定记录键，不绑定可变化的观察会话 ID；完整结束前的标记先落本局隔离记录，避免进程中断后遗漏。
这是恢复既有一次语义所需的记录，不是另一套对局状态机。

目标／观察会话失效、最小化、停帧、映射变化、用户停止或实际截止均走现有关闭路径。
故障后仍需现有显式同局恢复入口，不添加自动激活、自动重绑 HWND 或自动重启观察。

## 图像位移与滑块变化联合门禁

接入位置为 `NativeWarehouseAutoCapture._page` 的 `WAIT_MOVED`。
当前这里只要求 VERIFIED 向下图像位移与重叠，滚动条只是有效状态标签；缺少滑块实际移动证明。

使用现有 `WarehouseScrollbarObserver` 的 `trackBox/thumbBox/thumbPosition/thumbLength`，
对比 **滚动前已保存且稳定的锚页** 和滚动后已保存新页。
只有轨道、滑块长度及客户区映射可比较，滑块顶端像素位置明确向下且归一化位置增加，
并同时满足现有 VERIFIED 向下图像位移（内容偏移为负）和连续重叠，才进入稳定支持核对。
不以 `segmentChange`、状态由 TOP 变 MIDDLE 或 SendMessage 返回成功单独证明进展；
不用其 0.035 指纹联合阈值代替滑块坐标证明。
几何不一致、像素量化内无可分辨位移、滑块不动／反向、图像未动／方向不符／重叠不确定，均停止并保留部分覆盖。
若实际有效滚动因检测噪声被拒，只针对保存的两页离线定位，不预先猜测放宽阈值。

继续先保存合格页并收到 ACK，再发 `SCROLL_DOWN`，只能消费当前来源一次。
`WarehouseWindowScroll` 仍只给指定 HWND 安全客户区点发 `WM_MOUSEWHEEL`，有界 SendMessageTimeout，
不激活、不移动鼠标、不使用全局键鼠，也不回退旧 `warehouse_wheel_driver`。
首尾、顺序、重叠、重复页和拼接由既有清单／覆盖账本判定，消息成功与观察框数不替代全覆盖或物品总数。

## 未来时钟诊断与停止接入

当前 `CaptureAfterRequest -> RequestFrameSelector` 已接入生产待请求 SOURCE，
普通持续 FRAME 仍为原 `Capture`。新选择器离线通过不代表真实通过；最新旧现场 QA 是
3 次尝试／2 张接受，第三次未来来源时间被拒，整体失败。

独立入口为 `tools/native_qa/run_qa.py`；下次仅在明确真实授权后进行最多 3 次／8 秒工作／10 秒实际退出核实。
保留 `RequestClockDiagnostics` 的 WGC 原始 100ns ticks、requestNs/deadlineNs、
比较时的 QPC ticks/frequency/商/余数/ns、aheadNs、读回时原始数值。
未读回记录 NOT_REACHED，截断数量如实记；不得修改时间戳、删除 future 检查或凭猜测放宽门槛。

生产接线只在待请求 SOURCE 时启用同一有界原始诊断，将完成或失败的
`LastRequestClockDiagnosticsJson` 连同作用域／请求编号写入当前 session 的诊断日志，
异常路径在现有 `capture-failed` 发布和关停前写出；不通过业务 FRAME 刷新健康、替代拒绝帧或扩展租约。
普通持续 FRAME 不因本设计改选择算法；其原检查保持。
先定位真实数值失败点再修改相应换算或选择缺陷；本设计本身不宣称时钟问题已解决。

用户“停止采集”走 `_stop/close_source` 撤销计时器、generation 和待 SOURCE，保留已保存页，按 INCOMPLETE 结束；
停止观察走 `native_stop -> evidenceLease.SignalStop` 即时撤销，保持查询后和写盘前的停止检查。
SOURCE 超时沿用关租约路径；非超时采集异常沿用 PAUSED／Host 受控退出，不能隐藏错误继续。
独立 QA 的父进程拥有 Job 与 10 秒退出核实；生产停止回执不等于该证明，未观察到实际退出不得写“已退出”。

## 预计修改范围与最小验证

| 文件 | 具体增量 |
| --- | --- |
| `app/main.py` | 复用旧触发判定，接入接纳后的 Native 分支；共享一次记录、隔离草稿落盘、作用域失效与停止；保持旧全局只读拒绝 |
| `app/main_window.py`、`core/main_window.html/js`、`app/config.json` | 启动前的会话自动收页选项、等待／开始／已保存／停止状态；不新增 HUD 模式或每局武装 |
| `app/native_observation.py` | 启动时固定选项与候选能力确认；不新增采集进程 |
| `app/native_warehouse_auto_capture.py` | 同一协调器受控启动及图像＋滑块联合门禁；沿用结束后异步处理 |
| `core/native_trial_drafts.py`（仅若现有隔离元数据接口不足） | 本局已尝试的可恢复标记，不写正式历史／身份／标签 |
| `NativeObservationService.cs`、`WarehouseEvidenceLease.cs` | 将来源资格与账单冻结分离、能力回执、待请求 SOURCE 原始时钟诊断；保持当前生命周期与既有绝对预算 |
| 现有 Native 相关测试与小型夹具 | 扩展受影响行为用例，引用已入库源码和夹具 |

不修改 `core/warehouse_vision.py`、资料主表或标签；项链／卡丁车、57px 周期及品质块未知边界保持。
不改 Engine／CurrentMatch 已有生命周期；若接线发现缺少上下文，只补传当前已有轻量证据，先指出必要文件增量。

确认实施后，最小离线验证针对三个可观察行为：同局重复和恢复不能二次启动、新局可启动且旧回调不能污染；
图像移动但滑块未动／反向／不可比较必须停止；冻结前来源可用但离场、停止及截止仍撤销来源和输入。
沿用现有测试，编译受影响 Host；不重跑旧识别矩阵或全套故障矩阵。
真实时钟诊断与正式滚动仍分别等明确授权，失败只针对最早断点。

完整拍卖、多页全覆盖及物品身份准确性均未验证。本轮实施授权不包含游戏采集或输入。

## 实施落点

Native 接纳函数返回接纳回执，来源包装器仅对已接纳 FRAME 尝试触发；拒绝的旧事件不再直接撤销当前 SOURCE，实际失效仍通过当前来源契约关闭。
本帧原图必须在指定 session 目录内，尺寸及像素哈希一致，随后复用网格／滚动条轻量观察；没有新增 WGC 通道。
本局尝试以独占创建、flush/fsync 标记保存在隔离 `warehouse-intake/attempts/`，不修改账单。
主窗口刷新和手动确认亦对 Native 路由禁用旧置顶／前台准备。
终止清单记录作用域、页面顺序、状态与终止原因；换局取消不会把旧页写入新局。

具体文件清单、启动／停止与未验边界见 `docs/reports/2026-10-04-native-auto-settlement-wiring.md`；
版本哈希、编译与定向日志见 `build/native-auto-trigger-20261004/result.json`。
