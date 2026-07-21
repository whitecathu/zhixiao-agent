# 演示脚本

目标是完成一次真实跨栈任务并展示可审计证据，不预先声明任务成功。

## 准备

1. 使用不含秘密的演示仓库，确认初始测试通过并记录 commit SHA。
2. 配置模型密钥，启动 Compose，确认 Web/API 健康。
3. 在 Web 创建空间与 Repository，路径必须位于 `/workspace/runs`。
4. 选择 `edit` 权限；命令执行时再单独批准 `execute`，不批准 commit/push。

## Web 演示

Prompt：

> 为示例应用增加任务标签：数据库迁移、FastAPI 请求/响应、Vue 列表展示和测试必须同步完成；先给计划，批准后实现，测试失败时修复，最后只交付 diff。

演示顺序：

1. 查看仓库探测、目录级 `AGENTS.md` 和任务路由结果。
2. 审查计划、文件范围与预计测试，批准计划。
3. 查看独立 worktree、Todo、工具输入输出和实时终端。
4. 若测试失败，查看根因、修复轮次与重跑结果。
5. 在 Diff、测试与制品页核对 migration、API、前端类型/页面和 E2E。
6. 下载 diff，在全新 worktree 中应用并重跑测试。
7. 保持 commit/push 未批准，证明默认只交付 diff。

## CLI 演示

```bash
zhixiao run \
  --workspace /path/to/demo-repo \
  --permission execute \
  --prompt "修复分页边界缺陷，补回归测试并只输出可应用 diff"
```

记录退出码、run id、测试报告路径和 diff SHA-256。中途发送中断，再以同一 run id 恢复，确认事件序号连续且已消费事件不会重复执行。

## 通过标准

- diff 可在干净基线应用，无工作区外修改。
- 目标测试与全量回归通过；不能运行的门禁有具体原因和复现命令。
- Web 和 CLI 都显示一致的 run id、终态与制品。
- 未经批准没有 commit、push、PR 或外部网络副作用。
- 只把实际运行结果写入评测文件，不在演示稿中填估算百分比。
