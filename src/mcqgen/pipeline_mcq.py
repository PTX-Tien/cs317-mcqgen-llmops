"""
pipeline_mcq.py — Full MCQ Generation Pipeline (5 calls/question, async)
Chạy: python -m src.mcqgen.pipeline_mcq
"""
from .common import (
    build_p1_gen_stem_key,
    build_p4_option_candidates,
    build_p5_cot_evaluate,
    build_p6_remove_bad,
    build_p7_select_final,
    build_p8_assemble,
    build_eval_overall_prompt,
    parse_json_output,
)

import asyncio, json, os, time, re
from contextlib import asynccontextmanager
from pathlib import Path
from openai import AsyncOpenAI
import chromadb
from sentence_transformers import SentenceTransformer
from .advanced_retrieval import adaptive_retrieve_sw as adaptive_retrieve, emb_model, reranker, collection, sw_collection
from .math_format import normalize_mcq_math
from .opening_families import (
    select_opening_family,
    build_opening_style_card,
    build_previous_openings_block,
    extract_opening_prefix,
)
from .prompt_loader import load_weak_openings, load_misconception_types

# ── Config ────────────────────────────────────────────────────────
VLLM_URL   = os.getenv("VLLM_URL", "http://localhost:8000/v1")
MODEL      = os.getenv("VLLM_MODEL", "mcqgen")
INDEX_DIR  = Path("data/indexes")
OUTPUT_DIR = Path("output/exp_01")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ENABLE_LLM_EVAL = os.getenv("ENABLE_LLM_EVAL", "0") == "1"
DEFAULT_RETRIEVAL_MODE = os.getenv("DEFAULT_RETRIEVAL_MODE", "auto")

def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default

