# CS317 — MCQGen: Hệ Thống Sinh Đề Thi MCQ Tự Động với LLMOps

> **Đồ án môn CS317 — Nhóm 3 | ĐH Công nghệ Thông tin, ĐHQG TP.HCM**
> Hệ thống production-grade tự động sinh câu hỏi trắc nghiệm chất lượng cao từ slide PDF và transcript bài giảng, tích hợp đầy đủ LLMOps pipeline.

[![Python](https://img.shields.io/badge/Python-3.10-blue)](https://python.org)
[![vLLM](https://img.shields.io/badge/vLLM-0.8.5-green)](https://vllm.ai)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-black)](https://nextjs.org)
[![DVC](https://img.shields.io/badge/DVC-pipeline-purple)](https://dvc.org)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## Mục lục

- [Tổng quan](#-tổng-quan)
- [Kết quả nổi bật](#-kết-quả-nổi-bật)
- [Kiến trúc hệ thống](#️-kiến-trúc-hệ-thống)
- [Cấu trúc project](#-cấu-trúc-project)
- [Tech Stack](#️-tech-stack)
- [Yêu cầu hệ thống](#️-yêu-cầu-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Khởi động & Dừng hệ thống](#️-khởi-động--dừng-hệ-thống)
- [Hướng dẫn sử dụng](#-hướng-dẫn-sử-dụng)
- [DVC Pipeline](#-dvc-pipeline)
- [Triển khai Docker](#-triển-khai-docker)
- [API Reference](#-api-reference)
- [Monitoring & Observability](#-monitoring--observability)
- [Troubleshooting](#-troubleshooting)
- [Release History](#-release-history)

---

## 📌 Tổng quan

MCQGen là hệ thống end-to-end tự động sinh câu hỏi trắc nghiệm (Multiple Choice Questions) cho môn **CS116 — Lập trình Python cho Máy học**. Hệ thống nhận đầu vào là slide PDF và transcript bài giảng (từ Whisper ASR), sau đó qua pipeline LLM 5 bước kết hợp **Adaptive RAG** (HyDE + Sentence-Window + CrossEncoder Reranker) để sinh câu hỏi chất lượng cao.

Dự án áp dụng đầy đủ các thực hành **LLMOps production-grade**: quản lý data version bằng DVC, serving LLM với vLLM, task queue bằng Celery/Redis, observability với Langfuse, CI/CD bằng GitHub Actions và đóng gói Docker.

## 🏆 Kết quả nổi bật

| Metric                       | Kết quả                                                  |
| ---------------------------- | -------------------------------------------------------- |
| Thời gian sinh 1 MCQ         | ~2-3 phút (giảm từ ~60 phút thủ công, cải thiện **20×**) |
| Quality score trung bình     | **1.00 / 1.00**                                          |
| RAG improvement (trung bình) | +46% so với naive retrieval                              |
| Latency P50 / P99            | 45.1s / 2m 3s                                            |

---

## 🏗️ Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────────┐
│                     Browser (Next.js :8081)                     │
│          Login · Dashboard · Generate · History · Quiz          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI REST API (:8080)                     │
│              JWT Auth · Rate Limit · Structured Log             │
└──────────┬─────────────────────────────────────┬────────────────┘
           │ Celery task                         │ sync query
           ▼                                     ▼
┌──────────────────────┐          ┌───────────────────────────────┐
│   Redis (:6379)      │          │      SQLite (sqlmodel)        │
│   Task broker/result │          │  Users · Exams · Questions    │
└──────────┬───────────┘          └──────────────┬────────────────┘
           │                                     |
           ▼                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Worker                                │
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐     │
│   │              Adaptive RAG Pipeline                    │     │
│   │   HyDE Query Gen → Sentence-Window ChromaDB           │     │
│   │                  → CrossEncoder Reranker              │     │
│   └────────────────────────┬──────────────────────────────┘     │
│                            │ retrieved context                  │
|                            ▼                                    |
│   ┌───────────────────────────────────────────────────────┐     │
│   │             MCQ Generation Pipeline (async)           │     │
│   │   P1: Gen Stem  →  P4: Gen Distractors                │     │
│   │   P5-P7: Select Best  →  P8: Assemble MCQ             │     │
│   │   Eval: Quality Check (auto-accept/reject)            │     │
│   └───────────────────────────────────────────────────────┘     │
└────────────────────────────┬────────────────────────────────────┘
                             │ OpenAI-compat API
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              vLLM Server (:7681)                                │
│       Qwen2.5-7B-Instruct · Prefix Cache · Async Engine         │
└─────────────────────────────────────────────────────────────────┘

Observability: Langfuse (:8083) — LLM traces · sessions · scores
```

---

## 📁 Cấu trúc project

```
cs317-mcqgen-llmops/
│
├── api/                          # FastAPI + Celery service layer
│   ├── main.py                   # REST API, WebSocket, queue endpoints
│   ├── tasks.py                  # Celery task entrypoint
│   ├── pdf_exporter.py           # Export đề thi/đáp án ra PDF
│   └── core/
│       ├── auth.py               # JWT auth + default users
│       ├── config.py             # Settings từ .env
│       ├── database.py           # SQLite models/session
│       └── logger.py             # Structured logging middleware
│
├── src/
│   ├── mcqgen/                   # Production MCQ pipeline package
│   │   ├── pipeline_mcq.py       # Async MCQ generation (5-step pipeline)
│   │   ├── advanced_retrieval.py # Adaptive RAG: HyDE + SW + CrossEncoder
│   │   ├── common.py             # Config, prompts, JSON parser, utilities
│   │   ├── chunk_transcripts.py  # DVC stage: chunking Whisper transcripts
│   │   └── indexing.py           # DVC stage: indexing slides + transcripts
│   ├── adaptive/                 # Adaptive learning logic
│   ├── eval/                     # Evaluation metrics (eval_overall, eval_iwf)
│   └── gen/                      # Generation helpers và legacy modules
│
├── webapp/                       # Next.js 16 App Router frontend
│   ├── app/                      # Pages: login, dashboard, generate, history, quiz
│   ├── components/               # UI components (shadcn/ui)
│   ├── lib/                      # API client, Zustand auth store, helpers
│   └── types/                    # TypeScript interfaces
│
├── vllm/                         # vLLM benchmark experiments
│   ├── exp02_llm_concurrency_sweep.py
│   ├── exp03_pipeline_sequential_vs_async.py
│   ├── exp04_max_num_seqs_ablation.py
│   ├── exp05_prefix_cache_ablation.py
│   ├── exp06_official_vllm_bench.py
│   └── exp07_no_vllm_baselines.py
│
├── vllm_demo_webapp/             # Web demo riêng cho vLLM experiments
├── monitoring/                   # Langfuse tracing configuration
├── scripts/                      # Script vận hành hệ thống
│   ├── start_system.sh           # Khởi động tất cả services (parallel)
│   ├── stop_system.sh            # Dừng tất cả services
│   └── set_env.sh                # Thiết lập environment variables
│
├── prompts/                      # Versioned prompt assets (P1–P8)
├── input/                        # Input: slide PDF, Whisper JSON transcripts
├── data/                         # Processed data, ChromaDB indexes, SQLite DB
├── docs/                         # Tài liệu bổ sung
├── tests/                        # Test scripts
├── .github/workflows/            # GitHub Actions CI/CD
│
├── dvc.yaml                      # DVC pipeline định nghĩa 3 stages
├── dvc.lock                      # DVC lockfile
├── Dockerfile                    # Image mcqgen-api:v1.0
├── docker-compose.yml            # Stack: redis + api + worker + flower
├── docker-compose.scalable.yml   # Scalable variant (multi-worker)
├── requirements_api.txt          # Python dependencies cho API/Worker
├── next.config.ts                # Next.js config
└── .env.example                  # Template biến môi trường
```

---

## 🛠️ Tech Stack

| Layer                  | Công nghệ                             | Phiên bản |
| ---------------------- | ------------------------------------- | --------- |
| **Frontend**           | Next.js + TypeScript + Tailwind CSS   | 16.x      |
| **UI Components**      | shadcn/ui                             | latest    |
| **State Management**   | Zustand                               | 4.x       |
| **Backend API**        | FastAPI                               | 0.136     |
| **Authentication**     | JWT (python-jose)                     | 3.3.0     |
| **Task Queue**         | Celery + Redis                        | 5.x       |
| **LLM Serving**        | vLLM                                  | 0.8.5     |
| **LLM Model**          | Qwen2.5-7B-Instruct                   | —         |
| **RAG Strategy**       | HyDE + Sentence-Window + CrossEncoder | custom    |
| **Embedding Model**    | BAAI/bge-m3                           | —         |
| **Vector Database**    | ChromaDB                              | 1.5.x     |
| **Data Versioning**    | DVC                                   | —         |
| **LLM Observability**  | Langfuse (self-hosted)                | —         |
| **Relational DB**      | SQLite (sqlmodel)                     | —         |
| **Structured Logging** | structlog (JSON)                      | 24.x      |
| **PDF Export**         | ReportLab                             | —         |
| **CI/CD**              | GitHub Actions                        | —         |
| **Containerization**   | Docker + Docker Compose v2            | —         |

---

## 🖥️ Yêu cầu hệ thống

| Thành phần  | Yêu cầu                                              |
| ----------- | ---------------------------------------------------- |
| GPU         | RTX 2080 Ti 11GB VRAM hoặc tương đương (≥ 10GB VRAM) |
| RAM         | ≥ 32GB                                               |
| Disk        | ≥ 100GB                                              |
| CUDA Driver | ≥ 12.2 (kiểm tra: `nvidia-smi`)                      |
| OS          | Ubuntu 20.04+                                        |
| Python      | 3.10 (khuyến nghị qua Conda)                         |
| Node.js     | 20.x                                                 |
| Docker      | ≥ 27.x + Docker Compose v2                           |

---

## 🚀 Cài đặt

### Bước 1 — Clone repository

```bash
git clone https://github.com/PTX-Tien/cs317-mcqgen-llmops.git
cd cs317-mcqgen-llmops
```

### Bước 2 — Tạo Conda environment

```bash
conda create -n mcqgen_v2 python=3.10 -y
conda activate mcqgen_v2

# Cài Node.js 20 cho Next.js webapp
conda install -c conda-forge nodejs=20 -y

# Kiểm tra
python --version    # Python 3.10.x
node --version      # v20.x.x
```

### Bước 3 — Cấu hình biến môi trường

```bash
cp .env.example .env
nano .env   # Chỉnh sửa theo hạ tầng của bạn
```

Các biến bắt buộc cần đặt:

```dotenv
# ── vLLM ─────────────────────────────────────────
VLLM_URL=http://localhost:7681/v1
VLLM_MODEL=mcqgen
VLLM_TIMEOUT=180
VLLM_MAX_RETRIES=1
START_VLLM=0
VLLM_PORT=7681
VLLM_WAIT_SECONDS=0
VLLM_MAX_NUM_SEQS=4
VLLM_MAX_MODEL_LEN=5000

# ── Local service ports ──────────────────────────
API_PORT=8080
WEBAPP_PORT=8081
LANGFUSE_PORT=8083
START_LANGFUSE=1
LANGFUSE_WAIT_SECONDS=120
PUBLIC_HOST=

# ── Auth ─────────────────────────────────────────
JWT_SECRET=mcqgen-cs116-secret-2026-change-in-production-abc123xyz
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Database ──────────────────────────────────────
DATABASE_URL=sqlite:///./data/mcqgen.db

# ── Redis ────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER=redis://localhost:6379/0
CELERY_BACKEND=redis://localhost:6379/1
REDIS_CACHE_URL=redis://localhost:6379/2
REDIS_SESSION_URL=redis://localhost:6379/3
CELERY_QUEUE_ISOLATE_BY_USER=1
TASK_RESULT_TTL_SECONDS=86400

# ── Rate Limit ────────────────────────────────────
RATE_LIMIT_TEACHER=10/hour
RATE_LIMIT_STUDENT=30/hour

# ── Monitoring ────────────────────────────────────
LOG_LEVEL=INFO
ENABLE_LANGFUSE=0
LANGFUSE_BASE_URL=http://localhost:8083
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_MAX_IO_CHARS=12000

# ── Trace Tags ───────────────────────────────────
APP_ENV=prod
TRACE_RUN_TYPE=manual
LOAD_TEST_ID=
SERVER_INSTANCE=
REQUEST_SOURCE=web

# ── Pipeline ──────────────────────────────────────
ENABLE_LLM_EVAL=0
DEFAULT_RETRIEVAL_MODE=auto
MCQGEN_RESOURCE_MAX_RUNNING_JOBS=4
MCQGEN_TARGET_CONCURRENT_USERS=4
CELERY_GENERATION_CONCURRENCY=4
CELERY_LOW_CONCURRENCY=1
MCQGEN_CONCURRENCY_AUTOTUNE=1
MCQGEN_DYNAMIC_CONCURRENCY=1
MCQGEN_GLOBAL_SLOT_GUARD=1
MCQGEN_GLOBAL_LLM_SLOTS=4
MCQGEN_LOAD_TRACKING_TTL_SECONDS=21600
MCQGEN_MAX_CONCURRENT_QUESTIONS=4
MCQGEN_LLM_MAX_CONCURRENCY=4
MCQGEN_LLM_STREAM_METRICS=1
```

### Bước 4 — Cài Python dependencies

```bash
conda activate mcqgen_v2

# PyTorch với CUDA 12.1
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# vLLM
pip install vllm==0.8.5 --extra-index-url https://download.pytorch.org/whl/cu121

# transformers (vLLM 0.8.5 cần 4.x, KHÔNG dùng 5.x)
pip install "transformers==4.51.3" --force-reinstall

# Remaining dependencies
pip install -r requirements_api.txt
```

> **Lưu ý CUDA path:** Nếu server dùng CUDA toolkit 11.8, thêm vào `~/.bashrc`:
>
> ```bash
> export CUDA_HOME=/usr/local/cuda-11.8
> export PATH=$CUDA_HOME/bin:$PATH
> export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
> ```

### Bước 5 — Download model Qwen2.5-7B-Instruct (~15GB)

```bash
export HF_HOME=/path/to/storage/.cache/huggingface
mkdir -p models

python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-7B-Instruct',
    local_dir='models/Qwen2.5-7B-Instruct',
    ignore_patterns=['*.msgpack', '*.h5']
)
print('Done!')
"
```

### Bước 6 — Chuẩn bị dữ liệu đầu vào

Đặt file vào đúng cấu trúc:

```
input/
├── slide/                    # PDF slides CS116 (11 bài)
│   ├── CS116-Bai02-Popular Libs.pdf
│   ├── CS116-Bai03-Pipeline & EDA.pdf
│   └── ...
├── transcribe_data/          # Whisper ASR JSON (79 files)
│   ├── 1.1.json              # Naming: {chapter}.{sub}.json
│   └── ...
└── videos1.txt               # YouTube URL mapping
```

### Bước 7 — Build vector index (chạy 1 lần)

```bash
conda activate mcqgen_v2

# Build toàn bộ pipeline tự động với DVC
dvc repro

# Hoặc từng bước thủ công
python -m src.mcqgen.chunk_transcripts   # ~2 phút → 924 transcript chunks
python -m src.mcqgen.indexing            # ~10 phút → 1220 chunks vào ChromaDB
python src/gen/sentence_window_indexing.py  # ~15 phút → 4756 SW chunks
```

### Bước 8 — Cài đặt Next.js frontend

```bash
cd webapp
npm install

# Tạo .env.local — thay SERVER_IP bằng IP thật
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://SERVER_IP:7860
NEXT_PUBLIC_WS_URL=ws://SERVER_IP:7860
EOF

npm run build
cd ..
```

---

## ▶️ Khởi động & Dừng hệ thống

### Khởi động

```bash
conda activate mcqgen_v2
bash scripts/start_system.sh
```

Script tự động khởi động 6 services theo thứ tự tối ưu (parallel khi có thể):

```
[1/6] Redis          → chờ PONG
[2/6] vLLM ─┐
      Langfuse├─ song song (~3 phút để load model)
      Next.js─┘
[3/6] Celery Worker  → sau khi Redis sẵn sàng
[4/6] FastAPI        → sau khi Redis sẵn sàng
[5/6] Wait vLLM      → block đến khi /health OK
[6/6] Confirm        → in URL tất cả services
```

Sau ~3-4 phút, các endpoint sẵn sàng:

| Service               | URL                          |
| --------------------- | ---------------------------- |
| 🖥️ Web UI             | `http://SERVER_IP:8081`      |
| 📡 API Docs (Swagger) | `http://SERVER_IP:8080/docs` |
| 📈 Langfuse           | `http://SERVER_IP:8083`      |
| 🌸 Celery Flower      | `http://SERVER_IP:6379`      |

### Dừng hệ thống

```bash
bash scripts/stop_system.sh
```

---

## 📖 Hướng dẫn sử dụng

### Tài khoản admin mặc định

Hệ thống khởi tạo sẵn một tài khoản admin duy nhất. Tất cả tài khoản người dùng thông thường (giảng viên, sinh viên) được **tự tạo qua giao diện đăng ký**.

| Role  | Username | Password     | Quyền                                 |
| ----- | -------- | ------------ | ------------------------------------- |
| Admin | `admin`  | (xem `.env`) | Quản lý hệ thống, xem toàn bộ lịch sử |

> ⚠️ **Production:** Đổi password admin trong `api/core/auth.py` hoặc qua biến môi trường trước khi triển khai.

---

### Đăng ký tài khoản

Người dùng chưa có tài khoản tự đăng ký qua giao diện web:

1. Truy cập `http://SERVER_IP:8081`
2. Tại trang đăng nhập, click **Đăng ký**
3. Điền thông tin: họ tên, tên đăng nhập, mật khẩu
4. Click **Tạo tài khoản** → chuyển tự động sang trang đăng nhập
5. Đăng nhập bằng tài khoản vừa tạo

---

### Người dùng — Sinh đề thi

1. Đăng nhập bằng tài khoản người dùng đã đăng ký
2. Click **⚡ Sinh câu hỏi** trên navbar
3. Nhập tên đề thi (VD: `exam_giua_ky`)
4. Thêm topics: **Chapter → Topic → Độ khó → Số câu**
5. Click **🚀 Sinh câu hỏi** → xem progress bar real-time qua WebSocket
6. Tải kết quả: **JSON**, **PDF Đề thi**, hoặc **PDF Đáp án**
   Ví dụ các chapter và topic:

| Chapter | Topic examples                                      |
| ------- | --------------------------------------------------- |
| Ch04    | SimpleImputer, dropna/fillna, Isolation Forest, IQR |
| Ch07b   | Decision Trees, Logistic Regression, SVM            |
| Ch08    | CNN Neural Networks, Convolution Layer              |
| Ch10    | Random Forest, Boosting, Bagging                    |

---

### Admin — Quản lý hệ thống

1. Đăng nhập bằng tài khoản admin
2. Truy cập **⚙️ Admin** trên navbar
3. Xem tổng quan: tổng đề thi, câu hỏi, quality score
4. Xem bảng lịch sử đề thi của tất cả người dùng
5. Quick links: API Docs / Langfuse

---

## 🔄 DVC Pipeline

Pipeline gồm 3 stages được định nghĩa trong `dvc.yaml`:

```
+---------------------+
| transcript_chunking |   input/transcribe_data/ → 924 transcript chunks
+---------------------+
          ↓
    +----------+
    | indexing |          slide PDFs + chunks → 1220 entries → ChromaDB
    +----------+
          ↓
  +---------------+
  | benchmark_rag |       Chạy Adaptive RAG và ghi benchmark report
  +---------------+
```

Lệnh thường dùng:

```bash
dvc dag          # Xem pipeline graph
dvc repro        # Rebuild stages bị thay đổi
dvc status       # Kiểm tra cache status
```

Khi thêm dữ liệu mới:

```bash
cp new_slide.pdf input/slide/
cp new_transcript.json input/transcribe_data/
dvc repro        # Tự động rebuild chỉ stages bị ảnh hưởng
git add .
git commit -m "data: add new chapter"
git tag -a "data-v1.x" -m "Added chapter XX"
git push origin master --tags
```

---

## 🐳 Triển khai Docker

### Build image

```bash
docker build -t mcqgen-api:v1.0 .
```

### Chạy với docker-compose

```bash
# Stack cơ bản: redis + api + worker + flower
docker-compose up -d

# Stack scalable (nhiều worker)
docker-compose -f docker-compose.scalable.yml up -d
```

Services trong `docker-compose.yml`:

| Service  | Port | Mô tả                         |
| -------- | ---- | ----------------------------- |
| `redis`  | 6379 | Broker/backend cho Celery     |
| `api`    | 8080 | FastAPI REST server           |
| `worker` | —    | Celery worker (concurrency=1) |

> **Lưu ý:** vLLM server chạy trên host machine (GPU access), API/Worker kết nối qua `host.docker.internal:7681`.

---

## 📡 API Reference

Xem đầy đủ tại `http://SERVER_IP:8080/docs` (Swagger UI).

| Method | Endpoint                     | Mô tả                     |
| ------ | ---------------------------- | ------------------------- |
| `POST` | `/auth/login`                | Đăng nhập, nhận JWT token |
| `POST` | `/generate`                  | Tạo job sinh MCQ (async)  |
| `GET`  | `/queue/status`              | Xem trạng thái queue      |
| `GET`  | `/exams`                     | Danh sách đề thi          |
| `GET`  | `/exams/{id}/export/pdf`     | Export đề thi PDF         |
| `GET`  | `/exams/{id}/export/answers` | Export đáp án PDF         |
| `WS`   | `/ws/{task_id}`              | WebSocket progress stream |
| `GET`  | `/health`                    | Health check              |

---

## 📊 Monitoring & Observability

### Langfuse (LLM Tracing)

Truy cập `http://SERVER_IP:8083` để xem:

- **Traces**: mỗi lần gọi LLM trong pipeline
- **Sessions**: toàn bộ quá trình sinh 1 đề thi
- **Scores**: quality score của từng MCQ
- **Users**: tracking theo giảng viên

### Structured Logging

API ghi log dạng JSON với `structlog`, xem tại `logs/fastapi.log`:

```bash
tail -f logs/fastapi.log | python3 -m json.tool
```

### Celery Flower

Truy cập `http://SERVER_IP:6379` để theo dõi task queue, worker status, và task history.

---

## ❓ Troubleshooting

**vLLM không start được**

```bash
nvidia-smi                    # Kiểm tra GPU
tail -50 logs/vllm.log        # Xem log
# Fix CUDA path nếu cần
export CUDA_HOME=/usr/local/cuda-11.8
```

**FastAPI trả về 401 Unauthorized**

```bash
# Test login trực tiếp
curl -s -X POST http://localhost:8080/auth/login \
  -d "username=giaovien&password=gv2026" | python3 -m json.tool
```

**ChromaDB lỗi "disk I/O error"**

```bash
rm -rf data/indexes/ data/processed/
dvc repro
```

**Next.js không kết nối được API**

```bash
# Kiểm tra .env.local phải dùng IP thật, không phải localhost
cat webapp/.env.local
curl http://SERVER_IP:8081/health
```

**Celery không nhận job**

```bash
redis-cli ping        # Phải ra PONG
tail -20 logs/celery.log
pkill -f "celery.*worker" && sleep 2
nohup celery -A api.tasks worker --loglevel=info --concurrency=1 \
    > logs/celery.log 2>&1 &
```

**Conflict bcrypt / transformers**

```bash
pip install "bcrypt==4.0.1" --force-reinstall
pip install "transformers==4.51.3" --force-reinstall
pip install "tokenizers>=0.21,<0.22" --force-reinstall
```

---

## 🔖 Release History

| Tag           | Nội dung                                                         |
| ------------- | ---------------------------------------------------------------- |
| `data-v1.0`   | DVC tracking — slides, transcripts, index                        |
| `prompt-v1.0` | Prompt versioning v1 (P1–P8)                                     |
| `v1.1`        | Full DVC pipeline + Adaptive RAG + FastAPI + Celery              |
| `v1.2`        | Phoenix LLM observability                                        |
| `v1.3`        | Parallel startup scripts                                         |
| `v1.4`        | PDF export API (đề thi + đáp án)                                 |
| `v1.5`        | PDF UI + GitHub Actions CI                                       |
| `v1.6`        | Docker containerization (mcqgen-api:v1.0)                        |
| `v1.7`        | Sentence-Window RAG (+81% Decision Trees)                        |
| `v1.8`        | Queue position display + `/queue/status` endpoint                |
| `v1.9`        | Langfuse tracing                                                 |
| `v2.0`        | JWT auth + Rate limiting + SQLite + structlog                    |
| `v2.1`        | Next.js 16 UI (Login, Dashboard, Generate, History, Quiz, Admin) |

---

## 👥 Nhóm thực hiện

Đồ án môn **CS317 — Hệ Thống Sinh Đề Thi Tham Khảo Cho Sinh Viên**, Nhóm 3
Trường Đại học Công nghệ Thông tin, ĐHQG TP.HCM
