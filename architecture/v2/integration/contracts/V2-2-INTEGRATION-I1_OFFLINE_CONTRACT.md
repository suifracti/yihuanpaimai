# V2-2 Integration I1 离线安全链路合同

## 范围与边界

本轮只组合已接受的 A/B/C 抽象接口和 fake source/observer/actuator：

- A：`934ce47e3dec223a8046dbca35452de8774f857c`
- B：`b1334c6ac11a9873030ed67e7f6418b22f69ccc0`
- C：`878435e96034caa130c622de0ab968162d65a595`
- 共同基线：`a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9`

不启动真实窗口、WinEvent hook、低级输入 hook、鼠标、`SendInput`、游戏或生产入口。I1 结果只表示 Integration 离线范围待外审，不表示真实桌面或完整拍卖流程可用。

## 三种身份不可混用

| 层 | 来源 | 语义 | 本轮接口 |
|---|---|---|---|
| 窗口身份/lifetime | A `WindowIdentity` | HWND、PID、image、class、process-instance 的完整身份 | `WindowIdentityToken` 生成 B `TargetId` |
| A acquisition | A `WindowMonitorSnapshot.Generation` | A 目标获取代次，仅作 provenance | 记录为 `AGeneration`，不作为 B Epoch |
| focus history | Integration adapter | 每个已观察 foreground/lifecycle transition 都推进 | B `FocusSnapshot.Epoch` |
| C session | C `FreezeCoordinator.GenerationId` | Integration/C session identity | C scan/rearm/session gate |

同一个 HWND 重新创建但 process-instance 或其他身份字段变化时，B `TargetId` 必须变化。A 的 Generation 数值即使偶然相等，也不能被解释为 B Epoch 或 C Generation。

## Raw revision/fence

accepted A 的公开快照/派生事件没有向 Integration 暴露“每个原始观察连续到达”的 revision fence。I1 增加最小整合边界 `IntegrationWindowObservation.RawRevision`、批次起点、pending 和 drop delta。adapter 的规则是：

1. revision 必须连续；
2. pending、overflow、缺口、回退、目标身份读取失败均 fail closed；
3. 不用轮询、`WaitForIdle` 或短暂 sleep 重建缺失事件；
4. 每个观察到的 leave/return/lifecycle 事件推进独立 B Epoch，即使最终快照已经回到原 foreground。

## 动作顺序与提交点

```text
A raw observation + revision fence
        │
        ▼
AWindowFocusAdapter ── TargetId / independent B Epoch ──► B FocusSnapshotProvider
        │                         │
        └─ broken/changed ────────┴────► C Freeze(reason)

C Precheck + C commit (FreezeCoordinator.ExecuteScrollRequest)
        │ delegate
        ▼
B Execute: precheck #1 → prepare → final precheck → ticket
        │
        ▼
CArbitratedRawInputBackend: C permission + underlying fake raw entry under one fence
        │
        ▼
fake raw backend
```

- C denial before its commit invokes no B action and has zero raw calls。
- B final precheck denial has zero underlying raw calls。
- C freeze/takeover before the raw arbitration fence wins and has zero underlying raw calls。
- Raw entry first is the submission point; a later freeze is recorded but cannot retract the accepted fake input。
- B hardware takeover calls B cancellation and independently adds C `USER_TAKEOVER`。
- Focus return never auto-rearms. C reasons must be cleared independently, current session validated, and a current single-use credential plus all four rearm conditions must pass。

## I1 验收范围

I01 成功发送；I02 完整 focus flap；I03 queue lag；I04 overflow；I05 same-HWND identity rebuild；I06 hardware takeover；I07 multiple C reasons；I08 old credential after session change；I09 restart/resync；I10 freeze/raw competition with before, between-final-and-raw and after-raw barriers；I11 A/B/C identity-scope separation。

所有场景使用确定性 callback 或 `ManualResetEventSlim` barrier。每个场景逐项记录状态、原因、B outcome、C commit、underlying raw call/accepted 数和 B trace。键盘文本不收集。

## accepted source 与本轮差异

本轮不修改 accepted A/B/C。新增差异只在 Integration：

- A raw revision/fence adapter：为无法由 accepted A 派生事件证明的 queue lag/overflow/flap 边界提供 fail-closed 输入；真实生产 bridge 仍需提供等价 raw fence。
- A identity → B TargetId 映射：使用完整 `WindowIdentity`，不是 HWND 或 A Generation。
- 独立 B Epoch 计数：由 adapter 对已观察 focus/lifecycle 事件推进。
- C/B action coordinator 与 `CArbitratedRawInputBackend`：定义 C commit、B final gate 和 underlying raw submission 的顺序。

这不是对 accepted A 已经保证完整快速 flap 的追认；I1 fake source 证明的是整合合同和 fail-closed 顺序。
