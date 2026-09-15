# 冻结包识别进程退出恢复

隔离候选 build/isolated_trial_worker_20260913/dist/异环拍卖助手，冻结提交9cba07e，构建元数据isDirty=false，包含d948d25生产改动。

build/isolated_trial_worker_20260913/exit-ui-verified/report.json PASS：实际冻结Main/HUD，结束真实识别子进程，从主窗口恢复14796→30996，再从HUD恢复30996→24144；两次对局ID不变，恢复到WAITING，正常关闭。无游戏待机验证，不冒充游戏中OCR异常、连续录像或本人获胜准确率。

首次测试因PowerShell中文进程路径输出编码导致验证器严格路径断言失败，未执行误杀；明确UTF-8输出后清理已观察到的本次子进程，重跑同一冻结包通过。首次失败记录保留。测试工具修正未改变冻结生产代码。

下一步推进同一候选的连续运行与延迟定位；P3 PARTIAL，完整试用/P5未完成，逐件调优暂停，v13未覆盖，无真实70秒游戏输入。
