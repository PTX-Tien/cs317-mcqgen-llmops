#!/bin/bash
# MCQGen System Stop (no Docker)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"

API_PORT=${API_PORT:-8080}
WEBAPP_PORT=${WEBAPP_PORT:-8081}
VLLM_PORT=${VLLM_PORT:-7681}
REDIS_PORT=${REDIS_PORT:-6379}

echo "Stopping MCQGen system..."

stop_proc() {
    local pattern=$1 label=$2
    if pkill -f "$pattern" 2>/dev/null; then
        echo "  ✅ $label stopped"
    fi
}

stop_port() {
    local port=$1 label=$2
    if command -v fuser >/dev/null 2>&1 && fuser -n tcp "$port" >/dev/null 2>&1; then
        fuser -k -n tcp "$port" >/dev/null 2>&1 \
            && echo "  ✅ $label listener on :$port stopped"
    fi
}

stop_proc "uvicorn.*api.main.*--port $API_PORT"   "FastAPI"
stop_port "$API_PORT"                              "FastAPI"
stop_proc "celery.*mcqgen.*worker"                 "Celery workers"
stop_proc "next .* -p $WEBAPP_PORT"                "Next.js"
stop_proc "next .*--port $WEBAPP_PORT"             "Next.js"
stop_proc "node .*next.* -p $WEBAPP_PORT"          "Next.js"
stop_proc "node .*next.*--port $WEBAPP_PORT"       "Next.js"
stop_proc "next-server.*$PROJECT/webapp"           "Next.js server"
stop_port "$WEBAPP_PORT"                           "Next.js"
stop_proc "vllm serve.*--port $VLLM_PORT"          "vLLM"

# Redis: shutdown graceful, không tắt nếu có service khác dùng
if redis-cli -p $REDIS_PORT ping 2>/dev/null | grep -q PONG; then
    redis-cli -p $REDIS_PORT shutdown nosave 2>/dev/null \
        && echo "  ✅ Redis stopped" \
        || echo "  ⚠️  Redis shutdown failed (có thể đang dùng bởi service khác)"
fi

echo "Done."
