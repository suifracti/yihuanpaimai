# 边界 2 三项窄缺口收口报告（外部审核指定范围）

- 日期：2026-09-16
- 基线 HEAD：`2c81f9aad1ec2edef064390a4509a6e7a1a64929`（提交信息 `feat(boundary-2): implement bottom quality sell default checked mechanism`，2026-09-16 01:05:25 +0800）
- 冻结候选（外审给定）：`build/isolated_trial_ux_fixes_20260916_2c81f9a/dist/异环拍卖助手/异环拍卖助手.exe`，SHA256 `F7175A3DE14A9BD921B43F58B52F9BF763027F1B805D73170DBACCA2F0C24BA0`（本地复算一致）
- 本轮产出候选：`build/isolated_trial_ux_fixes_20260916_2c81f9a_g3fix/dist/异环拍卖助手/异环拍卖助手.exe`，SHA256 `CC086845F1597EDF34BDC0254415E7B69AEFE040FC8CBB437E06ABA92B768AFE`
- 整体状态：仍 **PARTIAL**；**不进入边界 3**；未提交。

---

## 0. 结论摘要

| 缺口 | 状态 | 一句话结论 |
| --- | --- | --- |
| 1 保护模型审计 + 最小修复 | **完成** | `qualitySellSelectionSource` 从未进入 `USER_CONFIRMED_FACT_KEYS`，外审的前提在当前代码中不成立；真实缺陷是"单值聚合 provenance"，已改为逐色 provenance；A→D 序列 10/10 PASS |
| 2 取消前后身份不漂移测试 | **完成** | 按格位配对后逐件比对身份字段：**18 件**两帧都 exact 的全部逐字节一致、**5 件**两帧都 ambiguous、6 件单向 `ambiguous→exact`、0 件反向、**真漂移 0**（数字已更正，见 §2.1）；可比性边界已写明 |
| 3 冻结 EXE 最小产品路径 | **完成（含最小修复 + 新目录重打包）** | 既有 2c81f9a 冻结 EXE 停在**最早断点**，定位到两处既有产品链路缺口并做最小修复；重打包后真实 EXE 最小链 **5/5 PASS** |
| 3′ bundle 导出/导入往返（外审指定） | **完成** | 走产品现有正式入口：导出 → 全新临时 `DATA_ROOT` → 导入 → 重启 → 历史详情；**13/13 PASS**；正式 bundle 的 `records.json` 确实承载三键，**未新造导出格式**（§3.7） |
| 4 canonical 14 项编号恢复 | **完成** | 计划文档与 2026-09-15 验收报告均已恢复/撤回；本轮未改名、未换序、未用局部验证替换 |
| 附带：既有 7 项回归失败归因 | **完成** | 用 2c81f9a 冻结包内 `PYZ-00.pyz` 的**改前字节码**做 A/B：改前改后失败集合完全相同 → 既有测试债（**仍留在债务列表**，只证明"不是本轮引入"） |
| 附带：git 仓库处置 | **完成** | 不修旧 `.git`；只读取证封存 + 新兄弟目录 `D:\yihuanpaimai-recovery\` recovery 仓库（§7.1） |
| 附带：Vault Evidence 同步 | **完成** | A–E 五组 + F/G 附录 + 逐文件 SHA256 清单已入 Vault（§8.3） |

---

## 1. 缺口 1：qualitySellSelection 实际保护模型审计与最小修复

### 1.1 先审计（未改码）得到的实际模型

| 项 | 实际值 |
| --- | --- |
| 完整 HEAD | `2c81f9aad1ec2edef064390a4509a6e7a1a64929` |
| clean/dirty | **无法用 git 判定**（对象库损坏，见 §5）。替代证据：`build/boundary2_g3fix_20260916/dirty_set_inventory.json` |
| `USER_CONFIRMED_FACT_KEYS` 数量 | **41 项** |
| 本轮新增字段 | `qualitySellSelection`（**仅此一个**） |
| `qualitySellSelectionSource` 是否在其中 | **否**（也不在 `FIXED_FACT_KEYS`） |

**回答外审的直接提问**：「为什么 `qualitySellSelectionSource` 需要进入 `USER_CONFIRMED_FACT_KEYS`？」——**当前代码里它并不需要，也从未进入。** 外审担心的"provenance 被当作普通用户确认业务事实整体永久锁定"在本基线**不成立**。审计发现的问题恰好相反：

1. `qualitySellSelection` 整体在 `USER_CONFIRMED_FACT_KEYS` 内，而 `fieldStates` 的 `protected/status` 是**整体级**的，因此"人工只动了一色"会让另外五色也拿不到视觉更新；
2. `qualitySellSelectionSource` 是**单值聚合字符串**，无法表达"绿=人工、蓝/紫=视觉、白/金/红=默认"；
3. 二者叠加导致 **provenance 与值脱钩**：selection 保持人工值，而聚合 source 被视觉覆写成 `visual_observed`。

### 1.2 A→D 严格序列（改前实测，全部失败点）

| 步骤 | 动作 | 改前结果 |
| --- | --- | --- |
| A | `acquired=True` → 默认 | 六色正确，但默认写入**绕过 `_write_field`**，不产生 `fieldStates` 与审计行 |
| B | 只取消 green | 正确：green=`unselected`/`manual_override` |
| C | 视觉观察 blue/purple=`unselected` | **FAIL**：被整体拒绝（`MANUAL_CONFIRMED_PROTECTED`），blue/purple 拿不到 `visual_observed`，新值只落进 `candidate`；**同时 `qualitySellSelectionSource` 被覆写为 `visual_observed`，而 selection 仍是人工值 → provenance 与值脱钩** |
| D | 普通 acquisition / 自动刷新 | 不重置（靠聚合串巧合通过） |

### 1.3 最小修复（逐色 provenance）

新增派生事实键 `qualitySellSelectionSources`（color→source），保护与合并按颜色进行：

- **人工动过的颜色**才受保护并保留 `manual_override`；其余颜色照常接受 `visual_observed`；
- `qualitySellSelectionSource` **降级为由逐色来源派生的聚合串**，并**拒绝被直接写入**（审计原因 `DERIVED_PROVENANCE_NOT_DIRECT_WRITABLE`）；
- `qualitySellSelection` 保留在 `USER_CONFIRMED_FACT_KEYS` 内，但由逐色逻辑先行接管，不再整体锁死；
- acquisition 刷新改为**逐色补默认**，只对无视觉/人工来源的颜色生效，并走 `_write_field` 产生审计行（`ACQUISITION_PER_COLOR_DEFAULT`）。

**未用一个整体 `manual_override` 覆盖六种颜色**；`qualitySellSelectionSource` 未被作为普通"用户确认业务事实"整体永久锁定。**未倒改 7.1 累计纠正表**；"40 项"保留其历史时点语义，新实际数量（41）只写在当前 7.4。

### 1.4 A→D 修复后复测

| 步骤 | 六色 selection | 逐色来源 | 受保护子键 | 仍允许视觉更新的子键 |
| --- | --- | --- | --- | --- |
| A | 白/绿/蓝/紫/金=selected，红=unselected | 六色 `default_self_acquired` | 无 | 全部六色 |
| B（只取消 green） | green=unselected，其余同 A | green=`manual_override`，其余 `default_self_acquired` | 仅 green | white/blue/purple/gold/red |
| C（视觉：blue、purple=unselected） | blue/purple=unselected；green 保持 unselected；白/金/红不变 | blue/purple=`visual_observed`；green 仍 `manual_override`；白/金/红仍 `default_self_acquired` | 仅 green | white/gold/red（blue/purple 已由视觉确认） |
| D（普通 acquisition 刷新） | 与 C 完全一致 | 与 C 完全一致 | 仅 green | 不变 |

**判定矩阵 10/10 项全部通过**，证据：`build/boundary2_audit_20260916/audit_run_after_fix.txt`。

---

## 2. 缺口 2：取消前后身份不漂移

- 新增用例：`tests/test_bottom_quality_sell_selection.py::test_identity_stability_across_deselection`
- 材料：既有真实帧 `build/codex_other_video_20260912/desktop-early/frame-255.png`（部分取消）与 `frame-257.png`（全部取消），**未要求用户重打一局**
- 配对规则：按**格位 (row, col)** 配对（几何键不预设身份相等），再逐件比对 canonical ID / name / price / identificationStatus / status / row / col / widthCells / heightCells / rarity

### 2.1 逐项结论

> **数字更正（2026-09-16，本轮）**：本节原写"两帧都 `exact` 的 **23 件**逐字节一致"。
> 经机器产物 `identity_drift_frame255_vs_257.json` 逐件复算，正确分解为
> **18 件 both-exact + 5 件 both-ambiguous + 6 件 `ambiguous→exact` = 29**。
> 原"23"实为"非 `ambiguous→exact` 的件数（18+5）"，把 5 件两帧都 `ambiguous`
> 的件误并入"两帧都 exact"，属表述错误，已在下方更正；结论方向不变（真漂移仍为 0）。

| 检查 | 结果 |
| --- | --- |
| 共同格位数 | 29（两帧各 29 件） |
| 漏件 | 无（`onlyInFrame255 = []`） |
| 幻影新件 | 无（`onlyInFrame257 = []`） |
| 同格重复 / 身份交叉 | 无（`duplicateInFrame255/257 = []`） |
| 几何 `row/col/w/h` + `rarity` | 逐件一致（`geometryDriftCount = 0`，`rarityDriftCount = 0`） |
| **两帧都 `exact`** | **18 件**，canonical ID / exactItemId / 名称 / 价格 / 身份状态 / 确认状态 **全部逐字节一致**（`bothExactWithDriftCount = 0`） |
| **两帧都 `ambiguous`** | **5 件**：`(0,5)(0,6)(1,4)(8,8)(9,0)`，两帧均无可比身份字段（catalogId/name/price 皆 `None`），故不参与等值检查 |
| **`ambiguous → exact`** | **6 件**：`(0,4)(0,7)(0,8)(8,9)(9,6)(9,9)`，逐件明细见机器产物 |
| **`exact → ambiguous`** | **0 件** |
| **真漂移（`trueDrift`）** | **0 行** —— 无 ID 漂移、无改名、无价格漂移 |
| 原始逐字段 DIFF 计数 | `idFieldDiffs = 12`、`nameDiffs = 6`、`priceDiffs = 6`，**全部来自上述 6 件 `ambiguous→exact` 的 `None → 有值` 解析变化**，不是身份漂移 |

**真漂移判据（可复算，写入机器产物 `summary.trueDriftNote`）**：
两帧都有值且不同，或几何 / rarity 不一致 → 真漂移；
状态字段 `ambiguous→exact` 属本轮明确允许的**方向性解析**，不计真漂移；
一边 `None` 一边有值属解析强度差异，不计真漂移，但以方向性单列。

**未用 `slots255 == slots257` 代替身份一致**：几何/品质相等只作为前置条件，身份一致性由上述字段逐件比对承担。

**机器产物**：`build/boundary2_audit_20260916/identity_drift_frame255_vs_257.json`（逐件 29 条 + 全量控制台原文）、`identity_drift_frame255_vs_257.txt`。

### 2.2 可比性声明（哪些字段可比 / 不可比 / 为什么）

- **可比且要求相等**：`row/col/widthCells/heightCells/rarity`；以及"两帧都为 `exact`"的件的 canonical ID / name / price / identificationStatus / status。
- **不可比**：单帧 `ambiguous` 的身份字段。未解析不等于存在竞争身份，属**解析强度差异**，故按**方向性**检查（只允许 `ambiguous→exact`）而非等值检查。
- **原因**：两帧分属动画不同时刻（255 为部分取消、257 为全部取消），小尺寸 1×1 / 1×2 图标在 255 帧仍带粉色选择环，模板证据更弱。
- 已额外验证识别**确定性**：三种调用顺序（255→257 同实例、257→255 同实例、每帧新实例）结果逐字节相同 → 上述差异是真实的逐帧差异，不是识别器状态泄漏。
- **范围限制**：既有"红未勾选仍识别红"用例保留，但**仅可表述为"该真实样本通过"，不推广为所有红物或所有帧的身份准确率**。

---

## 3. 缺口 3：冻结 EXE 最小产品路径

### 3.1 第一步：用既有 2c81f9a 冻结 EXE（未重打包）→ 停在最早断点

按"优先不重打包"执行：在全新临时 `YIHUAN_DATA_ROOT` 下真实启动既有冻结 EXE（**未用系统 Python import 源码代替**），结果在最早断点失败：

```
EXE SHA256 OK: f7175a3d…（与给定一致）
saved record id=replayfile_85ce3299… lifecycle=FINALIZED
qualitySellSelection        = {"white":"unknown", …, "red":"unknown"}
qualitySellSelectionSource  = unknown
qualitySellSelectionSources = null
#detail-sell-selection = None（WS 桥偶发返回 null；重试后实为"未记录"）
```

### 3.2 定位到的两处既有产品链路缺口

**断点 1 — 识别结果未出管线。** `core/vision_pipeline.py::NTEVisionPipeline._attach_settlement_ledger` 只把 `ledger["settlementItems"]` 与若干计数字段提升进 `settlement` / `current_context`，**没有提升 `qualitySellSelection` / `qualitySellSelectionSource`**。
检测本身成功：对 `build/exe_chain_20260915/frames/settlement_blob_144037.png`（2560×1440）直接调用 `detect_quality_sell_selection_from_frame` 返回六色全 `unselected`。但结果只留在 `settlement["ledger"]`，`auto_archiver` 读 `ctx.get("qualitySellSelection")` 得 `None`，走 `acquired is False` 兜底分支，`canonical_match_record` 落库为六色 `unknown` + 来源 `unknown`。

**断点 2 — 投影丢字段，UI 永远显示"未记录"。** `app/main_view_state.py::HistoryRecordProjection.to_payload()` 的 `settlement` 是有界白名单摘要，**不含该三个字段**，Main 历史详情拿到的 `record.settlement` 里没有它，`main_window.js` 的 `qSel` 恒为 `undefined`，渲染结果恒为"未记录"。
经真实 EXE 的 WS 桥实测确认：`#detail-sell-selection` 元素**存在**（静态 HTML，`elementExists=true`），文本为"未记录"——**是字段被投影丢弃，不是 DOM 缺失**。

