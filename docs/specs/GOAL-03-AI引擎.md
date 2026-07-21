# GOAL-03: AI核心引擎开发（LangChain+LangGraph 多Agent与RAG引擎）

## 需要调用的Skill
| Skill名称 | 用途 |
|-----------|------|
| `ai-engineer` | AI应用工程师 |
| `ai-rag` | RAG和搜索工程 |
| `ai-llm` | LLM全生命周期 |
| `ai-prompt-engineering` | 提示词工程 |
| `mega-agent-systems` | AI Agent系统设计 |
| `mcp-developer` | MCP服务器开发 |

## 执行目标
基于LangChain + LangGraph实现「智效工坊」多Agent协同执行引擎与自动知识沉淀RAG系统，封装为可被后端直接调用的独立服务。集成MetaGPT的Role-Team-Environment架构模式。

## 角色定位
资深AI应用工程师 / Agent开发专家 + AI系统架构师

## 技术约束
- 编排框架：LangGraph 实现状态机式工作流，支持状态持久化与断点续跑
- 模型适配：兼容主流LLM接口，支持模型配置热切换
- 向量库：Chroma 向量存储，支持混合检索与重排序
- 输出规范：所有Agent输出结构化可解析格式，与业务层解耦
- **Agent架构**：基于MetaGPT的Role-Team-Environment模式设计Agent系统

## MetaGPT模式集成实现

### 1. Agent角色系统（基于MetaGPT Role模式）
```python
# app/agents/base_agent.py
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field
from langchain_core.language_models import BaseLLM
from langchain_core.tools import BaseTool

class BaseAgent(BaseModel):
    """Agent基类 - 参考MetaGPT Role设计"""
    name: str
    profile: str
    goal: str
    llm: Optional[BaseLLM] = None
    tools: List[BaseTool] = Field(default_factory=list)
    watch: List[str] = Field(default_factory=list)  # 订阅的消息来源
    system_prompt: str = ""
    
    class Config:
        arbitrary_types_allowed = True
    
    async def _think(self, context: Dict[str, Any]) -> bool:
        """思考阶段 - 决定下一步行动"""
        # 分析当前状态，决定是否需要执行
        return True
    
    async def _act(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行阶段 - 执行具体动作"""
        # 根据思考结果执行相应动作
        raise NotImplementedError
    
    async def _observe(self, message: Any) -> Dict[str, Any]:
        """观察阶段 - 处理执行结果"""
        # 分析执行结果，更新内部状态
        return {"status": "observed", "data": message}
    
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """运行Agent"""
        # 1. 观察阶段
        observation = await self._observe(context.get("message"))
        
        # 2. 思考阶段
        should_act = await self._think({**context, "observation": observation})
        
        # 3. 执行阶段
        if should_act:
            result = await self._act(context)
            return result
        
        return {"status": "no_action_needed"}
    
    def _format_system_prompt(self) -> str:
        """格式化系统提示词"""
        return f"""
你是一个{self.profile}。
你的目标是：{self.goal}

{self.system_prompt}
"""
```

### 2. 具体Agent实现示例
```python
# app/agents/task_decomposer.py
from typing import Dict, Any, List
from app.agents.base_agent import BaseAgent
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

class SubTask(BaseModel):
    """子任务定义"""
    task_id: str
    instruction: str
    dependencies: List[str] = []
    expected_output: str

class TaskDecomposerAgent(BaseAgent):
    """任务拆解Agent - 参考MetaGPT ProductManager"""
    
    system_prompt = """
你是一个专业的任务拆解专家。你的职责是将用户目标拆解为可执行的子任务。

输出格式要求：
- 每个子任务必须有明确的ID、指令、依赖关系和预期输出
- 子任务之间应该有清晰的依赖关系
- 确保子任务的完整性，覆盖用户目标的所有方面
"""
    
    async def _think(self, context: Dict[str, Any]) -> bool:
        """思考是否需要拆解任务"""
        # 检查是否有待拆解的任务
        message = context.get("message")
        if message and hasattr(message, 'content'):
            return True
        return False
    
    async def _act(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务拆解"""
        message = context.get("message")
        
        # 使用LLM进行任务拆解
        prompt = ChatPromptTemplate.from_messages([
            ("system", self._format_system_prompt()),
            ("human", "{input}")
        ])
        
        chain = prompt | self.llm
        result = await chain.ainvoke({"input": message.content})
        
        # 解析结果为子任务列表
        sub_tasks = self._parse_sub_tasks(result.content)
        
        return {
            "status": "success",
            "sub_tasks": sub_tasks,
            "original_task": message.content
        }
    
    def _parse_sub_tasks(self, content: str) -> List[SubTask]:
        """解析子任务"""
        # 这里可以添加更复杂的解析逻辑
        # 简化示例：假设LLM返回JSON格式的子任务列表
        import json
        try:
            # 尝试从内容中提取JSON
            json_match = content[content.find('['):content.find(']')+1]
            if json_match:
                tasks_data = json.loads(json_match)
                return [SubTask(**task) for task in tasks_data]
        except:
            pass
        
        # 如果解析失败，返回默认子任务
        return [SubTask(
            task_id="1",
            instruction=content,
            expected_output="执行结果"
        )]
```

