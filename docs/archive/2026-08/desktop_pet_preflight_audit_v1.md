# Desktop Pet Preflight Audit v1

**审计日期：** 2026-08-21  
**审计基线：** `7122e4242bd57ea397f15c93a040fed02c1a3a7d`  
**范围：** 只读架构审计；未实现桌宠、未修改产品代码、未提交。  
**最终裁决：** `READY_FOR_MINIMAL_IMPLEMENTATION`

---

## 1. Executive Summary

### FACT

- 当前 EXE 已有一个明确的应用生命周期 owner：native `MainWindow`，由 `Application.Run(main_window)` 驱动。
- Main、Overlay 都在 `app/main.py::_gui_thread()` 创建，运行于同一个 .NET STA 线程、同一个 WinForms message loop。
- Overlay 是唯一 production Solver WebView runtime；它使用 `DirectCompositionHudForm` + `CoreWebView2CompositionController` 加载 `core/overlay_alpha.html`。
- Main 的 WebView2 仅为 presentation runtime，且与 Overlay 即使共享 `CoreWebView2Environment`，仍是独立 JS runtime。
- mascot 已有冻结的 RGBA PNG、校验 hash、manifest 与 state mapping；桌宠 v1 不需要生成新素材。
- `PresentationRuntimeSnapshot` 已是 native-owned、锁保护、只读标量快照，不含 `CurrentMatch`、Solver、OCR 或 raw transport object。
- 当前 automatic mascot selection 仍在 `core/mascot_runtime_binding.js` 内执行，Main JS 调用它；这是接入第二个 presentation consumer 时唯一需要收口的状态所有权缺口。

### RECOMMENDATION

采用 **C：native image / lightweight transparent window**，具体为：

- 同一个现有 GUI STA 上创建一个无边框 native WinForms HWND；
- 用 `WS_EX_LAYERED` + `UpdateLayeredWindow` 显示 premultiplied 32-bit ARGB PNG；
- 不创建 WebView2、不创建 JS runtime、不创建额外线程或 message loop；
- 由一个 native presentation-state coordinator 唯一计算 mascot state，Main 与 Pet 消费同一不可变结果；
- Pet 只拥有显示、命中、拖拽和位置持久化，不拥有任何业务状态。

标准 `TransparencyKey` WinForms 方案无法可靠保留软 alpha/glow；transparent WebView2 能实现视觉，但会为静态 PNG 引入第三套 Web runtime、异步生命周期和更高资源成本，均不适合作为 v1。

---

## 2. 当前应用架构事实

## 2.1 Process / thread / window lifecycle

### FACT

真实调用链如下：

```text
app/main.py::main()
  ├─ daemon icon thread: apply_runtime_icon
  ├─ daemon websocket thread: start_ws_loop
  └─ app/main.py::run_hud_app()
       └─ System.Threading.Thread(STA)::_gui_thread()
            ├─ create MainWindow once
            ├─ create DirectCompositionHudForm once
            ├─ Overlay.Show()
            ├─ create one CoreWebView2Environment
            ├─ initialize Overlay composition WebView
            ├─ initialize Main windowed WebView
            └─ Application.Run(main_window)
                 └─ Main close -> idempotent ShutdownCoordinator
                      └─ message loop returns -> STA joins -> process exits
```

- `app/main.py` 在启动时调用 `SetProcessDpiAwareness(2)`。
- `_gui_thread()` 是当前全部 WinForms HWND 的正确创建线程。
- `Application.Run(main_window)` 只有一个 message loop；Main 是逻辑 application lifetime owner。
- Overlay 的 native owner/game attachment 由 `DirectCompositionHudForm.SetGameOwner()` 维护，仅属于 Overlay 行为。
- Overlay 的 `FormClosing` 在非 shutdown 时被取消并重定向为 `Hide()`；不会退出 App，也不会重建 Overlay。
- `OverlayVisibilityController` 保存唯一 Overlay object，并以 `Show()/Hide()` 操作同一个实例。