### 3.3 最小修复

| 文件 | 修复 |
| --- | --- |
| `core/vision_pipeline.py` | `_attach_settlement_ledger` 中把三个键从 ledger 提升到 `settlement` 与 `current_context`（仅当 ledger 中非空） |
| `app/main_view_state.py` | `HistoryRecordProjection` 增加三个有界字段（六色固定基数 map + 聚合串），`to_payload()` 的 `settlement` 块输出，`_project_record` 中规范化提取 |

**未扩大范围**：未触碰鼠标点击、键鼠接管、滚仓、图鉴、阈值、求解器、性能、Arena。

### 3.4 链路离线验证（不启动 EXE）

`build/boundary2_g3fix_20260916/probe_chain.py`：frame → `parse_settlement_ledger` → `_attach_settlement_ledger` → 归档块 → canonical v7 → Main 投影，每一跳都保留六色状态与 `visual_observed` 来源。**9/9 PASS**，canonical 校验 `(True, [])`。

### 3.5 重打包（新目录，不覆盖）

冻结包内 Python 已编译进 EXE、无法就地修补，按外审"停在最早断点做最小修复，再新目录重打包"执行：

- 新候选：`build/isolated_trial_ux_fixes_20260916_2c81f9a_g3fix/dist/异环拍卖助手/异环拍卖助手.exe`
- SHA256：`CC086845F1597EDF34BDC0254415E7B69AEFE040FC8CBB437E06ABA92B768AFE`
- 隔离标记：`{"profile":"isolated-trial-v1","codeRevision":"2c81f9a_g3fix","builtAt":"2026-09-15T18:06:53Z"}`
- 旧候选 `isolated_trial_ux_fixes_20260916_2c81f9a`（7442436 字节）**完好未动**。

