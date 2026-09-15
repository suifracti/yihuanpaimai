# 异环拍卖助手：接手审查与重新规划

## 2026-09-07 03:11｜v2 可运行包与展示阻塞修复断点

本轮没有继续旧五场识别或全量回归。确认并修复了一个冻结包级实时问题：Shadow 计算完成后，`app/main.py` 的 presentation listener 只更新顶层 payload，Overlay 仍读取 `solverInput` 内旧的 pending/结构输入，因此出现“后台结果已到、界面仍无正式建议”。新增 `tests/test_live_shadow_presentation_payload_v1.py`，并与既有仓库/采集/取消相关定向回归共 34 项通过；日志 `build/takeover_20260907/realtime-recovery-evidence/targeted-test-v2.log`。

使用正式 `app/异环拍卖助手.spec` 在独立目录构建 v2：`build/takeover_20260907/realtime-recovery-package-v2/异环拍卖助手/异环拍卖助手.exe`。EXE SHA256=`ad795c63e25cf2adc296665485c3afdc26c4a890e4e0a252612adb1822915fe9`；源码 fingerprint=`b1bb14e4bf4847d132dbce24c22d78cd60f9f9a4ad2d6469bc6d0c7aac2e3877`；构建日志 `build/takeover_20260907/realtime-recovery-package-v2-build.log`。v2 隔离冻结 WebView 证据 `build/takeover_20260907/realtime-recovery-evidence/packaged-valid-webview-v2.json`：Shadow 约 0.536s 到界面，`solverInput` 已同步，P50=437503、建议上限=432503，生产 History SHA 未变化。

同一 v2 EXE 的冻结帧 smoke `build/takeover_20260907/realtime-recovery-evidence/packaged-frame-smoke-v2.json` 通过：载入 103 条视觉参考；t=40s 帧仍为 q=7、goldAvg=null、无正式估价，说明包内资源和 fail-honest 分支均生效。

当前用户包已启动：主 PID 20868，worker PID 30172，8766 端口监听；启动日志 `C:\Users\Administrator\AppData\Local\异环拍卖助手\data\logs\run_2026-09-07_03-10-38.log`。旧包 PID 26032/14312 已确认路径后停止。当前仍是 PARTIAL：主录像无 goldAvg 时保持不报价；真实游戏窗口滚轮、真人结算完整推进/保存与取消晚到写回仍未完成原生验证。用户下一步直接实战反馈；若有新失败，只针对新证据取证。

## 2026-09-07 03:27｜无 goldAvg 合同与完成审计

生产 `auction_engine_v06.solveAuctionPipeline` 隔离探针已覆盖 `q`、`q+knownGold`、`q+knownRed`、`q+goldTotal`、`q+goldGrid`；全部 `fallback`，正式 `formalValue` 与三条出价线均为空。`live_shadow_runtime.js` 和 WebView adapter 还在 `q/avg` 入口 fail-closed。结论是当前主录像缺少现有合法估价模式所需的金色价格事实，不能修成“默认报价”。证据：`build/takeover_20260907/realtime-recovery-evidence/goldavg-contract-probe-v2.json`。

按 Goal 完成审计已落盘：`build/takeover_20260907/realtime-recovery-evidence/completion-audit-v2.json`。合法 q+goldAvg 隔离价格链为 PASS（真实异步链约 0.795s、冻结 WebView 可见约 0.536s）；采集三段覆盖/保存与取消晚到拒绝仅为隔离 recording adapter 证据；原生游戏窗口滚轮、真人结算推进仍 UNVERIFIED。另以精确 Main Window 句柄对隔离包做了 `WM_CLOSE`，日志确认 clean exit，见 `normal-exit-observed-v2.json`。当前用户包保持运行，不中断用户实例。

Blocked 状态恢复后的外部状态复核：没有发现真实“异环”游戏窗口；当前用户包 PID 20868/30172 及 8766 端口仍正常。PID 29352 经命令行确认为早先 `--smoke-vision-frame` 遗留测试进程，已精确关闭并确认消失；不能把该测试窗口的脚本异常归因于用户包。

再次核对 `D:\video` 只有主录像 `2026-09-07 00-12-11.mkv`，补充录像仍不存在；本轮没有向任何前台窗口注入输入，也没有新增 production logic、图鉴或测试真值。

## 2026-09-07 03:31｜主录像 live 输入缺失证据补齐

对主录像对应的既有 live 日志 `build/takeover_20260907/live-001211/run_2026-09-06_22-23-24.log` 做了针对性字段审计：18 条带 `q` 的记录中，`goldAvg` 非空为 0；局中 `IN_AUCTION` 与后续 `SETTLEMENT` 记录均保持 `goldAvg=None`，包括 `settleReady=True` 的记录。录像 SHA256=`233A43E631C65D02417050FA9F0D89EB48301EF636DAA46EB7A153498D96D86A`；日志 SHA256=`b4388a8767e72c5b96538402cb50a3751de06ffadb04ea39dcdfd51d6341c4bc`。证据 `build/takeover_20260907/realtime-recovery-evidence/main-live-goldavg-absence-v2.json`，并已挂入 `completion-audit-v2.json`。这只证明本段 live 输入没有合法 `q+goldAvg`，不证明所有局面都永远不会产生均价；不据此修改价格模型或默认报价。

## 断点：有效估价延迟 + 采集控制（2026-09-07 01:05）

产品 FAIL。HEAD `5bebd1ba8204685eb2c910573bc20304426cf2e5`，未提交改动全部保留。无活构建/测试。解释器 `build/takeover_20260905/repro-venv/Scripts/python.exe`。隔离 `build/takeover_20260907/`。主录像日志副本 `build/takeover_20260907/live-001211/run_2026-09-06_22-23-24.log`。对应运行包仍是 `build/takeover_20260906/final-live-package`，与当前源码已分叉。

根因：1) early/worker 同步跑仓库身份再 OCR，现场 LOADING→q 约 44s；2) extraIntel 无 goldAvg，Solver 资格不足；3) 采集非前台 10s TIMEOUT 而非暂停，Alt+Tab 不恢复。

已改：`vision_pipeline.process_frame(include_heavy_identity=False)` + `complete_heavy_identity`；worker executor 先发 OCR；early 路径几何 only；capture 前台等待直到恢复或取消。探针 t=40s OCR 5.5s 得 q=7/timer=42。targeted 21 + worker 2 OK。

下一步：extraIntel 估价口径（不猜 goldAvg）→ 结算短片段 capture 推进/停止写回 → 目标过后再打独立新包。细节见 Obsidian Handoff。

---

## 最新执行：五场逐件识别（2026-09-06 04:20）

最新五场结算回放为 15/15、23/23、17/18、15/29、20/21；90/106 件名称和价格对上独立标签，剩余 16 件未知。第一、第二场逐件验收 PASS，整体 PARTIAL，尚未实现全识别。独立标签覆盖 103/106；五场金额、收益、可见件数和逐次归档断言通过。

当前识别参考 103 条。增加同一原图的较完整裁剪、低对比特征与轻微模糊参考匹配；模糊参考另检查图像梯度，防止把雕塑共用底座当身份。识别勾选标记后排除遮挡区域；勾选前的身份只有在同局、同位置多物品像素配准通过且原图持久化成功后才补入，并携带原图证据。没有使用结算总价选择身份。

14 项识别、几何、遮挡与多帧证据回归通过，验收器另 1 项通过。前一次扩展测试的 1 失败/1 错误已修复：补经源图确认的小塔标签，并让多帧测试明确设置未知输入，避免单帧识别提升改变测试前提。新包 continued-package 已重建，冻结运行时载入 103 条参考，第五场连续两次识别 20/21、合计 538072。未重新验收完整 GUI、局中仓库或 Solver。

下一步处理剩余 16 件：第三场鸡蛋形物品（另有小物件单帧识别仍不稳定）；第四场勾选遮挡、小物件和绘画参考缺失；第五场纸牌形物品。第四场绘画放大后与“花原”原图不符，已撤回该人工标签；不按差价推定“解构”。鸡蛋、纸牌和该绘画仍缺独立完整标签。第二场旧交接所称“无梦果核漏项”更正为“墨染瓶”，现已补上。五场全部逐件通过后，再单独验收局中仓库揭晓、遮挡、滚动及完整界面。

工程证据：build/takeover_20260905/continued-replay-summary.json、continued-identity-acceptance.json、continued-recognition-v1/v2/v3a/v3b/v4、continued-frozen-smoke.json。源码未提交，未发布；所有模拟归档隔离。录像参与了开发，不能据此声称未见对局准确率。

---

日期：2026-09-05。审查基线：`5bebd1ba8204685eb2c910573bc20304426cf2e5`，产品版本 `v0.67-alpha`。

## 实施更新：仓库补写数据保持修复

用户授权“你去做”后，第1项已在源码完成修复，尚未提交或打包。History新增仅更新DRAFT仓库占用的接口，在现有进程内共享锁下读取最新磁盘记录、检查生命周期、更新目标字段并复用校验写盘。Host不再用CurrentMatch整条替换历史；默认CurrentMatch写回要求packet明确携带相同对局编号，缺编号和上一局晚到包均不写入。

先新增回归并确认旧代码两项失败，再修复实现。相关34项测试全部通过，包含原FINALIZED夹具补全明确acquired后实际执行的不可变断言。重新运行AutoArchiver→实时同步→capture完成原复现：goldCount=4、totalItems=30、R1出价历史保持，occupancy成功写入。证据：`build/takeover_20260905/occupancy_fix_test_results.json`、`data_preservation_fixed.json`；原失败证据保留。

边界：现有锁只覆盖单进程；跨进程写盘竞争、实时状态同步及GUI验收仍未解决。自定义occupancy_sink保持其原回调合同，此次旧包隔离测试针对默认CurrentMatch路径。下一项为第2项生产进程事实与写盘责任核验。

## 当前判断

2026-09-06 00:37 名称识别最新进展

用户“继续”，识别准确性仍为第一目标。本轮已把名称识别接通，有真实像素验证，不是只改计划。

