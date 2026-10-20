# 后端 Goal：做到真实可用（2026-10-20 起，GPT 6.1 sol 连续执行）

> 执行方：后端（GPT）。规划：Claude（前端）。以 GitHub `main` 为准。
> 授权沿用 2026-10-19 用户原话：“不需要我在场，我全部同意他一直做下去”。启动游戏、入场、观察、仪器、出价、确认、结算收仓、返回、下一局全部已授权，不逐次询问。
> 节奏：不排天数，连续做到下面的“真实可用”验收通过为止。只有真正无法自行解决的阻塞才停，并把阻塞写进 Handoff。

## 真实可用的定义（唯一完成标准）

用户双击正常入口（`app/run.bat`，或打包后的 exe），在主窗口打开“自动拍卖”，然后离开：

1. 程序自己完成 **入场 → 回合观察（含需要的仪器）→ 按 Solver 出价并确认 → 结算跳过与收仓 → 归档 → 返回大厅 → 下一局**，循环进行；
2. **连续 10 局无人值守**，每局都有归档记录（仓库 COMPLETE，或写明原因的 PARTIAL），落槌簿能回看；
3. 花费不超过配置的每局上限，结果未知不重发；
4. 用户在主窗口点“停止”、资金低于下限、游戏窗口消失、场景长时间认不出、回执 UNKNOWN 时，**停在安全状态**并在主窗口显示原因；
5. 不需要任何环境变量、临时脚本或手工改配置。

## 现状（读 `git log 0c6e96a..origin/main` 与 README 得出，开工前再核对一次）

- 已有：仓库收仓实机 COMPLETE（`build/goal-20261019-b/match-5`）；同局剩余估值落盘；出价上限与“未知不重发”；场景锚点解码 + Host 票据发送（`bedbca3`）；出价 → 返回 → 下一局状态机（`3c30544`）；`f4c9791` 离线 CI 绿。
- 卡点：最新实机尝试 `build/goal-20261019-c/match-12` 以 `settlement-without-send` 结束，日志里 `estimate=None`、`phase=None`，**从未成功发出出价**。`f4c9791`（engine 快照进入求解）之后没有再实测。
- 临时性实现，必须在完成前收掉：
  - 出价循环只靠 `NTE_DOMAIN_ALLOW_GAME_INPUT` / `NTE_SCENE_ANCHOR_DIR` / `NTE_DOMAIN_LIVE_LOOP` 环境变量开启；
  - `app/main.py` 里 `approvalId` 写死为 `"goal-20261019-authorized"`、`userConfirmed` 写死为 `True`；
  - 状态机一局只出一次价，下一局开始后就 `done`，不是持续循环；
  - `main.py` 另起了一条 Python 侧路径：`ImageGrab` 截屏、每帧把助手窗口压到底层、直接前台点击（`_send_foreground_client_click`、`_live_fee_confirm_if_visible`）。这绕开了 Host 的窗口身份/票据检查，也会让主窗口和悬浮票被反复压到底。
  - 仪器选择和“使用”按钮的排查只在临时脚本里，正常 Main 没有接入。

## 工作方式（防丢、防重复，每一步都遵守）

1. 开工先 `git fetch origin main`，读本文件、README“当前状态”、Obsidian Handoff 第 2 节和最近提交。已有提交或 `build/` 证据的事不重做，已通过的检查不重跑。
2. 直接在 `main` 小步提交并 push（CI 已在 push 到 main 时运行），推完读回 GitHub，看 CI；红了立刻修，不叠新改动。
3. 不 `reset --hard` / `clean` / 强推，不整文件覆盖别人的改动。原图、日志、实机目录只增不删，每次实机用新目录（`build/goal-20261020-*/match-N`）。
4. 每个实机失败：用这一局保存的材料离线复现最早断点 → 写成离线测试（修前 FAIL、修后 PASS）→ 修 → 再开一局。不靠反复开局猜原因。
5. 进度只记 Obsidian `Handoff.md` 第 2 节，每完成下面一个里程碑更新一次，写清提交、CI、实机目录、结果、下一步。README“当前状态”在里程碑完成时同步。

## 保持简单（2026-10-20 追加，优先于上面的习惯做法）

`0c448a5`～`d4e616d` 连续 6 个提交都在修“图够不够新、证明是否成立”，卡住链路的是自加的检查，不是游戏。以后：

1. **输入安全只有三条**：窗口身份正确、一次性票据、回执未知不重发。其他检查都不是安全条件，不许因它们阻止动作。
2. **动作确认只用一种流程**：点击 → 取点击之后截的帧 → 每帧只识别一次并缓存结果 → 认出预期画面就 `CONFIRMED`，3 秒内认不出就 `UNKNOWN`。不判断“未来帧”“锚点老化”“首帧证明”这类条件。
3. 已有的新鲜度/证明类检查如果妨碍第 2 条，**直接删掉**，不再给它们打补丁。删自加的多余关卡不算放宽测试；安全三条的测试必须保留。
4. **同一断点修两次还不通**，就停下来把那一段从头简化重写，不再加第三个补丁。
5. **一次只追一个目标**。当前目标：实机拿到一次出价 `CONFIRMED`。达到之前不碰费用确认、持续循环和 M5。
6. 新增代码前先问：删掉什么能达到同样效果？能删就不加。测试只覆盖安全三条和真实出过错的断点，不为假想情况写测试。

