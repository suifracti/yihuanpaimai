# 0.6 ↔ 0.65 Schema & Data Contract 审计报告

> **审计时间**：2026-08-16  
> **审计基准**：原始 0.6（`lab/index.html`、`core/auction_engine_v06.js`、`core/solver_core_v06.js`、`assets/business_sot_v06.json`、`tools/migrate-v06-schema6.mjs`）、当前 0.65 运行时（`core/vision_contract.py`、`core/delta_intel.py`、`core/session_fsm.py`、`core/auto_archiver.py`、`core/auction_brain.py`）及 151 局历史数据库（`异环拍卖数据.json`）。  
> **审计结论**：**C. 明显 Contract Drift**。可以运行，但 0.65 Match Record 丢失了核心品质均价与结构化已知形状约束，导致 0.6 Solver 退化为无约束盲算。

---

## 一、0.6 数据模型盘点

在原始 0.6 架构中，数据模型由以下分层组成：

### 1. 业务输入模型 (Business Input Schema)
* **场地与规则上下文**：
  * `venue`：中文名称（中级场 · 珊瑚场 / 高级场 · 密林场 / 高级场 · 白夜场 / 顶级场 · 海沫场）。
  * `box`：完整箱名（如「实木宝箱 · 中级藏品概率提升」）。
  * `fieldCondition`：Canonical 词条 ID（`standard`, `dark`, `gem_boost`, `high_risk`, `steady`, `welfare_boost`, `intel_leak`, `price_drop`）。
  * `avgValueBasis`：均价计算基准（`public_only`, `all_inclusive`）。
  * `privateBidCap`：暗标出价上限。
  * `bidActionCount`：允许加价次数。
  * `welfare`：福利政策对象（`base`, `rate`）。
  * `sparkle`：闪光/璀璨机制上下文（`transformedOneByOneCount`, `verifiedGemItems`, `complete`, `parsedCount`, `validationError`）。
* **角色与仪器组**：
  * `character`：竞拍帮手（如「达芙蒂尔」、「浔」）。
  * `role`：参拍身份（`"参与竞拍"` / `"纯看客"`）。
  * `toolGroup`：0.6 Solver 预设仪器算法组（默认 `"group1"` / `"group2"`）。
* **成本与目标**：
  * `costs`：门票与情报成本细分（`entry`, `info/intel`, `other`, `sunkCost`, `futureIncrementalCost`, `total`）。
  * `cost`：总成本数值。
  * `targetProfit`：目标利润（默认 30,000）。
  * `targetROI`：期望 ROI 目标。

### 2. 藏品品质与统计模型 (Multi-Tier Capacity & Stats)
* **容量统计**：
  * `q`：高阶总件数 $Q = G + P + R$。
  * `totalItems`：全场藏品总件数（如大厅公开的 66 件）。
  * `totalGrid`：仓库总占格数。
* **六大品质分层**：
  * **红 (Red)**：`redCount`、`minRed`、`redMin`、`redMax`、`knownRed`（字符串如 `"81088"`、`"500001+200201"`）、`decisionKnownRed`、`redItems`、`settlementVerifiedRedItems`、`redInventoryComplete`。
  * **金 (Gold)**：`goldCount`、`minGold`、`goldAvg`、`goldTotal`、`goldGrid`、`knownGold`（字符串如 `"51077"`、`"101537+18031"`）、`goldGroups`。
  * **紫 (Purple)**：`purpleCount`、`minPurple`、`purpleAvg`、`purpleGrid`、`knownPurple`、`purpleGroups`。
  * **蓝 (Blue)**：`blueCount`、`blueAvg`、`blueGrid`。
  * **绿 (Green)**：`greenCount`、`greenAvg`、`greenGrid`。
  * **白 (White)**：`whiteCount`、`whiteAvg`、`whiteGrid`。
* **统计与估值**：
  * `avg`：高阶均价。
  * `systemEstimate`：系统估价。
  * `singleAvg` / `nineAvg`：单件/九件均价。
  * `publicNote`：公开情报文本注记。

### 3. Solver 内部状态与候选空间 (State Inference & Candidate Space)
* **状态枚举**：
  * `states`：合法状态列表，每项包含 $\{G, P, R, \text{sampleCombo}, \text{minVal}, \text{maxVal}, \text{weight}\}$。
