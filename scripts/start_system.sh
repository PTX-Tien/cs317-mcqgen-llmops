#!/bin/bash
# MCQGen System Startup using Docker Compose
# Usage:
#    bash scripts/start_system.sh [--with-vllm | --no-vllm] [--scalable]
#    CUDA_VISIBLE_DEVICES=2,3,5,6 bash scripts/start_system.sh --with-vllm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT"

# ── 1. KHỞI TẠO FILE .env NẾU CHƯA CÓ ─────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[INFO] Không tìm thấy file .env. Tự động copy từ .env.example..."
    cp .env.example .env
fi

read_env_value() {
    local key="$1"
    local value
    value=$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d= -f2-)
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    echo "$value"
}

set_default_env() {
    local key="$1"
    local default="$2"
    local current="${!key:-}"

    if [ -z "$current" ]; then
        current="$(read_env_value "$key")"
    fi
    if [ -z "$current" ]; then
        current="$default"
    fi

    export "$key=$current"
}

is_port_busy() {
    local port="$1"
    python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.2)
try:
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
finally:
    sock.close()
PY
}

pick_available_port() {
    local key="$1"
    local port="${!key}"
    local original="$port"

    while is_port_busy "$port"; do
        port=$((port + 1))
    done

    if [ "$port" != "$original" ]; then
        echo "⚠️  Port $original cho $key đang bận, tự chuyển sang $port."
        export "$key=$port"
    fi
}

# Đọc cổng cấu hình từ biến môi trường/.env, nếu thiếu thì dùng default ổn định.
set_default_env API_PORT 8080
set_default_env WEBAPP_PORT 8081
set_default_env LANGFUSE_PORT 8083
set_default_env VLLM_PORT 7681
set_default_env CHROMA_PORT 8000
set_default_env START_LANGFUSE 1

# ── 2. CẤU HÌNH BIẾN MẶC ĐỊNH CHO FLAGS ───────────────────────────────────────
USE_VLLM=1        # Mặc định bật vLLM (dùng GPU Server Lab)
USE_LANGFUSE="$START_LANGFUSE"
SCALABLE_MODE=0   # Mặc định chạy stack tiêu chuẩn, 1 là chạy bản scalable phân tải

usage() {
    cat <<EOF
Sử dụng: bash scripts/start_system.sh [Tùy chọn]
Các tùy chọn:
  --with-vllm     Khởi động kèm container vLLM local dùng GPU (Mặc định)
  --no-vllm       Bỏ qua vLLM container (Dùng khi kết nối API ngoài hoặc dev UI máy yếu)
  --with-langfuse Khởi động Langfuse bằng monitoring/langfuse/docker-compose.yml (Mặc định)
  --no-langfuse   Bỏ qua Langfuse, chỉ chạy app core
  --scalable      Chạy hệ thống bằng cấu hình docker-compose.scalable.yml (Nginx + Multi-workers)
  -h, --help      Hiển thị hướng dẫn này

Chọn GPU cho vLLM:
  CUDA_VISIBLE_DEVICES=2,3,5,6 bash scripts/start_system.sh --with-vllm
  CUDA_VISIBLE_DEVICES=1,2,3,4 bash scripts/start_system.sh --with-vllm
  CUDA_VISIBLE_DEVICES=2,3 VLLM_TENSOR_PARALLEL_SIZE=2 bash scripts/start_system.sh
EOF
}

# Đọc tham số truyền vào
for arg in "$@"; do
    case "$arg" in
        --with-vllm)     USE_VLLM=1 ;;
        --no-vllm)       USE_VLLM=0 ;;
        --with-langfuse) USE_LANGFUSE=1 ;;
        --no-langfuse)   USE_LANGFUSE=0 ;;
        --scalable)      SCALABLE_MODE=1 ;;
        -h|--help)       usage; exit 0 ;;
        *)               echo "[ERROR] Tùy chọn không hợp lệ: $arg"; usage; exit 2 ;;
    esac
done

# Chọn đúng file docker-compose mục tiêu
COMPOSE_FILE="docker-compose.yml"
if [ "$SCALABLE_MODE" -eq 1 ]; then
    COMPOSE_FILE="docker-compose.scalable.yml"
fi

echo "[0/3] Dọn container cũ của MCQGen nếu đang chạy..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1 || true

