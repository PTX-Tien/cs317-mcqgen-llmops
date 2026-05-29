"""
compare_chunks_v3.py — So sánh Legacy vs Semantic v1 vs v2 vs v3
================================================================
Chạy: python compare_chunks_v3.py

Đọc files:
  - data/processed/chunks_legacy.jsonl       (baseline)
  - data/processed/chunks_semantic.jsonl     (v1)
  - data/processed/chunks_semantic_v2.jsonl  (v2)
  - data/processed/chunks_semantic_v3.jsonl  (v3 — latest)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmarks"

FILES = {
    "Legacy":      PROCESSED_DIR / "chunks_legacy.jsonl",
    "Semantic v1": PROCESSED_DIR / "chunks_semantic.jsonl",
    "Semantic v2": PROCESSED_DIR / "chunks_semantic_v2.jsonl",
    "Semantic v3": PROCESSED_DIR / "chunks_semantic_v3.jsonl",
}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def analyze(chunks: list[dict], label: str) -> dict:
    if not chunks:
        return {"label": label, "count": 0}

    wcs = [c.get("word_count", len(c.get("text", "").split())) for c in chunks]

    # Cắt giữa câu
    cut_mid = 0
    for c in chunks:
        text = c.get("text", "").strip()
        if text and text[-1] not in ".?!。\"'":
            cut_mid += 1

    return {
        "label": label,
        "count": len(chunks),
        "wc_avg": sum(wcs) / len(wcs),
        "wc_min": min(wcs),
        "wc_max": max(wcs),
        "wc_median": sorted(wcs)[len(wcs) // 2],
        "wc_std": (sum((w - sum(wcs)/len(wcs))**2 for w in wcs) / len(wcs)) ** 0.5,
        "under_50": sum(1 for w in wcs if w < 50),
        "under_80": sum(1 for w in wcs if w < 80),
        "over_400": sum(1 for w in wcs if w > 400),
        "over_500": sum(1 for w in wcs if w > 500),
        "cut_mid": cut_mid,
        "cut_mid_pct": cut_mid / len(chunks) * 100,
        "chapters": dict(sorted(Counter(c.get("chapter_id", "?") for c in chunks).items())),
    }


def print_table(datasets: list[dict]):
    labels = [d["label"] for d in datasets if d["count"] > 0]
    col_w = max(14, max(len(l) for l in labels) + 2)

    # Header
    header = f"{'Metric':<28}" + "".join(f"{l:>{col_w}}" for l in labels)
    print(header)
    print("─" * len(header))

    def row(metric, key, fmt=">12.0f"):
        vals = []
        for d in datasets:
            if d["count"] == 0:
                continue
            v = d.get(key, 0)
            vals.append(f"{v:{fmt}}")
        print(f"{metric:<28}" + "".join(f"{v:>{col_w}}" for v in vals))

    row("Tổng chunks",          "count",      ">12")
    row("Avg words/chunk",      "wc_avg",     ">12.0f")
    row("Min words",            "wc_min",     ">12")
    row("Max words",            "wc_max",     ">12")
    row("Median words",         "wc_median",  ">12")
    row("Std dev",              "wc_std",     ">12.0f")
    row("Chunks < 50 words",    "under_50",   ">12")
    row("Chunks < 80 words",    "under_80",   ">12")
    row("Chunks > 400 words",   "over_400",   ">12")
    row("Chunks > 500 words",   "over_500",   ">12")
    row("Cắt giữa câu",        "cut_mid",    ">12")
    row("  (% tổng)",           "cut_mid_pct",">11.0f")

    # Per chapter
    all_chs = sorted(set(
        ch for d in datasets if d["count"] > 0
        for ch in d.get("chapters", {}).keys()
    ))
    if all_chs:
        print(f"\n{'Chapter':<12}" + "".join(f"{l:>{col_w}}" for l in labels))
        print("─" * (12 + col_w * len(labels)))
        for ch in all_chs:
            vals = []
            for d in datasets:
                if d["count"] == 0:
                    continue
                vals.append(f"{d.get('chapters', {}).get(ch, 0):>{col_w}}")
            print(f"{ch:<12}" + "".join(vals))


def save_report(datasets: list[dict]):
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    out = BENCHMARK_DIR / "chunk_comparison_v3_report.md"

    lines = ["# So sánh Chunks: Legacy vs Semantic v1 vs v2 vs v3\n"]
    lines.append("## Tổng quan\n")
    lines.append("| Metric | " + " | ".join(d["label"] for d in datasets if d["count"] > 0) + " |")
    lines.append("|--------|" + "|".join("--------" for d in datasets if d["count"] > 0) + "|")

    active = [d for d in datasets if d["count"] > 0]
    metrics = [
        ("Tổng chunks",       "count",     ".0f"),
        ("Avg words",         "wc_avg",    ".0f"),
        ("Min words",         "wc_min",    ".0f"),
        ("Max words",         "wc_max",    ".0f"),
        ("Std dev",           "wc_std",    ".0f"),
        ("Chunks < 50w",      "under_50",  ".0f"),
        ("Chunks < 80w",      "under_80",  ".0f"),
        ("Chunks > 400w",     "over_400",  ".0f"),
        ("Cắt giữa câu (%)", "cut_mid_pct",".0f"),
    ]
    for name, key, fmt in metrics:
        vals = " | ".join(f"{d.get(key, 0):{fmt}}" for d in active)
        lines.append(f"| {name} | {vals} |")

    # Verdict
    lines.append("\n## Đánh giá v3 vs v2\n")
    v1 = next((d for d in datasets if d["label"] == "Semantic v1" and d["count"] > 0), None)
    v2 = next((d for d in datasets if d["label"] == "Semantic v2" and d["count"] > 0), None)
    v3 = next((d for d in datasets if d["label"] == "Semantic v3" and d["count"] > 0), None)
    legacy = next((d for d in datasets if d["label"] == "Legacy" and d["count"] > 0), None)

    compare_target = v3 or v2  # use latest available

    if compare_target and v2 and compare_target is not v2:
        checks = [
            ("Chunks < 50w", v2["under_50"], compare_target["under_50"], True),
            ("Chunks < 80w", v2["under_80"], compare_target["under_80"], True),
            ("Chunks > 400w", v2["over_400"], compare_target["over_400"], True),
            ("Max words", v2["wc_max"], compare_target["wc_max"], True),
            ("Std dev", v2["wc_std"], compare_target["wc_std"], True),
            ("Cắt giữa câu %", v2["cut_mid_pct"], compare_target["cut_mid_pct"], True),
        ]
        for name, old, new, lower_is_better in checks:
            improved = new < old if lower_is_better else new > old
            icon = "✅" if improved else "⚠️"
            lines.append(f"- {icon} {name}: {old:.0f} → {new:.0f}")

    if compare_target and legacy:
        lines.append(f"\n## Đánh giá {compare_target['label']} vs Legacy\n")
        checks = [
            ("Chunks < 80w", legacy["under_80"], compare_target["under_80"], True),
            ("Chunks > 400w", legacy["over_400"], compare_target["over_400"], True),
            ("Cắt giữa câu %", legacy["cut_mid_pct"], compare_target["cut_mid_pct"], True),
            ("Std dev", legacy["wc_std"], compare_target["wc_std"], True),
        ]
        for name, old, new, lower_is_better in checks:
            improved = new < old if lower_is_better else new > old
            icon = "✅" if improved else "⚠️"
            lines.append(f"- {icon} {name}: {old:.0f} → {new:.0f}")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ Report: {out}")


def main():
    print("═══ So sánh Chunks: Legacy vs Semantic v1 vs v2 ═══\n")

    datasets = []
    for label, path in FILES.items():
        chunks = load_jsonl(path)
        if chunks:
            print(f"📂 {label}: {path.name} → {len(chunks)} chunks")
        else:
            print(f"⚠️  {label}: {path.name} → không tìm thấy")
        datasets.append(analyze(chunks, label))

    active = [d for d in datasets if d["count"] > 0]
    if len(active) < 2:
        print("\n❌ Cần ít nhất 2 files để so sánh.")
        print("\nCách tạo:")
        print("  1. chunks_legacy.jsonl      — đã có từ lần chạy trước")
        print("  2. chunks_semantic.jsonl     — đã có từ lần chạy trước")
        print("  3. chunks_semantic_v2.jsonl  — từ lần chạy trước")
        print("  4. chunks_semantic_v3.jsonl  — chạy:")
        print("     CHUNKING_MODE=semantic python -m src.mcqgen.chunk_transcripts")
        print("     cp data/processed/transcript_chunks_with_timestamps.jsonl data/processed/chunks_semantic_v3.jsonl")
        sys.exit(0)

    print()
    print_table(datasets)

    # Quick verdict
    v1 = next((d for d in datasets if d["label"] == "Semantic v1" and d["count"] > 0), None)
    v2 = next((d for d in datasets if d["label"] == "Semantic v2" and d["count"] > 0), None)
    legacy = next((d for d in datasets if d["label"] == "Legacy" and d["count"] > 0), None)

    print("\n═══ Đánh giá nhanh ═══")

    v3 = next((d for d in datasets if d["label"] == "Semantic v3" and d["count"] > 0), None)
    compare_target = v3 or v2  # latest

    if compare_target and v2 and compare_target is not v2:
        print(f"\n[{compare_target['label']} vs Semantic v2]")
        if compare_target["under_50"] < v2["under_50"]:
            print(f"  ✅ Chunks < 50w: {v2['under_50']} → {compare_target['under_50']}")
        if compare_target["under_80"] < v2["under_80"]:
            print(f"  ✅ Chunks < 80w: {v2['under_80']} → {compare_target['under_80']}")
        if compare_target["over_400"] < v2["over_400"]:
            print(f"  ✅ Chunks > 400w: {v2['over_400']} → {compare_target['over_400']}")
        if compare_target["wc_max"] < v2["wc_max"]:
            print(f"  ✅ Max words: {v2['wc_max']} → {compare_target['wc_max']}")
        if compare_target["wc_std"] < v2["wc_std"]:
            print(f"  ✅ Std dev: {v2['wc_std']:.0f} → {compare_target['wc_std']:.0f}")
        if compare_target["cut_mid_pct"] < v2["cut_mid_pct"]:
            print(f"  ✅ Cắt giữa câu: {v2['cut_mid_pct']:.0f}% → {compare_target['cut_mid_pct']:.0f}%")

    if compare_target and legacy:
        print(f"\n[{compare_target['label']} vs Legacy]")
        if compare_target["cut_mid_pct"] < legacy["cut_mid_pct"]:
            print(f"  ✅ Cắt giữa câu: {legacy['cut_mid_pct']:.0f}% → {compare_target['cut_mid_pct']:.0f}%")
        else:
            print(f"  ⚠️ Cắt giữa câu: {legacy['cut_mid_pct']:.0f}% → {compare_target['cut_mid_pct']:.0f}%")
        if compare_target["under_80"] == 0:
            print(f"  ✅ Không có chunk < 80 words")
        if compare_target["over_400"] == 0:
            print(f"  ✅ Không có chunk > 400 words")

    save_report(datasets)


if __name__ == "__main__":
    main()