事实与改动：发现catalog_065.json与solver快照及原始图鉴的尺寸不一致（扭扭饼干JSON2x1/原图1x1，无梦果核等亦有不符），且原目录缺猫丸秘制豚骨拉面等已有截图物品。48张图鉴原图完成离线OCR，232张卡片草稿仅为检查资料，未直接作为真值。逐图目视核对相关原图后新增assets/items/visual_catalog_v2.json，42条有原图路径/SHA/卡片bbox/姓名/价值/尺寸的视觉参考（其中部分用于第二局）。保留catalog_065与v0.6历史Solver价格快照不改，SettlementCatalogCandidateResolver只在默认生产识别加载这些参考覆盖，catalogVersion/fingerprint包含视觉快照，自定义catalog_path仍隔离。

新增core/visual_catalog.py：只载SHA吻合的已目视参考，裁掉名称/价格等区域，按catalogId寻图；双向特征匹配阻止多对一，非退化几何和覆盖率约束；对齐后梯度验证，少纹理另做同一位置/尺度的轮廓+颜色双重比对。分数是匹配证据强度，非校准准确率。纯色/随机打乱图的42参考反例全部拒绝。唯一候选只有独立视觉证据通过才EXACT；未分清的碎片只保留候选，不匹配或自动确认。后者也修复旧截图大量碎片反复匹配造成的严重耗时（一次旧最终测试长时间运行已主动停止，visual-identity-final-tests.log为不完整；不得称该次通过）。

程序真实结果：240s开发样本23/23名称逐项正确，价值631993，与游戏结算一致；错误actual_total=1也仍识别相同23件且不verified，未用总价凑答案。455s带勾选遮挡样本29件，9件自动名称正确、其余20件待解决；只标了可独立核对的9个身份，未把所有29件都假设已知。fixture annotations保存23完整身份及第二图9项部分身份；visual-identity-results.json/log记录上述结果，recognition-23-items-verified.png逐项展示结算裁图与独立图鉴卡，已目视核对并修正文字重叠。

历史真实链路：旧whitelist丢弃了name/price，已补name/exactItemId/price仅EXACT可见。JS核对卡显示自动识别名字/价值，匹配分明确非准确率，保留人工确认与机器事实区分。实际读取隔离历史结果visual-identity-real-reviews-fixed.json：第一局另一张已存main帧22/23，合计630171，仍漏炫动三角铁1822；第二局9/29，合计219951；历史字节不变。故开发图23/23不能冒充现存全部历史23/23，更不能称全面识别完成。程序源码已接入，当前旧冻结GUI/包仍不含这些变化，未做新包原生UI验收、未提交、生产History未改。

最终检查visual-identity-complete-tests.json/log：36项，41.390s，全部通过；包括独立名字对应、错误总价不影响识别、背景/随机噪声拒绝、碎片不确认、两图几何及缩放、候选/证据/历史核对合同、旧manifest完整性。JS node --check通过，改动diff --check无错误。此前visual-identity-fixed-tests36通过是在加入少纹理补充前，不能混成最终验证。

下一步仍优先识别：1. 将现存第一局漏识别的三角铁帧纳入可移植样本，修跨帧少纹理稳定性；2. 第二局勾选遮挡20件，优先找原录像未勾选稳定帧/遮挡掩码与多帧识别，继续逐图补独立身份；3. 校验42视觉参考之外的剩余图鉴，不把OCR草稿或全目录计数当已核实；4. 正确识别后才刷新完整可运行包、原生记录核对。当前目标active，有实质进展，未标完成或阻塞。


2026-09-05 23:39 最新优先级与识别进展

第一目标：把藏品识别做好。用户最新明确要求“第一目标把识别做好”，此前环境、打包、UI收尾顺序让位于识别准确性。验收以真实图逐件对应为准，不能用通过测试数、候选覆盖或人工纠错代替识别正确。

执行顺序：1. 原图定位与完整分件；2. 核实图鉴图片—名称—ID映射，提取纯藏品参考图；3. 修视觉身份匹配并对误报/漏报逐件标注；4. 用未参与调参的其他真实局、缩放/遮挡/滚动场景复验；5. 回到历史记录链路验证同一件裁图、名称、数量、价值对应。相关截图取证与记录保存修复继续服务于识别，其他功能扩展后置。

本轮已修：结算ROI原(1315,216)-(1877,815)把筛选条算入网格，分件/候选仅遍历8行且允许4x4/1x3合并。新增core/settlement_grid.py统一结算ROI为1920x1080下(1315,214)-(1878,776)，以实际闭合卡片边框分件、多阈值+暗沟验证+缩放归一化，取消穷举数百个交叠矩形和固定坐标noise。接入ledger、proposals、stable_frame及review两处。真实240s/455s仓库裁图及人工逐框坐标已纳入tests/fixtures/settlement_cards_v2，分别23/29件；严格比较完整坐标集合而非旧IoU=.25或任意子集覆盖。两图52个框在原尺寸及2/3、3/4、4/3缩放检查通过。来源SHA/框坐标存annotations.json，无身份标签，不能据此宣称名字识别率。

实际Service读取隔离历史第二局返回proposals/grouping/identity各29条，原历史字节未改，见recognition-real-review.json；原始main图片继续正确。当前旧冻结GUI/package尚未包含本轮识别改动。首轮组合28项仅1失败为旧ROI216断言，已按真实ROI修正；缩放验证暴露单阈值合并/碎裂后增加多阈值边界复验，最终测试日志见recognition-final-tests.json/log（以最终结果文件为准）。标框图verified-cards-2026-08-18_11-19-25_455.png已目视核对。

待办核心：名称识别尚未通过。参考manifest共200项，仅134项有参考卡片，66项未映射；已目视image1-0-0参考含名称、价格和面板，不能直接与仓库小图整幅拉伸比较。当前tpl_dir只载catalog_screenshots，GUID文件名也不能可靠对应name/ID。SIFT离线初探recognition-feature-probe.json出现大量肥皂等错误top1（多对一/退化几何未过滤），仅实验，未接生产。下一轮优先修正模板来源和纯图提取、非退化匹配与独立身份真值，不回去做外围打包。52框仅两局可见视口，不代表全仓或所有场景通过。


2026-09-05 22:54 干净依赖复现已完成实质验收：新增requirements-desktop.lock.txt为本机实际11个直接依赖及传递闭包36项版本；tools/check_runtime_environment.py报告版本与模块来源。用3.10.20创建ignored repro-venv，pip install成功exec37757 exit0，pip check无冲突；runtime_environment_clean.json所有11模块均来自repro-venv，不借全局site-packages。观察环境脚本/日志单独保留，不宣称原全局包下载来源已知。

实际干净源码入口首次失败warehouse_capture_session notfound，repro-vision-smoke.log保留；main.py把BASE_DIR/BUNDLE_DIR/PROJECT_ROOT/CORE_DIR等路径初始化从业务导入后移至前方，解决全局PYTHONPATH掩盖的启动缺陷。repro-vision-smoke-fixed.json真实75s图连续两帧成功，模板8/2/1。最初直接unittest discover因无app路径失败repro-worker-tests.log，新增通用tools/run_tests.py仅加仓库模块路径、临时runtime数据目录，干净环境13项回放/控制/身份通过repro-selected-tests.json。

干净环境直接python -m PyInstaller完整spec构建成功exec87307 exit0，repro-package-build.log，输出build/takeover_20260905/repro-package/异环拍卖助手（旧package与dist保留）。从仓库外TEMP cwd、清PYTHONPATH/PYTHONHOME启动该冻结exe探针成功repro-frozen-smoke.json，与源码输入SHA/模板/全部选定facts含warehouseSlots相同，repro-source-package-parity.json全true。未启动这个新包原生GUI，旧main-image包exec35742仍运行；新变化仅启动路径与环境复现工具/文档，不冒充已做新包真人UAT。

README当前版本纠正v0.67-alpha，run.bat移除硬编码0.65标题；docs/desktop-environment.md给出虚拟环境安装、检查、隔离运行、测试与构建步骤及证据边界。下一步按原六项最终审计、补证据可移植/当前新包必要检查，等待用户真实游戏就绪开展原生全仓/中断及集中UAT。用户暂无游戏就绪回复；目标active，本轮具体进展。未提交/生产History写入；无活构建/测试，原GUI仍运行。

2026-09-05 22:42 最新包选图与离场复验完成：旧GUI exec19309 UI正常退出0，package-build-main-image.log构建成功exec16235 exit0。launch_identity_ui.py重开exec35742当前活着，主35390420/HUD10622348隐藏；实际打开同一已修正草稿并滚到核对区，预览恢复完整结算页（不再局部图）、姓名祭、归属未知、整行表单和摘要布局正常。仍4条隔离记录，未再次保存。包根无临时replay config/录像关键帧。

recheck_exit_recordings.py对原75帧SHA核对后完整运行，exec35126 exit0，identity_recordings_exit_fixed.json/log COMPLETE75；旧identity_recordings_trace保留。第一局250秒loading清姓名/winner，第二局320秒IN_AUCTION姓名祭/winnernull，第二局451秒结算OCR仍蔡，510秒大厅双方字段null。identity_exit_assertions.json检查75完整、所有局内无上一局winner、index32后离场/loading无身份残留、末帧大厅均true。源码pipeline录制序列复验，不冒充原生采集/冻结双进程再跑。

已通过async输入询问用户准备真实游戏拍卖结算可查看仓库场景，尚无回复；这是原生全仓/中断所需外部场景，其他收尾继续，不标记blocked。当前无运行worker/测试/构建，仅GUI exec35742。下一步依据六项原规划做最终范围审计与可复现交付检查，待真实全仓/中断及集中UAT，不能宣布全部完成。生产History未改、未提交，目标active，本轮为具体进展。

2026-09-05 22:32 主结算预览选图修复：build_truth_evidence_v2原逐项refs.insert(0)把最后warehouse-segment顶到首位，create_review_session又优先refs[0]，使展示/普通识别读局部图而分组v2_img仍读main。新增2项先失败main_image_before.json。现保存引用按main-settlement优先稳定排序，保留所有分段和旧引用；current review读取有明确main角色的v2_path优先，uri/sha/实际图片同源；旧已写错序记录也无须回写即可正确展示。legacy lane未改。

