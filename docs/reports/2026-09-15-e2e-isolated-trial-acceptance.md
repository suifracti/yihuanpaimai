# 冻结候选 ff0e2da 完整隔离试用流程 E2E 体验验收与单局连续性收口报告（2026-09-15）

整体结论：**PARTIAL**（16 步隔离试用最小完整流程与单局连续性实测全部闭环通过；同一局手动/自动事实严格原地演进进入唯一一条 `FINALIZED` 记录，零残留幽灵草稿，冷启动与异机导入保持严格 1 条，显式开启下一局才生成第 2 条；具备提供给用户进行隔离试用的坚实基础；底部品质出售默认勾选机制尚未实现，如实记录为既定十四类未完成边界第 2 项真实缺口）。

---

## 交付身份与环境基线

| 项 | 值 |
|---|---|
| 评估对象 | 冻结构建候选 `ff0e2da` |
| 代码基线 (Git HEAD) | `ff0e2da42d62bf3dca77e384ba630c76ad7c1a96` |
| 前置修复提交 | `a8fe6eb` (单局连续性草稿原地演进与事实继承), `ff0e2da` (启动对局会话预置) |
| 候选包路径 | `D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_ff0e2da\dist\异环拍卖助手\异环拍卖助手.exe` |
| 候选包 SHA256 | `77A8A6F1DF54F8ACC71AC81542249818581126E9B2849E030408F4B1EA65A1DF` |
| 候选标记 | profile: `isolated-trial-v1`, codeRevision: `ff0e2da` |
| 隔离测试数据目录 1 | `D:\yihuanpaimai\build\e2e_trial_20260915\data_trial_1` |
| 隔离测试数据目录 2 | `D:\yihuanpaimai\build\e2e_trial_20260915\data_trial_2` |
| 离线回放素材 | `settlement_blob_144037.png` (SHA256 `85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6`) |
| 自动化验收驱动 | `D:\yihuanpaimai\build\e2e_trial_20260915\run_e2e_isolated_trial.py` |
| 机器证据文件 | `D:\yihuanpaimai\build\e2e_trial_20260915\e2e_trial_report.json` |
| 导出验证压缩包 | `D:\yihuanpaimai\build\e2e_trial_20260915\trial_export_bundle.zip` (8,929,159 字节，35 个文件，1 条记录) |
| 日常与旧试用目录保护 | `%LOCALAPPDATA%\异环拍卖助手` (1603 文件)、`异环拍卖助手试用` (61 文件) 严格未变 |
| 历史候选包保护 | `df58589`、`447f28b`、`879dfed` 目录与产物哈希完全一致，无任何篡改或覆盖 |

---

## 1. 16 步隔离试用最小完整流程实测（含单局连续性）

本轮测试在全新独立临时 `YIHUAN_DATA_ROOT` 下，通过真实启动候选 EXE 进程并调用 WinForms/WebView2/WebSocket 接口执行：

