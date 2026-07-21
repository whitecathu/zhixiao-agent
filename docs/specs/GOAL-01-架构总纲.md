# GOAL-01: 顶层架构总纲 - 全系统落地方案设计

## 需要调用的Skill
| Skill名称 | 用途 |
|-----------|------|
| `software-architecture-design` | 系统架构设计 |
| `api-design` | REST API设计规范 |
| `backend-patterns` | 后端架构模式 |
| `product-manager` | 产品需求分析 |
| `data-engineer` | 数据层设计 |
| `mega-agent-systems` | Agent系统架构设计 |

## 执行目标
输出「智效工坊」多Agent协同任务执行与知识沉淀平台的完整企业级落地方案，作为全项目开发的唯一依据。基于MetaGPT的Role-Team-Environment架构模式设计。

## 角色定位
资深AI全栈架构师 + 技术负责人

## 核心定位
以「多Agent协同执行复杂任务」为核心能力，以「执行过程自动结构化知识沉淀」为核心差异化，构建「任务提交→Agent分工执行→成果交付→经验自动沉淀→新任务智能复用」的正向业务闭环，区别于传统静态RAG知识库，实现"越用越聪明"的企业级AI工作台。

## MetaGPT架构模式集成（核心设计原则）

### 1. Role（角色）模式
```python
class BaseRole:
    """角色基类 - 参考MetaGPT Role设计"""
    name: str                    # 角色名称
    profile: str                 # 角色描述
    goal: str                    # 角色目标
    tools: list[str] = []        # 可用工具列表
    watch: list[str] = []        # 订阅的消息来源
    
    async def _think(self) -> bool:
        """思考阶段 - 决定下一步行动"""
        pass
    
    async def _act(self) -> ActionOutput:
        """执行阶段 - 执行具体动作"""
        pass
    
    async def _observe(self) -> bool:
        """观察阶段 - 处理执行结果"""
        pass
```

### 2. Team（团队）模式
```python
class Team:
    """团队管理 - 参考MetaGPT Team设计"""
    def hire(self, roles: list[BaseRole]):
        """雇佣角色"""
        pass
    
    def disband(self, roles: list[BaseRole]):
        """解雇角色"""
        pass
    
    async def run(self, task: str):
        """执行任务"""
        pass
```

### 3. Environment（环境）模式
```python
class Environment:
    """环境管理 - 参考MetaGPT Environment设计"""
    def publish_message(self, msg: Message, publicer: str):
        """发布消息"""
        pass
    
    def subscribe(self, role: str, action_types: list[str]):
        """订阅消息"""
        pass
```

### 4. Memory（记忆）模式
```python
class Memory:
    """记忆系统 - 参考MetaGPT Memory设计"""
    def add(self, message: Message):
        """添加记忆"""
        pass
    
    def get_by_actions(self, action_types: list[str]) -> list[Message]:
        """按动作类型获取记忆"""
        pass
    
    def search(self, query: str, top_k: int = 5) -> list[Message]:
        """语义搜索记忆"""
        pass
```

### 5. Plan/Task（计划/任务）模式
```python
class Task:
    """任务定义 - 参考MetaGPT Task设计"""
    task_id: str
    instruction: str
    code: str = ""
    result: str = ""
    is_success: bool = False
    is_finished: bool = False
    assignee: str = ""

class Plan:
    """计划管理 - 参考MetaGPT Plan设计"""
    def add_tasks(self, tasks: list[Task]):
        """添加任务（自动拓扑排序）"""
        pass
    
    def finish_current_task(self):
        """完成当前任务"""
        pass
    
    @property
    def current_task(self) -> Task:
        """获取当前任务"""
        pass
```

### 6. Tool（工具）模式
```python
from metagpt.tools.tool_registry import register_tool

@register_tool(tags=["code", "editor"])
class Editor:
    """工具类 - 参考MetaGPT Tool设计"""
    def read(self, path: str) -> str:
        pass
    
    def write(self, path: str, content: str):
        pass
```

