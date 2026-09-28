# Luna Goal 验收报告

日期：2026-09-20  
仓库：`D:/yihuanpaimai`  
分支：`codex/consolidate-workspace`  
基线 HEAD：`cb86697c976a0658f5e301f5e199b269f26a14e6`

## 结论

本轮 V2 试验候选达到 G0–G5 的最小充分交付条件：真实 Host、真实 Python Engine、固定 MMF 帧环、既有视觉入口、隔离 `CurrentMatch`/canonical history、同局恢复、受控窗口只读捕获和相关故障边界均有可复算证据。

这不是“真实游戏接管通过”。所有候选运行均关闭真实输入；正常业务帧使用带 `sourceKind=replay_fixture` 的现有图片，实时捕获使用项目自有受控 Win32 窗口。真实游戏、真实本人获胜实录、跨电脑部署和完整长稳曲线保持未验收。

## G0–G5

| 工作包 | 状态 | 证据与判断 |
|---|---|---|
| G0 基线 | PASS | `build/goal-luna/baseline/`；I1 11/11、V2-0 46/46、V2-1 28/28、Python 定向 53 项通过。工作区 dirty 范围已保留，未 reset/clean。 |
| G1 真实观察桥 | PASS（受控窗口范围） | `build/goal-luna/native-bridge/integration-summary-g1.json`；I1 12/12，连续 raw revision gap fail-closed；真实 Win32 hook raw revision 覆盖 1–39，结束时无 pending/残留回调；`controlled-integration/integration-result.json` 再证明真实观察源到 A/B/C 协调器的正常/失焦/重建边界。 |
| G2 实际帧传输 | PASS | `candidate-final/host-result.json`、`engine_mmf_probe.json`、`frame_records.ndjson`；64-byte header、4 槽、BGRA8、只读 Engine 映射、哈希/几何/序号/ACK/感知结果均闭环。`run-frameprobe` 覆盖满环不覆盖、错 ACK、重复 ACK、超限帧；`run-partialwrite/partialwrite-result.json` 覆盖部分写入回收。 |
| G3 真实 Engine 与业务投影 | PASS（最小投影） | READY 前加载 catalog、RapidOCR、`NTEVisionPipeline`、`CurrentMatch`、history store；`command-result.json` 覆盖去重/载荷复用/过期/旧会话；`candidate-final/route-comparison.json` 显示既有入口与 V2 的 scene/inAuction 一致，状态仍 DRAFT/replay。 |
| G4 恢复、只读捕获、故障 | PASS（已实现范围） | `recovery-result.json` 覆盖硬终止、检测、换代、状态同步和同局 ID；`fault-matrix-summary.json` 覆盖 ACK/消费者退出/坏头等；`fault-model-load-v2/` 与 `fault-state-unwritable-v2/` 在 READY 前 fail-closed；受控窗口捕获和失败诊断见 `native-bridge/readonly-capture/capture-result.json`。 |
| G5 稳定性与交付 | PASS（最小充分） | 满环、部分写入回收、重启换代、正常退出和最新候选入口均通过；没有未解的资源累积证据，因此按规则未启动固定两小时长稳。候选入口和依赖已固定。 |

## 当前候选

## Integration I1 受控窗口追加

新增受控窗口 harness 运行真实 `WindowMonitorObservationSource` 和 `IntegrationCoordinator`，但使用 `CountingRawInputBackend` 作为原始后端：

- 正常焦点下动作通过，计数型 raw backend 调用 1 次；
- 焦点切换后动作拒绝，raw 调用数保持 1；
- 目标窗口重建后身份变化被拒绝，raw 调用数仍保持 1；
- 证据为 `build/goal-luna/native-bridge/controlled-integration/integration-result.json`，其中 `productionReachable=false`、`realInputExecuted=false`。

本追加只证明受控窗口的生产观察适配和 A/B/C 边界，不把受控窗口冒充真实游戏，也不构成真实 `SendInput` 或真实产品窗口验收。

唯一当前候选运行目录：`build/goal-luna/frames/candidate-final/`。

启动入口：`tools/v2/run_v22_framepipe.ps1`。默认行为是：

- 使用 `build/takeover_20260905/repro-venv/Scripts/python.exe`、Release `NteHost.exe` 和 `architecture/v2/host/engine_v22/nte_engine_v22.py`；
- 将临时目录、BGRA8 输入、Host 结果、Engine 日志和隔离状态写入 `build/goal-luna/frames/`；
- 从 `tests/fixtures/real_snapshots_4d2d1j/fixture_settlement_client_sanitized.png` 准备回放帧；
- 不连接真实游戏，不执行键盘、鼠标、出价、购买或出售动作。

运行方式：

```powershell
& .\tools\v2\run_v22_framepipe.ps1
```

