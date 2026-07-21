# 智效工坊 后端服务 (zhixiao-backend)

> AI 全栈工程 Agent 控制平面：认证、空间、任务运行、审批、制品、配置、评测与知识图谱
> Python 3.11 · FastAPI 0.110 · SQLAlchemy 2.0 异步 · MySQL 8.0 · Redis Streams

## 一、目录结构与职责

```
zhixiao-backend/
├── app/
│   ├── main.py                # FastAPI 应用入口；生命周期；OpenAPI 分组
│   ├── core/                  # 通用层
│   │   ├── config.py          # pydantic-settings 配置
│   │   ├── error_codes.py     # 错误码枚举
│   │   ├── response.py        # 统一响应体
│   │   ├── exceptions.py      # 异常 + 全局处理器
│   │   ├── security.py        # JWT 双令牌 + bcrypt
│   │   ├── redis_client.py    # Redis 单例 + 幂等/限流/锁/SSE 队列
│   │   ├── logging.py         # loguru 接管 + trace_id
│   │   └── middleware.py      # TraceId/RateLimit/鉴权依赖/RBAC 注解
│   ├── db/                    # 数据库
│   │   └── session.py         # 异步引擎与 session factory
│   ├── model/                 # ORM 表对应（与 4.1 一一对应）
│   ├── schema/                # 业务请求/响应 Pydantic 模型
│   ├── dao/                   # 仅做 SQL，无业务逻辑
│   ├── service/               # 业务编排（auth/space/task/knowledge/stats）
│   ├── router/                # HTTP/SSE 接口
│   ├── engine/                # 本地/Worker 执行引擎适配器
│   │   ├── abstract_engine.py # AbstractExecutionEngine 接口
│   │   ├── registry.py        # 全局引擎注册
│   │   └── vector_client.py   # Chroma 单例 + 健康降级
│   ├── schemas/message.py     # MetaGPT 风格消息体
│   ├── roles/base_role.py     # MetaGPT Role
│   ├── environments/.py       # MetaGPT Environment
│   ├── teams/team.py          # MetaGPT Team
│   ├── memory/memory.py       # MetaGPT Memory
│   └── plans/task.py          # MetaGPT Plan/Task
├── alembic/                   # 迁移
├── tests/                     # pytest 单测
├── .env.example
├── requirements.txt
├── pytest.ini
├── alembic.ini
└── README.md
```

## 二、本地启动

```bash
# 1. 准备虚拟环境
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# 或安装为开发包
pip install -e ".[test]"

# 2. 复制配置
cp .env.example .env           # 调整 MySQL/Redis/LLM 等

# 3. 数据库迁移
alembic upgrade head

# 4. 启动
python -m app.main    # 默认 0.0.0.0:8000
# 或 uvicorn app.main:app --reload
```

OpenAPI 文档：`http://localhost:8000/docs`；按模块分组（认证/团队空间/任务/SSE 执行流/知识/统计与回溯）。

