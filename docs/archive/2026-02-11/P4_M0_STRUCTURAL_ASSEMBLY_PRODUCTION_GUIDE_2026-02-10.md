# P4-M0 生产指南：结构化装配（不改业务行为）

最后更新：2026-02-10  
阶段目标：把 `core/api.py` 从“巨石入口”拆成“薄入口 + 可组合装配层”，在**零行为变更**前提下建立后续重构底座。  
关联文档：`P4_BACKEND_REFACTOR_EXECUTION_SYSTEM_2026-02-10.md`、`P4_BACKEND_REFACTOR_PLAN_2026-02-10.md`

---

## 1. 里程碑定义

### 1.1 使命

1. 新建 server 装配骨架（`core/server/*`），承接 app/ctx 组装职责。
2. `core/api.py` 变成 thin wrapper（兼容现有启动命令）。
3. 对外行为完全一致（端点、参数、响应、日志主语义不变）。

### 1.2 非目标

1. 不改任何推理逻辑。
2. 不改 cache key 计算。
3. 不改 v1/v2 路由实现细节（仅搬运组织）。

---

## 2. 边界与影响面

### 2.1 In Scope

- 目录新增：
  - `core/server/main.py`
  - `core/server/app.py`
  - `core/server/ctx.py`
  - `core/server/__init__.py`
- `core/api.py` 改为入口代理（保持 CLI 参数与运行方式兼容）。

### 2.2 Out of Scope

- `core/api_v2_routes.py` 不改业务逻辑。
- `core/worker.py` 不改。
- UI 页面和 bridge 行为不改。

### 2.3 风险点

1. 导入路径改变导致启动失败。
2. 全局变量初始化顺序变化导致运行期状态异常。
3. CLI 参数解析丢失导致 `StartAPIServer.bat` 行为变化。

---

## 3. 交付物（DoD）

完成标准（全部满足才算 Done）：

1. `python core/api.py --help` 正常输出，参数与重构前一致。
2. `StartAPIServer.bat` 启动成功，`/api/v2/health` 返回 200。
3. v1/v2 核心 smoke 全通过。
4. `rg "^@app.route" core/api.py` 的结果显著减少（或仅保留入口层）。

---

## 4. 任务拆解（工业级执行单）

## Phase A：设计冻结（0.5 天）

1. 梳理 `core/api.py` 的全局初始化顺序：
   - env/warnings/log
   - 路径与模型依赖
   - Flask app 创建与 middleware
   - v2 state 初始化
   - blueprint 注册
   - CLI 入口
2. 输出迁移映射表（旧段落 -> 新文件位置）。
3. 明确“不可变项”清单：路由 URL、默认端口、默认配置路径、响应体格式。

产物：
- `M0_migration_map.md`（可放到 PR 描述中）

## Phase B：代码搬运（1 天）

1. 新建 `core/server/ctx.py`
   - 搬运并封装 v2 state（路径、锁、store、cache、metrics、job queue）。
   - 提供 `build_context()`。
2. 新建 `core/server/app.py`
   - 提供 `create_app(ctx)`。
   - 挂载 middleware、blueprint。
3. 新建 `core/server/main.py`
   - CLI 参数解析、调用 `build_context()` + `create_app()` + `run()`。
4. 改造 `core/api.py`
   - 仅保留兼容入口：
     - `from core.server.main import main`
     - `if __name__ == "__main__": main()`

原则：
- 尽量“原样复制 + 最小改名”，减少行为改变风险。

## Phase C：验证与收尾（0.5 天）

1. 运行静态验证：
   - `python -m py_compile core\\api.py`
   - `python -m py_compile core\\server\\app.py`
2. 运行功能 smoke：
   - 启动 API
   - 调用 v1/v2 核心端点
3. 补充注释与文档更新：
   - 在 `P4_BACKEND_REFACTOR_PLAN_2026-02-10.md` 记录 M0 完成情况。

---

## 5. 测试矩阵

### 5.1 启动类测试

1. `python core/api.py --help`
2. `python core/api.py --config config\\super_agent.json --host 127.0.0.1 --port 9880`

### 5.2 API smoke（v2）

1. `GET /api/v2/health`
2. `GET /api/v2/voices`
3. `GET /api/v2/assets/audio`

### 5.3 API smoke（v1）

1. `GET /speakers`
2. `GET /api/health`
3. `POST /api/tts`（可用最短文本）

### 5.4 回归脚本

1. `python scripts/p2_backend_acceptance_test.py`

---

## 6. 发布策略（M0）

### 6.1 发布前检查

1. 启动命令保持不变（脚本无需改）。
2. 环境变量行为保持不变。
3. 日志中出现新模块路径可接受，但关键语义字段不可丢。

### 6.2 观察窗口

- 发布后 2 小时重点观察：
  - 启动失败率
  - 健康检查失败率
  - 请求 5xx 比例

### 6.3 回滚动作

1. 回退 `core/api.py` 到 M0 前版本。
2. 删除/忽略 `core/server/*` 新文件（不影响旧路径）。
3. 重启服务验证核心端点恢复。

---

## 7. 代码评审清单（Reviewer Checklist）

1. 是否存在业务逻辑改动？（M0 不允许）
2. 全局初始化顺序是否与旧版一致？
3. CLI 参数是否完整保留？
4. 路由注册是否完整保留？
5. 出错时错误码/响应格式是否变化？

---

## 8. 风险与预案

风险 A：循环导入  
预案：`core/server/*` 只依赖基础模块，禁止反向依赖 `core/api.py`。

风险 B：上下文初始化时机错误  
预案：将 context 构建写成纯函数，禁止模块导入阶段副作用。

风险 C：隐藏行为变更  
预案：保留一份“重构前后请求录制样本”进行 diff（状态码、header、响应体主字段）。

---

## 9. 乔布斯理念对齐（M0 版本）

1. 简洁：`core/api.py` 从“实现文件”降级为“入口文件”。
2. 聚焦：M0 只做架构骨架，不碰业务行为。
3. 端到端：从启动脚本到 API 响应，用户体验不变。
4. 细节：CLI 参数、默认值、错误响应格式逐项保真。

---

## 10. M0 结束后必须达到的状态

1. 团队可以在 `core/server/*` 增量迭代，而不用继续扩写 `core/api.py`。
2. 后续 M1-M4 的改动可以“定点改动”而不是全文件搜索替换。
3. 系统外部行为无感知变化，为下一阶段建立安全起点。