运行依赖：Python 3.10.20 复现环境、.NET SDK/runtime 10.0.203、项目内现有 OpenCV/RapidOCR/业务依赖；Node 仍使用 `runtime/node.exe`，本轮未改变估值数学核心或 Node 求解器。

## 关键结果

`candidate-final/host-result.json`：

- Engine `READY`，`engineBusinessReady=true`；
- 帧 `1920×1080`、stride `7680`、BGRA8、buffer length `8294400`；
- source SHA-256：`04246fe2a9949d6dd2fed41af938a93151d2405570e88db96c73a7179375d1cc`；
- 传输 raw SHA-256：`74ceb8c310aa1f65736fd9d2462bf92cc0750dc35208cae4ed64a2e7c01e6871`；
- `FRAME_ACK=CONSUMED` 且精确释放槽位，`PERCEPTION_RESULT` 的 `scene=SETTLEMENT`、`inAuction=true`、`bids=[]`；
- `CurrentMatch` 保持 `DRAFT`，`dataOrigin=replay`，同一隔离目录写入状态清单和 canonical history；
- 正常关闭在 2000ms 内完成，未使用强制终止。

受控窗口只读捕获：

- `captureMethod=printwindow`，客户区 `1264×681×3`；
- PNG 哈希为 `6fd370766d15eacc59611a484d910e3b31f3003e7268eb68241ed314c494bf22`；
- 健康诊断 `safe=true`，并确认非前台窗口拒绝捕获；
- 空帧、小分辨率、黑屏、低对比度和无效句柄均返回显式失败原因；
- `automaticInputActions=0`，范围标记为 controlled window，不代表真实游戏。

## 故障与恢复边界

- 无 ACK、错 ACK、旧会话 ACK、重复 ACK、消费者退出、坏帧头已在 `fault-matrix-summary.json` 留存；满环时不覆盖消费者持有的槽。
- 部分写入探针确认像素已写、头部写失败时不发布 `FRAME_READY`，返回 `ERR_BUFFER_UNAVAILABLE`，`CaptureFailureCount=1`，槽位回到 `Free`。
- Engine 模型初始化失败和状态文件不可写都在 HELLO_ACK/READY 前失败，Host 只得到 `ERR_HANDSHAKE_TIMEOUT`，不把 IPC 进程误报为业务就绪。
- 恢复探针先检测进程/管道故障，再创建新 generation 和新 nonce，完成状态 snapshot 同步后进入 READY；恢复后的 match ID、scene 和 DRAFT 状态与崩溃前一致，没有凭空生成胜者、报价或财务字段。
- `commandprobe` 的旧会话测试会使 Engine fail-closed，因此该场景自身的 child exit code 不是优雅关闭证据；正常关闭证据来自 `candidate-final` 和 recovery probe。

## Canonical 十四类边界

| 编号 | 本轮状态 |
|---|---|
| 1 真实本人获胜实录及自动归属 | 未验收；没有用回放或手工字段冒充真实实录。 |
| 2 底部品质出售默认勾选 | 复用既有未受影响证据；本轮未修改。 |
| 3 真实游戏键鼠接管与防干扰 | 部分通过；观察桥和受控窗口只读捕获通过，真实游戏和主动输入未验收。 |
| 4 真实限时全仓滚动与跨页去重 | 未验收。 |
| 5 疑难物品详情采集与关闭恢复 | 未验收。 |
| 6 截止时间与离线继续识别 | 未验收真实实机边界。 |
| 7 离线结算、草稿和胜者名单治理 | 部分通过；本轮证明 DRAFT/恢复无幽灵草稿，未替代完整胜者名单验收。 |
| 8 至少三局真实对局端到端 | 未验收。 |
| 9 连续识别稳定性与内存 | 仅完成本轮生命周期/资源路径的最小检查，未提供长稳曲线。 |
| 10 实时 P95 门槛 | 未验收；单帧处理耗时不等于 UI 展示延迟 P95。 |
| 11 跨电脑/目录带图导出与 manifest | 本地源图、raw 和状态 manifest 已绑定；跨电脑往返未验收。 |
| 12 免费情报专属链 | 未验收。 |
| 13 `tests.test_match_trunk` 历史测试债 | 未在本轮重新裁定。 |
| 14 二维全面可行性与摆放求解 | 未验收，架构迁移不替代数学验收。 |

## 未验证范围

本报告不覆盖真实游戏窗口、真实对局获胜归属、自动键鼠输入、跨电脑部署、正式发布冻结包、固定两小时长稳以及 canonical 十四类中明确列为未验收的业务边界。新增证据和日志均位于项目内 `build/goal-luna/`；没有创建备份、外部 worktree 或正式历史数据。
