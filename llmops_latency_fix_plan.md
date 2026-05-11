# Kế hoạch tối ưu latency cho hệ thống MCQGen LLMOps

## 0. Mục tiêu

Mục tiêu của bản sửa là giảm thời gian generate đề thi trong pipeline LLMOps mà vẫn giữ được các thành phần cần thiết để chứng minh dự án có LLMOps/RAG/vLLM/monitoring.

Hiện trạng quan sát từ log:

- Sinh 12 câu mất khoảng 27.6 phút.
- Trung bình khoảng 138 giây/câu.
- 12 câu tạo ra khoảng 89 request LLM tới vLLM.
- RAG bị chạy lặp lại theo từng câu dù nhiều câu cùng topic.
- Phoenix tracing bị lỗi liên tục vì Phoenix server không chạy nhưng tracing vẫn cố export span.
- vLLM đang giới hạn concurrency thấp với `--max-num-seqs 4` và context dài `--max-model-len 8192`.

Nguyên tắc fix:

1. Sửa lỗi runtime trước khi tối ưu sâu.
2. Đo timing trước khi thay đổi lớn.
3. Giảm số lần gọi LLM/câu.
4. Cache RAG theo topic.
5. Sau khi pipeline nhẹ hơn mới tune vLLM.
6. Không giảm prompt/context khi chưa có xác nhận của chủ dự án.

---

## 1. Thứ tự fix khuyến nghị

| Thứ tự | Layer | Việc cần làm | Lý do ưu tiên | Mức ảnh hưởng kỳ vọng |
|---:|---|---|---|---|
| 1 | Layer 4 | Fix Phoenix tracing | Đang lỗi liên tục, spam log, có thể làm chậm từng LLM call | Trung bình |
| 2 | Instrumentation | Thêm timing log từng phase | Cần số liệu để tránh tối ưu đoán mò | Cao cho debug |
| 3 | Layer 1 | Preload RAG/pipeline khi Celery worker start | Loại bỏ cold start 1-2 phút ở task đầu | Trung bình/cao |
| 4 | Layer 2 | Cache/precompute RAG theo `(topic, chapter_id)` | Tránh retrieve lại nhiều lần cho cùng topic | Cao |
| 5 | Layer 2 | Thêm chế độ HyDE trên UI | HyDE chỉ bật khi cần chất lượng retrieval cao | Trung bình/cao |
| 6 | Layer 3 | Bỏ `eval overall` khỏi production path | Giảm ít nhất 1 LLM call/câu | Cao |
| 7 | Layer 5 | Tune vLLM: `max_model_len=4096`, `max_num_seqs=8` | Tăng batching/concurrency sau khi pipeline nhẹ hơn | Trung bình |
| 8 | Layer 2/5 | Rà soát prompt/context cần giảm | Chỉ làm sau khi có timing và hỏi xác nhận | Cao nhưng có rủi ro chất lượng |
| 9 | Optional | Endpoint/job warmup hoặc tách RAG service resident | Dùng nếu deploy thực tế cần latency ổn định | Tùy kiến trúc |

---

# 2. Layer 4 — Fix Phoenix tracing trước

## 2.1. Vấn đề

Trong log có lỗi lặp lại:

```text
Exception while exporting Span
ConnectionRefusedError: [Errno 111] Connection refused
HTTPConnectionPool(host='localhost', port=6006)
```

Nguyên nhân chính:

- Phoenix server không start đúng.
- Pipeline vẫn bật OpenTelemetry/OpenInference instrumentation.
- Sau mỗi LLM request, tracing cố export span đến Phoenix và lỗi.

## 2.2. File cần sửa

- `start_system.sh`
- `monitoring/setup_tracing.py`
- `.env.example`
- `.env`

## 2.3. Sửa `start_system.sh`

Nếu command hiện tại giống dạng:

```bash
TMPDIR=$PROJECT/tmp python -m phoenix.server.main serve --port 6006 --host 0.0.0.0
```

và được truyền vào hàm `start_bg` dùng `nohup`, nên sửa thành:

```bash
env TMPDIR=$PROJECT/tmp python -m phoenix.server.main serve --port 6006 --host 0.0.0.0
```

Lý do: khi dùng `nohup`, `TMPDIR=...` có thể bị hiểu nhầm là tên executable. `env TMPDIR=... python ...` an toàn hơn.

## 2.4. Thêm env flag

