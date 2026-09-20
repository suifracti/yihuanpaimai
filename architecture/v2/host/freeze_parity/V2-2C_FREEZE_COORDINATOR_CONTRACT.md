# V2-2C Freeze Coordinator 离线合同

## 范围与权威边界

本合同只覆盖 `architecture/v2/host/NteHost.Freeze/` 的抽象冻结状态机、fake actuator 验证器，以及对旧 Python 组件的离线逐步对照。
状态机不包含 Win32、全局 hook、窗口发现、`SendInput`、真实滚轮驱动或生产接入；`productionReachable=false` 是本轮硬约束。

`core/warehouse_active_scan_freeze.py` 是旧 PRD-F 行为参考，不是本轮 native 扩展的完整实现。Python 与 native 只在 `scenarios.json` 中标为 `PYTHON_PARITY` 的安全表面逐步比较。多原因、启动默认冻结、session/generation、snapshot fail-closed、逐原因清除和凭据限制属于 native 扩展，列为预期差异，不宣称完全 parity。Python 组件不修改。

## 冻结与恢复

- 有效原因是集合，不是单一的最后写入值。任一原因存在即 `FROZEN`，扫描必须拒绝。
- 重复添加同一原因是幂等 no-op；清除一个原因不会清除其他原因。
- 清除最后一个原因也只进入 `awaitingRearm`；必须显式、重新验证的 rearm 才能进入 `ALLOW`。
- 四个 rearm 条件必须全部为严格的 `true`：人工确认、目标焦点有效、无游戏冲突、无用户接管。四个布尔值本身不能绕过 session 或凭据校验。
- halt 回调异常只记录 provenance；异常不得解冻。

## Session、冻结轮次和凭据

`GenerationId` 是 C 自己的 session identity，`SessionId` 只是其稳定诊断拼写；它不是 A 的 `Generation`，也不表示已存在 A/B bridge。

- 每一次 scan、reason clear 和 rearm 请求必须带当前 `GenerationId`；缺失或不匹配一律拒绝。
- `FreezeRound` 从 0 开始；新增原因、`SessionChanged` 或 `SnapshotResync` 开启新的轮次。
- `IssueRearmToken()` 返回 opaque credential。实现内部将它绑定到 coordinator instance、当前 session、当前 freeze round，并以单次消费状态登记；调用方不能依赖 token 文本格式。
- 缺失、foreign、stale session、过期 round、重复消费的 credential 均拒绝。成功 `APPLIED` 或 `ALREADY_ALLOW` 后消费 credential；新的冻结轮次不能复用旧 credential。
- 新 session 和 resync 都退休旧 credential，并保持 `SESSION_UNVERIFIED` 的 fail-closed 状态。

## Scan 提交边界

`_gate` 内原子完成 permission check 与 scan commit：

1. freeze 在 commit 之前获胜：请求被拒绝，fake actuator 调用数必须增加 0。
2. commit 之后发生 freeze：该已提交操作不能撤销，但后续操作必须被拒绝。
3. actuator delegate 在 commit 之后、gate 之外调用，允许确定性重入；delegate 异常记录为 post-commit failure，不能把实际调用伪装为零调用。

verifier 同时记录 `ScanCommitCount`、fake actuator 实际调用次数、异常次数和 wheel emission 次数。callback 返回 `None` 仍算一次实际调用。

## 对照记录与差异

`run_python_reference.py` 加载真实 Python 类，不重写其行为；fake actuator 在 delegate 进入时先落调用记录。`compare_results.py` 对每个 parity 场景逐步比较安全表面和实际 actuator-call 判据，并对每个 native extension 场景读取 `native_extension_expectations.json`，逐步检查状态、原因集合、恢复结果和实际 actuator 次数。任何未列入合同的差异都使比较失败。

`scenarios.json` 的 `divergenceScenarios` 单列以下预期差异：Python 初始 ALLOW、未知 reason 映射、重复冻结副作用、rearm 计数、逐原因清除 API 缺失、generation/session 缺失，以及 Python rearm 会清除单一 active reason 而 native 要求先逐原因清除的 CONTRACT_GAP-7。三个对应场景只允许这组明确的安全表面/实际 actuator 差异；其他差异仍使比较失败。native expectation 文件不参与放宽 parity 或 divergence 断言。

## 本轮验证边界

验证只使用 fake actuator 和离线线程/barrier；不运行真实输入、全局 hook、窗口或 production。证据应绑定实际源码 commit、父提交、branch、源码/场景/脚本哈希、原始 NDJSON、逐步比较、退出码和明确预期文件清单。完成后仅报告 C 离线范围待外审，不延伸为 Integration 或生产验收。
