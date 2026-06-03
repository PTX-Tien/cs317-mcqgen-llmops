#!/bin/bash
# MCQGen System Startup (no Docker)
# Usage:
#   bash scripts/start_system.sh [--with-vllm | --no-vllm]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR=$PROJECT/logs
mkdir -p $LOG_DIR $PROJECT/redis_data $PROJECT/tmp $PROJECT/data

load_env_file() {
    local file=$1 key value
    [ -f "$file" ] || return 0
    while IFS='=' read -r key value || [ -n "$key" ]; do
        key="${key%$'\r'}"
        value="${value%$'\r'}"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        [ -z "${!key+x}" ] || continue
        value="${value#\"}"; value="${value%\"}"
        value="${value#\'}"; value="${value%\'}"
        export "$key=$value"
    done < "$file"
}

load_env_file "$PROJECT/.env"

positive_int_or_default() {
    local value=$1 default=$2
    case "$value" in
        ''|*[!0-9]*) echo "$default" ;;
        0) echo "$default" ;;
        *) echo "$value" ;;
    esac
}

truthy_value() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

# ── Conda env ─────────────────────────────────────────────────────────────────
source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2 2>/dev/null

# ── CUDA ──────────────────────────────────────────────────────────────────────
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export PYTHONNOUSERSITE=1
export HF_HOME=/mmlab_students/storageStudents/nguyenvd/trangbtt/.cache/huggingface
export HF_HUB_OFFLINE=0

# ── GPU split ─────────────────────────────────────────────────────────────────
export VLLM_CUDA_VISIBLE_DEVICES=${VLLM_CUDA_VISIBLE_DEVICES:-2,3,4,7}
export TASK_CUDA_VISIBLE_DEVICES=${TASK_CUDA_VISIBLE_DEVICES:-4,7}

