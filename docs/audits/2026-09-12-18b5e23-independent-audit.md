# 18b5e23 独立复核：58项回归通过，裁图证据链仍有三处缺口

审查基线：`18b5e23fe505f21b819022dd6439e1b518140faf`，main，代码审查开始与测试结束时工作区干净。日期：2026-09-12。只做独立审阅、隔离验证和文档同步，未修改业务代码或测试文件。

## 结论

**P3保持PARTIAL，不能接受“四项生产缺口全部修复通过”。** 新缓存的普通更新/命中/写盘失败恢复、非法bbox、真实源卡交叉错配、size严格解析的现有回归已独立通过；但旧记录兼容、备份获取失败及源图实际哈希核验存在可复现缺口。

## 独立验证

使用仓库既有隔离测试入口，执行导入安全13项、仓库持久化38项、局后捕获导出7项，**58/58通过，0失败、0错误、0跳过，总耗时113.141秒**。

- 结果：`build/codex_audit_18b5e23/targeted-results.json`
- 原始日志：`build/codex_audit_18b5e23/targeted.log`
- 独立反例：`build/codex_audit_18b5e23/probe_evidence_boundaries.py`
- 反例结果与日志：`build/codex_audit_18b5e23/evidence-boundary-results.json`、`evidence-boundary.log`

反例使用真实WarehouseCaptureHost与CanonicalHistoryStore，临时数据全部位于本轮build隔离目录。彩色测试图仅验证证据流转，无藏品身份/名称，不污染生产History或图鉴；临时fixture由TemporaryDirectory退出清理，复现脚本与结果保留。

实施方所述三轮真实双窗口12/12属于其自测，本轮因已确认以下生产缺口，未重跑真实应用三轮或视觉全套。没有运行游戏采集、没有覆盖v13、没有进入P4。

## P1：旧记录缺少来源哈希时仍误用旧裁图

位置：`app/warehouse_capture_host.py:1169–1184`，尤其1176行 `not eu_sha or eu_sha == blob_sha`。

条件：同一recordId/reviewUnitId的旧记录已有cropPath/cropSha256和bbox，但无observations；新版本缓存文件不存在。这种记录由当前真实store.persist_warehouse_evidence接受，非伪造store返回。随后同一bbox收到另一张原图。

实测：新包保存成功，新来源SHA写入记录；磁盘仍保留旧裁图，前后SHA同为 `4f3f6a9d7fdc70c031fc5c166b9d11ac51de1160d157f213442aef6b005bb986`。因此旧兼容分支绕过了新缓存的来源/版本约束。

修复要求：来源、版本或坐标绑定证据不完整必须缓存未命中并重新裁切；不能把缺失哈希当作任意新来源的匹配。补旧记录无observations/空哈希/无缓存元数据的生产入口更新反例，验证新来源与新图一致。

## P1：备份旧图失败后仍覆盖，保存失败无法恢复

位置：`app/warehouse_capture_host.py:1351–1363`。

条件：对旧crop的备份read_bytes发生I/O异常，当前代码捕获后pass，继续移动新图；随后持久化发生异常。独立探针仅对隔离旧图备份读取注入PermissionError，并对同一真实store的最终写入注入OSError，用于验证故障边界，不是已发生的用户数据事故。

实测：备份失败1次后仍调用持久化1次；host返回None，History字节未变，旧图却未恢复。旧图SHA由 `4f3f6a9d7fdc70c031fc5c166b9d11ac51de1160d157f213442aef6b005bb986` 变成 `f46298dcf7779c669dadaa6acc7b73ce8369e27ac6fe7a52bb748b05d7e5e8ed`，磁盘图与记录cropSha256不一致。

修复要求：所有旧图备份必须成功才允许移动任何新图；备份失败立即拒绝。恢复失败不能吞掉后仍只返回普通None并清理唯一可恢复证据。补备份读取失败、部分移动失败和恢复失败的有界故障用例。

## P2：源图文件名哈希未与实际字节校验

位置：`app/warehouse_capture_host.py:1087–1105`，1103行直接解码。

条件：blob目录中的文件名符合声明SHA，内容被损坏/替换为另一张仍能解码的图；当前get_blob_image只用文件名定位，未比较实际SHA。探针在隔离目录中模拟替换，未改生产文件。

实测：实际源图SHA为 `3af67f306771da5bf02800af5b8d8d86010db05fffc238a1912c91c75362174b`，声明为 `1923537bf24726878a6cbac448eb75220ce227bc41a1c17f9dae1eda77b97728`，host仍返回成功、生成裁图并保存声明SHA。未验证字节的blobSha256不能作为可信缓存绑定。

修复要求：读取一次原图字节，计算并严格比对声明SHA，通过后再用同一字节解码；缓存命中前也须确认源图完整性，不能仅相信文件名/元数据。

## 唯一下一步

Gemini只收口以上三条证据链边界，保留本次58项已有回归。修复后对新基线独立运行相关回归、三个反例和真实39件应用往返。保持P3 PARTIAL；其余录像、完整身份、实机70秒滚仓、详情、中断恢复、未见对局与冻结包全链仍未验收。