* **金色状态推断 (`goldInference`)**：
  * `goldMatchCount`：满足硬约束的金色组合总数。
  * `goldMatchCountExact`：组合数是否完全精确（未被超时截断）。
  * `candidateGs`：所有合法的金色件数数组（如 `[3, 4]`）。
  * `uniqueG`：是否 $G$ 唯一。
  * `uniqueCombination`：是否金色组合完全唯一确定。
  * `byG`：按 $G$ 分组的组合详情与总价。
  * `remainingByG`：按每个 $G$ 展开的剩余紫/红关系（$P+R = Q - G$；当 $P$ 已知时推导 $R = Q - G - P$）。
* **分布与边界**：
  * `candidatePs`：候选紫色件数列表。
  * `probabilityProfile`：全量概率分布（`shadowWhole`, `p20`, `p50`, `p80`, `p90`, `pdf`, `cdf`）。
  * `componentBreakdown`：红/金/紫独立贡献方差。
  * `theoreticalMin` / `theoreticalMax`：理论下界与上界。
  * `structuralCenter`：结构均值。
  * `roundingAudit`：取整审计（`floor`/`round`/`ceil`）。
  * `solverStatus`：求解状态（`valid`, `no-match`, `fallback`, `incomplete`, `timeout`, `diagnostic`）。

### 4. 结算与回放模型 (Settlement & Lifecycle Record)
* **结算字段**：`actualTotal`, `clearingPrice`, `bid` / `highestPersonalBid`, `purchaseSpend`, `acquired`, `realizedProfit`, `resultReason`, `winner`, `realizedState`, `settlement`。
* **对局时序**：`rounds`, `screenshots`, `ocrEvidence`, `migrationAuditV06`。

---

## 二、0.65 数据模型盘点

在当前 0.65 运行时中，数据通过以下管道流转：

```
VisionPipeline (OCR / 视觉特征提取)
   ↓
VisionObservation (跨帧瞬时观测 Contract)
   ↓
DeltaIntelManager (增量情报累加与已知形状聚合)
   ↓
AuctionSessionFSM (SessionContext 生命周期状态机)
   ↓
AuctionBrain (推流 Payload & V8 求解调用)
   ↓
AutoArchiver (终局落盘: 追加 Match Record 写入 异环拍卖数据.json)
```

### 1. 0.65 视觉观测与会话模型 (VisionObservation / SessionContext)
* **场地与局况**：`venue`（代码枚举如 `"shanhu"`）、`box`（完整箱名）、`boxType`（`wood`, `glass`, `iron`）、`fieldCondition`、`round`、`timer`。
* **情报与藏品**：`intel`（`q`, `avg`, `purple`, `knownPurple: []`, `knownGold: []`）。
* **出价与座位**：
  * `bids`（`myBid`, `leaderBid`, `leaderName`, `isMyLead`）。
  * `seats`（4 个座位的 `slot`, `name`, `bid`, `currentBid`, `isMe`）。
  * `opponents`（3 个对手出价）。
  * `historicalBids`（`< cur_round` 的历史叫价字典）。
  * `finalBids`（所有回合的终局叫价字典）。
  * `leaderTies`（平局领跑者列表）。
* **仓库网格**：`warehouseVision` / `warehouseSlots`。
* **结算大屏**：`settlement`（`isSettlement`, `clearingPrice`, `actualTotal`, `profit`, `items: [{name, price, size, rarity}]`）。

### 2. 0.65 Match Record 落盘模型 (AutoArchiver Schema 6)
* `id`, `productVersion: "v0.65"`, `playedAt`, `venue`, `character`, `toolGroup`, `boxType`, `box`, `fieldCondition`。
* `q`, `avg`, `purple` (及 `purpleCount`), `totalGrids`。
* `clearingPrice`, `actualTotal`, `realizedProfit`, `costs`, `purchaseSpend`, `isAcquired` (及 `acquired`), `winnerName` (及 `winner`), `myFinalBid`, `myName`, `opponents`。
* `historicalBids`, `finalBids`, `leaderTies`。
* `identifiedShapes: { knownGold: [], knownPurple: [], knownRed: [] }`。
* `settlementItems: [...]`, `roundTimeline: [...]`, `rounds: [...]`, `prediction`。

