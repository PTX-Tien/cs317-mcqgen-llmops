FROM python:3.10-slim

# Ngăn Python sinh các file .pyc thừa và đảm bảo log hiển thị ngay lập tức
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài đặt các thư viện hệ thống cần thiết cho PyMuPDF và curl để test healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Tận dụng Docker layer cache bằng cách cài đặt dependencies trước
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ mã nguồn từ thư mục api/ vào trong container
COPY . .

# Expose cổng nội bộ của FastAPI (cổng này sẽ được map ra ngoài qua docker-compose)
EXPOSE 7860

# Lệnh khởi chạy mặc định cho API (khi chạy Celery worker, docker-compose sẽ tự đè lệnh khác)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]