### INFERENCE

Desktop Pet 无需、也不应创建第二个 STA 或第二个 `Application.Run()`。它可以与 Main/Overlay 一样由现有 `_gui_thread()` 创建，由现有 WinForms message loop 驱动。这样可直接复用 UI thread affinity、shutdown coordinator 和 native event dispatch。

## 2.2 Overlay / DirectComposition boundary

### FACT

`app/DirectCompositionHost.cs::DirectCompositionHudForm` 当前负责：

- borderless/topmost Overlay Form；
- DirectComposition device/visual target；
- WebView2 composition controller；
- native mouse message 转发到 WebView2；
- Overlay drag；
- game HWND owner；
- topmost guard timer；
- `CloseCompositionResources()` 的幂等 controller/timer/resource 清理。

它不是通用透明图片宿主。其 mouse forwarding、WebView controller、game owner 和 Overlay topmost 策略均与桌宠需求无关。

### RECOMMENDATION

不要复用或扩展 `DirectCompositionHudForm` 来承载桌宠。桌宠用独立、轻量的 native Form/Win32 layered-window helper；Overlay host 保持不变。

## 2.3 当前 shutdown path

### FACT

`ShutdownCoordinator` 通过锁保证只执行一次。当前顺序为：

1. disable UI / stop new overlay commands / `MainWindow.begin_shutdown()`；
2. flush manual draft；
3. stop vision worker；
4. stop websocket bus；
5. close Main presentation resources；
6. close Overlay composition/resources/form；
7. 如请求者要求则 close Main；
8. `Application.Run(main_window)` 返回；
9. STA thread join 返回。

Overlay 的 `exit_app` 已路由到该 coordinator，不是正常路径上的 `os._exit(0)`。

### RECOMMENDATION

桌宠必须成为 coordinator 的显式 cleanup step，不能依赖进程退出回收 GDI/bitmap/handler。详见第 8 节。

---

## 3. Mascot / runtime ownership 审计

## 3.1 已有 visual and state SOT

### FACT

`design/mascot/mascot_final_asset_manifest_v1.json` 是冻结资产清单，包含文件路径、SHA-256、尺寸和 visual authority；`design/mascot/mascot_state_asset_map_v1.json` 定义：

| State | Approved asset |
|---|---|
| `idle` | `mascot.chibi.idle` |
| `thinking` | `mascot.chibi.thinking` |
| `loading` | `mascot.chibi.loading.v2` |
| `success` | `mascot.chibi.success` |
| `warning` | `mascot.chibi.warning` |
| `sleep` | `mascot.chibi.sleep` |

当前 spec 只打包 approved manifest/map 与 approved PNG；retired loading 不在 runtime asset list。

`app/main_window.py::load_mascot_presentation_contract()` 会验证 schema/authority、每个 asset 的存在性与 SHA-256，并生成 presentation-only contract。

### RECOMMENDATION

Pet 直接消费这一份已验证 contract；不得另建 state map、复制路径常量或扫描 exports 目录。v1 只做 PNG state swap，不需要动画、Live2D 或新图片。

## 3.2 presentationRuntime boundary

### FACT

`app/presentation_runtime.py::PresentationRuntimeSnapshot` 是 frozen dataclass，只允许：

```json
{
  "snapshotVersion": 1,
  "visionProcessState": "running | stopped | exited | disabled",
  "refreshPending": false,
  "sceneClass": "auction | loading | lobby | navigation | unknown",
  "shadowUpdating": false
}
```

`PresentationRuntimeState`：

- 只复制 whitelist scalar；
- 不保留 raw payload mapping；
- 通过 lock 暴露 immutable snapshot；
- 对 refresh request 保留 correlation/stale protection；
- 不暴露 `LATEST_PAYLOAD`、`CurrentMatch`、Solver input/result、OCR text 或 auction facts。

