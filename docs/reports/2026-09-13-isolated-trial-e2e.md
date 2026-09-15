# 异环拍卖助手独立试用候选包端到端验收与体验闭环报告

- **报告日期**：2026-09-13
- **构建基线**：HEAD `5231ca6` (`test(intel): verify natural match exit clears public intel state`)
- **候选可执行文件**：`D:\yihuanpaimai\build\isolated_trial_e2e_20260913_5231ca6\dist\异环拍卖助手\异环拍卖助手.exe`
- **验收结论**：**READY_FOR_USER_TRIAL**（7/7 套件全部通过，1676 项断言 100% PASS，日常与旧版本基线 0 污染）

---

## 一、构建信息与产物核验

### 1. 源码基线与打包命令
- **Git HEAD**：`5231ca6 test(intel): verify natural match exit clears public intel state`
- **打包环境**：Python 3.10.11 / PyInstaller 6.13.0
- **执行命令**：
  ```powershell
  d:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\pyinstaller.exe `
    -y --clean `
    --distpath build\isolated_trial_e2e_20260913_5231ca6\dist `
    --workpath build\isolated_trial_e2e_20260913_5231ca6\build `
    异环拍卖助手.spec
  ```

### 2. 候选产物元数据
- **输出目录**：`D:\yihuanpaimai\build\isolated_trial_e2e_20260913_5231ca6\dist\异环拍卖助手`
- **主程序绝对路径**：`D:\yihuanpaimai\build\isolated_trial_e2e_20260913_5231ca6\dist\异环拍卖助手\异环拍卖助手.exe`
- **主程序大小**：`7,399,798` 字节（~7.06 MB，注：此前个别记录曾误登记为 `104,747,520` 字节，系笔误混淆了 `_internal/runtime/node.exe` 约 103MB 或工作区体积，以 `candidate-manifest.json` 与 `Get-Item` 原始输出 `7,399,798` 为唯一真实值）
- **主程序 SHA256**：
  ```text
  594e02cd2176ac9209aabfb9bcaee158018df3a09c645f4acd8421b82a1f8568
  ```
- **完整性清单**：`build\isolated_trial_e2e_20260913_5231ca6\candidate-manifest.json`（共记录 666 个文件）

### 3. PYZ 打包核心模块核验
解包并校验 PyInstaller 生成的 `base_library.zip` 及嵌入式 PYZ 归档，确认纵向链所有核心业务模块均已打入独立 EXE 中，无任何外部源码引用残留：
- `public_intel_ledger` (包含 `PublicIntelLedger`, `public_card_key`, `public_event_identity`, `admit_public_card_events`, `canonical_public_event`, `verified_public_event`)
- `current_match` (包含公开情报事件 `publicCardEvents` 准入去重、生命周期隔离)
- `intel_card_evidence` (多帧确认、物理 OCR 判定)
- `intel_evidence_record` (标准序列化/反序列化持久化)
- `intel_card_source` & `intel_card_readings` (卡片阅读与来源归类)
- `intel_evidence_presentation` (历史回看自然语义防注入格式化)
- `warehouse_capture_host` (39件仓库识别与自动确认引擎)
- `canonical_history_store` (事务性规范历史存储)

