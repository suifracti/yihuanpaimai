# 历史归属与收益展示

业务提交809f2cb。实际他人获胜录像归档记录ownership-replay-144037中，winner为致敬最良心不歪、acquired=false、账单realizedProfit=333902。此前历史详情把该数字显示在“本局净收益”，可能误认为本人收入。现统一按严格布尔归属展示：他人拍下显示“他人拍下（非本人收益）”；未知显示“归属未知”；本人拍下才显示结算账面数字。字段改名“结算账面收益”，不宣称已扣完整成本/奖励后的个人净现金。原始账单证据不改写。拍下方显示本人/他人/未知及已读winner名称。当前与历史投影拒绝把字符串、数字或容器强转为归属。

验证：build/codex_other_video_20260912/ownership-presentation-tests.json，21项通过4.015秒，无跳过。包括true/false/unknown和非法归属值、单字姓名与姓名跟踪边界。

真实Main/HUD：tools/verify_ownership_history_real_app.py复制实际录像自动归档数据至隔离目录，通过真实历史行点击检查主窗口DOM，WM_CLOSE正常退出后再次启动检查。ownership-history-ui-v3/report.json为PASS，两次双窗口启动、正常关闭，历史归属与收益文案一致，源记录与保存后settlement完全一致。此样本逐件审阅区隐藏，不把review-profit验收算作真实审阅通过；HUD仅确认启动，不宣称验证其结算内容。另在实际页面执行纯展示函数+1/0/-1/unknown/非法布尔值边界，这是模拟值，不是本人获胜实录。

前两次脚本失败保留：ownership-history-ui因eval_main返回已解析对象而重复解析；v2错误假定该记录存在逐件审阅DTO。v3改为验证实际可见历史详情，并在审阅区可见时才检查该区；不是修饰数据让断言通过。

正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，v13未覆盖，无真实游戏输入。本人获胜真实样本、迟进入结算、跨局自动归属与完整试用包仍待完成。下一步继续迟进入与跨局归属保护，再补其余P4参数/UI及隔离包；逐件识别优化暂停，P3仍PARTIAL。
