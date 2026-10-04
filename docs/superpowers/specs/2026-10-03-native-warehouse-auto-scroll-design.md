# Native 仓库自动翻页采集：最小接入设计

2026-10-03。用户授权把滚动采集做进项目，不要求外部 UI 工具操作游戏。随后用户明确回复“确认，按该方案接入”；本设计的代码接入和定向离线验证已完成，真实窗口滚动尚未验收。

## 当前断点与真实证据

项目已有 `WarehouseWheelDriver`、`ProductionScrollDriverFactory`、16步与结算绝对截止的采集状态机。Native 路由仅接入手动收页，不能用旧链路的成功代替原生自动翻页已完成。

新选择器真实验证 `live-f357c8c232` 尝试3次、读回2次、接受2张后台客户区原帧，1.22716秒核实退出。第3次因来源时间晚于查询后QPC而拒绝，整体未通过；原日志未含超前数值，不能从这次 raw 断言根因或扩大容差。当前只增加异常中的 source/observed/ahead/request/deadline 数值，门槛、停止及3/8/10 QA预算保持不变，不重采游戏。

## 用户体验与范围

沿用项目现有“采集完整仓库”入口。用户启动一次后由程序收页、向下翻页、等待稳定新帧、保存和核对覆盖，不要求用户手动滚动或抢在90秒退出前发送消息。持续后台观察仍只读；显式完整仓库采集才拥有本次会话的滚动权限。

不新增HUD模式，不操作出价、交易、退出或其他游戏区域。不自动启动游戏。窗口定向滚动绑定当前 HWND/PID/进程创建时间和本局记录；无法证明目标、结算稳定或客户区映射时停止并保留部分证据。

## 最小增量

1. `app/native_warehouse_auto_capture.py`：新增有界自动协调器；复用已获准的原帧收页、滚动条观察、重叠核对和覆盖账本，不创建第二条截图通道。
2. `app/native_warehouse_intake.py`、`app/native_warehouse_source.py`、`app/main.py`：将原生完整采集命令路由至该协调器；保留手动入口。现有持续观察启动本身不触发自动滚动；一键武装等待结算是否需要作为另一产品功能，另行说明，不在本最小增量中暗加。
3. `architecture/v2/host/wgc_live_harness/WarehouseEvidenceLease.cs` 与 `NativeObservationService.cs`：在本局有效租约内增加显式向下滚动操作与结果证据；实际窗口消息只发给已校验的游戏 HWND，坐标必须处于客户区仓库范围。优先窗口定向滚轮消息，不移动系统鼠标、不主动激活窗口；若游戏不接受该消息，只能报滚动未生效并停止，不能偷偷回退到全局 SendInput。
4. SOURCE 的请求后选帧单独接入 `CaptureAfterRequest`；源时钟错误仍拒绝。普通持续业务 FRAME 保持原入口，此改动不声称 FRAME 也完成新选择器接入。

这涉及 SOURCE 操作与自动路由的生产语义。用户确认后已接入候选代码，不能把独立 QA 的两张接受帧写成生产实机验收通过。

## 单次采集顺序与边界

目标/本局/场景/映射有效 → 收第一张新原帧并确认滚动条顶端 → 保存 → 一个向下滚动脉冲 → 请求滚动后新帧 → 等待可证明稳定并保存 → 核对相邻页重叠 → 继续，直到账本证明覆盖或停止。

保留现有最多16页和绝对70秒上限，失败不续预算。页面及保存字节受已有租约和intake限制；用户停止、场景离开、本局或目标变化、失效映射、时钟拒绝、停帧、重复未变化或重叠无法证明均停止。底部到达不单独等于完整覆盖；旧图重复或相邻帧不构成新独立场景。局部物品框、身份、数量和人工标签由各自规则处理，滚动成功不证明识别准确。

独立实机 QA 仍是3次显式尝试、8秒工作、10秒核实退出；不能重复启动短 QA 拼出70秒采集。生产多页采集须通过本设计的单次显式入口执行。

## 只验证本次影响

离线检查自动状态机只在有效结算租约滚动、原生命令不落入旧截图链路、失败和停止不再输入、预算不续、保存先于滚动以及覆盖证据门槛。复用既有滚轮/账本/停止矩阵，不重跑旧截图回归。

实机需另一次明确授权：先定位并解决实际源时钟拒绝，再验证一次窗口消息是否有效、原帧是否晚于滚动请求、跨页重叠和停止。游戏不支持后台窗口消息时报告这一具体限制，再决定是否允许项目内前台滚轮适配；不会要求用户代做翻页来把未实现写成完成。

