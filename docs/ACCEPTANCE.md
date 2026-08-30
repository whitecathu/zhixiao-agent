# GOAL-01～07 验收矩阵

CI 的唯一事实源是 **GitHub Actions**（`.github/workflows/ci.yml`），不要用本机一次 pytest 或口头「全绿」代替。`packages/agent_core/pyproject.toml` 的 `version = "1.0.0"` 只是包元数据，**不是已发布的 v1.0.0**。

状态只描述仓库中的可验证证据：`已实现` 表示存在实现与聚焦测试，`CI 待验证` 表示必须以 GitHub Actions 该次 run 的结论为准。任何状态都不等于真实任务完成率。不要发明 CI 通过次数。

| Goal | 验收项 | 实现证据 | 自动化证据 | 当前状态 |
|---|---|---|---|---|
| 01 | Monorepo、统一执行图、架构与安全边界 | `apps/`、`packages/`、`infra/`、`docs/ARCHITECTURE.md` | Core/API/Web CI | 已实现，CI 待验证 |
| 02 | 认证、空间、仓库、任务运行/fork、预算与用量、审批、制品、SSE、MCP 定义 | `apps/api/app/router`、`apps/api/app/model/platform.py`、`0005_agent_cli_control` | `apps/api/tests` | 已实现 |
| 03 | 单 Agent 工具循环、PluginHost、LangGraph SQLite interrupt/resume、预算终止、CLI/TUI、路由标签、工具、Skill/指令 | `packages/agent_core/src/zhixiao_agent` | `packages/agent_core/tests`、CLI CI smoke（含 `zhixiao plugins doctor`） | 已实现 |
| 04 | Vue 管理台、上手引导、运行观测、运行证据条、可视化工作流、图谱证据链与运行回放 | `apps/web/src` | ESLint、Vitest、类型检查、构建；容器内 Playwright 为 UI 烟测 | 已实现；Playwright 不证明编码 Agent 完成率 |
| 05 | API/Worker/Web 与 MySQL/Redis/Chroma/Milvus/Neo4j/Prometheus/Grafana 一键编排 | `infra/docker-compose.yml`、`infra/observability`、Dockerfiles、Nginx | Compose 配置、CI 容器冒烟、定时完整编排 | 静态校验通过，容器待验证 |
| 06 | 向量抽象、双写迁移、图谱融合、数据清洗、LoRA、模型注册和 A/B | `zhixiao_agent/rag`、`zhixiao_agent/training` | RAG/训练单元测试 | **未上线 / 未实测**（最多 CPU stub；GPU/LoRA/百万召回不得当作成品） |
| 07 | 项目指令、Skill、复盘资料与证据约束 | `AGENTS.md`、`skills.py`、`docs/project` | Skill 测试、评测清单校验 | 已实现；量化数据待实测 |

## 离线质量门禁（行为，非完成率）

GitHub Actions 的 `offline-evaluation-gates` 会跑 `python tests/evals/run_behavioral.py`（ScriptedModel + 真实 `AgentRuntime`）：`dangerous-command`、`interrupt-resume`、`ask-read-only`。这是离线质量门禁。

`tests/evals/fixtures/offline_harness_results.json` 只证明报告管线能吃结果文件（provenance），**不是**任务完成率或幻觉率。`--validate-only` 只证明 `scenarios.json` 结构有效。

## 发布门禁

`packages/agent_core` 的版本号 `1.0.0` 不等于已经发布。真正的 `v1.0.0` 只在以下证据全部存在后打 tag：

1. Core 的 Ruff、Mypy、Pytest 与覆盖率制品通过。
2. API 单元/集成测试和 Alembic migration 通过。
3. Web lint、Vitest、生产构建通过；Playwright 仅作为 CI 容器 UI 烟测，不替代 live 编码评测。
4. Compose 配置解析、镜像构建、服务健康检查通过。
5. 固定评测清单被校验；真实结果文件覆盖全部场景且制品齐全。
6. 安全扫描没有高危代码问题，仓库没有密钥、权重、数据集、任务仓库或 worktree。
7. Web 与 CLI 各完成一次真实跨栈任务，交付的 diff 可应用且测试报告可回放。

## Agent 与 CLI 控制面验收

