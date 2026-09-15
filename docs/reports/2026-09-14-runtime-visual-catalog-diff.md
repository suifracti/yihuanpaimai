# 运行时视觉图鉴差异审计（2026-09-14）

对照对象：AuctionPilot v0.12.7 `Assets/CatalogFull/catalog.json`（220 项）。
我方源码：`D:\yihuanpaimai` HEAD `84e0207`。
我方冻结包：`build/isolated_trial_ux_fixes_20260914_84e0207`。
本文件只做对照，不把对方 catalog 当权威，不复制对方图片或 DLL。

## 先前线索核实

先前口头数字「对方 220 / 我方 catalog_065 200 / 少 20 / 约 19 条属性分歧」**不能直接当成运行时缺口**。

| 线索 | 核实结果 |
|---|---|
| 对方 220 | 成立。对方 `catalog.json` 实读 220 项。 |
| catalog_065 200 | 成立。源码与 84e0207 包均为 200 项，SHA256 一致。 |
| 少 20 件运行时条目 | **不成立为整表缺 20。** 对方多出的 `catalog-gold-*` / `catalog-red-*` 多数已在 visual_catalog_v2 / 源卡注册表 / manifest v2 以 `visual-*` 或其他 ID 存在。几何主表 `catalog_065.json` 确实没有这 20 个对方 ID。 |
| 约 19 条 Shape/尺寸分歧 | catalog_065 与对方同 ID 属性差 19 条；其中名称不一致 3 条。同 ID 不等于同一藏品。 |

## 实际加载链

1. 生产视觉 worker：`app/main.py` → `KeyboardAuctionPipeline(catalog_path=assets/catalog_065.json)`。
2. 仓库几何/候选：`warehouse_vision.py` / `item_identity_resolver.py` / `shape_matcher.py` **只读 catalog_065.json**。
3. 结算身份模板：`settlement_item_recognizer.py` → `visual_catalog.load_visual_templates()`：
   - `assets/items/visual_catalog_v2.json` 中 `VISUALLY_CHECKED_SOURCE_CARD` 且哈希匹配的源卡；
   - `catalog_reference_manifest_v2.json`（若存在）否则 v1，状态 `RECOVERED_DETERMINISTIC` 且裁图哈希匹配。
4. 命名权威：`catalog_validator.py` 以 catalog_065 **加上** `verified_source_card_registry.json` 为正式名来源。
5. 求解器价格/尺寸：`core/solver_core_v06.js` 独立快照，不代替视觉主表。

`catalog_065.json` 是几何/候选主表，不是唯一层。视觉模板和源卡映射是另外两层。

### 各来源计数

| 来源 | 源码 | 84e0207 包 |
|---|---|---|
| catalog_065.json | 200 | 200 |
| catalog_reference_manifest_v2.json | 214（声明 214 / 接通 213 / 未决 1） | **未打包** |
| catalog_reference_manifest_v1.json | 200（声明 200 / 接通 134 / 未决 66） | 200 |
| visual_catalog_v2.json | 107 | 107 |
| verified_source_card_registry.json | 249（声明 249） | 249 |
| solver_core_v06.js 具名条目 | 225 | 随 JS 打包 |

加载器实跑：成功。
源码 `verified_references`=107，`deterministic_reference_crops`=213，模板键=None。
源码侧优先加载 manifest v2。

**包内缺口（已核实文件存在性，非游戏局）：** spec 只加入 `catalog_reference_manifest_v1.json`，84e0207 `_internal/assets/items/` 无 v2。因此冻结包的 `deterministic_reference_crops()` 走 v1（200 项、仅 134 接通），不是源码的 v2（214 项、213 接通）。这是源码/打包差异，不是竞品 20 项本身。

## 结论分布（对对方 220 项）

- 已由其他清单补齐，并非缺项：188
- 属性冲突，待源卡裁定：19
- 确实缺运行时条目：9
- 条目存在，但缺有效视觉参考：3
- 证据不足，暂不处理：1