### 3.6 真实 EXE 最小链实测：5/5 PASS

驱动 `build/boundary2_g3fix_20260916/run_min_product_path.py`，**不 import 任何生产模块**，全部观测来自真实 EXE 的 WS 桥（`ws://127.0.0.1:8766`）、DOM 与它写盘的 JSON。

| 步骤 | 结果 | 关键实测值 |
| --- | --- | --- |
| 1 真实 EXE 启动 | PASS | Main HWND=6427310 / HUD HWND=5771952 / PID=35376；`DATA_ROOT` 为全新临时目录 |
| 2 获得 qualitySellSelection | PASS | 六色全 `unselected`；source=`visual_observed`；逐色 sources 六色全 `visual_observed`；record `replayfile_85ce3299…`，lifecycle `FINALIZED` |
| 3 历史详情实际显示 | PASS | DOM 文本 `白:✗·视觉 绿:✗·视觉 蓝:✗·视觉 紫:✗·视觉 金:✗·视觉 红:✗·视觉 (逐色来源)`；`elementExists=true`、`cardHidden=false`、`fieldHidden=false` |
| 4 正常关闭 | PASS | `WM_CLOSE` 后无残留进程 |
| 5 重启同一 EXE 重读 | PASS | 记录数 1 / FINALIZED 1；selection、source、逐色 provenance、DOM 文本**四者全部一致** |