---

## 三、历史数据字段统计 (`异环拍卖数据.json` 151 局)

| 字段分类 | 字段名 | 记录数 / 151 | 非空占比 | 数据类型 | 典型样本值 / 规范 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **基础元数据** | `id` | 151 | 100.0% | `str` | `r-mssnm7b8-s29`, `auto_1771142400` |
| | `productVersion` | 151 | 100.0% | `str` | `v0.6` (142条), `v0.65` (9条) |
| | `playedAt` / `date` | 151 | 100.0% | `str` | `2026-08-14T20:05:00.000Z` |
| | `venue` | 151 | 100.0% | `str` | `中级场 · 珊瑚场`, `shanhu` |
| | `box` / `boxType` | 151 | 100.0% | `str` | `实木宝箱 · 中级藏品概率提升`, `wood` |
| | `fieldCondition` | 151 | 100.0% | `str` | `standard`, `dark`, `gem_boost` |
| **角色与仪器** | `character` | 151 | 100.0% | `str` | `达芙蒂尔` (149条), `浔` (2条) |
| | `toolGroup` | 24 | 15.2% | `str` | `group1`, `高级品鉴仪器组` |
| | `costs` / `cost` | 151 | 100.0% | `dict / int` | `{'entry': 5000, 'intel': 45000, 'total': 50000}` |
| **全品质统计** | `q` | 151 | 94.7% | `int` | `15`, `9`, `13` |
| | `totalItems` | 112 | 7.9% | `int` | `23`, `32`, `66` |
| | `totalGrid` / `totalGrids` | 113 | 4.6% | `int` | `84`, `71` |
| | `goldAvg` | 133 | 54.3% | `int` | `33538`, `60071` |
| | `goldCount` | 111 | 13.9% | `int` | `4`, `10` |
| | `goldGrid` / `goldTotal` | 112 | 5.3% | `int` | `16`, `32` |
| | `knownGold` | 111 | 33.8% | `str` | `"51077"`, `"101537+18031"` |
| | `purpleCount` / `purple` | 135 | 56.3% | `int` | `5`, `3` |
| | `purpleAvg` | 112 | 6.0% | `int` | `2007`, `6613` |
| | `purpleGrid` | 88 | 6.0% | `int` | `21`, `17` |
| | `knownPurple` | 111 | 20.5% | `str` | `"18075+8128"`, `"2011*2"` |
| | `blueCount` / `blueAvg` | 142 | 5.3% | `int` | `blueCount: 7`, `blueAvg: 3462` |
| | `greenCount` / `greenAvg` | 86 | 0.0% | `null` | 预留占位字段 |
| | `whiteCount` / `whiteAvg` | 86 | 0.0% | `null` | 预留占位字段 |
| | `redCount` / `minRed` | 119 | 78.8% | `int` | `minRed: 1`, `redCount: 2` |
| | `knownRed` / `decisionKnownRed`| 142 | 18.5% | `str` | `"81088"`, `"500001+200201"` |
| | `settlementVerifiedRedItems` | 142 | 2.6% | `str` | `"150051"`, `"52000"` |
| | `redInventoryComplete` | 142 | 50.3% | `bool` | `False`, `True` |
| | `avg` (0.65混用) | 10 | 2.0% | `int` | `67571`, `68928` |
| **结算与收益** | `actualTotal` | 151 | 97.4% | `int` | `403298`, `972970` |
| | `clearingPrice` | 151 | 44.4% | `int` | `400000`, `454444` |
| | `realizedProfit` | 10 | 6.6% | `int` | `518526`, `256918` |
| | `acquired` / `isAcquired` | 151 | 16.6% | `bool` | `True`, `False` |
| | `winner` / `winnerName` | 151 | 17.2% | `str` | `"本人拍下"`, `"PLAYER_LOCAL"` |
| | `opponents` / `seats` | 9 | 6.0% | `list` | 0.65 结构化座位出价 |
| | `historicalBids` / `finalBids` | 9 | 6.0% | `dict` | 0.65 回合归属历史字典 |
| | `settlementItems` | 9 | 6.0% | `list` | 0.65 结算单件物品识别列表 |
| **求解与推演** | `prediction` | 121 | 72.2% | `dict` | 求解器完整输出快照 |
| | `solverStatus` | 151 | 100.0% | `str` | `legacy`, `valid`, `fallback` |

