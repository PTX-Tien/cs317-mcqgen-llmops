# Kế hoạch chứng minh dự án CS317-MCQGen đang dùng vLLM và vLLM có hiệu quả

> File này dùng để chuẩn bị demo/báo cáo với giảng viên: **dự án đang thật sự dùng vLLM ở đâu**, **vLLM giải quyết vấn đề gì**, **cần đo metric nào**, và **làm thí nghiệm nào để thấy hiệu quả bằng mắt thường**.
>
> Lưu ý quan trọng: file này là **kế hoạch + checklist + template thí nghiệm**. Nó chưa chứa kết quả benchmark thật, vì kết quả phụ thuộc GPU, version vLLM, model, prompt length, concurrency và workload thực tế trên máy của bạn.

---

## 0. Mục tiêu chứng minh

Bạn cần chứng minh 2 ý chính:

1. **Dự án thật sự đang dùng vLLM**
   - Có vLLM server chạy riêng ở `localhost:8000`.
   - Pipeline gọi LLM qua OpenAI-compatible API của vLLM.
   - vLLM expose `/metrics` trực tiếp để kiểm tra serving metrics khi cần benchmark.

2. **vLLM có hiệu quả trong dự án**
   - Hiệu quả chính cần chứng minh: **serving throughput tốt hơn khi có nhiều LLM calls đồng thời**.
   - Không nên chỉ demo 1 request đơn lẻ, vì vLLM thường thể hiện rõ nhất khi có concurrency, batching, prompt/output dài, KV cache lớn.
   - Trong project MCQGen, mỗi câu MCQ cần nhiều LLM calls, nên đây là workload phù hợp để chứng minh vLLM.

---

## 1. Kiến thức nền: vLLM là gì?

### 1.1 vLLM là gì?

vLLM là một inference/serving engine cho Large Language Models. Nói đơn giản, thay vì app của bạn tự load model và tự generate từng request, bạn chạy một **vLLM server** chuyên phụ trách inference. App gửi request tới server này qua API.

Trong dự án của bạn, vLLM đóng vai trò:

```text
MCQGen Pipeline / FastAPI / Celery
        |
        | OpenAI-compatible API
        v
vLLM server: http://localhost:8000/v1
        |
        v
Model: models/Qwen3-8B-AWQ, served name: mcqgen
```

### 1.2 Tại sao vLLM ra đời?

LLM serving có một vấn đề lớn: **GPU tính rất nhanh nhưng inference lại dễ bị nghẽn bởi memory**, đặc biệt là **KV cache**.

Khi LLM sinh văn bản, nó sinh từng token một. Mỗi token mới phụ thuộc vào các token trước đó. Để không phải tính lại attention cho toàn bộ lịch sử, hệ thống lưu lại key/value của các token trước — gọi là **KV cache**.

Vấn đề:

- Mỗi request có độ dài prompt/output khác nhau.
- Output length thường không biết trước.
- KV cache tăng dần trong quá trình sinh token.
- Nếu lưu KV cache theo vùng memory liên tục và cấp phát dư từ đầu, GPU memory bị lãng phí.
- Khi memory bị lãng phí, batch size giảm, dẫn tới throughput thấp.

Paper vLLM chỉ ra rằng high-throughput LLM serving cần batch đủ nhiều request, nhưng các hệ thống cũ bị giới hạn vì KV cache lớn, thay đổi động và dễ gây fragmentation. Paper đề xuất **PagedAttention** để quản lý KV cache hiệu quả hơn.

### 1.3 vLLM giải quyết vấn đề gì?

vLLM tập trung giải quyết các bottleneck sau:

| Bottleneck | Ý nghĩa trong LLM serving | vLLM giúp gì? |
|---|---|---|
| KV cache lớn | Prompt/output càng dài thì KV cache càng lớn | Quản lý KV cache theo block |
| Memory fragmentation | GPU còn memory nhưng bị chia nhỏ hoặc đặt trước quá nhiều | PagedAttention giảm lãng phí |
| Batch size thấp | Ít request xử lý cùng lúc | Cho phép nhiều request fit vào GPU memory hơn |
| Throughput thấp | Ít token/request mỗi giây | Continuous batching + efficient KV cache |
| Prompt lặp lại | Nhiều request có prefix giống nhau | Prefix caching nếu bật và workload phù hợp |

### 1.4 vLLM giải quyết như thế nào?

#### Trực giác

Hãy tưởng tượng mỗi request cần thuê chỗ trong GPU memory để lưu KV cache.

Cách cũ giống như:

> Mỗi request được cấp một căn phòng lớn liên tục ngay từ đầu, dù chưa chắc dùng hết.

vLLM giống như:

> Chia memory thành nhiều block nhỏ. Request cần tới đâu lấy block tới đó. Các block không cần nằm cạnh nhau.

#### Kỹ thuật

vLLM dùng **PagedAttention**:

- Chia KV cache thành các **KV blocks**.
- Dùng **block table** để map logical blocks của request sang physical blocks trên GPU.
- Không cần cấp phát một vùng liên tục cực lớn cho cả sequence.
- Có thể cấp phát block mới khi request sinh thêm token.
- Có thể share block trong một số trường hợp, ví dụ shared prefix hoặc parallel decoding.

