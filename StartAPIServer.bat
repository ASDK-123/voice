@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo   CosyVoice API Server 启动脚本
echo   for Super Agent Party v0.3.6
echo ====================================
echo.

REM 读取 app_config.json 的 v2 voices 配置路径（确保 UI 内嵌服务与外部服务一致）
set "CFG_PATH=config\super_agent.json"
if not exist "app_config.json" goto :skip_config
for /f "usebackq delims=" %%A in (`.pixi\envs\default\python.exe -c "import json; d=json.load(open('app_config.json','r',encoding='utf-8')); print((d.get('v2_voices_config_path') or '').strip())"`) do (
    if not "%%A"=="" set "CFG_PATH=%%A"
)
:skip_config

REM 检查配置文件是否存在
if not exist "%CFG_PATH%" (
    echo ⚠️ 配置文件不存在: %CFG_PATH%
    echo.
    echo 请在 app_config.json 里设置 v2_voices_config_path，或创建默认配置：config\super_agent.json
    echo.
    pause
    exit /b 1
)

REM 检查 bridge.py 是否存在
if not exist "bridge.py" (
    echo ⚠️ 桥接脚本不存在: bridge.py
    echo.
    echo 将只启动 CosyVoice API 服务
    echo.
)

echo 📦 正在启动 API 服务...
echo 📍 服务地址: http://localhost:9880
echo 📖 配置文件: %CFG_PATH%
echo.
echo 💡 提示: 在 Super Agent Party 中填入服务地址: http://localhost:9880
echo.

REM 启动 API 服务
echo 🚀 启动 CosyVoice API 服务...
start "CosyVoice API" .pixi\envs\default\python.exe core\api.py --config "%CFG_PATH%" --host 0.0.0.0 --port 9880

REM 等待 CosyVoice API 启动
echo ⏳ 等待 CosyVoice API 启动 (3秒)...
timeout /t 3 /nobreak >nul

REM 启动桥接服务（如果存在）
if exist "bridge.py" (
    echo 🚀 启动 OpenAI 桥接服务...
    start "Bridge Service" .pixi\envs\default\python.exe bridge.py
    echo.
    echo ✅ 双服务已启动！
    echo    - CosyVoice API: http://localhost:9880
    echo    - OpenAI Bridge: http://localhost:5000
) else (
    echo.
    echo ✅ CosyVoice API 已启动！
    echo    - 服务地址: http://localhost:9880
)

echo.
pause
