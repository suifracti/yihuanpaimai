# Native 仓库原帧停止与映射门禁

日期：2026-10-02。设计已获用户确认；来源：父线程转述助手07:38:42提出停止即时生效、保存前后核对窗口映射，用户07:39:01回复“做吧”。本设计细化此前已交付最小方案，不新增HUD、权限或协议。

## 问题与目标

实际编译Host的隔离复现已证实：生产读线程收到native_stop、stdin保持打开而主循环未消费普通停止队列时，原帧租约仍开放，能写出70字节假BMP并发SOURCE。另有静态缺口：Capture取帧检查客户区映射，但经过Engine后写盘前后只有身份/焦点回调；其间同窗映射变化可能先发布原帧。

修正独立证据通道这两个门禁；停止原业务队列、固定MMF/NamedPipe1.0、业务FRAME分支及冻结事实不变。

## 已选最小方案

1. 读线程解析现有native_stop后立即调用现有线程安全SignalStop，仍把原消息交原普通队列；读线程退出也撤销证据租约。没有新消息或Engine指令。
2. WgcWindowCapture仅增加原帧专属、无副作用的新鲜映射核验入口。复用已有Win32/DWM客户区映射读数，核对初始item extent、客户区宽高及相对裁切偏移，变化或无法证明时false；不重绑、重裁切、缩放或重新创建capture。
3. NativeObservationService给独立TryPublish传身份/焦点且新鲜映射成立的回调。TryPublish已有写盘前后两次回调继续使用；写前拒绝不保存，写后拒绝保留已写证据但不发SOURCE。
4. 屏幕位置纯平移且相对映射未变可以通过；不把绝对screen origin作为客户区裁切变化。原Capture映射算法与普通FRAME不修改。

不选暂停后自动恢复或重建捕获：会改变观察会话与冻结事实边界。不给所有业务控制附加新映射算法：本次只修原帧保存漏洞。

## 保留合同

16原帧、首次Host SETTLEMENT起70秒绝对期限、单请求/未ACK、Host128MiB包括失败预留、intake64MiB实际PNG、≤1920×1080；源时间严格晚于请求、真实Store/manifest成功后接受页、旧session/generation拒绝、失焦/身份变化终止、人工确认/否决、正式历史隔离、DIRECT身份门槛均保持。

## 最小验收

- 沿同一已失败诊断加载实际修后Host：正常对照可发布；native_stop已读而普通队列未消费、stdin保持打开时，租约立即失效，SOURCE=0、停止后的原图=0，原停止消息仍在普通队列。保留修前result，不覆盖。
- 原帧映射合同使用fake compositor/窗口几何读数，覆盖正常与平移可用、尺寸/偏移/extent改变或读数失败拒绝；分别写盘前变化不写/不发、写盘后变化保留原图且不发。不得把模拟称WGC实机。
- 编译真实Host（不启动）及仅本轮差异检查。复用旧Store/identity/coverage结果，不重刷矩阵或录像。
- 游戏前台/WGC SystemRelativeTime、真实免激活HUD仍未验；不启动游戏/输入/抢前台/改变捕获权限。

## 执行约束

唯一仓库D:\yihuanpaimai，保留全部用户dirty/untracked；资料及诊断置build。无备份/删除/reset/clean/提交/推送/发布/归档。brainstorming技能已读；writing-plans在本次完整可用技能目录中不存在，采用下一份本地简短计划，不因此重复等待批准。