### 1.5 Hiệu quả kỳ vọng của vLLM

Theo paper vLLM, hệ thống vLLM đạt throughput cao hơn khoảng **2–4×** so với các baseline trong thí nghiệm của paper, với mức latency tương đương. Tuy nhiên, đây là kết quả của paper trong setup cụ thể; bạn **không nên hứa giáo sư rằng project của bạn chắc chắn cũng đạt đúng 2–4×**. Bạn cần benchmark trên GPU/model/workload thật của dự án.

Trong project của bạn, hiệu quả kỳ vọng nên trình bày thực tế hơn:

```text
vLLM không nhất thiết làm 1 request đơn lẻ nhanh hơn rõ rệt.
vLLM giúp hệ thống xử lý nhiều LLM calls đồng thời hiệu quả hơn,
đặc biệt khi pipeline sinh nhiều câu MCQ song song.
```

---

## 2. Dự án hiện tại đang dùng vLLM ở đâu?

Dựa trên source code hiện tại trong project upload, các điểm chứng minh như sau.

### 2.1 `start_system.sh`: khởi động vLLM server

Trong `start_system.sh`, hệ thống chạy vLLM bằng command dạng:

```bash
vllm serve models/Qwen3-8B-AWQ \
  --dtype half --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --enforce-eager --enable-prefix-caching \
  --max-num-seqs 4 \
  --port 8000 \
  --host 0.0.0.0 \
  --served-model-name mcqgen
```

Ý nghĩa để trình bày:

| Thành phần | Ý nghĩa |
|---|---|
| `vllm serve` | Chạy model bằng vLLM server |
| `models/Qwen3-8B-AWQ` | Model đang serve |
| `--served-model-name mcqgen` | Tên model mà app gọi trong API |
| `--port 8000` | vLLM server expose ở port 8000 |
| `--enable-prefix-caching` | Bật prefix caching |
| `--max-num-seqs 4` | Giới hạn số sequence tối đa xử lý trong một iteration |
| `--gpu-memory-utilization 0.90` | Cho phép vLLM dùng tối đa khoảng 90% GPU memory cho engine/cache |

### 2.2 `pipeline_mcq.py`: pipeline gọi vLLM qua OpenAI-compatible API

Trong `pipeline_mcq.py`, project dùng:

```python
from openai import AsyncOpenAI

VLLM_URL = "http://localhost:8000/v1"
MODEL = "mcqgen"
client_llm = AsyncOpenAI(base_url=VLLM_URL, api_key="x")
```

Và mỗi LLM call đi qua:

```python
resp = await client_llm.chat.completions.create(
    model=MODEL,
    messages=[...],
    temperature=temperature,
    max_tokens=max_tokens,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}}
)
```

Điều này chứng minh app không gọi trực tiếp HuggingFace trong pipeline chính, mà gọi vLLM qua endpoint tương thích OpenAI.

### 2.3 `generate_one_mcq()`: mỗi câu MCQ có nhiều LLM calls

Trong `pipeline_mcq.py`, mỗi MCQ đi qua nhiều bước:

| Bước | Mục đích | LLM call? |
|---|---|---|
| P1 | Generate stem/key | Có |
| P4 | Generate distractors | Có |
| P5 | Evaluate distractors | Có |
| P6 | Remove bad options | Có |
| P7 | Select final distractors | Có |
| P8 | Assemble MCQ | Có |
| Eval | Evaluate final MCQ | Có |

Vì vậy, mỗi MCQ không phải 1 request mà là nhiều request tới LLM. Đây là lý do project rất phù hợp để demo vLLM với concurrency.

### 2.4 `run_pipeline()`: pipeline đang chạy async

Trong `run_pipeline()`, project tạo nhiều task:

```python
all_tasks.append(generate_one_mcq(topic_cfg, seq))
```

Sau đó chạy:

```python
results = await asyncio.gather(*all_tasks, return_exceptions=True)
```

Ý nghĩa:

- Nhiều MCQ được generate song song ở cấp application.
- Nhiều LLM calls có thể cùng lúc đi vào vLLM server.
- Đây là điều kiện để vLLM thể hiện lợi ích batching/serving throughput.

### 2.5 `advanced_retrieval.py`: HyDE cũng gọi vLLM

Trong `advanced_retrieval.py`, project cũng dùng:

```python
llm_client = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="x")
```

HyDE generation cũng có thể tạo thêm LLM calls tới vLLM.

### 2.6 vLLM metrics kiểm tra trực tiếp khi benchmark

vLLM expose metrics ở endpoint `/metrics`. Khi benchmark, kiểm tra trực tiếp:

```bash
curl -s http://localhost:8000/metrics | grep 'vllm:'
```

Các metric nên quan sát:

| Panel | PromQL |
|---|---|
| vLLM Requests Running | `vllm:num_requests_running{model_name="mcqgen"}` |
| Requests Waiting | `vllm:num_requests_waiting{model_name="mcqgen"}` |
| GPU KV Cache Usage % | `vllm:gpu_cache_usage_perc{model_name="mcqgen"} * 100` |
| Token Throughput | `rate(vllm:iteration_tokens_total_sum{model_name="mcqgen"}[1m])` |
| Prefix Cache Hit Rate | `vllm:gpu_prefix_cache_hit_rate{model_name="mcqgen"} * 100` |

Đây là phần rất quan trọng để demo “bằng mắt thường”.

---

## 3. Thông điệp chính khi trình bày với giáo sư

Bạn có thể trình bày như sau:

> Project MCQGen của em dùng vLLM như một inference server độc lập. Pipeline sinh câu hỏi gửi request tới vLLM qua OpenAI-compatible API. Vì mỗi câu MCQ cần nhiều LLM calls, em dùng async execution để tạo nhiều request đồng thời. vLLM giúp xử lý workload này hiệu quả hơn bằng continuous batching, quản lý KV cache bằng PagedAttention, và expose metrics để quan sát throughput/KV cache/request queue.

Cần nhấn mạnh:

```text
vLLM không làm model thông minh hơn.
vLLM làm quá trình serving/inference hiệu quả hơn.
Hiệu quả cần đo bằng throughput, latency, wall-clock time, GPU memory/KV cache, queue size.
```

---

## 4. Những metric cần đo

### 4.1 Metric bắt buộc

| Metric | Cách đo | Ý nghĩa |
|---|---|---|
| Wall-clock time | `time.time()` quanh pipeline | Tổng thời gian sinh N MCQs |
| Requests/sec | Benchmark client | Hệ thống xử lý bao nhiêu LLM requests/s |
| Output tokens/sec | vLLM metrics hoặc benchmark | Throughput sinh token |
| p50/p95 latency | Benchmark client | Độ trễ trung bình và tail latency |
| Accepted MCQs | Output pipeline | Đảm bảo tăng tốc không làm hỏng quality |
| Failed MCQs | Output pipeline | Kiểm tra lỗi parse/quality |
| GPU KV cache usage | vLLM `/metrics` hoặc log benchmark | Chứng minh vLLM đang dùng KV cache |
| Requests running/waiting | vLLM `/metrics` hoặc log benchmark | Chứng minh batching/queue đang diễn ra |
| GPU memory/utilization | `nvidia-smi` | Chứng minh GPU đang phục vụ inference |

### 4.2 Metric nên có nếu đủ thời gian

| Metric | Ý nghĩa |
|---|---|
| TTFT | Time To First Token, quan trọng cho streaming/chat |
| ITL/TPOT | Inter-token latency/time per output token |
| Prefix cache hit rate | Chứng minh prefix caching nếu nhiều prompt có prefix giống nhau |
| Cost per MCQ | Nếu quy đổi theo GPU time |
| Throughput under concurrency sweep | Chứng minh hệ thống scale khi tăng concurrent requests |

---

## 5. Các thí nghiệm cần làm

## Experiment 1 — Chứng minh đang dùng vLLM

### Mục tiêu

Cho giáo sư thấy server vLLM thật sự đang chạy và app có thể gọi được.

### Commands

```bash
curl -s http://localhost:8000/health
```

```bash
curl -s http://localhost:8000/v1/models | jq
```

```bash
curl -s http://localhost:8000/metrics | head
```

```bash
curl -s http://localhost:8000/metrics | grep -E "vllm.*(request|token|cache|queue|running|waiting)" | head -50
```

### Evidence cần lưu

```bash
mkdir -p results/vllm_demo

curl -s http://localhost:8000/v1/models \
  > results/vllm_demo/models.json

curl -s http://localhost:8000/metrics \
  > results/vllm_demo/vllm_metrics_snapshot.txt

cp logs/vllm.log results/vllm_demo/vllm.log 2>/dev/null || true
```

### Cách giải thích

- `/v1/models` trả về model `mcqgen` → app đang gọi đúng served model.
- `/metrics` có metric `vllm:*` → vLLM expose observability.
- `logs/vllm.log` có command/load model → chứng minh vLLM server đang host model.

---

## Experiment 2 — Benchmark LLM-only: concurrency sweep

### Mục tiêu

Đo hiệu quả vLLM khi tăng số request đồng thời.

Đây là demo dễ thấy nhất vì nó bỏ qua retrieval/reranker/IO, chỉ tập trung vào LLM serving.

### Script đề xuất: `bench_vllm_visible.py`

Tạo file ở root project:

```python
import argparse
import asyncio
import csv
import statistics
import time
from openai import AsyncOpenAI

PROMPT = """Tạo 1 câu MCQ tiếng Việt về topic Python Pandas, độ khó G2.
Output JSON:
{"question_text":"...","options":{"A":"...","B":"...","C":"...","D":"..."},"correct_answers":["A"]}
Chỉ JSON, không text khác."""

def percentile(values, p):
    if not values:
        return 0
    values = sorted(values)
    k = int((len(values) - 1) * p / 100)
    return values[k]

async def one_call(client, model, i, max_tokens):
    t0 = time.time()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=0.7,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    dt = time.time() - t0

    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

    return {
        "id": i,
        "latency_s": dt,
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "total_tokens": total_tokens or 0,
    }

async def run(args):
    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key)
    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(i):
        async with sem:
            return await one_call(client, args.model, i, args.max_tokens)

    print(f"Warmup {args.warmup} requests...")
    for i in range(args.warmup):
        await one_call(client, args.model, -i, args.max_tokens)

    print(f"Running benchmark: num_requests={args.num_requests}, concurrency={args.concurrency}")
    t0 = time.time()
    results = await asyncio.gather(*[guarded(i) for i in range(args.num_requests)])
    wall = time.time() - t0

    latencies = [r["latency_s"] for r in results]
    total_completion_tokens = sum(r["completion_tokens"] for r in results)
    total_tokens = sum(r["total_tokens"] for r in results)

    summary = {
        "num_requests": args.num_requests,
        "concurrency": args.concurrency,
        "wall_time_s": round(wall, 3),
        "requests_per_s": round(args.num_requests / wall, 3),
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "completion_tokens_per_s": round(total_completion_tokens / wall, 3) if total_completion_tokens else 0,
        "total_tokens_per_s": round(total_tokens / wall, 3) if total_tokens else 0,
        "latency_avg_s": round(statistics.mean(latencies), 3),
        "latency_p50_s": round(percentile(latencies, 50), 3),
        "latency_p95_s": round(percentile(latencies, 95), 3),
        "latency_max_s": round(max(latencies), 3),
    }

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    if args.output:
        write_header = True
        try:
            with open(args.output, "r", encoding="utf-8"):
                write_header = False
        except FileNotFoundError:
            pass

        with open(args.output, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(summary)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default="mcqgen")
    parser.add_argument("--num-requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--output", default="results/vllm_demo/vllm_visible_benchmark.csv")
    args = parser.parse_args()
    asyncio.run(run(args))
```

### Chạy benchmark

```bash
mkdir -p results/vllm_demo

for C in 1 2 4 8; do
  python bench_vllm_visible.py \
    --num-requests 40 \
    --concurrency $C \
    --max-tokens 512 \
    --output results/vllm_demo/vllm_visible_benchmark.csv
done
```

Nếu OOM hoặc queue quá lâu ở concurrency 8, dừng ở 4.

### Bảng kết quả cần điền

| Concurrency | Wall time | Requests/s | Output tokens/s | p50 latency | p95 latency | Ghi chú |
|---:|---:|---:|---:|---:|---:|---|
| 1 | ... | ... | ... | ... | ... | baseline |
| 2 | ... | ... | ... | ... | ... |  |
| 4 | ... | ... | ... | ... | ... | config hiện tại `max_num_seqs=4` |
| 8 | ... | ... | ... | ... | ... | chỉ nếu không OOM |

### Cách giải thích kết quả

Nếu concurrency tăng từ 1 → 4 và:

- Requests/s tăng,
- Tokens/s tăng,
- Wall-clock time giảm,
- GPU KV cache usage tăng,
- Requests running trong vLLM metrics tăng,

thì đây là bằng chứng rõ ràng rằng vLLM đang xử lý concurrent serving hiệu quả hơn single-request/sequential mode.

---

## Experiment 3 — Full pipeline: sequential vs async vLLM

### Mục tiêu

So sánh pipeline thật của project:

| Mode | Ý nghĩa |
|---|---|
| Sequential | Chạy từng MCQ task tuần tự, ít tận dụng batching |
| Async + vLLM | Chạy nhiều MCQ task song song qua vLLM |

### Vì sao cần experiment này?

Experiment 2 chứng minh LLM serving. Experiment 3 chứng minh tác động lên project thật.

### Patch đề xuất cho `pipeline_mcq.py`

Thêm function:

```python
async def run_tasks_with_mode(all_tasks, mode: str = "async"):
    if mode == "sequential":
        results = []
        for i, task in enumerate(all_tasks, 1):
            print(f"[Sequential] Running task {i}/{len(all_tasks)}")
            results.append(await task)
        return results

    return await asyncio.gather(*all_tasks, return_exceptions=True)
```

Trong `run_pipeline()`, thay:

```python
results = await asyncio.gather(*all_tasks, return_exceptions=True)
```

bằng:

```python
import os
mode = os.getenv("MCQGEN_RUN_MODE", "async")
print(f"Run mode: {mode}")
results = await run_tasks_with_mode(all_tasks, mode)
```

Trong `run_pipeline_with_topics()`, cũng có thể thay tương tự nếu bạn demo qua API/Celery.

### Chạy baseline sequential

```bash
mkdir -p results/vllm_demo

MCQGEN_RUN_MODE=sequential python -m src.mcqgen.pipeline_mcq \
  | tee results/vllm_demo/pipeline_sequential.log
```

### Chạy async + vLLM

```bash
MCQGEN_RUN_MODE=async python -m src.mcqgen.pipeline_mcq \
  | tee results/vllm_demo/pipeline_async_vllm.log
```