---

## 四、完整 Field Matrix

| 业务语义 | 0.6 字段 | 0.6 来源 | 0.6 Solver 消费? | 0.6 UI 消费? | 历史 JSON 存在? | 0.65 Vision 字段 | 0.65 Context 字段 | 0.65 MatchRecord 字段 | 类型 | 兼容性状态 | 核心差异与审计结论 |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| **场地标识** | `venue` | SOT / UI | 是 | 是 | 是 | `venue` | `venue` | `venue` | `str` | `RENAMED` | 0.6 中文全称 vs 0.65 英文缩写（`shanhu`） |
| **宝箱类型** | `box` | SOT / UI | 是 | 是 | 是 | `box` / `boxType` | `box` / `boxType` | `box` | `str` | `RENAMED` | 0.6 识别完整箱名，0.65 早期混入 `boxType` |
| **场地词条** | `fieldCondition` | SOT / UI | 是 | 是 | 是 | `fieldCondition` | `fieldCondition` | `fieldCondition` | `str` | `DIRECT` | Canonical 词条 ID（`standard` 等）完全一致 |
| **竞拍帮手** | `character` | SOT / UI | 否 | 是 | 是 | `character` | `character` | `character` | `str` | `DIRECT` | 0.6 默认达芙蒂尔；0.65 支持大厅识别 |
| **Solver 仪器组** | `toolGroup` | SOT / UI | 是 | 是 | 是 | — | `toolGroup` | `toolGroup` | `str` | `MISSING_IN_065` | 0.6 用于算法分支（`group1`）；0.65 未向下传递 |
| **大厅仪器组** | `lobbyToolGroup` | 大厅 OCR | 否 | 否 | 否 | `lobbyToolGroup` | `lobbyToolGroup` | `toolGroup` (混写) | `str` | `SEMANTIC_MERGED`| 视觉大厅仪器与 Solver toolGroup 被错误同名混写 |
| **高阶件数 Q** | `q` | OCR / Input | 是 | 是 | 是 | `intel.q` | `q` | `q` | `int` | `DIRECT` | 语义完全一致（$Q = G + P + R$） |
| **全场总件数** | `totalItems` | 大厅公开 OCR | 否 | 是 | 是 | — | — | — | `int` | `MISSING_IN_065` | OCR 读到「总数量66件」，0.65 无字段丢弃 |
| **仓库总格数** | `totalGrid` | OCR / Input | 是 | 是 | 是 | — | `totalGrids` | `totalGrids` | `int` | `RENAMED` | 0.6 `totalGrid` vs 0.65 `totalGrids` |
| **金色均价** | `goldAvg` | OCR / Input | 是 | 是 | 是 | `intel.avg` (混用) | `avg` (混用) | `avg` (混用) | `int` | `SEMANTIC_MERGED`| 0.65 将金/紫均价写入同一 `avg` 导致覆盖 |
| **紫色均价** | `purpleAvg` | OCR / Input | 是 | 是 | 是 | `intel.avg` (混用) | `avg` (混用) | `avg` (混用) | `int` | `SEMANTIC_MERGED`| 0.65 缺失独立的 `purpleAvg` |
| **蓝色均价** | `blueAvg` | OCR / Input | 是 | 是 | 是 | — | — | — | `int` | `MISSING_IN_065` | 0.6 消费，0.65 视觉未暴露 |
| **绿色均价** | `greenAvg` | OCR / Input | 是 | 是 | 否 | — | — | — | `int` | `MISSING_IN_065` | 0.6 预留，0.65 未暴露 |
| **白色均价** | `whiteAvg` | OCR / Input | 是 | 是 | 否 | — | — | — | `int` | `MISSING_IN_065` | 0.6 预留，0.65 未暴露 |
| **紫色件数** | `purpleCount` | OCR / Input | 是 | 是 | 是 | `intel.purple` | `purple` | `purple` / `purpleCount` | `int` | `RENAMED` | 0.6 消费 `purpleCount`，0.65 为 `purple` |
| **金色件数** | `goldCount` | OCR / Input | 是 | 是 | 是 | — | — | — | `int` | `MISSING_IN_065` | 0.65 未暴露 `goldCount` |
| **红色件数** | `redCount` | OCR / Input | 是 | 是 | 是 | — | — | — | `int` | `MISSING_IN_065` | 0.65 未暴露 `redCount` |
| **已知金色** | `knownGold` | 形状 / OCR | 是 | 是 | 是 | `intel.knownGold` | `knownGold` | `identifiedShapes.knownGold` | `str` vs `list` | `TYPE_CHANGED` | 0.6 为字符串/算式，0.65 为结构化 List |
| **已知紫色** | `knownPurple` | 形状 / OCR | 是 | 是 | 是 | `intel.knownPurple` | `knownPurple` | `identifiedShapes.knownPurple` | `str` vs `list` | `TYPE_CHANGED` | 同上 |
| **已知红色** | `knownRed` | 形状 / OCR | 是 | 是 | 是 | `intel.knownRed` | `knownRed` | `identifiedShapes.knownRed` | `str` vs `list` | `TYPE_CHANGED` | 同上 |
| **金色状态推断** | `goldInference`| Solver 产出 | 是 | 是 | 是 | — | — | — | `dict` | `MISSING_IN_065` | 0.65 Payload 丢弃了 Candidate 展开对象 |
| **候选金色数** | `candidateGs` | Solver 产出 | 是 | 是 | 是 | — | — | — | `list[int]` | `MISSING_IN_065` | 0.65 HUD 无法展示候选 G 集合 |
| **候选紫色数** | `candidatePs` | Solver 产出 | 是 | 是 | 是 | — | — | — | `list[int]` | `MISSING_IN_065` | 同上 |
| **理论极值界** | `theoreticalMin/Max`| Solver 产出 | 是 | 是 | 是 | — | — | — | `int` | `MISSING_IN_065` | 0.65 未向上透传 |
| **分量方差分解** | `componentBreakdown`| Solver 产出 | 是 | 是 | 是 | — | — | — | `dict` | `MISSING_IN_065` | 0.65 未向上透传 |
| **门票与总成本** | `cost` / `costs`| 计算 / 门票+情报 | 是 | 是 | 是 | — | `costs` | `costs` / `cost` | `dict/int` | `DIRECT` | 结构完全兼容 |
| **成交价** | `clearingPrice` | 结算 OCR | 否 | 是 | 是 | `settlement.clearingPrice` | `clearingPrice` | `clearingPrice` | `int` | `DIRECT` | 结算权威成交价 |
| **真实总值** | `actualTotal` | 结算 OCR | 否 | 是 | 是 | `settlement.actualTotal` | `actualTotal` | `actualTotal` | `int` | `DIRECT` | 结算权威真实总额 |
| **实际净利** | `realizedProfit`| 结算计算 | 否 | 是 | 是 | `settlement.profit` | `profit` | `realizedProfit` | `int` | `DIRECT` | 0.65 正式持久化 |
| **竞得归属** | `acquired` / `isAcquired` | 结算判定 | 否 | 是 | 是 | — | `isAcquired` | `acquired` / `isAcquired` | `bool` | `DIRECT` | 双写兼容 |
| **竞得者名** | `winner` / `winnerName` | 结算判定 | 否 | 是 | 是 | — | `winnerName` | `winner` / `winnerName` | `str` | `DIRECT` | 双写兼容 |
| **4 座位叫价** | `seats` / `opponents` | OCR 提取 | 否 | 是 | 是 | `seats` | `seats` / `opponents` | `opponents` | `list[dict]` | `DIRECT` | 0.65 结构化保存 |
| **历史回合槽** | `historicalBids`| 视觉回溯 | 否 | 是 | 是 | `historicalBids` | `historicalBids` | `historicalBids` | `dict` | `MISSING_IN_06` | 0.65 独有能力 |
| **终局叫价表** | `finalBids` | 视觉管道 | 否 | 是 | 是 | `finalBids` | `finalBids` | `finalBids` | `dict` | `MISSING_IN_06` | 0.65 独有能力 |
| **结算藏品切片**| `settlementItems`| 结算视觉识别 | 否 | 是 | 是 | `settlement.items` | `settlementData.items` | `settlementItems` | `list[dict]` | `MISSING_IN_06` | 0.65 独有能力 |