## 3.3 当前 automatic mapping 的所有权缺口

### FACT

当前状态选择逻辑位于 `core/mascot_runtime_binding.js`：

```text
shutting_down           -> sleep
refreshPending          -> loading
sceneClass == loading   -> loading
shadowUpdating          -> thinking
otherwise               -> idle
```

Main JS 每 750ms 通过既有 `request_app_status/app_status` 获取 runtime snapshot，然后在自己的 JS runtime 内调用该 selector。`success`/`warning` 只保留为 local/manual presentation。

### INFERENCE

如果 Desktop Pet 再实现一次 selector，即使输入相同，也会产生两份可漂移的 mapping；如果 Pet 依赖 Main WebView 回调，则 Main WebView 又会意外成为桌宠状态 authority。两者都不满足单一事实源。

### RECOMMENDATION — single presentation truth

下一刀建立一个 **native-owned `MascotPresentationStateCoordinator`**：

```text
PresentationRuntimeSnapshot + applicationState
             |
             v
native MascotPresentationStateCoordinator   (唯一 selector owner)
             |
             +--> immutable MascotPresentationSnapshot
                    { version, state, assetId }
                         |                 |
                         v                 v
                   Main app_status      Desktop Pet
```

规则：

- coordinator 只读 `PresentationRuntimeSnapshot` 与 app lifecycle scalar；
- state rule 必须与当前 `mascot_runtime_binding.js` 冻结规则逐例 parity；
- manifest/state map 在 native host 加载并验证一次；
- Main 通过既有 `app_status` 接收同一派生 state，JS 只负责换图，不再自行判断；
- Pet 直接在 GUI thread 消费同一 immutable snapshot；
- Pet 不接 WebSocket、不读取 Main WebView、不读取 Overlay WebView；
- `success`/`warning` 仍不自动触发，除非未来有独立可靠的只读信号；
- 不增加 `request_app_status` 之外的运行状态 action，仅可扩展既有 status payload。

`core/mascot_runtime_binding.js` 在迁移后应成为薄 consumer/兼容层或由 parity tests 保护的冻结规范，不应继续与 native coordinator 各自独立选状态。

---

## 4. Host 方案 A / B / C 比较

### 方案定义

- **A — WinForms layered / transparent window：** 常规 `Form` + `TransparencyKey`/PictureBox 或 WinForms 透明属性。
- **B — transparent WebView2 host：** 第三个 WebView2 controller，以 HTML/CSS 透明背景显示 PNG 并处理输入。
- **C — native image / lightweight transparent window：** 轻量 native Form/HWND，使用 `WS_EX_LAYERED + UpdateLayeredWindow` 呈现 per-pixel ARGB。

> 注：若 A 最终自行 P/Invoke `UpdateLayeredWindow`，技术上已经收敛为 C。本报告中的 A 特指常规 WinForms 透明绘制路径，C 特指显式 per-pixel native layered composition。

