# 暂持缓冲接入结果

候选：`50d6ae8+retained-boundary/3971ddcff33d`，基于 HEAD `50d6ae8a0edb646f0b7defc6f034abaaaf98f632` 及既有 dirty 成果。未提交、推送或发布。本轮没有游戏/桌面捕获、游戏输入或完整生命周期实测。

固定清单：`build/native-retained-boundary-20261006/candidate-manifest.json`。Host 位于 `build/native-retained-boundary-20261006/host/WgcLiveHarness.exe`；实际托管代码 `WgcLiveHarness.dll` SHA256 为 `033d1ab704812a4f46982df0839b45d2799a088bdeb8b413e5f34f58412f40e4`。EXE 是 apphost，哈希与旧版相同；版本核对必须使用整份二进制清单，不能只比 EXE。

## 实际接入

- `DeliveredFrameSelector.cs`：最多三次清池；前两张非空暂持，第三张非空纳入统一清理后拒绝。见空→统一释放完成→后续取帧。取得帧后先登记所有权，再执行可抛错的时钟、属性、诊断与取消检查。
- 统一清理逐张尝试一次释放；一个释放/日志/时钟异常不会跳过后面的帧。首个业务失败保留，释放异常另记；不重复 Dispose、不继续选择或发布。选中帧交给 WGC 读回方后由该方 finally 释放，读取/检查异常也执行清理。Dispose 本身抛错时，日志表示释放调用失败，不能声称该缓冲已经成功归还。
- `WgcCapture.cs`：保留逐次清池见证、丢弃帧原始属性及读取区间、释放调用前后区间和结果。正常返回前选中表面亦完成 Dispose，私有 BGRA 数据不受后续帧覆盖。
- `CaptureDeliveryProof.cs`、`app/native_capture_delivery.py`：证明升级为 `capture-delivery-proof.v2`，必须包含 `retained-pool-buffers.v1`、容量2、1–3次取帧、暂持数量和释放完成时刻。验证请求≤空边界≤释放完成≤后续出池；旧 v1 不能混作新方案通过。Engine 准备清单同步版本。SOURCE v2 原图/哈希绑定、MMF协议及业务生命周期不变。
- `app/main.py`：既有触发条件逐项记原因，缺同局对局锚点与建议未合格可同时呈现；其余会话/局代际/目标/当前帧、原图、标题、网格、顶端、本局已尝试等原因分别记录。只在原因或作用域变化时发布日志；诊断输出异常不改变触发决定。新观察清空诊断，摘要仅显示匹配当前局及会话的原因。
- `core/main_window.js`：现有自动收页选项显示具体拒绝原因；不改场景或正式事实。
- Main 总线准备日志记录实际 PID/父 PID、Python路径和明确 IPv4 总线。Bridge 记录 Host spawn PID及其创建父进程、会话目录；Host状态自报实际 PID/执行路径/会话；Supervisor记录Engine launcher PID、创建父进程、pipe/map；Engine自报实际 PID/父 PID及同一会话/pipe/map。不按进程数量猜重复实例。

本轮源码/用例增量清单与整合前文件哈希分别在 manifest 的 `thisRoundFiles`、`baseline.json`。`core/warehouse_vision.py` 未改，正式身份、数量、价格与记账门槛未改。所有既有 dirty 成果保留。

## 最小检查结果

| 检查 | 实际结果 | 证据 |
|---|---|---|
| Host、行为用例、窗口QA构建 | 各0警告、0错误 | host-build.log、contracts-build.log、qa-build.log |
| 缓冲行为 | 15个定向情形通过：0/1/2库存成功、持续补帧、第三非空、属性/取帧/时钟/日志异常、取消/超时、释放异常、后续取帧取消/等待异常；各帧释放调用一次及见空/释放/交付顺序 | boundary-contracts.json |
| Python影响检查 | 5个用例通过：v2时间与容量见证、同局/跨局触发及分别拒绝、MMF复制/ACK绑定、SOURCE保存同图且不写正式事实、独立稳定帧 | python-targeted.log、proof-v2-source-stability.log |
| UI | 具体双原因显示、模式说明及选项行为通过；JS语法通过 | tests/native_delivery_status.js |
| 真实子进程身份离线验证 | Bridge spawn PID=实际Host自报PID；创建父 PID等于测试控制进程；Host因无效模式退出码2，在窗口监控/捕获/Engine初始化之前结束 | process-identity-verified.json/log |

身份用例首次因测试清理已退出子进程stdin的缓冲flush报Windows errno22；身份断言已取得，首次日志保留，修正测试清理后通过。自建QA首次预检将Host exe当目录，未启动子进程/取帧；修正目录解析后执行唯一一次窗口实验，见 `qa-preflight-failure.json`。两者不是游戏或新帧门禁反例。

## 新Host自建持续出帧验证

计划与原始证据：`build/native-retained-boundary-20261006/plan.json`、`controlled-77d1e04650/{raw.jsonl,result.json,stderr.txt}`。

仅自建无私人内容的640×360 DXGI窗口，不激活游戏、不捕获桌面；nonce解码确认像素来自自建窗口。独占线程反射调用**固定新Host的实际 CaptureDelivered**，没有用另写选择算法替代；独立线程持续提交内容。

最多3次请求、每次最多3次清池，8秒工作/10秒实际退出。实际3次都取到两张非空后在第三次见空，随后各取得1张合格交付帧；正常最大暂持2张，9次真实Dispose调用均成功，3个捕获ID递增。1,350.6444 ms确认退出，退出码0，stderr空。没有自动补采。

| 请求 | 清池次数/暂持 | 空边界ns | 释放完成ns | 后续取帧开始ns |
|---|---|---:|---:|---:|
| 1 | 3/2 | 176687450108000 | 176687451091800 | 176687451892000 |
| 2 | 3/2 | 176687587224000 | 176687587328500 | 176687590382400 |
| 3 | 3/2 | 176687681066100 | 176687681243800 | 176687684483400 |

三张原始来源值均仍为 FUTURE_AT_READ，originStrictQualified=false。没有加容差、等时间追上或修改原来源值。第二、三张自建内容计数不晚于请求时计数，也再次说明后续交付不能证明请求后提交/渲染。这里证明的是有界本地交付边界与释放顺序；来源绝对年龄、上游迟交/重放风险及游戏效果仍未解决/未验。

既有两次游戏失败 `lifecycle-real-01/02` 及自建立即释放对照 `build/native-pool-boundary-20261006/controlled-034b3aaaff` 保留；旧候选全部二进制哈希未变。

## 下一步入口及边界

准备入口：

```powershell
build/takeover_20260905/repro-venv/Scripts/python.exe tools/start_native_delivery_candidate.py
```

本轮已执行默认准备，固定清单核对通过，不启动助手、捕获或输入。`prepared-entry.json` 报告旧助手占用127.0.0.1:8766；未停止/替换它。运行中的旧进程不会自动加载本次源码和新Host。

用户下一轮确认游戏实测后才使用同一入口的 `--start-authorized --output <build内新目录>`。若总线仍占用，入口拒绝启动；需先明确结束旧助手，不能将旧GUI误作新候选。交付模式＋结算自动收页继续走原生命周期，SOURCE仍为16张/32请求/70秒。启动及时性、真实大厅→对局→结算滚动及自然跨局继续均等待那一轮实际验证，不把本轮自建成功写成游戏通过。