- **生产目录未被触碰**：`%LOCALAPPDATA%\异环拍卖助手` 前后均为 **1603 文件**，逐文件 size+mtime 完全一致。
- **运行路径证明**：驱动启动前断言 EXE 路径与 SHA256 等于重打包产物，并校验 `_internal/isolated_trial.json` 的 `profile`；所有观测经该进程的桥与它写下的历史 JSON 取得。
- 导出/导入 bundle 往返：已在 §3.7 补做完成（外审指定）。

### 3.7 bundle 导出 / 导入往返（外审指定，13/13 PASS）

**链路（全部由 g3fix 冻结 EXE 自己完成，驱动脚本不 import 任何生产模块）**：

```
g3fix 冻结 EXE → 已有含 qualitySellSelection 的隔离历史记录（DATA_ROOT=data_src）
  → 原生导出 bundle（postNative("export_history_records", {outputPath})）
  → 新建全新临时 DATA_ROOT=data_dst
  → 导入 bundle（postNative("import_history_bundle", {inputPath})）
  → 启动同一冻结 EXE → 打开历史详情 → 逐字段核对
```

**这是产品现有正式入口，不是测试专用格式**：`core/main_window.js` 的导出/导入按钮本身就 `postNative` 这两个动作并传 `outputPath` / `inputPath`；`app/main_window.py`（约 1789 行）在 payload 已带路径时**跳过文件选择框**，直接 `self._bridge.dispatch(payload)`。驱动只是复用同一路径，未新造任何导出格式。

| 项 | 导出前 | 导入后 | 判定 |
| --- | --- | --- | --- |
| 1 六色 `qualitySellSelection` | `{white/green/blue/purple/gold/red: unselected}` | 同左 | PASS |
| 2 每色 `qualitySellSelectionSources` | 六色全 `visual_observed` | 同左 | PASS |
| 3 aggregate `qualitySellSelectionSource` | `visual_observed` | 同左 | PASS |
| 4 `lifecycleStatus` | `FINALIZED` | `FINALIZED` | PASS |
| 5 `dataOrigin` | `replay` | `replay` | PASS |
| 6 record ID | `replayfile_85ce3299…78b6` | 同左 | PASS |
| 7 `reviewUnits` 数量 | 29 | 29 | PASS |
| 8 Main 历史详情实际显示文本 | — | `白:✗·视觉 绿:✗·视觉 蓝:✗·视觉 紫:✗·视觉 金:✗·视觉 红:✗·视觉 (逐色来源)`（字段标签"底部品质出售勾选"，`elementExists=true`） | PASS |
| 9 逐色来源仍是六色映射（未压平） | — | `set(keys) == 六色` | PASS |
| 10 未降级为整体 `manual_override` | — | `manual_override ∉ values` | PASS |
| 11 未把 selection 转成物品存在事实 | — | `reviewUnits` 数量不变 | PASS |
| 12 `unknown` 未丢失 | 无 `unknown` | 无 `unknown` | PASS |
| 13 DOM 处于逐色来源模式（非整体降级） | — | 文本含 `(逐色来源)`，非 `(视觉识别)` | PASS |

