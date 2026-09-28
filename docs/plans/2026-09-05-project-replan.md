---
type: project-handoff
status: active
updated: 2026-09-14
project: 异环拍卖助手
plan_version: perception-rebuild-2026-09-09-v1
implementation_status: manifest-v2-package
---

# 异环拍卖助手｜完整识别重构与当前交接

> **2026-09-24 当前规划导航：** 主路线为 `YH-MASTER-2026-09-22`；本页下方保留旧识别阶段及证据，不把旧P1/P2/P3当作当前Native五阶段状态。用户已确认“先完成正在执行的1.4图鉴／角色与原图回看，再接续旧藏品识别恢复＋图鉴到局内参考验证”。该增补的唯一正文位于 [Obsidian Decisions](D:/ObsidianLiveSyncTestVault/03-项目与工程/异环拍卖助手/Decisions.md) 的“2026-09-24 藏品识别恢复与图鉴到局内参考规划”；实际进度见同目录Handoff。此处仅作导航，不另立主计划，不表示接续实施已启动或P5已完成。

> 2026-09-20 规划补充：用户先选择 recovery 最新代码，随后要求合并目录；现在唯一仓库为 `D:\yihuanpaimai`，含 V2-2 A/B/C 与 I1 离线集成。下一轮长时间实施使用 [Luna Max Goal 执行包](2026-09-20-luna-max-goal.md)，承接本页业务目标及 canonical 十四类边界；本页历史阶段的“本轮不进入”保留原时点含义。执行包尚未启动，不能据此提升任何验收状态。

> 这是唯一当前执行计划；工程代码与实际证据是事实源。本地原执行规划作为同步副本，不建立平行路线。
> 概览见 [[03-项目与工程/异环拍卖助手/README|项目首页]]，长期决定见 [[03-项目与工程/异环拍卖助手/Decisions|Decisions]]。
> P1/P2已有阶段验收，P3保持PARTIAL；识别基线为桌面第二局23件几何、21自动确证/2待确认。当前证据及唯一下一步见第7节。

## 1. 当前状态、已知产物与证据范围

**整体 PARTIAL，P3 未闭环。** 13:40:43可见17件几何/身份全部匹配，真实双窗口回看、重启及DOM导出通过；仍缺底部，不能称整仓完整。开发局39/39回归通过；识别基线为桌面第二局23/23几何、21正确自动确证/2待确认。人工确认保存、导出往返和部分冻结UI流程已验证，完整试用验收未完成；其他对局、未见对局及实机整链仍未验收。

- 工程事实源：`D:/yihuanpaimai`；最新源码/冻结与分项证据见第7节，历史提交链保存在Raw和写前归档。版本仍v0.68-alpha、Canonical v7。
- 2026-09-14 接手基线：业务/候选曾为 `84e0207` 包。打包修复提交为 `3c270c8`（spec 补打 manifest v2 + 加载探针；未改 catalog_065/求解器）。随后文档提交使当前 git HEAD 为 `f4e58e2`。新隔离候选由 `3c270c8` 构建：`build/isolated_trial_ux_fixes_20260914_3c270c8/dist/异环拍卖助手/异环拍卖助手.exe`，SHA256 `6DCE290A047340813993003151CA4A2E3EAC2332AEE932CE74B5513829ECBD71`。旧 84e0207 包保留未覆盖。e590b74 不是当前候选。
- 上一轮60项相关用例通过；开发局39/39、新录像可见17/17几何及身份正确。新局保存、重读、导出/导入及真实双窗口两次启动回看通过，17张裁图像素正确，DOM名称和重启一致；草稿及覆盖PARTIAL保留。正式历史哈希不变。
- 前轮哈希及DOM检查未覆盖裁切位置，不能作为旧v5裁图正确的证据；前轮6d7db48修复重建局部坐标到源图坐标的转换，旧文件与报告保留，不声称旧用户记录已自动修正。
- 本地`docs/plans/2026-09-05-project-replan.md`仍为本Handoff同步副本；当前下一步只维护在第7节。

### 已通过范围与未完成边界

| 范围 | 已有证据 | 当前结论与边界 |
|---|---|---|
| P1 字段保护 | 22项隔离测试、录像字段对照、真实主窗口/HUD的单字段编辑、确认/清空/恢复自动、两端模式切换 | 已通过其阶段验收；未证明当前日常冻结包已包含 |
| P2 运行与局内 | Node独立计算与数值一致性；超时杀进程、自动恢复；真实忙碌交互；隔离包固定Node；14:40:37录像45/45检查；历史DOM二次重启；DirectComposition交互8项 | 已通过既定阶段验收；未结构化情报仍为PENDING_PARSER，不代表全部情报语义解析完成 |
| P3 几何 | 14:40:37开发录像39/39精确边界匹配，覆盖连续性与端点证据 | 仅该局开发回归几何通过，不等于身份全识别或独立未见对局通过 |
| P3 图鉴接通 | 旧47项接通报告记46项接通、1项未决；之后加入琉璃尾。当前manifest共214项、213项标记接通、1项未决；源卡注册表249张 | 旧“47项全部未接通”已退役；`image2-1-1`仍未决。清单计数不能证明裁图正确、源卡语义绑定或自动身份验收 |
| P3 历史/导出应用验证 | 前轮7bd8bdd使用新packet连续三轮各12/12，39件、39确证/0候选、56文件导出及重启一致；每轮39裁图像素核验通过 | 当前开发局逐件身份和正确裁图的保存/回看通过；不是其他录像、实机滚仓或冻结包验收 |
| 4d5c74c独立复核 | 2026-09-12 14:16记录：导入安全12项、持久化36项、局后捕获导出7项，55/55 PASS，99.290秒 | 同次独立复核复现四项缺口，确立后续修复基线；不称安全彻底闭环 |
| 18b5e23独立复核 | 历史58/58 PASS，113.141秒，另三个反例复现缺口 | 保留为修复前证据；后续4dabf27修复及验证见历史报告，不改写旧结论 |
| 4dabf27历史修复验证 | 前轮65项业务、2项窗口选择、三轮应用各12/12 | 缓存/备份/源图哈希边界仍有效；当时未验证裁切位置，后续6d7db48修复 |
| 6d7db48历史验证 | 17项回归、39/39严格几何、11候选视觉源卡对照、新packet三轮各12/12及39/39像素核验 | 坐标缺陷已收口；当时11候选，后续50d0702补顶部帧、7bd8bdd处理旋转；P3整体仍PARTIAL |
| 后续完整验收 | 其余三段录像全量逐件审计、实机70秒滚仓、疑难详情、原生中断/恢复、独立未见对局、当前源码冻结包整链 | 尚未完成；P4实施中、P5未开始，保持P3 PARTIAL |

证据入口（以下P1/P2及旧P3产物保留为既有证据，本轮修复验证见第7节）：

- P1：`build/diagnosis_20260909/p1-field-authority-video/report.json`、`build/diagnosis_20260909/p1-real-ui/result.json`。
- P2：`build/diagnosis_20260909/p2-real-ui-busy/result.json`、`build/diagnosis_20260909/p2-video-recognition/comparison.json`、`build/diagnosis_20260909/p2-real-ui-history-reopen/result.json`；对应工具 `tools/verify_p2_bundled_node.py`、`tools/verify_p2_dcomp_interactive.py`。
- P3：`build/diagnosis_20260911/p3-warehouse/video_audit_retest_v5/audit_report.json`；真实应用三轮报告位于 `build/diagnosis_20260911/p3-warehouse/isolated_app_real_test/`，文件名为 `isolated_app_real_test_report_run1.json`、`isolated_app_real_test_report_run2.json`、`isolated_app_real_test_report_run3.json`。
- 图鉴：`assets/items/catalog_47_connection_report.json`、`catalog_reference_manifest_v2.json`、`verified_source_card_registry.json`；`catalog_unresolved_47_audit.json`明确标注为接通前历史基线。

### 已知交付包与历史数据

已知 v13：`D:\yihuanpaimai\build\takeover_20260909\friend-app-package-v13\异环拍卖助手\异环拍卖助手.exe`，本轮确认文件存在；产品版本 v0.68-alpha，须分发完整目录。它修复此前主程序与悬浮窗通信卡死，不能视为已包含后续P1/P2/P3源码，也不保证当前进程在线。本轮不覆盖v13。

正式可写历史使用 `%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json`；测试必须使用隔离数据目录。历史列表还能通过 `app/legacy_archive.py` 独立读取旧JSON并投影为LEGACY；旧记录不会因展示而迁入CanonicalHistoryStore或自动取得正式评估资格。P2当时“291条=1条当前草稿+290条旧档案”的记录是当时列表组成，不是当前固定记录数。旧交接中的“自动迁移加载”应更正为“独立读取展示”。

详细历史测试矩阵、原始故障与旧进度保留在 [[90-Archive/Projects/异环拍卖助手/2026-09-12_双向进度整理前/Handoff|本次整理前完整交接]]。

## 2. 已确认的目标与约束

- 用户最新顺序：先完成其余功能与可靠试用流程，再实际使用，之后返回自动识别优化；基础排错由实施方先完成。
- 只做键鼠兼容，沿用场景ROI组路由；聚焦拍卖开始→加载→局内→结算→返回→大厅→补货→开始。加载后直接返回大世界是中断，不生成完成对局。
- 左侧四人的所有可见出价，包括当前价与历回合；中央全部可见情报；右侧所有已显露藏品信息及滚动。
- 局内轮廓、品质、单格品质/不完整轮廓、具体物品按证据层级保留，不能要求用户逐件补录。
- 结算约80秒内优先保存完整仓库证据，允许左键单击疑难物品打开详情；离开后继续离线识别。
- 身份暂未确认时保全证据并列出缺口，是用户认可的超时处理；不是以大量unknown掩盖低召回。
- 悬浮窗“简洁常驻、完整展开”。手动/自动保留并双向同步；结算采集独立开关。
- 保留当前估值数学核心，先修输入契约、缓存、计算归属与展示口径，不用换模型掩盖识别缺失。
- 每件藏品都进入可追溯的数据候选池，后续服务识图和估价优化；结算真值不得泄漏到事前预测。

