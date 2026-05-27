#!/usr/bin/env python3
"""
bench_vllm_demo_mcqgen.py

One-file demo/benchmark runner for proving vLLM usage and effectiveness in
the MCQGen project.

Typical flow:
  python bench_vllm_demo_mcqgen.py evidence
  python bench_vllm_demo_mcqgen.py llm-sweep --concurrency-list 1,2,4
  python bench_vllm_demo_mcqgen.py pipeline --mode sequential --topic-limit 2 --questions-per-topic 1
  python bench_vllm_demo_mcqgen.py pipeline --mode async --concurrency 2 --topic-limit 2 --questions-per-topic 1
  python bench_vllm_demo_mcqgen.py prefix --label prefix_on
  python bench_vllm_demo_mcqgen.py summary

The direct Transformers baseline is intentionally optional because it can be
hard to fit a full 7B model on a single GPU:
  python bench_vllm_demo_mcqgen.py direct --num-requests 3
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import importlib
import json
import math
import os
import shutil
import socket
import statistics
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results" / "vllm_demo"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")

MCQ_SYSTEM_PROMPT = (
    "Bạn là giảng viên Trường ĐH Công nghệ Thông tin ĐHQG-HCM, "
    "dạy môn CS116 - Lập trình Python cho Máy học. "
    "Bạn đang biên soạn câu hỏi trắc nghiệm cho sinh viên đại học."
)

MCQ_PROMPT = """Tạo 1 câu MCQ tiếng Việt về topic Python Pandas, độ khó G2.

[YÊU CẦU]
- Câu hỏi kiểm tra hiểu khái niệm hoặc áp dụng, không hỏi định nghĩa thuần túy.
- Có đúng 4 options A/B/C/D.
- Có đúng 1 đáp án đúng.
- Distractors phải plausible nhưng sai rõ ràng về mặt kỹ thuật.

[OUTPUT JSON ONLY]
{
  "question_text": "...",
  "question_type": "single_correct",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answers": ["A"],
  "correct_rationale": "...",
  "topic": "Python Pandas",
  "difficulty_label": "G2"
}
"""

PREFIX_SHARED_BLOCK = """[ROLE]
Bạn là giảng viên Trường ĐH Công nghệ Thông tin ĐHQG-HCM dạy CS116.
Bạn đang tạo câu hỏi trắc nghiệm tiếng Việt cho sinh viên đại học.

[RUBRIC CỐ ĐỊNH]
- Câu hỏi phải bám sát kiến thức học thuật của môn Python cho Máy học.
- Không thêm bối cảnh doanh nghiệp dài dòng.
- Luôn trả về JSON hợp lệ.
- Có đúng 4 options A/B/C/D.
- Không dùng "Tất cả đáp án trên" hoặc "Không đáp án nào đúng".
- Distractors phải sai nhưng plausible.
- Câu hỏi phải kiểm tra hiểu khái niệm hoặc áp dụng, không chỉ học thuộc.

[CONTEXT CỐ ĐỊNH]
Pandas cung cấp các thao tác xử lý dữ liệu dạng bảng như chọn cột, lọc dòng,
xử lý missing values, groupby, merge, apply, và biến đổi dữ liệu. Trong tiền xử
lý dữ liệu cho machine learning, sinh viên cần hiểu khi nào nên drop missing
values, khi nào nên impute, và tác động của từng lựa chọn tới mô hình.

