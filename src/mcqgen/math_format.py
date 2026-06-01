"""Utilities for keeping generated math notation renderable.

The pipeline stores MCQs as JSON text, so LaTeX must stay lightweight and safe:
inline math uses ``$...$`` and display math uses ``$$...$$``.  These helpers do
not try to be a full TeX engine; they normalize common ML/math symbols so the
web UI and PDF exporter can render them consistently.
"""

from __future__ import annotations

import re
from typing import Any

MATH_FORMAT_INSTRUCTIONS = """[ĐỊNH DẠNG KÝ HIỆU TOÁN - BẮT BUỘC]
- Nếu có công thức, metric, biến số hoặc ký hiệu toán học, viết bằng LaTeX.
- Công thức ngắn trong câu phải đặt giữa `$...$`; công thức riêng dòng đặt giữa `$$...$$`.
- Vì output là JSON, mọi dấu backslash trong lệnh LaTeX phải escape thành `\\\\`.
  Ví dụ JSON hợp lệ: `"MSE = $\\\\frac{1}{n}\\\\sum_{i=1}^{n}(y_i - \\\\hat{y}_i)^2$"`.
- Không dùng ký tự toán rời rạc như ≤, ≥, ≠, ×, ∑, √, ², ₁; dùng `\\\\le`, `\\\\ge`,
  `\\\\neq`, `\\\\times`, `\\\\sum`, `\\\\sqrt{}`, `^2`, `_1`.
- Không bọc tên hàm, tên biến code hoặc API bằng LaTeX. Ví dụ giữ nguyên
  `train_test_split`, `np.mean`, `model.fit`, `DataFrame.dropna`.
"""

_CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`]*`)", re.DOTALL)
_MATH_SPLIT_RE = re.compile(r"(\$\$.*?\$\$|\$[^$\n].*?\$)", re.DOTALL)
_CONTROL_LATEX_REPAIRS = {
    "\x0crac": r"\frac",
    "\x08ar": r"\bar",
    "\x08eta": r"\beta",
    "\theta": r"\theta",
    "\times": r"\times",
    "\nabla": r"\nabla",
    "\neq": r"\neq",
    "\rightarrow": r"\rightarrow",
}

_UNICODE_TO_LATEX = {
    "≤": r"$\le$",
    "≥": r"$\ge$",
    "≠": r"$\neq$",
    "≈": r"$\approx$",
    "±": r"$\pm$",
    "×": r"$\times$",
    "·": r"$\cdot$",
    "∞": r"$\infty$",
    "∑": r"$\sum$",
    "∏": r"$\prod$",
    "√": r"$\sqrt{}$",
    "∇": r"$\nabla$",
    "Δ": r"$\Delta$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "γ": r"$\gamma$",
    "δ": r"$\delta$",
    "λ": r"$\lambda$",
    "μ": r"$\mu$",
    "σ": r"$\sigma$",
    "θ": r"$\theta$",
    "π": r"$\pi$",
}

_SUPERSCRIPTS = str.maketrans({
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
})

_SUBSCRIPTS = str.maketrans({
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
})


def _normalize_latex_delimiters(text: str) -> str:
    for broken, repaired in _CONTROL_LATEX_REPAIRS.items():
        text = text.replace(broken, repaired)
    text = re.sub(r"\\\[(.*?)\\\]", r"$$\1$$", text, flags=re.DOTALL)
    text = re.sub(r"\\\((.*?)\\\)", r"$\1$", text, flags=re.DOTALL)
    return text


def _normalize_math_segment(segment: str) -> str:
    """Normalize text outside code spans and outside existing dollar math."""

    pieces = _MATH_SPLIT_RE.split(segment)
    normalized: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if piece.startswith("$"):
            normalized.append(piece)
            continue

        value = piece
        for symbol, latex in _UNICODE_TO_LATEX.items():
            value = value.replace(symbol, latex)

        # R², x₁, y₂ -> $R^2$, $x_1$, $y_2$
        value = re.sub(
            r"\b([A-Za-z])([⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
            lambda m: f"${m.group(1)}^{m.group(2).translate(_SUPERSCRIPTS)}$",
            value,
        )
        value = re.sub(
            r"\b([A-Za-z])([₀₁₂₃₄₅₆₇₈₉]+)",
            lambda m: f"${m.group(1)}_{m.group(2).translate(_SUBSCRIPTS)}$",
            value,
        )

        # Conservative conversions: single-letter variables only, so code-like
        # names such as train_test_split or y_true are left untouched.
        value = re.sub(r"\b([A-Za-z])\s*\^\s*([0-9]+)\b", r"$\1^\2$", value)
        value = re.sub(r"\b([A-Za-z])_([0-9ijkn])\b", r"$\1_\2$", value)
        value = re.sub(r"\bŷ\b", lambda _m: r"$\hat{y}$", value)
        normalized.append(value)

    return "".join(normalized)


def normalize_math_text(text: Any) -> Any:
    """Return text with common math symbols normalized to lightweight LaTeX."""

    if not isinstance(text, str) or not text:
        return text

    text = _normalize_latex_delimiters(text)
    parts = _CODE_SPLIT_RE.split(text)
    output: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`"):
            output.append(part)
        else:
            output.append(_normalize_math_segment(part))
    return "".join(output)


def normalize_mcq_math(mcq: dict[str, Any]) -> dict[str, Any]:
    """Normalize visible math text in an MCQ without changing answer labels."""

    if not isinstance(mcq, dict):
        return mcq

    mcq["question_text"] = normalize_math_text(mcq.get("question_text", ""))
    options = mcq.get("options")
    if isinstance(options, dict):
        mcq["options"] = {
            key: normalize_math_text(value)
            for key, value in options.items()
        }
    if "correct_rationale" in mcq:
        mcq["correct_rationale"] = normalize_math_text(mcq.get("correct_rationale", ""))
    return mcq


def strip_answers_for_view(mcq: dict[str, Any]) -> dict[str, Any]:
    """Return a public MCQ payload that does not reveal the answer."""

    public = dict(mcq)
    public["correct_answers"] = []
    public.pop("correct_rationale", None)
    return public
