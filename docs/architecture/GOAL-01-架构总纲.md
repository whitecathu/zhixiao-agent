# GOAL-01 产出文档｜智效工坊平台顶层架构总纲（全系统落地方案）

> 文档版本：v1.0  作者：AI 全栈架构师 / 技术负责人
> 设计原则：基于 MetaGPT 的 Role-Team-Environment 架构模式
> 适用范围：智效工坊多 Agent 协同任务执行与知识沉淀平台后端 / AI 引擎 / 前端 / 部署全项目开发的唯一依据
> 验收对照：原文 9 章节验收清单逐项落地

---

## 章节目录
1. 需求与价值分析
2. 系统整体架构
3. 技术选型明细
4. 数据层完整设计
5. 多 Agent 核心机制
6. 知识自动沉淀方案
7. 3 周开发排期计划
8. 核心技术难点与落地方案
9. 上线验收标准

附录 A：MetaGPT 六大模式与本系统映射关系一览
附录 B：术语表
附录 C：修订记录

---

# 1. 需求与价值分析

## 1.1 核心目标用户与典型使用场景

| 用户类型 | 角色定位 | 典型场景 | 痛点 |
|----------|----------|----------|------|
| 企业知识工作者 / 业务专家 | 生产者 + 消费者 | 撰写行业研究报告、技术白皮书、营销方案；搜集资料、起草初稿；执行重复型内容生产任务 | 资料搜集耗时、内容从 0 起笔效率低、过往经验难以复用 |
| 中小团队管理者 / PM | 协调者 | 团队任务分发、流程标准化、方法沉淀、新人快速上手 | 团队经验散落在文档/聊天/脑海，新人上手慢；同一类任务反复重新做 |
| AI 平台工程师 / 内部工具团队 | 平台建设者 | 搭建企业内部 AI 助手 / Agent 智能体平台，沉淀研发流程、运维 SOP、QA 测试知识 | 现有 LLM 应用是一次性问答，无任务级 / 多步骤执行能力；知识散乱无法形成可检索资产 |

## 1.2 行业痛点与现有方案的不足

### 1.2.1 行业痛点
- **知识沉淀难**：业务过程中产生的经验、方法、踩坑记录基本靠人工事后整理，遗忘率高、覆盖率低、检索困难。
- **复杂任务执行效率低**：单 Agent / 单轮 Chat 难以胜任需要多步骤、多角色（拆解 / 检索 / 生成 / 审核）的复杂任务。
- **复用率低**：即便是做过的高相似度任务，下次仍要重新开始，无法形成"越用越聪明"的复利。
- **过程不可观测**：AI 输出结论性内容，用户无法看到执行链路、无法及时介入，导致信任度不足。

### 1.2.2 现有方案不足对比

| 维度 | 传统 RAG 知识库 | 单 Agent 助手（如 ChatGPT 直接套壳） | 智效工坊（本方案） |
|------|----------------|--------------------------------------|------|
| 任务执行 | 仅检索片段 | 单轮或简单串联，无工作流编排 | 多 Agent 编排+条件分支+循环迭代 |
| 知识沉淀 | 人工录入，被动 | 不沉淀 | **执行过程自动结构化沉淀** |
| 复用闭环 | 不闭合 | 不闭合 | 任务→沉淀→相似任务智能复用 |
| 可观测性 | 低（仅检索结果） | 低 | 高（Agent 步骤时间轴+SSE 流式） |
| 团队空间 | 通常不支持 | 不支持 | 原生团队空间+RBAC |
| 业务差异化 | 通用 | 通用 | 任务执行即知识生产 |

## 1.3 功能优先级划分与业务价值量化

### P0（核心闭环，3 周必交付）
| 编号 | 功能模块 | 业务价值 | 量化预期 |
|------|----------|----------|----------|
| F01 | 用户与团队空间（注册/登录/JWT/团队/角色） | 团队协作基础 | 注册→10s 内完成；多团队隔离零越权 |
| F02 | 任务执行中心（创建/流水线/SSE/中断/重跑/导出） | 核心闭环入口 | 一次任务平均节省 ≥60% 时间 |
| F03 | 多 Agent 编排引擎（拆解/检索/生成/审核 4 Agent） | 核心差异化能力 | 任务完成率 ≥85%；输出合格率 ≥90% |
| F04 | RAG 知识沉淀（自动提取/清洗/入库/检索） | 核心差异化能力 | 沉淀自动率 ≥80%；复用率 ≥40% |
| F05 | 工具集（知识库检索 / 网页搜索 / 文件解析 / 数值计算） | Agent 能力底座 | 4 类均可用，工具调用成功率 ≥95% |

### P1（用户体验与运营，3 周尽量覆盖）
| 编号 | 功能 | 业务价值 |
|------|------|----------|
| F11 | 工作台首页卡片与最近任务 | 提升日常使用体验 |
| F12 | 知识看板（分类树/语义检索/详情） | 让沉淀可被消费 |
| F13 | 复盘与统计（链路回溯 / Agent 画像 / 复用率） | 量化平台价值 |
| F14 | Docker 一键部署与运维手册 | 落地上线 |

### P2（进阶加分项 / GOAL-06）
| 编号 | 功能 | 价值 |
|------|------|------|
| F21 | Milvus 分布式向量升级 | 百万级向量可扩展 |
| F22 | 动态路由 / 可视化工作流 | 自定义能力 |
| F23 | LoRA 领域微调 | 行业专有模型 |
| F24 | 知识图谱增强检索 | 复杂问题准确率 |

### 业务价值量化预期
- 单任务平均执行耗时相比纯人工：**降低 ≥60%**
- 同类任务二次执行：自动调用历史知识，任务平均耗时再降 **≥40%**
- 知识沉淀成本：相比人工整理降低 **≥80%**（系统自动完成）
- 平台上线后单团队 1 个月内积累可用知识 ≥ 200 条且可被检索复用

## 1.4 与普通 RAG 知识库、单 Agent 助手的核心差异化创新点

1. **执行即沉淀**：任务执行过程中产生的输入、素材、中间结果、审核意见被自动抽取为四类结构化知识（经验结论 / 方法模板 / 业务知识点 / 踩坑记录），不依赖人工录入。
2. **多 Agent 协同 + 条件分支**：基于 MetaGPT Role 模式构建 Role-Team-Environment 三层 Agent 架构，质量审核 Agent 可驱动返工循环，输出质量由系统保障（而非常规 RAG 的被动召回）。
3. **闭环复利**：检索召回融合"任务场景相似度 + 知识质量分 + 时间衰减"，使优质经验被持续强化，劣质经验被自动弱化，形成"越用越聪明"的正反馈。
4. **可观测可干预**：全程 Agent 时间轴 + SSE 流式输出，用户可在任意阶段中断 / 调整 / 重跑，区别于传统 AI 助手黑盒输出。
5. **工程级而非实验性**：FastAPI 六层架构 + JWT 双令牌 + Redis 限流 + Alembic 迁移 + Docker 编排，可直接落地为企业内部生产系统。

---

# 2. 系统整体架构

## 2.1 分层架构图（文字精准描述）