| 维度 | A. 常规 WinForms transparent | B. transparent WebView2 | C. native layered image |
|---|---|---|---|
| 透明背景可靠性 | `TransparencyKey` 是色键；边缘容易出现锯齿/色边 | CSS transparent 可用，但受 controller/background/初始化时序影响 | **高**；由 32-bit per-pixel alpha 直接控制 |
| PNG soft alpha / glow | **不足**；色键无法表达连续 alpha | 高 | **高**；需 premultiplied ARGB |
| 无边框 | 简单 | 简单 | 简单 |
| always-on-top | `TopMost` | host Form `TopMost` | `TopMost` / `HWND_TOPMOST` |
| 动态全窗 click-through | 可改 extended style，但色键命中仍粗糙 | 需 host/WebView hit-test 协调，较复杂 | 可切 `WS_EX_TRANSPARENT`；但建议 v1 defer |
| 透明像素命中 | 默认仍可能是矩形命中 | DOM/host 双层命中 | 可用 alpha-aware `WM_NCHITTEST` 返回 `HTTRANSPARENT` |
| 拖拽 | native mouse 简单 | JS -> bridge -> native 或 host mouse forwarding | native mouse/`WM_NCHITTEST`，简单稳定 |
| 单击/双击/右键 | WinForms events | JS events + WebMessage | native events / ContextMenuStrip |
| 多显示器 | 可做，需自行恢复/clamp | host 仍需 native 处理 | 可直接使用 `Screen.AllScreens` 与 virtual desktop coordinates |
| DPI scaling | WinForms 自动行为有限，需审慎 | WebView CSS scale 较方便；host DPI 仍需处理 | 需处理 `WM_DPICHANGED`/`DeviceDpi`，从原 PNG 重渲染 |
| 位置记忆 | native 可做 | native host 可做 | native 可做，最直接 |
| idle CPU | 低 | 较高；多一个 controller/renderer/event loop participation | **最低**；无动画时事件驱动，状态变化才重绘 |
| memory | 低 | **最高**；即使共享 Environment，仍有独立 WebView/runtime/controller | **最低**；一张 bitmap + native Form |
| Windows 10/11 | 高 | 取决于 WebView2 Runtime（当前已有） | 高；layered window API 成熟 |
| PyInstaller 风险 | 低 | 中；当前依赖已存在，但新增 transparent host/controller smoke 面扩大 | 低到中；无需新 runtime，但需验证 pythonnet/Win32 handle cleanup |
| shutdown / dispose | 简单 | controller async callback/Close 顺序复杂 | 简单但必须显式释放 HBITMAP/DC/GDI handle |
| 额外线程/message loop | 不需要 | 不需要新 loop，但新增独立 JS runtime | **不需要** |
| 对 Main/Overlay 影响 | 小；视觉质量不足 | 新增第三套 Web presentation，增加初始化与回归面 | **最小**；不触碰已有两个 WebView |
| 是否可能复制状态逻辑 | native 若设计不当仍可能 | **高风险**，很容易在 Pet JS 再实现 selector | 由 native coordinator 统一，可明确禁止 |
| v1 结论 | 淘汰 | 淘汰 | **推荐** |

## 4.1 淘汰 A 的理由

### RECOMMENDATION

不采用 `TransparencyKey` / 常规 transparent Form 作为最终渲染路径：冻结 mascot PNG 含软 alpha、发丝、链条和 glow，色键会牺牲这些已审定资产的边缘质量。若为解决它再引入 `UpdateLayeredWindow`，就应明确按方案 C 实现和测试。

## 4.2 淘汰 B 的理由

### RECOMMENDATION

v1 不采用 transparent WebView2：

- 会成为当前进程第三个独立 WebView/JS runtime；
- 共享 `CoreWebView2Environment` 只降低部分初始化/资源成本，不共享 JS state；
- 静态 PNG 切图不需要 DOM/CSS runtime；
- transparent controller、host hit-test、初始化/导航 callback 与 shutdown race 都扩大风险；
- 最容易出现第二份 mascot mapping/selector。

未来若冻结素材升级为复杂 timeline/HTML 动画，才重新评估 B；当前没有该需求。

## 4.3 推荐 C 的理由

### RECOMMENDATION

方案 C 与当前项目匹配度最高：

- 复用现有 pythonnet + WinForms STA；
- 只需一个 native HWND 和 GDI+/Win32 bitmap；
- 精确保留 frozen PNG 的 per-pixel alpha；
- 不引入 WebView、JS、Solver、Vision 或第二套业务 runtime；
- input、drag、context menu、position persistence 都是 native presentation concern；
- 可以作为 shutdown coordinator 的普通资源 owner 幂等释放。

---

## 5. Desktop Pet v1 最小功能边界

## 5.1 Included

### RECOMMENDATION

v1 只包含：

