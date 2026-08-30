# 演示脚本

先证明 harness（边界、插件、离线 JSON、协同中断），再视环境决定是否跑真实模型和 Compose。第一条路径不需要 Docker，也不需要模型密钥。

中断停的是 **LangGraph 工具循环**（`interrupt({"kind":"operator_stop"})`），不只是把本地清单标成 `interrupted`。同一 `run_id` 可以 `resume`。脚本化证明见行为门禁 `interrupt-resume`（`tests/evals/run_behavioral.py`，ScriptedModel），不要用 fixture 里的完成率代替。

## 1. 五分钟无 Docker CLI（主路径）

```bash
python -m venv .venv
pip install -e "packages/agent_core[dev,cli]"

# 换成任意空目录
tmp="$(mktemp -d)"
# Windows PowerShell:
# $tmp = Join-Path $env:TEMP ("zx-" + [guid]::NewGuid().ToString("n"))
# New-Item -ItemType Directory -Path $tmp | Out-Null

zhixiao doctor --json
zhixiao plugins list
zhixiao plugins doctor --workspace "$tmp"
zhixiao run "Inspect this workspace without modifying it" \
  --workspace "$tmp" \
  --offline \
  --permission read_only \
  --approval-policy never \
  --output-format json \
  --events none

python tests/evals/run_behavioral.py
```

现场讲解：

1. `doctor` / `plugins doctor`：环境与 PluginHost 可组装；未信任工作区不会加载 `.zhixiao/plugins`。
2. 离线 JSON：`RunResult` 含 `verification`、`termination_reason`、`usage`；不要把 `verification.outcome=skipped` 说成「已通过」。
3. 打开 `run_behavioral.py` 的 `eval_interrupt_resume`：第二次模型回合写入 `{state_dir}/control/{run_id}` → runtime unlink → `interrupt(operator_stop)` → 同一 run_id `resume` 后跑完。这就是「中断停工具循环、可恢复」的可复现证据。
4. 同脚本的 `dangerous-command`、`ask-read-only`：无审批不执行 `git push` / `rm -rf`；`ask` 模式即使权限是 `edit` 也不开放写工具。

可选口头补充（不必当场对 live 进程发信号）：`zhixiao interrupt <run-id>` 只负责写控制文件并更新清单；真正暂停循环的是 runtime 里的 LangGraph interrupt。

## 2. 可选：真实模型 CLI

需要 `LLM_API_KEY`（或当前 settings 对应的密钥环境变量）和一个不含秘密的演示仓库。

```bash
zhixiao run \
  --workspace /path/to/demo-repo \
  --permission execute \
  --prompt "修复分页边界缺陷，补回归测试并只输出可应用 diff"
```

记录退出码、run id、测试报告路径和 diff SHA-256。长任务中途可另开终端 `zhixiao interrupt <run-id>`，再 `zhixiao resume <run-id>`。若现场来不及跑完，退回第 1 节的行为门禁，不要假装 live 已成功。

## 3. 可选：Compose / Web

1. 使用不含秘密的演示仓库，确认初始测试通过并记录 commit SHA。
2. 配置模型密钥，启动 Compose，确认 Web/API 健康（本机无 Docker 时跳过，以 GitHub Actions 容器作业为准）。
3. 在 Web 创建空间与 Repository，路径必须位于 `/workspace/runs`。
4. 选择 `edit` 权限；命令执行时再单独批准 `execute`，不批准 commit/push。

Prompt 示例：

> 为示例应用增加任务标签：数据库迁移、FastAPI 请求/响应、Vue 列表展示和测试必须同步完成；先给计划，批准后实现，测试失败时修复，最后只交付 diff。

演示顺序：

1. 查看仓库探测、目录级 `AGENTS.md`。路由事件里的 planner/explorer 是标签，不是四个独立 Agent。
2. 审查计划、文件范围与预计测试，批准计划（LangGraph interrupt，SQLite checkpoint）。
3. 查看独立 worktree、Todo、工具输入输出和实时终端。
4. 任务页「运行证据」条：权限模式、验证结果（缺失显示「未回报」）、终止原因、用量；不要把空 verification 说成已通过。
5. 若测试失败，查看根因、修复轮次与重跑结果。
6. 下载 diff，在全新 worktree 中应用并重跑测试。
7. 保持 commit/push 未批准，证明默认只交付 diff。

Playwright 只覆盖容器内 Web UI 烟测，不能当作「真实编码 Agent 已完成跨栈任务」的证据。

## 通过标准

- 第 1 节命令可复制执行；`run_behavioral.py` 三门禁通过。
- 有 live/Web 时：diff 可在干净基线应用，无工作区外修改；未经批准没有 commit、push、PR 或外部网络副作用。
- 只把实际运行结果写入评测文件，不在演示稿中填估算百分比，不引用 fixture 的 task_completion_rate / hallucination_rate。
