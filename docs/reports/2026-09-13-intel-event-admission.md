# 公开情报事件准入与纵向链路贯通

业务提交针对已由 `PublicIntelLedger` 确认的公开情报内容，正式接通“事件准入 → CurrentMatch → 标准保存/恢复 → 自动归档 → 历史回看”纵向链路。此前确认的卡片事实停留在 vision/ledger 快照层；本轮将其提升为具备稳定 identity、幂等去重与跨局隔离的 canonical intel event。

## 核心设计与修改

1. **事件身份与防篡改 Canonical 准入**：
   - 依赖 `verified_public_event` 作为严格准入门槛：必须经过 2 帧独立物理 OCR、同回合、标题精确匹配“拍卖师公开情报”、状态为 `CONFIRMED_CONTENT`。
   - **防篡改与费用语义强校验**：`verified_public_event` 显式校验 `sourceKind in (None, 'AUCTIONEER_PUBLIC')`、`costClassification in (None, 'UNKNOWN')`、`incrementalCost is None`。任何带有 `costClassification="FREE"`、`incrementalCost=0`、`sourceKind="PAID_INSTRUMENT"` 的篡改对象均直接被拒，无法通过准入。
   - **规范字典重构（Canonical Reconstruction）**：新增 `canonical_public_event(event)`。准入时不信任调用方对象，强制按证明事实重构规范字典（`sourceKind='AUCTIONEER_PUBLIC'`、`costClassification='UNKNOWN'`、`incrementalCost=None`），彻底剔除调用方注入的任意额外脏字段。
   - 定义稳定事件身份 `public_event_identity(event) = (event['id'], event.get('roundObserved'))`。其中 `event['id']` 由确定性的 `public_card_key`（纯文本 SHA-256）派生，不含时间戳、UUID 或帧 ID。结合回合数，既能保证 pipeline 重复发布、同帧重复、缓存重复、保存/恢复后再收到时幂等去重，又能防止不同回合相同文本的独立确认被全局盲目吞掉。
   - 新增 `admit_public_card_events(events, existing=None)`，用于事实写入、反序列化净化和展示过滤。

2. **状态权威与持久化**：
   - Live 权威状态归属于 `CurrentMatch.facts['publicCardEvents']`。
   - `CurrentMatch._coerce_value` 与 `apply_facts` 在接收 `publicCardEvents` 时，严格执行准入过滤与基于现有状态的增量去重合并；显式清空时安全置为 `[]`；空观测（`[]`）触发 `MISSING_DOES_NOT_CLEAR`。
   - 持久化时严格保持 Canonical Schema 规范，仅保存在 `canonical_record['intelCardEvidence']['publicCardEvents']` 中，根节点不新增并列字段。
   - `intel_evidence_record` 与 `restore_intel_evidence` 均使用 `admit_public_card_events`，确保非法数据绝不落盘、反序列化后 proof 完整且重新通过校验；旧记录缺省时安全返回，实现平滑向后兼容。
   - 经纵向生命周期测试与源码追踪，`core/auto_archiver.py` 现有逻辑通过 `intel_evidence_record(ctx)` 已能完整保留 `intelCardEvidence`，确认无需修改，避免制造未经统一校验的深拷贝旁路。

3. **生产视觉通道贯通与局间重置隔离**：
   - 在 `app/main.py:sync_vision_to_current_match` 中，将视觉上下文中的 `intelCardReadings` 与 `publicCardEvents` 写入 `patch` 并下发至 `CURRENT_MATCH`，打通此前断掉的生产视觉同步链。
   - **局间彻底隔离修复**：排查发现 `NTEVisionPipeline.clear_match_trunk()` 原先未清理 `_intel_ledger` 与 `publicCardEvents`，在大厅退出或局间重置时存在将上一局账本残留事件回灌至下一局的隐患。本次在 `clear_match_trunk` 和 `reset_session_state` 中同步显式重置 `_intel_ledger = None`、`_latest_intel_evidence = None` 以及上下文 `publicCardEvents = []`，并在 `match_trunk_dirty` 中纳管账本状态，彻底杜绝跨局事件回灌。

4. **历史回看展示文案调整**：
   - `app/intel_evidence_presentation.py` 采用 `public_event_identity` 进行展示去重。
   - 回看文案由 `（不重复计费）` 调整为 `（仅记录观察事实，不据此判定免费）`，避免给用户造成“本助手已证明该卡免费”的误解。

5. **非数值卡与生命周期隔离**：
   - 非数值卡（如“随机展示2件藏品”）以原文及证据形式进入公开事件，严格断言不回写 `totalItems=2`、不写均价、不干扰 solver 输入与估值。
   - `CurrentMatch.begin_next_match()` 彻底重置实时事件为 `[]`，同时历史归档数据完整持久化在存储中，实现跨局彻底隔离。

## 专项审计与关键证明

