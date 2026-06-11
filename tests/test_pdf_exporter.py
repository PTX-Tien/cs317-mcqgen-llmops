"""Smoke test cho PDF exporter (api/pdf_exporter.py)."""
import pytest


def test_export_exam_pdf_returns_pdf_bytes():
    try:
        from api.pdf_exporter import export_exam_pdf
    except Exception as exc:
        pytest.skip(f"Không import được pdf_exporter (thiếu reportlab?): {exc}")

    fake_mcqs = [{
        "question_id": "q1",
        "question_text": "1 + 1 = ?",
        "question_type": "single_correct",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "correct_answers": ["B"],
        "correct_rationale": "1 cộng 1 bằng 2.",
        "topic": "Math",
        "difficulty": "G1",
        "chapter_id": "ch01",
    }]
    pdf = export_exam_pdf(fake_mcqs, exam_name="Đề test", include_answer_key=True)
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:5] == b"%PDF-", "output không phải file PDF hợp lệ"
    assert len(pdf) > 500
