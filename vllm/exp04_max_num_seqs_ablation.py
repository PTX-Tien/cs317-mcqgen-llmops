#!/usr/bin/env python3
"""
Experiment 04: vLLM --max-num-seqs ablation for MCQGen.

This script benchmarks vLLM with a fixed client concurrency of 4 by default.
Recommended mode: let the script restart vLLM and run all max_num_seqs configs:

  python vllm/exp04_max_num_seqs_ablation.py \
    --auto-restart \
    --server-max-num-seqs-list 1,2,4,8 \
    --concurrency 4 \
    --num-requests 40

Manual mode is still supported if you restart vLLM yourself:

  python vllm/exp04_max_num_seqs_ablation.py --server-max-num-seqs 4

The script keeps a small JSON state file and regenerates two demo artifacts:
  - one SVG visualization
  - one Markdown summary
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
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp04_max_num_seqs_ablation"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")

SYSTEM_PROMPT = (
    "Bạn là giảng viên đại học dạy môn CS116 - Lập trình Python cho Máy học. "
    "Bạn đang biên soạn câu hỏi trắc nghiệm tiếng Việt. "
    "Chỉ trả về JSON hợp lệ."
)

PROMPT_TEMPLATE = """Tạo 1 câu MCQ tiếng Việt về topic "{topic}", độ khó G2.

[YÊU CẦU]
- Có đúng 4 options A/B/C/D.
- Có đúng 1 đáp án đúng.
- Distractors phải plausible nhưng sai về mặt kỹ thuật.
- Câu hỏi kiểm tra hiểu khái niệm hoặc áp dụng.

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
    "regularization",
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


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


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


def build_prompt(i: int) -> str:
    return PROMPT_TEMPLATE.format(topic=TOPICS[i % len(TOPICS)])


def parse_int_list(value: str) -> list[int]:
    values = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        parsed = int(part)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("max_num_seqs values must be positive")
        values.append(parsed)
    if not values:
        raise argparse.ArgumentTypeError("at least one max_num_seqs value is required")
    return values


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


def tail_text(path: Path, max_chars: int = 5000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def stop_vllm_on_port(args: argparse.Namespace) -> None:
    if not args.stop_existing:
        return
    pattern = f"vllm serve .*--port {args.port}"
    print(f"[vLLM] stopping existing server on port {args.port} if any")
    subprocess.run(["pkill", "-f", pattern], cwd=PROJECT_ROOT, check=False)
    time.sleep(args.shutdown_grace_s)


def start_vllm_for_config(args: argparse.Namespace, max_num_seqs: int) -> subprocess.Popen:
    log_dir = ensure_dir(VLLM_DIR / "logs")
    log_path = log_dir / f"exp04_vllm_max_num_seqs_{max_num_seqs}_{args.run_id}.log"
    command = [
        args.vllm_bin,
        "serve",
        args.model_path,
        "--dtype",
        args.dtype,
        "--tensor-parallel-size",
        str(args.tensor_parallel_size),
        "--max-model-len",
        str(args.max_model_len),
        "--gpu-memory-utilization",
        str(args.gpu_memory_utilization),
        "--enforce-eager",
        "--enable-prefix-caching",
        "--disable-log-requests",
        "--max-num-seqs",
        str(max_num_seqs),
        "--port",
        str(args.port),
        "--host",
        args.host,
        "--served-model-name",
        args.model,
    ]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = args.cuda_visible_devices
    if args.cuda_home:
        env["CUDA_HOME"] = args.cuda_home
        env["PATH"] = f"{args.cuda_home}/bin:" + env.get("PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{args.cuda_home}/lib64:" + env.get("LD_LIBRARY_PATH", "")
        )

    print(f"[vLLM] starting max_num_seqs={max_num_seqs}")
    print(f"[vLLM] log={rel(log_path)}")
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    args.current_vllm_log = str(log_path)
    return proc


def wait_for_vllm_ready(args: argparse.Namespace, proc: subprocess.Popen) -> None:
    deadline = time.time() + args.startup_timeout_s
    health_url = f"{server_root(args.base_url)}/health"
    while time.time() < deadline:
        if http_get(health_url, timeout=args.http_timeout)["ok"]:
            print("[vLLM] ready")
            return
        if proc.poll() is not None:
            log_tail = tail_text(Path(getattr(args, "current_vllm_log", "")))
            raise SystemExit(
                "vLLM exited before it became ready.\n"
                f"Log tail:\n{log_tail}"
            )
        time.sleep(args.startup_poll_s)
    log_tail = tail_text(Path(getattr(args, "current_vllm_log", "")))
    raise SystemExit(f"Timed out waiting for vLLM.\nLog tail:\n{log_tail}")


def stop_process(proc: subprocess.Popen, timeout_s: float = 20.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)


async def one_call(
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
        )
        if not result.ok:
            print(f"  warmup failed: {result.error}")


async def benchmark_current_server(args: argparse.Namespace) -> dict[str, Any]:
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
            )

    print(
        f"[exp04] max_num_seqs={args.server_max_num_seqs} "
        f"requests={args.num_requests} concurrency={args.concurrency}"
    )
    t0 = time.perf_counter()
    results = await asyncio.gather(*[guarded(i) for i in range(args.num_requests)])
    wall_time = time.perf_counter() - t0

    success = [item for item in results if item.ok]
    failed = [item for item in results if not item.ok]
    latencies = [item.latency_s for item in success]
    completion_tokens = sum(item.completion_tokens for item in success)
    total_tokens = sum(item.total_tokens for item in success)

    first_error = next((item.error for item in failed if item.error), "")
    row = {
        "run_id": args.run_id,
        "timestamp": dt.datetime.now().isoformat(),
        "label": args.label,
        "base_url": args.base_url,
        "model": args.model,
        "server_max_num_seqs": args.server_max_num_seqs,
        "num_requests": args.num_requests,
        "success": len(success),
        "failed": len(failed),
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
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
        "first_error": first_error[:300],
    }
    print_summary(row)
    return row


