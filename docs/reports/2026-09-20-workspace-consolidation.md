# 2026-09-20 工作区合并

用户要求合并、转移、删除散落的项目目录，且不制作备份。唯一工作目录为 `D:\yihuanpaimai`。

## 源码

采用健康 recovery 版本库中的 `cb86697` I1 集成作为合并基线；核实集成内 A/B/C 模块分别与 `934ce47`、`b1334c6`、`878435e` 最新源文件一致。三个分支提交历史导入同一 Git 仓库，删除重复克隆和 integration worktree。原损坏 `.git` 删除，由健康版本库替代。原未提交规划、spikes 源码和原目录独有素材保留。

此前仅查看 recovery 的规划未覆盖外部 A/B/C/I1，后续执行必须从当前集成状态继续，不能重复实现已存在的窗口监视、输入安全和冻结协调器。I1 仍仅证明离线 fake 链，不代表真实业务或游戏验收完成。

## 路径

| 原位置 | 当前位置/处理 |
|---|---|
| `D:\yihuanpaimai-recovery` | 最新源码与正常 `.git` 合入项目；旧目录删除 |
| `D:\yihuanpaimai-v2-2a`、`-2b`、`-2c`、`-v2-2-integration` | 源码统一，重复工程删除；有效验收材料移入 `build/` |
| `D:\video` | 移至 `data/videos/` |
| `D:\yihuanpaimai-private` | 移至 `data/reference-crops/` |
| `D:\v2-2b-*`、`D:\v22b-*` | 证据移至 `build/evidence/原目录名/`；编译产物和旧 input-backup 删除 |
| recovery 的 Python 环境链接 | 删除链接，实际环境仍在 `build/takeover_20260905/repro-venv` |

历史证据中的旧路径属于当时来源记录，不批量篡改哈希或原始报告；当前可执行脚本的失效仓库/录像路径已修正。验收器不再声称存在已删除的备份。

目录动作记录在 `build/workspace-consolidation/actions.json`。项目生成物统一写入 `build/`；`AGENTS.md` 记录长期目录约束。

## 迁移后验证与剩余清理

- D 盘根目录相关工程只剩 `yihuanpaimai`；`git worktree list` 仅一个工作区，健康 HEAD 为 `cb86697`，迁移修改尚在工作区。
- 原 Python 3.10 环境正常，53 项业务定向回归全部通过。
- V2 I1 verifier 从统一目录重新编译成功（0 警告、0 错误），11/11 离线场景通过；未执行真实输入。
- 项目内部旧包批量删除被自动审批检查拒绝，原因仅 `blocked by policy`，未执行。用户随后要求提供脚本，已写入 `scripts/cleanup-obsolete-builds.ps1`。
- 脚本预览已执行：101 个生成物目录、约 20.73 GiB；未执行 `-Delete`。源码、Python 环境、录像、参考裁图及包外证据不在删除范围。不创建备份。