## 最值得下一轮处理的缺口

1. **冻结包未包含 manifest v2**（源码有、包内缺）。影响结算模板裁图接通数，不改变 catalog_065 200 项几何主表。证据：`app/异环拍卖助手.spec` 第 105 行只打 v1；包内目录实列只有 v1。
2. **几何主表仍是 catalog_065 的 200 项。** 8.13 后金/红若只存在于 visual-* / registry，则 ShapeMatcher / ItemIdentityResolver / warehouse 候选索引看不见它们。这与“视觉模板是否存在”不是同一回事。
3. **同 ID 属性冲突必须用用户源卡裁定**，不能用对方 Shape 覆盖。

### 属性冲突（catalog_065 同 ID）

| 结论 | 我方ID | 我方名 | 对方ID | 对方名 | 匹配依据 | 源卡 |
|---|---|---|---|---|---|---|
| 属性冲突，待源卡裁定 | `image2-1-1` | 磨刀石 | `image2-1-1` | 锻刀石 | same_id_different_name | assets/items/catalog_screenshots/2X1/{48710325-8642-4753-AAFD-302E079D2B93}.png |
| 属性冲突，待源卡裁定 | `image5-0-0` | M1000模型 | `image5-0-0` | M1000模型 | same_id_and_normalized_name | assets/items/catalog_screenshots/4X4/{A56C0E29-265B-49E6-9060-91691585BA0A}.png |
| 属性冲突，待源卡裁定 | `image6-1-2` | 斑斓的一尾 | `image6-1-2` | 斑斓的一尾 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X1/{E065324C-AC60-41CF-B56A-8043A3B76C53}.png |
| 属性冲突，待源卡裁定 | `image7-0-2` | 千代家自酿生啤 | `image7-0-2` | 千代家自酿生啤 | same_id_and_normalized_name | assets/items/catalog_screenshots/1X2/{39EB6D1F-C312-4C1E-A622-BFADD00F264F}.png |
| 属性冲突，待源卡裁定 | `image7-1-2` | 梦中茧 | `image7-1-2` | 梦中茧 | same_id_and_normalized_name | assets/items/catalog_screenshots/1X2/{39EB6D1F-C312-4C1E-A622-BFADD00F264F}.png |
| 属性冲突，待源卡裁定 | `image11-0-2` | 鳞纹 | `image11-0-2` | 鳞纹 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X2/{DFB6F983-7A0D-41C6-AB47-6C150B5F7770}.png |
| 属性冲突，待源卡裁定 | `image11-1-2` | 觊觎钱币 | `image11-1-2` | 觊觎钱币 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X2/{DFB6F983-7A0D-41C6-AB47-6C150B5F7770}.png |
| 属性冲突，待源卡裁定 | `image15-0-2` | 扭扭饼干 | `image15-0-2` | 扭扭饼干 | same_id_and_normalized_name | assets/items/catalog_screenshots/1x1/{E4BB419A-6292-4A50-9CEB-D3351D50AF74}.png |
| 属性冲突，待源卡裁定 | `image15-1-0` | 拳王的战意 | `image15-1-0` | 拳王的战意 | same_id_and_normalized_name | assets/items/catalog_screenshots/1x1/{E4BB419A-6292-4A50-9CEB-D3351D50AF74}.png |
| 属性冲突，待源卡裁定 | `image15-1-2` | 无梦果核 | `image15-1-2` | 无梦果核 | same_id_and_normalized_name | assets/items/catalog_screenshots/1x1/{92DEEC27-CED4-4688-95EC-5A01A337AF9D}.png |
| 属性冲突，待源卡裁定 | `image26-1-1` | 条纹鲷 | `image26-1-1` | 条纹椰 | same_id_different_name | — |
| 属性冲突，待源卡裁定 | `image27-1-0` | 浅维祈手办 | `image27-1-0` | 浅绯祈手办 | same_id_different_name | assets/items/catalog_screenshots/3X3/{AF7A8555-2180-49BC-9395-F0DD5444F0EE}.png |
| 属性冲突，待源卡裁定 | `image32-1-0` | 落日珍珠 | `image32-1-0` | 落日珍珠 | same_id_and_normalized_name | assets/items/catalog_screenshots/1x1/{60C0E71A-D308-4533-9AD9-1ADF34119353}.png |
| 属性冲突，待源卡裁定 | `image34-0-0` | 一簇幽火 | `image34-0-0` | 一簇幽火 | same_id_and_normalized_name | assets/items/catalog_screenshots/3X3/{AF7A8555-2180-49BC-9395-F0DD5444F0EE}.png |
| 属性冲突，待源卡裁定 | `image34-0-1` | 九格小食 | `image34-0-1` | 九格小食 | same_id_and_normalized_name | assets/items/catalog_screenshots/3X3/{AF7A8555-2180-49BC-9395-F0DD5444F0EE}.png |
| 属性冲突，待源卡裁定 | `image34-1-1` | 细颈莲纹瓶 | `image34-1-1` | 细颈莲纹瓶 | same_id_and_normalized_name | assets/items/catalog_screenshots/1X3/{8443FC6A-7C86-4902-BAB8-454E077003BF}.png |
| 属性冲突，待源卡裁定 | `image34-1-2` | 莹碧翡翠 | `image34-1-2` | 莹碧翡翠 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X4/{52CC891D-443F-4464-A8D5-F6ECDA1A8AE2}.png |
| 属性冲突，待源卡裁定 | `image36-0-0` | 「摇星」 | `image36-0-0` | 「摇星」 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X2/{3D2983C4-2C10-49CB-8E12-4E20E57E0F4C}.png |
| 属性冲突，待源卡裁定 | `image36-0-1` | 酥酥酥天井 | `image36-0-1` | 酥酥酥天井 | same_id_and_normalized_name | assets/items/catalog_screenshots/2X1/{C3E32ADB-9348-4FE5-B70F-C7B9F66B659A}.png |

