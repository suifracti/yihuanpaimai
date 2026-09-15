# 主窗口预测交接与两端冲突冻结

21d6ee7修复生产结果发布到HUD但未更新Main所读ACTIVE_SNAPSHOT_HOLDER的问题：已接受同局完成事件与当前手动attach返回的已完成缓存均交接；原同局/来源保护保留。主窗口预测摘要明确携带solverStatus，no-match清除分位/建议金额并显示约束冲突原因；界面优先按状态显示无可行解与冲突行动标记。

源码与干净21d6ee7冻结同EXE通过：空历史、珊瑚琉璃、真实算力面包和断落的剑柄条件，HUD蓝格2→1→清空，生产valid/no-match/valid、exact非空/空/非空；Main预测状态及DOM无可行解/约束冲突与HUD一起出现并恢复。报告 build/constraint_main_20260913/{final,frozen}/report.json。1项发布回归PASS（3.187秒）。第一次source定位Main预测None；verified测试误读不存在的action-title节点，改为实际action-badge后验证，失败保留。

最新候选 build/isolated_trial_constraint_20260913/dist/异环拍卖助手，metadata21d6ee7/isDirty=false；包含前轮空历史计算修复。仅此组计算纵向证明，不等同全参数、全部历史/导出或游戏输入验收。

下一步继续扩展件数/均价/总格等实际参数对照与剩余语义、布局；P3 PARTIAL，P4实施中，完整试用/P5未完成，逐件匹配调优暂停，v13未覆盖。
