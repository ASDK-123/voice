# CosyVoice Desktop API 使用与局域网调用说明

本文基于当前项目代码（`core/api.py`、`bridge.py`、`StartAPIServer.bat`、`client/api_client.py`）整理，覆盖以下内容：
- 如何启动 API 服务
- API 端点与请求格式
- 局域网（LAN）调用方式
- OpenAI 兼容桥接（`bridge.py`）使用方式
- 常见问题排查

---

**重要说明**
- 服务默认返回 `audio/wav` 音频字节流，不是 JSON。
- 角色（speaker/character）来源于配置文件（默认 `config/super_agent.json`）。
- API 服务监听地址在启动脚本里是 `0.0.0.0:9880`，这意味着可被局域网访问（前提是防火墙放行端口）。

---

## 1. 启动 API 服务

推荐使用项目自带脚本：

```bat
StartAPIServer.bat
```

该脚本会启动两个服务：
- CosyVoice API：`http://localhost:9880`
- OpenAI Bridge：`http://localhost:5000`（若 `bridge.py` 存在）

脚本内部实际上执行了：

```bat
.pixi\envs\default\python.exe core\api.py --config config\super_agent.json --host 0.0.0.0 --port 9880
```

如果只想启动核心 API，也可以手动执行：

```powershell
.pixi\envs\default\python.exe core\api.py --config config\super_agent.json --host 0.0.0.0 --port 9880
```

---

## 2. 角色配置来源

API 中的 `speaker` / `character_name` 来自配置文件：

- 默认（外部脚本 `StartAPIServer.bat`）：`config/super_agent.json`
- UI 内嵌启动（`ui/api_page.py`）：使用 `app_config.json` 里的 `v2_voices_config_path`
- 格式：数组或单对象
- 必须包含字段：
  - `name`：角色名
  - `mode`：推理模式（示例：`零样本复制` / `精细控制` / `指令控制`）
  - `prompt_text` / `prompt_audio` 等（不同模式需要）

v2 推荐把 `name` 作为 `voice_id` 使用，格式为：
- `voice_id = {character}#{emotion}`
  - 示例：`胡桃#default`、`胡桃#happy`

示例（节选）：

```json
[
  {
    "name": "默认音色",
    "mode": "零样本复制",
    "prompt_text": "各位观众大家好，欢迎收看今天的节目",
    "prompt_audio": "asset/xxx.wav",
    "instruct_text": "",
    "color": "#FF6B6B"
  }
]
```

---

## 3. API 端点一览（9880）

### 3.1 健康检查

`GET /api/health`

返回 JSON，例如：

```json
{
  "status": "ok",
  "model": "CosyVoice3-0.5B",
  "characters": ["默认音色", "..."]
}
```

---

### 3.2 获取角色列表

`GET /api/characters`  
返回：

```json
[
  {"name": "默认音色", "voice_id": "默认音色"}
]
```

**酒馆兼容端点：**

`GET /speakers`  
返回结构同上。

---

### 3.3 标准 TTS（推荐）

`POST /api/tts`

请求 JSON：

```json
{
  "text": "要合成的文本",
  "character_name": "默认音色",
  "mode": "零样本复制",
  "speed": 1.0
}
```

返回：`audio/wav` 字节流。

**curl 示例：**

```bash
curl -X POST "http://127.0.0.1:9880/api/tts" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"你好\",\"character_name\":\"默认音色\",\"mode\":\"零样本复制\",\"speed\":1.0}" ^
  --output out.wav
```

---

### 3.4 酒馆兼容端点（根路径）

`GET /` 或 `POST /`

请求字段（POST JSON 或 GET Query）：

- `text`
- `speaker`
- `speed`
- `instruct`（可选）

示例：

```bash
curl -X POST "http://127.0.0.1:9880/" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"你好\",\"speaker\":\"默认音色\",\"speed\":1.0}" ^
  --output out.wav
```

---

### 3.5 直接 TTS（不依赖角色配置）