| 步骤编号 | 步骤名称 | 预期行为 | 实际运行结果 | 状态 | 关键证据 |
|:---|:---|:---|:---|:---:|:---|
| **Step 1** | **启动主窗口与 HUD** | 双窗口启动，HWND 可探测，WebSocket 通信建立，WebView2 桥就绪 | 主窗口 HWND=200380，HUD HWND=2297376，PID=12432，WS 成功连接，DirectComposition 与 WebView2 正常渲染就绪 | **PASS** | `step1_launch_windows` |
| **Step 2** | **空历史/新局初始状态** | 独立目录下历史初始为空，DOM 徽章显示 `0 条`，空状态占位符可见，无幽灵草稿落盘 | DOM `history-empty-state` 显示，徽章 `0 条`，列表项为 0，磁盘 `异环拍卖数据.json` 记录数为 0 | **PASS** | `step2_empty_state` |
| **Step 3** | **创建或进入一局** | 对局会话激活，使用稳定可信会话 ID，生命周期为 `DRAFT`，总览卡片正确展示概况 | `matchId=replayfile_85ce3299...`，生命周期为 `DRAFT`，总览展示“珊瑚场 · 琉璃宝箱 / 标准规则” | **PASS** | `step3_enter_match` |
| **Step 4** | **手动填入现有可填事实** | 主窗口与 HUD 填入可编辑字段（q=21，蓝=3，红=1，场次=珊瑚，箱型=琉璃，均价=64836） | 主窗口与 HUD 同步更新相应输入控件，DOM 表单与 native 状态均成功接收并保持输入值 | **PASS** | `step4_fill_facts` |
| **Step 5** | **自动更新与手动保护共存** | 手动修改标记 protected；输入 `__unknown__` 清空；输入 `__restore_auto__` 恢复自动识别 | 选箱后 `boxProtected: True`；清空后状态为 `cleared`；恢复后 `boxProtected: False`，符合 7.1 规则 | **PASS** | `step5_manual_protection_coexistence` |
| **Step 6** | **主窗口与 HUD 联动** | 主窗口修改 q 值（21）同步至 HUD；HUD 切换箱型（琉璃宝箱）同步至主窗口展示 | HUD `qInput` 变为 21；主窗口 `match-box-display` 变为“琉璃宝箱”，双向通信无卡顿 | **PASS** | `step6_main_hud_sync` |
| **Step 7 & 8** | **离线真实素材结算识别与原地归档（单局连续性）** | 结算归档落盘：同一对局 ID 原地演进为 `FINALIZED`，**磁盘严格仅 1 条记录（0 残留草稿）**，继承 Step 4/5 保护事实，挂载 29 件审查单元与第 10 项规范 ID | `totalRecords=1, finalizedRecords=1, draftRecords=0`；继承 `envBox='琉璃宝箱', pubQ=21, blueCount=3, redCount=1, goldAvg=64836`；第 10 项 `visual-latiao-1x2` (280k CONFIRMED)；切片 SHA 一致 | **PASS** | `step7_recognition_and_step8_save` |
| **Step 9** | **历史回看逐件核对** | 打开历史视图，列表项严格 1 条（徽章 `1 条`），展开详情卡片，29 件切片图完整存在且 SHA256 一致 | 点击已归档对局成功展开详情，DOM 徽章为 `1 条`，第 10 项切片路径 `5e1b9aba...png` 存在且哈希校验一致 | **PASS** | `step9_history_review_and_items` |
| **Step 10** | **关闭程序** | 响应 `WM_CLOSE` 优雅退出，协调器正常清理资源，无残留僵尸进程 | 进程返回退出码，后台无残留 `*异环*` 孤儿进程 | **PASS** | `step10_close_program` |
| **Step 11** | **重新打开继续回看** | 重启相同候选 EXE，读取相同目录历史数据，**严格保持 1 条记录**，无新增幽灵空草稿 | 重启后 DOM 徽章 `1 条`，列表项 1 个，磁盘记录严格为 1，无自动产生冗余草稿 | **PASS** | `step11_restart_and_reopen_history` |
| **Step 12** | **导出记录** | 原生无头触发导出 ZIP 数据包，包含 manifest、records.json 与切片原图（仅 1 条记录） | 生成 `trial_export_bundle.zip` (8.9MB)，含 35 个文件，包含 1 条 finalized 记录与完整切片 | **PASS** | `step12_export_records` |
| **Step 13 & 14** | **导入全新 DATA_ROOT 并核对** | 启动全新空目录 `data_trial_2`，导入 ZIP，**严格呈现 1 条记录**；文字、图片、来源、生命周期完全保真 | 导入后成功还原 1 条对局、29 件审查单元，第 10 项辣条切片存在且哈希匹配，来源保持 `replay`，状态 `FINALIZED`，DOM 徽章 `1 条` | **PASS** | `step13_import_and_step14_verify` |
| **Step 15** | **显式开启下一局（多局隔离验证）** | 显式触发 `begin_next_manual_match`，**产生第 2 条记录（DRAFT）**，原 FINALIZED 记录不被冲掉 | 记录总数变为 2（1 finalized + 1 draft），原对局数据完整保留，DOM 徽章 `2 条` | **PASS** | `step15_new_match_reset` |
| **Step 16** | **全程目录与历史隔离** | 验证日常数据目录、旧试用目录、旧候选目录无任何被写入或篡改迹象 | 正式与旧试用目录文件数与哈希前后一致；`df58589`、`447f28b`、`879dfed` 构建包完全未被改动 | **PASS** | `step16_isolation_and_integrity` |

