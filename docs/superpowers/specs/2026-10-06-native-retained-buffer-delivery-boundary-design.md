# 持续帧池交付边界：两次失败核对与最小方案

状态：下文保留原研究与提案；用户已批准暂持接入，实施与定向验证已完成，结果见 [接入结果](../../reports/2026-10-06-native-retained-boundary-integration.md)。本轮未采游戏，游戏验收待另行确认；严格来源、场景、身份、数量及记账门槛未改。

当前候选：`50d6ae8+delivery-observation/88211996f55c`，HEAD `50d6ae8a0edb646f0b7defc6f034abaaaf98f632`。
Host：`build/native-delivery-20261006/host/WgcLiveHarness.exe`，SHA256 `70c46802eaa860dc9e7d1295d1940bf96f2c86e4a5b35e38f57c1b723409ce02`。

## 1. POOL_BOUNDARY_UNPROVEN 的已证事实与缺证

两次原始记录分别保留在 `build/native-delivery-20261006/lifecycle-real-01`、`lifecycle-real-02`，对应 Host 会话 `session-0cd911f7c41f42bfad52821aaf44dbec`、`session-c8ee0b55604e495396677aa741701cdd`。本轮提取索引：`build/native-pool-boundary-20261006/two-breakpoints-evidence.json`。

以下仅为**各次最终失败请求**的清池操作；相对时刻均以该请求开始为零，单位 ms，QPC 频率均为 10,000,000 Hz。

| 会话 | 请求时间 ns | 三次取帧返回 | 三次调用起止 ms | 调用本身耗时 ms | 请求至第三次返回 |
|---|---:|---|---|---|---:|
| 01 | 172648916611700 | 非空、非空、非空 | 0.0100–0.0296；0.1486–0.1552；1.3774–1.3902 | 0.0196；0.0066；0.0128 | 1.3902 |
| 02 | 173304505156600 | 非空、非空、非空 | 0.0325–0.0639；4.0821–4.1147；4.2415–4.2821 | 0.0314；0.0326；0.0406 | 4.2821 |

日志未保存这些丢弃帧的来源属性、逐帧身份、属性读取/释放时刻及 FrameArrived 提示。因此不能复原每张是请求前库存还是清池期间新交付，也不能给出实际进入池的精确时刻。调用间隙包含属性读取、检查、释放和调度，现有日志不能再分摊。处理帧诊断仅保留有限操作，不能把这两个失败请求扩写成全部正常清池请求的逐次记录。

`DeliveredFrameSelector.Select` 当前每取到非空帧就立即 `Dispose`，再进行下一次取帧。3 次的依据是项目设计的“2 个缓冲＋一次空确认”，不是官方保证。[官方捕获说明](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)说明 Dispose 会把缓冲归还帧池；[CreateFreeThreaded](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframepool.createfreethreaded?view=winrt-26100)使用内部工作线程，并按 numberOfBuffers 配置存储；[TryGetNextFrame](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframepool.trygetnextframe?view=winrt-26100)提供下一帧/空结果，没有持续生产时必在三次内空池的保证。

可复现的实现问题是：**把会随释放继续补充的帧池，当作固定的两张库存清理**。游戏两次失败的逐帧归因仍缺证，不据此断言所有丢弃帧都是新交付；也不能把第三张非空简单记作“旧帧未清完”。

## 2. 一次自建持续出帧对照

执行前固定计划在 `build/native-pool-boundary-20261006/plan.json`。结果与原始事件在 `build/native-pool-boundary-20261006/controlled-034b3aaaff/`。

- 自建 640×360 DXGI 窗口，无私人内容，非激活显示；WGC 只接当前子进程自有 HWND，无外部窗口参数。
- 独立呈现线程持续生成 nonce＋计数画面；WGC/取帧/读回均由独占线程完成，池缓冲数 2。
- 总共 6 次边界请求：立即释放 3 次、暂持缓冲 3 次，每次最多 3 次清池取帧。工作 8 秒/实际退出 10 秒；未重复实验。
- 有意设置 30 ms 取帧间隔，并读回丢弃帧验证自建计数；不是两次游戏的 1.39/4.28 ms 时序复刻。

