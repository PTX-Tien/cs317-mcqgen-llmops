#!/usr/bin/env python3
"""
Experiment 07: How to prove the "no vLLM" baseline.

This implements section 6 of vllm_demo_plan_mcqgen.md.

There are two baseline levels:

1. Baseline A - sequential / no-batching baseline:
   Same running vLLM server, same model/API, but client concurrency=1.
   This is the safest main comparison because it isolates the benefit of
   concurrent serving/batching without changing model/runtime too much.

2. Baseline B - true no-vLLM direct Transformers baseline:
   Optional. The script loads the model with HuggingFace Transformers and runs
   model.generate() sequentially. This is the strictest "no vLLM" baseline, but
   it can fail or be unfair if GPU memory/version/quantization differs.

By default, the script runs Baseline A and the comparable concurrent vLLM run.
Direct Transformers runs only when --include-direct-transformers is passed.

Outputs:
  - one SVG visualization
  - one Markdown report
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import html
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VLLM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VLLM_DIR.parent
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp07_no_vllm_baselines"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")
DEFAULT_DIRECT_MODEL = PROJECT_ROOT / "models" / "Qwen2.5-7B-Instruct"

SYSTEM_PROMPT = (
    "Bạn là giảng viên đại học dạy môn CS116 - Lập trình Python cho Máy học. "
    "Bạn đang biên soạn câu hỏi trắc nghiệm tiếng Việt cho sinh viên đại học. "
    "Chỉ trả về JSON hợp lệ."
)

PROMPT_TEMPLATE = """Tạo 1 câu MCQ tiếng Việt về topic "{topic}", độ khó G2.

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
    "Pandas missing values",
    "train test split",
    "feature scaling",
    "classification metrics",
    "overfitting and regularization",
    "decision trees",
    "k-means clustering",
    "CNN basics",
]


@dataclass
class CallResult:
    ok: bool
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    error: str = ""


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def server_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


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


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


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


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def numeric(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def build_prompt(request_id: int) -> str:
    return PROMPT_TEMPLATE.format(topic=TOPICS[request_id % len(TOPICS)])


def preflight_vllm(args: argparse.Namespace) -> None:
    if args.skip_preflight:
        return
    root = server_root(args.base_url)
    health = http_get(f"{root}/health", timeout=args.http_timeout)
    models = http_get(f"{args.base_url.rstrip('/')}/models", timeout=args.http_timeout)
    if not health["ok"] or not models["ok"]:
        raise SystemExit(
            "vLLM server is not ready. Start vLLM first or pass --skip-preflight."
        )


async def one_openai_call(
    client: Any,
    *,
    model: str,
    request_id: int,
    max_tokens: int,
    temperature: float,
    request_timeout: float,
) -> CallResult:
    t0 = time.perf_counter()
    try:
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
        return CallResult(
            ok=True,
            latency_s=time.perf_counter() - t0,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
    except Exception as exc:
        return CallResult(
            ok=False,
            latency_s=time.perf_counter() - t0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            error=repr(exc),
        )


async def run_openai_mode(
    args: argparse.Namespace,
    *,
    mode_name: str,
    concurrency: int,
) -> dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency `openai`. Activate the project environment first."
        ) from exc

    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key)
    for i in range(args.warmup):
        await one_openai_call(
            client,
            model=args.model,
            request_id=-1000 - i,
            max_tokens=min(args.max_tokens, 128),
            temperature=args.temperature,
            request_timeout=args.request_timeout,
        )

    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(i: int) -> CallResult:
        async with semaphore:
            return await one_openai_call(
                client,
                model=args.model,
                request_id=i,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                request_timeout=args.request_timeout,
            )

    print(f"\n[exp07] {mode_name} | requests={args.num_requests} concurrency={concurrency}")
    t0 = time.perf_counter()
    results = await asyncio.gather(*[guarded(i) for i in range(args.num_requests)])
    wall_time = time.perf_counter() - t0
    return summarize_results(
        label=args.label,
        mode=mode_name,
        engine="openai_compatible_vllm_server",
        model=args.model,
        num_requests=args.num_requests,
        concurrency=concurrency,
        max_tokens=args.max_tokens,
        wall_time=wall_time,
        results=results,
        note="Baseline A" if concurrency == 1 else "Concurrent vLLM comparison",
    )