## 三、接口清单

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| POST | /api/v1/auth/register | 注册 | - |
| POST | /api/v1/auth/login | 登录，返回 access+refresh | - |
| POST | /api/v1/auth/refresh | 刷新令牌 | - |
| POST | /api/v1/auth/logout | 登出 | ✅ |
| PUT  | /api/v1/auth/password | 修改密码 | ✅ |
| GET  | /api/v1/auth/me | 当前用户 | ✅ |
| POST | /api/v1/spaces | 创建空间 | ✅ |
| GET  | /api/v1/spaces/mine | 我的空间列表 | ✅ |
| PUT  | /api/v1/spaces/{id} | 修改空间 | space_admin+ |
| POST | /api/v1/spaces/{id}/members | 邀请成员 | space_admin+ |
| GET  | /api/v1/spaces/{id}/members | 成员列表 | ✅ |
| DELETE | /api/v1/spaces/{id}/members/{uid} | 移除成员 | space_admin+ |
| POST | /api/v1/tasks | 创建任务（异步由引擎执行） | ✅ + X-Space-Id |
| GET  | /api/v1/tasks | 任务分页 | ✅ + X-Space-Id |
| GET  | /api/v1/tasks/{id} | 任务详情 | ✅ + X-Space-Id |
| POST | /api/v1/tasks/{id}/control | interrupt/resume | ✅ |
| GET  | /api/v1/tasks/{id}/log | 步骤回溯 | ✅ |
| GET  | /sse/tasks/{id} | SSE 流式执行 | ✅ |
| GET  | /api/v1/knowledge | 知识分页 | ✅ + X-Space-Id |
| GET  | /api/v1/knowledge/{id} | 知识详情 | ✅ |
| PUT  | /api/v1/knowledge/{id} | 修改 | ✅ |
| DELETE | /api/v1/knowledge/{id} | 软删除 | ✅ |
| POST | /api/v1/knowledge/search | 混合检索 | ✅ |
| GET  | /api/v1/knowledge/tags | 标签 | ✅ |
| GET  | /api/v1/knowledge/categories | 分类 | ✅ |
| GET  | /api/v1/stats/overview | 工作台首页 | ✅ |
| GET  | /api/v1/stats/agents | Agent 画像 | ✅ |
| GET  | /api/v1/stats/recent-tasks | 最近任务 | ✅ |
| GET  | /api/v1/stats/tasks/{id}/replay | 链路回溯 | ✅ |
| POST/GET | /api/v1/repositories | 仓库接入与列表 | ✅ + X-Space-Id |
| POST/GET | /api/v1/task-runs | 工程任务运行创建与列表 | ✅ + X-Space-Id |
| GET | /api/v1/tasks/{id}/events | 可回放 SSE（支持 Last-Event-ID） | ✅ + X-Space-Id |
| GET | /api/v1/tasks/{id}/approvals | 审批记录 | ✅ + X-Space-Id |
| POST | /api/v1/approvals/{id}/decision | 批准/拒绝高风险操作 | ✅ + X-Space-Id |
| POST | /api/v1/tasks/{id}/interrupt | 中断运行 | ✅ + X-Space-Id |
| POST | /api/v1/tasks/{id}/resume | 从中断状态恢复 | ✅ + X-Space-Id |
| GET | /api/v1/tasks/{id}/diff | 统一 diff 与验证状态 | ✅ + X-Space-Id |
| GET/POST | /api/v1/tasks/{id}/artifacts | 测试报告、日志、数据集等制品 | ✅ + X-Space-Id |
| GET/POST | /api/v1/tasks/{id}/steps | Planner/Tester 等运行步骤 | ✅ + X-Space-Id |
| GET/POST | /api/v1/tasks/{id}/tool-invocations | 结构化工具结果 | ✅ + X-Space-Id |
| GET/POST | /api/v1/workflows | 版本化工作流 DSL | ✅ + X-Space-Id |
| GET/POST | /api/v1/agents | Agent 定义及工具白名单 | ✅ + X-Space-Id |
| GET | /api/v1/tools | 内置工具与统一结果契约 | ✅ |
| GET/POST | /api/v1/models | OpenAI-compatible 模型配置 | ✅ + X-Space-Id |
| GET/POST | /api/v1/evaluations | 固定数据集评测运行 | ✅ + X-Space-Id |
| GET/POST | /api/v1/fine-tunes | LoRA 微调作业元数据 | ✅ + X-Space-Id |
| GET | /api/v1/knowledge/graph | 实体、关系与证据链 | ✅ + X-Space-Id |

> 凡 `✅ + X-Space-Id` 均要求 Header `X-Space-Id: <space_id>`，由 `get_space_id` 依赖解析；内存隔离由 DAO 强制过滤 `space_id` 实现。

## 四、统一响应体

所有接口返回结构固定：
```json
{ "code": 0, "message": "ok", "data": <any>, "trace_id": "..." }
```
- `code`: 0 表示成功；非 0 即 `ErrorCode`（详见 `app/core/error_codes.py`）
- `trace_id`: 由 `X-Trace-Id` 中间件注入；HTTP 响应头 `X-Trace-Id`、`X-Duration-Ms` 同步附录

