# CS431 MCQGen — Automatic MCQ Generation & Adaptive Learning System

> **CS116 — Lập trình Python cho Máy học | ĐH Công nghệ Thông tin ĐHQG-HCM**  
> Hệ thống tự động sinh câu hỏi trắc nghiệm chất lượng cao từ slide và transcript bài giảng, ứng dụng LLMOps production-grade.

![Python](https://img.shields.io/badge/Python-3.10-blue)
![vLLM](https://img.shields.io/badge/vLLM-0.8.5-green)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688)
![DVC](https://img.shields.io/badge/DVC-pipeline-purple)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## 📌 Tổng quan

Hệ thống tự động sinh câu hỏi trắc nghiệm (MCQ) cho môn CS116, sử dụng pipeline LLM 5 bước với Adaptive RAG. Từ slide PDF và transcript bài giảng, hệ thống tạo ra câu hỏi chất lượng cao với tỉ lệ chấp nhận 100% và quality score trung bình 1.00.

**Cải thiện so với baseline thí nghiệm:**
- ⏱ Thời gian giảm từ **~60 phút → ~7 phút** (cải thiện 8×)
- 📈 RAG retrieval score tăng **+190%** trên topic yếu (Missing Data)
- ✅ Accept rate: **100%** (15/15 câu)

---

## 🏗️ Kiến trúc hệ thống

```
┌─────────────────────────────────────────────┐
│              USER LAYER                     │
│   Streamlit UI (:8501) / FastAPI (:7860)    │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           ORCHESTRATION LAYER               │
│        Celery + Redis (Async Queue)         │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │         ADAPTIVE RAG PIPELINE       │   │
│  │  HyDE → BGE-m3 → CrossEncoder      │   │
│  │  ChromaDB Vector Store (1220 chunks)│   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │       MCQ GENERATION (5 calls)      │   │
│  │  P1: Gen Stem + Self-Refine         │   │
│  │  P4: Gen Distractor Candidates      │   │
│  │  P5+P6+P7: Select Best Distractors  │   │
│  │  P8: Assemble Final MCQ             │   │
│  │  Eval: 8-criteria Quality Check     │   │
│  └─────────────────────────────────────┘   │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           INFERENCE LAYER                   │
│   vLLM Server — Qwen3-8B-AWQ (:8000)       │
│   RTX 2080 Ti 11GB | AWQ 4-bit | FP16      │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│       OBSERVABILITY & DATA LAYER            │
│   Phoenix Monitoring (:6006)                │
│   DVC Pipeline (3 stages)                  │
│   ChromaDB + Redis + SQLite                 │
└─────────────────────────────────────────────┘
```

---

## ⚡ Quick Start

### Yêu cầu
- GPU: RTX 2080 Ti 11GB (hoặc tương đương, VRAM ≥ 10GB)
- RAM: ≥ 16GB
- CUDA: Driver ≥ 12.2
- Python 3.10, Conda

### Khởi động toàn bộ system

```bash
git clone https://github.com/PTX-Tien/cs431-mcqgen-llmops.git
cd cs431-mcqgen-llmops

conda create -n mcqgen_v2 python=3.10 -y
conda activate mcqgen_v2
pip install -r requirements.txt

# Khởi động tất cả services (parallel)
bash start_system.sh
```

Truy cập:
| Service | URL |
|---------|-----|
| 🖥️ Web UI | `http://SERVER_IP:8501` |
| 🔧 API Docs | `http://SERVER_IP:7860/docs` |
| 📈 Monitoring | `http://SERVER_IP:6006` |

### Dừng system

```bash
bash stop_system.sh
```

---

## 📊 Hiệu năng

| Metric | Giá trị |
|--------|---------|
| Thời gian sinh 15 MCQ | ~7 phút |
| Accept rate | 100% (15/15) |
| Quality score (avg) | 1.00 / 1.00 |
| Latency P50 / P99 | 45.1s / 2m3s |
| RAG improvement (avg) | +75% vs naive |
| RAG improvement (weak topics) | +190% (HyDE) |
| Total chunks indexed | 1,220 (296 slide + 924 transcript) |

---

## 🛠️ Tech Stack

| Layer | Component | Tool |
|-------|-----------|------|
| **LLM Serving** | Inference engine | vLLM 0.8.5 |
| **LLM Model** | Generation + Eval | Qwen3-8B-AWQ (4-bit) |
| **RAG** | Retrieval strategy | Adaptive RAG (HyDE + CrossEncoder) |
| **Embedding** | Semantic search | BAAI/bge-m3 |
| **Reranker** | Result reranking | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| **Vector DB** | Chunk storage | ChromaDB |
| **Task Queue** | Async execution | Celery + Redis |
| **API** | REST endpoints | FastAPI |
| **UI** | Web interface | Streamlit |
| **Data Versioning** | Pipeline tracking | DVC |
| **Monitoring** | LLM observability | Arize Phoenix |
| **CI/CD** | Automated testing | GitHub Actions |
| **Export** | Output format | PDF (ReportLab) + JSON |

---

## 📁 Cấu trúc project

```
cs431-mcqgen-llmops/
│
├── pipeline_mcq.py          # Core MCQ generation pipeline
├── advanced_retrieval.py    # Adaptive RAG (HyDE + CrossEncoder)
├── indexing.py              # Slide + transcript indexing
├── chunk_transcripts.py     # Whisper JSON → semantic chunks
├── common.py                # Prompts P1-P8, configs
├── dvc.yaml                 # DVC pipeline definition
│
├── api/
│   ├── main.py              # FastAPI REST endpoints
│   ├── tasks.py             # Celery async tasks
│   └── pdf_exporter.py      # PDF export (đề thi + đáp án)
│
├── monitoring/
│   └── setup_tracing.py     # Phoenix OpenTelemetry tracing
│
├── prompts/
│   └── v1/                  # Versioned prompt templates
│
├── input/
│   ├── slide/               # PDF slides (CS116 chapters)
│   ├── transcribe_data/     # Whisper ASR JSON output
│   └── videos1.txt          # YouTube URL mapping
│
├── streamlit_app.py         # Web UI
├── start_system.sh          # Parallel startup script
├── stop_system.sh           # Graceful shutdown
└── .github/
    └── workflows/
        └── ci.yml           # GitHub Actions CI
```

---

## 🔄 DVC Pipeline

Pipeline tự động rebuild khi data thay đổi (slide mới, transcript mới):

```
┌─────────────────────┐
│  transcript_chunking │  → 924 transcript chunks
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│      indexing        │  → 1220 chunks vào ChromaDB
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   benchmark_rag      │  → RAG quality report
└─────────────────────┘
```

```bash
dvc dag          # Xem pipeline graph
dvc repro        # Rebuild nếu data thay đổi
dvc status       # Kiểm tra trạng thái
```

---

## 🧠 Adaptive RAG Strategy

```
Topic query
    ↓
[Naive check] Best score ≥ 0.25?
    ├── YES → Naive embedding + CrossEncoder Rerank
    └── NO  → HyDE (generate hypothetical question)
                  ↓
              Ensemble embed (60% topic + 40% HyDE)
                  ↓
              Retrieve top-12 + CrossEncoder Rerank → top-5
```

**Kết quả benchmark:**

| Topic | Strategy | Naive | Adaptive | Delta |
|-------|----------|-------|----------|-------|
| Missing Data | HyDE+rerank | 0.136 | 0.238 | +75% |
| Decision Trees | naive+rerank | 0.366 | 0.366 | 0% |
| CNN Networks | HyDE+rerank | 0.244 | 0.279 | +14% |
| Outlier Detection | naive+rerank | 0.296 | 0.296 | 0% |

---

## 📈 Monitoring

Phoenix dashboard tại `http://SERVER_IP:6006`:

- **Traces**: Toàn bộ LLM call history
- **Latency**: P50/P75/P90/P99 percentiles
- **Token usage**: Prompt + completion tokens
- **Error tracking**: Failed calls và nguyên nhân

---

## 🔖 Release History

| Tag | Nội dung |
|-----|---------|
| `data-v1.0` | DVC tracking — slides, transcripts, index |
| `prompt-v1.0` | Prompt versioning v1 (P1-P8) |
| `v1.1` | Full DVC pipeline + Adaptive RAG + FastAPI + Celery |
| `v1.2` | Phoenix observability |
| `v1.3` | Parallel startup scripts |
| `v1.4` | PDF export API |
| `v1.5` | PDF download UI + GitHub Actions CI |

---

## 👥 Nhóm thực hiện

Đồ án môn **CS317 — Phát triển và Vận hành hệ thống học máy**, nhóm 14  
Trường Đại học Công nghệ Thông tin, ĐHQG TP.HCM