# Native SOURCE 离线契约适配器

维护源码从 `build/warehouse-recognition-20260930/top160-unmerged-review/native-source-contracts/` 整理入库；旧运行与编译证据保留原位。项目直接编译当前 WarehouseEvidenceLease 和 Protocol 源码，不构造 WGC、不查询游戏窗口、不发送游戏输入。

`dotnet build tests/native_source_contracts/evidence-contracts.csproj -c Release` 的输出和中间文件均位于 `build/native-source-contracts/`。`tests.test_native_warehouse_source` 的协议用例仅调用 `--protocol-fixture` 假来源模式；维护源码可从新检出编译，无需旧 build 目录中的源码或 DLL。裁图填充画布的来源说明见 `tests/fixtures/native_intake_pages_v1/provenance.json`，这些像素不作为真实新帧或身份准确率证据。