## 五、错误码速查

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 99xxxx | 系统级（参数 / 限流 / DB / Redis） |
| 10xxxx | 认证 |
| 11xxxx | 用户 |
| 12xxxx | 空间 |
| 13xxxx | 任务 |
| 14xxxx | 执行引擎 |
| 15xxxx | 知识 |
| 16xxxx | 工具 |

## 六、调试指南与常见异常排查

| 现象 | 可能原因 | 排查 |
|------|----------|------|
| `/api/v1/auth/me` 401 | access token 过期或已黑名单 | 调 `/api/v1/auth/refresh` |
| 登录 `100007 AUTH_USER_LOCKED` | 15 min 内连续失败 5+ 次 | 等 15 min 或运营清 `auth:lock:*` |
| 接口 429 | 限流计数命中 | Redis `ratelimit:*` 查计数；联系管理员调整 RATE_LIMIT_* |
| `X-Space-Id` 缺失 | 业务接口未带空间头 | 客户端补 Header |
| SSE 一直无事件 | Nginx 缓冲未关闭 | 校验 Nginx 配置 `proxy_buffering off`（见 GOAL-05） |
| Chroma 检索为空 | 向量库未启动或连接超时 | 后端日志降级提示；接口仍可走关键词检索 |
| Alembic 报 `target_metadata empty` | 未 import 模型 | `alembic env.py` 已 `import app.model.*` |
| `task_state_set` 写不进 | Redis 不通 | 检查 `REDIS_HOST/PORT`；任务运行态降级 |
| 502 / 504 | 后端进程崩溃或超时 | `docker logs backend` 查看 trace；前端走 `/health` 接口探活 |
| JOIN 报 `Not implemented for SQLite` | 单测使用 SQLite，不适合联合查询 | 单测中避开 JOIN，使用子查询或单独的 fixture |

## 七、MetaGPT 六模式集成点

| 模式 | 文件 | 关键 API |
|------|------|----------|
| Role | `app/roles/base_role.py` | `BaseRole._think/_act/_observe/run` |
| Team | `app/teams/team.py` | `Team.hire/disband/run` |
| Environment | `app/environments/environment.py` | publish/subscribe 路由 |
| Memory | `app/memory/memory.py` | 长期 + 工作记忆 + 向量检索 |
| Plan/Task | `app/plans/task.py` | 拓扑排序 + 依赖管理 + current_task |
| Tool | （GOAL-06） | `ToolRegistry / @register_tool / ToolRecommender` |

## 八、单测运行

```bash
pytest -v
```

已编写覆盖：
- 认证：注册/登录/重复用户名/me 鉴权/失败登录
- 任务状态机：正向流转 / 终态约束 / resume
- Plan 拓扑：线性链 / 循环依赖抛错 / prefix 合并
- Environment：`watch` 过滤 / Team.run 完整循环

## 九、字符集与时区

- MySQL 表统一 `utf8mb4`，模型 `String` 默认走 8.0 默认 collation
- 时区：业务时间统一 UTC；前端展示按用户本地
- JSON：默认 `orjson` 兜底；接口返回 `ensure_ascii=False` 以正确展示中文

## 十、与执行引擎的接入方式

业务层通过依赖注入取得 `AbstractExecutionEngine`。未配置远程 Worker 时使用可测试的进程内生命周期适配器；部署环境可调用 `register_engine()` 绑定 LangGraph Worker 适配器：
- 任务创建 → `engine.submit(task_id, goal, context)` 立即返回 execution_id
- 客户端订阅 `/api/v1/tasks/{task_id}/events`，事件写入 Redis Stream 并用游标回放
- 中断 → `engine.interrupt(execution_id)` + Redis 控制标志
- 续跑 → `engine.resume(execution_id)` 加载最近 checkpoint

测试配置使用内存事件存储；生产配置使用 Redis Streams，多个消费者互不争抢事件，并支持 `Last-Event-ID` 断线续传。
