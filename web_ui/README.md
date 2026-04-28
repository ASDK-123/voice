# WebUI Workspace

`web_ui/` 是当前项目的前端主线。

当前定位：

1. 默认工作入口是 `Pro Workspace`
2. `Voices / Assets / Task / Export / System` 能力逐步并入 WebUI
3. 桌面 GUI 仅作为 legacy 兼容入口保留

## 开发

```powershell
cd web_ui
npm install
npm run dev
```

默认开发地址：

```text
http://127.0.0.1:3000
```

如果 `3000` 端口被占用，Vite 会自动切换到下一个可用端口，实际地址以终端输出或自动打开的浏览器页面为准。

如需连接本地 API，请先启动根目录的：

```powershell
StartAPIServer.bat
```

## 构建

```powershell
cd web_ui
npm run build
```

## Smoke

最小 smoke 检查脚本：

```powershell
cd web_ui
npm run smoke:install
npm run smoke
```

说明：

1. `smoke` 会先构建，再启动脚本内静态预览服务
2. 脚本会用 Playwright 打开页面，并对 `Pro Workspace` 主流程做最小检查
3. 失败截图会输出到 `web_ui/output/playwright/`
