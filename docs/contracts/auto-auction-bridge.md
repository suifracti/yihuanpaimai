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

`auto_auction_start / auto_auction_stop` 与 `app_status.autoAuction` 按主计划 M5 接入；
**当前尚未提供这些动作**。完成时在这里更新确切请求体及状态字段，再由前端接按钮。
当前临时环境开关仍需在 M5 删除。费用确认的 Host 接线、持续循环及真实验收尚未完成。