31项选图/身份/原核对/证据合同组合全部通过main_image_fixed.json，exec84497 exit0。另check_main_image_real_record.py实际读取identity-ui-data内刚经GUI改名的draft_43d42c6f32dc48338ddd32ce272c49af，执行真实service.create_review_session，返回dataURL字节SHA和声明SHA都与main一致、1920x1080，History字节不变，main_image_real_record.json全部通过。非模拟read DTO，未改生产记录。最初诊断输出误展开大量描述符被截断，后续仅提取紧凑字段，不以截断内容作完整审查结论。

此次未重建包，当前旧新包exec19309仍为identity-layout版本（主437718938，HUD20976836隐藏），不含本次选图源码；未操作GUI。无测试/构建/worker运行。下一步最终包含选图的包与实际窗口复验、离场序列、原生全仓/中断及完整审计。目标active，本轮具体进展，未提交/生产History写入。

2026-09-05 22:28 新包原生身份纠错验收完成：旧exec76638经UI正常退出0；package-build-identity-review.log构建成功，launch_identity_ui.py复制frozen-recordings-data到identity-ui-data、NTE_DISABLE_VISION=1隔离启动exec16397。原源库在旧GUI退出后已有4条（含21:28未结算草稿），本轮保存前identity-ui-before.json为4条基准，勿称新增4局。实际点击第二局draft_43d42c6f32dc48338ddd32ce272c49af，输入PLAYER_LOCAL，保留归属未知，勾核对后保存。磁盘identity_ui_save_verified.json全部true：数量不变、其他记录逐字段不变、DRAFT/null、winner祭、audit before蔡、预测/金额不变。实际UI摘要同步，保存提示出现。

原生UI发现fieldset放在两列截图网格内导致摘要挤窄换行，移到截图区上方，增加整行两列表单样式。exec16397经UI退出0，package-build-identity-layout.log重新构建成功（exec99445 exit0），重新启动exec19309当前仍运行；主窗口437718938，HUD20976836已隐藏。实际重开姓名祭/归属未知保持，表单和下方截图/摘要不再挤列。包无临时根config.json和录像关键帧（启动脚本断言），默认配置恢复；尚未最终交付。Computer Use一次提示user input detected，已重新取状态后继续，无猜测坐标。

新发现待修：保存身份后的重载预览由完整结算页变成仓库局部图（实际UI确认），金额/预测/原始before记录未丢；需检查truthEvidence refs与v2主图选择顺序，不把部分图当主结算图。此问题独立于已过姓名保存/布局。下一步修主图选择、离场改动录像复验、原生全仓/中断和最终审计。当前无构建/测试/worker；GUI exec19309活着。生产History未改，未提交，目标active，本轮具体进展。

2026-09-05 22:16 历史草稿身份核对源码已接通：review DTO增加identityEditable（普通会话/导入会话），只对本地DRAFT显示姓名、本人/他人/未知选择及明确勾选确认。复用save_settlement_review消息带identityReview，原生Host转发，Service拒绝泛称/非本地输入并生成服务端时间；HistoryStore在跨进程事务锁内重读后检查DRAFT、姓名长度与严格bool/null。追加identityReviews before/after/user/time，保留原OCR与证据、金额、预测；保存仍DRAFT，不自动终结。再归档preserve_archive_sidecars保留winner/acquired/identityReviews，避免晚到OCR覆盖人工。

新增3项隔离测试：未知保持null、原图凭证/金额不变、前值蔡/后值祭审计、终态与非法字符串归属拒绝且磁盘字节不变、晚到归档保持人工姓名/归属。首次1error为测试重复创建同id FINALIZED夹具，history_identity_tests.json保留，改唯一id。30项核对/归档/结算组合通过history_identity_verified.json（exec41680 exit0），另17主窗口生命周期通过history_identity_host.json；JS --check通过。未把测试相加称独立全套。当前UI字段尚未原生截图验收，布局/真实点击到磁盘仍需新包验证；保存身份后触发重载、显示保留草稿提示。

当前无活测试/构建，旧GUI未操作，包尚不含最新改动。下一步该功能真实桌面验收、离场修复录像复验、原生全仓/中断、最终包清理与完整验收。未提交/生产History写入，目标active，本轮为具体功能进展。

2026-09-05 22:09 导入截图限定解绑：Evidence Store新增可选evidenceOrigin闭集runtime-capture/user-import，导入入口明确user-import。同字节原图与导入关联独立evidenceId（import后缀）/去重，blob仍复用不可变；unlink_user_imports在原有锁内仅移除显式user-import索引项，不删除blob，不把缺来源旧描述符当导入。delete_imported_screenshot不再清整个索引、不再清canonical truthEvidence/settlementItems，索引失败返回错误不吞；旧legacy overlay仍走已有移除。UI按钮/确认/成功提示改“移除导入关联”，说明保留原图与审阅。已存凭证可能继续展示其原始截图，这是保留审计证据，不宣称文件删除。

新增3项测试验证同字节runtime/import分离、实际canonical文件字节不变、两描述符原件仍能读取、幂等、旧来源未知保留、索引异常反馈。原截图删除测试先前要求原凭证消失，按保护原证据修为恢复原图并验证非导入SHA。首轮29项2失败import_unlink_tests.json是新字段被严格合同拒绝；Python合同与JSON schema补可选闭集字段、旧文档仍合法，40项全部通过import_unlink_verified.json（exec29122 exit0），随后store入口来源校验最终23项通过import_origin_final.json。无失败错误跳过；不是重复测试相加。

源码UI未原生重载，未重建包，未提交/生产History写入。无活测试/构建；旧GUI未操作。下一步已存DRAFT人工竞得身份纠错入口、离场修复复验、原生全仓/中断和最终包验收。目标active，本轮具体进展。

2026-09-05 22:02 核对截图目标校验：确认import_screenshot在检查目标History存在前写legacy evidence副本和v2原始证据，delete_imported_screenshot在检查前清v2索引。新增test_review_missing_record_writes，两条测试四个current/legacy子场景先失败review_target_before.json；现在两入口先确认记录存在，再允许副作用。17项含既有核对全组通过，0失败错误跳过（review_target_fixed.json，45.5s，exec86540已exit0）。测试按全部文件路径+字节验证失效请求无文件变化；不声称解决检查后的并发删除竞态。

新确认待办：现有历史核对只保存reviewedItems，无已保存DRAFT的竞得者名称纠错入口，当前手动结算只针对CurrentMatch。需补按recordId绑定的人工身份核对、保留原OCR证据及归属unknown。另delete_imported_screenshot对有效记录仍清整个v2索引，不能区分导入截图和自动原图，存在误删原始证据引用风险，下一步应改为有来源标识的限定解绑并保留原件。此次只修失效目标前置校验，未宣称完整截图删除边界解决。

未重建/发布，旧GUI未操作，无运行测试或构建。原生全仓/中断、身份核对功能、离场修复录像复验、最终包与收尾仍待；目标active，当前轮为实际进展，生产History未改。

2026-09-05 22:03 实际75帧身份复验完成：recheck_identity_recordings.py使用frozen_recording_manifest全部原帧并逐张SHA校验，实际pipeline/OCR，无手填姓名、无History归档，独立identity-recordings-data/captures。exec33937 exit0，identity_recordings_trace.log COMPLETE75。第一局180/230秒触发_horizontal fallback前后均PLAYER_LOCAL，结算本人姓名保持、winner汐；第二局本人姓名保持、winner仍蔡而真值祭。此为源码pipeline序列，非冻结Main/worker或原生采集复验。

序列暴露普通离场顶层winner汐残留下一局；clear_match_trunk此前也没清内部_slot_names/finals/cur_bids/bid_candidates/leader_slot，下一帧derive可重新带回旧事实。新增普通离场回归先失败seat_exit_before.json，已补清winner和内部席位缓存。25项组合无失败错误跳过seat_exit_fixed.json，涵盖普通离场/强制刷新/同名/备用保持/归档保护/实时控制。75帧trace保留修复前离场缺陷，不宣称此次新清理改动已重跑全部原录像。

当前无测试/worker/构建运行；旧冻结GUI PID16608已只读确认仍在，未操作。包仍未含归档/身份/离场最新源码，临时replay配置需最终重建清理。待姓名冲突处理、清理修复实际复验、真实全仓与中断、最终包与完整验收。未提交/生产History写入，目标active，当前轮具体进展。

2026-09-05 21:51：本人身份路径修复。_bind_horizontal_seats 备用识别原来从空席位建表，只复制姓名、不复制isMe，导致已识别本人变None；_derive_seat_leader_and_context原按姓名相等给isMe，会把同名对手也标为本人。新增测试先复现两项失败seat_identity_before.json，现备用路径保留已有席位isMe，主路径仅slot4为本人。继续增加重置边界测试后发现reset_session_state清内部slot缓存却保留外部seats/myName/opponents/leader；失败seat_identity_verified.json保留，现同步清空这组身份和出价展示状态。23项组合检查无失败错误跳过（seat_identity_combined.json），覆盖新4项、结算权威、环境归档、实时控制、估值确认、大厅重置。未改winner或acquired推断，不按近似名字纠正。源码路径缺陷已复现，不等于已重跑整段录像证明旧第一局的唯一成因。

本轮未重建包、未操作运行中的旧GUI、未改生产History。下一步仍为真实录像验证身份修复和姓名冲突处理、原生全仓与中断、最终包清理/重建及完整收尾。目标active；上轮及本轮均为具体进展。

2026-09-05 21:40：AutoArchiver 环境归档缺陷已修源码。canonical builder 与归档器保留 venueId/boxId/catalogVersion/catalogApprovalStatus/catalogSha256/gameEvidenceCohort/venueEvidenceClass/boxEvidenceClass；去掉无证据的珊瑚/wood默认，去重签名包含这些环境信息，允许金额相同但目录晚到的同局更新。新增3项先失败（archive_environment_before.json），修后组合31项全部通过、无跳过（archive_environment_verified.json）。原算法检查点保留：auction_engine 只允许唯一一行 decision 深拷贝传输字段，移除此行后原SHA精确一致；未放宽为任意新哈希。没有回填旧录像记录。