- **个人投入期限（2026-09-13用户最新明确表达）**：用户仍想把项目做完，但“会给自己最后一周的期限”，同时想把精力转回上课。这是最新收尾时间边界，不得默认为无限续期；详细原话见 [[10-Journal/Raw/2026/2026-09-13/131212-chatgpt-study-priority-final-week]]。
- 日期口径：从9月13日起一周可参考9月20日；“9月20日晚上／9月21日起学习优先”是AI给出的具体化建议，用户尚未单独确认精确时点，不写成已确认日程。本轮没有设置提醒、下发新的开发任务或改变既定实施顺序。
- 期限不等于验收通过：继续按本页原有范围和发布门槛判断，PARTIAL、未入包、P3/P4/P5缺口仍以真实证据为准；本次同步不把项目标成完成、不改变源码和验证结论。

## 3. 实施设计

### 3.1 先保护事实，统一编辑协议

- 主UI/HUD仅提交实际编辑字段，取消整表回传。未识别、映射失败和未编辑空框均“不更新”；主动清空为独立操作。
- 字段保存value、source、status、observedAt、evidenceRefs、matchGeneration、revision及人工保护状态。用户明确确认即使数值相同，也建立保护；提供“恢复自动”。
- 箱型、会场及相同统计范围的同局固定事实，新自动值冲突时保留确认值，记录候选冲突；不直接用新值或null覆盖。
- 回合、倒计时、各席出价按回合/席位/观测时间更新；新回合清当前报价，不清固定事实或历史。
- 所有入口共用命令ID、字段patch、确认回执和最新状态。消息带matchId、sceneGeneration、factsRevision；新包序号不能使旧业务事实变新。
- 完整snapshot只作状态传输/恢复，不能将null作为逐字段覆盖命令。显示默认值不升级为已观测事实。
- 记录每次字段接受/拒绝/冲突的旧值、新值、来源、帧、回合、版本和原因，便于下次精确定位。

### 3.2 统一生产入口，隔离耗时工作

- 一次仅运行一个场景ROI组；拍卖组内部出价、情报、仓库各自有界调度。慢身份任务不能阻挡场景定位、模式切换或截图。
- 捕获/变化检测先保存关键画面，OCR与身份匹配随后处理；稳定内容去重，短暂新情报也保留原图，不能被“只取最新帧”丢弃。
- 统一卡片确认与语义解析，不再由fast路径绕过；移除未接入节流和旧旁路。Replay与live共用实际生产入口，不写只为录像通过的分支。
- 已有JS求解抽为明确导出的纯函数，独立持久计算进程运行，随包携带固定Node运行时，不依赖用户系统安装。移除DOM伪装、字符串替换取函数和双重枚举。
- Main/HUD仅投影同一结果。相同输入只计算一次；新版本替换排队旧输入；超时可终止重启计算进程，采集和持久化继续。
- 对已有求解数值做迁移前后同输入一致性验证，不将宿主迁移与统计模型更换混为一项。

### 3.3 左、中、右完整读取

**四人出价**
- 以稳定seatId建立“4席×回合”矩阵，姓名/本人身份独立补齐，同名玩家不混并。
- 保存当前价、历史回合价与时间证据；零、未出价、不可见不同。
- 中途启动补读画面仍可见的历史格；不把最终当前值伪造为所有过去报价。

**中央情报**
- 保存卡片标题、来源、全文、数字、品质、统计范围、回合、原图。
- 已支持卡片映射统一字段注册表；未支持卡片也显示“已保存、暂未结构化”，进入待补规则清单。
- 新解析器可对旧证据重跑并展示差异，不改写原始观察。所有情报标明是否已进入算法及原因。

**右侧仓库**
- 局内与结算共享跨页物理账本，使用真实像素位移、重叠和格网建立全局位置；不把采样序号当行数。
- 支持不同步长、回滚、裁切、重复同名物、相邻同色物与揭晓变化。匹配歧义保留，不能强行合并。
- 仅见一个品质格时保存局部mask/品质，尺寸身份为空；完整轮廓、品质、候选、确定身份是不同证据。
- 尺寸假设来自完整已核实图鉴和实际边界，撤掉七种尺寸限制；补齐图像—名称—ID独立映射，不按金额差反推。
- 允许新证据纠正错误身份，保留纠正记录，不把EXACT设为不可撤回。
- 局内自动滚动采用可打断小步，仓库稳定且用户未进行出价/其他操作时执行；用户手动滚动同样跟踪。

### 3.4 统一逐件证据与历史接口

- MatchRecord v7新增带独立版本的perception扩展，保存观察索引、字段来源/确认/冲突、跨页物品账本及覆盖缺口。
- 每个观察带唯一ID、matchId、sceneGeneration、时间、来源、ROI/原图引用及哈希、识别器/解析器版本。每件藏品有跨页稳定物理ID、多帧引用、几何/局部可见区域、品质、候选、确认身份与纠正轨迹。
- 原始观察不可变，确认结果为版本化派生。候选、人工审阅和机器确认不混成同一种真值。
- warehouse.slots、settlementItems等旧字段成为兼容投影，避免多套独立可写列表；修通v1/v2采集、复核、保存与导出适配。
- 旧记录向后兼容读取，缺失视为未采集，不自动提升旧候选。保持测试数据隔离、原历史备份和FINALIZED的事前事实/预测不可被赛后重识别覆盖。
- 草稿立即保存，原图与派生识别允许按原matchId安全续写；退出、重启后可继续重识别。导出为对局+manifest+相对路径原图+逐件结果，不导成孤立散图。
- 原始截图删除/撤销、空结算留DRAFT、导出选择等已有能力保留并在新接口下回归，不因重构丢失。

## 4. 结算80秒策略

首次检测到结算页起计时，同时读游戏剩余时间，以更早截止时间为准。以下是待验收目标，不是当前已达到的性能。

| 预算 | 执行 |
|---|---|
| 0–5秒 | 保存首图，定位仓库/倒计时；账单终态识别独立运行 |
| 最迟30秒 | 优先采完整仓库原图：定位顶部，逐段滚动，稳定帧落盘，保留重叠，确认底部 |
| 全仓完成后至65秒 | 后台识别已采物品；疑难项左键打开详情，读名称/品质/价格，关闭并核对原位置 |
| 65–70秒 | 必要补页、账单复核、持久化检查并关闭详情 |
| 70秒以后 | 停止新增主动操作，预留退出余量；离开后继续离线识别 |

- 每页先落盘再昂贵匹配；账单不等待仓库完成。
- 顶部、底部、中间连续覆盖都证明后才显示“整仓截图完整”；物理分件、品质、身份完成度分开。
- 优先疑难/缺参考/冲突物品详情，所有品质都纳入，不因低价值忽略。
- 输入前后核对游戏前台、场景、目标位置与剩余时间；只执行采集所需操作，不触发出售等状态变更。
- 失焦、用户接管、滚动不动时暂停；恢复后补缺页。同局首次失败不永久禁止重试。
- 时间不足仍保存已采证据和缺口；未知不算0，不用总价凑身份。
- 结算金额按标签位置、动画终态、多帧一致性核对；支持0收益、负收益、不同字段相等，不按数值去重丢字段。
- 结算记录与返回/补货流程分离。仪器配置不等于消耗，点击补货不等于成功；本局用量及上一局遗留按证据归属。未观察到成功时保留待核对，不自动购买。

## 5. UI、悬浮窗与算法选项

- 保留现有外观框架，重构数据与运行边界，不重新制作整套皮肤。
- 主对局页常驻四席出价表、情报时间线、仓库地图/采集进度，估值为摘要+详情。
- HUD常驻阶段、手动/自动、识别健康、关键情报与有效估值；完整展开约束、组成候选、价值拆分及缺口。
- 采集/OCR/身份/估价/保存分别显示状态和更新时间；未检测结算、账单未稳定、仓库未采完整、身份未完成分别提示。
- 两端共用字段定义/校验/目录/单位，编辑有回执。忙碌状态只由真实任务驱动，旧估值标注对应旧事实，不继续冒充当前正式建议。
- 所有情报显示“已参与估价/仅记录/待解析”；每个参数显示当前生效值。补齐数量、占格、已知藏品、成本和出价等适配与缓存键，未支持的约束明确列出。
- full_shadow/partial_shadow/structural_only是自动数据支持状态，不是可随意切换的算法。部分历史条件P50不放在正式整仓价格位置。
- 保留现有P20/P50/P80数学口径，宿主迁移先保证数值一致。
- 用户最新决定不设最低利润或收益率目标，预期利润1也算正收益；不再新增收益率入口。显示预期盈亏、全成本保本价和边际追价参考，说明分位依据与估算性质。旧目标公式只保留历史回放兼容，不作为当前UI门槛。
- 没有goldAvg的估价资格仍为独立未完成能力，不制造默认均价或用结算总价反推；新约束不足时正确展示事实与缺口。
- 名称/价格前缀联想与“/”候选语法，两端使用同一目录和解析器。

### 每件藏品用于以后优化

每件自动进入可追溯候选池，确认单件可用于单件识别/价格统计；整仓覆盖与组成符合要求时才用于整仓分布评估。未知继续保留并重识别，不丢整局。打通样本导出、离线评估和差异报告，不在实战中悄悄改参数。训练/调参与评估按对局和时间分开；事后结算不得回填成当局事前情报。单局总结由已持久化记录确定性派生，不能补猜。

## 6. 实施顺序与发布门槛

