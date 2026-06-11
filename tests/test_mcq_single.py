"""
test_mcq_single.py — Chạy 1 câu MCQ end-to-end qua vLLM API mới
Mục đích: validate Qwen2.5-7B-Instruct sinh MCQ tiếng Việt đạt chất lượng chưa

Chạy: python test_mcq_single.py
"""

import os
import sys

if "pytest" in sys.modules and os.getenv("RUN_LLM_SMOKE_TESTS") != "1":
    import pytest
    pytest.skip("LLM smoke test; set RUN_LLM_SMOKE_TESTS=1 to run", allow_module_level=True)

import json
import time
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────
VLLM_BASE_URL = os.getenv("VLLM_URL", "http://localhost:7681/v1")
MODEL_NAME    = os.getenv("VLLM_MODEL", "mcqgen")

# Dùng 1 context block thực từ data của bạn (copy từ concept_chunks.jsonl)
# Hoặc để mặc định để test nhanh
SAMPLE_CONTEXT = """
--- Context 1 ---
[ch04] | Slide | Trang 12
Missing data là tình trạng một hoặc nhiều giá trị trong dataset bị thiếu.
Các chiến lược xử lý gồm: (1) Xóa hàng/cột có missing value,
(2) Imputation: điền giá trị trung bình/trung vị/mode,
(3) Dùng model để dự đoán giá trị còn thiếu (KNN imputer, IterativeImputer).
Pandas dùng df.isnull(), df.fillna(), df.dropna() để xử lý.
"""

# ── Prompt P1 merged (stem + self-refine in 1 call) ────────────────
SYSTEM_PROMPT = """Bạn là giảng viên Trường ĐH Công nghệ Thông tin ĐHQG-HCM, 
dạy môn CS116 – Lập trình Python cho Máy học. 
Bạn đang biên soạn câu hỏi trắc nghiệm cho sinh viên đại học."""

def build_mcq_prompt(topic: str, context: str, difficulty: str = "G2") -> str:
    return f"""Dựa trên context bên dưới, hãy tạo 1 câu hỏi trắc nghiệm {difficulty} tiếng Việt.

[CONTEXT]
{context}

[YÊU CẦU]
- Topic: {topic}
- 1 đáp án đúng, 3 distractor hợp lý (plausible nhưng sai)
- Câu hỏi ngắn gọn, rõ ràng, kiểm tra hiểu khái niệm
- Distractor phải liên quan đến topic, không quá dễ loại
- Sau khi tạo câu hỏi, hãy tự review và cải thiện nếu cần

[OUTPUT FORMAT — chỉ JSON, không thêm text nào khác]
{{
  "question_text": "Câu hỏi tiếng Việt",
  "question_type": "single_correct",
  "difficulty_label": "{difficulty}",
  "topic": "{topic}",
  "options": {{
    "A": "...",
    "B": "...",
    "C": "...",
    "D": "..."
  }},
  "correct_answers": ["A"],
  "correct_rationale": "Giải thích ngắn tại sao A đúng",
  "distractor_rationale": {{
    "B": "Tại sao B sai",
    "C": "Tại sao C sai",
    "D": "Tại sao D sai"
  }},
  "self_review": "Nhận xét ngắn về chất lượng câu hỏi"
}}"""

# ── Prompt Eval (eval overall + IWF merged) ─────────────────────────
def build_eval_prompt(mcq: dict) -> str:
    q_str = json.dumps(mcq, ensure_ascii=False, indent=2)
    return f"""Đánh giá câu hỏi MCQ sau theo các tiêu chí:

[MCQ]
{q_str}

[CHECKLIST]
1. format_pass: JSON đúng, đủ 4 options A/B/C/D
2. language_pass: tiếng Việt, ngữ pháp đúng
3. relevance_pass: phù hợp context và topic
4. answerability_pass: có thể trả lời được từ context
5. correct_set_pass: đáp án đúng thực sự đúng
6. distractor_plausible_pass: distractor plausible, không quá dễ loại
7. no_grammar_clue_pass: không có dấu hiệu ngữ pháp giúp đoán đáp án

[OUTPUT — chỉ JSON]
{{
  "format_pass": true/false,
  "language_pass": true/false,
  "relevance_pass": true/false,
  "answerability_pass": true/false,
  "correct_set_pass": true/false,
  "distractor_plausible_pass": true/false,
  "no_grammar_clue_pass": true/false,
  "overall_valid": true/false,
  "quality_score": 0.0-1.0,
  "fail_reasons": ["lý do nếu fail"],
  "judge_comment": "nhận xét tổng thể"
}}"""