姓名仍未修：winner_roi_probe.json 对第二局451/453/455秒原图分别裁剪与2倍放大，六次都读成秋星蔡02，约0.879—0.890。同局磁盘bidding.myName及slot4为PLAYER_LOCAL，局内两轮也读出此名，构成身份冲突核对依据；不能凭近似名字直接覆盖或认定acquired。第一局myName退为玩家本人、早先两轮出现PLAYER_LOCAL，亦需继续核对身份保持链。没有实施写死字符替换或把重复OCR当真值。

当前包仍是21:31之前构建，不包含此次归档修复；隔离GUI exec76638/PID16608此前仍运行，无新构建/worker。发布前必须清理包内临时replay/18766及录像关键帧。下一步身份冲突处理及本人身份保持、真实游戏全仓采集/中断、最终重建验收与收尾。目标active，未提交、未改生产History。

2026-09-05 21:31 冻结双进程真实录制双局已跑通到预测/结算/退出：从14-11-56全局及11-19-25的第二局选75张有序原录像帧（frozen_recording_manifest.json），不手填事实。主程序自动启动自己的--vision-worker，皆为冻结exe，显式replay/18766，数据frozen-recordings-data与captures隔离。第一轮暴露Overlay固定8766而后台读配置，先18测试通过仍在原生实测发现file URI query报文件不存在；改用fragment携带端口，重编DirectCompositionHost.cs/DLL，实际连接成功。原失败日志frozen-recordings-port-before.log/frozen-recordings-query-failed.log保留。

首次运行到结算发生真实死锁：py-spy只读栈frozen_gui_hang_stack.txt显示WS线程持capture展示锁枚举窗口，GetWindowTextLengthW等自己的UI；UI线程等同锁。worker栈显示重连等待。现场保存后校验PID/路径，停止仅隔离GUI16736/worker7900。WindowCaptureManager.find_game_hwnd复用真实game gate，GameWindowTracker先排除同进程再读标题，7项通过window_discovery_fixed.json。没有把助手窗口当成游戏或伪造hwnd。临时诊断工具py-spy0.4.2只装在ignored diagnostic-tools。编译使用Framework64/v4.0.30319/csc.exe，引用已核Python310/webview/lib/Microsoft.Web.WebView2.Core.dll、System.Windows.Forms、System.Drawing。

同步缺失目录编号导致实际UI会场未就绪：sync_vision_to_current_match现从confirmed lobbyVenueKey按已批准alias取得venueId，box同venue映射，保留手工明确ID优先级，并补目录provenance到Current/ctx；不改批准目录或新增推测alias。新增先失败live_catalog_before.json，20项通过live_catalog_fixed.json。需区分先前UI未就绪和预测本身：最终磁盘显示失败轮次也有同局partial_shadow快照，不能称其完全无预测。

最新构建package-build-discovery-catalog.log成功后第三轮主exec76638（PID16608）、自动worker16740完成75/75，日志frozen-recordings-runtime-final.log：21:28:14 EOF；worker进程已不存在，observer exec78441正常退出0。首个观察器43109超时exit1、次个4496因死锁握手超时exit1均已确认终止，没有凭观测超时重启活进程。最新独立两局id draft_2235891ecf0640108f87154dbe0cdfa1、draft_43d42c6f32dc48338ddd32ce272c49af，Q12/74379、Q11/47286；成交666666/实际631993和成交500000/实际426860与清晰原画面一致。两局各有同局预测cutoff早于结算、原始证据引用，partial_shadow，不是完整库存正式分位。第一轮失败草稿draft_03cb...另保留，共3条；未声称旧记录逐字段不变。汇总frozen_recordings_summary.json，观察器hasPrediction=false仅检查广播不携带的字段，不能据此判定没快照。实际最新UI显示403359部分覆盖8.1%、正式分位为空。

当前仍有真实缺陷：第二局画面姓名“PLAYER_LOCAL”，OCR存为“秋星蔡02”；两局acquired均null故DRAFT。AutoArchiver丢目录编号/provenance，environment.box为琉璃却boxType默认wood；需沿真实记录修，不回填旧证据。自动全仓/原生游戏采集与中断未验；当前没有真实游戏窗口，UI正确禁用完整采集。当前GUI主窗口218892952、HUD104071750仍运行（exec76638），无模态；包临时config.json为replay/18766，根下录像关键帧为验收输入，发布前必须恢复常规配置；原录像副本在frozen-recording-inputs可复用，不能误算正式资源。下一步上述归档字段/身份真值与原生全仓，最后完整审计；目标active，未提交/改生产History。

2026-09-05 20:53 更新：未知竞得归属的摘要、结果卡片、凭证区已统一。SettlementReviewService导入/替换截图的DTO补回acquired/winner，20项通过（review_ownership_fixed.json，修复前review_ownership_before.log）。重建package-build-ownership.log并启动包83846，实际详情三处均不再声称本人收益，显示归属未知；已有winner FE夏独立显示。该姓名仍是OCR结果，未宣称已核真值。当前包83846已通过UI正常退出，退出码0。

回放正式worker入口五项缺陷均先复现：EOF重新播放、空目录反复重连、缺目录误落live捕获、停止信号后仍处理下一帧、断线后从头推理。现一次枚举帧、跨连接保留进度及待发HUD、保留离场session，停止/EOF走结算flush后退出；缺失/空回放明确退出。5项新增回归及控制/传输/预测组合共27项通过（replay_lifecycle_before.json/replay_lifecycle_fixed.json）。这些是实际worker入口配合受控帧/网络的回归，不冒充真实冻结进程两局验收。

75s/90s物体级证据已解决：从14-11-56原录像提取并逐图查看，实际六件灰色独立轮廓。旧程序把左上两个1×1合并为1×2，又把仓库下方背景算成金色1×1，导致总数“6”掩盖两处错误；原集成测试“5”也不符合物体边界。现不向上取整不完整网格，并用跨缝线亮度中位数保留亮边夹着的暗缝；新增可移植75s/90s夹具及六个位置/尺寸断言。原集成测试按同一物体级真值校正并加强，非单纯改数量。25项轮廓/身份/Canonical含真实录像集成无失败错误跳过，另10项旧网格/ROI无失败错误跳过（warehouse_outline_before.json/warehouse_outline_fixed.json/warehouse_grid_boundary_check.json）。候选和未知身份权限不变。

最新包重建成功，package-build-replay-outline.log。源码和冻结程序75s同图连续两帧SHA/尺寸/真实模板8/2/1/全部选定事实含warehouseSlots一致，六件轮廓逐位置符合真值（package_outline_parity.json/package_outline_truth.json）。冻结探针从仓库外临时cwd、清除Python路径环境运行，未归档。最新包未再次启动GUI，前一个仅缺回放/轮廓改动的包已完成上述UI验收；没有重复导出已证明的路径。旧dist保留，未提交或改生产History。下一步冻结worker+冻结GUI完整录制序列两局、原生游戏全仓采集/中断及winner独立真值；不能据此宣布全部完成。

2026-09-05 20:32 新包真实窗口/预测归档/重开导出：源码旧exec17409已通过UI退出，包exec84866启动，首页/对局切换/隐藏HUD/人工珊瑚实木选择实际可用。独立源码worker exec55937真实OCR处理frame_t360四帧及另一张结算fixture四帧，连接冻结GUI原Overlay；Q11/金均47286，GUI显示部分覆盖参考274572、正式分位为空、39%部分覆盖说明。worker收到3次prediction_snapshot及有快照的归档响应，保存同局draft_0bf78d5f2cce4e7e855db59102290d03，partial_shadow/valid预测cutoff早于结算证据（package_worker_prediction.json、package_prediction_summary.json）。manual已有草稿因此newCount=0/oldRecordsUnchanged=false是同局更新；不能声称所有记录不变。归属unknown，保持DRAFT。这是组合录制图+人工环境+源码worker/冻结GUI验收，不是两场真实比赛或冻结worker自动全仓。

实际发现DRAFT有金额就绿标“已结算”，已改本地列表完成标签以FINALIZED为准，有金额草稿显示“待补全”，DRAFT排除文案“草稿待补全”。正常关闭84866后重建package-build-status.log并启动exec77331（主窗口41617658，HUD620695364隐藏），实际标签正确。重开磁盘字节保持，实际导出原生对话框到package-desktop-export.json，共1条与磁盘逐字段一致（package_restart_persistence.json/package_export_comparison.json），成功提示持续显示。

详情继续发现归属unknown仍声称收益185974、竞得者摘要有FE夏而卡片未记录；源码已修canonical摘要未知归属不声称本人收益、详情收益显示归属未知、winner姓名独立显示。先失败回归unknown_profit_before.log，17项通过unknown_profit_fixed.json，JS语法通过。该最后批次尚未打入当前运行包；凭证核对区的净收益口径也需继续统一。实际核对页该遮挡截图产生568个分组假设，仍标机器候选非确认，不视为已完成全仓；身份/75s证据待。当前包77331保持运行、同局历史详情，操作前刷新窗口；没有提交/生产数据写入。下一步完成以上展示口径、重载复查，并继续原生全仓/冻结worker/连续两局与replay EOF。

2026-09-05 20:13 整组视觉与新包：exec76410完成，25项视觉worker回归无失败/错误/跳过，645.667s（vision_full_suite_results.json）。六项旧基线失败已有对应修复/测试入口解释，整组也通过；不据此替代75s分割或winner独立真值验收。

