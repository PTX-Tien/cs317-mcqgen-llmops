"""
pipeline_mcq.py — Full MCQ Generation Pipeline (5 calls/question, async)
Chạy: python pipeline_mcq.py
"""
# Thêm import ở đầu file
import sys
sys.path.insert(0, '.')
from common import (
    build_p1_gen_stem_key,
    build_p4_option_candidates,
    build_p5_cot_evaluate,
    build_p6_remove_bad,
    build_p7_select_final,
    build_p8_assemble,
    build_eval_overall_prompt,
    parse_json_output,
)

import asyncio, json, time
from pathlib import Path
from openai import AsyncOpenAI
import chromadb
from sentence_transformers import SentenceTransformer
from advanced_retrieval import adaptive_retrieve, emb_model, reranker, collection

# ── Config ────────────────────────────────────────────────────────
VLLM_URL   = "http://localhost:8000/v1"
MODEL      = "mcqgen"
INDEX_DIR  = Path("data/indexes")
OUTPUT_DIR = Path("output/exp_01")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOPICS = [
    # Thay "Missing Data" bằng các subtopic cụ thể
    {"topic_id": "ch04_t01", "chapter_id": "ch04",
     "topic": "SimpleImputer và KNNImputer trong sklearn",
     "difficulty": "G2", "n": 2},
    {"topic_id": "ch04_t01b", "chapter_id": "ch04",
     "topic": "dropna và fillna trong Pandas",
     "difficulty": "G2", "n": 1},

    # Thay "Outlier Detection" tương tự
    {"topic_id": "ch04_t02", "chapter_id": "ch04",
     "topic": "IQR method và Z-score để phát hiện outlier",
     "difficulty": "G2", "n": 2},
    {"topic_id": "ch04_t02b", "chapter_id": "ch04",
     "topic": "Isolation Forest outlier detection",
     "difficulty": "G2", "n": 1},

    # Giữ nguyên các topic đã tốt
    {"topic_id": "ch07b_t01", "chapter_id": "ch07b",
     "topic": "Decision Trees", "difficulty": "G2", "n": 3},
    {"topic_id": "ch07b_t02", "chapter_id": "ch07b",
     "topic": "Logistic Regression", "difficulty": "G2", "n": 3},
    {"topic_id": "ch08_t01", "chapter_id": "ch08",
     "topic": "CNN Neural Networks", "difficulty": "G2", "n": 3},
]

SYSTEM_PROMPT = """Bạn là giảng viên Trường ĐH Công nghệ Thông tin ĐHQG-HCM,
dạy môn CS116 – Lập trình Python cho Máy học.
Bạn đang biên soạn câu hỏi trắc nghiệm cho sinh viên đại học."""

# ── Phoenix Tracing ──────────────────────────────────────────────
from monitoring.setup_tracing import init_tracing
init_tracing(project_name='mcqgen')

client_llm = AsyncOpenAI(base_url=VLLM_URL, api_key="x")

# ── Retrieval setup ───────────────────────────────────────────────
print("Ready.\n")  # models loaded in advanced_retrieval.py

def retrieve_context(topic: str, chapter_id: str, top_k: int = 8) -> str:
    # Query 1: theo topic
    emb1 = emb_model.encode([topic])[0].tolist()
    res1 = collection.query(
        query_embeddings=[emb1],
        n_results=top_k,
        where={"chapter_id": chapter_id},
        include=["documents", "metadatas"]
    )
    # Query 2: thêm keyword kỹ thuật để pull chunks cụ thể hơn
    technical_query = f"{topic} sklearn pandas phương pháp kỹ thuật xử lý"
    emb2 = emb_model.encode([technical_query])[0].tolist()
    res2 = collection.query(
        query_embeddings=[emb2],
        n_results=4,
        where={"chapter_id": chapter_id},
        include=["documents", "metadatas"]
    )
    # Merge, deduplicate
    seen_docs = set()
    blocks = []
    for docs, metas in [
        (res1["documents"][0], res1["metadatas"][0]),
        (res2["documents"][0], res2["metadatas"][0]),
    ]:
        for doc, meta in zip(docs, metas):
            key = doc[:100]
            if key not in seen_docs:
                seen_docs.add(key)
                src = f"[{meta['source_type']}|{meta.get('source_file','?')}]"
                blocks.append(f"--- Context {src} ---\n{doc[:1500]}")
    return "\n\n".join(blocks[:8])