def summarize_results(
    *,
    label: str,
    mode: str,
    engine: str,
    model: str,
    num_requests: int,
    concurrency: int,
    max_tokens: int,
    wall_time: float,
    results: list[CallResult],
    note: str,
) -> dict[str, Any]:
    success = [item for item in results if item.ok]
    failed = [item for item in results if not item.ok]
    latencies = [item.latency_s for item in success]
    completion_tokens = sum(item.completion_tokens for item in success)
    total_tokens = sum(item.total_tokens for item in success)
    first_error = next((item.error for item in failed if item.error), "")
    row = {
        "run_id": "",
        "timestamp": dt.datetime.now().isoformat(),
        "label": label,
        "mode": mode,
        "engine": engine,
        "model": model,
        "num_requests": num_requests,
        "success": len(success),
        "failed": len(failed),
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "wall_time_s": round(wall_time, 4),
        "requests_per_s": round(safe_div(len(success), wall_time), 4),
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "completion_tokens_per_s": round(safe_div(completion_tokens, wall_time), 4),
        "total_tokens_per_s": round(safe_div(total_tokens, wall_time), 4),
        "latency_avg_s": round(safe_mean(latencies), 4),
        "latency_p50_s": round(percentile(latencies, 50), 4),
        "latency_p95_s": round(percentile(latencies, 95), 4),
        "latency_p99_s": round(percentile(latencies, 99), 4),
        "latency_max_s": round(max(latencies), 4) if latencies else 0,
        "note": note,
        "first_error": first_error[:300],
    }
    print_summary(row)
    return row


def print_summary(row: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "mode",
        "engine",
        "success",
        "failed",
        "concurrency",
        "wall_time_s",
        "requests_per_s",
        "completion_tokens_per_s",
        "latency_avg_s",
        "latency_p95_s",
    ]:
        print(f"{key}: {row.get(key)}")


def encode_chat(tokenizer: Any, prompt: str) -> Any:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        )
    text = SYSTEM_PROMPT + "\n\n" + prompt
    return tokenizer(text, return_tensors="pt").input_ids


