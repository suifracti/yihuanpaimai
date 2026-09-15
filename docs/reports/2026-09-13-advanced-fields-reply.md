# 高级字段回传与表单清空修复

c004175修主窗口摘要facts漏回传blueCount/goldCount/totalItems/totalGrid：输入已进入fieldStates、qualities/publicIntel，但表单只从facts刷新，导致四项输入被回执清空。现在从相同事实源回传四字段，不改求解权威。

旧95929c4冻结实际DOM填写8字段验证失败，证据build/advanced_fields_20260913/frozen/report.json；包含已进入内部状态但facts缺字段的原始回执。修复后源码source-fixed、冻结frozen-fixed均PASS：真实Main输入蓝3/金2/红1/总件12/紫均12000/总格40/金格8/紫格6→原生facts回执→DOM值相同，再主动清空8字段→回执None/DOM空，正常关闭。工具tools/verify_advanced_fields_ui.py。两次成功报告位于同目录。

新隔离包build/isolated_trial_fields_20260913/dist/异环拍卖助手，冻结c004175；继承此前95929c4识别修复，但本轮仅重验高级字段回传及清空，不冒充8字段全部求解/归档/重启验收。初次失败保留。下一步核对这些字段保存重启与历史显示，继续P4字段完整生效；P3 PARTIAL，完整试用/P5未完成，逐件调优暂停，v13未覆盖。
