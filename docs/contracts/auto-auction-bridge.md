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

`auto_auction_start / auto_auction_stop` 与 `app_status.autoAuction` 已于 2026-10-22 接入，
请求、回包和状态字段见下文「产品开关」。界面按钮和悬浮票由前端下一包接。

## 产品开关：`auto_auction_start / auto_auction_stop`

开关只有一份持久状态：`config.json` 的 `autoAuction.enabled`。两个动作都由 Main 桥接接收，
控制的就是已有的 `liveDomainLoop`，不另开一条自动循环。`CONFIG` 与文件在同一个动作里更新，
先写临时文件再 `os.replace`，写失败时开关保持原样并返回原因。

### 启动

请求（字段全部可省，参数不从 `payload` 读）：

```json
{"type": "command", "action": "auto_auction_start", "requestId": "<可选>"}
```

回包沿用 `app_status` 载荷，另加 `autoAuctionCommand`：

```json
{
  "type": "app_status",
  "action": "auto_auction_start",
  "requestId": "<原样回传>",
  "autoAuctionCommand": {"ok": true, "autoAuction": {"...": "见下表"}},
  "autoAuction": {"...": "动作之后的同一份状态"}
}
```

- `ok=false` 的 `reason` 只有两种：`CONFIG_WRITE_FAILED`（配置文件写不进去）、
  `OBSERVATION_UNAVAILABLE`（观察没起来）。后者会把 `enabled` 写回 `false`，不留半开状态。
- 成功时 `liveDomainLoop` 重置为 `null`，下一帧用 `fresh_live_domain_state()` 重新开始；
  旧的票据、`settledMatch`、`matchesDone` 都不跨这次开启复用。
- 开启后每一帧只走 `_advance_authorized_live_domain_loop` 这一条路；没有帧就没有动作。

### 停止

请求：`{"type": "command", "action": "auto_auction_stop"}`。回包结构同上。

- 三件事一起做：`enabled=false` 落盘、现有循环置 `phase=stopped`、
  主窗恢复（取消最小化，标题与状态栏写 `自动拍卖已停止：<reason>`）。
- `reason` 由 Main 给：用户点按钮是 `USER_STOP`；到 `maxMatches` 是 `AUTO_AUCTION_MATCH_LIMIT`；
  宿主派发被拒、回执未知等沿用原有停止原因。
- 重复调用幂等；同一个 `reason` 只恢复主窗一次。
- 停止不删除任何已保存的收页、草稿或细化作业；细化继续在后台跑完并合并。

### 状态

每个 `app_status` 都带 `autoAuction`；没有接产品开关的嵌入方是 `null`，不要当成“关闭”。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `enabled` | bool | 开关当前值，来自 config |
| `mode` | `"bid"` / `"observe"` | 本局是否出价 |
| `minimumFunds` | int | 大厅补仪器的资金下限 |
| `maxMatches` | int / null | `null` 表示一直跑；整数是本次开启后的局数上限 |
| `instrumentTargets` | `{goldAverage,purpleCount}` | 补仪器目标；切换开关不会丢 |
| `approvalId` | string / null | 本次开启生成的一次性票据 `auto-<YYYYmmddTHHMMSS>` |
| `running` | bool | `enabled` 且循环存在且 `phase != "stopped"` |
| `phase` | string / null | `liveDomainLoop.phase` 原值 |
| `reason` | string / null | 停止原因或当前等待原因 |
| `matchesDone` | int | 本次开启后完整走完的局数 |
| `coverage` | string / null | 最近一局收页覆盖，照实：`COMPLETE` / `PARTIAL` / `COVERAGE_UNPROVEN` |
| `savedSources` | int | 最近一局落盘的原图张数 |

`liveDomainLoop.coverage` / `savedSources` 与这里同源，不另算一份。

## 两种停止（2026-10-22）

| 动作 | 作用范围 | 循环 | 主窗 |
| --- | --- | --- | --- |
| `auto_auction_stop` | 整个自动拍卖 | 置 `stopped`，不再派发 | 恢复并显示原因 |
| `stop_warehouse_capture` | 只结束本次收页 | 不动，继续等本局收页收尾 → 返回大厅 → 下一局 | 不动 |

- `stop_warehouse_capture` 在 Native 路由下走自动收页的 `stop()`：关闭这次滚动/原帧租约，
  保留已保存原图和部分审阅包，`warehouseCapture.automaticTerminationReason` 记为 `USER_STOP`。
- 它不中止正在跑的细化，也不再次触发同一局的收页：一次性守卫仍按 `recordStableKey`
  返回 `ALREADY_ATTEMPTED`。
- 收页停掉后 `collectionFinished` 以 `USER_STOP` 为真，循环照常往下走；即使一张也没存到，
  也不会把这一局卡在 `WAITING_WAREHOUSE_SAVE`。
- `stop_live_vision` 范围更大，是“停止观察及本次自动运行”，不应由普通 Esc 代发。
- Native 收仓没有 Esc/全局鼠标接管监听；窗口消息直接发给绑定窗口，不要求游戏在前台，
  不移动全局鼠标。窗口身份失效、窗口关闭或离开结算仍按实际原因保存部分结果，
  不能归因成用户停止。
- 跳过动画走同一窗口消息路径：按下后保持 80 毫秒再释放；回执只表示发送，不证明动画已结束。
  按钮仍可用时可重试。

## 连续局的保存语义

- 连续 10 局沿用现有可重开回看的隔离草稿（`live-trial` DRAFT，每条 `lifecycleStatus=DRAFT`，
  `source=live-trial`）。**不新增**从 DRAFT 晋升到正式 History 的路径；界面照实标注“草稿”。
- 覆盖照实记录：`COMPLETE` 只在台账给出完整覆盖时写入，其余是 `PARTIAL` 或 `COVERAGE_UNPROVEN`。
- 后台细化不阻塞下一局：循环只等本次收页对上本局（`captureRecordKey == settledMatch`），
  细化在独立进程里继续，跑完再合并到同一份草稿。