1. 独立无边框、透明、always-on-top native pet window；
2. 使用当前冻结的六个 chibi PNG；
3. 自动状态：`idle/loading/thinking/sleep-on-shutdown`，与 Main 同一 native snapshot；
4. `success/warning` 保留为现有 manual/local presentation 能力，不做自动业务绑定；
5. opaque/可见像素区域左键拖拽；
6. 多显示器安全的位置恢复和 clamp；
7. 基础鼠标行为；
8. Main 退出时幂等 clean shutdown。

## 5.2 Click-through

### RECOMMENDATION

- **全窗口动态 click-through：v1 不做。** 一旦开启，必须提供稳定的恢复入口、状态提示和跨显示器可发现性；这不是 vertical slice 的必要条件。
- **透明像素不拦截鼠标：v1 应做。** 根据当前显示 bitmap 的 alpha 命中；低于阈值的像素在 `WM_NCHITTEST` 返回 `HTTRANSPARENT`，避免透明矩形区域挡住桌面。
- 可见人物区域保持 interactive，便于拖拽和菜单。

这一区分避免把“正确的 alpha hit-test”与“整只桌宠完全 click-through 模式”混为一谈。

## 5.3 Mouse interaction model

### RECOMMENDATION

| Gesture | v1 behavior |
|---|---|
| 左键按下并移动 | 超过小阈值后拖拽；mouse-up 保存位置 |
| 单击 | 不触发业务；可仅作为选中/no-op，避免误操作 |
| 双击 | 激活/显示现有 MainWindow，同一实例，不创建窗口 |
| 右键 | native 菜单：`打开主窗口`、`隐藏桌宠`；不放 Solver/AI 命令 |
| Pet window close / Alt+F4 | 非 App shutdown 时转为 Hide，不退出应用 |

若提供 `隐藏桌宠`，Main 必须有一个很小的 presentation-only 显示/隐藏入口用于恢复；该入口只操作同一个 Pet HWND。不要为此引入 tray。

## 5.4 Explicitly excluded

### RECOMMENDATION

- tray/NotifyIcon：v1 不需要；Main 已是生命周期与恢复入口。
- animation：v1 不需要；当前 frozen PNG state swap 足够。
- chat、Live2D、语音、AI 对话、随机漫游、物理弹跳：全部不做。
- Solver、CurrentMatch、Vision/OCR 或 raw runtime subscription：全部不做。
- Overlay game owner、Overlay show/hide 与 Pet 状态绑定：全部不做。

---

## 6. Position persistence / multi-monitor / DPI model

## 6.1 Storage

### FACT

当前 `app/config.json` 没有 Desktop Pet state，且 packaged runtime 的安装目录不保证可写。

### RECOMMENDATION

使用独立的 presentation state 文件，而不是写回产品 config：

```text
%LOCALAPPDATA%/异环拍卖助手/desktop_pet_state_v1.json
```

最小 schema：

```json
{
  "schemaVersion": 1,
  "visible": true,
  "monitorDeviceName": "...",
  "x": 0,
  "y": 0,
  "savedDpi": 96
}
```

- 保存坐标使用 Windows virtual desktop 坐标，允许负值；
- 保存 monitor device name，恢复时优先相同 monitor；
- monitor 缺失或位置完全离屏时 clamp 到 primary work area；
- 默认位置为 primary work area 右下角，保留安全边距；
- mouse-up/显式 hide/shutdown 时 debounce + atomic temp/replace；不在 mouse-move 每帧写盘；
- 位置文件不含 mascot/业务状态，不成为 runtime authority。

## 6.2 DPI

### RECOMMENDATION

- 遵循当前进程 DPI awareness，不猜固定 100% 缩放；
- 监听 DPI/monitor change，在新 DPI 下从原始 PNG 重新采样；
- 不对已缩放 bitmap 连续二次缩放；
- `UpdateLayeredWindow` 的 bitmap extent、hit mask 与 Form bounds 必须来自同一次 scale calculation；
- 在 100%、125%、150%、200% 以及负坐标 secondary monitor 做 smoke。

