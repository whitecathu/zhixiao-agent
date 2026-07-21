# 系统架构

智效工坊把控制面与执行面分开。Web/CLI 负责输入和审批，API 负责持久化与审计，Worker 调用 Agent Core，工具只在声明的 workspace 中运行。

```mermaid
flowchart LR
  U["Web / CLI / CI"] --> A["FastAPI control plane"]
  A --> DB[(MySQL)]
  A --> R[(Redis Streams)]
  R --> W["Worker"]
  W --> G["LangGraph runtime"]
  G --> T["Typed tool registry"]
  T --> L["Local runner"]
  T --> D["Docker runner"]
  G --> V["Chroma / Milvus"]
  G --> N["Neo4j"]
  G --> M["OpenAI-compatible models"]
  W --> R
  A --> U
```

## 执行状态机

```mermaid
flowchart TD
  I["intake"] --> X["discover repository"]
  X --> P["plan and route"]
  P --> Q{"approval required?"}
  Q -- yes --> H["interrupt / await approval"]
  H --> W["prepare isolated workspace"]
  Q -- no --> W
  W --> E["execute tool loop"]
  E --> V["verify tests and gates"]
  V --> F{"passed?"}
  F -- no --> R["review and repair"]
  R --> E
  F -- yes --> O["diff, artifacts, knowledge"]
```

`AgentRuntime` 使用正式 `StateGraph` 节点和 checkpointer；计划审批可中断并以同一 run id 恢复。控制面保存 TaskRun、RunStep、ToolInvocation、Approval 与 Artifact，Redis Stream 使用游标支持多消费者和断线续传。测试门禁或明确的“无法验证”记录是终态的必要证据。

## 模块职责

- `packages/agent_core`：状态机、任务路由、模型适配、权限、Runner、工具、项目指令、Skill、RAG、训练和 CLI/TUI。
- `apps/api`：认证、多租户空间、仓库/运行元数据、审批、事件订阅、工作流、Agent、模型、知识图谱和评测 API。
- `apps/worker`：消费任务队列，运行 Agent Core，将事件与结果写回控制面。
- `apps/web`：操作台和运行可视化，不直接访问数据库或 Runner。
- `infra`：独立镜像、Compose、Nginx SSE 配置、数据服务和健康检查。

## 数据与事件

MySQL 是业务记录的事实源；Redis Stream 是运行事件传输层；制品目录保存 diff、测试报告与日志索引。向量与图数据保存知识索引，答案必须携带来源引用。运行事件至少包含事件 id、类型、run id、序号、数据块与终态；客户端通过 `Last-Event-ID` 或 `cursor` 恢复。

## 扩展点

- WorkflowDefinition 是版本化 JSON DSL，可保存节点、边、条件、重试与审批规则。
- AgentDefinition 保存角色、Prompt 与工具白名单。
- ToolRegistry 统一类型化输入和 ToolResult 输出。
- ModelProfile 采用 OpenAI-compatible 协议，路由层负责超时、回退、成本与 A/B 选择。
- VectorStore 和 GraphStore 是异步抽象，支持内存测试适配器与外部后端。
