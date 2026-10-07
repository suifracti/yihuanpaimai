# 本轮持续观察定位与准备结果

基线50d6ae8及既有dirty全部保留；本次没有采游戏、输入、提交或重跑旧矩阵。
这是部分修正与待确认结构方案，不是持续观察可靠性已通过。

## 失败时间线（北京时间）

时间由最后成功帧的原UTC/QPC锚点换算，原始数值未修改。

| 节点 | 时间 | 证据 |
| --- | --- | --- |
| Native启动请求 | 20:55:40 | main-diagnostic.log STARTUP:NATIVE |
| 首帧读回 | 20:55:42.809 | frame_records.ndjson |
| 第180帧读回 | 20:56:21.774 | captureTimestampNs 10949628873200 |
| FRAME_READY发送/Engine收到 | 20:56:21.785/21.786 | Host/Engine pipe trace |
| Engine复制完成并ACK | 20:56:21.852 | ACK距收到65.5243ms |
| 第180帧识别结果发出 | 20:56:26.544 | ACK后4692.1855ms，processingMs 4678.4123 |
| 下一读回拒绝 | 20:56:26.687 | sourceNs 10949331925000，readbackNs 10954541561500 |
| Engine受控退出完成 | 20:56:26.857 | shutdown.complete，162.9982ms，childExitCode 0 |

拒绝帧的来源时间约20:56:21.477，读回旧5209.6365ms。没有精确的帧池入队/出队时间日志，不能伪造这些节点。
180帧的处理耗时中位45.47715ms，仅第180帧超过500ms。没有对局、SOURCE、程序滚动或结算收页事件。
原失败证据不覆盖，派生时间线在 `build/native-auto-trigger-20261004/slow-frame-timeline.json`。

## 原因与尚不能证明的部分

`SupervisorSession.SendFrame` 在早ACK后仍等待PERCEPTION_RESULT，Native循环在返回前不调用Capture。
因此4.69秒的识别等待确实阻塞Host取帧。WGC两槽帧池持续到达；Engine有界队列并没有因这一帧挤满，
因为Host当前通常只有一帧在途。上一轮普通Capture换新选择器只避免随后直接拿旧排队帧，不解耦识别与取帧，
不保证这4.69秒内出现的短暂画面被保存。

旧processingMs包括观察、业务/局次投影和history落盘；缺少子阶段记录，不能精确追溯4.68秒内部占比。
同一原帧、原header/像素hash、保存的最终上下文作一次完整隔离对照：observe 2113.9091ms，
context/lifecycle 0.7184ms，history 8.8227ms；cProfile显示RapidOCR 2021ms，ONNX推理1929ms。
这证明该画面存在慢OCR路径，不证明原场景4.68秒全部是OCR。原前一帧内部上下文与当时调度条件不可重建。
第一份profile夹具缺cornerChecksum，运行失败，记录保留；补齐原frame_records中的header后仅重跑该单帧对照，
成功结果在 `saved-frame-180-profile-complete/result.json`，不把首份失败算通过。

本次source小于readback，是旧帧问题，不是来源未来；新鲜度2秒/发布31秒等门槛未改。
此前来源未来根因仍未解决。既有请求选择器离线结果可复用，但不能当真实QPC/WGC时钟问题已解决。

## 已实施与最小检查

- `app/native_observation.py`：当前Host的EOF始终报告停止/错误，即使退出码0或暂未确认；保留session及实际PAUSED原因；
  退出未知时复用有界停止，无法确认退出就保留进程归属，避免丢弃活子进程再开第二个。旧reader不能停止替换后的Host。
- `app/main.py`、`core/main_window.js`：停止健康状态保留最后成功原帧时间/序号/局次；明确“观察已停止、材料保留、未自动重启”；
  不再让草稿的“进行中”徽章被理解为仍在采集。本次已有PAUSED回执，旧UI有暂停提示，
  但没有渲染/屏幕证据能证明当时用户具体看到什么；不伪称有桌面验收。
- Engine仅补六项阶段诊断与queueWaitMs，不改业务处理结构、物品身份、正式账单或生命周期。
- 5项新退出/状态行为检查通过，JS停止提示检查通过；一项现有真实Engine队列行为检查通过：
  慢业务回调阻塞时早ACK仍返回、待处理上限2，第四张明确SKIPPED。该检查不证明Host已经解耦。
