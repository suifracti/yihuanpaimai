# Offline Quantile Calibration Experiment v1 — Report

## 概述与执行总结

本实验针对此前审计中确立的 **分位数覆盖不足（Quantile Under-Coverage）** 与 **上尾漏包（Heavy-Tail Miss）** 现象，建立了严格遵循 Proper Scoring Rules（Quantile Pinball Loss 与 Winkler Interval Score）的时间安全（Time-Safe）、样本外扩展窗口（Expanding Walk-Forward）离线评测框架。

> [!IMPORTANT]
> **本实验核心铁律**：
> 1. **零生产侵入**：未修改任何生产求解器代码、未修改线上参数、主数据库 `异环拍卖数据.json` 保持 100% 字节不变；
> 2. **杜绝自测调参**：严禁在全集上调参后再自测；所有候选模型的缩放与残差参数均在历史训练折（Training Fold）上学习，在未来测试折（Test Fold）上做样本外评测；
> 3. **严格判定标准**：必须同时改善覆盖率与 Proper Scoring Loss，绝不为了刷覆盖率而无限放宽区间。

---

## Part A. v1.1 审计问题的完整收口与闭合

### 1. Cleaner 预测分桶样本数闭合（14 条记录查清）
- **现象定位**：v1.1 报告中 Cleaner 子集标记为 $N=35$，但预测分桶表仅列出 21 条（缺少 14 条）；
- **查清原因**：主库中共有 36 条记录带有 `solverStatus == "valid"`，但其中 15 条（含 14 条 `auto_1786804482` 等）在当时**未生成任何点预测/分位数**（属于 `distributionOnly = True`，`estimate = None`）；
- **真实基准**：**Cleaner 可比点预估样本的精确数量为 $N=21$**（21 局均具有有效 `actualTotal` 与 `point_estimate`）；
- **精确分桶与 Record ID 清单**（$2 + 8 + 9 + 2 = 21$，100% 闭合）：
  1. **`Pred < 30w` ($N=2$)**：`r-msw1vzqp-k4wsht`, `r-msvzv133-3y6ljx`
  2. **`Pred 30w~50w` ($N=8$)**：`r-msw240yh-jflucz`, `r-msw1svxg-ywh6e5`, `r-msw1jsym-kuccw9`, `r-msw1f5l9-ezfg1s`, `r-msw06101-mve216`, `r-msvzdzia-24xwwn`, `r-msvz1kf0-eze7o9`, `r-msvypx11-xjm4qc`
  3. **`Pred 50w~70w` ($N=9$)**：`r-msw1arqo-bascy3`, `r-msw16drb-13km2k`, `r-msw0zatl-b2gtr8`, `r-msw0sh9u-94rikb`, `r-msw0datl-ozwk1k`, `r-msvzrdkz-pdr0gc`, `r-msvzlpww-1rqtl3`, `r-msvz8beg-3flliq`, `r-msvt5jxu-kewgma`
  4. **`Pred 70w~100w` ($N=2$)**：`r-msw1pux4-r1tgou`, `r-msw014jf-ug8f80`

### 2. Cleaner 分位数分母纠正
- **现象定位**：v1.1 报告中 Cleaner 分位数样本标记为 $N=26$，但 Wilson CI 对应 $n=14$；
- **查清原因**：在 21 条 Cleaner 记录中，**精确具有完整分位数（$P20, P50, P80$）的样本量即为 $n=14$**（表头 $26$ 系早期脚本硬编码残留文本）；
- **精确比例与 95% Wilson 置信区间**（$n=14$）：
  - $F(P20) = 7 / 14 = \mathbf{50.0\%}$（95% CI: $[26.8\%, 73.2\%]$，理论目标 $\approx 20\%$）
  - $F(P50) = 7 / 14 = \mathbf{50.0\%}$（95% CI: $[26.8\%, 73.2\%]$，理论目标 $\approx 50\%$）
  - $F(P80) = 9 / 14 = \mathbf{64.3\%}$（95% CI: $[38.8\%, 83.7\%]$，理论目标 $\approx 80\%$）
  - $\text{Central60} = 2 / 14 = \mathbf{14.3\%}$（95% CI: $[4.0\%, 39.9\%]$，理论目标 $\approx 60\%$）

### 3. 标定回归斜率置信区间与稳健回归
计算 OLS 参数置信区间、2,000 次 Bootstrap 置信区间与 Theil-Sen 稳健回归：

| 子集 | N | OLS 拟合方程 | OLS 斜率 95% CI | Bootstrap 斜率 95% CI | Theil-Sen 稳健拟合 | 判定结论 |
| :--- | :---: | :--- | :---: | :---: | :--- | :--- |
| **Cleaner 子集** | 21 | $\text{act} = 155.6\text{k} + 1.141 \times \text{pred}$ | $[-1.071, 3.354]$ | $[-0.195, 2.233]$ | $\text{act} = -161.0\text{k} + 1.344 \times \text{pred}$ | **`SLOPE_INCLUDES_1_INSUFFICIENT_STANDALONE_COMPRESSION_EVIDENCE`** |
| **Proven-Only** | 39 | $\text{act} = 193.9\text{k} + 0.984 \times \text{pred}$ | $[0.266, 1.702]$ | $[0.438, 1.376]$ | $\text{act} = -55.5\text{k} + 1.167 \times \text{pred}$ | **`SLOPE_INCLUDES_1_INSUFFICIENT_STANDALONE_COMPRESSION_EVIDENCE`** |
| **Proven+Likely**| 108| $\text{act} = 344.7\text{k} + 0.599 \times \text{pred}$ | $[0.309, 0.890]$ | $[0.295, 0.993]$ | $\text{act} = 39.5\text{k} + 0.892 \times \text{pred}$ | **`PROVISIONAL`** |

