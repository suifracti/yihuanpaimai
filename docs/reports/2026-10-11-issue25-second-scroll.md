# Issue #25 — 第11次第二次滚动首断点

## 最新追加任务：发送后等待独立证据（离线修复）

基于本 PR 初次交付 `420f56ebe09e60d40bad15ad75f729b4f4fdc98c`，按 Issue #25 comment-6105463624 执行。下方 STOP_CORRECT 是旧合同的历史结论；该合同安全停止正确，但把发送前的旧内容支持延续到成功发送之后，阻断了连续采集。

先修改定向回归，在生产代码未改时复现失败：第二次 API 返回成功且调用期间出现独立新回读、仅旧内容支持失效时，租约关闭，不能等待滚后 SOURCE。然后只修改 `WarehouseEvidenceLease.cs`、`WarehouseWindowScroll.cs`：每次滚动有独立的 API 成功阶段标记，仅非零返回才能设置；发送前所有守卫保持原逻辑。成功发送后，只有全部失败项**恰好**为 `scrollContentQuantizationSupported` 时允许等待；仍检查旧 SOURCE 独立证明、最新读回时效/epoch、场景、租约、目标与映射，任何其他失配仍停止。

使用既有 `SCROLLED/WINDOW_WHEEL_MESSAGE_SENT` 合同，补充 `SENT_WAIT_POST_SCROLL_EVIDENCE`、`displacementVerified=false`、`postScrollFrameReceived=false`。Python 生产代码无需修改：已有接收路径进入 WAIT_MOVED，只取得新独立 SOURCE 后验证滚动条与生产位移/重叠；再取得独立稳定支持才允许下一次输入。旧请求已消费，重复回执/轮询不重发。API 失败、异常、未知发送以及不带精确成功资格的旧 CLOSED 回执仍不能重解释或恢复。

定向结果：C# 第二次滚动 16/16，受影响适配器合同 13/13，Python 序列 11/11 子场景 PASS；生产 Host 构建 0 警告/0 错误。覆盖成功发送后旧内容变化、其他安全资格失败、重复/跨局回执、用户取消、没有移动及原截止超时。C# 实际成功回执保存为 `tests/fixtures/native_adapter_postsend_receipt.json`，Python 仅重绑定隔离测试的请求身份、时钟和合成视口步长，保留发送状态；合成视口不代表真实准确率。

新 DLL：`build/issue25-post-send/host/WgcLiveHarness.dll`，SHA-256 `b384191e4a3e3a1492c691bdec88013bf06349ae5195083aedd54ec3dffdab1c`。运行前须使用该构建；本次没有启动 Host、Main 或游戏，没有真实输入。16 SOURCE / 32 请求 / 首次结算 70 秒、SOURCE 准入、底部及 Host 覆盖账本未修改。完整收仓实机仍 NOT_RUN / 原局 PARTIAL，尚不能称 COMPLETE。

下一步需另行授权一次实机，唯一重点为第二次成功发送后取得独立滚后 SOURCE、验证连续位移/重叠并持续到真实底部及 Host COMPLETE；离线检查通过不代替该验收。原仓库 dirty、PR #22 和其他 owner 工作树未修改。

## 初次交付记录

源基线：PR #22 `84ac4d8565f557a48b6a00fcbb2cee632616127e`；子分支 `codex/issue-25-second-scroll-closed`。Luna 最后交接声明停止，线程 idle；复用已有干净候选工作树。原仓库 `6ecde36`、26 条既有 dirty 及禁用 push 设置保留。

## 真实日志结论：STOP_CORRECT，收仓仍为 PARTIAL

本机候选工作树中的 `build/native-observation/session-9816e706fe7543d49bb91c791c976fb8/warehouse-scroll-diagnostics.jsonl` 有完整 29 行、44,285 字节，SHA-256 `642e5b854543665ea10cf6ab7125b956713216c4475d743fb18e18c2320ee677`。完整原图、窗口标识及原始日志保持私有。

- 第一次发送成功，滚后 SOURCE 位移 -271px、重叠 0.5152、置信度 0.993；第五张独立 SOURCE 支持稳定后发起第二次滚动。
- 第二次发送前的身份、映射及内容资格全部通过。第24行 `SendMessageTimeoutW` **已经调用**，返回值 1、错误码 0，分类 `SENT_DISPLACEMENT_UNPROVEN`。
- 最早失败是第25/26行发送后复查：唯一失败项 `scrollContentQuantizationSupported`。该次比较使用的最新帧回读时间 `134616138900000ns` 位于 API 调用区间 `134616120417700–134616149093300ns` 内，比较时间为 `134616156841100ns`。
- 第28行 `SENT_GUARD_LOST`，随后 CLOSED；共两次真实 API 调用，仅一次 SCROLLED 回执。第二次实际位移 UNKNOWN，不能解释为 NOT_SENT 或自动重发。
- 关闭后目标/映射字段为 null，是 lease 检查短路的结果，不能推断窗口失效。内容变化是否来自本次滚动、渲染或业务变化尚 UNKNOWN。

既有合同明确禁止发送后守卫失败自动重试；本次停止符合该合同，未发现足以授权放宽合同的证据。没有生产补丁，没有修改 SOURCE 准入、16/32/70 预算或 Host 账本门禁。

## 定向改动与验证

仅扩展 `tests/native_scroll_diagnostics/{Program.cs,ContentRecheckChecks.cs}` 和 `tests/test_native_half_viewport_flow.py`。C# 九种第二次滚动分类；Python 六种分类，序列保留首张未支持原图、第一次成功滚动与生产位移匹配、第五张稳定支持、第二次失败；检查原截止、重复回执/轮询、旧请求不可重放及用户停止。合成像素仅验证调度，不证明真实画面准确率。

运行入口：

```text
dotnet build tests/native_scroll_diagnostics/scroll-diagnostics.csproj -c Release -o build/issue25-second-scroll/checks-out --nologo -v quiet
dotnet build/issue25-second-scroll/checks-out/scroll-diagnostics.dll build/issue25-second-scroll/checks --second-scroll-only
python -m unittest tests.test_native_half_viewport_flow.HalfViewportFlowTests.test_second_scroll_failure_after_verified_move_is_bounded -v
```

C# 9/9 PASS、构建 0 警告/0 错误；Python 6/6 子场景 PASS。测试适配器为 FakePlatform，不调用真实输入。实机 NOT_RUN；没有重编译生产 Host，第11次 Host SHA-256 `3c12234a31b8265c2c94cabdf1f27ae57916009756a2edcd165d0cdef11313d6`。

下一步应先离线界定发送后内容比较与正常滚动变化的区分证据/合同，再决定最小生产修复；不能把已经发送改成未发送。新的实机仍须另行授权，唯一验证项是第二次发送后的独立滚后 SOURCE、连续覆盖及真实底部；当前不具备宣称 COMPLETE 的条件。
