from __future__ import annotations

import re
from collections import Counter
from typing import Any

try:
    from .prompt_loader import load_opening_families, load_weak_openings
except ImportError:
    from src.mcqgen.prompt_loader import load_opening_families, load_weak_openings

def _families() -> list[dict[str, Any]]:
    families = load_opening_families()
    return families or [{
        "id": "mechanism_reasoning",
        "question_form": "mechanism_explanation",
        "required_intent": "Kiểm tra cơ chế hoạt động.",
        "allowed_opening_patterns": ["Cơ chế nào giúp..."],
        "forbidden_opening_patterns": ["Trong các mô hình phân lớp sau..."],
        "style_note": "Đi thẳng vào cơ chế.",
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

    return f"""[OPENING STYLE CARD — BẮT BUỘC]
- opening_family: {card.get("id", opening_family)}
- question_form: {card.get("question_form", "")}
- required_intent: {card.get("required_intent", "")}
- Các mẫu mở đầu được phép:
{allowed}
- Các mẫu mở đầu BỊ CẤM:
{forbidden}
- Ghi chú phong cách: {card.get("style_note", "")}

[QUY TẮC MỞ ĐẦU — BẮT BUỘC]
- Câu hỏi hiện tại PHẢI dùng đúng opening_family ở trên.
- Không dùng lại các mẫu mở đầu trong danh sách bị cấm.
- Không bắt đầu bằng mẫu generic dạng "Trong các ... sau".
- Nếu opening_family là scenario_application, stem phải có một tình huống ngắn.
- Nếu opening_family là parameter_effect, stem phải có một biến/tham số/điều kiện thay đổi.
- Nếu opening_family là comparison, stem phải có ít nhất hai đối tượng để so sánh.
"""

def build_previous_openings_block(previous_openings: list[str] | None) -> str:
    previous_openings = previous_openings or []
    if not previous_openings:
        return ""

    items = "\n".join(f'  - "{x}"' for x in previous_openings[-8:])
    return f"""[CÁC MỞ ĐẦU ĐÃ DÙNG TRONG ĐỀ — KHÔNG ĐƯỢC LẶP]
{items}
- KHÔNG được bắt đầu bằng bất kỳ cụm nào ở trên.
- KHÔNG được dùng cùng 4 từ đầu với bất kỳ câu trước.
- Phải dùng cách mở đầu hoàn toàn khác.
"""

def extract_opening_prefix(question_text: str, max_words: int = 8) -> str:
    text = re.sub(r"^\[[^\]]+\]\s*", "", question_text or "").strip()
    return " ".join(text.split()[:max_words])