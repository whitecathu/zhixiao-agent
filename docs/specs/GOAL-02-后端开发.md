# GOAL-02: 后端服务开发（FastAPI 企业级工程实现）

## 需要调用的Skill
| Skill名称 | 用途 |
|-----------|------|
| `fastapi-developer` | FastAPI框架开发专家 |
| `python-pro` | Python专业开发 |
| `backend-patterns` | 后端架构模式 |
| `api-design` | REST API设计规范 |
| `database-optimizer` | 数据库性能优化 |
| `software-backend` | 生产级后端API |
| `mega-agent-systems` | Agent系统架构设计 |

## 执行目标
基于FastAPI框架，编写「智效工坊」平台的后端完整工程实现方案与核心代码，严格遵循企业级开发规范。集成MetaGPT的Role-Team-Environment架构模式。

## 角色定位
资深Python后端工程师 + AI系统架构师

## 技术约束
- 架构：router / service / dao / model / schema / common 六层架构，职责严格分离
- 数据库：SQLAlchemy 2.0 异步ORM操作MySQL 8.0，支持事务与连接池
- 缓存：Redis 7.0 实现会话管理、任务状态缓存、接口限流、分布式锁
- 规范：RESTful API 设计、统一响应体、全局错误码、全局异常处理、参数自动校验
- 安全：JWT双令牌鉴权（access+refresh）、密码bcrypt加密、接口幂等性校验、CORS跨域配置
- **Agent架构**：基于MetaGPT的Role-Team-Environment模式设计Agent系统

## MetaGPT模式集成实现

### 1. Role（角色）系统实现
```python
# app/roles/base_role.py
from pydantic import BaseModel, Field
from typing import Optional, Any

class BaseRole(BaseModel):
    """角色基类 - 参考MetaGPT Role设计"""
    name: str
    profile: str
    goal: str
    tools: list[str] = Field(default_factory=list)
    watch: list[str] = Field(default_factory=list)  # 订阅的消息来源
    
    class Config:
        arbitrary_types_allowed = True
    
    async def _think(self) -> bool:
        """思考阶段 - 决定下一步行动"""
        raise NotImplementedError
    
    async def _act(self) -> Any:
        """执行阶段 - 执行具体动作"""
        raise NotImplementedError
    
    async def _observe(self, message: Any) -> bool:
        """观察阶段 - 处理执行结果"""
        raise NotImplementedError
    
    async def run(self, message: Any = None) -> Any:
        """运行角色"""
        if message:
            await self._observe(message)
        
        should_act = await self._think()
        if should_act:
            return await self._act()
        return None
```

### 2. Team（团队）系统实现
```python
# app/teams/team.py
from typing import Optional
from app.roles.base_role import BaseRole
from app.environments.environment import Environment

class Team:
    """团队管理 - 参考MetaGPT Team设计"""
    
    def __init__(self):
        self.roles: dict[str, BaseRole] = {}
        self.env: Environment = Environment()
    
    def hire(self, roles: list[BaseRole]) -> None:
        """雇佣角色到团队"""
        for role in roles:
            self.roles[role.name] = role
            self.env.add_role(role)
    
    def disband(self, role_names: list[str]) -> None:
        """从团队解雇角色"""
        for name in role_names:
            if name in self.roles:
                del self.roles[name]
                self.env.remove_role(name)
    
    async def run(self, task: str) -> dict:
        """执行任务"""
        # 初始化任务消息
        from app.schemas.message import Message
        initial_message = Message(
            content=task,
            role="user",
            cause_by="UserRequirement"
        )
        
        # 发布初始消息
        self.env.publish_message(initial_message, publicer="user")
        
        # 执行循环
        results = {}
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            # 获取下一个要执行的角色
            next_role = self._get_next_role()
            if not next_role:
                break
            
            # 获取角色的消息
            role_messages = self.env.get_messages_for_role(next_role.name)
            if not role_messages:
                break
            
            # 执行角色
            result = await next_role.run(role_messages[-1])
            results[next_role.name] = result
            
            # 发布执行结果
            result_message = Message(
                content=str(result),
                role="assistant",
                sent_from=next_role.name,
                cause_by=type(next_role).__name__
            )
            self.env.publish_message(result_message, publicer=next_role.name)
            
            iteration += 1
        
        return results
    
    def _get_next_role(self) -> Optional[BaseRole]:
        """获取下一个要执行的角色"""
        # 基于消息队列和订阅关系确定执行顺序
        for role in self.roles.values():
            messages = self.env.get_messages_for_role(role.name)
            if messages:
                return role
        return None
```