> [!NOTE]
> **结论定性**：在小样本（$N=21, 39$）下，OLS 与 Bootstrap 的斜率 95% 置信区间均跨越 1.0，因此**不能仅凭单点斜率 $\beta = 1.141$ 宣称在统计学上独立证明了压缩**；但正截距（$+155\text{k} \sim +194\text{k}$）稳定存在，且 Theil-Sen 稳健斜率在 $1.16 \sim 1.34$ 区间。

---

## Part B. 重尾误差集中度深度审计 (Heavy-Tail Error Concentration)

对全量 63 条分位数样本的残差分布与误差集中度审计发现：

- **平均绝对误差 (MAE)**：`137,351.56`
- **残差中位数 (Median Signed Residual)**：**`-4,991.33`（几乎为 0，说明常态局中心值无明显系统性偏移）**
- **残差均值 (Mean Signed Residual)**：**`-69,902.29`（被极少数大误差严重拉向负数）**
- **极端尾部误差集中度**：
  - **Top 1 离群样本**：单局贡献全库 **`11.44%`** 的总绝对误差；
  - **Top 5 离群样本**：贡献全库 **`36.00%`** 的总绝对误差；
  - **Top 10 离群样本**：贡献全库 **`53.95%`（超过一半的总误差）**！
- **业务定论**：历史数据中的负向偏差并非“所有局都普遍偏低”，而是**由于少数（Top 10%）爆发性多金/大奖局被模型按平庸均值估算，产生了单局 50w~150w 的巨大负残差**。

---

## Part C. 样本外扩展窗口离线实验 (E0 ~ E4 Walk-Forward OOS)

采用 4 折时间安全扩展窗口（Training Fold $\ge 15$，Test Fold 逐折向后推进，共评测 48 局样本外预测）：

| 实验模型编号与名称 | 平均 Pinball 综合 Loss | 平均 Winkler 评分 (越低越优) | 经验 $F(P80)$ (目标 80%) | Central 60% 覆盖率 (目标 60%) | Central 60% 95% Wilson CI | 中位数归一化宽度 (Span/P50) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **E0: Baseline (原始分位数)** | 48,265.75 | 438,839.12 | 58.33% | 27.08% | $[16.6\%, 41.0\%]$ | 15.76% |
| **E1: 对称宽度自适应缩放** | **48,038.13** | **435,424.85** | 60.42% | 35.42% | $[23.4\%, 49.6\%]$ | 25.21% |
| **E2: 非对称上尾缩放** | 49,595.65 | 458,787.71 | 62.50% | 33.33% | $[21.7\%, 47.5\%]$ | 23.94% |
| **E3: 经验残差后验校准** | 52,803.11 | 506,899.60 | **85.42%** | **54.17%** | $[40.3\%, 67.4\%]$ | 61.54% (过宽) |
| **E4: 特征条件化上尾展开** | 48,740.30 | 445,957.47 | 64.58% | 33.33% | $[21.7\%, 47.5\%]$ | 28.03% |

---

## Part D. 模型世代分群评测结果 (Cohort-by-Cohort)

| 历史算法世代 | 最优模型 | Baseline Winkler | 最优模型 Winkler | Baseline 覆盖率 | 最优模型 覆盖率 | 世代诊断洞察 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`v0.5-field-conditions`** ($N=21$) | **E4 (特征条件化)** | 408,764.19 | **377,999.31** ($-7.5\%$) | 19.05% | **38.10%** ($F(P80): 57.1\% \rightarrow 76.2\%$) | **后验特征展开显著全面改善 Proper Score** |
| **`v0.3-dynamic-walkforward`** ($N=28$) | **E0 (Baseline)** | **636,402.16** | 675,320.66 (E1) | 35.71% | 46.43% (E1) | 原始区间宽度本就较宽（46%），进一步外部后验拉宽会恶化 Sharpness 罚分 |

---

## Part E. 裁决与下一步架构建议

### 1. 实验胜出判定：`NO_CLEAR_WINNER` (无全局统一外部后验胜出者)
- **判定依据**：单一的全局外部后验标定（Post-hoc Scalar Transform）无法在不破坏宽区间代次（v0.3）的前提下，完美修复窄区间代次（v0.5/v0.6）；
- E3 虽刷高了覆盖率至 54%，但 Winkler 罚分大幅恶化（+15.5%），属无效过度放宽。

### 2. 下一步算法原型方向：内部状态概率生成器重构 (State Probability Distribution Generator)
- 严禁在求解器外层强行叠加全局粗暴的外部放大系数；
- 正确的改动位置在 **`v0.65` 内部状态概率生成模块 (`generateDistributionV06`)**：
  - 仅在已知箱型且 $Q \ge 12$ 的高信息局中，基于金/红离散组合的组合数，动态自然生成厚尾概率分布。