## 里程碑（按顺序）

### M1 出价真正发出去

- 用 `tools/inspect_saved_auction.py` 和 match-12 的 `watch.log`、状态文件，离线追 `estimate=None` / `phase=None`：从 engine 快照 → Solver 准入 → `predictionSnapshot` → `BidIntentBook` → `advance_live_domain_loop` → Host 票据，找到第一个断开的地方。
- 写一个用 match-12 真实材料回放的离线测试，证明修后会产生出价意图并调用发送。
- 实机一局：至少一次出价 `CONFIRMED`。

### M2 仪器（如果求解需要）

- 先确认：没有仪器情报时 Solver 是否给不出估值。如果是，就把“选仪器 → 点使用 → 新画面确认”接进正常 Main，走和出价相同的场景锚点 + Host 票据路径，模板放 `assets/scene_anchors/` 并附 provenance。
- 仪器使用策略用 Solver/Decisions 已有的“仪器顺序”，不另写一套。
- **开局前补仪器**（用户 2026-10-20 确认可以）：每局入场前在大厅检查 Solver 要用的仪器（至少金均）；不够就补到配置数量再入场。走同样的场景锚点 + Host 票据，补货花费计入资金并受资金下限约束；补不了就写原因停下，不入场。
- 局内仍缺情报时不卡住：Solver 用金总价或已有可行区间出价；仍算不出就本回合放弃、继续观察，放弃是正常结果。

### M3 一条输入路径

- 把 `main.py` 里的 `ImageGrab` 截屏、压窗口、前台点击、费用确认点击移到 Host 已有的采帧和 `TicketedSceneAnchorDispatch`（费用粉色按钮作为一个场景锚点控件）。之后所有游戏输入都经过 Host 的窗口身份、焦点和一次性票据检查。
- 删除 Python 侧这些临时函数，不保留两套。主窗口和悬浮票不再被每帧压到底层。

### M4 持续循环

- 状态机从“一局一次”改为：每回合按 Solver 决定出价或放弃 → 结算收仓 → 归档 → 返回 → 下一局 → 继续，直到停止条件。
- 停止条件：用户停止、资金低于下限（配置）、窗口消失、场景超时认不出、UNKNOWN 回执、连续失败次数上限。每次停止都写原因。
- 每局的出价账本、回执、收仓结果写进同一局历史记录，落槌簿可回看。

### M5 产品开关（替换环境变量）

- `config.json` 增加 `autoAuction` 段：每局上限、资金下限、最多局数（可空=不限）。`config.example.json` 同步。
- `MainWindowBridge` 增加动作 `auto_auction_start` / `auto_auction_stop`，`app_status` 增加：
  `autoAuction: { enabled, phase, reason, round, matchesDone, matchesTarget, spentThisMatch, cap, lastReceipt }`
- 这份字段和动作写进 `docs/contracts/auto-auction-bridge.md`，提交后在 Handoff 注明“前端待接”。**主窗口按钮和显示由 Claude 做**，GPT 不改前端文件。
- 删掉三个环境变量开关、写死的 `approvalId` 和 `userConfirmed=True`；授权来自用户在主窗口点“开始”（`approvalId` 用这次点击生成）。

### M6 无人值守验收

- 正常入口启动，经桥接动作开始（前端按钮未到时可用桥接动作直接触发，但不得用环境变量），连续 10 局。
- 记录每局：出价次数与金额、回执、仓库 COMPLETE/PARTIAL、归档、返回与下一局用时、停止原因。全部写进 `build/goal-20261020-soak/`，摘要写 Handoff 和 README。
- 任何一局失败按“工作方式 4”修，修完从头再数 10 局。

### M7 收尾

- `app/run.bat` 正常入口与打包 spec（`app/异环拍卖助手.spec`）都能跑通自动拍卖；README 更新“如何使用自动拍卖”和已知限制（例如只支持 1920×1080，因为场景锚点按这个分辨率做）。
- Obsidian Decisions 记一条：自动拍卖达到真实可用，以及验收证据位置。

## 边界

- 前端文件归 Claude：`core/main_window.*`、`core/auction*.css`、`core/overlay_alpha.html`、`docs/demo/`。需要新显示时写进桥接契约，Claude 来接。改 `app/main_window.py` 的桥接白名单时在提交说明里点名。
- 不拆 `app/main.py`，M3 只搬走临时输入代码。不换技术栈，不建第二份数据源，不恢复 16/32/70 额度，不跳过或放宽测试。
- 不做自动补货（开局前补仪器除外）、自动售卖、固定递增出价。
