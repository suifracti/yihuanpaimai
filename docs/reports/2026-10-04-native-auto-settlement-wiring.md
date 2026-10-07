# Native 自动结算收页接线（2026-10-04）

基线 `50d6ae8`，本轮增量保留在当前工作树，未自动提交、推送、发布或打完成标签。
实际源码和候选二进制哈希见 `build/native-auto-trigger-20261004/result.json`。
后续实测准备的候选身份与入口核对见同目录 `readiness.json`：相对原行为证据只补界面说明，
运行链路、Host 二进制和算法未变，复用原定向通过证据；本次只检查 JavaScript 语法和相关差异。
本轮游戏帧 0、游戏输入 0，没有启动助手或游戏。

## 本轮改动清单

| 文件 | 增量 |
| --- | --- |
| `app/main.py` | 已接纳 Native FRAME 后调用既有自动触发入口的 Native 分支；本局一次、结算、网格、TOP/NO_SCROLL、确切原帧和作用域门禁；跳过旧前台准备；只给已接纳事件边界权，迟到事件不能取消当前来源 |
| `app/main_window.py`、`core/main_window.html/js`、`app/config.json` | 默认关闭的启动前“结算自动收页”；运行中可取消；Native 路由禁用旧置顶保护，及时显示启动／保存／停止状态 |
| `core/native_trial_drafts.py` | 隔离目录内持久化本局已尝试标记，恢复也不能二次启动；不编辑账单或身份 |
| `app/native_warehouse_auto_capture.py` | 复用同一收页器，启动前消费一次权限；滚动后同时核对滑块和图像向下移动／重叠；无进展、反向、未知分别停止 |
| `app/native_warehouse_intake.py`、`app/native_warehouse_source.py` | 终止清单、取消原因和旧代际拒绝；保留原图／部分材料；Native 路由声明无需前台准备 |
| `architecture/v2/host/wgc_live_harness/NativeObservationService.cs`、`WarehouseEvidenceLease.cs` | SOURCE 可用与账单冻结分离，显式能力回执；仅待 SOURCE 请求启用现有原始时钟诊断，失败先记录再退出；不改普通 FRAME 选择算法 |
| `tests/test_native_warehouse_auto_capture.py`、`test_native_background_observation.py`、`test_native_warehouse_source.py`、`tests/native_source_contracts/Program.cs` | 新增／扩展触发、换代、旧事件、联合门禁、停止及证据保留行为；假 Host 增加独立 `--settlement-wiring-only` 入口，不重跑旧矩阵 |
| 本设计及本报告 | 授权状态、实际接线和交付边界 |

Engine／CurrentMatch 原完整生命周期、视觉算法、正式资料主表与人工标签未改。
不新增状态机、采集进程、每局人工武装、全局键鼠或激活窗口回退。

## 定向检查

Host 和源码链接的假 SOURCE 契约入口编译均为 0 警告、0 错误。
定向 Python 行为检查通过：同局一次及恢复、新局触发、旧局与迟到超时回调拒绝、异常启动不重试、
取消选项、图像／滑块联合证明、到底／无滚动结束、无进展与未知停止、截止与异常关闭后不再发滚动。
真实隔离 Store 验证换局后原图及旧局终止清单保留，账单文件不变。
新假 Host 分支验证冻结前来源、离场／停止／映射失效、下一局作用域与旧命令拒绝。
这些是假帧／假上下文的契约证据，不是实机滚动或新场景准确率保证。
Python 语法、JavaScript 语法和差异检查通过；旧截图矩阵没有重跑。

## 下一次获实机授权后的启动与停止

源码入口仍为 `app/run.bat`，使用项目 repro-venv 运行 `app/main.py --debug`。
Host 默认选择 `build/native-observation/WgcLiveHarness.exe`；若设置了 `NTE_NATIVE_HOST_EXE`，启动前必须核对覆盖目标。
旧进程不会因重编译自动更新；应由用户正常退出旧助手后打开该源码入口。

在开始观察前选择“后台只读识别”和“结算自动收页”，再点“开始新局观察”；可以在大厅或对局中提前启动观察，
无需等结算再操作。Host 能力回执缺失时不自动收页；合格新结算帧、仓库网格及顶端条件成立后本局自动开始。
“后台只读识别”本身不操作游戏；独立启用“结算自动收页”后才允许项目向指定异环窗口发送滚动消息，
不激活窗口、不使用全局输入。当前配置仍为前台观察／自动收页关闭；本次准备没有启动或修改运行选项。
该会话后续新局继续有效；开始被拒、停止或失败后同局不自动重试。
“采集完整仓库”保留手动路径，与自动路径共用本局一次及运行互斥。