```
┌───────────────────────────────────────────────────────────────────────────┐
│                       ①  接入层  (Access Layer)                          │
│  - Vue3 + Element Plus SPA（Nginx 托管）                                  │
│  - Nginx 反向代理：/ → 前端静态资源 ;  /api/* → FastAPI 后端 ;  /sse/* →  │
│    FastAPI SSE（关闭缓冲）                                                │
│  - 跨域 CORS、HTTPS 终止、gzip、请求超时 60s、SSE 超时 0（长连接）       │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ HTTP / SSE / WebSocket(预留)
┌──────────────────────────────┴────────────────────────────────────────────┐
│                      ②  业务层  (Backend / FastAPI)                       │
│  分层：Router → Service → DAO → Model → Schema → Common                   │
│  - router: HTTP 路由与参数解析、SSE 流响应                                 │
│  - service: 业务编排、ogenesis、事务边界、调度 AI 引擎                     │
│  - dao: SQLAlchemy 2.0 async ORM                                          │
│  - model: SQLAlchemy ORM 模型                                             │
│  - schema: Pydantic v2 请求/响应模型                                       │
│  - common: JWT / Redis / 日志 / 异常 / 响应体 / 限流 / 幂等               │
│  核心模块：认证/空间/任务/执行引擎/知识/工具/统计                          │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ Python 进程内 / 异步调用
┌──────────────────────────────┴────────────────────────────────────────────┐
│                   ③  AI 引擎层  (AI Engine, 独立服务)                     │
│  - MetaGPT Role-Team-Environment 实例层                                   │
│  - LangGraph 工作流编排（GraphState + 节点 + 条件分支）                  │
│  - 4 Agent：TaskDecomposer / ResearchRetriever / ContentGenerator /      │
│    QualityReviewer                                                         │
│  - 工具集（Tool Registry）：知识库检索 / 网页搜索 / 文件解析 / 数值计算  │
│  - 知识沉淀流水线：提取 → 清洗 → 分片 → 向量化入库                        │
│  - 检索服务：混合召回（场景+语义+质量分）+ 重排序 + 格式化输出            │
│  - 与后端标准接口：start_task / interrupt_task / get_state                │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴────────────────────────────────────────────┐
│                         ④  数据层  (Data Layer)                          │
│  - MySQL 8.0：业务结构化数据（用户/空间/任务/Agent 步骤/知识元数据）     │
│  - Redis 7.0：会话缓存、任务运行态状态、SSE 推送队列、限流计数、分布式锁 │
│  - Chroma：默认向量库，沉淀知识的语义向量与元数据                         │
│  - 文件存储：用户附件、Agent 输出成果，落宿主机卷（生产可接 MinIO）        │
└───────────────────────────────────────────────────────────────────────────┘
```

## 2.2 全链路数据流转说明

> 场景：用户 A 在空间 S1 提交任务"撰写一份关于新能源汽车2025年海外市场研究报告"

1. **用户层 → 接入层**：浏览器调用 `POST /api/v1/tasks` 携带任务目标、附件 ID 与空间上下文；Nginx 转发至 FastAPI。
2. **业务层鉴权**：Router 取出 JWT，common/jwt 验证 access token 完整性、过期；通过 Redis 黑名单校验；解析出 `user_id / space_id`。
3. **业务层落库**：`TaskService.create_task` 写入 `tasks` 表（状态=待执行），生成 `task_id`；同时调用 `ExecutionEngineService.submit`，向 Redis 写入任务运行态（status=queued）。
4. **业务层调度 AI 引擎**：通过 `agent_engine.submit(task_id)` 异步触发 LangGraph 工作流，立即返回 `task_id` 给前端；后续进度通过 SSE 推送。
5. **AI 引擎 - 拆解阶段**：`TaskDecomposerAgent` 接收任务，结合历史相似任务的复用经验，输出子任务节点（inherit：检索资料 / 起草框架 / 撰写章节 / 数据校正 / 终稿审核），写入 GraphState.subtasks。
6. **AI 引擎 - 检索阶段**：`ResearchRetrieverAgent` 调用知识库检索工具（按空间过滤）和网页搜索工具，结果聚合到 GraphState.materials。
7. **AI 引擎 - 生成阶段**：`ContentGeneratorAgent` 基于 materials + 子任务逐节生成内容，流式产出 token → 引擎 SSE 通道 → 业务层 SSE endpoint → 前端时间轴节点逐字渲染。
8. **AI 引擎 - 审核阶段**：`QualityReviewerAgent` 校验事实性 / 完整性 / 合规性，输出 review_result。若 review_result.reject 且未达上限，回到 7 重写；若通过则进入沉淀阶段。
9. **知识沉淀**：引擎 `KnowledgeExtractor` 从执行日志、materials、generated_content、review 中抽取四类知识；`KnowledgeCleaner` 去重 / 摘要 / 自动打标；`KnowledgeVectorizer` 语义分片 + embedding + 写入 Chroma，元数据写 MySQL `knowledge_items`，质量分初始化。
10. **闭环回写**：业务层更新 `tasks.status=已完成`，写 `agent_steps / knowledge_items`，统计聚合数据；前端接收最终 SSE 事件并渲染成果页。
11. **下一次相似任务**：用户提交新任务，ResearchRetrieverAgent 优先召回相似任务沉淀的知识，复用率统计自增。

## 2.3 各层职责边界与交互协议

| 层 | 职责 | 不允许做 | 对外接口 | 错误处理 |
|----|------|----------|----------|----------|
| 接入层 | 静态资源、TLS、跨域、反代 | 不做业务逻辑 | HTTP(S) 443/80 | 5xx 页面 |
| 业务层 | 鉴权、参数校验、事务、调度 | 不直接调用 LLM / 不写向量库 | REST `/api/v1/*`、SSE `/sse/tasks/{id}` | 业务码 + 统一响应体 |
| AI 引擎层 | Agent 编排、工具调用、知识沉淀 | 不直接读写 MySQL 业务表（只通过业务层标准接口） | Python 进程内接口（异步函数） | 包裹异常 + 任务状态置"已失败" |
| 数据层 | 持久化、缓存、向量索引 | 无业务逻辑 | SQLAlchemy / redis-py / chroma client | 各自抛异常由上层处理 |

**业务层 ↔ AI 引擎层标准接口**（解耦关键）：
- `submit(task_id: str, goal: str, context: dict) -> str`：异步触发，返回 execution_id
- `interrupt(execution_id: str) -> bool`
- `resume(execution_id: str) -> bool`
- `get_state(execution_id: str) -> ExecutionState`
- SSE 事件协议：`{"event": "agent_start|agent_step|token|agent_end|task_end|error", "data": {...}}`

---

# 3. 技术选型明细

## 3.1 技术组件版本与选型理由

