# GitHub 最稳妥上传清单（voice 项目）

更新时间：2026-02-17

## 1. 建议上传（源码与必要配置）

- `core/`
- `cosyvoice/`（仅源码，若内含大模型文件会被 `.gitignore` 过滤）
- `ui/`
- `scripts/`
- `tests/`
- `config/`（建议仅保留 `.json/.toml` 等文本配置，音频会被忽略）
- `docs/`
- `client/`（如需）
- `main.py`
- `README.md`
- `API_USAGE.md`
- `StartAPIServer.bat`
- `StartCosyVoice.bat`
- `DownloadModel.bat`
- `restore_onnx_cpu.bat`
- `LICENSE`

## 2. 不建议上传（已在 `.gitignore` 处理）

- 运行环境与缓存：`.pixi/`、`__pycache__/`、`.pytest_cache/`
- 本地输出：`output/`、`logs/`、`*.log`
- 本机私有配置：`app_config.json`、`.env*`
- 大模型与多媒体产物：`pretrained_models/`、`asset/`、`data/`、`*.pt/*.onnx/*.wav` 等
- 嵌套仓库与个人素材：`third_party/Matcha-TTS/`、`peiying/`

## 3. 首次上传前检查

```powershell
cd C:\Users\lilei\Desktop\voice

# 确认忽略规则生效
git init
git check-ignore -v app_config.json pretrained_models\foo.pt output\demo.wav

# 预览即将提交的文件（不应出现 output/pretrained_models/app_config.json 等）
git add .
git status --short
```

## 4. 推送到你的 GitHub 仓库

```powershell
git branch -M main
git config user.name "你的GitHub用户名"
git config user.email "你的GitHub邮箱"

git commit -m "Initial import: source code and docs"
git remote add origin https://github.com/<你的用户名>/<你的仓库名>.git
git push -u origin main
```

## 5. 常见问题

- 报错 `File ... is 100.00 MB`：
  - 说明大文件未被忽略，先 `git rm --cached <大文件路径>`，再提交
  - 或改用 Git LFS（仅在你确实要托管模型时）
- 报错 `embedded git repository`：
  - 说明误加了嵌套仓库目录，当前默认已忽略 `third_party/Matcha-TTS/`
- 报错认证失败：
  - 使用 GitHub PAT（token）替代密码

