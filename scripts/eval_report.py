#!/usr/bin/env python3
"""
eval_report.py — Sinh báo cáo evaluation cho hệ thống MCQGen.

Mục tiêu (bài thực hành mục 5.7 — Evaluation report):
  Sau khi đã generate ít nhất một đề (qua UI hoặc API /generate), script đọc kết quả
  đã được persist trong SQLite `data/mcqgen.db` (bảng `exam`/`question`) và tổng hợp:
    - cấu hình run (model, retrieval mode, prompt version, số câu, chapters/topics);
    - kết quả: requested / accepted / rejected / acceptance_rate;
    - rejection reasons & stages (P1/P4/P8/opening_check/final_eval/dedup_history);
    - duplicate rate trong các câu được chấp nhận;
    - trạng thái PDF export (tuỳ chọn smoke test).
  Sau đó ghi `reports/eval_results.md`.

  Các con số này khớp với Langfuse scores do `api/tasks.py` emit:
    accepted_questions, failed_questions, acceptance_rate, reject_stage.<stage>, job_failed.

Cách dùng:
    # tự lấy đề success gần nhất
    python scripts/eval_report.py --latest

    # chỉ định đúng task_id
    python scripts/eval_report.py --task-id <TASK_ID>

    # liệt kê các đề gần đây rồi thoát
    python scripts/eval_report.py --list

    # kèm smoke test xuất PDF cho đề đã chọn
    python scripts/eval_report.py --latest --check-pdf
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path


# ─── Phân loại reason -> nhóm (để phục vụ phần phân tích) ─────────────────────
REASON_BUCKET = {
    "json_parse_error":             "Lỗi định dạng JSON (model trả output sai format)",
    "missing_candidate_distractors": "Thiếu / không đủ distractor (stage P4)",
    "llm_eval_rejected":            "Bị final eval / guardrail loại (relevance, chất lượng)",
    "opening_repair_failed":        "Opening style xấu, sửa không đạt",
    "duplicate_question":           "Trùng câu đã sinh (dedup theo lịch sử)",
    "generation_exception":         "Exception khi sinh câu",
}

# Câu hỏi phân tích trong bài thực hành -> stage/reason tương ứng
ANALYSIS_QUESTIONS = [
    ("Reject do JSON format?",            lambda s, r: r == "json_parse_error"),
    ("Reject do distractor?",             lambda s, r: r == "missing_candidate_distractors"),
    ("Reject do relevance / RAG context?", lambda s, r: r == "llm_eval_rejected"),
    ("Reject do opening style?",          lambda s, r: s == "opening_check"),
    ("Reject do trùng câu (dedup)?",      lambda s, r: r == "duplicate_question"),
]


def find_repo_root(start: Path) -> Path:
    return start.resolve().parent.parent


def detect_db(root: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    for cand in (root / "data" / "mcqgen.db", root / "src" / "mcqgen" / "data" / "mcqgen.db"):
        if cand.exists():
            return cand
    return root / "data" / "mcqgen.db"


def _resolve_table(conn: sqlite3.Connection, wanted: str) -> str | None:
    """Tìm tên bảng không phân biệt hoa thường (SQLModel hay dùng tên lớp viết thường)."""
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = [r[0] for r in rows]
    for n in names:
        if n.lower() == wanted.lower():
            return n
    return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().split())


def list_exams(conn: sqlite3.Connection, exam_tbl: str, limit: int = 15) -> None:
    cols = "task_id, exam_name, status, requested_questions, accepted_questions, failed_questions, prompt_version, created_at"
    rows = conn.execute(
        f"SELECT {cols} FROM {exam_tbl} ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    print(f"\n{'created_at':<22} {'status':<8} {'acc/req':<9} {'task_id':<38} exam_name")
    print("-" * 110)
    for r in rows:
        task_id, name, status, req, acc, fail, pv, created = r
        print(f"{str(created):<22} {str(status):<8} {f'{acc}/{req}':<9} {str(task_id):<38} {name}")
    print()


def fetch_exam(conn: sqlite3.Connection, exam_tbl: str, task_id: str | None, latest: bool) -> dict | None:
    base = f"SELECT * FROM {exam_tbl}"
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if task_id:
        row = cur.execute(base + " WHERE task_id = ?", (task_id,)).fetchone()
    elif latest:
        row = cur.execute(
            base + " WHERE status = 'success' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:  # fallback: bất kỳ đề nào mới nhất
            row = cur.execute(base + " ORDER BY created_at DESC LIMIT 1").fetchone()
    else:
        return None
    return dict(row) if row else None


def fetch_questions(conn: sqlite3.Connection, q_tbl: str, exam_id: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {q_tbl} WHERE exam_id = ?", (exam_id,)).fetchall()
    return [dict(r) for r in rows]


def smoke_test_pdf(root: Path, exam: dict, questions: list[dict]) -> tuple[str, str]:
    """Thử import pdf_exporter và sinh 1 PDF tạm. Trả về (status, chi tiết)."""
    try:
        import importlib
        import sys
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        mod = importlib.import_module("api.pdf_exporter")
    except Exception as exc:  # pragma: no cover
        return "SKIP", f"không import được api.pdf_exporter ({exc}); kiểm tra thủ công bằng API /export/pdf/{{task_id}}"

    # Tìm 1 hàm export khả dĩ
    fn = None
    for name in ("export_exam_to_pdf", "export_to_pdf", "build_pdf", "generate_pdf", "export_pdf"):
        if hasattr(mod, name):
            fn = getattr(mod, name)
            break
    if fn is None:
        return "SKIP", "không tìm thấy hàm export trong api.pdf_exporter; kiểm tra thủ công qua API"
    try:
        out = root / "reports" / f"_pdf_smoke_{exam.get('task_id','x')}.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Nhiều chữ ký khác nhau — thử vài cách gọi phổ biến, không fail cứng
        try:
            fn(questions, str(out))
        except TypeError:
            fn(exam, questions, str(out))
        ok = out.exists() and out.stat().st_size > 0
        return ("OK", f"đã sinh {out.name} ({out.stat().st_size} bytes)") if ok else ("FAILED", "file PDF rỗng")
    except Exception as exc:
        return "FAILED", f"lỗi khi sinh PDF: {exc}"


def build_report(root: Path, exam: dict, questions: list[dict], pdf_status: tuple[str, str] | None) -> str:
    requested = int(exam.get("requested_questions") or 0)
    accepted = int(exam.get("accepted_questions") or 0)
    failed = int(exam.get("failed_questions") or 0)
    if requested == 0:
        requested = accepted + failed
    acceptance_rate = accepted / max(accepted + failed, 1)

    # failures
    try:
        failures = json.loads(exam.get("failure_info_json") or "[]")
        if not isinstance(failures, list):
            failures = []
    except Exception:
        failures = []

    stage_counts = Counter(f.get("stage", "unknown") for f in failures if isinstance(f, dict))
    reason_counts = Counter(f.get("reason", "unknown") for f in failures if isinstance(f, dict))

    # phân tích theo câu hỏi bài thực hành
    analysis_rows = []
    for label, pred in ANALYSIS_QUESTIONS:
        n = sum(
            1 for f in failures
            if isinstance(f, dict) and pred(f.get("stage", ""), f.get("reason", ""))
        )
        analysis_rows.append((label, n))

    # duplicate rate trong câu accepted (theo stem normalize)
    stems = [_normalize(q.get("question_text", "")) for q in questions if q.get("question_text")]
    stem_counts = Counter(stems)
    n_dup = sum(c - 1 for c in stem_counts.values() if c > 1)
    dup_rate = n_dup / max(len(stems), 1)

    # phân bố
    by_diff = Counter(q.get("difficulty", "?") for q in questions)
    by_chapter = Counter(q.get("chapter_id", "?") for q in questions)
    by_strategy = Counter((q.get("rag_strategy") or "?") for q in questions)
    by_type = Counter(q.get("question_type", "?") for q in questions)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L: list[str] = []
    a = L.append

    a("# Báo cáo Evaluation (MCQGen)")
    a("")
    a(f"- Thời điểm sinh báo cáo: `{now}`")
    a(f"- Nguồn dữ liệu: SQLite `data/mcqgen.db` (bảng `exam` + `question`)")
    a(f"- Script: `scripts/eval_report.py`")
    a("")

    a("## 1. Cấu hình run")
    a("")
    a("| Thông tin | Giá trị |")
    a("| --- | --- |")
    a(f"| Task ID | `{exam.get('task_id','')}` |")
    a(f"| Tên đề | {exam.get('exam_name','')} |")
    a(f"| Trạng thái | {exam.get('status','')} |")
    a(f"| Người tạo | {exam.get('created_by','')} |")
    a(f"| Model serving | Qwen2.5-7B-Instruct (vLLM, served-name `mcqgen`) |")
    a(f"| Prompt version | {exam.get('prompt_version','')} |")
    rag_modes = ", ".join(sorted(k for k in by_strategy if k and k != '?')) or "(không ghi nhận)"
    a(f"| RAG strategy ghi nhận trên câu hỏi | {rag_modes} |")
    a(f"| Chapters xuất hiện | {', '.join(sorted(k for k in by_chapter if k and k != '?')) or '(n/a)'} |")
    a(f"| Thời điểm tạo | {exam.get('created_at','')} |")
    a(f"| Thời điểm hoàn tất | {exam.get('completed_at','')} |")
    a("")

    a("## 2. Kết quả tổng quan")
    a("")
    a("| Metric | Giá trị |")
    a("| --- | --- |")
    a(f"| Requested questions | {requested} |")
    a(f"| Accepted questions | {accepted} |")
    a(f"| Rejected / failed questions | {failed} |")
    a(f"| **Acceptance rate** | **{acceptance_rate:.1%}** |")
    qa = exam.get("quality_avg")
    if qa is not None:
        a(f"| Quality score trung bình (accepted) | {float(qa):.3f} |")
    a(f"| Duplicate trong accepted (theo stem) | {n_dup} câu ({dup_rate:.1%}) |")
    if pdf_status is not None:
        a(f"| PDF export (smoke test) | {pdf_status[0]} — {pdf_status[1]} |")
    else:
        a(f"| PDF export | kiểm tra thủ công: `GET /export/pdf/{exam.get('task_id','<task_id>')}` |")
    a("")
    a("> Các con số trên trùng với Langfuse scores: `accepted_questions`, `failed_questions`, "
      "`acceptance_rate` (và `reject_stage.<stage>` ở mục 3).")
    a("")

    a("## 3. Rejection theo stage và reason")
    a("")
    if stage_counts:
        a("**Theo stage** (khớp score `reject_stage.<stage>` trên Langfuse):")
        a("")
        a("| Stage | Số câu bị loại |")
        a("| --- | --- |")
        for stage, cnt in stage_counts.most_common():
            a(f"| `{stage}` | {cnt} |")
        a("")
        a("**Theo reason:**")
        a("")
        a("| Reason | Ý nghĩa | Số câu |")
        a("| --- | --- | --- |")
        for reason, cnt in reason_counts.most_common():
            a(f"| `{reason}` | {REASON_BUCKET.get(reason, '—')} | {cnt} |")
        a("")
    else:
        a("Không có câu nào bị loại trong run này (hoặc `failure_info_json` rỗng).")
        a("")

    a("## 4. Phân tích nguyên nhân reject")
    a("")
    a("| Câu hỏi phân tích | Số câu |")
    a("| --- | --- |")
    for label, n in analysis_rows:
        a(f"| {label} | {n} |")
    a("")

    a("## 5. Phân bố câu hỏi được chấp nhận")
    a("")
    a(f"- Theo độ khó: {dict(by_diff)}")
    a(f"- Theo chương: {dict(by_chapter)}")
    a(f"- Theo loại câu: {dict(by_type)}")
    a(f"- Theo RAG strategy: {dict(by_strategy)}")
    a("")

    a("## 6. Nhận xét & đề xuất cải thiện")
    a("")
    # gợi ý tự động dựa trên stage trội nhất
    suggestions = []
    if reason_counts.get("json_parse_error", 0) > 0:
        suggestions.append("Nhiều câu rớt do `json_parse_error`: siết lại format trong prompt P1/P4/P8 "
                           "(yêu cầu JSON thuần, thêm ví dụ output đúng), hoặc giảm `temperature` cho stage sinh JSON.")
    if reason_counts.get("missing_candidate_distractors", 0) > 0:
        suggestions.append("Rớt ở P4 do thiếu distractor: tăng `NUM_CANDIDATE_DISTRACTORS` hoặc cải thiện prompt "
                           "sinh phương án nhiễu.")
    if reason_counts.get("llm_eval_rejected", 0) > 0:
        suggestions.append("Rớt ở `final_eval`: xem lại chất lượng RAG context (Adaptive RAG mode), "
                           "có thể tăng `top_k`/đổi sang mode `quality` để context sát hơn.")
    if stage_counts.get("opening_check", 0) > 0:
        suggestions.append("Rớt ở `opening_check`: bổ sung mẫu opening tốt vào `prompts/v2/style_bank.json` "
                           "và cập nhật `bad_openings.json`/`opening_families.json`.")
    if reason_counts.get("duplicate_question", 0) > 0:
        suggestions.append("Có câu trùng theo dedup history: cân nhắc tăng đa dạng topic/độ khó khi request, "
                           "hoặc nới `MCQGEN_DEDUP_*` nếu loại nhầm.")
    if not suggestions:
        suggestions.append("Acceptance rate tốt và không có pattern reject nổi bật. "
                           "Có thể tăng số câu/đa dạng chương để kiểm tra độ ổn định.")
    for s in suggestions:
        a(f"- {s}")
    a("")

    return "\n".join(L)


def main() -> int:
    root = find_repo_root(Path(__file__))
    p = argparse.ArgumentParser(description="Sinh báo cáo evaluation cho MCQGen.")
    p.add_argument("--db", default=None, help="Đường dẫn SQLite (mặc định: auto-detect data/mcqgen.db)")
    p.add_argument("--task-id", default=None, help="Task ID của đề cần đánh giá")
    p.add_argument("--latest", action="store_true", help="Lấy đề success mới nhất")
    p.add_argument("--list", action="store_true", help="Liệt kê các đề gần đây rồi thoát")
    p.add_argument("--check-pdf", action="store_true", help="Smoke test xuất PDF cho đề đã chọn")
    p.add_argument("--report", default=str(root / "reports" / "eval_results.md"))
    args = p.parse_args()

    db_path = detect_db(root, args.db)
    print("=" * 70)
    print("MCQGen — Evaluation Report")
    print(f"DB: {db_path}")
    print("=" * 70)

    if not db_path.exists():
        print(f"\n[!] Chưa có DB {db_path}.")
        print("    Hãy generate ít nhất 1 đề (qua UI hoặc API /generate) rồi chạy lại.")
        # vẫn ghi report template để có artifact
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            "# Báo cáo Evaluation (MCQGen)\n\n"
            "> Chưa có dữ liệu run trong `data/mcqgen.db`.\n"
            "> Generate một đề rồi chạy: `python scripts/eval_report.py --latest`.\n",
            encoding="utf-8",
        )
        print(f"📝 Đã ghi report template: {args.report}")
        return 0

    conn = sqlite3.connect(str(db_path))
    exam_tbl = _resolve_table(conn, "exam")
    q_tbl = _resolve_table(conn, "question")
    if not exam_tbl:
        print("[!] Không tìm thấy bảng 'exam' trong DB.")
        return 1

    if args.list:
        list_exams(conn, exam_tbl)
        return 0

    if not args.task_id and not args.latest:
        print("\nChưa chọn đề. Dùng --latest hoặc --task-id <id>. Các đề gần đây:")
        list_exams(conn, exam_tbl)
        return 0

    exam = fetch_exam(conn, exam_tbl, args.task_id, args.latest)
    if not exam:
        print("[!] Không tìm thấy đề phù hợp.")
        list_exams(conn, exam_tbl)
        return 1

    questions = fetch_questions(conn, q_tbl, exam["id"]) if q_tbl else []
    print(f"\nĐề: {exam.get('exam_name')} | task_id={exam.get('task_id')} | "
          f"accepted={exam.get('accepted_questions')} failed={exam.get('failed_questions')}")
    print(f"Số câu hỏi đọc được từ bảng question: {len(questions)}")

    pdf_status = None
    if args.check_pdf:
        pdf_status = smoke_test_pdf(root, exam, questions)
        print(f"PDF smoke test: {pdf_status[0]} — {pdf_status[1]}")

    report = build_report(root, exam, questions, pdf_status)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report, encoding="utf-8")
    print(f"\n📝 Đã ghi report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