**正式 bundle 确实承载新字段（正面证明，非"未做"）**：
`bundle` 内 `records.json` 的 `schemaVersion = history-export.v2`，含 1 条记录，其 `settlement` 同时带 `qualitySellSelection` / `qualitySellSelectionSources` / `qualitySellSelectionSource` 三键，**与源记录逐字段相等**；bundle 共 35 个条目（含 31 张图片）。导出/导入状态行分别为
`已导出 1 条对局及 31 张图片：…\异环拍卖对局包_roundtrip.zip`、
`已导入 1 条新对局，跳过 0 条重复记录，关联 31 张图片。`
→ **未出现"最早断点"，因此未做任何针对 bundle 的修复。**

**冻结候选（完整 SHA256，非前缀）**：

| 项 | 值 |
| --- | --- |
| 路径 | `D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260916_2c81f9a_g3fix\dist\异环拍卖助手\异环拍卖助手.exe` |
| 完整 SHA256 | `cc086845f1597edf34bdc0254415e7b69aefe040fc8cbb437e06aba92b768afe` |
| 大小 | `7459953` bytes |
| 隔离标记 | `{"profile":"isolated-trial-v1","codeRevision":"2c81f9a_g3fix","builtAt":"2026-09-15T18:06:53.629810+00:00"}` |

- **生产目录未被触碰**：`%LOCALAPPDATA%\异环拍卖助手` 前后均 1603 文件，逐文件 size+mtime 一致。
- **机器结果载体说明**：`exportResult` / `importResult` 恒为 `null`，因为 WS 调试桥（`app/main.py:1601`）只转发 `type=main_js_result`，原生响应体只交付给应用内 JS。故本轮以**产品自身的用户可见状态行**（`#history-export-status`）+ **磁盘副作用**（bundle 文件、目标根历史库）+ **bundle 内部 records.json** 作为机器结果，未另造测试通道。
- **一次额外发现（本轮同一改动的内部不一致，已最小补齐）**：`core/canonical_history_store.py` 的 **archive-sidecar 保留列表**（约 863–870 行）漏了 `qualitySellSelectionSources`，而 draft-merge 列表（约 831–845 行）三键齐全。这构成一条"一次 OCR 归档写入即静默压平逐色 provenance"的潜在路径。已把该键补入同一列表，未改动其他逻辑。**该路径不被 bundle 往返覆盖**（往返导入写入的是全新记录，走不到该分支），故本条为潜在缺陷的预防性补齐，已如实标注。

**证据**：`build/boundary2_g3fix_20260916/run_bundle_roundtrip.py`、
`build/boundary2_g3fix_20260916/roundtrip/run_20260916_031535/bundle_roundtrip_report.json`（含 13 项判定 + bundle 内容检查 + 源/目标全字段快照）、
`roundtrip/log_A_export.log` / `log_B_import.log` / `log_C_reread.log`。

---

## 4. 缺口 4：canonical 14 项编号恢复

- 计划文档 `docs/plans/2026-09-05-project-replan.md` 已写入 canonical 14 项（唯一权威编号与名称）。
- `docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md` 第 4 节原先自拟的 8 项清单已**就地撤回**并加更正记录。
- **未改名、未换序号、未用本轮局部验证替换这 14 项**；任何局部验证都不得替换 canonical 清单。

canonical 14 项（逐字）：1. 真实本人获胜实录及自动归属全链；2. 底部品质出售默认勾选机制；3. 真实游戏键鼠接管与防干扰；4. 真实限时全仓滚动与跨页物品去重拼接；5. 疑难物品左键详情采集与关闭恢复；6. 70秒/游戏倒计时截止及离线继续识别；7. 离线结算与草稿治理，含胜者名单治理；8. 至少3局未参与调参的真实对局端到端验证；9. 连续识别稳定性与内存问题；10. 实时性能门槛：忙碌确认P95≤0.5s；出价到显示P95≤1.5s；情报结构化P95≤2s；11. 跨电脑/目录带图导出及manifest校验；12. 免费情报专属业务链；13. `tests.test_match_trunk` 两项历史测试债；14. 2D无有限上限全面可行性与二维摆放求解。

---

## 5. 附带结论：既有 7 项回归失败的归因（非本轮回归）

`scripts/run_audit_regression_suite.py` 的 79 项批次中有 7 项失败。为排除"本轮引入"，用 **2c81f9a 冻结包内的 `PYZ-00.pyz`（1161 项）取出改前字节码**，在测试 import 之前 `exec` 进 `sys.modules`，从而在**不改动任何源码**的前提下得到真正的改前运行时（`build/boundary2_g3fix_20260916/probe_prefix_ab.py`，Python 3.10.20，替换 7 个模块）。

| 运行 | 用例数 | 失败数 | 失败集合 |
| --- | --- | --- | --- |
| 改前（PYZ 字节码） | 23 | **7** | 见下 |
| 改后（工作区） | 23 | **7** | **完全相同** |

失败集合：`test_archive_with_warehouse_preserves_slots_in_memory_and_on_disk`、`test_case_b_unknown_with_winner_name`、`test_cost_correction_updates_saved_draft_inside_duplicate_window`、`test_private_controls_update_and_clear_in_same_record`、`test_receipt_updates_same_record_without_changing_inventory_value`、`test_cross_match_backwrite_protects_current_match`、`test_finalized_backwrite_preserves_facts`。汇总：`build/boundary2_g3fix_20260916/regression_ab_summary.json`。