### 3. Team（团队）系统集成
```python
# app/teams/agent_team.py
from typing import Dict, Any, List, Optional
from app.agents.base_agent import BaseAgent
from app.environments.agent_environment import AgentEnvironment
from app.memory.agent_memory import AgentMemory

class AgentTeam:
    """Agent团队 - 参考MetaGPT Team设计"""
    
    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.env: AgentEnvironment = AgentEnvironment()
        self.memory: AgentMemory = AgentMemory()
    
    def hire(self, agents: List[BaseAgent]) -> None:
        """雇佣Agent"""
        for agent in agents:
            self.agents[agent.name] = agent
            self.env.add_agent(agent)
    
    def disband(self, agent_names: List[str]) -> None:
        """解雇Agent"""
        for name in agent_names:
            if name in self.agents:
                del self.agents[name]
                self.env.remove_agent(name)
    
    async def execute_task(self, task: str) -> Dict[str, Any]:
        """执行任务"""
        from app.schemas.message import Message
        
        # 1. 创建初始消息
        initial_message = Message(
            content=task,
            role="user",
            cause_by="UserRequirement"
        )
        
        # 2. 发布初始消息
        self.env.publish_message(initial_message, publicer="user")
        
        # 3. 执行循环
        results = {}
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            # 获取下一个要执行的Agent
            next_agent = self._get_next_agent()
            if not next_agent:
                break
            
            # 获取Agent的消息
            agent_messages = self.env.get_messages_for_agent(next_agent.name)
            if not agent_messages:
                break
            
            # 准备上下文
            context = {
                "message": agent_messages[-1],
                "team": self,
                "memory": self.memory
            }
            
            # 执行Agent
            result = await next_agent.run(context)
            results[next_agent.name] = result
            
            # 记录到记忆
            self.memory.add({
                "agent": next_agent.name,
                "action": "execute",
                "result": result,
                "timestamp": "now"
            })
            
            # 发布执行结果
            result_message = Message(
                content=str(result),
                role="assistant",
                sent_from=next_agent.name,
                cause_by=type(next_agent).__name__
            )
            self.env.publish_message(result_message, publicer=next_agent.name)
            
            iteration += 1
        
        return results
    
    def _get_next_agent(self) -> Optional[BaseAgent]:
        """获取下一个要执行的Agent"""
        # 基于消息队列和订阅关系确定执行顺序
        for agent in self.agents.values():
            messages = self.env.get_messages_for_agent(agent.name)
            if messages:
                return agent
        return None
```

### 4. Environment（环境）系统集成
```python
# app/environments/agent_environment.py
from typing import Dict, Any, List, Optional
from app.schemas.message import Message
from collections import defaultdict

class AgentEnvironment:
    """Agent环境 - 参考MetaGPT Environment设计"""
    
    def __init__(self):
        self.agents: Dict[str, Any] = {}
        self.message_queue: List[Message] = []
        self.message_history: Dict[str, List[Message]] = defaultdict(list)
    
    def add_agent(self, agent: Any) -> None:
        """注册Agent"""
        self.agents[agent.name] = agent
    
    def remove_agent(self, agent_name: str) -> None:
        """移除Agent"""
        if agent_name in self.agents:
            del self.agents[agent_name]
    
    def publish_message(self, msg: Message, publicer: str) -> None:
        """发布消息"""
        msg.sent_from = publicer
        self.message_queue.append(msg)
        self.message_history[publicer].append(msg)
    
    def get_messages_for_agent(self, agent_name: str) -> List[Message]:
        """获取Agent的消息"""
        agent = self.agents.get(agent_name)
        if not agent:
            return []
        
        # 根据Agent的watch列表过滤消息
        watched_messages = []
        for msg in self.message_queue:
            if msg.sent_from in agent.watch or not agent.watch:
                watched_messages.append(msg)
        
        return watched_messages
    
    def clear_queue(self) -> None:
        """清空消息队列"""
        self.message_queue.clear()
```