新包已构建到build/takeover_20260905/package/异环拍卖助手，旧dist包保留。三轮构建均完成，最后package-build-current.log；新增共享--smoke-vision-frame入口，正式business_sot资源初始化后执行，按生产worker传入catalog路径。首次探针置于初始化之前导致包内路径失败的证据保留package_probe_init_before.json，未把它说成正式worker故障。现源码和冻结包同图frame_t360连续两帧全比较一致，包从仓库外临时cwd读取复制的图片、清除PYTHONPATH/PYTHONHOME运行；真实加载模板8/2/1，见source_vision_probe.json/package_vision_probe.json/package_source_parity.json。界面/求解器6文件字节一致（package_ui_solver_parity.json），大厅目录包括manifest共9/3/2文件一致。

包内版本与证据保存回读成功；旧canonical smoke缺winner/acquired却要求终态，实际失败保留package_initial_checks.json。脚本现验证未知归属DRAFT，再补SmokeOpponent/acquired=false同局FINALIZED，源码与更新包均通过（source_canonical_probe.log/package_current_checks.json）。版本明确HEAD-dirty，未提交或伪报干净版本。所有数据隔离。最新包尚未GUI启动验收，不等于独立真实两局/预测/自动全仓已完成；下一步包的实际窗口及完整链，内置replay EOF重复重开待处理，生产历史不改。

2026-09-05 20:00 自动预测留档/视觉回归更新：真实JS fallback快照的自动首次归档与已保存DRAFT补全FINALIZED两条路径均复现丢失（auto_fallback_before.json，两项失败）。AutoArchiver及HistoryStore受限sidecar保持路径改用storage专用校验；正式评估规则不动，39项通过（auto_fallback_fixed.json）。进一步发现save_draft先复制整条记录，使异局/坏哈希快照即使校验不通过也已留在副本中；新增回归先失败，改为移除副本快照后仅通过校验才准入。28项通过（auto_integrity_fixed.json），验证原输入不变、合法fallback保存、异局/坏哈希不写入；没有回填旧记录或制造预测。

视觉剩余三项局部结果：末秒刷新测试改为注入当前DF数字入口，保留timer=3强制全图刷新断言；DF回退测试明确全图已读出估值时不重复OCR、跳帧时仍须ROI回退，保留最终13221/23及失败场景检查，两项通过（vision_contract_tests.log，207.215s）。历史出价原测试未改断言，单独通过（slot_contract_test.log、slot_contract_fixed.json）；原图三帧诊断也正确（seat_fixture_diagnosis.json）。不把单独通过等同整组稳定，整组25项视觉worker回归已启动exec76410，输出vision_full_suite.log，尚在运行，下一轮先观察同句柄，不重复启动。旧基线六项当前各有局部通过，组合结果待定；75s物体分割、winner真值、真实预测/全仓与打包仍待完成。

2026-09-05 19:50 独立worker实际OCR→运行中的GUI WebSocket两遍录制序列已完成，新增两个不同编号DRAFT，原有5条隔离记录逐字段不变（real_worker_two_matches.json）。两局均识别Q15、金4、成交600000、实际785974，acquired未知故不终结。会场/金均缺失，GUI两次归档请求都无已完成预测，所以此次不证明原Overlay预测闭环。它是同一组录制截图重复两遍，不是两场独立真实游戏；截图含遮挡，winner“FE夏”未经独立真值确认；全仓未模拟。

该实际运行发现连续结算帧污染席位姓名（“实际价值”“竞拍表现”等）。新增连续4帧回归先失败：结算状态仍调用2次席位绑定。现Fast ROI席位/数字后续读取要求明确IN_AUCTION且非结算，保留此前身份；连续结算/首次结算/正常出价确认共12项通过（settlement_seat_before.json、settlement_seat_fixed.json）。修复后的独立进程序列尚未重跑，旧隔离证据不回填。自动归档对fallback快照仍使用正式评估校验的差异、3项视觉遗留、原生全仓采集及新包继续待处理。未提交、未打包、未改生产历史。

2026-09-05 客户区捕获边界更新：核查生产worker时发现capture_game_client失败后再次抓取整显示器，导致下游仍按客户区ROI解读桌面文字。提取capture_tracked_game_frame共用入口，主worker和旧live_capture入口均只接收客户区或None，旧入口无帧时等待重试；WindowCaptureManager仍支持PrintWindow→客户区MSS，但不再返回两路都失败后的黑屏/尺寸异常帧。新增5项覆盖客户区失败不抓桌面、缺游戏不捕获、原尺寸保持、两路坏帧拒绝、客户区MSS仍可用。连同实时传输/控制共16项通过（client_boundary_test_results.json），视觉安全/仓库生产组合进一步通过（capture_safety_test_results.json）。

这修复实时来源边界，不代表既有桌面录屏夹具已裁剪，也不证明MSS客户区被其他窗口遮挡时的文字安全或winner识别质量。真正Main/worker连续两局、自动全仓采集和新包仍待验收。当前隔离桌面exec17409仍加载此前手动/导出修复；本轮不重复重启已通过的手动验收，也不标记新捕获已真机验证。

2026-09-05 19:33 桌面结算/导出/重开验收：新竞得者文本输入已实际重载。空输入在前端提示，泛称“其他人拍下”被后台拒绝，表单与金额保持、按钮恢复可用。具名输入暴露新阻塞：缺Q/金均时正常fallback预测被正式评估资格校验拒绝，从而阻止有效结算。新增validate_prediction_snapshot_for_storage，仅允许已知非正式求解状态的原始快照留档；同局、输入哈希与来源校验仍强制，正式评估校验保持不变。真实JS fallback→ManualTerminal→磁盘回归及缺环境中文提示回归先失败再通过，35项相关测试通过，另1项fallback异局/坏哈希不写盘回归通过（manual_fallback_test_results.json、manual_fallback_integrity_results.json）。缺环境不再向用户显示溢出的内部错误码。

重启后真实窗口只选珊瑚/实木、无核心情报，手动输入180000/220000/acquired=false/winner=FixturePlayer成功终结，同局FINALIZED id draft_7b9e94b5e86d41bb9aadc404a125d818，fallback快照保留，表单关闭且Current清空。历史详情实际显示具名竞得者和正确金额/收益。修复前失败隔离DRAFT draft_6c9de4f73d84456fb84fa192331673da保留作为证据，不改生产历史。

实际导出按钮→原生保存对话框→desktop-history-export.json，共5条本地canonical记录逐字段等于磁盘；列表295条含290条旧版只读参考，并非导出数量。UI新增明确范围及持续结果提示，取消/失败也显示反馈，原生导出无结果不再假报成功。18项导出/摘要测试通过（export_feedback_test_results.json）。正常退出exec10478并重开exec17409（主窗口80414302，HUD68686122隐藏）后，实际历史摘要保持，再次导出desktop-history-export-reopened.json的5条记录与前次逐字段一致，见desktop_export_comparison.json、desktop_restart_export_comparison.json；“已导出5条本地对局”真实渲染已确认。

以上使用desktop-data/desktop-captures及NTE_DISABLE_VISION=1，只证明手动/原Overlay/历史/导出/重开，不代替真正Main/worker连续两局和全仓采集。最新运行窗口已包含本轮修复，当前为FixturePlayer历史详情。剩余视觉3项、录屏winner、75s槽数、真实自动链与新包继续。没有提交/打包/迁移生产历史。

2026-09-05 结算首次识别更新：未知场景原先使用 focused_opening_canvas，裁掉结算标题/金额标签，反而读入遮挡助手窗口里的局内文字。现仅在已确认 AUCTION_LOADING 且 loadingDirection=to_auction 时使用窄区域；未知画面先完整识别。原基线的估值场景隔离、倒计时场景隔离、非局内四席读取三项均通过（scene_roi_test_results.json、scene_seat_test_results.json）。新增更严格的首帧回归：必须明确为 SETTLEMENT/isSettlement=true，估值/倒计时为空、两类局内数字读取计数均为0，也通过（scene_first_test_results.json）。没有把 UNKNOWN 当作修复成功，也没有改低原断言。

该截图名称虽含 client_sanitized，实际仍含桌面/助手遮挡；这次证明首次场景分类，不证明 winner 精确身份或统一客户区裁剪已经解决。另三项视觉基线失败仍待核对：末秒调度用例注入旧计时入口、DF回退次数预期与已有全图结果复用不一致、跨轮最终出价落点。尚未据此调整断言或改产品逻辑。新手动结算表单、Main/worker完整两局/全仓/导出/重开与新包仍待验收。

以下实施更新按时间记录；历史段落中的“待验证”应以其后的实际验证和本段最新结论为准，原始失败证据保留。

2026-09-05 18:31实际桌面/手动结算更新：旧exec28029通过UI关闭并确认退出，新exec24358运行（主窗口47255218、HUD24708778隐藏）。实际输入珊瑚/实木/Q9/33538/紫5，结构参考值208523正确标明“非P50”，正式P20/P50/P80为空，原Solver说明已展示：结构推断不生成正式三线。这两项最新展示已完成真实窗口复查，不再待验。

通过实际结算表单输入180000/220000/非本人，保存后进入历史列表；隔离磁盘有同局FINALIZED且predictionSnapshot保留，当前局清空。记录id draft_5c40d7abb27f4d9083fd7d6206b7bcdb，测试数据仅desktop-data。发现旧表单winner只提供本人/其他人泛称，ManualTerminal甚至拒绝本人对应真实名称，并把“其他人拍下”写为winner。已改竞得者文本输入，acquired独立，后端拒绝CurrentMatch同一占位名称集合；未知身份保持草稿而不放宽终态。合法旧测试夹具改为FixturePlayer，增加泛称拒绝/磁盘不变和具名对手回归。22项全通过（manual_identity_test_results.json）。

另补结算UI反馈：提交后等待native manualFinalizeResult，成功才关闭，失败显示原因并保留表单；不再无条件关闭掩盖校验/写盘失败。JS语法通过，这一批新表单/反馈尚未在运行窗口重载验收。当前窗口处于历史列表；新exec仍运行，未启用真实视觉。完整Main/worker两局、自动采集、导出/退出重开、视觉遗留、新包仍待完成，未提交/改生产历史。