**直接机制（已复现，`probe_dark_controls.py`）**：`AutoArchiver.archive_match` 成功落盘后把调用方 `ctx` **就地改写**为 `ctx["settlementFinalized"]=True`（`core/auto_archiver.py:656`），下次调用被守卫 `if ctx.get("settlementFinalized"): return None`（`core/auto_archiver.py:189`）直接挡掉；测试复用同一 `ctx` 字典并期望第二次调用返回非 None，与实现契约冲突。两处均在**本轮未改动的行区间**内（本轮对 `auto_archiver.py` 的编辑仅限 503–536 的 quality-sell 块）。

另：多个测试模块硬编码 `C:\Program Files\Python310\Lib\site-packages`（该解释器本体已不存在，只剩 cp310 二进制），在 3.12 下会毒化 numpy/cv2 导入，属测试环境债。

**结论：7 项失败为既有测试债，非本轮回归。**

---

## 6. 本轮未做 / 未验证（诚实边界）

- **未做**（遵守禁止清单）：真实鼠标点击、键鼠接管、70 秒滚仓、新图鉴补件、匹配阈值调整、`catalog_065` 修改、求解器修改、性能优化、Arena、未知红 PMF；六品质联合求解与 Historical Shadow 未动。
- **已补做**：导出/导入 bundle 往返（§3.7，13/13 PASS）。
- **未做**：未提交（工作区 dirty）；未自动进入边界 3。
- **性能**：本轮无任何性能优化，`identity_frame_ms` 类指标沿用历史单次值。
- **边界 2 状态**：仅可标记为「业务规则 + 视觉容错 + 状态/provenance + 冻结隔离产品路径 PASS；**真实游戏物理点击仍未验，属于边界 3**」。

---

## 7. git 对象库损坏：只读取证封存 + 新建 recovery 仓库（已按用户决策执行）

为做"改前/改后对照"执行 `git stash push -- core/` 时失败，并暴露出仓库对象库已损坏（**非本轮代码问题**）：

- `git stash` 报 `fatal: e5e3d78… is not a valid object`，并把整棵工作树变成 staged 新增（约 660 条 `A`）。
- `.git/refs/heads` 一度缺失、`HEAD` 被报为字面量 `"HEAD"`；`.git/objects/pack/` **只剩 `multi-pack-index` 与 `pack-64c9077c….idx`，`pack-*.pack` 数据文件已丢失**；全盘搜索 `pack-*.pack` 无结果。
- reflog（654 行）本身完整，可读出提交序列：`… 9865460 → 2c81f9a commit: feat(boundary-2): implement bottom quality sell default checked mechanism`（`1789491925` = 2026-09-16 01:05:25 +0800）。据此已把 `.git/refs/heads/main` 重建为 `2c81f9a…`，`git rev-parse HEAD` 恢复正常，但 `git status` 仍报 `fatal: bad object HEAD`。
- **仓库未配置任何 remote，本地无 pack 备份** → 提交历史暂不可恢复。
- 证据保全：`build/boundary2_audit_20260916/git_damage_evidence/`；源码快照 `build/boundary2_audit_20260916/backup_modified/`。

### 7.1 决策：**不修旧 .git**，新建 recovery 仓库

**未执行**（禁止清单）：`git gc` / `git repack` / `git prune` / `git reset` / `git checkout` / `git clean`。旧仓库工作树与 `.git` 均未被写入、移动或删除。

#### 7.1.1 只读取证封存