[JSON SCHEMA CỐ ĐỊNH]
{
  "question_text": "...",
  "question_type": "single_correct",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answers": ["A"],
  "correct_rationale": "...",
  "topic": "...",
  "difficulty_label": "G2"
}
"""


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def server_root(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


def http_get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": resp.status,
                "latency_s": round(time.perf_counter() - t0, 4),
                "body": body,
                "error": "",
            }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_s": round(time.perf_counter() - t0, 4),
            "body": "",
            "error": repr(exc),
        }


def run_cmd(args: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.stdout
    except Exception as exc:
        return f"[command failed] {' '.join(args)}\n{exc!r}\n"


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_csv(path: Path, row: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if p == 50:
        return float(statistics.median(ordered))
    idx = max(0, min(len(ordered) - 1, math.ceil((p / 100) * len(ordered)) - 1))
    return ordered[idx]


def safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def filter_vllm_metrics(metrics_text: str) -> str:
    keywords = ("request", "token", "cache", "queue", "running", "waiting", "prefix")
    lines = []
    for line in metrics_text.splitlines():
        lower = line.lower()
        if "vllm" in lower and any(k in lower for k in keywords):
            lines.append(line)
    return "\n".join(lines[:300]) + ("\n" if lines else "")


def build_prompt(prompt_kind: str, request_id: int) -> str:
    if prompt_kind == "prefix":
        topic = [
            "dropna và fillna trong Pandas",
            "SimpleImputer trong sklearn",
            "groupby trong Pandas",
            "train/test split",
            "chuẩn hóa dữ liệu",
        ][request_id % 5]
        return (
            PREFIX_SHARED_BLOCK
            + f"\n[PHẦN THAY ĐỔI]\nTạo câu hỏi số {request_id} về topic: {topic}.\n"
            + "Chỉ trả về JSON, không thêm giải thích ngoài JSON."
        )
    return MCQ_PROMPT


@dataclass
class CallResult:
    request_id: int
    ok: bool
    latency_s: float
    ttft_s: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    output_chars: int
    error: str = ""
    output_preview: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ok": self.ok,
            "latency_s": round(self.latency_s, 4),
            "ttft_s": round(self.ttft_s, 4) if self.ttft_s else 0,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "output_chars": self.output_chars,
            "error": self.error,
            "output_preview": self.output_preview,
        }


async def one_vllm_call(
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    request_id: int,
    temperature: float,
    max_tokens: int,
    stream: bool,
) -> CallResult:
    t0 = time.perf_counter()
    try:
        if stream:
            first_token_at = 0.0
            chunks: list[str] = []
            completion_tokens = 0
            stream_resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": MCQ_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            async for chunk in stream_resp:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = delta.content or ""
                if text and not first_token_at:
                    first_token_at = time.perf_counter()
                if text:
                    chunks.append(text)
                    completion_tokens += 1
            output = "".join(chunks)
            latency = time.perf_counter() - t0
            return CallResult(
                request_id=request_id,
                ok=True,
                latency_s=latency,
                ttft_s=(first_token_at - t0) if first_token_at else 0.0,
                prompt_tokens=0,
                completion_tokens=completion_tokens,
                total_tokens=completion_tokens,
                output_chars=len(output),
                output_preview=output[:240],
            )

        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": MCQ_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        latency = time.perf_counter() - t0
        usage = getattr(resp, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        output = resp.choices[0].message.content or ""
        return CallResult(
            request_id=request_id,
            ok=True,
            latency_s=latency,
            ttft_s=0.0,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            output_chars=len(output),
            output_preview=output[:240],
        )
    except Exception as exc:
        return CallResult(
            request_id=request_id,
            ok=False,
            latency_s=time.perf_counter() - t0,
            ttft_s=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            output_chars=0,
            error=repr(exc),
        )


async def run_one_openai_benchmark(
    *,
    base_url: str,
    api_key: str,
    model: str,
    num_requests: int,
    concurrency: int,
    max_tokens: int,
    temperature: float,
    warmup: int,
    stream: bool,
    prompt_kind: str,
    label: str,
    results_dir: Path,
    csv_name: str,
) -> dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency `openai`. Activate the project environment or install requirements_api.txt."
        ) from exc

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    run = now_id()

    for i in range(warmup):
        await one_vllm_call(
            client,
            model,
            build_prompt(prompt_kind, -1000 - i),
            -1000 - i,
            temperature,
            max_tokens,
            stream,
        )

    metrics_before = http_get(f"{server_root(base_url)}/metrics", timeout=10)
    if metrics_before["ok"]:
        write_text(
            results_dir / f"metrics_before_{label}_{prompt_kind}_c{concurrency}_{run}.txt",
            metrics_before["body"],
        )

    sem = asyncio.Semaphore(concurrency)

    async def guarded(i: int) -> CallResult:
        async with sem:
            prompt = build_prompt(prompt_kind, i)
            return await one_vllm_call(
                client, model, prompt, i, temperature, max_tokens, stream
            )

    print(
        f"[llm] label={label} prompt={prompt_kind} "
        f"requests={num_requests} concurrency={concurrency} max_tokens={max_tokens}"
    )
    wall_start = time.perf_counter()
    results = await asyncio.gather(*[guarded(i) for i in range(num_requests)])
    wall_time = time.perf_counter() - wall_start

    metrics_after = http_get(f"{server_root(base_url)}/metrics", timeout=10)
    if metrics_after["ok"]:
        write_text(
            results_dir / f"metrics_after_{label}_{prompt_kind}_c{concurrency}_{run}.txt",
            metrics_after["body"],
        )
        write_text(
            results_dir / f"metrics_filtered_after_{label}_{prompt_kind}_c{concurrency}_{run}.txt",
            filter_vllm_metrics(metrics_after["body"]),
        )

    per_request_path = results_dir / f"requests_{label}_{prompt_kind}_c{concurrency}_{run}.jsonl"
    for item in results:
        append_jsonl(per_request_path, item.as_dict())

    success = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    latencies = [r.latency_s for r in success]
    ttfts = [r.ttft_s for r in success if r.ttft_s]
    completion_tokens = sum(r.completion_tokens for r in success)
    total_tokens = sum(r.total_tokens for r in success)

    summary = {
        "run_id": run,
        "engine": "vllm_openai_api",
        "label": label,
        "prompt_kind": prompt_kind,
        "base_url": base_url,
        "model": model,
        "num_requests": num_requests,
        "success": len(success),
        "failed": len(failed),
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "stream": stream,
        "wall_time_s": round(wall_time, 4),
        "requests_per_s": round(len(success) / wall_time, 4) if wall_time else 0,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "completion_tokens_per_s": round(completion_tokens / wall_time, 4)
        if wall_time
        else 0,
        "total_tokens_per_s": round(total_tokens / wall_time, 4) if wall_time else 0,
        "latency_avg_s": round(safe_mean(latencies), 4),
        "latency_p50_s": round(percentile(latencies, 50), 4),
        "latency_p95_s": round(percentile(latencies, 95), 4),
        "latency_max_s": round(max(latencies), 4) if latencies else 0,
        "ttft_avg_s": round(safe_mean(ttfts), 4),
        "ttft_p95_s": round(percentile(ttfts, 95), 4),
        "per_request_file": str(per_request_path.relative_to(PROJECT_ROOT)),
    }
    append_csv(results_dir / csv_name, summary)
    print_summary(summary)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    important_keys = [
        "engine",
        "label",
        "prompt_kind",
        "num_requests",
        "success",
        "failed",
        "concurrency",
        "wall_time_s",
        "requests_per_s",
        "completion_tokens_per_s",
        "total_tokens_per_s",
        "latency_avg_s",
        "latency_p50_s",
        "latency_p95_s",
        "ttft_avg_s",
    ]
    for key in important_keys:
        if key in summary:
            print(f"{key}: {summary[key]}")
    print()


def collect_evidence(args: argparse.Namespace) -> dict[str, Any]:
    results_dir = ensure_dir(Path(args.results_dir))
    root = server_root(args.base_url)
    run = now_id()

    health = http_get(f"{root}/health", timeout=args.timeout)
    models = http_get(f"{args.base_url.rstrip('/')}/models", timeout=args.timeout)
    metrics = http_get(f"{root}/metrics", timeout=args.timeout)

    write_json(results_dir / "health.json", health)
    if models["ok"]:
        write_text(results_dir / "models.json", models["body"])
    else:
        write_json(results_dir / "models_error.json", models)
    if metrics["ok"]:
        write_text(results_dir / "vllm_metrics_snapshot.txt", metrics["body"])
        write_text(
            results_dir / "vllm_metrics_filtered.txt",
            filter_vllm_metrics(metrics["body"]),
        )
    else:
        write_json(results_dir / "vllm_metrics_error.json", metrics)

    vllm_log = PROJECT_ROOT / "logs" / "vllm.log"
    if vllm_log.exists():
        shutil.copy2(vllm_log, results_dir / f"vllm_{run}.log")

    env_text = []
    env_text.append(f"DATE={dt.datetime.now().isoformat()}")
    env_text.append(f"HOST={socket.gethostname()}")
    env_text.append(f"PROJECT_ROOT={PROJECT_ROOT}")
    env_text.append(f"CUDA_VISIBLE_DEVICES={os.getenv('CUDA_VISIBLE_DEVICES', '')}")
    env_text.append(f"VLLM_URL={args.base_url}")
    env_text.append(f"VLLM_MODEL={args.model}")
    env_text.append("\n## python\n")
    env_text.append(sys.version)
    env_text.append("\n\n## nvidia-smi\n")
    env_text.append(run_cmd(["nvidia-smi"], timeout=20))
    env_text.append("\n\n## pip show vllm\n")
    env_text.append(run_cmd([sys.executable, "-m", "pip", "show", "vllm"], timeout=20))
    env_text.append("\n\n## pip show torch\n")
    env_text.append(run_cmd([sys.executable, "-m", "pip", "show", "torch"], timeout=20))
    env_text.append("\n\n## scripts/start_system.sh vLLM lines\n")
    start_system = REPO_ROOT / "scripts" / "start_system.sh"
    if start_system.exists():
        lines = [
            line
            for line in start_system.read_text(encoding="utf-8").splitlines()
            if "VLLM_" in line or "vllm serve" in line or "served-model-name" in line
        ]
        env_text.append("\n".join(lines))
    write_text(results_dir / "env.txt", "\n".join(env_text))

    evidence = {
        "run_id": run,
        "base_url": args.base_url,
        "server_root": root,
        "model": args.model,
        "health_ok": health["ok"],
        "models_ok": models["ok"],
        "metrics_ok": metrics["ok"],
        "health_status": health["status"],
        "models_status": models["status"],
        "metrics_status": metrics["status"],
        "vllm_log_copied": vllm_log.exists(),
        "files": {
            "env": str((results_dir / "env.txt").relative_to(PROJECT_ROOT)),
            "models": str((results_dir / "models.json").relative_to(PROJECT_ROOT)),
            "metrics": str(
                (results_dir / "vllm_metrics_snapshot.txt").relative_to(PROJECT_ROOT)
            ),
        },
    }
    write_json(results_dir / "evidence_summary.json", evidence)
    print_summary({"engine": "evidence", "label": "vllm_usage", **evidence})
    return evidence


async def cmd_llm_sweep(args: argparse.Namespace) -> None:
    results_dir = ensure_dir(Path(args.results_dir))
    concurrencies = parse_int_list(args.concurrency_list)
    for concurrency in concurrencies:
        await run_one_openai_benchmark(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            num_requests=args.num_requests,
            concurrency=concurrency,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            warmup=args.warmup,
            stream=args.stream,
            prompt_kind=args.prompt_kind,
            label=args.label,
            results_dir=results_dir,
            csv_name="llm_benchmark.csv",
        )


async def cmd_prefix(args: argparse.Namespace) -> None:
    results_dir = ensure_dir(Path(args.results_dir))
    await run_one_openai_benchmark(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        num_requests=args.num_requests,
        concurrency=args.concurrency,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        warmup=args.warmup,
        stream=args.stream,
        prompt_kind="prefix",
        label=args.label,
        results_dir=results_dir,
        csv_name="prefix_benchmark.csv",
    )


async def cmd_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    results_dir = ensure_dir(Path(args.results_dir))
    os.environ["VLLM_URL"] = args.base_url
    os.environ["VLLM_MODEL"] = args.model
    os.environ["MCQGEN_MAX_CONCURRENT_QUESTIONS"] = str(args.concurrency)

    print("[pipeline] Importing src.mcqgen.pipeline_mcq. This can load retrieval models...")
    pipeline_mcq = importlib.import_module("src.mcqgen.pipeline_mcq")

    topics = load_pipeline_topics(args, pipeline_mcq)
    task_specs = [(topic, seq) for topic in topics for seq in range(topic.get("n", 1))]
    if not task_specs:
        raise SystemExit("No pipeline tasks selected.")

    rag_cache: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
    if args.precompute_rag:
        unique_keys: dict[tuple[str, str, str], dict[str, Any]] = {}
        for topic_cfg, _seq in task_specs:
            key = (topic_cfg["topic"], topic_cfg["chapter_id"], args.retrieval_mode)
            unique_keys.setdefault(key, topic_cfg)
        print(f"[pipeline] Precomputing RAG for {len(unique_keys)} unique topics...")
        for idx, (key, topic_cfg) in enumerate(unique_keys.items(), 1):
            topic, chapter_id, retrieval_mode = key
            t0 = time.perf_counter()
            rag_cache[key] = await pipeline_mcq.adaptive_retrieve(
                topic,
                chapter_id,
                mode=retrieval_mode,
            )
            print(
                f"  RAG {idx}/{len(unique_keys)} {topic_cfg['topic_id']} "
                f"{time.perf_counter() - t0:.2f}s"
            )

    async def run_one(topic_cfg: dict[str, Any], seq: int) -> Any:
        key = (topic_cfg["topic"], topic_cfg["chapter_id"], args.retrieval_mode)
        precomputed = rag_cache.get(key)
        return await pipeline_mcq.generate_one_mcq(
            topic_cfg,
            seq,
            precomputed_rag=precomputed,
            retrieval_mode=args.retrieval_mode,
        )

    print(
        f"[pipeline] mode={args.mode} tasks={len(task_specs)} "
        f"concurrency={args.concurrency} precompute_rag={args.precompute_rag}"
    )
    t0 = time.perf_counter()
    if args.mode == "sequential":
        results = []
        for idx, (topic_cfg, seq) in enumerate(task_specs, 1):
            print(f"[pipeline:sequential] {idx}/{len(task_specs)} {topic_cfg['topic_id']} q{seq}")
            try:
                results.append(await run_one(topic_cfg, seq))
            except Exception as exc:
                print(f"  generation exception: {exc!r}")
                results.append(exc)
    else:
        sem = asyncio.Semaphore(args.concurrency)

        async def guarded(topic_cfg: dict[str, Any], seq: int) -> Any:
            async with sem:
                try:
                    return await run_one(topic_cfg, seq)
                except Exception as exc:
                    print(f"  generation exception: {exc!r}")
                    return exc

        results = await asyncio.gather(
            *[guarded(topic_cfg, seq) for topic_cfg, seq in task_specs],
            return_exceptions=True,
        )
    wall_time = time.perf_counter() - t0

    accepted = [r for r in results if isinstance(r, dict) and r]
    failed = len(task_specs) - len(accepted)
    run = now_id()
    out_jsonl = results_dir / f"pipeline_{args.mode}_{run}.jsonl"
    for mcq in accepted:
        append_jsonl(out_jsonl, mcq)

    summary = {
        "run_id": run,
        "engine": "project_pipeline",
        "label": args.label,
        "mode": args.mode,
        "model": args.model,
        "target_mcqs": len(task_specs),
        "accepted": len(accepted),
        "failed": failed,
        "concurrency": args.concurrency if args.mode == "async" else 1,
        "precompute_rag": args.precompute_rag,
        "retrieval_mode": args.retrieval_mode,
        "wall_time_s": round(wall_time, 4),
        "mcq_per_min": round((len(accepted) / wall_time) * 60, 4)
        if wall_time and accepted
        else 0,
        "output_file": str(out_jsonl.relative_to(PROJECT_ROOT)),
    }
    append_csv(results_dir / "pipeline_benchmark.csv", summary)
    print_summary(summary)
    return summary


def load_pipeline_topics(args: argparse.Namespace, pipeline_mcq: Any) -> list[dict[str, Any]]:
    if args.topics_json:
        topics = json.loads(Path(args.topics_json).read_text(encoding="utf-8"))
    else:
        topics = list(getattr(pipeline_mcq, "TOPICS"))
    topics = topics[: args.topic_limit] if args.topic_limit else topics
    normalized = []
    for idx, topic in enumerate(topics):
        item = dict(topic)
        if args.questions_per_topic is not None:
            item["n"] = args.questions_per_topic
        item.setdefault("topic_id", f"topic_{idx:02d}")
        item.setdefault("difficulty", "G2")
        normalized.append(item)
    return normalized


def cmd_direct(args: argparse.Namespace) -> dict[str, Any]:
    results_dir = ensure_dir(Path(args.results_dir))
    run = now_id()
    print(
        "[direct] Loading model with Transformers. This is the true no-vLLM baseline "
        "and may fail if VRAM is insufficient."
    )
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:
        summary = direct_failure_summary(args, run, f"import_error: {exc!r}")
        append_csv(results_dir / "direct_benchmark.csv", summary)
        print_summary(summary)
        return summary

    dtype = torch.float16 if args.dtype == "float16" else torch.bfloat16
    t_load = time.perf_counter()
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            args.direct_model_path,
            trust_remote_code=True,
        )
        model_kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "trust_remote_code": True,
        }
        if args.device_map:
            model_kwargs["device_map"] = args.device_map
        model = AutoModelForCausalLM.from_pretrained(args.direct_model_path, **model_kwargs)
        if not args.device_map:
            model = model.to(args.device)
        model.eval()
    except Exception as exc:
        summary = direct_failure_summary(
            args,
            run,
            "load_error: " + repr(exc) + "\n" + traceback.format_exc(limit=3),
        )
        append_csv(results_dir / "direct_benchmark.csv", summary)
        print_summary(summary)
        return summary
    load_time = time.perf_counter() - t_load

    def encode_prompt(prompt: str) -> Any:
        messages = [
            {"role": "system", "content": MCQ_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        if hasattr(tokenizer, "apply_chat_template"):
            return tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
            )
        text = MCQ_SYSTEM_PROMPT + "\n\n" + prompt
        return tokenizer(text, return_tensors="pt").input_ids

    latencies: list[float] = []
    output_tokens = 0
    errors = 0
    per_request = results_dir / f"direct_requests_{run}.jsonl"

    # Warmup.
    for i in range(args.warmup):
        try:
            input_ids = encode_prompt(build_prompt("mcq", -1000 - i)).to(model.device)
            with torch.inference_mode():
                _ = model.generate(
                    input_ids,
                    max_new_tokens=min(args.max_tokens, 64),
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
        except Exception:
            break

    wall_start = time.perf_counter()
    for i in range(args.num_requests):
        prompt = build_prompt("mcq", i)
        t0 = time.perf_counter()
        try:
            input_ids = encode_prompt(prompt).to(model.device)
            with torch.inference_mode():
                out = model.generate(
                    input_ids,
                    max_new_tokens=args.max_tokens,
                    do_sample=args.temperature > 0,
                    temperature=args.temperature if args.temperature > 0 else None,
                    pad_token_id=tokenizer.eos_token_id,
                )
            latency = time.perf_counter() - t0
            generated = out[0][input_ids.shape[-1] :]
            text = tokenizer.decode(generated, skip_special_tokens=True)
            latencies.append(latency)
            output_tokens += int(generated.shape[-1])
            append_jsonl(
                per_request,
                {
                    "request_id": i,
                    "ok": True,
                    "latency_s": round(latency, 4),
                    "completion_tokens": int(generated.shape[-1]),
                    "output_preview": text[:240],
                },
            )
        except Exception as exc:
            errors += 1
            append_jsonl(
                per_request,
                {"request_id": i, "ok": False, "error": repr(exc)},
            )
    wall_time = time.perf_counter() - wall_start

    summary = {
        "run_id": run,
        "engine": "transformers_direct_no_vllm",
        "label": args.label,
        "model_path": args.direct_model_path,
        "device": args.device,
        "device_map": args.device_map or "",
        "num_requests": args.num_requests,
        "success": len(latencies),
        "failed": errors,
        "concurrency": 1,
        "max_tokens": args.max_tokens,
        "load_time_s": round(load_time, 4),
        "wall_time_s": round(wall_time, 4),
        "requests_per_s": round(len(latencies) / wall_time, 4) if wall_time else 0,
        "completion_tokens": output_tokens,
        "completion_tokens_per_s": round(output_tokens / wall_time, 4)
        if wall_time
        else 0,
        "latency_avg_s": round(safe_mean(latencies), 4),
        "latency_p50_s": round(percentile(latencies, 50), 4),
        "latency_p95_s": round(percentile(latencies, 95), 4),
        "latency_max_s": round(max(latencies), 4) if latencies else 0,
        "per_request_file": str(per_request.relative_to(PROJECT_ROOT)),
        "error": "",
    }
    append_csv(results_dir / "direct_benchmark.csv", summary)
    print_summary(summary)
    return summary


def direct_failure_summary(args: argparse.Namespace, run: str, error: str) -> dict[str, Any]:
    return {
        "run_id": run,
        "engine": "transformers_direct_no_vllm",
        "label": args.label,
        "model_path": args.direct_model_path,
        "device": args.device,
        "device_map": args.device_map or "",
        "num_requests": args.num_requests,
        "success": 0,
        "failed": args.num_requests,
        "concurrency": 1,
        "max_tokens": args.max_tokens,
        "load_time_s": 0,
        "wall_time_s": 0,
        "requests_per_s": 0,
        "completion_tokens": 0,
        "completion_tokens_per_s": 0,
        "latency_avg_s": 0,
        "latency_p50_s": 0,
        "latency_p95_s": 0,
        "latency_max_s": 0,
        "per_request_file": "",
        "error": error[:500],
    }


def cmd_official(args: argparse.Namespace) -> None:
    results_dir = ensure_dir(Path(args.results_dir))
    run = now_id()
    cmd = [
        "vllm",
        "bench",
        "serve",
        "--model",
        args.model,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--random-input-len",
        str(args.random_input_len),
        "--random-output-len",
        str(args.random_output_len),
        "--num-prompts",
        str(args.num_prompts),
    ]
    print("[official] " + " ".join(cmd))
    output = run_cmd(cmd, timeout=args.timeout)
    out_file = results_dir / f"official_vllm_bench_{run}.txt"
    write_text(out_file, output)
    print(f"Saved: {out_file}")


def make_markdown_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    if not rows:
        return "_No results yet._\n"
    lines = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join(["---"] * len(columns)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines) + "\n"


def cmd_summary(args: argparse.Namespace) -> None:
    results_dir = ensure_dir(Path(args.results_dir))
    evidence_path = results_dir / "evidence_summary.json"
    evidence = {}
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    llm_rows = load_csv(results_dir / "llm_benchmark.csv")
    prefix_rows = load_csv(results_dir / "prefix_benchmark.csv")
    pipeline_rows = load_csv(results_dir / "pipeline_benchmark.csv")
    direct_rows = load_csv(results_dir / "direct_benchmark.csv")

    md = []
    md.append("# vLLM Demo Results\n")
    md.append("## Environment\n")
    md.append(f"- Generated at: {dt.datetime.now().isoformat()}\n")
    md.append(f"- Project: `{PROJECT_ROOT}`\n")
    md.append(f"- Base URL: `{args.base_url}`\n")
    md.append(f"- Served model name: `{args.model}`\n")
    md.append(f"- Evidence env file: `results/vllm_demo/env.txt`\n")

    md.append("\n## Experiment 1: Proof vLLM Is Used\n")
    if evidence:
        md.append(f"- `/health`: {'pass' if evidence.get('health_ok') else 'fail'}\n")
        md.append(f"- `/v1/models`: {'pass' if evidence.get('models_ok') else 'fail'}\n")
        md.append(f"- `/metrics`: {'pass' if evidence.get('metrics_ok') else 'fail'}\n")
        md.append(f"- vLLM log copied: {'yes' if evidence.get('vllm_log_copied') else 'no'}\n")
    else:
        md.append("_Run `python bench_vllm_demo_mcqgen.py evidence` first._\n")

    md.append("\n## Experiment 2: LLM-Only Concurrency Benchmark\n")
    md.append(
        make_markdown_table(
            llm_rows,
            [
                "label",
                "prompt_kind",
                "concurrency",
                "num_requests",
                "success",
                "failed",
                "wall_time_s",
                "requests_per_s",
                "completion_tokens_per_s",
                "latency_p50_s",
                "latency_p95_s",
            ],
        )
    )

    md.append("\n## Experiment 3: Full Pipeline Benchmark\n")
    md.append(
        make_markdown_table(
            pipeline_rows,
            [
                "label",
                "mode",
                "target_mcqs",
                "accepted",
                "failed",
                "concurrency",
                "wall_time_s",
                "mcq_per_min",
            ],
        )
    )
    speedup_note = compute_pipeline_speedup_note(pipeline_rows)
    if speedup_note:
        md.append("\n" + speedup_note + "\n")

    md.append("\n## Experiment 4/5: Prefix Cache / Config Ablation Workload\n")
    md.append(
        make_markdown_table(
            prefix_rows,
            [
                "label",
                "concurrency",
                "num_requests",
                "success",
                "wall_time_s",
                "requests_per_s",
                "completion_tokens_per_s",
                "latency_p95_s",
            ],
        )
    )
    md.append(
        "\nNote: use different `--label` values such as `max_num_seqs_1`, "
        "`max_num_seqs_4`, `prefix_off`, `prefix_on` after restarting vLLM with "
        "the corresponding server config.\n"
    )

    md.append("\n## Optional True No-vLLM Baseline: Direct Transformers\n")
    md.append(
        make_markdown_table(
            direct_rows,
            [
                "label",
                "engine",
                "success",
                "failed",
                "wall_time_s",
                "requests_per_s",
                "completion_tokens_per_s",
                "latency_p95_s",
                "error",
            ],
        )
    )

    md.append("\n## Interpretation Template\n")
    md.append(
        "- vLLM does not improve model quality by itself; it improves serving efficiency.\n"
        "- The strongest evidence is higher requests/s or tokens/s under concurrency while accepted MCQs stay comparable.\n"
        "- If full-pipeline speedup is smaller than LLM-only speedup, retrieval/reranker/IO is likely part of the bottleneck.\n"
        "- If direct Transformers baseline fails to load, report it as an environment/VRAM limitation and keep the no-batching vLLM baseline.\n"
    )

    out = results_dir / "summary.md"
    write_text(out, "".join(md))
    print(f"Saved summary: {out}")


def compute_pipeline_speedup_note(rows: list[dict[str, str]]) -> str:
    sequential = None
    async_row = None
    for row in reversed(rows):
        if row.get("mode") == "sequential" and sequential is None:
            sequential = row
        if row.get("mode") == "async" and async_row is None:
            async_row = row
    if not sequential or not async_row:
        return ""
    try:
        seq_time = float(sequential["wall_time_s"])
        async_time = float(async_row["wall_time_s"])
        if seq_time > 0 and async_time > 0:
            return (
                f"Pipeline speedup estimate: `{seq_time / async_time:.2f}x` "
                f"(sequential {seq_time:.1f}s / async {async_time:.1f}s)."
            )
    except Exception:
        return ""
    return ""


async def cmd_all(args: argparse.Namespace) -> None:
    collect_evidence(args)
    await cmd_llm_sweep(args)
    if args.include_prefix:
        prefix_args = argparse.Namespace(**vars(args))
        prefix_args.prompt_kind = "prefix"
        prefix_args.concurrency = max(parse_int_list(args.concurrency_list))
        await cmd_prefix(prefix_args)
    if args.include_pipeline:
        seq_args = argparse.Namespace(**vars(args))
        seq_args.mode = "sequential"
        await cmd_pipeline(seq_args)
        async_args = argparse.Namespace(**vars(args))
        async_args.mode = "async"
        async_args.concurrency = max(parse_int_list(args.concurrency_list))
        await cmd_pipeline(async_args)
    if args.include_direct:
        cmd_direct(args)
    cmd_summary(args)


def parse_int_list(value: str) -> list[int]:
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(max(1, int(part)))
    if not out:
        raise argparse.ArgumentTypeError("empty integer list")
    return out


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--label", default="current")
    parser.add_argument("--timeout", type=int, default=30)


def add_openai_bench_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--num-requests", type=int, default=40)
    parser.add_argument("--concurrency-list", default="1,2,4")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--prompt-kind", choices=["mcq", "prefix"], default="mcq")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MCQGen vLLM evidence and benchmark runner."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_evidence = sub.add_parser("evidence", help="Collect vLLM health/model/metrics/env evidence.")
    add_common_args(p_evidence)

    p_llm = sub.add_parser("llm-sweep", help="Run vLLM OpenAI API concurrency sweep.")
    add_common_args(p_llm)
    add_openai_bench_args(p_llm)

    p_prefix = sub.add_parser("prefix", help="Run shared-prefix workload for prefix-cache demos.")
    add_common_args(p_prefix)
    add_openai_bench_args(p_prefix)

    p_pipeline = sub.add_parser("pipeline", help="Run project pipeline sequential or async.")
    add_common_args(p_pipeline)
    p_pipeline.add_argument("--mode", choices=["sequential", "async"], default="async")
    p_pipeline.add_argument("--concurrency", type=int, default=2)
    p_pipeline.add_argument("--topic-limit", type=int, default=2)
    p_pipeline.add_argument("--questions-per-topic", type=int, default=1)
    p_pipeline.add_argument("--topics-json", default="")
    p_pipeline.add_argument("--retrieval-mode", choices=["fast", "auto", "quality"], default="auto")
    p_pipeline.add_argument("--precompute-rag", action=argparse.BooleanOptionalAction, default=True)

    p_direct = sub.add_parser("direct", help="Optional true no-vLLM Transformers baseline.")
    add_common_args(p_direct)
    p_direct.add_argument("--direct-model-path", default=str(REPO_ROOT / "models" / "Qwen2.5-7B-Instruct"))
    p_direct.add_argument("--num-requests", type=int, default=5)
    p_direct.add_argument("--max-tokens", type=int, default=256)
    p_direct.add_argument("--temperature", type=float, default=0.0)
    p_direct.add_argument("--warmup", type=int, default=1)
    p_direct.add_argument("--device", default="cuda:0")
    p_direct.add_argument("--device-map", default="auto")
    p_direct.add_argument("--dtype", choices=["float16", "bfloat16"], default="float16")

    p_official = sub.add_parser("official", help="Run official vLLM serving benchmark if installed.")
    add_common_args(p_official)
    p_official.add_argument("--host", default="localhost")
    p_official.add_argument("--port", type=int, default=8000)
    p_official.add_argument("--random-input-len", type=int, default=512)
    p_official.add_argument("--random-output-len", type=int, default=256)
    p_official.add_argument("--num-prompts", type=int, default=40)

    p_summary = sub.add_parser("summary", help="Generate results/vllm_demo/summary.md.")
    add_common_args(p_summary)

    p_all = sub.add_parser("all", help="Run evidence + LLM sweep + summary; optional heavy parts via flags.")
    add_common_args(p_all)
    add_openai_bench_args(p_all)
    p_all.add_argument("--include-prefix", action="store_true")
    p_all.add_argument("--include-pipeline", action="store_true")
    p_all.add_argument("--include-direct", action="store_true")
    p_all.add_argument("--mode", choices=["sequential", "async"], default="async")
    p_all.add_argument("--topic-limit", type=int, default=2)
    p_all.add_argument("--questions-per-topic", type=int, default=1)
    p_all.add_argument("--topics-json", default="")
    p_all.add_argument("--retrieval-mode", choices=["fast", "auto", "quality"], default="auto")
    p_all.add_argument("--precompute-rag", action=argparse.BooleanOptionalAction, default=True)
    p_all.add_argument("--direct-model-path", default=str(REPO_ROOT / "models" / "Qwen2.5-7B-Instruct"))
    p_all.add_argument("--device", default="cuda:0")
    p_all.add_argument("--device-map", default="auto")
    p_all.add_argument("--dtype", choices=["float16", "bfloat16"], default="float16")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "evidence":
        collect_evidence(args)
    elif args.command == "llm-sweep":
        asyncio.run(cmd_llm_sweep(args))
    elif args.command == "prefix":
        asyncio.run(cmd_prefix(args))
    elif args.command == "pipeline":
        asyncio.run(cmd_pipeline(args))
    elif args.command == "direct":
        cmd_direct(args)
    elif args.command == "official":
        cmd_official(args)
    elif args.command == "summary":
        cmd_summary(args)
    elif args.command == "all":
        asyncio.run(cmd_all(args))
    else:
        parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
