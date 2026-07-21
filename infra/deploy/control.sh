#!/usr/bin/env bash
# 服务启停 / 状态 / 日志通用脚本
# 用法：bash deploy/control.sh [start|stop|restart|status|logs <name>]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

CMD="${1:-status}"
SVC="${2:-}"

case "${CMD}" in
  start)   docker compose up -d ;;
  stop)    docker compose down ;;
  restart) docker compose restart "${SVC}" ;;
  status)  docker compose ps ;;
  logs)    docker compose logs -f --tail=300 "${SVC}" ;;
  ps)      docker compose ps ;;
  *) echo "用法: $0 {start|stop|restart|status|logs <svc>}"; exit 1 ;;
esac