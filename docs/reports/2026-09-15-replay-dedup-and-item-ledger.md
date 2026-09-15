# 同源重复回放收口与逐件明细（2026-09-15）

整体仍 **PARTIAL**。首次闭环不重做。本轮：补齐 29 项明细；核对 hold_last/FINALIZED；a10f167 上主动重复回放复现重复建局；最小修复后用冻结 447f28b 验证进程内与退出后再带回放均为 1 条。

## 交付身份

| 项 | 值 |
|---|---|
| 构建修订 | 447f28b79adea7148c27117e504ba85800c44508 |
| 冻结候选 | D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_447f28b\dist\异环拍卖助手\异环拍卖助手.exe |
| EXE SHA256 | 5E6236D332A1771DCFBF67D4AB1C63C6A6F1380628BBACBC717094596A67EA00 |
| 保留 | a10f167、3c270c8、990f53f、84e0207、v13 |
| 首次闭环 DATA_ROOT（不改） | D:\yihuanpaimai\build\exe_chain_20260915\data_20260915_011821 |
| a10f167 重复回放对照 | ...\data_replay_dup_20260915_123038 |
| 447f28b 验证 DATA_ROOT | D:\yihuanpaimai\build\exe_chain_20260915\data_replay_fix_20260915_123631 |
| 原图 SHA | 85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6 |

单次性能记录保留：identity_frame_ms=54525（a10f167 首次闭环）。本轮不展开全局性能。

## 1. 可见范围依据

结算原图 2560x1440。检测格 (0,0) bbox (1753,285,150,225) 对应 2x3，单元格 75px，仓原点 (1753,285)。
本帧占用最大末行 = 9（由 29 个检测格的 row+h-1 得出）。
整仓 GT 是 10x25 拼接画布，不是这一张结算窗。

| 集合 | 规则 | 件数 |
|---|---|---|
| 完全可见 GT | lastRow <= 9 | **27** |
| 部分可见 GT | startRow <= 9 < lastRow | **2**（储钱小哼、灯塔） |
| 完全折下 | startRow > 9 | **10** |
| 上一轮所称「折下 12」 | lastRow > 9 | 2 部分 + 10 折下 |

原图引用一律 `evidence/settlement_v2/blobs/85/85ce3299....png`。

## 2. 29 项逐件（磁盘保存）