| 阶段 | 交付 | 当前状态 |
|---|---|---|
| P0 文档 | 本计划、当前首页、决定与旧内容归档 | 已写入 |
| P1 事实保护 | 逐项录像对照；箱型清空/整表误写回归；字段patch/权威/日志；主界面与通信纵向 | 22 项隔离测试 + 录像对照 + 真实主窗口/悬浮窗 PASS；未打包 |
| P2 运行与局内 | 统一观察入口、计算隔离；四席/全文到UI和历史 | 既定阶段验收通过：计算隔离、隔离Node包、基准录像四席（含0）、历史DOM重启及忙碌恢复；不代表所有情报解析或日常包完整验收 |
| P3 全仓 | 跨页账本、80秒采集、详情、重启历史与导出 | PARTIAL：基准开发局几何39/39；参考清单214项中213项标记接通、1项未决；完整身份、证据正确性、其余录像及实机滚仓未验收 |
| P4 UI/参数 | 简洁常驻/完整展开；逐字段实际生效与两端同步 | 实施中：按用户取消最低收益目标；数量/金均/叫价清空的实际双端回执与合成盈亏DOM边界通过；其余参数/UI待补齐 |
| P5 完整验收 | 冻结包连续回放、独立新对局、真实输入采集与性能 | 未开始 |

每阶段做真实纵向验证，不再只靠单组件通过数。先处理最早阻断根因，再继续本计划下游；局部通过不能标整局完成。

完整自动识别正式发布仍必须满足下列要求；按最新顺序先交付人工确认可用的隔离试用版，自动识别相关门槛留待试用后验收，不据此宣称整项目完成：
1. 原录像逐席、逐回合、逐情报、逐件人工对照，走真实KeyboardAuctionPipeline/worker/原生Main与HUD/隔离历史；不只抽Q和账单，不向每帧注入已识别状态。
2. 可明确判读的出价、全文与账单逐项一致；物品无静默漏件、重复或串身份；有独立参考/可读详情的逐件核对正确。
3. 已有参与调参录像只作开发回归；另至少3局未参与调参完整对局验收，分别报告误识、漏识、未知和覆盖。失败样本进入回归后不再冒充未见数据。
4. 覆盖箱型读空/未知/错值、只改Q、确认相同值也保护、主动清空/恢复自动、两端同时编辑、手动/自动、回合切换、旧包晚到、跨局、断线、崩溃恢复。
5. 覆盖半揭示单格、相邻同色、同名多件、不同步长和回滚、裁切、白边滑块干扰、空底部、失焦/用户接管、超时、倒计时提前结束。
6. 性能目标：忙碌时控制确认P95≤0.5秒；稳定可读出价到显示P95≤1.5秒；情报结构化P95≤2秒。OCR/传输/显示耗时分别量，不用消息0.25秒冒充识图0.25秒。
7. 真实冻结包完成滚仓→详情→70秒停止主动采集→保存→关闭重启→历史逐件回看→含图导出。fake OS、按钮返回或单帧TOP不能替代实机。
8. 跨电脑/目录导出包可按manifest核对原图和物品引用；旧数据不被测试污染，未完成身份和证据缺口不丢。
9. 核心链通过后才恢复日常使用。不能让用户连续十几局承担基础排错，也不能以大量unknown宣称已满足完整识别。

## 7. 当前修复与验收入口

### 7.1 当前结论与基线

当前隔离候选是 `3c270c8`：`D:/yihuanpaimai/build/isolated_trial_ux_fixes_20260914_3c270c8/dist/异环拍卖助手`，EXE SHA256 `6DCE290A047340813993003151CA4A2E3EAC2332AEE932CE74B5513829ECBD71`，profile=`isolated-trial-v1`。旧候选 84e0207 包保留。上轮报告：`USER_CONFIRMED_FACT_KEYS` 40 项、DATA_ROOT 指向「异环拍卖助手试用\data」；本轮有独立前后快照，不复用旧 1602 口头结论，也不把可启动写成识别完成。e590b74 只作历史冻结包。整体 PARTIAL：P3 保持 PARTIAL，P4 实施中，完整试用/P5 未完成。

先完成可用流程供用户试用，再优化逐件匹配；自动判断本人拍下是关键能力，不依赖每局人工确认。本人ID是赢家栏游戏昵称，可一次保存、修改和清空；稳定赢家读数与配置精确比较，名单冲突保持未知。未配置且纯结算晚启动缺名单时未知，不能靠金额/领先/出售勾选猜测。真实本人获胜及完整连续归属仍待验；缺本人实录不阻塞其他实施。

已接人工审阅/修改保存/历史重读/含图导出、HUD归属、目标收益0、成本及部分数量/面积约束、默认隔离试用数据。自动识图基线仍第二局23件几何、21自动确证/2未知；人工确认和性能修改不提高此成绩。

#### 2026-09-14 累计纠正与证据层级（外部补记）

来源：用户迁入本对话的完整交接及其转发的 Grok 本轮报告，原交接见 [[99-系统与后台/AI对话与记忆/Raw/2026/2026-09-14/230607-chatgpt-v1vipa|接手原话]]。以下不表示本次外部审核亲自运行过 Windows 工程。Grok 本轮未重跑整套验收；旧表格中的 PASS、未入包及测试数量均属于各自历史时点，不自动成为当前候选的全项结论。

| 累计事项 | 当前应保留的事实与纠正 | 证据层级与未完成边界 |
|---|---|---|
| 手动/自动事实合并 | 已报告保护规则、Q、六品质数量/均价/占格/已知名称；自动出价与情报继续更新，新局清空保护。系统费用、结算派生字段和普通福利 OCR 不应被旧手填永久锁死。USER_CONFIRMED_FACT_KEYS 为 40 项，32 是旧报告笔误。 | 用户交接转述实施方修复；40 项本轮按已报告事实保留。不可据此声称所有实战竞态通过。 |
| 游戏窗口 | 真实客户端为 htgame.exe / UnrealWindow；进程匹配、窗口发现与抓取曾修复。历史 HWND 不能当当前固定句柄。 | 用户交接转述实施方报告；本次未重新运行窗口采集。 |
| 出价记录 | 同回合多次 OCR 观察合并成一条用户可见出价记录。 | 已报告修复；多次观察不冒充多条业务出价。 |
| 结算流程 | 已报告千分撇号金额解析、赢家与竞拍帮手分离、结算摘要默认只读、修正入口折叠、不可知费用取消普通手填，以及同局归档幂等。 | 实施方累计报告；组件测试、打包验证、实战反馈分别核对，不合并为整套 PASS。 |
| 13:07 帮手 | “小哎”为错误 OCR；已报告改用用户已有 8 人角色素材与名单校验，对应样本匹配为“小吱”。 | 单一样本及修复报告，不证明其他角色全部识别完成。 |
| 福利到账语义 | 用户明确：最终结算画面“奖励金获取”右侧数字就是应记录的到账值；1,585 与 101,350 不得一概当作“社交分享噪声”排除。 | 用户明确业务澄清；不能用旧助手解释覆盖。OCR 实现是否覆盖所有画面仍须证据。 |
| 19:32 对局 | draft_ffa8cc599a7146dc98ed12ffe94ae399 后续报告买受人为“墨初”，不是早先“伊尔”；报告称该局可归档，27 件 reviewUnits/crops 可保存重读。 | 实施方个案报告；保存 27 个审阅单元/裁图不等于 27 件自动身份全正确，更不等于所有对局完成。 |
| 13:07 “结算两次” | 后续核查报告为上一局草稿加下一局空白占位草稿，不是同一物理局两次 finalize。 | 用户实战困惑与实施方结构核查并存；不能因此抹掉空草稿体验问题，也不宣称该体验已修好。 |
| 历史备份误认 | history_delete_backup_v1.json 是 15:21 删除历史前的旧备份，不含 19:32 新局，不能称为 20:28 切片回填前的有效现场备份。 | 用户纠正的备份时间线；本轮笔记备份不补足那次历史数据迁移的现场备份。 |
| dirty build 与候选 | 曾用未提交修改覆盖旧 1610400 目录的 dirty build，不可作正式基线；后续已报告以新提交、新目录重打包。当前候选仍为本节所列 84e0207 包，审计 HEAD 为 e1536c4；有新交付时核实前进，不 reset。 | 实施方打包/提交报告；当前 clean 不抹去历史 dirty build，也不等于功能验收。 |

上轮隔离证据：profile=isolated-trial-v1；DATA_ROOT=`C:\Users\Administrator\AppData\Local\异环拍卖助手试用\data`；生产目录当次启动前后检查 1602 个文件，added/removed/changed 均为空。以上为用户转发的上轮实施方证据，本次未复测；不能推广为所有运行永久不污染或整套识别通过。

协作：用户转发任务与结果，Grok 当前实施，外部审核负责审阅与补记；达到用户设定的 70% 周额度切换点后由用户确认切换 Gemini，不声称能监控额度，不同 Agent 不并行改同一工作区。用户已打完并要求修改时，优先处理已有证据，不再要求重打一局承担基础排错。

### 7.2 实现与证据约束

- 同记录、同证据包的纯自动摘要可接续人工审阅；保留未处理的自动确证及其AUTO来源。逐件名称与确认状态和摘要原子保存；事务内核验旧摘要指纹以防并发覆盖。V2可恢复人工选择，修改前摘要保留到warehouseIdentityReviewHistory，保存成功更新会话基线；V1保持原不可覆盖契约。人工暂缓不被自动重新确认，未处理未知不冒充人工暂缓。
- 用户纠正：底部品质颜色控制出售勾选，自己拍下默认勾选除红色外的所有品质；逐色取消后图标标记才消失，并非自动揭示。截图 `docs/evidence/settlement-quality-selection.png`。采集不能依赖先取消勾选或等待标记自行消失；红色默认不勾选不代表物品缺失。
- TOP不证明无遮挡或勾选状态；窗口移动后的旧裁区不证明真实滚仓。仍需验证默认勾选、用户接管、跨页、详情与超时恢复。

### 7.3 已有验证及范围