## 算法归属

白色1×2与右上1×1被输出为上方2×1及左下1×1，属于新真实帧的拆分/误合并错误。`core/warehouse_vision.py` 和相关算法用例继续由“推进局内仓库离线识别”独占；以当前ff67算法为基线交独立增量，不改正式资料、标签或旧交付。采集侧不通过改物品尺寸修补该错误。

## 代码接入与验证结果

Native 的现有 prepare/confirm/stop 命令已路由至 `NativeWarehouseAutoCapture`，不再落入旧窗口截图或全局滚轮链路。只有显式确认的本局会话 OPEN 带 `allowWindowScroll=true`，手动 OPEN 仍不授予输入。Host 的 SCROLL_DOWN 要求当前租约、原帧已收到 SAVED ACK、最新来源ID/哈希、单页未滚动过；重新核对真实 HWND/PID/创建时间、HTGame.exe/UnrealWindow、可见/未最小化、客户区大小与映射后，只发送一个 WM_MOUSEWHEEL(-120)。窗口消息处理最多100ms，不激活或移动鼠标，无全局输入回退。SCROLLED 回报 inputActions=true，其他 SOURCE 事件仍为false，不伪装输入为只读 FRAME。

SOURCE 有请求时，Host 调用 CaptureAfterRequest 并沿用原请求截止；无 SOURCE 请求时普通 FRAME 仍调用原 Capture。SOURCE取消或请求截止只结束本次收页资格，下一次循环继续检查原普通观察及native_stop；不会把用户停止收页误报成业务捕获失败。实际来源时钟未来值仍进入严格失败门禁。稳定性支持帧也显式计入 SOURCE 请求次数，原16原图／32请求／70秒和字节预算不续期。严格新鲜的重复像素只回报时间、序号、映射与精确哈希证据，用来证明画面未动，不计新页或独立身份场景。每页先保存、观察顶端/位移、再取得稳定证据；无位移、不确定重叠、未知滚动条、停止或截止结束并保留原图。底端后仍由覆盖账本判断完整；失败终止向账本传INCOMPLETE，不能因有底端截图被误记为完整。

冻结结算不再发布业务 FRAME 时，只在当前独立 SOURCE 租约的相同本局和目标范围内保留结算收页资格；不刷新业务健康、FRAME 时间或事实。Native SOURCE 与 scoped SCROLLED 的读取分别验证，普通持续后台观察仍无输入。

当前算法已按相对ff67的独立白框增量整合为eef9968a…。对应真实图单例通过，其他30观察框不变；32观察组件仍不是物品数，身份、未知品质块及X偏移边界保留。定向自动协调器、冻结范围、输入事件关联检查通过，Host假输入适配器证明保存授权、重放、停止、重复新帧及绝对截止；没有重跑旧矩阵。证据见 [接入结果](../../../build/native-background-20261003/auto-scroll-integration-result.json)。Windows消息契约依据 [WM_MOUSEWHEEL](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-mousewheel) 与 [SendMessageTimeoutW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw)。消息送达不证明游戏实际滚动。

候选Host编译0警告0错误，未启动助手或游戏，未执行新WGC/滚动。此前live-f357c8c232仍是3尝试／2接受／第3次来源时钟未来值拒绝／1.22716秒核实退出，整体失败。下一次另授权后先按3/8/10预算定位该实际拒绝；生产多页/窗口滚动和完整拍卖均不能据此声称通过。

## 下一轮启动准备：本轮没有读取游戏

当前源目录启动入口是 `app/run.bat -> build/takeover_20260905/repro-venv/Scripts/python.exe app/main.py --debug`；无 `NTE_NATIVE_HOST_EXE` 覆盖时，Native 优先选择 `build/native-observation/WgcLiveHarness.exe`（实际实现为同目录DLL）。本轮只重建候选Host与独立QA Worker，不启动助手。算法仍为eef9968a…，白框、资料、人工标签不改。构建和精确哈希见 `build/native-background-20261003/readiness/result.json`。

独立时钟诊断入口仍是 `build/warehouse-recognition-20261002/bounded-wgc-qa/run_qa.py`。将来另获明确授权后才用 `--mode live --observation-window-mode background-readonly --game-ready --hwnd <当时核实的HWND> --pid <PID> --instance <创建FILETIME>`，不复用历史进程身份；不直接运行无参数入口（其默认offline会重复旧矩阵）。Controller使用当前编译Host，Worker在构造WGC前要求原始时钟诊断能力，缺失则拒绝旧候选。3次显式尝试（失败计入）、8秒工作、10秒实际退出核实不变，首次失败即结束，不循环补采。