### 3. Environment（环境）系统实现
```python
# app/environments/environment.py
from typing import Optional
from app.schemas.message import Message
from collections import defaultdict

class Environment:
    """环境管理 - 参考MetaGPT Environment设计"""
    
    def __init__(self):
        self.roles: dict[str, Any] = {}
        self.message_queue: list[Message] = []
        self.message_history: dict[str, list[Message]] = defaultdict(list)
    
    def add_role(self, role: Any) -> None:
        """注册角色到环境"""
        self.roles[role.name] = role
    
    def remove_role(self, role_name: str) -> None:
        """从环境移除角色"""
        if role_name in self.roles:
            del self.roles[role_name]
    
    def publish_message(self, msg: Message, publicer: str) -> None:
        """发布消息"""
        msg.sent_from = publicer
        self.message_queue.append(msg)
        self.message_history[publicer].append(msg)
    
    def get_messages_for_role(self, role_name: str) -> list[Message]:
        """获取角色的消息"""
        role = self.roles.get(role_name)
        if not role:
            return []
        
        # 根据角色的watch列表过滤消息
        watched_messages = []
        for msg in self.message_queue:
            if msg.sent_from in role.watch or not role.watch:
                watched_messages.append(msg)
        
        return watched_messages
    
    def clear_queue(self) -> None:
        """清空消息队列"""
        self.message_queue.clear()
```

### 4. Memory（记忆）系统实现
```python
# app/memory/memory.py
from typing import Optional
from app.schemas.message import Message
from chromadb import Client

class Memory:
    """记忆系统 - 参考MetaGPT Memory设计"""
    
    def __init__(self, chroma_client: Optional[Client] = None):
        self.messages: list[Message] = []
        self.chroma_client = chroma_client
        if chroma_client:
            self.collection = chroma_client.get_or_create_collection("memory")
    
    def add(self, message: Message) -> None:
        """添加记忆"""
        self.messages.append(message)
        
        # 添加到向量数据库
        if self.chroma_client:
            self.collection.add(
                documents=[message.content],
                metadatas=[{
                    "role": message.role,
                    "cause_by": message.cause_by,
                    "sent_from": message.sent_from
                }],
                ids=[message.id]
            )
    
    def get_by_actions(self, action_types: list[str]) -> list[Message]:
        """按动作类型获取记忆"""
        return [msg for msg in self.messages if msg.cause_by in action_types]
    
    def search(self, query: str, top_k: int = 5) -> list[Message]:
        """语义搜索记忆"""
        if not self.chroma_client:
            # 简单的关键词搜索
            return [msg for msg in self.messages if query.lower() in msg.content.lower()][:top_k]
        
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        
        # 根据ID获取消息
        message_ids = results["ids"][0]
        return [msg for msg in self.messages if msg.id in message_ids]
    
    def clear(self) -> None:
        """清空记忆"""
        self.messages.clear()
        if self.chroma_client:
            self.collection.delete(where={})
```

