# 安全模型

## 信任边界

用户 Prompt、任务仓库内容、网页内容、模型输出和 MCP 返回值都不可信。API 身份与空间成员关系决定控制面权限；Runner 的 workspace 根路径决定文件系统边界；命令策略与审批记录决定执行权限。模型不能自行扩大权限。

## 权限模式

| 模式 | 允许能力 |
|---|---|
| `read_only` | 浏览、读取、搜索、Git status/diff |
| `edit` | read_only + 工作区内精确编辑/写入 |
| `execute` | read_only + 受策略限制的本地命令与测试 |
| `full` | edit + execute；危险命令、网络、发布仍需单独审批 |

路径解析必须落在已解析的 workspace 根目录内，拒绝 `..`、符号链接逃逸与外部绝对路径。命令有允许/拒绝策略、超时和进程树终止。Git commit、push、PR、破坏性命令与联网执行即使处于 `full` 也不能隐式批准。

## 沙箱与容器

Compose 中 API、Worker 与 Web 使用只读根文件系统、限额临时目录、进程/CPU/内存限制和 `no-new-privileges`。任务 workspace 与 artifacts 是显式挂载。Docker Runner 进一步限制网络、挂载和 writable layer 大小（默认 2 GiB）；`--storage-opt size` 依赖 Docker storage driver 支持，不支持时必须改用受配额 volume/driver，不能静默取消磁盘门禁。Local Runner 依靠路径边界、命令策略与超时，不等价于强隔离，处理未知恶意仓库时应优先 Docker Runner。

## 密钥与隐私

- 只提交 `.env.example`，真实 `.env`、密钥和令牌由运行环境注入。
- 日志、事件和训练数据进入持久化前执行去敏；不得上传任务仓库源码、模型权重或未审查数据。
- ModelProfile 只保存 provider/model/base URL 和密钥引用，不保存明文密钥。
- 训练导出必须去敏、去重、划分训练/验证集，并记录数据来源与审查人。

## 发布与审计

默认只生成 diff。commit、push、PR 和 Release 是独立审批动作，记录发起者、范围、决策、时间和结果。失败与拒绝同样进入时间线。发现漏洞时不要在公开 Issue 附带密钥或可利用细节；先私下通知仓库所有者并附最小复现和影响范围。

## 发布前检查

```bash
rg -n "(BEGIN .*PRIVATE KEY|api[_-]?key\s*=|password\s*=)" --glob "!*.example" --glob "!package-lock.json"
python -m bandit -q -r apps/api/app packages/agent_core/src -lll -ii
npm audit --omit=dev --audit-level=high --prefix apps/web
```