---

## 7. Runtime update model

### RECOMMENDATION

Pet 不订阅 WebSocket，也不接收 live payload。最小、安全路径：

1. `_gui_thread()` 创建并持有 `MascotPresentationStateCoordinator`；
2. coordinator 每次只读 `get_presentation_runtime_snapshot()` 返回的 frozen snapshot；
3. 在 GUI thread 通过一个低频 WinForms timer（可与 750ms presentation cadence 对齐）pull；
4. 只有 derived state/assetId 变化时替换 bitmap；
5. Main 的 `app_status` 同时序列化该 coordinator 的 fresh JSON-safe payload；
6. Pet 直接消费 coordinator 的 immutable native snapshot，不经过 Main WebView；
7. shutdown 开始后停止 timer 和 publish，拒绝所有新的 show/hide/update command。

如果未来从 worker thread push，必须 `BeginInvoke` marshal 回现有 Main GUI STA；不得从 worker 直接操作 Pet HWND，也不得把 live mapping/object reference 传给 Pet。

### Forbidden boundary

Desktop Pet 及其 coordinator 禁止 import/读取：

- Solver / `auction_engine_v06.js` / `solver_core_v06.js`；
- `CurrentMatch`；
- `LATEST_PAYLOAD`；
- OCR/Vision raw results；
- bids / settlement / auction facts；
- `live_shadow.current_snapshot()`；
- Main/Overlay WebView 内部 JS object；
- mutable runtime dict/list reference。

---

## 8. Lifecycle / shutdown model

## 8.1 Creation

### RECOMMENDATION

- 在现有 `app/main.py::_gui_thread()` 内创建 Pet，和 Main/Overlay 同一 STA。
- 在 `Application.Run(main_window)` 之前创建并显示一次。
- 由 `DesktopPetController` 保存唯一 Form/HWND；`create()` 在实例已存在时 fail closed 或返回同一实例。
- Pet 不设置 game HWND owner；Main 是逻辑 lifetime owner，不强制成为 Pet native owner。
- Overlay hide/show 不改变 Pet 可见性或 mascot state。

## 8.2 Normal close behavior

### RECOMMENDATION

- Pet 用户关闭：`Cancel=True` + `Hide()`，应用继续运行。
- Overlay 用户关闭：继续沿用现有 Hide 行为。
- Main 用户关闭：唯一全 App shutdown trigger。
- 双击/菜单打开 Main：只 `Show/Activate` 现有 Main 实例。
- 任何 re-show：对同一 Pet HWND/Form 调 `Show()`，不重新 load assets/state。

## 8.3 Shutdown order

### RECOMMENDATION

将 Pet cleanup 明确插入现有 idempotent coordinator：

```text
1. begin_shutdown
   - stop new Main/Overlay/Pet commands
   - publish applicationState=shutting_down (可得到 sleep；不等待动画)
2. stop/dispose Pet state timer
3. detach Pet mouse/menu/FormClosing/DPI callbacks
4. atomically persist final Pet position/visibility
5. flush manual draft
6. stop vision worker
7. stop websocket bus
8. close/dispose Pet window and release bitmap/HBITMAP/DC/GDI handles
9. close Main presentation WebView
10. close Overlay composition/controller/form
11. close Main; Application.Run returns
```

第 8～10 步彼此不应存在 runtime ownership；若实际实现沿用现有 Main-before-Overlay 顺序也可，但 Pet 必须在 message loop 返回前显式关闭。任何 tick/callback 先检查 `_shutting_down/_disposed`，避免 disposed HWND race。

---

## 9. Packaging implications

### FACT

当前 PyInstaller spec 已包含：

- mascot manifest/state map；
- 六个 approved chibi PNG；
- pythonnet/.NET/WinForms 依赖；
- WebView2 和 Overlay host 依赖。

### RECOMMENDATION

