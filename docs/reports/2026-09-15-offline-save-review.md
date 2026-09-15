# 离线识别→正式保存→重启 GUI 回看（2026-09-15）

整体仍 **PARTIAL**。本轮完成最小真实闭环：冻结 EXE 识别已有结算原图 → `AutoArchiver` 写入独立临时 DATA_ROOT → 关闭 → 重启同一候选 → 真实 GUI 历史找到该记录并逐件回看。未认全 39 件，未改图鉴/阈值/求解器。

## 交付身份

| 项 | 值 |
|---|---|
| Git HEAD | `a10f167893325f3b2fd0f968a533a5290967814e` |
| 构建修订 | `a10f167`（`isolated-trial-v1`） |
| 候选 EXE | `D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_a10f167\dist\异环拍卖助手\异环拍卖助手.exe` |
| EXE SHA256 | `C9BBDE57D593BEC63BE3F1319DCBEE7D62FF4A37CB7A08CD778BF5158349D381` |
| 启动 cwd | `C:\Users\Administrator\AppData\Local\Temp\yihuan-exe-cwd-990f53f` |
| 绝对 DATA_ROOT | `D:\yihuanpaimai\build\exe_chain_20260915\data_20260915_011821` |
| 素材 | `settlement_blob_144037.png` SHA256 `85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6` 2560×1440 |
| 保留未覆盖 | `3c270c8`、`990f53f`、`84e0207`、日常 v13 |

先提交 `990f53f`（文件源 + `ctx["frame"]` + warehouse.slots），用该包验证时单张静帧在场景确认前被 EOF，未归档。再提交 `a10f167`：`KeyframeDirectorySource(hold_last=True)` 把同一张物理原图保持到 stop，不把它算成独立多帧。

## 正式链（未走测试旁路）

`NTE_REPLAY_FRAMES_DIR` → worker `KeyframeDirectorySource`（n=1, hold_last=1）→ `KeyboardAuctionPipeline.process_frame` → `CurrentMatch` / `LiveMatchSession.observe` → `AutoArchiver.archive_match` → `CanonicalHistoryStore`。日志：

- `frame source=files ... n=1 hold_last=1`
- `scene=SETTLEMENT` `settle=1222222/1556124/333902`
- `[WORKER:VISION] catalog_reference_manifest selected=v2 path=...\ _internal\assets\items\catalog_reference_manifest_v2.json recovered=213`
- `identity_frame_ms=54525 scene=SETTLEMENT exact=26`
- `settlement finalize reason=stable price=1222222.0 actual=1556124.0 profit=333902.0`
- `💾 [全自动记账] 成功归档至: ...\data_20260915_011821\history\异环拍卖数据.json`

未预填身份、未伪造赢家、未手写 records/reviewUnits。赢家 `致敬最良心不歪` 来自该帧 OCR；现有规则因此写成 FINALIZED，不是本轮强制。

## 保存一致性（与识别准确率分开）

| 项 | 结果 |
|---|---|
| 保存后记录数 | 1 |
| 重启后再读 | 1（未重复建局） |
| source | `vision-auto-archiver` |
| lifecycle | FINALIZED |
| reviewUnits | 29 |
| 裁图落盘 / SHA / 与原图 bbox 像素一致 | **29 / 29 / 29** |
| GUI 历史列表 | 1 条，点击 `draft_a8f29dc739fa403e89e1aca932280c4d` |
| GUI 回看 | 29 张 grouping-card；名称与 confirmationStatus 与磁盘 29/29 一致 |
| GUI 原图 | `evidence/settlement_v2/blobs/85/85ce3299....png`（与输入帧同一 SHA） |
| 仓库摘要 | `29 件（其中 3 件未具名）` |
| 成交/实际 | `1,222,222` / `1,556,124` |

未知 3 件保存为 `CANDIDATE_ONLY`，名称仍空，未因保存升级为 CONFIRMED。

## 识别准确率（对本帧可见范围，不是 39 仓）

整仓 GT 39 件在 10×25 拼接画布。本帧可见最大行=9 → **可见 GT 27**，折下 12 件不计入漏检。

| 口径 | 数 |
|---|---|
| 本帧检出 | 29 |
| 可见 GT 名称正确（exact/CONFIRMED） | **26** |
| 可见 GT 未知保留 | 1（M1000模型，4×4 绿，未命名） |
| 可见 GT 名称错误 | 0 |
| 可见 GT 漏检 | 0 |
| 本帧额外未命名（底部部分可见，不在可见 GT 对齐集） | 2 |
| 折下未在本帧 | 12 |

26 exact ≠ 26 件正确仓；不能用 39−29=10 当漏检。

折下 12：储钱小哼、灯塔、罐装随心泥、「强身好伙伴！」、琉璃尾、番茄百分百果冻、引航者望远镜、蟑螂！蟑螂！、断落的剑格、吨吨锤、「莲-C198」唱片机、清凉凉止痛药。

## 逐件（磁盘保存 = GUI 回看）

原图引用均为上述 85ce3299 blob。裁图均从该原图 bbox 切出，像素一致。

