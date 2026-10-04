# 局内右侧仓库：离线修复、证据与待整合差异

2026-10-03。用户已批准优先修复完整外框被内部图案拆件。已在独立 worktree 实施：已知护甲原图由7槽恢复为3个物理框，半尺寸图由8槽恢复为3框；右裁视口由52px恢复56px，票据保持1×2。另一局项链和卡丁车仍分件，不能宣称完整识别通过。

工作目录 `D:/yihuanpaimai/build/worktrees/offline-right-warehouse`，分支 `codex/offline-right-warehouse`，Git起点 `7e98c93`。实际算法基线是主目录已有未提交版本 `0c7c7cac273647f6ae5d2af3a8e48e938fcad142fe19c9555c85525930834660`，最终算法 `4a73a396dc9e07b9f78e1d20863ba6a9d352200e1ec65b26f6e291f9e5bc5014`。未提交、合并或归档。

## 文件归属与材料

实施前已与正式后台识别对话协调：本对话唯一修改 `core/warehouse_vision.py` 及本轮新增离线测试；对方继续负责Host/WGC和接线，不改算法/测试/夹具。本次先在worktree继承其既有dirty基线，未用旧HEAD覆盖主目录。继承清单在 [inherited-baseline.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/inherited-baseline.json)。交付时确认主目录算法及所继承测试/夹具仍等于协调基线。

已读两级AGENTS、当前Handoff、9/30识别交接及截图索引、结算压力回归、10/2原帧门禁交接、现有真实夹具出处及相关源码差异。已查 `data/videos/`、`data/reference-crops/`、`assets/items/`、`assets/ocr_study_frames/`、`tests/fixtures/`、`docs/`、`build/warehouse-recognition-20260930/`、`build/warehouse-recognition-20261002/`、`build/warehouse_ui_chain_20260925/`、`build/native-observation/`。本轮使用已有图，没有重拍、WGC等待或后台采集。

已读参考核对的 `candidate_catalog.json`、`difference_list.csv`、`evidence_index.json`，并核对其 `right_warehouse_targets.json`、后续 `adjudication/armor_priority.json` 与交接。候选元数据、机器来源绑定和未裁定名称不作真值，没有修改生产目录。现有护甲源卡 `image11-1-1` 显示蓝3×3，支持几何核对；相同品质/尺寸的艺术画不能据此成为护甲身份。正式名称迁移、别名和其他尺寸裁定均不在本补丁内。

## 两个原因与实际改动

**分件原因**：已知蓝3×3内一个格被判空，另一个被银色图案判成白色，部分内部边被判gutter。旧扩张要求内部格同色且fill≥0.70，因而把内部图案当作独立件。

新增保守的完整彩色多格外框恢复：四边须有连续品质色描边和向内亮度差、与网格对齐、完整落在裁图内；贯穿矩形的分隔线仍阻止合并。先保留完整框的cells，后续扩张检查已保留cells，避免重复吞入。没有降低全局身份门槛或按最大外接框强合并。白色和1×1仍走原逻辑；边缘断裂、遮挡及不满足描边条件的物品不保证恢复。

**定位原因**：右裁后仍保留原图ROI起点，裁图505×605。X轴实测56px峰0.391815强于52px峰0.277977，但旧preferred按可见宽度/10接近50.5，覆盖了强峰；Y轴也受裁图高度偏置，随后方格约束把两轴压为52。这不是护甲分件造成的周期变化，也不是ROI起点被重归一化。尺寸先验现在仅打破等强证据的平局，不能覆盖更强观测峰。

取消偏置后，旧结算开发控制暴露另一个既有问题：X轴150px峰稍强于75px，谐波循环先命中弱71px就退出。已改为比较所有合格基频，按ACF强度择优、同分时比较整数倍误差，保留原谐波范围。该图75px的两轴峰分别0.447164/0.427513，明显强于71px的0.245374/0.263020；无需写死56或75。

离线工具按人工独立核对的场景索引，仅放行IN_AUCTION；大厅/结算默认在调用识别前拒绝。结算对照须显式诊断绕过。它不是自动场景检测器，也没有改变正式入口门禁。每张单图reset后只处理一次，不重复静图伪造时序确认。

