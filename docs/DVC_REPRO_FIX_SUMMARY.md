# DVC Repro Fix Summary

Ngày: 2026-05-03

## Bối cảnh

Khi chạy full pipeline bằng `dvc repro`, stage `benchmark_rag` bị lỗi:

```bash
ERROR: failed to reproduce 'benchmark_rag': failed to run:
mkdir -p data/benchmarks && python advanced_retrieval.py adaptive > data/benchmarks/rag_benchmark.log 2>&1, exited with 1
```

## Nguyên nhân

Log tại `data/benchmarks/rag_benchmark.log` cho thấy lỗi thực tế là:

```text
openai.APIConnectionError: Connection error.
httpx.ConnectError: All connection attempts failed
```

`advanced_retrieval.py` đang dùng OpenAI-compatible client trỏ tới:

```text
http://localhost:8000/v1
```

với served model:

```text
mcqgen
```

Tại thời điểm lỗi, không có vLLM server nào chạy trên `localhost:8000`, nên stage `benchmark_rag` không thể gọi LLM để chạy HyDE/adaptive RAG benchmark.

## Những gì đã làm

Không chỉnh sửa source code.

Các bước xử lý runtime/config đã thực hiện:

1. Kiểm tra `data/benchmarks/rag_benchmark.log` để lấy traceback thật.
2. Xác nhận `advanced_retrieval.py` không có thay đổi code sau khi thao tác trước đó bị hủy.
3. Kiểm tra vLLM:

```bash
curl -sS --max-time 3 http://localhost:8000/health
```

Kết quả ban đầu: không kết nối được.

4. Kiểm tra model local:

```text
models/Qwen3-8B-AWQ
```

Model tồn tại và có đầy đủ các file safetensors/tokenizer/config cần thiết.

5. Kiểm tra GPU bằng `nvidia-smi`; GPU 7 là GPU rảnh nhất tại thời điểm chạy.

6. Khởi động vLLM trong conda env `mcqgen_v2`:

```bash
source /mmlab_students/storageStudents/nguyenvd/anaconda3/etc/profile.d/conda.sh
conda activate mcqgen_v2
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export CUDA_VISIBLE_DEVICES=7

vllm serve models/Qwen3-8B-AWQ \
  --dtype half \
  --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --enforce-eager \
  --enable-prefix-caching \
  --max-num-seqs 4 \
  --port 8000 \
  --host 0.0.0.0 \
  --served-model-name mcqgen
```

7. Xác nhận vLLM sẵn sàng:

```bash
curl -sS --max-time 5 http://localhost:8000/health
curl -sS --max-time 5 http://localhost:8000/v1/models
```

`/v1/models` trả về model `mcqgen`.

8. Chạy lại stage bị fail:

```bash
dvc repro benchmark_rag
```

## Kết quả

`dvc repro benchmark_rag` chạy thành công với exit code `0`.

DVC output:

```text
Stage 'transcript_chunking' didn't change, skipping
Stage 'indexing' is cached - skipping run, checking out outputs

Running stage 'benchmark_rag':
> mkdir -p data/benchmarks && python advanced_retrieval.py adaptive > data/benchmarks/rag_benchmark.log 2>&1
Updating lock file 'dvc.lock'
Use `dvc push` to send your updates to remote storage.
```

Benchmark log sau khi chạy thành công nằm tại:

```text
data/benchmarks/rag_benchmark.log
```

Log có kết quả cho các topic benchmark như:

- `Missing Data`
- `Decision Trees`
- `CNN Neural Networks`
- `Outlier Detection`

Sau khi xác minh xong, vLLM session đã được dừng để không giữ GPU.

## Trạng thái hiện tại

Git status sau khi chạy:

```text
M  dvc.lock
```

`dvc.lock` bị cập nhật bởi `dvc repro`; DVC autostage đang bật nên thay đổi này đang ở trạng thái staged.

`dvc status` vẫn báo:

```text
indexing:
        changed outs:
                modified:           data/indexes
```

Điều này có thể xảy ra vì ChromaDB index trong `data/indexes` bị thay đổi metadata/file state khi benchmark đọc hoặc checkout output. Đây không phải lỗi connection ban đầu, nhưng có thể khiến DVC khó về trạng thái clean tuyệt đối nếu chưa điều chỉnh cách quản lý ChromaDB output.

## Lưu ý khi chạy lại

Trước khi chạy full pipeline hoặc stage `benchmark_rag`, cần đảm bảo vLLM đang chạy tại:

```text
http://localhost:8000/v1
```

và có served model:

```text
mcqgen
```

Lệnh kiểm tra nhanh:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