Trong `.env.example`:

```env
ENABLE_TRACING=0
PHOENIX_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_HEALTH_URL=http://localhost:6006/healthz
```

Khuyến nghị default:

```env
ENABLE_TRACING=0
```

Chỉ bật khi cần demo monitoring:

```env
ENABLE_TRACING=1
```

## 2.5. Sửa `monitoring/setup_tracing.py`

Đề xuất logic:

```python
import os
import requests


def init_tracing(project_name: str = "mcqgen"):
    if os.getenv("ENABLE_TRACING", "0") != "1":
        print("ℹ️ Tracing disabled by ENABLE_TRACING")
        return None

    health_url = os.getenv("PHOENIX_HEALTH_URL", "http://localhost:6006/healthz")
    endpoint = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")

    try:
        requests.get(health_url, timeout=0.5)
    except Exception as e:
        print(f"⚠️ Phoenix not healthy, tracing disabled: {e}")
        return None

    try:
        from phoenix.otel import register
        from openinference.instrumentation.openai import OpenAIInstrumentor

        tracer_provider = register(
            project_name=project_name,
            endpoint=endpoint,
        )
        OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        print(f"✅ Phoenix tracing enabled: {endpoint}")
        return tracer_provider
    except Exception as e:
        print(f"⚠️ Failed to initialize tracing, disabled: {e}")
        return None
```

## 2.6. Test sau khi sửa

```bash
export ENABLE_TRACING=0
bash start_system.sh
```

Sau đó generate 1 câu và kiểm tra:

```bash
grep -c "Exception while exporting Span" logs/celery.log
```

Kỳ vọng:

```text
0
```

Nếu bật tracing:

```bash
export ENABLE_TRACING=1
curl -s http://localhost:6006/healthz
```

Kỳ vọng Phoenix healthy trước khi worker chạy.

---

# 3. Thêm timing log trước khi tối ưu sâu

## 3.1. Vì sao cần làm

Hiện ta biết pipeline chậm, nhưng cần đo chính xác:

- RAG mất bao lâu?
- P1/P4/P5/P6/P7/P8 mất bao lâu?
- Eval overall mất bao lâu?
- Tổng thời gian/câu là bao nhiêu?

Nếu không có timing log thì dễ tối ưu sai chỗ.

## 3.2. File cần sửa

- `pipeline_mcq.py`
- Có thể thêm `api/core/logger.py` nếu muốn structured logging, nhưng bản tối thiểu chỉ cần `print` hoặc logger hiện có.

## 3.3. Code helper đề xuất

```python
import time
from contextlib import asynccontextmanager


@asynccontextmanager
async def atimer(name: str, q_id: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[TIMING] {q_id} | {name} | {dt:.2f}s")
```

Bọc quanh các bước chính:

```python
async with atimer("RAG", q_id):
    context, rag_debug = await adaptive_retrieve(topic, chapter_id)

async with atimer("P1", q_id):
    raw_p1 = await llm(p1_prompt, temperature=0.7, max_tokens=768)

async with atimer("P4", q_id):
    raw_p4 = await llm(p4_prompt, temperature=0.7, max_tokens=384)

async with atimer("P8", q_id):
    raw_p8 = await llm(p8_prompt, temperature=0.1, max_tokens=768)
```

## 3.4. Test

Generate 1 câu:

```bash
tail -f logs/celery.log | grep TIMING
```

Kỳ vọng có log dạng:

```text
[TIMING] t1_q00 | RAG | 3.12s
[TIMING] t1_q00 | P1 | 8.45s
[TIMING] t1_q00 | P4 | 5.77s
[TIMING] t1_q00 | total | 31.25s
```

---

# 4. Layer 1 — Cold start Celery/RAG

## 4.1. Vấn đề

Task đầu tiên bị chậm vì worker phải load các thành phần nặng:

- Embedding model: `BAAI/bge-m3`
- CrossEncoder reranker
- Chroma collection
- Có thể cả Phoenix tracing/instrumentation

Nếu load xảy ra trong lúc task đầu tiên chạy, user sẽ thấy job đầu tiên bị cộng thêm 1-2 phút.

---

## 4.2. Phương án A — Preload pipeline/RAG khi worker start

### Ý tưởng

Khi Celery worker vừa khởi động, ta import/load sẵn RAG models và collection. Khi user bấm generate, các thành phần này đã sẵn sàng.

### Ưu điểm

