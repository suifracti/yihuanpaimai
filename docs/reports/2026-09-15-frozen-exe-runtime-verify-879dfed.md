# 冻结候选 879dfed 第 10 项规范 ID 绑定与消歧真实 EXE 运行验证报告（2026-09-15）

整体状态：**PARTIAL**（第 10 项“酷辣辣辣条”规范 ID 绑定与物理消歧完全闭环，继承并维持 Fix A/B 溯源与去重契约，准备交付外部审核）。

---

## 交付身份

| 项 | 值 |
|---|---|
| 代码修订 (Git HEAD) | 879dfed5ae7aa93c8dc71caf04486df94bc22566 (short 879dfed) |
| 构建脚本 | scripts/build_isolated_trial.ps1 |
| 冻结候选产物 | D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_879dfed\dist\异环拍卖助手\异环拍卖助手.exe |
| EXE SHA256 | B72151685AD319EFF6777D86842CB498CAFD38F3091A55DA9A04C9F4AD3AD0DD |
| 隔离标记 | profile: isolated-trial-v1, codeRevision: 879dfed |
| 验证 DATA_ROOT | D:\yihuanpaimai\build\exe_chain_20260915\data_879dfed_verify_20260915_143820 |
| 测试回放素材 | settlement_blob_144037.png (SHA256 85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6) |
| 机器证据文件 | verify_879dfed_20260915_143820.json |
| 保留历史基线 | df58589、447f28b、a10f167、3c270c8、990f53f、84e0207、日常 v13 (严格未动) |

---

## 1. 第 10 项“酷辣辣辣条”规范 ID 绑定与审查单元完整性实测

在全新隔离数据目录 `data_879dfed_verify_20260915_143820` 下，启动冻结 `异环拍卖助手.exe` 进行真实结算解析落盘。

### 审查单元落盘实测数据（settlement_item_10）

```json
{
  "reviewUnitId": "settlement_item_10",
  "canonicalName": "酷辣辣辣条",
  "selectedCatalogId": "visual-latiao-1x2",
  "price": 280000,
  "confirmationStatus": "CONFIRMED",
  "identityStatus": "EXACT_IDENTIFIED",
  "footprint": {
    "widthCells": 1,
    "heightCells": 2
  },
  "rarity": "red",
  "gridShape": "1x2",
  "cropPath": "evidence/settlement_v2/blobs/5e/5e1b9abaad84003b9fed5c3899c6a3d40cb3b3987abfcc9c43edec54bf4c1b17.png",
  "cropSha256": "5e1b9abaad84003b9fed5c3899c6a3d40cb3b3987abfcc9c43edec54bf4c1b17"
}
```

### 核心断言核对

| 检查项 | 历史现状 (df58589) | 本轮实测 (879dfed) | 状态 | 规范要求 |
|---|---|---|---|---|
| **规范 catalogId** | `image3-0-2` (错误混用) | **`visual-latiao-1x2`** | **PASS** | 严格绑定红 1×2 独立源卡规范主键 |
| **物品名称** | `酷辣辣辣条` | **`酷辣辣辣条`** | **PASS** | 保持规范名称一致 |
| **估值价格** | 280,000 | **280,000** | **PASS** | 准确下游赋值，非循环前置推导 |
| **网格形态** | `1x2` (w=1, h=2) | **`1x2` (w=1, h=2)** | **PASS** | 物理占位严格为 1×2 纵向 |
| **品质颜色** | `red` | **`red`** | **PASS** | 物理视觉品质为红色 |
| **审查单元状态** | CONFIRMED / EXACT_IDENTIFIED | **CONFIRMED / EXACT_IDENTIFIED** | **PASS** | 确保证实无误，不退化为待核 |
| **截图切片文件** | 存在且 SHA256 匹配 | **存在且 SHA256 匹配** | **PASS** | 5e1b9aba... 证据无损保全 |
| **审查单元总数** | 29 | **29** | **PASS** | 29 件审查单元无分裂、丢失或增删 |

