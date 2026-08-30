# 智效工坊（Zhixiao Agent）

面向真实软件仓库的软件工程 Agent harness（默认：一个模型 + 工具循环 + 权限/验证，不是 4 个独立 Agent）。它可以探测项目、制定计划、在隔离 worktree 中修改代码、运行测试、复核结果，并交付可审计的 Git diff。

## 产品形态

- Web：团队、仓库、任务、实时事件、计划审批、Diff、运行证据条、可视化工作流；知识图谱与评测控制台是平台 UI，LoRA/百万召回未上线。
- CLI/TUI：在本地仓库中交互执行，或以无头模式接入 CI。
- API/Worker：持久化任务、编排 Agent、执行工具、流式推送事件。
- Agent Core：LangGraph 工作流、权限、Runner、插件化工具/命令/hooks、技能、记忆、模型与评测。

## 仓库结构

```text
apps/api             FastAPI 平台 API
apps/web             Vue 3 Web 管理台
packages/agent_core  Agent 运行时与 CLI
infra                Docker Compose、镜像与运维配置
docs                 原始目标、设计、验收矩阵与项目资料
tests                跨模块场景与端到端测试
```

## 本地快速开始（无需 Docker）

```bash
python -m venv .venv
pip install -e "packages/agent_core[dev,cli]"
zhixiao doctor --json
zhixiao plugins list
zhixiao plugins doctor --workspace <tmp>
zhixiao run "Inspect this workspace without modifying it" --workspace <tmp> --offline \
  --permission read_only --approval-policy never --output-format json --events none
python tests/evals/run_behavioral.py
```

把 `<tmp>` 换成一个空目录。无头模式接受位置参数、`--prompt`、`--prompt-file` 或标准输入，并支持 `text`、`json`、`jsonl` 输出。交互模式运行 `zhixiao`，也可携带首条任务；TUI 与 CLI 共用本地会话清单。写入、命令执行与发布权限需要通过 `--permission` 显式提升；`--mode ask|plan|review` 只读，无头 `run` 默认 `--mode code`。没有模型密钥时用 `--offline` 验证只读链路。

常用控制命令：

```bash
zhixiao version
zhixiao runs list
zhixiao interrupt <run-id>
zhixiao resume <run-id>
zhixiao events <run-id> --follow
zhixiao review --uncommitted --offline
zhixiao config show
zhixiao skills list
zhixiao plugins list
zhixiao mcp list
```

CLI 会持久化本地运行清单，支持恢复、fork、制品查询和 JSONL 事件回放。模型回合、工具调用、Token、成本和时长均可设预算；写任务只有验证通过或记录明确的未验证 waiver 才能成功。

平台模式使用 Docker Compose：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Web 默认地址为 `http://localhost:5173`，API 文档为 `http://localhost:8000/docs`。
Prometheus 与 Grafana 随 Compose 启动，默认仅在内部网络抓取 `/metrics`；空间管理员通过 Web 的“运行观测”查看空间级 SLO。首次进入空间时，上手引导会保存进度，可跳过或重新播放。

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
- 未受信任目录只启用只读能力，不加载项目配置、hooks、自定义命令、项目 Skill 或工作区插件。
- `--yes` 只批准启动计划，不批准危险命令、联网、MCP 或 Git 发布。
- 每次运行保留步骤、工具调用、审批、测试和制品记录。

详细需求与可验证证据见 [验收矩阵](docs/ACCEPTANCE.md)。

## 证明什么 / 不证明什么

**能证明（本地或 GitHub Actions 可复现）**

- workspace 边界：工具路径不能逃出声明的根目录。
- 危险命令拦截：无审批时 `git push` / `rm -rf` 被 `CommandPolicy` 挡住（行为门禁 `dangerous-command`）。
- 插件组装：`zhixiao plugins doctor`；未信任目录不加载 `.zhixiao/plugins`。
- 离线 JSON 运行：`--offline --output-format json` 得到可解析的 `RunResult`。
- 协同中断可恢复：runtime 消费控制文件后 LangGraph `interrupt(operator_stop)`，同一 run_id `resume`（行为门禁 `interrupt-resume`，ScriptedModel）。
- Web 运行证据字段：`permission_mode`、verification（缺失为「未回报」）、`termination_reason`、`usage_snapshot`。

**不能证明**

- 真实模型的任务完成率或幻觉率（含 fixture 里的数字）。
- 已交付 4 个独立 Agent；或 Redis 作为 LangGraph 图 checkpointer。
- GPU LoRA / 百万向量召回的质量。
- Playwright 验证了真实编码 Agent（CI 容器里是 Web UI 烟测）。

`packages/agent_core/pyproject.toml` 的 `version = "1.0.0"` 不是已发布版本。CI 以 GitHub Actions 为准，不要口头报通过次数。

## 文档导航

- [系统架构](docs/ARCHITECTURE.md)
- [安全模型](docs/SECURITY.md)
- [开发手册](docs/DEVELOPMENT.md)
- [部署手册](docs/DEPLOYMENT.md)
- [API 指南](docs/API.md)
- [演示脚本](docs/DEMO.md)
- [评测方法](docs/EVALUATION.md)
- [可观测性与 SLO](docs/OBSERVABILITY.md)
- [GOAL-01～07 验收矩阵](docs/ACCEPTANCE.md)

## 交付原则

版本号、任务完成率、首次通过率、成本与延迟只从 CI 制品或 live 评测文件生成。本仓库不会用估算数据替代实测结果。默认交付物是可审查 diff；commit、push 与 PR 都是单独的受审操作。
