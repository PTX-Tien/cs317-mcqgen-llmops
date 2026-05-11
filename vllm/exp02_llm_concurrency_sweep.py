#!/usr/bin/env python3
"""
Experiment 02: LLM-only vLLM concurrency sweep for MCQGen.

This experiment isolates vLLM serving performance from retrieval, reranking,
Celery, database IO, and the full MCQ pipeline. It sends OpenAI-compatible chat
completion requests directly to the running vLLM server and compares throughput
and latency across concurrency levels.

Typical run:
  python exp02_llm_concurrency_sweep.py \
    --num-requests 100 \
    --concurrency-list 1,2,4,8,100 \
    --max-tokens 512 \
    --label vllm_4gpu_load
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import html
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VLLM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VLLM_DIR.parent
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp02_llm_concurrency_sweep"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")

SYSTEM_PROMPT = (
    "Bạn là giảng viên đại học dạy môn CS116 - Lập trình Python cho Máy học. "
    "Bạn đang biên soạn câu hỏi trắc nghiệm tiếng Việt cho sinh viên đại học. "
    "Luôn trả về JSON hợp lệ, không thêm giải thích ngoài JSON."
)

MCQ_PROMPT_TEMPLATE = """Tạo 1 câu MCQ tiếng Việt về topic "{topic}", độ khó G2.

[YÊU CẦU]
- Câu hỏi kiểm tra hiểu khái niệm hoặc áp dụng, không hỏi định nghĩa thuần túy.
- Có đúng 4 options A/B/C/D.
- Có đúng 1 đáp án đúng.
- Distractors phải plausible nhưng sai rõ ràng về mặt kỹ thuật.
- Văn phong phù hợp đề thi đại học.