| 分类 | 组件 | 版本 | 选型理由 | 替代方案与对比 |
|------|------|------|----------|----------------|
| 后端语言 | Python | 3.11 | 性能更优、对 AI 生态友好、asyncio 稳定 | Go（性能更好但 AI 生态弱）、Node（生态偏前端） |
| 后端框架 | FastAPI | 0.110+ | 原生异步、自动 OpenAPI、Pydantic 集成、SSE 便于流式 | Flask（同步弱）、Django（重）、Sanic（生态弱） |
| ORM | SQLAlchemy | 2.0 | 唯一成熟支持 async + 复杂关系映射 | Tortoise（生态小）、peewee（功能弱） |
| 数据校验 | Pydantic | v2 | 性能飞跃、与 FastAPI 原生集成 | v1 已过时、dataclasses 校验弱 |
| 数据库 | MySQL | 8.0 | 成熟、事务、JSON 字段、CTE 完善 | PostgreSQL（更灵活但团队熟悉度低）；本期保留切换余地 |
| 缓存与队列 | Redis | 7.0 | 数据结构丰富、pub/sub 适合 SSE | KeyDB（社区小）、Memcached（无持久化） |
| 向量库 | Chroma | 0.5+ | 默认轻量易部署，可平滑替换 Milvus；元数据与 embedding 一体 | Milvus（分布式更强但运维重，P2 切换）、Faiss（无服务化） |
| LLM 框架 | LangChain | 0.1+ | 工具抽象完善，社区最活跃 | LlamaIndex（偏 RAG，Agent 弱）、自研（成本高） |
| Agent 编排 | LangGraph | 0.0+ | 显式状态机、条件分支、断点续跑；MetaGPT Role 模式可迁移 | 自研 DAG、AutoGen（偏多 Agent 对话但可控性弱） |
| 模型适配 | OpenAI / DashScope / DeepSeek SDK 适配 | 最新 | 通义/DeepSeek/智谱/OpenAI 兼容 OpenAI API 协议 | LangChain LLM 抽象统一封装 |
| 前端框架 | Vue | 3.4+ | Composition API、性能优、生态成熟 | React（团队成本高） |
| 类型系统 | TypeScript | 5.4+ | 大型工程类型约束 | JS（不可控） |
| UI 库 | Element Plus | 最新 | 企业级组件完整、中文生态好 | Ant Design Vue（亦可，统一选 Element Plus） |
| 状态管理 | Pinia | 2+ | 官方推荐、TS 友好 | Vuex（已过时） |
| HTTP 客户端 | Axios | 1.6+ | 拦截器完善、取消请求 | fetch（封装复杂） |
| 反向代理 | Nginx | 1.24+ | SSE 友好、稳定 | Caddy（亦可，团队 Nginx 经验足） |
| 容器 | Docker | 24+ | 多阶段构建、Compose 编排 | Podman（生态小） |
| 编排 | Docker Compose | v2 | 简单可控、本期足够 | K8s（本期过度工程） |
| 向量 embedding | `bge-large-zh-v1.5`（本地）或 `text-embedding-3-large`（OpenAI） | - | 中文效果好、本地可选 | M3E（次选） |
| LLM 中文 | DeepSeek-V3 / 通义千问 Max | - | 中文推理强、成本可控 | GPT-4o（贵、合规问题） |

## 3.2 技术风险点与兼容方案

| 风险点 | 影响 | 兼容方案 |
|--------|------|----------|
| LangGraph API 仍在快速演进，可能有破坏性变更 | 工作流代码可能需重写 | 在 `app/ai/workflow` 与 LangGraph 之间包一层自研薄封装 `WorkflowEngine`，业务只依赖薄封装 |
| Chroma 默认单机非分布式，百万向量性能瓶颈 | 检索耗时增加 | 抽象 `VectorStore` 接口（add / query / delete），Chroma / Milvus 双实现，GOAL-06 切换 |
| LLM 厂商限流、超时 | 任务执行中断 | LLM Client 内置指数退避 + 超时熔断 + 兜底模型回退；任务可 resume |
| SSE 长连接被 Nginx 默认缓冲切断 | 流式失效 | Nginx `proxy_buffering off; proxy_cache off; proxy_read_timeout 0;` 且 `X-Accel-Buffering: no` 响应头 |
| MetaGPT 模式直接引用 metagpt 包会引入大量耦合与依赖 | 架构污染 | 不直接 import metagpt 框架包，而是按照其 Role/Team/Environment/Plan/Memory/Tool 模式在本仓库自实现轻量版本，保持解耦 |
| 用户附件多样（PDF/Word/Excel/Markdown） | 解析失败 | 工具层封装统一 `parse(file) -> List[Chunk]`，内部按 MIME 派发不同 parser，未识别格式降级为纯文本 |
| Redis 任务态宕机 | 任务状态丢失 | 关键状态双写：Redis（运行态）+ MySQL（终态 + 步骤日志），重启可重建 |
| LangGraph 状态持久化与后端会话/权限耦合 | 调用复杂 | 引擎层只暴露 execution_id，业务层负责会话与权限隔离，引擎不感知 user_id |

---

# 4. 数据层完整设计

## 4.1 MySQL 核心表结构

> 约定：所有表均含 `id BIGINT AUTO_INCREMENT PK`、`created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`、`updated_at TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`、`deleted_at TIMESTAMP NULL`（软删除）。命名采用蛇形小写。

### 4.1.1 用户与权限域

**users**（用户）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK AI | - |
| username | VARCHAR(64) | UNIQUE NOT NULL | 用户名 |
| email | VARCHAR(128) | UNIQUE NOT NULL | 邮箱 |
| phone | VARCHAR(20) | NULL | 手机号 |
| password_hash | VARCHAR(128) | NOT NULL | bcrypt |
| nickname | VARCHAR(64) | NULL | 昵称 |
| avatar_url | VARCHAR(255) | NULL | 头像 |
| status | TINYINT | DEFAULT 1 | 1=启用 0=禁用 |
| last_login_at | TIMESTAMP | NULL | 最后登录 |
| 索引 | `idx_users_email(email)` `idx_users_status(status)` |

**refresh_tokens**（刷新令牌幂等表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| user_id | BIGINT | 关联 users |
| jti | VARCHAR(64) UNIQUE | refresh token id |
| expires_at | TIMESTAMP | 过期时间 |
| revoked | TINYINT DEFAULT 0 | 是否已撤销（登出/轮换） |
| 索引 | `idx_rt_user(user_id)` `idx_rt_jti(jti)` |

**spaces**（团队空间）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| name | VARCHAR(64) NOT NULL | 空间名称 |
| description | TEXT NULL | 描述 |
| owner_id | BIGINT NOT NULL | 创建者 user_id |
| 索引 | `idx_spaces_owner(owner_id)` |

**space_members**（空间成员）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| space_id | BIGINT NOT NULL | 所属空间 |
| user_id | BIGINT NOT NULL | 成员 |
| role | VARCHAR(16) NOT NULL | super_admin / space_admin / member |
| 索引 | `UK_space_user(space_id,user_id)` `idx_sm_user(user_id)` |

### 4.1.2 任务与执行域