# ── vLLM config ───────────────────────────────────────────────────────────────
export VLLM_TENSOR_PARALLEL_SIZE=${VLLM_TENSOR_PARALLEL_SIZE:-4}
export VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-5000}
export VLLM_MAX_NUM_SEQS=$(positive_int_or_default "${VLLM_MAX_NUM_SEQS:-4}" 4)
export VLLM_GPU_MEMORY_UTILIZATION=${VLLM_GPU_MEMORY_UTILIZATION:-0.9}
export VLLM_CPU_OFFLOAD_GB=${VLLM_CPU_OFFLOAD_GB:-0}
export VLLM_TIMEOUT=${VLLM_TIMEOUT:-180}
export VLLM_MAX_RETRIES=${VLLM_MAX_RETRIES:-1}
export START_VLLM=${START_VLLM:-1}
export VLLM_WAIT_SECONDS=${VLLM_WAIT_SECONDS:-0}
export VLLM_PORT=${VLLM_PORT:-7681}
export VLLM_URL=${VLLM_URL:-http://localhost:${VLLM_PORT}/v1}
export VLLM_MODEL=mcqgen

# ── MCQ concurrency ───────────────────────────────────────────────────────────
# Resource-driven default: each running generation job needs at least one vLLM
# sequence slot. A single job can use all slots; multiple jobs share them.
export MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$(positive_int_or_default "${MCQGEN_RESOURCE_MAX_RUNNING_JOBS:-$VLLM_MAX_NUM_SEQS}" "$VLLM_MAX_NUM_SEQS")
if [ "$MCQGEN_RESOURCE_MAX_RUNNING_JOBS" -gt "$VLLM_MAX_NUM_SEQS" ]; then
    export MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$VLLM_MAX_NUM_SEQS
fi
export MCQGEN_TARGET_CONCURRENT_USERS=$(positive_int_or_default "${MCQGEN_TARGET_CONCURRENT_USERS:-$MCQGEN_RESOURCE_MAX_RUNNING_JOBS}" "$MCQGEN_RESOURCE_MAX_RUNNING_JOBS")
export CELERY_GENERATION_CONCURRENCY=$(positive_int_or_default "${CELERY_GENERATION_CONCURRENCY:-$MCQGEN_RESOURCE_MAX_RUNNING_JOBS}" "$MCQGEN_RESOURCE_MAX_RUNNING_JOBS")
if [ "$CELERY_GENERATION_CONCURRENCY" -gt "$MCQGEN_RESOURCE_MAX_RUNNING_JOBS" ]; then
    export CELERY_GENERATION_CONCURRENCY=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
fi
export CELERY_LOW_CONCURRENCY=$(positive_int_or_default "${CELERY_LOW_CONCURRENCY:-1}" 1)
export MCQGEN_CONCURRENCY_AUTOTUNE=${MCQGEN_CONCURRENCY_AUTOTUNE:-1}
export MCQGEN_DYNAMIC_CONCURRENCY=${MCQGEN_DYNAMIC_CONCURRENCY:-1}
export MCQGEN_LOAD_TRACKING_TTL_SECONDS=$(positive_int_or_default "${MCQGEN_LOAD_TRACKING_TTL_SECONDS:-21600}" 21600)
if truthy_value "$MCQGEN_DYNAMIC_CONCURRENCY"; then
    export MCQGEN_MAX_CONCURRENT_QUESTIONS=$VLLM_MAX_NUM_SEQS
    export MCQGEN_LLM_MAX_CONCURRENCY=$VLLM_MAX_NUM_SEQS
elif truthy_value "$MCQGEN_CONCURRENCY_AUTOTUNE"; then
    DERIVED_QUESTION_CONCURRENCY=$(( VLLM_MAX_NUM_SEQS / CELERY_GENERATION_CONCURRENCY ))
    [ "$DERIVED_QUESTION_CONCURRENCY" -lt 1 ] && DERIVED_QUESTION_CONCURRENCY=1
    export MCQGEN_MAX_CONCURRENT_QUESTIONS=$DERIVED_QUESTION_CONCURRENCY
    export MCQGEN_LLM_MAX_CONCURRENCY=$DERIVED_QUESTION_CONCURRENCY
else
    export MCQGEN_MAX_CONCURRENT_QUESTIONS=$(positive_int_or_default "${MCQGEN_MAX_CONCURRENT_QUESTIONS:-4}" 4)
    export MCQGEN_LLM_MAX_CONCURRENCY=$(positive_int_or_default "${MCQGEN_LLM_MAX_CONCURRENCY:-$MCQGEN_MAX_CONCURRENT_QUESTIONS}" "$MCQGEN_MAX_CONCURRENT_QUESTIONS")
fi
export MCQGEN_LLM_STREAM_METRICS=${MCQGEN_LLM_STREAM_METRICS:-1}
export MCQGEN_GLOBAL_SLOT_GUARD=${MCQGEN_GLOBAL_SLOT_GUARD:-1}
export MCQGEN_GLOBAL_LLM_SLOTS=$(positive_int_or_default "${MCQGEN_GLOBAL_LLM_SLOTS:-$VLLM_MAX_NUM_SEQS}" "$VLLM_MAX_NUM_SEQS")
if [ "$MCQGEN_GLOBAL_LLM_SLOTS" -gt "$VLLM_MAX_NUM_SEQS" ]; then
    export MCQGEN_GLOBAL_LLM_SLOTS=$VLLM_MAX_NUM_SEQS
fi
if truthy_value "$MCQGEN_DYNAMIC_CONCURRENCY"; then
    TOTAL_LLM_SLOTS=$VLLM_MAX_NUM_SEQS
else
    TOTAL_LLM_SLOTS=$(( CELERY_GENERATION_CONCURRENCY * MCQGEN_MAX_CONCURRENT_QUESTIONS ))
fi

# ── Trace convention ─────────────────────────────────────────────────────────
export APP_ENV=${APP_ENV:-prod}
export TRACE_RUN_TYPE=${TRACE_RUN_TYPE:-manual}
export LOAD_TEST_ID=${LOAD_TEST_ID:-}
export SERVER_INSTANCE=${SERVER_INSTANCE:-$(hostname)}
export REQUEST_SOURCE=${REQUEST_SOURCE:-web}

# ── Service ports ─────────────────────────────────────────────────────────────
export API_PORT=${API_PORT:-8080}
export WEBAPP_PORT=${WEBAPP_PORT:-8081}
export START_LANGFUSE=${START_LANGFUSE:-1}
export LANGFUSE_PORT=${LANGFUSE_PORT:-8083}
export ENABLE_LANGFUSE=${ENABLE_LANGFUSE:-0}
export LANGFUSE_BASE_URL=${LANGFUSE_BASE_URL:-http://localhost:${LANGFUSE_PORT}}
export LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY:-}
export LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY:-}
export LANGFUSE_TRACING_ENABLED=${LANGFUSE_TRACING_ENABLED:-true}
export LANGFUSE_MAX_IO_CHARS=${LANGFUSE_MAX_IO_CHARS:-12000}
export WEBAPP_WAIT_SECONDS=${WEBAPP_WAIT_SECONDS:-30}
export LANGFUSE_WAIT_SECONDS=${LANGFUSE_WAIT_SECONDS:-120}

