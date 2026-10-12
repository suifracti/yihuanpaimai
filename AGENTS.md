# 项目工作规则

> **当前项目交接入口（2026-10-12 起）**：如有授权访问用户 Obsidian Vault，请先遵守 Vault 根 `AGENTS.md`，再读 `03-项目与工程/异环拍卖助手/README.md` → `Handoff.md`（唯一当前进度、最早断点与下一项任务）→ `Decisions.md`（当前技术取舍）。**本 GitHub 仓库只作为代码主源和历史证据，不是另一份当前规划**。旧 [Issue #19](https://github.com/suifracti/yihuanpaimai/issues/19) 已关闭，不自动重开 Issue、PR 或旧 Agent 任务；Google Drive 仅传私人原图、日志、构建 ZIP 等交接附件。没有 Vault 访问权时，将仓库 README 的功能描述视为带日期快照，不假装读过 Vault，不据旧 Issue 进行自动出价、游戏输入或推送。

通用工作与验证规则已移至 [用户级 AGENTS.md](C:/Users/Administrator/.codex/AGENTS.md)。如果当前工具未自动加载，开始工作前读取该文件；本文件仅保留项目专属约束。

## 项目目录约束

- 唯一工作仓库是本文件所在目录，目前为 `D:\yihuanpaimai`。V2-2 A/B/C 和 I1 集成已经合并，勿重新建立 recovery 或兄弟项目目录。
- 用户明确不要备份。不要创建 backup、bak、_forensic、整仓副本或兄弟工作目录；正常 Git 提交用于记录源码变更。
- 构建、测试临时目录、运行日志、验收证据全部放本项目 `build/` 内；发布产物放 `dist/`；不要向 D 盘根目录写入项目产物。
- 原始录像在 `data/videos/`，参考裁图在 `data/reference-crops/`。这些是唯一工作素材，不是备份，禁止按生成物删除。
- 原有 `build/takeover_20260905/repro-venv` 是实际开发环境，禁止随构建缓存一起删除。使用仓库测试入口隔离正式用户历史。
- 不默认新建 worktree。确有隔离必要时只能在项目内部明确管理，结束后合并并删除；并行任务按文件分工，避免同一文件多写入者。
- 源码和工具使用项目相对位置推导路径。历史验收报告的旧绝对路径保留当时含义，路径迁移见 `docs/reports/2026-09-20-workspace-consolidation.md`。