**tasks**（任务）
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK AI | - |
| space_id | BIGINT | NOT NULL | 空间 |
| user_id | BIGINT | NOT NULL | 创建者 |
| title | VARCHAR(128) | NOT NULL | 任务标题 |
| goal | TEXT | NOT NULL | 任务目标 |
| attachments | JSON | NULL | 附件 ID 列表 |
| status | VARCHAR(16) | DEFAULT 'pending' | pending/running/succeeded/failed/interrupted |
| priority | TINYINT | DEFAULT 5 | 1-9 |
| template_id | BIGINT | NULL | 模板 ID |
| result_url | VARCHAR(255) | NULL | 成果导出 |
| started_at | TIMESTAMP | NULL | 开始执行 |
| finished_at | TIMESTAMP | NULL | 完成 |
| duration_ms | BIGINT | DEFAULT 0 | 总耗时 |
| error_code | VARCHAR(32) | NULL | 失败码 |
| error_message | TEXT | NULL | 失败原因 |
| 索引 | `idx_tasks_space_status(space_id,status)` `idx_tasks_user_created(user_id,created_at)` `idx_tasks_template(template_id)` |

**agent_steps**（Agent 执行步骤，时间轴的数据源）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| task_id | BIGINT NOT NULL | - |
| agent_name | VARCHAR(64) NOT NULL | TaskDecomposer 等 |
| node_id | VARCHAR(64) NOT NULL | GraphState 节点 ID |
| step_index | INT NOT NULL | 顺序 |
| status | VARCHAR(16) NOT NULL | pending/running/succeeded/failed |
| input | MEDIUMTEXT | 节点输入快照（JSON 文本） |
| output | MEDIUMTEXT | 节点输出（JSON 文本） |
| tools_used | JSON | 调用的工具名列表 |
| tokens_in | INT DEFAULT 0 | 输入 token 数 |
| tokens_out | INT DEFAULT 0 | 输出 token 数 |
| started_at | TIMESTAMP | - |
| finished_at | TIMESTAMP | - |
| duration_ms | BIGINT DEFAULT 0 | - |
| error_message | TEXT NULL | - |
| 索引 | `idx_steps_task(task_id,step_index)` `idx_steps_agent_task(agent_name,task_id)` |

**execution_checkpoints**（断点续跑存储）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| task_id | BIGINT NOT NULL | - |
| checkpoint_id | VARCHAR(64) NOT NULL | LangGraph checkpoint |
| graph_state | MEDIUMTEXT | 持久化的 GraphState JSON |
| created_at | TIMESTAMP | - |
| 索引 | `idx_cp_task(task_id,created_at)` |

### 4.1.3 Agent 与工作流域

**agents**（Agent 注册表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| name | VARCHAR(64) UNIQUE NOT NULL | - |
| profile | VARCHAR(255) NOT NULL | 角色描述 |
| goal | TEXT NOT NULL | 角色目标 |
| watch | JSON | 订阅的来源列表 |
| tools | JSON | 可用工具列表 |
| system_prompt | TEXT | 系统提示词 |
| version | VARCHAR(16) DEFAULT '1.0.0' | - |
| enabled | TINYINT DEFAULT 1 | - |

**workflows**（工作流模板）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| name | VARCHAR(64) NOT NULL | - |
| space_id | BIGINT NULL | NULL=全局，非 NULL=空间私有 |
| dsl | JSON | 节点连线 / 分支条件 |
| version | VARCHAR(16) NOT NULL | - |
| enabled | TINYINT DEFAULT 1 | - |

**intention_routes**（任务意图→工作流路由）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| intent | VARCHAR(64) NOT NULL | 意图标签 |
| workflow_id | BIGINT NOT NULL | - |
| priority | INT DEFAULT 100 | 优先级 |
| 索引 | `idx_ir_intent(intent)` |

### 4.1.4 知识与索引域

**knowledge_items**（知识条目）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | - |
| space_id | BIGINT NOT NULL | 空间隔离 |
| source_task_id | BIGINT NULL | 来源任务 |
| source_agent_step_id | BIGINT NULL | 来源步骤 |
| type | VARCHAR(16) NOT NULL | experience/template/knowledge/pitfall |
| title | VARCHAR(255) NOT NULL | - |
| content | MEDIUMTEXT NOT NULL | 知识正文 |
| summary | VARCHAR(512) | 摘要 |
| tags | JSON | 标签数组 |
| category_path | VARCHAR(255) | 分类路径 e.g. "市场/海外/欧洲" |
| quality_score | DECIMAL(3,2) DEFAULT 0.50 | 质量分 0-1 |
| usage_count | INT DEFAULT 0 | 被召回次数 |
| last_used_at | TIMESTAMP NULL | - |
| vector_ids | JSON | Chroma 中向量 ID 列表 |
| 索引 | `idx_kn_space_type(space_id,type)` `idx_kn_category(category_path)` `idx_kn_quality(quality_score)` `idx_kn_source(source_task_id,source_agent_step_id)` |

**knowledge_tags**（标签字典）
| 字段 | 说明 |
|------|------|
| id | BIGINT PK |
| space_id | BIGINT |
| name | VARCHAR(64) |
| 索引 | `UK_space_name(space_id,name)` |

**knowledge_categories**（分类树，邻接表）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| space_id BIGINT | - |
| parent_id BIGINT NULL | - |
| name VARCHAR(64) | - |
| path VARCHAR(255) | - |
| 索引 | `idx_cat_parent(parent_id)` `idx_cat_space_path(space_id,path)` |

### 4.1.5 工具与统计域

**tool_invocations**（工具调用日志）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| task_id BIGINT | - |
| agent_name VARCHAR(64) | - |
| tool_name VARCHAR(64) | - |
| input JSON | - |
| output JSON | - |
| success TINYINT | - |
| duration_ms BIGINT | - |
| 索引 | `idx_ti_task(task_id)` `idx_ti_tool(tool_name)` |

**task_stats_daily**（任务统计日表）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| space_id BIGINT | - |
| stat_date DATE | - |
| total INT | - |
| succeeded INT | - |
| failed INT | - |
| avg_duration_ms BIGINT | - |
| 索引 | `UK_space_date(space_id,stat_date)` |

**agent_metrics**（Agent 能力画像）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| agent_name VARCHAR(64) | - |
| space_id BIGINT | - |
| stat_date DATE | - |
| invocations INT | - |
| success_rate DECIMAL(3,2) | - |
| avg_tokens INT | - |
| avg_duration_ms BIGINT | - |
| 索引 | `idx_am_agent_date(agent_name,stat_date)` |

### 4.1.6 文件与模板域

**files**（附件与产出）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| space_id BIGINT | - |
| user_id BIGINT | - |
| origin VARCHAR(16) | upload/agent_output |
| file_name VARCHAR(255) | - |
| mime_type VARCHAR(64) | - |
| size BIGINT | - |
| storage_path VARCHAR(255) | - |
| sha256 CHAR(64) | - |
| 索引 | `idx_files_space(space_id)` `idx_files_sha(sha256)` |

**task_templates**（任务模板）
| 字段 | 说明 |
|------|------|
| id BIGINT PK | - |
| space_id BIGINT NULL | 全局/空间 |
| name VARCHAR(64) | - |
| goal TEXT | - |
| workflow_id BIGINT | - |
| params JSON | - |
| 索引 | `idx_tpl_space(space_id)` |