# ── Redis — DB phân tách theo concern ─────────────────────────────────────────
export REDIS_PORT=${REDIS_PORT:-6379}
export CELERY_BROKER=${CELERY_BROKER:-redis://localhost:${REDIS_PORT}/0}
export CELERY_BACKEND=${CELERY_BACKEND:-redis://localhost:${REDIS_PORT}/1}
export REDIS_CACHE_URL=${REDIS_CACHE_URL:-redis://localhost:${REDIS_PORT}/2}
export REDIS_SESSION_URL=${REDIS_SESSION_URL:-redis://localhost:${REDIS_PORT}/3}

# ── Database ──────────────────────────────────────────────────────────────────
export DATABASE_URL=${DATABASE_URL:-sqlite:///./data/mcqgen.db}

# ── Admin account (auto-tạo lần đầu) ─────────────────────────────────────────
export ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
export ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin2026}
export ADMIN_FULL_NAME=${ADMIN_FULL_NAME:-Administrator}

# ── Auth ──────────────────────────────────────────────────────────────────────
export JWT_SECRET=${JWT_SECRET:-mcqgen-secret-change-in-production}
export ACCESS_TOKEN_EXPIRE_MINUTES=${ACCESS_TOKEN_EXPIRE_MINUTES:-60}
export REFRESH_TOKEN_EXPIRE_DAYS=${REFRESH_TOKEN_EXPIRE_DAYS:-7}

# ── Rate limit ────────────────────────────────────────────────────────────────
export RATE_LIMIT_ADMIN=${RATE_LIMIT_ADMIN:-50/hour}
export RATE_LIMIT_USER=${RATE_LIMIT_USER:-20/hour}

# ── Celery queues ─────────────────────────────────────────────────────────────
export CELERY_WORKER_NAMESPACE=${CELERY_WORKER_NAMESPACE:-${USER:-mcqgen}}
export CELERY_QUEUE_NAMESPACE=${CELERY_QUEUE_NAMESPACE:-$CELERY_WORKER_NAMESPACE}
export CELERY_QUEUE_ISOLATE_BY_USER=${CELERY_QUEUE_ISOLATE_BY_USER:-1}
if truthy_value "$CELERY_QUEUE_ISOLATE_BY_USER"; then
    export CELERY_QUEUE_HIGH="mcq.${CELERY_QUEUE_NAMESPACE}.high"
    export CELERY_QUEUE_LOW="mcq.${CELERY_QUEUE_NAMESPACE}.low"
else
    export CELERY_QUEUE_HIGH=${CELERY_QUEUE_HIGH:-mcq.high}
    export CELERY_QUEUE_LOW=${CELERY_QUEUE_LOW:-mcq.low}
fi

# ── vLLM CPU offload arg ──────────────────────────────────────────────────────
VLLM_CPU_OFFLOAD_ARGS=""
if [ "$VLLM_CPU_OFFLOAD_GB" != "0" ] && [ "$VLLM_CPU_OFFLOAD_GB" != "0.0" ]; then
    VLLM_CPU_OFFLOAD_ARGS="--cpu-offload-gb $VLLM_CPU_OFFLOAD_GB"
fi

cd $PROJECT

# ── Utility functions ─────────────────────────────────────────────────────────
log() { echo "[$(date '+%H:%M:%S')] $*"; }

usage() {
    cat <<EOF
Usage: bash scripts/start_system.sh [--with-vllm | --no-vllm]
Options:
  --with-vllm   Khởi động local vLLM (port $VLLM_PORT)
  --no-vllm     Bỏ qua vLLM (dùng khi vLLM đã chạy hoặc chỉ dev UI)
  --with-langfuse / --no-langfuse
                Bật/tắt Langfuse self-host (port $LANGFUSE_PORT)
Env vars chính:
  START_VLLM=0          Giống --with-vllm
  START_LANGFUSE=1      Khởi động Langfuse Docker Compose
  MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$VLLM_MAX_NUM_SEQS
                        Số generation jobs tối đa chạy song song theo slot vLLM
  MCQGEN_TARGET_CONCURRENT_USERS=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
                        Nhãn mục tiêu cho tracing/load-test, không phải hard limit
  MCQGEN_CONCURRENCY_AUTOTUNE=1
                        Tự tính questions/job theo VLLM_MAX_NUM_SEQS
  MCQGEN_DYNAMIC_CONCURRENCY=1
                        Tự chia slot/job theo số generation jobs đang active
  MCQGEN_GLOBAL_SLOT_GUARD=1
                        Giới hạn tổng câu hỏi đang dùng LLM trên mọi worker theo Redis
  CELERY_GENERATION_CONCURRENCY=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
                        Số generation jobs chạy song song trên queue high
  CELERY_QUEUE_ISOLATE_BY_USER=1
                        Tách queue theo user để tránh worker người khác nhận job

  API_PORT=8080         FastAPI port
  WEBAPP_PORT=8081      Next.js port
  LANGFUSE_PORT=8083    Langfuse web port
  ADMIN_PASSWORD=...    Mật khẩu admin (auto-tạo lần đầu)
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
        --with-vllm|--start-vllm) export START_VLLM=1 ;;
        --no-vllm|--skip-vllm)    export START_VLLM=0 ;;
        --with-langfuse|--start-langfuse) export START_LANGFUSE=1 ;;
        --no-langfuse|--skip-langfuse)    export START_LANGFUSE=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage; exit 2 ;;
    esac
done

wait_until() {
    local label=$1 cmd=$2
    log "⏳ Waiting for $label..."
    while true; do
        if eval "$cmd" >/dev/null 2>&1; then log "✅ $label ready"; return 0; fi
        sleep 3
    done
}

wait_with_timeout() {
    local label=$1 cmd=$2 timeout=$3 elapsed=0
    [ "$timeout" -le 0 ] && return 1
    log "⏳ Waiting up to ${timeout}s for $label..."
    while [ "$elapsed" -lt "$timeout" ]; do
        if eval "$cmd" >/dev/null 2>&1; then log "✅ $label ready"; return 0; fi
        sleep 3; elapsed=$((elapsed + 3))
    done
    return 1
}

redis_ping() {
    python - "$REDIS_PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        data = sock.recv(16)
    raise SystemExit(0 if data.startswith(b"+PONG") else 1)
except OSError:
    raise SystemExit(1)
PY
}

start_bg() {
    local label=$1 check_cmd=$2 run_cmd=$3 logfile=$4
    if eval "$check_cmd" >/dev/null 2>&1; then
        log "✅ $label already running — skip"
    else
        log "🚀 Starting $label..."
        setsid bash -lc "$run_cmd" > "$logfile" 2>&1 < /dev/null &
        log "   PID=$! | log=$logfile"
    fi
}

stop_port_listeners() {
    local port=$1 label=$2
    if command -v fuser >/dev/null 2>&1 && fuser -n tcp "$port" >/dev/null 2>&1; then
        log "♻️  $label: stopping existing listener on port $port"
        fuser -k -n tcp "$port" >/dev/null 2>&1 || true
        sleep 2
    fi
}

next_health_check() {
    local body
    body="$(curl -fsS "http://localhost:$WEBAPP_PORT" 2>/dev/null || true)"
    [ -n "$body" ] || return 1
    ! printf '%s' "$body" | grep -q "Could not find a production build"
}

next_proxy_health_check() {
    next_health_check &&
        curl -fsS "http://localhost:$WEBAPP_PORT/api/health" >/dev/null 2>&1
}

langfuse_health_check() {
    curl -fsS "http://localhost:$LANGFUSE_PORT/api/public/health" >/dev/null 2>&1 ||
        curl -fsS "http://localhost:$LANGFUSE_PORT" >/dev/null 2>&1
}

stop_broken_nextjs() {
    local body
    body="$(curl -fsS "http://localhost:$WEBAPP_PORT" 2>/dev/null || true)"
    if printf '%s' "$body" | grep -q "Could not find a production build"; then
        log "⚠️  Next.js is serving a stale production-start error; restarting it"
        stop_nextjs_service
    fi
}

stop_nextjs_service() {
    local stopped=0
    stop_port_listeners "$WEBAPP_PORT" "Next.js"
    local patterns=(
        "next .* -p $WEBAPP_PORT"
        "next .*--port $WEBAPP_PORT"
        "node .*next.* -p $WEBAPP_PORT"
        "node .*next.*--port $WEBAPP_PORT"
        "next-server.*$PROJECT/webapp"
    )
    for pattern in "${patterns[@]}"; do
        if pkill -f "$pattern" 2>/dev/null; then
            stopped=1
        fi
    done
    if [ "$stopped" -eq 1 ]; then
        log "♻️  Old Next.js process stopped"
        sleep 2
    fi
}

start_nextjs_service() {
    stop_broken_nextjs
    # Next.js keeps build manifests in memory. Always restart it on system start
    # so a freshly rebuilt .next directory cannot serve stale chunks.
    stop_nextjs_service

    # Production nếu đã build, dev nếu chưa
    if [ -f "$PROJECT/webapp/.next/BUILD_ID" ]; then
        log "   Next.js: production mode"
        start_bg "Next.js" \
            "next_health_check" \
            "bash -lc 'cd $PROJECT/webapp && PORT=$WEBAPP_PORT NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_API_BACKEND=http://127.0.0.1:$API_PORT npm run start -- --hostname 0.0.0.0 -p $WEBAPP_PORT'" \
            "$LOG_DIR/nextjs.log"
    else
        log "   Next.js: dev mode (chạy 'bash scripts/deploy.sh' để build production)"
        start_bg "Next.js" \
            "next_health_check" \
            "bash -lc 'cd $PROJECT/webapp && NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_API_BACKEND=http://127.0.0.1:$API_PORT npm run dev -- --hostname 0.0.0.0 --port $WEBAPP_PORT'" \
            "$LOG_DIR/nextjs.log"
    fi
}

log "════════════════════════════════════════"
log "🚀 MCQGen System Starting"
if is_enabled "$START_VLLM"; then
    log "vLLM: enabled | GPUs=$VLLM_CUDA_VISIBLE_DEVICES | port=$VLLM_PORT"
else
    log "vLLM: skipped (--with-vllm để bật)"
fi
log "API=$API_PORT | UI=$WEBAPP_PORT | Redis=$REDIS_PORT"
if is_enabled "$START_LANGFUSE"; then
    log "Langfuse: enabled | port=$LANGFUSE_PORT"
else
    log "Langfuse: skipped (--with-langfuse để bật)"
fi
log "Admin: $ADMIN_USERNAME (auto-created on first run)"
log "Concurrency: capacity_jobs=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS | target_users=$MCQGEN_TARGET_CONCURRENT_USERS | celery_generation=$CELERY_GENERATION_CONCURRENCY | max_questions/job=$MCQGEN_MAX_CONCURRENT_QUESTIONS | max_llm/job=$MCQGEN_LLM_MAX_CONCURRENCY | dynamic=$MCQGEN_DYNAMIC_CONCURRENCY | global_guard=$MCQGEN_GLOBAL_SLOT_GUARD | vllm_max_seqs=$VLLM_MAX_NUM_SEQS | total_slots=$TOTAL_LLM_SLOTS"
log "Queues: high=$CELERY_QUEUE_HIGH | low=$CELERY_QUEUE_LOW | worker_namespace=$CELERY_WORKER_NAMESPACE"
if [ "$TOTAL_LLM_SLOTS" -gt "$VLLM_MAX_NUM_SEQS" ]; then
    log "⚠️  Concurrency overcommitted: celery_generation * questions/job > vllm_max_seqs"
fi
log "════════════════════════════════════════"

# ── STEP 1: Redis ─────────────────────────────────────────────────────────────
log "[1/6] Redis..."
if redis_ping; then
    log "✅ Redis already running on port $REDIS_PORT"
else
    redis-server \
        --port $REDIS_PORT \
        --daemonize yes \
        --logfile $LOG_DIR/redis.log \
        --dir $PROJECT/redis_data \
        --save 60 1 \
        --loglevel warning
fi
wait_until "Redis" "redis_ping"

# ── STEP 2: vLLM (optional) + Langfuse — chạy song song ─────────────────────
log "[2/6] Starting parallel services..."

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
            --max-num-seqs $VLLM_MAX_NUM_SEQS \
            --port $VLLM_PORT --host 0.0.0.0 \
            --served-model-name mcqgen" \
        "$LOG_DIR/vllm.log"
else
    log "⏭️  vLLM skipped"
fi

if is_enabled "$START_LANGFUSE"; then
    start_bg "Langfuse" \
        "langfuse_health_check" \
        "bash '$PROJECT/scripts/start_langfuse.sh'" \
        "$LOG_DIR/langfuse.log"
else
    log "⏭️  Langfuse skipped"
fi

log "⏭️  Next.js will start after FastAPI /health is ready"

# ── STEP 3: Celery workers ────────────────────────────────────────────────────
# High-priority worker: xử lý MCQ generation (queue mcq.high + default celery)
# Low-priority worker : xử lý background tasks (queue mcq.low)
log "[3/6] Celery workers..."

# Dừng worker cũ trước
pkill -f "celery -A api.tasks worker" 2>/dev/null && sleep 2

# High-priority worker
setsid bash -lc "
    export CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES
    export CELERY_BROKER=$CELERY_BROKER
    export CELERY_BACKEND=$CELERY_BACKEND
    export REDIS_CACHE_URL=$REDIS_CACHE_URL
    export REDIS_SESSION_URL=$REDIS_SESSION_URL
    export DATABASE_URL=$DATABASE_URL
    export VLLM_URL=$VLLM_URL
    export MCQGEN_MAX_CONCURRENT_QUESTIONS=$MCQGEN_MAX_CONCURRENT_QUESTIONS
    export MCQGEN_LLM_MAX_CONCURRENCY=$MCQGEN_LLM_MAX_CONCURRENCY
    export MCQGEN_LLM_STREAM_METRICS=$MCQGEN_LLM_STREAM_METRICS
    export MCQGEN_DYNAMIC_CONCURRENCY=$MCQGEN_DYNAMIC_CONCURRENCY
    export MCQGEN_GLOBAL_SLOT_GUARD=$MCQGEN_GLOBAL_SLOT_GUARD
    export MCQGEN_GLOBAL_LLM_SLOTS=$MCQGEN_GLOBAL_LLM_SLOTS
    export MCQGEN_LOAD_TRACKING_TTL_SECONDS=$MCQGEN_LOAD_TRACKING_TTL_SECONDS
    export MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
    export MCQGEN_TARGET_CONCURRENT_USERS=$MCQGEN_TARGET_CONCURRENT_USERS
    export MCQGEN_CONCURRENCY_AUTOTUNE=$MCQGEN_CONCURRENCY_AUTOTUNE
    export CELERY_GENERATION_CONCURRENCY=$CELERY_GENERATION_CONCURRENCY
    export APP_ENV=$APP_ENV
    export TRACE_RUN_TYPE=$TRACE_RUN_TYPE
    export LOAD_TEST_ID=$LOAD_TEST_ID
    export SERVER_INSTANCE=$SERVER_INSTANCE
    export REQUEST_SOURCE=$REQUEST_SOURCE
    export VLLM_MAX_NUM_SEQS=$VLLM_MAX_NUM_SEQS
    export CELERY_QUEUE_HIGH=$CELERY_QUEUE_HIGH
    export CELERY_QUEUE_LOW=$CELERY_QUEUE_LOW
    export CELERY_WORKER_NAMESPACE=$CELERY_WORKER_NAMESPACE
    export CELERY_QUEUE_NAMESPACE=$CELERY_QUEUE_NAMESPACE
    export ENABLE_LANGFUSE=$ENABLE_LANGFUSE
    export LANGFUSE_BASE_URL=$LANGFUSE_BASE_URL
    export LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY
    export LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY
    export LANGFUSE_TRACING_ENABLED=$LANGFUSE_TRACING_ENABLED
    export LANGFUSE_MAX_IO_CHARS=$LANGFUSE_MAX_IO_CHARS
    celery -A api.tasks worker \
        --loglevel=info \
        --concurrency=$CELERY_GENERATION_CONCURRENCY \
        --queues=${CELERY_QUEUE_HIGH},celery \
        --hostname=${CELERY_WORKER_NAMESPACE}-worker-high@%h \
        --max-tasks-per-child=10 \
        -Ofair
" > "$LOG_DIR/celery_high.log" 2>&1 < /dev/null &
log "   Worker-high PID=$! | concurrency=$CELERY_GENERATION_CONCURRENCY | queues=${CELERY_QUEUE_HIGH},celery | log=$LOG_DIR/celery_high.log"

# Low-priority worker (background/warmup tasks)
setsid bash -lc "
    export CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES
    export CELERY_BROKER=$CELERY_BROKER
    export CELERY_BACKEND=$CELERY_BACKEND
    export REDIS_CACHE_URL=$REDIS_CACHE_URL
    export REDIS_SESSION_URL=$REDIS_SESSION_URL
    export DATABASE_URL=$DATABASE_URL
    export VLLM_URL=$VLLM_URL
    export MCQGEN_LLM_STREAM_METRICS=$MCQGEN_LLM_STREAM_METRICS
    export MCQGEN_DYNAMIC_CONCURRENCY=$MCQGEN_DYNAMIC_CONCURRENCY
    export MCQGEN_GLOBAL_SLOT_GUARD=$MCQGEN_GLOBAL_SLOT_GUARD
    export MCQGEN_GLOBAL_LLM_SLOTS=$MCQGEN_GLOBAL_LLM_SLOTS
    export MCQGEN_LOAD_TRACKING_TTL_SECONDS=$MCQGEN_LOAD_TRACKING_TTL_SECONDS
    export MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
    export CELERY_LOW_CONCURRENCY=$CELERY_LOW_CONCURRENCY
    export APP_ENV=$APP_ENV
    export TRACE_RUN_TYPE=$TRACE_RUN_TYPE
    export LOAD_TEST_ID=$LOAD_TEST_ID
    export SERVER_INSTANCE=$SERVER_INSTANCE
    export REQUEST_SOURCE=$REQUEST_SOURCE
    export CELERY_QUEUE_HIGH=$CELERY_QUEUE_HIGH
    export CELERY_QUEUE_LOW=$CELERY_QUEUE_LOW
    export CELERY_WORKER_NAMESPACE=$CELERY_WORKER_NAMESPACE
    export CELERY_QUEUE_NAMESPACE=$CELERY_QUEUE_NAMESPACE
    export ENABLE_LANGFUSE=$ENABLE_LANGFUSE
    export LANGFUSE_BASE_URL=$LANGFUSE_BASE_URL
    export LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY
    export LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY
    export LANGFUSE_TRACING_ENABLED=$LANGFUSE_TRACING_ENABLED
    export LANGFUSE_MAX_IO_CHARS=$LANGFUSE_MAX_IO_CHARS
    celery -A api.tasks worker \
        --loglevel=info \
        --concurrency=$CELERY_LOW_CONCURRENCY \
        --queues=${CELERY_QUEUE_LOW} \
        --hostname=${CELERY_WORKER_NAMESPACE}-worker-low@%h \
        --max-tasks-per-child=20 \
        -Ofair
" > "$LOG_DIR/celery_low.log" 2>&1 < /dev/null &
log "   Worker-low  PID=$! | concurrency=$CELERY_LOW_CONCURRENCY | queues=${CELERY_QUEUE_LOW} | log=$LOG_DIR/celery_low.log"

# ── STEP 4: FastAPI ───────────────────────────────────────────────────────────
log "[4/6] FastAPI..."
pkill -f "uvicorn.*api.main.*--port $API_PORT" 2>/dev/null && sleep 2
stop_port_listeners "$API_PORT" "FastAPI"

setsid bash -lc "
    export CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES
    export CELERY_BROKER=$CELERY_BROKER
    export CELERY_BACKEND=$CELERY_BACKEND
    export REDIS_CACHE_URL=$REDIS_CACHE_URL
    export REDIS_SESSION_URL=$REDIS_SESSION_URL
    export DATABASE_URL=$DATABASE_URL
    export VLLM_URL=$VLLM_URL
    export VLLM_MODEL=$VLLM_MODEL
    export VLLM_MAX_NUM_SEQS=$VLLM_MAX_NUM_SEQS
    export MCQGEN_MAX_CONCURRENT_QUESTIONS=$MCQGEN_MAX_CONCURRENT_QUESTIONS
    export MCQGEN_LLM_MAX_CONCURRENCY=$MCQGEN_LLM_MAX_CONCURRENCY
    export MCQGEN_LLM_STREAM_METRICS=$MCQGEN_LLM_STREAM_METRICS
    export MCQGEN_DYNAMIC_CONCURRENCY=$MCQGEN_DYNAMIC_CONCURRENCY
    export MCQGEN_GLOBAL_SLOT_GUARD=$MCQGEN_GLOBAL_SLOT_GUARD
    export MCQGEN_GLOBAL_LLM_SLOTS=$MCQGEN_GLOBAL_LLM_SLOTS
    export MCQGEN_LOAD_TRACKING_TTL_SECONDS=$MCQGEN_LOAD_TRACKING_TTL_SECONDS
    export MCQGEN_RESOURCE_MAX_RUNNING_JOBS=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS
    export MCQGEN_TARGET_CONCURRENT_USERS=$MCQGEN_TARGET_CONCURRENT_USERS
    export MCQGEN_CONCURRENCY_AUTOTUNE=$MCQGEN_CONCURRENCY_AUTOTUNE
    export CELERY_GENERATION_CONCURRENCY=$CELERY_GENERATION_CONCURRENCY
    export APP_ENV=$APP_ENV
    export TRACE_RUN_TYPE=$TRACE_RUN_TYPE
    export LOAD_TEST_ID=$LOAD_TEST_ID
    export SERVER_INSTANCE=$SERVER_INSTANCE
    export REQUEST_SOURCE=$REQUEST_SOURCE
    export ADMIN_USERNAME=$ADMIN_USERNAME
    export ADMIN_PASSWORD=$ADMIN_PASSWORD
    export ADMIN_FULL_NAME='$ADMIN_FULL_NAME'
    export JWT_SECRET=$JWT_SECRET
    export ACCESS_TOKEN_EXPIRE_MINUTES=$ACCESS_TOKEN_EXPIRE_MINUTES
    export REFRESH_TOKEN_EXPIRE_DAYS=$REFRESH_TOKEN_EXPIRE_DAYS
    export RATE_LIMIT_ADMIN=$RATE_LIMIT_ADMIN
    export RATE_LIMIT_USER=$RATE_LIMIT_USER
    export CELERY_QUEUE_HIGH=$CELERY_QUEUE_HIGH
    export CELERY_QUEUE_LOW=$CELERY_QUEUE_LOW
    export CELERY_WORKER_NAMESPACE=$CELERY_WORKER_NAMESPACE
    export CELERY_QUEUE_NAMESPACE=$CELERY_QUEUE_NAMESPACE
    export ENABLE_LANGFUSE=$ENABLE_LANGFUSE
    export LANGFUSE_BASE_URL=$LANGFUSE_BASE_URL
    export LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY
    export LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY
    export LANGFUSE_TRACING_ENABLED=$LANGFUSE_TRACING_ENABLED
    export LANGFUSE_MAX_IO_CHARS=$LANGFUSE_MAX_IO_CHARS
    uvicorn api.main:app --host 0.0.0.0 --port $API_PORT
" > "$LOG_DIR/fastapi.log" 2>&1 < /dev/null &
log "   PID=$! | port=$API_PORT | log=$LOG_DIR/fastapi.log"

# ── STEP 5: vLLM health check ─────────────────────────────────────────────────
log "[5/6] vLLM status..."
if is_enabled "$START_VLLM"; then
    if curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
        log "✅ vLLM already ready"
    elif wait_with_timeout "vLLM" "curl -s http://localhost:$VLLM_PORT/health" "$VLLM_WAIT_SECONDS"; then
        true
    elif pgrep -f "vllm serve.*--port $VLLM_PORT" >/dev/null 2>&1; then
        log "⏳ vLLM still loading — check $LOG_DIR/vllm.log"
    else
        log "⚠️  vLLM failed — check $LOG_DIR/vllm.log"
    fi
else
    if curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
        log "✅ External vLLM detected on port $VLLM_PORT"
    else
        log "⏭️  vLLM skipped (use --with-vllm for generation)"
    fi
fi

# ── STEP 6: Chờ FastAPI khởi động ────────────────────────────────────────────
log "[6/6] Waiting for FastAPI..."
sleep 4
API_READY=0
for i in 1 2 3 4 5; do
    if curl -s http://localhost:$API_PORT/health >/dev/null 2>&1; then
        API_READY=1; break
    fi
    sleep 2
done

if [ "$API_READY" -eq 1 ]; then
    log "✅ FastAPI ready — starting Next.js UI"
    start_nextjs_service
    wait_with_timeout "Next.js + API proxy" "next_proxy_health_check" "$WEBAPP_WAIT_SECONDS" || true
else
    log "❌ FastAPI not ready — Next.js UI not started to avoid broken proxy state"
fi
if is_enabled "$START_LANGFUSE"; then
    wait_with_timeout "Langfuse" "langfuse_health_check" "$LANGFUSE_WAIT_SECONDS" || true
fi

# ── Final status ──────────────────────────────────────────────────────────────
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

log "════════════════════════════════════════"
log "📊 System Status:"

check_svc() {
    local name=$1 cmd=$2 addr=$3
    if eval "$cmd" >/dev/null 2>&1; then
        printf "  ✅ %-12s %s\n" "$name" "$addr"
    else
        printf "  ❌ %-12s %s  — check logs/\n" "$name" "$addr"
    fi
}

check_svc "Redis"     "redis_ping"                                                ":$REDIS_PORT"
check_svc "FastAPI"   "curl -s http://localhost:$API_PORT/health"                  ":$API_PORT"
check_svc "Next.js"   "next_proxy_health_check"                                    ":$WEBAPP_PORT"
if is_enabled "$START_LANGFUSE"; then
    check_svc "Langfuse"  "langfuse_health_check"                                  ":$LANGFUSE_PORT"
fi

if is_enabled "$START_VLLM"; then
    if curl -s http://localhost:$VLLM_PORT/health >/dev/null 2>&1; then
        printf "  ✅ %-12s %s\n" "vLLM" ":$VLLM_PORT"
    elif pgrep -f "vllm serve.*--port $VLLM_PORT" >/dev/null 2>&1; then
        printf "  ⏳ %-12s %s  — still loading\n" "vLLM" ":$VLLM_PORT"
    else
        printf "  ❌ %-12s %s\n" "vLLM" ":$VLLM_PORT"
    fi
fi

# Celery workers status. Redis may be shared by multiple team members, so only
# count workers with this process namespace.
WORKERS=$(celery -A api.tasks inspect ping --timeout=3 2>/dev/null | grep -c "^->  ${CELERY_WORKER_NAMESPACE}-worker-" || true)
[ -n "$WORKERS" ] || WORKERS=0
printf "  ✅ %-12s %s own workers responding\n" "Celery" "$WORKERS"

echo ""
echo "  ⚙️  Concurrency:"
echo "     capacity_jobs=$MCQGEN_RESOURCE_MAX_RUNNING_JOBS | target_users=$MCQGEN_TARGET_CONCURRENT_USERS | celery_generation=$CELERY_GENERATION_CONCURRENCY"
echo "     max_questions/job=$MCQGEN_MAX_CONCURRENT_QUESTIONS | max_llm/job=$MCQGEN_LLM_MAX_CONCURRENCY"
echo "     vllm_max_seqs=$VLLM_MAX_NUM_SEQS | total_llm_slots=$TOTAL_LLM_SLOTS | dynamic=$MCQGEN_DYNAMIC_CONCURRENCY | global_guard=$MCQGEN_GLOBAL_SLOT_GUARD | autotune=$MCQGEN_CONCURRENCY_AUTOTUNE"
echo "     queues=$CELERY_QUEUE_HIGH,$CELERY_QUEUE_LOW | worker_namespace=$CELERY_WORKER_NAMESPACE"
echo ""
echo "  🌐 UI:       http://$IP:$WEBAPP_PORT"
echo "  🔧 API docs: http://$IP:$API_PORT/docs"
if is_enabled "$START_LANGFUSE"; then
    echo "  📈 Langfuse: http://$IP:$LANGFUSE_PORT"
fi
echo "  👤 Admin:    $ADMIN_USERNAME / $ADMIN_PASSWORD"
echo ""
echo "  Logs:"
echo "    FastAPI  → logs/fastapi.log"
echo "    Celery   → logs/celery_high.log | logs/celery_low.log"
echo "    Next.js  → logs/nextjs.log"
echo "    Langfuse → logs/langfuse.log"
echo "    vLLM     → logs/vllm.log"
log "════════════════════════════════════════"
