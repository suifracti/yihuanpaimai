# 天黑隐藏叫价的决策保护

发现FIELD_CONDITIONS.dark虽登记hiddenBids，calculateV06DecisionLines和solveAuctionPipeline仍会使用ctx.leaderBid判断追价盈亏/弃拍。修复：隐藏词条传入的旧叫价不参与expectedProfit/ROI，也不触发超过全局/边际线的判断；藏品价值及参考线保持，已付费用不变。完整估值时提示“出价金额不可见；保本线仅作私人出价参考，不使用旧叫价判断追价盈亏”。decision增加hiddenBids，原始输入不修改。

tests/test_dark_bid_guard.py覆盖dark/中文别名×None/0/10000/900000的直接引擎与生产Node入口；生产快照盈亏/ROI为null、不弃拍，估值/全局/边际线一致，保留输入原值。标准条件生产入口的低价正收益/高价负收益保持。加其余四词条16组语义对照，共3项PASS，6.559秒，build/dark_bid_guard_20260913/verified.json。

初次标准对照使用无概率资料的直接引擎，expectedProfit本就null，后改为与正式功能相符的生产入口；失败测试保留。修复未隐藏或删除原始证据，不声称视觉层已处理。

尚未接Main/HUD隐藏金额展示、私人上限/可见次数的保存入口与实际切换验收；源码未冻结，最新候选仍d458188。下一步连接这些链路，再处理免费情报事件。P3 PARTIAL、P4实施中，P5/完整试用未完成；逐件匹配调优暂停，v13未覆盖，不执行真实70秒操作。
