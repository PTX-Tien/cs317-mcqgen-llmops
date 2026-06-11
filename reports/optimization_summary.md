# Báo cáo Tối ưu hóa (Optimization Summary) — MCQGen

Ngày cập nhật: 2026-06-11

## 1. Quan điểm tối ưu hóa của hệ thống

MCQGen **không train và không fine-tune** mô hình ngôn ngữ. Hệ thống dùng mô hình
**Qwen2.5-7B-Instruct** được phục vụ cục bộ qua **vLLM** (OpenAI-compatible API,
served-name `mcqgen`). Vì vậy phần "model optimization" trong bài thực hành được hiểu
theo đúng bối cảnh **LLMOps**, gồm bốn nhóm tối ưu **thật sự có trong repo**:

1. **Retrieval optimization** — Adaptive RAG (naive → HyDE → cross-encoder rerank).
2. **Prompt optimization** — prompt versioning v1 → v2, few-shot style bank, guardrail opening.
3. **Serving/runtime optimization** — vLLM (PagedAttention, prefix caching, batching), pipeline bất đồng bộ, dynamic concurrency, global slot guard.
4. **System optimization** — cache kết quả (Redis), dedup câu hỏi theo lịch sử.

> Lưu ý trung thực: các con số đo phụ thuộc GPU, version vLLM, workload. Các mục đã đo thật:
> 3.1 (RAG), 3.3 (vLLM serving), 3.4 (async vs sequential), 3.5 (prefix cache).
> Mục 3.2 (prompt v1 vs v2) còn `📌` vì chưa generate đề để lấy số.
> Không claim fine-tune / quantize / cloud deploy nếu nhóm chưa làm.

## 2. Bảng tổng hợp tối ưu hóa

| Optimization                            | Bằng chứng trong repo                                                                                              | Metric nên đo                                                         | Lệnh / cách đo                                                                                 |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Adaptive RAG vs naive retrieval         | `src/mcqgen/advanced_retrieval.py`, `data/benchmarks/rag_benchmark.log`                                            | top-k similarity (before/after rerank), retrieval time, strategy chọn | `python -m src.mcqgen.advanced_retrieval adaptive`                                             |
| Prompt versioning / style bank          | `prompts/v1/metadata.json`, `prompts/v2/style_bank.json`, `bad_openings.json`, `opening_families.json`             | acceptance rate, reject_stage `opening_check`                         | so sánh acceptance rate giữa prompt v1 và v2 (xem 3.2)                                         |
| Async pipeline vs sequential            | `src/mcqgen/pipeline_mcq.py`, `vllm/exp03_pipeline_sequential_vs_async.py`                                         | tổng thời gian/đề, throughput (MCQ/phút), speedup                     | `python vllm/exp03_pipeline_sequential_vs_async.py --modes sequential,async --concurrency 4`   |
| vLLM serving (batching + concurrency)   | `scripts/start_system.sh` (vllm serve), `vllm/exp02_llm_concurrency_sweep.py`, `vllm/exp06_official_vllm_bench.py` | throughput (req/s, tokens/s), latency P50/P95, TTFT                   | `python vllm/exp02_llm_concurrency_sweep.py --concurrency-list 1,2,4,8`                        |
| vLLM `--max-num-seqs` ablation          | `vllm/exp04_max_num_seqs_ablation.py`                                                                              | throughput/latency theo từng `max_num_seqs`                           | `python vllm/exp04_max_num_seqs_ablation.py --auto-restart --server-max-num-seqs-list 1,2,4,8` |
| vLLM prefix caching                     | bật sẵn trong `start_system.sh` (`--enable-prefix-caching`), `vllm/exp05_prefix_cache_ablation.py`                 | prefix hit rate, prompt tokens/s                                      | `python vllm/exp05_prefix_cache_ablation.py --prefix-cache-mode on`                            |
| Baseline "no batching"                  | `vllm/exp07_no_vllm_baselines.py`                                                                                  | so sánh concurrency=1 vs concurrency>1 trên cùng vLLM                 | `python vllm/exp07_no_vllm_baselines.py`                                                       |
| Dynamic concurrency + global slot guard | `src/mcqgen/pipeline_mcq.py`, `api/core/load_tracking.py`, env trong `start_system.sh`                             | latency single-user vs multi-user, slot vLLM bão hòa                  | đọc Langfuse tag `traffic:*`, `ccu:*` (3.6)                                                    |
| Cache kết quả (Redis)                   | `api/core/cache.py` (`get/set_cached_task_id`, TTL 7 ngày)                                                         | cache hit, thời gian phản hồi request trùng                           | gọi `/generate` 2 lần cùng payload, xem log `cache_hit_generation`                             |
| Dedup câu hỏi theo lịch sử              | `pipeline_mcq.py` stage `dedup_history`, `MCQGEN_DEDUP_*`                                                          | duplicate rate trong đề                                               | xem `reports/eval_results.md` (mục 5.7)                                                        |

