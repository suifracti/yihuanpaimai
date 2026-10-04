# 局内右仓第二轮：稳健周期与完整框分隔修复交付

2026-10-03。用户已批准最小设计，第二轮已在独立分支实施并完成定向离线复核。上一轮交付补丁、工具、测试、报告和证据保持冻结；本轮没有修改主目录源码或正式资料，没有提交、合并或发布。独立未见图为0，结果仅为已知回归。

## 已实施增量与最终结果

最终算法SHA256：**ff67a1224533f3c27c2cfeddb2494474c3a690ec43d0ac943f40a7ef80bf35c4**。增量基线为第一轮冻结的4a73a396…，不能用相对Git HEAD的全部差异重复覆盖第一轮。

1. 在均值Sobel信号之外计算跨行/列中位数信号。仅两轴ACF都达到原0.18门槛、同周期，且至少3条重复格线的局部相位支持率达到85%时采用稳健信号；否则保留均值回退。周期和相位同时重算，无56、57、75或目标尺寸硬编码。
2. 完整外框内的分隔必须存在窄暗谷、两侧品质描边，以及沿整条分隔至少85%的亮度差和色支持。宽度按格距比例取；保留12亮度差、55饱和度/亮度、完整外框覆盖与对齐检查。平坦暗填色或不同短图案段不能拼成分隔。
3. 已证实的分隔边同时记录横纵方向，传给本帧格子扩张，避免外框拒绝合并后被回退重新合并。原 `_has_item_gutter` 与回退的其余条件保留；身份、时序与主程序接口未改。

| 已知输入/定向预期 | 第一轮修前 | 第二轮最终 | 结论范围 |
|---|---|---|---|
| f564项链外观完整2×2框 | 56×57，拆成2个1×2片段 | 56×56，框 `[1318,382,112,112]` | 恢复完整外框；相对目视框X仍偏右2px |
| 同图车外观完整4×4框 | 56×57，拆成12片 | 56×56，框 `[1430,438,224,224]` | 恢复完整外框；X仍偏右2px |
| 护甲原尺寸及同画面票据 | 56×56，3个观察组件 | 56×56，3个观察组件 | 蓝框3×3与金框1×2均保持 |
| 同图半尺寸派生 | 28×28，3个观察组件 | 28×28，3个观察组件 | 非独立局样本 |
| 同图右裁派生 | 56×56，9列10行，3组件 | 同左 | 没有再次漂到52px；非独立局样本 |
| 结算75px两个相邻紫框 | 75×75，选定两框各1×1 | 同左，仍分离 | 整图35组件仅作raw；全图真值不完整 |
| 六个无图标品质块 | 75×75，身份未确认 | 同左，6个identifiedName/ID均null，EXACT为0 | 身份、数量、底下真实占格未知；不是6件物品 |

最终6个定向输入的预期几何检查均无issues。它们来自4个既有来源组，其中半尺寸和右裁是同源派生，不是6局。4个测试方法覆盖已知目标，以及合成单框暗底、相邻双框、四框双向边界，合成横/纵及原/半尺寸均符合作者独立绘制的边界契约；不能算真实跨局验证。真实结算对照证明所选邻件没有吞并，不能扩大为所有相邻物品都不会误合并。

raw含源图路径/哈希、裁剪框、目视预期、实际框和问题列表：[最终results.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/final-delivery-regressions/results.json)；[修前修后对比](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/before-after-comparison.json)；[4项测试日志](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/final-separator-tests.log)。对比分别保留分件与定位，不用组件减少作为成功判据。

![第一轮同图仍拆件](D:/yihuanpaimai/build/offline-right-warehouse-20261003/reserved-repeat-final/reserved-different-match-icons-overlay.png)

![第二轮完整目标框，外围品质块仍未知](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/final-delivery-regressions/reserved-different-match-icons-overlay.png)

开发过程中曾发现半尺寸真实窄缝被回退重新合并，已由分隔边传递修复；随后发现票据内部不同短图案段被误拼成横分隔，已由整条分隔一致支持修复。相关失败raw保留，最终版本已复核这些行为；没有删除失败断言或改变目视预期。早期合成绘图的描边覆盖了原设定黑缝，已修正绘图顺序，原失败日志也保留。

