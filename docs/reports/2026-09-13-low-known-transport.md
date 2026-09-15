# 低品质已知名称传递缺口

已定位并修复：CurrentMatch canonical已保存knownBlue/Green/White，但Python与JS v06 adapter没有输出，live_shadow传递/缓存与LiveMatchControl嵌套覆盖也未列入。现在三字段从canonical qualities.knownItems或平铺兼容输入保留为原始表达式，并进入计算参数/缓存；人工清空替换嵌套publicInfo，避免旧约束残留。

build/low_known_20260913/transport-verified.json：6项PASS，11.618秒。实际图鉴三色名称组成二选一+重复表达式，canonical和平铺两种入口，Python/Node JS转换一致；_solver_ctx保留，清空顶层/嵌套一致且cache key变化。原联合求解回归通过。首次测试错误地要求本来原位更新的控制接口不改顶层对象；按接口传入独立上下文后检查共享旧嵌套不变，失败日志保留。

本轮只补传递，不证明低品质已知名称已经影响候选结果。下一步扩展名称解析与联合副本分配，必须保留同名/同价候选区别，不能仅按价格把明确名称串成别的藏品。最新冻结仍e09543f，源码改动尚未入包。

P3 PARTIAL，完整试用/P5未完成；二维摆放、无有限数量上限全面可行性等缺口保留。逐件识别调优暂停，v13未覆盖。