## 3. Chi tiết các tối ưu

### 3.1. Adaptive RAG — đã đo

`advanced_retrieval.py` triển khai pipeline truy hồi nhiều bước thay cho naive retrieval:

- **Naive check**: embed topic bằng `BAAI/bge-m3`, query ChromaDB, lấy best similarity.
- **Adaptive strategy**: nếu naive đủ tốt → `naive+rerank`; nếu naive yếu → kích hoạt **HyDE**
  (LLM sinh câu hỏi giả định, ensemble embedding `0.6*topic + 0.4*hypo`) → `hyde+rerank`.
- **Cross-encoder rerank**: `cross-encoder/ms-marco-MiniLM-L-6-v2` xếp lại top-k.
- **Sentence-window**: có hỗ trợ trong code (collection `concept_chunks_sw`) nhưng **hiện chưa
  build collection này**, nên benchmark chạy ở chế độ fallback "standard"
  (log: `SW collection not found — fallback to standard`).

Kết quả `benchmark_adaptive()` (`python -m src.mcqgen.advanced_retrieval adaptive`,
log: `data/benchmarks/rag_benchmark.log`):

| Topic                      | Strategy     | Naive best | Adaptive best |      Δ | Time (s) |
| -------------------------- | ------------ | ---------: | ------------: | -----: | -------: |
| Missing Data (ch04)        | hyde+rerank  |      0.136 |         0.224 | +0.088 |      1.8 |
| Decision Trees (ch07b)     | naive+rerank |      0.366 |         0.366 | +0.000 |      0.3 |
| CNN Neural Networks (ch08) | hyde+rerank  |      0.094 |         0.141 | +0.047 |      1.4 |
| Outlier Detection (ch04)   | naive+rerank |      0.296 |         0.296 | +0.000 |      0.3 |

Nhận xét:

- **Adaptive không bao giờ kém naive** (Δ ≥ 0 ở cả 4 topic), trung bình Δ ≈ +0.034.
- Khi naive yếu (Missing Data 0.136, CNN 0.094), hệ thống **tự kích hoạt HyDE** và cải thiện rõ
  (+0.088 và +0.047). Khi naive đã tốt (Decision Trees 0.366, Outlier 0.296), hệ thống **chọn
  `naive+rerank`**, không tốn thêm 1 lượt gọi LLM cho HyDE → tiết kiệm thời gian (0.3 s so với
  1.4–1.8 s khi có HyDE). Đây đúng là hành vi "adaptive": tốn chi phí HyDE chỉ khi cần.
- Giá trị similarity tuyệt đối ở mức vừa phải (đặc trưng của embedding/đữ liệu môn học), nhưng
  điểm cần chứng minh là **cải thiện tương đối** và **chiến lược chọn tự động**, cả hai đều đạt.

### 3.2. Prompt optimization (v1 → v2)

- `prompts/v1/metadata.json`: prompt P1–P8 gốc, model `Qwen2.5-7B-Instruct`.
- `prompts/v2/style_bank.json`: few-shot lấy từ **đề thi CS116 thật** để model học style diễn đạt.
- `prompts/v2/bad_openings.json` + `opening_families.json`: guardrail loại các mở đầu xấu;
  pipeline có stage `opening_check` (repair → reject nếu sửa không đạt).
- `prompts/v2/misconception_types.json`: định hướng sinh distractor theo lỗi sai thường gặp.

Hiệu quả đo bằng **acceptance rate** và phân bố **reject_stage** (đặc biệt `opening_check`,
`final_eval`) — so sánh giữa hai prompt version, lấy số từ `reports/eval_results.md`.

📌 [điền số sau khi generate đề + chạy `python scripts/eval_report.py --latest`]:

| Prompt version | Acceptance rate | reject `opening_check` | reject `final_eval` |
| -------------- | --------------- | ---------------------- | ------------------- |
| v1.0           | …               | …                      | …                   |
| v2.0-phase2    | …               | …                      | …                   |

### 3.3. Serving & runtime optimization (vLLM) — đã đo

Cấu hình vLLM thực tế khi chạy (đọc từ log khởi động vLLM):