2026-09-05 实际桌面复查：通过computer-use关闭旧隔离源码窗口，确认exec4574退出后启动当前源码（新exec28029，主窗口57021338，HUD12128920）。使用desktop-data/desktop-captures、NTE_DISABLE_VISION=1。缺会场/宝箱/核心情报时“等待情报”真实渲染通过；手动选择珊瑚场+实木宝箱并输入Q=9、金均33538、紫5，实际窗口出现208523估值，说明输入和原Overlay求解链可用。它不是正式整仓P50：0%历史覆盖下旧展示把formalValue的结构分位标成P20/P50/P80，且frozenPrediction没有携带decision，导致具体建议缺失。

已修：Solver frozenPrediction只新增复制原decision的传输字段，不改算法；Main分位仅采纳predictionSnapshot.forecast.quantiles，结构/部分覆盖值用referenceValue和明确estimateLabel展示，结构值不再冒充整仓P50；UI保留求解器原行动说明，部分覆盖徽标单独表述。22项通过（structural_ui_test_results.json），含真实JS Solver输出经过Main presentation；JS语法通过。该最后一批改动尚未在运行窗口重新加载；当前窗口保留测试输入，方便下一次复查。真实双进程连续两局/完整采集/导出/退出重开、视觉遗留和冻结包仍未完成。

2026-09-05 再归档/缓存更新：已复现“DRAFT→warehouse capture补写成功→补成交归属FINALIZED”再次清空warehouseOccupancy。原失败保留rearchive_occupancy_loss_before.json。AutoArchiver专用HistoryStore选项扩展为preserve_archive_sidecars：在同一文件锁内保留已落盘预测和独立capture/review拥有的warehouseOccupancy、warehouseIdentityReview，合并后重新校验；其他普通persist语义和FINALIZED不可变规则保持。真实Host补写后终结及真实review session落盘后终结两个回归均通过，审核artifact不变。

Live history缓存改为检测文件mtime_ns/大小/文件标识，未变化不重新打开JSON；原子替换后从打开文件的fstat记录读取版本、刷新数据集revision/单调history generation并清空预测缓存。生产WebView仍按dataset revision同步；已经运行的Node测试runtime同步更新records。独立Python进程同长度替换文件、缓存刷新、未变化不重读、文件删除清缓存均有测试。GUI原接收路径每局内帧调用load_history_snapshot，因此可感知worker新增历史，不再永久使用启动快照。

验证结果见rearchive_refresh_test_results.json，完整测试清单/数量以该文件为准，全部通过。未提交/打包/修改生产History；修改后的实际窗口、真正两局与自动采集全链、视觉失败和新包仍待验证。下一步回到实际窗口重启复查和两局链，不能继续用局部测试替代整体验收。

2026-09-05 18:03 预测归档更新：发现已完成的GUI预测必须等下一局内帧才回传，而worker先归档后发结算帧，末次完成结果可能漏存。新增prediction_archive_request/response，仅注册worker可请求；GUI读取同matchId已完成预测，不重新调Solver、不输入结算事实、不等待计算完成。worker结算保存前异步取回，正常循环/内置replay/关闭flush共用；等待期间换局拒绝旧局保存，通信超时或断开仍允许本地保存已有结算事实。关闭命令的flush以独立任务执行，避免占用接收循环而收不到响应。

新增真实本地WebSocket→生产ws_handler→worker capture loop→AutoArchiver→磁盘测试，证明已完成预测被原样保存到同局FINALIZED。测试Solver输入由现有Node测试入口产生，不冒充真实Overlay GUI求解验收。另先复现DRAFT后补归属导致predictionSnapshot丢失，再修AutoArchiver调用HistoryStore的受限保留选项：同局DRAFT更新/终结若本次缺预测，在文件锁内保留已落盘且校验有效的预测。覆盖工作进程重启、内存清空后补归属；不修改FINALIZED不可变规则。原失败draft_prediction_loss_before.json保留。相关47项无失败/错误/跳过（prediction_archive_test_results.json）。

仍待：GUI历史缓存感知其他进程写盘；DRAFT重复更新对独立warehouse采集/审核字段的保持；真实窗口改后复查、真实双进程两局/完整采集/退出重开/导出；视觉基线与冻结包。当前隔离源码桌面仍在运行，加载的是此前源码，未重启所以新改动未在该窗口生效。

2026-09-05 预测与界面更新：生产worker明确不发起第二个Solver计算，主进程使用既有Overlay WebView计算并向worker传递绑定matchId的prediction_snapshot。求解上下文和缓存键保留matchId；快照持有器拒绝异局输入、新局清除旧快照并复制输入。相关25项通过，证据prediction_owner_test_results.json。尚未证明真实GUI异步计算完成到结算归档的完整时序，也未完成两局导出验收。

隔离源码桌面试用发现：只选会场/宝箱、缺少关键事实时，预测为空仍默认显示BID和“当前最高叫价低于推荐上限”。已移除默认BID/A+及用EV代替推荐上限的推断；没有明确建议显示等待，有效PASS/BID保留，非法上限不能支持BID。界面增加中性等待状态与中文行动文案。相关26项全通过（prediction_advice_test_results.json）；修改后的实际窗口尚待重启复查。桌面使用desktop-data/desktop-captures隔离目录、NTE_DISABLE_VISION=1，不代表真实游戏识别验收。

2026-09-05 双向控制/重连更新：人工事实修正和手动下一局生成带revision的manualControl，worker确认前主窗口拒绝旧revision帧。worker在本局后续观测上保留人工修正，自然离局释放修正；手动下一局后抑制旧结算，直到观测离场。worker_hello握手恢复主窗口当前局、修正和等待离场状态，替换旧连接；传输断开让工作循环退出至外层重连，过期命令拒绝后确认revision避免永久卡帧。实时facts同步提前到归档之前，后续HUD处理不重复同步。

相关51项通过（`live_control_test_results.json`）：命令确认/旧帧、手动切局、重连恢复、实际WebSocket替换旧连接、断线退出、归档前事实、共享操作和仓库保护。尚未跑真实游戏桌面全流程，也不能从这些测试推出Overlay Solver结果已正确跨进程存档。下一阶段优先审计实际计算/快照与采集/历史展示，再处理视觉基线失败、打包、UI与功能完整性。

2026-09-05 实时状态链更新：工作循环发送带session/sequence的visionState快照，主窗口实际ws_handler接收后更新同局CurrentMatch，并拒绝乱序帧/已退役matchId。默认镜像保留GUI侧warehouseOccupancy，换局清空旧事实。明确观测到离局后工作循环更换matchId；短暂UNKNOWN不换局。已保存DRAFT允许离局清理，正式FINALIZED仍服从真实归档状态。刷新/内置replay共享发布序号，replay使用同样换局观察器；main以__main__执行时注册相同main模块，避免回调重复初始化。

自动capture触发移至主进程接收路径，worker的process_live_game_frame明确关闭原生编排；主进程刷新自己的capture展示。settlementStable由归档前的稳定/已完成状态传输，不再仅凭结算场景或hadSettlement判断稳定。

验证：`test_live_match_transport`使用独立Python子进程连接真实本地WebSocket，经过生产ws_handler传入两局快照并发回旧局晚到帧，确认主窗口事实更新、旧字段清空且旧帧不再广播。连同结算/离局/自动采集测试共28项通过，结果`live_transport_test_results.json`。这不是完整真实游戏GUI两局验收。仍待：手动事实/下一局命令与worker协同、断线重连/多连接归属、归档在warehouse同步之前的时序、真实自动采集与Overlay Solver快照跨进程证据、既有视觉缺陷、打包和UI核验。

2026-09-05 跨进程写盘更新：CanonicalHistoryStore的新增/覆盖、DRAFT占用补写、审核更新、删除均在原进程内锁外配合按数据库路径的OS文件锁；读取最新记录到替换写盘期间不允许另一进程写入，支持同线程嵌套补写，异常退出由OS释放锁。新的双进程测试在父进程持锁时确认两个子进程不能写盘，释放后同时写入的24条不同记录全部保持。多进程/占用/结算18项和审核写盘9项全部通过。证据`multiprocess_test_results.json`、`history_review_lock_test_results.json`。这验证HistoryStore的进程间互斥，不代替Main/worker状态镜像或所有旧代码写入入口审计。

HEAD对照已结束：6项视觉失败在修改前版本全部复现，失败断言签名完全一致（`head_baseline_test_results.json`）。因此这些是已存在的问题，仍纳入持续修复队列；不据此改动预期掩盖缺陷。原运行句柄84151已退出，不再轮询或重启这次对照。

持续目标已由用户扩展为“全部做完，做完之后自己找bug，找ui优化。找功能实现”。原计划全部阶段保持，另外包含稳定版本上的主动缺陷检查、实际渲染界面检查与有证据的功能缺口实现；不能以目前局部修复或测试通过代替全部完成。

2026-09-05 后续实施：实时sync已接入显式acquired并补齐已观察数量等事实；CurrentMatch与AutoArchiver共享严格bool/null归属规则。工作循环、关闭flush及内置replay改为依据同局归档返回的真实lifecycle设置状态，DRAFT不再触发pipeline finalized。归档去重加入matchId和winner/acquired，避免金额相同的新局或新归属证据被60秒窗口吞掉。新增自然链/工作循环回归，连同既有归属测试22项通过。对应证据`build/takeover_20260905/settlement_authority_test_results.json`。

大厅三个模板目录已补入spec，源码资源计数8/2/1，语法检查通过；尚未重建冻结包，不能宣布包能力已验证。主进程接收与worker状态一致、跨进程写盘、连续两局、视觉输入边界、完整打包与UI验收仍待完成。

扩大回归47项：41通过、6失败，无错误/跳过；结果`settlement_related_test_results.json`。失败均在test_live_vision_worker_liveness_v1，分别为结算帧误判IN_AUCTION（2项）、DF回退调用次数（1项）、非局内四席识别调用（1项）、末秒全图扫描调度（1项）、跨轮出价落点（1项）。其余当前局展示/History展示/仓库补写用例通过。已启动`run_head_baseline.py`，通过import loader加载HEAD版本的本轮修改模块，仅复跑这6项，不改工作区，输出`head_baseline_test_results.json`；在基线结果出来前不裁定这些失败由本轮引入。