| 内容 | 证据及范围 |
|---|---|
| 公开情报事件准入与生命周期隔离 | 提交链 `dd12561`、`e8106e2`、`ee345c0`、`5231ca6` 外部审核判定PASS。打通独立物理双帧确认→事件准入→CurrentMatch→规范化持久化→归档回看纵向链；接防篡改强校验（拒绝FREE/0/伪造来源）、规范重构丢弃脏键、生命周期隔离重置_intel_ledger与自然离场清空。`tests.test_public_intel_ledger` 26项PASS、8套综合回归47项PASS、`tests.test_intel_card_evidence_v1` 22项PASS。`tests.test_match_trunk` 双边对照证明2项失败系既有测试债无新回归。`AUCTIONEER_PUBLIC != FREE`，费用分类保持UNKNOWN/None，单局跨回合内容去重；未入新包，实机两物理帧素材仍缺。`10-Journal/Raw/2026/2026-09-13/132500-codex-intel-event-admission-lifecycle.md` |
| 无数值卡片记录 | `c5a1e22`两条提取路径/当前帧传递/保存恢复/历史回看已接，31项回归及源码7次历史切换PASS；未冻结、跨回合事件未接。`docs/reports/2026-09-13-intel-card-readings.md` |
| 公开情报标题来源 | `20fc848`真实同值仪器/公开卡标题区分，来源标签保存/恢复且不改变费用；29项回归PASS，未冻结。独立多帧事件确认与无数值卡仍待接；`docs/reports/2026-09-13-intel-public-title-source.md` |
| 情报历史回看冻结 | `b45c50c`统一包含规则提示/证据保存/历史回看，7项回归、源码及同包历史六次切换、同包规则三步PASS。免费来源仍未知；`docs/reports/2026-09-13-intel-history-frozen.md` |
| 情报原始证据保存 | `0f2caa0`保存/恢复ledger与帧来源，缺省保留、显式清空、证据变化更新；18项回归PASS。免费来源仍UNKNOWN，未生成免费事件，已纳入b45c50c隔离包。`docs/reports/2026-09-13-intel-evidence-persistence.md` |
| 免费情报规则提示 | Main/HUD规则可用性与已观察事实分开，3项回归/源码实际三步切换PASS。`docs/reports/2026-09-13-free-intel-rule-hint.md`；提示已纳入b45c50c隔离包；免费事件准入/持久化/可靠来源识别未接 |
| 私人上限/次数界面冻结 | e590b74同EXE两字段填写/0/清空/非法反馈/重启历史PASS；15项传递/归档回归PASS。`docs/reports/2026-09-13-dark-controls-ui-frozen.md`；非游戏次数OCR验收 |
| 私人上限/次数传递 | CurrentMatch标准bidding保存/恢复、双适配器、覆盖与缓存/生产快照接通，8项回归PASS。`docs/reports/2026-09-13-dark-control-transport.md`；已接并纳入e590b74冻结 |
| 隐藏金额显示 | 9737454两端隐藏标记/输入收起及普通恢复、旧叫价保留，源码实际三步PASS、4项回归PASS。`docs/reports/2026-09-13-dark-bid-display.md`；私人上限/次数与冻结未接 |
| 隐藏叫价计算保护 | 修dark旧叫价仍参与盈亏/弃拍；双别名4种金额直接/生产对照与标准恢复、共3项回归PASS。`docs/reports/2026-09-13-dark-bid-decision-guard.md`；显示/私人上限/冻结未接 |
| 归属收支展示 | 8组Main/HUD原生投影一致、模型合计5项PASS；d458188实际历史9组本人/他人/未知/零/收益1展示PASS。`docs/reports/2026-09-13-accounting-ownership-presentation.md`；全部合成测试证据，非游戏归属识别 |
| 福利反馈与冻结 | d458188同包4组正常输入+两端8组非法反馈/保留/修正、重启历史PASS。`docs/reports/2026-09-13-welfare-feedback-frozen.md`；归属原生投影/合成历史展示已验，非游戏局 |
| 福利实收界面/归档 | c924545主窗口/HUD实收与收支、历史详情及归档到账去重已接；源码四组双端/重启历史PASS、19项回归PASS。`docs/reports/2026-09-13-welfare-receipt-ui.md`；已入d458188，未真实到账OCR验收 |
| 福利实收模型 | CurrentMatch/标准记录实收保存及独立结算价值净收益模型，9项回归PASS。`docs/reports/2026-09-13-welfare-accounting-model.md`；UI/原生/历史/归档已接，冻结未验 |
| 其余词条非倍率核对 | 4词条中英文×费用0/1200共16组生产对照PASS；efd6480同EXE9步实际切换/恢复PASS。`docs/reports/2026-09-13-remaining-condition-semantics.md`；福利实收/隐藏出价/免费事件专属链仍未完成 |
| 闪耀界面与冻结 | efd6480同EXE双端五组输入/清空/矛盾/未知、词条切换与重启历史回看PASS；截图已查看。`docs/reports/2026-09-13-sparkle-evidence-ui-frozen.md`；非真实游戏局验收 |
| 闪耀证据传递 | a11ed91 CurrentMatch标准记录/双适配器/实时覆盖/缓存与inputHash接通，证据计算免金色均价门槛；6项回归PASS。`docs/reports/2026-09-13-sparkle-transport.md`；已纳入efd6480冻结 |
| 闪耀严格证据范围 | 29fe690真实宝石池/精确名称/数量与总数一致/安全整数校验，生产快照15组新增、9项回归PASS。`docs/reports/2026-09-13-sparkle-strict-bounds.md`；已纳入efd6480并接界面/保存/显示 |
| 闪耀限制冻结 | 2a77f00同EXE实际词条切换/恢复与包内三别名直接/生产入口回归PASS。`docs/reports/2026-09-13-sparkle-frozen.md`；证据上下界仍未接 |
| 闪耀之心生产限制 | e44836a源码禁止未知宝石概率下整仓分位/推荐线，直接及生产入口/别名8项回归PASS；UI切换恢复通过。`docs/reports/2026-09-13-sparkle-production-guard.md`；已入2a77f00，非概率证据边界仍未接 |
| 布局及编辑冻结 | ac3cac3同EXE四阶段布局、600×480滚动到底、17项数值往返/0/清空PASS。`docs/reports/2026-09-13-layout-frozen.md`；非全DPI/鼠标验收 |
| 悬浮窗自适应布局 | 085b498自然高度/滚动/深色输入/hidden修复；源码四阶段尺寸与底部可达、隐藏元素检查PASS。`docs/reports/2026-09-13-hud-layout.md`；已入ac3cac3，非全DPI |
| 金紫词条倍率实测 | 同052dbb9包，金/紫各五阶段词条切换+均价改变，生产可行/冲突及两端提示10/10 PASS。`docs/reports/2026-09-13-condition-multiplier-ui.md`；非所有词条/键鼠 |
| 连续编辑/24组冻结 | 052dbb9同步解除HUD回传抑制；源码与同EXE八类24组计算及两端冲突/恢复PASS。`docs/reports/2026-09-13-input-guard-frozen.md`；非所有竞态/键鼠验收 |
| 八类参数实际计算/红格漏传 | a29678b补Python/JS红格映射；源码真实24组可行/冲突/清空及两端提示PASS，9项回归PASS。`docs/reports/2026-09-13-red-grid-calculation.md`；已入052dbb9 |
| 主窗口预测交接与冲突冻结 | 21d6ee7同EXE实际输入valid/no-match/valid，Main与HUD冲突出现/恢复一致PASS；1项发布回归PASS。`docs/reports/2026-09-13-main-constraint.md`；非全参数 |
| 空历史实际约束计算 | f41d50b不再跳过结构计算；真实输入蓝格2/1/清空，生产valid/no-match/valid及HUD冲突出现/消失PASS。`docs/reports/2026-09-13-empty-history-constraints.md`；已入21d6ee7，非全参数 |
| 高级数值及名称双端冻结 | 62cb065同EXE17字段Main→HUD、HUD修改/0/清空→Main；三色名称往返/清空复验PASS。`docs/reports/2026-09-13-numeric-dual.md`；不代表全字段计算 |
| 低品质名称双端 | 49e3d10源码三色Main→HUD、HUD候选/重复→Main及清空DOM验证PASS；60390c4状态回归PASS。`docs/reports/2026-09-13-low-known-hud.md`；已入62cb065，非真实游戏键鼠 |
| 六品质名称历史与冻结 | 225286d同EXE六色输入保存/重启点击历史表达式一致；清空后重启均未记录，PASS。`docs/reports/2026-09-13-known-history.md`；非HUD/全计算链 |
| 低品质名称输入 | 8c01485源码三色DOM候选/重复表达式回传与落盘、非法输入反馈、删除清空通过；14项回归PASS。`docs/reports/2026-09-13-low-known-ui.md`；已入225286d |
| 品质数值界面与历史 | e0492f4冻结17项填写/保存、第二实例历史点击一致及清空PASS；新增九项品质数值入口。`docs/reports/2026-09-13-quality-numeric-ui.md`；非所有字段计算/HUD全链 |
| 低品质已知名称联合及冻结 | 源码14项、包内Node六项回归PASS；新增36组名称/候选/重复件对照。同EXE双窗口四次启动与编辑保存通过。`docs/reports/2026-09-13-low-known-identity.md`；e8f6dbe，非全部GUI参数链验收 |
| 低品质已知名称传递 | Python/JS adapter、计算参数/缓存及嵌套清空已补，6项回归PASS。`docs/reports/2026-09-13-low-known-transport.md`；后续名称求解已接并入e8f6dbe |
| 紫红未知面积 | 按图鉴/已知候选组/紫均价生成面积域，联合金色实际组合及低品质总格检查；7组新增生产对照、共12项回归PASS。`docs/reports/2026-09-13-high-tier-area.md`；已入e8f6dbe |
| 低品质跨色总面积 | 高品质面积已确定时联合(count,area)集合，7组新增生产对照、共11项回归PASS。`docs/reports/2026-09-13-low-tier-total-area.md`；已入e8f6dbe |
| 低品质参数与包内运行时 | e09543f包内Node/JS跑38组案例通过；源码Python映射、覆盖/清空及缓存变化通过；不是冻结GUI全链。`docs/reports/2026-09-13-low-tier-transport.md` |
| 未知低品质件数 | 有总件数/面积有限上限时枚举可行件数，跨色件数和一致；8组新增生产对照、共9项回归PASS，原ctx不变。`docs/reports/2026-09-13-low-tier-unknown-counts.md`；已入e09543f |
| 低品质联合约束 | 源码已接已知件数的蓝/绿/白均价和面积联合检查，21组真实图鉴生产runtime对照，连同原有共8项回归PASS；`docs/reports/2026-09-13-low-tier-joint.md`；已入e09543f |
| 空草稿修复 | 2aae16c冻结真实4次启动通过：空启动/只读历史不改文件，实际编辑保存，重启只读不添记录；`docs/reports/2026-09-13-frozen-empty-draft.md` |
| 高级表单与历史 | c004175冻结8字段填写/回传/清空；02ae8fb冻结第二实例点击历史8字段正确。`docs/reports/2026-09-13-advanced-fields-reply.md`、`docs/reports/2026-09-13-advanced-history.md`；不代表全部求解生效 |
| 估价/出价/归属与保存 | 95929c4冻结真实录像8点→他人归属→归档证据重读；同包真实双端进程恢复。`docs/reports/2026-09-13-frozen-bid-recognition.md`；非完整连续、非本人获胜 |
| 延迟定位与修复 | 估价ROI纠偏、四席视口补偿、单字裁图已入包；源码局内8次处理23.092→16.783→14.591秒，单次开发片段非P95。`docs/reports/2026-09-13-bid-glyph.md` |
| 提示与存储恢复 | 4ae2f5f冻结收起HUD错误可见；7e18ea2冻结真实文件占用失败/释放/重试及晚结算证据通过；各报告保留原范围 |
| 基础试用流 | 15c9911同EXE昵称保存重启、成本、39件历史/含图导出通过；默认试用数据和日常哨兵隔离已验；`docs/reports/2026-09-12-consolidated-trial-checks.md` |

