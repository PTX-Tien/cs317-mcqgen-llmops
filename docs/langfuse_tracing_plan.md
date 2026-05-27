# LangFuse tracing plan cho MCQGen

## Mục tiêu

- Theo dõi được một lượt sinh đề từ API submit job -> Celery worker -> RAG -> từng bước LLM P1/P4/P5/P6/P7/P8.
- Gắn trace với `user_id`, `task_id`, `exam_name`, `topic`, `chapter_id`, `difficulty`.
- Dùng LangFuse để giải thích LLM hoạt động như thế nào qua prompt, response, latency, token usage nếu vLLM trả về usage.
- Dùng Prometheus/Grafana song song để chứng minh tải hệ thống: queue, latency API, vLLM throughput, GPU/system metrics.

## Kiến trúc đề xuất

```text
Next.js UI
  -> FastAPI /generate
      -> LangFuse span: api.generate.submit
      -> Celery task_id cố định
          -> LangFuse span: celery.run_mcq_pipeline
          -> LangFuse span: rag.precompute
          -> LangFuse span: mcqgen.question
              -> LangFuse generation: llm.P1_gen_stem
              -> LangFuse generation: llm.P4_distractors
              -> LangFuse generation: llm.P5_evaluate_distractors
              -> LangFuse generation: llm.P6_remove_bad
              -> LangFuse generation: llm.P7_select_final
              -> LangFuse generation: llm.P8_assemble
              -> optional: llm.opening_repair / llm.eval_overall
```

## Cách bật LangFuse

1. Chạy LangFuse self-host từ `monitoring/langfuse/docker-compose.yml`.
2. Mở `http://localhost:3000`, tạo project và lấy public/secret key.
3. Bật các biến môi trường backend:

```env
ENABLE_LANGFUSE=1
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_MAX_IO_CHARS=12000
```

Nếu `ENABLE_LANGFUSE=0` hoặc thiếu key, toàn bộ helper tự no-op và hệ thống vẫn chạy như cũ.

## Dữ liệu cần xem trong báo cáo

- Trace theo `session_id = task_id`: chứng minh một lượt sinh đề gồm bao nhiêu bước.
- Span `rag.precompute`: strategy RAG, best score, context length.
- Generation spans `llm.*`: prompt, output, latency, model parameters, token usage.
- Score `accepted_questions` và `failed_questions`: chất lượng/độ ổn định job.
- Metadata `user_id`: truy vết user nào submit job nào.

## Đo tối đa bao nhiêu user

LangFuse trả lời phần “LLM đã làm gì”. Để trả lời “tối đa bao nhiêu user”, cần load test riêng:

- Kịch bản: login teacher -> submit `/generate` -> poll `/status/{task_id}` hoặc websocket -> lấy `/results/{task_id}`.
- Sweep: 1, 2, 5, 10, 20 user đồng thời.
- Metric cần ghi: success rate, queue wait, job duration p50/p95, API p95 latency, vLLM tokens/s, GPU memory, error/OOM.
- Với cấu hình hiện tại `celery --concurrency=1` và `VLLM_MAX_NUM_SEQS=4`, hệ thống xử lý 1 job active, còn user khác vào queue. Vì vậy “max user” cần định nghĩa theo SLA, ví dụ p95 job hoàn tất dưới N phút và success rate >= 95%.

