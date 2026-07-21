# GOAL-06: 进阶能力扩展指令（技术深度加分项）

## 需要调用的Skill
| Skill名称 | 用途 |
|-----------|------|
| `ai-engineer` | AI应用工程师 |
| `machine-learning-engineer` | 机器学习工程师 |
| `ai-ml-data-science` | ML和数据科学 |
| `ai-rag` | RAG和搜索工程 |
| `ai-llm-inference` | LLM推理优化 |
| `pytorch-patterns` | PyTorch深度学习模式 |

## 执行目标
在现有「智效工坊」基础版本之上，扩展4项进阶能力，大幅提升项目技术深度与竞争力。集成MetaGPT的Tool系统设计模式。

## 角色定位
AI架构师 / 高级算法工程师 + AI系统架构师

## 扩展方向与实现要求

### 1. 向量库升级：Chroma → Milvus 分布式向量检索
**迁移方案：**
- 数据结构映射、迁移脚本、双写过渡方案

**架构设计：**
- Milvus集群模式、索引选型（IVF_FLAT/HNSW）、分片策略

**性能对比：**
- 百万级向量下的检索耗时、召回率、资源占用对比

**代码改造：**
- 向量库抽象层设计，无缝切换Chroma/Milvus，不影响上层业务

### 2. 多Agent动态路由与自定义工作流
**动态路由机制：**
- 任务意图识别，根据任务类型自动匹配最优Agent组合与工具集

**可视化工作流编排：**
- 支持用户拖拽配置Agent节点、连线、分支条件

**自定义Agent：**
- 支持用户上传提示词创建专属Agent，加入工作流调度

**实现方案：**
- 意图分类模型、工作流DSL定义、动态图构建逻辑

### 3. 领域模型微调接入
**微调数据构造：**
- 从历史任务数据中自动构造指令微调数据集，包含指令、输入、输出

**训练方案：**
- 基于LoRA轻量化微调，适配开源7B/14B模型，给出训练参数与步骤

**模型评估：**
- 构建领域测试集，从准确率、格式合规性、幻觉率三个维度评估效果

**工程接入：**
- 模型服务化部署，平台支持一键切换基础模型与微调模型，A/B测试能力

### 4. 知识图谱增强检索
**图谱构建方案：**
- 从沉淀知识中自动抽取实体、关系、属性，构建领域知识图谱

**存储选型：**
- Neo4j图数据库存储，设计节点、关系、属性模型

**混合检索：**
- 向量语义检索 + 图谱关系推理 + 关键词匹配，三路召回融合重排序

**实体问答：**
- 支持基于图谱的实体关系查询，提升复杂问题回答准确率

### 5. MetaGPT Tool系统集成
**Tool Registry（工具注册表）：**
```python
# app/tools/tool_registry.py
from typing import Dict, List, Any, Callable, Optional
from pydantic import BaseModel, Field
import inspect

class ToolSchema(BaseModel):
    """工具Schema定义"""
    name: str
    description: str
    parameters: Dict[str, Any] = {}
    returns: Dict[str, Any] = {}
    tags: List[str] = []

class Tool(BaseModel):
    """工具定义"""
    name: str
    path: str
    schemas: ToolSchema
    code: str = ""
    tags: List[str] = []

class ToolRegistry:
    """工具注册表 - 参考MetaGPT ToolRegistry设计"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.tools_by_tags: Dict[str, Dict[str, Tool]] = {}
    
    def register_tool(
        self,
        tool_name: str,
        tool_path: str,
        schemas: Optional[ToolSchema] = None,
        tool_code: str = "",
        tags: Optional[List[str]] = None
    ) -> None:
        """注册工具"""
        if self.has_tool(tool_name):
            return
        
        if not schemas:
            schemas = self._make_schema_from_code(tool_path)
        
        if not schemas:
            return
        
        tags = tags or []
        tool = Tool(
            name=tool_name,
            path=tool_path,
            schemas=schemas,
            code=tool_code,
            tags=tags
        )
        self.tools[tool_name] = tool
        
        for tag in tags:
            if tag not in self.tools_by_tags:
                self.tools_by_tags[tag] = {}
            self.tools_by_tags[tag][tool_name] = tool
    
    def has_tool(self, key: str) -> bool:
        """检查工具是否存在"""
        return key in self.tools
    
    def get_tool(self, key: str) -> Optional[Tool]:
        """获取工具"""
        return self.tools.get(key)
    
    def get_tools_by_tag(self, key: str) -> Dict[str, Tool]:
        """按标签获取工具"""
        return self.tools_by_tags.get(key, {})
    
    def get_all_tools(self) -> Dict[str, Tool]:
        """获取所有工具"""
        return self.tools
    
    def validate_tool_names(self, tools: List[str]) -> Dict[str, Tool]:
        """验证工具名称"""
        valid_tools = {}
        for key in tools:
            if self.has_tool(key):
                valid_tools[key] = self.get_tool(key)
            elif self.has_tool_tag(key):
                valid_tools.update(self.get_tools_by_tag(key))
        return valid_tools
    
    def _make_schema_from_code(self, tool_path: str) -> Optional[ToolSchema]:
        """从代码生成Schema"""
        # 这里可以添加自动从代码生成Schema的逻辑
        return None

# 全局工具注册表实例
TOOL_REGISTRY = ToolRegistry()

def register_tool(
    tags: Optional[List[str]] = None,
    schema_path: str = "",
    **kwargs
):
    """工具注册装饰器"""
    def decorator(cls):
        # 获取文件路径和源代码
        file_path = inspect.getfile(cls)
        source_code = inspect.getsource(cls)
        
        # 生成Schema
        schema = ToolSchema(
            name=cls.__name__,
            description=cls.__doc__ or "",
            tags=tags or []
        )
        
        # 注册工具
        TOOL_REGISTRY.register_tool(
            tool_name=cls.__name__,
            tool_path=file_path,
            schemas=schema,
            tool_code=source_code,
            tags=tags
        )
        return cls
    
    return decorator
```

