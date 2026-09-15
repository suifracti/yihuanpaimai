# 高级数值双端与统一冻结

62cb065悬浮窗新增17项高级数值入口，放在更多件数/均价/占格折叠区；收集、监听、初始化、持续同步和原生手动/实时payload补齐。details切换触发尺寸更新，低品质名称折叠区同样适用。

源码与干净62cb065隔离包均通过真实双窗口17字段Main填写→HUD值一致；HUD修改→Main回传/DOM一致；明确0及清空分别一致，保持同一matchId。使用DOM input及显式blur，不注入后端事实，不替代游戏键鼠操作验收。测试值用于传递对照，不证明可行仓库组合或全部求解正确。

同EXE低品质名称三色Main→HUD、HUD候选+重复3件→Main与清空复验PASS。报告 build/numeric_dual_20260913/{source,frozen,frozen-known}/report.json。四场景HUD状态JS回归PASS。日常历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431。

最新候选 build/isolated_trial_dual_20260913/dist/异环拍卖助手，metadata 62cb065/isDirty=false。前轮49e3d10低品质名称悬浮窗已纳入；历史验证不自动扩为本包全项验收。

下一步：核对实际输入到计算候选/解释的纵向，剩余参数语义与布局验收。P3 PARTIAL、P4实施中、完整试用/P5未完成；本人胜局/实时性能/二维摆放等未验，逐件匹配调优暂停、v13未覆盖。