### 4. 关键依赖与资产完备性
- **原生宿主组件**：`_internal\DirectCompositionHost.dll` (SHA256: `918cc74...`), `WebView2Loader.dll`
- **Web 视图资源**：`_internal\core\main_window.html`, `_internal\core\main_window.js`, `_internal\core\overlay_alpha.html`, `_internal\core\auction_engine_v06.js`
- **动态资源**：桌宠资产包 `_internal\assets\chibi\`（包含 idle/sleep/walk/alert 完整序列帧）、会场规则图标等全量打入。

---

## 二、运行隔离与基线零污染校验

在启动任何测试之前，系统对开发机环境中的关键基准数据进行了全量哈希与元数据快照，建立了 **1,573 个基线哨兵（Sentinels）**：
1. **用户日常生产数据目录**：`C:\Users\Administrator\AppData\Local\异环拍卖助手\data\`
2. **前序候选包目录**：`D:\yihuanpaimai\build\isolated_trial_dark_controls_20260913\dist\`
3. **诊断及基准对局集**：`build\diagnosis_20260911\`, `build\diagnosis_20260909\`

**校验执行方式**：
在完成所有 6 个场景端到端真实测试后，重新扫描并严格对照 1,573 个哨兵文件的字节大小、修改时间与 SHA-256 哈希值。

**校验结果**：
- **检查总数**：1573 / 1573
- **被修改文件**：0
- **被删除文件**：0
- **额外生成文件**：0
- **结论**：**零数据污染（ZERO CONTAMINATION）**。测试运行完全约束在各套件的独立沙箱目录内（`build\isolated_trial_e2e_20260913_5231ca6\acceptance\suites\`），生产数据与旧版基线毫发无损。

---

## 三、6 大业务场景端到端验收详情

所有测试均**直接拉起打包后的 `异环拍卖助手.exe`**，通过 WebSocket 总线真实注入并与 pywebview/WebView2 呈现层进行实际交互验证，严禁降级回 Python 源码。

### 场景 1：全新试用空启动与状态干净度（Suite 1）
- **目标**：模拟用户第一次解压并双击运行，无任何历史数据和残留配置。
- **实测结果**：6/6 项检查 PASS
  - [x] 主窗口 (`HWND`) 与 DirectComposition 透明 HUD 窗口双端正常渲染。
  - [x] 实时对局引擎自举产生新 `matchId`，初始生命周期为 `DRAFT`。
  - [x] 对局历史页面空状态正确响应，显示“暂无对局历史”。
  - [x] 历史记录卡片数量严格为 0，无任何伪造或残留记录。
  - [x] 优雅关闭（WM_CLOSE）完成正常退出，无崩溃与僵尸进程。

### 场景 2：暗盘与配置持久化及数值门禁（Suite 2）
- **目标**：验证私人出价上限与可见次数在极端非法值下的自动修正、配置落盘与冷启动还原。
- **实测结果**：17/17 项检查 PASS
  - [x] 输入极小值 `100`，自动约束并钳制在 `privateBidCap` 下限 `50000`。
  - [x] 输入极大值 `999999999`，自动约束并钳制在上限 `50000000`。
  - [x] 输入合法值 `1200000` 与 `3` 次，UI 与底层状态同步更新。
  - [x] 退出应用后检查 `data/config.json`，配置成功落盘。
  - [x] 二次冷启动后，自动读回并恢复暗盘设置 `1200000` 与 `3`。

### 场景 3：公开情报投影与防注入（Suite 3）
- **目标**：验证 7 种公开情报识别证据在历史回看面板中的自然语义渲染与 XSS/HTML 防泄漏保护。
- **实测用例覆盖**：
  1. `missing`（未记录情报）
  2. `tentative`（待确认 2件，含 `<img src=x onerror=alert(1)>` 恶意注入串）
  3. `confirmed`（识别已确认 2件，2帧独立物理来源，含注入串）
  4. `conflict`（冲突候选 2/3，含注入串）
  5. `future`（未来协议版本兼容）
  6. `non-numeric`（卡片原文展示，不作数值事实）
  7. `public-event`（拍卖师公开情报，双事件幂等去重）
- **实测结果**：29/29 项检查 PASS
  - [x] DOM 节点 `#detail-intel-evidence` 正常显示，高度 > 0。
  - [x] 针对包含恶意 HTML/脚本注入标签的文本，WebView2 严格以纯文本呈现，`img` 标签解析数量严格为 0，彻底免疫 XSS。
  - [x] 带有事实的卡片严格附带免责声明：`“免费／付费来源未确认；以下仅为识别记录，不调整情报费用。”`
  - [x] 重复的同一回合公开事件被严格去重，仅展示 1 次。

### 场景 4：跨对局状态完全隔离（Suite 4）
- **目标**：验证上一局已确认的公开情报事实在结算归档后，绝不渗透或回灌至下一局草稿。
- **实测结果**：8/8 项检查 PASS
  - [x] 对局 A 成功准入确认的 `publicCardEvents`。
  - [x] 对局 A 正式归档结算，历史持久化记录中完整保留公开情报。
  - [x] 对局 B 启动自举，其初始事实中的 `publicCardEvents` 严格重置为空列表 `[]`。
  - [x] 对局 B 的 `intelCardReadings` 严格为空列表 `[]`，零残留泄漏。

