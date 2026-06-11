# CS317 — MCQGen: Hệ Thống Sinh Đề Thi MCQ Tự Động với LLMOps

> **Đồ án môn CS317 — Nhóm 3 | ĐH Công nghệ Thông tin, ĐHQG TP.HCM**  
> Hệ thống sinh câu hỏi trắc nghiệm từ slide PDF và transcript bài giảng, kết hợp RAG, prompt engineering, vLLM serving và Langfuse tracing.

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
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Tech Stack](#️-tech-stack)
- [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Khởi động & dừng hệ thống](#-khởi-động--dừng-hệ-thống)
- [Hướng dẫn sử dụng](docs/huong-dan-su-dung.md)
- [DVC Pipeline](#-dvc-pipeline)
- [Triển khai Docker](#-triển-khai-docker)
- [Troubleshooting](#-troubleshooting)
- [Release History](#-release-history)
- [Nhóm thực hiện](#-nhóm-thực-hiện)

---

## 📌 Tổng quan

MCQGen là hệ thống end-to-end tự động sinh câu hỏi trắc nghiệm (Multiple Choice Questions) cho môn **CS116 — Lập trình Python cho Máy học**.  
Hệ thống nhận đầu vào là slide PDF và transcript bài giảng (Whisper ASR), sau đó đi qua pipeline RAG + prompt engineering để sinh câu hỏi chất lượng cao.

Điểm LLMOps chính của project:

- DVC quản lý pipeline dữ liệu.
- vLLM host model local.
- FastAPI + Celery + Redis xử lý request bất đồng bộ.
- Langfuse theo dõi trace, session, user, score và latency.
- Docker hỗ trợ triển khai local/container.

---

## 🏆 Kết quả nổi bật

| Metric                       | Kết quả                                                  |
| ---------------------------- | -------------------------------------------------------- |
| Thời gian sinh 1 MCQ         | ~2-3 phút (giảm từ ~60 phút thủ công, cải thiện **20×**) |
| Quality score trung bình     | **1.00 / 1.00**                                          |
| RAG improvement (trung bình) | +46% so với naive retrieval                              |
| Latency P50 / P99            | 45.1s / 2m 3s                                            |

---

## 🏗️ Kiến trúc hệ thống

![Kiến trúc hệ thống](architecture-summary.svg)

Tóm tắt:

- Next.js: login, dashboard, generate, history, quiz.
- FastAPI: auth, generate, status, results, PDF export.
- Celery + Redis: async queue và progress tracking.
- RAG pipeline: slide PDF + transcript → clean/chunk/index → ChromaDB.
- vLLM: host Qwen2.5-7B-Instruct local.
- Langfuse: trace session, user, prompt stage, score, token usage.

---

## 🛠️ Tech Stack

| Layer                  | Công nghệ                             | Phiên bản |
| ---------------------- | ------------------------------------- | --------- |
| Frontend               | Next.js + TypeScript + Tailwind CSS   | 16.x      |
| UI Components          | shadcn/ui                             | latest    |
| State Management       | Zustand                               | 5.0.12    |
| Backend API            | FastAPI                               | 0.136     |
| Authentication         | JWT (python-jose)                     | 3.3.0     |
| Task Queue             | Celery + Redis                        | 5.x       |
| LLM Serving            | vLLM                                  | 0.8.5     |
| LLM Model              | Qwen2.5-7B-Instruct                   | —         |
| RAG Strategy           | HyDE + Sentence-Window + CrossEncoder | custom    |
| Embedding Model        | BAAI/bge-m3                           | —         |
| Vector Database        | ChromaDB                              | 1.5.x     |
| Data Versioning        | DVC                                   | —         |
| LLM Observability      | Langfuse (self-hosted)                | —         |
| Relational DB          | SQLite (sqlmodel)                     | —         |
| Structured Logging     | structlog (JSON)                      | 24.x      |
| PDF Export             | ReportLab                             | —         |
| CI/CD                  | GitHub Actions                        | —         |
| Containerization       | Docker + Docker Compose v2            | —         |

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
```

### Bước 3 — Cấu hình biến môi trường

Xem file mẫu tại [`.env.example`](.env.example).  
Người dùng chỉ cần copy file này thành `.env` rồi chỉnh theo máy của mình.

### Bước 4 — Cài Python dependencies

```bash
pip install -r requirements_api.txt
```

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

Tải bộ dữ liệu gốc của nhóm tại: **[Google Drive dữ liệu đầu vào](<THÊM_LINK_GOOGLE_DRIVE_CỦA_NHÓM_VÀO_ĐÂY>)**

Sau khi tải về, đặt file vào đúng cấu trúc:

```text
input/
├── slide/                    # PDF slides CS116 (11 bài)
│   ├── CS116-Bai02-Popular Libs.pdf
│   ├── CS116-Bai03-Pipeline & EDA.pdf
│   └── ...
├── transcribe_data/          # Whisper ASR JSON
│   ├── 1.1.json
│   └── ...
└── videos1.txt               # YouTube URL mapping
```

### Bước 7 — Build vector index (chạy 1 lần)

```bash
conda activate mcqgen_v2
dvc repro
```

Hoặc chạy từng bước:

```bash
python -m src.mcqgen.chunk_transcripts
python -m src.mcqgen.indexing
python src/gen/sentence_window_indexing.py
```

### Bước 8 — Cài đặt Next.js frontend

```bash
cd webapp
npm install
npm run build
cd ..
```

---

## ▶️ Khởi động & dừng hệ thống

### Khởi động

```bash
conda activate mcqgen_v2
bash scripts/start_system.sh
```

Sau khi hệ thống lên, các URL chính:

| Service          | URL                          |
| ---------------- | ---------------------------- |
| Web UI           | `http://SERVER_IP:8081`      |
| API Docs         | `http://SERVER_IP:8080/docs` |
| Langfuse         | `http://SERVER_IP:8083`      |

### Dừng hệ thống

```bash
bash scripts/stop_system.sh
```

---

## 📖 Hướng dẫn sử dụng

Chi tiết được tách sang file riêng:

- [docs/huong-dan-su-dung.md](docs/huong-dan-su-dung.md)

---

## 🔄 DVC Pipeline

Pipeline gồm 3 stages:

```text
transcript_chunking → indexing → benchmark_rag
```

Lệnh thường dùng:

```bash
dvc dag
dvc repro
dvc status
```

Khi thêm dữ liệu mới:

```bash
cp new_slide.pdf input/slide/
cp new_transcript.json input/transcribe_data/
dvc repro
git add .
git commit -m "data: add new chapter"
```

---

## 🐳 Triển khai Docker

### Build image

```bash
docker build -t mcqgen-api:v1.0 .
```

### Chạy với docker-compose

```bash
docker-compose up -d
docker-compose -f docker-compose.scalable.yml up -d
```

---

## ❓ Troubleshooting

**vLLM không start được**

```bash
nvidia-smi
tail -50 logs/vllm.log
```

**FastAPI trả về 401 Unauthorized**

```bash
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
cat webapp/.env.local
curl http://SERVER_IP:8081/health
```

---

## 🔖 Release History

| Tag           | Nội dung                                           |
| ------------- | -------------------------------------------------- |
| `data-v1.0`   | DVC tracking — slides, transcripts, index         |
| `prompt-v1.0` | Prompt versioning v1 (P1–P8)                      |
| `v1.1`        | Full DVC pipeline + Adaptive RAG + FastAPI + Celery |
| `v1.8`        | Queue position display + `/queue/status` endpoint |
| `v1.9`        | Langfuse tracing                                  |
| `v2.0`        | JWT auth + Rate limiting + SQLite + structlog    |
| `v2.1`        | Next.js 16 UI (Login, Dashboard, Generate, History, Quiz, Admin) |

---

## 👥 Nhóm thực hiện

Đồ án môn **CS317 — Hệ Thống Sinh Đề Thi Tham Khảo Cho Sinh Viên**, Nhóm 3  
Trường Đại học Công nghệ Thông tin, ĐHQG TP.HCM

