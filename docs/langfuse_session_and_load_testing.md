# Theo dõi Session và So sánh Tải bằng Langfuse

Tài liệu này hướng dẫn cách đọc trace/session của MCQGen trên Langfuse và cách so sánh khi 1 user sử dụng hệ thống với khi nhiều user cùng generate đề.

## 1. Chuẩn bị hệ thống

Trong `.env`, cần có:

```bash
ENABLE_LANGFUSE=1
LANGFUSE_BASE_URL=http://localhost:8083
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_TRACING_ENABLED=true
MCQGEN_LLM_STREAM_METRICS=1
APP_ENV=prod
TRACE_RUN_TYPE=manual
LOAD_TEST_ID=
MCQGEN_DYNAMIC_CONCURRENCY=1
```

Khởi động hệ thống:

```bash
bash scripts/start_system.sh --with-langfuse --no-vllm
```

Nếu cần tự bật local vLLM:

```bash
bash scripts/start_system.sh --with-langfuse --with-vllm
```

Mở Langfuse:

```text
http://192.168.20.154:8083
```

Các trace mới sau khi restart sẽ có đủ `session_id`, `user_id`, `use_case`, TTFT và tokens/sec. Trace cũ trước thời điểm này có thể thiếu các trường này.

## 2. Cách hệ thống đang gắn trace

Mỗi lần bấm generate đề, hệ thống tạo:

- `trace_name`: `mcqgen.generate_exam`
- `use_case`: `generate_exam`
- `session_id`: `<user_id>:exam:<task_id>`
- `user_id`: username của user đang đăng nhập
- `tags`: `app:mcqgen`, `env:<env>`, `usecase:generate_exam`, `traffic:<single-user|multi-user>`, `ccu:<bucket>`, `run:<manual|loadtest>`

Tag và metadata concurrency được tính bằng Redis tại thời điểm request bắt đầu, không suy luận từ latency:

- `traffic:single-user` hoặc `traffic:multi-user`
- `ccu:1`, `ccu:2-5`, `ccu:6-10`, `ccu:11-20`, `ccu:21-50`, `ccu:50+`
- `concurrent_users_at_start`: số user khác nhau đang có generation job chưa kết thúc, tính cả request hiện tại.
- `concurrent_traces_at_start`: số generation traces/jobs active, tính cả request hiện tại.
- `active_sessions_at_start`: số session active, tính cả request hiện tại.
- `traffic_mode`: `single-user` hoặc `multi-user`.
- `concurrency_bucket`: bucket CCU chính xác hơn cho dashboard.
- `target_concurrency`: mục tiêu cấu hình, ví dụ 3.
- `server_instance`, `request_source`, `load_test_id`.

Các observation chính trong một session:

- `api.generate.submit`: API nhận request từ UI, queue depth, estimated runtime.
- `celery.run_mcq_pipeline`: Celery worker chạy job generate.
- `pipeline.run_pipeline_with_topics`: toàn bộ pipeline generate đề.
- `rag.retrieve` hoặc `rag.cache_hit`: retrieval context theo topic/chapter.
- `llm.P1_gen_stem_key`: sinh stem và đáp án đúng.
- `llm.P4_option_candidates`: sinh distractor candidates.
- `llm.P5_cot_evaluate`: đánh giá distractors.
- `llm.P6_remove_bad`: loại distractors kém.
- `llm.P7_select_final`: chọn distractors cuối.
- `llm.P8_assemble`: lắp câu hỏi hoàn chỉnh.
- `llm.P9_explanation`: sinh giải thích, nếu bật.
- `llm.final_eval`: đánh giá cuối, nếu bật.
- `guardrail.opening_check`: kiểm tra opening style.
- `mcqgen.question.accepted`: câu hỏi được accept.
- `mcqgen.question.rejected`: câu hỏi bị reject, level `WARNING`.

LLM generation observations có thêm:

- `model`: model vLLM đang dùng, ví dụ `mcqgen`.
- `metadata.prompt_name`: tên stage, ví dụ `llm.P1_gen_stem_key`.
- `completion_start_time`: dùng để Langfuse tính Time To First Token.
- `usage_details.input`, `usage_details.output`, `usage_details.total`: token usage.
- score `time_to_first_token_seconds`.
- score `output_tokens_per_second`.

