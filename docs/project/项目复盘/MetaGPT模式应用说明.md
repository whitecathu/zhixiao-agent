# 智效工坊 - MetaGPT 架构模式应用说明

> 更新：2026-07-25 — MetaGPT Role/Team 已抽取到 `packages/agent_core/src/zhixiao_agent/metagpt/`，
> Worker 支持 opt-in `engine=metagpt`（见 `metagpt_runtime.py`）。**默认执行面仍是 LangGraph `AgentRuntime`**。
> API 下 `app/roles` 等为 re-export，单元测试继续可用。

> 实际模块与证据以 `packages/agent_core` 和 `docs/ACCEPTANCE.md` 为准。

## 双引擎

| 引擎 | 入口 | 何时启用 |
|------|------|----------|
| LangGraph（默认） | `AgentRuntime.run` | `RunJob.engine=langgraph` 或缺省 |
| MetaGPT Team | `run_metagpt_team` | `engine=metagpt`；AgentDefinition.role ∈ {metagpt,team,metagpt_team} 或仓库 settings.engine |

两者共用 ToolRegistry、权限 flags，并发布兼容的 `run_started` / `model_turn` / `tool_result` / `workflow_node_*` / `run_finished` 事件，供 SSE 与实时执行图着色。

## 设计原则

本项目不直接 `import metagpt` 框架包，而是自实现轻量 Role / Team / Environment / Memory / Plan：

1. **解耦**：避免上游破坏性变更。
2. **可演进**：Worker 与 API 共享 `zhixiao_agent.metagpt`。

## 模块位置（现行）

| 模式 | 实现 |
|------|------|
| Role | `zhixiao_agent.metagpt.role` + `metagpt_runtime.LlmToolRole` |
| Team | `zhixiao_agent.metagpt.team` |
| Environment | `zhixiao_agent.metagpt.environment` |
| Memory | `zhixiao_agent.metagpt.memory` |
| Plan/Task | `zhixiao_agent.metagpt.plan` |
| Message | `zhixiao_agent.metagpt.message` |
| API 兼容层 | `apps/api/app/{roles,teams,environments,memory,plans}` re-export |

## v1 范围与非目标

**在范围内：** 单角色或短角色链、工具调用、SSE 事件、与 LangGraph 相同的权限模型。

**非目标（v1）：** Plan 拓扑驱动 Worker、Chroma 强依赖、与 LangGraph interrupt/checkpoint 对等的暂停恢复。
