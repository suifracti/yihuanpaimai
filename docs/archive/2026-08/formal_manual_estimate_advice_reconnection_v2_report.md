# Formal Manual Estimate / Advice Reconnection v2

## 1. Initial HEAD

`b26ca04faa966fba167f040186a09133214ddf5f`

## 2. Final HEAD

本报告与实现由同一独立 commit 收口；最终 commit hash 见第 31 节及交付回报。

## 3. Tracked status

本 cut 开始时 tracked worktree clean。提交范围仅包含 Manual estimate/advice consumer wiring、必要的浏览器 snapshot hash 修复、focused tests 与本报告；既有 untracked research、mascot、benchmark 与截图文件未纳入提交。

## 4. Compatibility consumer path

`Manual exact venueId/boxId` → `app/main.py::build_manual_alpha_payload` → `core/venue_box_catalog.py::solver_context_translation` → frozen `v06_solver_compatibility_v1.json` → `solverInput.venue/box` → existing `AuctionEngineV06.solveAuctionPipeline`。

Current game truth 仍只保存海贝场、珊瑚场、真珠场及 current boxId。`初级场 · 海贝场`、`中级场 · 珊瑚场`、`高级场 · 真珠场` 只存在于 Solver consumer input，不写回 CurrentMatch/Canonical game truth。Overlay 不维护第二套映射。

## 5. Manual Solver input path

`overlay_alpha.html::collectFacts` → existing `apply_manual_facts` bridge → native CurrentMatch/DRAFT → `build_manual_alpha_payload` → frozen compatibility translation → optional live-shadow probabilityProfile → Overlay `scheduleLocalSolver` → `AuctionEngineV06.solveAuctionPipeline` → `paintResult`。

新 match 在 `solverAvailability=UNAVAILABLE` 时不调用 engine fallback，避免生成 `unknown_match` snapshot 或闪回上一局建议。

## 6. probabilityProfile / support path

Manual 与 Vision HUD 复用同一 `core/live_shadow.py` profile producer。数据只来自 `resolve_runtime_history_path()` 指向的 per-user RuntimeDataRoot；repo research history 不参与 production Advice。

Native 仅当 `supportEligibleRecordCount > 0` 时 attach profile。零支持记录、profile 失败或 history unavailable 均不会被包装成 historical support。

## 7. Inputs restored

- 已有 intrinsic facts：Q、goldAvg、purpleCount、known Gold/Red/Purple、exact venue、exact box、field condition。
- 新恢复最小 bidding facts：`leaderBid`（当前出价）与 `targetProfit`（目标利润）。
- 未引入 debug 参数、第二套事实模型或 Main Solver API。

## 8. Current bid semantics

`leaderBid` 是 decision-layer 输入，unknown 与 0 分开，负数/非整数 fail-soft。只改变 current bid 时，同一次 intrinsic facts 的 P20/P50/P80 与 recommendedMax 不变；existing v0.6 action threshold 随 bid 相对 recommendedMax 改变。

代表结果：100,000 → `仍在目标利润区 · 可以继续`；600,000 → `超过边际追价线 · 建议停止`。

## 9. Target profit semantics

原 adapter 的 silent `30000` fallback 已从 Manual 数据语义中移除。产品保留 v0.6 的 30,000 默认，但现在以可见、可编辑的 `VISIBLE_PRODUCT_DEFAULT` 输入呈现，不再冒充用户未表达的事实。

当前 v0.6 decision implementation 不用 targetProfit 改写 recommendedMax；测试锁定 targetProfit 不污染 P20/P50/P80。它被保留为显式 decision configuration，而不是 intrinsic prediction truth。

## 10. Costs semantics

Entry cost 仅来自 frozen Alpha catalog：海贝 0、珊瑚 5,000、真珠 20,000。未恢复固定 5,000，也未把 unknown cost 静默当 0。

## 11. P20 / P50 / P80 behavior

三者来自同一次 existing Solver solve，语义为 intrinsic value distribution quantiles，不是 accuracy、confidence、win rate 或 bid recommendation。UI 对 unavailable 使用“暂无”，不显示假 0，并要求 `P20 <= P50 <= P80`。

Supported fixture 实际结果：P20 `415124.0131428572`、P50 `437503.0131428572`、P80 `513175.0131428572`。

## 12. recommendedMax source

唯一来源是 existing `calculateV06DecisionLines` / engine decision result。Supported 珊瑚 fixture 的真实值为 `432503`（现有 v0.6 语义下为 P50 437503.013 减 entry cost 5000）。任何 unavailable 情况均保持 null；禁止以 P50 顶替。

## 13. Action / advice source

唯一来源是 existing v0.6 fixed decision rules。未新增 AI、策略公式或第二套 Advice engine。Overlay 只把 native/engine result 渲染成最小产品文案。

## 14. Degraded / unavailable reasons

最小稳定状态包括：`STRUCTURAL_ONLY`、`INSUFFICIENT_HISTORY`、`MISSING_INPUT`、`UNKNOWN_BOX`、compatibility invalid、history/profile unavailable。Bridge/UI 不泄漏 raw path、exception 或 stack trace，也不显示 NaN/Infinity/0 元假建议。

## 15. Empty-history behavior

Isolated empty RuntimeDataRoot 下：structural estimate 正常、mode=`structural_only`、support=`STRUCTURAL_ONLY`、reason=`INSUFFICIENT_HISTORY`、probabilityProfile=null、recommendedMax=null，无 fake historical support，source/package 均 clean exit。

