#!/bin/bash
# MCQGen System Startup — Production grade

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR=$PROJECT/logs
LANGFUSE_ENV_FILE=$PROJECT/monitoring/langfuse/.env
mkdir -p $LOG_DIR
mkdir -p $PROJECT/redis_data
mkdir -p $PROJECT/tmp

source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2 2>/dev/null

export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1
# Qwen2.5-7B-Instruct full precision is larger than one RTX 2080 Ti.
# Use TP=4 so vLLM stays GPU-only. Override these two variables before running
# this script if you need a strict GPU split between vLLM and RAG workers.
export VLLM_CUDA_VISIBLE_DEVICES=${VLLM_CUDA_VISIBLE_DEVICES:-2,3,4,7}
export TASK_CUDA_VISIBLE_DEVICES=${TASK_CUDA_VISIBLE_DEVICES:-4,7}
export HF_HOME=/mmlab_students/storageStudents/nguyenvd/Thanhld/.cache/huggingface
export HF_HUB_OFFLINE=0

# Latency-first defaults for Qwen2.5-7B-Instruct on RTX 2080 Ti.
# TP=4 avoids CPU offload; keep per-GPU reservation low because GPUs are shared.
export VLLM_TENSOR_PARALLEL_SIZE=${VLLM_TENSOR_PARALLEL_SIZE:-4}
export VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-5000}
export VLLM_MAX_NUM_SEQS=${VLLM_MAX_NUM_SEQS:-4}
export VLLM_GPU_MEMORY_UTILIZATION=${VLLM_GPU_MEMORY_UTILIZATION:-0.9}
export VLLM_CPU_OFFLOAD_GB=${VLLM_CPU_OFFLOAD_GB:-0}
export VLLM_TIMEOUT=${VLLM_TIMEOUT:-180}
export VLLM_MAX_RETRIES=${VLLM_MAX_RETRIES:-1}
export START_VLLM=${START_VLLM:-0}
export VLLM_WAIT_SECONDS=${VLLM_WAIT_SECONDS:-0}
export MCQGEN_MAX_CONCURRENT_QUESTIONS=${MCQGEN_MAX_CONCURRENT_QUESTIONS:-4}
export MCQGEN_LLM_MAX_CONCURRENCY=${MCQGEN_LLM_MAX_CONCURRENCY:-$VLLM_MAX_NUM_SEQS}
export VLLM_PORT=${VLLM_PORT:-7681}
export VLLM_URL=${VLLM_URL:-http://localhost:${VLLM_PORT}/v1}
export VLLM_MODEL=mcqgen
export API_PORT=${API_PORT:-8080}
export WEBAPP_PORT=${WEBAPP_PORT:-8081}
export PHOENIX_PORT=${PHOENIX_PORT:-8082}
export PHOENIX_GRPC_PORT=${PHOENIX_GRPC_PORT:-4319}
export LANGFUSE_PORT=${LANGFUSE_PORT:-8083}

VLLM_CPU_OFFLOAD_ARGS=""
if [ "$VLLM_CPU_OFFLOAD_GB" != "0" ] && [ "$VLLM_CPU_OFFLOAD_GB" != "0.0" ]; then
    VLLM_CPU_OFFLOAD_ARGS="--cpu-offload-gb $VLLM_CPU_OFFLOAD_GB"
fi

cd $PROJECT

# ── Utility functions ─────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }

usage() {
    cat <<EOF
Usage: bash scripts/start_system.sh [--with-vllm|--no-vllm]

Options:
  --with-vllm  Start local vLLM on VLLM_PORT=${VLLM_PORT}.
  --no-vllm    Skip local vLLM startup. Useful for UI/API work.

Env:
  START_VLLM=1            Same as --with-vllm.
  VLLM_WAIT_SECONDS=180   Wait up to N seconds for /health when vLLM is enabled.
  WEBAPP_PORT=8081        Next.js UI port.
  PHOENIX_PORT=8082       Phoenix monitor port.
  PHOENIX_GRPC_PORT=4319  Phoenix OTLP/gRPC port.
  LANGFUSE_PORT=8083      LangFuse web port.
EOF
}

is_enabled() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

for arg in "$@"; do
    case "$arg" in
        --with-vllm|--start-vllm)
            export START_VLLM=1
            ;;
        --no-vllm|--skip-vllm)
            export START_VLLM=0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            usage
            exit 2
            ;;
    esac
done

# Loop cho đến khi lệnh thành công, không timeout
wait_until() {
    local label=$1
    local cmd=$2
    log "⏳ Waiting for $label..."
    while true; do
        if eval "$cmd" >/dev/null 2>&1; then
            log "✅ $label is ready"
            return 0
        fi
        sleep 3
    done
}