### 5. Plan/Task（计划/任务）系统实现
```python
# app/plans/task.py
from pydantic import BaseModel, Field
from typing import Optional

class Task(BaseModel):
    """任务定义 - 参考MetaGPT Task设计"""
    task_id: str
    dependent_task_ids: list[str] = Field(default_factory=list)
    instruction: str
    task_type: str = ""
    code: str = ""
    result: str = ""
    is_success: bool = False
    is_finished: bool = False
    assignee: str = ""
    
    def reset(self) -> None:
        """重置任务"""
        self.code = ""
        self.result = ""
        self.is_success = False
        self.is_finished = False
    
    def update_task_result(self, task_result: Any) -> None:
        """更新任务结果"""
        self.code = self.code + "\n" + task_result.code
        self.result = self.result + "\n" + task_result.result
        self.is_success = task_result.is_success

class Plan(BaseModel):
    """计划管理 - 参考MetaGPT Plan设计"""
    goal: str
    context: str = ""
    tasks: list[Task] = Field(default_factory=list)
    task_map: dict[str, Task] = Field(default_factory=dict)
    current_task_id: str = ""
    
    def add_tasks(self, tasks: list[Task]) -> None:
        """添加任务（自动拓扑排序）"""
        if not tasks:
            return
        
        # 拓扑排序
        sorted_tasks = self._topological_sort(tasks)
        
        if not self.tasks:
            self.tasks = sorted_tasks
        else:
            # 合并任务
            prefix_length = 0
            for old_task, new_task in zip(self.tasks, sorted_tasks):
                if old_task.task_id != new_task.task_id or old_task.instruction != new_task.instruction:
                    break
                prefix_length += 1
            
            final_tasks = self.tasks[:prefix_length] + sorted_tasks[prefix_length:]
            self.tasks = final_tasks
        
        self._update_current_task()
        self.task_map = {task.task_id: task for task in self.tasks}
    
    def _topological_sort(self, tasks: list[Task]) -> list[Task]:
        """拓扑排序"""
        task_map = {task.task_id: task for task in tasks}
        dependencies = {task.task_id: set(task.dependent_task_ids) for task in tasks}
        sorted_tasks = []
        visited = set()
        
        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)
            for dependent_id in dependencies.get(task_id, []):
                visit(dependent_id)
            sorted_tasks.append(task_map[task_id])
        
        for task in tasks:
            visit(task.task_id)
        
        return sorted_tasks
    
    def _update_current_task(self) -> None:
        """更新当前任务"""
        self.tasks = self._topological_sort(self.tasks)
        self.task_map = {task.task_id: task for task in self.tasks}
        
        current_task_id = ""
        for task in self.tasks:
            if not task.is_finished:
                current_task_id = task.task_id
                break
        self.current_task_id = current_task_id
    
    @property
    def current_task(self) -> Optional[Task]:
        """获取当前任务"""
        return self.task_map.get(self.current_task_id, None)
    
    def finish_current_task(self) -> None:
        """完成当前任务"""
        if self.current_task_id:
            self.current_task.is_finished = True
            self._update_current_task()
    
    def is_plan_finished(self) -> bool:
        """检查计划是否完成"""
        return all(task.is_finished for task in self.tasks)
    
    def get_finished_tasks(self) -> list[Task]:
        """获取已完成的任务"""
        return [task for task in self.tasks if task.is_finished]
```

## 核心功能模块实现要求

### 1. 用户认证模块
- 用户注册、登录、登出、令牌刷新、密码修改
- JWT鉴权中间件，支持白名单与权限注解
- RBAC角色权限体系：超级管理员/空间管理员/普通成员三级权限

### 2. 团队空间模块
- 空间创建、编辑、解散、成员邀请/移除/角色变更
- 空间级数据隔离，所有业务数据绑定空间ID

### 3. 任务管理模块
- 任务创建、列表查询、详情查询、状态更新、任务重跑、成果导出
- 任务状态机设计：待执行/执行中/已完成/已失败/已中断
- 分页查询、条件筛选、排序支持

### 4. 执行引擎接口
- 接收任务请求，异步调度AI执行引擎
- SSE服务端事件推送，流式返回Agent执行步骤与生成内容
- 支持任务中断、暂停、继续的控制指令

### 5. 知识管理模块
- 知识条目CRUD、标签分类管理、批量操作
- 智能检索接口：支持关键词+语义混合检索，分页返回
- 知识关联任务回溯：查看知识来源的任务执行记录

### 6. 工具与统计模块
- 文件上传与解析接口，支持常见文档格式
- 任务统计、知识复用统计、团队活跃度统计接口

## 代码输出要求
1. 完整的项目目录结构，标注每个目录/文件的职责
2. 通用层代码：统一响应体、错误码枚举、全局异常处理器、JWT工具类、Redis工具类、日志配置
3. 核心模块的完整代码实现：model层、schema层、dao层、service层、router层，附带详细注释
4. AI执行引擎的调用抽象层：定义标准输入输出协议，解耦业务层与AI层
5. 数据库迁移脚本示例（Alembic）
6. 单元测试示例：核心接口的pytest测试用例
7. Swagger接口文档配置与分组说明
8. 接口调试指南与常见异常排查方案

## 工程质量要求
- 所有接口必须有参数校验与异常捕获
- 核心写操作必须支持幂等性
- 关键路径必须有日志埋点，支持链路追踪
- 代码遵循PEP8规范，类型注解完整

## 验收标准
- [ ] 6层架构完整实现，职责清晰
- [ ] JWT双令牌鉴权正常工作
- [ ] 任务状态机流转正确
- [ ] SSE流式推送可用
- [ ] 接口文档完整可访问
- [ ] 核心测试用例通过