def run_direct_transformers(args: argparse.Namespace) -> dict[str, Any]:
    print(
        "\n[exp07] direct_transformers_no_vllm | "
        "loading model with HuggingFace Transformers"
    )
    t_load = time.perf_counter()
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:
        return direct_failure(args, "import_error", repr(exc))

    try:
        dtype = torch.float16 if args.direct_dtype == "float16" else torch.bfloat16
        tokenizer = AutoTokenizer.from_pretrained(
            args.direct_model_path,
            trust_remote_code=True,
        )
        model_kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "trust_remote_code": True,
        }
        if args.direct_device_map:
            model_kwargs["device_map"] = args.direct_device_map
        model = AutoModelForCausalLM.from_pretrained(
            args.direct_model_path,
            **model_kwargs,
        )
        if not args.direct_device_map:
            model = model.to(args.direct_device)
        model.eval()
        load_time = time.perf_counter() - t_load
    except Exception as exc:
        return direct_failure(args, "load_error", repr(exc))

    results: list[CallResult] = []

    def model_device() -> Any:
        if hasattr(model, "device"):
            return model.device
        return next(model.parameters()).device

    for i in range(args.direct_warmup):
        try:
            input_ids = encode_chat(tokenizer, build_prompt(-1000 - i)).to(model_device())
            with torch.inference_mode():
                _ = model.generate(
                    input_ids,
                    max_new_tokens=min(args.direct_max_tokens, 64),
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
        except Exception:
            break

    wall_start = time.perf_counter()
    for i in range(args.direct_num_requests):
        t0 = time.perf_counter()
        try:
            input_ids = encode_chat(tokenizer, build_prompt(i)).to(model_device())
            with torch.inference_mode():
                output = model.generate(
                    input_ids,
                    max_new_tokens=args.direct_max_tokens,
                    do_sample=args.temperature > 0,
                    temperature=args.temperature if args.temperature > 0 else None,
                    pad_token_id=tokenizer.eos_token_id,
                )
            generated = output[0][input_ids.shape[-1] :]
            results.append(
                CallResult(
                    ok=True,
                    latency_s=time.perf_counter() - t0,
                    prompt_tokens=int(input_ids.shape[-1]),
                    completion_tokens=int(generated.shape[-1]),
                    total_tokens=int(input_ids.shape[-1] + generated.shape[-1]),
                )
            )
        except Exception as exc:
            results.append(
                CallResult(
                    ok=False,
                    latency_s=time.perf_counter() - t0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    error=repr(exc),
                )
            )
    wall_time = time.perf_counter() - wall_start
    row = summarize_results(
        label=args.label,
        mode="direct_transformers_no_vllm",
        engine="huggingface_transformers_direct",
        model=args.direct_model_path,
        num_requests=args.direct_num_requests,
        concurrency=1,
        max_tokens=args.direct_max_tokens,
        wall_time=wall_time,
        results=results,
        note=f"Baseline B, model_load_time_s={load_time:.2f}",
    )
    row["model_load_time_s"] = round(load_time, 4)
    return row


def direct_failure(args: argparse.Namespace, stage: str, error: str) -> dict[str, Any]:
    row = {
        "run_id": "",
        "timestamp": dt.datetime.now().isoformat(),
        "label": args.label,
        "mode": "direct_transformers_no_vllm",
        "engine": "huggingface_transformers_direct",
        "model": args.direct_model_path,
        "num_requests": args.direct_num_requests,
        "success": 0,
        "failed": args.direct_num_requests,
        "concurrency": 1,
        "max_tokens": args.direct_max_tokens,
        "wall_time_s": 0,
        "requests_per_s": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "completion_tokens_per_s": 0,
        "total_tokens_per_s": 0,
        "latency_avg_s": 0,
        "latency_p50_s": 0,
        "latency_p95_s": 0,
        "latency_p99_s": 0,
        "latency_max_s": 0,
        "note": f"Baseline B failed at {stage}. This is an expected possible limitation.",
        "first_error": error[:500],
        "model_load_time_s": 0,
    }
    print_summary(row)
    return row


def render_svg(rows: list[dict[str, Any]], output_path: Path, title: str) -> None:
    ensure_dir(output_path.parent)
    width = 1440
    height = 900
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

    seq = next((row for row in rows if row.get("mode") == "sequential_no_batching_vllm"), None)
    concurrent = next((row for row in rows if row.get("mode") == "concurrent_vllm"), None)
    speedup = safe_div(numeric(concurrent or {}, "requests_per_s"), numeric(seq or {}, "requests_per_s"))

    def short_label(row: dict[str, Any]) -> str:
        labels = {
            "sequential_no_batching_vllm": "seq/no-batch",
            "concurrent_vllm": "vLLM async",
            "direct_transformers_no_vllm": "direct HF",
        }
        return labels.get(str(row.get("mode")), str(row.get("mode")))

    def bar_chart(
        x: int,
        y: int,
        w: int,
        h: int,
        metric: str,
        heading: str,
        color: str,
        suffix: str = "",
        lower_is_better: bool = False,
    ) -> str:
        values = [numeric(row, metric) for row in rows]
        max_value = max(values) if values else 1.0
        if max_value <= 0:
            max_value = 1.0
        inner_x = x + 70
        inner_y = y + 78
        inner_w = w - 118
        inner_h = h - 136
        gap = 24
        bar_w = max(46, (inner_w - gap * (len(rows) - 1)) / max(1, len(rows)))
        mean_value = statistics.mean(values) if values else 0
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{panel}" stroke="#e2e8f0"/>',
            f'<text x="{x + 28}" y="{y + 42}" font-size="24" font-weight="800" fill="{text}">{html.escape(heading)}</text>',
            f'<line x1="{inner_x}" y1="{inner_y + inner_h}" x2="{inner_x + inner_w}" y2="{inner_y + inner_h}" stroke="{grid}"/>',
        ]
        for i in range(1, 5):
            gy = inner_y + inner_h - inner_h * i / 4
            parts.append(f'<line x1="{inner_x}" y1="{gy:.1f}" x2="{inner_x + inner_w}" y2="{gy:.1f}" stroke="{grid}" stroke-dasharray="4 8"/>')
        for i, row in enumerate(rows):
            value = numeric(row, metric)
            bar_h = inner_h * value / max_value
            bx = inner_x + i * (bar_w + gap)
            by = inner_y + inner_h - bar_h
            fill = color
            if lower_is_better:
                fill = "#16a34a" if value <= mean_value else color
            if row.get("mode") == "direct_transformers_no_vllm":
                fill = "#7c3aed"
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="8" fill="{fill}"/>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 10:.1f}" text-anchor="middle" font-size="15" font-weight="800" fill="{text}">{value:.2f}{suffix}</text>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 32:.1f}" text-anchor="middle" font-size="15" fill="{muted}">{html.escape(short_label(row))}</text>')
        return "\n".join(parts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="58" y="70" font-size="34" font-weight="900" fill="{text}">{html.escape(title)}</text>',
        f'<text x="58" y="106" font-size="18" fill="{muted}">Baseline A is sequential/no-batching. Baseline B direct Transformers is optional.</text>',
        f'<rect x="1070" y="42" width="312" height="92" rx="18" fill="#e0f2fe" stroke="#bae6fd"/>',
        f'<text x="1098" y="80" font-size="18" font-weight="800" fill="#075985">vLLM async vs seq</text>',
        f'<text x="1098" y="118" font-size="32" font-weight="900" fill="#0369a1">{speedup:.2f}x</text>',
        bar_chart(58, 166, 640, 300, "requests_per_s", "Requests per second", colors["throughput"]),
        bar_chart(742, 166, 640, 300, "completion_tokens_per_s", "Output tokens per second", colors["tokens"]),
        bar_chart(58, 520, 640, 300, "wall_time_s", "Wall time", colors["wall"], "s", True),
        bar_chart(742, 520, 640, 300, "latency_p95_s", "p95 latency", colors["latency"], "s", True),
        "</svg>",
    ]
    write_text(output_path, "\n".join(svg))


