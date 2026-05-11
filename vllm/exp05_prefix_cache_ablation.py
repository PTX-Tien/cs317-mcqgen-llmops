#!/usr/bin/env python3
"""
Experiment 05: vLLM prefix caching ablation for MCQGen.

This experiment benchmarks the currently running vLLM server with a
shared-prefix workload. It does not stop, restart, or reload the LLM.

The workload intentionally uses a long identical prompt prefix and only changes
the final request line. This makes the experiment suitable for showing whether
vLLM can reuse shared prompt prefixes.

Recommended run:
  conda run -n mcqgen_v2 python vllm/exp05_prefix_cache_ablation.py \
    --concurrency 4 \
    --num-requests 40 \
    --max-tokens 256 \
    --prefix-cache-mode on \
    --label prefix_cache_c4

Outputs:
  - one SVG visualization
  - one Markdown report
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import html
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VLLM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VLLM_DIR.parent
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp05_prefix_cache_ablation"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")

SYSTEM_PROMPT = (
    "Bạn là giảng viên đại học dạy môn CS116 - Lập trình Python cho Máy học. "
    "Bạn đang biên soạn câu hỏi trắc nghiệm tiếng Việt cho sinh viên đại học. "
    "Chỉ trả về JSON hợp lệ."
)

SHARED_PREFIX = """[ROLE]
Bạn là giảng viên Trường Đại học Công nghệ Thông tin, ĐHQG-HCM.
Bạn đang tạo câu hỏi trắc nghiệm tiếng Việt cho sinh viên đại học.

[COURSE CONTEXT]
Môn học tập trung vào Python cho Machine Learning: xử lý dữ liệu với Pandas,
tiền xử lý dữ liệu, train/test split, feature scaling, mô hình phân loại,
đánh giá mô hình, overfitting, regularization, cây quyết định, clustering,
và các khái niệm cơ bản của deep learning.

[EXAM STYLE]
- Câu hỏi dùng trong đề thi hoặc bộ ôn tập cuối kỳ.
- Câu hỏi phải ngắn gọn, học thuật, rõ ràng.
- Không tạo bối cảnh doanh nghiệp dài dòng.
- Không dùng "Tất cả đáp án trên" hoặc "Không đáp án nào đúng".
- Có đúng 4 options A/B/C/D.
- Có đúng 1 đáp án đúng.
- Distractors phải plausible nhưng sai rõ ràng về mặt kỹ thuật.
- Output phải là JSON hợp lệ, không thêm text ngoài JSON.

[JSON SCHEMA]
{
  "question_text": "...",
  "question_type": "single_correct",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answers": ["A"],
  "correct_rationale": "...",
  "topic": "...",
  "difficulty_label": "G2"
}

[REFERENCE KNOWLEDGE]
Pandas DataFrame hỗ trợ lọc dòng, chọn cột, xử lý missing values, groupby,
merge, apply và biến đổi dữ liệu. Trong pipeline machine learning, sinh viên
cần hiểu tác động của dropna, fillna, SimpleImputer, chuẩn hóa dữ liệu và
chia tập train/test. Khi đánh giá mô hình phân loại, cần phân biệt accuracy,
precision, recall, F1-score và confusion matrix. Overfitting xảy ra khi mô
hình học quá sát dữ liệu train và tổng quát hóa kém trên dữ liệu mới.
"""

TOPICS = [
    "dropna và fillna trong Pandas",
    "SimpleImputer trong sklearn",
    "train/test split",
    "StandardScaler và MinMaxScaler",
    "precision và recall",
    "overfitting",
    "decision tree depth",
    "k-means clustering",
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


def build_prompt(request_id: int, repeat_prefix: int) -> str:
    shared = "\n\n".join([SHARED_PREFIX] * repeat_prefix)
    topic = TOPICS[request_id % len(TOPICS)]
    return f"""{shared}

