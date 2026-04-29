"""
pdf_exporter.py — Export MCQ sang PDF đề thi chuẩn
"""
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

# ── Font hỗ trợ tiếng Việt ────────────────────────────────────────
import os, subprocess

def _setup_font():
    """Tìm và đăng ký font hỗ trợ tiếng Việt."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont("VietFont", path))
            bold_path = path.replace(".ttf", "-Bold.ttf").replace("Regular", "Bold")
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont("VietFont-Bold", bold_path))
            else:
                pdfmetrics.registerFont(TTFont("VietFont-Bold", path))
            return "VietFont"
    return "Helvetica"

FONT = _setup_font()
FONT_BOLD = f"{FONT}-Bold" if FONT != "Helvetica" else "Helvetica-Bold"

# ── Styles ────────────────────────────────────────────────────────
def _get_styles():
    styles = getSampleStyleSheet()
    base = {"fontName": FONT, "leading": 16}

    return {
        "school": ParagraphStyle("school",
            fontName=FONT, fontSize=10, alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"), leading=14),
        "exam_title": ParagraphStyle("exam_title",
            fontName=FONT_BOLD, fontSize=16, alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"), leading=22, spaceAfter=4),
        "exam_meta": ParagraphStyle("exam_meta",
            fontName=FONT, fontSize=11, alignment=TA_CENTER,
            textColor=colors.HexColor("#444444"), leading=16),
        "instruction": ParagraphStyle("instruction",
            fontName=FONT, fontSize=10, alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#555555"), leading=14,
            leftIndent=10, rightIndent=10),
        "question": ParagraphStyle("question",
            fontName=FONT_BOLD, fontSize=11, alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#1a1a2e"), leading=16, spaceAfter=4),
        "option_correct": ParagraphStyle("option_correct",
            fontName=FONT_BOLD, fontSize=11,
            textColor=colors.HexColor("#1a6b1a"), leading=15),
        "option": ParagraphStyle("option",
            fontName=FONT, fontSize=11,
            textColor=colors.HexColor("#1a1a2e"), leading=15),
        "answer_key": ParagraphStyle("answer_key",
            fontName=FONT, fontSize=10,
            textColor=colors.HexColor("#333333"), leading=14),
    }


# ── Header/Footer ─────────────────────────────────────────────────
def _make_header_footer(canvas, doc, exam_name: str, show_answers: bool):
    canvas.saveState()
    w, h = A4

    # Header line
    canvas.setStrokeColor(colors.HexColor("#1a1a2e"))
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, h - 1.8*cm, w - 2*cm, h - 1.8*cm)

    # Footer
    canvas.setFont(FONT, 9)
    canvas.setFillColor(colors.HexColor("#888888"))
    label = "ĐÁP ÁN" if show_answers else exam_name
    canvas.drawString(2*cm, 1.2*cm, label)
    canvas.drawRightString(w - 2*cm, 1.2*cm,
        f"Trang {doc.page}")
    canvas.line(2*cm, 1.6*cm, w - 2*cm, 1.6*cm)
    canvas.restoreState()


# ── Build exam content ────────────────────────────────────────────
def _build_exam_content(mcqs: list[dict], styles: dict,
                         exam_name: str, show_answers: bool) -> list:
    story = []
    W = A4[0] - 4*cm  # content width

    # ── School header
    story.append(Paragraph(
        "TRƯỜNG ĐẠI HỌC CÔNG NGHỆ THÔNG TIN — ĐHQG TP.HCM",
        styles["school"]))
    story.append(Paragraph(
        "Khoa Khoa học và Kỹ thuật Thông tin",
        styles["school"]))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width=W, thickness=1.5,
                             color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3*cm))

    # ── Exam title
    story.append(Paragraph(exam_name.upper(), styles["exam_title"]))
    story.append(Paragraph(
        "Môn: CS116 — Lập trình Python cho Máy học",
        styles["exam_meta"]))

    # ── Meta table (thời gian, số câu)
    n_single = sum(1 for m in mcqs if m.get("question_type") == "single_correct")
    n_multi  = len(mcqs) - n_single
    meta_data = [[
        Paragraph(f"<b>Số câu:</b> {len(mcqs)}", styles["exam_meta"]),
        Paragraph(f"<b>Thời gian:</b> {len(mcqs) * 2} phút", styles["exam_meta"]),
        Paragraph(f"<b>Hình thức:</b> Trắc nghiệm", styles["exam_meta"]),
    ]]
    meta_table = Table(meta_data, colWidths=[W/3]*3)
    meta_table.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(Spacer(1, 0.2*cm))
    story.append(meta_table)
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width=W, thickness=0.5,
                             color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 0.3*cm))

    # ── Instructions
    instruction_text = (
        "<b>Hướng dẫn:</b> Chọn đáp án đúng nhất cho mỗi câu hỏi. "
        "Câu có nhãn [Một đáp án đúng] chỉ có 1 đáp án đúng. "
        "Câu có nhãn [Nhiều đáp án đúng] có thể có 2–3 đáp án đúng."
    )
    story.append(Paragraph(instruction_text, styles["instruction"]))
    story.append(Spacer(1, 0.4*cm))

    # ── Questions
    for i, mcq in enumerate(mcqs, 1):
        q_text = mcq.get("question_text", "")
        options = mcq.get("options", {})
        correct = mcq.get("correct_answers", [])
        topic   = mcq.get("topic", "")

        # Question stem
        story.append(Paragraph(
            f"<b>Câu {i}.</b> {q_text}",
            styles["question"]))

        # Options
        for key, val in options.items():
            if show_answers and key in correct:
                style = styles["option_correct"]
                prefix = f"<b>{key}. ✓ {val}</b>"
            else:
                style = styles["option"]
                prefix = f"{key}. {val}"
            story.append(Paragraph(prefix, style))

        story.append(Spacer(1, 0.3*cm))

        # Subtle topic label
        if topic:
            story.append(Paragraph(
                f"<font size='8' color='#aaaaaa'>[{topic}]</font>",
                styles["answer_key"]))

        story.append(HRFlowable(width=W, thickness=0.3,
                                 color=colors.HexColor("#eeeeee")))
        story.append(Spacer(1, 0.2*cm))

    return story


# ── Main export function ──────────────────────────────────────────
def export_exam_pdf(
    mcqs: list[dict],
    exam_name: str = "ĐỀ KIỂM TRA",
    include_answer_key: bool = True,
) -> bytes:
    """
    Export MCQs sang PDF.
    Returns: bytes của PDF file.
    """
    buffer = io.BytesIO()
    styles = _get_styles()
    W, H = A4

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title=exam_name,
        author="MCQGen CS116",
    )

    # ── Page 1+: Exam questions (không hiện đáp án)
    story = _build_exam_content(mcqs, styles, exam_name, show_answers=False)

    # ── Answer key page (nếu cần)
    if include_answer_key:
        story.append(PageBreak())
        story.append(Paragraph("BẢNG ĐÁP ÁN", styles["exam_title"]))
        story.append(Spacer(1, 0.5*cm))

        # Grid: 5 cột
        answers = []
        row = []
        for i, mcq in enumerate(mcqs, 1):
            correct = ", ".join(mcq.get("correct_answers", []))
            cell = Paragraph(
                f"<b>Câu {i}:</b> {correct}",
                styles["answer_key"])
            row.append(cell)
            if len(row) == 5:
                answers.append(row)
                row = []
        if row:
            while len(row) < 5:
                row.append(Paragraph("", styles["answer_key"]))
            answers.append(row)

        col_w = (W - 4*cm) / 5
        ans_table = Table(answers, colWidths=[col_w]*5)
        ans_table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#dddddd")),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f9f9f9")),
        ]))
        story.append(ans_table)

    # Build với header/footer
    doc.build(
        story,
        onFirstPage=lambda c, d: _make_header_footer(c, d, exam_name, False),
        onLaterPages=lambda c, d: _make_header_footer(c, d, exam_name, False),
    )

    buffer.seek(0)
    return buffer.read()
