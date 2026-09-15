# 桌面环境与构建复现

产品版本由 `core/version.py` 管理。2026-09-05 已验证的运行环境为 Windows x64、Python 3.10.20，WebView2 与 .NET Framework 提供原生界面。

## 本次实际环境

本次验收使用 `C:/Users/Administrator/.astrbot_launcher/components/python/py310/python.exe`，加载 `C:/Program Files/Python310/Lib/site-packages` 中已有依赖，以及其中的 `win32`、`win32/lib`、`Pythonwin`。包的最初下载来源无法从现有文件确认，不能宣称这些依赖均来自一次干净安装。

`requirements-desktop.lock.txt` 记录实际安装的桌面依赖及传递依赖版本；它是环境快照，不含安装包哈希。`tools/check_runtime_environment.py` 只检查版本元数据和模块可发现性，不替代 DLL 加载、OCR、构建或原生窗口验收。本次观察结果保存在 `build/takeover_20260905/runtime_environment_observed.json`。

## 独立环境操作

在仓库根目录使用 Windows x64 Python 3.10 创建环境，避免依赖全局 Python 搜索路径：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tools/check_runtime_environment.py --output build/runtime-environment.json
```

从隔离数据目录启动，避免验收写入日常使用的历史：

```powershell
$env:YIHUAN_DATA_ROOT = Join-Path $PWD 'build\acceptance-data'
$env:YIHUAN_UPPER_TAIL_CAPTURE_DIR = Join-Path $PWD 'build\acceptance-captures'
.\.venv\Scripts\python.exe app/main.py
```

需要验证界面而暂不连接游戏时，可另设 `NTE_DISABLE_VISION=1`；真实识别验收前移除此变量。不得把这种界面验收当作游戏采集验收。

## 构建

指定测试可通过仓库入口运行，无须把依赖目录写进全局搜索路径：

```powershell
.\.venv\Scripts\python.exe tools/run_tests.py test_replay_worker_lifecycle test_live_match_control --output build/tests.json
```

该入口为运行时数据设置临时目录；测试自己创建的夹具由各测试清理。不会自动把整个测试目录当作已验收通过。

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath build/package --workpath build/pyinstaller-work app/异环拍卖助手.spec
```

spec 包含已批准大厅模板、WebView 页面与求解器，生成 `app/build_info.json` 记录构建时间、commit 和 dirty 状态。修改 `DirectCompositionHost.cs` 后需要用 .NET Framework x64 C# 编译器重新生成对应 DLL，引用当前 pywebview 自带的 `Microsoft.Web.WebView2.Core.dll`、`System.Windows.Forms.dll`、`System.Drawing.dll`。

构建后须在独立目录启动冻结包，验证模板加载、真实 OCR、主窗口与 worker 通信、同局预测归档和退出重开。回放用的临时 `config.json`、`录像关键帧` 不应留在交付包根目录。保留旧包作为比较基线。

## 当前验证边界

本机已多次完成构建和隔离原生窗口验收。独立虚拟环境安装已成功，`pip check` 无冲突，模块路径指向新虚拟环境；真实 75s 截图 OCR 探针加载模板 8/2/1 成功，13 项回放/控制/身份测试通过。证据为 `build/takeover_20260905/repro-install.log`、`runtime_environment_clean.json`、`repro-vision-smoke-fixed.json`、`repro-selected-tests.json`。

干净环境首次源码启动失败于核心目录初始化过晚，修复前日志 `repro-vision-smoke.log` 保留。最初直接 unittest discover 也缺少 app 路径，现使用上述仓库测试入口。新环境构建日志 `repro-package-build.log`，完成状态以执行规划最新记录为准；跨机器及真实游戏完整链仍未验收。
`repro-package-build.log` 已确认构建完成，且冻结包从仓库外目录运行真实截图探针成功；输入、模板和选定事实与源码一致，见 `repro-source-package-parity.json`。此包尚未做原生 GUI 与真人 UAT。