### 几何主表缺定义或确缺运行时条目

| 结论 | 我方ID | 我方名 | 对方ID | 对方名 | 匹配依据 | 源卡 |
|---|---|---|---|---|---|---|
| 确实缺运行时条目 | `—` | — | `catalog-red-chaojicunchupan` | 超级存储盘 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-red-yaomuquanbing` | 曜目权柄 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-red-tashanzhishi` | 他山之石 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-red-zhanxinpaiqiu` | 崭新限量排球 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-red-mingpei` | 鸣佩 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-gold-chiselaidian` | 赤色来电 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-gold-chengkongzhiyan` | 澄空之眼 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-gold-canjinhuan` | 灿金环 | normalized_name_against_solver_only | — |
| 确实缺运行时条目 | `—` | — | `catalog-gold-huangyouyaqi` | 黄釉雅器 | normalized_name_against_solver_only | — |

### 源码有、包内缺（按对方条目投影）

| 结论 | 我方ID | 我方名 | 对方ID | 对方名 | 匹配依据 | 源卡 |
|---|---|---|---|---|---|---|

### 有条目但缺有效视觉参考

| 结论 | 我方ID | 我方名 | 对方ID | 对方名 | 匹配依据 | 源卡 |
|---|---|---|---|---|---|---|
| 条目存在，但缺有效视觉参考 | `image8-1-2` | 毛毛球 | `image8-1-2` | 毛毛球 | same_id_and_normalized_name | — |
| 条目存在，但缺有效视觉参考 | `image19-1-0` | 青花碗 | `image19-1-0` | 青花碗 | same_id_and_normalized_name | — |
| 条目存在，但缺有效视觉参考 | `image28-1-2` | 万花筒 | `image28-1-2` | 万花筒 | same_id_and_normalized_name | — |

完整逐项表：
- `docs/reports/2026-09-14-runtime-visual-catalog-diff.json`
- `docs/reports/2026-09-14-runtime-visual-catalog-diff.csv`

本轮不替换运行时图鉴，不从对方目录拷图。