- Dễ triển khai nhất.
- Không cần thay đổi kiến trúc lớn.
- Phù hợp với project hiện tại.
- Giữ nguyên Celery + FastAPI + pipeline hiện có.

### Nhược điểm

- Worker start chậm hơn.
- Nếu worker crash/restart thì vẫn cần warm lại.
- Nếu có nhiều worker, mỗi worker có thể load riêng model, tốn RAM.

### Khuyến nghị

Nên làm ngay. Đây là lựa chọn mặc định cho project hiện tại.

### File cần sửa

- `api/tasks.py`
- `advanced_retrieval.py` nếu cần thêm hàm `warmup_retriever()`

### Cách làm đề xuất

Trong `advanced_retrieval.py`, thêm hàm warmup:

```python
def warmup_retriever():
    """Force load embedding model, reranker, and Chroma collection."""
    # Gọi nhẹ vào các global object đã được lazy/global init.
    # Tùy code thực tế, có thể chỉ cần import module là đã load.
    _ = collection.count()
    _ = embed_model
    _ = reranker
    print("✅ RAG retriever warmed up")
```

Trong `api/tasks.py`:

```python
from celery.signals import worker_process_init


@worker_process_init.connect
def preload_worker_process(**kwargs):
    try:
        from advanced_retrieval import warmup_retriever
        warmup_retriever()
        print("✅ Celery worker preload completed")
    except Exception as e:
        print(f"⚠️ Celery worker preload failed: {e}")
```

Lưu ý: nếu Celery chạy `concurrency=1` thì cách này đơn giản. Nếu concurrency > 1, mỗi process có thể preload riêng.

---

## 4.3. Phương án B — Endpoint/job warmup

### Ý tưởng

Tạo một endpoint hoặc task đặc biệt để gọi trước khi demo/deploy:

```text
POST /admin/warmup
```

Endpoint này sẽ:

1. Load RAG model.
2. Load reranker.
3. Kiểm tra Chroma collection.
4. Gửi một request nhỏ đến vLLM để warm model/KV/cuda path.
5. Kiểm tra Phoenix nếu tracing bật.

### Ví dụ flow

```text
Admin mở dashboard
→ bấm nút "Warm up system"
→ backend chạy warmup
→ UI hiển thị "System ready"
→ lúc này mới generate đề
```

### Ưu điểm

- Chủ động trước khi demo.
- Dễ hiển thị trạng thái readiness trên UI.
- Có thể warm cả FastAPI, Celery, RAG, vLLM.
- Không làm worker start quá chậm nếu không cần dùng ngay.

### Nhược điểm

- User/admin phải nhớ chạy warmup.
- Nếu system idle lâu hoặc worker restart thì cần warm lại.
- Cần thêm endpoint và quyền admin.
- Không thay thế hoàn toàn preload nếu worker bị restart liên tục.

### Khi nào nên dùng

Nên dùng nếu:

- Bạn demo với giáo sư và muốn bấm warmup trước.
- Bạn deploy nhưng chưa có traffic thường xuyên.
- Bạn muốn dashboard có trạng thái `ready/not ready`.

Không bắt buộc nếu:

- Worker luôn chạy resident.
- Có health check và preload tự động ổn định.

### Đề xuất UI label

Tên nút nên dễ hiểu:

```text
Khởi động nóng hệ thống
```

Hoặc ngắn hơn:

```text
Warm up hệ thống
```

Mô tả tooltip:

```text
Tải trước mô hình RAG và gửi một request thử tới vLLM để giảm độ trễ cho lần generate đầu tiên.
```

---

## 4.4. Phương án C — Tách RAG service luôn resident

### Ý tưởng

Thay vì Celery worker import trực tiếp `advanced_retrieval.py`, ta tách RAG thành một service riêng:

```text
FastAPI/Celery → RAG Service → Chroma + Embedding + Reranker
```

RAG service luôn chạy, load sẵn embedding/reranker trong RAM. Khi pipeline cần context, nó gọi HTTP/gRPC nội bộ:

```text
POST http://rag-service:9000/retrieve
```

### Ưu điểm

- RAG luôn resident, giảm cold start.
- Có thể scale RAG độc lập với generation worker.
- Dễ cache context trong RAG service.
- Dễ monitoring riêng latency retrieval.
- Kiến trúc production rõ ràng hơn.

### Nhược điểm

