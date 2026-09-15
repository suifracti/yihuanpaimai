# 冻结估价与四席读取复验

冻结95929c4（isDirty=false），候选build/isolated_trial_bid_20260913/dist/异环拍卖助手，已含估价ROI纠偏、四席视口补偿、单字裁图。新增诊断记录currentEstimate/seats/fastSeatBids，未修改识别逻辑。

真实开发录像8个顺序采样点走冻结KeyboardAuctionPipeline→HUD投影→AutoArchiver→CanonicalStore重读通过。配置文件昵称PLAYER_LOCAL；112/114秒currentEstimate=153286；114秒fastSeatBids=[711111,0,555555,333333]；赢家致敬最良心不歪，162秒起acquired=false，归档与归属证据重读通过。证据build/isolated_trial_bid_20260913/video-probe/report.json。非拍卖场景记录的估价/快速出价可能为保留上下文，不能当该帧新观察。

同一EXE真实Main/HUD退出恢复PASS：13972→39824→21668，分别从主窗口/HUD恢复，matchId保持，WAITING，正常退出；exit-ui/report.json。无游戏待机，不冒充游戏中OCR崩溃恢复。生产历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431。

本轮昵称从隔离配置读取，不是重新验证昵称UI保存；录像为顺序采样，不是完整连续/未见对局/P95；没有真实本人获胜录像。下一步检查同一候选的试用UI字段生效及历史流程，继续补齐P4，不继续扩展逐件调优。P3 PARTIAL，完整试用/P5未完成，v13未覆盖。
