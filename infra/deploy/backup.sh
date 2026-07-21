#!/usr/bin/env bash
# 智效工坊 备份脚本 - MySQL + Redis + Chroma 一起打包
# 用法：bash deploy/backup.sh [out_dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${1:-${PROJECT_ROOT}/backups}"
mkdir -p "${OUT_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"

# MySQL 转储
echo "📦 备份 MySQL..."
docker compose --project-directory "${PROJECT_ROOT}" exec -T mysql \
  mysqldump -uroot -p"${MYSQL_ROOT_PASSWORD}" --single-transaction \
  --routines --triggers --events "${MYSQL_DATABASE}" \
  > "${OUT_DIR}/mysql_${TS}.sql"

# Redis 落盘后拷贝 dump
echo "📦 备份 Redis（RDB快照）..."
docker compose --project-directory "${PROJECT_ROOT}" exec -T redis \
  redis-cli -a "${REDIS_PASSWORD:-}" BGSAVE >/dev/null 2>&1 || true
sleep 3
docker compose --project-directory "${PROJECT_ROOT}" cp redis:/data/dump.rdb \
  "${OUT_DIR}/redis_${TS}.rdb" 2>/dev/null || echo "⚠ Redis 拷贝跳过"

# Chroma 数据卷
echo "📦 备份 Chroma ..."
docker run --rm -v "$(docker volume inspect zhixiao_chroma_data --format '{{.Name}}')" \
  -v "${OUT_DIR}:/backup" alpine \
  sh -c "tar -C /data -czf /backup/chroma_${TS}.tar.gz ." 2>/dev/null || \
  echo "⚠ Chroma 备份跳过（卷名可能不一致）"

# 保留最近 7 份
echo "🧹 清理 7 天前的备份..."
find "${OUT_DIR}" -maxdepth 1 -type f -mtime +7 -delete

echo "✅ 备份完成: ${OUT_DIR}/*_${TS}*"

# ---- 恢复方法（写在说明里）----
# 1) MySQL: mysql -u <USER> -p < DB < mysql_<TS>.sql
# 2) Redis: 停 redis -> 替换 /data/dump.rdb -> 重启
# 3) Chroma: tar -C <vol path> -xzf chroma_<TS>.tar.gz