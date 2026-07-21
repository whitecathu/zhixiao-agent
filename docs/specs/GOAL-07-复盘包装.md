# GOAL-07: 项目复盘与求职包装指令

## 需要调用的Skill
| Skill名称 | 用途 |
|-----------|------|
| `technical-writer` | 技术写作 |
| `docs-codebase` | 技术文档编写 |

## 执行目标
对「智效工坊」多Agent协同任务执行与知识沉淀平台项目做完整技术复盘，并输出求职用的简历描述与面试准备素材。集成MetaGPT的Skill系统设计模式。

## 角色定位
技术面试官 / 求职辅导专家 + AI系统架构师

## 复盘输出要求

### 1. 项目整体复盘
**项目背景与核心痛点：**
- 针对企业知识沉淀难、复杂任务执行效率低的问题

**项目目标与定位：**
- 打造"执行即沉淀"的AI协同工作台，形成正向闭环

**整体技术架构：**
- 分层架构总览、技术栈清单
- 基于MetaGPT的Role-Team-Environment架构模式设计

**核心模块实现：**
- 分模块阐述设计思路、关键技术、落地难点
- MetaGPT模式集成：Role系统、Team系统、Environment系统、Memory系统、Plan/Task系统、Tool系统

**核心问题与解决方案：**
- 列出4个真实技术难点，对应解决方案、优化过程、量化效果

**量化成果：**
- 任务执行效率：相比人工提升比例
- 知识沉淀：自动沉淀知识条目数、知识复用率
- 系统性能：并发支持数、接口平均响应时长、任务平均执行耗时
- AI效果：任务完成率、输出合格率、知识召回准确率

**不足与迭代规划：**
- 当前方案的局限性、后续技术迭代方向

### 2. 简历版项目描述
**要求：**
- 4条项目经历要点，动词开头，技术点明确，成果量化
- 突出关键词：AI全栈、多Agent编排、LangGraph、RAG、FastAPI、Vue3、知识沉淀、LangChain、MetaGPT
- 匹配AI全栈开发、应用开发、AI工程师岗位招聘需求
- 语言精炼，单条不超过2行，适合简历排版

**示例结构：**
```
智效工坊 - 多Agent协同任务执行与知识沉淀平台
- 设计并实现基于LangGraph的多Agent编排引擎，支持任务拆解、资料检索、内容生成、质量审核的自动化流水线
- 构建RAG知识沉淀系统，实现执行过程自动提取、清洗、向量化入库，知识复用率提升40%
- 开发FastAPI后端服务，采用六层架构设计，支持SSE流式推送，接口平均响应时间<200ms
- 使用Vue3+TypeScript开发前端应用，实现任务执行过程可视化与知识看板管理
- 集成MetaGPT架构模式，设计Role-Team-Environment三层Agent系统，支持动态团队组建和消息路由
```

### 3. 面试高频问题与参考答案
**要求：**
- 列出10个该项目最高频的面试问题，覆盖架构、AI、后端、工程、创新点、MetaGPT模式
- 每个问题给出结构化参考答案，突出技术深度与个人贡献
- 包含追问方向与应答思路

**预期问题方向：**
1. 为什么选择多Agent架构而不是单Agent？
2. LangGraph工作流编排的核心设计是什么？
3. 知识沉淀系统是如何保证质量的？
4. 如何解决Agent之间的状态同步问题？
5. SSE流式推送的技术难点是什么？
6. 系统的并发能力如何？做了哪些优化？
7. 这个项目最大的技术挑战是什么？如何解决的？
8. 如果重新设计这个系统，你会做哪些改进？
9. MetaGPT的Role-Team-Environment架构模式是如何应用到项目中的？
10. 如何设计一个可扩展的Agent系统？Tool Registry是如何工作的？

## MetaGPT Skill系统集成