---

## 五、实际兼容性测试结果与分类

在 Node.js 隔离 Sandbox 中实际加载 `core/auction_engine_v06.js`，传入 0.65 最新 Match Record 进行推演测试：
1. **测试结果**：
   * `solveAuctionPipeline(rec065)` 返回 `solverStatus: 'valid'`，但由于 `knownGold` / `knownPurple` 位于嵌套的 `identifiedShapes` 内部，0.6 从顶层取到空值 `""`。
   * `goldAvg` / `purpleAvg` 未能传入，0.65 仅传入了单一 `avg`，导致 0.6 无法建立金色特化取整约束。
   * `solveExactStatesSync(rec065)` 输出了 33 个未剪枝的候选状态（从 $G=15$ 到 $G=4$），原本确定的对局退化为完全模糊状态。
2. **分类定级**：
   * **C. 明显 Contract Drift**。可以运行，但由于缺少 Adapter 对嵌套字典的展平与多品质均价映射，导致已知约束全部失效，求解器发生严重降级。

---

## 六、State Inference / Candidate Space 的实现来源

0.6 的推断可解释性与候选空间可视化来源于 `solver_core_v06.js` 中的 `summarizeGold` 函数：
* **核心数学关系**：
  $$\text{legalRows} = \{ (G, \text{combinations}) \mid Q - G - P_{\text{fixed}} \ge \text{minRed} \}$$