- 方案 C 不需要新增图片或 WebView assets。
- 新 Python module 通常由 PyInstaller analysis 收集，但 frozen smoke 必须验证 import。
- 若实现完全位于 Python/pythonnet + Win32 interop，不修改 `DirectCompositionHost.cs/.dll`。
- 不把 LocalAppData 的 position file 打包；首次运行时按需创建。
- packaged smoke 需要检查 approved asset hash、Unicode path、layered style、GDI handle cleanup 和无残留进程。

---

## 10. Desktop Pet v1 Minimal Vertical Slice — 精确修改范围

> 以下是下一刀建议，不在本轮实施。

### New

1. `app/desktop_pet.py`
   - `DesktopPetForm` / `DesktopPetController`
   - layered-window renderer (`UpdateLayeredWindow`)
   - alpha-aware hit-test、drag、double-click、context menu
   - one-instance guard、visibility、idempotent dispose
   - position load/save/clamp

2. `app/mascot_presentation_state.py`
   - frozen `MascotPresentationSnapshot`
   - native single-owner selector，与当前 JS rule parity
   - approved state/asset lookup only

3. focused tests，例如：
   - `tests/test_desktop_pet.py`
   - `tests/test_mascot_presentation_state.py`
   - packaged desktop-pet smoke probe

### Modify minimally

1. `app/main.py`
   - 在现有 GUI STA 创建 exactly-one Pet；
   - manifest/state contract load once 并注入 Main/Pet；
   - 将 Pet controller 接入 shutdown coordinator；
   - 不修改 Overlay construction/Solver path。

2. `app/main_window.py`
   - 消费预验证的同一 mascot contract；
   - `app_status` 增加 native-derived `mascotState`，不增加业务字段；
   - 如提供隐藏 Pet，增加 presentation-only visibility routing，不暴露业务 API。

3. `core/main_window.js`
   - automatic mode 改为只消费 host-derived mascot state；
   - 不再自行根据 runtime 重算；
   - 保留现有 manual/local success/warning preview。

4. `core/mascot_runtime_binding.js`
   - 收口为 thin consumer/compatibility validation，或停止作为第二 selector owner；
   - 不新增第二套 rule。

5. `core/main_window.html`（仅在需要恢复 hidden Pet 时）
   - 增加一个最小显示/隐藏入口；不重构 Dashboard。

6. `app/异环拍卖助手.spec`
   - 原则上无需新增 asset；只在 PyInstaller 未自动收集新 module/smoke helper 时做最小修正。

### Explicit non-changes

- `app/DirectCompositionHost.cs`：不改。
- Overlay HTML/JS/Solver：不改。
- `app/presentation_runtime.py` 的 whitelist/transport reducer：不扩业务语义。
- mascot manifest/map/PNG：不改。
- Vision/OCR/History/MainViewStateProvider/Prediction Evaluation：不改。

---

## 11. Focused validation plan

## 11.1 Unit / contract tests

下一刀至少覆盖：

1. native selector 与当前 frozen JS cases 完全一致；
2. Main 与 Pet 获得同一 `{state, assetId}`；
3. unknown/invalid state fail closed 到 approved fallback `idle`；
4. asset 必须来自 manifest/map 且 SHA-256 匹配；
5. `success/warning` 不由 runtime 自动触发；
6. Overlay show/hide 不改变 Pet state；
7. Pet 模块不 import Solver/CurrentMatch/Vision/OCR/live shadow；
8. exactly-one Form/HWND，重复 create 不产生第二实例；
9. Hide/Show 后 object/HWND/bitmap runtime identity 不变；
10. transparent pixel 命中返回 pass-through，opaque pixel 可交互；
11. drag 结束保存位置；restore 支持负坐标并 clamp 离屏位置；
12. DPI 变化从 source PNG 重绘，bounds/hit mask 同步；
13. position write 使用 atomic replace，损坏文件安全回退默认值；
14. Pet close 仅隐藏；Main close cleanup 只执行一次；
15. timer/callback 在 Form dispose 前停止；GDI handles 被释放；
16. 现有 Main/Overlay lifecycle、manual Solver 与 clean shutdown tests 全部保持通过。

