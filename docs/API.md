# API 指南

API 根路径为 `/api/v1`，交互文档为 `/docs`，OpenAPI JSON 为 `/openapi.json`。除注册、登录与健康检查外，业务请求需要：

```http
Authorization: Bearer <access-token>
X-Space-Id: <space-id>
```

响应使用统一 envelope：成功时 `code=0` 且业务值位于 `data`；错误包含稳定错误码、消息和 trace id。分页接口返回 `items`、页码、页大小与总数。

## 资源概览

| 资源 | 主要路径 |
|---|---|
| 认证 | `/auth/register`、`/auth/login`、`/auth/refresh`、`/auth/me` |
| 空间 | `/spaces`、`/spaces/mine`、`/spaces/{id}/members` |
| 仓库/工作区 | `/repositories`、`/repositories/{id}/workspaces` |
| 运行 | `/task-runs`、`/task-runs/{id}`、`/task-runs/{id}/fork`、`/tasks/{id}/interrupt`、`/tasks/{id}/resume` |
| 审批/步骤/工具 | `/tasks/{id}/approvals`、`/steps`、`/tool-invocations` |
| 事件/交付 | `/tasks/{id}/events`、`/diff`、`/tests`、`/artifacts` |
| 定义 | `/workflows`、`/agents`、`/tools`、`/models` |
| MCP 定义 | `/mcp-servers`、`/mcp-servers/{id}`、`/mcp-servers/{id}/test` |
| 工作流版本 | `/workflows/{id}/versions`、`/workflows/{id}/publish`、`/task-runs/{id}/workflow-replay` |
| AI/知识 | `/fine-tunes`、`/evaluations`、`/knowledge/graph`、`/knowledge/graph/explore`、`/knowledge/search` |
| 产品引导 | `/onboarding/me`、`/onboarding/config` |
| 运行观测 | `/observability/summary`；内部抓取端点 `/metrics` |

## 创建与观察运行

```http
POST /api/v1/task-runs
Content-Type: application/json

{
  "repository_id": 12,
  "title": "增加任务标签",
  "prompt": "同步修改 migration、API、Vue 页面和测试",
  "permission_mode": "edit",
  "session_name": "task-labels",
  "budget": {
    "max_model_turns": 30,
    "max_tool_calls": 50,
    "max_tokens": 200000,
    "max_cost_usd": 2.0,
    "max_duration_seconds": 1800
  },
  "verification_commands": ["pytest -q", "npm test"]
}
```

`allow_unverified` 是可选的明确 waiver 原因，不是布尔开关。任务响应保留 `parent_run_id`、`session_name`、`termination_reason`、`budget_snapshot`、`usage_snapshot` 和验证配置。Worker 回调同时持久化结构化 `verification`、`usage`、`budgets` 与 `next_actions`。

通过 `POST /task-runs/{id}/fork` 创建独立子运行；可覆盖 title、prompt、session name 或 permission，其他工作流、Agent、预算和验证设置从父运行复制。子运行重新进入计划审批，不继承父运行的能力审批。

`GET /task-runs` 支持 `workspace_id`、`status`、`created_from` 和 `created_to` 筛选，时间边界为 ISO 8601 且包含端点。

订阅事件：

```http
GET /api/v1/tasks/<run-id>/events
Accept: text/event-stream
Last-Event-ID: 1712345678901-0
```

也可用 `?cursor=<redis-stream-id>`。客户端应保存最后一个事件 id，断线后带游标重连；事件处理必须幂等。SSE 事件包括运行阶段、工具调用、Todo、审批、终端块、制品与终态。

## MCP server 定义

MCP 控制面只保存无密钥定义：`stdio` 使用 command/arguments，`streamable_http` 使用无内嵌凭据的公网 HTTPS URL；环境配置保存的是变量名引用，不保存变量值。成员可读，只有空间管理员可创建、更新、删除和诊断。

`POST /mcp-servers/{id}/test` 仅验证结构、引用和策略，响应明确返回 `network_attempted=false`、`command_executed=false`。它不会启动 stdio 命令或访问 URL，因此不代表服务器真实在线；真实 MCP 调用仍由 Worker、工具白名单、网络许可和独立审批控制。

## 审批

先读取 `/tasks/{run-id}/approvals`，再向 `/tasks/{run-id}/approvals` 提交 `approval_id` 和 `decision`。拒绝是终态证据，不应通过重新生成 approval 绕过。commit、push 和 PR 的批准范围必须精确到仓库、分支和动作。

## 工作流、图谱与引导

- 工作流先保存为草稿，再由空间管理员发布；TaskRun 只能引用已发布版本，并固化 `workflow_version`。DSL 校验节点可达性、条件边、重试上限、审批点和工具白名单。
- `POST /knowledge/graph/explore` 支持查询、实体类型、邻居深度和结果上限。响应明确标记截断、检索模式和证据是否充分。
- `/onboarding/me` 保存当前用户在当前空间的步骤进度；只有空间管理员可更新 `/onboarding/config`。
- `/observability/summary?window=1h|24h|7d|30d` 只对空间管理员开放，成本未知时返回 `null`，不得推算。

## 契约来源

本文只给出常用路径；字段和完整路由数量以运行时 `/openapi.json` 为准。CI 通过 API 测试保护认证、多租户隔离、平台实体和 SSE 重连契约。
