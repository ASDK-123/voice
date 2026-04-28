@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Unitale Pro 工作站 - WebUI（推荐）
echo ==========================================
echo.
echo 当前主线入口：WebUI 工作站
echo 说明：本地启动桥会随 WebUI 一起启动，系统页可一键拉起本地服务并加载模型
echo.

if not exist "web_ui\start.bat" (
    echo [错误] 未找到前端启动脚本：web_ui\start.bat
    echo 请确认项目目录完整。
    echo.
    pause
    exit /b 1
)

call "%~dp0web_ui\start.bat"
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [错误] WebUI 启动失败，退出码：%EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%
