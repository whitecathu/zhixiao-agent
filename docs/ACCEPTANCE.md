# GOAL-01～07 验收矩阵

状态只描述仓库中的可验证证据：`已实现` 表示存在实现与聚焦测试，`CI 待验证` 表示本机缺少 Docker 或外部服务，必须以 GitHub Actions 结果为准。任何状态都不等于真实任务完成率。

| Goal | 验收项 | 实现证据 | 自动化证据 | 当前状态 |
|---|---|---|---|---|
| 01 | Monorepo、统一执行图、架构与安全边界 | `apps/`、`packages/`、`infra/`、`docs/ARCHITECTURE.md` | Core/API/Web CI | 已实现，CI 待验证 |
| 02 | 认证、空间、仓库、任务运行、审批、制品、SSE | `apps/api/app/router`、`apps/api/app/model/platform.py`、Alembic 迁移 | `apps/api/tests` | 已实现 |
| 03 | LangGraph 计划/执行/验证/修复闭环、路由、工具、Skill/指令 | `packages/agent_core/src/zhixiao_agent` | `packages/agent_core/tests` | 已实现 |
| 04 | Vue 管理台、上手引导、运行观测、可视化工作流、图谱证据链与运行回放 | `apps/web/src` | ESLint、Vitest、类型检查、构建、`tests/e2e` | 已实现，新增容器 E2E 待验证 |
| 05 | API/Worker/Web 与 MySQL/Redis/Chroma/Milvus/Neo4j/Prometheus/Grafana 一键编排 | `infra/docker-compose.yml`、`infra/observability`、Dockerfiles、Nginx | Compose 配置、CI 容器冒烟、定时完整编排 | 静态校验通过，容器待验证 |
| 06 | 向量抽象、双写迁移、图谱融合、数据清洗、LoRA、模型注册和 A/B | `zhixiao_agent/rag`、`zhixiao_agent/training` | RAG/训练单元测试、GPU 工作流 | CPU 链路已实现，GPU/百万级基准待实测 |
| 07 | 项目指令、Skill、复盘资料与证据约束 | `AGENTS.md`、`skills.py`、`docs/project` | Skill 测试、评测清单校验 | 已实现；量化数据待实测 |

## 发布门禁

`v1.0.0` 只在以下证据全部存在后发布：

1. Core 的 Ruff、Mypy、Pytest 与覆盖率制品通过。
2. API 单元/集成测试和 Alembic migration 通过。
3. Web lint、Vitest、生产构建与 Playwright 容器烟测通过。
4. Compose 配置解析、镜像构建、服务健康检查通过。
5. 固定评测清单被校验；真实结果文件覆盖全部场景且制品齐全。
6. 安全扫描没有高危代码问题，仓库没有密钥、权重、数据集、任务仓库或 worktree。
7. Web 与 CLI 各完成一次真实跨栈任务，交付的 diff 可应用且测试报告可回放。

## 产品化扩展验收

- 空间管理员能查看不含敏感或高基数标签的运行指标；成员访问观测汇总返回 403，未知模型成本保持 `null`。
- 上手引导按用户和空间恢复进度，支持完成、跳过和重放；空间配置只允许管理员修改。
- 非法、未发布或禁用的工作流不能执行；Worker 将已发布 DSL 和版本传给 Agent Core，运行回放保留固化版本。
- 图谱探索受空间隔离、深度和数量上限约束；无来源证据时明确返回降级状态，不把关系作为回答依据。

## 评测场景映射

| 场景 | 关键门禁 |
|---|---|
| Python 缺陷修复 | 回归测试、最小 diff、边界不越权 |
| FastAPI 接口修改 | OpenAPI 契约、非法输入、API 测试 |
| Vue 页面实现 | 严格类型、组件状态、组件测试 |
| 补充测试 | 不改变生产行为、覆盖率提升 |
| 跨前后端功能 | migration、API/类型一致、E2E |
| 失败测试自修复 | 初次失败、根因与修复轮次可回放 |
| 暂停恢复 | 同一 run id、审批与 checkpoint 证据 |
| 危险命令审批 | 删除/push 不产生未经批准的外部变更 |

定义在 `tests/evals/scenarios.json`。`--validate-only` 只证明清单结构有效，输出的指标必须为 `null`；只有提供逐场景真实结果，脚本才计算任务完成率等指标。

## 尚需外部环境的证据

- 本机当前 Docker daemon 不可用，因此 Compose 只能做 `docker compose config`/静态校验，服务级验收由 GitHub Actions 执行。
- Milvus 百万级性能、7B/14B LoRA、vLLM 服务和真实模型成本需要 GPU/基准环境，不得由微型单测结果代替。
- commit、push、PR 与 Release 属于显式审批操作；代码存在不代表已经发布。