## 强制统一技术栈与版本约束
- 后端：Python 3.11 + FastAPI 0.110+ + SQLAlchemy 2.0 + Pydantic v2，严格遵循RESTful API规范
- 前端：Vue 3.4+ + TypeScript 5.4+ + Element Plus + Pinia + Vue Router 4
- AI层：LangChain 0.1+ + LangGraph 0.0+，兼容OpenAI/通义千问/DeepSeek等主流LLM接口
- 数据层：MySQL 8.0（业务数据）+ Redis 7.0（会话缓存、任务队列、限流、状态存储）+ Chroma（默认向量库，兼容Milvus扩展）
- 工程化：Git + Docker 24+ + Docker Compose v2 + 多阶段构建优化
- 安全规范：JWT鉴权、接口幂等性、参数校验、SQL注入防护、敏感信息脱敏

## 核心业务模块（强制覆盖）
1. 用户与团队空间：注册登录、JWT无感刷新、团队空间管理、RBAC角色权限控制
2. 任务执行中心：任务提交、多Agent流水线执行、SSE流式过程展示、成果导出、中断/重跑/重试控制
3. 多Agent编排引擎：任务拆解Agent、资料检索Agent、内容生成Agent、质量审核Agent，支持条件分支与循环迭代
4. 工具集平台：知识库检索、网页搜索、文件解析（PDF/Word/Markdown）、数值计算4类基础工具，Agent自主调度
5. 知识沉淀系统：执行过程自动提取知识点/经验/模板、语义清洗、自动打标、向量化入库、分类管理
6. 复盘与统计：执行链路可视化回溯、任务效果统计、Agent能力画像、知识复用率分析

## 输出要求（高标准结构化）
### 1. 需求与价值分析
- 核心目标用户与典型使用场景（至少3类）
- 行业痛点与现有方案的不足
- 功能优先级划分（P0/P1/P2）与业务价值量化预期
- 与普通RAG知识库、单Agent助手的核心差异化创新点

### 2. 系统整体架构
- 分层架构图（文字精准描述，明确接入层/业务层/AI引擎层/数据层）
- 全链路数据流转说明：从用户提交任务到成果交付+知识沉淀的完整数据流
- 各层职责边界与交互协议

### 3. 技术选型明细
- 每个技术组件的具体版本建议、选型理由、替代方案对比
- 技术风险点与兼容方案

### 4. 数据层完整设计
- MySQL核心表结构：字段名、类型、约束、索引、关联关系，覆盖所有核心业务
- Redis键值设计：命名规范、数据结构、过期策略、业务场景映射
- 向量库存储结构：元数据设计、分片策略、索引类型

### 5. 多Agent核心机制
- 4类Agent的角色定义、职责边界、能力边界
- LangGraph工作流编排逻辑：状态定义、节点流转、条件分支、异常回退、循环终止条件
- 全局状态管理与Agent间信息共享机制
- 核心Prompt设计原则与输出格式化约束

### 6. 知识自动沉淀方案
- 从执行日志中提取知识的触发规则与提取策略
- 文本清洗、去重、语义分片的具体算法与规则
- 自动标签分类、向量化入库的完整流程
- 检索召回策略：场景匹配+语义相似度+质量分加权排序

### 7. 3周开发排期计划
- 按周拆分里程碑，明确每周交付物、验收标准
- 按天拆分核心任务，标注前后端与AI模块的并行开发节点

### 8. 核心技术难点与落地方案
- 列出至少6个核心技术难点（含多Agent协同稳定性、知识沉淀准确性、流式输出一致性等）
- 每个难点对应可落地的解决方案、备选方案、效果预期

### 9. 上线验收标准
- 功能验收：核心业务流程100%跑通的测试用例
- AI效果验收：任务完成率、输出合格率、知识召回率、幻觉率的量化指标与测试方法
- 性能验收：接口响应时长、并发支持数、任务执行耗时的量化标准
- 工程验收：容器化一键部署、接口文档完整、日志可追溯

## 验收标准
- [ ] 完成9个章节的结构化输出
- [ ] 技术栈版本明确且一致
- [ ] 数据库表结构完整覆盖所有业务
- [ ] 3周排期计划具体到每天
- [ ] 至少6个技术难点有落地解决方案