封存位置：`D:\yihuanpaimai-recovery\_forensic\old_git_damaged_20260916\`（脚本 `build/boundary2_g3fix_20260916/git_forensic_seal.py`，全部 git 调用均为只读子命令）

| 内容 | 结果 |
| --- | --- |
| `.git` 逐字节完整副本 `sealed_dot_git/` | **35 个文件**，逐文件 size / mode / sha256 |
| 关键元数据 `metadata_copies/` | `HEAD`、`ORIG_HEAD`、`config`、`description`、`COMMIT_EDITMSG`、`index`；`refs/**`、`logs/**`、`info/**`、`hooks/**`、`objects/info/**`、`objects/pack/**` |
| `git fsck --full` 原始输出 | 9768 行，**2614 条 `error:`**（1307 条 `HEAD: invalid reflog entry`、1305 条 `refs/heads/main: invalid reflog entry`、各 1 条 `invalid sha1 pointer`），**7 个 dangling 对象** |
| `git remote -v` | **输出为空** |
| `.git/config` 是否含 `[remote` | **False** → **结论：无远端**（`seal_report.json.remoteDecision`） |
| `git log --oneline` | `fatal: bad object HEAD`（exit 128） |
| `git status --porcelain` | `fatal: bad object HEAD`（exit 128） |
| `git rev-parse HEAD` | `2c81f9aad1ec2edef064390a4509a6e7a1a64929`（exit 0） |
| `git count-objects -v` | `count: 7`、**`in-pack: 0`**、`packs: 0`；`warning: no corresponding .pack: …pack-64c9077c….idx` |
| `git verify-pack -v …idx` | exit 1，`.pack: bad`，`fatal: Cannot open existing pack file …idx` |
| 当前工作树全量 manifest | `worktree_manifest.json`：**85,912 个文件 / 37.31 GiB / 0 条错误**，每文件 `relativePath / size / mtime / sha256` |
| 本轮未提交源码文件独立副本 | `source_copies/`：**24 个文件，0 缺失**，逐文件 sha256 |

**残留 7 个松散对象**（唯一幸存的真实 git 内容，均为 dangling）：5 个 blob + 2 个 tree。其中两个 tree 可读出（`097e7808…` 为仓库根 tree：`.gitignore/README.md/app/assets/core/design/docs/experiments/lab/requirements-desktop.lock.txt`；`086f7dd3…` 为 `docs/` tree），blob 含 `app/main.py`（v0.65，217,035 字节）等真实文件内容。

#### 7.1.2 recovery 仓库

- 位置：**新兄弟目录** `D:\yihuanpaimai-recovery\`（`D:\yihuanpaimai\.git` **未被删除或替换**）
- 来源：损坏仓库的**当前工作树**（按 `.gitignore` 语义排除生成物/缓存/运行库；`build*`、`dist`、`runtime`、`__pycache__`、`*.exe/*.dll/*.pyd`、`evidence/`、`异环拍卖数据*.json`、`_forensic/` 等）
- 首个 commit 如实记录：来源说明、**最后已知历史 HEAD `2c81f9aad1ec2edef064390a4509a6e7a1a64929`**、g3fix 改动清单、**新候选完整 SHA `cc086845f1597edf34bdc0254415e7b69aefe040fc8cbb437e06aba92b768afe`**、旧损坏 `.git` 的封存位置
- **未伪造任何旧 commit 历史**；仓库根 `RECOVERY.md` 与提交信息均显式声明"本仓库不是原仓库的历史延续"
- 若日后找到远端或备份：恢复真实旧历史，并把本 recovery 工作树迁回（写入 `RECOVERY.md` 的后续步骤）

**影响（未变）**：本轮仍无法用 `git status` / `git diff` 证明 clean/dirty。替代证据：`build/boundary2_g3fix_20260916/dirty_set_inventory.json`（前端资产用冻结包 `_internal/core/*` 与工作区逐文件哈希比对；Python 改动用 §5 的"改前字节码 A/B"做行为级对照），以及本次 `worktree_manifest.json` 全量 85,912 文件哈希清单。

---

## 8. 本轮变更文件与产物

### 8.1 代码/测试变更

| 文件 | 变更 |
| --- | --- |
| `core/quality_sell_selection.py` | 逐色 provenance 层：`VALID_SELECTION_SOURCES`、`normalize_quality_sell_selection_sources`、`sources_from_aggregate`、`manual_override_colors`、`aggregate_selection_source`、`merge_quality_sell_selection`、`apply_single_color_override` |
| `core/current_match.py` | `FACT_KEYS`/`empty_facts` 增 `qualitySellSelectionSources`；`_coerce_value` 分支；`apply_facts` 逐色合并分支 + 派生键拒写；acquisition 逐色刷新；`update_quality_sell_selection_color` 改写；`to_canonical` 输出三键 |
| `core/canonical_match_record.py` | 禁止根级 legacy 字段增 `qualitySellSelectionSources`；settlement→record 逐色规范化 + 聚合派生；新增校验码 |
| `core/canonical_history_store.py` | 两处保留列表增 `qualitySellSelectionSources`；**本轮补**：archive-sidecar 列表（约 863–870 行）原先漏该键，已补齐（见 §3.7） |
| `core/auto_archiver.py` | quality-sell 块读取/规范化逐色来源并写三键（503–536 区间） |
| `core/vision_pipeline.py` | **缺口 3 断点 1 修复**：`_attach_settlement_ledger` 提升三个键 |
| `app/main_view_state.py` | **缺口 3 断点 2 修复**：`HistoryRecordProjection` 三字段 + `to_payload` 输出 + `_project_record` 提取 |
| `core/main_window.js` | 历史详情渲染逐色来源标记（`默认`/`视觉`/`人工`）与 `(逐色来源)` |
| `tests/test_bottom_quality_sell_selection.py` | 新增身份不漂移用例、逐色 A→D 用例、链路锁定用例；现 **10 项全通过（115.276s）** |
| `docs/plans/2026-09-05-project-replan.md` | canonical 14 项、缺口 1/2/3 结论、7 项回归归因、git 损坏记录（未改 7.1） |
| `docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md` | 第 4 节 8 项非 canonical 清单就地撤回 |

### 8.2 证据产物

| 路径 | 内容 |
| --- | --- |
| `build/boundary2_audit_20260916/audit_protection_model.py` / `audit_run_after_fix.txt` | 缺口 1 A→D 审计与 10/10 判定矩阵 |
| `build/boundary2_audit_20260916/audit_identity_drift.py` + `identity_drift_frame255_vs_257.{txt,json}` | 缺口 2 逐件身份漂移比对（**新增机器产物**：29 条逐件 + 真漂移语义 + 全量控制台原文） |
| `build/boundary2_audit_20260916/git_damage_evidence/` | git 损坏证据 |
| `build/boundary2_audit_20260916/backup_modified/` | 6 个改动文件快照（哈希一致，无丢失） |
| `build/boundary2_g3fix_20260916/probe_detect.py` | 证明检测在 replay 帧上成功（六色全 `unselected`） |
| `build/boundary2_g3fix_20260916/probe_chain.py` | 五跳链路离线验证 9/9 PASS |
| `build/boundary2_g3fix_20260916/probe_dom.py` | WS 桥 DOM 实测（元素存在、文本"未记录"） |
| `build/boundary2_g3fix_20260916/probe_dark_controls.py` | 7 项失败的直接机制复现 |
| `build/boundary2_g3fix_20260916/probe_prefix_ab.py` + `regression_ab_{prefix,current}.json` + `regression_ab_summary.json` | 改前/改后 A/B |
| `build/boundary2_g3fix_20260916/run_min_product_path.py` + `min_product_path_report.json` | 真实 EXE 最小链 5/5 PASS |
| `build/boundary2_g3fix_20260916/run_bundle_roundtrip.py` + `roundtrip/run_20260916_031535/bundle_roundtrip_report.json` + `roundtrip/log_{A_export,B_import,C_reread}.log` | **bundle 往返 13/13 PASS**（含 bundle 内部 records.json 检查） |
| `build/boundary2_g3fix_20260916/git_forensic_seal.py` + `D:\yihuanpaimai-recovery\_forensic\old_git_damaged_20260916\` | **旧仓库只读取证封存**（`.git` 全量副本、`worktree_manifest.json` 85,912 文件、`git_forensics/`、`source_copies/` 24 文件、`seal_report.json`） |
| `build/boundary2_g3fix_20260916/create_recovery_repo.py` + `D:\yihuanpaimai-recovery\` | **recovery 仓库**（新兄弟目录，首个 commit 记录来源/HEAD/改动清单/候选 SHA/封存位置） |
| `build/boundary2_g3fix_20260916/dirty_set_inventory.json` | git 不可用下的可复算 dirty 集合 |

### 8.3 Vault 版本化 Evidence 同步

本轮全部原始 Evidence 已同步到 Obsidian Vault（不只在本地）：

`D:\ObsidianLiveSyncTestVault\03-项目与工程\异环拍卖助手\Evidence\2026-09-16-boundary2-g3fix-evidence\`

| 组 | 内容 |
| --- | --- |
| `A-protection-audit/` | A→D 10/10 审计脚本与产物、逐色 provenance 用例、`core/quality_sell_selection.py` |
| `B-identity-drift/` | 逐件 identity diff 脚本 + txt/json、**原始帧 frame-255.png / frame-257.png** |
| `C-frozen-exe-min-path/` | 最小链驱动与报告、两次实例日志、`probe_detect/chain/dom`、两处断点修复的源码 |
| `D-regression-ab/` | PYZ 改前字节码 A/B 脚本、`regression_ab_{prefix,current,summary}.json`、`probe_dark_controls.py`、`tests_regression.json`、`core/auto_archiver.py` |
| `E-bundle-roundtrip/` | 往返驱动与报告、三段日志、`match_export_bundle.py` / `match_import_bundle.py` |
| `F-git-forensics/` | `git_forensics/*.txt`（`fsck --full` 原文等）、`seal_report.json` |
| `G-source-appendix/` | 本轮其余改动源码与文档 |
| `evidence_manifest.json` | **逐文件 relativePath / size / sha256** 清单 |

---

## 9. 请求外部审核裁定

1. 缺口 1：是否接受"外审前提在当前基线不成立 + 逐色 provenance 最小修复 + A→D 10/10"的结论？
2. 缺口 2：是否接受"按格位配对 + 身份字段逐件比对 + 单向 `ambiguous→exact` + 可比性声明"的判据？**并请确认 §2.1 的数字更正（18 both-exact + 5 both-ambiguous + 6 `ambiguous→exact` = 29；真漂移 0）成立**——原报告"23 件"为表述错误，已就地更正并留痕。
3. 缺口 3：是否接受"两处既有断点 + 最小修复 + 新目录重打包 + 真实 EXE 最小链 5/5 PASS"作为边界 2 的冻结隔离产品路径证据？
4. **bundle 往返（原第 3 问的补做项）**：13/13 PASS，且已正面证明正式 bundle 的 `records.json`（`history-export.v2`）承载三个新字段；请确认这是否满足"不新造测试专用导出格式"的要求。
5. **archive-sidecar 保留列表漏键的补齐**（§3.7 末）：该路径不被往返覆盖，属预防性最小补齐；请裁定是否接受，或要求单独补一条覆盖该分支的验证。
6. 缺口 4：canonical 14 项恢复是否符合要求？
7. **git**：已按"不修旧 .git"执行——只读取证封存 + 新兄弟目录 recovery 仓库（§7.1）。请裁定该处置是否合规；以及是否要求把 reflog 中 654 条历史提交元数据（SHA + message + 时间）另做一份可读归档以便日后比对远端/备份。
8. **Vault Evidence**：A–E 五组 + F/G 附录 + 逐文件 SHA256 清单已同步（§8.3）。请确认是否满足"不能只留本机"。
9. 边界 2 是否可据此标记为「业务规则 + 视觉容错 + 状态/provenance + 冻结隔离产品路径 PASS；真实游戏物理点击仍未验，属于边界 3」？**本轮不自动进入边界 3。**
