# 3c270c8 候选最小实际 EXE 运行验证（2026-09-15）

候选：`build/isolated_trial_ux_fixes_20260914_3c270c8/dist/异环拍卖助手/异环拍卖助手.exe`  
SHA256 实测 `6DCE290A047340813993003151CA4A2E3EAC2332AEE932CE74B5513829ECBD71`，与预期一致。  
启动 cwd：`C:\Users\Administrator\AppData\Local\Temp\yihuan-exe-cwd-3c270c8`（非工程根）。  
`YIHUAN_DATA_ROOT`：`build/exe_run_20260915_f4e58e2/data`。  
Git HEAD：`f4e58e2`。未改业务代码、未重打包。

机器附件：`docs/reports/` 与 Vault `Evidence/2026-09-15-frozen-exe-runtime/`。

## 1. 冻结进程确实跑起来了

| 入口 | Frozen | codeRevision | 要点 |
|---|---|---|---|
| `--smoke-vision-frame` ×7 | true | 3c270c8 | `visualReferenceCount=107`（包内 visual_catalog_v2 核过源卡） |
| `--smoke-canonical-persistence` | true | 3c270c8 | 现有断言失败：`validFinalizedV7=false` / `RECORD_NOT_DICT`；草稿曾写入进程临时目录 |
| `--smoke-evidence-storage` | true | 3c270c8 | 写入隔离 DATA_ROOT 的 png，哈希复核通过后入口自行删除文件 |
| GUI 两次 | 日志 `Frozen=True` | 日志 profile=`isolated-trial-v1` | WebView2 ready；子进程 `异环拍卖助手.exe --vision-worker`；第二次 worker `history snapshot n=0` |

GUI 从包内加载：`_internal\DirectCompositionHost.dll`、`overlay_alpha.html`、`main_window.html`。  
两次关闭后 `history/异环拍卖数据.json`（71 字节空文档）仍在临时 DATA_ROOT，第二次启动读到 n=0。这只证明空历史隔离存活，不是逐件身份回看。

**manifest v2：** 现有日志/smoke 字段没有打印 `catalog_reference_manifest_v2.json`。不能用日志直证“选中 v2”。冻结 SETTLEMENT 识别会走 `load_visual_templates()`，其 `asset_root()` 在 frozen 下是 `_MEIPASS`；该包内确有 v2 文件，加载器遇 v2 即选用。这是冻结进程 + 包内文件 + 加载规则的联合推断，不是文件名日志。

## 2. 逐样本（冻结 `--smoke-vision-frame`，不预填身份）

| 样本 | 来源 | 场景 | 结果 | 对照 |
|---|---|---|---|---|
| 2026-08-18_11-19-25_455 合成 1920×1080 | 结算卡夹具贴到黑底 | UNKNOWN | 0 命名；miss 25 | 缺完整结算 UI，场景门未开 |
| 2026-08-25_21-58-33_6 合成 | 同上 | UNKNOWN | 0 命名；miss 19 | 同上 |
| 2026-08-17_14-11-56_240 合成 | 同上 | UNKNOWN | 0 命名；miss 22 | 同上 |
| replay frame_0000 / frame_0005 | `assets/replay_frames` 960×540 | UNKNOWN | 无 GT 名 | 非结算整窗 |
| settlement_blob_144037 | 已有 2560×1440 结算原图 | **SETTLEMENT** 0.9857 | 29 件、**26 exact**、exactValueSum=680662 | GT 39 件；smoke 字段不含逐件名称，故不能列对/错名 |
| settlement_blob_p3_c3e47 | 已有 2560×1440 结算原图 | **SETTLEMENT** 0.9858 | 同样 29 / 26 exact / 680662 | 同口径 |

合成图 UNKNOWN 是场景路由 fail-closed，不是“图鉴没加载”。  
整窗结算图证明冻结进程做了结算识别。相对 144037 的 39 件真值：检出 29、exact 26、未检出约 10；3 件非 exact。**名称列表被现有 smoke 白名单丢掉**，本轮不能声称哪 26 个名字正确。

无 mp4，`--smoke-acquisition-video` 未跑。

## 3. 保存 / 重启 / 回看

- 识别结果（26 exact）**没有**写入 DATA_ROOT 历史或 reviewUnits；`--smoke-vision-frame` 不归档。
- GUI 两次启动：空 `异环拍卖数据.json` 仍在，第二次 worker `n=0`。没有裁图路径可对像素。
- `--smoke-evidence-storage` 曾写入隔离 evidence png 且哈希一致，随即删除，无法第二次启动回看该文件。

**最早阻断（身份保存回看）：** 现有冻结诊断入口能识别结算件数，但不持久化逐件名称/确认状态/裁图；GUI worker 无游戏窗、无录像目录，不会把本次帧写入历史。最小修复建议：给 `--smoke-vision-frame` 增加 `settlementItems` 名称字段，并可选写入隔离历史；或提供不改包的回放目录环境变量。本轮按授权不改代码。

## 4. 隔离

本轮独立前后快照（不复用上轮口头 1602）：

| 目录 | 前 | 后 |
|---|---|---|
| 日常 `%LOCALAPPDATA%\异环拍卖助手` | 1602 / `9ff6609a…` | 相同 |
| 原试用 `%LOCALAPPDATA%\异环拍卖助手试用` | 61 / `92519223…` | 相同 |
| 84e0207 包 | 682 / `db55938f…` | 相同 |
| v13 包 | 583 / `7ac5bc1c…` | 相同 |
| 临时 DATA_ROOT | — | 2 个文件：空历史 json + 桌宠 state |

未覆盖 v13 / 84e0207。未改用户原始历史。

## 未完成

- 日志直证 v2 文件名。
- 逐件名称对错表（smoke 未输出 names）。
- 识别结果保存后再启动核对裁图像素。
- 完整隔离试用端到端、未见对局、真实 70 秒滚仓。
- 不补 9 条目、不裁定 19 条冲突。

整体仍 PARTIAL。
