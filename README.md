# CS431 MCQGen — Automatic MCQ Generation & Adaptive Learning System

> **CS116 — Lập trình Python cho Máy học | ĐH Công nghệ Thông tin ĐHQG-HCM**  
> Hệ thống tự động sinh câu hỏi trắc nghiệm chất lượng cao từ slide và transcript bài giảng, ứng dụng LLMOps production-grade.

![Python](https://img.shields.io/badge/Python-3.10-blue)
![vLLM](https://img.shields.io/badge/vLLM-0.8.5-green)
![FastAPI](https://img.shields.io/badge/FastAPI-2.0-009688)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![DVC](https://img.shields.io/badge/DVC-pipeline-purple)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## 📌 Tổng quan

Hệ thống tự động sinh câu hỏi trắc nghiệm (MCQ) cho môn CS116, sử dụng pipeline LLM 5 bước với Adaptive RAG (HyDE + Sentence-Window + CrossEncoder). Từ slide PDF và transcript bài giảng, hệ thống sinh câu hỏi chất lượng cao với tỉ lệ chấp nhận 100%.

**Cải thiện so với baseline (~60 phút/đề):**
- ⏱ Thời gian giảm từ **~60 phút → ~7 phút** (cải thiện 8×)
- 📈 RAG retrieval score tăng **+190%** trên topic yếu (Missing Data)
- ✅ Accept rate: **100%** | Quality score avg: **1.00/1.00**

---

## 📁 Cấu trúc project

Root của project chỉ giữ file cấu hình cấp dự án và entrypoint hạ tầng. Source code production nằm trong `src/mcqgen/`, API nằm trong `api/`, frontend nằm trong `webapp/`, script vận hành nằm trong `scripts/`.

```
cs317-mcqgen-llmops/
│
├── 🌐 api/                         # FastAPI + Celery service layer
│   ├── main.py                     # REST API, WebSocket, queue/status endpoints
│   ├── tasks.py                    # Celery task entrypoint
│   ├── pdf_exporter.py             # Export đề thi/đáp án ra PDF
│   └── core/
│       ├── auth.py                 # JWT auth + default users
│       ├── config.py               # Settings từ .env
│       ├── database.py             # SQLite models/session
│       └── logger.py               # Structured logging middleware
│
├── 🧠 src/
│   ├── mcqgen/                     # Production MCQ pipeline package
│   │   ├── pipeline_mcq.py         # Async MCQ generation pipeline
│   │   ├── advanced_retrieval.py   # Adaptive RAG: HyDE + SW + reranker
│   │   ├── common.py               # Config, prompts, JSON parser, utilities
│   │   ├── chunk_transcripts.py    # DVC stage: transcript chunking
│   │   └── indexing.py             # DVC stage: slide/transcript indexing
│   ├── adaptive/                   # Adaptive learning logic
│   ├── eval/                       # eval_overall, eval_iwf, metrics
│   └── gen/                        # Generation/indexing modules và legacy helpers
│
├── 🖥️ webapp/                      # Next.js 16 App Router frontend chính
│   ├── app/                        # Login, dashboard, generate, history, quiz
│   ├── components/                 # UI components
│   ├── lib/                        # API client, auth store, helpers
│   └── types/                      # TypeScript interfaces
│
├── ⚡ vllm/                        # Benchmark/experiment chứng minh hiệu quả vLLM
│   ├── exp02_llm_concurrency_sweep.py
│   ├── exp03_pipeline_sequential_vs_async.py
│   ├── exp04_max_num_seqs_ablation.py
│   ├── exp05_prefix_cache_ablation.py
│   ├── exp06_official_vllm_bench.py
│   ├── exp07_no_vllm_baselines.py
│   └── vllm_demo_plan_mcqgen.md
│
├── 📊 monitoring/                  # Langfuse tracing configs
│   ├── langfuse_tracing.py
│   └── langfuse/
│
├── 🧪 tests/                       # Test/debug scripts thủ công
├── 🛠️ scripts/                     # Script vận hành
│   ├── start_system.sh
│   ├── stop_system.sh
│   └── set_env.sh
│
├── 📚 docs/                        # Tài liệu phụ, ghi chú fix, latency plan
├── 🎛️ vllm_demo_webapp/            # Web demo riêng cho experiment vLLM
├── 🧾 prompts/                     # Versioned prompt assets
├── 📥 input/                       # Input: slide, transcript, topic list
├── 📦 data/                        # Processed data, ChromaDB index, SQLite DB
├── 🤖 models/                      # Local model weights, không commit Git
├── 📝 logs/                        # Runtime logs, không commit Git
├── 📤 output/                      # Output đề thi, không commit Git
├── 🧩 tmp/                         # Temporary runtime files, không commit Git
│
├── dvc.yaml                        # DVC pipeline
├── dvc.lock
├── Dockerfile
├── docker-compose.yml
├── requirements_api.txt
├── .env.example
└── README.md
```

Các lệnh chạy core pipeline hiện dùng Python module path:

```bash
python -m src.mcqgen.chunk_transcripts
python -m src.mcqgen.indexing
python -m src.mcqgen.advanced_retrieval adaptive
python -m src.mcqgen.pipeline_mcq
```

---

## 🏗️ Kiến trúc hệ thống

```
Browser (:3000 Next.js)  ←→  FastAPI REST API (:7860)
                                      ↓ JWT Auth
                              Celery Worker ← Redis (:6379)
                                      ↓
                          Adaptive RAG Pipeline
                            ├── HyDE Query Generation
                            ├── Sentence-Window ChromaDB
                            └── CrossEncoder Reranker
                                      ↓
                          MCQ Generation — vLLM (:8000)
                            ├── P1: Gen Stem
                            ├── P4: Gen Distractors
                            ├── P5-P7: Select Best
                            ├── P8: Assemble MCQ
                            └── Eval: Quality Check
                                      ↓
                          Output: JSON + PDF

Observability Stack:
  Langfuse (:8083)
```

---

## 🖥️ Yêu cầu hệ thống

| Thành phần | Yêu cầu tối thiểu |
|------------|-------------------|
| GPU | RTX 2080 Ti 11GB VRAM (hoặc VRAM ≥ 10GB) |
| RAM | ≥ 32GB |
| Disk | ≥ 100GB |
| CUDA Driver | ≥ 12.2 — kiểm tra: `nvidia-smi` |
| OS | Ubuntu 20.04+ |
| Python | 3.10 (qua Conda) |
| Node.js | 20.x |
| Docker | ≥ 27.x + Docker Compose v2 |

---

## 🚀 Cài đặt từ đầu (Full Setup)

### Bước 1 — Clone repository

```bash
git clone https://github.com/PTX-Tien/cs431-mcqgen-llmops.git
cd cs317-mcqgen-llmops
```

### Bước 2 — Tạo Conda environment

```bash
# Tạo env Python 3.10
conda create -n mcqgen_v2 python=3.10 -y
conda activate mcqgen_v2

# Cài Node.js 20 (dùng cho Next.js webapp)
conda install -c conda-forge nodejs=20 -y

# Verify
python --version    # Python 3.10.x
node --version      # v20.x.x
npm --version       # 10.x.x
```

### Bước 3 — Thiết lập biến môi trường

```bash
# Copy template
cp .env.example .env

# Mở và chỉnh sửa — BẮT BUỘC đổi JWT_SECRET
nano .env
```

Nội dung `.env` cần chỉnh:

```bash
# ── vLLM ─────────────────────────────────────────
VLLM_URL=http://localhost:8000/v1
VLLM_MODEL=mcqgen
VLLM_TIMEOUT=120

# ── Auth — PHẢI ĐỔI SECRET ───────────────────────
JWT_SECRET=your-very-long-random-secret-minimum-32-chars

# ── Database ──────────────────────────────────────
DATABASE_URL=sqlite:///./data/mcqgen.db

# ── Redis ─────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER=redis://localhost:6379/0
CELERY_BACKEND=redis://localhost:6379/0
TASK_RESULT_TTL_SECONDS=86400

# ── Rate Limit ────────────────────────────────────
RATE_LIMIT_TEACHER=10/hour
RATE_LIMIT_STUDENT=30/hour

# ── Monitoring ────────────────────────────────────
LOG_LEVEL=INFO
PHOENIX_ENDPOINT=http://localhost:6006/v1/traces
```

### Bước 4 — Cài Python dependencies

```bash
conda activate mcqgen_v2

# Cài PyTorch với CUDA 12.1
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

# Cài vLLM
pip install vllm==0.8.5 --extra-index-url https://download.pytorch.org/whl/cu121

# Cài transformers đúng version (vLLM 0.8.5 cần transformers 4.x, KHÔNG dùng 5.x)
pip install "transformers==4.51.3" --force-reinstall

# Cài toàn bộ dependencies còn lại
pip install -r requirements.txt

# Verify GPU
python -c "
import torch
print('CUDA available:', torch.cuda.is_available())
print('GPU:', torch.cuda.get_device_name(0))
print('VRAM:', round(torch.cuda.get_device_properties(0).total_memory/1e9, 1), 'GB')
"
```

> ⚠️ **Lưu ý CUDA path:** Nếu server dùng CUDA toolkit 11.8 nhưng driver 12.x, cần thêm vào `~/.bashrc`:
> ```bash
> export CUDA_HOME=/usr/local/cuda-11.8
> export PATH=$CUDA_HOME/bin:$PATH
> export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
> ```

### Bước 5 — Download model Qwen2.5-7B-Instruct

```bash
# Đặt HuggingFace cache vào storage có đủ dung lượng
export HF_HOME=/path/to/large/storage/.cache/huggingface

mkdir -p models
python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-7B-Instruct',
    local_dir='models/Qwen2.5-7B-Instruct',
    ignore_patterns=['*.msgpack', '*.h5']
)
print('Model downloaded successfully!')
"
```

> ⏱ Download khoảng 15GB, mất thời gian tùy mạng.

### Bước 6 — Chuẩn bị dữ liệu đầu vào

```bash
# Cấu trúc thư mục input cần có:
input/
├── slide/                      # PDF slides CS116
│   ├── CS116-Bai02-Popular Libs.pdf
│   ├── CS116-Bai03-Pipeline & EDA.pdf
│   ├── CS116-Bai04-Data preprocessing.pdf
│   ├── CS116-Bai05-Eval model.pdf
│   ├── CS116-Bai06-Unsupervised learning.pdf
│   ├── CS116-Bai07a-Supervised learning-Regression.pdf
│   ├── CS116-Bai07b-Supervised learning-Classification.pdf
│   ├── CS116-Bai08-Deep learning voi CNN.pdf
│   ├── CS116-Bai09-Parameter tuning.pdf
│   ├── CS116-Bai10-Ensemble model.pdf
│   └── CS116-Bai11-Model Deployment.pdf
├── transcribe_data/            # Whisper ASR JSON (79 files)
│   ├── 1.1.json
│   ├── 1.2.json
│   └── ... (naming: {chapter}.{sub}.json)
└── videos1.txt                 # YouTube URL mapping
```

### Bước 7 — Build vector index (Chạy 1 lần)

```bash
conda activate mcqgen_v2

# Build toàn bộ pipeline tự động (recommended)
dvc repro

# Hoặc build từng bước nếu muốn theo dõi:
python -m src.mcqgen.chunk_transcripts  # Bước 1: ~2 phút → 924 transcript chunks
python -m src.mcqgen.indexing           # Bước 2: ~10 phút → 1220 chunks vào ChromaDB
python src/gen/sentence_window_indexing.py  # Bước 3: ~15 phút → 4756 SW chunks

# Kiểm tra kết quả
dvc dag     # Xem pipeline graph
dvc status  # Kiểm tra trạng thái
```

> ⏱ Tổng thời gian lần đầu: ~30 phút.

### Bước 8 — Setup Next.js frontend

```bash
cd webapp

# Cài Node dependencies
npm install

# Tạo env file — THAY SERVER_IP bằng IP thật của server
# Xem IP: hostname -I | awk '{print $1}'
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://192.168.20.154:7860
NEXT_PUBLIC_WS_URL=ws://192.168.20.154:7860
EOF

# Thêm config Next.js để tránh CORS trong dev
cat > next.config.ts << 'EOF'
import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  allowedDevOrigins: ['192.168.20.154'],  // Thay bằng IP server thật
};
export default nextConfig;
EOF

# Build production
npm run build

cd ..
```

---

## ▶️ Khởi động system

```bash
conda activate mcqgen_v2
bash scripts/start_system.sh
```

Script tự động khởi động các services theo thứ tự tối ưu (parallel khi có thể):

```
[1/6] Redis          → khởi động, chờ PONG
[2/6] vLLM           ─┐
      Langfuse        ├─ khởi động song song (~3 phút để load model)
      Next.js         ─┘
[3/6] Celery Worker  → khởi động (chỉ cần Redis)
[4/6] FastAPI        → khởi động (chỉ cần Redis)
[5/6] Wait vLLM      → block đến khi /health OK (không timeout)
[6/6] Next.js        → khởi động sau khi FastAPI sẵn sàng
```

**Output mong đợi sau ~3-4 phút:**

```
📊 System Status:
  ✅ Redis      :6379
  ✅ FastAPI    :8080
  ✅ Next.js    :8081
  ✅ Langfuse   :8083
  ✅ vLLM       :7681

  🌐 UI:        http://192.168.20.154:8081
  🔧 API docs:  http://192.168.20.154:8080/docs
  📈 Langfuse:  http://192.168.20.154:8083
```

---

## 🌐 Truy cập các services

| Service | URL | Mô tả |
|---------|-----|-------|
| 🖥️ **Web UI** | `http://SERVER_IP:8081` | Giao diện chính (Next.js) |
| 📡 **API Docs** | `http://SERVER_IP:8080/docs` | Swagger UI |
| 📈 **Langfuse** | `http://SERVER_IP:8083` | LLM traces, sessions, users, scores |

### Tài khoản mặc định

| Role | Username | Password | Quyền |
|------|----------|----------|-------|
| Giảng viên | `giaovien` | `gv2026` | Sinh MCQ, lịch sử, admin |
| Sinh viên | `sinhvien` | `sv2026` | Làm quiz |

> ⚠️ **Production:** Đổi password trong `api/core/auth.py`

---

## 📖 Hướng dẫn sử dụng

### Giảng viên — Sinh đề thi

1. Truy cập `http://SERVER_IP:3000` → đăng nhập `giaovien/gv2026`
2. Click **⚡ Sinh câu hỏi** trên navbar
3. Nhập tên đề thi (VD: `exam_giua_ky`)
4. Thêm topics: **Chapter → Topic → Độ khó → Số câu**
5. Click **🚀 Sinh câu hỏi** → theo dõi progress bar real-time
6. Khi hoàn thành: tải **JSON**, **PDF Đề thi**, hoặc **PDF Đáp án**

**Các chapter và topic gợi ý:**

| Chapter | Topic examples |
|---------|---------------|
| Ch04 | SimpleImputer, dropna/fillna, Isolation Forest, IQR |
| Ch07b | Decision Trees, Logistic Regression, SVM |
| Ch08 | CNN Neural Networks, Convolution Layer |
| Ch10 | Random Forest, Boosting, Bagging |

### Sinh viên — Làm bài quiz

1. Truy cập `http://SERVER_IP:3000/quiz`
2. Nhập họ tên + MSSV
3. Upload file JSON đề thi (lấy từ giảng viên export)
4. Click **🚀 Bắt đầu làm bài**
5. Chọn đáp án, điều hướng bằng nút **← Trước / Tiếp →**
6. Click **Nộp bài ✓** → xem điểm + phân tích theo topic

### Admin — Quản lý hệ thống

1. Đăng nhập giảng viên → **⚙️ Admin** trên navbar
2. Xem tổng quan: tổng đề thi, câu hỏi, quality score
3. Bảng lịch sử đề thi của tất cả người dùng
4. Quick links: API Docs / Langfuse

### Kiểm tra chất lượng MCQ

```bash
# Chạy pipeline trực tiếp (không qua UI) để test
TOKEN=$(curl -s -X POST http://localhost:7860/auth/login \
  -d "username=giaovien&password=gv2026" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:7860/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topics": [
      {"topic_id":"t1","chapter_id":"ch07b","topic":"Decision Trees","difficulty":"G2","n":3}
    ],
    "output_name": "test_exam"
  }' | python3 -m json.tool
```

---

## ⏹️ Dừng system

```bash
bash scripts/stop_system.sh
```

**Output mong đợi:**

```
Stopping MCQGen system...
  ✅ FastAPI stopped
  ✅ Celery stopped
  ✅ Phoenix stopped
  ✅ Next.js stopped
  ✅ vLLM stopped
  ✅ Redis stopped
Done.
```

---

## 🔄 DVC Pipeline

```bash
dvc dag          # Xem pipeline graph
dvc repro        # Rebuild nếu data thay đổi
dvc status       # Kiểm tra trạng thái
```

**Pipeline graph:**

```
+---------------------+
| transcript_chunking |  → 924 chunks (từ 79 Whisper JSON)
+---------------------+
          ↓
    +----------+
    | indexing |         → 1220 chunks → ChromaDB
    +----------+
          ↓
   +---------------+
   | benchmark_rag |     → RAG quality report
   +---------------+
```

**Khi có slide hoặc transcript mới:**

```bash
# Copy file mới vào đúng thư mục
cp new_slide.pdf input/slide/
cp new_transcript.json input/transcribe_data/

# Rebuild tự động chỉ những stage bị ảnh hưởng
dvc repro

# Commit
git add .
git commit -m "data: add new chapter slide"
git tag -a "data-v1.x" -m "Added chapter XX"
git push origin master --tags
```

---

## 🛠️ Tech Stack

| Layer | Tool | Version |
|-------|------|---------|
| **Frontend** | Next.js + TypeScript + Tailwind | 16.x |
| **UI Components** | shadcn/ui | latest |
| **State** | Zustand | 4.x |
| **Backend API** | FastAPI | 0.136 |
| **Auth** | JWT (python-jose) | 3.3.0 |
| **Task Queue** | Celery + Redis | 5.x |
| **LLM Serving** | vLLM | 0.8.5 |
| **LLM Model** | Qwen2.5-7B-Instruct | — |
| **RAG** | HyDE + Sentence-Window + CrossEncoder | custom |
| **Embedding** | BAAI/bge-m3 | — |
| **Vector DB** | ChromaDB | 1.5.x |
| **Data Version** | DVC | — |
| **LLM Tracing** | Langfuse | self-host |
| **Database** | SQLite (sqlmodel) | — |
| **Logging** | structlog (JSON) | 24.x |
| **Export** | ReportLab (PDF) | — |
| **CI/CD** | GitHub Actions | — |
| **Container** | Docker Compose | v2 |

---

## ❓ Troubleshooting

### vLLM không start được
```bash
# Kiểm tra GPU
nvidia-smi

# Kiểm tra CUDA path
which nvcc
nvcc --version

# Xem log
tail -50 logs/vllm.log

# Fix CUDA path nếu cần
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

### FastAPI 401 Unauthorized
```bash
# Test login
curl -s -X POST http://localhost:7860/auth/login \
  -d "username=giaovien&password=gv2026" | python3 -m json.tool

# Lấy token và test
TOKEN=$(curl -s -X POST http://localhost:7860/auth/login \
  -d "username=giaovien&password=gv2026" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -H "Authorization: Bearer $TOKEN" http://localhost:7860/queue/status
```

### ChromaDB lỗi "disk I/O error"
```bash
# Xóa index bị corrupt và rebuild
rm -rf data/indexes/ data/processed/
dvc repro
```

### Next.js không đăng nhập được
```bash
# Kiểm tra IP trong .env.local
cat webapp/.env.local
# Phải là IP thật: NEXT_PUBLIC_API_URL=http://192.168.x.x:7860
# KHÔNG dùng localhost nếu truy cập từ máy khác

# Test API trực tiếp
curl http://SERVER_IP:7860/health
```

### Celery không nhận job
```bash
# Kiểm tra Redis
redis-cli ping  # phải ra PONG

# Kiểm tra log
tail -20 logs/celery.log

# Restart worker
pkill -f "celery.*worker" 2>/dev/null
sleep 2
nohup celery -A api.tasks worker --loglevel=info --concurrency=1 \
    > logs/celery.log 2>&1 &
```

### bcrypt version conflict
```bash
pip install "bcrypt==4.0.1" --force-reinstall
pkill -f uvicorn; sleep 2
nohup uvicorn api.main:app --host 0.0.0.0 --port 7860 > logs/fastapi.log 2>&1 &
```

### transformers conflict sau khi cài package mới
```bash
pip install "transformers==4.51.3" --force-reinstall
pip install "tokenizers>=0.21,<0.22" --force-reinstall
```

---

## 📊 Hiệu năng benchmark

| Metric | Giá trị |
|--------|---------|
| Thời gian sinh 15 MCQ | ~7–11 phút |
| Accept rate | 100% (0 failed) |
| Quality score (avg) | 1.00 / 1.00 |
| Latency P50 / P99 | 45.1s / 2m 3s |
| RAG improvement (avg) | +46% vs naive |
| RAG improvement (Decision Trees) | **+81%** — Sentence-Window |
| RAG improvement (Missing Data) | **+190%** — HyDE |
| Chunks indexed (standard) | 1,220 |
| Chunks indexed (sentence-window) | 4,756 |

---

## 🔖 Release History

| Tag | Nội dung |
|-----|---------|
| `data-v1.0` | DVC tracking — slides, transcripts, index |
| `prompt-v1.0` | Prompt versioning v1 (P1-P8) |
| `v1.1` | Full DVC pipeline + Adaptive RAG + FastAPI + Celery |
| `v1.2` | Phoenix LLM observability |
| `v1.3` | Parallel startup scripts (no hardcoded timeout) |
| `v1.4` | PDF export API (đề thi + đáp án) |
| `v1.5` | PDF UI + GitHub Actions CI |
| `v1.6` | Docker containerization (mcqgen-api:v1.0) |
| `v1.7` | Sentence-Window RAG (+81% Decision Trees) |
| `v1.8` | Queue position display + /queue/status endpoint |
| `v1.9` | Langfuse tracing and observability |
| `v2.0` | JWT auth + Rate limiting + SQLite + structlog |
| `v2.1` | Next.js 16 UI (Login, Dashboard, Generate, History, Quiz, Admin) |

---

## 👥 Nhóm thực hiện

Đồ án môn **CS317 — Hệ Thống Sinh Đề Thi Tham Khảo Cho Sinh Viên**, nhóm 8  
Trường Đại học Công nghệ Thông tin, ĐHQG TP.HCM
