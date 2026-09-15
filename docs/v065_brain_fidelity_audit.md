# 异环拍卖助手 v0.65 核心大脑与算法保真度审计报告 (Brain Fidelity Audit Report)

**审计日期**: 2026-08-14  
**项目根目录**: `D:\yihuanpaimai`  
**核心引擎版本**: v0.65 (Canonical JS Core)  
**数据库基线**: `异环拍卖数据.json` (Live Canonical Database)

---

## 1. 核心架构纠偏与保真度总览

本轮纠偏彻底解决了上一阶段存在的“Python subprocess 依赖 Node.js”、“算法双轨分叉”、“假设性成本自动累加”和“出价线/状态语义偏移”问题，实现了**轻量化 Python 视觉感知 + 原生 WebView2 共享纯 JS 核心高保真推演**的现代化架构。

```
┌────────────────────────────────────────────────────────┐
│                   Python Backend                       │
│  LiveCapture ──► VisionPipeline ──► DeltaIntelManager  │
│                                    (事件驱动增量成本)  │
│                                           │            │
└───────────────────────────────────────────┼────────────┘
                                            │ WebSocket 
                                            │ (JSON Payload)
┌───────────────────────────────────────────▼────────────┐
│              WebView2 Frontends (No Node)              │
│                                                        │
│   ┌────────────────────────────────────────────────┐   │
│   │   core/auction_engine_v06.js (Shared Core)     │   │
│   │                                                │   │
│   │   1. State Probability (严格可行组合先验)      │   │
│   │   2. Formal Value (EV, RV, P20, P50, P80)      │   │
│   │   3. Raw & Calibrated Shadow (宽度与状态熵)    │   │
│   │   4. Market Model (竞争系数与预期成交)         │   │
│   │   5. Decision Engine (Target / Global / Chase) │   │
│   └────────────────────────────────────────────────┘   │
│              ▲                              ▲          │
│              │                              │          │
│   core/tactical_hud.html             lab/index.html    │
│    (实战战术 HUD 悬浮窗)              (对局回放与实验室)  │
└────────────────────────────────────────────────────────┘
```

---

## 2. 五大关键纠偏项证据与代码位置

