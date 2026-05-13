#!/usr/bin/env python3
"""
Experiment 03: full MCQGen pipeline benchmark, sequential vs async + vLLM.

This experiment measures the real project pipeline instead of synthetic LLM-only
requests. It imports src.mcqgen.pipeline_mcq, optionally precomputes RAG context, then
runs the same MCQ generation tasks in two modes:

  - sequential: one MCQ at a time
  - async: multiple MCQs concurrently, so vLLM can batch/schedule LLM calls

Typical run:
  python vllm/exp03_pipeline_sequential_vs_async.py \
    --modes sequential,async \
    --topic-limit 2 \
    --questions-per-topic 1 \
    --concurrency 4 \
    --label pipeline_vllm

The benchmark intentionally writes only two files:
  - one visualization file
  - one Markdown report
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import html
import importlib
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


VLLM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VLLM_DIR.parent
DEFAULT_RESULTS_DIR = VLLM_DIR / "results" / "exp03_pipeline_sequential_vs_async"
DEFAULT_BASE_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
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


def server_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/")


def parse_modes(value: str) -> list[str]:
    modes = []
    for item in value.split(","):
        mode = item.strip().lower()
        if not mode:
            continue
        if mode not in {"sequential", "async"}:
            raise argparse.ArgumentTypeError("modes must be sequential, async, or both")
        modes.append(mode)
    if not modes:
        raise argparse.ArgumentTypeError("at least one mode is required")
    return modes


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


def numeric(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0)
    except ValueError:
        return 0.0


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def collect_preflight(args: argparse.Namespace) -> None:
    if args.skip_preflight:
        return
    root = server_root(args.base_url)
    health = http_get(f"{root}/health", timeout=args.http_timeout)
    models = http_get(f"{args.base_url.rstrip('/')}/models", timeout=args.http_timeout)
    if not health["ok"] or not models["ok"]:
        raise SystemExit(
            "vLLM server is not ready. Start vLLM first or pass --skip-preflight."
        )


def import_pipeline(args: argparse.Namespace) -> Any:
    os.environ["VLLM_URL"] = args.base_url
    os.environ["VLLM_MODEL"] = args.model
    os.environ["MCQGEN_MAX_CONCURRENT_QUESTIONS"] = str(args.concurrency)
    os.environ["ENABLE_LLM_EVAL"] = "1" if args.enable_llm_eval else "0"
    os.environ["DEFAULT_RETRIEVAL_MODE"] = args.retrieval_mode

    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    print("[exp03] Importing src.mcqgen.pipeline_mcq. Retrieval models may load here...")
    return importlib.import_module("src.mcqgen.pipeline_mcq")


def load_pipeline_topics(args: argparse.Namespace, pipeline_mcq: Any) -> list[dict[str, Any]]:
    if args.topics_json:
        topics = json.loads(Path(args.topics_json).read_text(encoding="utf-8"))
    else:
        topics = list(getattr(pipeline_mcq, "TOPICS"))

    if args.topic_limit:
        topics = topics[: args.topic_limit]

    normalized = []
    for idx, topic in enumerate(topics):
        item = dict(topic)
        if args.questions_per_topic is not None:
            item["n"] = args.questions_per_topic
        item.setdefault("topic_id", f"topic_{idx:02d}")
        item.setdefault("chapter_id", "")
        item.setdefault("difficulty", "G2")
        item.setdefault("n", 1)
        normalized.append(item)
    return normalized


def build_task_specs(topics: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    return [(topic, seq) for topic in topics for seq in range(int(topic.get("n", 1)))]


async def precompute_rag_cache(
    *,
    args: argparse.Namespace,
    pipeline_mcq: Any,
    task_specs: list[tuple[dict[str, Any], int]],
) -> tuple[dict[tuple[str, str, str], tuple[str, dict[str, Any]]], float]:
    cache: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}

    if not args.precompute_rag:
        return cache, 0.0

    unique_topics: dict[tuple[str, str, str], dict[str, Any]] = {}
    for topic_cfg, _seq in task_specs:
        key = (topic_cfg["topic"], topic_cfg["chapter_id"], args.retrieval_mode)
        unique_topics.setdefault(key, topic_cfg)

    print(f"[exp03] Precomputing RAG for {len(unique_topics)} unique topics...")
    t_all = time.perf_counter()
    for idx, (key, topic_cfg) in enumerate(unique_topics.items(), 1):
        topic, chapter_id, mode = key
        t0 = time.perf_counter()
        try:
            cache[key] = await pipeline_mcq.adaptive_retrieve(
                topic,
                chapter_id,
                mode=mode,
            )
            ok = True
            error = ""
        except Exception as exc:
            ok = False
            error = repr(exc)
            cache[key] = ("", {"strategy": "rag_error", "top_scores_after_rerank": [0]})
        latency = time.perf_counter() - t0
        status = "ok" if ok else f"error={error}"
        print(
            f"  RAG {idx}/{len(unique_topics)} {topic_cfg.get('topic_id', '')} "
            f"{latency:.2f}s | {status}"
        )
    return cache, time.perf_counter() - t_all


async def run_one_mode(
    *,
    args: argparse.Namespace,
    pipeline_mcq: Any,
    mode: str,
    task_specs: list[tuple[dict[str, Any], int]],
    rag_cache: dict[tuple[str, str, str], tuple[str, dict[str, Any]]],
    rag_precompute_time_s: float,
) -> dict[str, Any]:
    async def run_one(topic_cfg: dict[str, Any], seq: int) -> Any:
        key = (topic_cfg["topic"], topic_cfg["chapter_id"], args.retrieval_mode)
        precomputed = rag_cache.get(key) if args.precompute_rag else None
        return await pipeline_mcq.generate_one_mcq(
            topic_cfg,
            seq,
            precomputed_rag=precomputed,
            retrieval_mode=args.retrieval_mode,
        )

    async def execute() -> list[Any]:
        if mode == "sequential":
            results = []
            for idx, (topic_cfg, seq) in enumerate(task_specs, 1):
                print(
                    f"[exp03:{mode}] {idx}/{len(task_specs)} "
                    f"{topic_cfg.get('topic_id', '')} q{seq}"
                )
                try:
                    results.append(await run_one(topic_cfg, seq))
                except Exception as exc:
                    print(f"  generation exception: {exc!r}")
                    results.append(exc)
            return results

        semaphore = asyncio.Semaphore(args.concurrency)

        async def guarded(topic_cfg: dict[str, Any], seq: int) -> Any:
            async with semaphore:
                try:
                    return await run_one(topic_cfg, seq)
                except Exception as exc:
                    print(f"  generation exception: {exc!r}")
                    return exc

        return await asyncio.gather(
            *[guarded(topic_cfg, seq) for topic_cfg, seq in task_specs],
            return_exceptions=True,
        )

    print(
        f"\n[exp03] mode={mode} tasks={len(task_specs)} "
        f"concurrency={args.concurrency if mode == 'async' else 1} "
        f"precompute_rag={args.precompute_rag}"
    )
    t0 = time.perf_counter()
    results = await execute()
    generation_wall_time = time.perf_counter() - t0

    accepted = [item for item in results if isinstance(item, dict) and item]
    failed_items = [item for item in results if not (isinstance(item, dict) and item)]

    total_with_rag = generation_wall_time + (rag_precompute_time_s if args.precompute_rag else 0.0)
    summary = {
        "run_id": args.run_id,
        "experiment": "exp03_pipeline_sequential_vs_async",
        "label": args.label,
        "mode": mode,
        "base_url": args.base_url,
        "model": args.model,
        "target_mcqs": len(task_specs),
        "accepted": len(accepted),
        "failed": len(task_specs) - len(accepted),
        "concurrency": args.concurrency if mode == "async" else 1,
        "topic_limit": args.topic_limit,
        "questions_per_topic": args.questions_per_topic,
        "retrieval_mode": args.retrieval_mode,
        "precompute_rag": args.precompute_rag,
        "enable_llm_eval": args.enable_llm_eval,
        "rag_precompute_time_s": round(rag_precompute_time_s, 4),
        "generation_wall_time_s": round(generation_wall_time, 4),
        "total_wall_time_with_rag_s": round(total_with_rag, 4),
        "mcq_per_min_generation": round(safe_div(len(accepted), generation_wall_time) * 60, 4),
        "mcq_per_min_total": round(safe_div(len(accepted), total_with_rag) * 60, 4),
        "failure_examples": "; ".join(
            repr(item)[:160] if isinstance(item, Exception) else str(item)[:160]
            for item in failed_items[:3]
        ),
    }
    print_summary(summary)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("\n=== SUMMARY ===")
    for key in [
        "label",
        "mode",
        "target_mcqs",
        "accepted",
        "failed",
        "concurrency",
        "rag_precompute_time_s",
        "generation_wall_time_s",
        "total_wall_time_with_rag_s",
        "mcq_per_min_generation",
        "mcq_per_min_total",
    ]:
        print(f"{key}: {summary.get(key)}")


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"sequential": 0, "async": 1}
    return sorted(rows, key=lambda row: order.get(row.get("mode", ""), 99))


def render_svg(rows: list[dict[str, str]], output_path: Path, title: str) -> None:
    ensure_dir(output_path.parent)
    width = 1320
    height = 780
    bg = "#f8fafc"
    panel = "#ffffff"
    text = "#0f172a"
    muted = "#64748b"
    grid = "#dbe4f0"
    blue = "#2563eb"
    green = "#059669"
    orange = "#f97316"
    red = "#dc2626"

    seq = next((row for row in rows if row.get("mode") == "sequential"), None)
    async_row = next((row for row in rows if row.get("mode") == "async"), None)
    seq_time = numeric(seq or {}, "generation_wall_time_s")
    async_time = numeric(async_row or {}, "generation_wall_time_s")
    speedup = safe_div(seq_time, async_time)

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
        max_v = max(values) if values else 1.0
        if max_v <= 0:
            max_v = 1.0
        inner_x = x + 70
        inner_y = y + 78
        inner_w = w - 116
        inner_h = h - 132
        gap = 52
        bar_w = max(60, (inner_w - gap * (len(rows) - 1)) / max(1, len(rows)))
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{panel}" stroke="#e2e8f0"/>',
            f'<text x="{x + 28}" y="{y + 42}" font-size="24" font-weight="800" fill="{text}">{html.escape(heading)}</text>',
            f'<line x1="{inner_x}" y1="{inner_y + inner_h}" x2="{inner_x + inner_w}" y2="{inner_y + inner_h}" stroke="{grid}"/>',
        ]
        for i in range(1, 5):
            gy = inner_y + inner_h - inner_h * i / 4
            parts.append(f'<line x1="{inner_x}" y1="{gy:.1f}" x2="{inner_x + inner_w}" y2="{gy:.1f}" stroke="{grid}" stroke-dasharray="4 8"/>')
        mean_value = statistics.mean(values) if values else 0
        for i, row in enumerate(rows):
            value = numeric(row, metric)
            bar_h = inner_h * value / max_v
            bx = inner_x + i * (bar_w + gap)
            by = inner_y + inner_h - bar_h
            fill = color
            if lower_is_better:
                fill = green if value <= mean_value else orange
            if metric.startswith("mcq_per_min") and row.get("mode") == "async":
                fill = green
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="10" fill="{fill}"/>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{by - 12:.1f}" text-anchor="middle" font-size="17" font-weight="800" fill="{text}">{value:.2f}{suffix}</text>')
            parts.append(f'<text x="{bx + bar_w / 2:.1f}" y="{inner_y + inner_h + 34:.1f}" text-anchor="middle" font-size="16" fill="{muted}">{html.escape(row.get("mode", ""))}</text>')
        return "\n".join(parts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
        f'<text x="54" y="68" font-size="34" font-weight="900" fill="{text}">{html.escape(title)}</text>',
        f'<text x="54" y="104" font-size="18" fill="{muted}">Full project pipeline: same RAG cache and MCQ tasks, different execution mode.</text>',
        f'<rect x="990" y="40" width="278" height="92" rx="18" fill="#dcfce7" stroke="#bbf7d0"/>',
        f'<text x="1018" y="78" font-size="18" font-weight="800" fill="#166534">Generation speedup</text>',
        f'<text x="1018" y="116" font-size="32" font-weight="900" fill="#15803d">{speedup:.2f}x</text>',
        bar_chart(54, 164, 584, 250, "generation_wall_time_s", "Generation wall time", orange, "s", True),
        bar_chart(682, 164, 584, 250, "mcq_per_min_generation", "Accepted MCQs per minute", blue, ""),
        bar_chart(54, 456, 584, 250, "total_wall_time_with_rag_s", "Total wall time with RAG", red, "s", True),
        bar_chart(682, 456, 584, 250, "mcq_per_min_total", "Total MCQs per minute", green, ""),
        "</svg>",
    ]
    write_text(output_path, "\n".join(svg))


def render_png(rows: list[dict[str, str]], output_path: Path, title: str) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False

    ensure_dir(output_path.parent)
    labels = [row.get("mode", "") for row in rows]
    metrics = [
        ("generation_wall_time_s", "Generation wall time (s)", "#f97316"),
        ("mcq_per_min_generation", "Accepted MCQs/min", "#2563eb"),
        ("total_wall_time_with_rag_s", "Total wall time with RAG (s)", "#dc2626"),
        ("mcq_per_min_total", "Total MCQs/min", "#059669"),
    ]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5))
    fig.patch.set_facecolor("#f8fafc")
    fig.suptitle(title, fontsize=20, fontweight="bold", color="#0f172a", y=0.98)

    for ax, (metric, heading, color) in zip(axes.flatten(), metrics):
        values = [numeric(row, metric) for row in rows]
        bars = ax.bar(labels, values, color=color, alpha=0.92, width=0.55)
        ax.set_title(heading, fontsize=13, fontweight="bold", color="#0f172a")
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


def write_report(rows: list[dict[str, Any]], args: argparse.Namespace, visual_path: Path) -> Path:
    report_path = Path(args.results_dir) / f"report_{args.label}_{args.run_id}.md"
    seq = next((row for row in rows if row.get("mode") == "sequential"), None)
    async_row = next((row for row in rows if row.get("mode") == "async"), None)
    seq_gen = numeric(seq or {}, "generation_wall_time_s")
    async_gen = numeric(async_row or {}, "generation_wall_time_s")
    seq_total = numeric(seq or {}, "total_wall_time_with_rag_s")
    async_total = numeric(async_row or {}, "total_wall_time_with_rag_s")

    lines = [
        "# Experiment 03 - Full Pipeline Sequential vs Async + vLLM",
        "",
        "## Config",
        "",
        f"- Run ID: `{args.run_id}`",
        f"- Label: `{args.label}`",
        f"- Base URL: `{args.base_url}`",
        f"- Model: `{args.model}`",
        f"- Modes: `{args.modes}`",
        f"- Topic limit: `{args.topic_limit}`",
        f"- Questions per topic: `{args.questions_per_topic}`",
        f"- Async concurrency: `{args.concurrency}`",
        f"- Retrieval mode: `{args.retrieval_mode}`",
        f"- Precompute RAG: `{args.precompute_rag}`",
        f"- LLM eval enabled: `{args.enable_llm_eval}`",
        "",
        "## Results",
        "",
        "| Mode | Target MCQs | Accepted | Failed | Concurrency | RAG precompute (s) | Generation wall time (s) | Total with RAG (s) | MCQs/min generation | MCQs/min total |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {mode} | {target_mcqs} | {accepted} | {failed} | {concurrency} | "
            "{rag_precompute_time_s} | {generation_wall_time_s} | {total_wall_time_with_rag_s} | "
            "{mcq_per_min_generation} | {mcq_per_min_total} |".format(**row)
        )
    lines.extend(["", "## Speedup", ""])
    if seq and async_row:
        lines.append(f"- Generation-only speedup: `{safe_div(seq_gen, async_gen):.2f}x`.")
        lines.append(f"- Total-with-RAG speedup: `{safe_div(seq_total, async_total):.2f}x`.")
    else:
        lines.append("- Need both sequential and async rows to compute speedup.")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This experiment uses the real MCQ pipeline, so it includes prompt construction, JSON parsing, RAG context, and multiple LLM calls per MCQ.",
            "- `generation_wall_time_s` is the cleanest number for showing vLLM + async serving benefit because RAG is precomputed once.",
            "- `total_wall_time_with_rag_s` is useful for end-to-end reporting because it adds the RAG precompute time back.",
            "- If speedup is smaller than Experiment 2, the remaining time is likely retrieval/reranking, pipeline dependencies P1-P8, JSON parsing, and quality checks.",
            "",
            "## Visualization",
            "",
        ]
    )
    lines.append(f"- [{visual_path.name}]({visual_path.name})")
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


def generate_visuals_and_report(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    results_dir = Path(args.results_dir)
    rows = sort_rows(rows)
    if not rows:
        print("[exp03] No result rows found; skipping report.")
        return

    title = f"MCQGen Pipeline Benchmark - {args.label}"
    svg_path = results_dir / f"pipeline_sequential_vs_async_{args.label}_{args.run_id}.svg"
    render_svg(rows, svg_path, title)
    report_path = write_report(rows, args, svg_path)

    print("\n[artifacts]")
    print(f"  svg:    {rel(svg_path)}")
    print(f"  report: {rel(report_path)}")


async def run(args: argparse.Namespace) -> None:
    args.results_dir = str(ensure_dir(Path(args.results_dir)))
    args.run_id = args.run_id or now_id()
    args.modes_list = parse_modes(args.modes)

    collect_preflight(args)
    pipeline_mcq = import_pipeline(args)
    topics = load_pipeline_topics(args, pipeline_mcq)
    task_specs = build_task_specs(topics)
    if not task_specs:
        raise SystemExit("No pipeline tasks selected.")

    rag_cache, rag_time = await precompute_rag_cache(
        args=args,
        pipeline_mcq=pipeline_mcq,
        task_specs=task_specs,
    )

    summaries = []
    for mode in args.modes_list:
        summaries.append(
            await run_one_mode(
                args=args,
                pipeline_mcq=pipeline_mcq,
                mode=mode,
                task_specs=task_specs,
                rag_cache=rag_cache,
                rag_precompute_time_s=rag_time,
            )
        )
    generate_visuals_and_report(args, summaries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Experiment 03: full pipeline sequential vs async + vLLM."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--label", default="pipeline_vllm")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--modes", default="sequential,async")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--topic-limit", type=int, default=2)
    parser.add_argument("--questions-per-topic", type=int, default=1)
    parser.add_argument("--topics-json", default="")
    parser.add_argument("--retrieval-mode", choices=["fast", "auto", "quality"], default="auto")
    parser.add_argument("--precompute-rag", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-llm-eval", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--http-timeout", type=float, default=10.0)
    args = parser.parse_args()

    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be positive")
    if args.topic_limit < 0:
        raise SystemExit("--topic-limit must be >= 0")
    if args.questions_per_topic is not None and args.questions_per_topic <= 0:
        raise SystemExit("--questions-per-topic must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
