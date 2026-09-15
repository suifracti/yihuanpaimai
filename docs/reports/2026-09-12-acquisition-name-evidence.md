# 自动归属：本局姓名证据连接

业务提交2092876。新增AcquisitionNameTracker，以recordStableKey隔离：生产Keyboard管线仅将本帧高置信四席OCR与最终显示姓名、对应席位一致的文本计为新样本，同一帧不重复计数；两帧稳定姓名后才构成本局名单。结算winner新增confidence/ambiguous，需两次新帧高置信一致且唯一对应本局稳定姓名；对应第4席为本人，其余席为非本人。名单缺失、同名、未知winner、低置信或冲突不能猜；新winner冲突撤销自动确定，空弱帧保留已确认值。新局/重置清空跟踪器。生成settlementData.acquired及ctx.isAcquired，沿用既有CurrentMatch/AutoArchiver显式布尔入口。

真实回放首次抽帧未进入生产场景，不能算通过；改为前置连续30帧场景检测。首次姓名采样暴露聊天“你骗人”污染，改为最终名单与新鲜OCR双重对应后再采样；旧缓存姓名不是新证据。最终D:/video/2026-09-08 14-40-37.mkv在110/112/114秒读到本人PLAYER_LOCAL及三位他人，在159秒结算winner致敬最良心不歪首次观察为未知，162/165/168秒自动acquired=false，置信约0.997且无候选歧义。不是按出价或利润倒推，也未注入winner/myName。116秒场景仍UNKNOWN，未伪装全时间线通过。

复现脚本build/codex_other_video_20260912/replay_acquisition.py；结果acquisition-real-replay/report.json。该回放验证生产像素/OCR到非本人布尔，未做本轮实际Main/HUD归档回看，也未完成真实本人拍下录像验证。首次脚本时间戳不合法已修正，最终无该错误。

acquisition-integrated-tests.json：32项通过65.141秒，无跳过，涵盖新鲜帧、本人/他人模拟、跨局、同名、未知、低置信、冲突撤销及现有CurrentMatch/AutoArchiver归属保护与真实结算winner图。正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431。未覆盖v13，未做真实游戏输入。

唯一下一步仍是自动归属：补真实本人拍下样本、自动结果到保存/重启历史显示的纵向验收、缺席/迟进入结算等边界与来源留档。只有完整可用后才转回一般P4 UI参数。不允许每局依赖人工确认；目前证明的是一个他人拍下开发样本，不能外推完整准确率。P3 PARTIAL，自动逐件匹配暂停，试用包未完成，完整目标保持。
