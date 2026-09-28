# 异环拍卖助手 (Neverness to Everness Auction Assistant)

> **2026-09-20 工作区合并：唯一项目目录为 `D:\yihuanpaimai`。** 已纳入 recovery 最新代码及 V2-2 A/B/C、I1 离线集成；原始录像在 `data/videos/`，裁图在 `data/reference-crops/`。不再使用外部 recovery/V2 分支目录。下文旧阶段验收仍按原范围解读，详见 [目录合并说明](docs/reports/2026-09-20-workspace-consolidation.md)。

当前产品版本为 **v0.68-alpha**，以 [core/version.py](core/version.py) 为准。

**整体 PARTIAL：P1/P2 已有阶段验收，P3 完整识别与实机采集尚未验收。** 用户先把识图做好，再恢复日常打局。当前执行与证据范围见 [执行规划](docs/plans/2026-09-05-project-replan.md)；该文件是 Obsidian 项目 Handoff 的同步副本，沿用同一计划。

`7bd8bdd`已修复重复空间特征计数并接入长轴前景对齐，开发局39/39精确几何与自动确证通过。52项回归、真实双窗口连续三轮各12/12通过，每轮39张裁图逐像素正确，正式历史未变。P3仍PARTIAL，下一步转入其他录像逐件审计；当前不进入P4、不覆盖v13、不做实机70秒滚仓。详见[旋转身份验收](docs/reports/2026-09-12-rotation-identity-evidence.md)。

## 当前能力与边界

- P1：字段保护、单字段编辑与真实主窗口/HUD交互已有阶段验收。
- P2：保留 v0.6 数学核心，源码采用独立持久 Node 计算进程；统一识别入口、基准录像四席出价/部分情报、历史重启与忙碌恢复已有阶段验收。
- P3：基准开发局39/39几何分件通过；本开发局39确证/0候选，不代表其他录像完整身份已验收。当前参考清单214项、213项标记接通、1项未决；接通计数不证明源卡绑定正确。
- 其余录像、完整身份、真实70秒滚仓与中断/恢复尚未完成；P4/P5未开始。本轮不覆盖已知v13日常包，也不把它当作包含当前源码的新包。

## 工程与文档

```text
app/       桌面入口、配置与打包
core/      视觉、事实、通信、计算、HUD与归档
lab/       共用v0.6求解器的实验室
assets/    图鉴、源卡、参考裁图与回归依据
tests/     回归测试
tools/     诊断、审计与验收工具
docs/      计划、契约、报告与历史归档
```

- [当前执行规划与验收边界](docs/plans/2026-09-05-project-replan.md)
- [文档索引](docs/README.md)
- [Canonical MatchRecord v7](docs/contracts/canonical-match-record-v7.md)
- [环境复现说明](docs/desktop-environment.md)
- [仓库整理记录](docs/reports/2026-09-08-repository-cleanup.md)
- [本次整理前README与旧架构/路线记录](docs/archive/2026-09/2026-09-12-progress-sync-before/root-README.md)

`build/`与`dist/`是本地构建、运行包与验证目录，不提交Git。原始截图、对局数据、验收证据、使用中的环境与运行包须保留；`experiments/`含实际被程序导入的模块，不能按目录名称直接删除。

## 运行与数据

- 实验室：[lab/index.html](lab/index.html)。
- 源码桌面入口：`app/run.bat`或`app/main.py`；打包配置：`app/异环拍卖助手.spec`。
- 正式可写历史：`%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json`；测试与回放必须使用隔离的`YIHUAN_DATA_ROOT`。
- 历史列表还能通过`app/legacy_archive.py`独立读取旧JSON并展示为LEGACY；根目录同名文件可作为旧档案来源。展示不会自动将它迁入CanonicalHistoryStore或提升正式评估资格。
- 当前已知v13包位置与历史验证范围见执行规划；文件存在不代表进程在线或具备后续源码能力。
