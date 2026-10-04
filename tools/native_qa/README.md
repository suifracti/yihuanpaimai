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