[OUTPUT JSON ONLY]
{{
  "question_text": "...",
  "question_type": "single_correct",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correct_answers": ["A"],
  "correct_rationale": "...",
  "topic": "{topic}",
  "difficulty_label": "G2"
}}
"""

TOPICS = [
    "Pandas DataFrame filtering",
    "missing value imputation",
    "train/test split",
    "feature scaling",
    "classification metrics",
    "overfitting and regularization",
    "decision trees",
    "k-means clustering",
]


@dataclass
class RequestResult:
    request_id: int
    concurrency: int
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
            "concurrency": self.concurrency,
            "ok": self.ok,
            "latency_s": round(self.latency_s, 4),
            "ttft_s": round(self.ttft_s, 4),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "output_chars": self.output_chars,
            "error": self.error,
            "output_preview": self.output_preview,
        }


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def server_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


def parse_int_list(value: str) -> list[int]:
    items = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        parsed = int(raw)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("Concurrency values must be positive")
        items.append(parsed)
    if not items:
        raise argparse.ArgumentTypeError("At least one concurrency value is required")
    return items


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if p == 50:
        return float(statistics.median(ordered))
    idx = max(0, min(len(ordered) - 1, math.ceil((p / 100) * len(ordered)) - 1))
    return float(ordered[idx])


def safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


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


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_prompt(request_id: int) -> str:
    topic = TOPICS[request_id % len(TOPICS)]
    return MCQ_PROMPT_TEMPLATE.format(topic=topic)


async def one_call(
    client: Any,
    *,
    model: str,
    request_id: int,
    concurrency: int,
    max_tokens: int,
    temperature: float,
    stream: bool,
    request_timeout: float,
) -> RequestResult:
    t0 = time.perf_counter()
    try:
        if stream:
            first_token_at = 0.0
            chunks: list[str] = []
            completion_chunks = 0
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(request_id)},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=request_timeout,
                stream=True,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            async for chunk in response:
                if not chunk.choices:
                    continue
                text = chunk.choices[0].delta.content or ""
                if text and not first_token_at:
                    first_token_at = time.perf_counter()
                if text:
                    chunks.append(text)
                    completion_chunks += 1
            output = "".join(chunks)
            return RequestResult(
                request_id=request_id,
                concurrency=concurrency,
                ok=True,
                latency_s=time.perf_counter() - t0,
                ttft_s=(first_token_at - t0) if first_token_at else 0.0,
                prompt_tokens=0,
                completion_tokens=completion_chunks,
                total_tokens=completion_chunks,
                output_chars=len(output),
                output_preview=output[:260],
            )

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(request_id)},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=request_timeout,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        usage = getattr(response, "usage", None)
        output = response.choices[0].message.content or ""
        return RequestResult(
            request_id=request_id,
            concurrency=concurrency,
            ok=True,
            latency_s=time.perf_counter() - t0,
            ttft_s=0.0,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            output_chars=len(output),
            output_preview=output[:260],
        )
    except Exception as exc:
        return RequestResult(
            request_id=request_id,
            concurrency=concurrency,
            ok=False,
            latency_s=time.perf_counter() - t0,
            ttft_s=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            output_chars=0,
            error=repr(exc),
        )


def filter_metrics(metrics: str) -> str:
    keywords = ("request", "token", "cache", "queue", "running", "waiting", "prefix")
    kept = []
    for line in metrics.splitlines():
        lower = line.lower()
        if "vllm" in lower and any(keyword in lower for keyword in keywords):
            kept.append(line)
    return "\n".join(kept[:400]) + ("\n" if kept else "")


async def warmup(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    stream: bool,
    warmup_requests: int,
    request_timeout: float,
) -> None:
    if warmup_requests <= 0:
        return
    print(f"[warmup] requests={warmup_requests}")
    for i in range(warmup_requests):
        result = await one_call(
            client,
            model=model,
            request_id=-1000 - i,
            concurrency=1,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            request_timeout=request_timeout,
        )
        if not result.ok:
            print(f"  warmup failed: {result.error}")


async def run_one_concurrency(args: argparse.Namespace, concurrency: int) -> dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency `openai`. Activate the project environment first."
        ) from exc

    results_dir = ensure_dir(Path(args.results_dir))
    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key)
    run_id = args.run_id

    await warmup(
        client,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        stream=args.stream,
        warmup_requests=args.warmup,
        request_timeout=args.request_timeout,
    )

    root = server_root(args.base_url)
    before = http_get(f"{root}/metrics", timeout=args.http_timeout)
    if before["ok"]:
        write_text(
            results_dir / f"metrics_before_{args.label}_c{concurrency}_{run_id}.txt",
            before["body"],
        )

    sem = asyncio.Semaphore(concurrency)

    async def guarded(i: int) -> RequestResult:
        async with sem:
            return await one_call(
                client,
                model=args.model,
                request_id=i,
                concurrency=concurrency,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                stream=args.stream,
                request_timeout=args.request_timeout,
            )

    print(
        f"\n[exp02] label={args.label} requests={args.num_requests} "
        f"concurrency={concurrency} max_tokens={args.max_tokens}"
    )
    wall_start = time.perf_counter()
    results = await asyncio.gather(*[guarded(i) for i in range(args.num_requests)])
    wall_time = time.perf_counter() - wall_start

    after = http_get(f"{root}/metrics", timeout=args.http_timeout)
    if after["ok"]:
        write_text(
            results_dir / f"metrics_after_{args.label}_c{concurrency}_{run_id}.txt",
            after["body"],
        )
        write_text(
            results_dir / f"metrics_filtered_after_{args.label}_c{concurrency}_{run_id}.txt",
            filter_metrics(after["body"]),
        )

    per_request_path = (
        results_dir / f"requests_{args.label}_c{concurrency}_{run_id}.jsonl"
    )
    for result in results:
        append_jsonl(per_request_path, result.as_dict())

    success = [item for item in results if item.ok]
    failed = [item for item in results if not item.ok]
    latencies = [item.latency_s for item in success]
    ttfts = [item.ttft_s for item in success if item.ttft_s > 0]
    prompt_tokens = sum(item.prompt_tokens for item in success)
    completion_tokens = sum(item.completion_tokens for item in success)
    total_tokens = sum(item.total_tokens for item in success)

    summary = {
        "run_id": run_id,
        "experiment": "exp02_llm_concurrency_sweep",
        "label": args.label,
        "base_url": args.base_url,
        "model": args.model,
        "num_requests": args.num_requests,
        "success": len(success),
        "failed": len(failed),
        "concurrency": concurrency,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "stream": args.stream,
        "wall_time_s": round(wall_time, 4),
        "requests_per_s": round(len(success) / wall_time, 4) if wall_time else 0,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "completion_tokens_per_s": round(completion_tokens / wall_time, 4)
        if wall_time
        else 0,
        "total_tokens_per_s": round(total_tokens / wall_time, 4) if wall_time else 0,
        "latency_avg_s": round(safe_mean(latencies), 4),
        "latency_p50_s": round(percentile(latencies, 50), 4),
        "latency_p95_s": round(percentile(latencies, 95), 4),
        "latency_p99_s": round(percentile(latencies, 99), 4),
        "latency_max_s": round(max(latencies), 4) if latencies else 0,
        "ttft_avg_s": round(safe_mean(ttfts), 4),
        "ttft_p95_s": round(percentile(ttfts, 95), 4),
        "per_request_file": rel(per_request_path),
    }
    append_csv(results_dir / "llm_concurrency_sweep.csv", summary)
    print_summary(summary)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "label",
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
        "latency_p99_s",
    ]:
        print(f"{key}: {summary.get(key)}")


def collect_preflight(args: argparse.Namespace) -> None:
    results_dir = ensure_dir(Path(args.results_dir))
    root = server_root(args.base_url)
    health = http_get(f"{root}/health", timeout=args.http_timeout)
    models = http_get(f"{args.base_url.rstrip('/')}/models", timeout=args.http_timeout)
    metrics = http_get(f"{root}/metrics", timeout=args.http_timeout)

    write_json(results_dir / f"preflight_{args.label}_{args.run_id}.json", {
        "run_id": args.run_id,
        "base_url": args.base_url,
        "model": args.model,
        "health_ok": health["ok"],
        "models_ok": models["ok"],
        "metrics_ok": metrics["ok"],
        "health_status": health["status"],
        "models_status": models["status"],
        "metrics_status": metrics["status"],
        "health_error": health["error"],
        "models_error": models["error"],
        "metrics_error": metrics["error"],
    })
    if models["ok"]:
        write_text(results_dir / f"models_{args.label}_{args.run_id}.json", models["body"])
    if metrics["ok"]:
        write_text(results_dir / f"metrics_initial_{args.label}_{args.run_id}.txt", metrics["body"])
        write_text(
            results_dir / f"metrics_initial_filtered_{args.label}_{args.run_id}.txt",
            filter_metrics(metrics["body"]),
        )

    env_text = [
        f"DATE={dt.datetime.now().isoformat()}",
        f"PROJECT_ROOT={PROJECT_ROOT}",
        f"VLLM_DIR={VLLM_DIR}",
        f"VLLM_URL={args.base_url}",
        f"VLLM_MODEL={args.model}",
        f"CUDA_VISIBLE_DEVICES={os.getenv('CUDA_VISIBLE_DEVICES', '')}",
        "\n## python",
        sys.version,
        "\n## nvidia-smi",
        run_cmd(["nvidia-smi"], timeout=20),
        "\n## pip show vllm",
        run_cmd([sys.executable, "-m", "pip", "show", "vllm"], timeout=20),
        "\n## pip show openai",
        run_cmd([sys.executable, "-m", "pip", "show", "openai"], timeout=20),
    ]
    write_text(results_dir / f"env_{args.label}_{args.run_id}.txt", "\n".join(env_text))

    if not health["ok"] or not models["ok"]:
        raise SystemExit(
            "vLLM server is not ready. Check http://localhost:8000/health and /v1/models."
        )


def numeric(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0)
    except ValueError:
        return 0.0


def load_rows_for_run(results_dir: Path, run_id: str, label: str) -> list[dict[str, str]]:
    rows = [
        row
        for row in load_csv(results_dir / "llm_concurrency_sweep.csv")
        if row.get("run_id") == run_id and row.get("label") == label
    ]
    return sorted(rows, key=lambda row: int(float(row.get("concurrency", "0") or 0)))


def render_svg(rows: list[dict[str, str]], output_path: Path, title: str) -> None:
    ensure_dir(output_path.parent)
    width = 1440
    height = 920
    bg = "#f8fafc"
    panel = "#ffffff"
    text = "#0f172a"
    muted = "#64748b"
    grid = "#dbe4f0"
    colors = {
        "throughput": "#2563eb",
        "tokens": "#059669",
        "wall": "#f97316",
        "latency": "#dc2626",
    }

    def chart_bar(
        x: int,
        y: int,
        w: int,
        h: int,
        metric: str,
        heading: str,
        color: str,
        suffix: str,
        lower_is_better: bool = False,
    ) -> str:
        values = [numeric(row, metric) for row in rows]
        max_v = max(values) if values else 1.0
        if max_v <= 0:
            max_v = 1.0
        gap = 22
        inner_x = x + 64
        inner_y = y + 76
        inner_w = w - 100
        inner_h = h - 130
        bar_w = max(16, (inner_w - gap * (len(rows) - 1)) / max(1, len(rows)))
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{panel}" stroke="#e2e8f0"/>',
            f'<text x="{x + 28}" y="{y + 40}" font-size="24" font-weight="700" fill="{text}">{html.escape(heading)}</text>',
            f'<line x1="{inner_x}" y1="{inner_y + inner_h}" x2="{inner_x + inner_w}" y2="{inner_y + inner_h}" stroke="{grid}"/>',
        ]
        for i in range(1, 5):
            gy = inner_y + inner_h - inner_h * i / 4
            parts.append(f'<line x1="{inner_x}" y1="{gy:.1f}" x2="{inner_x + inner_w}" y2="{gy:.1f}" stroke="{grid}" stroke-dasharray="4 8"/>')
        for i, row in enumerate(rows):
            value = numeric(row, metric)
            bar_h = inner_h * value / max_v
            bx = inner_x + i * (bar_w + gap)
            by = inner_y + inner_h - bar_h
            c = color
            if lower_is_better:
                c = "#16a34a" if value <= safe_mean(values) else color
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="8" fill="{c}"/>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 10:.1f}" text-anchor="middle" font-size="16" font-weight="700" fill="{text}">{value:.2f}{suffix}</text>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 32:.1f}" text-anchor="middle" font-size="16" fill="{muted}">c={row.get("concurrency")}</text>')
        return "\n".join(parts)

    c1 = numeric(rows[0], "requests_per_s") if rows else 0
    cmax = numeric(rows[-1], "requests_per_s") if rows else 0
    speedup = (cmax / c1) if c1 else 0
    failures = sum(int(float(row.get("failed", "0") or 0)) for row in rows)
    max_success = max((int(float(row.get("success", "0") or 0)) for row in rows), default=0)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="58" y="72" font-size="36" font-weight="800" fill="{text}">{html.escape(title)}</text>',
        f'<text x="58" y="108" font-size="18" fill="{muted}">LLM-only benchmark qua vLLM OpenAI API. Higher throughput is better; lower wall time and p95 latency are better.</text>',
        f'<rect x="1072" y="44" width="310" height="92" rx="18" fill="#e0f2fe" stroke="#bae6fd"/>',
        f'<text x="1100" y="82" font-size="18" font-weight="700" fill="#075985">Max throughput speedup</text>',
        f'<text x="1100" y="120" font-size="32" font-weight="800" fill="#0369a1">{speedup:.2f}x</text>',
        f'<text x="1250" y="120" font-size="14" fill="#075985">failures: {failures} | success/run: {max_success}</text>',
        chart_bar(58, 170, 640, 320, "requests_per_s", "Requests per second", colors["throughput"], ""),
        chart_bar(742, 170, 640, 320, "completion_tokens_per_s", "Output tokens per second", colors["tokens"], ""),
        chart_bar(58, 540, 640, 320, "wall_time_s", "Wall time", colors["wall"], "s", True),
        chart_bar(742, 540, 640, 320, "latency_p95_s", "p95 latency", colors["latency"], "s", True),
        "</svg>",
    ]
    write_text(output_path, "\n".join(svg))


def render_png_with_matplotlib(rows: list[dict[str, str]], output_path: Path, title: str) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False

    ensure_dir(output_path.parent)
    concurrencies = [f"c={row.get('concurrency')}" for row in rows]
    metrics = [
        ("requests_per_s", "Requests/s", "#2563eb"),
        ("completion_tokens_per_s", "Output tokens/s", "#059669"),
        ("wall_time_s", "Wall time (s)", "#f97316"),
        ("latency_p95_s", "p95 latency (s)", "#dc2626"),
    ]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    fig.patch.set_facecolor("#f8fafc")
    fig.suptitle(title, fontsize=22, fontweight="bold", color="#0f172a", y=0.98)

    for ax, (metric, heading, color) in zip(axes.flatten(), metrics):
        values = [numeric(row, metric) for row in rows]
        bars = ax.bar(concurrencies, values, color=color, alpha=0.92, width=0.62)
        ax.set_title(heading, fontsize=14, fontweight="bold", color="#0f172a")
        ax.tick_params(axis="x", labelrotation=0)
        ax.grid(axis="y", color="#dbe4f0", linestyle="--", linewidth=0.9)
        ax.set_facecolor("#ffffff")
        for spine in ax.spines.values():
            spine.set_color("#e2e8f0")
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:.2f}",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
                color="#0f172a",
            )

    plt.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output_path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True


def write_report(rows: list[dict[str, str]], args: argparse.Namespace, image_paths: list[Path]) -> Path:
    report_path = Path(args.results_dir) / f"report_{args.label}_{args.run_id}.md"
    baseline = numeric(rows[0], "requests_per_s") if rows else 0
    best = max((numeric(row, "requests_per_s") for row in rows), default=0)
    speedup = best / baseline if baseline else 0

    lines = [
        "# Experiment 02 - LLM-only vLLM Concurrency Sweep",
        "",
        "## Config",
        "",
        f"- Run ID: `{args.run_id}`",
        f"- Label: `{args.label}`",
        f"- Base URL: `{args.base_url}`",
        f"- Model: `{args.model}`",
        f"- Number of requests per concurrency: `{args.num_requests}`",
        f"- Concurrency list: `{args.concurrency_list}`",
        f"- Max tokens: `{args.max_tokens}`",
        f"- Stream: `{args.stream}`",
        "",
        "## Results",
        "",
        "| Concurrency | Success | Failed | Wall time (s) | Requests/s | Output tokens/s | Avg latency (s) | p95 latency (s) | p99 latency (s) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {concurrency} | {success} | {failed} | {wall_time_s} | {requests_per_s} | "
            "{completion_tokens_per_s} | {latency_avg_s} | {latency_p95_s} | {latency_p99_s} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Best requests/s speedup over concurrency=1: `{speedup:.2f}x`.",
            "- Nếu requests/s và output tokens/s tăng khi concurrency tăng, đây là bằng chứng vLLM xử lý concurrent serving tốt hơn chạy tuần tự.",
            "- Nếu p95 latency tăng mạnh ở concurrency rất cao nhưng failed vẫn thấp, hệ thống đang queue/schedule tải lớn thay vì crash.",
            "- Experiment này đo riêng LLM serving, chưa bao gồm retrieval/reranker/pipeline orchestration.",
            "",
            "## Visualizations",
            "",
        ]
    )
    for path in image_paths:
        lines.append(f"- [{path.name}]({path.name})")
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def generate_visuals_and_report(args: argparse.Namespace) -> None:
    results_dir = Path(args.results_dir)
    rows = load_rows_for_run(results_dir, args.run_id, args.label)
    if not rows:
        print("[plot] no rows found for this run; skipping visualization")
        return

    title = f"MCQGen vLLM LLM-only Load Test - {args.label}"
    svg_path = results_dir / f"concurrency_sweep_{args.label}_{args.run_id}.svg"
    png_path = results_dir / f"concurrency_sweep_{args.label}_{args.run_id}.png"

    render_svg(rows, svg_path, title)
    image_paths = [svg_path]
    if render_png_with_matplotlib(rows, png_path, title):
        image_paths.insert(0, png_path)
    report_path = write_report(rows, args, image_paths)

    print("\n[artifacts]")
    print(f"  csv:    {rel(results_dir / 'llm_concurrency_sweep.csv')}")
    print(f"  svg:    {rel(svg_path)}")
    if png_path.exists():
        print(f"  png:    {rel(png_path)}")
    print(f"  report: {rel(report_path)}")


async def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()

    collect_preflight(args)
    concurrencies = parse_int_list(args.concurrency_list)
    for concurrency in concurrencies:
        await run_one_concurrency(args, concurrency)
    generate_visuals_and_report(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 02: benchmark vLLM LLM-only concurrency for MCQGen."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--num-requests", type=int, default=100)
    parser.add_argument("--concurrency-list", default="1,2,4,8,100")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--stream", action="store_true", help="Enable streaming and TTFT measurement.")
    parser.add_argument("--request-timeout", type=float, default=900.0)
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--label", default="vllm_4gpu_load")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    if args.num_requests <= 0:
        raise SystemExit("--num-requests must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