剩余限制：f564输出网格相位X导致目标框偏右2px，尚未达到像素精确定位；结算35组件未逐件裁定，其他潜在分件/合并不能判全通过；没有身份或堆叠数量真值，不作身份/数量准确率。六品质块的API仍输出观察块形状/候选范围，不能解释为已证实的真实占格、数量或身份。旧b94ea126…的四真实帧未知身份记录保留作历史参考；本次没有重验四帧时序。身份代码与DIRECT/0.85/0.08/四真实帧门槛未修改，最终单次离线识别没有赋名。大厅入口隔离沿用第一轮离线证据，本轮未改该路径，不推断正式门禁或实时采集通过。

## 待主任务核对的独立增量

[算法增量补丁](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/warehouse-vision-round2-incremental.patch)仅含相对冻结第一轮的 `core/warehouse_vision.py` 修改；新增行为用例、PNG夹具及来源说明、本文按 [integration-delta.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/integration-delta.json) 中路径/哈希取用。两份前期纯几何诊断工具列为可选历史材料，默认拒绝非4a基线，不是最终算法运行入口。资料、ROI、身份标签和正式历史不在增量中。

原始诊断凭据 [diagnosis-baseline.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/diagnosis-baseline.json) 保留实施前含义，不更新成修后哈希；最终交付状态另见 [delivery-freeze.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/delivery-freeze.json)。主任务核对并整合后才成立整合结论，本对话没有应用补丁。

以下保留实施前诊断及批准的设计依据。

## 本轮基线与目录隔离

独立目录 `D:/yihuanpaimai/build/worktrees/offline-right-warehouse-round2`，分支 `codex/offline-right-warehouse-round2`，Git起点 `7e98c93`。继承上一轮冻结算法，SHA256 **4a73a396dc9e07b9f78e1d20863ba6a9d352200e1ec65b26f6e291f9e5bc5014**；相对HEAD的core差异是继承旧补丁，不是第二轮修复。

资料固定使用旧worktree的整合前版本：

| 文件 | SHA256 |
|---|---|
| assets/catalog_065.json | 16f826c9e32135ff01b33eb60973ce173b24b48f4b921db44255bbf2f926a1da |
| assets/items/catalog_reference_manifest_v2.json | f5844e5e6c3277a8187c5d228eeead50df36f025a5c6fab11fbe385c658f79e5 |
| assets/items/visual_catalog_v2.json | e98327c86b77d0c9651ef9bd5d6d67aeffbe8a06aa5bd59c4d35b416586a1e87 |
| core/roi_scaler.py | 968d36463d318a44b182d8a1bafc97daed83f2ab8a1a172ad9eee3f0e935a925 |

已按 `integration/planned_changes.json` 逐字段核对34个候选几何字段，全部等于其before值。更直接的隔离是：诊断仅调用构造器之前的图像几何方法；没有构造matcher、加载目录或候选覆盖，没有运行身份、估值和时序确认。候选尺寸不可能参与本次几何结论。版本、字段核对及上一轮冻结凭据见 [diagnosis-baseline.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/diagnosis-baseline.json)。本结论不推定主目录正在整合的资料/ROI版本会产生同样输入。

已同步主对话：它已隔离资料并应用旧冻结增量；本对话独占独立第二轮算法修复，双方不同时改同一版本。实施前诊断不加载matcher；最终离线管线加载上表固定正式资料，未引入候选覆盖。

## 原图、复现与四类影响

已知回归原图：`build/native-observation/session-f564d0116a0646b083b8da4c45bc68cb/latest-business-frame.bmp`，1920×1080，编码文件SHA256 `bb3b81624f0853977982952b4ffee6f23210069a3173dd375251b7bb26e2c3ec`。沿用已核对的原图board裁剪XYXY `[1315,211,1878,816]`。项链外观框 `[1316,382,112,112]`、车外观框 `[1428,438,224,224]` 是可见物理外框预期，名称和ID均为null，不是目录尺寸推断。两张旧保留图都已用，只能算已知回归。

纯图像阶段复现冻结版 **56×57px、18组件**，与旧raw一致，证明该失败不需要候选目录参与。18不能作物品数。

