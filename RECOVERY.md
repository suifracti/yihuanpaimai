# RECOVERY — 异环拍卖助手 源码恢复基线

> 本仓库**不是**原仓库的历史延续。原仓库 `D:\yihuanpaimai\.git` 的对象库已损坏，
> 本仓库是从其**当前工作树**恢复出的源码基线，**未伪造任何旧 commit 历史**。

## 来源

- 源仓库工作树：`D:\yihuanpaimai`
- 恢复时间：2026-09-16T03:30:57.020491+08:00
- 恢复方式：只读复制源码基线（按 `.gitignore` 语义排除生成物），`git init` 后建立首个 commit

## 最后已知历史 HEAD（原仓库，已不可读）

```
2c81f9aad1ec2edef064390a4509a6e7a1a64929
```

`git fsck --full` 原文：`error: refs/heads/main: invalid sha1 pointer 2c81f9aad1ec2edef064390a4509a6e7a1a64929`

## 原仓库损坏情况

- `.git/objects/pack/` 仅剩 `multi-pack-index` 与 `pack-64c9077cc24ac9ba34df82c5e0d7d1fc8b15963b.idx`，
  **`pack-*.pack` 数据文件缺失** → `git log` 返回 `fatal: bad object HEAD`
- `git remote -v` 输出为空，`.git/config` 无 `[remote ...]` 段 → **无远端**
- 未执行 `git gc / git repack / git prune / git reset / git checkout / git clean`
- 只读取证封存位置：`D:\yihuanpaimai-recovery\_forensic\old_git_damaged_20260916`

## 本轮（边界 2 缺口 1/2/3 闭合）改动清单

| 文件 | 改动 |
| --- | --- |
| `core/quality_sell_selection.py` | 逐色 provenance 层：VALID_SELECTION_SOURCES / normalize_quality_sell_selection_sources / sources_from_aggregate / manual_override_colors / aggregate_selection_source / merge_quality_sell_selection / apply_single_color_override |
| `core/current_match.py` | FACT_KEYS+empty_facts 增 qualitySellSelectionSources；_coerce_value 分支；apply_facts 逐色合并(protected=any_manual)+派生键拒写；acquisition 逐色刷新；to_canonical 输出三键 |
| `core/canonical_match_record.py` | FORBIDDEN_ROOT_LEGACY_FIELDS 增 qualitySellSelectionSources；settlement→record 逐色规范化 + 聚合派生；新增校验码 |
| `core/canonical_history_store.py` | 两处保留列表增 qualitySellSelectionSources（draft-merge 与 archive-sidecar） |
| `core/auto_archiver.py` | quality-sell 块（503–536）读取/规范化逐色来源并写三键 |
| `core/vision_pipeline.py` | 缺口 3 断点 1 修复：_attach_settlement_ledger 把三个键提升出 ledger 到 settlement/current_context |
| `app/main_view_state.py` | 缺口 3 断点 2 修复：HistoryRecordProjection 增三字段 + to_payload 输出 + _project_record 提取 |
| `core/main_window.js` | 历史详情渲染逐色来源标记（默认/视觉/人工）与 (逐色来源) |
| `tests/test_bottom_quality_sell_selection.py` | 新增身份不漂移用例、逐色 A→D 用例、五跳链路锁定用例（10 项全通过） |
| `docs/plans/2026-09-05-project-replan.md` | canonical 14 项编号恢复；缺口 1/2/3 结论；7 项回归归因；git 损坏记录（未改 7.1） |
| `docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md` | 第 4 节 8 项非 canonical 清单就地撤回 |
| `docs/reports/2026-09-16-boundary2-three-gaps-closure.md` | 本轮外审报告（新增） |
| `build/boundary2_audit_20260916/*` | 缺口 1/2 审计脚本与产物（本轮新增，见 Vault Evidence） |
| `build/boundary2_g3fix_20260916/*` | 缺口 3 最小修复验证、PYZ A/B、bundle 往返脚本与报告（本轮新增，见 Vault Evidence） |

## 冻结候选

| 项 | 值 |
| --- | --- |
| 路径 | `D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260916_2c81f9a_g3fix\dist\异环拍卖助手\异环拍卖助手.exe` |
| 完整 SHA256 | `cc086845f1597edf34bdc0254415e7b69aefe040fc8cbb437e06aba92b768afe` |
| 大小 | 7459953 bytes |
| 隔离标记 | `{"profile":"isolated-trial-v1","codeRevision":"2c81f9a_g3fix"}` |
| 修复前候选 SHA256 前缀 | `f7175a3d…`（完整值见 `min_product_path_report.json`） |

## 若日后找到远端或备份

1. 用真实旧历史恢复（`git fetch` 远端 / 从备份还原 `.git`）；
2. 把本 recovery 工作树按需迁回；
3. **不要**把本仓库的首个 commit 当作原历史。

## 证据

本轮全部原始 Evidence 已同步到 Obsidian Vault：
`D:\ObsidianLiveSyncTestVault\03-项目与工程\异环拍卖助手\Evidence\2026-09-16-boundary2-g3fix-evidence\`
