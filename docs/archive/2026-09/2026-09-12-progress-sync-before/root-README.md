# 异环拍卖助手 (Neverness to Everness Auction Assistant)

当前仓库只维护一个产品：`v0.67-alpha 异环拍卖助手`，版本以 `core/version.py` 为准。

当前接手修复与验收范围见 [执行规划](docs/plans/2026-09-05-project-replan.md)。真实游戏全仓采集、中断与集中 UAT 尚未完成，不能把局部测试通过当作整体验收完成。

> [!NOTE]
> 当前状态：P3 阶段性闭环（保持 P3 PARTIAL）。Codex 独立复核确认的四项生产安全缺口（ZIP 重复成员、元数据精确匹配与 size 校验、非官方条目不可变注册防伪、生产切图两阶段暂存与失败回滚）已彻底闭环，回归测试与真实应用隔离连续 3 轮实机双启动/重启/导出 12/12 PASS 全量通过。尚未进行真实 70 秒实机滚仓，未覆盖 v13，未进入 P4。

```text
app/       桌面入口、配置和 PyInstaller spec
core/      视觉、通信、HUD 和归档核心
lab/       与 App 共用同一套 v0.6 求解器的实验室界面
assets/    图鉴、藏品截图和角色/仪器素材
tests/     视觉与解析回归测试
tools/     迁移、旧版 CLI 和诊断工具
docs/      规划、审计和架构记录
```

文档入口见 [文档索引](docs/README.md)。根目录旧阶段报告已统一收进 `docs/archive/2026-08/`；当前开发以执行规划的最新记录为准。

`build/`、`dist/` 用于本地构建和验证，不提交 Git。清理时仅删除已确认不用的程序副本、编译缓存；原始截图、对局数据、验收证据、使用中的环境和运行包须保留。最近一次整理见 [仓库整理记录](docs/reports/2026-09-08-repository-cleanup.md)。

---

## 核心定位与技术路线

1. **视觉感知可靠性优先**：当前核心目标仍然是先把真人对局全流程的 **Perception / OCR** 识别与状态流转做到 100% 可靠。
2. **复用 v0.6 求解器核心**：`v0.6 Solver` 依然是当前估值与决策推演的核心资产，不进行直接重写。
3. **数据契约审计结论**：经全量实测（详见 [docs/audits/2026-08-16-v06-v065-contract-audit.md](docs/audits/2026-08-16-v06-v065-contract-audit.md)），确认当前 0.65 Match Record 与 0.6 求解器存在明显的 **Contract Drift**（旧求解器能够运行，但因均价混叠与嵌套结构丢失已知藏品约束，导致推演退化）。

---

## 目标架构 (Target Architecture)

通过定义标准化的 **Canonical MatchRecord v7**（详见 [docs/contracts/canonical-match-record-v7.md](docs/contracts/canonical-match-record-v7.md)），将视觉事实与求解推演彻底解耦：

```text
0.6 Historical JSON
        ↓
Legacy Normalizer
        ↓
Canonical MatchRecord v7
        ↑
0.65 Live Perception

Canonical MatchRecord v7
        ↓
v0.6 Solver Adapter
        ↓
0.6 Solver
        ↓
Rich Decision / Explainability
```

---

## 研发路线顺序 (Roadmap)

1. **Canonical Contract Design**：制定并固化 Canonical MatchRecord v7 数据中枢规范。
2. **补全 Perception 缺失事实字段**：拆分 `goldAvg` / `purpleAvg`，补齐 `totalItems`（如 66 件总数）等物理事实。
3. **v0.6 Solver Adapter**：编写双向适配器，打通 Canonical 记录与 0.6 求解器，恢复 `goldInference` 候选空间与可解释性。
4. **真人对局回归 (Live Match Regression)**：全链路验证 14:12、12:04 及真实对局。
5. **Warehouse W1**：推进仓库识别与空间推演。
6. **算法复盘与拓展**：对局复盘与多角色帮手支持。

---

## 运行与使用

Windows x64 开发环境与构建步骤见 [环境复现说明](docs/desktop-environment.md)。

- **实验室**：直接在浏览器打开 [lab/index.html](lab/index.html)。
- **桌面助手**：在 Windows 上运行 `app/run.bat`，或用 Python 执行 `app/main.py`。
- **打包配置**：`app/异环拍卖助手.spec`。
- **数据管理**：产品运行时的 writable canonical history 位于
  `%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json`；源码与打包版共用该
  per-user authority。仓库根目录同名文件仅为只读研发/研究参考数据集，产品不会默认读取、迁移或改写它。
