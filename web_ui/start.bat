@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Unitale Pro WebUI 启动器
echo ==========================================
echo       Unitale Pro WebUI 启动器
echo ==========================================

cd /d "%~dp0"
set "REPO_ROOT=%~dp0.."

set "BRIDGE_PY="
if exist "%REPO_ROOT%\.pixi\envs\default\Scripts\python.exe" (
    set "BRIDGE_PY=%REPO_ROOT%\.pixi\envs\default\Scripts\python.exe"
) else if exist "%REPO_ROOT%\.pixi\envs\default\python.exe" (
    set "BRIDGE_PY=%REPO_ROOT%\.pixi\envs\default\python.exe"
) else (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        set "BRIDGE_PY=%%i"
        goto :bridge_python_ready
    )
)
:bridge_python_ready

if not "!BRIDGE_PY!"=="" (
    call "!BRIDGE_PY!" "%REPO_ROOT%\scripts\webui_local_bridge.py" --ping >nul 2>nul
    if errorlevel 1 (
        echo [检查] 本地启动桥未运行，正在拉起...
        start "Unitale Local Bridge" /min "!BRIDGE_PY!" "%REPO_ROOT%\scripts\webui_local_bridge.py"
        timeout /t 1 >nul
    ) else (
        echo [检查] 本地启动桥已就绪。
    )
) else (
    echo [提示] 未找到可用 Python，系统页无法一键拉起本地服务。
)

if not exist "package.json" (
    echo [错误] 当前目录缺少 package.json，无法启动 WebUI。
    pause
    exit /b 1
)

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Node.js 环境。
    echo 请先安装 Node.js: https://nodejs.org/zh-cn/
    pause
    exit /b 1
)

where npm.cmd >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 npm.cmd，Node.js 安装可能不完整。
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo.
    echo [提示] 检测到首次运行，正在安装前端依赖...
    echo [注意] 这可能需要几分钟，请保持网络可用。
    echo.
    call npm.cmd install
    if %errorlevel% neq 0 (
        echo.
        echo [错误] 依赖安装失败！
        echo 请检查网络连接，或尝试更换 npm 镜像源。
        pause
        exit /b 1
    )
    echo.
    echo [成功] 依赖安装完成，即将在 3 秒后启动。
    timeout /t 3 >nul
) else (
    echo [检查] 依赖已安装，准备启动...
)

echo.
echo [提示] 正在启动 WebUI 开发服务器...
echo [提示] 启动成功后会自动打开浏览器。
echo [提示] 默认端口：3000；如被占用，Vite 会自动切换到下一个可用端口。
echo [提示] 系统页支持一键启动本地服务并加载模型。
echo.
echo 如需停止，请直接关闭此窗口。
echo.

call npm.cmd run dev -- --open

if %errorlevel% neq 0 (
    echo.
    echo [错误] WebUI 服务启动异常退出。
    pause
    exit /b 1
)

exit /b 0
