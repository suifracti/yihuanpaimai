# P4 双窗口盈亏与输入验证

提交b66bc30新增tools/verify_profit_dual_real_app.py，无业务代码修改。实际源程序Main/HUD双窗口启动、通过页面输入事件和宿主回执核验：Main输入Q=12到HUD，HUD金均74379到Main，HUD当前叫价390000到宿主，清空后为null，所有阶段targetProfit=0，目标利润输入不存在。测试隔离数据，正常WM_CLOSE退出。

另在实际HUD页面调用生产AuctionEngineV06，以固定完整先验和成本构造边界，再投影到实际Main/HUD DOM。两端均显示+1、0（保本）、-1、缺出价—。此部分是合成支持数据与展示验证，没有穿过后台历史先验计算，也不代表实战估值准确率或实时OCR输入验收。

最终证据build/codex_other_video_20260912/profit-dual-ui-scoped/report.json PASS。第一版profit-dual-ui仅覆盖数量/金均和盈亏边界，已PASS；扩展出价的final/focused两轮失败，因为验收脚本同页面多次声明顶层const el导致后续脚本未执行；最终块作用域修复后完整通过。日志保留，不将脚本失败当成产品输入缺陷。

正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，无v13覆盖和真实游戏输入。P4只新增本报告列出的验证范围，不标全部参数/UI完成。下一步核对P4逐字段契约与实际成本输入，整理试用包阻断清单，继续实施尚未接通字段。自动本人获胜实录仍缺，P3保持PARTIAL，逐件匹配优化暂停。
