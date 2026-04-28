# CosyVoice 日志事件字典 v1

`schema_version: 1`

## 1. 统一字段

所有结构化事件都遵循：

- `ts`
- `level`
- `module`
- `event`
- `request_id`
- `session_id`
- `thread`
- `msg_zh`
- `msg_en`
- `fields`
- `schema_version`

## 2. 事件码与固定字段

### APP

- `APP_START`: `version`
- `APP_READY`: `window`
- `APP_SHUTDOWN`: 无

### UI

- `UI_CLICK_SYNTH`: `voice_id`, `text_len`
- `UI_PLAY_START`: `file`
- `UI_PLAY_FAIL`: `file`, `reason`

### API

- `API_REQ_START`: `method`, `path`
- `API_REQ_END`: `method`, `path`, `status`, `duration_ms`
- `API_REQ_FAIL`: `method`, `path`, `status`, `error_code`

### SYN

- `SYN_START`: `voice_id`, `text_len`
- `SYN_DONE`: `voice_id`, `duration_ms`
- `SYN_FAIL`: `voice_id`, `reason`
- `SYN_CACHE_HIT`: `cache_key`
- `SYN_CACHE_MISS`: `cache_key`

### CRH

- `CRH_UNCAUGHT`: `error_type`, `message`
- `CRH_QT_FATAL`: `error_type`, `message`
- `CRH_THREAD_EXCEPTION`: `error_type`, `message`, `thread_name`

## 3. 兼容策略

- `log_compat_mode=smooth`：事件双写（结构化 + 旧文本）
- `log_compat_mode=legacy`：保留旧文本为主，结构化保底
- `log_compat_mode` 非上述值：仅结构化输出

