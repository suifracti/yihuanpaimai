# 冻结候选 df58589 边界修复实际 EXE 运行与数据溯源验证（2026-09-15）

整体状态：**PARTIAL**（按既定约束收敛，不跨越任务边界，准备交付外部审核）。  
本轮验证目标：针对 ChatGPT 外部审核意见，验证提交 df58589 的冻结 EXE 产物在独立隔离 DATA_ROOT 下的运行时行为。重点覆盖：
1. **Fix A 边界**：origsha 解耦，不同对局共用同一截图 blob 哈希时严格不合并；同源文件回放重入保持单条记录去重；
2. **Fix B 溯源**：全链路透传 dataOrigin: "replay"，历史复核可读（history.admitted=True），正式模型评估严格拦截（ormally_eligible=False，理由 DATA_ORIGIN_NOT_LIVE）；
3. **29 件审查单元完整保全**：结算图解析 29 件审查单元无损落盘，证据 PNG 无重复膨胀。

---

## 交付身份

| 项 | 值 |
|---|---|
| 代码修订 (Git HEAD) | df58589b61f97ae8492f023df15852cb7111cd86 (short df58589) |
| 构建脚本 | scripts/build_isolated_trial.ps1 |
| 冻结候选产物 | D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_df58589\dist\异环拍卖助手\异环拍卖助手.exe |
| EXE SHA256 | 318D9A0F5FDAA970DA418DA7D84642E1628A9EAAC170030756FBE761A0CFF372 |
| 隔离标记 | profile: isolated-trial-v1 |
| 验证 DATA_ROOT | D:\yihuanpaimai\build\exe_chain_20260915\data_df58589_verify_20260915_134318 |
| 测试回放素材 | settlement_blob_144037.png (SHA256 85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6) |
| 机器证据文件 | erify_df58589_20260915_134318.json |
| 保留历史基线 | 10f167、3c270c8、990f53f、84e0207、447f28b、13 (严格未动) |

---

## 1. Fix A：不同对局共用 origsha 隔离断言（生产存储契约）

在生产 CanonicalHistoryStore 运行环境下执行共用 origsha 隔离断言：
- 注入记录 1：id="match_live_001", dataOrigin="live", origsha="85ce3299..."
- 注入记录 2：id="match_live_002", dataOrigin="live", origsha="85ce3299..."
- 注入记录 3：id="replayfile_85ce3299...", dataOrigin="replay", origsha="85ce3299..."

### 实测结果
- 存储记录数：**严格为 3 条**，未发生任何因 origsha 相同导致的跨对局错误合并。
- 标识集合：{"match_live_001", "match_live_002", "replayfile_85ce3299f6c8304d"}。
- 同键更新断言：再次持久化更新后的 match_live_001，记录总数保持 3 条，match_live_001 的审查单元更新为 2 件。
- 结论：**_extract_match_keys 剔除 origsha:、_can_merge_records 显式非草稿 ID 冲突校验完全生效**。

---

## 2. 冻结 EXE 运行时同源重复回放去重与单元保全

使用全新隔离数据目录 data_df58589_verify_20260915_134318，启动冻结 异环拍卖助手.exe 进行真实多轮运行。

| 阶段 | 运行状态 | 磁盘记录数 | 记录 ID | 审查单元数 | 证据 PNG 数 |
|---|---|---|---|---|---|
| **Run 1 Hold** | 首次归档成功，静帧稳定 | **1** | eplayfile_85ce3299... | **29** | 31 |
| **Run 1 Exit** | 主窗口优雅退出 | **1** | eplayfile_85ce3299... | **29** | 31 |
| **Run 2 Hold** | 再次带同源回放启动，静帧稳定 | **1** | eplayfile_85ce3299... | **29** | 31 |
| **Run 2 Exit** | 主窗口再次优雅退出 | **1** | eplayfile_85ce3299... | **29** | 31 |

### 核心观察
1. **去重序列**：四阶段记录数 [1, 1, 1, 1]，无额外垃圾记录生成。
2. **审查单元**：29 项逐件识别明细完全保留，无审查单元分裂、丢失或重复追加。
3. **证据膨胀防护**：证据 PNG 数量稳定在 31 张，重复运行未产生冗余切片。

---

## 3. Fix B：数据源追踪与正式模型评估准入拦截

对磁盘实际持久化的记录执行契约检验：

`json
{
  "id": "replayfile_85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6",
  "dataOrigin": "replay",
  "lifecycleStatus": "FINALIZED",
  "coverageStatus": null
}
`

调用 pp.evaluation_eligibility.evaluate_record_eligibility(rec, dup_index) 实测结果：

| 检查项 | 预期 | 实测结果 | 评价 |
|---|---|---|---|
| 历史复核准入 (history.admitted) | True | **True** | 允许用户在历史界面查看、复核该回放对局 |
| 正式模型评估准入 (ormally_eligible) | False | **False** | 严格拦截，不可用于模型训练与指标评估 |
| 主要拒绝原因 (primary_reason) | DATA_ORIGIN_NOT_LIVE | **DATA_ORIGIN_NOT_LIVE** | 明确标记来源非真实对局 |
| 溯源元数据透传 (metadata.dataOrigin) | "replay" | **"replay"** | 契约元数据完整记录 |

---

## 4. 隔离与红线核对

1. **日常历史保护**：%LOCALAPPDATA%\异环拍卖助手 与 %LOCALAPPDATA%\异环拍卖助手试用 完全未被写入或修改。
2. **无越界修改**：未修改求解器核心参数、catalog_065 估值逻辑与图像匹配阈值；未修改 GT 标签。
3. **提案独立性**：#10 辣条 ID 冲突方案独立归档于 docs/reports/2026-09-15-item10-latiao-id-conflict-resolution-proposal.md，不越权提前实施。
