# 开发手册

## 环境

需要 Python 3.11、Node.js 20、Git。Docker 不是 Core/API/Web 单元测试的前提，但完整数据服务和容器验收需要 Docker Compose。

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e "packages/agent_core[dev,cli]"
python -m pip install -e "apps/api[test]"
cd apps/web && npm ci
```

## 日常门禁

```bash
ruff check --config pyproject.toml packages/agent_core/src packages/agent_core/tests
mypy --config-file pyproject.toml packages/agent_core/src
pytest -q packages/agent_core/tests

cd apps/api
alembic upgrade head --sql
pytest -q

cd ../web
npm run lint
npm test
npm run build:prod
```

修改功能时必须增加聚焦测试。进程边界使用 async 接口和显式类型；工具必须返回共享 ToolResult，不得返回仅供人读的自由文本结果。Vue 使用严格 TypeScript 与 Composition API。

## 本地 API

复制 `.env.example` 并把 MySQL/Redis/Chroma 主机保持为 `localhost`。启动依赖后：

```bash
cd apps/api
alembic upgrade head
uvicorn app.main:app --reload
```

测试使用 SQLite 和内存 Redis 适配器，不需要外部数据库。不要把测试适配器用于生产。

## CLI 与离线验证

```bash
zhixiao doctor
zhixiao run --workspace . --permission read_only --prompt "列出风险最高的三个模块"
zhixiao
```

写入与执行只对用户明确选择的权限生效。调试时使用临时仓库或 worktree，不要把任务仓库、worktree、日志或生成数据加入本仓库。

## 数据库变更

在 `apps/api` 创建 Alembic migration，先检查 SQL，再在一次性数据库上升级和回滚。模型变更、migration 和 API schema 必须在同一变更中提交。

## 评测开发

```bash
python tests/evals/run_scenarios.py --validate-only --output evaluation-manifest.json
python -m unittest discover -s tests/evals -p "test_*.py"
```

清单校验不是能力评测。真实运行产生逐场景结果与制品后，使用 `--results` 计算指标。
