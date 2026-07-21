#!/usr/bin/env bash
# 智效工坊 一键部署脚本
# 用法：bash deploy/deploy.sh [dev|test|prod]

set -euo pipefail

ENV="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env.${ENV}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ 找不到环境配置 ${ENV_FILE}，请先复制 .env.example 并填写"
  exit 1
fi

# 1. 拷贝 ENV 文件
cp -f "${ENV_FILE}" "${PROJECT_ROOT}/.env"
echo "✅ 已加载 ${ENV} 配置"

# 2. DB / Redis / Chroma 起来后再跑迁移
echo "🐳 启动数据层..."
docker compose --project-directory "${PROJECT_ROOT}" up -d mysql redis chroma
echo "⏳ 等数据层健康..."
for _ in {1..60}; do
  if docker compose --project-directory "${PROJECT_ROOT}" exec -T mysql \
       mysqladmin ping -p"$MYSQL_ROOT_PASSWORD" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# 3. 构建与启动 backend / ai / frontend
echo "🏗️  构建与启动业务容器..."
docker compose --project-directory "${PROJECT_ROOT}" build
docker compose --project-directory "${PROJECT_ROOT}" up -d

# 4. 后端迁移
echo "📦 运行数据库迁移..."
docker compose --project-directory "${PROJECT_ROOT}" exec -T \
  backend alembic upgrade head || echo "⚠ 迁移可能尚未就绪，稍后可手动执行"

# 5. 健康检查
echo "🩺 健康检查..."
sleep 5
curl -fsS http://localhost:${WEB_PORT_PUBLISH:-80}/health && echo " frontend ✅"
curl -fsS http://localhost:${BACKEND_PORT_PUBLISH:-8000}/health && echo " backend ✅"

echo "🎉 部署完成：前端 http://localhost:${WEB_PORT_PUBLISH:-80}"
echo "   API 文档 http://localhost:${BACKEND_PORT_PUBLISH:-8000}/docs"