`POST /api/tts_direct`

支持两种格式：

**A) multipart/form-data**
- `text`
- `prompt_text`
- `prompt_audio` (WAV/MP3)
- `speed` (可选)

**B) JSON + base64**

```json
{
  "text": "要合成的文本",
  "prompt_text": "参考音频对应文本",
  "prompt_audio_base64": "BASE64...",
  "speed": 1.0
}
```

返回：`audio/wav` 字节流。

---

### 3.6 运行时开关

`POST /api/toggle_stream`

```json
{ "enabled": true }
```

`POST /api/toggle_spk_cache`

```json
{ "enabled": true }
```

---

## 4. OpenAI 兼容桥接（5000）

`bridge.py` 提供 OpenAI 风格接口，端点如下：

`POST /v1/audio/speech`

请求 JSON：

```json
{
  "input": "要合成的文本",
  "voice": "默认音色"
}
```

该桥接服务内部会转发到 CosyVoice API 根路径 `/`。

**curl 示例：**

```bash
curl -X POST "http://127.0.0.1:5000/v1/audio/speech" ^
  -H "Content-Type: application/json" ^
  -d "{\"input\":\"你好\",\"voice\":\"默认音色\"}" ^
  --output out.wav
```

说明（bridge 内部转发行为）：
- bridge 对外保持 OpenAI 兼容输入输出不变
- bridge 内部会转发到后端 v2：`POST /api/v2/synthesize`（而不是旧版根路径 `/`）
- bridge 会透传/生成 `X-Request-Id`，便于排查问题

**健康检查：**

`GET /health`

---

## 5. 局域网调用指南

### 5.1 确保服务监听 `0.0.0.0`

启动脚本已指定 `--host 0.0.0.0`，可被局域网访问。

### 5.2 获取本机局域网 IP

在服务所在机器上运行：

```powershell
ipconfig
```

找到 IPv4 地址，例如 `192.168.1.100`。

### 5.3 放行防火墙端口

需要允许以下端口被局域网访问：
- 9880（CosyVoice API）
- 5000（Bridge，可选）

### 5.4 在局域网其他机器访问

把 `127.0.0.1` 换成服务端 IP：

```bash
curl -X POST "http://192.168.1.100:9880/api/tts" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"你好\",\"character_name\":\"默认音色\"}" ^
  --output out.wav
```

若使用 Bridge：

```bash
curl -X POST "http://192.168.1.100:5000/v1/audio/speech" ^
  -H "Content-Type: application/json" ^
  -d "{\"input\":\"你好\",\"voice\":\"默认音色\"}" ^
  --output out.wav
```

---

## 6. 客户端代码参考

项目自带简易客户端逻辑在：
- `client/api_client.py`
- `client/simple_ui.py`

其中 `CosyVoiceAPIClient` 已封装了：
- v2 优先：`/api/v2/health`、`/api/v2/voices`、`/api/v2/synthesize`
- 兼容回退：`/api/health`、`/speakers`/`/api/characters`、`/`、`/api/tts_direct`

可直接复用其请求格式。

---

## 7. 常见问题排查

### 7.1 返回 500 / 提示 “模型未加载”
- 检查模型文件是否下载完整。
- 启动日志是否有 `Model loaded successfully`。

### 7.2 404：找不到角色
- 检查 `config/super_agent.json` 是否存在、格式是否正确。
- 角色名必须和请求中的 `speaker` / `character_name` 完全一致。

### 7.3 局域网访问失败
- 确认服务监听 `0.0.0.0`。
- 防火墙放行 9880/5000。
- 确认局域网设备能 ping 通服务端 IP。

---

## 8. 快速验证清单

1. 本机健康检查：  
   `http://127.0.0.1:9880/api/health`
2. 局域网健康检查：  
   `http://<服务端IP>:9880/api/health`
3. 角色列表：  
   `http://<服务端IP>:9880/api/characters`
4. 实际合成测试：  
   `POST /api/tts` 并保存 wav