## 16. Supported-history behavior

测试只通过显式 isolated fixture 提供 admission-valid support。实际 profile 进入 existing live-shadow 与 engine，结果 mode=`full_shadow`、coverage=1、recommendedMax 非空；不是 UI 改标签。

## 17. Venue parity

海贝、珊瑚、真珠均使用上一 cut 冻结的 compatibility rows。Manual consumer 不再把 exact display name 直接传给旧 engine，因此不会重新落入 12,000 fallback。Focused parity 覆盖三场及其 8,000 / 12,000 / 30,000 prior semantics。

## 18. Box / unknown behavior

16 个 approved Alpha boxes 均通过 frozen helper 翻译为 existing v0.6 semantic。覆盖海贝、珊瑚、真珠代表 box。`boxId=null` 映射为 `UNKNOWN_NO_BOX_EFFECT` / no effect，不 fallback 到首项；cross-venue pair fail closed。

## 19. Prediction Snapshot behavior

继续复用 Prediction Snapshot Persistence v1。Overlay 将完整 snapshot wrapper 回传 native；inputHash/quantiles/matchId 使用既有 contract。未创建 predictionSnapshot2 或 advice snapshot。

真实 WebView smoke 发现浏览器 SHA-256 fallback 常量 `0xbef9a3f0` 与标准 SHA-256 不符，而 Node native crypto 路径会掩盖该问题。修正为标准 `0xbef9a3f7` 后，WebView prediction hash 与既有 Python snapshot contract 一致。该修复不改变 candidate、valuation、decision formula/prior 或 Solver 数值结果。

## 20. Terminal / finalize preservation

Estimate → snapshot persistence → FINALIZED → history re-read 已验证 predictionId 与 prediction-time quantiles保留；DRAFT autosave、FINALIZED exactly-once、keep-DRAFT、CANCELLED、failure preservation 与新 matchId 回归保持通过。

## 21. Next-match stale-state reset

Terminal success 后清除 P20/P50/P80、recommendedMax、action、support reason、snapshot sync 与 profile poll state。新局无有效 solverInput 时 engine 不运行，Overlay HWND/WebView/Solver runtime 不重建。

## 22. Source smoke

PASS。Isolated RuntimeDataRoot 下完成真实 Overlay WebView/bridge flow：选择 catalog venue/box、输入 facts、full-shadow solve、改变 bid、action threshold 改变、finalize/re-read snapshot、next match reset、same Overlay HWND、clean exit。另有 empty-history source smoke PASS。

## 23. Fresh package smoke

PASS。Fresh PyInstaller build 包含 frozen compatibility assets/module；real packaged WebView/bridge flow 与 source 相同。Runtime history 只写 isolated per-user root，package directory unchanged，clean exit，无 lingering process。另有 empty-history package smoke PASS。

## 24. Source / package parity

PASS。Full-support fixture 对 effective compatibility context、mode、P20/P50/P80、recommendedMax、action、reason、prediction snapshot semantics 完全一致；empty-history fixture 也完全一致。

## 25. Solver hashes before / after

| File | Before | After | Result |
|---|---|---|---|
| `auction_engine_v06.js` | `8f31258f73b22ce978a61555ad6765e231305588f0b8239609ce8a8230f98862` | `205b04c9b7af7094cc27b91003cbbff47d7b437d99e0ef4a5beecb78e3f35142` | Browser SHA-256 fallback one-nibble standard correction only; algorithm numerics unchanged |
| `solver_core_v06.js` | `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f` | same | unchanged |
| `shadow_profile_v06.js` | `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5` | same | unchanged |

## 26. Catalog compatibility hashes before / after

- `venue_box_catalog_v1.json`: `bb6ab1de152b1e86f539cbc86bb62b7968f7b3322d3ed16cd16132dae7c991df` → same.
- `v06_solver_compatibility_v1.json`: `99d002ff404f06a8ec8b149b1e3c99dc46e75847f7a92a49d4ef9a449f86ec5e` → same.

Packaged loader 仅增加 `_MEIPASS` application-asset root resolution；catalog truth、entry cost、evidence class 与 mapping values 未改。

## 27. Repo history hash

`异环拍卖数据.json`: `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a` → same。所有 runtime/smoke writes 使用 isolated data root。

## 28. Tests

- Focused/relevant suite: `75/75 PASS`。
- 覆盖 compatibility、empty/supported history、bid/profit separation、unknown/cross-venue fail close、snapshot/finalize、next-match engine gate、browser SHA parity、live-shadow async/coverage、terminal lifecycle、catalog contract。
- Source smoke: PASS。
- Fresh package build/smoke: PASS。
- Source/package parity: PASS。

## 29. Pre-existing failures

本 cut 未修改的既有债务：

- `tests.test_live_shadow_refresh` 2 failures：legacy fixture 仍假定 flat `actualTotal`；另一个 fixture 假定 missing parent directory 应写失败，而 Durable Runtime Data Authority 已规定自动创建目录。
- `tests.test_manual_alpha` 1 mismatch：legacy expectation 为 knownItems string，当前 baseline Canonical path 返回 item dict list。

这些均可在本 cut 前后独立复现，未为追求全绿而重写 legacy fixture/contract。

## 30. Final verdict

`MANUAL_ESTIMATE_ADVICE_READY`

## 31. Commit

独立 commit message：`feat(app): reconnect manual estimate and advice`。最终 hash 由提交完成后填写到交付回报；Git commit 无法在自身内容中可靠包含自身 hash。
