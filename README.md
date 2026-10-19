# 异环拍卖助手

> 为《异环》拍卖玩法制作的**非官方 Windows 桌面助手**：把竞拍信息、仓库观察、藏品识别、估值参考和对局回看集中在一处。

**当前版本：** `v0.68-alpha`（以 [`core/version.py`](core/version.py) 为准） · **阶段状态：** 2026-10-19 收尾停在实机入场。离线估值和出价确认已进 `main`。**这不是正式发布版，也未完成全自动拍卖验收。**

## 🎴 看看界面

### [查看六页完整交互预览 →](docs/demo/全页面交互预览.html)

演示采用「**拍卖图录**」设计：米白、墨色和朱红的**日场**，深蓝绿与暖白的**夜场**；竞拍席、开箱查验、藏品册、落槌簿、估值复盘、偏好六页可切换。包含图鉴搜索/筛选、藏品档案、主题切换、图片查看及悬浮票等演示交互。

**如何体验：** 在 GitHub 查看上述文件后，建议下载或克隆**整个仓库**，用浏览器打开 `docs/demo/全页面交互预览.html`。页面图片引用本仓库的 `1.4更新/` 公开参考资源；**只单独下载 HTML 可能缺少部分图片**。仓库暂未启用 GitHub Pages，因此 GitHub 文件查看页不是在线运行的演示站点。

这是一份**经过脱敏的只读设计演示**：不连接游戏、不操作鼠标键盘、不写入真实历史、不发起竞价，也不等于当前 Windows 主程序的全部功能。完整版原始设计与工程交接材料保留在项目的私有附件目录中。

### Windows 实际截图

这些图片取自 **2026-10-16 的 Windows 主窗口/HUD UI 验收**。当时使用只读或隔离数据，并非游戏中的实时自动竞拍成果；藏品册的图片与价格属于图鉴参考资料。

| 竞拍席 · 日场 | 藏品册 · 夜场 |
| :---: | :---: |
| ![竞拍席日场：仓库视口、回合和竞价参考单](docs/images/demo-bidding-day.png) | ![藏品册夜场：物品索引、实物展示与目录价签](docs/images/demo-catalog-night.png) |
| **藏品册 · 日场** | **估值复盘 · 日场** |
| ![藏品册日场：真实图鉴加载完成](docs/images/demo-catalog-day.png) | ![估值复盘日场：目录价与建议出价的依据说明](docs/images/demo-analysis-day.png) |

**悬浮票 · 日场（收起）**

![独立悬浮票日场收起截图](docs/images/demo-hud-day.png)

完整页面和主题交互请使用上面的 [只读 HTML 演示](docs/demo/全页面交互预览.html)；演示数据、UI 截图与真实游戏识别结果应分别看待。

## 项目包含什么

| 页面 / 能力 | 用途 |
|---|---|
| **竞拍席** | 集中查看回合、情报、仓库视口、四席出价和有依据的竞价参考 |
| **开箱查验** | 保存结算原图、按件审阅藏品与候选，区分完整覆盖、身份确认和未知 |
| **藏品册** | 按名称、品质、类型、规格浏览参考资料与角色资料；目录价格不等于成交价 |
| **落槌簿** | 回看历史局次、原图、估值和结算，支持已有的导入、导出及记录管理 |
| **估值复盘** | 将目录参考价、整仓估值、建议出价与实际结果分开解释 |
| **偏好与悬浮票** | 日场 / 夜场 / 跟随系统、窗口与 HUD；HUD 为独立原生窗口 |

程序现有 Python 视觉/主界面、JavaScript 求解器、C# Native Host、原图及历史存储链路。正式 Windows 版已完成六页主窗口集成、日夜主题同步与若干交互验收；**浏览器演示的互动成功不代表游戏实机成功**。

## 当前状态与限制