**Tool示例实现：**
```python
# app/tools/editor.py
from typing import Optional
from app.tools.tool_registry import register_tool

@register_tool(tags=["code", "editor"])
class Editor:
    """代码编辑工具"""
    
    def read(self, path: str, line_start: Optional[int] = None, line_end: Optional[int] = None) -> str:
        """读取文件内容"""
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if line_start and line_end:
            # 行号从1开始，索引从0开始
            start = max(0, line_start - 1)
            end = min(len(lines), line_end)
            return "".join(lines[start:end])
        
        return "".join(lines)
    
    def write(self, path: str, content: str) -> bool:
        """写入文件内容"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"写入文件失败: {e}")
            return False
    
    def edit(self, path: str, old_string: str, new_string: str) -> bool:
        """编辑文件内容"""
        try:
            content = self.read(path)
            if old_string in content:
                new_content = content.replace(old_string, new_string)
                return self.write(path, new_content)
            return False
        except Exception as e:
            print(f"编辑文件失败: {e}")
            return False

@register_tool(tags=["terminal", "command"])
class Terminal:
    """终端命令工具"""
    
    def run_command(self, cmd: str, timeout: int = 120) -> dict:
        """运行终端命令"""
        import subprocess
        import asyncio
        
        async def run_cmd():
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                return {
                    "returncode": process.returncode,
                    "stdout": stdout.decode('utf-8'),
                    "stderr": stderr.decode('utf-8')
                }
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"命令超时 ({timeout}秒)"
                }
        
        return asyncio.run(run_cmd())
    
    def check_command_exists(self, command: str) -> bool:
        """检查命令是否存在"""
        import subprocess
        import platform
        
        if platform.system().lower() == "windows":
            check_command = f"where {command}"
        else:
            check_command = f"command -v {command} >/dev/null 2>&1"
        
        result = subprocess.run(check_command, shell=True)
        return result.returncode == 0
```

**Tool推荐系统：**
```python
# app/tools/tool_recommend.py
from typing import List, Dict, Any
from app.tools.tool_registry import TOOL_REGISTRY

class ToolRecommender:
    """工具推荐系统"""
    
    def __init__(self, registry: ToolRegistry = TOOL_REGISTRY):
        self.registry = registry
    
    def recommend_tools(self, task_description: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """根据任务描述推荐工具"""
        recommendations = []
        
        # 基于标签匹配
        for tool_name, tool in self.registry.get_all_tools().items():
            score = self._calculate_relevance_score(task_description, tool)
            if score > 0:
                recommendations.append({
                    "tool_name": tool_name,
                    "tool": tool,
                    "score": score,
                    "reason": f"基于标签匹配，相关度: {score:.2f}"
                })
        
        # 按分数排序
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        
        return recommendations[:top_k]
    
    def _calculate_relevance_score(self, task_description: str, tool: Any) -> float:
        """计算工具与任务的相关度分数"""
        score = 0.0
        
        # 基于工具名称匹配
        if tool.name.lower() in task_description.lower():
            score += 0.3
        
        # 基于描述匹配
        if tool.schemas.description:
            # 简单关键词匹配（实际项目中可以使用语义匹配）
            keywords = tool.schemas.description.lower().split()
            for keyword in keywords:
                if keyword in task_description.lower():
                    score += 0.1
        
        # 基于标签匹配
        for tag in tool.tags:
            if tag.lower() in task_description.lower():
                score += 0.2
        
        return min(score, 1.0)
```

## 每个扩展点输出要求
- 架构设计图（文字描述）与改造点说明
- 核心实现思路与关键代码示例
- 技术价值与项目亮点说明
- 落地成本与收益评估

## 验收标准
- [ ] Milvus迁移方案完整，抽象层设计合理
- [ ] 动态路由机制可工作，意图识别准确
- [ ] 微调数据构造流程完整，训练方案可执行
- [ ] 知识图谱构建方案可行，混合检索逻辑清晰
- [ ] Tool Registry设计完整，支持工具注册、查询、推荐
- [ ] 工具自动发现和Schema生成机制可工作
