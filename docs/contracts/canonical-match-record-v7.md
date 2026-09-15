# Canonical MatchRecord v7 设计规范 (Data Contract Specification)

> **版本**：`schemaVersion: 7`  
> **文档定位**：异环拍卖助手对局数据中枢权威规范（Canonical Single Source of Truth）。  
> **核心原则**：
> 1. **事实与推断分离**：MatchRecord 主体只记录“视觉与对局真实事实”（Perception Facts），禁止将 Solver 推演假设混入事实字段。推演结果独立存放在 `solverResult`。
> 2. **全品质统一建模**：白、绿、蓝、紫、金、红六大品质采用统一、平行的字段结构，杜绝单字段均价混叠。
> 3. **角色与仪器解耦**：大厅展示仪器、角色帮手与求解器算法分支严格分离。
> 4. **值语义精准表达**：严格区分 `null`（未知/未检测）、`0`（确认为零）、`"unknown"`（已观测但无法分类）。

---

## 一、Canonical MatchRecord v7 结构定义

```jsonc
{
  "$schema": "https://yihuanpaimai.local/schemas/match-record-v7.json",
  "schemaVersion": 7,
  "productVersion": "v0.65",
  "id": "auto_1771142400_abc123",
  "playedAt": "2026-08-16T15:30:00.000Z",
  "periodKey": "2026-08",

  /* 1. 场地、箱型与环境词条 */
  "environment": {
    "venueTier": "zhongji",                 // 场地等级 (可选): chuji | zhongji | gaoji | dingji | null
    "venue": "shanhu",                      // 具体会场 Canonical ID (可选): shanhu | milin | baiye | haimo | null
    "venueName": "中级场 · 珊瑚场",           // 可选本地化显示名称
    "box": "实木宝箱 · 中级藏品概率提升",       // 完整箱名
    "boxType": "wood",                     // 归一化箱型: wood | glass | iron
    "fieldCondition": "standard",           // Canonical 词条 ID: standard | dark | gem_boost 等
    "fieldConditionName": "标准规则",        // 可选词条名称
    "fieldConditionSource": "ocr_banner"    // 词条识别来源: ocr_banner | user_override | default
  },

  /* 2. 角色与仪器配置 (严格解耦) */
  "loadout": {
    "character": "达芙蒂尔",                 // 竞拍帮手: 达芙蒂尔 | 浔 | 未知助手
    "lobbyToolGroup": "高级品鉴仪器组",       // 大厅画面中实际出现的仪器组名称
    "solverToolGroup": "group1"             // 求解器算法分支: group1 | group2
  },

  /* 3. 成本配置 (单位: 异环点/金币) */
  "costs": {
    "entry": 5000,                          // 门票成本
    "intel": 45000,                         // 情报购买成本
    "other": 0,                             // 其他消耗
    "sunkCost": 50000,                      // 沉没成本 (entry + intel + other)
    "futureIncrementalCost": 0,             // 预计后续追加成本
    "total": 50000                          // 本局总成本
  },

  /* 4. 全局容量与公开统计 (Public Facts) */
  "publicIntel": {
    "q": 15,                                // 箱体高阶总件数 Q = G + P + R (null 表示未揭晓)
    "totalItems": 66,                       // 全场藏品总件数 (如大厅公开 66 件，null 表示未揭晓)
    "totalGrid": 84,                        // 仓库/箱体总占格数 (null 表示未揭晓)
    "avgValueBasis": "all_inclusive"        // 均价计算口径: all_inclusive | public_only
  },

  /* 5. 六大品质全维度事实 (Qualities Model) */
  "qualities": {
    "white": {
      "count": null,                        // 数量 (null=未获知, 0=确认为0)
      "avg": null,                          // 均价 (null=未获知)
      "grid": null                          // 占格数
    },
    "green": {
      "count": null,
      "avg": null,
      "grid": null
    },
    "blue": {
      "count": 7,
      "avg": 3462,
      "grid": 6
    },
    "purple": {
      "count": 5,                           // 紫色总件数
      "minCount": 2,                        // 已知紫色下界 (如已知 2 件)
      "avg": 2007,                          // 紫色均价 (独立字段，禁止与金色均价混淆)
      "grid": 21,                           // 紫色总占格
      "knownItems": [                       // 视觉识别出的已知紫色藏品
        { "name": "拈花小像", "price": 18075, "size": "1x2" },
        { "name": "金角月芒", "price": 8128, "size": "2x2" }
      ]
    },
    "gold": {
      "count": 4,                           // 金色总件数 (null 表示未获知)
      "minCount": 1,                        // 已知金色下界
      "avg": 33538,                         // 金色均价 (独立字段，禁止与紫色均价混淆)
      "total": null,                        // 金总价硬约束 (若有时)
      "grid": 16,                           // 金色总占格
      "knownItems": [                       // 视觉识别出的已知金色藏品
        { "name": "万有星仪", "price": 51077, "size": "2x3" }
      ]
    },
    "red": {
      "count": 2,                           // 红色总件数 (null 表示未获知)
      "minCount": 1,                        // 已知红色下界
      "maxCount": 2,                        // 已知红色上界
      "knownItems": [                       // 视觉/仓库识别出的已知红色藏品
        { "name": "创生之柱", "price": 81088, "size": "3x3" }
      ],
      "redInventoryComplete": true,         // 红装仓库是否已完全锁定
      "settlementVerifiedRedItems": "81088" // 结算验证的红装条目
    }
  },

  /* 6. 回合与出价跟踪 (Seats & Bidding History) */
  "bidding": {
    "seats": [                              // 4 个座位的实时状态
      { "slot": 1, "name": "华星秋月", "bid": 900001, "currentBid": 900001, "isMe": false },
      { "slot": 2, "name": "爱馨宝", "bid": 888888, "currentBid": 888888, "isMe": false },
      { "slot": 3, "name": "秦幽雪", "bid": 200000, "currentBid": 200000, "isMe": false },
      { "slot": 4, "name": "PLAYER_LOCAL", "bid": 1099998, "currentBid": 1099998, "isMe": true }
    ],
    "myName": "PLAYER_LOCAL",
    "myFinalBid": 1099998,
    "leaderName": "PLAYER_LOCAL",
    "leaderBid": 1099998,
    "leaderTies": ["PLAYER_LOCAL"],             // 平局领跑玩家列表
    "isMyLead": true,
    "historicalBids": {                     // 历史已结束回合叫价 (< cur_round)
      "华星秋月": { "1": 100, "2": 100000, "3": 666666 },
      "爱馨宝": { "1": 888888, "2": 888888, "3": 888888 },
      "秦幽雪": { "1": 200000, "2": 200000, "3": 200000 },
      "PLAYER_LOCAL": { "1": 888888, "2": 1000000, "3": 999999 }
    },
    "finalBids": {                          // 全回合终局叫价全量表
      "华星秋月": { "1": 100, "2": 100000, "3": 666666, "4": 900001 },
      "爱馨宝": { "1": 888888, "2": 888888, "3": 888888, "4": 888888 },
      "秦幽雪": { "1": 200000, "2": 200000, "3": 200000, "4": 200000 },
      "PLAYER_LOCAL": { "1": 888888, "2": 1000000, "3": 999999, "4": 1099998 }
    },
    "rounds": [                             // 1~5 回合完整时序快照
      {
        "round": 1,
        "timer": 0,
        "intel": { "q": 15, "goldAvg": 33538 },
        "bids": { "PLAYER_LOCAL": 888888 }
      }
    ]
  },

  /* 7. 终局结算事实 (Settlement Truth) */
  "settlement": {
    "isSettled": true,
    "clearingPrice": 1099998,               // 最终成交价 (未成交则为 null)
    "actualTotal": 1013120,                 // 结算大屏真实总价值
    "realizedProfit": -136878,              // 实际净收益 (actualTotal - clearingPrice - costs.total)
    "acquired": true,                       // 是否本人拍下
    "winner": "PLAYER_LOCAL",                   // 最终获胜者名称
    "resultReason": "won",                  // won | outbid | early_close | folded
    "truthEvidence": {},                   // v1 或 v2：v2 另含非空 fileOriginals[]（完整 Settlement Evidence Store v2 descriptor）
    "warehouseIdentityReview": {},         // 可选；严格引用 warehouse-identity-review.v1。不得写入 truthEvidence，不含图像字节或本机路径
    "settlementItems": [                    // 结算大屏识别出的具体单件物品
      { "name": "乔望尼金雕像", "price": 271827, "size": "2x3", "rarity": "gold" },
      { "name": "创生之柱", "price": 81088, "size": "3x3", "rarity": "red" }
    ],
    "realizedState": {                      // 终局实际品质构成
      "gold": 4, "purple": 5, "red": 2, "blue": 4, "green": 0, "white": 0
    }
  },

  /* 8. Solver 推断与决策结果 (Inference & Explainability) */
  "solverResult": {
    "solverVersion": "v0.6",
    "solverStatus": "valid",                // valid | no-match | fallback | incomplete | timeout | diagnostic
    "inputHash": "sha1-abc12345",
    "solvedAt": "2026-08-16T15:30:05.000Z",
    "round": 4,

    // 决策出价线
    "decisions": {
      "targetLine": 950000,                 // 目标利润线
      "globalLine": 963120,                 // 全局保本线 (扣整局总成本)
      "marginalLine": 1013120,              // 边际保本线 (仅扣购入支出)
      "valP20": 980000,
      "valP50": 1013120,
      "valP80": 1050000,
      "theoreticalMin": 878424,
      "theoreticalMax": 1080000,
      "actionDirective": "🟢 建议跟进 · 领跑中",
      "actionReason": "当前叫价 109.9W 接近边际价值上限"
    },

    // 状态推断可解释性 (State Inference Explainability)
    "goldInference": {
      "constraintLabel": "金均取整约束",
      "goldMatchCount": 14,
      "goldMatchCountExact": true,
      "candidateGs": [3, 4],
      "uniqueG": false,
      "uniqueCombination": false,
      "byG": [
        { "G": 3, "combinationCount": 6, "samplePrices": [51077, 25000, 24537] },
        { "G": 4, "combinationCount": 8, "samplePrices": [33538, 33538, 33538, 33538] }
      ],
      "remainingByG": [
        { "G": 3, "PplusR": 12, "P": 5, "R": 7 },
        { "G": 4, "PplusR": 11, "P": 5, "R": 6 }
      ]
    },
    "candidatePs": [5],
    "componentBreakdown": {
      "gold": { "mean": 134152, "variance": 12000 },
      "purple": { "mean": 10035, "variance": 450 },
      "red": { "mean": 162176, "variance": 3200 }
    },
    "roundingAudit": {
      "chosenMode": "floor",
      "requestedMode": "floor"
    }
  }
}
```

