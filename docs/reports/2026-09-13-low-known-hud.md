# 低品质名称悬浮窗与双向同步

49e3d10补悬浮窗折叠区三色已知名称、实际图鉴建议及校验，输入采集/订阅更新/切局重置和事件绑定；补原生手动及实时payload传递。60390c4修旧状态测试未载入实际formatExpectedProfit的问题，四种场景状态回归PASS。

build/low_known_dual_20260913/blur/report.json PASS：真实双窗口每色主窗口名称提交→HUD显示，HUD候选+重复3件→主窗口标签一致，HUD清空→主窗口空，保持同一matchId。使用实际DOM input与显式blur事件；不调用后端注入。此前source/focused/debug/errors/expanded尝试未触发真实blur提交而超时，失败日志保留。该证据不是游戏鼠标键盘输入验收，也不是全部计算/重启历史验收。

源码未入包，最新候选仍225286d。下一步统一冻结本轮双向验证，继续数值字段两端链与计算一致性。P3 PARTIAL、P4实施中、完整试用/P5未完成，逐件匹配调优暂停、v13未覆盖。