- 相关Python/JS语法与差异检查；Host/C#未再改变，复用上一轮编译证据。没有全矩阵、录像或新截图回归。

## “完整记录一局”的实际含义与缺口

应持续观察大厅、加载、对局、结算、返回，沿用当前match/generation换局，不能每局重新武装。
现有普通采样间隔120ms加识别、传输、保存时间；实际大厅180帧/约39秒读回跨度，约4.62fps，不是配置保证。
保存结构化逐帧观察、隔离草稿、首/最新原图、确切情报/边界材料、结算SOURCE原图与清单，不保存所有普通帧像素。
当前同步等待会漏过慢识别期间的短画面。拟议解耦仍会有界跳过中间普通帧，必须记录缺口，不能承诺无损整局录像。
短暂关键情报若必须保留，需要另外批准有界关键ROI/事件材料方案，不直接变成无限录像。

局内手动滚动是正常操作，不停止观察，不触发结算自动滚动；移动期间不认稳定证据。
`core/warehouse_vision.py`的row明确是viewport行，Engine `_merge_warehouse_fact_slots`按网格原点累积，
该路径不能证明跨视口去重；不应把局内多个视口坐标当全仓实例或准确总数。
可靠性接线前须对未证明视口隔离新增身份/数量投影，复用原位稳定及重叠依据；不修改共享算法文件或人工标签。

## 下一步与候选边界

最小结构方案位于 `docs/superpowers/specs/2026-10-04-native-continuous-observation-reliability-design.md`，待用户确认。
拟保留单Engine/串行业务/现有MMF与ACK，增加WGC独占线程和最多一张普通待处理最新帧，SOURCE独立串行仲裁；
停止可取消，跳帧有记录，代际与窗口映射失效即终止，不自动恢复或补采。
本次候选身份及增量哈希见 `build/native-auto-trigger-20261004/reliability-preparation.json`；结构尚未实施，不用于宣称修好。
结构、视口隔离与相应定向检查完成后，才交付下一轮实机候选并另获启动授权；一轮授权覆盖自然发生的完整链路，
启动及异常停止及时回报，未发生下一局标未验。真实收页、联合滚动门禁与未来时钟继续未验。


## 2026-10-05 已批准结构实施与离线交付

以上2026-10-04定位和失败证据保留，不以新结果覆盖历史。现候选：`50d6ae8+continuous-observation/e52908e45825`，HEAD仍50d6ae8。
完整源码/Host哈希、与上一准备版本的差异及启动入口在 `build/native-observation-reliability-20261005/candidate.json`。
本轮游戏采集0、游戏输入0；未提交、推送、发布或重启旧Host。

- `LatestCapturePump.cs`、`ContinuousWgcCapture.cs`：WGC/D3D创建、选帧、读回、映射查询、释放均在独占线程。
  普通最新槽最多1帧；Take转交私有载荷所有权，替换只释放槽的旧引用。显式SOURCE作业独立、至多1项，
  抢占普通等待并丢弃先前待处理普通帧，保留原请求时刻/截止。普通采样间隔仍120ms，不保证8fps。
- `NativeObservationService.cs`：普通业务仍串行SendFrame；其等待期间采集线程继续前进。
  `WgcCapture.cs`增加实际读回计数和采集序号；日志记录取帧/处理/替换、替换时段、业务等待、观察空档、最终退出状态。
  Native私有BGRA载荷上限4份/33,177,600字节（生产中、待处理、业务中、显式SOURCE保守合计），
  MMF另为33,177,856字节；Engine/OCR和GPU资源另计，不能把此值当整个进程RAM上限。
- `SupervisorSession.cs`：同一inbox的ACK/结果等待可取消、50ms切片；原截止不续期、精确ACK释放规则不变。
  控制EOF、显式停止、队列溢出及读通道失败带具体原因关SOURCE并取消等待。采集所有者最多等待1500ms；
  无法退出明确ERROR，不假称释放。仍复用既有受控Engine关闭，不静默重启。
- Engine慢观察返回后先检查停止/失效代际，再提交事实；停止不再排空待处理帧到业务。
  阻塞任务未退出时记录worker.exit_unconfirmed，不在退出线程重写混合状态；Host仍有既有有界进程终止路径。
