# 归属证据保存与单字姓名

业务提交042ad7c。三条席位姓名解析路径曾拒绝单字名，实际13-40-43录像140秒winner为“音”，故允许合法单字玩家名，同时仍过滤单字固定UI/标点。新增单字音/汐到名单和归属的回归。跟踪器提供脱离内部对象的判断摘要，生产Keyboard管线将方法、对局key、winner、本人/他人/未知、至少两次观察计数及本局四席稳定姓名写入auctionEvidence.acquisition；同语义去重，最多32条。此处为算法证据摘要与时间线，不宣称已经保存每一次姓名原图。

实际14-40-37录像重新从像素执行到自动归属、AutoArchiver保存，再新建CanonicalHistoryStore读取：FINALIZED、acquired=false保持，winner致敬最良心不歪，归属判断摘要也在同一记录中保留。结果build/codex_other_video_20260912/acquisition-evidence-replay/archive-check.json，原始过程context.json及report.json，复现脚本replay_acquisition_evidence.py。前置acquisition-archive-replay仅测归属保存，最终evidence版增加判断摘要校验。没有手填姓名/归属，不是Main/HUD实际DOM重启验收。

27项通过3.859秒：acquisition-evidence-final-tests.json，包含单字名、摘要防外部修改、同局新帧确认、重复帧/跨局/同名/弱观察/冲突、CurrentMatch和AutoArchiver归属保护。

样本核对：00-29-50与00-31-38尾部是同局拍卖过程，本人PLAYER_LOCAL；00-33-00尾部结算winner莫要。13-40-43的140秒winner音；13-44-36已检结算winner汐/hope；14-40-37为致敬最良心不歪。已检查片段没有可确认的本人获胜，不能将这些材料冒充本人分支。不是声称已扫描每个视频每一帧。本人分支已有模拟测试，真实本人获胜录像验收仍缺。

下一步优先历史Main/HUD归属显示与他人结算收益不误计本人收益，继续查找真实本人获胜样本，并覆盖迟进入结算、缺席信息和跨局。自动归属整体仍未完成验收，不允许回退为每局手动确认。P3 PARTIAL，P4实施中，逐件自动匹配暂停，试用包未完成。正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，v13未覆盖，无真实游戏输入。
