# Canonical Source Refactor

本次结构重构把原来的 v0.6 实验室吸收到唯一的 v0.65 产品中：

- `lab/index.html` 是唯一正式实验室入口；App 的“打开实验室”也指向它。
- `core/` 是 Lab 与 App 共用的运行核心，不再复制一套 v0.6 Solver。
- `app/main.py` 是桌面入口；`app/config.json` 是桌面配置。
- `assets/catalog_065.json` 是视觉识别使用的图鉴主本。
- `%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json` 是桌面产品唯一的
  writable runtime canonical history；source/package 通过同一 resolver 消费它。
- 根目录 `异环拍卖数据.json` 的身份是 `READ_ONLY_RESEARCH_DATASET`。离线实验可以显式读取，
  但产品运行时不得把它当作用户历史、首启 seed 或自动迁移来源。

旧目录和重复 HTML 暂不删除。删除前必须通过：Lab 加载、App 启动、15:53 regression、schema6 读写，以及同 ID 数据合并测试。
