# 免费情报规则提示与观察事实分离

新增field_intel_status.free_intel_status并接Main/HUD原生载荷及提示。extraIntel及三别名：严格整数回合1/3提示有免费公开情报，2/4提示没有本词条额外免费情报；回合未知不默认R1。结算提示回看，新局不继承。状态为RULE_AVAILABLE/NOT_SCHEDULED/ROUND_UNKNOWN/SETTLED，observed始终false，明确只是规则可用性，不是已经观察到具体情报。

当前卡片识别ledger记录内容与证据，但缺少可靠免费公开卡/其他卡的来源区分，不能把R1/R3出现的任意情报自动视为免费。因此本轮不生成已获得intelEvents、不改变已付情报费、不新增估值事实。旧solver_core_v06按词条和回合自动写public-intel事件的行为不能直接当实际观察依据。

3项回归PASS，4.081秒，build/free_intel_20260913/tests.json：四别名×有效/无效/未知回合、费用与输入不变、Main/HUD实际CurrentMatch原生投影1至4/未知/新局一致，并保留其余词条费用/价值对照。实际源码双窗口standard→extraIntel→standard三步PASS，双方提示出现/消失一致，当前真实模型roundNo未知时显示“回合待识别”；原费用7200、估值不变。source/report.json。

未冻结，最新候选仍e590b74。免费事件准入/去重/持久化以及有来源证据的识别接入仍未完成；下一步接这条链，再统一冻结提示与事件流程。P3 PARTIAL、P4实施中、P5/完整试用未完成；逐件匹配调优暂停，不覆盖v13、不做真实70秒操作。
