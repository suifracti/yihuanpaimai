# 归属收支的原生投影与冻结历史展示

新增tests/test_accounting_presentation.py：以真实CurrentMatch调用主窗口原生摘要和HUD载荷构造器，8组本人/他人/未知、未知/零入场费、零/未知福利实收、收益1，双方sessionAccounting一致；预计后续99999不计已付，旧realizedProfit=999999不参与计算，原始藏品总值/旧利润不被修改。连同模型测试共5项PASS，build/accounting_ownership_20260913/tests.json。这是源码原生投影验证，不是实际赢家OCR。

tools/verify_session_accounting_history_ui.py在现有隔离包d458188实际启动双窗口，点击9条历史测试记录，核对完整净收益文本。本人16540、他人-3500、未知归属/入场费/福利实收显示未知、零入场费21540、零福利13540、后续未付费用不影响16540、净收益1正常显示。build/accounting_ownership_20260913/frozen/report.json PASS，原生进程正常退出。

所有记录明确source=synthetic-accounting-ui-test、collectionClass=SYNTHETIC_TEST且仅位于隔离测试数据目录，不是游戏录像/真实新局/识别准确率证据。历史展示实际验收与实时原生投影测试分开，不声称实际游戏本人拍下链闭环。此次未修改业务或重打包，最新候选仍d458188。

下一步继续天黑隐藏出价和一手情报免费事件的专属流程，保留真实游戏本人归属、默认勾选采集、未见对局与性能等原门槛。P3 PARTIAL、P4实施中、P5/完整试用未完成；逐件识别调优暂停，v13未覆盖，不执行真实70秒游戏操作。
