# 第 10 项“酷辣辣辣条” catalogId 冲突定性修正与规范化处理方案备忘录

**文件编号**：`PROPOSAL-20260915-ITEM10-LATIAO`  
**报告日期**：2026-09-15（补充外审非循环消歧与分轨机制细则）  
**执行方**：Gemini（单独实施接手）  
**审核方**：ChatGPT（外部审核）  
**当前状态**：待外部审核裁定（本轮严格保持“不改 GT、不改图鉴资料、不改生产匹配”红线）  

---

## 一、定性修正与撤回声明

在首轮报告中，实施方曾使用“已核实同物异 ID（别名映射分歧）”、“良性同物异 ID”等轻描淡写措辞。
**现正式撤回该轻描淡写定性，并接受外部审核纠正**：

1. **冲突的真实本质**：
   - 这是**同一 ID（`image3-0-2`）在不同历史版本与不同品质尺寸下被语义复用（Semantic ID Collision / ID Reuse Conflict）的严重冲突**，绝非单纯的同义别名。
2. **两者的物理与经济属性天差地别**：
   - **版本 A（`catalog_065.json` / 用户原始源卡 A）**：白/灰品质、**尺寸 1×1**、官方基础价值 **100** 金币。
   - **版本 B（`visual_catalog_v2.json` / 用户原始源卡 B / 真实视频录像）**：红色品质、**尺寸 1×2**、官方基础价值 **280,000** 金币。
3. **潜在风险**：
   - 若下游消费端、统计模块或求解器仅依赖裸字符串 `catalogId == "image3-0-2"` 进行简单哈希字典查询而未校验尺寸网格与品质颜色，存在将价值 280,000 的大红物误绑为 100 垃圾底物的致命风险；
   - 现行 `verified_source_card_registry.json` 中无条件将 `image3-0-2` 登记在 `alternateCatalogIds` 下也是不严谨的，缺乏前置上下文约束。

---

## 二、全链路事实核对矩阵（锁定证据）

| 维度 | 版本 A（白色 1×1 辣条） | 版本 B（红色 1×2 辣条） |
|---|---|---|
| **藏品全称** | 酷辣辣辣条 | 酷辣辣辣条 |
| **游戏内品质** | 白色 / 灰色（`white`） | 红色（`red`） |
| **占用网格** | **1×1**（`widthCells: 1, heightCells: 1`） | **1×2**（`widthCells: 1, heightCells: 2`） |
| **官方基础单价** | **100** | **280,000** |
| **对应用户独立源卡** | `1x1/{F65172DF-...}.png`（24, 26, 366, 236） | `1X2/{343D8F72-...}.png`（0, 0, 383, 278） |
| **早期资料（`catalog_065.json`）** | 主键登记为 `image3-0-2` | 未收录 |
| **准入清单（`catalog_reference_manifest_v2.json`）** | 登记为 `image3-0-2` | 独立登记为 **`visual-latiao-1x2`** |
| **生产图鉴（`assets/items/visual_catalog_v2.json`）** | 未独立收录 | **历史字段被错误赋值为 `image3-0-2`** |
| **真值基准（`video_ground_truth_reference_144037.json`）** | 非本局物品 | **明确确认为 `visual-latiao-1x2`** |
| **程序当前输出** | - | 名称对齐“酷辣辣辣条”，ID 取出主键 `image3-0-2` |

---

## 三、现行阶段处置原则（红线）

1. **本轮绝对不改生产代码与资料**：
   - 严禁修改 GT 文件 `video_ground_truth_reference_144037.json`；GT 登记 `visual-latiao-1x2` 属于完全正确的权威真值，绝不为迎合程序当前输出而改写真值。
   - 本轮不改动 `assets/items/visual_catalog_v2.json`、`catalog_065.json`、`verified_source_card_registry.json`。
   - 本轮不修改 `core/settlement_catalog_candidates.py` 等生产匹配器逻辑。
2. **报告与台账记录状态**：
   - 在 14:40:37 逐件台账与报告中，第 10 项状态维持：
     - **名称**：对齐（“酷辣辣辣条” = “酷辣辣辣条”）
     - **catalogId**：标记为 **`VERSION_IDENTIFIER_COLLISION_UNRESOLVED`**（程序输出 `image3-0-2`，真值要求 `visual-latiao-1x2`），保持未关闭状态，交付外部审核。

---

## 四、后续阶段独立实施方案（供外部审核裁定）

待外部审核批准进入图鉴治理专用阶段时，按以下规范化方案执行：

### 1. 彻底杜绝循环论证：消歧依据来自纯视觉物理观测，严禁以价格作为识别前提

**严禁逻辑闭环**：严禁“从歧义 ID 查出价格 280,000，再拿 280,000 证明它是红辣条”；更严禁“在识别尚未完成前，把待估算的基础单价作为识别条件”。

**合法的前置消歧输入（纯物理/视觉观测维度）**：
1. **槽位几何尺寸（Grid Dimension）**：
   - 目标检测在结算仓网格上计算出的 bbox 占格：`widthCells = 1, heightCells = 2`（单格 75px，投影尺寸 75×150）。白辣条为 `1×1`（75×75）。这是纯几何观测，先于任何身份判定。
2. **槽位边框/底色品质（Visual Quality/Rarity）**：
   - 图像槽位分割区域的边框颜色判定或 OCR 区域背景颜色分类：`rarity = "red"`。白辣条为 `white`。这是纯像素级颜色分类，先于任何图鉴查询。