当前包继承上述改动，但历史验证不自动扩为最新包全项通过。失败日志保留。源码4项空草稿回归包含显式0/正数/证据、拒绝空写入及已保存记录清空刷新；不删除已有空记录。

### 7.4 唯一下一步与边界

**当前外部审核（2026-09-15，879dfed 交付后）：接收 Fix A/B 的已报告修复与来源往返闭环，也接收第 10 项“酷辣辣辣条”单项规范 ID 修复。整体仍 PARTIAL；此前已完成的 v2 冻结加载、首次离线识别→正式保存→重启 GUI 回看、同文件重复回放去重均继续保留，不再重复派工。** ChatGPT 本轮依据用户转发的 Gemini 完整执行记录审核；未亲跑 Windows 工程、未复算 EXE 哈希，也未重新逐像素审阅源卡。实施方仍为 Gemini，用户转交任务与结果，ChatGPT 外部审核。

#### 当前基线与证据范围

- 最新上报文档/报告 HEAD：`559867a7f7e0eefe053d6530913fba2e1a69a614`。
- 构建提交：`879dfed5ae7aa93c8dc71caf04486df94bc22566`。
- 当前隔离候选：`build/isolated_trial_ux_fixes_20260915_879dfed/dist/异环拍卖助手/异环拍卖助手.exe`。
- EXE SHA256：`B72151685AD319EFF6777D86842CB498CAFD38F3091A55DA9A04C9F4AD3AD0DD`（实施方复算；外部未复算）。
- 隔离 profile：`isolated-trial-v1`；旧候选 `df58589`、447f28b、a10f167、3c270c8、990f53f、84e0207、日常 v13 均据报保留未覆盖。
- 本轮上传执行记录显示 Gemini 已在本地 Vault 写入 879dfed 证据与备份，但当前 Obsidian 连接器恢复后仍未看到这些新 Evidence 文件；因此本节按用户转发证据补记，不假称已从 Vault 原件回读。

#### 本轮接收结果

1. **Fix A/B 收口保持有效。** 去重不再用裸 `origsha` 作为对局键；不同 matchId 共用同一 blob 的 live 记录保持独立，live/replay 也不混并。`dataOrigin` 的 live/replay/test 来源门禁已通过同质量准入对照；后续来源保真往返覆盖保存→重读→导出→导入→正式消费：live 保持 live 并可正式准入；replay/test 保留来源并因 `DATA_ORIGIN_NOT_LIVE` 被拒；旧缺来源记录保持缺失并因 `DATA_ORIGIN_MISSING` 被拒。A/B 不再是当前待办。
2. **第 10 项“酷辣辣辣条”单项修复接收。** 红色 1×2 独立源卡在 `visual_catalog_v2` 的主 ID 已规范为 `visual-latiao-1x2`，`verified_source_card_registry` 对红项的无条件 `image3-0-2` alias 已解除；白色 1×1 继续使用 `image3-0-2`，未引入新的白色 ID。物理消歧只接受品质与网格尺寸等前置观测，不以价格作为识别条件；缺上下文和交叉矛盾 fail-closed。GT 与 `catalog_065` 保持未改。
3. **专项与冻结结果。** Gemini 报告 9 项辣条专项用例通过、视觉图鉴身份回归 36 项通过、runtime visual catalog precheck 107/213 接收、offline archive 9 项通过、来源往返通过。冻结 `879dfed` 在已有 144037 结算原图上保存的第 10 项为：名称“酷辣辣辣条”、`selectedCatalogId=visual-latiao-1x2`、红色、1×2、价格 280000、CONFIRMED/EXACT_IDENTIFIED；整局仍为 29 reviewUnits。同源回放计数继续 `[1,1,1,1]`，来源为 replay，正式评估因来源被拒。
4. **证据边界。** 上述为实施方执行记录与机器摘录，不能扩大为全图鉴、未见对局、真实 70 秒滚仓或性能通过。首次闭环的 `identity_frame_ms=54525` 仍保留为历史单次阶段耗时；没有本轮性能优化。

#### 唯一下一步

**回到用户较早明确的主线：完成“可用隔离试用流程”的端到端体验验收。先用现有 879dfed 候选做真实用户视角的隔离试用，不再继续扩第 10 项或重开 A/B。**

给 Gemini 的下一轮范围：
- 从当前真实 HEAD 和 `879dfed` 候选接续；先核工作区与候选身份，不 reset，不覆盖旧包或用户历史。
- 使用独立临时 `YIHUAN_DATA_ROOT`，真正启动冻结 EXE，从用户可见 GUI/HUD 走一遍最小可用流程：启动→进入/创建一局→手动与自动事实展示→已有离线素材触发识别→主窗口/HUD同步→结算保存→历史打开→关闭重启回看→导出/导入到另一隔离目录→新局/清空/恢复。已有成熟入口直接复用，不要求用户重新打一局，不执行真实游戏键鼠输入。
- 把“能看、能改、能保存、能重开、能导出导入、不污染日常数据”作为本轮产品验收重点；识别准确率继续沿已有样本，不为本轮强求全仓 39 件或新图鉴覆盖。
- 对第 6 节和原十四类边界逐项标记：本轮实际覆盖了什么、未覆盖什么。尤其检查底部品质出售默认勾选、草稿/FINALIZED 展示、空历史/新局占位、手动保护与自动更新、历史图片引用是否在试用流程中造成明显阻断。
- 若出现用户可见阻断，允许只修最早阻断和必要的 UX/传递/持久化问题，并加针对性回归；改代码后先提交、新目录打包，再用冻结候选完成同一流程。若需要真实游戏输入、完整滚仓、重大 schema/算法变化，则列为超范围，不自行扩展。
- 交付一份步骤化 E2E 证据：每一步预期/实际、截图或 DOM/日志、DATA_ROOT 前后、历史记录数、导出导入结果、完整 HEAD/构建/SHA，以及仍未完成项。完成后交外部审核，不自动进入性能优化或全图鉴阶段。

第 1 节两条历史说明、第 7.1 累计纠正表、第 6 节发布门槛均不改。原有十四类未完成边界继续有效；P3 仍 PARTIAL，完整试用/P5 未完成。六品质联合求解与 Historical Shadow 保持不变，不补 9 条目、不全面裁定 19 条冲突、不改匹配阈值/求解器，不做 Arena/未知红 PMF。

本次外部补记写前备份：`99-系统与后台/Archive/Legacy-90-Archive/Projects/异环拍卖助手/2026-09-15_155300_879dfed外审同步前/`。

#### 879dfed 候选完整隔离试用 E2E 体验验收实施交付（2026-09-15）

**实施方（Gemini）交付：完成针对冻结候选 `879dfed` 的完整隔离试用流程 16 步端到端（E2E）体验验收。自动化驱动真实 EXE 进程与真实双窗口（Main + HUD），全流程 16 步严格断言全部 PASS。整体状态保持 PARTIAL。**

##### 1. 上报基线与环境身份
- 最新上报文档/报告 HEAD：`559867a7f7e0eefe053d6530913fba2e1a69a614`。
- 构建提交：`879dfed5ae7aa93c8dc71caf04486df94bc22566`。
- 候选构建：`D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_879dfed\dist\异环拍卖助手\异环拍卖助手.exe`。
- EXE SHA256：`B72151685AD319EFF6777D86842CB498CAFD38F3091A55DA9A04C9F4AD3AD0DD`。
- profile：`isolated-trial-v1`。
- 运行驱动脚本：`build/e2e_trial_20260915/run_e2e_isolated_trial.py`。
- 机器证据：`build/e2e_trial_20260915/e2e_trial_report.json` 与 `Evidence/2026-09-15-e2e-isolated-trial/e2e_trial_report.json`。
- 详细验收报告：`docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md` 与 `Evidence/2026-09-15-e2e-isolated-trial/2026-09-15-e2e-isolated-trial-acceptance.md`。
- 导出产物：`build/e2e_trial_20260915/trial_export_bundle.zip` (8,929,516 字节，包含 manifest、records.json 及 33 个原图/切片 blob)。