诊断默认关闭，仅独立QA显式打开。每次请求记录原始QPC ticks、频率、商/余数及同次换算ns；每个被检查的队列帧记录WGC SystemRelativeTime的100ns ticks、原换算sourceNs、用于未来值判断的同次QPC原始数值、aheadNs、请求和原截止。读回发生时另记其原始QPC样本与读回后比较样本；未到读回则明确NOT_REACHED/null。最近32条来源比较保留，超出会注明截断总数，不能说后台只来了3帧。异常与成功均输出clock-diagnostic；原门槛、时间基准、时间戳和预算不改，不能从离线数值例子推定真实根因。

QA启动和每张原帧保存/接受会即时输出qa-progress；原始日志、失败与真实退出结果仍在每次新建的 `bounded-wgc-qa/live-<id>/child-output.jsonl`、`result.json`、`controller-result.json`，不覆盖旧run。后台生产日志位于 `build/native-observation/session-<id>/main-diagnostic.log`（WAREHOUSE:NATIVE_AUTO）；Host状态与stderr同会话目录。源启动脚本的普通日志目录改为 `build/native-observation/runtime-logs`。开始、原帧保存顺序、SOURCE/重复证明、滚动条、稳定页、图像重叠、停止原因均有文本诊断；该诊断不能替代保存清单与覆盖账本，日志缺失时相应证明仍未完成。

Host原始BMP在 `session-<id>/warehouse-sources/`；Native保留原帧及派生PNG的根是 `build/native-observation/trial-drafts/`，原帧在source-frames，按页保存清单在warehouse-intake/<session>.json，审阅结果在隔离canonical-history.json。清单保留原顺序/来源序号/哈希；结束后现有处理器根据图像重叠、顶端/底端及连续账本生成拼接和覆盖。重复页不算独立场景，中间起步停止为START_REQUIRES_TOP，未到尾或证据缺失只报部分/未证覆盖，观察框数不当物品数。

“采集完整仓库”仍须在结算页点击，再点弹出的确认；未到结算时不能武装等待。这是自动翻页而非结算自动触发。运行后同一按钮成为“停止采集”，发stop_warehouse_capture，撤销租约/计时器并以INCOMPLETE处理已保存页。停止整个观察是native_stop；它不等于独立QA父进程的10秒实际退出证明。正式SOURCE待请求时用新选择器，普通持续FRAME仍用原Capture；任何QA通过均不能代替生产滚动、覆盖或完整拍卖通过。

## 缺少的自动触发：最小待确认设计（本轮不实施）

本局记录建立后，在对局中显式选择“本局结算自动收页”，一次性绑定当前目标、观察会话和本局；没有有效本局时不能武装。武装本身不启动新观察或WGC，复用用户已启动的后台只读观察；不新增常驻截图通道。

已有正式观察给出新鲜稳定SETTLEMENT与仓库可用，且本局/目标/隔离存储/能力有效时，消费一次性武装，调用同一生产协调器。其第一张新原帧仍须证明TOP/NO_SCROLL，保存和稳定核对完成后才滚动；不能用消息送达当位移。沿用Host原结算绝对截止、16页/70秒及请求/字节上限，不从武装或触发重置结算预算。收页期间只做必要保存、轻量滚动条/稳定/重叠检查，逐物品识别在结束后异步进行。

界面明确显示“本局已武装/等待结算/已开始/已保存N页/已停止”；目标、观察会话或本局变化、用户停止、失效、期限到达均解除武装。一次消费或失败后不自动重试，不继承到下一局，不激活、不使用全局输入。新增一次性武装与自动消费的生产行为须另确认后实施，当前入口仍为结算页手动点击及确认。

只读核对还发现一项生产滚动验收前的具体缺口：协调器WAIT_MOVED当前要求VERIFIED向下图像重叠，但滚动条只检查TOP/MIDDLE/BOTTOM/NO_SCROLL有效状态，没有要求前后thumbPosition向下变化。因此“程序继续翻页”不能作为滚动位置已变化的证明。本轮补入日志记录原始thumbBox/trackBox/thumbPosition，未改变此门禁；下一步先完成时钟诊断，生产滚动前按当前验收要求补最小联合门禁：相同可比较轨道/滑块几何下，滑块实际向下移动且图像向下位移及重叠已验证；不确定或无进展停止。无需重开全仓或截图矩阵，尚不能宣称生产滚动验收准备全部完成。
