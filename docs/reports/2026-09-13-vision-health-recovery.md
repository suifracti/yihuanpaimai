# 识别异常与恢复提示

c27a8cc增加采集/识别/界面数据构建异常的vision_health状态；异常继续沿既有循环重试，不注入事实、不清空当前对局。主进程只接已登记识别工作连接的健康消息，单独合并健康字段，不把状态消息类型覆写成正常对局消息。主窗口与HUD提示“识别暂时异常，正在重试；当前显示为上次结果”；正常帧READY或无游戏WAITING清除异常提示。

build/vision_health_20260912/tests.json：1测试覆盖capture/recognition/presentation三类故障子例，错误状态不带对局事实，循环继续发布正常q=5和READY，通过。此为故障注入回归，不是OCR准确率。

build/vision_health_20260913/real-ui/report.json PASS：真实源码Main/HUD双窗口，原生工作连接发送ERROR→WAITING→ERROR→READY，主窗口读回健康状态与两端DOM显示/清除一致，正常退出。工具ed1983c。UI中健康事件为显式注入，不能称真实OCR异常已在实机触发；结合循环回归验证分层链路。最新冻结包仍7e18ea2，本轮业务尚未重建入包。

下一步合并健康提示到候选，并继续连续识别与延迟验收；P3 PARTIAL、完整试用/P5未完成，本人获胜实录、完整跨局/实机滚仓/性能门槛保留。v13不变。