def write_report(rows: list[dict[str, Any]], args: argparse.Namespace, visual_path: Path) -> Path:
    report_path = Path(args.results_dir) / f"report_{args.label}.md"
    seq = next((row for row in rows if row.get("mode") == "sequential_no_batching_vllm"), None)
    concurrent = next((row for row in rows if row.get("mode") == "concurrent_vllm"), None)
    speedup = safe_div(numeric(concurrent or {}, "requests_per_s"), numeric(seq or {}, "requests_per_s"))
    direct = next((row for row in rows if row.get("mode") == "direct_transformers_no_vllm"), None)

    lines = [
        "# Experiment 07 - Proving the no-vLLM Baseline",
        "",
        "## What This Experiment Proves",
        "",
        "- Baseline A: `sequential_no_batching_vllm` is the main fair baseline. It still uses the same vLLM server/model/API, but sends one request at a time.",
        "- `concurrent_vllm` shows what happens when the same server is allowed to serve multiple concurrent requests.",
        "- Baseline B: `direct_transformers_no_vllm` is optional and strict, because it loads the model directly with HuggingFace Transformers.",
        "",
        "## Config",
        "",
        f"- Label: `{args.label}`",
        f"- vLLM base URL: `{args.base_url}`",
        f"- vLLM model: `{args.model}`",
        f"- Requests for vLLM modes: `{args.num_requests}`",
        f"- vLLM concurrent comparison concurrency: `{args.vllm_concurrency}`",
        f"- Max tokens: `{args.max_tokens}`",
        f"- Include direct Transformers: `{args.include_direct_transformers}`",
        f"- Direct model path: `{args.direct_model_path}`",
        "",
        "## Results",
        "",
        "| Mode | Engine | Success | Failed | Concurrency | Wall time (s) | Requests/s | Output tokens/s | Avg latency (s) | p95 latency (s) | Note |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {mode} | {engine} | {success} | {failed} | {concurrency} | "
            "{wall_time_s} | {requests_per_s} | {completion_tokens_per_s} | "
            "{latency_avg_s} | {latency_p95_s} | {note} |".format(**row)
        )
    lines.extend(["", "## Interpretation", ""])
    if seq and concurrent:
        lines.append(f"- Concurrent vLLM throughput vs sequential/no-batching baseline: `{speedup:.2f}x`.")
        lines.append("- This is the main result to present when you want a fair comparison with the same model/API.")
    else:
        lines.append("- Run both sequential and concurrent vLLM modes to compute Baseline A speedup.")
    if direct:
        if int(direct.get("success", 0)) > 0:
            lines.append("- Direct Transformers ran successfully, so it can be used as an appendix true no-vLLM baseline.")
        else:
            lines.append("- Direct Transformers did not run successfully; this is acceptable to report as a VRAM/environment limitation.")
    else:
        lines.append("- Direct Transformers was skipped. In the report, call it optional/future-work unless you run `--include-direct-transformers`.")
    lines.extend(
        [
            "",
            "## How To Explain To The Professor",
            "",
            "- vLLM does not make the model smarter; it improves serving efficiency.",
            "- Baseline A is not absolute no-vLLM, but it cleanly isolates batching/concurrency benefits with minimal confounders.",
            "- Baseline B is absolute no-vLLM, but it can be less fair because Transformers loading, device mapping, dtype, and VRAM constraints may differ from vLLM.",
            "",
            "## Visualization",
            "",
            f"- [{visual_path.name}]({visual_path.name})",
        ]
    )
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def render_artifacts(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    order = {
        "sequential_no_batching_vllm": 0,
        "concurrent_vllm": 1,
        "direct_transformers_no_vllm": 2,
    }
    rows = sorted(rows, key=lambda row: order.get(str(row.get("mode")), 99))
    for row in rows:
        row["run_id"] = args.run_id
    visual_path = Path(args.results_dir) / f"no_vllm_baselines_{args.label}.svg"
    render_svg(rows, visual_path, f"MCQGen no-vLLM Baselines - {args.label}")
    report_path = write_report(rows, args, visual_path)
    print("\n[artifacts]")
    print(f"  svg:    {rel(visual_path)}")
    print(f"  report: {rel(report_path)}")


async def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()
    rows: list[dict[str, Any]] = []

    if args.run_vllm_baseline:
        preflight_vllm(args)
        rows.append(
            await run_openai_mode(
                args,
                mode_name="sequential_no_batching_vllm",
                concurrency=1,
            )
        )
        rows.append(
            await run_openai_mode(
                args,
                mode_name="concurrent_vllm",
                concurrency=args.vllm_concurrency,
            )
        )

    if args.include_direct_transformers:
        rows.append(run_direct_transformers(args))

    if not rows:
        raise SystemExit("Nothing to run. Enable --run-vllm-baseline or --include-direct-transformers.")
    render_artifacts(args, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 07: prove no-vLLM baselines from section 6."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--num-requests", type=int, default=40)
    parser.add_argument("--vllm-concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--request-timeout", type=float, default=900.0)
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--run-vllm-baseline", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-preflight", action="store_true")

    parser.add_argument("--include-direct-transformers", action="store_true")
    parser.add_argument("--direct-model-path", default=str(DEFAULT_DIRECT_MODEL))
    parser.add_argument("--direct-num-requests", type=int, default=5)
    parser.add_argument("--direct-max-tokens", type=int, default=256)
    parser.add_argument("--direct-warmup", type=int, default=1)
    parser.add_argument("--direct-device", default="cuda:0")
    parser.add_argument("--direct-device-map", default="auto")
    parser.add_argument("--direct-dtype", choices=["float16", "bfloat16"], default="float16")

    parser.add_argument("--label", default="no_vllm_baseline")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    if args.num_requests <= 0:
        raise SystemExit("--num-requests must be positive")
    if args.vllm_concurrency <= 0:
        raise SystemExit("--vllm-concurrency must be positive")
    if args.max_tokens <= 0:
        raise SystemExit("--max-tokens must be positive")
    if args.direct_num_requests <= 0:
        raise SystemExit("--direct-num-requests must be positive")
    if args.direct_max_tokens <= 0:
        raise SystemExit("--direct-max-tokens must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