##### 2. 16 步全流程逐步验收结果
| 步骤 | 步骤名称 | 预期行为 | 实际运行结果 | 判定 |
|---|---|---|---|---|
| Step 1 | 启动主窗口与HUD | 双窗口正常渲染，WebSocket 桥接建立，无崩溃 | Main HWND=2952278, HUD HWND=15144162, WS 连接成功 | PASS |
| Step 2 | 空历史/新局初始状态 | 历史列表为空，无幽灵草稿，空状态占位提示可见 | DOM emptyState=True, badge='0 条', 磁盘 0 条记录 | PASS |
| Step 3 | 创建/切入活跃对局 | 生成活跃草稿 session，对局生命周期为 DRAFT | matchId=draft_1b134554..., lifecycle=DRAFT, 标题正常 | PASS |
| Step 4 | 手动输入可填事实 | 主窗口/HUD输入框可输入事实并持久化为草稿 | 输入 q=21, 蓝格=3, 红格=1, 场地=珊瑚, 宝箱=琉璃, 均价=64836 | PASS |
| Step 5 | 手动保护与自动更新并存 | 手动修改锁定，清空状态可清，restoreAuto 解除锁定 | 手动输入置 protected=True; 清空置 cleared; restore 成功解除 | PASS |
| Step 6 | 主窗口与HUD同步联动 | 双端状态实时一致，无状态分叉与延迟撕裂 | Main q=21 同步至 HUD q; HUD 宝箱同步至 Main 宝箱 | PASS |
| Step 7 | 触发结算离线识别 | 离线素材 144037 识别完成，产出 29 reviewUnits | 耗时 48.6s, 第10项 visual-latiao-1x2 280k CONFIRMED/EXACT | PASS |
| Step 8 | 保存结算记录 | 结算记录落地 sqlite/json，生命周期变更为 FINALIZED | lifecycle=FINALIZED, dataOrigin=replay, 落盘成功 | PASS |
| Step 9 | 历史列表与单件核对 | 历史列表渲染已结算记录，展开单件卡片与切片可见 | 渲染已结算记录，第10项切片存在且 SHA 5e1b9aba... 一致 | PASS |
| Step 10 | 正常退出 | WM_CLOSE 正常退出，无死锁孤儿进程残留 | 进程干净退出，PID 存活检查确认已完全终结 | PASS |
| Step 11 | 重启并重开历史 | 冷启动能准确读取历史，DOM 与磁盘严格一致 | 重启展示 2 条记录 (1 draft + 1 finalized)，无幽灵空草稿 | PASS |
| Step 12 | 导出当前记录 | 导出包含 manifest、records 与图片资源的完整 ZIP 包 | Native 导出 trial_export_bundle.zip (8.9MB, 35 文件) | PASS |
| Step 13 | 导入到全新隔离 DATA_ROOT | 冷启动空白实例 2，无损导入导出包 | 实例 2 (0条初始) 通过 postNative 成功完成包导入 | PASS |
| Step 14 | 在新目录核对导入数据 | 记录数、审查单元、切片哈希跨环境完全一致 | 2 条记录、29 件商品完全恢复，辣条切片存在且哈希一致 | PASS |
| Step 15 | 新对局/清空/恢复 | 事实字段清空重置，回到初始就绪待命状态 | 字段已重置为空值，准备接受下一局 | PASS |
| Step 16 | 环境隔离与未完成项核验 | 生产数据与旧候选 100% 未受损；如实核对未完成项 | 生产数据 (1602+61 文件) 与旧构建 100% 完好；底部勾选如实标记 | PASS |

##### 3. 产品体验与 UX 评价
1. **可用性与闭环度**：在隔离环境下，用户无需键盘鼠标介入游戏客户端，依靠 EXE 自带的原生交互与 WebSocket 即可完成“建局→输入事实→结算识别→历史查阅→重启恢复→归档导出→异机导入”全流程。
2. **Main 与 HUD 字段一致性**：双端双向通信严格一致，场地、宝箱、品质格数等事实同步无偏差。
3. **手动保护与自动更新规则（7.1 节）**：手动录入字段被明确标记为保护状态（protected），后续流程不破坏用户手动输入事实；清空操作正确记录状态；restoreAuto 能按规范解除手动锁定。
4. **DRAFT / FINALIZED 展示**：历史列表中未结算草稿显示为“未结算”标签，已结算对局显示为“已结算”标签，条目区分清晰。
5. **空历史 / 新局提示**：全新目录冷启动显示清晰的空状态提示与占位符，不会在磁盘产生无意义的空记录。
6. **历史图片 / 切片查看**：识别切片保存完整，通过相对路径或绝对路径重定位均能正确定位到原始 blob，哈希严格校验无损。
7. **导出导入可重定位性**：导出的 ZIP 归档包含完整的 manifest、records.json 以及原图/切片，导入到全新独立 `YIHUAN_DATA_ROOT` 后能够完整复原所有历史记录与图片，不依赖原机器绝对路径。
8. **底部品质出售默认勾选机制**：**客观未实现**。十四类未完成边界第 2 项（低品质出售默认勾选机制与历史偏好记忆）当前代码中尚未完成，验收脚本如实判定并标记为 `REAL_GAP_UNFINISHED_BOUNDARY_ITEM_2`，不作虚假合规陈述。
9. **异常与重启容错**：排除了开发旧存档路径（`YIHUAN_LEGACY_HISTORY_PATH` 默认回溯）干扰；解决了超大结算消息（29 件切片）WebSocket 64MB 缓冲区溢出；验证了 WebView2 异步加载保护。

##### 4. 边界与未完成项
- **整体状态**：维持 **`PARTIAL`**。
- **未完成边界维持有效**：十四类未完成边界（尤其是第 2 项底部品质出售默认勾选、全仓 39 件整仓滚仓识别、70 秒实时性能、未见对局泛化、六品质联合求解及 Historical Shadow）均保持未完成，不因为本轮 E2E 试用流程通畅而假称全部闭环。
- **环境安全确认**：用户生产目录 `%LOCALAPPDATA%\异环拍卖助手`（1602 文件）与 `%LOCALAPPDATA%\异环拍卖助手试用`（61 文件）在实测前后哈希与文件数 100% 一致未被触碰；旧构建（`df58589`、`447f28b` 等）均完好保留。

#### ff0e2da 候选单局连续性（Single Match Continuity）收口与隔离试用 E2E 完整验收交付（2026-09-15）

**实施方（Gemini）交付：针对上一轮 879dfed 候选遗留的“结算后 totalRecords=2 (1 draft + 1 finalized)”问题，完成根因定位与工程修复，提交 `a8fe6eb` 与 `ff0e2da`，构建全新隔离候选 `ff0e2da`。在全新独立 `YIHUAN_DATA_ROOT` 下，完整通过 16 步 E2E 体验验收，实现同一局手动/自动事实严格原地演进为唯一一条 `FINALIZED` 记录，零残留草稿；冷启动与异机导入保持严格 1 条；显式开启下一局才生成第 2 条。整体状态保持 PARTIAL。**

##### 1. 上报基线与环境身份
- 最新代码提交（Git HEAD）：`ff0e2da42d62bf3dca77e384ba630c76ad7c1a96`。
- 修复提交：
  - `a8fe6eb`: `fix(match): ensure single match continuity across draft and settlement finalization`
  - `ff0e2da`: `fix(main): move boot replay session pre-initialization after CONFIG load`
- 候选构建：`D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260915_ff0e2da\dist\异环拍卖助手\异环拍卖助手.exe`。
- EXE SHA256：`77A8A6F1DF54F8ACC71AC81542249818581126E9B2849E030408F4B1EA65A1DF`。
- profile：`isolated-trial-v1`。
- 驱动脚本：`build/e2e_trial_20260915/run_e2e_isolated_trial.py`。
- 机器证据：`build/e2e_trial_20260915/e2e_trial_report.json`。
- 详细验收报告：`docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md`。
- 导出产物：`build/e2e_trial_20260915/trial_export_bundle.zip` (8,929,159 字节，包含 manifest、records.json 及 33 个原图/切片 blob，记录数 strictly 1)。

##### 2. 单局连续性修复与 16 步逐步验收结果
- **根因分析**：
  1. `LiveMatchReceiver.apply` 遗漏同步 `data_origin`，导致 GUI 中 `CURRENT_MATCH.data_origin` 保持 `live`，而 Worker 发布帧来源为 `replay`；结算归档时触发 Fix B 跨来源门禁，拒绝合并而另起记录。
  2. GUI 启动时先随机生成 `draft_{uuid}`，用户手动输入事实落入该草稿；后续离线回放以 `replayfile_{fingerprint}` 归档，造成两局分裂。
  3. `persist_record_transactional` 中，草稿转已结算时仅合并 sidecars，遗漏受保护事实（`fieldStates` 与命名空间 `environment`、`publicIntel`、`qualities`），且 Canonical v7 严禁顶层扁平旧字段。
- **工程修复**：
  1. `core/live_match_transport.py`: 同步更新 `current_match.data_origin`。
  2. `app/main.py`: 启动配置加载后，若配置了回放文件，立即预置稳定 session key 与 `data_origin = "replay"`。
  3. `core/canonical_history_store.py`: 规范合并草稿事实到 v7 命名空间，继承 `fieldStates` 保护标记，保持顶层无违规扁平字段。
  4. 新增 3 项单局连续性回归用例：`tests/test_single_match_continuity.py`，全套 20 项专项测试全部通过。

