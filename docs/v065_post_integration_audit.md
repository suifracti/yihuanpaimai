# 《异环拍卖助手》v0.65 全量架构重构与集成审计报告 (Post-Integration Audit)

## 1. 项目整体概述与重构目标达成情况

本项目根据严格的分阶段架构演进规范，顺利完成了从 v0.6 到 v0.65 的全模块解耦、算法纯核抽离、标准化视觉契约、增量情报状态机与战术 HUD 全链路端到端集成。

所有阶段均遵循 **“修改 → 自动测试 → 数据兼容验证 → git diff 审计 → 独立 Commit”** 的铁律，完整保留历史真实数据，未修改任何历史真实战绩，未伪造缺失字段。

---

## 2. 关键 Git 演进里程碑 (Milestones)

| Phase | Git Commit Hash | Commit Message | 核心交付内容 |
| :--- | :--- | :--- | :--- |
| **Phase 1** | `8464027` | `feat: finalize v0.6 decision and evaluation pipeline` | 沉没成本与未来边际成本独立建模；3条出价线与 ROI 精准分离；统一风险单轴可视化；Schema 6 `intelEvents` 结构化落盘 |
| **Phase 2** | `734af35` | `refactor: extract shared v0.6 engine core` | 抽离零 DOM 纯 JS 算法核 (`core/auction_engine_v06.js`)，UMD/CJS/Browser 通用；Node.js 与浏览器双向自测 100% 通过 |
| **Phase 3** | `dac3318` | `refactor: formalize vision observation contract` | 制定并实现 `VisionObservation` 标准数据契约；统一 Round, Timer, Intel, 4席位出价与结算字段 |
| **Phase 4** | `55e9422` | `feat: connect vision observations through delta intel` | 构建 `DeltaIntelManager` 流式状态机；动态捕获增量情报与状态熵变；沉没成本随轮次递增累加 |
| **Phase 5** | `8a0e734` | `feat: integrate shared auction brain with tactical HUD` | 实现 `AuctionBrain` 共享决策大脑；协调视觉、算法求解器、HUD 广播网关与自动记账器 |
| **Phase 6** | `a4627fa` | `fix: enforce solver status and stale result semantics` | 规范 6 种求解状态 (`valid`, `diagnostic`, `incomplete`, `stale`, `timeout`, `no-match`)；严禁在过期或未完成状态下推荐跟价 |
| **Phase 7** | `6f35e83` | `fix: isolate HUD from vision capture and improve diagnostics` | 引入 Windows DWM `WDA_EXCLUDEFROMCAPTURE` 免截图属性；增加黑屏、低对比度与模糊安全诊断 |
| **Phase 8** | `4a6f43e` | `feat: normalize vision ROIs for 1080p and 1440p` | 实现 `ROIScaler` 归一化坐标系；支持 1080p、1440p、4K 与 21:9 带鱼屏 Pillarbox/Letterbox 视口自适应 |
| **Phase 9** | `23f7d04` | `feat: introduce auction session state machine` | 构建 `AuctionSessionFSM` 显式状态机 (`IDLE` -> `BIDDING_ROUND` -> `SETTLEMENT` -> `ARCHIVED`) |
| **Phase 10** | `f03ce53` | `test: add end-to-end live auction validation` | 实现真实录像切片端到端全流程回放与沙箱数据库隔离记账测试 |
| **Phase 11** | (当前) | `docs: create v065_post_integration_audit.md` | 本架构全景审计与验收报告 |

---

## 3. 核心架构与决策模型设计

### 3.1 成本与三条决策出价线 (Decision Lines)

$$\text{GlobalLine} = \max(0, \text{RiskAdjustedValue} - \text{sunkCost} - \text{futureIncrementalCost})$$
$$\text{MarginalLine} = \max(0, \text{RiskAdjustedValue} - \text{futureIncrementalCost})$$
$$\text{TargetLine} = \begin{cases} \max(0, \lfloor \frac{\text{RiskAdjustedValue}}{1 + \text{targetROI}} - \text{allCosts} \rfloor) & \text{if targetROI is set} \\ \max(0, \lfloor \text{RiskAdjustedValue} - \text{allCosts} - \text{targetProfit} \rfloor) & \text{otherwise} \end{cases}$$

