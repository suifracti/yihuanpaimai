# 公开情报标题来源：真实样本识别与证据传递

业务提交20fc848。人工查看tests/fixtures/intel_card_evidence_v1/r3_intel_stack.png：同屏“金品均价仪器”和“拍卖师公开情报”均为47,286，因此值相同不能推断卡片来源。实际运行快速OCR读取r3_viewport.png，两张卡原文均保留完整标题。

新增intel_card_source.card_source，严格要求完整首部“拍卖师公开情报”标题后接“本局”或“随机”；仅忽略空白，不做模糊纠错，不接受正文中提及、部分标题或尚未获得描述。IntelCardObservation序列化附cardSource.kind=AUCTIONEER_PUBLIC及EXACT_OCR_TITLE依据；其余UNKNOWN，不把未知卡称为付费仪器。该标签仅表示读到标题，不表示已确认免费事件或零成本。缓存复用is_physical_ocr=false保持不变。

现有旁证保存/恢复自动保留cardSource；历史摘要从原文重新判断，不盲信外部标签，显示“读到拍卖师公开情报标题（不代表新增免费事件）”。总费用及costClassification=UNKNOWN不变。

29项回归PASS，63.422秒，build/intel_source_20260913/tests.json。新增真实快速OCR测试验证两个goldAvg同为47286而来源仅一张为公开标题，第二次相同画面走缓存且不冒充物理OCR；CurrentMatch保存/恢复标签和费用不变。包含既有真实情报卡、跨帧确认/冲突、生产识别接线与证据历史摘要回归。原样本为开发素材，不作为未见对局验收；重复同图也不冒充两帧真实确认。本轮未冻结，最新隔离候选仍b45c50c。

下一步需要独立的公开卡多帧确认/去重及完整卡片事件，尤其“随机展示”类卡没有已路由数值时当前不会产生IntelCardObservation，不能声称已覆盖。不能凭R1/R3或同值仪器推断本词条新增免费事件。继续优先自动本人归属与试用流程；逐件匹配调优暂停。P3 PARTIAL、P4实施中、P5/完整试用未完成；不覆盖v13、不做真实70秒游戏输入。
