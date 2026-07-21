#!/usr/bin/env bash
# 简易监控：探测核心服务存活并写入日志，便于接告警
# 用法：bash deploy/monitor.sh
set -euo pipefail

LOG_FILE=/var/log/zhixiao/monitor.log
mkdir -p "$(dirname "${LOG_FILE}")"
INTERVAL_SEC=${MONITOR_INTERVAL:-30}

check() {
  local name=$1 url=$2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${url}" || echo "000")
  echo "$(date '+%F %T') ${name} ${url} -> ${code}" >> "${LOG_FILE}"
  if [[ "${code}" != "200" ]]; then
    # 真实生产应转发到钉钉/Prometheus Alertmanager
    echo "$(date '+%F %T') ⚠ ${name} 异常: HTTP ${code}"
  fi
}

while true; do
  check frontend http://localhost:${WEB_PORT_PUBLISH:-80}/health
  check backend  http://localhost:${BACKEND_PORT_PUBLISH:-8000}/health
  check ai       http://localhost:${AI_PORT_PUBLISH:-8001}/health
  sleep "${INTERVAL_SEC}"
done