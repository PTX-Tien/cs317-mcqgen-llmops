# Báo cáo Triển khai Docker

## 1. Mục tiêu

Tài liệu này mô tả cách triển khai MCQGen theo hướng phục vụ bài thực hành trong môi trường
Docker / Docker Compose. Mục tiêu là có thể trình bày rõ với giảng viên rằng hệ thống có
hai kiểu chạy: chạy đầy đủ trên máy lab hoặc chạy theo lớp dịch vụ tối thiểu.

## 2. Các chế độ triển khai

### 2.1. Chạy đầy đủ

Khi cần demo end-to-end, nhóm khởi động:

```bash
bash scripts/start_system.sh
```

Chế độ này có thể bật:

- FastAPI
- Celery
- Redis
- Next.js
- vLLM local
- Langfuse self-host

### 2.2. Chạy UI/API only

Khi chỉ cần phát triển giao diện hoặc kiểm tra API:

```bash
bash scripts/start_system.sh --no-vllm --no-langfuse
```

Chế độ này phù hợp khi vLLM đã chạy sẵn hoặc khi nhóm chỉ cần kiểm tra logic frontend/backend.

## 3. Điểm cần chú ý

- `VLLM_URL` phải trỏ đúng endpoint của nhóm.
- `VLLM_MODEL` phải khớp với model served-name.
- Các port trong môi trường lab cần đồng bộ giữa backend, frontend và monitoring.
- Nếu GPU có tensor-parallel, cấu hình phải phù hợp với số attention heads của model.

## 4. Vai trò trong báo cáo thực hành

Phần triển khai không chỉ để “chạy được”, mà còn chứng minh hệ thống có thể được đóng gói,
khởi động lại và tái lập. Đây là một phần quan trọng của bài thực hành vì nó phản ánh cách nhóm
quản lý runtime, service orchestration và khả năng vận hành thực tế.