count_cuda_devices() {
    local devices="$1"
    if [ -z "$devices" ] || [ "$devices" = "all" ]; then
        echo 1
        return
    fi

    local cleaned="${devices// /}"
    if [ -z "$cleaned" ]; then
        echo 1
        return
    fi

    local without_commas="${cleaned//,/}"
    echo $(( ${#cleaned} - ${#without_commas} + 1 ))
}

# Docker Compose không tự dùng CUDA_VISIBLE_DEVICES để giới hạn GPU container.
# Script sẽ chuyển CUDA_VISIBLE_DEVICES thành NVIDIA_VISIBLE_DEVICES thông qua
# VLLM_GPU_DEVICES, đồng thời tự suy ra tensor parallel theo số GPU được chọn.
if [ "$USE_VLLM" -eq 1 ]; then
    if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        export VLLM_GPU_DEVICES="$CUDA_VISIBLE_DEVICES"
        export VLLM_DOCKER_GPUS="device=$CUDA_VISIBLE_DEVICES"

        if [ -z "${VLLM_TENSOR_PARALLEL_SIZE+x}" ]; then
            export VLLM_TENSOR_PARALLEL_SIZE="$(count_cuda_devices "$CUDA_VISIBLE_DEVICES")"
        fi
    elif [ -n "${VLLM_GPU_DEVICES:-}" ] && [ -z "${VLLM_TENSOR_PARALLEL_SIZE+x}" ]; then
        export VLLM_TENSOR_PARALLEL_SIZE="$(count_cuda_devices "$VLLM_GPU_DEVICES")"
        if [ "$VLLM_GPU_DEVICES" != "all" ]; then
            export VLLM_DOCKER_GPUS="device=$VLLM_GPU_DEVICES"
        fi
    fi
fi

COMPOSE_ARGS=(-f "$COMPOSE_FILE")
GPU_OVERRIDE_FILE=""

write_vllm_gpu_override() {
    local devices="${VLLM_GPU_DEVICES:-all}"
    GPU_OVERRIDE_FILE="$(mktemp "/tmp/mcqgen-vllm-gpu.XXXXXX.yml")"

    {
        echo "services:"
        echo "  vllm:"
        echo "    gpus:"
        echo "      - driver: nvidia"
        if [ -z "$devices" ] || [ "$devices" = "all" ]; then
            echo "        count: all"
        else
            echo "        device_ids:"
            IFS=',' read -ra ids <<< "$devices"
            for id in "${ids[@]}"; do
                id="${id// /}"
                if [ -n "$id" ]; then
                    echo "          - \"$id\""
                fi
            done
        fi
        echo "        capabilities: [gpu]"
    } > "$GPU_OVERRIDE_FILE"

    COMPOSE_ARGS+=(-f "$GPU_OVERRIDE_FILE")
}

if [ "$USE_VLLM" -eq 1 ]; then
    write_vllm_gpu_override
fi

cleanup_gpu_override() {
    if [ -n "${GPU_OVERRIDE_FILE:-}" ] && [ -f "$GPU_OVERRIDE_FILE" ]; then
        rm -f "$GPU_OVERRIDE_FILE"
    fi
}
trap cleanup_gpu_override EXIT

pick_available_port API_PORT
pick_available_port WEBAPP_PORT
pick_available_port CHROMA_PORT
if [ "$USE_VLLM" -eq 1 ]; then
    pick_available_port VLLM_PORT
fi

echo "════════════════════════════════════════════════════════"
echo "🚀 Khởi động MCQGen System via Docker"
echo " Thư mục dự án: $PROJECT"
echo " File cấu hình: $COMPOSE_FILE"
echo " Chế độ vLLM:  $( [ "$USE_VLLM" -eq 1 ] && echo "Bật (Local GPU)" || echo "Tắt (Gọi API ngoài)" )"
echo " Langfuse:     $( [ "$USE_LANGFUSE" -eq 1 ] && echo "Bật (stack monitoring/langfuse)" || echo "Tắt" )"
if [ "$USE_VLLM" -eq 1 ]; then
    echo " GPU vLLM:     ${VLLM_GPU_DEVICES:-theo .env hoặc all} | docker_gpus=${VLLM_DOCKER_GPUS:-all} | tensor_parallel=${VLLM_TENSOR_PARALLEL_SIZE:-theo .env hoặc 1}"
fi
echo " Cổng dịch vụ:  UI->$WEBAPP_PORT | API->$API_PORT | Langfuse->$LANGFUSE_PORT"
echo "════════════════════════════════════════════════════════"

# ── 3. QUẢN LÝ ARTIFACTS DỮ LIỆU (GIẢI PHÁP 1) ────────────────────────────────
echo "[1/3] Kiểm tra Data Artifacts cho RAG Pipeline..."

# Nếu thư mục indexes của ChromaDB trống, cảnh báo hoặc tự động chạy DVC
if [ ! -d "data/indexes" ] || [ -z "$(ls -A data/indexes 2>/dev/null)" ]; then
    echo "⚠️  Cảnh báo: Không tìm thấy Vector Index tại data/indexes/."
    if command -v dvc >/dev/null 2>&1; then
        echo "🔄 Phát hiện cài đặt DVC trên host. Tự động chạy 'dvc repro' để build dữ liệu..."
        dvc repro
    else
        echo "❌ Không tìm thấy DVC trên máy host. Hãy đảm bảo bạn đã kéo thư mục 'data/indexes/'"
        echo "   về máy hoặc chạy pipeline dữ liệu trước khi thực hiện RAG retrieval."
        echo "   Hệ thống vẫn sẽ khởi động nhưng kho dữ liệu trích xuất sẽ bị trống."
    fi
else
    echo "✅ Đã tìm thấy dữ liệu Vector Index (ChromaDB) sẵn sàng để mount."
fi

# ── 4. THỰC THI KHỞI CHẠY DOCKER COMPOSE ──────────────────────────────────────
echo "[2/3] Đang kích hoạt các Docker Containers..."

# Tạo các phân vùng thư mục tĩnh trên host để mount an toàn nếu chưa có
mkdir -p data input output logs

if [ "$USE_LANGFUSE" -eq 1 ]; then
    echo "🔎 Khởi động Langfuse monitoring stack..."
    LANGFUSE_PORT="$LANGFUSE_PORT" bash scripts/start_langfuse.sh
fi

if [ "$USE_VLLM" -eq 1 ]; then
    # Khởi chạy toàn bộ hệ thống bao gồm dịch vụ vLLM
    docker compose "${COMPOSE_ARGS[@]}" up -d --build
else
    # Khởi chạy hệ thống nhưng loại trừ service vllm ra để tiết kiệm tài nguyên
    docker compose "${COMPOSE_ARGS[@]}" up -d --build --scale vllm=0
fi

if [ $? -ne 0 ]; then
    echo "❌ Lỗi: Không thể khởi chạy Docker Compose. Vui lòng kiểm tra lại Docker Engine."
    exit 1
fi

# Nếu ở chế độ scalable mode, tự động scale mẫu lên 2 instances cho sinh viên dễ demo
if [ "$SCALABLE_MODE" -eq 1 ]; then
    echo "⚡ Đang mở rộng quy mô (Scaling) hệ thống phân tải..."
    docker compose "${COMPOSE_ARGS[@]}" up -d --build --scale api=2 --scale worker=2
fi

# ── 5. KIỂM TRA TRẠNG THÁI CUỐI CÙNG ──────────────────────────────────────────
echo "[3/3] Đang kiểm tra trạng thái các cổng dịch vụ..."
sleep 5

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo "════════════════════════════════════════════════════════"
echo "📊 Trạng thái hệ thống (Docker Stack):"
docker compose "${COMPOSE_ARGS[@]}" ps

echo ""
echo "🌐 Địa chỉ truy cập bài thực hành Lab:"
if [ "$SCALABLE_MODE" -eq 1 ]; then
    echo "  - Web App UI (Nginx Load Balancer): http://$IP"
else
    echo "  - Web App UI:        http://$IP:$WEBAPP_PORT"
fi
echo "  - FastAPI Open API Docs: http://$IP:$API_PORT/docs"
echo "  - Langfuse Dashboard:    http://$IP:$LANGFUSE_PORT"
echo ""
echo "💡 Mẹo giám sát:"
echo "  - Xem log thời gian thực:  docker compose -f $COMPOSE_FILE logs -f"
echo "  - Xem log của một service: docker compose -f $COMPOSE_FILE logs -f [api|worker|vllm]"
echo "  - Dừng toàn bộ hệ thống:  docker compose -f $COMPOSE_FILE down"
echo "════════════════════════════════════════════════════════"