下一目标是交付一版“连续两局的数据可靠保存、主窗口与 Overlay 一致、安装包能力与源码一致”的 Alpha。先处理已有证据支持的阻塞，再进入集中真人 UAT。此前桌面 smoke 的通过记录继续保留，但不能据此推定真实采集、跨进程状态和晚到仓库补写都正确。

当前已修改产品源码并进行隔离验证，尚未提交、迁移生产历史或重新打包。

## 审查范围与证据边界

全目录清单覆盖 10,074 个文件、2,704,706,733 字节，其中 Git 跟踪文件 766 个。排除 `.git` 内部数据库和本轮新生成的审查目录。所有清单文件均完整读取字节并记录 SHA256，无读取错误；4,011 个可解码 UTF-8 文本完成全文扫描，6,063 个文件归类为二进制或非 UTF-8。

314 个 Python/spec 文件完成语法树解析，17 个 JavaScript/内嵌脚本完成语法检查，识别出的 JSON 无解析错误；1,662 张项目/构建图片完成解码检查。全量索引包含 43 个 Markdown 文档，项目自有候选文本 696 个。

**这不等于逐行人工理解全部文件。** 人工语义审查集中于入口、主窗口桥接、视觉工作进程、CurrentMatch、归档与补写、仓库证据链、Solver 接线、摘要导出和打包配置。第三方运行库、缓存和旧构建包只做清单/格式层检查；图片解码不等于逐张视觉验收。尚未完成全部源文件逐行语义审阅、全部测试或实际双进程 GUI 整局验收，不把这些标记为完成。

原始证据位于 `build/takeover_20260905/`（本地忽略目录）：

| 文件 | 用途 |
| --- | --- |
| `file_inventory.json` / `scan_summary.json` | 逐文件读取、哈希、类型与覆盖统计 |
| `python_structure.json` / `markdown_fulltext.json` | 代码结构与文档全文索引 |
| `javascript_parse_results.json` / `image_inspection.json` | 脚本语法与图片解码 |
| `first_test_results.json` / `second_test_results.json` / `third_test_results.json` | 三批独立测试结果及完整异常 |
| `boundary_probes.py` / `.json` | 消息接收、acquired 同步、类型与模板复现 |
| `data_preservation_probe.py` / `.json` | 仓库补写前后历史字段对比 |

## 已验证的问题

### P0：仓库晚到补写覆盖已存事实

隔离复现中，已有 DRAFT 的 `goldCount=4`、`totalItems=30` 和 R1 出价历史，在仓库采集完成后变成 `null`、`null`、`{}`，占用信息则成功写入。

`app/warehouse_capture_host.py::_persist_draft_occupancy` 在同局 CurrentMatch 存在时用其整个 canonical 记录替代磁盘记录；CurrentMatch 未持有全部已存事实，随后 History 进行整条替换。因此“occupancy 已写入”不足以证明该链安全。这是对 Phase13 的新反例，仅重开补写数据保持性，不推翻全部仓库阶段。

### P0：主窗口与工作进程的事实衔接缺口

视觉工作进程通过独立 subprocess 启动，模块级 CurrentMatch 并不跨进程共享。调用实际 `ws_handler` 接收模拟工作进程消息后，`LATEST_PAYLOAD.q=12`，主进程 `CURRENT_MATCH.facts.q=null`，两端 matchId 也不一致；当前局摘要读取后者。

这是实际消息处理函数的隔离复现，尚非完整原生 GUI 运行结果。需沿生产入口验证当前局显示、控制命令、快照、自动采集和写盘究竟由谁负责，不能只靠同进程 harness 证明共享成功。

另有静态确定的不一致：`app/vision_worker_loop.py` 对任意非空归档返回值都设置 `FINALIZED`，未检查保存记录实际是否仍是 `DRAFT`。需用生产进程验收补齐影响证据。

### P1：显式 acquired 没有贯穿实时同步

`sync_vision_to_current_match` 输入明确 `acquired=True`，输出 CurrentMatch/canonical acquired 仍为 `null`。已有四层 fail-closed 修复不覆盖这个输入通路。

另外 `CurrentMatch.apply_facts` 使用一般布尔转换，字符串 `"false"`、`"unknown"` 等会变成 True。后者是边界健壮性反例，不表示 OCR 当前正常输出这些类型。应限定 bool/null 合同，未知不得推断归属。

### P1：源码与当前包的大厅模板不一致

源码实际加载角色 8、会场 2、仪器 1 个模板；当前包 `_internal/assets` 下三个目录均缺失，实际加载数量均为 0。打包 spec 未列入这些目录。当前包 build_info 声明 commit 与审查基线一致，故不能归咎于使用早期版本。

### P1：整局回放存在错误 winner 候选

现有真实帧 smoke 把 `11m` 写入 winner，测试预期为未知。检查 `assets/settlement_frames/sec_478.jpg` 可见这是含桌面侧栏的录屏，侧栏出现 `11m`；结算赢家筛选按整张图归一化区域取候选。

需区分桌面录屏与游戏客户区截图，统一裁剪/坐标和场景准入，再验证 winner；不能只屏蔽 `11m`、改断言迎合当前输出，或据此认定纯游戏截图也存在同样问题。

## 测试结论

使用可工作的 Python310 环境独立执行 27 个测试模块，共 **192 项：187 通过、4 失败、1 错误、0 跳过**。测试数据与采集输出分别隔离到 `YIHUAN_DATA_ROOT`、`YIHUAN_UPPER_TAIL_CAPTURE_DIR`，未对生产 History 执行回放。

| 未通过项 | 当前判断与处理 |
| --- | --- |
| real replay winner 得到 `11m` | 已检查原图，先明确图像输入与坐标合同 |
| 75s warehouse 预期 5、实际 6 个槽 | 待逐框比较真实物体与夹具，不能直接改数量或全面重开 Phase20 |
| archived identifiedName 预期“金色大货”、实际 None | 核对夹具是否提供当前 EXACT authority；不为通过测试提升候选身份 |
| canonical 预期 FINALIZED、实际 DRAFT | 夹具与当前 acquired/真值要求有差异，先核对有效终态输入 |
| FINALIZED 不可变测试在构造时出错 | 缺明确 acquired，尚未运行到不可变断言；修合法夹具，不放松校验 |

Shared Core 接线、v0.6 adapter、评估资格、运行时数据路径及角色/大厅 matcher 这批 65 项全部通过。Summary、JSON Export 相关用例已在本轮可用环境执行，属于已有能力；不再规划为从零开发。局部通过不能代替实际进程与安装包验收。

## 实施顺序与验收条件

### 1. 保住已保存的数据

第一项施工仅修仓库补写：基于同局已存 DRAFT 做受限 occupancy 更新，明确保留字段，不以不完整实时对象覆盖整条记录。

验收：补写前后的情报、出价、身份审核、预测与结算非目标字段保持；相同包重复完成不增记录；异局、缺记录与 FINALIZED 不写入。补充旧包晚到不能污染新局 CurrentMatch 的回归检查。使用本轮最小复现作为首个回归入口。

### 2. 明确状态和写盘归属，修通实时链

画清 Main、Overlay、vision worker 的实际运行边界；指定当前局事实和 History 写入责任，使用明确的快照/事件传输与 matchId/version 校验。先沿既有通信修复，不直接决定大规模重构。

逐字段核对 acquired、情报、出价、warehouse、结算、预测的接收与保存路径；归档成功与 FINALIZED 分开表达。确认下一局生成新 id，旧包不能推进新局状态，断线重连不会回放过期状态。

验收：从实际工作进程注入已知观测，Main、Overlay 和同局磁盘记录一致；明确本人/他人/未知分别保持 true/false/null；DRAFT 不因归档返回非空而被当作终态。并验证两进程写入是否需要收敛为单写者，不能仅靠线程锁假设安全。

### 3. 清理回放输入边界和失效夹具

先给既有录像/截图标注来源、游戏区域、分辨率和坐标变换；无可靠区域的图像不产生权威 winner。将当前五项异常逐一归类为实现缺陷、夹具失效或证据待定，保留原始失败记录。

验收：修复后原失败有明确解释和对应断言；纯游戏帧与桌面录屏各有正反例。75s 只在物体级证据支持时修局部分割，不重新做整个 Phase20。

### 4. 修打包并建立可复现环境

纳入大厅三个模板目录，增加必要资源清单检查与实际加载校验。统一版本/启动说明，记录 Python 与依赖安装来源，使其他环境能复现本轮测试。保留 commit、资源哈希和构建时间。

验收：同帧在源码与冻结包加载相同必要资源并给出一致关键事实；新包在独立运行目录启动，无源码路径依赖。旧包保留作为比较基线，暂不清理。

### 5. 真实进程整局验收，然后集中真人 UAT

复用现有 harness 和截图，不另造回放系统。当前 real replay smoke 未覆盖真正 Main/worker 双进程、完整自动仓库采集和退出重开，须补这些连接。

自动验收连续两局：入局→情报→预测→结算→自动采集→同局 History→退出重开→摘要→JSON 导出；另覆盖采集中断、工作进程断开和旧结果晚到。核对记录数、id、字段、终态、审核状态，未知不显示为确定事实。

通过后固定同一 commit/package 做集中真人 UAT，收集实际分辨率、场景和失败截图；每个失败对应可复现入口。此时才形成可交付 Alpha 的结论。

### 6. 在稳定版本上收集识别和算法证据

继续使用现有人工身份审核与 reviewed-label 导出工具，确认离机后证据图片可访问；JSON 导出本身不等于证据包可移植。

winnerCharacter、结算精确藏品身份仍需真实 ROI、标签与独立留出验证。局内候选、全仓占用与身份确定保持独立；唯一候选不得自动变 EXACT。自然预测与独立完整真值配对后才评估模型质量，历史/研究样本不混入正式准确率。

## 保留的既有决定

