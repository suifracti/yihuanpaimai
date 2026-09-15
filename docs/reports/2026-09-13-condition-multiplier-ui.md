# 金紫加倍实际界面计算验收

同一干净052dbb9隔离包，空历史、真实图鉴名称，通过HUD词条菜单点击及Main均价输入，验证金色/紫色加倍各五阶段：standard原均价valid→加倍原均价no-match→加倍双倍均价valid→standard双倍均价no-match→standard原均价valid。每步核对solverInput词条、生产snapshot状态、exact候选和Main/HUD冲突提示，10/10 PASS。金色使用算力面包60040；紫色取当前图鉴第一条实际名称/价格，保留报告原文。报告 build/condition_ui_20260913/{gold-focused,purple}/report.json。

验证工具 tools/verify_condition_calculation_ui.py 支持--purple与指定EXE。首次gold-frozen错误要求默认standard必写入事实，实际未显式改动时null由引擎按默认处理，测试按语义核对；gold-verified最后恢复输入因没有focus被界面回传覆盖，改用focus后同包通过。两次失败保留，未修改业务代码或伪造词条观测。使用真实DOM操作，不替代游戏键鼠验收。

最新候选仍build/isolated_trial_guard_20260913/dist/异环拍卖助手（052dbb9）。本轮新增验证工具/证据，无需重打同业务包。下一步继续其余词条、参数语义与布局，不能以金紫倍率十组代表全部规则。P3 PARTIAL、P4实施中、完整试用/P5未完成，逐件匹配调优暂停，v13未覆盖。