### Bảng kết quả cần điền

| Mode | Số MCQs target | Accepted | Failed | Total time | Speedup |
|---|---:|---:|---:|---:|---:|
| Sequential | ... | ... | ... | ... | 1.0x |
| Async + vLLM | ... | ... | ... | ... | ...x |

Công thức:

```text
Speedup = Total time sequential / Total time async_vLLM
```

### Cách giải thích

> Đây là thí nghiệm end-to-end. Nó đo tác động thực tế lên pipeline sinh câu hỏi, không chỉ đo synthetic benchmark. Nếu accepted/failed tương đương nhưng total time giảm, chứng tỏ dùng vLLM + async serving giúp project chạy hiệu quả hơn.

---

## Experiment 4 — A/B test `--max-num-seqs`

### Mục tiêu

Chứng minh lợi ích batching của vLLM bằng cách thay đổi `--max-num-seqs`.

`--max-num-seqs` càng cao thì vLLM càng có cơ hội xử lý nhiều sequence trong một iteration, nhưng nếu quá cao có thể gây áp lực GPU memory/KV cache.

### Matrix đề xuất

| Run | `--max-num-seqs` | Ý nghĩa |
|---|---:|---|
| A | 1 | Gần giống không batching |
| B | 2 | Batching nhẹ |
| C | 4 | Config hiện tại |
| D | 8 | Thử nếu GPU còn đủ memory |

### Command mẫu

```bash
vllm serve models/Qwen3-8B-AWQ \
  --dtype half \
  --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --enforce-eager \
  --enable-prefix-caching \
  --max-num-seqs 1 \
  --port 8000 \
  --host 0.0.0.0 \
  --served-model-name mcqgen
```

Sau đó đổi `--max-num-seqs` thành `2`, `4`, `8` và chạy lại `bench_vllm_visible.py`.

### Bảng kết quả cần điền

| max_num_seqs | Concurrency test | Requests/s | Tokens/s | p95 latency | GPU KV cache max | OOM? |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4 | ... | ... | ... | ... | no/yes |
| 2 | 4 | ... | ... | ... | ... | no/yes |
| 4 | 4 | ... | ... | ... | ... | no/yes |
| 8 | 4 | ... | ... | ... | ... | no/yes |

### Cách giải thích

Nếu `max_num_seqs=1` chậm hơn `max_num_seqs=4`, bạn có bằng chứng trực quan rằng batching/serving capacity của vLLM có tác dụng trong workload nhiều request.

---

## Experiment 5 — Prefix caching on/off

### Mục tiêu

Chứng minh `--enable-prefix-caching` có tác dụng nếu nhiều request có prefix/system prompt giống nhau.

Project của bạn có nhiều prompt lặp:

- `SYSTEM_PROMPT` cố định.
- Instruction JSON output lặp lại.
- Context/rubric/prompt template có cấu trúc tương tự.

### Matrix

| Run | Prefix caching | Command flag |
|---|---|---|
| A | Off | Không truyền `--enable-prefix-caching` |
| B | On | Truyền `--enable-prefix-caching` |

### Workload phù hợp

Tạo 20 request có cùng prefix dài và chỉ thay đổi topic/câu cuối.

Pseudo-prompt:

```text
[PREFIX CỐ ĐỊNH]
Bạn là giảng viên CS116...
Rubric...
JSON schema...
Context dài...

[PHẦN THAY ĐỔI]
Tạo câu hỏi số i về topic X.
```

### Metric cần nhìn

| Metric | Kỳ vọng |
|---|---|
| Prefix cache hit rate | Tăng khi caching bật và prefix thật sự giống nhau |
| TTFT hoặc wall time | Có thể giảm nếu prefix dài và cache hit tốt |
| Token throughput | Có thể tăng |

### Lưu ý

Nếu prefix không đủ dài hoặc request không thật sự có prefix identical sau tokenization, hiệu quả có thể không rõ. Khi đó, không nên kết luận prefix caching vô dụng; chỉ nói workload hiện tại chưa tạo điều kiện tốt để cache hit.

---

## Experiment 6 — Dùng benchmark chính thức của vLLM

### Mục tiêu

Có thêm benchmark bằng tool chính thức để tăng độ tin cậy.

### Cài dependencies

```bash
pip install "vllm[bench]"
```

### Online serving benchmark

```bash
vllm bench serve \
  --model mcqgen \
  --host localhost \
  --port 8000 \
  --random-input-len 512 \
  --random-output-len 256 \
  --num-prompts 40
```

Nếu CLI của version hiện tại khác, chạy:

```bash
vllm bench serve --help
```

### Cách dùng trong báo cáo

- Benchmark custom của bạn chứng minh workload MCQGen.
- Benchmark chính thức của vLLM chứng minh theo tool chuẩn.
- Hai loại benchmark bổ trợ nhau.

---

## 6. Chứng minh “không dùng vLLM” như thế nào?

Có 2 mức baseline. Nên trình bày rõ để tránh bị giáo sư hỏi về tính công bằng.

## Baseline A — Không tận dụng batching vLLM