## 11.2 Source smoke（下一刀 completion gate；本轮未执行）

1. source app 启动后同时存在 Main、Overlay、Pet，只有一个 Pet HWND；
2. Pet 为 borderless/layered/topmost，taskbar 不出现独立按钮；
3. white/black/deep-blue desktop 背景观察 soft alpha、glow、细链无硬边；
4. drag、多显示器、100/125/150/200% DPI；
5. 双击激活原 Main；右键菜单不触碰业务；
6. Overlay hide/show 不影响 Pet；
7. 触发受控 presentation fixture 时 Pet 与 Main 同步切换；
8. Main close 后全部 HWND/timer/thread 正常退出，无残留进程。

## 11.3 Packaged smoke（下一刀 completion gate；本轮未执行）

1. fresh PyInstaller build 无缺失 module/asset；
2. frozen path 下 manifest/hash 验证通过；
3. Pet layered alpha、input、drag、position persistence 正常；
4. 重启恢复位置，断开 secondary monitor 后自动回到可见 work area；
5. Main/Overlay/Pet 同一 EXE 生命周期；
6. Overlay Solver owner/runtime identity 不变；
7. clean shutdown，无 WebView callback/GDI handle exception、无 lingering process。

---

## 12. 风险清单

| 风险 | 严重度 | 控制方式 |
|---|---:|---|
| Main JS 与 Pet 各算一次 mascot state | 高 | native coordinator 单一 selector；Main/Pet消费同一 snapshot |
| `UpdateLayeredWindow` 使用非 premultiplied bitmap 导致 halo | 高 | 明确 premultiplied ARGB pipeline + 三背景 smoke |
| 透明矩形区域挡住桌面输入 | 高 | alpha-aware `WM_NCHITTEST`；测试透明/opaque 像素 |
| 全窗 click-through 后无法恢复 | 中 | v1 defer；只做透明像素 pass-through |
| GDI/HBITMAP/DC 泄漏 | 高 | controller 单一资源 owner；每次 swap/close 显式释放；handle test |
| DPI change 后显示与 hit mask 不一致 | 中 | 同一 scale calculation 同时生成 bitmap/bounds/mask |
| secondary monitor 拔出后 Pet 离屏 | 中 | monitor ID + work-area clamp + primary fallback |
| position 文件写入安装目录失败 | 中 | LocalAppData + atomic replace |
| Pet topmost 策略干扰 Overlay/game | 中 | 不设 game owner；不复用 Overlay topmost timer/host |
| shutdown tick/callback 访问 disposed HWND | 高 | 先停 timer/handler，所有 callback 检查 shutdown/disposed |
| 重复创建 Pet | 高 | GUI-thread controller + one-instance guard + identity tests |
| WebView/JS runtime 意外增加 | 高 | 方案 C；测试 Pet 无 WebView2 controller/import |

---

## 13. Final Verdict

`READY_FOR_MINIMAL_IMPLEMENTATION`

没有缺失素材、缺失 runtime signal 或现有 lifecycle blocker。下一刀只需实现：

> **在现有 GUI STA 上创建 exactly-one native per-pixel layered Pet；由 native single-owner mascot presentation coordinator 将现有 immutable `presentationRuntime` + lifecycle 映射为同一 `{state, assetId}`，同时供 Main 与 Pet 消费；加入 alpha hit-test、drag、LocalAppData 位置持久化和 idempotent shutdown；不创建 WebView、不修改 Overlay/Solver，不做全窗 click-through、动画、托盘或新业务绑定。**

这是 `Desktop Pet v1 Minimal Vertical Slice` 的精确范围；不应在同一刀扩展聊天、AI、Live2D、自动 success/warning、Vision/OCR 或任何业务 authority。