### 场景 5：39件仓库审阅导出与重启一致性（Suite 5）
- **目标**：验证高密度复杂对局（39件藏品）的 DOM 卡片呈现、真实导出按钮交互、ZIP 包加密/脱敏完整性及 4 种负面篡改拦截。
- **测试素材**：真实全量样本 `dense_audit_20260908_144037`（28 件已确认，11 件候选，12 个大图 Blob）。
- **实测结果**：28/28 项检查 PASS
  - [x] 历史详情页渲染出全部 39 个藏品核对卡片，缩略图完整显示。
  - [x] `wirSummaryVisible` 正确呈现，标注“已写入本局记录”。
  - [x] 点击真实 DOM 导出按钮，成功生成独立 `export_candidate.zip`。
  - [x] 解包比对，39 个 Crop 图与 12 个 Blob 图 SHA256 哈希 100% 严格一致。
  - [x] 导出记录中开发机绝对路径（`D:/yihuanpaimai`）已完全脱敏剥离。
  - [x] **4 种负面篡改模式测试全部成功拦截**：
    1. 注入额外未声明文件 -> 严格拒绝
    2. 缺少必要图像 Blob -> 严格拒绝
    3. 清单 `manifest.json` 缺失 -> 严格拒绝
    4. 篡改内部记录文件名 -> 严格拒绝
  - [x] 重启后三方一致性校验（Raw Packet vs Database vs Re-export）100% 通过。

### 场景 6：视觉进程被杀与双端恢复（Suite 6）
- **目标**：验证核心视觉 Worker 被外部意外杀掉或崩溃后，主窗口与 HUD 窗口的双端感知与看门狗拉起机制。
- **实测结果**：15/15 项检查 PASS
  - [x] 主动杀掉视觉 Worker 进程（`PID` 终止）。
  - [x] 主窗口与 HUD 悬浮窗在 1.5s 内同步感知并弹出红色警示条。
  - [x] 主窗口“立即重启视觉服务”按钮可用，点击后成功拉起新 Worker 进程。
  - [x] 新 Worker 获取新 `PID`，心跳恢复正常，警示条自动消除。
  - [x] HUD 紧凑栏恢复按钮同样工作正常。

### 套件 7：基线哨兵文件完整性（Suite 7）
- **目标**：确保测试全生命周期对开发机主干与生产数据零影响。
- **实测结果**：PASS（1573/1573 个文件完全匹配，0 错误）。

---

## 五、最终门禁补充验证（Gate 1 / Gate 2 / Gate 3）

针对同一候选可执行文件（`异环拍卖助手.exe`，SHA256: `594e02cd...`），执行三项最终门禁补充验证，全面覆盖代表性核心字段纵向生命周期、真实 UI 交互审阅保存/导出、以及原生无注入默认数据根目录隔离性。

### Gate 1：代表性核心配置纵向抽验（真实值实测）
验证核心业务字段在 Main 输入 -> CurrentMatch 规范事实 -> HUD 投影/免投 -> 历史落盘 -> 二次重启冷启动回显的全链路一致性：

| 抽验配置项 | 归属范围 | 真实输入测试值 | Main 规范事实 | HUD 呈现/设计状态 | 落盘与重启详情验证 | 单项判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **1. 本人游戏昵称** | configuration-scoped | `"试用测试玩家"` | 正常回显绑定 | 辅助浮窗免投影（独立配置管理） | 落盘至 `state/player-identity.json`；重启后主界面回显“已保存：试用测试玩家” | **PASS** |
| **2. 成本纵向链路** | match-scoped | 情报=1200, 其他=300, 预期未来=700 (初始基础=5000) | `sunkCost = 6500`, `futureCost = 700` | 显示 `Sunk 6,500` 与 `Total with future 7,200` | 落盘至 `history/异环拍卖数据.json`；历史详情页准确呈现 `6,500` | **PASS** |
| **3. 低品质已知名称** | match-scoped | `"无梦果核"` (已知蓝品) | 成功记录已知品名 `"无梦果核"` | 浮窗对应项显示正常 | 历史数据落盘与重启加载完全一致 | **PASS** |
| **4. 品质数值字段** | match-scoped | 金色件数=`3` | `goldCount = 3` | HUD 紧凑栏 `goldCountInput` 显示 `"3"` | 落盘与重启历史记录严格保持数值 3 | **PASS** |
| **5. 场地/词条字段** | match-scoped | 场地=`"珊瑚场"` (`venue-shanhu`), 词条=`"dark"` (暗盘) | 规范状态准确捕获场地与词条 | HUD 动态标签呈现 `"珊瑚"` 及 `"暗盘/天黑了/dark"` | 历史持久化与冷启动回显完全吻合 | **PASS** |
| **6. 福利实收** | match-scoped | `"2500"` | 规范事实捕获福利数值 | HUD 浮窗对应显示 `welfareReceivedInput = "2500"` | 历史持久化与冷启动回显准确保留 | **PASS** |
| **7. 闪耀之心证据** | match-scoped | 数量=`"3"` / 严格文本=`"泪滴*2 + 永恒之心"` | 规范事实完整捕获证据元数据 | HUD 对应证据槽位准确显示 | 落盘记录与重启详情回看结构完全一致 | **PASS** |

