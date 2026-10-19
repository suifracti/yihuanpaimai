# 后端任务单：修复 main 上的离线 CI（2026-10-19）

> 执行方：后端（GPT / Grok）。规划：Claude（前端）。以 GitHub 为准。
> 本单只修复测试与实现脱节，**不改变已决定的产品行为**；遇到需要改行为才能变绿的地方，停下来交用户决定。

## 背景

- `.github/workflows/offline-contracts.yml` 只在 **pull_request** 时运行。最后一次运行是 10-12。
- 10-13 至 10-16 有多个提交直接推到 `main`（fffe961、ed3b1ff、fd26eb1、b885e36、e11f7f8、a85eec9、927aeb4、892525a、bf4e8df 等），这些提交都没有经过 CI。
- 结果是 `main`（5b4736c）本身就是红的。PR #52（纯前端）上看到的两个红灯都来自 `main`，与该 PR 无关。

## 工作方式（必须）

1. 从最新 `origin/main` 建分支（例如 `grok/ci-repair-20261019`），**开 PR**，让 CI 跑。不要直接推 `main`：CI 只在 PR 上跑，直推正是这次问题的来源。
2. 每一项单独提交，提交信息写清“为何是测试漂移/为何是行为修正”。
3. 禁止：跳过、删除或放宽测试来变绿；恢复固定的 16 SOURCE / 32 请求 / 70 秒额度（见 `AGENTS.md`）；改动 `core/main_window.*`、`core/auction*.css`、`core/overlay_alpha.html` 等前端文件（前端归 Claude）。
4. 完成标准：PR 上 `Python offline half-viewport contract` 与 `.NET 8 offline scroll diagnostics` 都为绿；然后合并，并同步 Obsidian 交接。

## 任务清单

### T1 `.NET` — SOURCE 额度断言过时（已验证修法）

状态：已由 #53 完成。

- 失败：`tests/native_scroll_diagnostics/ContentRecheckChecks.cs:176` → `SOURCE budget is not reset`；同文件 `:159` 有同类断言。
- 原因：`WarehouseEvidenceLease.cs:67` 已改为 `MaxSources = int.MaxValue; // no collection quota`，`remainingSourcePages` 恒为哨兵值。测试仍按 16 页倒数。
- 修法：两处断言改为 `== WarehouseEvidenceLease.MaxSources`，说明文字改成“SOURCE 额度保持不限”。同一断言中“不重置/不续期 deadline”的其余检查保持不变。
- 已在 Linux .NET 8 上验证：改后 `--adapter-presend-only` 与 `--second-scroll-only`（CI 跑的两个模式）全部 PASS。
- 附带发现（CI 不跑，建议一并看）：不带参数的完整模式在 `Program.cs:110` 报 `warehouse-changed reports exact failed check without sending`。请判断属于测试漂移还是真实回归，并在 PR 里说明。

### T2 Python — 自动收仓停止路径的测试替身缺方法

状态：已由 #53 完成。

- 失败：`test_native_delivery_contract …test_business_close_after_admission_late_frame_and_durable_attempt_do_not_duplicate` → `'Source' object has no attribute 'end_collection'`。
- 原因：`bf4e8df` 让 `NativeWarehouseAutoCapture.stop()`（`app/native_warehouse_auto_capture.py:817-825`）在未激活时先 `close_source('USER_STOP')` 再 `intake.end_collection('USER_STOP')`。测试替身 `tests/test_native_warehouse_auto_capture.py` 的 `class Source`（`self.intake = self`）没有 `end_collection`。
- 修法：给替身补 `end_collection(reason)`，**模拟真实语义**（参考 `app/native_warehouse_intake.py:437`）：没有页时走 `cancel_manual_capture`，有页时走 `finish_manual_capture('INCOMPLETE')`。不要只返回 `{'ok': True}`。
- 需要决定：补完后 `test_native_route_never_calls_legacy_and_changed_scope_rejects_confirmation` 的期望会从 `[('CANCEL',)]` 变成 `[('CLOSE','USER_STOP'), ('CANCEL',)]`。如果 `bf4e8df` 停止时先关 source 是有意行为，就更新期望并在提交里引用 `bf4e8df`；如果不是有意的，停下来交用户决定。