---

## 9. 新增 API v2（全功能）

新增前缀：`/api/v2`

可选鉴权：

- 设置环境变量 `V2_API_KEY`（或 `API_KEY`）后启用鉴权
- 通过 `X-API-Key: <key>` 或 `Authorization: Bearer <key>` 调用

### 9.1 健康检查

- `GET /api/v2/health`

### 9.2 参考音频资产管理

- `POST /api/v2/assets/audio`（`multipart/form-data`，字段 `file` 或 `audio`）
- `GET /api/v2/assets/audio`
- `GET /api/v2/assets/audio/{asset_id}`
- `GET /api/v2/assets/audio/{asset_id}/content`
- `DELETE /api/v2/assets/audio/{asset_id}`

### 9.3 语音配置管理（voice CRUD）

- `GET /api/v2/voices`
- `POST /api/v2/voices`
- `GET /api/v2/voices/{voice_id}`
- `PUT /api/v2/voices/{voice_id}`
- `DELETE /api/v2/voices/{voice_id}`
- `POST /api/v2/voices/{voice_id}/compile`
- `POST /api/v2/voices/reload`
  - 用途：当你直接修改了 v2 voices JSON 文件（例如桌面端 UI 直写 `v2_voices_config_path`）后，让运行中的 API 进程重新从磁盘加载 voices
  - 说明：UI 的“语音设置”页在保存/应用/导入后会 best-effort 调用该接口；若你用外部脚本启动 API，也可以手动调用或直接重启服务

### 9.4 统一合成接口

- `POST /api/v2/synthesize`

支持两种调用：

1. `application/json`（使用 `voice_id` 或 direct 参数）
2. `multipart/form-data`（可直接上传 `prompt_audio`）

关键字段：

- `text`（必填）
- `mode`（可选）
- `speed`（可选）
- `voice_id`（使用已有 voice）
- `prompt_text` + `prompt_audio_asset_id`（direct 克隆）
- `response_format`: `audio` 或 `json`
- `save_output`: `true/false`

### 9.5 任务与批量

- `POST /api/v2/jobs`（异步提交，`segments` 数组必填）
- `GET /api/v2/jobs/{job_id}`
- `POST /api/v2/jobs/{job_id}/cancel`
- `POST /api/v2/jobs/{job_id}/retry`

### 9.6 合并音频

- `POST /api/v2/merge`
- 请求体示例：

```json
{
  "asset_ids": ["output_xxx", "output_yyy"],
  "output_name": "demo_merged.wav"
}
```

---

## 10. v2 规范（与现状一致）

### 10.1 Request ID
- 客户端可传 `X-Request-Id`；服务端会在响应头回传 `X-Request-Id`
- v2 的 JSON 成功响应也会带 `request_id` 字段；音频响应（`audio/wav`）仅响应头包含 `X-Request-Id`

### 10.2 错误格式
- 统一错误 JSON：
```json
{
  "error": { "code": "invalid_request", "message": "..." },
  "request_id": "req_xxx"
}
```
- `error.details`：可选（当服务端有额外信息时才会出现）

### 10.3 错误码枚举（常用）
- `invalid_request`：参数缺失/格式不正确（400）
- `unauthorized`：未通过 API Key（401）
- `conflict`：资源冲突（例如 voice 已存在）（409）
- `payload_too_large`：上传体积过大（413，受 `MAX_UPLOAD_MB` 控制，默认 50MB）
- `asset_not_found`：资产不存在（404）
- `voice_not_found`：角色/音色不存在（404）
- `job_not_found`：任务不存在（404）
- `model_not_loaded`：模型未加载（503）
- `internal_error`：未预期错误（500）

### 10.4 synth 缓存头（仅 /api/v2/synthesize）
- `X-Cache: HIT|MISS`
- `X-Cache-Key: <hash>`
- `X-Asset-Id: <asset_id>`：仅当 `save_output=true` 生成 output asset 时出现