def env_float(name: str, default: float, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default

# Keep these values aligned with vLLM --max-num-seqs. For the current 4-GPU
# Qwen2.5-7B-Instruct setup, 4 concurrent question pipelines gives vLLM enough
# in-flight requests to batch without opening multiple Celery jobs.
MAX_CONCURRENT_QUESTIONS = env_int("MCQGEN_MAX_CONCURRENT_QUESTIONS", 4)
MAX_CONCURRENT_LLM_REQUESTS = env_int(
    "MCQGEN_LLM_MAX_CONCURRENCY",
    MAX_CONCURRENT_QUESTIONS,
)
VLLM_TIMEOUT_SECONDS = env_float(
    "VLLM_TIMEOUT_SECONDS",
    env_float("VLLM_TIMEOUT", 180.0),
)
VLLM_MAX_RETRIES = env_int("VLLM_MAX_RETRIES", 1, minimum=0)
_LLM_SEMAPHORES: dict[int, asyncio.Semaphore] = {}
_LLM_CLIENTS: dict[int, AsyncOpenAI] = {}

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
def get_llm_semaphore() -> asyncio.Semaphore:
    """Return a loop-local semaphore so repeated Celery asyncio.run calls are safe."""
    loop = asyncio.get_running_loop()
    loop_key = id(loop)
    semaphore = _LLM_SEMAPHORES.get(loop_key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)
        _LLM_SEMAPHORES[loop_key] = semaphore
    return semaphore

def get_llm_client() -> AsyncOpenAI:
    """Return a loop-local AsyncOpenAI client for Celery's per-task event loops."""
    loop = asyncio.get_running_loop()
    loop_key = id(loop)
    client = _LLM_CLIENTS.get(loop_key)
    if client is None:
        client = AsyncOpenAI(
            base_url=VLLM_URL,
            api_key="x",
            timeout=VLLM_TIMEOUT_SECONDS,
            max_retries=VLLM_MAX_RETRIES,
        )
        _LLM_CLIENTS[loop_key] = client
    return client

async def llm(prompt: str, temperature: float = 0.7, max_tokens: int = 1024) -> str:
    async with get_llm_semaphore():
        resp = await get_llm_client().chat.completions.create(
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


def _truncate_for_log(text: str, limit: int = 2000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} chars]"


def log_llm_parse_error(stage: str, q_id: str, raw_text: str, parsed: dict | None = None):
    parsed = parsed or {}
    print(f"  ❌ {stage} error [{q_id}]")
    print(f"  [LLM_PARSE_ERROR] stage={stage} q_id={q_id} error={parsed.get('error', 'unknown')}")
    if parsed.get("raw"):
        print(f"  [LLM_PARSE_ERROR] parsed_raw_snippet:\n{_truncate_for_log(str(parsed['raw']))}")
    print(f"  [LLM_PARSE_ERROR] raw_output:\n{_truncate_for_log(raw_text)}")



def normalize_opening_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def final_opening_issues(question_text: str, opening_family: str = "") -> list[str]:
    opening = normalize_opening_text(question_text)
    issues: list[str] = []

    weak_openings = [w.lower() for w in load_weak_openings()]
    for weak in weak_openings:
        if opening.startswith(weak):
            issues.append(f"forbidden_opening:{weak}")

    # "Trong ..." quota gate. Allow only technical/API/formula openings.
    starts_with_trong = opening.startswith("trong ")
    allowed_trong_families = {"code_api", "formula_interpretation", "scenario_application"}

    allowed_prefixes = (
        "trong scikit-learn",
        "trong sklearn",
        "trong pandas",
        "trong numpy",
        "trong pytorch",
        "trong công thức",
        "trong hàm",
        "trong đoạn code",
        "trong một bài toán",
    )

    if starts_with_trong:
        is_allowed_prefix = opening.startswith(allowed_prefixes)
        is_allowed_family = opening_family in allowed_trong_families
        if not (is_allowed_prefix and is_allowed_family):
            issues.append("overused_trong_opening")

    return issues



def build_opening_repair_prompt(mcq: dict, issues: list[str], opening_family: str = "") -> str:
    return f"""[ROLE]
Bạn là giảng viên CS116 đang sửa cách mở đầu câu hỏi trắc nghiệm.

[ISSUES]
{json.dumps(issues, ensure_ascii=False)}

[OPENING FAMILY ĐƯỢC GÁN]
{opening_family}

[INPUT MCQ]
{json.dumps(mcq, ensure_ascii=False, indent=2)}

[YÊU CẦU SỬA - BẮT BUỘC]
- Chỉ viết lại `question_text` để tránh lỗi mở đầu.
- Giữ nguyên ý nghĩa kỹ thuật, options, correct_answers và các field còn lại.
- Không bắt đầu bằng "Trong ..." trừ khi thật sự là API/công thức/đoạn code.
- Không bắt đầu bằng "Trong các", "Trong quá trình", "Hãy chọn", "Hãy xác định", "Cho biết".
- Câu hỏi phải bằng tiếng Việt có dấu.
- Không giải thích đáp án trong câu hỏi.
- Trả về đúng một JSON object hợp lệ, không markdown.

[OUTPUT]
Trả lại MCQ đầy đủ sau khi sửa.
"""


def log_mcq_debug(q_id: str, mcq: dict):
    preview = {
        "question_id": q_id,
        "question_text": mcq.get("question_text"),
        "options": mcq.get("options"),
        "correct_answers": mcq.get("correct_answers"),
        "correct_rationale": mcq.get("correct_rationale"),
    }
    print("[MCQ_DEBUG] assembled_question:")
    print(json.dumps(preview, ensure_ascii=False, indent=2))


@asynccontextmanager
async def atimer(name: str, q_id: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[TIMING] {q_id} | {name} | {dt:.2f}s")


# ── Phase 3: Misconception helpers ────────────────────────────────

def build_misconception_guidance(topic: str) -> str:
    """Build misconception guidance block for P4 prompt based on topic."""
    types = load_misconception_types()
    if not types:
        return ""
    topic_lower = topic.lower()
    # Select relevant misconception types based on topic keywords
    relevant = []
    for mt in types:
        examples_str = " ".join(mt.get("examples", [])).lower()
        name_str = mt.get("name_vi", "").lower() + " " + mt.get("description", "").lower()
        # Check if any keyword from topic appears in misconception examples/description
        topic_words = [w for w in topic_lower.split() if len(w) > 3]
        if any(w in examples_str or w in name_str for w in topic_words):
            relevant.append(mt)
    # If no specific match, use first 4 general types
    if not relevant:
        relevant = types[:4]
    items = []
    for mt in relevant[:4]:
        examples = mt.get("examples", [])[:2]
        ex_str = "; ".join(examples) if examples else ""
        items.append(f"- {mt['id']} ({mt.get('name_vi','')}): {mt.get('description','')}. Ví dụ: {ex_str}")
    return "\nCác misconception phổ biến liên quan đến topic này:\n" + "\n".join(items) + "\n"


def extract_candidate_texts(raw_candidates: list) -> list[str]:
    """Extract plain text candidates from P4 output — backward compatible with both list[str] and list[dict]."""
    texts = []
    for c in raw_candidates:
        if isinstance(c, str):
            texts.append(c)
        elif isinstance(c, dict):
            texts.append(c.get("option_text", str(c)))
        else:
            texts.append(str(c))
    return texts

# ── Single MCQ pipeline (5 calls) ─────────────────────────────────
async def generate_one_mcq(
    topic_cfg: dict,
    seq: int,
    precomputed_rag: tuple[str, dict] | None = None,
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE,
    # ── Phase 1: diversity context ──
    opening_style_card: str = "",
    previous_openings_block: str = "",
) -> dict | None:
    topic      = topic_cfg["topic"]
    difficulty = topic_cfg["difficulty"]
    chapter_id = topic_cfg["chapter_id"]
    q_id       = f"{topic_cfg['topic_id']}_q{seq:02d}"

    async with atimer("TOTAL", q_id):
        # ── Retrieve context ──────────────────────────────────────
        if precomputed_rag is None:
            async with atimer("RAG", q_id):
                context, rag_debug = await adaptive_retrieve(
                    topic,
                    chapter_id,
                    mode=retrieval_mode,
                )
        else:
            context, rag_debug = precomputed_rag
            print(f"    RAG cache hit [{q_id}]")
        scores = rag_debug.get("top_scores_after_rerank", [0])
        print(f"    RAG: {rag_debug.get('strategy', 'unknown')} | best={max(scores):.3f}")

        # ── Call 1: P1 Gen Stem ───────────────────────────────────
        p1_prompt = build_p1_gen_stem_key(
            topic=topic,
            difficulty_target=difficulty,
            concept_context_blocks=context,
            question_type_target="single_correct",
            correct_answer_count_target=1,
            num_questions_total=1,
            num_single_correct=1,
            opening_style_card=opening_style_card,
            previous_openings_block=previous_openings_block,
        )
        async with atimer("P1", q_id):
            raw_p1 = await llm(p1_prompt, temperature=0.7, max_tokens=384)
        p1 = parse_json_output(raw_p1)
        if "error" in p1:
            log_llm_parse_error("P1", q_id, raw_p1, p1)
            return None

        # ── Call 2: P4 Gen Distractors (Phase 3: misconception-guided) ──
        misconception_guide = build_misconception_guidance(topic)
        p4_prompt = build_p4_option_candidates(
            p1, num_candidates=5,
            misconception_guidance=misconception_guide,
        )
        async with atimer("P4", q_id):
            raw_p4 = await llm(p4_prompt, temperature=0.7, max_tokens=768)
        p4 = parse_json_output(raw_p4)
        raw_candidates = p4.get("candidate_distractors", []) if "error" not in p4 else []
        candidates = extract_candidate_texts(raw_candidates)
        if not candidates:
            log_llm_parse_error("P4", q_id, raw_p4, p4)
            return None

        # ── Call 3-5: P5+P6+P7 Select Distractors ─────────────────
        correct_options = p1.get("correct_answers_content", [])

        p5_prompt = build_p5_cot_evaluate(p1, candidates, correct_options)
        async with atimer("P5", q_id):
            raw_p5 = await llm(p5_prompt, temperature=0.1, max_tokens=512)
        p5 = parse_json_output(raw_p5)
        p5_evals = p5.get("evaluations", []) if "error" not in p5 else []

        p6_prompt = build_p6_remove_bad(p1, candidates, p5_evals)
        async with atimer("P6", q_id):
            raw_p6 = await llm(p6_prompt, temperature=0.1, max_tokens=512)
        p6 = parse_json_output(raw_p6)
        kept = p6.get("kept_options", candidates[:3]) if "error" not in p6 else \
               [{"option_text": c} for c in candidates[:3]]

        p7_prompt = build_p7_select_final(p1, kept, 1)
        async with atimer("P7", q_id):
            raw_p7 = await llm(p7_prompt, temperature=0.1, max_tokens=512)
        p7 = parse_json_output(raw_p7)
        selected = p7.get("selected_distractors", []) if "error" not in p7 else \
                   [{"option_text": c, "error_type": "fallback", "misleading_score": 5}
                    for c in candidates[:3]]

        # ── Call 6: P8 Assemble ───────────────────────────────────
        p8_prompt = build_p8_assemble(p1, selected[:3], correct_options)
        async with atimer("P8", q_id):
            raw_p8 = await llm(p8_prompt, temperature=0.3, max_tokens=512)
        p8 = parse_json_output(raw_p8)
        if "error" in p8:
            log_llm_parse_error("P8", q_id, raw_p8, p8)
            return None
        opening_issues = final_opening_issues(
            p8.get("question_text", ""),
            p1.get("opening_family", ""),
        )
        if opening_issues:
            print(f"  ⚠️ OPENING_REPAIR [{q_id}]: {opening_issues}")
            opening_repair_prompt = build_opening_repair_prompt(
                p8,
                opening_issues,
                p1.get("opening_family", ""),
            )
            async with atimer("OPENING_REPAIR", q_id):
                raw_opening_repair = await llm(opening_repair_prompt, temperature=0.1, max_tokens=512)
            repaired_opening = parse_json_output(raw_opening_repair)
            if "error" in repaired_opening:
                log_llm_parse_error("OPENING_REPAIR", q_id, raw_opening_repair, repaired_opening)
                return None
            if final_opening_issues(repaired_opening.get("question_text", ""), p1.get("opening_family", "")):
                print(f"  ❌ OPENING_REJECT [{q_id}]: still has bad opening")
                return None
            p8 = repaired_opening

        p8 = normalize_mcq_math(p8)
        log_mcq_debug(q_id, p8)

        # ── Optional Call 7: Eval Overall ─────────────────────────
        if ENABLE_LLM_EVAL:
            eval_prompt = build_eval_overall_prompt(p8)
            async with atimer("EVAL", q_id):
                raw_eval = await llm(eval_prompt, temperature=0.1, max_tokens=512)
            eval_result = parse_json_output(raw_eval)
            if isinstance(eval_result, dict) and not eval_result.get("overall_valid", True):
                print(f"  ⚠️  Rejected [{q_id}]: {eval_result.get('fail_reasons', [])}")
                return None
        else:
            eval_result = {
                "enabled": False,
                "overall_valid": True,
                "quality_score": 0.0,
                "fail_reasons": [],
                "note": "LLM evaluation disabled in production mode.",
            }

        p8["question_id"]    = q_id
        p8["prompt_version"]  = "v1.0"
        p8["rag_strategy"]    = rag_debug.get("strategy", "unknown")
        p8["rag_best_score"]  = max(rag_debug.get("top_scores_after_rerank", [0]))
        p8["evaluation"]  = eval_result
        p8["status"]      = "accepted"
        # ── Propagate diversity metadata from P1 ──
        for meta_key in ("opening_family", "question_form", "tested_skill"):
            if meta_key not in p8 and meta_key in p1:
                p8[meta_key] = p1[meta_key]
        score = eval_result.get("quality_score", 0) if isinstance(eval_result, dict) else 0
        print(f"  ✅ [{q_id}] score={score:.2f} | {topic}")
        return p8

# ── Run all topics ─────────────────────────────────────────────────
async def run_pipeline():
    t0 = time.time()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_QUESTIONS)

    async def bounded_generate(topic_cfg: dict, seq: int):
        async with semaphore:
            return await generate_one_mcq(topic_cfg, seq)

    all_tasks = []
    for topic_cfg in TOPICS:
        for seq in range(topic_cfg["n"]):
            all_tasks.append(bounded_generate(topic_cfg, seq))

    print(
        f"Generating {len(all_tasks)} MCQs async "
        f"(question_concurrency={MAX_CONCURRENT_QUESTIONS}, "
        f"llm_concurrency={MAX_CONCURRENT_LLM_REQUESTS})...\n"
    )
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
    progress_callback=None,
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE,
) -> dict:
    """Được gọi từ Celery task."""
    def emit_progress(progress: int, step: str, **meta):
        if not progress_callback:
            return
        try:
            progress_callback(progress, step, **meta)
        except TypeError:
            progress_callback(progress, step)

    task_specs = []
    for topic_cfg in topics:
        for seq in range(topic_cfg.get("n", 1)):
            task_specs.append((topic_cfg, seq))

    total_questions = len(task_specs)
    retrieval_mode = (retrieval_mode or DEFAULT_RETRIEVAL_MODE).lower()
    if retrieval_mode not in {"fast", "auto", "quality"}:
        retrieval_mode = "auto"

    emit_progress(10, "retrieving_context",
                  current_question=0, total_questions=total_questions)

    rag_cache: dict[tuple[str, str, str], tuple[str, dict]] = {}
    unique_topic_configs: dict[tuple[str, str, str], dict] = {}
    for topic_cfg, _seq in task_specs:
        key = (topic_cfg["topic"], topic_cfg["chapter_id"], retrieval_mode)
        unique_topic_configs.setdefault(key, topic_cfg)

    total_topics = len(unique_topic_configs)
    for idx, (key, topic_cfg) in enumerate(unique_topic_configs.items(), 1):
        topic, chapter_id, mode = key
        cache_id = f"{topic_cfg.get('topic_id', 'topic')}:{topic}"
        async with atimer("RAG_PRECOMPUTE", cache_id):
            rag_cache[key] = await adaptive_retrieve(topic, chapter_id, mode=mode)
        progress = 10 + int((idx / total_topics) * 15) if total_topics else 25
        emit_progress(
            min(progress, 25),
            f"retrieving_context {idx}/{total_topics}",
            current_question=0,
            total_questions=total_questions,
            current_topic=idx,
            total_topics=total_topics,
        )

    completed_questions = 0

    # ── Phase 1: diversity tracking ──
    _diversity_lock = asyncio.Lock()
    used_families: list[str] = []
    previous_openings: list[str] = []

    async def tracked_generate(topic_cfg: dict, seq: int):
        nonlocal completed_questions

        # Select opening family & build blocks (thread-safe)
        async with _diversity_lock:
            family = select_opening_family(
                seq=len(used_families),
                total_questions=total_questions,
                used_families=used_families,
                difficulty=topic_cfg.get("difficulty", "G2"),
            )
            style_card = build_opening_style_card(family)
            prev_block = build_previous_openings_block(previous_openings)
            used_families.append(family)

        key = (topic_cfg["topic"], topic_cfg["chapter_id"], retrieval_mode)
        try:
            result = await generate_one_mcq(
                topic_cfg,
                seq,
                precomputed_rag=rag_cache.get(key),
                retrieval_mode=retrieval_mode,
                opening_style_card=style_card,
                previous_openings_block=prev_block,
            )

            # Update previous_openings after successful generation
            if result and result.get("question_text"):
                opening = extract_opening_prefix(result["question_text"])
                if opening:
                    async with _diversity_lock:
                        previous_openings.append(opening)

            return result
        finally:
            completed_questions += 1
            progress = 25 + int((completed_questions / total_questions) * 65) \
                if total_questions else 90
            emit_progress(
                min(progress, 90),
                f"generating {completed_questions}/{total_questions}",
                current_question=completed_questions,
                total_questions=total_questions,
            )

    max_concurrent_questions = min(MAX_CONCURRENT_QUESTIONS, total_questions or 1)
    semaphore = asyncio.Semaphore(max_concurrent_questions)

    async def bounded_tracked_generate(topic_cfg: dict, seq: int):
        async with semaphore:
            return await tracked_generate(topic_cfg, seq)

    emit_progress(
        25,
        f"generating question_concurrency={max_concurrent_questions} "
        f"llm_concurrency={MAX_CONCURRENT_LLM_REQUESTS}",
        current_question=0,
        total_questions=total_questions,
        question_concurrency=max_concurrent_questions,
        llm_concurrency=MAX_CONCURRENT_LLM_REQUESTS,
    )

    all_tasks = [bounded_tracked_generate(topic_cfg, seq) for topic_cfg, seq in task_specs]
    results = await asyncio.gather(*all_tasks, return_exceptions=True) if all_tasks else []
    for result in results:
        if isinstance(result, Exception):
            print(f"  ❌ generation exception: {result!r}")
    accepted = [r for r in results if isinstance(r, dict) and r]

    # Save output
    out_dir = OUTPUT_DIR.parent / output_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "mcqs.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for mcq in accepted:
            f.write(json.dumps(mcq, ensure_ascii=False) + "\n")

    emit_progress(95, "saving",
                  current_question=total_questions, total_questions=total_questions)

    return {
        "accepted": len(accepted),
        "failed": len(all_tasks) - len(accepted),
        "output_file": str(out_file),
        "mcqs": accepted,
        "question_concurrency": max_concurrent_questions,
        "llm_concurrency": MAX_CONCURRENT_LLM_REQUESTS,
        "vllm_url": VLLM_URL,
        "vllm_model": MODEL,
    }
