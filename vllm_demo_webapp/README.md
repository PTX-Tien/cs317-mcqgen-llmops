# MCQGen vLLM Demo Webapp

Webapp này dùng để demo trực quan 3 phần chính:

- Exp02: LLM-only concurrency sweep
- Exp03: Full pipeline sequential vs async + vLLM
- Exp07: Sequential/no-batching baseline vs concurrent vLLM

App dùng để trình bày kết quả dễ hiểu hơn: bấm chạy experiment, xem log realtime, xem SVG và Markdown report mới nhất.

## Run

Chạy trong môi trường dự án:

```bash
conda run -n mcqgen_v2 uvicorn vllm_demo_webapp.app:app \
  --host 0.0.0.0 \
  --port 8090
```

Mở:

```text
http://<server-ip>:8090
```

## Notes

- App gọi trực tiếp các script trong `vllm/`.
- App không tự stop/restart vLLM.
- Exp07 direct Transformers chỉ chạy nếu bật checkbox `Direct Transformers`; mặc định tắt vì dễ OOM khi vLLM đang chiếm GPU.