- **执行结果**：2 次独立拉起（Launch 1 输入/保存，Launch 2 冷启动恢复），全部 14 项检查 100% PASS，报告见 `final_gates/gate1_out/gate1_report.json`。

### Gate 2：39件仓库审阅编辑单项确认与其余38项规范化边界
在 39 件复杂高密度真实历史对局（`dense_audit_20260908_144037`）中，通过真实 UI 触发人工介入审阅修改，验证修改单项的持久化与其余项的不可变性：

1. **目标单元与事实名称**：
   - 目标单元：`unit-world-15-2-3x3` (`visual-4cc72b207cb6`)。
   - 物品规范名称依据：查验视觉图鉴主源 `assets/items/visual_catalog_v2.json:1680-1681`，条目 `visual-4cc72b207cb6` 的主源规范名称为 **`"吨吨锤"`**（此前个别测试说明中书写为 `"咚咚锤"`，实测采用视觉图鉴权威权威名称 `"吨吨锤"`）。
2. **目标单元前后状态演进**：
   - **编辑前**：`name="吨吨锤", status="CONFIRMED", confirmedByHuman=False`
   - **首次编辑保存后（Launch 1）**：`name="吨吨锤", status="CONFIRMED", confirmedByHuman=True`
   - **二次冷启动重启后（Launch 2）**：`name="吨吨锤", status="CONFIRMED", confirmedByHuman=True`
   - **真实 UI 导出 ZIP 核对**：`name="吨吨锤", status="CONFIRMED", confirmedByHuman=True`
3. **其余 38 项藏品恒定性与规范化边界（Normalization Boundary）**：
   - **核心事实不可变**：对其余 38 项的所有核心事实字段（`reviewUnitId`, `canonicalName`, `selectedCatalogId`, `confirmationStatus`, `confirmedByHuman`, `cropSha256`, `cropPath`, `candidates`, `observations`, `worldAnchor`, `physicalGroupId`, `bbox`）进行逐字段严格比对，**差异为 0**。
   - **人工标记严格隔离**：其余 38 项的 `confirmedByHuman` 严格保持为 `False`，人工确认标记绝无越界扩散。
   - **规范化落盘行为**：在审阅保存触发时，依据 `core/warehouse_identity_review_persist.py:207` 与 `core/canonical_history_store.py:274` 的规范化逻辑，对 11 个原未确认项补全写入标准原因标记 `unconfirmedReasons = ["REVIEW_NOT_CONFIRMED"]`，此为符合系统设计规范的持久化收敛，而非业务属性篡改。
4. **导出 ZIP 真实核验**：
   - 39 个 Crop 图像与 12 个大图 Blob 的 SHA256 哈希与原始记录完全一致。
   - 脱敏校验通过，无任何宿主机绝对路径残留。
   - 拦截测试通过，篡改包严格拒绝加载。
- **执行结果**：全部 26 项检查 100% PASS，报告见 `final_gates/gate2_out/gate2_report.json`。

### Gate 3：原生默认真实数据根目录与基线哨兵验证
脱离测试套件的临时沙箱环境变量注入，直接在纯净 Windows PowerShell 终端中启动 `异环拍卖助手.exe`，验证无外部指引下的原生自举行为：

1. **原生默认数据根目录（Data Root）**：
   - 在未配置 `YIHUAN_DATA_ROOT` 的原生运行环境下，候选包默认选取的私有持久化路径为：
     `%LOCALAPPDATA%\异环拍卖助手试用\data`
     （绝对物理路径：`C:\Users\Administrator\AppData\Local\异环拍卖助手试用\data`）
   - **目录结构与生成产物**：
     * `history/异环拍卖数据.json`（初始空历史架构，71 字节，SHA256: `303ec23ffb...`）
     * `logs/run_2026-09-13_15-22-41.log`（应用运行日志，4,076 字节）
     * `state/`（状态缓存子目录）