Đây là baseline dễ làm nhất:

- Vẫn dùng vLLM server để đảm bảo cùng model/API.
- Nhưng chạy request tuần tự hoặc set `--max-num-seqs=1`.
- Mục tiêu: chứng minh lợi ích batching/concurrent serving.

Ưu điểm:

- Dễ chạy.
- Ít lỗi môi trường.
- So sánh cùng model, cùng prompt, cùng endpoint.

Nhược điểm:

- Không phải “không dùng vLLM” tuyệt đối.
- Nên gọi tên là: **sequential / no batching baseline**.

## Baseline B — Không dùng vLLM thật sự: direct Transformers/HuggingFace

Đây là baseline đúng nghĩa hơn:

- App/script load model trực tiếp bằng HuggingFace Transformers.
- Generate tuần tự bằng `model.generate()`.
- So sánh với vLLM server.

Ưu điểm:

- Đúng nghĩa “không dùng vLLM”.

Nhược điểm:

- Có thể khó chạy với `Qwen3-8B-AWQ` tùy version Transformers, quantization backend, GPU memory.
- Có thể không công bằng nếu dtype/quantization/tokenizer/generation config khác.
- Nếu setup không giống vLLM, kết quả dễ bị tranh luận.

### Khuyến nghị trình bày

Nên có cả 2 nếu đủ thời gian:

1. **Main result**: Sequential/no-batching vs async/vLLM trong pipeline thật.
2. **Optional appendix**: Direct Transformers baseline nếu chạy ổn.

Nếu không đủ thời gian, dùng Baseline A và nói rõ:

> Vì project production hiện tại đã thiết kế quanh OpenAI-compatible vLLM server, em dùng sequential/no-batching baseline để cô lập lợi ích concurrency/batching. Direct Transformers baseline được xem là future work hoặc appendix nếu môi trường hỗ trợ.

---

## 7. Demo bằng mắt thường nên làm như thế nào?

### 7.1 Chuẩn bị 4 cửa sổ

| Cửa sổ | Nội dung |
|---|---|
| Terminal 1 | vLLM server log |
| Terminal 2 | Chạy benchmark/pipeline |
| Terminal 3 | `watch -n 1 nvidia-smi` |
| Browser | Langfuse traces hoặc report benchmark |

### 7.2 Kịch bản demo live

#### Bước 1 — Show vLLM server

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/v1/models | jq
```

Nói:

> Đây là vLLM server đang chạy model `mcqgen`. Pipeline gọi endpoint này thay vì tự load model.

#### Bước 2 — Show metrics

```bash
curl -s http://localhost:8000/metrics | grep -E "vllm.*(running|waiting|cache|token)" | head
```

Nói:

> vLLM expose metrics để đo số request đang chạy, đang chờ, KV cache usage, token throughput.

#### Bước 3 — Chạy concurrency benchmark

```bash
python bench_vllm_visible.py --num-requests 40 --concurrency 1
python bench_vllm_visible.py --num-requests 40 --concurrency 4
```

Nói:

> Khi tăng concurrency, ta kỳ vọng throughput tăng và vLLM metrics sẽ thấy request running/KV cache/token throughput thay đổi.

#### Bước 4 — Chạy full pipeline

```bash
MCQGEN_RUN_MODE=sequential python -m src.mcqgen.pipeline_mcq
MCQGEN_RUN_MODE=async python -m src.mcqgen.pipeline_mcq
```

Nói:

> Đây là benchmark end-to-end của project. Cùng model, cùng prompt pipeline, nhưng mode async + vLLM xử lý nhiều LLM calls đồng thời tốt hơn.

### 7.3 Ảnh cần chụp để đưa vào report

| Screenshot | Mục đích |
|---|---|
| `/v1/models` output | Chứng minh model served by vLLM |
| `/metrics` output | Chứng minh observability |
| vLLM metrics during benchmark | Thấy request running/KV cache/tokens/s |
| Terminal benchmark summary | Thấy throughput/latency |
| Pipeline sequential summary | Baseline |
| Pipeline async summary | Result sau khi dùng vLLM hiệu quả |
| `nvidia-smi` during run | Chứng minh GPU đang hoạt động |

---

## 8. Template ghi kết quả cuối cùng

Tạo file `results/vllm_demo/summary.md` sau khi chạy.

```markdown
# vLLM Demo Results

## Environment

- GPU: ...
- VRAM: ...
- CUDA: ...
- Python: ...
- vLLM version: ...
- Model: models/Qwen3-8B-AWQ
- Served model name: mcqgen
- max_model_len: 8192
- max_num_seqs: 4
- prefix caching: enabled

## Experiment 1: Proof vLLM is used

- `/health`: pass/fail
- `/v1/models`: pass/fail
- `/metrics`: pass/fail
- vLLM metrics snapshot: pass/fail

## Experiment 2: LLM-only concurrency benchmark

| Concurrency | Wall time | Requests/s | Output tokens/s | p95 latency |
|---:|---:|---:|---:|---:|
| 1 | ... | ... | ... | ... |
| 2 | ... | ... | ... | ... |
| 4 | ... | ... | ... | ... |

