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
- [Practical Extension for Lab](#-practical-extension-for-lab)
- [Kết quả nổi bật](#-kết-quả-nổi-bật)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Tech Stack](#️-tech-stack)
- [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Khởi động & dừng hệ thống](#-khởi-động--dừng-hệ-thống)
- [Hướng dẫn sử dụng](docs/huong-dan-su-dung.md)
- [Monitoring & Evaluation với Langfuse](#-monitoring--evaluation-với-langfuse)
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

## 🧪 Practical Extension for Lab

So với project ban đầu, phiên bản dùng cho bài thực hành nhấn mạnh các thành phần vận hành **LLMOps** thay vì chỉ dừng ở việc gọi LLM để sinh câu hỏi. Các phần mở rộng chính gồm:

- **Data pipeline có thể tái lập**: DVC xử lý slide/transcript, sinh chunk, build vector index và benchmark retrieval.
- **RAG optimization**: hỗ trợ adaptive retrieval với naive retrieval, HyDE, sentence-window collection và cross-encoder rerank.
- **Prompt optimization**: quản lý prompt theo version, bổ sung style bank từ đề CS116 thật, guardrail cho opening style và misconception-guided distractor.
- **Serving/runtime optimization**: phục vụ Qwen2.5-7B-Instruct bằng vLLM local, tận dụng batching, prefix caching, async pipeline và dynamic concurrency.
- **System optimization**: FastAPI + Celery + Redis cho xử lý bất đồng bộ, Redis cache cho request trùng và dedup câu hỏi theo lịch sử.
- **Observability**: Langfuse tracing cho session, user, latency, token usage, input/output từng stage, accepted/rejected scores và reject reason.

**Lưu ý quan trọng:**

- Nhóm **không fine-tune / quantize / optimize trọng số** của Qwen2.5-7B-Instruct.
- Phần "model optimization" trong project này được hiểu theo đúng bối cảnh **LLMOps**: tối ưu retrieval, prompt, runtime serving, cache, concurrency và monitoring.
- Các kết quả đo phụ thuộc GPU, version vLLM và workload. Những mục chưa đo đầy đủ được ghi rõ trong báo cáo, đặc biệt là so sánh prompt v1/v2 và prefix-cache ablation.

### Báo cáo liên quan tới bài thực hành

Các báo cáo hiện có:

- [Báo cáo Data Pipeline](reports/data_pipeline_report.md): mô tả xử lý slide/transcript, chunking, embedding, ChromaDB index và metric cần ghi nhận cho pipeline dữ liệu.
- [Báo cáo Data Validation](reports/data_validation_report.md): kiểm tra dữ liệu đầu vào và output processed; run hiện tại **PASS có cảnh báo**, 0 error, 2 warning.
- [Báo cáo Evaluation](reports/eval_results.md): tổng hợp run sinh đề `exam_01`, acceptance rate, phân bố accepted MCQ, RAG strategy và duplicate rate.
- [Báo cáo Optimization Strategy trực quan](reports/optimization_summary.md): chuyển phần Optimization Strategy ra report riêng, dùng dashboard hình ảnh để giải thích RAG, prompt/Langfuse trace, vLLM serving, async pipeline, quality gate, cache và các mục cần nói thận trọng.

---

## 🏆 Kết quả nổi bật

| Hạng mục | Kết quả / ghi nhận hiện tại |
| --- | --- |
| Data validation | **PASS có cảnh báo**: 0 error, 2 warning; 79 transcript JSON, 11 slide PDF; 780 transcript chunks và 993 concept chunks. |
| Evaluation run `exam_01` | 18 câu được yêu cầu, 8 câu accepted, 10 câu rejected/failed → **acceptance rate 44.4%**. |
| Duplicate trong accepted | 0 câu trùng theo stem trong 8 câu accepted → dedup theo lịch sử hoạt động tốt ở run này. |
| Adaptive RAG | Benchmark cho thấy adaptive retrieval không kém naive trên 4 topic thử nghiệm, trung bình Δ ≈ **+0.034**; HyDE chỉ được kích hoạt khi naive retrieval yếu. |
| vLLM serving | Throughput tăng khoảng **3.85×** từ concurrency 1 → 4, trong khi latency P50 gần như giữ quanh ~5.7s. |
| Async pipeline | Pipeline async nhanh hơn sequential khoảng **2.08×** ở phần generation-only trong thử nghiệm nhỏ. |
| Observability | Langfuse ghi nhận input/output từng prompt stage, latency, token usage, accepted/failed counts, acceptance rate và `reject_stage.<stage>`. |

---

## 🏗️ Kiến trúc hệ thống

![Kiến trúc hệ thống](figure/architecture-summary.svg)

Tóm tắt:

- Next.js: login, dashboard, generate, history, quiz.
- FastAPI: auth, generate, status, results, PDF export.
- Celery + Redis: async queue, progress tracking, cache và load tracking.
- RAG pipeline: slide PDF + transcript → clean/chunk/index → ChromaDB → adaptive retrieval/rerank.
- vLLM: host Qwen2.5-7B-Instruct local qua OpenAI-compatible API.
- Langfuse: trace session, user, prompt stage, input/output, latency, token usage, score và reject stage.

Luồng tối ưu prompt và trace bằng Langfuse được trình bày chi tiết trong [Báo cáo Optimization Strategy trực quan](reports/optimization_summary.md).

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

## 📡 Monitoring & Evaluation với Langfuse

Langfuse là kênh chính để nhóm debug và tối ưu pipeline sinh đề. Trong code, các wrapper tại `monitoring/langfuse_tracing.py` được dùng để tạo observation, cập nhật output, metadata, usage và score cho từng trace.

### Trace hierarchy

Một lượt generate đề thường có cấu trúc trace như sau:

```text
mcqgen.generate_exam
├── api.generate.submit
├── celery.run_mcq_pipeline
│   ├── rag.retrieve / rag.cache_hit
│   ├── llm.P1_gen_stem_key
│   ├── llm.P4_option_candidates
│   ├── llm.P5_cot_evaluate
│   ├── llm.P6_remove_bad
│   ├── llm.P7_select_final
│   ├── llm.P8_assemble
│   ├── guardrail.opening_check
│   ├── llm.OPENING_REPAIR
│   ├── llm.P9_explanation
│   └── llm.final_eval
└── trace scores: accepted_questions, failed_questions, acceptance_rate, reject_stage.<stage>
```

### Vì sao trace giúp tối ưu prompt?

Mỗi prompt stage đều lưu input/output rút gọn, metadata và usage. Khi một MCQ bị reject, nhóm có thể mở trace để xác định lỗi xảy ra ở layer nào:

- **RAG lỗi**: context retrieval không liên quan hoặc similarity thấp.
- **P1 lỗi**: stem/correct answer chưa rõ hoặc output không parse được JSON.
- **P4/P5/P6/P7 lỗi**: distractor không hợp lý, quá dễ, trùng ý hoặc không đúng misconception.
- **Opening lỗi**: câu hỏi mở đầu theo template xấu, bị guardrail phát hiện và repair/reject.
- **Final eval lỗi**: câu hỏi không đủ chất lượng, không đúng topic/chapter hoặc chưa đạt chuẩn format.
- **Dedup lỗi**: câu hỏi quá giống lịch sử của user.

Từ các failure stage này, nhóm quay lại chỉnh đúng prompt tương ứng thay vì sửa toàn bộ pipeline một cách cảm tính. Ví dụ: nếu nhiều câu fail ở `opening_check`, cần cập nhật `bad_openings.json` hoặc `opening_families.json`; nếu fail ở distractor, cần bổ sung `misconception_types.json` hoặc ràng buộc P4/P5 rõ hơn.

### Cách xem nhanh trên dashboard

Sau khi khởi động hệ thống:

```bash
bash scripts/start_system.sh
```

Mở Langfuse tại:

```text
http://SERVER_IP:8083
```

Các trường nên kiểm tra:

- Trace name: `mcqgen.generate_exam`.
- Observation name: `rag.retrieve`, `llm.P1_gen_stem_key`, `llm.P4_option_candidates`, `guardrail.opening_check`, `llm.final_eval`.
- Scores: `accepted_questions`, `failed_questions`, `acceptance_rate`, `reject_stage.<stage>`.
- Tags/metadata: `traffic:*`, `ccu:*`, `usecase:generate_exam`, `run:*`, `loadtest:<id>`.

### Evaluation hiện tại

Run `exam_01` hiện có 18 câu được yêu cầu, 8 câu accepted và 10 câu rejected/failed, tương ứng **acceptance rate 44.4%**. Run này chưa lưu chi tiết `failure_info_json`, vì vậy muốn phân tích reject đầy đủ cần generate đề mới bằng pipeline hiện tại rồi chạy lại script evaluation tương ứng trong môi trường repo.

---

## 🔄 DVC Pipeline

Pipeline trong `dvc.yaml` gồm 3 stages:

```text
transcript_chunking → indexing → benchmark_rag
```

Ý nghĩa từng stage:

| Stage | Output chính | Vai trò |
| --- | --- | --- |
| `transcript_chunking` | `data/processed/transcript_chunks_with_timestamps.jsonl` | Cắt transcript thành chunk có timestamp/youtube_url. |
| `indexing` | `data/processed/concept_chunks.jsonl`, `data/indexes/` | Gộp slide + transcript, sinh concept chunks và build ChromaDB index. |
| `benchmark_rag` | `data/benchmarks/rag_benchmark.log` | Chạy benchmark adaptive RAG để kiểm tra retrieval. |

Lệnh thường dùng:

```bash
dvc dag
dvc repro
dvc status
```

Sau khi chạy pipeline, đối chiếu thêm với [Báo cáo Data Validation](reports/data_validation_report.md) để kiểm tra số chunk, field bắt buộc, duplicate id, lỗi parse và các warning dữ liệu.

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
| `v2.2`        | README cập nhật báo cáo validation/evaluation/optimization + minh họa Langfuse prompt tracing |

---

## 👥 Nhóm thực hiện

Đồ án môn **CS317 — Hệ Thống Sinh Đề Thi Tham Khảo Cho Sinh Viên**, Nhóm 3  
Trường Đại học Công nghệ Thông tin, ĐHQG TP.HCM