- **沉没成本 (Sunk Cost)**：包含入场门票 (5,000 / 20,000) 以及过去轮次已花费的情报费，**在边际追价线（MarginalLine）中严格不再二次扣除**，保证博弈决策在后续轮次不产生非理性放弃。
- **ROI 分流**：界面严格区分 **总投入回报率** ($\frac{\text{expectedProfit}}{\text{purchaseSpend} + \text{allCosts}}$) 与 **买价资本回报率** ($\frac{\text{expectedProfit}}{\text{purchaseSpend}}$)，消除虚假 EV 提示。

### 3.2 共享纯核心 (Shared Pure Core)

- 文件位置：[core/auction_engine_v06.js](file:///d:/yihuanpaimai/core/auction_engine_v06.js)
- 零 DOM 依赖：完全脱离浏览器环境，既可在桌面 App (Node.js / Python Subprocess) 中无缝调用，也可在前端实验室 ([lab/index.html](file:///d:/yihuanpaimai/lab/index.html)) 中作为 UMD 库直接引入，杜绝算法双轨维护分歧。
- 15:53 实战回归：在 $Q=9, P=5, Avg=33538$, 已知紫色「拈花小像+金角月芒」与金色「万有星仪」条件下，严格求解出唯一的两种合法组合：
  - $3G + 5P + 1R \implies 100,616$
  - $4G + 5P + 0R \implies 134,155$

---

## 4. 视觉管线与系统安全

1. **Vision Observation Contract**：[core/vision_contract.py](file:///d:/yihuanpaimai/core/vision_contract.py) 将 OCR 解析结果统一打包为结构化的 `VisionObservation` 对象，下游模块只消费标准契约，解耦视觉感知与业务逻辑。
2. **HUD 自身防抓取与安全隔离**：[core/window_capture.py](file:///d:/yihuanpaimai/core/window_capture.py) 通过 Windows 系统的 `SetWindowDisplayAffinity(hwnd, 0x00000011)` 保证悬浮 HUD 窗口在录屏与截图时对捕获引擎透明不可见，彻底消除递归文字重叠 OCR 噪音。
3. **多分辨率与带鱼屏自适应**：[core/roi_scaler.py](file:///d:/yihuanpaimai/core/roi_scaler.py) 提供归一化坐标切片系统，自动适配 1080p、1440p、4K 与 21:9 宽屏。

---

## 5. Canonical Live Database 审计

- 唯一正式数据库：`D:\yihuanpaimai\异环拍卖数据.json`
- 结构规范：Schema 6
- 真实性审计：
  - 全部自动化测试均在独立 Temp 沙箱路径下运行，未向 Canonical Database 注入任何测试/合成脏数据。
  - 所有历史真实对局记录格式保持向后兼容。

---

## 6. 自动化回归测试汇总

```text
tests/test_v06_final.py                 ... OK (3 tests: 15:53 regression, red repeat=2, ROI lines)
tests/test_shared_core.py               ... OK (3 tests: Node pure core DP, exact solve, decision lines)
tests/test_vision_contract.py           ... OK (4 tests: dataclasses, serialization, from_context, validation)
tests/test_delta_intel.py               ... OK (2 tests: streaming rounds, delta events, sunk costs)
tests/test_auction_brain.py             ... OK (1 test: brain coordinator & HUD payload generation)
tests/test_solver_status_semantics.py   ... OK (3 tests: 6 solver states, stale protection, fold detection)
tests/test_vision_safety.py             ... OK (4 tests: WDA constants, black screen, contrast, sharpness)
tests/test_roi_scaling.py               ... OK (4 tests: 1080p, 1440p, 21:9 pillarbox, 16:10 letterbox)
tests/test_session_fsm.py               ... OK (1 test: full state machine lifecycle & auto reset)
tests/test_live_auction_e2e.py          ... OK (1 test: end-to-end streaming live replay & auto-archiving)
```

**综合测试通过率：100%**。
