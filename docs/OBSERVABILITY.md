# 可观测性与 SLO

智效工坊默认提供 API 内部指标、空间级运行汇总、Prometheus 告警和 Grafana 仪表盘。监控链路不记录提示词、用户名、任务编号、仓库路径、模型名称或密钥。

## 启动与访问

```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d api prometheus grafana
```

- Prometheus 只在 Compose 内网抓取 `http://api:8000/metrics`，不映射宿主机端口。
- Grafana 默认只绑定 `127.0.0.1:3000`。生产环境应通过现有受控入口接入，禁止将其直接暴露到公网。
- 首次部署前必须在 `infra/.env` 中替换 `GRAFANA_ADMIN_PASSWORD`。
- 预置仪表盘位于 Grafana 的 `Zhixiao / Zhixiao Agent Overview` 文件夹。

## API

`GET /metrics` 是内部 Prometheus 抓取端点，不依赖 JWT 或 `X-Space-Id`。它应仅通过容器网络访问。

`GET /api/v1/observability/summary?window=24h` 返回空间级聚合。`window` 支持 `1h`、`24h`、`7d`、`30d`，默认 `24h`。请求必须同时满足：

1. 有效的 Bearer access token；
2. `X-Space-Id` 指向目标空间；
3. 当前用户在 `space_members` 中的真实角色为 `space_admin` 或 `super_admin`。

响应包含 `generated_at`、`window`、`slo`、`tasks`、`queue`、`tools`、`models` 和 `recent_failures`，并保留审批与总量聚合。模型成本在 provider adapter 尚未持久化费用时明确返回 `null`，不会伪造为 0。

## 指标与标签约束

| 指标 | 固定标签 |
| --- | --- |
| `zhixiao_api_requests_total` | method、路由模板、状态码类别 |
| `zhixiao_api_request_duration_seconds` | method、路由模板 |
| `zhixiao_task_runs_active` | 有界任务状态 |
| `zhixiao_task_runs_completed_total` | 有界终态 |
| `zhixiao_task_run_duration_seconds` | 有界终态 |
| `zhixiao_tool_invocations_total` | 固定工具类别、有界结果 |
| `zhixiao_tool_invocation_duration_seconds` | 固定工具类别 |
| `zhixiao_approval_wait_seconds` | 有界审批结果 |
| `zhixiao_queue_depth` | 固定队列名称 |
| `zhixiao_model_tokens_total` | 已知 provider、输入/输出方向 |
| `zhixiao_model_cost_usd_total` | 已知 provider |

未知工具、provider、状态或队列统一归入 `other`。HTTP 指标使用 FastAPI 路由模板，例如 `/api/v1/task-runs/{run_id}`，不会使用真实 URL。

## 默认 SLO 与告警

- 任务成功率不低于 80%；
- 首次验证通过率不低于 60%（空间汇总）；
- 任务 p95 执行时延不高于 1800 秒；
- API 5xx 比例不高于 5%；
- 任务队列积压不高于 20；
- 最近 30 天模型估算费用不高于 50 USD。

API 聚合阈值可通过 `SLO_TASK_SUCCESS_RATE_TARGET`、`SLO_FIRST_PASS_RATE_TARGET`、`SLO_P95_DURATION_SECONDS_TARGET` 和 `SLO_MONTHLY_COST_BUDGET_USD` 调整。同步修改 `infra/observability/alerts.yml` 后应运行规则校验，确保控制面展示与 Prometheus 告警一致。

## 运行时接入

API 入口应注册 `PrometheusMiddleware` 并包含 `app.router.observability.router`。任务、工具、审批、队列和模型 adapter 应在状态成功持久化后调用 `app.core.metrics` 中对应的记录函数；禁止在失败事务提交前递增业务计数。

验证配置：

```bash
docker compose -f infra/docker-compose.yml config
promtool check config infra/observability/prometheus.yml
promtool check rules infra/observability/alerts.yml
```