| 步骤 | 步骤名称 | 预期行为 | 实际运行结果 | 判定 |
|---|---|---|---|---|
| Step 1 | 启动主窗口与HUD | 双窗口正常渲染，WebSocket 桥接建立，无崩溃 | Main HWND=200380, HUD HWND=2297376, PID=12432, WS 连接成功 | PASS |
| Step 2 | 空历史/新局初始状态 | 历史列表为空，无幽灵草稿，空状态占位提示可见 | DOM emptyState=True, badge='0 条', 磁盘 0 条记录 | PASS |
| Step 3 | 创建/切入活跃对局 | 稳定 session matchId，对局生命周期为 DRAFT | matchId=replayfile_85ce3299..., lifecycle=DRAFT, 标题正常 | PASS |
| Step 4 | 手动输入可填事实 | 主窗口/HUD输入框可输入事实并持久化为草稿 | 输入 q=21, 蓝格=3, 红格=1, 场地=珊瑚, 宝箱=琉璃, 均价=64836 | PASS |
| Step 5 | 手动保护与自动更新并存 | 手动修改锁定，清空状态可清，restoreAuto 解除锁定 | 手动输入置 protected=True; 清空置 cleared; restore 成功解除 | PASS |
| Step 6 | 主窗口与HUD同步联动 | 双端状态实时一致，无状态分叉与延迟撕裂 | Main q=21 同步至 HUD q; HUD 宝箱同步至 Main 宝箱 | PASS |
| Step 7 & 8 | 结算离线识别与原地归档 | 结算原地演进为 FINALIZED，**磁盘严格 1 条（0 草稿残留）**，受保护事实保留，第10项 visual-latiao-1x2 280k CONFIRMED | totalRecords=1, finalizedRecords=1, draftRecords=0; 继承 envBox/pubQ/blue/red/goldAvg; units=29; item10 规范绑定; 切片 SHA 严格一致 | PASS |
| Step 9 | 历史列表与单件核对 | 历史列表严格 1 条（徽章 1 条），展开单件卡片与切片可见 | 渲染已结算记录，DOM 徽章 '1 条'，第10项切片存在且 SHA 5e1b9aba... 一致 | PASS |
| Step 10 | 正常退出 | WM_CLOSE 正常退出，无死锁孤儿进程残留 | 进程干净退出，PID 存活检查确认已完全终结 | PASS |
| Step 11 | 重启并重开历史 | 冷启动能准确读取历史，**严格保持 1 条记录**，无幽灵空草稿 | 重启展示 1 条记录 (0 draft + 1 finalized)，DOM 与磁盘记录严格一致 | PASS |
| Step 12 | 导出当前记录 | 导出包含 manifest、records 与图片资源的完整 ZIP 包（含 1 条记录） | Native 导出 trial_export_bundle.zip (8.9MB, 35 文件, 1 record) | PASS |
| Step 13 & 14 | 导入全新隔离 DATA_ROOT 并核对 | 冷启动空白实例 2，无损导入导出包，**严格保持 1 条记录** | 实例 2 导入后 1 条记录、29 件商品完全恢复，辣条切片存在且哈希一致，来源 replay | PASS |
| Step 15 | 显式开启下一局 | 显式调用 begin_next_manual_match，**产生第 2 条记录（DRAFT）**，原 FINALIZED 完好保留 | totalRecords=2 (1 finalized + 1 draft), 原记录未被冲掉，DOM 徽章 '2 条' | PASS |
| Step 16 | 环境隔离与未完成项核验 | 生产数据与旧候选 100% 未受损；如实核对未完成项 | 生产数据 (1603+61 文件) 与旧构建 100% 完好；底部勾选如实标记缺口 | PASS |

##### 3. 边界与未完成项
- **整体状态**：维持 **`PARTIAL`**。
- **未完成边界维持有效**：十四类未完成边界（尤其是第 2 项底部品质出售默认勾选、全仓 39 件整仓滚仓识别、70 秒实时性能、未见对局泛化、六品质联合求解及 Historical Shadow）均保持未完成。
- **环境安全确认**：用户生产目录 `%LOCALAPPDATA%\异环拍卖助手`（1603 文件）与 `%LOCALAPPDATA%\异环拍卖助手试用`（61 文件）在实测前后哈希与文件数 100% 一致未被触碰；旧构建（`df58589`、`447f28b`、`879dfed` 等）均完好保留。

#### 2026-09-16 边界 2 三项窄缺口收口（外部审核指定范围）

**范围**：只补外部审核指定的三个窄缺口（保护模型审计与最小修复、取消前后身份不漂移测试、冻结 EXE 最小产品路径）＋恢复 canonical 14 项编号。整体仍 **PARTIAL**。本轮不做真实鼠标点击、键鼠接管、70 秒滚仓、新图鉴补件、匹配阈值调整、`catalog_065` 修改、求解器修改、性能优化、Arena、未知红 PMF；六品质联合求解与 Historical Shadow 不动。

##### Canonical 十四类未完成边界（唯一权威编号与名称，禁止改名、换序）

1. 真实本人获胜实录及自动归属全链
2. 底部品质出售默认勾选机制
3. 真实游戏键鼠接管与防干扰
4. 真实限时全仓滚动与跨页物品去重拼接
5. 疑难物品左键详情采集与关闭恢复
6. 70秒/游戏倒计时截止及离线继续识别
7. 离线结算与草稿治理，含胜者名单治理
8. 至少3局未参与调参的真实对局端到端验证
9. 连续识别稳定性与内存问题
10. 实时性能门槛：忙碌确认P95≤0.5s；出价到显示P95≤1.5s；情报结构化P95≤2s
11. 跨电脑/目录带图导出及manifest校验
12. 免费情报专属业务链
13. `tests.test_match_trunk` 两项历史测试债
14. 2D无有限上限全面可行性与二维摆放求解

> 更正记录：`docs/reports/2026-09-15-e2e-isolated-trial-acceptance.md` 第 4 节原先自拟的 8 项清单**不是 canonical**，已在该报告内就地撤回。任何局部验证都不得替换上述 14 项。

##### 基线（本轮开始时）

- 完整 HEAD：`2c81f9aad1ec2edef064390a4509a6e7a1a64929`；工作区 clean（仅本轮修改后为 dirty，未提交）。
- 冻结候选：`build/isolated_trial_ux_fixes_20260916_2c81f9a/dist/异环拍卖助手/异环拍卖助手.exe`，SHA256 `F7175A3DE14A9BD921B43F58B52F9BF763027F1B805D73170DBACCA2F0C24BA0`（本轮复算一致）。
- 隔离 profile：`isolated-trial-v1`；生产目录与旧候选未覆盖。

##### 缺口 1：qualitySellSelection 实际保护模型审计与最小修复

审计结论（先审计后改码，证据见 `build/boundary2_audit_20260916/audit_run_after_fix.txt`）：

- `USER_CONFIRMED_FACT_KEYS` 实际 **41 项**。新增字段是 `qualitySellSelection`；**`qualitySellSelectionSource` 从未进入该集合**（也不在 `FIXED_FACT_KEYS`）。历史"40 项"保留其历史时点语义，不倒改 7.1 表。
- 因此外部审核提出的"为何 provenance 需要进入 USER_CONFIRMED_FACT_KEYS"在**当前代码中并不成立**：provenance 既不是用户确认业务事实，也没有被整体永久锁定。真正的问题是反过来的——它是**单值聚合字符串**，无法表达逐色来源，且写入时会带上 `protected=True/status=confirmed` 的外观。
- 实测 A→D 严格序列（改前）：A 默认正确；B 只取消 green 正确；**C 视觉观察被整体拒绝**（`MANUAL_CONFIRMED_PROTECTED`，blue/purple 拿不到 `visual_observed`，新值只进 `candidate`）；同时 **`qualitySellSelectionSource` 被视觉覆写为 `visual_observed`，而 selection 本身仍保持人工值 → provenance 与值脱钩**；D 不重置（靠聚合字符串巧合通过）。此外 A 的默认写入**绕过 `_write_field`**，不产生 `fieldStates` 与审计行。
- 最小修复：改为**逐色 provenance**。新增派生事实键 `qualitySellSelectionSources`（color→source），保护与合并按颜色进行：人工动过的颜色才受保护并保留 `manual_override`，其余颜色照常接受 `visual_observed`；`qualitySellSelectionSource` 降级为**由逐色来源派生的聚合串**，拒绝被直接写入（`DERIVED_PROVENANCE_NOT_DIRECT_WRITABLE`）；`qualitySellSelection` 保留在 `USER_CONFIRMED_FACT_KEYS` 内但由逐色逻辑先行接管，不再整体锁死；acquisition 刷新改为**逐色补默认**，只对无视觉/人工来源的颜色生效，并走 `_write_field` 产生审计行（`ACQUISITION_PER_COLOR_DEFAULT`）。
- 修复后同一 A→D 序列 10/10 项判定通过：green 人工选择保留；blue/purple 接受 `visual_observed`；white/gold/red 未被误标 `manual_override`；acquisition 刷新不重置视觉或人工事实。

##### 缺口 2：取消前后身份不漂移（frame-255 vs frame-257）

原测试只比较 `(row, col, widthCells, heightCells, rarity)`，只能证明几何/品质一致。本轮新增逐件身份比对（`tests/test_bottom_quality_sell_selection.py::test_identity_stability_across_deselection`），按**格位 (row, col)** 配对（几何键不预设身份相等），再比对 canonical ID / name / price / identificationStatus / status。

实测结果：

- 两帧均 29 件，格位集合完全一致 → **无漏件、无新增假件、无同格重复**。
- 几何与 rarity 逐件一致。
- 已在两帧都 `exact` 的 23 件：canonical ID、名称、价格、身份状态、确认状态**全部逐字节一致** → 无串 identity、无改名、无价格漂移。
- 6 件由 `ambiguous → exact`（(0,4)(0,7)(0,8)(8,9)(9,6)(9,9)），方向单向，**不存在 `exact → ambiguous`** → 身份强度只增强不削弱。
- 可比性说明：`row/col/widthCells/heightCells/rarity` 与"两帧都 exact"的身份字段可比且要求相等；单帧 `ambiguous` 的身份字段**不可比**——未解析不等于竞争身份，属解析强度差异，故按方向性检查而非等值检查。两帧分属动画不同时刻（255 为部分取消、257 为全部取消），小尺寸 1×1/1×2 图标在 255 帧仍带粉色选择环，模板证据更弱。
- 该结论**仅限此真实样本**，不推广为所有红物或所有帧的身份准确率。

##### 缺口 3：冻结 EXE 最小产品路径

按外部审核要求"优先不重打包"，先用既有冻结候选 `isolated_trial_ux_fixes_20260916_2c81f9a`（SHA256 `F7175A3D…`，复算一致）在全新临时 `YIHUAN_DATA_ROOT` 下真实启动，未用系统 Python import 源码代替。结果在**最早断点**失败，定位到两处真实产品链路缺口（均为既有缺陷，非本轮引入）：