## 核心功能实现要求

### 1. 多Agent编排体系
**4个专业化Agent定义与实现：**
- **任务拆解Agent**：接收用户目标，拆解为可执行的子任务节点，明确每个节点的输入输出与依赖
- **资料检索Agent**：根据子任务需求，调用工具检索知识库与互联网资料，汇总整理参考素材
- **内容生成Agent**：基于素材与任务要求，生成对应交付内容，遵循格式规范
- **质量审核Agent**：校验内容准确性、完整性、合规性，给出修改意见，决定是否返工

**LangGraph工作流编排：**
- 定义全局GraphState，包含任务信息、子任务列表、素材库、生成内容、审核记录、执行日志
- 实现流水线式节点流转，支持条件分支（审核通过/驳回重写）、循环迭代、异常捕获与重试
- 支持任务中断与状态恢复，状态数据持久化对接后端Redis
- 每个Agent配套专属系统提示词，明确角色、职责、输出格式、约束规则
- 工具调用能力：Agent可自主判断是否调用工具、调用哪类工具、解析工具返回结果

### 2. 工具集封装
- **知识库检索工具**：对接Chroma向量库，实现语义检索+关键词匹配混合召回，支持按空间、标签过滤
- **网页搜索工具**：封装通用搜索接口，返回结构化摘要与来源
- **文件解析工具**：支持PDF/Word/Markdown/Excel文本提取与分片
- **数据计算工具**：支持简单数值计算、表格统计
- 统一工具抽象基类，新增工具只需继承基类即可被Agent识别

### 3. RAG知识沉淀全流程
**知识自动提取：**
- 任务完成后，从执行日志、素材、生成内容、审核意见中自动抽取结构化知识
- 提取规则：经验结论、方法模板、业务知识点、踩坑记录四类知识

**知识清洗与加工：**
- 去重、去冗余、语义规范化、自动摘要生成、自动标签分类

**向量化入库：**
- 语义分片、embedding向量化、元数据关联（来源任务、创建时间、标签、质量分）

**召回优化策略：**
- 检索时融合任务场景相似度、知识质量分、时间衰减因子加权排序
- 支持同类型任务优先召回历史经验

### 4. Prompt工程与效果优化
- 构建分层Prompt体系：角色层+任务层+工具层+格式层+约束层
- 幻觉抑制方案：引用溯源、事实校验、多轮交叉验证
- 输出一致性保障：结构化输出模板、约束词、示例引导
- 长上下文处理策略：分层摘要、动态上下文窗口管理

## 代码输出要求
1. 完整的引擎目录结构，职责分层清晰
2. GraphState 状态定义与工作流编排完整代码
3. 4个Agent的实现代码与完整Prompt模板
4. 工具集基类与4类工具的具体实现
5. 知识沉淀流水线的完整代码：提取→清洗→分片→入库
6. 检索服务的实现代码：混合召回、重排序、结果格式化
7. 引擎服务类封装：对外暴露标准的启动任务、中断任务、获取状态接口
8. 效果调优手册：检索准确率、Agent执行成功率、输出质量的调优参数与方法
9. 常见问题排查：Agent循环、输出格式错误、检索不准等问题的解决方案

## 验收标准
- [ ] 4个Agent定义完整，职责清晰
- [ ] LangGraph工作流编排正确，支持条件分支
- [ ] 工具集基类设计合理，4类工具可用
- [ ] 知识沉淀全流程贯通
- [ ] 检索准确率≥80%
- [ ] Agent执行成功率≥85%
- [ ] 输出格式合规率≥90%