3. **源卡裁图模板视觉相似度（Template Visual Match）**：
   - 待测物品裁图与红辣条独立源卡（`1X2/{343D8F72-...}.png`）的特征相似度达到置信度阈值。

**单向衍生关系**：
$$	ext{纯视觉观测 (1×2 网格, 红色品质, 源卡特征)} \longrightarrow 	ext{确定身份: } 	exttt{visual-latiao-1x2} \longrightarrow 	ext{下游估值模型赋予单价: } 280,000$$

### 2. 新规范绑定与旧记录兼容解析彻底分轨

将“生产识别生成新记录”与“读取消费已落盘旧记录”彻底分轨，避免相互污染：

#### 轨道 A：新规范绑定（生产视觉识别与归档端）
- 在 `assets/items/visual_catalog_v2.json` 中，将源卡 B 条目的主键 `catalogId` 正规化为 `visual-latiao-1x2`。
- 视觉识别管线在根据前述纯物理观测（1×2, red）匹配成功后，直接输出规范主键 `catalogId = "visual-latiao-1x2"`。
- 新归档记录直接携带规范 ID，**不再生产任何含有 `image3-0-2` 的新红色记录**。

#### 轨道 B：旧记录兼容解析（离线回看与历史重读端）
- 仅当系统读取历史上已经落盘的旧版本记录时生效。
- 若旧记录含有 `catalogId == "image3-0-2"`：
  - **允许安全兼容映射**：仅当该历史记录本身持久化了 `rarity == "red"` 或 `grid == (1, 2)` 等物理证据字段时，允许历史展示层安全降级映射至 `visual-latiao-1x2`；
  - **严格 Fail-Closed**：若该旧记录缺失品质与尺寸上下文（例如仅有一个孤立的字符串 `"image3-0-2"`），严禁自动猜测为红辣条，必须抛出 `AmbiguousCatalogIdentifierError` 或标记为待核实，防止误将白辣条当红辣条。
- **历史数据与 GT 只读保护**：绝不重写用户历史记录文件，GT 文件 `video_ground_truth_reference_144037.json` 保持只读。

```python
# 规范解析契约示例（纯物理输入，严禁传入 price）
def resolve_legacy_catalog_identity(
    raw_catalog_id: str,
    *,
    observed_quality: Optional[str] = None,
    observed_grid_w: Optional[int] = None,
    observed_grid_h: Optional[int] = None,
) -> str:
    """Resolve catalog ID with strict context gating (pure visual inputs only)."""
    if raw_catalog_id == "image3-0-2":
        # 必须依赖纯物理/视觉输入消歧，严禁依赖 price/value
        if observed_quality == "red" and observed_grid_w == 1 and observed_grid_h == 2:
            return "visual-latiao-1x2"
        elif observed_quality in ("white", "gray") and observed_grid_w == 1 and observed_grid_h == 1:
            return "catalog065-image3-0-2"
        else:
            raise AmbiguousCatalogIdentifierError(
                f"Identifier 'image3-0-2' requires unambiguous visual physical context. "
                f"Provided: quality={observed_quality}, grid={observed_grid_w}x{observed_grid_h}"
            )
    return raw_catalog_id
```

### 3. 正反例交叉错配检验矩阵（防串物与防串价断言）

后续实施时必须提供以下自动化测试用例，覆盖全部正反边界：

| 用例编号 | 纯物理观测输入 (名称, catalogId, 观测品质, 观测尺寸) | 期望判定结果 | 验证目的 |
|---|---|---|---|
| **TC-01 (白色正例)** | `("酷辣辣辣条", "catalog065-image3-0-2", "white", 1, 1)` | **PASS**，输出规范白 ID，下游估价 100 | 白色 1×1 正常解析与计价 |
| **TC-02 (红色正例)** | `("酷辣辣辣条", "visual-latiao-1x2", "red", 1, 2)` | **PASS**，输出规范红 ID，下游估价 280,000 | 红色 1×2 正常解析与计价（GT 对齐） |
| **TC-03 (受限兼容正例)** | `("酷辣辣辣条", "image3-0-2", "red", 1, 2)` | **PASS**，依据物理输入映射为 `visual-latiao-1x2` | 旧 ID 在物理上下文完整时受限兼容重读 |
| **TC-04 (反例：尺寸串物)** | `("酷辣辣辣条", "visual-latiao-1x2", "white", 1, 1)` | **FAIL-CLOSED**（尺寸/品质与规范 ID 冲突拒绝） | 防止将 1×1 白辣条误作为 1×2 红辣条 |
| **TC-05 (反例：价格窜改)** | `("酷辣辣辣条", "catalog065-image3-0-2", "red", 1, 2)` | **FAIL-CLOSED**（尺寸/品质与规范 ID 冲突拒绝） | 防止将 1×2 红辣条按 100 金币贱卖/估价 |
| **TC-06 (反例：裸别名无上下文)** | `("酷辣辣辣条", "image3-0-2", None, None, None)` | **FAIL-CLOSED**（无物理上下文拒绝） | 彻底封死无保护的全局裸别名盲查 |

---

## 五、结论

本备忘录彻底纠正了首轮审计对第 10 项 ID 冲突的定性偏差，排除了以价格证明 ID 的循环论证，确立了“消歧依据纯视觉物理观测”、“新规范生成与旧记录解析彻底分轨”、“GT 与历史原证据只读”的治理路径，现正式归档并交付外部审核（ChatGPT）裁定。
