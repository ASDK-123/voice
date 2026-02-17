# Project Overview

## 1. 目标

本项目提供一套本地化 TTS 生产能力：

- 桌面 GUI 操作
- HTTP API 调用
- v2 资产与角色统一管理
- 任务化合成与输出

## 2. 运行入口

- 桌面：`StartCosyVoice.bat` -> `main.py`
- API：`StartAPIServer.bat` -> `core/api.py` -> `core/server/main.py`
- 桥接：`bridge.py`（可选）

## 3. 核心模块

### `core/api_legacy.py`

当前 API 主实现，包含 v1/v2 路由与运行时装配。

### `core/api_v2_routes.py`

v2 资源与角色路由（资产、voices、jobs）。

### `core/synthesis/*`

统一合成链路：请求规范化、缓存键、参考音选择、合成执行。

### `core/storage/*`

角色配置文件存取（v2 voices）。

### `ui/*`

桌面端页面与服务控制、日志展示。

## 4. 数据与持久化

- 语音资产：`data/assets/audio/`
- 输出数据：`data/outputs/`
- 资产索引：`data/api_v2_assets.sqlite3`
- 缓存目录：`data/cache/`

## 5. 编码规范

项目统一为 UTF-8。

建议规则：

1. 禁止提交 GBK/ANSI 文件
2. 禁止提交明显乱码片段（如异常 emoji 前缀、中文标点错位、连续问号）
3. 对日志输出优先使用稳定 ASCII/UTF-8 文案
4. 子进程输出解码需有回退策略（UTF-8 优先）

## 6. 当前状态

已完成本轮乱码修复重点：

- 运行日志链路的乱码文案清理
- v2 默认模式字段修复
- 关键文档重建为可读 UTF-8 内容

后续可选工作：

- 对 `core/api_legacy.py` 进行进一步注释/文档清理
- 增加提交前编码检查脚本