---

## 二、数值与语义约定 (Value Semantics)

1. **`null` vs `0` vs `"unknown"`**：
   * **`null`**：**未获知 / 未观测到 / 暂无数据**（如尚未开出高阶总件数时 `publicIntel.q = null`；未拍下时 `settlement.clearingPrice = null`）。
   * **`0`**：**确认数值为零**（如确认为 0 件红装时 `qualities.red.count = 0`；无情报成本时 `costs.intel = 0`）。
   * **`"unknown"`**：**已发生观测但无法识别分类**（如无法确定词条时 `fieldCondition = "unknown"`）。
2. **多品质均价独立性**：
   * `qualities.gold.avg` 与 `qualities.purple.avg` 严格独立，禁止出现共用单个 `avg` 字段导致的读写覆盖。
3. **推断隔离性**：
   * `qualities.*` 中仅记录 OCR / 网格模板识别出的**确定事实**（`knownItems`）；所有排列组合推演出的候选解（如 `candidateGs`、`byG`）必须存放在 `solverResult.goldInference` 中。
4. **场地等级 `venueTier` 与具体会场 `venue` 的解耦约定**：
   * **`venueTier`**：场地等级（可选值：`"chuji"` 初级场 | `"zhongji"` 中级场 | `"gaoji"` 高级场 | `"dingji"` 顶级场 | `null`）。用于 Alpha 手动输入等仅指定等级但未确定具体会场 ID 的场景。
   * **`venue`**：具体会场 Canonical ID（如 `"shanhu"`, `"milin"`, `"baiye"`, `"haimo"` | `null`）。
   * **正交独立**：手动模式下只知等级时 `venueTier` 有值、`venue` 保持 `null`；历史 0.65 归档数据只知具体 ID 时 `venue` 有值，不要求强制逆向补齐 `venueTier`。两者不互相覆盖，此扩展属于 schemaVersion 7 的向下兼容可选扩展。

