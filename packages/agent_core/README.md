# Zhixiao Agent Core

`zhixiao_agent` 是智效工坊的软件工程 Agent 运行时与 CLI。默认是**一个模型 + 工具循环**（LangGraph `StateGraph` + SQLite checkpoint），不是四个独立 Agent。`routing.py` 的 planner/explorer 只是事件标签。计划审批与协同停止（`control/{run_id}` → `interrupt(operator_stop)`）可按同一 `run_id` resume。默认在 Git worktree 中隔离修改，并以测试结果和 Git diff 作为完成门禁。

## 能力

- 默认单循环：intake → discover → plan → execute → verify → finalize；Workflow DSL / MetaGPT Team 是可选切片。
- PluginHost 组装工具、斜杠命令、hooks、Skill、MCP；CLI / TUI / Worker 共用 `load_plugin_tree`。
- `read_only`、`edit`、`execute`、`full` 四级权限与危险操作审批；无审批拦截 `git push` / `rm -rf`。
- 文件、搜索、精确编辑、命令、测试、Git、Todo、后台任务；网络 / 知识 / 子 Agent / MCP 需独立能力。
- `AGENTS.md`/`AGENT.md`/`Claude.md` 目录作用域指令与 `SKILL.md`/旧模板兼容。
- OpenAI-compatible 模型协议；Chroma/Milvus/Neo4j/LoRA/vLLM 为可选实验切片，**未上线、未实测质量**。
- 运行预算、停滞/重复失败终止、结构化验证结论和可审计未验证 waiver。
- 本地会话清单、resume/fork、远程 SSE 断线续传和 `text`/`json`/`jsonl` 输出。
- 用户/项目配置分层、可信目录、声明式自定义命令、hooks 与无密钥 MCP 定义。

## 安装与运行

```bash
python -m venv .venv
pip install -e ".[dev,cli]"
pytest -q
zhixiao doctor
zhixiao version
zhixiao run "审查当前仓库" --offline --workspace . --permission read_only \
  --approval-policy never --output-format json --events none
```

真实改动需要模型密钥，并在计划通过后执行：

```bash
LLM_API_KEY=... zhixiao run --prompt "修复失败测试" --workspace . --permission full --yes
```

`--yes` 仅批准生成的执行计划。危险命令、联网、MCP、提交、推送和 PR 仍需要独立能力审批。未受信任目录只能以 `read_only` 运行；确认目录可信后使用 `--trust-workspace` 才会加载 `.zhixiao/config.toml`、`.zhixiao/commands/*.md`、hooks 和项目 Skill。

连接远程控制面：

```bash
zhixiao run --api-url http://localhost:8000 --api-token "$TOKEN" \
  --repository-id 1 --space-id 1 --prompt "实现跨栈功能" --permission full --yes
```

远程 Token 建议通过 `ZHIXIAO_API_TOKEN` 引用，不要写入配置文件或 shell 历史。SSE 客户端保存事件游标、去重并有限重连；Ctrl-C 默认仅脱离远程运行，只有显式 `--interrupt-on-exit` 才请求中断。

## 命令面

- `run [PROMPT]` 支持 prompt 文件/标准输入、`--mode ask|plan|code|review`、权限、审批策略、Runner、预算和结构化输出。无头 `run` 默认 `code`（可改代码）；`ask`/`plan`/`review` 只暴露只读工具。
- `resume`、`fork`、`runs list|show|delete`、`interrupt` 管理本地或远程运行。本地中断写入 `{state_dir}/control/{run_id}`，runtime 消费后暂停工具循环，同一 run id 可恢复。
- `events`、`approve`、`artifacts` 观察和控制运行；远程 `approve`/`fork`/`resume` 会等到终态。
- `review` 以只读模式审查未提交、相对分支或指定提交的变更。
- `config`、`skills`、`hooks`、`mcp`、`plugins` 检查分层配置、可信扩展和插件树。stdio MCP 只需 ops 审批；HTTP MCP 另需网络审批。工作区 Python 插件在 `--trust-workspace` 下加载，错误配置会失败退出。
- `doctor --json` 与 `version` 供安装诊断和 CI 使用。

退出码固定为：`0` 成功、`2` 参数/配置错误、`3` 等待审批或安全阻止、`4` 任务/验证失败、`5` 远程错误、`124` 超时、`130` 用户中断。

不带子命令运行 `zhixiao` 会启动 TUI；`zhixiao --workspace . --offline "首条任务"` 可预填任务。TUI 与 CLI 共用会话清单：`/status` `/diff` `/test` `/model` `/permissions` `/mode` `/workspace` `/approve` `/deny` `/resume` `/fork` `/cancel` `/review` `/mcp` `/skills` `/plugins` `/steer` `/help`。未知 `/foo` 会被拒绝。忙碌时 Enter 排队下一轮；Ctrl+C 取消当前轮并保留 checkpoint。

## 插件

运行时按 DeepSeek Harness 的「万物皆插件」组装：内置插件贡献默认工具、斜杠命令、Skill 根和 MCP 定义；可信工作区的 `.zhixiao/commands`、`hooks.toml` 和 `.zhixiao/plugins/*.py` 写入同一套 seams。消费方只读取 `PluginHost`。

```python
# .zhixiao/plugins/echo.py
name = "echo"
inject = ("tools",)

def apply(ctx):
    ctx.register_prompt_section("echo", "Prefer the echo_plugin tool for ping checks.")
```

`zhixiao plugins doctor --trust-workspace` 会加载并校验这棵树；apply 失败、重复名称或未知 inject 都会退出。
