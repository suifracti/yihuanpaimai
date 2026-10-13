# 项目工作规则

> **当前项目交接入口（2026-10-12 起）**：如有授权访问用户 Obsidian Vault，请先遵守 Vault 根 `AGENTS.md`，再读 `03-项目与工程/异环拍卖助手/README.md` → `Handoff.md`（唯一当前进度、最早断点与下一项任务）→ `Decisions.md`（当前技术取舍）。**本 GitHub 仓库只作为代码主源和历史证据，不是另一份当前规划**。旧 [Issue #19](https://github.com/suifracti/yihuanpaimai/issues/19) 已关闭，不自动重开 Issue、PR 或旧 Agent 任务；Google Drive 仅传私人原图、日志、构建 ZIP 等交接附件。没有 Vault 访问权时，将仓库 README 的功能描述视为带日期快照，不假装读过 Vault，不据旧 Issue 进行自动出价、游戏输入或推送。

通用工作与验证规则已移至 [用户级 AGENTS.md](C:/Users/Administrator/.codex/AGENTS.md)。如果当前工具未自动加载，开始工作前读取该文件；本文件仅保留项目专属约束。

## 源码同步（2026-10-13 用户决定）

- GitHub `main` 是最新代码主线；在本目录的 `main` 开发。每次完成修改和最小必要检查后 commit/push，不能把未同步的本地候选当成最新正式源码。Obsidian 保存进度、取舍和证据位置，不维护另一套源码基线。
- 开始修改前读取远端 `main` 和本地状态；发生并行修改时按行为整合，不整文件覆盖或强推。本轮普通修改已获持续同步授权，实机、发布和其他操作仍按当次授权。
- 本地 `codex/consolidate-workspace` 只保留旧私有历史，禁止推送、merge 或 mirror 到公开仓库；保留 `origin` 的禁用推送地址。从公开 `main` 提交后使用 `git push https://github.com/suifracti/yihuanpaimai.git main:main`，不推其他引用。
- 仓库滚动先保存独立原图、继续到物理底部，再核连续覆盖；不能从历史报告恢复 16 SOURCE / 32 请求 / 固定70秒人工总额度。未证明覆盖仍记 PARTIAL。

## 项目目录约束

- 唯一工作仓库是本文件所在目录，目前为 `D:\yihuanpaimai`。V2-2 A/B/C 和 I1 集成已经合并，勿重新建立 recovery 或兄弟项目目录。
- 用户明确不要备份。不要创建 backup、bak、_forensic、整仓副本或兄弟工作目录；正常 Git 提交用于记录源码变更。
- 构建、测试临时目录、运行日志、验收证据全部放本项目 `build/` 内；发布产物放 `dist/`；不要向 D 盘根目录写入项目产物。
- 原始录像在 `data/videos/`，参考裁图在 `data/reference-crops/`。这些是唯一工作素材，不是备份，禁止按生成物删除。
- 原有 `build/takeover_20260905/repro-venv` 是实际开发环境，禁止随构建缓存一起删除。使用仓库测试入口隔离正式用户历史。
- 不默认新建 worktree。确有隔离必要时只能在项目内部明确管理，结束后合并并删除；并行任务按文件分工，避免同一文件多写入者。
- 源码和工具使用项目相对位置推导路径。历史验收报告的旧绝对路径保留当时含义，路径迁移见 `docs/reports/2026-09-20-workspace-consolidation.md`。
