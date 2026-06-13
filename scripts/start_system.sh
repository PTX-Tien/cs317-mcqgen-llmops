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

# Làm sạch ký tự xuống dòng Windows (\r) để tránh lỗi parse trên Linux
sed -i 's/\r//g' .env 2>/dev/null

# Đọc cấu hình cổng dịch vụ chính xác bằng cách source file .env
API_PORT=$(source .env && echo $API_PORT)
WEBAPP_PORT=$(source .env && echo $WEBAPP_PORT)
LANGFUSE_PORT=$(source .env && echo $LANGFUSE_PORT)

API_PORT=${API_PORT:-8080}
WEBAPP_PORT=${WEBAPP_PORT:-8081}
LANGFUSE_PORT=${LANGFUSE_PORT:-8089}

# Cấu hình biến Admin mặc định để in ra màn hình nghiệm thu
export ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
export ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin2026}
export ADMIN_FULL_NAME=${ADMIN_FULL_NAME:-Administrator}


USE_VLLM=1        # Mặc định bật vLLM
SCALABLE_MODE=0   # Mặc định chạy stack tiêu chuẩn

usage() {
    cat <<EOF
Sử dụng: bash scripts/start_system.sh [Tùy chọn]
Các tùy chọn:
  --with-vllm     Khởi động kèm container vLLM local dùng GPU
  --no-vllm       Bỏ qua vLLM container (Dùng khi gọi API ngoài hoặc test hệ thống)
  -h, --help      Hiển thị hướng dẫn này
EOF
}

# Đọc tham số truyền vào
for arg in "$@"; do
    case "$arg" in
        --with-vllm)     USE_VLLM=1 ;;
        --no-vllm)       USE_VLLM=0 ;;
        -h|--help)       usage; exit 0 ;;
        *)               echo "[ERROR] Tùy chọn không hợp lệ: $arg"; usage; exit 2 ;;
    esac
done

COMPOSE_FILE="docker-compose.yml"

echo "════════════════════════════════════════════════════════"
echo "🚀 Khởi động MCQGen System via Docker (Branch: Trang_docker)"
echo " Thư mục dự án: $PROJECT"
echo " Cổng dịch vụ:  UI->$WEBAPP_PORT | API->$API_PORT | Langfuse->$LANGFUSE_PORT"
echo "════════════════════════════════════════════════════════"

echo "[1/3] Đang kích hoạt các Docker Containers..."
mkdir -p input output logs

# Hạ container cũ tránh xung đột
docker compose -f $COMPOSE_FILE down --remove-orphans

if [ "$USE_VLLM" -eq 1 ] && grep -q "vllm:" "$COMPOSE_FILE"; then
    docker compose -f $COMPOSE_FILE up -d
else
    # Nếu chạy --no-vllm hoặc file compose không định nghĩa vllm, cứ khởi chạy bình thường
    docker compose -f $COMPOSE_FILE up -d
fi

if [ $? -ne 0 ]; then
    echo "❌ Lỗi: Không thể khởi chạy Docker Compose."
    exit 1
fi

echo "[2/3] Đang kiểm tra hệ thống khởi tạo Database..."
sleep 6 # Đợi container API chạy hàm init_db() và tự tạo Admin account thành công

echo "[3/3] Kiểm tra trạng thái các cổng dịch vụ..."
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo "════════════════════════════════════════════════════════"
echo "📊 Trạng thái hệ thống (Docker Stack):"
docker compose -f $COMPOSE_FILE ps

echo ""
echo "🌐 Địa chỉ truy cập bài thực hành Lab:"
echo "  - Web App UI:        http://$IP:$WEBAPP_PORT"
echo "  - FastAPI Open API Docs: http://$IP:$API_PORT/docs"
echo "  - Langfuse Dashboard:    http://$IP:$LANGFUSE_PORT"
echo ""
echo "💡 Tài khoản Admin (Đã được Container tự động khởi tạo):"
echo "  - Username: $ADMIN_USERNAME"
echo "  - Password: $ADMIN_PASSWORD"
echo "════════════════════════════════════════════════════════"