- Thay đổi kiến trúc nhiều hơn.
- Thêm network hop.
- Phải quản lý thêm service, Docker, health check, logging.
- Có thể overkill cho project môn học nếu deadline gần.

### Khi nào nên dùng

Nên cân nhắc nếu:

- Bạn triển khai lâu dài.
- Nhiều worker cùng dùng chung RAG.
- RAG model/reranker nặng và không muốn mỗi worker load riêng.
- Cần benchmark latency RAG riêng.

Chưa nên làm ngay nếu:

- Mục tiêu hiện tại là fix nhanh demo.
- Project chỉ chạy 1 server/1 worker.
- Chưa có timing log chứng minh RAG là bottleneck lớn nhất.

### Khuyến nghị hiện tại

Chưa tách RAG service ngay. Nên làm theo thứ tự:

1. Preload RAG trong Celery worker.
2. Cache RAG theo topic.
3. Thêm timing log.
4. Nếu vẫn chậm hoặc muốn production hóa sâu hơn, mới tách RAG service.

---

# 5. Layer 2 — RAG chậm và bị lặp lại

## 5.1. Cache RAG theo key `(topic, chapter_id)`

### Vấn đề

Nếu generate 5 câu cùng topic `Decision Trees`, hiện pipeline có thể gọi RAG 5 lần. Trong khi context cho 5 câu này gần như giống nhau.

### File cần sửa

- `pipeline_mcq.py`

### Thiết kế

Cache theo key:

```python
rag_key = (topic_cfg["topic"], topic_cfg["chapter_id"])
```

Giá trị cache:

```python
rag_cache[rag_key] = {
    "context": context,
    "rag_debug": rag_debug,
}
```

### Code hướng sửa

Trong `run_pipeline_with_topics()`:

```python
rag_cache = {}

for topic_cfg, _seq in task_specs:
    key = (topic_cfg["topic"], topic_cfg["chapter_id"])
    if key not in rag_cache:
        context, rag_debug = await adaptive_retrieve(
            topic_cfg["topic"],
            topic_cfg["chapter_id"],
        )
        rag_cache[key] = (context, rag_debug)
```

Trong `generate_one_mcq()` thêm tham số:

```python
async def generate_one_mcq(
    topic_cfg: dict,
    seq: int,
    precomputed_rag: tuple[str, dict] | None = None,
) -> dict | None:
    ...
    if precomputed_rag is None:
        context, rag_debug = await adaptive_retrieve(topic, chapter_id)
    else:
        context, rag_debug = precomputed_rag
```

Khi gọi:

```python
key = (topic_cfg["topic"], topic_cfg["chapter_id"])
return await generate_one_mcq(topic_cfg, seq, precomputed_rag=rag_cache[key])
```

### Expected impact

Nếu 25 câu thuộc 5 topic:

```text
Trước: 25 RAG calls
Sau:   5 RAG calls
```

---

## 5.2. Precompute context theo topic trước khi generate câu

### Ý tưởng

Tách phase RAG và phase LLM generation:

```text
Phase 1: unique topics → retrieve context
Phase 2: generate all questions using precomputed context
```

### Lợi ích

- Log rõ ràng hơn.
- Biết RAG mất bao lâu trước khi LLM chạy.
- Dễ cache theo topic.
- Dễ hiển thị progress UI:
  - `Retrieving context...`
  - `Generating questions...`
  - `Exporting...`

### Progress UI đề xuất

| Phase | Progress |
|---|---:|
| Prepare job | 0-5% |
| Retrieve context per topic | 5-25% |
| Generate MCQs | 25-90% |
| Save/export result | 90-100% |

---

## 5.3. Giảm `top_k`, `top_k_final`, độ dài context

### Vấn đề

Context quá dài làm:

- Prompt dài hơn.
- vLLM xử lý chậm hơn.
- KV cache lớn hơn.
- Batch kém hơn.
- Reranker phải xử lý nhiều candidate hơn.

### Những tham số cần tìm trong code

Trong `advanced_retrieval.py`, cần tìm các biến/hàm liên quan:

```python
top_k
top_k_final
n_results
max_context_chars
max_context_tokens
rerank_top_k
```

### Hướng giảm đề xuất ban đầu

Nếu hiện tại chưa rõ value, đề xuất test theo 3 profile:

