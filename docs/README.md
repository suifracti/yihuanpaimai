# 文档索引

## 当前工作

- [3c270c8 最小实际 EXE 运行](reports/2026-09-15-frozen-exe-runtime-verify.md)：冻结进程跑通；整窗结算 29/26 exact；日志不打印 v2 文件名；识别未归档故无逐件回看。
- [运行时视觉图鉴真实加载与 v2 打包](reports/2026-09-14-runtime-visual-catalog-load.md)：3c270c8 隔离候选已选中 v2；源码/包 213+107 解码校验通过。旧 84e0207 包保留。
- [运行时视觉图鉴差异审计](reports/2026-09-14-runtime-visual-catalog-diff.md)：84e0207 只读对照 AuctionPilot v0.12.7；catalog_065 200 项不是唯一层。

- [源图坐标修复与11候选审计](reports/2026-09-12-source-coordinates-candidate-audit.md)：6d7db48，17项回归、39/39严格几何、新packet三轮应用各12/12及39张裁图像素核验；仍28确证/11候选。

- [裁图来源绑定与事务恢复修复](reports/2026-09-12-crop-provenance-recovery.md)：前轮4dabf27缓存/事务验证；当时哈希与DOM检查未覆盖裁切位置，本轮坐标修复另见上项。
- [18b5e23独立复核](audits/2026-09-12-18b5e23-independent-audit.md)：修复前历史，58项回归通过但三个裁图证据链反例失败。

- [当前执行规划、证据范围与唯一下一步](plans/2026-09-05-project-replan.md)：2026-09-12与Obsidian项目Handoff同步，沿用原路径；旧9月5—7日过程已归档。按用户授权由Codex继续实施；当前修复、验证及下一步见同一计划。
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

代码与真实运行证据是工程事实源。已提交基线、正在修改的工作区、既有测试结果、当前独立验收和已知日常包必须区分。当前P3保持PARTIAL，完整身份与实机采集尚未验收。

历史报告中的代码路径以仓库根目录为基准；本次备份文件中的相对链接保留原文，以原文件位置解释。`lab/`是可运行入口，`experiments/`包含实际导入的采集模块；`design/`、`assets/`及测试夹具分别保留设计来源、产品素材和回归依据。