| # | 格 | 名称 | catalogId | 状态 | bbox | 裁图SHA前8 | GT | 分类 |
|---|---|---|---|---|---|---|---|---|
| 0 | 0,0 2x3 | 销魂挠挠爪 | image12-0-0 | CONFIRMED | 1753,285,150,225 | 9fcec3c3 | ref_144037_01 销魂挠挠爪 | visible_gt_correct |
| 1 | 0,2 1x3 | 烟紫水晶 | image11-0-1 | CONFIRMED | 1903,285,75,225 | bbc25863 | ref_144037_02 烟紫水晶 | visible_gt_correct |
| 2 | 0,3 1x1 | 拍拍球 | image9-0-2 | CONFIRMED | 1978,285,75,75 | 68e4216c | ref_144037_03 拍拍球 | visible_gt_correct |
| 3 | 0,4 1x1 | 金月 | image8-1-1 | CONFIRMED | 2053,285,76,75 | f2b491d4 | ref_144037_04 金月 | visible_gt_correct |
| 4 | 0,5 2x1 | 复古圆桌 | image14-0-2 | CONFIRMED | 2129,285,150,75 | 5a90a737 | ref_144037_05 复古圆桌 | visible_gt_correct |
| 5 | 0,7 1x1 | （未来的）大师飞镖 | image16-0-0 | CONFIRMED | 2279,285,75,75 | ce8dbe9a | ref_144037_06 （未来的）大师飞镖 | visible_gt_correct |
| 6 | 0,8 2x1 | 惠比寿宫廷小塔 | image7-0-0 | CONFIRMED | 2354,285,150,75 | dbb9178c | ref_144037_07 惠比寿宫廷小塔 | visible_gt_correct |
| 7 | 1,3 3x3 | 艺术画「深林」 | image10-1-0 | CONFIRMED | 1978,360,226,225 | 39760767 | ref_144037_08 艺术画「深林」 | visible_gt_correct |
| 8 | 1,6 3x3 | 九格小食 | image34-0-1 | CONFIRMED | 2204,360,225,225 | 316f6f45 | ref_144037_09 九格小食 | visible_gt_correct |
| 9 | 1,9 1x1 | 鎏金坠 | image24-1-2 | CONFIRMED | 2429,360,75,75 | 41a3b188 | ref_144037_10 鎏金坠 | visible_gt_correct |
| 10 | 2,9 1x2 | 酷辣辣辣条 | image3-0-2 | CONFIRMED | 2429,435,75,150 | 5e1b9aba | ref_144037_11 酷辣辣辣条 | visible_gt_correct |
| 11 | 3,0 2x2 | 跳跳兔盒 | image20-0-1 | CONFIRMED | 1753,510,150,150 | f114ac39 | ref_144037_12 跳跳兔盒 | visible_gt_correct |
| 12 | 3,2 1x1 | 炭火脆皮烤肉 | image9-0-1 | CONFIRMED | 1903,510,75,75 | e258d702 | ref_144037_13 炭火脆皮烤肉 | visible_gt_correct |
| 13 | 4,2 2x2 | 蓝焰火花塞 | image30-0-0 | CONFIRMED | 1903,585,150,150 | 54c89523 | ref_144037_14 蓝焰火花塞 | visible_gt_correct |
| 14 | 4,4 3x1 | 炫动三角铁 | image5-1-0 | CONFIRMED | 2053,585,226,75 | 709dad18 | ref_144037_15 炫动三角铁 | visible_gt_correct |
| 15 | 4,7 2x1 | 巡哨-干练精英 | visual-922c073c366d | CONFIRMED | 2279,585,150,75 | d3a8309b | ref_144037_16 巡哨-干练精英 | visible_gt_correct |
| 16 | 4,9 1x1 | 银铃 | image15-0-1 | CONFIRMED | 2429,585,75,75 | 98f4a52d | ref_144037_17 银铃 | visible_gt_correct |
| 17 | 5,0 2x1 | 大将军章鱼烧 | image22-0-2 | CONFIRMED | 1753,660,150,75 | b89c3cd9 | ref_144037_18 大将军章鱼烧 | visible_gt_correct |
| 18 | 5,4 2x2 | 盈雪点翠 | image30-0-1 | CONFIRMED | 2053,660,151,150 | 15430d85 | ref_144037_19 盈雪点翠 | visible_gt_correct |
| 19 | 5,6 1x1 | 绵绵云 | image3-0-1 | CONFIRMED | 2204,660,75,75 | a4a7a778 | ref_144037_20 绵绵云 | visible_gt_correct |
| 20 | 5,7 1x1 | 猫丸秘制豚骨拉面 | visual-9607b248bbf4 | CONFIRMED | 2279,660,75,75 | fa4a46e6 | ref_144037_21 猫丸秘制豚骨拉面 | visible_gt_correct |
| 21 | 5,8 2x3 | 方盒随身听 | image1-0-0 | CONFIRMED | 2354,660,150,225 | 1448ad76 | ref_144037_22 方盒随身听 | visible_gt_correct |
| 22 | 6,0 4x4 | （未知） | — | CANDIDATE_ONLY | 1753,735,300,300 | df0cd1f8 | ref_144037_23 M1000模型 | visible_gt_unknown |
| 23 | 6,6 1x1 | 幽灵态 | image23-1-1 | CONFIRMED | 2204,735,75,75 | 6950b773 | ref_144037_24 幽灵态 | visible_gt_correct |
| 24 | 6,7 1x2 | 「方盒科技」智能手表 | image31-1-2 | CONFIRMED | 2279,735,75,150 | 20b05f92 | ref_144037_25 「方盒科技」智能手表 | visible_gt_correct |
| 25 | 7,4 2x1 | 巡哨-干练精英 | visual-922c073c366d | CONFIRMED | 2053,810,151,75 | 177d5bd2 | ref_144037_26 巡哨-干练精英 | visible_gt_correct |
| 26 | 7,6 1x1 | （未来的）大师飞镖 | image16-0-0 | CONFIRMED | 2204,810,75,75 | f1b50f9f | ref_144037_27 （未来的）大师飞镖 | visible_gt_correct |
| 27 | 8,4 5x2 | （未知） | — | CANDIDATE_ONLY | 2053,885,376,150 | 067687f1 | —  | extra_unaligned |
| 28 | 8,9 1x2 | （未知） | — | CANDIDATE_ONLY | 2429,885,75,150 | 2bb61943 | —  | extra_unaligned |