wait_with_timeout() {
    local label=$1
    local cmd=$2
    local timeout=$3
    local elapsed=0

    if [ "$timeout" -le 0 ]; then
        return 1
    fi

    log "⏳ Waiting up to ${timeout}s for $label..."
    while [ "$elapsed" -lt "$timeout" ]; do
        if eval "$cmd" >/dev/null 2>&1; then
            log "✅ $label is ready"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    return 1
}

# Start một service nếu chưa chạy
start_bg() {
    local label=$1
    local check_cmd=$2
    local run_cmd=$3
    local logfile=$4

    if eval "$check_cmd" >/dev/null 2>&1; then
        log "✅ $label already running — skip"
    else
        log "🚀 Starting $label..."
        setsid bash -lc "$run_cmd" > "$logfile" 2>&1 < /dev/null &
        log "   PID=$! | log=$logfile"
    fi
}

log "════════════════════════════════════"
log "🚀 MCQGen System Starting"
if is_enabled "$START_VLLM"; then
    log "vLLM startup=enabled | GPUs=$VLLM_CUDA_VISIBLE_DEVICES | port=$VLLM_PORT"
    log "vLLM max_model_len=$VLLM_MAX_MODEL_LEN max_num_seqs=$VLLM_MAX_NUM_SEQS | question_concurrency=$MCQGEN_MAX_CONCURRENT_QUESTIONS llm_concurrency=$MCQGEN_LLM_MAX_CONCURRENCY"
else
    log "vLLM startup=skipped | use --with-vllm or START_VLLM=1 for full generation"
fi
log "task GPUs=$TASK_CUDA_VISIBLE_DEVICES"
log "════════════════════════════════════"

# ── STEP 1: Redis (synchronous — phải ready trước) ───────────────
log "[1/7] Redis..."
if redis-cli ping 2>/dev/null | grep -q PONG; then
    log "✅ Redis already running"
else
    redis-server \
        --port 6379 --daemonize yes \
        --logfile $LOG_DIR/redis.log \
        --dir $PROJECT/redis_data
fi
wait_until "Redis" "redis-cli ping 2>/dev/null | grep -q PONG"

# ── STEP 2: Start PARALLEL — optional vLLM + Phoenix + Next.js ───
log "[2/7] Starting services in parallel..."

# vLLM
if is_enabled "$START_VLLM"; then
    start_bg "vLLM" \
        "curl -s http://localhost:$VLLM_PORT/health" \
        "env CUDA_VISIBLE_DEVICES=$VLLM_CUDA_VISIBLE_DEVICES vllm serve models/Qwen2.5-7B-Instruct \
            --dtype half \
            --tensor-parallel-size $VLLM_TENSOR_PARALLEL_SIZE \
            --max-model-len $VLLM_MAX_MODEL_LEN \
            --gpu-memory-utilization $VLLM_GPU_MEMORY_UTILIZATION \
            $VLLM_CPU_OFFLOAD_ARGS \
            --enforce-eager --enable-prefix-caching \
            --disable-log-requests \
            --max-num-seqs $VLLM_MAX_NUM_SEQS --port $VLLM_PORT --host 0.0.0.0 \
            --served-model-name mcqgen" \
        "$LOG_DIR/vllm.log"
else
    log "⏭️ vLLM startup skipped"
fi

# Phoenix
start_bg "Phoenix" \
    "curl -s http://localhost:$PHOENIX_PORT/healthz" \
    "env TMPDIR=$PROJECT/tmp PHOENIX_GRPC_PORT=$PHOENIX_GRPC_PORT python -m phoenix.server.main serve --port $PHOENIX_PORT --host 0.0.0.0" \
    "$LOG_DIR/phoenix.log"

# Next.js frontend
start_bg "Next.js" \
    "curl -s http://localhost:$WEBAPP_PORT" \
    "bash -lc 'cd $PROJECT/webapp && npm run dev -- --hostname 0.0.0.0 --port $WEBAPP_PORT'" \
    "$LOG_DIR/nextjs.log"

# ── STEP 3: Celery — chỉ cần Redis (đã ready) ───────────────────
log "[3/7] Celery worker..."
pkill -f "celery.*worker" 2>/dev/null || true
sleep 2
setsid bash -lc "CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES celery -A api.tasks worker \
    --loglevel=info --concurrency=1 --prefetch-multiplier=1 -Ofair \
    -n worker1@%h" \
    > "$LOG_DIR/celery.log" 2>&1 < /dev/null &