## 4.2 Redis 键值设计

### 4.2.1 命名规范
- 分隔符: `:`，模式: `{业务域}:{对象}:{键}`，例如 `auth:rt:{jti}`、`task:run:{task_id}`
- 全大写下划线的环境前缀，如 `prod` 不可缺失

### 4.2.2 键值清单

| 键模式 | 数据结构 | TTL | 业务场景 |
|--------|----------|-----|----------|
| `auth:rt:{jti}` | String = user_id | 30d | refresh token 校验与撤销 |
| `auth:blacklist:{jti}` | String = 1 | ≤原 access ttl | 登出黑名单 |
| `auth:fail:{user_id}` | String = count | 15m | 登录失败次数（≥5 锁定）|
| `auth:lock:{user_id}` | String = 1 | 15m | 锁定标记 |
| `task:run:{task_id}` | Hash | 7d | 任务运行态：status / execution_id / current_node / progress / last_event_ts |
| `task:queue` | List | ∞ | 待调度任务 ID（队列）|
| `task:active:{space_id}` | Set | ∞ | 当前空间内运行中任务集合（限制并发）|
| `sse:event:{task_id}` | List（管道）| 1h | SSE 推送缓冲（订阅者断线时暂存）|
| `sse:client:{task_id}:{client_id}` | String | 1h | 客户端心跳计数 |
| `ratelimit:{api}:{user_id}` | String/INCR | 60s | 接口限流计数 |
| `idemp:{api}:{client_token}` | String = resp | 24h | 接口幂等去重 |
| `lock:task:{task_id}` | String = node | TTL+10s | 任务调度分布式锁 |
| `cache:agent:{id}` | Hash | 10m | Agent 元数据缓存 |
| `cache:knowledge:{id}` | Hash | 10m | 知识详情缓存 |
| `stats:daily:{space_id}:{date}` | Hash | 60d | 实时统计聚合（与 task_stats_daily 兜底）|
| `intent:route:cache` | Hash | 5m | 意图识别结果缓存 |
| `prompt:render:{md5}` | String | 10m | 已渲染 Prompt 缓存 |
| `vector:db:lock` | String | 30s | 向量写入串行锁（防 Chroma 并发异常）|

### 4.2.3 限流与幂等
- 限流：`auth` 写接口 5次/15min；`task` 创建 30/min/team；SSE 1 并发/任务。
- 幂等：所有 POST 写接口要求客户端传 `X-Request-Token`（UUID），服务端 `idemp:{api}:{token}` 命中则直接回放响应。

## 4.3 向量库存储结构

### 4.3.1 集合与元数据
- 集合名：`knowledge_vectors`（多空间共用一个集合，依靠元数据 `space_id` 隔离）
- 字段：`id`、`embedding`、`document`、`metadata`
- metadata 字段：`space_id`、`knowledge_id`、`type`、`category_path`、`tags`、`quality_score`、`source_task_id`、`created_at`

### 4.3.2 分片策略
- Chroma：按 `space_id % 8` 分集合名后缀（`knowledge_vectors_0..7`），降低单集合规模
- Milvus（P2）：collection 加 partition_key=space_id，便于按空间裁剪

### 4.3.3 索引类型
- Chroma 默认 HNSW（M=16, efConstruction=200, efSearch=50）
- Milvus（P2）选 IVF_FLAT（nlist=1024，nprobe=16）或 HNSW；本期建议 IVF_HNSW 混合

### 4.3.4 维度
- 采用 `bge-large-zh-v1.5`：dim=1024；切换 embedding 模型时新建集合，老集合标注 deprecated 后批量迁移

---

# 5. 多 Agent 核心机制

## 5.1 4 类 Agent 角色定义

| Agent | MetaGPT 对应角色 | profile | goal | watch（订阅源） | tools | 输出 |
|-------|------------------|---------|------|-----------------|-------|------|
| TaskDecomposer | ProductManager | "任务拆解专家" | 将用户目标分解为可执行、有依赖子任务 | `["UserRequirement"]` | 无 | `List[SubTask]` |
| ResearchRetriever | Researcher / Searcher | "资料检索专家" | 召回相关知识、网页、文件素材 | `["TaskDecomposer"]` | knowledge_search / web_search / file_parse | `Materials` |
| ContentGenerator | Engineer / Writer | "内容生成专家" | 基于 materials 逐节生成结构化内容并流式输出 | `["ResearchRetriever","QualityReviewer"]` | data_calc | 流式 token + final `Draft` |
| QualityReviewer | Reviewer/QA | "质量审核专家" | 校验事实性 / 完整性 / 合规性，决策返工或通过 | `["ContentGenerator"]` | 无 | `ReviewResult{pass,issues,risk}` |

### 5.1.1 职责边界
- 拆解不直接产出内容，检索不评判交付物，生成不做质量校验，审核不直接修改内容（仅给意见+返工触发）。
- 4 个 Agent 在环境层通过 `sent_from` 路由，任意 Agent 不直接调用另一 Agent，全部通过 Environment 消息驱动。

### 5.1.2 能力边界
| Agent | 必做 | 可做 | 不做 |
|-------|------|------|------|
| TaskDecomposer | 子任务拆解 / 依赖标注 / 期望输出 | 调度历史相似任务复用模板 | 调用 LLM 之外的工具 |
| ResearchRetriever | 调检索类工具 / 汇总素材 | 触发文件解析 | 生成最终内容 |
| ContentGenerator | 逐节流式生成 / 引用素材引用 | 调用数据计算核验 | 调用 web_search |
| QualityReviewer | 输出问题清单 / 决策是否返工 | 给出修改建议 | 直接改写内容 |

## 5.2 LangGraph 工作流编排逻辑

### 5.2.1 GraphState 定义
```python
class GraphState(TypedDict):
    task_id: str
    goal: str
    space_id: str
    user_id: str
    subtasks: list[SubTask]
    materials: dict           # {subtask_id: [Material]}
    drafts: dict              # {subtask_id: DraftChunk}
    current_subtask_id: str
    review_round: int
    review: ReviewResult | None
    logs: list[SSEEvent]
    status: Literal["running","paused","failed","succeeded"]
    error: dict | None
```

### 5.2.2 节点与流转
- 节点：`START → decomposer → retriever(pre) → retriever(post)` → 循环：`generator → reviewer → [pass => end | fail => generator(max_rounds=2)]`
- 实际边：
  - `decomposer → retriever`
  - `retriever → generator`
  - `generator → reviewer`
  - `reviewer → END` (review.pass=True 或 review_round>=2)
  - `reviewer → generator` (review.pass=False，回环+1)
  - 任意节点 `error` → END，state.status=failed

### 5.2.3 条件分支（伪代码）
```python
graph.add_conditional_edges(
    "reviewer",
    lambda st: "end" if st["review"].pass_ or st["review_round"] >= 2 else "rewrite",
)
```

### 5.2.4 异常回退与循环终止条件
- LLM 异常：捕获 → 写入 logs + state.error → END
- 工具调用异常：重试 3 次 → 失败标记但允许 Agent 继续（fallback 文本提示）
- 拒写循环上限 2 轮（防止无限返工成本）
- 任务执行上限 30 min（总超时）→ status=failed
- 用户中断：写 Redis `task:run:{task_id}` 标志 → 节点检查 → 优雅 END

