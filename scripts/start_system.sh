#!/bin/bash
# MCQGen System Startup — Production grade

PROJECT=/mmlab_students/storageStudents/nguyenvd/thanhhn/cs317-mcqgen-llmops
LOG_DIR=$PROJECT/logs
mkdir -p $LOG_DIR
mkdir -p $PROJECT/redis_data
mkdir -p $PROJECT/tmp

source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2 2>/dev/null

export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
# Qwen2.5-7B-Instruct full precision is larger than one RTX 2080 Ti.
# Use TP=4 so vLLM stays GPU-only. Override these two variables before running
# this script if you need a strict GPU split between vLLM and RAG workers.
export VLLM_CUDA_VISIBLE_DEVICES=${VLLM_CUDA_VISIBLE_DEVICES:-2,3,4,7}
export TASK_CUDA_VISIBLE_DEVICES=${TASK_CUDA_VISIBLE_DEVICES:-4,7}
export HF_HOME=/mmlab_students/storageStudents/nguyenvd/thanhhn/.cache/huggingface
export HF_HUB_OFFLINE=0

# Latency-first defaults for Qwen2.5-7B-Instruct on RTX 2080 Ti.
# TP=4 avoids CPU offload; keep per-GPU reservation low because GPUs are shared.
export VLLM_TENSOR_PARALLEL_SIZE=${VLLM_TENSOR_PARALLEL_SIZE:-4}
export VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-5000}
export VLLM_MAX_NUM_SEQS=${VLLM_MAX_NUM_SEQS:-4}
export VLLM_GPU_MEMORY_UTILIZATION=${VLLM_GPU_MEMORY_UTILIZATION:-0.90}
export VLLM_CPU_OFFLOAD_GB=${VLLM_CPU_OFFLOAD_GB:-0}
export VLLM_TIMEOUT=${VLLM_TIMEOUT:-180}
export VLLM_MAX_RETRIES=${VLLM_MAX_RETRIES:-1}
export MCQGEN_MAX_CONCURRENT_QUESTIONS=${MCQGEN_MAX_CONCURRENT_QUESTIONS:-4}
export MCQGEN_LLM_MAX_CONCURRENCY=${MCQGEN_LLM_MAX_CONCURRENCY:-$VLLM_MAX_NUM_SEQS}
export VLLM_PORT=${VLLM_PORT:-7681}
export VLLM_URL=${VLLM_URL:-http://localhost:${VLLM_PORT}/v1}
export VLLM_MODEL=mcqgen

VLLM_CPU_OFFLOAD_ARGS=""
if [ "$VLLM_CPU_OFFLOAD_GB" != "0" ] && [ "$VLLM_CPU_OFFLOAD_GB" != "0.0" ]; then
    VLLM_CPU_OFFLOAD_ARGS="--cpu-offload-gb $VLLM_CPU_OFFLOAD_GB"
fi

cd $PROJECT

# ── Utility functions ─────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }

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
        eval "nohup $run_cmd > $logfile 2>&1 &"
        log "   PID=$! | log=$logfile"
    fi
}

log "════════════════════════════════════"
log "🚀 MCQGen System Starting"
log "vLLM GPUs=$VLLM_CUDA_VISIBLE_DEVICES | task GPUs=$TASK_CUDA_VISIBLE_DEVICES"
log "vLLM max_model_len=$VLLM_MAX_MODEL_LEN max_num_seqs=$VLLM_MAX_NUM_SEQS | question_concurrency=$MCQGEN_MAX_CONCURRENT_QUESTIONS llm_concurrency=$MCQGEN_LLM_MAX_CONCURRENCY"
log "════════════════════════════════════"

# ── STEP 1: Redis (synchronous — phải ready trước) ───────────────
log "[1/6] Redis..."
if redis-cli ping 2>/dev/null | grep -q PONG; then
    log "✅ Redis already running"
else
    redis-server \
        --port 6379 --daemonize yes \
        --logfile $LOG_DIR/redis.log \
        --dir $PROJECT/redis_data
fi
wait_until "Redis" "redis-cli ping 2>/dev/null | grep -q PONG"

# ── STEP 2: Start PARALLEL — vLLM + Phoenix + Next.js ────────────
log "[2/6] Starting vLLM, Phoenix, Next.js in parallel..."

# vLLM
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

# Phoenix
start_bg "Phoenix" \
    "curl -s http://localhost:6006/healthz" \
    "env TMPDIR=$PROJECT/tmp python -m phoenix.server.main serve --port 6006 --host 0.0.0.0" \
    "$LOG_DIR/phoenix.log"

# Next.js frontend
start_bg "Next.js" \
    "curl -s http://localhost:3000" \
    "bash -lc 'cd $PROJECT/webapp && npm run dev -- --hostname 0.0.0.0 --port 3000'" \
    "$LOG_DIR/nextjs.log"

# ── STEP 3: Celery — chỉ cần Redis (đã ready) ───────────────────
log "[3/6] Celery worker..."
pkill -f "celery.*worker" 2>/dev/null || true
sleep 2
CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES nohup celery -A api.tasks worker \
    --loglevel=info --concurrency=1 --prefetch-multiplier=1 -Ofair \
    -n worker1@%h \
    > $LOG_DIR/celery.log 2>&1 &
log "   PID=$! | log=$LOG_DIR/celery.log"

# ── STEP 4: FastAPI — chỉ cần Redis (đã ready) ──────────────────
log "[4/6] FastAPI..."
pkill -f "uvicorn.*api.main" 2>/dev/null || true
sleep 2
CUDA_VISIBLE_DEVICES=$TASK_CUDA_VISIBLE_DEVICES nohup uvicorn api.main:app \
    --host 0.0.0.0 --port 8081 \
    > $LOG_DIR/fastapi.log 2>&1 &
log "   PID=$! | log=$LOG_DIR/fastapi.log"

# ── STEP 5: Wait vLLM (blocking — phải ready trước khi thông báo) 
log "[5/6] Waiting for vLLM to finish loading model..."
wait_until "vLLM" "curl -s http://localhost:$VLLM_PORT/health"

# ── STEP 6: Prometheus + Grafana (Docker) ────────────────────────
log "[6/6] Prometheus + Grafana..."
cd monitoring 2>/dev/null || true
docker compose up prometheus grafana -d 2>/dev/null || true
cd ..
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
check_service "vLLM     " "curl -s http://localhost:$VLLM_PORT/health" ":$VLLM_PORT"
check_service "Phoenix  " "curl -s http://localhost:6006/healthz"      ":6006"
check_service "FastAPI  " "curl -s http://localhost:8081/health"        ":7860"
check_service "Streamlit"   "curl -s http://localhost:8501"                ":8501"
check_service "Prometheus" "curl -s http://localhost:9090/-/healthy"           ":9090"
check_service "Grafana"    "curl -s http://localhost:3001/api/health"          ":3001"

echo ""
echo "  🌐 UI:        http://$IP:8501"
echo "  🔧 API docs:  http://$IP:8081/docs"
echo "  📈 Monitor:   http://$IP:6006"
log "════════════════════════════════════"
