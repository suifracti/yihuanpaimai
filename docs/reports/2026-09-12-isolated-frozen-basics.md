# 隔离冻结包基础验收

业务基线 `4e1ad2d`，干净构建；验收工具提交 `eebf3d9`、`250fc4e`。候选包位于 `build/isolated_trial_20260912/dist/异环拍卖助手`，未覆盖日常 v13。P3 PARTIAL，完整试用交付和 P5 均未完成。

## 修复

打包加入共享计算模块、随包 Node、证据契约和核准源卡注册表。图鉴核准与证据契约使用冻结资源根目录。构建元数据可写入隔离目录，避免改动源码元数据。

## 独立执行结果

- `frozen-ui-focused/report.json` PASS：实际 EXE 双窗口启动，两次正常退出；数量/金均双向输入、叫价与清空、目标为0、成本7200显示和真实保存回执、第二实例历史回看通过。+1/0/-1/缺叫价为合成固定支持条件的引擎与 DOM 边界，不冒充真实结算收益。
- `bundled-compute-check.json` PASS：随包 Node 实际运行随包计算模块；相关资源哈希与源码一致。
- `frozen-warehouse/report.json` PASS：复制已有39件记录，28确证/11候选；实际历史行点击、39张裁图显示、DOM按钮导出55文件/54清单项，全部SHA256匹配，关闭重启一致。这是已有记录的回看与导出，不是冻结包新采集39件成功。输入记录的COMPLETE覆盖标签保留，不外推为实机采集验收。
- `vision-smoke.json` success=true/frozen=true：真实1440×810结算图进入冻结识别管线；加载107个视觉参考，角色/场地/仪器模板8/2/1；场景SETTLEMENT。settlementReady=false、settlementLedgerVerified=false；29检测项/17精确项仅诊断输出，未逐件核准，不报告准确率。单帧无拍卖阶段姓名，不能证明本人归属。
- 上述证据位于 `build/isolated_trial_20260912/`。EXE运行清除开发Python路径，PATH仅Windows System32，工作目录隔离。UI验收关闭vision；识别依赖另由vision smoke执行，不混为同一次完整运行。
- 初次 `frozen-ui/report.json` FAIL：验收脚本未聚焦金均输入，宿主刷新覆盖非活动编辑；补真实焦点后重跑PASS。失败证据保留。
- 正式历史SHA256仍为 `19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431`。

## 下一步

优先自动本人/他人归属的冻结连续帧验收与HUD实时显示，继续试用默认数据隔离入口、迁移状态和错误恢复。本人获胜真实录像仍缺，不让用户每局手动确认；纯结算晚启动缺名单保持未知。继续基础试用流程，逐件匹配调优留待用户试用后；不执行实机70秒滚仓，不宣称所有参数、性能、跨局或完整识别发布通过。