- **已具备的基础**：指定窗口观察、图像/OCR 处理、结算原图保存、仓库滚动与部分覆盖分析、目录参考和具体藏品审阅、历史读写/回看、估值求解与界面/HUD。real-once-10 已写入同局剩余估值：43 件已确认，目录小计 935775，剩余范围 0–0。梦中萤记为缺素材，梦中茧记为 METADATA。
- **已有的实测边界**：2026-10-20 实机目录 `build/goal-20261019-b/match-5` 的仓库收齐是 `COMPLETE`（`finalizationReason` 为 `COMPLETE`，保存 36 页，滚动 6 次，`coveragePending` 为空）。观察因 `COLLECTION_COMPLETE` 停止，Host 进程退出已确认。match-1 到 match-4 仍是 `PARTIAL`，目录和原图保留。match-5 的结算记录没有 `remainingValuation`。回看读的是 real-once-10 已经写入的同局估值，没有重跑 896 秒识别。
- **尚未完成的目标**：实机「出价 → 结算收仓 → 返回 → 自动进入下一局」没有跑成。Live Host 收到 `domain.action.dispatch` 后不发送输入。没有已连接的游戏解码器时，出价回执是 `NOT_SENT` / `GAME_DECODER_NOT_CONNECTED`。返回和下一局因为种类不是 Bid，被 `DISPATCH_SCOPE_INVALID` 拒绝。生产代码里没有可用的 `IGameDomainFrameDecoder`。本轮不新做出价模块，也不另找点击坐标。离线「确认 → 发送 → 新画面回执」和「结果未知不重发」在 `8380dc08d6924d7d925c365ce4f906f6b5d1e2b9`。仓库空尾一格修复在 `70c6654703e93c51ae6142091f978a0b14b2201d`，直推 CI [39309944087](https://github.com/suifracti/yihuanpaimai/actions/runs/39309944087) 的两个离线 job 都成功。
- **关于费用与风险**：估值、目录价、报价建议、游戏实际付款和收益是不同数据；证据不足时应显示未知，不能推断保本或获利。

最终产品方向仍是 **进入拍卖 → 识别与估值 → 有界出价及游戏确认 → 结算收仓 → 归档 → 返回 / 下一局**。目前不能把这些目标当成已交付能力。

## 在 Windows 从源码运行

需要 **Windows x64、Python 3.10、WebView2 Runtime、.NET 8 SDK**；求解器相关工具还会用到 **Node.js**。克隆源码并准备桌面依赖（首次安装需联网）：

```powershell
git clone https://github.com/suifracti/yihuanpaimai.git
cd yihuanpaimai
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.lock.txt

if (!(Test-Path app/config.json)) {
    Copy-Item app/config.example.json app/config.json
}

dotnet build architecture/v2/host/wgc_live_harness/WgcLiveHarness.csproj -c Release -o build/native-observation
```

**仅浏览 UI（不启动识别、隔离测试数据）**：

```powershell
$env:NTE_DISABLE_VISION = '1'
$env:YIHUAN_DATA_ROOT = Join-Path (Get-Location) 'build\readme-ui-data'
.\app\run.bat
```

正常入口为 [`app/run.bat`](app/run.bat) / [`app/main.py`](app/main.py)。若启用实际窗口观察，需使用本机有效配置和与源码对应的 Native Host，并按当次许可操作；不要直接把 UI 预览当成运行程序。更多环境说明见 [桌面环境文档](docs/desktop-environment.md)。

## 数据、源码与后续维护

GitHub `main` 是源码主线；**个人配置、正式历史、游戏原图、运行日志和私有测试证据不随公开仓库提供**。本地 `app/config.json`、`data/videos/`、`data/reference-crops/` 及 `build/` 里需要保存的资料，请勿因为重新克隆而清理。隔离数据可通过 `YIHUAN_DATA_ROOT` 指定。

本项目的**最新实际进度与长期决定**记录在有权限的 Obsidian Vault：`03-项目与工程/异环拍卖助手/README.md` → `Handoff.md` → `Decisions.md`；此公开 README 只说明可供外部理解的项目现状。已关闭的 [Issue #19](https://github.com/suifracti/yihuanpaimai/issues/19) 只用于历史追溯，不是当前待办清单。

**2026-10-20 收尾：** A 的剩余估值在 `d1c2998082ac4c2ebdf0eb67c6486b0228b01da3`。B 的仓库收齐在 `build/goal-20261019-b/match-5`，代码是 `70c6654703e93c51ae6142091f978a0b14b2201d`，直推 CI [39309944087](https://github.com/suifracti/yihuanpaimai/actions/runs/39309944087) 成功。C 的离线确认在 `8380dc08d6924d7d925c365ce4f906f6b5d1e2b9`，直推 CI [39292177883](https://github.com/suifracti/yihuanpaimai/actions/runs/39292177883) 成功。实机出价闭环停在 Host 的 `GAME_DECODER_NOT_CONNECTED`：现有链路只记不发送，不能当成成交、返回或下一局。本段不写入自己的提交号；读回后的提交号在 Handoff 第 2 节。2026-10-16 的暂停已经结束。更早「停在大厅」的说明不是这次仓库结果。

*本项目非《异环》官方产品。游戏名称及参考图像相关权利归原权利人所有；演示素材不代表官方授权或实时游戏事实。*