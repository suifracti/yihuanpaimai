# 拍卖界面直接读取

使用已验证的 UE4SS `3.0.1-1181-g83330635`（commit `8333063595fa3c49ad307f3b0f732accbb760d25`）。Lua 在游戏线程读取当前拍卖/结算 UI；当前回合、情报全文、四席姓名、账单及结算列表线索写到项目 `build/ue4ss/auction.json`。报价继续使用原识别。这是临时观察通道，不是另一套历史库。

2026-10-23 实机已把当前回合读入 Engine；箱子富文本和结算账单取得真实值。该场自然结束后，用保存的同场图像/字段回放，已通过 VisionPipeline → Engine → Main 结算摘要和原历史 writer：成交价 666,888、实际价值 1,001,417、账面收益 334,529，箱子 `box-shanhu-wood`。这次没有金均/紫数仪器结果；四席报价缓存不是可见报价，Lua 暂不输出报价，继续复用原报价识别。情报返回数组的包装和隐藏祖先控件已修正，修后尚未再进游戏验证。

现有 VisionPipeline 自动读取有效的当前观察，复用 `route_card_text`、业务闭集、CurrentMatch、Native Engine 和 Main/HUD。未取得的字段仍走原识别；空值不覆盖事实。原始 Params 与格式化文本分开保存到同局 `auctionEvidence.ue4ss`。结算列表仅保存线索，不设置覆盖 COMPLETE。

准备（离线，不安装、不启动）：

```powershell
build/takeover_20260905/repro-venv/Scripts/python.exe tools/ue4ss/prepare.py
```

2026-10-23 最新安排：用户已授权与 M6 连续十局一同运行。按字段接管：已实测的回合、箱子、账单使用直读；金均、紫数、四席报价在同屏核对前使用原识别，原始直读只作对照。缺字段不阻断流程，仓库仍截图识别，不另建循环。安装和撤载仍在游戏退出后进行：

```powershell
$game = 'D:\Games\Neverness To Everness\Client\WindowsNoEditor\HT\Binaries\Win64'
tools/ue4ss/session.ps1 -Action Check -GameDir $game
tools/ue4ss/session.ps1 -Action Install -GameDir $game
```

已有 `dwmapi.dll` 或 `ue4ss/` 就停止，不覆盖原文件，不同时加载 Anomaly。原启动器正常启动；当前已授权由现有 M6 流程入场、补金均/紫数至各1、出价（资金下限100000）和连续十局。探针不发输入、不购买/使用仪器、不报价、不进入下一局。普通 Lua 读取修正可以在这次运行内更新 `reader.lua`；原生加载器和 hooks 不换装。

助手照原有入口运行，自动拍卖由已有开始/停止动作控制；原截图、账单图和收仓继续使用既有流程。`NTE_UE4SS_SNAPSHOT` 可指定隔离现场的观察文件；默认位置为 `build/ue4ss/auction.json`。移除载荷或通道失效后自动回到识别，没有值清空操作。

结束时先保存 `build/ue4ss/runtime-*.log` 和游戏 `ue4ss/UE4SS.log`，正常退出。按安装身份只撤本次新增载荷：

```powershell
tools/ue4ss/session.ps1 -Action Remove -GameDir $game
tools/ue4ss/session.ps1 -Action Check -GameDir $game
```

原有模组、M6/个人历史与旧研究证据保持原样。不得以“脚本加载”替代实际属性读取，也不得以离线样本宣称游戏字段已通过。

现场证据在 `build/ue4ss/field-20261023T082709Z/`，包含原始阶段日志、结算原图、真实字段、修前失败、修后回放及撤载检查。原有 13 个加载文件/插件哈希不变，游戏/助手/Host 已退出，本次 `dwmapi.dll` 和 `ue4ss/` 已撤下。结算 `SettleSlots` 在揭示过程中从 18 变到 0，只保留动画列表线索，不充当完整藏品清单。