| Profile | top_k retrieval | top_k_final | Context target | Dùng khi |
|---|---:|---:|---:|---|
| Fast | 8-12 | 3 | 1,500-2,500 tokens | realtime UI |
| Balanced | 15-20 | 4-5 | 2,500-4,000 tokens | demo chất lượng |
| Quality | 30+ | 6-8 | 4,000-6,000 tokens | benchmark/offline |

### Lưu ý quan trọng

Không tự giảm context ngay nếu chưa kiểm tra chất lượng. Cần hỏi/confirm trước khi giảm vì có thể làm câu hỏi kém bám sát bài học.

Prompt hỏi xác nhận trước khi giảm:

```text
Hiện context retrieval đang khá dài, làm vLLM batch kém hơn. Bạn muốn tôi giảm context cho chế độ realtime xuống khoảng 2,000-2,500 tokens/topic không? Chế độ quality vẫn giữ context dài để benchmark.
```

---

## 5.4. Chỉ bật HyDE khi thật sự cần

### Vấn đề

HyDE thêm một LLM call để tạo truy vấn giả lập. Nếu bật thường xuyên, latency tăng rõ rệt.

### Chiến lược đề xuất

Không nên chỉ có bật/tắt cứng. Nên có 3 mode:

| Mode nội bộ | Tên hiển thị UI | Mô tả cho user | Hành vi |
|---|---|---|---|
| `fast` | Nhanh | Ưu tiên tốc độ, phù hợp generate đề nhanh | Không dùng HyDE |
| `auto` | Cân bằng | Tự bật tìm kiếm nâng cao khi context ban đầu chưa đủ tốt | Chỉ dùng HyDE nếu score thấp |
| `quality` | Chất lượng cao | Ưu tiên độ bám sát nội dung, có thể chậm hơn | Bật HyDE + reranker |

### UI/UX đề xuất

Thêm một dropdown hoặc segmented control trong trang Generate:

Label chính:

```text
Chế độ truy xuất tài liệu
```

Options:

1. `Nhanh`
2. `Cân bằng`
3. `Chất lượng cao`

Tooltip:

```text
Chọn cách hệ thống tìm ngữ cảnh từ bài giảng. Chế độ Nhanh giảm thời gian generate. Chế độ Chất lượng cao có thể dùng HyDE để tìm ngữ cảnh tốt hơn nhưng sẽ chậm hơn.
```

Giải thích ngắn dưới dropdown:

```text
Khuyến nghị: dùng "Cân bằng" cho hầu hết đề ôn tập. Dùng "Chất lượng cao" khi topic khó hoặc cần câu hỏi bám sát nội dung hơn.
```

### Backend payload đề xuất

Frontend gửi thêm:

```json
{
  "retrieval_mode": "auto"
}
```

Trong backend map:

```python
retrieval_mode = request.retrieval_mode or "auto"
```

Trong `advanced_retrieval.py`:

```python
async def adaptive_retrieve(topic: str, chapter_id: str, mode: str = "auto"):
    if mode == "fast":
        return await retrieve_naive_rerank(topic, chapter_id, use_hyde=False)

    if mode == "quality":
        return await retrieve_with_hyde(topic, chapter_id)

    # auto
    context, debug = await retrieve_naive_rerank(topic, chapter_id, use_hyde=False)
    best_score = max(debug.get("top_scores_after_rerank", [0]))
    if best_score < 0.45:
        return await retrieve_with_hyde(topic, chapter_id)
    return context, debug
```

Threshold `0.45` chỉ là giá trị khởi đầu, cần đo lại bằng log thực tế.

---

# 6. Layer 3 — Giảm số LLM calls/câu

## 6.1. Việc cần làm ngay: bỏ `eval overall` khỏi production

### Vấn đề

`eval overall` chỉ dùng để đánh giá chất lượng sau khi sinh. Trong production realtime, bước này làm tăng latency vì thêm 1 LLM call/câu.

### File cần sửa

- `pipeline_mcq.py`
- Có thể thêm `.env` flag

### Env đề xuất

```env
ENABLE_LLM_EVAL=0
```

### Code hướng sửa

Trong `pipeline_mcq.py`:

```python
ENABLE_LLM_EVAL = os.getenv("ENABLE_LLM_EVAL", "0") == "1"
```

Ở đoạn eval overall:

```python
if ENABLE_LLM_EVAL:
    eval_prompt = build_eval_overall_prompt(mcq)
    raw_eval = await llm(eval_prompt, temperature=0.0, max_tokens=512)
    eval_data = parse_json_output(raw_eval)
    mcq["evaluation"] = eval_data

    if not eval_data.get("overall_valid", False):
        print(f"❌ rejected by LLM eval: {q_id}")
        return None
else:
    mcq["evaluation"] = {
        "enabled": False,
        "overall_valid": None,
        "note": "LLM evaluation disabled in production mode."
    }
```

### Expected impact

Với 25 câu:

```text
Giảm ít nhất 25 LLM calls
```

Nếu mỗi call mất 5-15s, tiết kiệm khoảng 2-6 phút hoặc hơn.

---

## 6.2. Không khuyến nghị bỏ toàn bộ quality pipeline ngay

Hiện user yêu cầu chỉ bỏ eval overall. Vì vậy chưa nên tự ý đổi sang 1-call fast mode nếu chưa xác nhận.

Tuy nhiên, nên chuẩn bị kiến trúc mode:

| Mode | Dùng cho | Eval overall |
|---|---|---|
| `production` | UI generate thực tế | Tắt |
| `benchmark` | đo chất lượng/LLMOps report | Bật |
| `debug` | phân tích lỗi prompt/output | Bật tùy chọn |

Env:

```env
PIPELINE_MODE=production
ENABLE_LLM_EVAL=0
```

---

# 7. Layer 5 — Tune vLLM config realtime

## 7.1. Mục tiêu

Tăng khả năng batching và giảm KV cache pressure.

## 7.2. File cần sửa

- `start_system.sh`
- Có thể `.env.example` nếu muốn config hóa

## 7.3. Config hiện tại cần đổi

Đổi:

```bash
--max-model-len 8192
--max-num-seqs 4
```

Thành:

```bash
--max-model-len 4096
--max-num-seqs 8
```

Command gợi ý:

```bash
vllm serve models/Qwen3-8B-AWQ \
  --dtype half \
  --quantization awq \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --disable-log-requests \
  --max-num-seqs 8 \
  --port 8000 \
  --host 0.0.0.0 \
  --served-model-name mcqgen
```

## 7.4. Lưu ý về `--enforce-eager`

Nếu hiện đang có:

```bash
--enforce-eager
```

nên test bỏ flag này. Log trước đó cho thấy:

```text
Since enforce-eager is enabled, async output processor cannot be used
```

Nhưng không nên khẳng định bỏ luôn nếu chưa test trên GPU hiện tại. Cách làm an toàn:

1. Test config A: giữ `--enforce-eager`, chỉ đổi `max_model_len` và `max_num_seqs`.
2. Test config B: bỏ `--enforce-eager`.
3. So sánh latency 5 câu/10 câu.

## 7.5. Test sau khi đổi

```bash
grep "Maximum concurrency" logs/vllm.log | tail -5
grep "Running:" logs/vllm.log | tail -20
```

Kỳ vọng:

- Maximum concurrency tăng so với trước.
- Ít dòng `Pending` hơn.
- Không OOM.

Nếu OOM:

```bash
--max-num-seqs 6
```

hoặc giảm context/prompt sau khi có xác nhận.

---

# 8. Prompt/context cần giảm — chưa sửa ngay

## 8.1. Vì sao cần hỏi trước

Giảm prompt/context có thể làm:

- Câu hỏi ít bám sát bài học hơn.
- Distractor kém chất lượng hơn.
- Mất rationale hoặc metadata cần cho demo LLMOps.

Vì vậy không tự giảm ngay. Cần đo và xác nhận.

## 8.2. Những phần có thể giảm sau khi xác nhận

| Thành phần | Cách giảm | Rủi ro |
|---|---|---|
| RAG context | Giảm số chunks/top_k_final | Mất thông tin quan trọng |
| Prompt P1 | Bớt instruction lặp lại | Output kém ổn định hơn |
| Prompt P5/P6/P7 | Gộp hoặc rút ngắn tiêu chí | Distractor kém kiểm soát hơn |
| Explanation/rationale | Giới hạn độ dài | Câu trả lời ít giải thích hơn |
| JSON schema | Giữ field cần thiết, bỏ field debug | Mất dữ liệu phục vụ analysis |

## 8.3. Câu hỏi xác nhận cần hỏi trước khi giảm