## Experiment 3: Full pipeline

| Mode | Target MCQs | Accepted | Failed | Total time | Speedup |
|---|---:|---:|---:|---:|---:|
| Sequential | ... | ... | ... | ... | 1.0x |
| Async + vLLM | ... | ... | ... | ... | ...x |

## Interpretation

- vLLM improves ...
- The strongest evidence is ...
- Limitation: ...
```

---

## 9. Checklist việc cần làm theo thứ tự

### Phase 0 — Chuẩn hóa môi trường

- [ ] Ghi lại GPU bằng `nvidia-smi`.
- [ ] Ghi lại Python/vLLM/Torch version.
- [ ] Đảm bảo vLLM server chạy ổn.
- [ ] Đảm bảo `/health`, `/v1/models`, `/metrics` hoạt động.

Command:

```bash
mkdir -p results/vllm_demo

{
  echo "DATE=$(date)"
  echo "HOST=$(hostname)"
  echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
  nvidia-smi
  python --version
  pip show vllm | sed -n '1,20p'
  pip show torch | sed -n '1,20p'
} | tee results/vllm_demo/env.txt
```

### Phase 1 — Chứng minh đang dùng vLLM

- [ ] Lưu output `/v1/models`.
- [ ] Lưu output `/metrics`.
- [ ] Lưu log vLLM.
- [ ] Lưu snapshot vLLM metrics.

### Phase 2 — Benchmark LLM-only

- [ ] Tạo `bench_vllm_visible.py`.
- [ ] Chạy concurrency 1, 2, 4, 8.
- [ ] Lưu CSV.
- [ ] Vẽ hoặc lập bảng kết quả.

### Phase 3 — Benchmark full pipeline

- [ ] Thêm `MCQGEN_RUN_MODE=sequential`.
- [ ] Chạy sequential.
- [ ] Chạy async.
- [ ] So sánh accepted/failed/time.

### Phase 4 — Ablation vLLM config

- [ ] Chạy `max_num_seqs=1`.
- [ ] Chạy `max_num_seqs=4`.
- [ ] Nếu còn VRAM, chạy `max_num_seqs=8`.
- [ ] So sánh throughput/latency/KV cache.

### Phase 5 — Prefix caching

- [ ] Tạo workload có prefix dài giống nhau.
- [ ] Chạy không bật prefix caching.
- [ ] Chạy bật prefix caching.
- [ ] So sánh prefix cache hit rate, wall time, TTFT nếu đo được.

### Phase 6 — Chuẩn bị trình bày

- [ ] 1 slide giải thích vLLM/PagedAttention.
- [ ] 1 slide architecture project.
- [ ] 1 slide benchmark design.
- [ ] 1 slide kết quả bảng.
- [ ] 1 slide vLLM metrics snapshot.
- [ ] 1 slide limitations/future work.

---

## 10. Những câu hỏi giáo sư có thể hỏi và câu trả lời gợi ý

### Q1. vLLM có làm model trả lời đúng hơn không?

Không. vLLM chủ yếu cải thiện **serving efficiency**: throughput, batching, memory management, latency under load. Chất lượng câu trả lời vẫn phụ thuộc model, prompt, RAG, sampling và evaluator.

### Q2. Vì sao 1 request đơn lẻ không nhanh hơn rõ?

Vì lợi ích chính của vLLM nằm ở serving nhiều request: batching, KV cache management, giảm memory waste. Với 1 request, batching không phát huy nhiều.

### Q3. Làm sao biết project thật sự đang dùng vLLM?

Có 4 bằng chứng:

1. `start_system.sh` chạy `vllm serve`.
2. Pipeline dùng `AsyncOpenAI(base_url="http://localhost:8000/v1")`.
3. `/v1/models` trả về model `mcqgen`.
4. `/metrics` có metric `vllm:*`.

### Q4. Nếu async nhanh hơn, làm sao biết đó là nhờ vLLM chứ không chỉ nhờ asyncio?

Cần làm ablation:

- Async + `max_num_seqs=1`.
- Async + `max_num_seqs=4`.
- Sequential mode.

Nếu async với `max_num_seqs=4` có throughput tốt hơn `max_num_seqs=1`, đó là dấu hiệu batching/serving engine của vLLM đang đóng góp.

### Q5. Có cần baseline không dùng vLLM thật sự không?

Có thì tốt, nhưng không bắt buộc nếu môi trường khó chạy direct Transformers với AWQ. Nếu làm được, chạy thêm direct Transformers baseline. Nếu không, trình bày rõ là bạn dùng **sequential/no-batching baseline** để cô lập lợi ích serving.

### Q6. Metric nào quan trọng nhất?

Với project này:

1. Full-pipeline wall-clock time.
2. Accepted MCQs.
3. Requests/s.
4. Output tokens/s.
5. p95 latency.
6. GPU KV cache usage và requests running/waiting.

### Q7. Nếu kết quả không nhanh hơn thì sao?

Có vài nguyên nhân khả dĩ:

- Workload quá nhỏ.
- Concurrency thấp.
- `max_num_seqs` thấp.
- Bottleneck nằm ở retrieval/reranker CPU, không nằm ở LLM.
- Prompt/output ngắn nên KV cache bottleneck chưa rõ.
- `--enforce-eager` có thể làm mất một số tối ưu tùy setup.
- GPU đã compute-bound thay vì memory-bound.

Cách xử lý:

- Tách LLM-only benchmark khỏi full pipeline.
- Tăng số request.
- Tăng prompt/output length.
- Sweep concurrency.
- Sweep `max_num_seqs`.
- Quan sát vLLM `/metrics` và `nvidia-smi`.

---

## 11. Những rủi ro khi benchmark

| Rủi ro | Ảnh hưởng | Cách giảm rủi ro |
|---|---|---|
| Model cold start | Run đầu tiên chậm bất thường | Warmup trước benchmark |
| Prompt khác nhau | Kết quả không công bằng | Dùng cùng prompt/input/output limit |
| Output length khác nhau | Latency khó so sánh | Cố định `max_tokens`, đo tokens/s |
| Retrieval CPU bottleneck | Che mất lợi ích vLLM | Có benchmark LLM-only riêng |
| OOM khi concurrency cao | Benchmark fail | Tăng dần concurrency, theo dõi KV cache |
| Metrics name thay đổi theo version | Metric cần đọc khác tên | Kiểm tra trực tiếp `/metrics` |
| Direct Transformers baseline khó chạy | Không có true no-vLLM baseline | Ghi rõ limitation, dùng no-batching ablation |

---

## 12. Đề xuất cấu trúc slide trình bày

### Slide 1 — Problem

- MCQGen cần sinh nhiều câu hỏi.
- Mỗi câu hỏi cần nhiều LLM calls.
- Nếu chạy tuần tự, thời gian tăng rất nhanh.

### Slide 2 — Why vLLM

- LLM serving bị nghẽn bởi KV cache và batching.
- vLLM dùng PagedAttention để quản lý KV cache hiệu quả.
- Mục tiêu: tăng throughput khi có nhiều request.

### Slide 3 — Project Architecture

```text
Next.js/FastAPI/Celery
        |
        v