| 阶段 | 可复现发现 | 影响与结论 |
|---|---|---|
| 外框提取 | 项链purple轮廓109×109、矩形度0.979；车red轮廓221×221、矩形度0.990。两者四边颜色覆盖均100%，向内亮度差最低仍大于47，远高于现有12门槛 | 没有丢掉这两个完整外框，不需要扩大框、降低描边/身份阈值 |
| 周期及相位 | X均值ACF选56（0.45365）；Y均值选57（0.46142），56仅0.41414。1/57≈1.75%未触发现有4%方格纠正。车框按57映射的底边比真实色轮廓多7px，超过5.6px对齐容差 | 周期偏差先挡住车的完整框，不能通过扩大容差掩盖；相位也须随可信周期重算 |
| 内部格缝 | 项链内部4条邻格边有2条darkGutter=true，组成贯穿竖分隔，但没有一对双方框强度达到0.78；车24条边有18条暗缝，双方强框也为0。现有完整框separator使用“暗缝 OR 双方框” | 项链被暗色底纹误拆；车校正周期后仍因暗纹贯穿横分隔被拒绝。暗色条带不等于两件之间的窄缝 |
| 相邻物品合并 | 本图未发现跨项链／车的合并，主要是分件。旧结算的两个真实紫色1×1轮廓独立；实际缝darkGutter=true，但双方框强度仅0.15/0.630，sharedEdgeInterior仍true | OR改AND会把这条真实分隔判成内部；该对照的轮廓仍独立，尚不证明它已发生误合并。不能全局关闭暗缝，需要观察窄暗谷及两侧边界形态 |

原图裁剪（不添加身份）：

![已知回归的完整品质框与内部暗纹](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/known-regression-trace/known-regression-board.png)

实际函数拒绝分支、行号、轮廓、occupancy及每条内部边见 [known-regression-trace/trace.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/known-regression-trace/trace.json)。

诊断性干预只改变传入的测量几何，不修改算法，也不作为修后通过：

| 图像阶段输入 | 组件数 | 完整框恢复 | 结论 |
|---|---:|---:|---|
| 冻结版56×57，originY=212 | 18 | 0 | 原失败复现 |
| 仅把Y周期设为实测X周期56，保留原相位 | 20 | 0 | 单独纠正周期不能解决分件，甚至改变碎片数 |
| 同步重算相位，56×56，originY=215 | 18 | 0 | 车过了外框对齐，却仍被内部暗缝拦截 |

## 周期与暗缝的独立证据

Y轴去掉board底部UI后仍选57（0.45569），故底部UI不是主要原因。只在诊断信号中排除两个已核对的物品区域，Y均值就选56（0.72571）；再去底部UI仍56（0.73745）。影响来自物品区域强边缘混入整行Sobel均值，不是目录、ROI重归一化或仅底部UI造成。

不依赖物品尺寸的跨列中位数聚合，X/Y都选56，ACF为0.71961/0.70271，相位Y=214，与可见空网格对齐。旧护甲均值/中位数都选56；旧相邻紫件结算控制都选75。这里只测信号支持，没有实现新网格估计器，不能称新算法验证通过。见 [period-contributions.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/period-contributions.json) 与 [adjacent-item-seam-and-signal-control.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/adjacent-item-seam-and-signal-control.json)。

同一件项链内部交界附近17px灰度中位数一直约40–43，只有暗底纹，没有局部窄谷。真实紫色邻接缝两侧约79/80，中间连续5px约25–26，具有明显窄谷及两侧恢复。两个独立紫框也各自形成轮廓，没有合成1×2；见 [adjacent-contour-trace.json](D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/adjacent-contour-trace.json)。这支持以局部边界形态区分暗填色和真实分隔，不能只判断“低于50”。

## 已获批准的最小修复设计（实施前记录）

1. **先修周期与相位**：在现有均值边缘ACF之外，增加跨行/列稳健聚合信号；仅当两轴共同支持同一周期、重复格线和相位残差也一致时，用该观测周期构造方格。信号不可靠时保留原有可靠测量或未知，不无条件跟随X，也不硬写56/57/75或假定裁图满10列。周期改变时同步重算两轴相位和可见完整行列数。保留现有ACF/谐波和身份门槛，不以多放容差隐藏漂移。
2. **再修完整框内的分隔证据**：保留现有完整轮廓、四边色覆盖、亮度差、网格对齐和裁切完整性检查。只在已通过这些检查的完整外框内，要求贯穿分隔具备相对两侧的窄暗谷、对贴边界及品质色连续支持；不能把一整片暗填色/斜纹当物品缝。检查带宽按实测格距比例取，避免单图像素位置。不能简单关闭 `_has_item_gutter`，也不能仅依赖现有 `_shared_edge_is_interior`。未证明完整外框时沿用保守fallback，不扩大合并范围。

