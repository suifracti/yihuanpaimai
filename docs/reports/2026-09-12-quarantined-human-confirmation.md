# 图鉴尺寸待核对候选的人工核准

业务提交b41487a。真实界面正向确认“一簇幽火”复现死路：普通确认被QUARANTINED_REQUIRES_OVERRIDE拒绝，但覆盖确认又因候选已存在被OVERRIDE_ID_IN_CANDIDATES拒绝。现在仅对图鉴尺寸QUARANTINED的候选允许明确人工覆盖，仍要求合法图鉴身份、原图证据、核准理由及显式确认；普通候选不可绕过原有规则。UI给出待核对提示，普通确认按钮引导到带理由的核准操作，图鉴尺寸状态不被修改。

原始失败history-confirm-real-app/report.json；修复后history-confirm-fixed-real-app/report.json PASS（均在build/codex_other_video_20260912）。实际Main/HUD两次启动，DOM点击历史→继续审阅→撤销暂缓→选择一簇幽火→核准理由→明确确认→生成→写入；摘要20→21确认，保留原自动结果和原人工暂缓两份修改前记录。第二次重启身份及修订文本一致，DOM导出当前和历史摘要与磁盘一致，两次正常退出。测试是模拟人工核准，不计为自动识别提升。最终新增的一行常驻说明文字未单独重跑DOM，行为链在同版本逻辑下通过。

quarantined-human-review-tests.json 23项通过4.510秒。另给审阅视图增加记录标识，并在查看历史B时拒绝记录A结果；本轮未构造跨记录迟到回执实测，不称完整并发验收。正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，DRAFT/PARTIAL保留。

下一步完成跨记录迟到回执和导出取消/失败检查，再按规划推进采集恢复、其余UI参数同步及隔离试用包。自动匹配优化仍暂停至用户试用，v13未覆盖，未执行真实70秒游戏输入。完整项目仍未完成。