- 写任务只有验证通过或带理由的 waiver 才能成功；预算耗尽、停滞、连续同根因失败和无效模型响应产生结构化失败终态。
- `RunResult` 包含 schema version、verification、termination reason、usage、budgets、next actions 和完整制品元数据。
- CLI 帮助、版本及离线只读 JSON smoke 在 CI 中执行；JSON 可解析且包含运行、验证和预算字段，stdout 不混入进度日志。
- prompt 位置参数、`--prompt`、文件和 stdin 输入互斥；`jsonl` 的最后一条事件固定为 `result`。
- 本地运行可 list/show/delete、resume、fork 和 interrupt；TUI 与无头 CLI 写入同一 `SessionStore`。未知斜杠命令被拒绝，不会进入模型。未信任目录不能把权限升到 `edit/execute/full`。
- `--mode ask|plan` 只暴露只读工具；`--mode code` 才实现改动；`--mode review` 只读审查。无头 `run` 默认 `code`，TUI 默认 `ask`。
- 本地 `interrupt` 写入 `{state_dir}/control/{run_id}` 并把清单标为 `interrupted`。runtime **会消费该文件**（unlink）后调用 LangGraph `interrupt({"kind":"operator_stop"})`，因此停的是工具循环；同一 run id `resume` 可从 SQLite checkpoint 继续。平台 Worker 另用 Redis `run:control:{run_id}` 取消 asyncio 任务，不是图 checkpointer。stdio MCP 不要求网络审批；HTTP MCP 仍要求 `--approve-network mcp`。
- 运行时由 PluginHost 组装：内置插件贡献默认工具/斜杠命令/Skill/MCP；可信工作区的自定义命令、hooks 和 `.zhixiao/plugins/*.py` 写入同一套 seams。未知 inject、重复工具/命令名、apply 失败会明确报错。未信任目录不加载项目插件。TUI `/plugins` 与 `zhixiao plugins list|doctor` 观察同一棵树。
- 远程 SSE 同时支持 `Last-Event-ID` 与 cursor、去重、有限重试和总超时；远程 `resume`/`approve`/`fork` 会 follow 到终态。
- 未受信任目录只读且不加载项目扩展；`--yes` 不批准危险命令、网络、MCP 或 Git 发布。
- MCP 定义不保存密钥；控制面诊断不执行命令、不发网络，并拒绝 localhost、私网 IP 和 URL 嵌入凭据。

## 产品化扩展验收

- 空间管理员能查看不含敏感或高基数标签的运行指标；成员访问观测汇总返回 403，未知模型成本保持 `null`。
- 上手引导按用户和空间恢复进度，支持完成、跳过和重放；空间配置只允许管理员修改。
- 非法、未发布或禁用的工作流不能执行；Worker 将已发布 DSL 和版本传给 Agent Core，运行回放保留固化版本。
- 图谱探索受空间隔离、深度和数量上限约束；无来源证据时明确返回降级状态，不把关系作为回答依据。召回质量与百万向量基准 **未实测**。

## 评测场景映射

| 场景 | 关键门禁 |
|---|---|
| Python 缺陷修复 | 回归测试、最小 diff、边界不越权 |
| FastAPI 接口修改 | OpenAPI 契约、非法输入、API 测试 |
| Vue 页面实现 | 严格类型、组件状态、组件测试 |
| 补充测试 | 不改变生产行为、覆盖率提升 |
| 跨前后端功能 | migration、API/类型一致、E2E |
| 失败测试自修复 | 初次失败、根因与修复轮次可回放 |
| 暂停恢复 | 同一 run id；计划审批与 operator_stop 均为 LangGraph interrupt + SQLite checkpoint |
| 危险命令审批 | 删除/push 不产生未经批准的外部变更 |

定义在 `tests/evals/scenarios.json`。`--validate-only` 只证明清单结构有效，输出的指标必须为 `null`；只有提供逐场景 **live** 真实结果，脚本才计算任务完成率等指标。fixture 指标不得写入简历。

## 尚需外部环境的证据

- Compose 服务级验收以 GitHub Actions 的 `containers` 作业为准；本机无 Docker 时只做 `docker compose config`/静态校验。不要根据本机环境发明「CI 已通过 N 项」。
- GPU / LoRA / 百万向量召回 / vLLM 服务质量 **未上线、未实测**，不得由微型 CPU 单测代替。
- commit、push、PR 与 Release 属于显式审批操作；代码存在、pyproject 写着 1.0.0，都不代表已经发布。
