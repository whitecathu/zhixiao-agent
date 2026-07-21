# 智效工坊 - MetaGPT 架构模式应用说明

> 这是早期架构思路复盘。当前 Agent Core 已统一为正式 LangGraph `StateGraph`，实际模块与证据以 `packages/agent_core` 和 `docs/ACCEPTANCE.md` 为准。

> 输出时间：2026-07-19
> 范围：详细说明 MetaGPT 六大模式 + Skill 七模式在本项目中的落地映射，展示架构设计的深度

## 一、设计原则

本项目不直接 `import metagpt` 框架包，而是在本仓库自实现其角色 / 团队 / 环境 / 计划 / 记忆 / 工具 / 技能七大模式的轻量版本，原因有二：

1. **解耦**：MetaGPT 框架更新频繁，其内部 API 在版本间存在破坏性变更；自实现轻量版可保证业务与架构稳定。
2. **可演进**：保持"模式同构"的原则，业务层只依赖六模式抽象接口；后续如需接入 MetaGPT 官方实现或 LangGraph / AutoGen 替代方案，可平滑过渡。

## 二、七大模式在项目中的具体映射

### 2.1 Role（角色）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/roles/base_role.py`(后端) / `app/agents/base_agent.py`(AI 引擎) |
| 关键类 | `BaseRole` / `BaseAgent` |
| 生命周期 | `_think` → `_act` → `_observe` 三段式，外加 `run(message)` 总入口 |
| 子实现 | TaskDecomposer (≈ProductManager)、ResearchRetriever (≈Researcher)、ContentGenerator (≈Engineer/Writer)、QualityReviewer (≈Reviewer/QA) |
| 设计要点 | watch 列表决定该 Role 订阅谁的消息；tools 列表决定可用工具 |

### 2.2 Team（团队）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/teams/team.py` |
| 关键 API | `hire(roles) / disband(role_names) / run(task, max_iterations)` |
| 联动 Environment | 持有一个 `env: Environment` 实例；雇佣即 `add_role` |
| 联动 Memory | 任务循环每步写入 Memory；记忆可直接被后续 Role 检索 |
| 工作流编排 | AI 引擎侧 `WorkflowEngine.run` 是更细化的 Team 模式：固定状态机节点+边 |

### 2.3 Environment（环境）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/environments/environment.py` |
| 关键 API | `add_role / remove_role / publish_message / get_messages_for_role` |
| 路由规则 | 按 `watch` 列表过滤 `message_queue`，watch 为空表示收全部 |
| 消息体 | `Message{content,role,sent_from,cause_by,metadata}` |
| 工程意义 | Role 之间不直接函数调用，全部走 Environment 消息，松耦合便于异步调度与日志追溯 |

### 2.4 Memory（记忆）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/memory/memory.py` |
| 三种记忆 | 长期 (`messages`)、工作记忆 (`working`)、向量检索 (`chroma_collection`) |
| 关键 API | `add(message, working=True) / get_by_actions / search / clear_working` |
| 向量侧 | 写入 Chroma 失败仅降级（不阻塞主流程）；搜索时先 Chroma，无 Chroma 走关键词 |
| 业务意义 | 跨任务长期记忆让相似任务能复用历史子任务结果；工作记忆用于当前任务上下文 |

### 2.5 Plan/Task（计划/任务）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/plans/task.py` |
| 关键类 | `Task` / `Plan` |
| 关键 API | `add_tasks` 自动拓扑排序 + prefix 合并；`current_task` / `finish_current_task` |
| 单测覆盖 | 循环依赖抛错、线性链、prefix 合并 |
| 业务意义 | LangGraph 状态机对外仍以 Plan 表达；可断点续跑、可回溯 |

### 2.6 Tool（工具）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/tools/tool_registry.py` |
| 关键 API | `register_tool / has_tool / get_tool / get_tools_by_tag / validate_tool_names` |
| 装饰器 | `@register_tool(tags=...)` 自动注册到全局 `TOOL_REGISTRY` |
| 推荐系统 | `ToolRecommender.recommend_tools` 按 name / description / tags 三路加权 |
| Schema 自动生成 | `ast.parse` + docstring 拼出 OpenAI 兼容 function-call schema |
| 4 类内置工具 | knowledge_search / web_search / file_parse / data_calc |
| 双抽象共存 | 1) `BaseTool` 业务级 2) `@register_tool` 工程级；二者共享同一 Registry |

