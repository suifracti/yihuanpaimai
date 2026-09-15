# 运行时视觉图鉴真实加载（2026-09-14）

前置检查使用 `C:\Users\Administrator\.astrbot_launcher\components\python\py310\python.exe` + `C:\Program Files\Python310\Lib\site-packages`（cv2 5.0.0）。不是默认 Python 3.14。

机器结果：`docs/reports/2026-09-14-runtime-visual-catalog-load-source.json`（源码树）。冻结包结果另见同目录 `*-package.json`。

## 选择的 manifest

源码树选择 **v2**：`assets/items/catalog_reference_manifest_v2.json` 存在，故 `visual_catalog.deterministic_reference_crops` 与 `WarehousePlacementResolver` 都走 v2。

`image2-1-1`（磨刀石）在 v1/v2 均为 `MISSING_UNRESOLVED`，未进入 recovered 集合，未跳过校验。

## 生产加载器

| 入口 | 结果 |
|---|---|
| `verified_references()` | 107，全部解码且 `validate_catalog_record` 通过 |
| `deterministic_reference_crops()` | 213，全部解码且校验通过 |
| `load_visual_templates()` | 427 键 = 107×(body+expanded) + 213 裁图 |
| `WarehousePlacementResolver` | 选中 v2，refCache 213 |

visual_catalog_v2 拒绝 0；v2 recovered 拒绝 0。

## v1 / v2 / 107 项关系

不要把 213−134=79 当成净增 79 种藏品。

| 集合 | 数量 | 含义 |
|---|---|---|
| v1 recovered 且解码校验通过 | 134 | 旧包实际可用裁图 |
| v2 recovered 且解码校验通过 | 213 | 源码实际可用裁图 |
| v2 − v1 | 79 = 65 个 `image*`（v1 未接通、v2 接通）+ 14 个 `visual-*` | 同一批已有源卡/裁图，不是 79 个新藏品 |
| v1 − v2 | 0 | v1 recovered 是 v2 的子集 |
| visual_catalog_v2 ∩ v2 | 107 | 107 项全部落在 v2 recovered 内 |
| visual − v2 | 0 | |
| v2 ∪ visual | 213 | 与 v2 recovered 相同 |

14 个 `visual-*`：`visual-04d191b44682`、`visual-0ca7ed25ad80`、`visual-0f696df33258`、`visual-37894825cf77`、`visual-4974ca9119b0`、`visual-4cc72b207cb6`、`visual-65250f2f6c5a`、`visual-922c073c366d`、`visual-9607b248bbf4`、`visual-bbc3262913a7`、`visual-dc9ba21be2ec`、`visual-latiao-1x2`、`visual-liuliwei-4x1`、`visual-xiaoheng-5x5`。

## 能否进入生产识别分支

- `settlement_item_recognizer`：`load_visual_templates()`，源码侧 427 模板键。
- `settlement_catalog_candidates`：合并 catalog_065 + verified_references + deterministic_reference_crops。
- `warehouse_placement_resolver`：有 v2 文件则用 v2 裁图做 SIFT 参考。
- `shape_matcher` / `item_identity_resolver`：**仍只读 catalog_065**。本轮不改该几何主表。因此 14 个仅存在于 visual-* 的 ID 能进结算模板，不能进 catalog_065 几何索引。

本轮未补那 9 个无名条目，未裁定 19 条 Shape 冲突。

## 冻结包 3c270c8

新目录（未覆盖 84e0207）：
`build/isolated_trial_ux_fixes_20260914_3c270c8/dist/异环拍卖助手/`

- profile=`isolated-trial-v1`，codeRevision=`3c270c8`，isDirty=false
- EXE SHA256 `6DCE290A047340813993003151CA4A2E3EAC2332AEE932CE74B5513829ECBD71`
- 包内存在 v2 JSON、v1 JSON、visual_catalog_v2、源卡注册表、reference_crops_v1、catalog_screenshots
- 对 `_internal` 跑同一生产加载器：选中 v2；visual 107/0；v2 213/0；rooted 模板键 427，与源码集合完全一致；路径未逃出包根
- 旧 84e0207 包仍在，且仍无 v2 文件

源码身份回归：`test_visual_catalog_identity` + `test_catalog_reference_manifest_v1` 共 39 项，0 fail。这是开发夹具回归，不是未见对局。

DATA_ROOT 本轮独立前后快照（不可复用上轮 1602 口头结论）：日常与试用目录文件数和 aggregateSha256 均未变。未启动 GUI，未写用户历史。