---

## 2. 单局连续性（Single Match Continuity）根因与修复说明

上一轮 `879dfed` 验收中暴露的问题：结算归档后历史列表产生 2 条记录（1 draft + 1 finalized）。
本轮根因排查与工程修复闭环如下：

1. **根因一：`data_origin` 跨进程未同步触发 Fix B 隔离门禁**：
   GUI 进程启动时默认 `CURRENT_MATCH.data_origin = "live"`，但离线回放 Worker 发布帧为 `replay`。在结算归档时，Fix B 的 `_can_merge_records` 规则严格禁止将 `live` 与 `replay` 记录混并，导致原草稿无法原地演进，进而另起了一条结算记录。
   - **修复**：在 [`core/live_match_transport.py`](file:///D:/yihuanpaimai/core/live_match_transport.py) 中，`LiveMatchReceiver.apply` 同步更新 `current_match.data_origin = snapshot.get("dataOrigin")`；在 [`app/main.py`](file:///D:/yihuanpaimai/app/main.py) 启动配置读取后，若配置了回放文件源，立即预置稳定 session key 与 `data_origin = "replay"`。
2. **根因二：草稿演进至已结算时丢失受保护事实**：
   在 `persist_record_transactional` 中，此前仅处理了 sidecars 侧写信息合并，未将 DRAFT 中用户手动填入的 Rule 7.1 事实（`fieldStates`）及命名空间数据（`environment`、`publicIntel`、`qualities`）安全继承至 `FINALIZED` 记录中。同时，Canonical v7 schema 严禁在顶层直接写入 legacy 扁平字段（如顶层 `q`、`box`、`goldAvg`）。
   - **修复**：在 [`core/canonical_history_store.py`](file:///D:/yihuanpaimai/core/canonical_history_store.py) 中，实现了符合 v7 规约的命名空间事实合并逻辑与 `fieldStates` 保护继承，彻底打通原地演进链路。

---

## 3. 重点体验与 UX 审查点核对（如实回答，不作美化）

| UX 审查点 | 审查问题与核对结论 | 实测现状与评定 |
|:---|:---|:---:|
| **1. 页面与操作可用性** | **主窗口与 HUD 交互是否顺畅？有无死锁、无响应、按钮无效？**<br>总览、对局、历史视图切换流畅，HUD 浮窗透明度与 DirectComposition 渲染稳定无抖动。无头桥调用与原生事件均正常响应。 | **PASS** |
| **2. 主窗口与 HUD 字段一致性** | **两端同一概念命名与展示是否一致？数值联动是否即时？**<br>主窗口与 HUD 均使用“q”（底注参数）、“珊瑚场”、“琉璃宝箱”，主窗口输入 21 瞬间同步至 HUD，HUD 选箱即时同步至主窗口展示，字段语义统一。 | **PASS** |
| **3. DRAFT 与 FINALIZED 的展示与连续性** | **用户能不能一眼分清草稿与正式局？同一局是否会产生重复条目？**<br>在历史列表中，同一局在录入事实时为草稿，结算识别后原地演进为正式局，**列表中严格仅 1 条**；只有用户显式点击开启下一局后，才会出现第 2 条（新草稿），状态区分清晰，绝无重复条目。 | **PASS** |
| **4. 空草稿/历史边界** | **纯启动时是否会产生无意义空草稿？手动填入事实后草稿落盘是否正常？**<br>实测纯启动进入 Step 2 时磁盘记录为 0，绝无幽灵空草稿；进入 Step 4 手动录入事实后，草稿自动持久化落盘，确保用户录入不丢失。 | **PASS** |
| **5. 历史图片与切片展示** | **历史回看是否能看到逐件切片？图片缺失时如何表现？**<br>历史回看中全部 29 个审查单元均有独立切片并正常渲染，第 10 项辣条切片存在且哈希严格匹配。若图片缺失，UI 优雅回退为品类图标并标注缺失。 | **PASS** |
| **6. 导出导入可重定位性** | **导出的 ZIP 包搬到全新临时目录导入后，是否能完整查看文字与切片？**<br>在全新空目录 `data_trial_2` 中冷导入导出的 8.9MB ZIP 包，1 条对局、29 个审查单元与全部切片原图 100% 完整复原，哈希一致，来源保真为 `replay`。 | **PASS** |
| **7. 底部品质出售默认勾选机制** | **目前是否已实现“底部品质出售默认勾选”？**<br>**未实现**。该功能属于既定十四类未完成边界中的**第 2 项**（出货/出售默认勾选策略）。目前代码库中尚无该项业务逻辑。如实记录为缺口，绝不假装通过。 | **REAL GAP (第 2 项缺口)** |
| **8. 报错与重启表现** | **关闭程序时是否有报错弹窗或残留进程？重启后历史是否一致？**<br>正常响应 `WM_CLOSE` 优雅退出，协调器依次关闭各子系统，无报错弹窗，无孤儿进程残留；重启后历史数据严格呈现 1 条，无幽灵草稿产生。 | **PASS** |

---

## 4. 十四类未完成边界覆盖与缺口清查

> **2026-09-16 更正**：本节原先给出的 8 项清单**不是 canonical**，已就地撤回，不得继续引用。
> 本轮流程实际覆盖的是"试用链路可用性"，不是那 8 项；下面改为逐项对照 **canonical 十四类未完成边界**（编号与名称唯一权威，禁止改名、换序，也不得用本轮局部验证替换）。

Canonical 十四类未完成边界：

1. 真实本人获胜实录及自动归属全链
2. 底部品质出售默认勾选机制
3. 真实游戏键鼠接管与防干扰
4. 真实限时全仓滚动与跨页物品去重拼接
5. 疑难物品左键详情采集与关闭恢复
6. 70秒/游戏倒计时截止及离线继续识别
7. 离线结算与草稿治理，含胜者名单治理
8. 至少3局未参与调参的真实对局端到端验证
9. 连续识别稳定性与内存问题
10. 实时性能门槛：忙碌确认P95≤0.5s；出价到显示P95≤1.5s；情报结构化P95≤2s
11. 跨电脑/目录带图导出及manifest校验
12. 免费情报专属业务链
13. `tests.test_match_trunk` 两项历史测试债
14. 2D无有限上限全面可行性与二维摆放求解

本轮 16 步隔离试用对上述边界的影响范围：

- 第 2 项：本轮报告记为**未实现**。该结论属当时的代码时点；2026-09-16 已实现默认勾选与逐色 provenance，但真实游戏物理点击仍属第 3 项，故第 2 项不据此标完整 PASS。
- 第 11 项：导出/导入往返与 manifest 核对在隔离环境通过，仅覆盖隔离试用链路，不覆盖跨电脑真实场景。
- 第 7 项：单局连续性（零幽灵草稿）通过，但胜者名单治理仍未完成，故第 7 项整体仍未完成。
- 第 1、3、4、5、6、8、9、10、12、13、14 项：本轮未覆盖，保持未完成。

---

## 5. 结论与交付建议

- **当前候选版本评定**：**PARTIAL**。
- **可体验性回答**：本包 `ff0e2da` **完全可以提供给用户进行隔离试用与全流程功能体验**。
  1. 双窗口启动、实时双向通信、手动事实录入与保护、实机画面结算识别、历史回看（含逐件切片与详情）、退出与冷重启、导出/导入数据迁移均已在独立环境下实测验证通过；
  2. 单局事实与结算归档**严格原地演进**，结算后仅 1 条 FINALIZED 历史记录，无冗余草稿，冷重启与全新导入严格保持 1 条，显式开启下一局才生成第 2 条；
  3. 全程在独立临时数据目录下运行，对用户的正式数据或既有归档零干扰。
- **已知限制提醒**：用户试用时需注意“底部品质出售”需手动勾选，该功能为后续既定规划项。
