# 部署手册

## Compose 部署

```bash
cp .env.example .env
# 必须替换数据库密码、JWT_SECRET、WORKER_CALLBACK_TOKEN、
# WORKER_JOB_SIGNING_SECRET（与 callback token 不同）及模型配置
docker compose -f infra/docker-compose.yml config --quiet
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
```

地址：Web `http://localhost:5173`，API `http://localhost:8000`，OpenAPI `http://localhost:8000/docs`。MySQL、Redis、Chroma、Milvus、MinIO、etcd 与 Neo4j 默认不暴露宿主端口。

API 容器在启动 Uvicorn 前运行 `alembic upgrade head`。Web 健康检查为 `/health`，API 健康检查为 `:8000/health`；数据服务均配置健康检查，依赖服务只有健康后才启动下游。

Worker 的 checkpoint 位于共享卷 `/workspace/runs/.zhixiao-state`（由 `ZHIXIAO_STATE_DIR` 指定），因此容器使用只读根文件系统时仍可恢复运行。`RUNNER_ROOT`、`WORKSPACE_BASE` 和 `WORKSPACE_SOURCE_ROOTS` 必须指向受管挂载；API 与 Worker 都会拒绝越界路径。该目录属于运行状态，不得提交到 Git 或作为任务仓库制品发布。

## 模型配置

Worker 执行真实任务前必须设置 `LLM_API_KEY`，以及相应的 `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_BASE`。支持任何 OpenAI-compatible 端点。没有密钥时可构建和运行静态/API 门禁，但不能把模型任务标记为成功。

## Runner 选择

- `bubblewrap`：Linux/Compose 默认；只挂载运行时目录与当前 workspace，隔离网络和其他任务目录。
- `local`：仅限可信本地开发。`execute/full` 默认拒绝 local；临时调试必须显式设置 `ALLOW_UNSANDBOXED_LOCAL_EXECUTION=true`，生产禁止设置。
- `docker`：适合未知仓库，通过只读/读写挂载、网络、CPU、内存、进程、临时盘、writable layer 和超时限制提供更强隔离。默认 `--storage-opt size=2g` 只在支持该选项的 Docker storage driver 生效；不支持时必须使用受配额 volume/driver 后再启用未知仓库执行。

Compose 中的 Worker 自身处于受限容器。若选择嵌套 Docker Runner，必须以受控方式提供独立 Docker 代理；不要直接暴露生产宿主机的无限制 Docker socket。

## 升级与回滚

1. 备份 MySQL、Redis AOF、向量库、Neo4j 与 artifacts。
2. 拉取固定 tag，执行 `docker compose ... config --quiet` 和镜像构建。
3. 查看 migration SQL，在维护窗口滚动更新。
4. 验证 API/Web 健康、SSE 重连和一个只读任务。
5. 应用回滚使用前一固定 tag；数据库回滚仅在 migration 明确支持且已备份时执行。

向量迁移遵循源校验、双写、灰度切读、目标校验、停止双写的顺序。回滚只切回源读取，不先删除目标数据。

## Docker daemon 不可用时的本地校验

```bash
python -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('infra/docker-compose.yml').read_text())"
python -m unittest discover -s tests/evals -p "test_*.py"
```

这只能证明 YAML 与评测清单可解析，不能替代 Compose 服务健康与容器网络验证。完整证据来自 CI 的 `containers` 和 `Full integration` 工作流。

## 运维排查

```bash
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs --tail=200 api worker
docker compose -f infra/docker-compose.yml exec mysql mysqladmin ping -h localhost
docker compose -f infra/docker-compose.yml exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" ping'
```

日志中不得输出 Prompt 原文中的秘密、模型密钥或训练样本。故障制品只保存必要摘要与可重试方法。