- `warehouse_viewport_scope.py`与Engine适配层：本局保留一个图像/滑块共同证明的视口锚点；
  只在该作用域合并本地row/col。未知、移动或不同视口仅进观察日志/帧记录，不新增数量/总价事实。
  已知同视口事实保留，回到被证明的原视口可复用；换局清除锚点。
  `deferred_identity_analyzer.py`把视口加入既有任务作用域，返回不同视口时重置图像轨迹，避免缓存污染。
- 收页控制改为下一业务结果刷新作用域后接纳；Python自动收页还检查新原页确有结算标题，
  Host滚动还要求最近保存页在原2秒新鲜度内。无新门槛放宽、全局输入或平行状态机。
  完成显式取帧却未满足SOURCE准入时，关闭该次收页并留下时钟诊断，不在同一请求下偷偷再次采集。

最小行为证据：`pipeline-final-check.json`七项通过（最新槽/回收、SOURCE实际写盘并发、取消、异常、
未确认退出、真实MMF精确ACK、Supervisor阻塞等待取消）；`engine-check.log`四项通过；
`admission-check.log`四项通过（同视口有效身份、人工事实保护、实例决定保留、非结算页不能发送滚动）。
Host编译0警告0错误，Python语法及差异检查通过。旧截图矩阵未重跑。
新夹具首轮分别因Windows计时/FPS假设与缺失时间锚字段失败，原失败说明/日志保留，修的是夹具，未放松业务断言。
Main/JS未再改变，复用此前退出原因/最后成功时间/旧reader保护证据；没有桌面实机通过证据。

仍需真实验证：WGC线程与时钟、真实滚动联合门禁、同局一次、自然返回与下一局、覆盖范围。
旧队列导致5.209秒旧帧的根因已有结构修正及离线证据；慢OCR未被加速，原单帧4.678秒仍不能全部归因OCR。
此前“来源在未来”根因仍未解决，原数值和拒绝门槛保留。SOURCE仍需原worker序号/像素hash和2秒新鲜度，
慢业务可能拒绝收页；取帧持续不代表每条短暂情报都被识别，也没有新增无限录像。

下一次明确授权后从大厅提前启动：现有主窗口选择Native后台只读、启用结算自动收页，走`start_live_vision`。
后台只读本身无输入；结算自动收页只向指定异环窗口发消息。停止当前收页不重试本局；关闭结算自动收页
同时禁止后续自动触发；停止观察关闭Host/SOURCE。一次授权覆盖大厅→对局手动滚动→结算→返回，
不逐节点再询问，不无限等待未发生的下一局。当前项目助手/Host未运行，自动收页配置仍为false。


## 2026-10-05 本轮明确授权实机：启动后因来源未来停止

实际启动候选`50d6ae8+continuous-observation/e52908e45825`；本轮从现有Main的WebSocket `start_live_vision`入口启动一次，
后台只读及结算自动收页启用，运行数据隔离到`build/native-observation-reliability-20261005/live-211158/runtime-data`。
启动程序21:11:58，Main实际进程21:12:02，UI就绪21:12:07；正式开始观察请求21:12:43，
即程序启动至请求约45秒。不能把这段人工编排等待算成Host启动耗时，也不能宣称启动足够及时。
以后应把已有正式请求随Main通信就绪立即发出，避免中间准备延误。

目标HTGame.exe/UnrealWindow，HWND199964/PID3432，未最小化，客户区1920×1080；
WGC item1922×1112，偏移1,31。Host到达READY后停止，实际读回0、接纳FRAME0、SOURCE0、滚动消息0。
最早失败在WGC选择：requestNs=98329649541100，sourceNs=98329665102400，
comparisonNs=98329664116500，aheadNs=985900（0.9859ms），deadlineNs=98334649541100。
读回未到达，原始SystemRelativeTime ticks没有单独记录，不能反推后冒充实测raw；频率记录10,000,000Hz。
这是来源未来拒绝，既不是旧帧积压，也没有进入慢OCR。未来时间根因仍未解决。

