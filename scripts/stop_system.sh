#!/bin/bash
echo "Stopping MCQGen system..."
pkill -f "uvicorn.*api.main" 2>/dev/null && echo "  ✅ FastAPI stopped"
pkill -f "celery.*worker"    2>/dev/null && echo "  ✅ Celery stopped"
pkill -f "phoenix.server"    2>/dev/null && echo "  ✅ Phoenix stopped"
pkill -f "next.*3000"        2>/dev/null && echo "  ✅ Next.js stopped"
pkill -f "vllm serve"        2>/dev/null && echo "  ✅ vLLM stopped"
redis-cli shutdown           2>/dev/null && echo "  ✅ Redis stopped"
echo "Done."
