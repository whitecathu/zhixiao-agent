# 智效工坊（Zhixiao Agent）

面向真实软件仓库的 AI 全栈工程 Agent。它可以探测项目、制定计划、在隔离 worktree 中修改代码、运行测试、复核结果，并交付可审计的 Git diff。

## 产品形态

- Web：团队、仓库、任务、实时事件、计划审批、Diff、工作流、知识与评测管理。
- CLI/TUI：在本地仓库中交互执行，或以无头模式接入 CI。
- API/Worker：持久化任务、编排 Agent、执行工具、流式推送事件。
- Agent Core：LangGraph 工作流、权限、Runner、工具、技能、记忆、模型与评测。

## 仓库结构

```text
apps/api             FastAPI 平台 API
apps/web             Vue 3 Web 管理台
packages/agent_core  Agent 运行时与 CLI
infra                Docker Compose、镜像与运维配置
docs                 原始目标、设计、验收矩阵与项目资料
tests                跨模块场景与端到端测试
```

## 本地快速开始

```bash
python -m venv .venv
pip install -e "packages/agent_core[dev,cli]"
zhixiao run --prompt "分析当前仓库并给出改进建议" --workspace . --permission read_only
```

无头模式会输出结构化运行结果并使用退出码表示门禁结果；交互模式运行 `zhixiao`。写入、命令执行与发布权限需要通过 `--permission` 显式提升。没有模型密钥时可先运行 `zhixiao doctor` 检查本地环境。

平台模式使用 Docker Compose：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Web 默认地址为 `http://localhost:5173`，API 文档为 `http://localhost:8000/docs`。

开发者可分别验证三个主模块：

```bash
pytest -q packages/agent_core/tests
(cd apps/api && pytest -q)
(cd apps/web && npm ci && npm run lint && npm test && npm run build:prod)
python tests/evals/run_scenarios.py --validate-only
```

## 安全默认值

- 工具只能访问声明的 workspace 根目录。
- 默认不提交、不推送、不创建 PR。
- 写文件、执行命令、外部网络和 Git 发布按权限及审批策略控制。
- 每次运行保留步骤、工具调用、审批、测试和制品记录。

详细需求与可验证证据见 [验收矩阵](docs/ACCEPTANCE.md)。

## 文档导航

- [系统架构](docs/ARCHITECTURE.md)
- [安全模型](docs/SECURITY.md)
- [开发手册](docs/DEVELOPMENT.md)
- [部署手册](docs/DEPLOYMENT.md)
- [API 指南](docs/API.md)
- [演示脚本](docs/DEMO.md)
- [评测方法](docs/EVALUATION.md)
- [GOAL-01～07 验收矩阵](docs/ACCEPTANCE.md)

## 交付原则

版本号、任务完成率、首次通过率、成本与延迟只从 CI 制品或 `evaluation_runs` 生成。本仓库不会用估算数据替代实测结果。默认交付物是可审查 diff；commit、push 与 PR 都是单独的受审操作。