```text
model              : models/Qwen2.5-7B-Instruct  (served-name: mcqgen)
dtype              : half (bfloat16 -> float16)
tensor-parallel    : 2
max-model-len      : 5000
max-num-seqs       : 4
gpu-memory-util    : 0.9   (KV cache ~2 GiB, max concurrency cho 5000 tokens ≈ 15x)
prefix caching     : bật (--enable-prefix-caching)
mode               : --enforce-eager
attention backend  : XFormers (GPU Volta/Turing, Compute Capability < 8.0 → không dùng FlashAttention-2)
endpoint           : http://localhost:7681/v1
```

**Kết quả đo (exp02).** Workload: 100 request/mức, `max_tokens=512`, model `mcqgen` (TP=2),
endpoint `http://localhost:7681/v1`. Artifact: `vllm/results/exp02_llm_concurrency_sweep/`
(run `sweep_20260611_141807`).

| Concurrency | Throughput (req/s) | Completion tokens/s | Total tokens/s | Latency P50 (s) | Latency P95 (s) | Latency P99 (s) | Wall time (s) |
| ----------: | -----------------: | ------------------: | -------------: | --------------: | --------------: | --------------: | ------------: |
|           1 |               0.17 |                36.7 |           79.1 |            5.65 |            7.48 |            8.01 |         579.6 |
|           2 |               0.34 |                71.1 |          154.5 |            5.72 |            7.72 |            8.14 |         294.2 |
|           4 |               0.66 |               133.9 |          297.1 |            5.72 |            8.13 |            9.04 |         150.4 |
|           8 |               0.71 |               150.3 |          323.7 |           11.17 |           13.52 |           15.75 |         141.5 |

(TTFT không đo trong lần chạy này vì không bật `--stream`.)

Nhận xét:

- **Batching hiệu quả từ 1 → 4**: throughput tăng ~3.85× (0.17 → 0.66 req/s; 36.7 → 133.9
  completion tokens/s) trong khi **latency P50 gần như không đổi** (~5.7 s). Đúng lợi ích của
  continuous batching + PagedAttention: phục vụ nhiều request song song mà không tăng độ trễ.
- **Bão hòa tại 8**: từ 4 → 8 throughput chỉ tăng nhẹ (0.66 → 0.71 req/s) nhưng latency tăng
  mạnh (P50 5.7 → 11.2 s). Do server đặt `--max-num-seqs 4`, ở concurrency 8 có ~4 request xếp
  hàng (Pending) chờ tới lượt. Đây là điểm bão hòa hợp lý của cấu hình hiện tại.
- **Kết luận**: với GPU hiện có (Volta/Turing, XFormers), concurrency hiệu quả nhất ≈ 4, khớp
  đúng `max_num_seqs=4`. Muốn phục vụ nhiều người hơn nên tăng `--max-num-seqs` (xem exp04).

### 3.4. Async pipeline vs sequential — đã đo

`pipeline_mcq.py` sinh nhiều câu MCQ **bất đồng bộ** để vLLM batch/schedule các LLM call song song
thay vì xử lý tuần tự từng câu. Kết quả `exp03` (pipeline thật, RAG precompute, LLM eval tắt;
run `20260611_151246`, artifact `vllm/results/exp03_pipeline_sequential_vs_async/`):

| Mode       | MCQ | Accepted | Concurrency | RAG precompute (s) | Generation wall (s) | Total w/ RAG (s) | MCQs/min (gen) | MCQs/min (total) |
| ---------- | --: | -------: | ----------: | -----------------: | ------------------: | ---------------: | -------------: | ---------------: |
| sequential |   2 |        2 |           1 |               6.24 |              176.76 |            183.0 |           0.68 |             0.66 |
| async      |   2 |        2 |           4 |               6.24 |               84.91 |            91.14 |           1.41 |             1.32 |

- **Speedup (generation-only): 2.08×**; **speedup (total có RAG): 2.01×**.
- Đây là pipeline thật (có prompt P1–P8, parse JSON, RAG context, nhiều LLM call/câu), nên speedup
  thấp hơn benchmark LLM thuần (exp02) là hợp lý — phần thời gian còn lại nằm ở retrieval/rerank,
  phụ thuộc tuần tự giữa các stage và parse JSON.
- (Quy mô nhỏ: 2 topic × 1 câu để demo nhanh; có thể tăng `--topic-limit`/`--questions-per-topic`
  để có số ổn định hơn.)

### 3.5. vLLM prefix caching — đã đo (chưa kết luận)

vLLM được bật `--enable-prefix-caching`. Kết quả `exp05` (chế độ `on`, concurrency 4, 40 request,
max_tokens 256, prefix lặp 6 lần; artifact `vllm/results/exp05_prefix_cache_ablation/`):