线程停止让旧映射代理返回false，UI误报client-area-mapping-changed；日志未证明客户区映射变化。
本轮没有补采或重启：WGC ownerExited=true，Engine受控退出122.9642ms/exit0，随后进程清单确认Host及该Engine不存在。
首次EOF回执exitConfirmed=false，保留这条原始未知状态；不能用之后确认退出篡改首次回执。
程序主窗口仍开着并明确显示观察已停止，本局没有成功观察时间。

仅修对应误报：失效采集所有者不再当作几何否定，错误保留内部原因；普通采集拒绝补现有原始时钟诊断，
未删/放宽future检查、未改时间戳。定向离线检查通过，Host编译0警告0错误。
准备候选`50d6ae8+continuous-observation/edf733cafa06`未重新启动，不能算实机通过。实际运行和准备版本分别记录在
`build/native-observation-reliability-20261005/live-211158/result.json`；原失败session及UI事件完整保留。
下一步只应针对时钟失败做数值定位，另获明确采帧授权后才能再测。仓库识别、真实翻页、本局一次与跨局均未验。

## 2026-10-05 时钟与启动定位（纯离线）

原失败保持不变：source=98329665102400ns，比较=98329664116500ns，request=98329649541100ns，超前985900ns。
微软SystemRelativeTime契约是合成器render QPC的TimeSpan；Ticks为100ns，Stopwatch为Windows QPC，当前10MHz。
代码次序是owner请求→出池→读属性→重新读比较时钟→门禁→读回；没有UTC/进程起点扣减，未发现单位/整数换算或提前采样错误。
9859个QPC刻度超前不能用官方跨线程±1tick解释；原始source/QPC ticks未保存，仍不足以判定实际异常根因。
此前旧帧排队与慢OCR有独立证据；本轮发生在首个读回及OCR之前。

新增有界诊断保留出池和属性读取前后raw QPC、线程、原始来源ticks、比较计数/频率/商余数及比较后独立Win32 QPC/QPF夹测。
FRAME保留真实请求样本；QA原有attempt.requestClock继续给出调用方请求计数。入口观察不是原始请求，不逆算冒充raw。
比较后夹测不会替换门禁值、等待未来时间追上或增加重试。请求后新帧、年龄、身份、映射与期限规则不变。

既有日志显示总启动到请求44.985秒；前段首条日志约3.92–4.92秒（墙钟仅整秒，不能精确归属导入），
Main基准至总线0.110秒、WebView5.115秒、界面page ready5.571秒，界面ready之后35.180秒才收到外部启动连接。
Engine创建调用11.711ms，创建到business ready911.620ms（含导入/资料/OCR/状态，旧日志不能再拆）；generation到ready1.028秒。
新增入口/导入配置与Engine资料、OCR分段标记；真实新启动耗时尚未测量。

`tools/start_native_observation.py`默认只核对文件、依赖元数据与版本。将来显式授权启动后，在同一调用内等待本次Main总线ready并发送一次既有start_live_vision；
无需等WebView。占用总线直接拒绝，不接管旧进程，不编译/补装、不重启。engine READY只报告等待首帧，FRAME才报告观察启动成功。
总线等待最多15秒，首帧确认最多10秒；失败用已有stop_vision_worker结束，停止回执最多6秒，未确认必须报告未知。
这属于正式持续观察的启动编排，绝非独立QA的3次/8秒/10秒；下一轮时钟取证仍先使用该独立QA预算。

修正晚到UI ready覆盖运行/首次失败状态、采集owner已失败仍发READY、后续mapping/stop/EOF覆盖第一终止原因，以及停止时先丢弃未退出Host所有权的问题。
退出未确认显示在界面；旧UI反例和原失败结果均保留。

定向结果：4个Python行为用例通过（最新入口调整再跑其唯一相关用例通过），JS停止提示通过；原未来数值仍拒绝并释放一次、无等待/重试；
仅离线读取本机Win32 QPC与.NET夹测通过。Host及QA编译0警告0错误，Python语法和差异检查通过。未跑旧矩阵、未开助手/Host、未取游戏帧或发送输入。
候选清单和证据在`build/native-clock-startup-20261005/`；本轮改变文件详见candidate.json，另保留原始日志派生的startup-timeline.json和clock-analysis.json。
真实WGC根因与通过、真实启动改善、滚动及完整生命周期仍未验；没有提交、推送或发布，算法文件未改。
