# 八类实际计算对照与红格漏传修复

a29678b补Python/JS adapter中redGrid从canonical qualities.red.grid和平铺输入到顶层及publicInfo的传递。此前界面双向通过但计算未收到；冻结21d6ee7真实对照在红数0/红格1时没有产生冲突，已保留失败报告build/constraint_matrix_20260913/frozen/report.json。

修复源码真实应用24组PASS：蓝格、蓝件数、蓝均价、总件数、总格、金格、紫格、红格各可行/矛盾/清空恢复；每次检查输入回传、生产snapshot valid/no-match/valid、exact候选非空/空/非空、Main与HUD冲突出现/恢复。报告build/constraint_matrix_20260913/source-fixed/report.json。固定真实算力面包和断落的剑柄基线，不注入计算结果。9项转换/面积回归PASS，5.110秒；新增Python/JS canonical和平铺红格4/0/None及嵌套传递校验。

源码尚未入包，最新冻结仍21d6ee7，已知其红格漏传尚在。下一步统一冻结24组复验，继续其余参数/场地倍率/布局验收。仅此八类固定案例，不代表所有参数组合或完整游戏验证。P3 PARTIAL、P4实施中、完整试用/P5未完成，逐件匹配调优暂停，v13未覆盖。