[REQUEST]
Tạo câu hỏi số {request_id} về topic: {topic}.
Độ khó: G2.
Chỉ trả về JSON đúng schema."""


def preflight(args: argparse.Namespace) -> None:
    if args.skip_preflight:
        return
    root = server_root(args.base_url)
    health = http_get(f"{root}/health", timeout=args.http_timeout)
    models = http_get(f"{args.base_url.rstrip('/')}/models", timeout=args.http_timeout)
    if not health["ok"] or not models["ok"]:
        raise SystemExit(
            "vLLM server is not ready. Start vLLM first or pass --skip-preflight."
        )


async def one_call(
    client: Any,
    *,
    model: str,
    request_id: int,
    max_tokens: int,
    temperature: float,
    request_timeout: float,
    repeat_prefix: int,
) -> CallResult:
    t0 = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(request_id, repeat_prefix)},
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


async def warmup(client: Any, args: argparse.Namespace) -> None:
    if args.warmup <= 0:
        return
    print(f"[warmup] requests={args.warmup}")
    for i in range(args.warmup):
        result = await one_call(
            client,
            model=args.model,
            request_id=-1000 - i,
            max_tokens=min(args.max_tokens, 128),
            temperature=args.temperature,
            request_timeout=args.request_timeout,
            repeat_prefix=args.repeat_prefix,
        )
        if not result.ok:
            print(f"  warmup failed: {result.error}")


def parse_prefix_cache_hit_rate(metrics_text: str) -> float:
    best = 0.0
    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        lower = line.lower()
        if "prefix" not in lower or "hit" not in lower or "rate" not in lower:
            continue
        match = re.search(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$", line)
        if not match:
            continue
        try:
            best = max(best, float(match.group(1)))
        except ValueError:
            continue
    return best


async def benchmark_current_server(args: argparse.Namespace, mode: str) -> dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency `openai`. Activate the project environment first."
        ) from exc

    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key)
    await warmup(client, args)

    semaphore = asyncio.Semaphore(args.concurrency)

    async def guarded(i: int) -> CallResult:
        async with semaphore:
            return await one_call(
                client,
                model=args.model,
                request_id=i,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                request_timeout=args.request_timeout,
                repeat_prefix=args.repeat_prefix,
            )

    print(
        f"[exp05] prefix_cache={mode} requests={args.num_requests} "
        f"concurrency={args.concurrency} repeat_prefix={args.repeat_prefix}"
    )
    t0 = time.perf_counter()
    results = await asyncio.gather(*[guarded(i) for i in range(args.num_requests)])
    wall_time = time.perf_counter() - t0

    success = [item for item in results if item.ok]
    failed = [item for item in results if not item.ok]
    latencies = [item.latency_s for item in success]
    prompt_tokens = sum(item.prompt_tokens for item in success)
    completion_tokens = sum(item.completion_tokens for item in success)
    total_tokens = sum(item.total_tokens for item in success)

    metrics = http_get(f"{server_root(args.base_url)}/metrics", timeout=args.http_timeout)
    prefix_hit_rate = parse_prefix_cache_hit_rate(metrics["body"]) if metrics["ok"] else 0.0
    first_error = next((item.error for item in failed if item.error), "")
    row = {
        "run_id": args.run_id,
        "timestamp": dt.datetime.now().isoformat(),
        "label": args.label,
        "base_url": args.base_url,
        "model": args.model,
        "prefix_cache_mode": mode,
        "num_requests": args.num_requests,
        "success": len(success),
        "failed": len(failed),
        "concurrency": args.concurrency,
        "max_num_seqs": args.server_max_num_seqs,
        "max_tokens": args.max_tokens,
        "repeat_prefix": args.repeat_prefix,
        "temperature": args.temperature,
        "wall_time_s": round(wall_time, 4),
        "requests_per_s": round(safe_div(len(success), wall_time), 4),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_tokens_per_s": round(safe_div(prompt_tokens, wall_time), 4),
        "completion_tokens_per_s": round(safe_div(completion_tokens, wall_time), 4),
        "total_tokens_per_s": round(safe_div(total_tokens, wall_time), 4),
        "latency_avg_s": round(safe_mean(latencies), 4),
        "latency_p50_s": round(percentile(latencies, 50), 4),
        "latency_p95_s": round(percentile(latencies, 95), 4),
        "latency_p99_s": round(percentile(latencies, 99), 4),
        "latency_max_s": round(max(latencies), 4) if latencies else 0,
        "prefix_cache_hit_rate_after": round(prefix_hit_rate, 6),
        "first_error": first_error[:300],
    }
    print_summary(row)
    return row


def print_summary(row: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "prefix_cache_mode",
        "num_requests",
        "success",
        "failed",
        "concurrency",
        "wall_time_s",
        "requests_per_s",
        "prompt_tokens_per_s",
        "completion_tokens_per_s",
        "latency_avg_s",
        "latency_p95_s",
        "prefix_cache_hit_rate_after",
    ]:
        print(f"{key}: {row.get(key)}")


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
        "prompt": "#7c3aed",
        "wall": "#f97316",
        "latency": "#dc2626",
    }

    off = next((row for row in rows if row.get("prefix_cache_mode") == "off"), None)
    on = next((row for row in rows if row.get("prefix_cache_mode") == "on"), None)
    has_ablation = bool(off and on)
    speedup = safe_div(numeric(on or {}, "requests_per_s"), numeric(off or {}, "requests_per_s"))
    hit_rate = max((numeric(row, "prefix_cache_hit_rate_after") for row in rows), default=0.0)
    card_title = "On vs off throughput" if has_ablation else "Prefix cache hit rate"
    card_value = f"{speedup:.2f}x" if has_ablation else f"{hit_rate * 100:.1f}%"

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
        inner_x = x + 80
        inner_y = y + 78
        inner_w = w - 136
        inner_h = h - 134
        gap = 72
        bar_w = max(80, (inner_w - gap * (len(rows) - 1)) / max(1, len(rows)))
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
            elif row.get("prefix_cache_mode") == "on":
                fill = "#059669" if metric in {"requests_per_s", "prompt_tokens_per_s"} else fill
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="10" fill="{fill}"/>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 10:.1f}" text-anchor="middle" font-size="16" font-weight="800" fill="{text}">{value:.2f}{suffix}</text>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 34:.1f}" text-anchor="middle" font-size="17" fill="{muted}">cache={row.get("prefix_cache_mode")}</text>')
        return "\n".join(parts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="58" y="70" font-size="34" font-weight="900" fill="{text}">{html.escape(title)}</text>',
        f'<text x="58" y="106" font-size="18" fill="{muted}">Long identical prompt prefix; client concurrency fixed at {rows[0].get("concurrency") if rows else 4}.</text>',
        f'<rect x="1070" y="42" width="312" height="92" rx="18" fill="#dcfce7" stroke="#bbf7d0"/>',
        f'<text x="1098" y="80" font-size="18" font-weight="800" fill="#166534">{card_title}</text>',
        f'<text x="1098" y="118" font-size="32" font-weight="900" fill="#15803d">{card_value}</text>',
        bar_chart(58, 166, 640, 300, "requests_per_s", "Requests per second", colors["throughput"]),
        bar_chart(742, 166, 640, 300, "prompt_tokens_per_s", "Prompt tokens per second", colors["prompt"]),
        bar_chart(58, 520, 640, 300, "wall_time_s", "Wall time", colors["wall"], "s", True),
        bar_chart(742, 520, 640, 300, "latency_p95_s", "p95 latency", colors["latency"], "s", True),
        "</svg>",
    ]
    write_text(output_path, "\n".join(svg))


def write_report(rows: list[dict[str, Any]], args: argparse.Namespace, visual_path: Path) -> Path:
    report_path = Path(args.results_dir) / f"report_{args.label}.md"
    off = next((row for row in rows if row.get("prefix_cache_mode") == "off"), None)
    on = next((row for row in rows if row.get("prefix_cache_mode") == "on"), None)
    throughput_speedup = safe_div(numeric(on or {}, "requests_per_s"), numeric(off or {}, "requests_per_s"))
    prompt_speedup = safe_div(numeric(on or {}, "prompt_tokens_per_s"), numeric(off or {}, "prompt_tokens_per_s"))

    lines = [
        "# Experiment 05 - vLLM Prefix Cache Ablation",
        "",
        "## Config",
        "",
        f"- Label: `{args.label}`",
        f"- Base URL: `{args.base_url}`",
        f"- Model: `{args.model}`",
        f"- Prefix cache mode label: `{args.prefix_cache_mode}`",
        f"- Client concurrency: `{args.concurrency}`",
        f"- Reported server max_num_seqs: `{args.server_max_num_seqs}`",
        f"- Requests per mode: `{args.num_requests}`",
        f"- Max tokens: `{args.max_tokens}`",
        f"- Shared prefix repeat: `{args.repeat_prefix}`",
        f"- Server restart/load by this script: `false`",
        "",
        "## Results",
        "",
        "| Prefix cache | Success | Failed | Wall time (s) | Requests/s | Prompt tokens/s | Output tokens/s | Avg latency (s) | p95 latency (s) | Prefix hit rate after |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {prefix_cache_mode} | {success} | {failed} | {wall_time_s} | "
            "{requests_per_s} | {prompt_tokens_per_s} | {completion_tokens_per_s} | "
            "{latency_avg_s} | {latency_p95_s} | {prefix_cache_hit_rate_after} |".format(**row)
        )

    lines.extend(["", "## Interpretation", ""])
    if off and on:
        lines.append(f"- Requests/s speedup `on/off`: `{throughput_speedup:.2f}x`.")
        lines.append(f"- Prompt tokens/s speedup `on/off`: `{prompt_speedup:.2f}x`.")
    else:
        lines.append("- This run measures the currently loaded vLLM server only; it does not unload/reload the model to toggle prefix caching.")
        lines.append("- To make a true on/off ablation, start the server externally with each config and run this script once per config.")
    lines.extend(
        [
            "- Prefix caching is most visible when many requests share a long identical prefix.",
            "- `prompt_tokens_per_s` is the key metric here because prefix caching mainly reduces repeated prefill work.",
            "- If hit rate stays near zero, the prompt prefix may not be identical after tokenization, the vLLM version may expose a different metric, or the workload is too small.",
            "- If output generation dominates runtime, requests/s may improve less than prompt tokens/s.",
            "",
            "## Visualization",
            "",
            f"- [{visual_path.name}]({visual_path.name})",
        ]
    )
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def render_artifacts(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    order = {"off": 0, "on": 1, "current": 2}
    rows = sorted(rows, key=lambda row: order.get(row.get("prefix_cache_mode", ""), 99))
    visual_path = Path(args.results_dir) / f"prefix_cache_ablation_{args.label}.svg"
    render_svg(rows, visual_path, f"MCQGen vLLM Prefix Cache Ablation - {args.label}")
    report_path = write_report(rows, args, visual_path)
    print("\n[artifacts]")
    print(f"  svg:     {rel(visual_path)}")
    print(f"  report:  {rel(report_path)}")


async def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()
    preflight(args)
    row = await benchmark_current_server(args, args.prefix_cache_mode)
    rows = [row]
    render_artifacts(args, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 05: benchmark prefix-cache workload on the currently running vLLM server."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prefix-cache-mode", choices=["current", "off", "on"], default="current")
    parser.add_argument("--num-requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--repeat-prefix", type=int, default=6)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--request-timeout", type=float, default=900.0)
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--label", default="prefix_cache_c4")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--skip-preflight", action="store_true")

    parser.add_argument("--server-max-num-seqs", type=int, default=4)
    args = parser.parse_args()

    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be positive")
    if args.num_requests <= 0:
        raise SystemExit("--num-requests must be positive")
    if args.repeat_prefix <= 0:
        raise SystemExit("--repeat-prefix must be positive")
    if args.server_max_num_seqs <= 0:
        raise SystemExit("--server-max-num-seqs must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