Nếu một LLM call có `streaming_fallback=true`, nghĩa là vLLM không stream được ở call đó. Khi đó latency vẫn có, token usage vẫn có nếu backend trả usage, nhưng TTFT có thể không có.

## 3. Theo dõi toàn bộ pipeline của một session

1. Vào MCQGen UI và generate một đề.
2. Lấy `task_id` từ UI, lịch sử đề thi hoặc API response.
3. Vào Langfuse -> `Tracing` -> `Sessions`.
4. Tìm session:

```text
exam:<task_id>
```

5. Mở session, đọc theo thứ tự:

- Xem trace `mcqgen.generate_exam`.
- Mở observation `api.generate.submit` để biết user nào submit, queue bao nhiêu job.
- Mở `celery.run_mcq_pipeline` để xem accepted/failed/acceptance_rate.
- Mở `pipeline.run_pipeline_with_topics` để xem tổng số câu, số topic, failure stage counts.
- Mở từng `mcqgen.question.rejected` để xem `reject_stage`, `reject_reason`, `raw_preview`, `parsed_preview`.
- Mở từng `llm.*` stage để xem prompt input, output, latency, TTFT, token usage.

Khi cần tìm vì sao 35 câu chỉ accept 20 câu:

- Mở trace score `failed_questions`.
- Xem các score `reject_stage.<stage>`.
- Lọc observation level `WARNING`.
- Mở `mcqgen.question.rejected`.
- So sánh stage bị reject nhiều nhất với output của LLM stage ngay trước đó.

Ví dụ:

- Reject ở `P1_gen_stem_key`: thường do LLM output sai JSON hoặc thiếu field stem/key.
- Reject ở `P4_option_candidates`: thường do thiếu distractors hoặc sai JSON.
- Reject ở `P8_assemble`: thường do assemble sai format câu hỏi.
- Reject ở `opening_check`: câu hỏi vẫn vi phạm opening style sau repair.
- Reject ở `final_eval`: evaluator đánh giá câu không hợp lệ.

## 4. Dashboard cần tạo để so sánh 1 user và nhiều user

Trong Langfuse Dashboard/Metrics, nên filter chung:

- Tags contains `app:mcqgen`
- Tags contains `usecase:generate_exam`
- So sánh bằng `traffic:single-user` và `traffic:multi-user`
- Trace name = `mcqgen.generate_exam`
- Use case = `generate_exam`
- Chọn đúng time window của bài test
- Loại bỏ warmup run nếu có

### P95 Latency by Use Case

- View: `Traces`
- Metric: `Latency`, aggregation `p95`
- Group by: `traceName` hoặc metadata `use_case`
- Filter: `traceName = mcqgen.generate_exam`

Mục đích: xem độ trễ end-to-end của generate đề.

### P95 Latency by Level

- View: `Observations`
- Metric: `Latency`, aggregation `p95`
- Group by: `level`

Mục đích: so sánh latency giữa observation bình thường, `WARNING` và `ERROR`.

### Max Latency by User Id

- View: `Traces`
- Metric: `Latency`, aggregation `max`
- Group by: `userId`

Mục đích: user nào gặp job chậm nhất trong cùng một test window.

Lưu ý: nếu dùng Metrics API v2 trên Langfuse Cloud, `userId` có thể chỉ dùng để filter, không group vì high cardinality. Với self-host/UI, hãy ưu tiên dùng dashboard UI; nếu không group được, tạo từng filter user riêng và so sánh.

### Avg Time To First Token by Prompt Name

- View: `Observations`
- Filter: type/generation hoặc name starts with `llm.`
- Metric: `Time To First Token`, aggregation `avg`
- Group by: observation `name`

Trong dự án hiện tại, prompt stage được đặt ở observation name và `metadata.prompt_name`, ví dụ `llm.P1_gen_stem_key`. Nếu sau này tích hợp Langfuse Prompt Management, có thể group bằng native Prompt Name.

