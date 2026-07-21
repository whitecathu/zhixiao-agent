# Zhixiao Agent Core

`zhixiao_agent` 是智效工坊的软件工程 Agent 运行时与 CLI。它使用正式的 LangGraph `StateGraph`，通过 SQLite checkpoint 实现可恢复的计划审批，默认在 Git worktree 中隔离修改，并以测试结果和 Git diff 作为完成门禁。

## 能力

- Planner、Explorer、Implementer、Tester、Reviewer、Knowledge 角色路由。
- `read_only`、`edit`、`execute`、`full` 四级权限与危险操作审批。
- 文件、搜索、精确编辑、命令、测试、Git、Todo、后台任务、网络、知识、子 Agent 和 MCP 工具。
- `AGENTS.md`/`AGENT.md`/`Claude.md` 目录作用域指令与 `SKILL.md`/旧模板兼容。
- Chroma/Milvus 双写迁移、Neo4j 混合召回、训练数据去敏、LoRA、评估、模型注册和 A/B 路由。
- OpenAI-compatible 模型协议，可配置 xAI、OpenAI、DeepSeek、通义和 vLLM 地址。

## 安装与运行

```bash
python -m venv .venv
pip install -e ".[dev,cli]"
pytest -q
zhixiao doctor
zhixiao run --offline --prompt "审查当前仓库" --workspace . --permission read_only
```

真实改动需要模型密钥，并在计划通过后执行：

```bash
LLM_API_KEY=... zhixiao run --prompt "修复失败测试" --workspace . --permission full --yes
```

连接远程控制面：

```bash
zhixiao run --api-url http://localhost:8000 --api-token "$TOKEN" \
  --repository-id 1 --space-id 1 --prompt "实现跨栈功能" --permission full --yes
```

不带子命令运行 `zhixiao` 会启动 TUI。TUI 通过 `/mode` 切换权限，通过 `/approve` 或 `/deny` 恢复持久化运行。