# ── Prompts ───────────────────────────────────────────────────────
def prompt_gen(topic: str, difficulty: str, context: str, seq: int = 0) -> str:
    diversity_hint = ""
    if seq > 0:
        diversity_hint = f"""
[DIVERSITY — BẮT BUỘC]
- Đây là câu hỏi thứ {seq+1} về topic này
- KHÔNG được hỏi lại về isna/isnull/dropna/fillna nếu đã có câu trước
- Hỏi về khía cạnh KHÁC: chiến lược xử lý, khi nào dùng imputation vs drop, trade-off, ví dụ code phức tạp hơn
"""

    return f"""Dựa trên context bên dưới, tạo 1 câu MCQ tiếng Việt độ khó {difficulty}.

[CONTEXT]
{context}

[YÊU CẦU]
- Topic: {topic}
- 1 đáp án đúng (single_correct), 3 distractor plausible
- Câu hỏi kiểm tra HIỂU KHÁI NIỆM hoặc ÁP DỤNG, KHÔNG hỏi định nghĩa thuần túy
- Distractor phải SAI RÕ RÀNG về mặt kỹ thuật, không phải alias hay synonym của đáp án đúng
- Tự review: nếu distractor nào thực ra cũng đúng → thay bằng cái khác{diversity_hint}

[OUTPUT — chỉ JSON]
{{
  "question_text": "...",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correct_answers": ["A"],
  "correct_rationale": "...",
  "distractor_check": "giải thích tại sao B, C, D sai rõ ràng",
  "topic": "{topic}",
  "difficulty_label": "{difficulty}"
}}"""

def prompt_eval(mcq: dict) -> str:
    return f"""Đánh giá câu MCQ sau:

{json.dumps(mcq, ensure_ascii=False, indent=2)}

[OUTPUT — chỉ JSON]
{{
  "overall_valid": true/false,
  "quality_score": 0.0-1.0,
  "distractor_plausible": true/false,
  "language_correct": true/false,
  "fail_reasons": []
}}"""

# ── LLM call ──────────────────────────────────────────────────────
async def llm(prompt: str, temperature: float = 0.7, max_tokens: int = 1024) -> str:
    resp = await client_llm.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    )
    return resp.choices[0].message.content

def parse_json(text: str) -> dict:
    text = text.strip()
    if "<think>" in text:
        end = text.find("</think>")
        if end != -1:
            text = text[end + len("</think>"):].strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except Exception as e:
        return {"error": str(e), "raw": text[:300]}

