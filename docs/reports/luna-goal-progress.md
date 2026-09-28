# Luna Goal 进度

更新日期：2026-09-20

## 执行基线

- 唯一仓库：`D:/yihuanpaimai`
- 分支：`codex/consolidate-workspace`
- HEAD：`cb86697c976a0658f5e301f5e199b269f26a14e6` (`feat(v2-2): add offline Integration I1 safety chain`)
- 工作区：继承目录整合及用户未提交改动；不 reset、不 clean、不创建备份或外部 worktree。
- 当前目标：复用 V2-2 A/B/C/I1，补真实观察桥、实际帧传输、真实 Python Engine、隔离状态恢复和可复算验收；默认关闭，不向真实游戏自动出价、购买、出售或发送输入。
- 协议/业务边界：协议 1.0.0、Canonical v7、旧估值数学核心和实验资格边界保持不变。

## dirty 范围

G0 初始检查确认工作区包含已有修改和未跟踪文件，范围见 `build/goal-luna/baseline/git-status.txt`。这些内容均视为用户已有工作，后续只对本轮明确归属文件进行修改和提交。

## 当前工作包

- `G0`：整理当前基线与复现入口（已通过）
- `G1`：真实 WindowMonitor 观察桥和 raw revision fence（核心桥已通过；完整交付仍待 G2–G5）
- 工作包目录：`build/goal-luna/{baseline,native-bridge,frames,engine,recovery,soak}`
- 当前下一步：交付前复核最终候选和验收报告；不再追加无新风险依据的全量回归或长稳。

## 文件所有者

- 主代理：`architecture/v2/host/NteHost.WindowMonitor/`、`architecture/v2/integration/` 生产适配、V2 Engine 业务接入、CurrentMatch/归档的必要最小修改、G4 合并和最终交付。
- 帧通道：当前由主代理维护，限定为 `architecture/v2/host/` 的新帧生产/消费模块与 `build/goal-luna/frames/` 验收工具；协议契约变更须先证明必要性。
- 独立证据：当前由主代理维护，限定为 `tools/`、`tests/` 独立验收文件和 `build/goal-luna/` 证据。

## 通过/失败项

