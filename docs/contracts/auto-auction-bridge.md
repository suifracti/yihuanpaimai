# 自动拍卖后端桥接

2026-10-20：按 `docs/plans/2026-10-20-sol-until-usable.md` 连续接线中。
前端归 Claude。本文件记录实际已接字段，不代表十局无人值守验收已通过。

## 已接：报价前准备

`liveDomainLoop` 的 `phase` 新增 `preparing`。`reason` 表示正在等哪个操作的新画面。
新增 `preparationActionReceipt`，包含 `intentId / kind / status / reason / matchId /
matchGeneration / observationSessionId / round / factsRevision`。

`kind` 仅有：`OpenInstrument`、`SelectGoldAverage`、`UseGoldAverage`、`OpenBidPanel`。
状态沿用 `NOT_SENT / SENT_PENDING_CONFIRMATION / CONFIRMED / UNKNOWN`。
准备回执与 `bidActionReceipt`、返回/下一局的 `domainActionReceipt` 分开，不推动结算归档状态。

缺金均且 Q 已知时，按已有 Solver 所需输入使用金品均价仪器。
选中行不算使用；关闭列表也不算成功，Host 要看到金均专属情报标题。
标题可见不填金均数字，仍等同局真实事实与 Solver 结果后打开报价面板。
未知结果不重发。未观察到使用成功或支付金额时不写成消耗、免费或已付。

Host 的 `domainObservation` 是同一张 WGC FRAME 的页面/资金规划信息，
`planningOnly=true, inputActions=false`，不当作 SOURCE 或输入票据。
实际操作仍重新取得独立帧、核对窗口/控件并消费一次性票据。
Python 不再另截桌面、压低 Main/HUD 或直接点游戏。

## 后续产品开关

2026-10-20 开局前补仪器：`autoAuction.minimumFunds` 默认100000，
`autoAuction.instrumentTargets` 默认 `{"goldAverage":1}`，也支持当前仪器组的 `purpleCount`。
`liveDomainLoop.phase=restocking` 时不入场；`restockSpent` 记录本次实际确认的补充支出。
Host 新增 `OpenToolSetup / RequestToolRefill / ConfirmToolRefill / CloseToolSetup`，
沿原 preparation 回执与三秒新画面确认。大厅使用 `lobby-<observationSessionId>` 上下文和 round=0，
不创建竞拍事实或跨局写入。`domainObservation.instruments` 提供可用数量、补充价格和资金。
数量够则关闭窗口，资金下限、数量不可读/目标达不到、未知回执则给出原因停止；不买完假定成功。
目前只接已观测的高级品鉴组“一键补全”，不支持的组/更高储备数量无法达到时停止，不能声称已补齐。
局内已有金总价或全仓可行区间时可沿原 Solver 产生报价；没有可用数值则本回合不报价，继续观察。

`auto_auction_start / auto_auction_stop` 与 `app_status.autoAuction` 按主计划 M5 接入；
**当前尚未提供这些动作**。完成时在这里更新确切请求体及状态字段，再由前端接按钮。
当前临时环境开关仍需在 M5 删除。费用确认的 Host 接线、持续循环及真实验收尚未完成。
