#!/usr/bin/env python3
"""
validate_data_pipeline.py — Kiểm thử (validate) dữ liệu của pipeline MCQGen.

Mục tiêu (bài thực hành mục 5.3 — Data validation):
  Sau khi chạy `dvc repro` (transcript_chunking -> indexing), script này kiểm tra
  tính hợp lệ của dữ liệu input và các artifact JSONL đầu ra, rồi tự sinh
  `reports/data_validation_report.md` với số liệu thật.

Các rule được kiểm tra:
  [INPUT]
    - Thư mục input/transcribe_data có file JSON.
    - input/videos1.txt tồn tại.
    - input/slide có file PDF (cảnh báo nếu trống).
    - Mỗi transcript JSON parse được và có "segments".
    - (Tuỳ chọn) Slide PDF mở được bằng PyMuPDF.
  [JSONL OUTPUT] — cho cả transcript_chunks_with_timestamps.jsonl và concept_chunks.jsonl
    - Mỗi dòng là JSON hợp lệ.
    - Mỗi chunk có đủ field bắt buộc: chunk_id, chapter_id, source_type, text.
    - text không rỗng.
    - Độ dài chunk (số từ) nằm trong ngưỡng hợp lý.
    - Không trùng chunk_id.
    - Tỷ lệ transcript chunk có timestamp và youtube_url.

Cách dùng:
    python scripts/validate_data_pipeline.py
    python scripts/validate_data_pipeline.py --report reports/data_validation_report.md
    python scripts/validate_data_pipeline.py --processed-dir data/processed --input-dir input

Exit code:
    0  = không có lỗi nghiêm trọng (chỉ có thể có WARNING)
    1  = có ít nhất một ERROR
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

# ─── Ngưỡng kiểm tra (chỉnh tại đây nếu cần) ──────────────────────────────────
REQUIRED_FIELDS = ("chunk_id", "chapter_id", "source_type", "text")
WORD_COUNT_MIN_ERROR = 3      # < 3 từ coi như chunk hỏng -> ERROR
WORD_COUNT_MIN_WARN = 20      # < 20 từ -> WARNING
WORD_COUNT_MAX_WARN = 600     # > 600 từ -> WARNING (có thể dedup/chunk sai)


def find_repo_root(start: Path) -> Path:
    """scripts/validate_data_pipeline.py -> repo root là thư mục cha của scripts/."""
    return start.resolve().parent.parent


def detect_dir(root: Path, rel: str) -> Path:
    """Ưu tiên <root>/<rel>, fallback <root>/src/mcqgen/<rel> (do Config có thể trỏ vào src/mcqgen)."""
    cand1 = root / rel
    cand2 = root / "src" / "mcqgen" / rel
    if cand1.exists():
        return cand1
    if cand2.exists():
        return cand2
    return cand1  # mặc định trả về cand1 để báo "không tồn tại" rõ ràng


class Validator:
    def __init__(self, input_dir: Path, processed_dir: Path, check_pdf: bool):
        self.input_dir = input_dir
        self.processed_dir = processed_dir
        self.check_pdf = check_pdf
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: dict[str, object] = {}

    # ── helpers ────────────────────────────────────────────────────────────
    def err(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"  [ERROR] {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  [WARN ] {msg}")

    def ok(self, msg: str) -> None:
        print(f"  [ OK  ] {msg}")

    @staticmethod
    def _word_count(text: str) -> int:
        return len((text or "").split())

    # ── 1. INPUT ───────────────────────────────────────────────────────────
    def validate_inputs(self) -> None:
        print("\n=== 1. INPUT FILES ===")
        transcribe_dir = self.input_dir / "transcribe_data"
        videos_file = self.input_dir / "videos1.txt"
        slide_dir = self.input_dir / "slide"

        json_files = sorted(transcribe_dir.glob("*.json")) if transcribe_dir.exists() else []
        self.info["n_transcript_json"] = len(json_files)
        if not transcribe_dir.exists():
            self.err(f"Thiếu thư mục transcript: {transcribe_dir}")
        elif not json_files:
            self.err(f"Không có file JSON trong {transcribe_dir}")
        else:
            self.ok(f"{len(json_files)} transcript JSON trong {transcribe_dir}")

        if videos_file.exists():
            self.ok(f"videos1.txt tồn tại ({videos_file.stat().st_size} bytes)")
        else:
            self.warn(f"Thiếu {videos_file} -> youtube_url của transcript sẽ rỗng")
        self.info["videos_txt_exists"] = videos_file.exists()

        pdf_files = sorted(slide_dir.glob("*.pdf")) if slide_dir.exists() else []
        self.info["n_slide_pdf"] = len(pdf_files)
        if not pdf_files:
            self.warn(f"Không thấy slide PDF trong {slide_dir} "
                      f"(slide thường do DVC quản lý — bỏ qua nếu chạy DVC pull trước)")
        else:
            self.ok(f"{len(pdf_files)} slide PDF trong {slide_dir}")

        # Parse từng transcript JSON
        bad_json = 0
        empty_segments = 0
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:
                bad_json += 1
                self.err(f"Transcript JSON lỗi parse: {jf.name} ({exc})")
                continue
            if not data.get("segments"):
                empty_segments += 1
                self.warn(f"Transcript không có 'segments': {jf.name}")
        if json_files and bad_json == 0:
            self.ok(f"Tất cả {len(json_files)} transcript JSON parse được")
        self.info["transcript_json_parse_errors"] = bad_json
        self.info["transcript_json_empty_segments"] = empty_segments

        # Slide PDF readable (tuỳ chọn)
        if self.check_pdf and pdf_files:
            try:
                import fitz  # PyMuPDF
                unreadable = 0
                for pf in pdf_files:
                    try:
                        doc = fitz.open(str(pf))
                        _ = doc.page_count
                        doc.close()
                    except Exception as exc:
                        unreadable += 1
                        self.err(f"Slide PDF không mở được: {pf.name} ({exc})")
                if unreadable == 0:
                    self.ok(f"Tất cả {len(pdf_files)} slide PDF mở được bằng PyMuPDF")
            except ImportError:
                self.warn("Chưa cài PyMuPDF (fitz) — bỏ qua kiểm tra đọc slide PDF")

    # ── 2. JSONL artifact ──────────────────────────────────────────────────
    def validate_jsonl(self, path: Path, label: str, expect_timestamps: bool) -> None:
        print(f"\n=== 2. JSONL: {label} ===")
        stats: dict[str, object] = {"path": str(path), "exists": path.exists()}
        if not path.exists():
            self.warn(f"Chưa có file {path} (chạy `dvc repro` để sinh ra trước khi validate đầy đủ)")
            self.info[label] = stats
            return

        n_lines = 0
        n_bad_json = 0
        n_empty_text = 0
        missing_field_counts: Counter = Counter()
        word_counts: list[int] = []
        chunk_ids: list[str] = []
        source_types: Counter = Counter()
        n_with_timestamp = 0
        n_with_youtube = 0
        n_transcript = 0

        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                n_lines += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    n_bad_json += 1
                    continue

                for fld in REQUIRED_FIELDS:
                    if fld not in rec or rec.get(fld) in (None, ""):
                        # text rỗng đếm riêng để rõ nghĩa
                        if fld == "text" and (rec.get("text") in (None, "")):
                            continue
                        missing_field_counts[fld] += 1

                text = rec.get("text", "")
                if text in (None, ""):
                    n_empty_text += 1
                else:
                    word_counts.append(self._word_count(text))

                if rec.get("chunk_id"):
                    chunk_ids.append(rec["chunk_id"])

                stype = rec.get("source_type", "")
                source_types[stype] += 1
                if stype == "video_transcript":
                    n_transcript += 1
                    ts = rec.get("timestamp_start")
                    if ts is not None and ts != "":
                        n_with_timestamp += 1
                    if rec.get("youtube_url"):
                        n_with_youtube += 1

        # ── đánh giá ──
        stats["n_lines"] = n_lines
        stats["n_bad_json"] = n_bad_json
        stats["n_empty_text"] = n_empty_text
        stats["source_types"] = dict(source_types)
        stats["missing_fields"] = dict(missing_field_counts)

        if n_lines == 0:
            self.err(f"{label}: file rỗng (0 dòng)")
            self.info[label] = stats
            return
        self.ok(f"{label}: {n_lines} dòng")

        if n_bad_json:
            self.err(f"{label}: {n_bad_json} dòng KHÔNG parse được JSON")
        else:
            self.ok(f"{label}: tất cả dòng đều là JSON hợp lệ")

        if missing_field_counts:
            for fld, cnt in missing_field_counts.items():
                self.err(f"{label}: {cnt} chunk thiếu field bắt buộc '{fld}'")
        else:
            self.ok(f"{label}: mọi chunk đều có đủ {list(REQUIRED_FIELDS)}")

        if n_empty_text:
            self.err(f"{label}: {n_empty_text} chunk có text rỗng")
        else:
            self.ok(f"{label}: không có chunk text rỗng")

        # duplicate chunk_id
        dup = [cid for cid, c in Counter(chunk_ids).items() if c > 1]
        stats["n_duplicate_chunk_id"] = len(dup)
        if dup:
            sample = ", ".join(dup[:5])
            self.err(f"{label}: {len(dup)} chunk_id bị trùng (vd: {sample})")
        else:
            self.ok(f"{label}: chunk_id không trùng ({len(chunk_ids)} id)")

        # word-count range
        if word_counts:
            wmin, wmax = min(word_counts), max(word_counts)
            wavg = statistics.mean(word_counts)
            wmed = statistics.median(word_counts)
            stats["word_count"] = {
                "min": wmin, "max": wmax,
                "avg": round(wavg, 1), "median": round(wmed, 1),
            }
            self.ok(f"{label}: word_count min={wmin} avg={wavg:.0f} median={wmed:.0f} max={wmax}")
            too_short = sum(1 for w in word_counts if w < WORD_COUNT_MIN_ERROR)
            short = sum(1 for w in word_counts if WORD_COUNT_MIN_ERROR <= w < WORD_COUNT_MIN_WARN)
            too_long = sum(1 for w in word_counts if w > WORD_COUNT_MAX_WARN)
            stats["n_below_error"] = too_short
            stats["n_below_warn"] = short
            stats["n_above_warn"] = too_long
            if too_short:
                self.err(f"{label}: {too_short} chunk < {WORD_COUNT_MIN_ERROR} từ (gần như rỗng)")
            if short:
                self.warn(f"{label}: {short} chunk < {WORD_COUNT_MIN_WARN} từ (ngắn bất thường)")
            if too_long:
                self.warn(f"{label}: {too_long} chunk > {WORD_COUNT_MAX_WARN} từ (dài bất thường)")

        # transcript coverage
        if expect_timestamps and n_transcript:
            ts_rate = n_with_timestamp / n_transcript
            yt_rate = n_with_youtube / n_transcript
            stats["n_transcript"] = n_transcript
            stats["timestamp_rate"] = round(ts_rate, 3)
            stats["youtube_rate"] = round(yt_rate, 3)
            self.ok(f"{label}: {n_transcript} transcript chunk | "
                    f"timestamp {ts_rate:.0%} | youtube_url {yt_rate:.0%}")
            if ts_rate < 0.95:
                self.warn(f"{label}: chỉ {ts_rate:.0%} transcript chunk có timestamp (<95%)")
            if yt_rate < 0.5:
                self.warn(f"{label}: chỉ {yt_rate:.0%} transcript chunk có youtube_url (<50%) "
                          f"— kiểm tra mapping trong videos1.txt")

        self.info[label] = stats

    # ── chạy tất cả ────────────────────────────────────────────────────────
    def run(self) -> None:
        self.validate_inputs()
        self.validate_jsonl(
            self.processed_dir / "transcript_chunks_with_timestamps.jsonl",
            "transcript_chunks_with_timestamps.jsonl",
            expect_timestamps=True,
        )
        self.validate_jsonl(
            self.processed_dir / "concept_chunks.jsonl",
            "concept_chunks.jsonl",
            expect_timestamps=True,
        )


# ─── Sinh report markdown ─────────────────────────────────────────────────────
def render_report(v: Validator, report_path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "FAIL ❌" if v.errors else ("PASS (có cảnh báo) ⚠️" if v.warnings else "PASS ✅")
    lines: list[str] = []
    a = lines.append

    a("# Báo cáo Data Validation")
    a("")
    a(f"- Thời điểm chạy: `{now}`")
    a(f"- Input dir: `{v.input_dir}`")
    a(f"- Processed dir: `{v.processed_dir}`")
    a(f"- Kết quả tổng: **{status}**")
    a(f"- Số ERROR: **{len(v.errors)}** | Số WARNING: **{len(v.warnings)}**")
    a("")
    a("Script: `scripts/validate_data_pipeline.py`. "
      "Chạy lại bằng: `python scripts/validate_data_pipeline.py`.")
    a("")

    a("## 1. Input")
    a("")
    a("| Hạng mục | Giá trị |")
    a("| --- | --- |")
    a(f"| Transcript JSON (`input/transcribe_data/*.json`) | {v.info.get('n_transcript_json', 0)} |")
    a(f"| `input/videos1.txt` tồn tại | {v.info.get('videos_txt_exists', False)} |")
    a(f"| Slide PDF (`input/slide/*.pdf`) | {v.info.get('n_slide_pdf', 0)} |")
    a(f"| Transcript JSON lỗi parse | {v.info.get('transcript_json_parse_errors', 0)} |")
    a(f"| Transcript JSON thiếu `segments` | {v.info.get('transcript_json_empty_segments', 0)} |")
    a("")

    for label in ("transcript_chunks_with_timestamps.jsonl", "concept_chunks.jsonl"):
        st = v.info.get(label, {})
        a(f"## 2. `{label}`")
        a("")
        if not isinstance(st, dict) or not st.get("exists"):
            a("> Chưa có file này. Chạy `dvc repro` để sinh ra rồi validate lại.")
            a("")
            continue
        a("| Chỉ số | Giá trị |")
        a("| --- | --- |")
        a(f"| Số dòng (chunk) | {st.get('n_lines', 0)} |")
        a(f"| Dòng lỗi JSON | {st.get('n_bad_json', 0)} |")
        a(f"| Chunk text rỗng | {st.get('n_empty_text', 0)} |")
        a(f"| chunk_id trùng | {st.get('n_duplicate_chunk_id', 0)} |")
        mf = st.get("missing_fields", {})
        a(f"| Field bắt buộc bị thiếu | {mf if mf else 'không'} |")
        wc = st.get("word_count")
        if wc:
            a(f"| Word count (min/avg/median/max) | {wc['min']} / {wc['avg']} / {wc['median']} / {wc['max']} |")
        if "timestamp_rate" in st:
            a(f"| Transcript chunk | {st.get('n_transcript', 0)} |")
            a(f"| Tỷ lệ có timestamp | {st['timestamp_rate']:.0%} |")
            a(f"| Tỷ lệ có youtube_url | {st['youtube_rate']:.0%} |")
        stp = st.get("source_types", {})
        if stp:
            a(f"| Phân bố source_type | {stp} |")
        a("")

    a("## 3. Danh sách ERROR")
    a("")
    if v.errors:
        for e in v.errors:
            a(f"- ❌ {e}")
    else:
        a("- Không có ERROR.")
    a("")
    a("## 4. Danh sách WARNING")
    a("")
    if v.warnings:
        for w in v.warnings:
            a(f"- ⚠️ {w}")
    else:
        a("- Không có WARNING.")
    a("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📝 Đã ghi report: {report_path}")


def main() -> int:
    root = find_repo_root(Path(__file__))
    parser = argparse.ArgumentParser(description="Validate MCQGen data pipeline.")
    parser.add_argument("--input-dir", default=None, help="Thư mục input (mặc định: auto-detect)")
    parser.add_argument("--processed-dir", default=None, help="Thư mục data/processed (mặc định: auto-detect)")
    parser.add_argument("--report", default=str(root / "reports" / "data_validation_report.md"),
                        help="Đường dẫn file report markdown")
    parser.add_argument("--check-pdf", action="store_true",
                        help="Kiểm tra đọc slide PDF bằng PyMuPDF (cần đã cài fitz)")
    parser.add_argument("--no-report", action="store_true", help="Không ghi file report")
    args = parser.parse_args()

    input_dir = Path(args.input_dir) if args.input_dir else detect_dir(root, "input")
    processed_dir = Path(args.processed_dir) if args.processed_dir else detect_dir(root, "data/processed")

    print("=" * 70)
    print("MCQGen — Data Pipeline Validation")
    print(f"repo root     : {root}")
    print(f"input dir     : {input_dir}")
    print(f"processed dir : {processed_dir}")
    print("=" * 70)

    v = Validator(input_dir, processed_dir, check_pdf=args.check_pdf)
    v.run()

    print("\n" + "=" * 70)
    print(f"TỔNG KẾT: {len(v.errors)} ERROR | {len(v.warnings)} WARNING")
    print("=" * 70)

    if not args.no_report:
        render_report(v, Path(args.report))

    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