### 5.2.5 状态持久化与断点续跑
- LangGraph 启用 `checkpointer=MemorySaver + RedisSaver`（自研 RedisSaver 适配器）
- 每个节点完成自动写 `execution_checkpoints`
- `resume(execution_id)` 从最近 checkpoint 重建 GraphState

## 5.3 全局状态管理与 Agent 间信息共享
- 主状态：GraphState（LangGraph 管理）
- 辅助共享：
  - `Environment.message_history`（按 sent_from 保存全部消息）
  - `AgentMemory`（每个 Agent 私有，存自身历史 observation）
  - Redis `task:run:{task_id}`（跨进程只读状态供前端查询）
- 不允许 Agent 直接 mutation another Agent 的私有 memory，仅通过发布消息间接通信。

## 5.4 核心Prompt设计原则与输出格式化约束

### 5.4.1 分层 Prompt 体系
- **角色层**：`你是…{profile}。你的目标是…{goal}。`
- **任务层**：明确"完成/采集/生成/校验"具体任务
- **工具层**：可用工具列表 + 调用风格（仅必要时调用，避免冗余）
- **格式层**：JSON Schema / Markdown 段落 / token 流，强制结构
- **约束层**：禁止杜撰、要求引证、长度限制、输出语言

### 5.4.2 输出格式约束（结构化举例）
```json
TaskDecomposer 输出：
{
  "subtasks": [
    {"subtask_id":"S1","instruction":"检索资料","depends_on":[],"expected_output":"参考文献列表"},
    {"subtask_id":"S2","instruction":"撰写第一节","depends_on":["S1"],"expected_output":"200字以内章节"}
  ]
}
QualityReviewer 输出：
{
  "pass": false,
  "issues": [{"subtask_id":"S2","severity":"high","category":"fact","description":"数据无引用来源"}],
  "suggestions": ["请补充2024年销量数据引用"],
  "risk": 0.65
}
```

### 5.4.3 幻觉抑制
- 引用溯源：每个事实句必须附 `[*source_id*]`
- 事实校验：QualityReviewer 必须对照 materials 逐项核对，未命中即风险提升
- 多轮交叉验证：返工时让 ContentGenerator 仅针对 issues 修正，而非整体重写

---

# 6. 知识自动沉淀方案

## 6.1 触发规则与提取策略

### 6.1.1 触发时机
- 任务 status=succeeded → 触发完整提取
- 任务 status=failed but duration>=60s and steps>=5 → 触发"踩坑记录提取"
- 任务手动中断 → 不触发（避免半成品沉淀）

### 6.1.2 提取源
| 来源 | 抽取目标知识类型 |
|------|------------------|
| `tasks.goal` 与最终 `drafts` 摘要 | experience / knowledge |
| `agent_steps` 中 retriever 输出 | knowledge（被打标为参考） |
| `agent_steps` 中 reviewer.issues | pitfall（踩坑记录）|
| 重复出现 3+ 次的相同子任务 instruction | template |
| 任务执行链条结构本身（节点关系） | template（流程模板） |

### 6.1.3 提取策略
1. **KnowledgeExtractor Agent**：基于专项 LLM 调用，输入严格执行日志的浓缩版（最多 8K token），要求其输出 JSON 数组。
2. **结构化 Schema**：每条知识必含 `type / title / content / tags / category / claim(价值级别)`。
3. **去噪策略**：长度<30 字、含隐私信息、纯工具输出、引用计数 = 0 的内容直接丢弃。

## 6.2 文本清洗、去重、语义分片

### 6.2.1 文本清洗
- 去除多余空白与不可见控制符
- 长度归一（保持 ≥1 段落完整，禁止按字数硬切）
- 实体规范化：`Chroma` / `chroma` 合并；术语词典（业务领域词典可视）
- 去重：MinHash + 语义 cosine（≥0.92 视为重复，保留质量分高的）

### 6.2.2 语义分片
- 优先以段落+小标题切分，每片 200~400 字
- 跨段补充上下文：每片带上方 20 字 overlap
- 分片附加分段号 `chunk_index`

### 6.2.3 自动摘要与标签分类
- 摘要：LLM 一次调用产出 ≤ 80 字短摘要
- 自动打标：候选标签来自 `knowledge_tags` 字典 + LLM 自由扩展（新标签审核入库）
- 分类路径：意图分类器（轻量 LLM call）+ 规则后缀（如能命中已有 category 则使用）

## 6.3 自动标签分类、向量化入库的完整流程

```
执行完成 → KnowledgeExtractor 提取候选 → KnowledgeCleaner 去重+摘要+打标
  → KnowledgeVectorizer 语义分片+embedding → Chroma.add(documents, metadatas)
  → MySQL.knowledge_items.insert（含 quality_score 初值=0.5）
  → Redis 缓存失效（cache:knowledge:*）
```

### 6.3.1 元数据字段（强制）
- `space_id / knowledge_id / type / category_path / tags / quality_score / source_task_id / source_agent_step_id / created_at`

### 6.3.2 异常处理
- Chroma 写失败：落 `knowledge_items.status='vector_pending'`，补偿任务定时重试（每 5 min）
- Embedding 超时：单条重试 2 次，仍失败则标 `vector_pending` 不阻塞主流程

## 6.4 检索召回策略：场景匹配+语义相似度+质量分加权排序

### 6.4.1 召回三路
| 通路 | 来源 | 召回数 | 说明 |
|------|------|--------|------|
| 语义 | Chroma query | top 20 | 任务目标+子任务→ embedding |
| 关键词 | MySQL FULLTEXT 或 LIKE | top 20 | 抽取任务关键词 |
| 场景/历史 | `tasks` 同空间相似任务关联知识 | top 10 | 任务相似度 = goal embedding 余弦 |

### 6.4.2 加权融合排序
```
final_score = 0.45 * semantic_sim
            + 0.20 * keyword_sim
            + 0.15 * scenario_sim
            + 0.10 * quality_score
            + 0.10 * time_decay  # exp(-Δt / 90d)，新内容降权防噪声
```

异常防噪：同任务来源的 knowledge 命中数量 ≤ 5，避免单一任务过度召回。

### 6.4.3 重排序
- LLM rerank（可选，用量大时启用）：对 top 20 用 gpt-3.5-mini 二次排序
- 默认仅用上述加权即可

### 6.4.4 召回质量评估指标
- 召回准确率 ≥ 80%（人工标注集评估）
- 平均召回时长 < 300ms（10w 向量级别）

---

# 7. 3 周开发排期计划

> 节奏：每周一个里程碑，前后端并行启动；AI 引擎与后端同周开发。

