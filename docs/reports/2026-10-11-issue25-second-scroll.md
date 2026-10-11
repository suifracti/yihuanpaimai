# Issue #25 — 第11次第二次滚动首断点

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
