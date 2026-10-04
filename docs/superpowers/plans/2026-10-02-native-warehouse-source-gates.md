# Native 原帧门禁实施计划

关联：../specs/2026-10-02-native-warehouse-source-gates-design.md；用户已确认。

1. 记录当前两个Host源码的hash作为并发写入前提，仅修改匹配版本；保留既有差异。
2. 先给生产读线程native_stop/退出接现有SignalStop，编译真实Host，沿同一停止失败诊断验证正常对照与立即停止，保留前后result；通过立即回报。
3. 添加只供原帧的客户区新鲜核验入口并接TryPublish回调；不改变原Capture/FRAME/预算/消息。
4. 只补这段映射的离线几何合同和写盘前/后变化拒绝证据，编译后验证。必要受影响正常对照保留；不运行其他矩阵。
5. 最后检查本轮diff/源码及当前默认Host构建身份，更新一份build检查点，列清模拟与实机未验范围。无提交发布归档。
