# 默认试用数据隔离

提交1ce7bf3增加随包隔离配置，e70654f补桌宠设置隔离。默认数据目录为%LOCALAPPDATA%/异环拍卖助手试用/data，保留已有试用数据，跳过日常历史迁移；主窗口标注隔离试用。未带配置的日常构建沿用旧目录。配置损坏停止初始化，不回落日常目录；显式YIHUAN_DATA_ROOT仍为验收覆盖入口。

业务基线e70654f的干净构建位于build/isolated_trial_default_20260912/dist/异环拍卖助手。构建需NTE_BUILD_ISOLATED_TRIAL=1；隔离标记位于_internal/isolated_trial.json。

19项运行时数据/试用配置回归PASS，3.843秒，无跳过。build/isolated_trial_default_20260912/default-profile-pet-ui/report.json PASS：实际EXE、两次Main/HUD启动、昵称按钮保存/重启/清空、隔离标记显示、默认目录落盘；不设置YIHUAN_DATA_ROOT，只将LOCALAPPDATA指向测试沙箱。日常历史及桌宠哨兵文件字节不变；试用历史不含日常哨兵记录，桌宠状态落到试用目录。先前default-profile-ui PASS尚未覆盖桌宠隔离，最终报告覆盖了此项。

测试关闭视觉输入，归属DOM使用既有录像context和合成边界，不是冻结连续OCR验证。真实正式历史SHA256仍19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431，v13未覆盖。

试用启动说明docs/plans/2026-09-12-trial-start-guide.md已写。完整候选包尚未交付验收完毕。下一步冻结连续归属/昵称实际识别链及错误恢复，随后汇总试用交付；P3 PARTIAL、P5未完成，逐件匹配调优继续暂停。