src.mcqgen.pipeline_mcq / src.mcqgen.advanced_retrieval
        |
        v
OpenAI-compatible API: localhost:8000/v1
        |
        v
vLLM server: Qwen3-8B-AWQ, served as mcqgen
        |
        v
vLLM metrics + Langfuse traces
```

### Slide 4 — Evidence of vLLM usage

- `start_system.sh` command.
- `AsyncOpenAI(base_url=...)`.
- Screenshot `/v1/models`.
- Screenshot `/metrics`.

### Slide 5 — Benchmark Design

- LLM-only concurrency benchmark.
- Full-pipeline sequential vs async.
- `max_num_seqs` ablation.
- Prefix caching ablation.

### Slide 6 — Results

Bảng kết quả thực tế sau khi chạy.

### Slide 7 — Visual Monitoring

vLLM metrics snapshot:

- Requests running.
- Requests waiting.
- KV cache usage.
- Token throughput.
- Prefix cache hit rate.

### Slide 8 — Conclusion

- vLLM không thay đổi chất lượng model.
- vLLM cải thiện serving throughput.
- Với MCQGen, hiệu quả thể hiện khi generate nhiều MCQs/song song.

---

## 13. Câu kết luận mẫu cho báo cáo

> Trong dự án MCQGen, vLLM được sử dụng như inference server cho model Qwen3-8B-AWQ thông qua OpenAI-compatible API. Pipeline sinh MCQ tạo nhiều LLM calls cho mỗi câu hỏi và chạy nhiều câu hỏi đồng thời bằng asyncio. Do đó workload có tính concurrent serving, phù hợp với vLLM. Bằng cách so sánh sequential/no-batching baseline với async + vLLM, đồng thời quan sát vLLM metrics như token throughput, requests running/waiting và GPU KV cache usage, em có thể chứng minh vLLM không chỉ được tích hợp vào hệ thống mà còn đem lại hiệu quả thực tế về throughput và thời gian xử lý end-to-end.

---

## 14. Nguồn tham khảo nên ghi trong report

1. vLLM paper: **Efficient Memory Management for Large Language Model Serving with PagedAttention**.
2. vLLM GitHub: <https://github.com/vllm-project/vllm>
3. vLLM Quickstart: <https://docs.vllm.ai/en/latest/getting_started/quickstart/>
4. vLLM OpenAI-Compatible Server: <https://docs.vllm.ai/en/latest/serving/openai_compatible_server/>
5. vLLM CLI / Benchmark: <https://docs.vllm.ai/en/latest/cli/>
6. vLLM Production Metrics: <https://docs.vllm.ai/en/latest/usage/metrics/> hoặc kiểm tra theo version bạn đang dùng.

> Vì vLLM docs thay đổi theo version, khi báo cáo nên chụp `vllm --version`, `vllm serve --help`, `vllm bench serve --help` và `/metrics` trực tiếp từ môi trường của bạn.
