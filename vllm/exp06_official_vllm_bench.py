#!/usr/bin/env python3
"""
Experiment 06: official vLLM serving benchmark for MCQGen.

This experiment uses vLLM's own benchmark command:

  vllm bench serve

Unlike Exp02, which is a project-specific OpenAI chat benchmark, this script
wraps the official benchmark tool and formats the result for a report/demo.
It sweeps official --max-concurrency values and produces:

  - one SVG visualization
  - one Markdown summary

The official raw JSON and stdout logs are also kept under vllm/results for
traceability because they are the source of the report.

Typical run:
  conda run -n mcqgen_v2 python vllm/exp06_official_vllm_bench.py \
    --max-concurrency-list 1,2,4,8 \
    --num-prompts 40 \
    --random-input-len 512 \
    --random-output-len 256 \
    --label official_vllm
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


VLLM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VLLM_DIR.parent
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp06_official_vllm_bench"
DEFAULT_SERVER_URL = os.getenv("VLLM_SERVER_URL", "http://localhost:8000")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "mcqgen")


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


def normalize_server_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/")


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


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_int_list(value: str) -> list[int]:
    values = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        parsed = int(part)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("concurrency values must be positive")
        values.append(parsed)
    if not values:
        raise argparse.ArgumentTypeError("at least one concurrency value is required")
    return values


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def numeric(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def preflight(args: argparse.Namespace) -> None:
    if args.skip_preflight:
        return
    server_url = normalize_server_url(args.server_url)
    health = http_get(f"{server_url}/health", timeout=args.http_timeout)
    models = http_get(f"{server_url}/v1/models", timeout=args.http_timeout)
    if not health["ok"] or not models["ok"]:
        raise SystemExit(
            "vLLM server is not ready. Start vLLM first or pass --skip-preflight."
        )


def metric_from_json(data: dict[str, Any], candidates: list[str]) -> float:
    for key in candidates:
        if key in data:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def regex_metric(text: str, patterns: list[str]) -> float:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            continue
    return 0.0


def parse_official_result(
    *,
    output_text: str,
    result_json_path: Path,
    concurrency: int,
    args: argparse.Namespace,
    wall_time_s: float,
    returncode: int,
) -> dict[str, Any]:
    data = read_json(result_json_path)
    successful_requests = metric_from_json(
        data,
        ["completed", "successful_requests", "num_successful_requests", "num_prompts"],
    )
    failed_requests = metric_from_json(data, ["failed", "failed_requests", "num_failed_requests"])
    request_throughput = metric_from_json(
        data,
        ["request_throughput", "requests_per_second", "requests_per_s", "request_throughput_per_s"],
    )
    output_throughput = metric_from_json(
        data,
        ["output_throughput", "output_tokens_per_second", "output_tokens_per_s"],
    )
    total_token_throughput = metric_from_json(
        data,
        ["total_token_throughput", "total_tokens_per_second", "total_tokens_per_s"],
    )
    mean_e2el = metric_from_json(
        data,
        ["mean_e2el_ms", "mean_e2e_latency_ms", "mean_latency_ms"],
    )
    p99_e2el = metric_from_json(
        data,
        ["p99_e2el_ms", "p99_e2e_latency_ms", "percentile_99_e2el_ms"],
    )
    mean_ttft = metric_from_json(data, ["mean_ttft_ms", "mean_ttft"])
    p99_ttft = metric_from_json(data, ["p99_ttft_ms", "percentile_99_ttft_ms", "p99_ttft"])
    mean_tpot = metric_from_json(data, ["mean_tpot_ms", "mean_tpot"])

    if request_throughput <= 0:
        request_throughput = regex_metric(
            output_text,
            [
                r"Request throughput \(req/s\):\s*([0-9.]+)",
                r"Request throughput:\s*([0-9.]+)",
                r"requests/s\)?[:\s]+([0-9.]+)",
            ],
        )
    if output_throughput <= 0:
        output_throughput = regex_metric(
            output_text,
            [
                r"Output token throughput \(tok/s\):\s*([0-9.]+)",
                r"Output throughput:\s*([0-9.]+)",
            ],
        )
    if total_token_throughput <= 0:
        total_token_throughput = regex_metric(
            output_text,
            [
                r"Total Token throughput \(tok/s\):\s*([0-9.]+)",
                r"Total token throughput:\s*([0-9.]+)",
            ],
        )
    if mean_ttft <= 0:
        mean_ttft = regex_metric(output_text, [r"Mean TTFT \(ms\):\s*([0-9.]+)"])
    if p99_ttft <= 0:
        p99_ttft = regex_metric(output_text, [r"P99 TTFT \(ms\):\s*([0-9.]+)"])
    if mean_tpot <= 0:
        mean_tpot = regex_metric(output_text, [r"Mean TPOT \(ms\):\s*([0-9.]+)"])

    if successful_requests <= 0 and returncode == 0:
        successful_requests = args.num_prompts
    if request_throughput <= 0 and wall_time_s > 0 and returncode == 0:
        request_throughput = safe_div(successful_requests, wall_time_s)

    return {
        "run_id": args.run_id,
        "timestamp": dt.datetime.now().isoformat(),
        "label": args.label,
        "model": args.model,
        "served_model_name": args.served_model_name,
        "server_url": normalize_server_url(args.server_url),
        "endpoint": args.endpoint,
        "max_concurrency": concurrency,
        "num_prompts": args.num_prompts,
        "random_input_len": args.random_input_len,
        "random_output_len": args.random_output_len,
        "returncode": returncode,
        "wall_time_s": round(wall_time_s, 4),
        "successful_requests": int(successful_requests),
        "failed_requests": int(failed_requests),
        "request_throughput": round(request_throughput, 4),
        "output_token_throughput": round(output_throughput, 4),
        "total_token_throughput": round(total_token_throughput, 4),
        "mean_e2el_ms": round(mean_e2el, 4),
        "p99_e2el_ms": round(p99_e2el, 4),
        "mean_ttft_ms": round(mean_ttft, 4),
        "p99_ttft_ms": round(p99_ttft, 4),
        "mean_tpot_ms": round(mean_tpot, 4),
        "official_json": rel(result_json_path),
    }


def run_official_bench(args: argparse.Namespace, concurrency: int) -> dict[str, Any]:
    results_dir = ensure_dir(Path(args.results_dir))
    result_filename = f"official_{args.label}_c{concurrency}_{args.run_id}.json"
    stdout_path = results_dir / f"official_{args.label}_c{concurrency}_{args.run_id}.log"
    result_json_path = results_dir / result_filename
    server_url = normalize_server_url(args.server_url)

    command = [
        args.vllm_bin,
        "bench",
        "serve",
        "--base-url",
        server_url,
        "--endpoint",
        args.endpoint,
        "--endpoint-type",
        "openai-comp",
        "--model",
        args.model,
        "--served-model-name",
        args.served_model_name,
        "--dataset-name",
        "random",
        "--random-input-len",
        str(args.random_input_len),
        "--random-output-len",
        str(args.random_output_len),
        "--num-prompts",
        str(args.num_prompts),
        "--request-rate",
        args.request_rate,
        "--max-concurrency",
        str(concurrency),
        "--metric-percentiles",
        args.metric_percentiles,
        "--percentile-metrics",
        args.percentile_metrics,
        "--save-result",
        "--result-dir",
        str(results_dir),
        "--result-filename",
        result_filename,
        "--label",
        f"{args.label}_c{concurrency}",
        "--disable-tqdm",
    ]
    if args.trust_remote_code:
        command.append("--trust-remote-code")
    if args.ignore_eos:
        command.append("--ignore-eos")

    print(f"\n[exp06] official vLLM bench | max_concurrency={concurrency}")
    print("[cmd] " + " ".join(command))
    t0 = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout_s,
        check=False,
    )
    wall_time = time.perf_counter() - t0
    write_text(stdout_path, proc.stdout)
    row = parse_official_result(
        output_text=proc.stdout,
        result_json_path=result_json_path,
        concurrency=concurrency,
        args=args,
        wall_time_s=wall_time,
        returncode=proc.returncode,
    )
    row["stdout_log"] = rel(stdout_path)
    row["error_preview"] = "" if proc.returncode == 0 else proc.stdout[-800:]
    print_summary(row)
    return row


def print_summary(row: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "max_concurrency",
        "returncode",
        "successful_requests",
        "failed_requests",
        "wall_time_s",
        "request_throughput",
        "output_token_throughput",
        "total_token_throughput",
        "mean_ttft_ms",
        "p99_ttft_ms",
        "mean_tpot_ms",
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
        "request": "#2563eb",
        "output": "#059669",
        "ttft": "#f97316",
        "tpot": "#dc2626",
    }

    baseline = rows[0] if rows else None
    best = max(rows, key=lambda row: numeric(row, "request_throughput")) if rows else None
    speedup = safe_div(numeric(best or {}, "request_throughput"), numeric(baseline or {}, "request_throughput"))

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
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 32:.1f}" text-anchor="middle" font-size="16" fill="{muted}">c={row.get("max_concurrency")}</text>')
        return "\n".join(parts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="58" y="70" font-size="34" font-weight="900" fill="{text}">{html.escape(title)}</text>',
        f'<text x="58" y="106" font-size="18" fill="{muted}">Official vLLM benchmark: random dataset through OpenAI-compatible completions endpoint.</text>',
        f'<rect x="1070" y="42" width="312" height="92" rx="18" fill="#e0f2fe" stroke="#bae6fd"/>',
        f'<text x="1098" y="80" font-size="18" font-weight="800" fill="#075985">Best vs first config</text>',
        f'<text x="1098" y="118" font-size="32" font-weight="900" fill="#0369a1">{speedup:.2f}x</text>',
        bar_chart(58, 166, 640, 300, "request_throughput", "Request throughput", colors["request"], " req/s"),
        bar_chart(742, 166, 640, 300, "output_token_throughput", "Output token throughput", colors["output"], " tok/s"),
        bar_chart(58, 520, 640, 300, "mean_ttft_ms", "Mean TTFT", colors["ttft"], " ms", True),
        bar_chart(742, 520, 640, 300, "mean_tpot_ms", "Mean TPOT", colors["tpot"], " ms", True),
        "</svg>",
    ]
    write_text(output_path, "\n".join(svg))


def write_report(rows: list[dict[str, Any]], args: argparse.Namespace, visual_path: Path) -> Path:
    report_path = Path(args.results_dir) / f"report_{args.label}.md"
    baseline = rows[0] if rows else None
    best = max(rows, key=lambda row: numeric(row, "request_throughput")) if rows else None
    speedup = safe_div(numeric(best or {}, "request_throughput"), numeric(baseline or {}, "request_throughput"))

    lines = [
        "# Experiment 06 - Official vLLM Serving Benchmark",
        "",
        "## Config",
        "",
        f"- Label: `{args.label}`",
        f"- Server URL: `{normalize_server_url(args.server_url)}`",
        f"- Endpoint: `{args.endpoint}`",
        f"- Model: `{args.model}`",
        f"- Served model name: `{args.served_model_name}`",
        f"- Max concurrency list: `{args.max_concurrency_list}`",
        f"- Num prompts: `{args.num_prompts}`",
        f"- Random input length: `{args.random_input_len}`",
        f"- Random output length: `{args.random_output_len}`",
        f"- Request rate: `{args.request_rate}`",
        "",
        "## Results",
        "",
        "| Max concurrency | Return code | Success | Failed | Wall time (s) | Request throughput | Output tok/s | Total tok/s | Mean TTFT (ms) | P99 TTFT (ms) | Mean TPOT (ms) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {max_concurrency} | {returncode} | {successful_requests} | {failed_requests} | "
            "{wall_time_s} | {request_throughput} | {output_token_throughput} | "
            "{total_token_throughput} | {mean_ttft_ms} | {p99_ttft_ms} | {mean_tpot_ms} |".format(**row)
        )
    lines.extend(["", "## Interpretation", ""])
    if baseline and best:
        lines.append(
            f"- Best official request throughput: `max_concurrency={best.get('max_concurrency')}` "
            f"with `{best.get('request_throughput')}` req/s."
        )
        lines.append(f"- Speedup over first config: `{speedup:.2f}x`.")
    else:
        lines.append("- Need at least one successful row to compute throughput.")
    lines.extend(
        [
            "- This is the official vLLM serving benchmark, so it complements the project-specific MCQGen benchmarks.",
            "- It uses a synthetic random-token workload, not the real MCQ prompt format.",
            "- Use Exp02 for MCQ-like prompt behavior and Exp06 for a standardized vLLM tool result.",
            "- TTFT means time to first token; TPOT means time per output token.",
            "",
            "## Visualization",
            "",
            f"- [{visual_path.name}]({visual_path.name})",
            "",
            "## Raw Official Outputs",
            "",
        ]
    )
    for row in rows:
        lines.append(
            f"- concurrency={row.get('max_concurrency')}: "
            f"`{row.get('official_json')}`, `{row.get('stdout_log')}`"
        )
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def render_artifacts(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    rows = sorted(rows, key=lambda row: int(row.get("max_concurrency", 0)))
    visual_path = Path(args.results_dir) / f"official_vllm_bench_{args.label}.svg"
    render_svg(rows, visual_path, f"MCQGen Official vLLM Benchmark - {args.label}")
    report_path = write_report(rows, args, visual_path)
    write_json(Path(args.results_dir) / f"raw_summary_{args.label}.json", rows)
    print("\n[artifacts]")
    print(f"  svg:      {rel(visual_path)}")
    print(f"  report:   {rel(report_path)}")
    print(f"  raw json: {rel(Path(args.results_dir) / f'raw_summary_{args.label}.json')}")


def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()
    args.server_url = normalize_server_url(args.server_url)
    if not args.served_model_name:
        args.served_model_name = args.model
    preflight(args)

    rows = []
    for concurrency in parse_int_list(args.max_concurrency_list):
        rows.append(run_official_bench(args, concurrency))
    render_artifacts(args, rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 06: run official vLLM serving benchmark."
    )
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--served-model-name", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default="/v1/completions")
    parser.add_argument("--max-concurrency-list", default="1,2,4,8")
    parser.add_argument("--num-prompts", type=int, default=40)
    parser.add_argument("--random-input-len", type=int, default=512)
    parser.add_argument("--random-output-len", type=int, default=256)
    parser.add_argument("--request-rate", default="inf")
    parser.add_argument("--metric-percentiles", default="50,95,99")
    parser.add_argument("--percentile-metrics", default="ttft,tpot,itl,e2el")
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--ignore-eos", action="store_true")
    parser.add_argument("--vllm-bin", default=os.getenv("VLLM_BIN", "vllm"))
    parser.add_argument("--timeout-s", type=float, default=1800.0)
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--label", default="official_vllm")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    if args.num_prompts <= 0:
        raise SystemExit("--num-prompts must be positive")
    if args.random_input_len <= 0:
        raise SystemExit("--random-input-len must be positive")
    if args.random_output_len <= 0:
        raise SystemExit("--random-output-len must be positive")
    run(args)


if __name__ == "__main__":
    main()