### P95 Time To First Token by Model

- View: `Observations`
- Filter: type/generation hoặc name starts with `llm.`
- Metric: `Time To First Token`, aggregation `p95`
- Group by: `model` hoặc `providedModelName`

Mục đích: xem model bắt đầu trả token chậm thế nào khi tải tăng.

### P95 Latency by Model

- View: `Observations`
- Filter: type/generation hoặc name starts with `llm.`
- Metric: `Latency`, aggregation `p95`
- Group by: `model` hoặc `providedModelName`

Mục đích: xem tổng thời gian LLM call theo model.

### Avg Output Tokens Per Second by Model

- View: `Scores` hoặc `scores-numeric`
- Score name: `output_tokens_per_second`
- Metric: score value, aggregation `avg`
- Group by: score metadata `model`

Mục đích: đo throughput sinh token của model. Chỉ tính trên LLM call có usage output token.

## 5. Thiết kế bài test 1 user vs 3 user

Để so sánh công bằng, giữ nguyên:

- Số câu hỏi.
- Chapter/topic/difficulty.
- Retrieval mode.
- vLLM model.
- `MCQGEN_MAX_CONCURRENT_QUESTIONS`.
- `MCQGEN_LLM_MAX_CONCURRENCY`.
- Không thay đổi code giữa hai bài test.

Nên làm một warmup run nhỏ trước, sau đó không tính warmup vào dashboard.

### Cấu hình concurrency hiện tại

Ở profile tĩnh, hệ thống dùng công thức:

```text
CELERY_GENERATION_CONCURRENCY * MCQGEN_MAX_CONCURRENT_QUESTIONS <= VLLM_MAX_NUM_SEQS
```

Ở profile dynamic, công thức được áp dụng tại từng job:

```text
effective_questions_per_job = floor(VLLM_MAX_NUM_SEQS / active_generation_jobs)
```

Các biến chính:

- `MCQGEN_RESOURCE_MAX_RUNNING_JOBS`: số generation job tối đa được chạy song song theo tài nguyên vLLM.
- `MCQGEN_TARGET_CONCURRENT_USERS`: nhãn mục tiêu cho tracing/load-test; không còn là hard limit.
- `CELERY_GENERATION_CONCURRENCY`: số generation job chạy đồng thời ở worker-high.
- `MCQGEN_MAX_CONCURRENT_QUESTIONS`: số câu hỏi sinh song song trong một job.
- `MCQGEN_LLM_MAX_CONCURRENCY`: số LLM request tối đa trong một job.
- `VLLM_MAX_NUM_SEQS`: số request vLLM có thể xử lý đồng thời.
- `MCQGEN_CONCURRENCY_AUTOTUNE=1`: tự tính `MCQGEN_MAX_CONCURRENT_QUESTIONS` và `MCQGEN_LLM_MAX_CONCURRENCY` theo `VLLM_MAX_NUM_SEQS / CELERY_GENERATION_CONCURRENCY`.
- `MCQGEN_DYNAMIC_CONCURRENCY=1`: mỗi job tự nhận số slot theo số generation jobs active tại runtime.
- `MCQGEN_GLOBAL_SLOT_GUARD=1`: dùng Redis để giới hạn tổng số câu hỏi đang dùng LLM trên mọi worker, tránh vượt `VLLM_MAX_NUM_SEQS`.
- `CELERY_QUEUE_ISOLATE_BY_USER=1`: tự tách queue theo user, ví dụ `mcq.thanhld.high`, để worker của thành viên khác không nhận job của mình.

Profile mặc định hiện tại cho nhiều user:

```bash
MCQGEN_RESOURCE_MAX_RUNNING_JOBS=4
MCQGEN_TARGET_CONCURRENT_USERS=4
CELERY_GENERATION_CONCURRENCY=4
MCQGEN_CONCURRENCY_AUTOTUNE=1
MCQGEN_DYNAMIC_CONCURRENCY=1
MCQGEN_GLOBAL_SLOT_GUARD=1
MCQGEN_GLOBAL_LLM_SLOTS=4
CELERY_QUEUE_ISOLATE_BY_USER=1
VLLM_MAX_NUM_SEQS=4
```