* **字段生成**：
  * `candidateGs = legalRows.map(x => x.G)`
  * `goldMatchCount = legalRows.reduce((sum, x) => sum + x.combinationCount, 0)`
  * `remainingByG = legalRows.map(x => ({ G: x.G, PplusR: Q - x.G, P: P_fixed, R: Q - x.G - P_fixed }))`
* **UI 渲染**（在 `lab/index.html`）：
  * 渲染约束类型标签（`金总价硬约束` / `金均取整约束` / `金色离散组合`）。
  * 展开呈现每个 $G$ 对应的组合数与样例藏品，以及剩余紫红关系 $P+R = Q - G$。

---

## 七、未来架构设计建议

```
                ┌───────────────────────────────┐
                │  0.6 Historical JSON Records  │
                └──────────────┬────────────────┘
                               │ (Legacy Normalizer)
                               ▼
                ┌───────────────────────────────┐
                │     Canonical MatchRecord     │ <── [SchemaVersion: 7]
                │   (完整保留视觉事实与全局情报)  │
                └──────────────▲────────────────┘
                               │ (Perception Ingestion)
                ┌──────────────┴────────────────┐
                │      0.65 Live Perception     │
                └───────────────────────────────┘
                               │
                               ▼
                ┌───────────────────────────────┐
                │      v0.6 Solver Adapter      │
                └──────────────┬────────────────┘
                               │ (Flatten & Map Fields)
                               ▼
                ┌───────────────────────────────┐
                │          0.6 Solver           │
                └──────────────┬────────────────┘
                               │ (Compute Full State Space)
                               ▼
                ┌───────────────────────────────┐
                │ Rich Decision & Explainability│
                │ (P50, Lines, goldInference,   │
                │ candidateGs, remainingByG)    │
                └───────────────────────────────┘
```

1. **事实与推断彻底解耦**：
   * `CanonicalMatchRecord` 仅存储感知到的**客观物理事实**（各品质均价、件数、格数、座位叫价、识别藏品）。
   * `solverResult` 作为独立嵌套对象存储**推演计算结果**（`goldInference`, `candidateGs`, `probabilityProfile`, `theoreticalMin/Max`）。
2. **引入 `schemaVersion: 7`**：
   * 显式标记版本号，通过 `LegacyNormalizer` 升级 0.6 历史对局，通过 `v0.6 Solver Adapter` 双向适配 0.6 求解器。