不改身份、价格、目录或正式主程序接线；DIRECT、0.85、0.08、四真实帧保持。外框恢复只证明该可见轮廓，不按候选名赋身份。六个品质块的身份、数量及底下真实占格仍未知，组件数始终不作物品数。

预计实施修改点仅新worktree的 `core/warehouse_vision.py`，以及对应离线回归/夹具和本文；旧冻结版本不再修改。实施前只需与主对话对齐已整合基线版本，不能把第二轮相对HEAD的继承差异再次覆盖主目录。

最小验证：已知f564检查两完整框及周期/相位；旧护甲与裁切票据检查上一轮行为仍成立；真实同品质紫色邻接对照检查没有吞并。保留品质块未知边界，只检查本次可能受影响之处，不跑旧全矩阵或四次静图。结果仍须按分件与定位分别记录，不以组件总数变小判成功。

## 新验证图查找结果与缺口

已读取资料对话新交付的 [reference_index.json](D:/yihuanpaimai/build/item_reference_audit_20261003/adjudication/usage/reference_index.json)。该有界查找检查 `build/native-observation/` 的42个session、64个frame/state记录和22个来源组，目视20图，并核对 `data/reference-crops/`、`assets/items/`、`data/videos/` 的既有抽帧/卡图索引及相关 `build/codex_matching_20260912/`、9/30样本。没有重复宽泛查找、识别或解码录像。

本批没有找到可证明来自不同局、具有目标完整外框且能作为新未见验证的原图。seq256边界与f564 seq255仅隔0.437秒，属于同局近邻，排除；同图裁切/缩放也排除。两张不同外观的车辆/项链参考是结算，历史使用和上游独立性未知，只能作混淆对照。两张无state的首次局内图未揭示目标且来源关系未知，不能充当不同局完整物品验证。旧护甲来源已开发使用，也不能改称新图。

4条源卡参考可查外观与卡面文字，不能充当局内验证、正式名称或Cells/Shape真值；本轮不采用任何候选覆盖。具体缺口是有来源链和使用记录的不同局右仓清晰完整物品框。未新解码的录像范围尚有索引缺口，因此结论只限已查材料，不能说所有原录像没有新图。没有新图不阻碍上述诊断，但后续修复只能宣称已知回归改善，不能宣称跨局泛化通过。

## 最终复现入口

用第一轮已冻结的离线工具、明确指定算法目录。输出需选择不存在的 `build/` 子目录，避免覆盖证据；历史工具保留的reserved命名不代表本轮未见样本：

```powershell
& D:/yihuanpaimai/build/takeover_20260905/repro-venv/Scripts/python.exe D:/yihuanpaimai/build/worktrees/offline-right-warehouse/tools/diagnose_offline_right_warehouse.py --source-root D:/yihuanpaimai --algorithm-root D:/yihuanpaimai/build/worktrees/offline-right-warehouse-round2 --manifest D:/yihuanpaimai/build/offline-right-warehouse-20261003/sample-manifest.json --output D:/yihuanpaimai/build/offline-right-warehouse-round2-20261003/repro-final-new --case icons-cursor-1080 --case icons-cursor-derived-540 --case icons-right-clipped --case quality-only-1440 --case settlement-similar-icons-control --case reserved-different-match-icons --allow-reserved --diagnose-wrong-scene --evaluation-label known-regressions-zero-unseen
# 修前复现把algorithm-root改为build/worktrees/offline-right-warehouse；输出另选新目录。
# 合成及已知目标行为测试在第二轮worktree内运行：
& D:/yihuanpaimai/build/takeover_20260905/repro-venv/Scripts/python.exe -m unittest tests.test_warehouse_closed_frame_separators_v2
```

最终上述离线工具和4项测试均已实际运行。相关最小检查已回答本次周期、外框分件、相邻误合并及历史目标保持的问题，停止扩展验证。没有新未见图、WGC、桌面验收或完整拍卖通过结论。