| # | 格 | 名称 | catalogId | 状态 | bbox | 裁图像素 |
|---|---|---|---|---|---|---|
| 0 | 0,0 | 销魂挠挠爪 | image12-0-0 | CONFIRMED | 1753,285,150,225 | 是 |
| 1 | 0,2 | 烟紫水晶 | image11-0-1 | CONFIRMED | 1903,285,75,225 | 是 |
| 2 | 0,3 | 拍拍球 | image9-0-2 | CONFIRMED | 1978,285,75,75 | 是 |
| 3 | 0,4 | 金月 | image8-1-1 | CONFIRMED | 2053,285,76,75 | 是 |
| 4 | 0,5 | 复古圆桌 | image14-0-2 | CONFIRMED | 2129,285,150,75 | 是 |
| 5 | 0,7 | （未来的）大师飞镖 | image16-0-0 | CONFIRMED | 2279,285,75,75 | 是 |
| 6 | 0,8 | 惠比寿宫廷小塔 | image7-0-0 | CONFIRMED | 2354,285,150,75 | 是 |
| 7 | 1,3 | 艺术画「深林」 | image10-1-0 | CONFIRMED | 1978,360,226,225 | 是 |
| 8 | 1,6 | 九格小食 | image34-0-1 | CONFIRMED | 2204,360,225,225 | 是 |
| 9 | 1,9 | 鎏金坠 | image24-1-2 | CONFIRMED | 2429,360,75,75 | 是 |
| 10 | 2,9 | 酷辣辣辣条 | image3-0-2 | CONFIRMED | 2429,435,75,150 | 是 |
| 11 | 3,0 | 跳跳兔盒 | image20-0-1 | CONFIRMED | 1753,510,150,150 | 是 |
| 12 | 3,2 | 炭火脆皮烤肉 | image9-0-1 | CONFIRMED | 1903,510,75,75 | 是 |
| 13 | 4,2 | 蓝焰火花塞 | image30-0-0 | CONFIRMED | 1903,585,150,150 | 是 |
| 14 | 4,4 | 炫动三角铁 | image5-1-0 | CONFIRMED | 2053,585,226,75 | 是 |
| 15 | 4,7 | 巡哨-干练精英 | visual-922c073c366d | CONFIRMED | 2279,585,150,75 | 是 |
| 16 | 4,9 | 银铃 | image15-0-1 | CONFIRMED | 2429,585,75,75 | 是 |
| 17 | 5,0 | 大将军章鱼烧 | image22-0-2 | CONFIRMED | 1753,660,150,75 | 是 |
| 18 | 5,4 | 盈雪点翠 | image30-0-1 | CONFIRMED | 2053,660,151,150 | 是 |
| 19 | 5,6 | 绵绵云 | image3-0-1 | CONFIRMED | 2204,660,75,75 | 是 |
| 20 | 5,7 | 猫丸秘制豚骨拉面 | visual-9607b248bbf4 | CONFIRMED | 2279,660,75,75 | 是 |
| 21 | 5,8 | 方盒随身听 | image1-0-0 | CONFIRMED | 2354,660,150,225 | 是 |
| 22 | 6,0 | （未知） | — | CANDIDATE_ONLY | 1753,735,300,300 | 是 |
| 23 | 6,6 | 幽灵态 | image23-1-1 | CONFIRMED | 2204,735,75,75 | 是 |
| 24 | 6,7 | 「方盒科技」智能手表 | image31-1-2 | CONFIRMED | 2279,735,75,150 | 是 |
| 25 | 7,4 | 巡哨-干练精英 | visual-922c073c366d | CONFIRMED | 2053,810,151,75 | 是 |
| 26 | 7,6 | （未来的）大师飞镖 | image16-0-0 | CONFIRMED | 2204,810,75,75 | 是 |
| 27 | 8,4 | （未知） | — | CANDIDATE_ONLY | 2053,885,376,150 | 是 |
| 28 | 8,9 | （未知） | — | CANDIDATE_ONLY | 2429,885,75,150 | 是 |

## 隔离

本轮独立前后快照（日常/试用 hash 与上轮冻结运行相同）：

| 目录 | 前 | 后 |
|---|---|---|
| `%LOCALAPPDATA%\异环拍卖助手` | 1602 / `9ff6609a…` | 相同 |
| `%LOCALAPPDATA%\异环拍卖助手试用` | 61 / `92519223…` | 相同 |
| 84e0207 包 | 未改 | 相同 |
| v13 包 | 未改 | 相同 |
| 3c270c8 包 | 未改 | 相同 |
| 临时 DATA_ROOT | — | 35 个文件（历史 + 原图 blob + 29 裁图） |

未改用户原始历史。测试写入只限该临时目录。

## 本轮代码（已提交后打包）

- `NTE_REPLAY_FRAMES_DIR` + PNG 无 `frame_` 前缀
- 观察帧写入 `ctx["frame"]`，flush 前补 heavy identity
- 由 reviewUnits 合成 warehouse 时带 `slots: []`，避免 `WAREHOUSE_SLOTS_NOT_LIST`
- smoke 输出 `settlementItems` 与 `catalogLoad`
- manifest 选用路径日志
- **hold_last**：单张静帧保持到 stop，供场景确认与 SETTLEMENT_STABLE_FRAMES；同一文件不是独立物理多帧
- 回归：`tests/test_offline_frame_archive_chain.py`

## 未完成 / 仍 PARTIAL

- 未做真实 70 秒滚仓、未见对局、本人获胜全链、跨页 39 件拼接。
- 不补 9 条目、不裁定 19 条冲突。
- 跨进程再次喂同一张图会新开 CurrentMatch id（现有对局身份规则）；本轮验收是同进程签名门 + 无回放重启不增记录。
- 完整隔离试用与第 6 节发布门槛不能由这一段代替。

机器附件：`docs/reports/2026-09-15-offline-save-review.md`、`build/exe_chain_20260915/`。