**断点 1（识别结果未出管线）**：`core/vision_pipeline.py::NTEVisionPipeline._attach_settlement_ledger` 只把 `ledger["settlementItems"]` 与若干计数字段提升进 `settlement` / `current_context`，**没有提升 `qualitySellSelection` / `qualitySellSelectionSource`**。检测本身是成功的（对 `settlement_blob_144037.png` 直接调用 `detect_quality_sell_selection_from_frame` 返回六色全 `unselected`），但结果只留在 `settlement["ledger"]` 里，`auto_archiver` 读 `ctx.get("qualitySellSelection")` 得到 `None`，于是走 `acquired is False` 的兜底分支，`canonical_match_record` 落库为六色 `unknown` + 来源 `unknown`。
最小修复：在 `_attach_settlement_ledger` 中把三个键从 ledger 提升到 `settlement` 与 `current_context`（仅当 ledger 中非空）。

**断点 2（投影丢字段，UI 永远显示"未记录"）**：`app/main_view_state.py::HistoryRecordProjection.to_payload()` 的 `settlement` 是有界白名单摘要，**不含 `qualitySellSelection` / `qualitySellSelectionSource` / `qualitySellSelectionSources`**，因此 Main 历史详情拿到的 `record.settlement` 里没有该字段，`main_window.js` 的 `qSel` 恒为 `undefined`，渲染结果恒为"未记录"。经真实 EXE 的 WS 桥实测确认：`#detail-sell-selection` 元素**存在**（静态 HTML），但文本为"未记录"——即字段被投影丢弃，而不是 DOM 缺失。
最小修复：在 `HistoryRecordProjection` 增加三个有界字段（六色固定基数 map + 聚合串），在 `to_payload()` 的 `settlement` 块内输出，并在 `_project_record` 中从记录里规范化提取。

**链路离线验证**（`build/boundary2_g3fix_20260916/probe_chain.py`，9/9 PASS）：frame → `parse_settlement_ledger` → `_attach_settlement_ledger` → 归档块 → canonical v7 → Main 投影，每一跳都保留 `qualitySellSelection` 六色状态与 `visual_observed` 来源。

**测试锁定**：新增 `tests/test_bottom_quality_sell_selection.py::test_ledger_quality_sell_reaches_product_surface`，锁住上述五个跳点。该文件现为 **10 项测试全通过**（115.276s）。

**重打包**：因冻结包内 Python 已编译进 EXE、无法就地修补，按外部审核"停在最早断点做最小修复，再新目录重打包"的指示，重打包到**新目录**（不覆盖 `isolated_trial_ux_fixes_20260916_2c81f9a`，不触碰生产目录）：

- 新候选：`build/isolated_trial_ux_fixes_20260916_2c81f9a_g3fix/dist/异环拍卖助手/异环拍卖助手.exe`
- SHA256：`CC086845F1597EDF34BDC0254415E7B69AEFE040FC8CBB437E06ABA92B768AFE`
- 隔离标记：`{"profile":"isolated-trial-v1","codeRevision":"2c81f9a_g3fix"}`
- 旧候选 `isolated_trial_ux_fixes_20260916_2c81f9a`（7442436 字节）完好未动。

##### 缺口 3 实测结果

驱动脚本 `build/boundary2_g3fix_20260916/run_min_product_path.py`（**不 import 任何生产模块**，全部观测来自真实 EXE 的 WS 桥、DOM 与它写盘的 JSON）。结果 **5/5 PASS**，报告见 `build/boundary2_g3fix_20260916/min_product_path_report.json`。

| 步骤 | 结果 | 关键实测值 |
| --- | --- | --- |
| 1 真实 EXE 启动 | PASS | Main HWND=6427310 / HUD HWND=5771952 / PID=35376；DATA_ROOT 为全新临时目录 |
| 2 获得 qualitySellSelection | PASS | 六色全 `unselected`；`qualitySellSelectionSource=visual_observed`；`qualitySellSelectionSources` 六色全 `visual_observed`；record `replayfile_85ce3299…`，lifecycle `FINALIZED` |
| 3 历史详情实际显示 | PASS | DOM 文本 `白:✗·视觉 绿:✗·视觉 蓝:✗·视觉 紫:✗·视觉 金:✗·视觉 红:✗·视觉 (逐色来源)`；`elementExists=true`，`cardHidden=false`，`fieldHidden=false` |
| 4 正常关闭 | PASS | WM_CLOSE 后无残留进程 |
| 5 重启同一 EXE 重读 | PASS | 记录数 1 / FINALIZED 1；selection、source、逐色 provenance、DOM 文本**四者全部一致** |

- 生产目录 `%LOCALAPPDATA%\异环拍卖助手` 前后均为 1603 文件、逐文件 size+mtime 完全一致 → **未被触碰**。
- 运行路径证明：驱动在启动前断言 EXE 路径与 SHA256 等于重打包产物，并校验 `_internal/isolated_trial.json` 的 profile；所有观测均经该进程的 `ws://127.0.0.1:8766` 桥与它写下的历史 JSON 取得，未用系统 Python import 源码代替。
- 顺带修正：上一轮 Step 3 读取为 `None` 属 WS 桥偶发返回 `null`（本轮加重试后仍在 Step 5 观测到一次 `eval_main null`，重试后成功），**不是 DOM 缺失**；已用重试加固。

##### 本轮附带结论：既有 7 项回归失败的归因

`scripts/run_audit_regression_suite.py` 的 79 项批次中有 7 项失败。为排除"本轮引入"，用 **2c81f9a 冻结包内的 `PYZ-00.pyz`（1161 项）取出改前字节码**，在测试 import 之前 `exec` 进 `sys.modules`，从而在不改动任何源码的前提下得到**真正的改前运行时**（脚本 `build/boundary2_g3fix_20260916/probe_prefix_ab.py`，替换 7 个模块，Python 3.10.20）。

| 运行 | 用例数 | 失败数 | 失败集合 |
| --- | --- | --- | --- |
| 改前（PYZ 字节码） | 23 | **7** | 见下 |
| 改后（工作区） | 23 | **7** | 完全相同 |

失败集合完全一致：`test_archive_with_warehouse_preserves_slots_in_memory_and_on_disk`、`test_case_b_unknown_with_winner_name`、`test_cost_correction_updates_saved_draft_inside_duplicate_window`、`test_private_controls_update_and_clear_in_same_record`、`test_receipt_updates_same_record_without_changing_inventory_value`、`test_cross_match_backwrite_protects_current_match`、`test_finalized_backwrite_preserves_facts`。汇总见 `build/boundary2_g3fix_20260916/regression_ab_summary.json`。

**结论：7 项失败为既有测试债，非本轮回归。** 已定位到直接机制（`build/boundary2_g3fix_20260916/probe_dark_controls.py` 复现）：`AutoArchiver.archive_match` 成功落盘后会把调用方的 `ctx` 就地改写为 `ctx["settlementFinalized"]=True`（`core/auto_archiver.py:656`），而下次调用被 `archive_match` 的守卫 `if ctx.get("settlementFinalized"): return None`（`core/auto_archiver.py:189`）直接挡掉；测试复用同一个 `ctx` 字典并期望第二次调用返回非 None，与实现契约冲突。该两处均在**本轮未改动的行区间**内（本轮对 `auto_archiver.py` 的编辑仅限 503–536 的 quality-sell 块）。同批测试另有两处硬编码 `C:\Program Files\Python310\Lib\site-packages`（该解释器本体已不存在），在 3.12 下会毒化 numpy/cv2 导入，属测试环境债。

##### 本轮环境阻塞：git 对象库损坏（需用户决策）

本轮为做"改前/改后对照"执行 `git stash push -- core/` 时失败并暴露出仓库对象库已损坏，**非本轮代码问题**：

- `git stash` 报 `fatal: e5e3d78… is not a valid object`，并把整棵工作树变成 staged 新增（约 660 条 `A`）。
- `.git/refs/heads` 一度缺失、`HEAD` 被报为字面量 `"HEAD"`；`.git/objects/pack/` **只剩 `multi-pack-index` 与 `pack-64c9077c….idx`，`pack-*.pack` 数据文件已丢失**（`git multi-pack-index verify` 报 `failed to load pack in position 0/1`）；全盘搜索 `pack-*.pack` 无结果。
- reflog（654 行）本身完整，可读出提交序列：`… 9865460 → 2c81f9a commit: feat(boundary-2): implement bottom quality sell default checked mechanism`（`1789491925` = 2026-09-16 01:05:25 +0800）。据此已把 `.git/refs/heads/main` 重建为 `2c81f9aad1ec2edef064390a4509a6e7a1a64929`，`git rev-parse HEAD` 恢复正常，但 `git status` 仍报 `fatal: bad object HEAD`。
- **仓库未配置任何 remote，本地无 pack 备份** → 提交历史暂不可恢复。
- 已保全证据于 `build/boundary2_audit_20260916/git_damage_evidence/`（reflog 143883 字节、ORIG_HEAD=`5bebd1ba…`、git config、`.idx`、`multi-pack-index`），并把 6 个改动文件快照到 `build/boundary2_audit_20260916/backup_modified/`（与工作区逐文件哈希一致，证明无源码丢失）。
- 影响：本轮无法用 `git status`/`git diff` 证明 clean/dirty。已改用可复算替代证据（`build/boundary2_g3fix_20260916/dirty_set_inventory.json`）：前端资产用冻结包 `_internal/core/*` 与工作区逐文件哈希比对（仅 `main_window.js` 变更，`main_window.html` 等 12 个文件一致），Python 改动用"改前字节码 A/B"行为级对照证明。**未做任何破坏性修复，等待用户决定。**

##### 本轮未做（遵守禁止清单）

未做真实鼠标点击、键鼠接管、70 秒滚仓、新图鉴补件、匹配阈值调整、`catalog_065` 修改、求解器修改、性能优化、Arena、未知红 PMF；六品质联合求解与 Historical Shadow 未动；未提交、未自动进入边界 3。整体仍 **PARTIAL**。


- 本轮：ff0e2da 候选单局连续性（Single Match Continuity）收口与可用隔离试用流程 E2E 端到端体验验收完成（16 步全部 PASS，整体 PARTIAL）。
- 写前归档：[[99-系统与后台/Archive/Legacy-90-Archive/Projects/异环拍卖助手/2026-09-15_204500_ff0e2da单局连续性验收前/Handoff|Handoff]]。