#10 名称「酷辣辣辣条」与 GT 一致，程序 catalogId=`image3-0-2`，GT 清单为 `visual-latiao-1x2`。名称正确，catalogId 标 **待核**，不改真值。

## 3. 27 件完全可见 GT

| ref | 名称 | catalogId | 格 | lastRow | 拼接画布bbox | 投影本帧bbox |
|---|---|---|---|---|---|---|
| ref_144037_01 | 销魂挠挠爪 | image12-0-0 | 0,0 2x3 | 2 | [0, 0, 150, 225] | [1753, 285, 150, 225] |
| ref_144037_02 | 烟紫水晶 | image11-0-1 | 0,2 1x3 | 2 | [150, 0, 225, 225] | [1903, 285, 75, 225] |
| ref_144037_03 | 拍拍球 | image9-0-2 | 0,3 1x1 | 0 | [225, 0, 300, 75] | [1978, 285, 75, 75] |
| ref_144037_04 | 金月 | image8-1-1 | 0,4 1x1 | 0 | [300, 0, 375, 75] | [2053, 285, 75, 75] |
| ref_144037_05 | 复古圆桌 | image14-0-2 | 0,5 2x1 | 0 | [375, 0, 525, 75] | [2128, 285, 150, 75] |
| ref_144037_06 | （未来的）大师飞镖 | image16-0-0 | 0,7 1x1 | 0 | [525, 0, 600, 75] | [2278, 285, 75, 75] |
| ref_144037_07 | 惠比寿宫廷小塔 | image7-0-0 | 0,8 2x1 | 0 | [600, 0, 750, 75] | [2353, 285, 150, 75] |
| ref_144037_08 | 艺术画「深林」 | image10-1-0 | 1,3 3x3 | 3 | [225, 75, 450, 300] | [1978, 360, 225, 225] |
| ref_144037_09 | 九格小食 | image34-0-1 | 1,6 3x3 | 3 | [450, 75, 675, 300] | [2203, 360, 225, 225] |
| ref_144037_10 | 鎏金坠 | image24-1-2 | 1,9 1x1 | 1 | [675, 75, 750, 150] | [2428, 360, 75, 75] |
| ref_144037_11 | 酷辣辣辣条 | visual-latiao-1x2 | 2,9 1x2 | 3 | [675, 150, 750, 300] | [2428, 435, 75, 150] |
| ref_144037_12 | 跳跳兔盒 | image20-0-1 | 3,0 2x2 | 4 | [0, 225, 150, 375] | [1753, 510, 150, 150] |
| ref_144037_13 | 炭火脆皮烤肉 | image9-0-1 | 3,2 1x1 | 3 | [150, 225, 225, 300] | [1903, 510, 75, 75] |
| ref_144037_14 | 蓝焰火花塞 | image30-0-0 | 4,2 2x2 | 5 | [150, 300, 300, 450] | [1903, 585, 150, 150] |
| ref_144037_15 | 炫动三角铁 | image5-1-0 | 4,4 3x1 | 4 | [300, 300, 525, 375] | [2053, 585, 225, 75] |
| ref_144037_16 | 巡哨-干练精英 | visual-922c073c366d | 4,7 2x1 | 4 | [525, 300, 675, 375] | [2278, 585, 150, 75] |
| ref_144037_17 | 银铃 | image15-0-1 | 4,9 1x1 | 4 | [675, 300, 750, 375] | [2428, 585, 75, 75] |
| ref_144037_18 | 大将军章鱼烧 | image22-0-2 | 5,0 2x1 | 5 | [0, 375, 150, 450] | [1753, 660, 150, 75] |
| ref_144037_19 | 盈雪点翠 | image30-0-1 | 5,4 2x2 | 6 | [300, 375, 450, 525] | [2053, 660, 150, 150] |
| ref_144037_20 | 绵绵云 | image3-0-1 | 5,6 1x1 | 5 | [450, 375, 525, 450] | [2203, 660, 75, 75] |
| ref_144037_21 | 猫丸秘制豚骨拉面 | visual-9607b248bbf4 | 5,7 1x1 | 5 | [525, 375, 600, 450] | [2278, 660, 75, 75] |
| ref_144037_22 | 方盒随身听 | image1-0-0 | 5,8 2x3 | 7 | [600, 375, 750, 600] | [2353, 660, 150, 225] |
| ref_144037_23 | M1000模型 | image5-0-0 | 6,0 4x4 | 9 | [0, 450, 300, 750] | [1753, 735, 300, 300] |
| ref_144037_24 | 幽灵态 | image23-1-1 | 6,6 1x1 | 6 | [450, 450, 525, 525] | [2203, 735, 75, 75] |
| ref_144037_25 | 「方盒科技」智能手表 | image31-1-2 | 6,7 1x2 | 7 | [525, 450, 600, 600] | [2278, 735, 75, 150] |
| ref_144037_26 | 巡哨-干练精英 | visual-922c073c366d | 7,4 2x1 | 7 | [300, 525, 450, 600] | [2053, 810, 150, 75] |
| ref_144037_27 | （未来的）大师飞镖 | image16-0-0 | 7,6 1x1 | 7 | [450, 525, 525, 600] | [2203, 810, 75, 75] |

