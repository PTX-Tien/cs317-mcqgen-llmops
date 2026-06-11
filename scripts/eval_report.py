#!/usr/bin/env python3
"""
eval_report.py — Sinh báo cáo evaluation cho hệ thống MCQGen.

Mục tiêu (bài thực hành mục 5.7 — Evaluation report):
  Tổng hợp kết quả một run sinh đề và ghi `reports/eval_results.md`.

Nguồn "accepted" (ưu tiên theo thứ tự):
  1. --mcqs-file <path>            : đọc trực tiếp các câu accepted từ mcqs.jsonl.
  2. exam.output_file (mcqs.jsonl) : nếu file tồn tại.
  3. bảng `question` trong DB      : khi cột accepted_questions = 0 nhưng có câu đã lưu.
  4. cột exam.accepted_questions   : fallback cuối.

Số liệu khớp Langfuse scores (api/tasks.py): accepted_questions, failed_questions,
acceptance_rate, reject_stage.<stage>, job_failed.

Cách dùng:
    python scripts/eval_report.py --latest
    python scripts/eval_report.py --task-id <ID>
    python scripts/eval_report.py --latest --mcqs-file output/exam_01/mcqs.jsonl
    python scripts/eval_report.py --mcqs-file output/exam_01/mcqs.jsonl    # chỉ đọc file
    python scripts/eval_report.py --list
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path


REASON_BUCKET = {
    "json_parse_error":              "Lỗi định dạng JSON (model trả output sai format)",
    "missing_candidate_distractors": "Thiếu / không đủ distractor (stage P4)",
    "llm_eval_rejected":             "Bị final eval / guardrail loại (relevance, chất lượng)",
    "opening_repair_failed":         "Opening style xấu, sửa không đạt",
    "duplicate_question":            "Trùng câu đã sinh (dedup theo lịch sử)",
    "generation_exception":          "Exception khi sinh câu",
}

ANALYSIS_QUESTIONS = [
    ("Reject do JSON format?",             lambda s, r: r == "json_parse_error"),
    ("Reject do distractor?",              lambda s, r: r == "missing_candidate_distractors"),
    ("Reject do relevance / RAG context?", lambda s, r: r == "llm_eval_rejected"),
    ("Reject do opening style?",           lambda s, r: s == "opening_check"),
    ("Reject do trùng câu (dedup)?",       lambda s, r: r == "duplicate_question"),
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
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for n in [r[0] for r in rows]:
        if n.lower() == wanted.lower():
            return n
    return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().split())


def normalize_mcq(rec: dict) -> dict:
    """Chuẩn hoá 1 MCQ (từ mcqs.jsonl HOẶC từ bảng question) về shape chung."""
    ev = rec.get("evaluation", {})
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:
            ev = {}
    if not isinstance(ev, dict):
        ev = {}
    qscore = rec.get("quality_score", ev.get("quality_score", 0))
    try:
        qscore = float(qscore or 0)
    except Exception:
        qscore = 0.0
    return {
        "question_text": rec.get("question_text", "") or "",
        "difficulty":    rec.get("difficulty_label", rec.get("difficulty", "?")) or "?",
        "chapter_id":    rec.get("chapter_id", "?") or "?",
        "rag_strategy":  rec.get("rag_strategy", "") or "?",
        "question_type": rec.get("question_type", "?") or "?",
        "prompt_version": rec.get("prompt_version", "?") or "?",
        "quality_score": qscore,
    }


def read_mcqs_jsonl(path: Path) -> list[dict]:
    mcqs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                mcqs.append(json.loads(line))
            except Exception:
                pass
    return mcqs


def list_exams(conn, exam_tbl, limit=20):
    cols = "task_id, exam_name, status, requested_questions, accepted_questions, failed_questions, prompt_version, created_at"
    rows = conn.execute(f"SELECT {cols} FROM {exam_tbl} ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    print(f"\n{'created_at':<28} {'status':<8} {'acc/req':<9} {'task_id':<38} exam_name")
    print("-" * 110)
    for r in rows:
        task_id, name, status, req, acc, fail, pv, created = r
        print(f"{str(created):<28} {str(status):<8} {f'{acc}/{req}':<9} {str(task_id):<38} {name}")
    print()


def fetch_exam(conn, exam_tbl, task_id, latest):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if task_id:
        row = cur.execute(f"SELECT * FROM {exam_tbl} WHERE task_id = ?", (task_id,)).fetchone()
    elif latest:
        row = cur.execute(f"SELECT * FROM {exam_tbl} WHERE status='success' ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            row = cur.execute(f"SELECT * FROM {exam_tbl} ORDER BY created_at DESC LIMIT 1").fetchone()
    else:
        return None
    return dict(row) if row else None


def fetch_questions(conn, q_tbl, exam_id):
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {q_tbl} WHERE exam_id = ?", (exam_id,)).fetchall()
    return [dict(r) for r in rows]


def build_report(exam: dict | None, accepted_mcqs: list[dict], failures: list[dict],
                 requested_hint: int, source_label: str, mcqs_path: str | None) -> str:
    accepted = len(accepted_mcqs)
    n_fail_records = len([f for f in failures if isinstance(f, dict)])

    requested = int(requested_hint or 0)
    if requested <= 0:
        requested = accepted + n_fail_records
    failed = n_fail_records if n_fail_records > 0 else max(requested - accepted, 0)
    denom = accepted + failed
    acceptance_rate = accepted / denom if denom > 0 else (1.0 if accepted > 0 else 0.0)

    stage_counts = Counter(f.get("stage", "unknown") for f in failures if isinstance(f, dict))
    reason_counts = Counter(f.get("reason", "unknown") for f in failures if isinstance(f, dict))

    analysis_rows = []
    for label, pred in ANALYSIS_QUESTIONS:
        n = sum(1 for f in failures if isinstance(f, dict) and pred(f.get("stage", ""), f.get("reason", "")))
        analysis_rows.append((label, n))

    norm = [normalize_mcq(m) for m in accepted_mcqs]
    stems = [_normalize(m["question_text"]) for m in norm if m["question_text"]]
    stem_counts = Counter(stems)
    n_dup = sum(c - 1 for c in stem_counts.values() if c > 1)
    dup_rate = n_dup / max(len(stems), 1)

    qscores = [m["quality_score"] for m in norm if m["quality_score"] > 0]
    qavg = sum(qscores) / len(qscores) if qscores else None

    by_diff = Counter(m["difficulty"] for m in norm)
    by_chapter = Counter(m["chapter_id"] for m in norm)
    by_strategy = Counter(m["rag_strategy"] for m in norm)
    by_type = Counter(m["question_type"] for m in norm)
    by_pv = Counter(m["prompt_version"] for m in norm)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L: list[str] = []
    a = L.append

    a("# Báo cáo Evaluation (MCQGen)")
    a("")
    a(f"- Thời điểm sinh báo cáo: `{now}`")
    a(f"- Nguồn câu accepted: **{source_label}**" + (f" (`{mcqs_path}`)" if mcqs_path else ""))
    a(f"- Script: `scripts/eval_report.py`")
    a("")

    a("## 1. Cấu hình run")
    a("")
    a("| Thông tin | Giá trị |")
    a("| --- | --- |")
    if exam:
        a(f"| Task ID | `{exam.get('task_id','')}` |")
        a(f"| Tên đề | {exam.get('exam_name','')} |")
        a(f"| Trạng thái | {exam.get('status','')} |")
        a(f"| Người tạo | {exam.get('created_by','')} |")
        a(f"| Thời điểm tạo | {exam.get('created_at','')} |")
        a(f"| Thời điểm hoàn tất | {exam.get('completed_at','')} |")
    a(f"| Model serving | Qwen2.5-7B-Instruct (vLLM, served-name `mcqgen`) |")
    pv_show = ", ".join(f"{k}×{v}" for k, v in by_pv.items() if k and k != "?") or (exam.get("prompt_version") if exam else "?")
    a(f"| Prompt version (trên câu accepted) | {pv_show} |")
    rag_modes = ", ".join(sorted(k for k in by_strategy if k and k != "?")) or "(không ghi nhận)"
    a(f"| RAG strategy ghi nhận | {rag_modes} |")
    a(f"| Chapters xuất hiện | {', '.join(sorted(k for k in by_chapter if k and k != '?')) or '(n/a)'} |")
    a("")

    a("## 2. Kết quả tổng quan")
    a("")
    a("| Metric | Giá trị |")
    a("| --- | --- |")
    a(f"| Requested questions | {requested} |")
    a(f"| Accepted questions | {accepted} |")
    a(f"| Rejected / failed questions | {failed} |")
    a(f"| **Acceptance rate** | **{acceptance_rate:.1%}** |")
    if qavg is not None:
        a(f"| Quality score trung bình (accepted) | {qavg:.3f} |")
    else:
        a(f"| Quality score trung bình (accepted) | (không có điểm trong dữ liệu) |")
    a(f"| Duplicate trong accepted (theo stem) | {n_dup} câu ({dup_rate:.1%}) |")
    a(f"| PDF export | kiểm tra thủ công: `GET /export/pdf/{exam.get('task_id','<task_id>') if exam else '<task_id>'}` |")
    a("")
    a("> Khớp Langfuse scores: `accepted_questions`, `failed_questions`, `acceptance_rate`, "
      "`reject_stage.<stage>` (mục 3).")
    a("")

    a("## 3. Rejection theo stage và reason")
    a("")
    if stage_counts:
        a("**Theo stage** (khớp score `reject_stage.<stage>`):")
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
        a("Không có bản ghi failure cho run này (cột `failure_info_json` rỗng). "
          "Các câu không đạt ở pipeline này không được lưu lại chi tiết stage/reason.")
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
    a(f"- Theo prompt version: {dict(by_pv)}")
    a("")

    a("## 6. Nhận xét & đề xuất cải thiện")
    a("")
    sug = []
    if reason_counts.get("json_parse_error", 0) > 0:
        sug.append("Có câu rớt do `json_parse_error`: siết format trong prompt P1/P4/P8 (yêu cầu JSON thuần, thêm ví dụ), hoặc giảm temperature cho stage sinh JSON.")
    if reason_counts.get("missing_candidate_distractors", 0) > 0:
        sug.append("Rớt ở P4 do thiếu distractor: tăng `NUM_CANDIDATE_DISTRACTORS` hoặc cải thiện prompt sinh phương án nhiễu.")
    if reason_counts.get("llm_eval_rejected", 0) > 0:
        sug.append("Rớt ở `final_eval`: xem lại chất lượng RAG context (đổi mode `quality`/tăng top_k).")
    if stage_counts.get("opening_check", 0) > 0:
        sug.append("Rớt ở `opening_check`: bổ sung mẫu opening tốt vào `prompts/v2/style_bank.json`, cập nhật `bad_openings.json`.")
    if reason_counts.get("duplicate_question", 0) > 0:
        sug.append("Có câu trùng (dedup): tăng đa dạng topic/độ khó khi request.")
    if not stage_counts:
        sug.append("Run này không lưu chi tiết reject. Để phân tích reject đầy đủ, generate đề mới với pipeline hiện tại rồi chạy lại script (cột `failure_info_json` sẽ có dữ liệu).")
    if n_dup == 0:
        sug.append(f"Không phát hiện câu trùng trong {accepted} câu accepted → cơ chế dedup theo lịch sử hoạt động tốt.")
    if qavg is not None and qavg >= 0.8:
        sug.append(f"Quality score trung bình cao ({qavg:.2f}) → guardrail/eval đang giữ chất lượng tốt.")
    for s in sug:
        a(f"- {s}")
    a("")
    return "\n".join(L)


def main() -> int:
    root = find_repo_root(Path(__file__))
    p = argparse.ArgumentParser(description="Sinh báo cáo evaluation cho MCQGen.")
    p.add_argument("--db", default=None)
    p.add_argument("--task-id", default=None)
    p.add_argument("--latest", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--mcqs-file", default=None, help="Đường dẫn mcqs.jsonl chứa các câu accepted")
    p.add_argument("--check-pdf", action="store_true")
    p.add_argument("--report", default=str(root / "reports" / "eval_results.md"))
    args = p.parse_args()

    db_path = detect_db(root, args.db)
    print("=" * 70)
    print("MCQGen — Evaluation Report")
    print(f"DB: {db_path}")
    print("=" * 70)

    exam = None
    questions = []
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        exam_tbl = _resolve_table(conn, "exam")
        q_tbl = _resolve_table(conn, "question")
        if args.list:
            if exam_tbl:
                list_exams(conn, exam_tbl)
            return 0
        if exam_tbl and (args.task_id or args.latest):
            exam = fetch_exam(conn, exam_tbl, args.task_id, args.latest)
            if exam and q_tbl:
                questions = fetch_questions(conn, q_tbl, exam["id"])
    elif not args.mcqs_file:
        print(f"\n[!] Chưa có DB {db_path} và không truyền --mcqs-file.")
        return 0

    # ── Xác định nguồn accepted ─────────────────────────────────────────────
    accepted_mcqs: list[dict] = []
    source_label = ""
    mcqs_path = None

    # 1) --mcqs-file
    cand_file = None
    if args.mcqs_file:
        cand_file = Path(args.mcqs_file)
        if not cand_file.is_absolute():
            cand_file = root / cand_file
    # 2) exam.output_file
    elif exam and exam.get("output_file"):
        of = Path(exam["output_file"])
        if not of.is_absolute():
            of = root / of
        if of.exists():
            cand_file = of

    if cand_file and cand_file.exists():
        accepted_mcqs = read_mcqs_jsonl(cand_file)
        source_label = "mcqs.jsonl"
        mcqs_path = str(cand_file)
    elif questions:
        accepted_mcqs = questions  # normalize_mcq xử lý được row bảng question
        source_label = "bảng question (DB)"
    elif exam:
        # fallback cuối: dùng cột đếm, tạo placeholder rỗng
        accepted_mcqs = []
        source_label = "cột accepted_questions (DB)"

    # requested hint
    requested_hint = 0
    failures = []
    if exam:
        requested_hint = int(exam.get("requested_questions") or 0)
        try:
            failures = json.loads(exam.get("failure_info_json") or "[]")
            if not isinstance(failures, list):
                failures = []
        except Exception:
            failures = []
    # nếu dùng cột DB làm fallback và accepted rỗng, lấy luôn con số cột
    accepted_count = len(accepted_mcqs)
    if accepted_count == 0 and exam and int(exam.get("accepted_questions") or 0) > 0:
        # tạo danh sách rỗng có độ dài = accepted để báo cáo đúng số (không có chi tiết)
        accepted_mcqs = [{} for _ in range(int(exam["accepted_questions"]))]
        source_label = "cột accepted_questions (DB)"

    if exam:
        print(f"\nĐề: {exam.get('exam_name')} | task_id={exam.get('task_id')}")
    print(f"Nguồn accepted: {source_label} | số câu accepted = {len(accepted_mcqs)}")
    if mcqs_path:
        print(f"File: {mcqs_path}")

    if args.check_pdf:
        print("PDF smoke test: SKIP — kiểm tra thủ công qua API /export/pdf/{task_id}")

    report = build_report(exam, accepted_mcqs, failures, requested_hint, source_label, mcqs_path)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report, encoding="utf-8")
    print(f"\n📝 Đã ghi report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())