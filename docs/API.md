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
| 运行 | `/task-runs`、`/task-runs/{id}`、`/tasks/{id}/interrupt`、`/tasks/{id}/resume` |
| 审批/步骤/工具 | `/tasks/{id}/approvals`、`/steps`、`/tool-invocations` |
| 事件/交付 | `/tasks/{id}/events`、`/diff`、`/tests`、`/artifacts` |
| 定义 | `/workflows`、`/agents`、`/tools`、`/models` |
| AI/知识 | `/fine-tunes`、`/evaluations`、`/knowledge/graph`、`/knowledge/search` |

## 创建与观察运行

```http
POST /api/v1/task-runs
Content-Type: application/json

{
  "repository_id": 12,
  "title": "增加任务标签",
  "prompt": "同步修改 migration、API、Vue 页面和测试",
  "permission_mode": "edit"
}
```

订阅事件：

```http
GET /api/v1/tasks/<run-id>/events
Accept: text/event-stream
Last-Event-ID: 1712345678901-0
```

也可用 `?cursor=<redis-stream-id>`。客户端应保存最后一个事件 id，断线后带游标重连；事件处理必须幂等。SSE 事件包括运行阶段、工具调用、Todo、审批、终端块、制品与终态。

## 审批

先读取 `/tasks/{run-id}/approvals`，再向 `/tasks/{run-id}/approvals` 提交 `approval_id` 和 `decision`。拒绝是终态证据，不应通过重新生成 approval 绕过。commit、push 和 PR 的批准范围必须精确到仓库、分支和动作。

## 契约来源

本文只给出常用路径；字段和全部 57 个路由以运行时 `/openapi.json` 为准。CI 通过 API 测试保护认证、多租户隔离、平台实体和 SSE 重连契约。
