# 结算白框：相对ff67的独立修复

2026-10-03。独立分支 `codex/offline-white-frame`，目录 `D:/yihuanpaimai/build/worktrees/offline-white-frame`，Git起点7e98c93，实际算法基线为第二轮冻结版 **ff67a1224533f3c27c2cfeddb2494474c3a690ec43d0ac943f40a7ef80bf35c4**，最终 **eef9968acfb2a5664b7a35acf44778e0788d586eaeaa1a8f4bb20becff5de89c**。不能取相对HEAD的整包差异；未覆盖主目录，未提交、发布、合并或归档。

## 原图与根因

唯一真实来源是主线程提供、用户确认的结算仓库场景：`build/warehouse-recognition-20261002/bounded-wgc-qa/live-f357c8c232/candidate-01.bmp`，SHA256 `54006174ca61acdffadc5bb6550ef8dcb3fa79de5d391b713a75b1781f011a4e`，1920×1080。离线ROI XYXY `[1315,211,1878,775]`。算法线程没有采集WGC、操作游戏或验证生产采集控制器资格。相邻接受帧属同一场景，没有把它们算作独立样本。

用户确认、原图外框支持左白框1×2和右上独立白框1×1。三个格均被分类为white，高光吸收未改色；周期/相位均正常：56×56，origin `[1318,214]`。失败发生在完整框/邻接回退，不是周期估计。

ff67完整框路径只支持五种饱和品质色，漏掉白色；白色共享边框强度也返回0/0。真实两件竖缝在格线左侧，灰度约29–30，两侧约176。格线x1654的旧5px带线均值是 `[30,29.5,176,170,164]`，中位164，未判成暗缝。左物上下交界没有暗谷，也未被暗缝误拆。于是从左上白格开始，2×1与1×2都可扩张、面积和fill同分，既有向右优先选择上排2×1；seen占格后留下左下1×1。不是两个独立失败门槛同时失效。

原图白色HSV轮廓是两个独立闭框 `[1598,496,52,109]` 和 `[1654,496,53,53]`，矩形度0.965/0.948，四边覆盖均1.0，亮度差最低25.67，对齐误差4/3px，满足现有门槛。只把目视真实竖边提供给ff67已有分隔输入，回退便从2×1变为1×2，这是诊断性输入探针，不当成修后通过。原始诊断与探针保持原含义：[trace.json](D:/yihuanpaimai/build/offline-white-frame-20261003/diagnosis-01/trace.json)、[white-contour-gates-and-causal-probe.json](D:/yihuanpaimai/build/offline-white-frame-20261003/diagnosis-01/white-contour-gates-and-causal-probe.json)。

## 最小修复与定向证据

只在完整框和其整条窄谷/对贴边支持中增加white分支，复用已有 **S≤40、V≥160** 白色谓词。其他品质的像素条件保留，完整框面积/矩形度、85%边覆盖、12亮度差、网格对齐和裁切完整性门槛不变。窄谷宽度/整条支持要求不变，已确认分隔仍传给回退。周期、宽高回退优先级和身份代码未改；没有硬编码目标尺寸或赋予目录名称。

| 目标 | ff67修前输出框XYWH | eef9968修后输出框XYWH |
|---|---|---|
| 左白色窄完整框 | `[1598,494,112,56]`误含右件，左下另出`[1598,550,56,56]` | `[1598,494,56,112]`，1×2 |
| 右上独立白框 | 被上排2×1吞并 | `[1654,494,56,56]`，1×1 |

同源整帧机器结果比较仅这两个观察框发生替换；其他30个观察框的box/rarity/size不变，网格逐字段不变。32是观察组件数，不是物品数量。目标及全图identifiedName/ID均未确认，无EXACT；只有一次离线观测，不作四帧身份通过结论。候选列表不是身份真值。

3项针对性测试通过：该真实图；合成单白框暗底；合成相邻白框触光。后两项均检查横/纵及原/半尺寸，单件不拆、邻件不并。绘图边界是独立的预设契约，未用实现生成期望值；合成不能算真实跨局验证。没有重跑旧矩阵。

[修前原始结果](D:/yihuanpaimai/build/warehouse-recognition-20261002/bounded-wgc-qa/live-f357c8c232/offline-recognition-01/result.json)、[修后结果](D:/yihuanpaimai/build/offline-white-frame-20261003/after-repair-01/result.json)、[逐框差异](D:/yihuanpaimai/build/offline-white-frame-20261003/before-after-comparison.json)、[测试日志](D:/yihuanpaimai/build/offline-white-frame-20261003/white-frame-tests.log)。源路径、哈希、裁剪、预期与实际均保留；原图未修改。

![白框修后：左1×2、右上1×1](D:/yihuanpaimai/build/offline-white-frame-20261003/after-repair-01/viewport-overlay.png)

## 范围与待整合

此场景已用于诊断和修复，独立未见图余量为0；不宣称跨局泛化、整套仓库、自动滚动、生产协议或完整拍卖通过。同图仍有原有unknown 2×2框 `[1430,606,112,112]`，未凭图标猜身份或新增占格真值；其余框没有逐件裁定，不能把“结果不变”写成准确率通过。六品质块的身份、数量、真实占格未知政策及DIRECT/0.85/0.08/四真实帧门槛不变；该旧六块场景本轮未重跑。

资料固定使用与ff67工作目录相同的正式版本，运行记录给出catalog/manifest/registry及ROI文件哈希；没有候选覆盖、资料/标签/正式历史修改。新增白色分支使灰色边框开始进入已有完整框检查，仍可能遇到未知遮挡/裁切或物品内部亮边，未以这张图宣称此类情况都解决。

[增量补丁](D:/yihuanpaimai/build/offline-white-frame-20261003/warehouse-white-frame-incremental.patch)仅含相对ff67的算法两处修改。新增测试、原图board夹具及来源说明、离线工具、本文的精确路径/哈希见 [integration-delta.json](D:/yihuanpaimai/build/offline-white-frame-20261003/integration-delta.json)。旧交付保持冻结，本轮交付哈希见 [delivery-freeze.json](D:/yihuanpaimai/build/offline-white-frame-20261003/delivery-freeze.json)。主任务核对后整合，本对话不应用。

复现仅需该图，输出另选不存在的项目build子目录：

```powershell
& D:/yihuanpaimai/build/takeover_20260905/repro-venv/Scripts/python.exe D:/yihuanpaimai/build/worktrees/offline-white-frame/tools/diagnose_white_frame_regression.py --source-root D:/yihuanpaimai --output D:/yihuanpaimai/build/offline-white-frame-20261003/repro-new
# 在新worktree内运行相关行为用例：
& D:/yihuanpaimai/build/takeover_20260905/repro-venv/Scripts/python.exe -m unittest tests.test_warehouse_white_frames_v1
```