---

## 三、0.6 历史数据 $\rightarrow$ Canonical v7 映射规范

| 0.6 Historical Field | Canonical v7 Field | 映射规则 / 转换逻辑 | 状态 (Status) |
| :--- | :--- | :--- | :---: |
| `id` | `id` | 原样复制 | `DIRECT` |
| `productVersion` | `productVersion` | 原样复制（记录原版本如 `"v0.6"`） | `DIRECT` |
| `playedAt` / `date` | `playedAt` | 补全 ISO 格式时间戳 | `DIRECT` |
| `venue` | `environment.venue` | 通过 SOT 字典将「中级场 · 珊瑚场」转为 `"shanhu"`，原中文存入 `venueName` | `RENAMED` |
| `box` | `environment.box` | 原样复制；提取箱型至 `boxType`（如 `wood`） | `DIRECT` |
| `fieldCondition` | `environment.fieldCondition` | 原样复制（如 `standard`） | `DIRECT` |
| `character` | `loadout.character` | 原样复制（如 `达芙蒂尔`） | `DIRECT` |
| `toolGroup` | `loadout.solverToolGroup` | 存入 `solverToolGroup`（`group1`/`group2`） | `RENAMED` |
| `q` | `publicIntel.q` | 原样复制 | `DIRECT` |
| `totalItems` | `publicIntel.totalItems` | 原样复制 | `DIRECT` |
| `totalGrid` | `publicIntel.totalGrid` | 原样复制 | `RENAMED` |
| `goldAvg` | `qualities.gold.avg` | 映射至金色独立均价 | `RENAMED` |
| `purpleAvg` | `qualities.purple.avg` | 映射至紫色独立均价 | `RENAMED` |
| `blueAvg` | `qualities.blue.avg` | 映射至蓝色独立均价 | `RENAMED` |
| `purpleCount` | `qualities.purple.count` | 映射至紫色件数 | `RENAMED` |
| `minPurple` | `qualities.purple.minCount` | 映射至紫色下界 | `RENAMED` |
| `knownPurple` | `qualities.purple.knownItems` | 解析算式/字符串（如 `"18075+8128"`）转为 Item 对象数组 | `TYPE_CHANGED` |
| `goldCount` | `qualities.gold.count` | 映射至金色件数 | `RENAMED` |
| `minGold` | `qualities.gold.minCount` | 映射至金色下界 | `RENAMED` |
| `goldTotal` | `qualities.gold.total` | 映射至金色总价硬约束 | `RENAMED` |
| `knownGold` | `qualities.gold.knownItems` | 解析算式/字符串（如 `"51077"`）转为 Item 对象数组 | `TYPE_CHANGED` |
| `redCount` | `qualities.red.count` | 映射至红色件数 | `RENAMED` |
| `minRed` | `qualities.red.minCount` | 映射至红色下界 | `RENAMED` |
| `knownRed` / `decisionKnownRed` | `qualities.red.knownItems` | 解析字符串转为 Item 对象数组 | `TYPE_CHANGED` |
| `redInventoryComplete` | `qualities.red.redInventoryComplete` | 原样复制 | `DIRECT` |
| `costs` / `cost` | `costs` | 映射并确保 `entry`, `intel`, `sunkCost`, `total` 齐全 | `DIRECT` |
| `actualTotal` | `settlement.actualTotal` | 映射至结算真实总值 | `DIRECT` |
| `clearingPrice` | `settlement.clearingPrice` | 映射至结算成交价 | `DIRECT` |
| `acquired` | `settlement.acquired` | 原样复制 | `DIRECT` |
| `winner` | `settlement.winner` | 原样复制 | `DIRECT` |
| `prediction.goldInference` | `solverResult.goldInference` | 原样保留候选推断对象 | `DIRECT` |
| `prediction.candidateGs` | `solverResult.goldInference.candidateGs` | 归入推断对象 | `DIRECT` |
| `prediction.candidatePs` | `solverResult.candidatePs` | 原样保留 | `DIRECT` |
| `prediction.theoreticalMin/Max` | `solverResult.decisions.theoreticalMin/Max` | 归入决策边界 | `RENAMED` |
| `prediction.componentBreakdown` | `solverResult.componentBreakdown` | 原样保留 | `DIRECT` |
| `historicalBids` / `finalBids` | `bidding.historicalBids` | 历史 0.6 缺失该字段，置为空字典 `{}` | `MISSING` |

