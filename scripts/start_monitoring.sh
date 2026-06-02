#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT/logs"
LOG_FILE="$LOG_DIR/grafana.log"

mkdir -p "$LOG_DIR"

GRAFANA_PORT=${GRAFANA_PORT:-8082}
PROMETHEUS_PORT=${PROMETHEUS_PORT:-8084}
DCGM_EXPORTER_PORT=${DCGM_EXPORTER_PORT:-9400}
START_DCGM_EXPORTER=${START_DCGM_EXPORTER:-1}
MCQGEN_MONITORING_PROJECT=${MCQGEN_MONITORING_PROJECT:-mcqgen-monitoring}
COMPOSE_FILE="$PROJECT/monitoring/docker-compose.yml"

compose_cmd() {
    GRAFANA_PORT="$GRAFANA_PORT" \
    PROMETHEUS_PORT="$PROMETHEUS_PORT" \
    DCGM_EXPORTER_PORT="$DCGM_EXPORTER_PORT" \
    docker compose \
        --project-name "$MCQGEN_MONITORING_PROJECT" \
        -f "$COMPOSE_FILE" \
        "$@"
}

write_status() {
    echo "### Monitoring compose status"
    compose_cmd ps || true
    echo
    echo "### Grafana logs"
    compose_cmd logs --no-color --tail=160 grafana || true
    echo
    echo "### Prometheus logs"
    compose_cmd logs --no-color --tail=160 prometheus || true
    echo
    echo "### DCGM exporter logs"
    compose_cmd logs --no-color --tail=160 dcgm-exporter || true
}

if [ "${1:-}" = "--logs-only" ]; then
    write_status
    exit 0
fi

{
    echo "[$(date '+%F %T')] Starting MCQGen monitoring stack"
    echo "Project: $MCQGEN_MONITORING_PROJECT"
    echo "Grafana: host port $GRAFANA_PORT"
    echo "Prometheus: host port $PROMETHEUS_PORT"
    echo "DCGM exporter: host port $DCGM_EXPORTER_PORT | enabled=$START_DCGM_EXPORTER"
    echo

    compose_cmd up -d prometheus grafana
    if [ "$START_DCGM_EXPORTER" = "1" ] || [ "$START_DCGM_EXPORTER" = "true" ]; then
        compose_cmd up -d dcgm-exporter || {
            echo
            echo "Warning: DCGM exporter failed to start. Grafana/Prometheus can still run without GPU metrics."
            echo "If this server lacks NVIDIA Container Runtime, set START_DCGM_EXPORTER=0."
        }
    fi
    echo
    write_status
} > "$LOG_FILE" 2>&1
