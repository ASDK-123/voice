# CosyVoice 闪退排障 Runbook（日志 v2）

## 1. 快速定位入口

默认日志目录：`data/logs`

- `crash.log`：未捕获异常 / 线程异常 / Qt 致命消息
- `app.log`：人读日志
- `access.jsonl`：结构化 API 请求日志

## 2. 5 分钟快速排障流程

1. 先看 `crash.log` 最后一条，确认异常类型和线程名。
2. 记录同时间窗口（前后 30 秒）的 `session_id`、`request_id`。
3. 在 `access.jsonl` 里按 `request_id` 检索请求链路：
   - `API_REQ_START`
   - `API_REQ_END` / `API_REQ_FAIL`
4. 在 `app.log` 中检索同一 `request_id`，确认 UI/推理/播放侧对应日志。
5. 判断故障域：
   - API 有 `200` 但 UI 闪退：优先排查 UI 线程、播放器、QThread 生命周期
   - API `FAIL`：优先排查参数与后端推理

## 3. 常见问题判定

### 场景 A：合成成功但点击播放闪退

- 关键事件：`SYN_DONE` 存在，`UI_PLAY_START` 或 `UI_PLAY_FAIL`
- 处理：检查音频路径、播放器状态、线程销毁时机

### 场景 B：请求失败

- 关键事件：`API_REQ_FAIL`
- 处理：检查 `fields.error_code`、`status`、`path`

### 场景 C：完全无日志

- 检查 `app_config.json` 的 `log_dir` 是否可写
- 检查 `log_level` 是否过高（建议 `INFO`）
- 检查是否异常退出在 logger 初始化之前

## 4. 建议用户反馈模板

请附上：

1. `data/logs/crash.log` 最后 200 行
2. 出问题时间点前后 1 分钟的 `app.log`
3. 对应时间窗口的 `access.jsonl`
4. 操作步骤（点击了什么按钮、选择了哪个 voice）

也可以直接导出诊断包：

```powershell
python scripts/export_diagnostic_bundle.py
```
