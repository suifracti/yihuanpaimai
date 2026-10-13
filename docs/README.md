# 文档索引

> **本仓库 `docs/` 是工程技术与历史资料索引，不是新的项目交接或实时任务规划。** 请先按仓库根 `AGENTS.md` 阅读授权 Obsidian 的现行 Handoff，再按需要查本目录的日期报告。

## 当前工作

- **2026-10-13 本地/公开源码收敛**：[源码与历史对齐记录](reports/2026-10-13-source-mainline-alignment.md)。以后 GitHub `main` 保存最新源码，每次修改完成同步；Obsidian 保留当前进度与授权边界。旧分支、旧候选和日期报告不作为另一条活动源码主线。

- **2026-10-12 单主线**：所有已公开开发成果已收拢至 `main`；**项目最新任务与验收状态只在授权 Obsidian Vault 的 `03-项目与工程/异环拍卖助手/README.md` → `Handoff.md` 中交接**，技术决定见 `Decisions.md`。已关闭的 [Issue #19](https://github.com/suifracti/yihuanpaimai/issues/19) 仅为历史归档，不能据其旧正文继续派工。下方日期文档只按各自发生时点使用。

- **2026-10-09 规划接手**：[收尾规划](plans/2026-09-05-project-replan.md#2026-10-09-规划接手恢复成果收敛到完整产品)。已有成果归位、第一包接收结果及下一包自动收仓范围见该节；当前状态见 Obsidian Handoff 最新节。以下保留历史证据范围。

- [2026-10-03 正式后台只读识别设计与交付](superpowers/specs/2026-10-03-native-background-observation-design.md)及[自动翻页候选](superpowers/specs/2026-10-03-native-warehouse-auto-scroll-design.md)：代码已实施、真实生产验收未完成。早期大厅QA为2尝试/1接受，最新结算QA为3尝试/2接受、未来来源时间拒绝，均整体未通过；原始时钟诊断已准备，真实滚动、全仓覆盖及完整拍卖仍未验证。

- **现行 Obsidian 项目入口**：`03-项目与工程/异环拍卖助手/README.md`，其下 `Handoff.md` 是唯一活动交接，`Decisions.md` 是长期决定；需获 Vault 访问权。`YH-MASTER-2026-09-22` 及 2026-09-28 的 P5 记载属于历史，不能作为当前任务或授权。

- [2026-09-20 Luna Max Goal 执行规划](plans/2026-09-20-luna-max-goal.md) 与 [已实施范围报告](reports/luna-goal-acceptance.md)：保留当时 V2-2 A/B/C、I1 的传帧、恢复与受控窗口证据；其结果不替代当前 Native P5 现场验收，旧时长/验证矩阵不作为本轮默认执行要求。

- [3c270c8 最小实际 EXE 运行](reports/2026-09-15-frozen-exe-runtime-verify.md)：冻结进程跑通；整窗结算 29/26 exact；日志不打印 v2 文件名；识别未归档故无逐件回看。
- [运行时视觉图鉴真实加载与 v2 打包](reports/2026-09-14-runtime-visual-catalog-load.md)：3c270c8 隔离候选已选中 v2；源码/包 213+107 解码校验通过。旧 84e0207 包保留。
- [运行时视觉图鉴差异审计](reports/2026-09-14-runtime-visual-catalog-diff.md)：84e0207 只读对照 AuctionPilot v0.12.7；catalog_065 200 项不是唯一层。

- [源图坐标修复与11候选审计](reports/2026-09-12-source-coordinates-candidate-audit.md)：6d7db48，17项回归、39/39严格几何、新packet三轮应用各12/12及39张裁图像素核验；仍28确证/11候选。

- [裁图来源绑定与事务恢复修复](reports/2026-09-12-crop-provenance-recovery.md)：前轮4dabf27缓存/事务验证；当时哈希与DOM检查未覆盖裁切位置，本轮坐标修复另见上项。
- [18b5e23独立复核](audits/2026-09-12-18b5e23-independent-audit.md)：修复前历史，58项回归通过但三个裁图证据链反例失败。

- [旧识别执行规划与证据范围](plans/2026-09-05-project-replan.md)：保留旧 P1/P2/P3 识别阶段及历史证据；页首已有当前主路线导航，最新修复与下一动作见上述项目 Handoff。
- [桌面环境与构建复现](desktop-environment.md)：依赖、启动、测试和打包步骤。
- [仓库整理记录](reports/2026-09-08-repository-cleanup.md)：保留范围与整理依据。
- [9月8日手动对局排查](reports/2026-09-08-manual-match-diagnosis.md)：历史问题与证据，不代替当前计划。
- [v13通信冻结修复报告](reports/2026-09-09-v13-freeze-fix.md)：已知旧交付包范围，不等于当前源码验收。
- [整理前执行规划完整记录](archive/2026-09/2026-09-12-progress-sync-before/2026-09-05-project-replan.md)：原文保留，用于追溯。
- [整理前根目录README](archive/2026-09/2026-09-12-progress-sync-before/root-README.md)、[整理前文档索引](archive/2026-09/2026-09-12-progress-sync-before/docs-README.md)。

## 目录用途

| 目录 | 内容 |
|---|---|
| `plans/` | 当前执行计划；与Obsidian同一计划同步，不另立路线 |
| `contracts/` | 数据契约与JSON Schema |
| `distribution/` | 使用者交付说明 |
| `reports/` | 有日期和验证范围的报告 |
| `audits/` | 专题审计，按其基线与证据范围阅读 |
| `archive/` | 旧阶段报告与整理前原文 |

代码与真实运行证据是工程事实源。已提交基线、正在修改的工作区、既有测试结果、当前独立验收和已知日常包必须区分。旧识别阶段 P3 保持 PARTIAL；当前 Native P5 仍未完成，完整身份与实机采集不能由旧报告推定通过。

历史报告中的代码路径以仓库根目录为基准；本次备份文件中的相对链接保留原文，以原文件位置解释。`lab/`是可运行入口，`experiments/`包含实际导入的采集模块；`design/`、`assets/`及测试夹具分别保留设计来源、产品素材和回归依据。
# QA 维护入口迁移（2026-10-04）

独立 QA 的维护源码与使用说明见 [tools/native_qa](../tools/native_qa/README.md)。编译及新运行输出为 `build/native_qa/`；旧 `build/warehouse-recognition-20261002/bounded-wgc-qa/` 仅保留历史源码快照与证据。本次迁移只检查编译、帮助参数与未授权启动拒绝，没有采集游戏或重跑旧矩阵。