活动收页时按钮显示“停止采集”，只停止当前收页；取消“结算自动收页”同时停止当前收页及未来自动触发。
停止当前收页保留已有页面，本局不重试，选项仍开启时下一局继续；取消自动收页后只读观察继续。
退出助手结束观察和来源租约。界面状态与日志不是子进程已退出证明。

保存顺序、稳定页、图像重叠、滚动条和停止原因在当前 session 的诊断日志与
`trial-drafts/warehouse-intake/` 清单中；逐物品识别在收页结束后进行。
保持指定窗口消息、16 张来源／32 次请求及首次结算起的绝对 70 秒，支持帧仍计入预算。
没有图像与滑块双重进展就停止；从中间开始、未到末尾或证明不足只报部分覆盖。

下一轮用户明确“开始实机”后，从对局中启动上述正式入口与两个选项，一次授权覆盖自然发生的完整链路，
不在结算阶段临时构建、逐节点询问或每局重新武装。不另插入独立 QA 采帧；已有离线检查继续复用。
开始观察后及时记录启动及 READY／目标身份；自动触发后及时记录 `automatic-trigger` 和首个 `original-saved`，
逐物品分析留到收页结束后。退出结算、窗口失效或局次换代须终止旧任务，保存旧局原图和清单；
冻结前材料仅为本局证据。失败保存原始诊断并结束，不恢复旧任务或补采绕过本局一次与预算。

日志定位：`build/native-observation/runtime-logs/run_*.log` 是启动日志；新 `session-*/` 内
`host-trace.jsonl` 的 `warehouse.source.request_clock` 记录 SOURCE 原始时钟数值，
`host-status.jsonl`／`ui-frame-events.jsonl` 记录接纳与状态，`main-diagnostic.log` 记录自动触发、
原图保存、滑块变化、图像重叠和结束原因。原图及终止清单位于隔离 `trial-drafts/warehouse-intake/`。
按实际节点核对请求／来源／读回／比较及换算数值、真实图像与滑块变化、本局一次、离场取消和自然发生的跨局换代。
未发生下一局就标未验，不为补齐节点无限等待；消息发送成功不算滚动成功，多页不算完整覆盖。

## 保留边界

未来时钟根因与真实滚动效果仍未验，不能删除检查、改时间戳或放宽新鲜度。
本轮仅准备；下一次明确授权后验证上述正式生命周期。独立 `tools/native_qa/run_qa.py` 的
3 次／8 秒工作／10 秒实际退出核实预算保持独立，本次生命周期准备不执行该入口或新增一轮采集。
独立 QA 通过不能代替生产 SOURCE、覆盖、完整拍卖或身份确认。
项链／卡丁车拆件、57px 周期和品质块未知仍保留；观察框数不是准确物品总数。

## 大厅启动后的真实失败与单点修复

用户明确授权大厅提前启动后，20:55:40 通过现有 WebSocket `start_live_vision` 启动正式 Native 入口，
启用后台观察和结算自动收页。目标 HTGame.exe／UnrealWindow、HWND 199964、PID 3432，
客户区 1920×1080，偏移 (1,31)，未最小化且失焦。接纳 180 张真实普通 WGC 帧，均在大厅阶段。
随后 `source-clock-stale-at-readback` 拒绝来源 10949331925000ns、读回 10954541561500ns，
相差 5209.6365ms；Host 停止，Engine 正常退出（shutdown 162.9982ms），没有重启或补采。
没有 SOURCE 请求、仓库页面或滚动消息，不构成完整一局、结算、未来时钟或跨局验收。
真实原始状态和边界见 `build/native-auto-trigger-20261004/live-start-result.json` 及其 session 路径。

最早断点是普通 FRAME 仍使用旧的 `WaitOne → TryGetNextFrame` 单次出队入口。
前一帧 Engine 感知耗时 4678.4123ms，之后读到该期间排队的旧来源；既有请求后选择器只用于 SOURCE。
本次仅将 `WgcCapture.Capture` 委托给既有 `CaptureAfterRequest`，在感知完成后固定新请求时刻，
丢弃请求前排队帧并在原 timeout 内等待新帧；不改 SOURCE 调用者的时刻或绝对截止，
不修改读回／发布新鲜度、未来时钟、映射、局次、身份或账单门禁。NativeObservationService 只更新相应注释。
Host 针对性编译 0 警告／0 错误、相关差异检查通过；没有重跑旧矩阵或新的真实采集。
自动收页已关闭，真实修复后连续链路仍未验；新的候选 DLL SHA256 为
`b6bed304d1cf804efc46840b392aec02b4116085856d1379c6dd664f5a833d25`。