def print_summary(row: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "server_max_num_seqs",
        "num_requests",
        "success",
        "failed",
        "concurrency",
        "wall_time_s",
        "requests_per_s",
        "completion_tokens_per_s",
        "total_tokens_per_s",
        "latency_avg_s",
        "latency_p95_s",
        "latency_p99_s",
    ]:
        print(f"{key}: {row.get(key)}")


def state_path(args: argparse.Namespace) -> Path:
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.label)
    return Path(args.results_dir) / f"state_{safe_label}.json"


def update_state(args: argparse.Namespace, row: dict[str, Any]) -> list[dict[str, Any]]:
    path = state_path(args)
    state = read_json(path, {"label": args.label, "runs": []})
    runs = [item for item in state.get("runs", []) if item.get("label") == args.label]

    if args.replace_same_config:
        runs = [
            item
            for item in runs
            if int(item.get("server_max_num_seqs", -1)) != args.server_max_num_seqs
        ]
    runs.append(row)
    runs = sorted(runs, key=lambda item: int(item.get("server_max_num_seqs", 0)))
    write_json(path, {"label": args.label, "updated_at": dt.datetime.now().isoformat(), "runs": runs})
    return runs


def numeric(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


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

    baseline = next((row for row in rows if int(row.get("server_max_num_seqs", 0)) == 1), None)
    best = max(rows, key=lambda row: numeric(row, "requests_per_s")) if rows else None
    speedup = safe_div(numeric(best or {}, "requests_per_s"), numeric(baseline or {}, "requests_per_s"))

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
        inner_x = x + 68
        inner_y = y + 78
        inner_w = w - 112
        inner_h = h - 134
        gap = 22
        bar_w = max(18, (inner_w - gap * (len(rows) - 1)) / max(1, len(rows)))
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
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="8" fill="{fill}"/>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 10:.1f}" text-anchor="middle" font-size="16" font-weight="800" fill="{text}">{value:.2f}{suffix}</text>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 32:.1f}" text-anchor="middle" font-size="16" fill="{muted}">seqs={row.get("server_max_num_seqs")}</text>')
        return "\n".join(parts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="58" y="70" font-size="34" font-weight="900" fill="{text}">{html.escape(title)}</text>',
        f'<text x="58" y="106" font-size="18" fill="{muted}">Client concurrency fixed at 4. Each bar uses a different vLLM --max-num-seqs server config.</text>',
        f'<rect x="1070" y="42" width="312" height="92" rx="18" fill="#e0f2fe" stroke="#bae6fd"/>',
        f'<text x="1098" y="80" font-size="18" font-weight="800" fill="#075985">Best vs max_num_seqs=1</text>',
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
    baseline = next((row for row in rows if int(row.get("server_max_num_seqs", 0)) == 1), None)
    best = max(rows, key=lambda row: numeric(row, "requests_per_s")) if rows else None
    speedup = safe_div(numeric(best or {}, "requests_per_s"), numeric(baseline or {}, "requests_per_s"))

    lines = [
        "# Experiment 04 - vLLM max_num_seqs Ablation",
        "",
        "## Config",
        "",
        f"- Label: `{args.label}`",
        f"- Base URL: `{args.base_url}`",
        f"- Model: `{args.model}`",
        f"- Client concurrency: `{args.concurrency}`",
        f"- Requests per run: `{args.num_requests}`",
        f"- Max tokens: `{args.max_tokens}`",
        f"- Config list: `{args.server_max_num_seqs_list}`",
        f"- Auto restart vLLM: `{args.auto_restart}`",
        f"- State file: `{rel(state_path(args))}`",
        "",
        "## Results",
        "",
        "| max_num_seqs | Success | Failed | Wall time (s) | Requests/s | Output tokens/s | Avg latency (s) | p95 latency (s) | p99 latency (s) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {server_max_num_seqs} | {success} | {failed} | {wall_time_s} | "
            "{requests_per_s} | {completion_tokens_per_s} | {latency_avg_s} | "
            "{latency_p95_s} | {latency_p99_s} |".format(**row)
        )
    lines.extend(["", "## Interpretation", ""])
    if baseline and best:
        lines.append(
            f"- Best throughput: `max_num_seqs={best.get('server_max_num_seqs')}` "
            f"with `{best.get('requests_per_s')}` requests/s."
        )
        lines.append(f"- Speedup over `max_num_seqs=1`: `{speedup:.2f}x`.")
    else:
        lines.append("- Run `max_num_seqs=1` plus at least one larger value to compute speedup.")
    lines.extend(
        [
            "- This experiment keeps client concurrency fixed at 4, so the main variable is the vLLM server scheduling/batching limit.",
            "- If requests/s or output tokens/s improves from 1 to 4, it is evidence that vLLM batching capacity helps under concurrent load.",
            "- If latency rises at higher values but failures remain zero, the server is trading per-request latency for higher throughput.",
            "- If values above 4 do not improve, the current GPU/model/prompt workload may already be saturated around concurrency 4.",
            "",
            "## Visualization",
            "",
            f"- [{visual_path.name}]({visual_path.name})",
        ]
    )
    log_rows = [row for row in rows if row.get("vllm_log_file")]
    if log_rows:
        lines.extend(["", "## vLLM Logs", ""])
        for row in log_rows:
            lines.append(
                f"- max_num_seqs={row.get('server_max_num_seqs')}: "
                f"`{row.get('vllm_log_file')}`"
            )
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def render_artifacts(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    rows = sorted(rows, key=lambda row: int(row.get("server_max_num_seqs", 0)))
    visual_path = Path(args.results_dir) / f"max_num_seqs_ablation_{args.label}.svg"
    render_svg(rows, visual_path, f"MCQGen vLLM max_num_seqs Ablation - {args.label}")
    report_path = write_report(rows, args, visual_path)
    print("\n[artifacts]")
    print(f"  state:  {rel(state_path(args))}")
    print(f"  svg:    {rel(visual_path)}")
    print(f"  report: {rel(report_path)}")


async def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()
    if args.auto_restart and args.fresh and state_path(args).exists():
        state_path(args).unlink()

    if not args.auto_restart:
        if args.server_max_num_seqs is None:
            raise SystemExit(
                "Manual mode requires --server-max-num-seqs. "
                "Use --auto-restart to run --server-max-num-seqs-list."
            )
        preflight(args)
        row = await benchmark_current_server(args)
        rows = update_state(args, row)
        render_artifacts(args, rows)
        return

    rows: list[dict[str, Any]] = []
    configs = parse_int_list(args.server_max_num_seqs_list)
    for index, max_num_seqs in enumerate(configs):
        args.server_max_num_seqs = max_num_seqs
        stop_vllm_on_port(args)
        proc = start_vllm_for_config(args, max_num_seqs)
        try:
            wait_for_vllm_ready(args, proc)
            row = await benchmark_current_server(args)
            row["vllm_log_file"] = rel(Path(args.current_vllm_log))
            rows = update_state(args, row)
        finally:
            is_last = index == len(configs) - 1
            if not is_last or not args.leave_running:
                stop_process(proc)
                time.sleep(args.shutdown_grace_s)
    render_artifacts(args, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 04: benchmark vLLM max_num_seqs ablation."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default="x")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--server-max-num-seqs", type=int)
    parser.add_argument("--server-max-num-seqs-list", default="1,2,4,8")
    parser.add_argument("--auto-restart", action="store_true")
    parser.add_argument("--num-requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--request-timeout", type=float, default=900.0)
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--label", default="max_num_seqs_c4")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--replace-same-config", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fresh", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--vllm-bin", default=os.getenv("VLLM_BIN", "vllm"))
    parser.add_argument("--model-path", default=str(PROJECT_ROOT / "models" / "Qwen2.5-7B-Instruct"))
    parser.add_argument("--cuda-visible-devices", default=os.getenv("VLLM_CUDA_VISIBLE_DEVICES", "1,2,3,4"))
    parser.add_argument("--tensor-parallel-size", type=int, default=4)
    parser.add_argument("--max-model-len", type=int, default=5000)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--dtype", default="half")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--cuda-home", default="/usr/local/cuda-11.8")
    parser.add_argument("--startup-timeout-s", type=float, default=600.0)
    parser.add_argument("--startup-poll-s", type=float, default=3.0)
    parser.add_argument("--shutdown-grace-s", type=float, default=3.0)
    parser.add_argument("--stop-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--leave-running", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if args.server_max_num_seqs is not None and args.server_max_num_seqs <= 0:
        raise SystemExit("--server-max-num-seqs must be positive")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be positive")
    if args.num_requests <= 0:
        raise SystemExit("--num-requests must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
