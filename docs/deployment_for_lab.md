# Deployment cho bài thực hành (MCQGen)

Tài liệu này mô tả cách triển khai MCQGen trên server lab theo 2 chế độ, kèm URL,
biến môi trường quan trọng, cách dừng và đồng bộ với Docker.

## 0. Yêu cầu trước khi chạy

- Conda env `mcqgen_v2` (Python 3.10) đã cài `requirements_api.txt` và Node.js 20.
- Đã tải model: `models/Qwen2.5-7B-Instruct`.
- Đã build dữ liệu RAG (chạy 1 lần): `dvc repro` → tạo `data/processed/*.jsonl` + `data/indexes/`.
- Copy cấu hình: `cp .env.example .env` rồi chỉnh theo máy.

## 1. Mode 1 — Local/server đầy đủ (vLLM + Langfuse)

Dùng khi demo end-to-end (có sinh đề thật). Mặc định `start_system.sh` đã bật cả vLLM và Langfuse
(`START_VLLM=1`, `START_LANGFUSE=1`):

```bash
conda activate mcqgen_v2
cp .env.example .env
bash scripts/start_system.sh                       # = --with-vllm --with-langfuse (mặc định)
# hoặc viết tường minh:
bash scripts/start_system.sh --with-vllm --with-langfuse
```

Sau đó chạy giao diện web:

```bash
cd webapp && npm run dev      # UI ở port 8081 (npm run build trước nếu chạy production)
```

> Lưu ý GPU (quan trọng): Qwen2.5-7B-Instruct có 28 attention heads, nên `tensor-parallel-size`
> phải là ước của 28 (1, 2, 4, 7, 14). Trên máy GPU dùng chung, chỉ định rõ GPU và TP hợp lệ:
>
> ```bash
> VLLM_TENSOR_PARALLEL_SIZE=2 VLLM_CUDA_VISIBLE_DEVICES=2,3 bash scripts/start_system.sh
> ```

## 2. Mode 2 — UI/API only (không chạy vLLM)

Dùng khi chỉ phát triển UI/API, hoặc vLLM đã chạy sẵn ở nơi khác (không khởi động lại model):

```bash
bash scripts/start_system.sh --with-langfuse --no-vllm
# nếu cũng không cần Langfuse:
bash scripts/start_system.sh --no-vllm --no-langfuse
```

Khi dùng vLLM có sẵn (ví dụ trên port 7681), trỏ API/benchmark về đúng endpoint + tên model:

```bash
export VLLM_URL=http://localhost:7681/v1
export VLLM_MODEL=mcqgen
```

> Trên máy GPU dùng chung, **port 8000 mặc định thường là server của người khác** — luôn export
> `VLLM_URL` về đúng port của nhóm (7681) để tránh gọi nhầm model.

## 3. Các flag của `start_system.sh`

| Flag | Ý nghĩa |
| --- | --- |
| `--with-vllm` / `--no-vllm` | Bật/tắt khởi động vLLM local (port `VLLM_PORT`, mặc định 7681) |
| `--with-langfuse` / `--no-langfuse` | Bật/tắt Langfuse self-host (port `LANGFUSE_PORT`, mặc định 8083) |
| `-h`, `--help` | In hướng dẫn |

M��c định (không truyền flag) = `--with-vllm --with-langfuse`. Có thể override bằng biến môi trường
`START_VLLM`, `START_LANGFUSE`, `VLLM_PORT`, `API_PORT`, `WEBAPP_PORT`, `LANGFUSE_PORT`, `REDIS_PORT`.

## 4. URL các service (bare-metal, qua `start_system.sh`)

| Service | URL |
| --- | --- |
| Web UI (Next.js) | `http://<server-ip>:8081` |
| API docs (FastAPI) | `http://<server-ip>:8080/docs` |
| Langfuse | `http://<server-ip>:8083` |
| vLLM (OpenAI API) | `http://<server-ip>:7681/v1` |
| Redis | `localhost:6379` |

Kiểm tra nhanh:

```bash
curl http://localhost:8080/health
curl http://localhost:7681/v1/models      # phải thấy "id": "mcqgen"
```

## 5. Dừng hệ thống

```bash
bash scripts/stop_system.sh
```

Script dừng FastAPI (uvicorn theo `API_PORT`), Celery workers, và vLLM. Nếu còn tiến trình Next.js
(`npm run dev`) chạy thủ công thì dừng riêng (Ctrl-C ở tab đó).

## 6. Log & troubleshooting

```bash
nvidia-smi                 # kiểm tra GPU
tail -f log/vllm.log       # log vLLM (đường dẫn theo cấu hình script)
```

- vLLM lỗi `attention heads (28) must be divisible by tensor parallel size`: đặt `VLLM_TENSOR_PARALLEL_SIZE` là ước của 28 (xem Mode 1).
- ChromaDB lỗi I/O: `rm -rf data/indexes/ data/processed/ && dvc repro`.
- Next.js không gọi được API: kiểm tra `webapp/.env.local` và `curl http://localhost:8081/api/health`.

## 7. Triển khai bằng Docker (tùy chọn)

> Lưu ý: cổng trong Docker compose **khác** với chế độ bare-metal ở trên.

`docker-compose.yml` (single-node) gồm các service:

| Service | Mô tả | Port |
| --- | --- | --- |
| `redis` | Broker/cache | `6380:6379` |
| `api` | FastAPI (`uvicorn api.main:app`) | `7860:7860` |
| `worker` | Celery worker (`concurrency=1`) | — |
| `flower` | Celery monitoring UI | `5555:5555` |

```bash
docker build -t mcqgen-api:v1.0 .
docker-compose up -d
# bản scale-out (nginx + worker-high/low):
docker-compose -f docker-compose.scalable.yml up -d
```

## 8. Đồng bộ service monitoring (tránh mâu thuẫn README/script)

Để demo nhất quán, trạng thái thực tế của hệ thống:

- **Kênh monitoring/tracing chính là Langfuse** (self-host, port 8083). Tất cả trace session, user,
  pipeline stage, score (`accepted_questions`, `acceptance_rate`, `reject_stage.*`) đều ở Langfuse.
- **Flower** chỉ tồn tại trong Docker compose (port 5555) như công cụ theo dõi Celery; **không** được
  `start_system.sh` khởi động. Khi chạy bare-metal thì không có Flower.
- **Grafana/Prometheus**: không được triển khai như service trong hệ thống hiện tại (không có trong
  `start_system.sh` lẫn compose). Nếu README còn nhắc tới, nên xóa để khớp với thực tế.