- 已有迁移后 Python 定向结果：53 项通过，证据 `build/workspace-consolidation/python-tests.json`；需要以本轮源码身份重新复核。
- 已有迁移后 I1 离线结果：11/11 通过，证据 `build/workspace-consolidation/integration-summary.json` / `integration-raw.ndjson`；来源字段为空，只能作为迁移历史记录，不能替代本轮绑定证据。
- G0：通过。当前 HEAD 上 I1 verifier 11/11 通过；V2-0 合同回归 46/46 通过；V2-1 主机监管回归 28/28 通过；53 项 Python 定向回归通过。重建产物和原始日志在 `build/goal-luna/baseline/`，I1 机器证据在 `build/goal-luna/baseline/i1-evidence/`。
- G0 限制：I1 仍明确是 fake source/observer/actuator 离线范围；V2-1 的 MMF 仍是生命周期探针，未写帧头/像素，也未发送 `FRAME_READY`。桌面受控窗口和真实窗口观察尚未纳入本轮通过项。
- G1：已添加生产 `WindowMonitorObservationSource`，由真实 `WindowMonitor.ReadIntegrationObservation()` 原子提供快照、派生事件、raw revision 和 pending/drop fence；`IntegrationWindowObservation.HasGap` 现检查完整 raw revision 序列，可拒绝内部间隙而非只检查两端点。
- G1 离线反例：I1 verifier 扩展为 12/12；I12 `SOURCE_REVISION_GAP:0->2` fail-closed 且 raw 调用为 0。证据在 `build/goal-luna/native-bridge/integration-summary-g1.json` 和 `integration-raw-g1.ndjson`。
- G1 真实受控窗口：真实 Win32 hook 已安装，受控窗口进程产生真实事件；raw revision 读数覆盖 1–39，最终 observation 无 pending，dispose 后无残留回调。证据在 `build/goal-luna/native-bridge/controlled-window/monitor.json`、`session.ndjson` 和 `python-controlled-window-suite.log`。
- G1 受控窗口 Integration：新增 `WindowMonitorObservationSource -> IntegrationCoordinator` harness，真实受控窗口链路的正常动作通过；焦点丢失和窗口重建后的动作均拒绝，计数型 raw backend 没有新增调用。证据在 `build/goal-luna/native-bridge/controlled-integration/integration-result.json`；明确 `productionReachable=false`、`realInputExecuted=false`。
- G1 修正：`ReadIntegrationObservation()` 现在返回“上一次稳定 raw cursor”作为批次左端点，避免完整的 `[1,2,3]` 批次被错误解释为 `3 -> 3` 的 revision gap；修正后的受控 Integration 证据已重新生成。
- G1 回归归因：受控窗口套件核心场景通过；聚合结果唯一失败为既有 V2-1 的 V2-0 artifact guard（`dotnet_contract_results.json` 非 timestamp-only），且本轮独立 G0 的 V2-1 28/28 已通过；另有 1 个 Windows 前台抢占环境 skip。该聚合结果不作为 G1 全绿证据。
- G2：核心实际帧闭环已通过。`MmfFrameRingWriter` 在固定 64-byte header / 4 槽 / BGRA8 v1 映射中写入像素和元数据；真实 Python Engine 以 `FILE_MAP_READ` 读取、校验 header/stride/geometry/corner checksum，复制像素后发送 `FRAME_ACK`，再由既有 `NTEVisionPipeline` 生成 `PERCEPTION_RESULT`。`run-normal-v3` 证据显示 READY、字节哈希一致、ACK 释放、感知结果、隔离 `CurrentMatch` 状态和 canonical history 均成功；Engine 未申请写视图。来源图像是 replay fixture，`realInputExecuted=false`，不代表真实游戏输入。
- G2 不变量探针：`run-frameprobe` 已证明四槽全锁时新帧被丢弃且旧槽不覆盖；错误 session/sequence ACK 和重复 ACK 均拒绝；只有精确 ACK 后槽可复用；超过 1920×1080 明确拒绝。证据保留在 `build/goal-luna/frames/`。
- G2 部分写入：`run-partialwrite` 注入“像素已复制、头部复制失败”，结果为 `ERR_BUFFER_UNAVAILABLE`、`CaptureFailureCount=1`、无头部发布、全部槽回到 `Free`。
- G3：真实 Engine 在 READY 前加载 `assets/catalog_065.json`、RapidOCR、`NTEVisionPipeline`、`CurrentMatch` 和隔离 history store；`commandprobe` 覆盖重复 ID、同 ID 不同载荷、过期和旧会话；`recoveryprobe` 覆盖硬终止、进程检测、重启、状态同步和同局 ID；`route-comparison.json` 比对既有业务入口与 V2 投影，保持 DRAFT/replay 且不把缺失报价写成 0。
- G4：已完成本轮实际影响范围的最小边界。ACK/消费者退出/坏头等矩阵在 `build/goal-luna/frames/fault-matrix-summary.json`；模型加载失败和状态文件不可写分别在 `fault-model-load-v2/`、`fault-state-unwritable-v2/` fail-closed；受控窗口只读捕获在 `native-bridge/readonly-capture/capture-result.json`，包含健康帧、失焦拒绝、空帧/小分辨率/黑屏/低对比度/无效句柄诊断。真实游戏仍未声称通过。
- G5：按本轮风险完成最小充分稳定性检查：有界四槽、部分写入回收、恢复换代、正常退出和最新候选入口均通过；没有未解的资源累积证据，因此未安排固定两小时长稳。候选入口为 `tools/v2/run_v22_framepipe.ps1`，当前候选目录为 `build/goal-luna/frames/candidate-final/`。

## 运行进程与日志

- G0 已启动并正常退出的短时 Host/Engine 验证进程均已结束；未启动真实游戏输入。
- 所有本轮构建、测试、日志和原始样本写入 `build/goal-luna/`；测试进程使用项目内 `TEMP/TMP`，未改变全局 Python 或系统配置。

## 外部依赖

- Python：`build/takeover_20260905/repro-venv/Scripts/python.exe`
- Node：`runtime/node.exe`
- .NET SDK：10.0.203。
- 真实游戏/真实对局/跨电脑设备：当前未承诺可用；受控窗口、录像回放和真实游戏分别记账。

## 当前判定

本轮目标范围的 G0–G5 最小交付证据已齐，当前候选可复算；范围仍严格限定为回放素材、受控窗口和隔离 Engine。真实游戏接管、真实本人获胜实录、跨电脑部署和长时间压力曲线未验收，不得据此宣称完整真实游戏产品通过。
