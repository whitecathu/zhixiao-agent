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
zhixiao version
zhixiao run "列出风险最高的三个模块" --workspace . --offline \
  --permission read_only --approval-policy never --output-format json --events none
zhixiao
```

CLI 配置优先级是命令行 → `ZHIXIAO_*` 环境变量 → 可信项目的 `.zhixiao/config.toml` → 用户 `~/.zhixiao/config.toml` → 默认值。密钥只通过 `*_env` 引用和环境变量注入；使用 `zhixiao config show` 验证时输出会脱敏。

写入与执行只对用户明确选择的权限生效，未受信任目录只允许 `read_only`。调试时使用临时仓库或 worktree，不要把任务仓库、worktree、运行状态、日志或生成数据加入本仓库。

CI 的 CLI 冒烟至少验证根帮助、`run --help`、`version`，以及 `--offline --permission read_only --approval-policy never --output-format json --events none` 的无头运行。结构化烟测必须解析 JSON 并断言 `schema_version`、`run_id`、`status`、`verification`、`usage` 和 `budgets`，不能只匹配控制台文字。`--verbose` 诊断只允许出现在 stderr。

TUI 与无头 CLI 共用 `SessionStore`。`zhixiao` 根命令接受 `--workspace`、`--offline`、`--permission`、`--mode`、`--trust-workspace`。`--mode ask|plan|review` 裁剪为只读工具；无头 `run` 默认 `--mode code`。

## 运行状态与扩展

- 本地清单位于配置的 `state_dir`，通过 `runs list|show|delete` 检查；删除索引不会删除 checkpoint，避免误删恢复证据。
- `resume` 使用原 run id 和原配置恢复；`fork` 创建带 `parent_run_id` 的新运行。
- 项目自定义命令位于 `.zhixiao/commands/*.md`；hooks 位于 `.zhixiao/hooks.toml`。二者只有在可信目录中加载。自定义命令的 `mode`/`tools` frontmatter 会约束该次运行。
- 工作区 Python 插件位于 `.zhixiao/plugins/*.py`，或由 `.zhixiao/plugins.toml` 显式列出。插件导出 `name`、`apply(ctx)` 和可选 `inject`，向 tools/commands/hooks/skills/mcp/prompt 贡献。用户插件由 `~/.zhixiao/plugins.toml` 显式组合。`zhixiao plugins list` 与 `zhixiao plugins doctor` 检查同一棵树；错误配置不得被跳过。
- MCP CLI 保存无密钥定义和环境变量引用。`mcp test` 是配置诊断，不应被当作远程能力可用性证明。stdio 传输不要求 `--approve-network mcp`。
- `zhixiao interrupt RUN_ID` 对本地运行写入 `{state_dir}/control/{run_id}` 并标记 `interrupted`，随后 `zhixiao resume RUN_ID` 从 checkpoint 继续。

## 数据库变更

在 `apps/api` 创建 Alembic migration，先检查 SQL，再在一次性数据库上升级和回滚。模型变更、migration 和 API schema 必须在同一变更中提交。当前 Agent/CLI 控制面迁移 head 为 `0005_agent_cli_control`，包含 TaskRun 会话/预算/用量元数据与 MCP server 定义。

## 评测开发

```bash
python tests/evals/run_scenarios.py --validate-only --output evaluation-manifest.json
python -m unittest discover -s tests/evals -p "test_*.py"
```

清单校验不是能力评测。真实运行产生逐场景结果与制品后，使用 `--results` 计算指标。
