#!/bin/bash
# MCQGen System Startup — Production grade

PROJECT=/mmlab_students/storageStudents/nguyenvd/Thanhld/cs317-mcqgen-llmops
LOG_DIR=$PROJECT/logs
mkdir -p $LOG_DIR
mkdir -p $PROJECT/redis_data
mkdir -p $PROJECT/tmp

source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2 2>/dev/null

export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export CUDA_VISIBLE_DEVICES=6
export HF_HOME=/mmlab_students/storageStudents/nguyenvd/thanhld/.cache/huggingface
export HF_HUB_OFFLINE=0

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
log "════════════════════════════════════"

# ── STEP 1: Redis (synchronous — phải ready trước) ───────────────
log "[1/5] Redis..."
if redis-cli ping 2>/dev/null | grep -q PONG; then
    log "✅ Redis already running"
else
    redis-server \
        --port 6379 --daemonize yes \
        --logfile $LOG_DIR/redis.log \
        --dir $PROJECT/redis_data
fi
wait_until "Redis" "redis-cli ping 2>/dev/null | grep -q PONG"

# ── STEP 2: Start PARALLEL — vLLM + Phoenix + Streamlit ──────────
log "[2/5] Starting vLLM, Phoenix, Streamlit in parallel..."

# vLLM
start_bg "vLLM" \
    "curl -s http://localhost:8000/health" \
    "vllm serve models/Qwen3-8B-AWQ \
        --dtype half --quantization awq \
        --max-model-len 4096 \
        --gpu-memory-utilization 0.90 \
        --enforce-eager --enable-prefix-caching \
        --disable-log-requests \
        --max-num-seqs 8 --port 8000 --host 0.0.0.0 \
        --served-model-name mcqgen" \
    "$LOG_DIR/vllm.log"

# Phoenix
start_bg "Phoenix" \
    "curl -s http://localhost:6006/healthz" \
    "env TMPDIR=$PROJECT/tmp python -m phoenix.server.main serve --port 6006 --host 0.0.0.0" \
    "$LOG_DIR/phoenix.log"

# Streamlit
pkill -f "streamlit" 2>/dev/null || true
sleep 1
start_bg "Streamlit" \
    "curl -s http://localhost:8501" \
    "streamlit run streamlit_app.py \
        --server.port 8501 --server.address 0.0.0.0 \
        --server.headless true" \
    "$LOG_DIR/streamlit.log"

# ── STEP 3: Celery — chỉ cần Redis (đã ready) ───────────────────
log "[3/5] Celery worker..."
pkill -f "celery.*worker" 2>/dev/null || true
sleep 2
nohup celery -A api.tasks worker \
    --loglevel=info --concurrency=1 \
    -n worker1@%h \
    > $LOG_DIR/celery.log 2>&1 &
log "   PID=$! | log=$LOG_DIR/celery.log"

# ── STEP 4: FastAPI — chỉ cần Redis (đã ready) ──────────────────
log "[4/5] FastAPI..."
pkill -f "uvicorn.*api.main" 2>/dev/null || true
sleep 2
nohup uvicorn api.main:app \
    --host 0.0.0.0 --port 7860 \
    > $LOG_DIR/fastapi.log 2>&1 &
log "   PID=$! | log=$LOG_DIR/fastapi.log"

# ── STEP 5: Wait vLLM (blocking — phải ready trước khi thông báo) 
log "[5/5] Waiting for vLLM to finish loading model..."
wait_until "vLLM" "curl -s http://localhost:8000/health"

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
check_service "vLLM     " "curl -s http://localhost:8000/health"       ":8000"
check_service "Phoenix  " "curl -s http://localhost:6006/healthz"      ":6006"
check_service "FastAPI  " "curl -s http://localhost:7860/health"        ":7860"
check_service "Streamlit"   "curl -s http://localhost:8501"                ":8501"
check_service "Prometheus" "curl -s http://localhost:9090/-/healthy"           ":9090"
check_service "Grafana"    "curl -s http://localhost:3001/api/health"          ":3001"

echo ""
echo "  🌐 UI:        http://$IP:8501"
echo "  🔧 API docs:  http://$IP:7860/docs"
echo "  📈 Monitor:   http://$IP:6006"
log "════════════════════════════════════"