```text
Bạn có muốn tối ưu prompt/context theo chế độ production không? Nếu có, tôi sẽ giữ lại các field bắt buộc cho UI/PDF, giảm context xuống khoảng 2,000-2,500 tokens/topic và rút ngắn instruction lặp lại. Chế độ benchmark vẫn giữ prompt đầy đủ.
```

---

# 9. Test plan tổng thể sau khi fix

## 9.1. Test đơn vị service

```bash
redis-cli ping
curl -s http://localhost:8000/health
curl -s http://localhost:7860/health
curl -s http://localhost:6006/healthz
```

Kỳ vọng:

```text
Redis: PONG
vLLM: OK
FastAPI: OK
Phoenix: OK nếu ENABLE_TRACING=1
```

Nếu `ENABLE_TRACING=0`, Phoenix không bắt buộc.

---

## 9.2. Test generate 1 câu

Mục tiêu:

- Không còn tracing exception.
- Có timing log.
- Eval overall không chạy nếu `ENABLE_LLM_EVAL=0`.

Kiểm tra:

```bash
grep "TIMING" logs/celery.log | tail -20
grep -c "Exception while exporting Span" logs/celery.log
grep -c "eval overall" logs/celery.log
```

---

## 9.3. Test generate nhiều câu cùng topic

Payload ví dụ:

```json
{
  "topics": [
    {
      "topic_id": "t1",
      "chapter_id": "ch07b",
      "topic": "Decision Trees",
      "difficulty": "G2",
      "n": 5
    }
  ],
  "retrieval_mode": "auto",
  "output_name": "latency_test_5q"
}
```

Kiểm tra số RAG calls:

```bash
grep -c "RAG:" logs/celery.log
```

Kỳ vọng:

```text
Khoảng 1 RAG call cho 5 câu cùng topic
```

---

## 9.4. Test 25 câu

Chạy cùng payload thực tế bạn dùng trong UI.

Cần ghi lại:

| Metric | Trước fix | Sau fix |
|---|---:|---:|
| Tổng thời gian job |  |  |
| Số câu accepted |  |  |
| Số LLM calls |  |  |
| Số RAG calls |  |  |
| Avg seconds/question |  |  |
| vLLM pending queue |  |  |
| Tracing exceptions |  |  |

Command gợi ý:

```bash
grep -c "POST /v1/chat/completions" logs/vllm.log
grep -c "RAG:" logs/celery.log
grep -c "Exception while exporting Span" logs/celery.log
grep "Task .* succeeded in" logs/celery.log | tail -5
```

---

# 10. Definition of Done

Xem như fix đạt yêu cầu nếu:

- `Exception while exporting Span = 0` khi `ENABLE_TRACING=0` hoặc Phoenix healthy.
- 5 câu cùng topic chỉ retrieve context 1 lần.
- Production không gọi `eval overall`.
- vLLM không pending queue quá nhiều khi generate 5-10 câu.
- 1 câu không còn mất 2-3 phút trong trạng thái warm.
- 25 câu giảm đáng kể so với baseline 30-60 phút.

Target thực tế ban đầu:

| Scenario | Target sau fix bước 1-7 |
|---|---:|
| 1 câu warm | dưới 30-60s nếu vẫn giữ nhiều prompt calls |
| 5 câu cùng topic | dưới 3-8 phút tùy GPU/model |
| 25 câu | giảm rõ rệt, kỳ vọng thấp hơn 1 giờ đáng kể |

Lưu ý: nếu vẫn giữ pipeline nhiều bước P1/P4/P5/P6/P7/P8, rất khó quay lại mức `0.5-0.75s/câu`. Muốn đạt latency gần realtime cần thêm bước tối ưu lớn hơn: generate nhiều câu/topic trong 1 LLM call hoặc fast mode 1-call/câu.

---

# 11. Khuyến nghị cuối cùng

Thứ tự triển khai nên là:

1. Fix Phoenix tracing và thêm `ENABLE_TRACING`.
2. Thêm timing log.
3. Preload RAG khi Celery worker start.
4. Cache/precompute RAG theo `(topic, chapter_id)`.
5. Thêm UI option `Chế độ truy xuất tài liệu`: `Nhanh / Cân bằng / Chất lượng cao`.
6. Tắt `eval overall` trong production bằng `ENABLE_LLM_EVAL=0`.
7. Tune vLLM: `--max-model-len 4096`, `--max-num-seqs 8`.
8. Sau khi có số liệu mới, mới quyết định giảm prompt/context hoặc thêm fast mode.

