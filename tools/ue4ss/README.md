# 拍卖界面直接读取

使用已验证的 UE4SS `3.0.1-1181-g83330635`（commit `8333063595fa3c49ad307f3b0f732accbb760d25`）。Lua 在游戏线程读取当前拍卖/结算 UI；当前回合、情报全文、四席可见报价、账单及结算列表线索写到项目 `build/ue4ss/auction.json`。这是临时观察通道，不是另一套历史库。

现有实机证据覆盖普通对象与回合原值0→1；这次扩展的卡片、四席、账单和生产接线尚待一次现场验证。离线接线检查不能替代该结果。

现有 VisionPipeline 自动读取有效的当前观察，复用 `route_card_text`、业务闭集、CurrentMatch、Native Engine 和 Main/HUD。未取得的字段仍走原识别；空值不覆盖事实。原始 Params 与格式化文本分开保存到同局 `auctionEvidence.ue4ss`。结算列表仅保存线索，不设置覆盖 COMPLETE。

准备（离线，不安装、不启动）：

```powershell
build/takeover_20260905/repro-venv/Scripts/python.exe tools/ue4ss/prepare.py
```

现场必须取得当轮进程内加载授权，M6/自动拍卖保持停止。游戏退出后：

```powershell
$game = 'D:\Games\Neverness To Everness\Client\WindowsNoEditor\HT\Binaries\Win64'
tools/ue4ss/session.ps1 -Action Check -GameDir $game
tools/ue4ss/session.ps1 -Action Install -GameDir $game
```

已有 `dwmapi.dll` 或 `ue4ss/` 就停止，不覆盖原文件，不同时加载 Anomaly。原启动器正常启动一次；用户本人手动入场、使情报出现并自然到结算。探针不发输入、不购买/使用仪器、不报价、不进入下一局。普通 Lua 读取修正可以在这次运行内更新 `reader.lua`；原生加载器和 hooks 不换装。

助手照原有入口运行，自动拍卖开关保持关闭；原截图、账单图和收仓继续使用既有流程。`NTE_UE4SS_SNAPSHOT` 可指定隔离现场的观察文件；默认位置为 `build/ue4ss/auction.json`。移除载荷或通道失效后自动回到识别，没有值清空操作。

结束时先保存 `build/ue4ss/runtime-*.log` 和游戏 `ue4ss/UE4SS.log`，正常退出。按安装身份只撤本次新增载荷：

```powershell
tools/ue4ss/session.ps1 -Action Remove -GameDir $game
tools/ue4ss/session.ps1 -Action Check -GameDir $game
```

原有模组、M6/个人历史与旧研究证据保持原样。不得以“脚本加载”替代实际属性读取，也不得以离线样本宣称游戏字段已通过。