### 1. 费用字段防篡改审计（问题 A）
- **复现**：在 `e8106e2` 上，构造合法 confirmed public event 并篡改 `costClassification="FREE"`、`incrementalCost=0`、`sourceKind="PAID_INSTRUMENT"`，由于当时未验证费用字段且直接 `deepcopy`，篡改字段被准入并写入 `CurrentMatch`。
- **修复与验证**：通过 `verified_public_event` 字段门禁与 `canonical_public_event` 重构后，篡改 `costClassification="FREE"`、`incrementalCost=0`、`sourceKind="PAID_INSTRUMENT"` 均被 verifier 拒绝，准入结果为 `[]`；注入的额外键（如 `evilKey`）在准入后被严格剥离，输出严格限定为标准规范字典。

### 2. 真实 `PublicIntelLedger.update()` 跨回合审计（问题 B）
- 编写端到端单元测试 `test_real_public_intel_ledger_cross_round_same_text_audit`，不经过 mock event，对真实 `PublicIntelLedger` 连续喂送：R1 帧 A/B（确认 R1）-> R2 空 -> R3 帧 C/D（相同文本）。
- **结果**：`ledger.snapshot()` 严格返回 1 个事件（R1）。
- **根因与业务语义**：`dd12561` 设计 `PublicIntelLedger` 时明确为每局跨回合内容去重账本（`self.confirmed[key]` 键控，第 84 行 `if key in self.confirmed: continue`）。上游视觉账本在单局内针对相同公屏卡片内容全局只确认一次，不会为 R3 重新生成第二个事件；下游 `admit_public_card_events` 采用 `(id, round)` 键控，具备兼容多回合事件准入的能力，但上游账本单局内保持幂等单次确认。

### 3. 局间切换与账本生命周期串接审计（问题 C）
- 审计生产调用链：`begin_next_match` 在 `_manual_terminal_payload` 及测试中触发；大厅与场景离开时由 `_end_match_on_lobby_or_egress()` 调用 `clear_match_trunk()`。
- 修复 `clear_match_trunk()` 中未重置 `_intel_ledger` 的泄漏缺陷。
- 编写集成测试 `test_match_transition_pipeline_to_current_match_no_reinjection`：运行第 1 局并确认事件，同步至 `CURRENT_MATCH`；触发局间重置与 `clear_match_trunk`；喂入第 2 局新帧（无公屏卡）；断言第 2 局 `CURRENT_MATCH.snapshot()['publicCardEvents'] == []`，证实无残留回灌。

## 证据分类与边界说明

- **真实素材**：`tests/fixtures/intel_card_evidence_v1/r3_viewport.png` 用于验证真实快速 OCR 提取、公开卡与仪器卡在同为 47,286 金品均价时的来源区分、以及缓存复用产生 `is_physical_ocr=False` 的实际表现。此项明确为真实截图集成测试，不宣称独立多帧物理确认。
- **合成证据**：两帧独立物理确认、缓存复用抑制、跨帧冲突抑制、多回合独立事件、JSON 序列化往返、生命周期隔离、防篡改注入、局间无回灌等测试均使用明确标注为 `SYNTHETIC_TEST` 的数据。
- **当前边界**：
  - 严格遵守 `AUCTIONEER_PUBLIC != FREE`：`costClassification` 保持 `UNKNOWN`，`incrementalCost` 保持 `None`，原 `intelCost` 不变，估值与推荐不变。
  - `extraIntel` R1/R3 仅作为规则可用性提示，不伪造已观察事件。
  - 未重写 `PublicIntelLedger`，未触碰日常数据，未覆盖 v13，未开始 P5，未执行 70 秒实机滚仓，未制作最终冻结包。

## 测试命令与结果

1. **公开情报账本、防篡改与事件纵向全链路回归**：
   ```powershell
   $env:PYTHONPATH="core;app"
   d:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\python.exe -m unittest tests/test_public_intel_ledger.py
   ```
   **结果**：25 项测试全部 PASS（5.638s）。

2. **情报相关综合 8 套回归**（含卡片读取、来源区分、旁证持久化、历史回看文本、免费规则提示、差量情报与四席投影）：
   ```powershell
   $env:PYTHONPATH="core;app"
   d:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\python.exe -m unittest tests/test_public_intel_ledger.py tests/test_intel_card_readings.py tests/test_intel_card_source.py tests/test_intel_evidence_persistence.py tests/test_intel_evidence_presentation.py tests/test_free_intel_status.py tests/test_delta_intel.py tests/test_p2_seats_intel_projection_v1.py
   ```
   **结果**：46 项测试全部 PASS（4.086s）。

3. **视觉流水线与多帧确认历史回归**：
   ```powershell
   $env:PYTHONPATH="core;app"
   d:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\python.exe -m unittest tests/test_intel_card_evidence_v1.py
   ```
   **结果**：22 项测试全部 PASS（110.875s）。