---

## 2. 身份、资料与非循环消歧机制闭环

1. **白色 1×1 保留原有规范 ID**：
   - `assets/catalog_065.json` 中 `image3-0-2` 维持 `name: 酷辣辣辣条, quality: 灰/白, widthCells: 1, heightCells: 1, value: 100`，原文件只读未改。
   - 绝未引入提案示例中的 `catalog065-image3-0-2`，避免图鉴命名空间污染。
2. **解除 Registry 无条件 Alias 绑定**：
   - `assets/items/verified_source_card_registry.json` 中 `visual-latiao-1x2` 的 `alternateCatalogIds` 已清空为 `[]`。
   - 彻底切断任何无物理门禁前提下将 `image3-0-2` 自动转为红辣条的通道。
3. **视觉源卡主 ID 修正**：
   - `assets/items/visual_catalog_v2.json` 中对应红辣条记录 `catalogId` 修正为 `"visual-latiao-1x2"`，保留 `legacyCatalogId: "image3-0-2"` 供兼容层追溯。
4. **纯物理消歧（拒绝价格循环论证）**：
   - `core/catalog_validator.py` 中 `resolve_legacy_catalog_identity` 与 `validate_item_physical_consistency` 严格以物理观测（`quality`、`widthCells`、`heightCells`、视觉相似度）作为消歧条件。
   - **绝不使用待求估值 280,000 作为判定红辣条的前提条件**。
   - 缺失物理上下文的裸 `image3-0-2` 严格 Fail-Closed（抛出 `AmbiguousCatalogIdentifierError`），绝不盲猜红辣条。
5. **交叉物理一致性校验**：
   - `validate_item_physical_consistency` 强制校验名称、尺寸与品质。例如 `visual-latiao-1x2` 若出现 1×1 或白色品质，或者 `image3-0-2` 出现 1×2 或红色品质，立即拦截并报错。

---

## 3. 继承与维持 Fix A & Fix B 运行契约

| 阶段 | 运行状态 | 磁盘记录数 | 记录 ID | 审查单元数 | 证据 PNG 数 |
|---|---|---|---|---|---|
| **Run 1 Hold** | 首次归档成功，静帧稳定 | **1** | replayfile_85ce3299... | **29** | 31 |
| **Run 1 Exit** | 主窗口优雅退出 | **1** | replayfile_85ce3299... | **29** | 31 |
| **Run 2 Hold** | 再次带同源回放启动，静帧稳定 | **1** | replayfile_85ce3299... | **29** | 31 |
| **Run 2 Exit** | 主窗口再次优雅退出 | **1** | replayfile_85ce3299... | **29** | 31 |

- **去重序列**：[1, 1, 1, 1]，同文件重入完全去重，记录 ID 严格保持 `replayfile_85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6`。
- **不同对局共用 origsha 隔离断言**：通过 `CanonicalHistoryStore` 真实多对局共用同一 blob 插入断言，3 条记录（2 场 live，1 场 replay）严格保持隔离不合并。
- **数据源追踪与准入拦截**：
  - `dataOrigin` 严格透传为 `"replay"`；
  - `history.admitted = True`（允许历史查看复核）；
  - `formally_eligible = False`（严格拦截正式模型评估）；
  - `primaryReason = DATA_ORIGIN_NOT_LIVE`。

---

## 4. 隔离与红线核对

1. **日常历史保护**：%LOCALAPPDATA%\异环拍卖助手 与 %LOCALAPPDATA%\异环拍卖助手试用 完全未被写入或修改。
2. **基线包保护**：df58589、447f28b、a10f167、3c270c8、990f53f、84e0207 及日常 v13 均严格完整保留，未被覆盖。
3. **真值文件保护**：`assets/items/video_ground_truth_reference_144037.json` 保持只读未改。
4. **无越权修改**：未修改求解器核心参数、catalog_065 估值逻辑与图像匹配阈值。