- v0.6 Solver 与 Shared Core 继续复用；Overlay 保持唯一生产 Solver WebView，不增加第二份估价逻辑。
- Phase20 已闭环的分割修复保持；仅凭新物体级反例重开相关点。
- 不迁移或清理旧生产历史，不自动把 DRAFT 提升 FINALIZED。
- Summary、Export、候选收敛、人工审核和占用链均已有实现，工作重点是完整性与连接验收。
- 研究侧当前证据不足，不能把探索性实验结论写成产品精度保证。

下一施工入口：复查改后的实际窗口，并验证Overlay异步预测到worker归档的时序；继续第2项完整两局链，随后依次处理视觉基线、打包和功能验收。第1项已按上述范围修复。每项更新本计划与Obsidian当前交接，用实际运行结果记录完成范围。

## 2026-09-07 接手断点｜实时恢复目标继续执行

- Obsidian MCP 本轮读取失败：`vault_read` 返回 HTTP transport error；已确认 `D:\ObsidianLiveSyncTestVault` 为同一 Vault 后改用本地文件读取。未伪称已同步。
- 实际状态：HEAD `5bebd1ba8204685eb2c910573bc20304426cf2e5`，分支 `main`；工作区保留大量既有未提交修改，禁止 reset/clean/覆盖。当前源码尚未证明已打入新包。
- 正在运行实例：`D:\yihuanpaimai\build\takeover_20260906\final-live-package\异环拍卖助手\异环拍卖助手.exe` PID 3860；其 `--vision-worker` PID 11192。两者是上一包用户窗口，暂不盲杀、不当作本轮源码证据。
- 本轮隔离目录：`D:\yihuanpaimai\build\takeover_20260907\`；解释器：`D:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\python.exe`。主录像和已有 probe/日志保持不变。
- 已核对 Obsidian README/Handoff 与本地工程计划：当前唯一目标是实时估价资格/时效、结算采集推进与保存、取消晚到结果安全、随后独立构建交付包；不追旧五场 106/106，不污染生产 History。
- 当前下一条执行顺序：核对现有价格链（尤其 `goldAvg` 资格语义）和已有 OCR/采集/取消修改是否真实生效；针对确认缺口做最小修改与三组限定验证；最后用正式 spec 在新的子目录构建并做最小启动/关键接口检查。

## 2026-09-07 实时恢复最小修复与交付结果

- 未修改正式图鉴、Solver 算法、历史价格快照或生产 History；未 reset/clean/checkout，保留工作区所有既有未提交改动。
- 最小代码改动：`core/live_shadow.py` 增加非 stale Shadow 完成回调；`app/main.py` 将完成的概率/预测结果立即合并到同局最新 HUD payload，并拒绝异局 snapshot；`app/warehouse_capture_host.py` 取消后保留 review packet 但禁止 occupancy sink/CurrentMatch/History DRAFT 写回；`core/overlay_alpha.html` 缺少 Q/金色均价时明确“不生成正式出价建议”。
- 相关定向回归：33 项全通过。证据：`build/takeover_20260907/validation/targeted-after-fix/`。
- 限定验证：`build/takeover_20260907/realtime-recovery-evidence/targeted-validation.json`。主录像 SHA256=`233a43e631c65d02417050fa9f0d89eb48301ef636daa46eb7a153498d96d86a`；t=40s 真实画面事实 q=67、goldAvg/avg 缺失，Node fallback 三条正式线均 null；UI 文案明确不报价。隔离 Shadow listener 回 Main 约 0.017s；settlementReady=False + grid=OK/TOP 时 capture prepare/confirm 成功；wrong scene 不触发；前台等待恢复、取消 sink 不写回、prediction late response 拒绝。compute stub 仅用于验证发布链，不冒充真人价格。
- 正式 spec 构建成功：`build/takeover_20260907/realtime-recovery-package/异环拍卖助手/异环拍卖助手.exe`。EXE SHA256=`445ff0cf9a2e4ac26b48c6de8527c4a884f7a1180f865c2bfa3efa8f42af663a`；source fingerprint=`37d88cc410dc61d37d5561889e9202f92e75466064fb5670a3080ac710cb505f`；证据 `build/takeover_20260907/realtime-recovery-evidence/package-evidence.json`。隔离 smoke 使用 8876 临时端口通过 Main/HUD/WebView2/worker/正常退出；正式包未改默认 8766。
- 当前最终边界：录像本身没有独立金色均价时保持 unknown/不报价；真实游戏窗口滚轮、完整结算原图落盘与真人端到端合法价格时效仍 UNVERIFIED。当前新包已启动（主 PID 26032、worker PID 14312）供用户直接实战；不继续主动找下一项优化。

## 2026-09-07 实际合法输入链与采集会话补证

- `build/takeover_20260907/actual_valid_input_chain.py` 在隔离 `YIHUAN_DATA_ROOT` 中复制既有历史样本，走实际异步 `live_shadow` runtime、`app.main._publish_live_shadow_event` 和 `auction_engine_v06.js`。q=12、goldAvg=74379、purpleCount=7 的 full-shadow 输入：首次返回约 0.003s，Shadow 完成并发布约 0.736s，正式 P50=`437503.013...`、safeBuy=`359585`、recommendedMax=`432503`、chaseLimit=`437503`；总价格链约 0.795s。源 History 与隔离副本前后 SHA 均为 `36278a8e7648defdb5488ffecfc144dca5f1ad04dd9af50655c2e0e1187207b6`。
- `build/takeover_20260907/actual_capture_session_evidence.py` 走实际 `WarehouseCaptureSession` 与隔离 `SettlementEvidenceStoreV2`：TOP→MIDDLE→BOTTOM 共 3 段、2 次 DOWN、coverage=`COMPLETE`，首段保存原图按保存 descriptor SHA 校验通过；取消在首段保存后返回 `USER_STOP`、coverage=`PARTIAL`，没有后续滚轮请求。
- 采集证据的 requester 是录制适配器，不是原生游戏窗口；因此原生窗口滚轮与真人完整落盘仍 `UNVERIFIED`。本轮只新增 build 证据脚本/JSON，没有新的 production logic，现有 EXE/source fingerprint 无需重打包。
- 新证据：`build/takeover_20260907/realtime-recovery-evidence/actual-valid-input-chain.json`、`actual-capture-session-evidence.json`。当前正式包仍为 `build/takeover_20260907/realtime-recovery-package/异环拍卖助手/异环拍卖助手.exe`。

## 2026-09-07 Goal 停滞纠偏补充结果

- 无均价时序已补齐到当前 worker/Main/Overlay presentation seam：主录像同源 t=40s 冷路径首个事实与明确不足约 `5.579097s`，完整识别任务结束约 `6.035262s`；同源 t=50s 依据已有阶段耗时并以 t=40 seam 推导约 `3.667797s` / `3.733662s`。这回答了原约 50s 等待已改善，但不把合法 q+goldAvg 或 WebView smoke 当真人端到端；原生 WebView repaint、真实游戏窗口仍 `UNVERIFIED`。
- 复用已有真实录制帧 `tests/fixtures/seats_bids_v1/frame_t360.png`（SHA=`7e5c3b744b6eabfc06e18c0a1791b52ce495d9491aefa278a497b7f811263dfd`）走当前源码视觉 smoke 与异步 Shadow/Main：q=11、goldAvg=47286，约 `1.031354s` 完成 `solverStatus=valid` 的 `partial_shadow`。帧内没有独立 `purpleCount`，所以无正式分位/三条价格线；证明不是计算一直卡住，而是事实覆盖不足。证据：`build/takeover_20260907/realtime-recovery-evidence/valid-frame-smoke-v1.json`、`valid-frame-price-chain-v1.json`。
- 另复用已有完整回放帧 `continued-recognition-v3a/v1-0181.000.jpg`（SHA=`3339785983a013265ba514f3728aedf3aa9ede028cba84d625a19a12c8f6b9be`）探查生产视觉上下文：`q=5、goldAvg=76591`，但 `purpleCount/purpleAvg/goldCount` 均为 `null`，没有可独立证明正式三段价格线的输入；不从 warehouseSlots 反推。证据：`build/takeover_20260907/realtime-recovery-evidence/valid-frame-context-v1.json`，并已挂入 `completion-audit-v2.json`。
- 对旧录像 `frozen-recording-inputs` 的两段各 4 帧短序列走当前 `NTEVisionPipeline`：`frame_00007..10` 最后取得 `q=12、goldAvg=74379`；`frame_00041..44` 最后取得 `q=11、goldAvg=47286、purpleAvg=4357`；两段 `purpleCount` 都没有独立输出。证据：`build/takeover_20260907/realtime-recovery-evidence/goal-short-recorded-sequence-v1.json`，说明事实链可结束但完整价格输入仍不足。
- 直接探测当前 `auction_engine_v06`：`q+goldAvg` 无紫件数时仅为 `structural_only`（结构 `formalValue.p50` 不等于决策 `valueP50`，三条线仍为空）；`q+purpleAvg` 或 `q+purpleCount` 无 `goldAvg` 时均 `fallback`。无均价分支没有现成合法估价模式，证据：`build/takeover_20260907/realtime-recovery-evidence/goal-partial-input-contract-v1.json`。
- 取消控制已通过真实 `MainWindowBridge` → `WarehouseCaptureHost` → `WarehouseCaptureSession` 在途任务实测：最新 `CANCEL_ACK_LATENCY=0.000040s`，令牌 ACK 前置位；首帧抓取在 confirm 返回前已观察到，首段保存约 `0.031418s`；无新 requester 输入，晚到 `USER_STOP` 结果未进入 occupancy/History，worker 终止约 `0.018086s`。证据：`build/takeover_20260907/realtime-recovery-evidence/goal-cancel-ack-v1.json`。
- 本轮只新增 build 下诊断脚本/证据与交接记录，未修改 production logic，未重打包，继续保留 v2。当前判断：离线工程链可交付为 `PARTIAL`；无独立 `goldAvg` 是估价能力缺口（需要独立金色均价观测或经授权的可审计估价模型/数据），不是录像重复输入问题；原生真人 UAT 仍 `UNVERIFIED`。