def call_llm(client: OpenAI, prompt: str, system: str = None,
             temperature: float = 0.7, max_tokens: int = 1024) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
#        extra_body={"guided_json": None}  # bỏ nếu gây lỗi
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False}  # Tắt thinking mode
        }
    )
    return resp.choices[0].message.content


def parse_json_safe(text: str) -> dict:
    text = text.strip()
    # Strip thinking block nếu có
    if "<think>" in text:
        end = text.find("</think>")
        if end != -1:
            text = text[end + len("</think>"):].strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw": text[:500]}


def run_single_mcq_test():
    client = OpenAI(base_url=VLLM_BASE_URL, api_key="not-needed")
    
    topic = "Missing Data"
    context = SAMPLE_CONTEXT
    
    print("=" * 60)
    print(f"TEST: Sinh MCQ cho topic '{topic}'")
    print("=" * 60)

    # ── Step 1: Generate MCQ ──────────────────────────────────────
    print("\n[Step 1] Generating MCQ...")
    t0 = time.time()
    raw_gen = call_llm(
        client,
        prompt=build_mcq_prompt(topic, context, "G2"),
        system=SYSTEM_PROMPT,
        temperature=0.7,
        max_tokens=1024,
    )
    t1 = time.time()
    print(f"  Generation time: {t1-t0:.1f}s")
    
    mcq = parse_json_safe(raw_gen)
    if "error" in mcq:
        print(f"  ❌ Parse error: {mcq['error']}")
        print(f"  Raw: {mcq.get('raw', '')}")
        return
    
    print("\n  📝 Generated MCQ:")
    print(f"  Q: {mcq.get('question_text', 'N/A')}")
    for k, v in mcq.get("options", {}).items():
        marker = "✓" if k in mcq.get("correct_answers", []) else " "
        print(f"  {marker} {k}. {v}")
    print(f"  Rationale: {mcq.get('correct_rationale', 'N/A')}")
    print(f"  Self-review: {mcq.get('self_review', 'N/A')}")

    # ── Step 2: Evaluate MCQ ──────────────────────────────────────
    print("\n[Step 2] Evaluating MCQ...")
    t2 = time.time()
    raw_eval = call_llm(
        client,
        prompt=build_eval_prompt(mcq),
        system="Bạn là chuyên gia đánh giá câu hỏi trắc nghiệm.",
        temperature=0.1,
        max_tokens=512,
    )
    t3 = time.time()
    print(f"  Evaluation time: {t3-t2:.1f}s")
    
    eval_result = parse_json_safe(raw_eval)
    if "error" in eval_result:
        print(f"  ❌ Eval parse error: {eval_result['error']}")
    else:
        status = "✅ PASS" if eval_result.get("overall_valid") else "❌ FAIL"
        print(f"  {status} | Score: {eval_result.get('quality_score', 0):.2f}")
        print(f"  Comment: {eval_result.get('judge_comment', 'N/A')}")
        if eval_result.get("fail_reasons"):
            print(f"  Fail reasons: {eval_result['fail_reasons']}")

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = t3 - t0
    print(f"⏱  Total time: {total:.1f}s (Gen: {t1-t0:.1f}s, Eval: {t3-t2:.1f}s)")
    print(f"📊 Estimated for 30 MCQs (5 calls each, async): ~{total*30*5/60:.0f}–{total*30*5/60*1.5:.0f} min")
    print("=" * 60)

    # Save output
    out = {
        "mcq": mcq,
        "eval": eval_result,
        "timing": {"gen_s": round(t1-t0, 2), "eval_s": round(t3-t2, 2)}
    }
    with open("test_output.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n✅ Output saved to test_output.json")


if __name__ == "__main__":
    run_single_mcq_test()