log "   PID=$! | log=$LOG_DIR/celery.log"

# ── STEP 4: FastAPI — chỉ cần Redis (đã ready) ──────────────────
log "[4/7] FastAPI..."
pkill -f "uvicorn.*api.main" 2>/dev/null || true
sleep 2
setsid bash -lc "CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES uvicorn api.main:app \
    --host 0.0.0.0 --port $API_PORT" \
    > "$LOG_DIR/fastapi.log" 2>&1 < /dev/null &
log "   PID=$! | log=$LOG_DIR/fastapi.log"

# ── STEP 5: Optional vLLM health check ───────────────────────────
log "[5/7] vLLM status..."

if is_enabled "$START_VLLM"; then
    if curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
        log "✅ vLLM is ready"
    elif wait_with_timeout "vLLM" "curl -s http://localhost:$VLLM_PORT/health" "$VLLM_WAIT_SECONDS"; then
        true
    elif pgrep -f "vllm serve.*--port $VLLM_PORT" >/dev/null 2>&1; then
        log "⏳ vLLM is still loading — continuing startup | log=$LOG_DIR/vllm.log"
    else
        log "⚠️ vLLM failed to start — continuing startup | log=$LOG_DIR/vllm.log"
    fi
else
    log "⏭️ vLLM skipped"
fi

# ── STEP 6: LangFuse (Docker) ────────────────────────────────────
log "[6/7] LangFuse..."
bash "$PROJECT/scripts/start_langfuse.sh" > "$LOG_DIR/langfuse.log" 2>&1 \
    && log "✅ LangFuse startup submitted | log=$LOG_DIR/langfuse.log" \
    || log "⚠️ LangFuse startup failed | log=$LOG_DIR/langfuse.log"
LANGFUSE_PORT=$(sed -n 's/^LANGFUSE_PORT=//p' "$LANGFUSE_ENV_FILE" 2>/dev/null | tail -n 1)
LANGFUSE_PORT=${LANGFUSE_PORT:-8083}

# ── STEP 7: Prometheus + Grafana (Docker) ────────────────────────
log "[7/7] Prometheus + Grafana..."
docker compose up prometheus grafana -d 2>/dev/null || true
sleep 5

# ── Final health check ────────────────────────────────────────────
sleep 3
IP=$(hostname -I | awk '{print $1}')

log "════════════════════════════════════"
log "📊 System Status:"

check_service() {
    local name=$1 cmd=$2 addr=$3
    if eval "$cmd" >/dev/null 2>&1; then
        echo "  ✅ $name  $addr"
    else
        echo "  ❌ $name  $addr  — check logs/"
    fi
}

check_service "Redis    " "redis-cli ping 2>/dev/null | grep -q PONG" ":6379"
if ! is_enabled "$START_VLLM"; then
    if curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
        echo "  ✅ vLLM       :$VLLM_PORT  — already running; startup skipped"
    else
        echo "  ⏭️ vLLM       :$VLLM_PORT  — skipped; use --with-vllm for generation"
    fi
elif curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
    echo "  ✅ vLLM       :$VLLM_PORT"
elif pgrep -f "vllm serve.*--port $VLLM_PORT" >/dev/null 2>&1; then
    echo "  ⏳ vLLM       :$VLLM_PORT  — loading, check logs/vllm.log"
else
    echo "  ❌ vLLM       :$VLLM_PORT  — check logs/vllm.log"
fi
check_service "Phoenix  " "curl -s http://localhost:$PHOENIX_PORT/healthz"      ":$PHOENIX_PORT"
if [ -f "$LANGFUSE_ENV_FILE" ]; then
    check_service "LangFuse " "curl -s http://localhost:$LANGFUSE_PORT" ":$LANGFUSE_PORT"
fi
check_service "Next.js  " "curl -s http://localhost:$WEBAPP_PORT"              ":$WEBAPP_PORT"
check_service "FastAPI  " "curl -s http://localhost:$API_PORT/health"        ":$API_PORT"
check_service "Prometheus" "curl -s http://localhost:9090/-/healthy"           ":9090"
check_service "Grafana"    "curl -s http://localhost:3001/api/health"          ":3001"

echo "  🌐 UI:        http://$IP:$WEBAPP_PORT"
echo "  🔧 API docs:  http://$IP:$API_PORT/docs"
echo "  📈 Monitor:   http://$IP:$PHOENIX_PORT"
if [ -f "$LANGFUSE_ENV_FILE" ]; then
    echo "  📈 LangFuse:  http://$IP:$LANGFUSE_PORT"
fi
log "════════════════════════════════════"
