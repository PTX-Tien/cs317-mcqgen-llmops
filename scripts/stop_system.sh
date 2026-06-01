#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"

API_PORT=${API_PORT:-8080}
WEBAPP_PORT=${WEBAPP_PORT:-8081}
PHOENIX_PORT=${PHOENIX_PORT:-8082}
VLLM_PORT=${VLLM_PORT:-7681}

echo "Stopping MCQGen system..."
pkill -f "uvicorn.*api.main.*--port $API_PORT" 2>/dev/null && echo "  ✅ FastAPI stopped"
pkill -f "celery.*worker"                     2>/dev/null && echo "  ✅ Celery stopped"
pkill -f "phoenix.server.*--port $PHOENIX_PORT" 2>/dev/null && echo "  ✅ Phoenix stopped"
pkill -f "next.*$PROJECT/webapp"              2>/dev/null && echo "  ✅ Next.js stopped"
pkill -f "next-server.*$PROJECT/webapp"       2>/dev/null && echo "  ✅ Next.js server stopped"
pkill -f "next.*--port $WEBAPP_PORT"          2>/dev/null && echo "  ✅ Next.js port $WEBAPP_PORT stopped"
pkill -f "vllm serve.*--port $VLLM_PORT"      2>/dev/null && echo "  ✅ vLLM stopped"
redis-cli shutdown                            2>/dev/null && echo "  ✅ Redis stopped"
echo "Done."