Với dynamic concurrency, script cho phép tối đa số generation jobs bằng capacity tài nguyên, nhưng pipeline tự chia slot theo tải:

```text
1 active job  -> 4 questions/job -> 1 user sinh nhanh hơn
2 active jobs -> 2 questions/job mỗi job
3 active jobs -> 1 question/job mỗi job
4 active jobs -> 1 question/job mỗi job
5+ jobs      -> các job vượt capacity vào hàng đợi
```

Giới hạn vẫn được giữ:

```text
effective_questions_per_job = floor(VLLM_MAX_NUM_SEQS / active_generation_jobs)
```

Nếu muốn 1 job nhanh nhất:

```bash
MCQGEN_TARGET_CONCURRENT_USERS=1 \
MCQGEN_RESOURCE_MAX_RUNNING_JOBS=1 \
CELERY_GENERATION_CONCURRENCY=1 \
MCQGEN_CONCURRENCY_AUTOTUNE=1 \
MCQGEN_DYNAMIC_CONCURRENCY=1 \
bash scripts/start_system.sh --with-langfuse --no-vllm
```

Kết quả với `VLLM_MAX_NUM_SEQS=4`:

```text
1 job * 4 questions/job = 4 LLM slots
```

Nếu muốn 2 user cân bằng:

```bash
MCQGEN_TARGET_CONCURRENT_USERS=2 \
MCQGEN_RESOURCE_MAX_RUNNING_JOBS=2 \
CELERY_GENERATION_CONCURRENCY=2 \
MCQGEN_CONCURRENCY_AUTOTUNE=1 \
MCQGEN_DYNAMIC_CONCURRENCY=1 \
bash scripts/start_system.sh --with-langfuse --no-vllm
```

Kết quả:

```text
2 jobs * 2 questions/job = 4 LLM slots
```

Nếu muốn tự custom:

```bash
MCQGEN_CONCURRENCY_AUTOTUNE=0 \
MCQGEN_DYNAMIC_CONCURRENCY=0 \
CELERY_GENERATION_CONCURRENCY=2 \
MCQGEN_MAX_CONCURRENT_QUESTIONS=2 \
MCQGEN_LLM_MAX_CONCURRENCY=2 \
bash scripts/start_system.sh --with-langfuse --no-vllm
```

Sau khi start, kiểm tra dòng `Concurrency` trong terminal hoặc gọi:

```text
http://192.168.20.154:8080/health
http://192.168.20.154:8080/queue/status
```

Trong output `start_system.sh`, kiểm tra queue đang có namespace riêng:

```text
queues=mcq.<user>.high,mcq.<user>.low | worker_namespace=<user>
```

Nếu thấy queue chung `mcq.high`, các worker của thành viên khác có thể cạnh tranh job và làm sai kết quả so sánh load.

### Test A: 1 user

1. Login bằng một user, ví dụ `user_a`.
2. Generate cùng một cấu hình đề.
3. Đặt tên đề dễ lọc, ví dụ:

```text
loadtest_1user_20260602_01
```

4. Ghi lại thời gian bắt đầu/kết thúc.
5. Trong Langfuse, filter theo time window và `userId = user_a`.

Trace metadata sẽ có:

- tag `traffic:single-user`
- tag `ccu:1`
- `traffic_mode = single-user`
- `concurrent_users_at_start = 1`
- `concurrent_traces_at_start = 1`, nếu không có job khác đang active
- `queue_depth_at_submit = 0`

### Test B: 3 user đồng thời

1. Chuẩn bị 3 tài khoản, ví dụ `user_a`, `user_b`, `user_c`.
2. Mỗi user mở một browser/session riêng.
3. Chọn cùng một cấu hình đề.
4. Đặt tên đề khác nhau để tránh trùng:

```text
loadtest_3user_a_20260602_01
loadtest_3user_b_20260602_01
loadtest_3user_c_20260602_01
```

5. Bấm generate gần như cùng lúc.
6. Trong Langfuse, filter theo time window của test này.

