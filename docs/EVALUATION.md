# 评测方法

## 固定场景集

`tests/evals/scenarios.json` 固定八类工程任务：Python 缺陷、FastAPI 契约、Vue 页面、补测试、跨栈功能、测试失败自修复、暂停恢复和危险命令审批。每个场景定义权限、断言与必需制品，场景版本随 schema/version 记录。

```bash
python tests/evals/run_scenarios.py --validate-only --output evaluation-manifest.json
```

该命令只校验清单，报告 `status=manifest_validated` 且 `metrics=null`。它不能证明 Agent 完成了场景。

## 离线门禁（Fixture）

CI 运行 `run_offline_gates.py`，使用仓库内固定 fixture 检查报告管线与安全策略。其结果必须标记为：

```json
{
  "status": "offline_harness",
  "evaluation_mode": "offline_fixture",
  "metrics_source": "fixture"
}
```

这些指标只描述确定性 fixture，不是模型实测值，不能用于声明在线 Agent 的任务完成率、延迟或质量。

## 在线评测（Live）

对真实模型跑场景（默认关闭；CI 不得设置 `ZHIXIAO_LIVE_EVAL`）：

```bash
ZHIXIAO_LIVE_EVAL=1 LLM_API_KEY=... python tests/evals/run_live.py \
  --output artifacts/evaluation/live_results.json
python tests/evals/run_scenarios.py \
  --results artifacts/evaluation/live_results.json \
  --output artifacts/evaluation/live_report.json
```

未设置 `ZHIXIAO_LIVE_EVAL=1` 或缺少 `LLM_API_KEY` 时进程以退出码 2 结束，且不会调用 Offline/Scripted 模型冒充 live。可选 `LLM_INPUT_COST_PER_MILLION` / `LLM_OUTPUT_COST_PER_MILLION` 用于成本字段。

## 真实结果格式

Live 运行器输出 `status=live`、`evaluation_mode=live`、`metrics_source=live_agent_runtime`，并为每个场景记录结果：

```json
{
  "status": "live",
  "evaluation_mode": "live",
  "metrics_source": "live_agent_runtime",
  "results": [
    {
      "scenario_id": "python-bugfix",
      "passed": true,
      "attempts": 2,
      "latency_ms": 48321,
      "cost_usd": 0.084,
      "hallucination_rate": 0.0,
      "artifacts": ["diff", "test_report", "timeline"]
    }
  ]
}
```

文件必须覆盖全部场景且成功项包含所有必需证据：

```bash
python tests/evals/run_scenarios.py \
  --results artifacts/evaluation/results.json \
  --output artifacts/evaluation/report.json
```

## 指标定义

- 任务完成率：所有自动断言通过并具备必需制品的场景占比。
- 首次通过率：第一次实现后验证通过、未进入 repair 的场景占比。
- 重试数：Agent 工具/修复轮次，基础设施重试另列。
- 延迟：接收任务到终态的 wall-clock 时间。
- 成本：模型 provider 返回的输入/输出 token 计费合计。
- 幻觉率：无证据声明、虚构文件/接口/测试结果的审查项占比。
- 检索指标：固定知识查询的 recall@k、MRR、引用覆盖与证据链正确率。

报告必须保存运行版本、基线 SHA、模型配置、数据集版本、随机种子、权限、Runner 和环境信息。不同模型或路由的 A/B 对比使用同一场景与基线。

## 性能层级

- CI：内存/轻量后端和 1 万向量级功能/回归门禁。
- 手工基准：100 万向量、并发查询、p50/p95/p99、召回率、索引大小和构建时间。
- GPU：微型模型先验证数据到 adapter 的完整链路；7B/14B 在自托管 GPU 工作流运行并上传 adapter、配置、指标和模型卡。

微型训练通过不代表 7B/14B 质量或性能达标，1 万级检索也不能外推百万级数据。简历和复盘中的任何百分比必须能定位到不可变报告制品。