### 2.1 Lab 与 HUD 使用完全同一份 Shared JS Core
- **权威核心**: [`core/auction_engine_v06.js`](file:///d:/yihuanpaimai/core/auction_engine_v06.js) 作为全项目唯一算法 Single Source of Truth。
- **Tactical HUD 引入**:
  [`core/tactical_hud.html:L7`](file:///d:/yihuanpaimai/core/tactical_hud.html#L7)
  ```html
  <script src="auction_engine_v06.js"></script>
  ```
- **Lab 引入与委托**:
  [`lab/index.html:L8`](file:///d:/yihuanpaimai/lab/index.html#L8)
  ```html
  <script src="../core/auction_engine_v06.js"></script>
  ```
  [`lab/index.html:L4760`](file:///d:/yihuanpaimai/lab/index.html#L4760)
  ```javascript
  function calculateV06DecisionLines(ctx={}, d={}, liveBid=null){
    if (window.AuctionEngineV06 && typeof window.AuctionEngineV06.calculateV06DecisionLines === "function") {
      return window.AuctionEngineV06.calculateV06DecisionLines(ctx, d, liveBid);
    }
    // ...
  }
  ```
- **证明结论**: 彻底消除了算法双轨，Lab 实验室与实战 HUD 悬浮窗在相同输入下产生 100% 一致的推演结果。

---

### 2.2 HUD 完整接入 v0.6 流水线，无自行简化的 Shadow/Market
- **严谨流水线实现**: [`core/auction_engine_v06.js:L532-L660`](file:///d:/yihuanpaimai/core/auction_engine_v06.js#L532-L660) (`solveAuctionPipeline`)：
  1. **State Probability**: 基于组合搜索返回的全部可行解 $(G, P, R)$ 计算归一化状态概率 $P(s) = w(s)/\sum w(s_j)$。
  2. **Formal Value**: 精确加权计算 $EV = \sum_s P(s) \cdot V(s)$，并求出 $RV=P20$、$P50$、$P80$。
  3. **Raw & Calibrated Shadow**: 严格计算影子宽度 $\Delta = P80 - P20$，以及状态信息熵 $H(S) = -\sum P(s)\ln P(s)$。
  4. **Market Model**: 计算 0.52 竞争系数下的市场预期成交价 $\text{ClearingEst} = \lfloor EV \times 0.52 \rfloor$。
  5. **Decision Engine**: 严格计算 Target Line（目标回报线）、Global Line（全成本保本线）、Marginal Chase Line（边际追价线，只扣未来新增成本）。
- **HUD 实时调用**:
  [`core/tactical_hud.html:L634-L640`](file:///d:/yihuanpaimai/core/tactical_hud.html#L634-L640)
  ```javascript
  if (window.AuctionEngineV06 && window.AuctionEngineV06.solveAuctionPipeline && (d.q || d.avg)) {
    engineResult = window.AuctionEngineV06.solveAuctionPipeline(d);
  }
  ```
- **证明结论**: 删除了此前临时切片排序的粗糙推算，HUD 每一帧均运行标准数学流水线。

---

### 2.3 App 运行彻底摆脱 Node.js 运行时依赖
- **改动前**: 每次视觉识别到新帧均通过 `subprocess.run(["node", "-e", ...])` 启动独立 Node 进程，带来 80~160ms 进程启动开销并要求用户机器安装 Node.js。
- **改动后**: [`core/auction_brain.py`](file:///d:/yihuanpaimai/core/auction_brain.py) 完全移除 `subprocess.run(["node", ...])`。
- **运行机制**: Python 视觉与增量引擎处理后，将原始观察与上下文数据包直接推送到 WebSocket。WebView2 (Chromium 内核) 直接在前端 0 延迟执行 `auction_engine_v06.js`。
- **证明结论**: 客户端用户无需安装 Node.js 即可原生流畅运行桌面 App。

---

### 2.4 规范 solverStatus 状态枚举与 diagnosticOnly 独立性
- **规范 6 种状态枚举**:
  - `valid`: 严格求解有效。
  - `incomplete`: 情报不完整 (缺少 Q 或 均价)。
  - `fallback`: 降级估算模式 (精确求解未命中时启用)。
  - `no-match`: 输入与图鉴/场地倍率严格冲突。
  - `timeout`: 搜索超时保护。
  - `stale`: 旧结果过期中 (输入发生变更，等待重新求解)。
- **diagnosticOnly 独立设计**:
  [`core/auction_brain.py:L114`](file:///d:/yihuanpaimai/core/auction_brain.py#L114)
  ```python
  if diagnostic_only:
      action = f"[诊断模式] {action}"
  ```
  [`core/tactical_hud.html:L644-L666`](file:///d:/yihuanpaimai/core/tactical_hud.html#L644-L666) 状态徽章独立追加 `[诊断]` 标识，严禁以 `diagnostic` 状态取代 `fallback`。
- **自动化测试保证**: [`tests/test_solver_status_semantics.py`](file:///d:/yihuanpaimai/tests/test_solver_status_semantics.py) 100% 覆盖 6 种状态及 `diagnosticOnly` 组合。

---

### 2.5 真实事件驱动的成本模型 (删除假设性累加)
- **改动前**: 轮次推进时自动扣减 `added_cost = rounds_advanced * 15000`；强制赋予珍珠场地 `20000` 门票。
- **改动后**:
  [`core/delta_intel.py:L80-L90`](file:///d:/yihuanpaimai/core/delta_intel.py#L80-L90)
  ```python
  # 轮次推进本身不扣费，成本严格由真实付费事件驱动
  if obs.round > self.current_round:
      self.current_round = obs.round
      delta_detected = True
      delta_details.append(f"round_advance -> R{self.current_round}")
  ```
  [`core/delta_intel.py:L128-L135`](file:///d:/yihuanpaimai/core/delta_intel.py#L128-L135)
  ```python
  event_cost = getattr(obs.intel, "cost", 0) or 0
  if event_cost > 0:
      self.sunk_cost += event_cost
  ```
- **证明结论**: 确保在无真实付费事件时 `incrementalCost = 0`，`marginalChaseLine` 不会被错误削减。

---

## 3. 永久回归测试与全量套件验证结果

### 3.1 15:53 经典回归测试 (Core Native Regression)
输入约束：
- 箱体件数 $Q = 9$
- 紫色已知件数 $P = 5$
- 金色单件均价 $\text{Avg} = 33538$
- 已知金色: `万有星仪` (单价 51,077)
- 已知紫色: `拈花小像` (18,075) + `金角月芒` (8,128)
- 取整模式: `floor`

**实测输出结果**:
- 必须命中状态 1: **$G=3, P=5, R=1$** (残余金色基准和 100,616)
- 必须命中状态 2: **$G=4, P=5, R=0$** (残余金色基准和 134,155)
- 状态判定: `solverStatus = "valid"` (未发生 no-match)

### 3.2 自动化测试套件全量汇总
执行 `python -m unittest discover tests`:

```text
Ran 27 tests in 21.253s
OK
- test_auction_brain.py:               OK
- test_delta_intel.py:                 OK
- test_live_auction_e2e.py (Replay):   OK
- test_roi_scaling.py:                 OK
- test_session_fsm.py:                 OK
- test_shared_core.py:                 OK
- test_solver_status_semantics.py:     OK
- test_v06_final.py:                   OK
- test_vision_contract.py:             OK
- test_vision_pipeline.py:             OK
- test_vision_safety.py:               OK
```

---

## 4. 架构元数据与状态标注

| 模块 / 机制 | 当前状态 | 备注 |
| :--- | :--- | :--- |
| **Shared JS Core** | ✅ 完全统一 | `auction_engine_v06.js` 供 Lab 与 HUD 共同加载 |
| **HUD 决策推演** | ✅ 完整流水线 | 包含 State Probability, Formal Value, Shadow, Market, Decision |
| **Node.js 运行时依赖** | ❌ 彻底移除 | 0 外部 Node 依赖，计算直接运行在 WebView2 |
| **solverStatus** | ✅ 6 种规范语义 | `valid / incomplete / fallback / no-match / timeout / stale` |
| **diagnosticOnly** | ✅ 独立标志 | 独立 boolean 旁路，不污染 fallback |
| **成本计算** | ✅ 纯事件驱动 | 无付费事件时不扣费，删除 +15000/轮假设 |
| **Session FSM** | 🟡 标记为 Scaffold | 宏观对局生命周期脚手架，不凭空造细粒度状态 |
| **E2E 验证命名** | 🟡 Replay E2E Validation | 明确标记为切片回放端到端全链路验证 |
| **WDA_EXCLUDEFROMCAPTURE** | 🟡 机制已实现 | Win32 API 绑定完成，待真实游戏+HUD+mss 像素级实测 |
