#!/bin/bash
# MCQGen System Startup using Docker Compose
# Usage:
#    bash scripts/start_system.sh [--with-vllm | --no-vllm] [--scalable]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT"

# ── 1. KHỞI TẠO FILE .env NẾU CHƯA CÓ ─────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[INFO] Không tìm thấy file .env. Tự động copy từ .env.example..."
    cp .env.example .env
fi

# Đọc cổng cấu hình từ file .env để hiển thị thông tin chính xác
API_PORT=$(grep -E '^API_PORT=' .env | cut -d= -f2 || echo 8080)
WEBAPP_PORT=$(grep -E '^WEBAPP_PORT=' .env | cut -d= -f2 || echo 8081)
LANGFUSE_PORT=$(grep -E '^LANGFUSE_PORT=' .env | cut -d= -f2 || echo 8083)

# ── 2. CẤU HÌNH BIẾN MẶC ĐỊNH CHO FLAGS ───────────────────────────────────────
USE_VLLM=1        # Mặc định bật vLLM (dùng GPU Server Lab)
SCALABLE_MODE=0   # Mặc định chạy stack tiêu chuẩn, 1 là chạy bản scalable phân tải

usage() {
    cat <<EOF
Sử dụng: bash scripts/start_system.sh [Tùy chọn]
Các tùy chọn:
  --with-vllm     Khởi động kèm container vLLM local dùng GPU (Mặc định)
  --no-vllm       Bỏ qua vLLM container (Dùng khi kết nối API ngoài hoặc dev UI máy yếu)
  --scalable      Chạy hệ thống bằng cấu hình docker-compose.scalable.yml (Nginx + Multi-workers)
  -h, --help      Hiển thị hướng dẫn này
EOF
}

# Đọc tham số truyền vào
for arg in "$@"; do
    case "$arg" in
        --with-vllm)     USE_VLLM=1 ;;
        --no-vllm)       USE_VLLM=0 ;;
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

echo "════════════════════════════════════════════════════════"
echo "🚀 Khởi động MCQGen System via Docker"
echo " Thư mục dự án: $PROJECT"
echo " File cấu hình: $COMPOSE_FILE"
echo " Chế độ vLLM:  $( [ "$USE_VLLM" -eq 1 ] && echo "Bật (Local GPU)" || echo "Tắt (Gọi API ngoài)" )"
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

# Thực hiện hạ hoặc dọn dẹp các container cũ đang chạy trùng cấu hình tránh xung đột cổng
docker compose -f  $COMPOSE_FILE down --remove-orphans

if [ "$USE_VLLM" -eq 1 ]; then
    # Khởi chạy toàn bộ hệ thống bao gồm dịch vụ vLLM
    docker compose -f $COMPOSE_FILE up -d
else
    # Khởi chạy hệ thống nhưng loại trừ service vllm ra để tiết kiệm tài nguyên
    docker compose -f $COMPOSE_FILE up -d --scale vllm=0
fi

if [ $? -ne 0 ]; then
    echo "❌ Lỗi: Không thể khởi chạy Docker Compose. Vui lòng kiểm tra lại Docker Engine."
    exit 1
fi

# Nếu ở chế độ scalable mode, tự động scale mẫu lên 2 instances cho sinh viên dễ demo
if [ "$SCALABLE_MODE" -eq 1 ]; then
    echo "⚡ Đang mở rộng quy mô (Scaling) hệ thống phân tải..."
    docker compose -f docker-compose.scalable.yml up -d --scale api=2 --scale worker=2
fi

# ── 5. KIỂM TRA TRẠNG THÁI CUỐI CÙNG ──────────────────────────────────────────
echo "[3/3] Đang kiểm tra trạng thái các cổng dịch vụ..."
sleep 5

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo "════════════════════════════════════════════════════════"
echo "📊 Trạng thái hệ thống (Docker Stack):"
docker compose -f $COMPOSE_FILE ps

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