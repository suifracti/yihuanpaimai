# 异环拍卖助手

> 为《异环》拍卖玩法制作的**非官方 Windows 桌面助手**：把竞拍信息、仓库观察、藏品识别、估值参考和对局回看集中在一处。

**当前版本：** `v0.68-alpha`（以 [`core/version.py`](core/version.py) 为准） · **阶段状态：** 2026-10-16 暂停继续开发，保留现有成果。**这不是正式发布版，也未完成全自动拍卖验收。**

## 🎴 看看界面

### [查看六页完整交互预览 →](docs/demo/全页面交互预览.html)

演示采用「**拍卖图录**」设计：米白、墨色和朱红的**日场**，深蓝绿与暖白的**夜场**；竞拍席、开箱查验、藏品册、落槌簿、估值复盘、偏好六页可切换。包含图鉴搜索/筛选、藏品档案、主题切换、图片查看及悬浮票等演示交互。

**如何体验：** 在 GitHub 查看上述文件后，建议下载或克隆**整个仓库**，用浏览器打开 `docs/demo/全页面交互预览.html`。页面图片引用本仓库的 `1.4更新/` 公开参考资源；**只单独下载 HTML 可能缺少部分图片**。仓库暂未启用 GitHub Pages，因此 GitHub 文件查看页不是在线运行的演示站点。

这是一份**经过脱敏的只读设计演示**：不连接游戏、不操作鼠标键盘、不写入真实历史、不发起竞价，也不等于当前 Windows 主程序的全部功能。完整版原始设计与工程交接材料保留在项目的私有附件目录中。

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

- **已具备的基础**：指定窗口观察、图像/OCR 处理、结算原图保存、仓库滚动与部分覆盖分析、目录参考和具体藏品审阅、历史读写/回看、估值求解与界面/HUD。
- **已有的实测边界**：曾实机收取多张独立原图并观察到底部，但原实机连续覆盖结果仍标为 `PARTIAL`；后续离线重建的 `COMPLETE` 不替代真实整场验收。已有局次的身份审阅成果不等于每局所有物品都能准确识别。
- **尚未完成的目标**：真实游戏自动报价及**本人接受确认**、完整结算闭环、自动返回与开启下一局，以及同一版本下的完整连续实机验收。
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

**2026-10-16 阶段性收尾：** 本次将 README 更新并将交互演示归档到仓库，之后暂不继续追加 UI 或业务改造；何时恢复开发由项目所有者决定。暂停不等于完成、发布或通过全自动实战验收。

*本项目非《异环》官方产品。游戏名称及参考图像相关权利归原权利人所有；演示素材不代表官方授权或实时游戏事实。*