### T3 Python — 跳过动画回执测试的驱动顺序过时

状态：已由 #53 完成。

- 失败：`test_native_half_viewport_flow …test_skip_animation_receipt_cannot_cross_match_or_claim_completion` → `command` 为 `None`（第 268 行）。
- 原因：现在流程是 `WAIT_STABLE → tick → 再 deliver` 后才发 `SKIP_ANIMATION`。另外 fd26eb1 规定“可见内容已稳定时即使粉色按钮在也继续滚动”。所以只投 `viewport(0)` 时，不会产生跳过命令，而是会走 `SCROLL`。
- 修法：参照同文件 `test_skip_animation_retries_unknown_on_fresh_source_then_collects`（第 179 行）：用 `scene(0, revealing=True)` 投帧，`marker.observe` 返回 `animationState: 'UNKNOWN'`，再按 deliver → tick → deliver 的顺序，断言 `f.sent[-1]['operation'] == 'SKIP_ANIMATION'` 后才取 `_pending`。保留原测试的核心意图：跨局回执不能完成，`animationCompletionProven` 不能被当作完成证据。
- 已试：只加 tick/第二次 deliver 而不改成 revealing 画面时，会得到 `SCROLL_PENDING`。这验证了上面的原因。

### T4 Python — 一次性启动器 `monitor()` 返回值改成二元组

状态：已由 #53 完成。

- 失败（CI 的 M1 步骤）：`test_native_one_shot_runner` 的三个用例 → `cannot unpack non-iterable bool object`。
- 原因：`892525a` 把 `tools/start_native_delivery_candidate.py` 中 `monitor()` 改为返回 `(reason, exit_confirmed)`，`start()` 在第 384 行解包。测试仍 `patch.object(runner, 'monitor', return_value=False/True)`；第 170 行还在 `assertFalse(monitor(...))`，而元组永远为真。
- 修法：替身返回二元组，例如成功用 `('COLLECTION_COMPLETE', True)`，失败或未确认用 `('USER_STOP', False)` 等，按每个用例原本的语义选择。第 170 行改为分别断言 `reason` 与 `exit_confirmed`。

### T5 workflow — DELIVERY 用例数写死

状态：已由 #53 完成。

- `offline-contracts.yml` 的 “Full Native DELIVERY contract” 要求 `DELIVERY_TESTS == 15`，现在实际有 18 个。
- 修法：先确认新增的 3 个用例是有意加入的，再把期望改成 18。更好的做法是改成 `>= 18` 并保留 `failures/errors/skipped == 0`，避免以后每加一个用例就要改 workflow；二选一，在 PR 里说明。

## 验证

- Windows（与 CI 一致）：
  - `python tools/run_tests.py test_native_delivery_contract test_native_one_shot_runner test_native_warehouse_auto_capture test_native_warehouse_intake`
  - `python -m unittest tests.test_native_half_viewport_flow -v`
  - `dotnet run --project tests/native_scroll_diagnostics/scroll-diagnostics.csproj -- build/ci-dotnet --adapter-presend-only`，以及同一命令的 `--second-scroll-only`
- 最终以 PR 上整套 `Offline PR contracts` 为准，两项都绿才合并。

## 不在本单（前端，归 Claude）

以下陈旧测试涉及主窗口 HTML/JS 与桥接白名单，由 Claude 另行处理：

- `test_quality_matrix_layout`
- `test_main_window_lifecycle` 的三个“页面资产 / 桥接动作白名单”用例
- `test_history_match_summary_v1.test_ac12_ui_dom_and_javascript_wiring`
- `test_history_record_warehouse_projection_v1.test_html_and_js_contract`
- `test_warehouse_identity_review_*` 中的 UI 断言

如果其中涉及 Python 桥接动作白名单（`app/main_window.py`），Claude 会在 PR 里点名，由后端确认。