## 4. 部分可见 2 + 完全折下 10

| ref | 名称 | catalogId | 格 | lastRow | 可见性 | 拼接画布bbox | 投影本帧bbox |
|---|---|---|---|---|---|---|---|
| ref_144037_28 | 储钱小哼 | visual-xiaoheng-5x5 | 8,4 5x5 | 12 | partial_in_this_viewport | [300, 600, 675, 975] | [2053, 885, 375, 375] |
| ref_144037_29 | 灯塔 | image11-0-0 | 8,9 1x3 | 10 | partial_in_this_viewport | [675, 600, 750, 825] | [2428, 885, 75, 225] |
| ref_144037_30 | 罐装随心泥 | image26-0-2 | 10,0 4x3 | 12 | below_fold | [0, 750, 300, 975] | [1753, 1035, 300, 225] |
| ref_144037_31 | 「强身好伙伴！」 | image27-1-2 | 11,9 1x5 | 15 | below_fold | [675, 825, 750, 1200] | [2428, 1110, 75, 375] |
| ref_144037_32 | 琉璃尾 | visual-liuliwei-4x1 | 13,0 4x1 | 13 | below_fold | [0, 975, 300, 1050] | [1753, 1260, 300, 75] |
| ref_144037_33 | 番茄百分百果冻 | image12-1-1 | 13,4 2x2 | 14 | below_fold | [300, 975, 450, 1125] | [2053, 1260, 150, 150] |
| ref_144037_34 | 引航者望远镜 | image10-1-2 | 13,6 3x2 | 14 | below_fold | [450, 975, 675, 1125] | [2203, 1260, 225, 150] |
| ref_144037_35 | 蟑螂！蟑螂！ | image1-1-0 | 14,0 2x2 | 15 | below_fold | [0, 1050, 150, 1200] | [1753, 1335, 150, 150] |
| ref_144037_36 | 断落的剑格 | image13-1-0 | 14,2 2x1 | 14 | below_fold | [150, 1050, 300, 1125] | [1903, 1335, 150, 75] |
| ref_144037_37 | 吨吨锤 | visual-4cc72b207cb6 | 15,2 3x3 | 17 | below_fold | [150, 1125, 375, 1350] | [1903, 1410, 225, 225] |
| ref_144037_38 | 「莲-C198」唱片机 | image5-1-1 | 15,5 2x2 | 16 | below_fold | [375, 1125, 525, 1275] | [2128, 1410, 150, 150] |
| ref_144037_39 | 清凉凉止痛药 | image14-0-0 | 15,7 2x1 | 15 | below_fold | [525, 1125, 675, 1200] | [2278, 1410, 150, 75] |

## 5. 两件底部额外项分类

| 检测 | 格 | bbox | 稀有度 | 重叠 GT | 分类 |
|---|---|---|---|---|---|
| settlement_item_27 | 8,4 5x2 | 2053,885,376,150 | red | 储钱小哼 8,4 5x5 lastRow=12，投影 375x375 仅露出上 150px（2 格） | **真实部分物**。不是空地误检，也不是把已完整可见件再拆一次。身份因裁切不足保持未知，**待核完整脚印**。 |
| settlement_item_28 | 8,9 1x2 | 2429,885,75,150 | blue | 灯塔 8,9 1x3 lastRow=10，投影 75x225 仅露出上 150px | **真实部分物**。同上。 |