| 策略 | 三次请求的清池结果 | 见空次数 | 后续交付 |
|---|---|---:|---:|
| 每帧立即释放 | 每次均非空、非空、非空 | 0/3 | 未进入选择阶段 |
| 暂持最多两个缓冲 | 每次均非空、非空、空 | 3/3 | 3 张推进的交付帧 |

第一组第 1 次请求时自建提交计数 148，清理得到 80、86、150；150 是请求后提交的内容，证明本条件下清池确实可混入新的生产内容。其他两次末帧计数仍不晚于请求时计数，不能都标为请求后渲染。

实际退出 2,490.0545 ms，工作/退出均在预算内，退出码 0。18 张取出的帧全部释放，最大暂持 2 张；编译 0 警告/0 错误。呈现计数 584 是调用数量，不是实际显示完成或 WGC 帧数。Present 与 CPU 提交事件不能证明真实显示完成；FrameArrived 是提示，未证明与特定帧一一对应。对照支持有界暂持方案，不能写成游戏已通过或所有驱动环境保证成立。

## 3. 建议的最小生产增量（待确认）

保留空池边界，但改变缓冲所有权顺序，使边界能在持续生产时有界建立：

1. 沿用现有独占 WGC 线程、2 缓冲池与最新待处理帧队列。请求建立后丢弃待处理旧候选。
2. 最多进行 3 次清池取帧。非空的前两张暂持，不在两次取帧之间释放，不做 OCR/业务保存/正式投影。
3. 取得空结果时记录边界及暂持数量；在 finally 中释放暂持帧，记录释放完成时刻，然后按原截止等待并取得下一张交付帧。
4. 第三次仍非空、池容量不符、停止、身份/映射失效或截止均失败；释放所有已取得帧。不扩大次数、不等到空、不自动重建池或降级。
5. 记录池容量、边界类型 `retained-pool-buffers.v1`、逐次取帧/属性读取/释放区间及丢弃 ordinal/原始来源值；FrameArrived 仍只标提示。校验边界与释放完成先于选中帧出池。所有异常均释放且不发布。

**合同差异：**旧版本以“每张立即归还后仍看到空”作见证；建议版本以“此前取出的缓冲仍被暂持时看到空，随后释放并取得交付”作见证。保留本地空边界语义，但所有权顺序及 proof 字段改变，需确认后才接入。暂持的是池已有的最多两张表面，不新增两个 BGRA 副本；既有 BGRA/MMF/SOURCE 所有权与待处理最多一张不变。

它能证明本地请求后的池边界及其后交付，仍不能证明请求后渲染、来源绝对年龄，或排除上游迟交/重放。原始来源值及 FUTURE 状态不改；严格模式不变；局代际、捕获 ID、窗口、映射、哈希、取消、稳定页及图像位移＋滑块联合门禁独立有效。空边界/新捕获 ID 不等于页面稳定或滚动成功。身份、数量、价格与正式账单门槛不变。

预计涉及 `DeliveredFrameSelector.cs`、`WgcCapture.cs`、`CaptureDeliveryProof.cs`、`app/native_capture_delivery.py` 及对应定向行为用例；如 proof 校验需要补字段，只调整相应传输/验证位置，不改 MMF 协议、SOURCE v2 原图核对、业务生命周期或识别算法。

确认后仅验证：持续生产下有界建立边界；第三次非空仍拒绝；异常/取消/截止逐帧释放；原始 FUTURE 不被改成严格通过；受影响的 proof/SOURCE 同图与稳定页见证。已有无影响用例不重跑。`Recreate` 虽有官方丢弃帧语义，但涉及池代际与稳定证据失效，本轮不采用或自动回退。

## 4. 第二轮四帧的场景、局代际与触发门禁

独立核对的原图是第二会话的 `first-frame.bmp`（帧 1）、`latest-settlement-frame.bmp`（帧 4）；两者 BGRA 哈希均对应各自帧记录。实际像素都有“竞拍结束”标题，第一张尚在揭示动画、第四张内容已变化。帧 2/3 未保留原图，仅有哈希和识别记录，明确缺图。四条帧记录哈希不同，不能据此证明上游未重放。