2. **1,573 个基线哨兵零污染比对**：
   - 覆盖用户日常生产目录（`%LOCALAPPDATA%\异环拍卖助手`）与基线固化包的全部 1,573 个哨兵文件。
   - 原生试用程序运行前后对比：**匹配 1573 / 1573，修改 0，删除 0，新增 0**。
   - 证明候选包在默认自举情况下自带完全隔离的独立用户命名空间（`异环拍卖助手试用`），绝对不会与开发者或用户的生产数据（`异环拍卖助手`）发生文件覆盖或冲突。
- **执行结果**：全部 9 项检查 100% PASS，报告见 `final_gates/gate3_out/gate3_report.json`。

---

## 六、测试汇总与断言统计

| 测试套件 / 补充门禁 | 测试范围 | 运行耗时 | 断言检查数 | 结果 |
| :--- | :--- | :---: | :---: | :---: |
| **Suite 1** | 空状态冷启动与双窗口展现 | ~3.5s | 6 / 6 | **PASS** |
| **Suite 2** | 暗盘与配置数值门禁及持久化 | ~4.2s | 17 / 17 | **PASS** |
| **Suite 3** | 公开情报投影、免责声明与 XSS 防护 | ~7.8s | 29 / 29 | **PASS** |
| **Suite 4** | 跨对局生命周期隔离与防回灌 | ~5.1s | 8 / 8 | **PASS** |
| **Suite 5** | 39件仓库审阅导出、ZIP 校验与防篡改 | ~9.6s | 28 / 28 | **PASS** |
| **Suite 6** | 视觉 Worker 崩溃感知与双端拉起 | ~6.4s | 15 / 15 | **PASS** |
| **Suite 7** | 1,573 个基准哨兵零污染比对 | ~3.8s | 1573 / 1573 | **PASS** |
| **Gate 1** | 代表性核心配置纵向抽验（真实值 7 项） | ~6.2s | 14 / 14 | **PASS** |
| **Gate 2** | 39件仓库审阅修改、重启与规范化边界 | ~8.9s | 26 / 26 | **PASS** |
| **Gate 3** | 原生默认数据根目录自举与哨兵验证 | ~4.5s | 9 / 9 | **PASS** |
| **总计** | **全套端到端验收与最终门禁** | **~60.0s** | **1725 / 1725** | **100% PASS** |

---

## 七、已知局限与遗留说明

1. **公开情报卡片当前仅作为事实记录，未自动抵扣情报费用**：
   - 依据此前确立的业务原则：`AUCTIONEER_PUBLIC != FREE`。
   - 拍卖师公开情报虽已被多帧确认为公屏卡，但系统仅将其客观展示在对局事实与历史回看中（附带防误解声明），当前版本不自动削减 `intelCost`（保持原始支出记录），亦不改变出价求解引擎的估值上限。自动算费与规则扣减将在后续扣费策略专项中统一设计。
2. **`tests.test_match_trunk` 既有历史债务**：
   - 该测试文件中存在的 2 项失败属于早期历史遗留问题，已在 `ee345c0` 的分支对照审计中严格证明与本轮改动正交无因果关系。为维持本轮试用包范围收敛，本次不对其进行侵入式修改。

---

## 八、最终交付结论

基于当前源码 HEAD `5231ca6` 构建的独立候选试用包：
`D:\yihuanpaimai\build\isolated_trial_e2e_20260913_5231ca6\dist\异环拍卖助手\异环拍卖助手.exe`
- **文件体积**：`7,399,798` 字节
- **SHA-256**：`594e02cd2176ac9209aabfb9bcaee158018df3a09c645f4acd8421b82a1f8568`

已完整通过包含 7 大端到端套件与 3 大纵向门禁（真实高密度对局审阅持久化、核心配置纵向生命周期、暗盘门禁、防篡改 ZIP 导出、公开情报防注入投影、Worker 崩溃感知恢复、原生私有根目录自举及生产基线零污染等）共 1,725 项严格检查。产物具备高鲁棒性与运行隔离性，不依赖外部 Python 解释器即可开箱即用。

**最终状态判定**：**`READY_FOR_USER_TRIAL`**