### 2.7 Skill（技能）模式
| 项 | 说明 |
|----|------|
| 实现位置 | `app/skills/skill_manager.py` |
| 关键类 | `SkillConfig / Skill / SkillManager` |
| 关键 API | `_load_skills / get_skill / list_skills / search_skills / render_prompt` |
| 目录约定 | `skills/<Name>/config.json + skprompt.txt` |
| Prompt 模板 | 支持 `{{$变量}}` 渲染 |
| 价值 | 业务团队可零代码贡献角色级能力（如"市场分析" / "技术选型"） |

#### 2.7.1 本项目内置 Skill 示例目录

```
zhixiao-ai/skills/
├── TaskDecomposer/{config.json, skprompt.txt}
├── ContentGenerator/{config.json, skprompt.txt}
├── QualityReviewer/{config.json, skprompt.txt}
└── KnowledgeExtractor/{config.json, skprompt.txt}
```

## 三、模式相互调用关系图（文字版）

```
                 ┌────────── SkillManager ───────────┐
                 ↓                                    │ (购买模板)
            ┌── BaseAgent ──┐                          │
            │   (Role)       │                          │
            └───┬────────────┘                          │
        _think / _act / _observe	                    │
                │                                       │
   subscribes  │ publish         registers               │
        ┌──────▼──────┐  ┌──────────────┐  ┌────────────┴───┐
        │ Environment │  │  Team.run    │  │ ToolRegistry   │
        └─────────────┘  └──────┬───────┘  └────────────────┘
                                │  schedules
                                ▼
                          ┌──────────┐    uses
                          │   Plan   │──────▶ tools from ToolRegistry
                          └────┬─────┘
                               │ drives
                               ▼
                         Memory (long-term + working + vector)
                               │
                               ▼
                         Chroma / Milvus 检索
```

## 四、一个完整任务在六模式下的运行轨迹

1. 用户任务 → Team.run 入 Environment 发布 UserRequirement 消息
2. TaskDecomposer Role 观察到 incoming → `_think` 决定拆解 → `_act` 输出 SubTask 写入 **Plan**
3. ResearchRetriever 通过 Environment 看到 TaskDecomposer 输出 → 调用 **ToolRegistry** 推荐工具
   - knowledge_search → 走 **Memory.collection** 语义检索
4. ContentGenerator 拿 materials 流式生成 → emit token；通过 Environment 给 QualityReviewer 发 ContentReady
5. QualityReviewer 决定 passOrFail；若 fail，触发 ContentGenerator **Skill.partial_rewrite**，仅针对 issue 区域改写
6. 任务 done → KnowledgeExtractor **Skill** 调度 → 输出四类知识入库；usage_count 起步

## 五、设计模式回归映射

| 设计模式 | 在本项目对应位置 |
|---------|------------------|
| Strategy | 4 Agent 选择不同 system_prompt + tools |
| Template Method | BaseAgent.run = observe → think → act |
| Observer | Environment.publish/subscribe |
| Chain of Responsibility | 状态机节点按 watch 接力 |
| Command | ToolRegistry 入队的 ToolAction |
| Decorator | `@register_tool` 装饰器 |
| Registry | ToolRegistry / SkillManager / AgentRegistry |
| Memento | LangGraph checkpointer 区域存 GraphState |
| Adapter | VectorStore 抽象 Chroma↔Milvus |

## 六、效果与未来兼容

- 当前实现由自动化测试覆盖六类协作模式；代码规模不作为质量指标
- 后续若需迁移到 MetaGPT / LangGraph/AutoGen 主流实现，仅需替换 AbstractExecutionEngine 内部实现
- SkillManager + ToolRegistry 形成"扩展面板"，新业务模块不需要直接修改核心引擎

## 七、小结

通过自实现 MetaGPT 六大模式 + Skill 系统，本项目达成了：
- 多 Agent 协同的清晰边界与可演进性
- 工程级 RAG 业务而非"玩具"
- 秒级骨干 + 长期可维护
- 团队扩展贡献技能的可持续路径