| Prefix cache | Success | Wall time (s) | Requests/s | Prompt tokens/s | Output tokens/s | Avg latency (s) | P95 latency (s) | Prefix hit rate after |
| ------------ | ------: | ------------: | ---------: | --------------: | --------------: | --------------: | --------------: | --------------------: |
| on           |      40 |         63.69 |      0.628 |          1663.8 |           123.5 |            5.98 |            7.61 |                   0.0 |

Lưu ý (trung thực):

- Lần chạy này **chỉ đo chế độ `on`** và **không restart** server để bật/tắt cache, nên **chưa
  phải ablation on/off đúng nghĩa**. `Prefix hit rate after = 0.0` → workload này chưa thể hiện
  được lợi ích prefix caching (có thể prefix sau tokenize không trùng tuyệt đối, hoặc workload quá nhỏ).
- Muốn chứng minh đúng: khởi động server riêng cho từng cấu hình (có/không `--enable-prefix-caching`)
  rồi chạy script một lần mỗi cấu hình, so `prompt_tokens_per_s` và hit rate.
- Quan sát hỗ trợ: trong log vLLM lúc chạy exp02 (workload prompt lặp lại nhiều), `Prefix cache hit
rate (GPU)` tăng dần tới ~90% — cho thấy cơ chế prefix caching **có hoạt động** với workload phù hợp.

### 3.6. Dynamic concurrency & global slot guard

`start_system.sh` suy ra số job/câu song song theo `VLLM_MAX_NUM_SEQS`; `pipeline_mcq.py` dùng
semaphore cho số câu và số LLM request đồng thời; `api/core/load_tracking.py` (Redis) gắn tag
Langfuse: `traffic:single-user|multi-user`, `ccu:<bucket>`, `usecase:generate_exam`, `run:*`,
`loadtest:<id>`.

Đo: chạy 1 user vs nhiều user (đặt `LOAD_TEST_ID`), so sánh latency và mức bão hòa slot vLLM
trên Langfuse.

### 3.7. Cache & dedup

- **Cache** (`api/core/cache.py`): key theo `topics + retrieval_mode`, TTL `CACHE_TTL_GENERATION`
  (mặc định 7 ngày). Request trùng được trả `task_id` đã cache → tiết kiệm toàn bộ pipeline.
  Bằng chứng log: `cache_hit_generation`.
- **Dedup** (`pipeline_mcq.py`, stage `dedup_history`): so câu mới với lịch sử user, loại trùng
  với reason `duplicate_question`. Đo bằng duplicate rate trong `reports/eval_results.md`.

## 4. Cách tái lập số liệu (tóm tắt lệnh)

```bash
cd /mmlab_students/storageStudents/nguyenvd/thanhhn/cs317-mcqgen-llmops
export VLLM_URL=http://localhost:7681/v1
export VLLM_MODEL=mcqgen

# (a) RAG benchmark  (đã chạy)
python -m src.mcqgen.advanced_retrieval adaptive | tee data/benchmarks/rag_benchmark.log

# (b) vLLM serving / async / prefix cache  (đã chạy — kết quả trong vllm/results/)
python vllm/exp02_llm_concurrency_sweep.py --num-requests 100 --concurrency-list 1,2,4,8 --label sweep
python vllm/exp03_pipeline_sequential_vs_async.py --modes sequential,async --concurrency 4 --label pipeline
python vllm/exp05_prefix_cache_ablation.py --concurrency 4 --num-requests 40 --prefix-cache-mode on

# (c) acceptance rate / reject stage  (cần generate vài đề trước)
python scripts/eval_report.py --latest
```

## 5. Không nên claim

- ❌ Đã fine-tune / quantize Qwen2.5-7B-Instruct (chỉ download + serve qua vLLM).
- ❌ Đã optimize trọng số mô hình.
- ❌ Đã cloud deploy / cloud logging (hiện chạy local/server lab + self-host Langfuse).
- ❌ Sentence-window RAG đang chạy (code có hỗ trợ nhưng collection `concept_chunks_sw` chưa build).
- ❌ Prefix caching đã được chứng minh hiệu quả bằng ablation (mới đo 1 chế độ, hit rate 0.0).

Nên claim đúng: **Adaptive RAG (HyDE + rerank), prompt v1→v2 + guardrail, vLLM serving optimization
(batching/PagedAttention) với throughput tăng ~3.85× tới concurrency 4, async pipeline nhanh ~2.08×
so với sequential, dynamic concurrency, cache + dedup.**