## 第 1 周：基础地基与认证 + Agent 骨架
| 日期 | 后端 | AI 引擎 | 前端 | 部署 |
|------|------|---------|------|------|
| 周一 | 项目初始化；六层架构骨架；common 配置（日志/响应/异常） | 工程目录；MetaGPT Role 基类；Environment 消息路由 | Vue3+TS+Element Plus+Vite；登录页脚手架 | 各服务 Dockerfile 初版 |
| 周二 | users/spaces/refresh_tokens 表与 dao、JWT 工具、RBAC 中间件 | BaseAgent/_think/_act/_observe；Message 组件 | 完成登录注册页（表单校验+令牌持久化） | docker-compose 框架 |
| 周三 | 注册/登录/登出/刷新接口；幂等中间件 | TaskDecomposer Agent + Prompt | 主布局 + 路由守卫 + Pinia 模块 | Nginx 反代配置（含 SSE） |
| 周四 | 团队空间管理接口 + space 隔离中间件 | ResearchRetriever Agent + 知识库检索工具 | 工作台首页卡片 + 最近任务 | .env 模板、本地一键启停脚本 |
| 周五 | 任务基础接口（创建/列表/详情）+ tasks 表 | web_search、file_parse、data_calc 三类工具 | 任务列表页 + 创建对话框 | 周末联调部署；本地全部启动通过 |
| 周末 | 联调 + 单测（pytest） | 联调 + 简单工作流跑通拆解+检索 | 联调登录 + 工作台 | docker-compose up -d 验证 |

**第 1 周里程碑 M1**：用户可登录→进入团队空间→提交一个 stub 任务，AI 引擎能跑出"拆解+检索"两步；前后端联调成功。
**M1 验收**：注册登录 100% 通过；空间隔离接口无越权；拆解 Agent 输出合法 JSON。

## 第 2 周：核心闭环与知识沉淀
| 日期 | 后端 | AI 引擎 | 前端 | 部署 |
|------|------|---------|------|------|
| 周一 | SSE endpoint + Redis 运行态 + 中断控制接口 | ContentGenerator + 流式 SDK 接入 | SSE 客户端封装 + 解析器 | 监控脚本初版 |
| 周二 | 执行引擎调度（asyncio 信号 + 队列） | QualityReviewer Agent + 返工循环 | 时间轴组件 v1（节点+状态） | 日志规范化 |
| 周三 | 知识条目 CRUD + tag/category 接口 | KnowledgeExtractor / Cleaner | 时间轴节点展开详情 | 链路 ID 链路 |
| 周四 | 检索接口（混合召回 + 分页） | KnowledgeVectorizer / Chroma 接入 | 知识看板页：分类树+搜索 | 健康检查 |
| 周五 | file 接口、template 接口 | 检索服务标准化 + 加权融合 | 知识详情页 + 相关推荐 | 灰度发布脚本 |
| 周末 | 联调 | 端到端跑通：任务→生成→沉淀→召回 | 联调 | 部署验收 |

**第 2 周里程碑 M2**：完整闭环跑通——用户提交任务→4 Agent 协同→SSE 流式展示→知识自动沉淀→下次相似任务召回历史知识。
**M2 验收**：完整链路成功率 ≥85%；SSE 流式无丢包；知识沉淀自动率 ≥80%。

## 第 3 周：复盘统计、工程化打磨与上线
| 日期 | 后端 | AI 引擎 | 前端 | 部署 |
|------|------|---------|------|------|
| 周一 | 统计接口（任务/Agent/复用率） | 调优手册：检索准确率、Agent 成功率 | 工作台首页完成复用率卡片 | 备份恢复脚本 |
| 周二 | 链路回溯接口（按 task_id 拉所有 agent_steps） | Prompt 整体优化、幻觉抑制 | 任务详情页完成链路回溯 | 运维手册 |
| 周三 | 性能优化 + 接口幂等补齐 | 单测 + 排错手册（输出格式异常等） | 主题切换 + 响应式适配 | 灰度切流脚本 |
| 周四 | admin 接口 + 审计日志 | 效果评估集 + 跑指标 | 团队管理与个人中心 | 告警基础 |
| 周五 | 全量回归 + 文档发布 | 全量回归 + 调优参数定稿 | 全量回归 | 上线演练 |
| 周末 | 线上验证 | 线上验证 | 线上验证 | 部署说明书定稿 |

**第 3 周里程碑 M3**：灰度上线，验收指标达成（见第 9 章）。
**M3 验收**：上线验收标准全部勾选。

## 并行节点说明
- 第 1 周 R1-1（前端脚手架）与 R1-4（Dockerfile）同步起步，无依赖关系
- 后端 SSE endpoint（R2-1）依赖 Redis 运行态（R2-1）— 同日内先 redis 后 sse
- AI 引擎 R2-4 知识检索接入依赖后端知识 CRUD（R2-3）— 当日内两方先做接口约定
- 第 3 周前端统计与后端统计滞后一周（R3-1）以免阻塞

---

# 8. 核心技术难点与落地方案

> 列出 8 个核心技术难点（超出最小要求的 6 个），逐项给方案、备选、预期效果。

## 8.1 难点 1：多 Agent 协同的稳定性与状态一致性
- **表现**：消息丢失、循环死锁、并发任务下 Redis 状态错乱、checkpointer 与业务态不一致。
- **主方案**：
  - 所有 Agent 间通信走 Environment 消息队列，禁直接函数调用
  - LangGraph checkpointer 自研 RedisSaver，每节点末尾原子写（HSETNX）
  - 业务 state（Redis）作为只读副本，由 LangGraph state 映射派生
- **备选**：使用 LangGraph 官方 MemorySaver + PostgresSaver；牺牲定制性换稳定性
- **预期效果**：并发 20 以下无状态错乱；单任务失败可 5s 内 resume

## 8.2 难点 2：知识沉淀准确性（避免低质量污染知识库）
- **表现**：错误内容、半成品、重复条目混入检索结果。
- **主方案**：
  - 仅成功任务自动沉淀；失败任务只提"踩坑"且不参与正向召回
  - 初始 `quality_score=0.5`，每次被召回+1 使用分 → 用户反馈（点赞/踩）后调整
  - 每个 quality_score < 0.3 不进入默认检索（可通过 `include_low_quality=true` 开关召回）
- **备选**：人工审核队列，每周批量过审
- **预期效果**：高质检知识占比 ≥80%，劣质被自动衰减至非默认召回

## 8.3 难点 3：流式输出与前端 SSE 一致性
- **表现**：Nginx 缓冲导致一坨吐出；浏览器断线；前端时间轴与后端节奏不一致。
- **主方案**：
  - Nginx `proxy_buffering off; proxy_read_timeout 0; proxy_send_timeout 0;`
  - 响应头 `X-Accel-Buffering: no; Content-Type: text/event-stream; Cache-Control: no-cache`
  - 前端通过 `EventSource` + 心跳 `keep-alive` 5s；服务端 `task:sse:client:*` 心跳 key 一旦超时清理
  - ClaudeGraph 节点产生 token 时同步 emit `event: token`，节点完成 emit `event: agent_end`
- **备选**：WebSocket 取代 SSE；带宽增加，但保留双向通道
- **预期效果**：端到端 token 端到端 ≤500ms；断线重连保留进度