# ── Single MCQ pipeline (5 calls) ─────────────────────────────────
async def generate_one_mcq(topic_cfg: dict, seq: int) -> dict | None:
    topic      = topic_cfg["topic"]
    difficulty = topic_cfg["difficulty"]
    chapter_id = topic_cfg["chapter_id"]
    q_id       = f"{topic_cfg['topic_id']}_q{seq:02d}"

    # ── Retrieve context ──────────────────────────────────────────
    context, rag_debug = await adaptive_retrieve(topic, chapter_id)
    print(f"    RAG: {rag_debug['strategy']} | best={max(rag_debug['top_scores_after_rerank']):.3f}")

    # ── Call 1: P1 Gen Stem (dùng prompt chuẩn từ common.py) ─────
    p1_prompt = build_p1_gen_stem_key(
        topic=topic,
        difficulty_target=difficulty,
        concept_context_blocks=context,
        question_type_target="single_correct",
        correct_answer_count_target=1,
        num_questions_total=1,
        num_single_correct=1,
    )
    raw_p1 = await llm(p1_prompt, temperature=0.7, max_tokens=1024)
    p1 = parse_json_output(raw_p1)
    if "error" in p1:
        print(f"  ❌ P1 error [{q_id}]")
        return None

    # ── Call 2: P4 Gen Distractors ────────────────────────────────
    p4_prompt = build_p4_option_candidates(p1, num_candidates=5)
    raw_p4 = await llm(p4_prompt, temperature=0.7, max_tokens=512)
    p4 = parse_json_output(raw_p4)
    candidates = p4.get("candidate_distractors", []) if "error" not in p4 else []
    if not candidates:
        print(f"  ❌ P4 error [{q_id}]")
        return None

    # ── Call 3: P5+P6+P7 Select Distractors ──────────────────────
    correct_options = p1.get("correct_answers_content", [])

    p5_prompt = build_p5_cot_evaluate(p1, candidates, correct_options)
    raw_p5 = await llm(p5_prompt, temperature=0.1, max_tokens=1024)
    p5 = parse_json_output(raw_p5)
    p5_evals = p5.get("evaluations", []) if "error" not in p5 else []

    p6_prompt = build_p6_remove_bad(p1, candidates, p5_evals)
    raw_p6 = await llm(p6_prompt, temperature=0.1, max_tokens=512)
    p6 = parse_json_output(raw_p6)
    kept = p6.get("kept_options", candidates[:3]) if "error" not in p6 else \
           [{"option_text": c} for c in candidates[:3]]

    p7_prompt = build_p7_select_final(p1, kept, 1)
    raw_p7 = await llm(p7_prompt, temperature=0.1, max_tokens=512)
    p7 = parse_json_output(raw_p7)
    selected = p7.get("selected_distractors", []) if "error" not in p7 else \
               [{"option_text": c, "error_type": "fallback", "misleading_score": 5}
                for c in candidates[:3]]

    # ── Call 4: P8 Assemble ───────────────────────────────────────
    p8_prompt = build_p8_assemble(p1, selected[:3], correct_options)
    raw_p8 = await llm(p8_prompt, temperature=0.3, max_tokens=1024)
    p8 = parse_json_output(raw_p8)
    if "error" in p8:
        print(f"  ❌ P8 error [{q_id}]")
        return None

    # ── Call 5: Eval Overall ──────────────────────────────────────
    eval_prompt = build_eval_overall_prompt(p8)
    raw_eval = await llm(eval_prompt, temperature=0.1, max_tokens=512)
    eval_result = parse_json_output(raw_eval)
    if isinstance(eval_result, dict) and not eval_result.get("overall_valid", True):
        print(f"  ⚠️  Rejected [{q_id}]: {eval_result.get('fail_reasons', [])}")
        return None

    p8["question_id"]    = q_id
    p8["prompt_version"]  = "v1.0"
    p8["rag_strategy"]    = rag_debug.get("strategy", "unknown")
    p8["rag_best_score"]  = max(rag_debug.get("top_scores_after_rerank", [0]))
    p8["evaluation"]  = eval_result
    p8["status"]      = "accepted"
    score = eval_result.get("quality_score", 0) if isinstance(eval_result, dict) else 0
    print(f"  ✅ [{q_id}] score={score:.2f} | {topic}")
    return p8

# ── Run all topics ─────────────────────────────────────────────────
async def run_pipeline():
    t0 = time.time()
    all_tasks = []
    for topic_cfg in TOPICS:
        for seq in range(topic_cfg["n"]):
            all_tasks.append(generate_one_mcq(topic_cfg, seq))

    print(f"Generating {len(all_tasks)} MCQs async...\n")
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    accepted = [r for r in results if isinstance(r, dict) and r]
    failed   = len(all_tasks) - len(accepted)
    total_t  = time.time() - t0

    # Save
    out_file = OUTPUT_DIR / "mcqs.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for mcq in accepted:
            f.write(json.dumps(mcq, ensure_ascii=False) + "\n")

    print(f"\n{'='*50}")
    print(f"✅ Done: {len(accepted)} accepted, {failed} failed")
    print(f"⏱  Total: {total_t:.1f}s ({total_t/60:.1f} phút)")
    print(f"📄 Output: {out_file}")
    print(f"{'='*50}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())

# ── Entry point cho Celery ─────────────────────────────────────────
async def run_pipeline_with_topics(
    topics: list,
    output_name: str = "exam",
    progress_callback=None
) -> dict:
    """Được gọi từ Celery task."""
    if progress_callback:
        progress_callback(10, "loading_retriever")

    all_tasks = []
    for topic_cfg in topics:
        for seq in range(topic_cfg.get("n", 1)):
            all_tasks.append(generate_one_mcq(topic_cfg, seq))

    if progress_callback:
        progress_callback(20, "generating")

    results = await asyncio.gather(*all_tasks, return_exceptions=True)
    accepted = [r for r in results if isinstance(r, dict) and r]

    # Save output
    out_dir = OUTPUT_DIR.parent / output_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "mcqs.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for mcq in accepted:
            f.write(json.dumps(mcq, ensure_ascii=False) + "\n")

    if progress_callback:
        progress_callback(95, "saving")

    return {
        "accepted": len(accepted),
        "failed": len(all_tasks) - len(accepted),
        "output_file": str(out_file),
        "mcqs": accepted,
    }