---

## 四、0.65 当前 MatchRecord $\rightarrow$ Canonical v7 映射规范

| 0.65 Current Field | Canonical v7 Field | 映射规则 / 转换逻辑 | 状态 (Status) |
| :--- | :--- | :--- | :---: |
| `id` | `id` | 原样复制 | `DIRECT` |
| `productVersion` | `productVersion` | 原样复制 (`"v0.65"`) | `DIRECT` |
| `playedAt` / `timestamp` | `playedAt` | 原样复制 | `DIRECT` |
| `venue` | `environment.venue` | 原样复制 (`"shanhu"`)，反查 SOT 补充 `venueName` | `DIRECT` |
| `box` | `environment.box` | 原样复制 | `DIRECT` |
| `boxType` | `environment.boxType` | 原样复制 | `DIRECT` |
| `fieldCondition` | `environment.fieldCondition` | 原样复制 | `DIRECT` |
| `character` | `loadout.character` | 原样复制 | `DIRECT` |
| `toolGroup` | `loadout.lobbyToolGroup` | 修复语义混叠：0.65 的 `toolGroup` 实为大厅仪器组，存入 `lobbyToolGroup` | `SEMANTIC_MERGED` |
| — | `loadout.solverToolGroup` | 默认赋 `"group1"` | `MISSING` |
| `q` | `publicIntel.q` | 原样复制 | `DIRECT` |
| `avg` | `qualities.gold.avg` 或 `qualities.purple.avg` | 需根据情报上下文拆分；单箱体默认高阶金均价存入 `qualities.gold.avg` | `SEMANTIC_MERGED` |
| — | `publicIntel.totalItems` | 0.65 当前未暴露，置为 `null`（待 Perception 补充） | `MISSING` |
| `totalGrids` | `publicIntel.totalGrid` | 字段名去 `s` 归一化 | `RENAMED` |
| `purple` / `purpleCount` | `qualities.purple.count` | 统一存入 `qualities.purple.count` | `RENAMED` |
| `identifiedShapes.knownGold` | `qualities.gold.knownItems` | 将识别出的名称/尺寸转为 Item 数组 | `DIRECT` |
| `identifiedShapes.knownPurple`| `qualities.purple.knownItems` | 将识别出的名称/尺寸转为 Item 数组 | `DIRECT` |
| `identifiedShapes.knownRed` | `qualities.red.knownItems` | 将识别出的名称/尺寸转为 Item 数组 | `DIRECT` |
| `seats` / `opponents` | `bidding.seats` | 保持 4 座位完整结构 | `DIRECT` |
| `historicalBids` | `bidding.historicalBids` | 原样复制 | `DIRECT` |
| `finalBids` | `bidding.finalBids` | 原样复制 | `DIRECT` |
| `leaderName` / `leaderBid` | `bidding.leaderName / leaderBid` | 原样复制 | `DIRECT` |
| `leaderTies` | `bidding.leaderTies` | 原样复制 | `DIRECT` |
| `isMyLead` | `bidding.isMyLead` | 原样复制 | `DIRECT` |
| `clearingPrice` | `settlement.clearingPrice` | 原样复制 | `DIRECT` |
| `actualTotal` | `settlement.actualTotal` | 原样复制 | `DIRECT` |
| `realizedProfit` | `settlement.realizedProfit` | 原样复制 | `DIRECT` |
| `isAcquired` / `acquired` | `settlement.acquired` | 归一化为 `acquired` | `RENAMED` |
| `winnerName` / `winner` | `settlement.winner` | 归一化为 `winner` | `RENAMED` |
| `settlementItems` | `settlement.settlementItems` | 原样复制 | `DIRECT` |
| `roundTimeline` / `rounds` | `bidding.rounds` | 原样复制 | `RENAMED` |
| `costs` / `cost` | `costs` | 原样复制 | `DIRECT` |
| — | `solverResult.goldInference` | 0.65 当前丢弃了推断中间态，待 Adapter 恢复 | `MISSING` |
| — | `solverResult.candidateGs` | 同上 | `MISSING` |
| — | `solverResult.candidatePs` | 同上 | `MISSING` |
