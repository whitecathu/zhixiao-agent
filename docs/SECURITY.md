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

工作模式 `ask|plan|code|review`、审批策略和权限上限彼此独立。默认权限是 `read_only`、审批策略是 `on_request`；`--yes` 只批准启动计划。预算耗尽、重复根因、空响应或停滞属于失败终止，不能转换成成功。

未受信任 workspace 只允许只读任务，并忽略项目配置、hooks、自定义命令、项目 Skill 和 `.zhixiao/plugins`。只有用户配置中的可信路径或显式 `--trust-workspace` 才启用这些扩展；CI 中不得通过隐式当前目录信任绕过此门禁。工作区插件路径必须落在 workspace 内，apply 失败会终止加载。

## 沙箱与容器

Compose 中 API、Worker 与 Web 使用只读根文件系统、限额临时目录、进程/CPU/内存限制和 `no-new-privileges`。任务 workspace 与 artifacts 是显式挂载。Docker Runner 进一步限制网络、挂载和 writable layer 大小（默认 2 GiB）；`--storage-opt size` 依赖 Docker storage driver 支持，不支持时必须改用受配额 volume/driver，不能静默取消磁盘门禁。Local Runner 依靠路径边界、命令策略与超时，不等价于强隔离，处理未知恶意仓库时应优先 Docker Runner。

## 密钥与隐私

- 只提交 `.env.example`，真实 `.env`、密钥和令牌由运行环境注入。
- 日志、事件和训练数据进入持久化前执行去敏；不得上传任务仓库源码、模型权重或未审查数据。
- ModelProfile 只保存 provider/model/base URL 和密钥引用，不保存明文密钥。
- 用户/项目 CLI 配置和 MCP server 定义只保存环境变量名引用；`config show` 始终脱敏。
- MCP HTTP URL 拒绝 localhost、非公网 IP 和嵌入凭据；控制面 test 不执行命令、不访问网络，防止被当作命令执行或 SSRF 入口。
- 训练导出必须去敏、去重、划分训练/验证集，并记录数据来源与审查人。

## 发布与审计

默认只生成 diff。commit、push、PR 和 Release 是独立审批动作，记录发起者、范围、决策、时间和结果。失败与拒绝同样进入时间线。发现漏洞时不要在公开 Issue 附带密钥或可利用细节；先私下通知仓库所有者并附最小复现和影响范围。

写任务的终态还必须包含验证结论。只有 `passed` 或带非空原因的显式 waiver 可成功；`failed`、`blocked`、预算耗尽和未记录理由的 `skipped` 都不得通过完成门禁。

## 发布前检查

```bash
rg -n "(BEGIN .*PRIVATE KEY|api[_-]?key\s*=|password\s*=)" --glob "!*.example" --glob "!package-lock.json"
python -m bandit -q -r apps/api/app packages/agent_core/src -lll -ii
npm audit --omit=dev --audit-level=high --prefix apps/web
```