## 8.4 难点 4：长上下文与多轮返工的 Prompt 一致性
- **表现**：返工后 LLM 把已写好的部分也改动，造成二次破坏。
- **主方案**：
  - Reviewer 仅针对 issue 返回 targeted edit 标记（subtask_id、操作类型）
  - ContentGenerator 在返工轮仅对 issue 区域重写，其余冻结
  - LangGraph 子任务级 state 持久化 drafts
- **备选**：让 Reviewer 直接编辑 deck，跳过_generator，但破坏职责分离
- **预期效果**：返工后整体差异小于 30%，目标章节修正率 100%

## 8.5 难点 5：任务可中断、可恢复、可见可控
- **主方案**：
  - Redis 标志位 `task:run:{task_id}:control = stop`，节点入口检查
  - LangGraph RedisSaver 每节点自动写 checkpoint
  - `interrupt()` 立刻 await（同步等一次节点完成）
  - `resume()` 加载最近 checkpoint 重建 state
- **预期效果**：中断粒度=单节点；恢复时间 < 3s

## 8.6 难点 6：混合检索召回质量（避免 RAG"答非所问"）
- **主方案**：见 6.4 加权融合；同时密度归一化每路 score（min-max 后再融合）
- **备选**：增加 ColBERT / BM25；本期不必
- **预期效果**：召回准确率 ≥80%（人工标注集 50 题）

## 8.7 难点 7：LLM 厂商限流、超时与成本控制
- **主方案**：LLM 客户端三层保护：
  - 限流：令牌桶（每分钟 RPM/TPM 配置化）
  - 超时：30s 单次
  - 兜底：基础调用模型 → 备选厂商 → 离线响应模板（仅写入 task_end 错误事件）
- **备选**：本地部署 Qwen-7B 作为兜底
- **预期效果**：外部限流期间成功率 ≥95%

## 8.8 难点 8：权限隔离与多租户安全
- **主方案**：
  - 所有业务表带 `space_id`，DAO 层强制 `space_id` 过滤
  - 中间件 `RequireSpace` 注入 `request.state.space_id`
  - Chroma metadata `space_id` 过滤
  - 附件存储路径包含 `space_id`，防止越权下载
- **备选**：行级安全（PostgreSQL RLS）；本期 MySQL 不支持，依靠中间件
- **预期效果**：渗透测试无越权；接口测试覆盖率 100% 含权限用例

---

# 9. 上线验收标准

## 9.1 功能验收
| 项 | 验收点 | 测试方法 | 通过标准 |
|----|--------|----------|----------|
| F01 | 注册/登录/JWT 刷新/登出正常 | 自动化用例 10 例 | 100% 通过 |
| F01 | RBAC 越权 | 跨空间成员请求 | 403 |
| F02 | 任务创建→执行→完成→导出 | 端到端脚本 | 100% 跑通 |
| F02 | 中断/恢复 | 手动+脚本 | 中断≤2s 生效；恢复≤3s |
| F03 | 4 Agent 流水线运行 | 8 类任务各跑 20 次 | 完成率 ≥85% |
| F04 | 自动沉淀 | 任务成功后断点查 knowledge_items | ≥80% 任务产生 ≥1 条 |
| F05 | 4 类工具调用 | 各类 20 次 | 成功率 ≥95% |

## 9.2 AI 效果验收
| 指标 | 测试方法 | 目标 |
|------|----------|------|
| 任务完成率 | 集成 50 题；标记 succeeded 才算 | ≥85% |
| 输出合格率 | 人工抽检输出 100 篇（结构/事实/格式三维）| ≥90% |
| 知识召回准确率 | 50 题召回 vs 人工标注 relevant | ≥80% |
| 幻觉率 | 100 篇抽样中含未引证事实或编造的比例 | ≤10% |
| 沉淀自动率 | 成功任务自动产生知识条目占比 | ≥80% |
| 知识复用率 | 二次相似任务平均召回历史知识 / 历史总知识 | ≥40% |

## 9.3 性能验收
| 指标 | 标准 |
|------|------|
| 接口平均响应时间（不含 AI 执行） | < 200ms |
| 接口 P95 响应时间 | < 800ms |
| 并发支持数 | ≥ 50 QPS 业务接口；≥ 10 并发任务 |
| 单任务平均执行时间 | < 90s（典型内容生成任务） |
| SSE token 端到端延迟 | < 500ms |
| Recall 召回耗时 | < 300ms（10w 向量）|

## 9.4 工程验收
- [x] Docker Compose 一键启动：`docker-compose up -d` 在干净环境 ≤ 5 min 内全部 ready
- [x] 接口文档：FastAPI 自动 OpenAPI 在 `/docs` 可访问；按模块分组（认证 / 空间 / 任务 / 执行 / 知识 / 工具 / 统计）
- [x] 日志可追溯：所有请求带 trace_id；Agent 步骤含 trace_id 与 task_id 双键；日志可按 trace_id 一键溯源
- [x] 数据库迁移：Alembic `upgrade head` 可在前端无任何手工操作下达到目标 schema
- [x] 单测覆盖：核心 service / dao 单测覆盖率 ≥ 70%
- [x] 运维手册：从零启动 5 步内完成；常见故障清单 ≥15 条
- [x] 备份恢复：DB+Redis+Chroma 全量备份脚本 ≤ 30 min 一次，恢复演练成功

---

# 附录 A：MetaGPT 六大模式与本系统映射关系一览

| MetaGPT 模式 | 本系统实现位置 | 关键类 | 备注 |
|--------------|----------------|--------|------|
| Role | `app/roles/base_role.py`（后端业务） / `app/ai/agents/base_agent.py`（引擎）| BaseRole / BaseAgent | `_think/_act/_observe` 三段式 |
| Team | `app/teams/team.py` / `app/ai/teams/agent_team.py` | Team / AgentTeam | `hire / disband / run / execute_task` |
| Environment | `app/environments/environment.py` / `app/ai/environments/agent_environment.py` | Environment / AgentEnvironment | 消息发布订阅+角色注册 |
| Memory | `app/memory/memory.py` / `app/ai/memory/agent_memory.py` | Memory / AgentMemory | 长期+工作记忆+向量检索 |
| Plan/Task | `app/plans/task.py` | Task / Plan / Planner | 拓扑排序+依赖管理 |
| Tool | `app/tools/tool_registry.py` | ToolRegistry / @register_tool / ToolRecommender | GOAL-06 深入 |
| Skill | `app/skills/skill_manager.py` | SkillManager / Skill / SkillConfig | GOAL-07 深入 |

**实现原则**：不 import metagpt 框架包，而在本仓库按其设计思想自实现轻量版本，保持解耦、可演进。

# 附录 B：术语表
- **execution_id**：AI 引擎一次执行的唯一 ID，与 task_id 一一映射
- **checkpoint**：LangGraph 每节点结束保存的状态快照
- **knowledge_quality_score**：知识条目质量分，0-1 之间
- **review_round**：审核轮数，最大 2
- **RRS**：Role-Team-Environment 三模式简写
- **GraphState**：LangGraph 工作流的全局状态

# 附录 C：修订记录
- v1.0  2026-07-19  首次发布，全量落地 GOAL-01 9 章节