DIRECT、0.85置信、0.08优势及四真实帧确认均保持。物理外框锁定不授权EXACT，未新增数量猜测或改变公开process_frame/slots接口。

## 修前修后证据

清单 [sample-manifest.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/sample-manifest.json) 共7个来源组、9个案例；半尺寸和右裁是同一原图的派生反例，不能增加独立样本数。相邻录屏帧仅作时序检查，不充当多组准确率样本。原图路径、来源哈希、裁剪框、预期、实际和叠框均可追溯。

| 样本与独立可见预期 | 修前 | 修后及证据范围 |
|---|---|---|
| Native 3419，第5回合1920×1080：金2×3、金1×2、蓝3×3 | 7槽，护甲拆5槽 | 3框，护甲保持3×3；原帧单次识别及最终真实夹具用例 |
| 同图半尺寸960×540，派生 | 8槽，护甲拆6槽 | 3框，28px周期；最终夹具用例通过 |
| 同图右裁100px，派生 | 52×52px、11行、13槽，票变2×2 | 56×56px、10行、3框，票保持56×112px/1×2；最终夹具用例通过 |
| 00-31-38@40.05s，2560×1440：6个品质色块，无图标 | 6个观测色块 | 最终仍6色块、75px，全部name为空、非EXACT；真实物品尺寸及数量未知 |
| 00-29-50@80s，局内未揭示 | 0槽 | 开发修后0槽；不推断真实空仓 |
| Native e9aec，拍卖大厅 | 无场景限制地直接调用引擎得27槽 | 离线入口SKIPPED_WRONG_SCENE、recognitionInvoked=false；未检验正式live门禁 |
| 00-33-00@20s，结算开发控制：所标两个紫色1×1相邻框 | 周期75px，全图输出34槽 | 最终75px，所标两框独立且定位符合；全图35组件未做完整真值评分，不能宣称全图通过 |

原帧护甲修前（绿色为独立预期，红色为实际）：

![护甲修前拆件](D:/yihuanpaimai/build/offline-right-warehouse-20261003/baseline-current/icons-cursor-1080-overlay.png)

开发修后外框：

![护甲修后完整外框](D:/yihuanpaimai/build/offline-right-warehouse-20261003/after-development/icons-cursor-1080-overlay.png)

图及批量raw的算法版本为首次冻结版 `b94ea126…`；最终版本对原图、半尺寸、裁切的真实夹具用例仍通过。初始自动比较误把护甲内部小碎片归为空格误检，已仅用原raw修正为定位/分件，未重跑造结果；修前最终归组见 [classification-review](D:/yihuanpaimai/build/offline-right-warehouse-20261003/classification-review/reviewed-error-groups.json)。

主要raw：[修前](D:/yihuanpaimai/build/offline-right-warehouse-20261003/baseline-current/results.json)、[开发修后](D:/yihuanpaimai/build/offline-right-warehouse-20261003/after-development/results.json)、[最终品质块](D:/yihuanpaimai/build/offline-right-warehouse-20261003/final-quality-period-check/results.json)、[最终结算局部控制](D:/yihuanpaimai/build/offline-right-warehouse-20261003/final-development-control/results.json)、[大厅离线隔离](D:/yihuanpaimai/build/offline-right-warehouse-20261003/scene-isolation-after/results.json)。

## 保留图与剩余错误

先固定开发修复版本，再首次运行两张保留图。首次冻结前漏先复核旧结算开发控制；随后发现并修复上述71px回归，保留全部中间失败，并在最终冻结后重复这两张图。调参依据是旧开发控制，不是保留图；但两张图已经运行，后续不能再称未见样本。未证明它们在全部历史工作中从未用于调参，也不据此宣称独立准确率。

| 原保留样本 | 首次结果 | 最终重复验证 |
|---|---|---|
| Native f564，不同match，第4回合：项链2×2、卡丁车4×4，另有品质块 | 18组件；项链拆2个1×2，车拆12组件；网格56×57px | 同样失败，未依据此图继续调参；18不是物品数 |
| Native 0726，第1回合未揭示 | 0槽 | 0槽；只能证明没有可见物品被误识别 |