未见把同一完整可见 GT 拆成两件。未见背景误检证据。不改阈值把这两件抹掉。

## 6. hold_last 与 FINALIZED（代码）

**来源 / 观察 / 时间（修复前 a10f167）**

- 文件源只把目录喂给 worker。记录 `id` / `recordStableKey` 来自 `CurrentMatch.begin_next_match`：`draft_{uuid}`（`current_match.py:427`）。每进程新 uuid。
- 修复前 `KeyframeDirectorySource.provide` 每次 `datetime.now()`。hold_last 重读同一文件会换墙钟时间。
- worker `record_stable_key=current_match.id`（`vision_worker_loop.py` 约 203-225 行）。
- 证据 `evidenceOrigin=runtime-capture`，`capturedAt` 为处理时刻。原图字节 SHA 已在 blob 路径，但未作为对局身份。

**确认计数**

- `SETTLEMENT_STABLE_FRAMES = 2`（`vision_pipeline.py:63`）。`_stabilize_settlement`（4077-4103）在成交/实际/收益数字不变时 `_settlement_stable += 1`。注释是防止动画早期 0/顶格成交价，不是 N 次独立物理采集。
- `SettlementIdentityMemory.observe`（71-72）同一 exact 签名直接 return，不因 hold_last 再记一条独立身份观察。
- 维持静帧让场景确认和账单稳定，不等于新的独立证据。本例 `reason=stable` 是账单数字连续稳定，允许单帧终态截图归档。

**本例 FINALIZED 既有规则（未改准入）**

`auto_archiver.py:239-254` 与 `472-474`：

- 赢家「致敬最良心不歪」非空且不在占位黑名单 → `has_proven_winner`
- `clearing=1222222`、`actual=1556124` 非空
- `acquired` 为 bool（本例 False，他人获胜）
- `profit=333902` 非空
- → `is_finalized=True`

不强制 FINALIZED，也不改为 DRAFT。FINALIZED 不等于整仓完整：`coverageStatus=COVERAGE_UNPROVEN`。`evaluate_record_eligibility`：`formally_eligible=False`（缺预测快照、truth confidence 等），不会自动进入正式学习/评估。

**修复（447f28b）**

- `content_fingerprint()`：唯一文件字节 SHA。同一静帧等于同一来源。
- hold_last 复用 `_hold_stamp`，不再每次 now()。
- worker：`recordStableKey=replayfile_{fingerprint}`（`main.py:3763-3771`）。
- 归档键增加 `origsha:{sha256}`（`canonical_history_store.py:107`），按原图像素身份去重，不按金额/昵称。

## 7. 主动重复回放对照

素材始终 `settlement_blob_144037.png` / SHA `85ce3299`。隔离日常/试用哈希未变。

### a10f167（缺陷）

复制首次 DATA_ROOT 后再次带回放源启动：

| 时刻 | 记录数 | 单位 | 证据 PNG | ID |
|---|---|---|---|---|
| 启动前 | 1 | 29 | 31 | draft_a8f29dc7 |
| 进程内 hold 后 | 2 | 29+29 | 32 | + draft_2a307498 |
| 退出后 | 2 | 29+29 | 32 | 两条共用同一 origsha 85ce3299 |

两条都是 FINALIZED、同一赢家和金额，但是新 uuid。进程内 60s 签名门挡不住跨进程。

### 447f28b（修复后冻结 EXE）

新 DATA_ROOT：第一次带回放保存 → hold → 退出 → 再次带回放源启动。

| 时刻 | 记录数 | 单位 | 证据 PNG | ID |
|---|---|---|---|---|
| 首次 hold | 1 | 29 | 31 | replayfile_85ce3299 |
| 首次退出 | 1 | 29 | 31 | 同 |
| 二次 hold | 1 | 29 | 31 | 同 |
| 二次退出 | 1 | 29 | 31 | 同 |

日志两次都有 `replay source fingerprint=85ce3299` 和成功归档，磁盘仍 1 条 29 件。

## 未完成

十四类边界仍在。不补 9 条目、不裁定 19 冲突。完成后交付外部审核。
