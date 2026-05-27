from __future__ import annotations

import re
from collections import Counter
from typing import Any

try:
    from .prompt_loader import load_opening_families, load_weak_openings, select_fewshot_examples, load_bad_opening_examples
except ImportError:
    from src.mcqgen.prompt_loader import load_opening_families, load_weak_openings, select_fewshot_examples, load_bad_opening_examples

def _families() -> list[dict[str, Any]]:
    families = load_opening_families()
    return families or [{
        "id": "mechanism_reasoning",
        "question_form": "mechanism_explanation",
        "required_intent": "Kiem tra co che hoat dong.",
        "allowed_opening_patterns": ["Co che nao giup..."],
        "forbidden_opening_patterns": ["Trong cac mo hinh phan lop sau..."],
        "style_note": "Di thang vao co che.",
        "suitable_for": ["G2", "G3"],
    }]

def weak_openings() -> list[str]:
    return load_weak_openings()

def select_opening_family(seq: int, total_questions: int, used_families: list[str] | None = None, difficulty: str = "G2") -> str:
    used_families = used_families or []
    families = _families()
    suitable = [f for f in families if difficulty in f.get("suitable_for", ["G1", "G2", "G3"])] or families
    counts = Counter(used_families)
    min_count = min(counts.get(f["id"], 0) for f in suitable)
    pool = [f for f in suitable if counts.get(f["id"], 0) == min_count] or suitable
    return pool[seq % len(pool)]["id"]

def build_opening_style_card(opening_family: str) -> str:
    families = {f["id"]: f for f in _families()}
    card = families.get(opening_family) or next(iter(families.values()))

    allowed = "\n".join(f"  - {x}" for x in card.get("allowed_opening_patterns", []))
    forbidden = "\n".join(f"  - {x}" for x in card.get("forbidden_opening_patterns", []))

    return f"""[OPENING STYLE CARD - BAT BUOC]
- opening_family: {card.get("id", opening_family)}
- question_form: {card.get("question_form", "")}
- required_intent: {card.get("required_intent", "")}
- allowed_opening_patterns:
{allowed}
- forbidden_opening_patterns:
{forbidden}
- style_note: {card.get("style_note", "")}

[OPENING STYLE RULES - BAT BUOC]
- Cau hoi hien tai PHAI dung dung opening_family o tren.
- Khong dung lai cac mau mo dau trong forbidden_opening_patterns.
- Khong bat dau bang mau generic dang "Trong cac ... sau".
- Neu opening_family la scenario_application, stem phai co mot tinh huong ngan.
- Neu opening_family la parameter_effect, stem phai co mot bien/tham so/dieu kien thay doi.
- Neu opening_family la comparison, stem phai co it nhat hai doi tuong de so sanh.
"""

def build_previous_openings_block(previous_openings: list[str] | None) -> str:
    previous_openings = previous_openings or []
    if not previous_openings:
        return "[CAC MO DAU DA DUNG TRONG DE]\n- Chua co cau truoc do.\n"

    items = "\n".join(f'  - "{x}"' for x in previous_openings[-8:])
    return f"""[CAC MO DAU DA DUNG TRONG DE - KHONG DUOC LAP]
{items}
- Khong duoc bat dau bang bat ky cum nao o tren.
- Khong duoc dung cung 4 tu dau voi bat ky cau truoc.
"""

def extract_opening_prefix(question_text: str, max_words: int = 8) -> str:
    text = re.sub(r"^\[[^\]]+\]\s*", "", question_text or "").strip()
    return " ".join(text.split()[:max_words])


# ── Phase 2: Few-shot blocks ─────────────────────────────────

def build_fewshot_block(topic: str, opening_family: str, difficulty: str = "G2", n: int = 2) -> str:
    """Build few-shot examples block for P1 prompt."""
    examples = select_fewshot_examples(topic, opening_family, difficulty, n)
    if not examples:
        return ""

    items = []
    for i, ex in enumerate(examples, 1):
        items.append(
            f"[VÍ DỤ THAM KHẢO {i}]\n"
            f"- opening_family: {ex.get('opening_family', '?')}\n"
            f"- question_text: {ex.get('question_text', '')}\n"
            f"- Điểm tốt: {ex.get('why_good', ex.get('quality_note', ''))}\n"
            f"- Lưu ý: {ex.get('do_not_copy_note', 'Chỉ học phong cách, KHÔNG sao chép nội dung.')}"
        )
    return (
        "\n[STYLE REFERENCE — Ví dụ câu hỏi tốt từ đề thi thật]\n"
        "Học cách mở đầu và đặt vấn đề từ các ví dụ dưới, KHÔNG sao chép nội dung.\n\n"
        + "\n\n".join(items)
        + "\n"
    )


def build_bad_examples_block(n: int = 2) -> str:
    """Build anti-examples block for P1 prompt."""
    examples = load_bad_opening_examples()
    if not examples:
        return ""

    items = []
    for ex in examples[:n]:
        items.append(
            f"❌ KHÔNG NÊN: {ex.get('bad_opening', '')}\n"
            f"   Lý do: {ex.get('bad_reason', '')}\n"
            f"✅ NÊN: {ex.get('better_rewrite', '')}\n"
            f"   Lý do: {ex.get('better_reason', '')}"
        )
    return "\n[ANTI-EXAMPLES — Mở đầu cần tránh]\n" + "\n\n".join(items) + "\n"
