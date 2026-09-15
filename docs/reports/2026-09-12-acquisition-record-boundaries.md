# 自动归属的名单冲突与跨局边界

业务提交481df2c。发现并修复两项实际代码缺口：确认本人/他人后，后续名单出现重复winner或本人姓名变化，旧结果未撤销；Keyboard在UNKNOWN或导航识别尚忙时提前返回，绕过基类的记录绑定，可能仍带上一局归属。现更新名单时重新核验已确认归属；新key在场景路由前绑定并清除顶层与嵌套归属/winner，嵌套字典复制，不改已发布的历史对象。同局空白观察仍可保留确认，不把弱/空OCR直接判成他人。

验证：ownership-boundary-tests.json，24项通过3.875秒；ownership-boundary-downstream-tests.json，25项通过3.969秒，均无跳过。包含真实Keyboard早返回路径（场景与忙碌状态模拟）、同名冲突、本人姓名变动、迟进入结算缺名单保持未知及新鲜名单后恢复判断、CurrentMatch/AutoArchiver/流程证据保护。迟进入相关测试是模拟证据，不冒充真实迟进入实录。

真实14-40-37开发录像重新运行像素/OCR→归属→自动归档→新Store重读。159秒第一次winner保持未知，162/165/168秒判他人false，ARCHIVE_REOPEN_PASS。证据build/codex_other_video_20260912/acquisition-boundary-replay/archive-check.json及report.json；脚本replay_acquisition_boundary.py。116秒仍UNKNOWN，不宣称连续全录像无误。本轮未重做Main/HUD DOM，上一轮实际DOM验收不扩大为本轮所有边界。

边界仍在：缺少本局本人姓名时不猜测，纯结算晚启动不保证自动归属；真实本人获胜视频尚缺，尚未达到完整归属实录验收。不能因此每局强制人工确认；日常采集应从拍卖过程自动积累本人姓名。每帧姓名原图及HUD实时归属仍待验收。

下一步推进P4实际Main/HUD参数与盈亏显示验证（取消最低收益目标、+1/0/-1、无当前出价），继续整理隔离试用包剩余项。本人获胜实录缺口单列保留，不因无样本反复调参或阻塞其他已授权实施。P3 PARTIAL，P4实施中，P5未完成；逐件匹配暂停。正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，v13不覆盖，无真实游戏输入。
