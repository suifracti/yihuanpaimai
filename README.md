# 异环拍卖助手 (Neverness to Everness Auction Assistant)

> **2026-09-20 工作区合并：唯一项目目录为 `D:\yihuanpaimai`。** 已纳入 recovery 最新代码及 V2-2 A/B/C、I1 离线集成；原始录像在 `data/videos/`，裁图在 `data/reference-crops/`。不再使用外部 recovery/V2 分支目录。下文旧阶段验收仍按原范围解读，详见 [目录合并说明](docs/reports/2026-09-20-workspace-consolidation.md)。

当前产品版本为 **v0.68-alpha**，以 [core/version.py](core/version.py) 为准。

**当前 Native 主路线为 `YH-MASTER-2026-09-22`，P5 未完成。** 最新阶段、授权范围和下一动作以 [项目 Handoff](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Handoff.md) 与 [Decisions](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Decisions.md) 为准；[旧执行规划](docs/plans/2026-09-05-project-replan.md) 保留历史识别阶段及证据导航，不是最新 Handoff 的完整同步副本。

旧识别阶段的 `7bd8bdd` 已修复重复空间特征计数并接入长轴前景对齐，开发局39/39精确几何与自动确证通过。52项回归、真实双窗口连续三轮各12/12通过，每轮39张裁图逐像素正确，正式历史未变。当时 P3 为 PARTIAL、尚未进入 P4；这些历史结果及后续逐件审计安排不替代当前 Native 路线。详见[旋转身份验收](docs/reports/2026-09-12-rotation-identity-evidence.md)。

## 已有能力与验收边界

- Native 主界面提供默认关闭、启动前选择的“后台只读识别”；允许指定异环窗口失焦或覆盖，最小化/映射失效/无新帧仍停止。普通观察保持只读；用户确认“采集完整仓库”后，独立租约可向异环仓库窗口发向下滚动消息，沿用16页/70秒且无激活或全局输入回退。代码与定向离线检查已完成，真实窗口滚动未验。最新真实后台QA为3尝试/2接受，第3次来源时钟未来值被拒绝，整体未通过；结算原图的白框1×2误合并已定向修复，仓库完整覆盖及完整拍卖未验。见[自动翻页设计与结果](docs/superpowers/specs/2026-10-03-native-warehouse-auto-scroll-design.md)。

- P1：字段保护、单字段编辑与真实主窗口/HUD交互已有阶段验收。
- P2：保留 v0.6 数学核心，源码采用独立持久 Node 计算进程；统一识别入口、基准录像四席出价/部分情报、历史重启与忙碌恢复已有阶段验收。
- P3：基准开发局39/39几何分件通过；本开发局39确证/0候选，不代表其他录像完整身份已验收。当前参考清单214项、213项标记接通、1项未决；接通计数不证明源卡绑定正确。
- Native 已有合格输入的离线 Main/HUD 消费、结算终帧归档和离场续作；最新目录接线修复见 `118370f`。这些定向结果不证明现场及时建议、完整账单、全仓覆盖或连续跨局，P5 仍未完成。
- 旧识别阶段的完整身份与真实70秒滚仓仍未验收；开发材料的机器匹配不等于人工真值或未见准确率。已知 v13 日常包不代表当前源码。

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