### Skill（技能）系统设计
```python
# app/skills/skill_manager.py
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
import json
import os
from pathlib import Path

class SkillConfig(BaseModel):
    """技能配置"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)

class Skill(BaseModel):
    """技能定义"""
    config: SkillConfig
    prompt_template: str = ""
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)

class SkillManager:
    """技能管理器 - 参考MetaGPT Skill设计"""
    
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self._load_skills()
    
    def _load_skills(self) -> None:
        """加载所有技能"""
        if not self.skills_dir.exists():
            return
        
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill = self._load_skill(skill_dir)
                if skill:
                    self.skills[skill.config.name] = skill
    
    def _load_skill(self, skill_dir: Path) -> Optional[Skill]:
        """加载单个技能"""
        config_file = skill_dir / "config.json"
        prompt_file = skill_dir / "skprompt.txt"
        
        if not config_file.exists():
            return None
        
        try:
            # 加载配置
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            config = SkillConfig(**config_data)
            
            # 加载Prompt模板
            prompt_template = ""
            if prompt_file.exists():
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    prompt_template = f.read()
            
            return Skill(
                config=config,
                prompt_template=prompt_template
            )
        except Exception as e:
            print(f"加载技能失败 {skill_dir}: {e}")
            return None
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self.skills.get(name)
    
    def list_skills(self) -> List[str]:
        """列出所有技能"""
        return list(self.skills.keys())
    
    def search_skills(self, query: str) -> List[Skill]:
        """搜索技能"""
        results = []
        query_lower = query.lower()
        
        for skill in self.skills.values():
            # 基于名称和描述搜索
            if query_lower in skill.config.name.lower() or \
               query_lower in skill.config.description.lower():
                results.append(skill)
            # 基于标签搜索
            elif any(query_lower in tag.lower() for tag in skill.config.tags):
                results.append(skill)
        
        return results
    
    def render_prompt(self, skill_name: str, context: Dict[str, Any]) -> str:
        """渲染技能Prompt"""
        skill = self.get_skill(skill_name)
        if not skill:
            return ""
        
        # 简单的模板渲染（实际项目中可以使用更复杂的模板引擎）
        prompt = skill.prompt_template
        for key, value in context.items():
            placeholder = f"{{{{${key}}}}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))
        
        return prompt

# 全局技能管理器实例
SKILL_MANAGER = SkillManager()
```

### Skill目录结构示例
```
skills/
├── TaskDecomposer/
│   ├── config.json
│   └── skprompt.txt
├── ContentGenerator/
│   ├── config.json
│   └── skprompt.txt
├── QualityReviewer/
│   ├── config.json
│   └── skprompt.txt
└── KnowledgeExtractor/
    ├── config.json
    └── skprompt.txt
```

### Skill配置文件示例
```json
{
  "name": "TaskDecomposer",
  "description": "任务拆解技能，将复杂任务分解为可执行的子任务",
  "version": "1.0.0",
  "author": "智效工坊团队",
  "tags": ["task", "decomposition", "planning"],
  "dependencies": ["llm", "task-manager"]
}
```

### Skill Prompt模板示例
```
[任务拆解规则]
- 使用简洁、清晰、完整的句子
- 不要使用项目符号或破折号
- 使用主动语态
- 最大化细节和意义
- 专注于内容

[禁止短语]
这个任务
这个项目
这个文档
[结束列表]

任务描述：
{{$input}}
++++++

请将上述任务拆解为可执行的子任务：
```

## 输出文件清单
1. `docs/项目复盘报告.md` - 完整复盘文档
2. `docs/简历项目描述.md` - 简历用项目描述
3. `docs/面试准备手册.md` - 面试问题与答案
4. `docs/MetaGPT模式应用说明.md` - MetaGPT架构模式在项目中的应用

## 验收标准
- [ ] 复盘报告完整覆盖9个章节
- [ ] 量化成果数据合理可信
- [ ] 简历描述精炼，关键词突出
- [ ] 面试问题覆盖全面，答案结构清晰
- [ ] MetaGPT模式应用说明完整，展示架构设计深度