分类入口：`core/scene_anchors.py:settlement_title_visible` 对标题 ROI 模板匹配，阈值 0.88；两张保留图得分 0.98385、0.98240。`core/vision_pipeline.py:2664` 进入结算路线，`:1549` 起的解析设置 SETTLEMENT，`:1558` 还显式设置 inAuction=True。因此 **inAuction=True 不等于已观察到前置对局**。

用户说从大厅开始不能被分类输出否定：可证明的仅是两张交付图像显示结算。不能证明它们在读取时刚渲染，也不能重建未观察间隔中的游戏行为。第一次最后采集至第二次首帧约隔 647.67 秒；这不是第二次程序启动耗时，第二次请求至首帧为 4.57 秒。

旧状态核查：第二次 coldBoot=true、resumeSameMatch=false、新工作目录无 resume-state.json、无 state.restored 记录；Engine 从空上下文新建 recordKey `replayfile_70b3ec64a26711d0c7a8`、matchGeneration=1，与旧会话 key 不同。Main 启动时在 `app/main.py:7728` 清空 `_NATIVE_DELIVERY_ANCHORED_MATCH`。无旧会话恢复的证据；同会话跳过全扫描时可沿用上下文，因此不能把每条分类都当独立完整 OCR。捕获 poolEpoch 变化不是局代际变化。

未触发收页的两个独立阻断：

- `app/main.py:3125` 只在合格 `scene == IN_AUCTION` 的本局观察后建立 anchor。本轮四帧全为 SETTLEMENT，没有本轮对局锚点；旧会话锚点已清空。
- `app/main.py:1610` 要求同局 anchor 且 `currentAdviceQualified is True`。本轮四帧该值均 False；日志不足以把这个 False 进一步归因到某个确切 ROI。

两项均可阻止收页，且尚未满足完整的稳定结算/仓库/顶端链。因此 SOURCE 请求 0、保存原页 0、滚动 0 合乎当前门禁，不能改 inAuction、复用旧局 anchor 或绕开稳定性来凑触发。最小方案是先修有界取帧边界，使大厅→对局→结算能持续观察；同时把触发拒绝的实际分项原因写日志，便于之后一次授权链路验收，不新增状态机或放宽门槛。

## 5. 启动链与控制身份

本轮查询确认 Python PID 12580 的父进程为 30932，二者启动约差 29.3 ms：30932 是 venv Python 入口，12580 是其实际 Python 运行时，两者命令均为 app/main.py。属于同一启动链，不能仅按两个 PID 判独立实例。

本次控制总线为 `127.0.0.1:8766`，监听归属 PID 12580。另一个 `:::8766` 的 PID 5016 是 svchost.exe，不属于本次控制的项目链，未停止它或任何其他实例。

第二 Host observationSessionId 为 `native-live-f366237810f94cf3aaccb0dd037aa355`，工作目录和固定 Host 哈希如上，命令选择 background-readonly/wgc-delivery-v1。历史 Host OS PID 未记入日志，退出后无法从当前进程表补证。Engine 启动日志记录 launcher PID 29988、Engine 自报 PID 10960，但后者物理父子关系缺证。建议随准备/退出回执增加 Host PID/父 PID、Engine launcher/实际 PID 与总线身份；本轮未改生产日志。

## 本轮文件与停止边界

新增维护 QA：`tools/native_qa/pool_boundary_probe/{Directory.Build.props,PoolBoundaryProbe.csproj,PoolBoundaryProbe.cs}`、`tools/native_qa/run_pool_boundary_probe.py`，以及本设计。原始证据在 build 内；未改生产源码、识别共享文件、标签或历史，未提交/推送/发布。

下一步只待确认第 3 节缓冲所有权/交付见证增量及第 4/5 节诊断增量；确认后先定向离线接入，不自行启动游戏验收。本轮自建对照已结束，不追加环境或采样。
