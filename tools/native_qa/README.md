# 独立窗口 WGC QA

维护入口为 `tools/native_qa/run_qa.py` 和 `Worker.cs`。源自
`build/warehouse-recognition-20261002/bounded-wgc-qa` 的现有入口；旧源码快照、
离线结果、原帧与真实运行证据仍保留在原处，不以迁移重新运行旧矩阵。
Worker 本次未改逻辑；Controller 仅调整源码/产物路径和过时的固定版本元数据。

## 编译与路径

先按项目既有构建入口生成 `build/native-observation/`，其中须有
`WgcLiveHarness.dll`、`NteHost.WindowMonitor.dll`、`NteHost.Protocol.dll` 和其依赖。
QA 编译引用该候选的 Protocol/JSON/Pipelines 程序集，不复制另一套生产源码。

```powershell
dotnet build tools/native_qa/Worker.csproj -c Release
& build/takeover_20260905/repro-venv/Scripts/python.exe tools/native_qa/run_qa.py --help
```

编译产物位于 `build/native_qa/out/`，中间产物位于 `build/native_qa/obj/`；
每次运行输出位于 `build/native_qa/<mode>-<id>/`。全部留在忽略的 build 目录。
默认无参数是旧离线矩阵，日常路径核对只运行 `--help`，不重跑该矩阵。

## 将来获明确授权后的真实入口

```powershell
& build/takeover_20260905/repro-venv/Scripts/python.exe tools/native_qa/run_qa.py --mode live --observation-window-mode background-readonly --game-ready --hwnd <当时核实的HWND> --pid <PID> --instance <创建FILETIME>
```

这条示例不是授权。每次重新核实异环窗口身份，禁止复用旧进程身份。
只采指定窗口客户区，最多 3 次显式尝试（失败计数），8 秒停止工作，10 秒核实实际退出；
首个失败结束，不循环补采。窗口/映射失效或新权限提示均拒绝；没有桌面采集、
激活、游戏输入、生产 SOURCE 租约、正式历史或标签写入。

`qa-progress` 即时报启动与保存，数值时钟诊断保留在原始子进程日志与结果中；
未来时间与请求后新帧检查不放宽。此入口通过只说明独立 QA，不代表生产 FRAME、
SOURCE、自动翻页或完整拍卖流程已经通过。

## 自建窗口时间戳投影对照

`timestamp_probe/`与`run_timestamp_probe.py`仅用于自建无私人内容窗口的同帧
SystemRelativeTime投影/直接ABI对照。使用现有候选Host的WGC类及相同投影DLL，
不重建Host，不进入FRAME、SOURCE或Engine；直接ABI也调用同一个Windows属性，
不是另一套来源时钟。设计与一次实验结果见
`docs/superpowers/specs/2026-10-06-wgc-timestamp-contract-repro-design.md`。

```powershell
dotnet build tools/native_qa/timestamp_probe/TimestampProbe.csproj -c Release
& build/takeover_20260905/repro-venv/Scripts/python.exe tools/native_qa/run_timestamp_probe.py
```

默认只检查二进制身份，不创建窗口或采帧。仅在已获自建窗口实验授权时加
`--run-once`：最多3次请求、8秒工作、10秒核实实际退出，无自动重试。
工具会自行创建并只捕获自己的640×360窗口；不接受游戏HWND、没有桌面入口。
所有读回均是诊断样本，未来值也不能因此成为正式接受帧。
源码构建及运行输出在`build/native-timestamp-contract-20261006/`。

## 已结束的同异常游戏帧ABI取证

`game_timestamp_probe/`复用当前Host的WGC类和选择器，只在独立QA回调中
固定原比较值后补读同一活帧的ABI；生产文件和二进制不变。

```powershell
dotnet build tools/native_qa/game_timestamp_probe/GameTimestampProbe.csproj -c Release
& build/takeover_20260905/repro-venv/Scripts/python.exe tools/native_qa/run_game_timestamp_probe.py
```

默认仅核对候选/投影/Protocol哈希，不查询窗口、不采帧。获该次授权并重新核实
目标后才加`--run-once --game-ready --hwnd <HWND> --pid <PID> --instance <FILETIME>`。
3次/8秒/10秒，失败即止；不激活、不输入、不进入完整流程。
未来值按原比较拒绝，不等时间追上；异常帧不读回图片，正常帧仅诊断读回/hash，
不保存游戏图片或发布FRAME/SOURCE。输出在`build/native-timestamp-contract-20261006/game-abi-<id>/`。
同帧判定、字段和一次取证之后的分支决策见上述设计，正常不复现也不算修复。

游戏取证已结束；当前不再运行上述游戏入口。完整异常证据保留在
`build/native-timestamp-contract-20261006/game-abi-13f9870435/`。

## 一次有限的自建DXGI窗口对照

`dxgi_timestamp_probe/`和`run_dxgi_timestamp_probe.py`只接受自建窗口，
不接受外部HWND。使用640×360、窗口化flip-sequential交换链和自己生成的
nonce/编号；复用候选WGC、严格选择器和已审计的同帧ABI读取。

```powershell
dotnet build tools/native_qa/dxgi_timestamp_probe/DxgiTimestampProbe.csproj -c Release
python tools/native_qa/run_dxgi_timestamp_probe.py
```

默认只核对清单，不创建窗口或取帧。一次授权实验已经执行，不自动再加
`--run-once`。最多3次请求、8秒工作、10秒确认退出；首次未来值固定拒绝，
自己的诊断读回不撤销拒绝。此次2次尝试、1帧诊断接受，第2次原生未来值复现，
实际退出880.0966ms。详见`docs/reports/2026-10-06-dxgi-timestamp-engineering-conclusion.md`。
生产门禁和完整生命周期未因此通过。

## 内容判稳离线收页原型（2026-10-07）

`tests/test_native_content_flow.py` 使用独立生成的无私人内容图元，只将
WGC交付和窗口发送替换为离线适配器；实际 SOURCE v2、原图存储、收页器、
滑块观察、重叠和覆盖账本参与正常路径。身份参照使用独立空目录，不验证
生产物品身份。默认不依赖未入库的游戏原图，不使用任何捕获/输入接口。

```powershell
python tests/test_native_content_flow.py FlowTests.test_normal_reveal_stability_save_scroll_overlap_bottom
```

共同Q5双线性采样模型仅验证已知夹具渲染条件；真实16图的既有检查在
`build/native-content-flow-offline-20261007/retained-model-results.json`，后段
参照区无法解释，不能启用到生产。原严格判定和交付时序生产入口不变。
需要分析已有原图时才显式运行 `check_retained_content_model.py --manifest
<已保留的real-result.json> --output <本项目build内的结果文件>`；它不采游戏。