Trace metadata sẽ có:

- tag `traffic:multi-user`, nếu tại thời điểm request có từ 2 user active trở lên.
- tag `ccu:2-5` cho bài test 3 user.
- `traffic_mode = multi-user`
- `concurrent_users_at_start`: số user khác nhau đang có generation job active.
- `concurrent_traces_at_start`: số generation jobs active.
- `active_jobs_at_submit`
- `queued_jobs_at_submit`
- `queue_depth_at_submit`

Nếu một trace vẫn hiện `traffic:single-user`, nghĩa là tại thời điểm request đó bắt đầu, Redis chỉ thấy 1 user active. Khi test đồng thời, nên bấm 3 request sát nhau hơn hoặc tăng số câu để job đầu chưa kết thúc quá nhanh.

## 6. Cách đọc kết quả so sánh

Ưu tiên so sánh theo thứ tự:

1. Trace latency end-to-end:
   - `P95 Latency by Use Case`
   - `Max Latency by User Id`

2. Pipeline bottleneck:
   - Mở trace chậm nhất.
   - Xem observation nào chiếm thời gian nhiều nhất: RAG, LLM stage, guardrail hay queue.

3. LLM bottleneck:
   - `P95 Time To First Token by Model`
   - `P95 Latency by Model`
   - `Avg Output Tokens Per Second by Model`

4. Quality/reject:
   - `acceptance_rate`
   - `failed_questions`
   - `reject_stage.<stage>`
   - observation `mcqgen.question.rejected`

Nếu test 3 user chậm hơn 1 user:

- TTFT tăng: model bị chờ batch/queue trước khi token đầu tiên.
- Latency tăng nhưng TTFT không tăng nhiều: generation dài hơn hoặc token throughput giảm.
- Output tokens/sec giảm: GPU/model serving bị nghẽn.
- Queue depth tăng: nghẽn ở Celery/job scheduling, không hẳn ở model.
- Reject tăng: cần xem output raw của các stage bị reject, có thể do model trả format kém khi tải cao hoặc prompt quá dài.

## 7. Có trace GPU % trên Langfuse được không?

Có thể, nhưng không nên dùng Langfuse làm hệ thống monitoring GPU chính.

Langfuse phù hợp để trace LLM application:

- input/output prompt
- latency
- TTFT
- token usage
- cost
- user/session/use case
- scores và reject reason

GPU utilization là hạ tầng runtime. Sau khi bỏ stack dashboard metrics, cách phù hợp trong repo này là ghi snapshot tần suất thấp vào Langfuse cho từng job cần phân tích, hoặc kiểm tra thủ công bằng `nvidia-smi` khi chạy load test.

Nếu vẫn muốn đưa GPU vào Langfuse, nên trace dạng snapshot tần suất thấp:

- Tạo observation `infra.gpu.snapshot`.
- Gắn metadata:
  - `gpu_index`
  - `gpu_util_percent`
  - `gpu_memory_used_mb`
  - `gpu_memory_total_mb`
  - `task_id`
  - `session_id`
- Gắn numeric score:
  - `gpu_util_percent`
  - `gpu_memory_percent`

Không nên gửi GPU sample mỗi giây cho mọi GPU vào Langfuse vì sẽ làm trace rất nhiễu và tăng lượng dữ liệu lớn. Nếu cần giải thích một job cụ thể chậm vì GPU nghẽn, gửi vài snapshot vào Langfuse là hợp lý.

## 8. Link docs Langfuse liên quan

- Sessions: https://langfuse.com/docs/observability/features/sessions
- Users: https://langfuse.com/docs/observability/features/users
- Tags: https://langfuse.com/docs/observability/features/tags
- Metadata: https://langfuse.com/docs/observability/features/metadata
- Core data model: https://langfuse.com/docs/observability/data-model
- Metrics overview: https://langfuse.com/docs/metrics/overview
- Metrics API: https://langfuse.com/docs/metrics/features/metrics-api
- Time To First Token: https://langfuse.com/docs/observability/sdk/advanced-features#time-to-first-token-ttft
