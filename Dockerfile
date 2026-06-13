FROM python:3.10-slim

# Ngăn Python sinh các file .pyc thừa và đảm bảo log hiển thị ngay lập tức
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cài đặt các thư viện hệ thống cần thiết cho PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# SỬA TẠI ĐÂY: Copy file requirements_api.txt ở gốc vào container
COPY requirements_api.txt .
RUN pip install --no-cache-dir -r requirements_api.txt

# Copy toàn bộ mã nguồn từ thư mục gốc vào trong container
COPY . .

# Expose cổng nội bộ của FastAPI
EXPOSE 7860

# Lệnh khởi chạy mặc định dạng module
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