首次冻结 [repair-freeze.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/repair-freeze.json)，首次结果 [reserved-first-validation](D:/yihuanpaimai/build/offline-right-warehouse-20261003/reserved-first-validation/results.json)；最终冻结 [final-repair-freeze.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/final-repair-freeze.json)，重复结果 [reserved-repeat-final](D:/yihuanpaimai/build/offline-right-warehouse-20261003/reserved-repeat-final/results.json)。

![不同局仍有分件和纵向定位偏差](D:/yihuanpaimai/build/offline-right-warehouse-20261003/reserved-repeat-final/reserved-different-match-icons-overlay.png)

错误按行为归组：

- 漏检：所标物理件主要被拆散，没有完全消失；未标全图/被遮挡物品不能评价召回。
- 误检：已隔离大厅的离线误用。未揭示样本输出0；不把内部碎片冒充空格误检。
- 定位/分件：已修护甲反例及裁切52px漂移；不同局项链/车仍分裂，纵向57px也仍偏离可见56px格距。结算全图大块宝石仍出现碎片，未承诺全图无回归。
- 物品混淆：所选局内图没有正式身份真值；仅有源卡形状对照不能确认名称。六色块无图标，全部保留未知，色块的1×1观测框不等于底下真实物品占格。
- 数量：接口未提供可验证stackCount，组件数与占格数均不能作堆叠数。所查目录没有已核实局内堆叠数字正例，数量UNKNOWN。

六色块另用已有2400–2403四张不同真实帧作一次时序检查，EXACT=0、named=0，证据 [quality-four-real-observations-after.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/quality-four-real-observations-after.json)。它们只有一个来源组，不计四个独立样本；算法版本记录在raw，最后周期修复后另单图确认6色块定位仍75px、无名称。

当前具体素材缺口：真实右仓图中已核实的堆叠角标、物品被鼠标/弹层遮挡的可信几何标签、独立局内名称确认。现有光标在暗格，不能验证遮挡物品；暗格不能区分空位和未揭示。滚动条只保留观测器原始结果，裁切图为UNKNOWN，不代表已验证滚动拼接。未请求重拍。

## 最小检查与待整合差异

新增一个真实fixture和两个行为用例：完整外框在原尺寸/半尺寸保持3件；右裁票据保持1×2/56px。最终两个用例通过，日志 [final-focused-checks.log](D:/yihuanpaimai/build/offline-right-warehouse-20261003/final-focused-checks.log)。相邻同品质gutter、已有多色2×1控制各通过一次受影响复核；末列/1440相位原检查通过，新恢复只处理多格框，未重复不受影响矩阵。中间失败日志保留：半尺寸边缘描边曾被过严裁边检查排除，裁切曾错误要求仅8列；修复后允许8个完整列及近完整第9列，不虚构第10列。

独立只读检查仅看算法增量，未发现可定位的新增阻塞缺陷，未重复测试。未跑全量、桌面、WGC、冻结包或完整拍卖验收。当前结果只证明上述离线范围。

待整合清单 [integration-delta.json](D:/yihuanpaimai/build/offline-right-warehouse-20261003/integration-delta.json)：

- 修改 `core/warehouse_vision.py`；增量 [warehouse-vision-incremental.patch](D:/yihuanpaimai/build/offline-right-warehouse-20261003/warehouse-vision-incremental.patch) 相对协调的dirty基线导出，主目录只读 `git apply --check` 通过，尚未应用。
- 新增 `tools/diagnose_offline_right_warehouse.py`、`tests/test_warehouse_complete_frame_v1.py`、`tests/fixtures/warehouse_complete_frame_v1/{armour-board.png,provenance.json}` 及本文。
- 继承的 `tests/test_warehouse_vision.py`、`tests/test_derived_warehouse_identity_boundary.py`、`warehouse_active_boundary_v1/` 没有本轮增量，整合时不能误算或覆盖。不能直接用相对HEAD的整包diff，因为其中含他方既有dirty修复。
- 主程序接线、Host/WGC、窗口资格、正式历史和人工标签没有本轮修改。生产目录与参考核对候选没有自动采纳。

后续具体动作：由用户控制整合上述增量；若继续改项链/车外框和两轴周期，应将已失败f564转为开发反例，另选不同来源验证图，不能复用它宣称未见通过。当前worktree和所有修前/修后证据保留，未自动提交、合并或归档。