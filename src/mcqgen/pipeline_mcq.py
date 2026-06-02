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
    build_p9_explanation,
    EXPLAIN_SYSTEM_PROMPT,
    build_eval_overall_prompt,
    parse_json_output,
)

import asyncio, json, os, time, re, unicodedata
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from openai import AsyncOpenAI
import chromadb
from sentence_transformers import SentenceTransformer
from .advanced_retrieval import adaptive_retrieve_sw as adaptive_retrieve, emb_model, reranker, collection, sw_collection
from .opening_families import (
    select_opening_family,
    build_opening_style_card,
    build_previous_openings_block,
    extract_opening_prefix,
)
from .prompt_loader import load_weak_openings, load_misconception_types
from monitoring.langfuse_tracing import (
    langfuse_attributes,
    langfuse_observation,
    sanitize_for_langfuse,
    score_langfuse_observation,
    truncate_for_langfuse,
    update_langfuse_observation,
    usage_details_from_response,
)

# ── Config ────────────────────────────────────────────────────────
VLLM_URL   = os.getenv("VLLM_URL", "http://localhost:8000/v1")
MODEL      = os.getenv("VLLM_MODEL", "mcqgen")
INDEX_DIR  = Path("data/indexes")
OUTPUT_DIR = Path("output/exp_01")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ENABLE_LLM_EVAL = os.getenv("ENABLE_LLM_EVAL", "0") == "1"
ENABLE_EXPLANATION = os.getenv("ENABLE_EXPLANATION", "1") == "1"
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

def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# Keep these values aligned with vLLM --max-num-seqs. For the current 4-GPU
# Qwen2.5-7B-Instruct setup, 4 concurrent question pipelines gives vLLM enough
# in-flight requests to batch without opening multiple Celery jobs.
MAX_CONCURRENT_QUESTIONS = env_int("MCQGEN_MAX_CONCURRENT_QUESTIONS", 4)
MAX_CONCURRENT_LLM_REQUESTS = env_int(
    "MCQGEN_LLM_MAX_CONCURRENCY",
    MAX_CONCURRENT_QUESTIONS,
)
TARGET_CONCURRENT_USERS = env_int("MCQGEN_TARGET_CONCURRENT_USERS", 3)
CELERY_GENERATION_CONCURRENCY = env_int(
    "CELERY_GENERATION_CONCURRENCY",
    TARGET_CONCURRENT_USERS,
)
VLLM_MAX_NUM_SEQS = env_int("VLLM_MAX_NUM_SEQS", 4)
ENABLE_DYNAMIC_CONCURRENCY = env_bool("MCQGEN_DYNAMIC_CONCURRENCY", True)
VLLM_TIMEOUT_SECONDS = env_float(
    "VLLM_TIMEOUT_SECONDS",
    env_float("VLLM_TIMEOUT", 180.0),
)
VLLM_MAX_RETRIES = env_int("VLLM_MAX_RETRIES", 1, minimum=0)
ENABLE_LLM_STREAM_METRICS = env_bool("MCQGEN_LLM_STREAM_METRICS", True)
DEDUP_SIMILARITY_THRESHOLD = env_float(
    "MCQGEN_DUPLICATE_SIMILARITY_THRESHOLD",
    0.86,
    minimum=0.5,
)
DEDUP_MIN_CHARS = env_int("MCQGEN_DEDUP_MIN_CHARS", 32)
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


async def _chat_completion_non_stream(messages: list[dict], temperature: float, max_tokens: int):
    resp = await get_llm_client().chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return resp.choices[0].message.content, usage_details_from_response(resp)


async def _chat_completion_stream(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> tuple[str, dict[str, int] | None, datetime | None, float | None]:
    stream = await get_llm_client().chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    chunks: list[str] = []
    usage_details: dict[str, int] | None = None
    completion_start_time: datetime | None = None
    first_token_perf: float | None = None

    async for chunk in stream:
        chunk_usage = usage_details_from_response(chunk)
        if chunk_usage:
            usage_details = chunk_usage

        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if not content:
            continue
        if completion_start_time is None:
            completion_start_time = datetime.now(timezone.utc)
            first_token_perf = time.perf_counter()
        chunks.append(content)

    return "".join(chunks), usage_details, completion_start_time, first_token_perf


async def llm(
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    *,
    trace_name: str | None = None,
    trace_metadata: dict | None = None,
) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    prompt_name = trace_name or "llm.chat_completion"
    trace_metadata = trace_metadata or {}
    metadata = {
        "model": MODEL,
        "prompt_name": prompt_name,
        "use_case": trace_metadata.get("use_case") or "generate_exam",
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming_metrics_enabled": ENABLE_LLM_STREAM_METRICS,
        **trace_metadata,
    }
    with langfuse_observation(
        prompt_name,
        as_type="generation",
        input={"messages": messages},
        metadata=metadata,
        model=MODEL,
        model_parameters={"temperature": temperature, "max_tokens": max_tokens},
    ) as lf_generation:
        request_started = time.perf_counter()
        completion_start_time: datetime | None = None
        first_token_perf: float | None = None
        usage_details: dict[str, int] | None = None
        streaming_fallback_error: str | None = None
        try:
            async with get_llm_semaphore():
                if ENABLE_LLM_STREAM_METRICS:
                    try:
                        (
                            output,
                            usage_details,
                            completion_start_time,
                            first_token_perf,
                        ) = await _chat_completion_stream(messages, temperature, max_tokens)
                    except Exception as stream_exc:
                        streaming_fallback_error = str(stream_exc)
                        output, usage_details = await _chat_completion_non_stream(
                            messages,
                            temperature,
                            max_tokens,
                        )
                else:
                    output, usage_details = await _chat_completion_non_stream(
                        messages,
                        temperature,
                        max_tokens,
                    )

            latency_seconds = time.perf_counter() - request_started
            ttft_seconds = (
                first_token_perf - request_started
                if first_token_perf is not None
                else None
            )
            output_tokens = usage_details.get("output") if usage_details else None
            output_tokens_per_second = None
            if output_tokens is not None:
                generation_seconds = latency_seconds
                if ttft_seconds is not None:
                    generation_seconds = max(latency_seconds - ttft_seconds, 0.001)
                output_tokens_per_second = output_tokens / max(generation_seconds, 0.001)

            metric_metadata = {
                **metadata,
                "status": "success",
                "latency_seconds": latency_seconds,
                "time_to_first_token_seconds": ttft_seconds,
                "output_tokens_per_second": output_tokens_per_second,
                "streaming_fallback": streaming_fallback_error is not None,
                "streaming_fallback_error": streaming_fallback_error,
            }
            update_langfuse_observation(
                lf_generation,
                output=output,
                metadata=metric_metadata,
                usage_details=usage_details,
                completion_start_time=completion_start_time,
            )
            if ttft_seconds is not None:
                score_langfuse_observation(
                    lf_generation,
                    "time_to_first_token_seconds",
                    ttft_seconds,
                    metadata={
                        "model": MODEL,
                        "prompt_name": prompt_name,
                        "use_case": metadata.get("use_case"),
                    },
                )
            if output_tokens_per_second is not None:
                score_langfuse_observation(
                    lf_generation,
                    "output_tokens_per_second",
                    output_tokens_per_second,
                    metadata={
                        "model": MODEL,
                        "prompt_name": prompt_name,
                        "use_case": metadata.get("use_case"),
                    },
                )
            return output
        except Exception as exc:
            update_langfuse_observation(
                lf_generation,
                output={"error": str(exc)},
                metadata={**metadata, "status": "error", "error": str(exc)},
                level="ERROR",
                status_message=str(exc),
            )
            raise

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


def build_question_metadata(
    topic_cfg: dict,
    seq: int,
    retrieval_mode: str,
    opening_family: str | None = None,
    trace_payload: dict | None = None,
) -> dict:
    metadata = {
        "question_id": f"{topic_cfg['topic_id']}_q{seq:02d}",
        "topic_id": topic_cfg.get("topic_id"),
        "topic": topic_cfg.get("topic"),
        "chapter_id": topic_cfg.get("chapter_id"),
        "difficulty": topic_cfg.get("difficulty"),
        "seq": seq,
        "retrieval_mode": retrieval_mode,
        "opening_family": opening_family,
    }
    trace_payload = trace_payload or {}
    for key in ("task_id", "session_id", "user_id", "exam_name", "output_name", "use_case"):
        if trace_payload.get(key):
            metadata[key] = trace_payload[key]
    metadata.setdefault("use_case", "generate_exam")
    return metadata


def build_failure_record(
    topic_cfg: dict,
    seq: int,
    stage: str,
    reason: str,
    *,
    details: dict | None = None,
    raw_text: str | None = None,
    parsed: dict | None = None,
) -> dict:
    q_id = f"{topic_cfg['topic_id']}_q{seq:02d}"
    failure = {
        "status": "rejected",
        "question_id": q_id,
        "topic_id": topic_cfg.get("topic_id"),
        "topic": topic_cfg.get("topic"),
        "chapter_id": topic_cfg.get("chapter_id"),
        "difficulty": topic_cfg.get("difficulty"),
        "stage": stage,
        "reason": reason,
        "details": details or {},
    }
    if raw_text is not None:
        failure["raw_preview"] = truncate_for_langfuse(raw_text, 2000)
    if parsed is not None:
        failure["parsed_preview"] = sanitize_for_langfuse(parsed, 2000)
    return failure


def normalize_for_dedup(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_jaccard(a: str, b: str) -> float:
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))


def duplicate_similarity(a: str, b: str) -> float:
    norm_a = normalize_for_dedup(a)
    norm_b = normalize_for_dedup(b)
    if len(norm_a) < DEDUP_MIN_CHARS or len(norm_b) < DEDUP_MIN_CHARS:
        return 0.0
    sequence_score = SequenceMatcher(None, norm_a, norm_b).ratio()
    token_score = token_jaccard(norm_a, norm_b)
    return max(sequence_score, token_score)


def find_duplicate_question(question_text: str, history: list[dict]) -> dict | None:
    best: dict | None = None
    best_score = 0.0
    for item in history:
        if not isinstance(item, dict):
            continue
        old_text = str(item.get("question_text") or "")
        score = duplicate_similarity(question_text, old_text)
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= DEDUP_SIMILARITY_THRESHOLD:
        return {
            "similarity": round(best_score, 4),
            "matched_question_id": best.get("question_id"),
            "matched_question_text": truncate_for_langfuse(best.get("question_text", ""), 600),
            "matched_exam_name": best.get("exam_name"),
            "matched_topic": best.get("topic"),
            "matched_chapter_id": best.get("chapter_id"),
            "threshold": DEDUP_SIMILARITY_THRESHOLD,
        }
    return None


def relevant_history_questions(
    previous_questions: list[dict],
    topic: str,
    chapter_id: str,
    limit: int = 20,
) -> list[dict]:
    exact: list[dict] = []
    same_chapter: list[dict] = []
    others: list[dict] = []
    topic_norm = normalize_for_dedup(topic)
    for item in previous_questions:
        if not isinstance(item, dict):
            continue
        item_topic = normalize_for_dedup(str(item.get("topic") or ""))
        item_chapter = str(item.get("chapter_id") or "")
        if item_chapter == chapter_id and item_topic == topic_norm:
            exact.append(item)
        elif item_chapter == chapter_id:
            same_chapter.append(item)
        else:
            others.append(item)
    return (exact + same_chapter + others)[:limit]


def build_history_avoidance_block(previous_questions: list[dict], topic: str, chapter_id: str) -> str:
    relevant = relevant_history_questions(previous_questions, topic, chapter_id, limit=20)
    if not relevant:
        return ""
    lines = [
        "\nRàng buộc chống trùng lịch sử user:",
        "- Không được tạo lại câu hỏi có cùng stem/tình huống/ý hỏi với các câu dưới đây.",
        "- Hãy đổi bối cảnh, dữ kiện, yêu cầu suy luận và cách hỏi nếu vẫn kiểm tra cùng khái niệm.",
        "- Output vẫn phải đúng JSON theo schema đã yêu cầu.",
        "Các câu hỏi user đã từng nhận:",
    ]
    for idx, item in enumerate(relevant, 1):
        text = re.sub(r"\s+", " ", str(item.get("question_text") or "")).strip()
        if text:
            lines.append(f"{idx}. {truncate_for_langfuse(text, 320)}")
    return "\n".join(lines) + "\n"


def reject_question(
    lf_question,
    topic_cfg: dict,
    seq: int,
    stage: str,
    reason: str,
    *,
    details: dict | None = None,
    raw_text: str | None = None,
    parsed: dict | None = None,
) -> dict:
    failure = build_failure_record(
        topic_cfg,
        seq,
        stage,
        reason,
        details=details,
        raw_text=raw_text,
        parsed=parsed,
    )
    metadata = {
        "status": "rejected",
        "reject_stage": stage,
        "reject_reason": reason,
        **{k: v for k, v in failure.items() if k not in {"raw_preview", "parsed_preview", "details"}},
    }
    if lf_question is None:
        with langfuse_observation(
            "mcqgen.question.rejected",
            as_type="span",
            input={
                "question_id": failure["question_id"],
                "topic": failure.get("topic"),
                "chapter_id": failure.get("chapter_id"),
            },
            output=failure,
            metadata=metadata,
            level="WARNING",
        ):
            pass
    else:
        update_langfuse_observation(
            lf_question,
            output=failure,
            metadata=metadata,
            level="WARNING",
            status_message=f"{stage}: {reason}",
        )
    print(f"  ❌ Rejected [{failure['question_id']}] stage={stage} reason={reason}")
    return failure


def summarize_rag_output(context: str, rag_debug: dict) -> dict:
    scores = rag_debug.get("top_scores_after_rerank", []) if isinstance(rag_debug, dict) else []
    best_score = max(scores) if scores else 0
    return {
        "strategy": rag_debug.get("strategy", "unknown") if isinstance(rag_debug, dict) else "unknown",
        "best_score": best_score,
        "top_scores_after_rerank": scores[:8],
        "context_length": len(context or ""),
        "context_preview": truncate_for_langfuse(context or "", 3000),
    }


@asynccontextmanager
async def atimer(name: str, q_id: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[TIMING] {q_id} | {name} | {dt:.2f}s")


def effective_question_concurrency(total_questions: int, trace_payload: dict | None = None) -> int:
    trace_payload = trace_payload or {}
    if not ENABLE_DYNAMIC_CONCURRENCY:
        return min(MAX_CONCURRENT_QUESTIONS, total_questions or 1)

    active_jobs = int(
        trace_payload.get("runtime_concurrent_traces")
        or trace_payload.get("concurrent_traces_at_start")
        or 1
    )
    active_jobs = max(1, active_jobs)
    per_job_slots = max(1, VLLM_MAX_NUM_SEQS // active_jobs)
    return min(MAX_CONCURRENT_QUESTIONS, per_job_slots, total_questions or 1)


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
    # ── Phase 2: family routing ──
    opening_family: str | None = None,
    trace_payload: dict | None = None,
    duplicate_checker=None,
) -> dict | None:
    topic      = topic_cfg["topic"]
    difficulty = topic_cfg["difficulty"]
    chapter_id = topic_cfg["chapter_id"]
    q_id       = f"{topic_cfg['topic_id']}_q{seq:02d}"
    question_meta = build_question_metadata(
        topic_cfg,
        seq,
        retrieval_mode,
        opening_family=opening_family,
        trace_payload=trace_payload,
    )
    previous_questions = (
        trace_payload.get("previous_questions", [])
        if isinstance(trace_payload, dict)
        else []
    )

    async with atimer("TOTAL", q_id):
        # ── Retrieve context (Phase 2: pass opening_family) ───────
        if precomputed_rag is None:
            async with atimer("RAG", q_id):
                with langfuse_observation(
                    "rag.retrieve",
                    as_type="retriever",
                    input={
                        "topic": topic,
                        "chapter_id": chapter_id,
                        "retrieval_mode": retrieval_mode,
                        "opening_family": opening_family,
                    },
                    metadata=question_meta,
                ) as lf_rag:
                    context, rag_debug = await adaptive_retrieve(
                        topic,
                        chapter_id,
                        mode=retrieval_mode,
                        opening_family=opening_family,
                    )
                    update_langfuse_observation(
                        lf_rag,
                        output=summarize_rag_output(context, rag_debug),
                        metadata={**question_meta, "status": "success"},
                    )
        else:
            context, rag_debug = precomputed_rag
            print(f"    RAG cache hit [{q_id}]")
            with langfuse_observation(
                "rag.cache_hit",
                as_type="retriever",
                input={
                    "topic": topic,
                    "chapter_id": chapter_id,
                    "retrieval_mode": retrieval_mode,
                    "opening_family": opening_family,
                },
                output=summarize_rag_output(context, rag_debug),
                metadata={**question_meta, "status": "cache_hit"},
            ):
                pass
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
        p1_prompt += build_history_avoidance_block(previous_questions, topic, chapter_id)
        async with atimer("P1", q_id):
            raw_p1 = await llm(
                p1_prompt,
                temperature=0.7,
                max_tokens=384,
                trace_name="llm.P1_gen_stem_key",
                trace_metadata={**question_meta, "stage": "P1_gen_stem_key"},
            )
        p1 = parse_json_output(raw_p1)
        if "error" in p1:
            log_llm_parse_error("P1", q_id, raw_p1, p1)
            return reject_question(
                None,
                topic_cfg,
                seq,
                "P1_gen_stem_key",
                "json_parse_error",
                details={"parse_error": p1.get("error")},
                raw_text=raw_p1,
                parsed=p1,
            )

        # ── Call 2: P4 Gen Distractors (Phase 3: misconception-guided) ──
        misconception_guide = build_misconception_guidance(topic)
        p4_prompt = build_p4_option_candidates(
            p1, num_candidates=5,
            misconception_guidance=misconception_guide,
        )
        async with atimer("P4", q_id):
            raw_p4 = await llm(
                p4_prompt,
                temperature=0.7,
                max_tokens=768,
                trace_name="llm.P4_option_candidates",
                trace_metadata={**question_meta, "stage": "P4_option_candidates"},
            )
        p4 = parse_json_output(raw_p4)
        raw_candidates = p4.get("candidate_distractors", []) if "error" not in p4 else []
        candidates = extract_candidate_texts(raw_candidates)
        if not candidates:
            log_llm_parse_error("P4", q_id, raw_p4, p4)
            reason = "json_parse_error" if "error" in p4 else "missing_candidate_distractors"
            return reject_question(
                None,
                topic_cfg,
                seq,
                "P4_option_candidates",
                reason,
                details={
                    "parse_error": p4.get("error"),
                    "candidate_count": len(candidates),
                },
                raw_text=raw_p4,
                parsed=p4,
            )

        # ── Call 3-5: P5+P6+P7 Select Distractors ─────────────────
        correct_options = p1.get("correct_answers_content", [])

        p5_prompt = build_p5_cot_evaluate(p1, candidates, correct_options)
        async with atimer("P5", q_id):
            raw_p5 = await llm(
                p5_prompt,
                temperature=0.1,
                max_tokens=512,
                trace_name="llm.P5_cot_evaluate",
                trace_metadata={**question_meta, "stage": "P5_cot_evaluate"},
            )
        p5 = parse_json_output(raw_p5)
        p5_evals = p5.get("evaluations", []) if "error" not in p5 else []

        p6_prompt = build_p6_remove_bad(p1, candidates, p5_evals)
        async with atimer("P6", q_id):
            raw_p6 = await llm(
                p6_prompt,
                temperature=0.1,
                max_tokens=512,
                trace_name="llm.P6_remove_bad",
                trace_metadata={**question_meta, "stage": "P6_remove_bad"},
            )
        p6 = parse_json_output(raw_p6)
        kept = p6.get("kept_options", candidates[:3]) if "error" not in p6 else \
               [{"option_text": c} for c in candidates[:3]]

        p7_prompt = build_p7_select_final(p1, kept, 1)
        async with atimer("P7", q_id):
            raw_p7 = await llm(
                p7_prompt,
                temperature=0.1,
                max_tokens=512,
                trace_name="llm.P7_select_final",
                trace_metadata={**question_meta, "stage": "P7_select_final"},
            )
        p7 = parse_json_output(raw_p7)
        selected = p7.get("selected_distractors", []) if "error" not in p7 else \
                   [{"option_text": c, "error_type": "fallback", "misleading_score": 5}
                    for c in candidates[:3]]

        # ── Call 6: P8 Assemble ───────────────────────────────────
        p8_prompt = build_p8_assemble(p1, selected[:3], correct_options)
        async with atimer("P8", q_id):
            raw_p8 = await llm(
                p8_prompt,
                temperature=0.3,
                max_tokens=512,
                trace_name="llm.P8_assemble",
                trace_metadata={**question_meta, "stage": "P8_assemble"},
            )
        p8 = parse_json_output(raw_p8)
        if "error" in p8:
            log_llm_parse_error("P8", q_id, raw_p8, p8)
            return reject_question(
                None,
                topic_cfg,
                seq,
                "P8_assemble",
                "json_parse_error",
                details={"parse_error": p8.get("error")},
                raw_text=raw_p8,
                parsed=p8,
            )
        opening_issues = final_opening_issues(
            p8.get("question_text", ""),
            p1.get("opening_family", ""),
        )
        if opening_issues:
            print(f"  ⚠️ OPENING_REPAIR [{q_id}]: {opening_issues}")
            with langfuse_observation(
                "guardrail.opening_check",
                as_type="guardrail",
                input={
                    "question_text": p8.get("question_text", ""),
                    "opening_family": p1.get("opening_family", ""),
                },
                output={"issues": opening_issues, "action": "repair"},
                metadata={**question_meta, "stage": "opening_check", "status": "needs_repair"},
                level="WARNING",
            ):
                pass
            opening_repair_prompt = build_opening_repair_prompt(
                p8,
                opening_issues,
                p1.get("opening_family", ""),
            )
            async with atimer("OPENING_REPAIR", q_id):
                raw_opening_repair = await llm(
                    opening_repair_prompt,
                    temperature=0.1,
                    max_tokens=512,
                    trace_name="llm.OPENING_REPAIR",
                    trace_metadata={**question_meta, "stage": "OPENING_REPAIR"},
                )
            repaired_opening = parse_json_output(raw_opening_repair)
            if "error" in repaired_opening:
                log_llm_parse_error("OPENING_REPAIR", q_id, raw_opening_repair, repaired_opening)
                return reject_question(
                    None,
                    topic_cfg,
                    seq,
                    "OPENING_REPAIR",
                    "json_parse_error",
                    details={"parse_error": repaired_opening.get("error")},
                    raw_text=raw_opening_repair,
                    parsed=repaired_opening,
                )
            remaining_opening_issues = final_opening_issues(
                repaired_opening.get("question_text", ""),
                p1.get("opening_family", ""),
            )
            if remaining_opening_issues:
                print(f"  ❌ OPENING_REJECT [{q_id}]: still has bad opening")
                return reject_question(
                    None,
                    topic_cfg,
                    seq,
                    "opening_check",
                    "opening_repair_failed",
                    details={
                        "initial_issues": opening_issues,
                        "remaining_issues": remaining_opening_issues,
                    },
                    raw_text=raw_opening_repair,
                    parsed=repaired_opening,
                )
            p8 = repaired_opening
        else:
            with langfuse_observation(
                "guardrail.opening_check",
                as_type="guardrail",
                input={
                    "question_text": p8.get("question_text", ""),
                    "opening_family": p1.get("opening_family", ""),
                },
                output={"issues": [], "action": "pass"},
                metadata={**question_meta, "stage": "opening_check", "status": "pass"},
            ):
                pass

        log_mcq_debug(q_id, p8)

        # ── P9: Generate Explanation (tái sử dụng từ src/gen/explain_mcq.py) ──
        if ENABLE_EXPLANATION:
            p9_prompt = build_p9_explanation(p8, concept_context=context)
            async with atimer("P9_EXPLAIN", q_id):
                raw_p9 = await llm(
                    p9_prompt,
                    temperature=0.3,
                    max_tokens=1200,
                    trace_name="llm.P9_explanation",
                    trace_metadata={**question_meta, "stage": "P9_explanation"},
                )
            p9 = parse_json_output(raw_p9)
            if "error" not in p9:
                p8["explanation"] = p9
                print(f"    ✅ Explanation generated [{q_id}]")
            else:
                print(f"    ⚠️  P9 explanation parse error [{q_id}], skipping")
                p8["explanation"] = None

        # ── Optional Call 7: Eval Overall ─────────────────────────
        if ENABLE_LLM_EVAL:
            eval_prompt = build_eval_overall_prompt(p8)
            async with atimer("EVAL", q_id):
                raw_eval = await llm(
                    eval_prompt,
                    temperature=0.1,
                    max_tokens=512,
                    trace_name="llm.final_eval",
                    trace_metadata={**question_meta, "stage": "final_eval"},
                )
            eval_result = parse_json_output(raw_eval)
            if isinstance(eval_result, dict) and not eval_result.get("overall_valid", True):
                print(f"  ⚠️  Rejected [{q_id}]: {eval_result.get('fail_reasons', [])}")
                return reject_question(
                    None,
                    topic_cfg,
                    seq,
                    "final_eval",
                    "llm_eval_rejected",
                    details={
                        "quality_score": eval_result.get("quality_score"),
                        "fail_reasons": eval_result.get("fail_reasons", []),
                    },
                    raw_text=raw_eval,
                    parsed=eval_result,
                )
        else:
            eval_result = {
                "enabled": False,
                "overall_valid": True,
                "quality_score": 0.0,
                "fail_reasons": [],
                "note": "LLM evaluation disabled in production mode.",
            }

        p8["question_id"]    = q_id
        p8["topic"]          = p8.get("topic") or topic
        p8["chapter_id"]     = p8.get("chapter_id") or chapter_id
        p8["difficulty_label"] = p8.get("difficulty_label") or difficulty
        p8["prompt_version"]  = "v1.0"
        p8["rag_strategy"]    = rag_debug.get("strategy", "unknown")
        p8["rag_best_score"]  = max(rag_debug.get("top_scores_after_rerank", [0]))
        p8["evaluation"]  = eval_result
        p8["status"]      = "accepted"
        # ── Propagate diversity metadata from P1 ──
        for meta_key in ("opening_family", "question_form", "tested_skill"):
            if meta_key not in p8 and meta_key in p1:
                p8[meta_key] = p1[meta_key]
        if duplicate_checker is not None:
            duplicate = await duplicate_checker(p8)
            if duplicate:
                return reject_question(
                    None,
                    topic_cfg,
                    seq,
                    "dedup_history",
                    "duplicate_question",
                    details=duplicate,
                    raw_text=p8.get("question_text", ""),
                    parsed=p8,
                )
        score = eval_result.get("quality_score", 0) if isinstance(eval_result, dict) else 0
        with langfuse_observation(
            "mcqgen.question.accepted",
            as_type="span",
            input=question_meta,
            output={
                "question_id": q_id,
                "question_text": p8.get("question_text"),
                "options": p8.get("options"),
                "correct_answers": p8.get("correct_answers"),
                "quality_score": score,
                "rag_strategy": p8.get("rag_strategy"),
                "rag_best_score": p8.get("rag_best_score"),
            },
            metadata={**question_meta, "status": "accepted", "quality_score": score},
        ):
            pass
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

    accepted = [
        r for r in results
        if isinstance(r, dict) and r.get("status") == "accepted"
    ]
    failures = [
        r for r in results
        if isinstance(r, dict) and r.get("status") == "rejected"
    ]
    failures.extend(
        build_failure_record(
            {"topic_id": "unknown", "topic": "", "chapter_id": "", "difficulty": ""},
            idx,
            "exception",
            "generation_exception",
            details={"error": repr(r)},
        )
        for idx, r in enumerate(results)
        if isinstance(r, Exception)
    )
    failed = len(all_tasks) - len(accepted)
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
    trace_payload: dict | None = None,
) -> dict:
    """Được gọi từ Celery task."""
    trace_payload = trace_payload or {}
    session_id = trace_payload.get("session_id") or (
        f"exam:{trace_payload.get('task_id')}" if trace_payload.get("task_id") else None
    )
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

    with langfuse_attributes(
        user_id=trace_payload.get("user_id"),
        session_id=session_id,
        tags=trace_payload.get("langfuse_tags") or ["app:mcqgen", "usecase:generate_exam"],
        metadata={
            **trace_payload,
            "use_case": trace_payload.get("use_case") or "generate_exam",
            "output_name": output_name,
            "retrieval_mode": retrieval_mode,
            "total_questions": total_questions,
        },
        trace_name="mcqgen.generate_exam",
    ):
        with langfuse_observation(
            "pipeline.run_pipeline_with_topics",
            as_type="chain",
            input={
                "topics": topics,
                "output_name": output_name,
                "retrieval_mode": retrieval_mode,
            },
            metadata={
                **trace_payload,
                "use_case": trace_payload.get("use_case") or "generate_exam",
                "total_questions": total_questions,
                "topic_count": len(topics),
            },
        ) as lf_pipeline:
            result = await _run_pipeline_with_topics_impl(
                topics=topics,
                output_name=output_name,
                progress_callback=progress_callback,
                retrieval_mode=retrieval_mode,
                trace_payload=trace_payload,
                total_questions=total_questions,
                task_specs=task_specs,
                emit_progress=emit_progress,
            )
            update_langfuse_observation(
                lf_pipeline,
                output={
                    "accepted": result.get("accepted"),
                    "failed": result.get("failed"),
                    "failure_stage_counts": result.get("failure_stage_counts"),
                    "output_file": result.get("output_file"),
                },
                metadata={
                    **trace_payload,
                    "accepted": result.get("accepted"),
                    "failed": result.get("failed"),
                    "failure_stage_counts": result.get("failure_stage_counts"),
                },
            )
            return result


async def _run_pipeline_with_topics_impl(
    *,
    topics: list,
    output_name: str,
    progress_callback,
    retrieval_mode: str,
    trace_payload: dict,
    total_questions: int,
    task_specs: list,
    emit_progress,
) -> dict:
    emit_progress(10, "retrieving_context",
                  current_question=0, total_questions=total_questions)

    rag_cache: dict[tuple[str, str, str], tuple[str, dict]] = {}
    unique_topic_configs: dict[tuple[str, str, str], dict] = {}
    for topic_cfg, _seq in task_specs:
        key = (topic_cfg["topic"], topic_cfg["chapter_id"], retrieval_mode)
        unique_topic_configs.setdefault(key, topic_cfg)

    # Phase 2: RAG precompute is SKIPPED when opening_family routing is active.
    # RAG will be called lazily inside generate_one_mcq after opening_family is known.
    # This lets family routing (cross-chapter, multi-query) adapt to each question type.
    use_lazy_rag = os.getenv("ENABLE_LAZY_RAG", "true").lower() == "true"

    if not use_lazy_rag:
        # Legacy: precompute RAG (no family routing)
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
    else:
        # Phase 2: Lazy RAG — skip precompute, go straight to generation
        emit_progress(25, "lazy_rag_enabled",
                      current_question=0, total_questions=total_questions)

    completed_questions = 0

    # ── Phase 1: diversity tracking ──
    _diversity_lock = asyncio.Lock()
    used_families: list[str] = []
    previous_openings: list[str] = []
    _dedup_lock = asyncio.Lock()
    previous_questions = (
        trace_payload.get("previous_questions", [])
        if isinstance(trace_payload, dict)
        else []
    )
    seen_questions: list[dict] = [
        item for item in previous_questions if isinstance(item, dict)
    ]

    async def duplicate_checker(mcq: dict) -> dict | None:
        question_text = str(mcq.get("question_text") or "")
        async with _dedup_lock:
            duplicate = find_duplicate_question(question_text, seen_questions)
            if duplicate:
                duplicate["dedup_scope"] = "user_history_or_current_job"
                duplicate["candidate_question_text"] = truncate_for_langfuse(question_text, 600)
                return duplicate
            seen_questions.append(
                {
                    "question_id": mcq.get("question_id"),
                    "question_text": question_text,
                    "topic": mcq.get("topic"),
                    "chapter_id": mcq.get("chapter_id"),
                    "exam_name": trace_payload.get("exam_name") if isinstance(trace_payload, dict) else None,
                }
            )
        return None

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
                opening_family=family,  # Phase 2: pass family for routing
                trace_payload=trace_payload,
                duplicate_checker=duplicate_checker,
            )

            # Update previous_openings after successful generation
            if result and result.get("status") == "accepted" and result.get("question_text"):
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

    max_concurrent_questions = effective_question_concurrency(total_questions, trace_payload)
    trace_payload["effective_question_concurrency"] = max_concurrent_questions
    trace_payload["dynamic_concurrency"] = ENABLE_DYNAMIC_CONCURRENCY
    semaphore = asyncio.Semaphore(max_concurrent_questions)

    async def bounded_tracked_generate(topic_cfg: dict, seq: int):
        async with semaphore:
            return await tracked_generate(topic_cfg, seq)

    emit_progress(
        25,
        "Đang sinh câu hỏi",
        current_question=0,
        total_questions=total_questions,
        target_concurrent_users=TARGET_CONCURRENT_USERS,
        celery_generation_concurrency=CELERY_GENERATION_CONCURRENCY,
        dynamic_concurrency=ENABLE_DYNAMIC_CONCURRENCY,
        runtime_concurrent_traces=trace_payload.get("runtime_concurrent_traces"),
        effective_question_concurrency=max_concurrent_questions,
        question_concurrency=max_concurrent_questions,
        llm_concurrency=MAX_CONCURRENT_LLM_REQUESTS,
    )

    all_tasks = [bounded_tracked_generate(topic_cfg, seq) for topic_cfg, seq in task_specs]
    results = await asyncio.gather(*all_tasks, return_exceptions=True) if all_tasks else []
    for result in results:
        if isinstance(result, Exception):
            print(f"  ❌ generation exception: {result!r}")
    accepted = [
        r for r in results
        if isinstance(r, dict) and r.get("status") == "accepted"
    ]
    failures = [
        r for r in results
        if isinstance(r, dict) and r.get("status") == "rejected"
    ]
    failures.extend(
        build_failure_record(
            {"topic_id": "unknown", "topic": "", "chapter_id": "", "difficulty": ""},
            idx,
            "exception",
            "generation_exception",
            details={"error": repr(result)},
        )
        for idx, result in enumerate(results)
        if isinstance(result, Exception)
    )
    failure_stage_counts = Counter(
        failure.get("stage", "unknown")
        for failure in failures
        if isinstance(failure, dict)
    )

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
        "failures": failures,
        "failure_stage_counts": dict(failure_stage_counts),
        "output_file": str(out_file),
        "mcqs": accepted,
        "target_concurrent_users": TARGET_CONCURRENT_USERS,
        "celery_generation_concurrency": CELERY_GENERATION_CONCURRENCY,
        "dynamic_concurrency": ENABLE_DYNAMIC_CONCURRENCY,
        "runtime_concurrent_traces": trace_payload.get("runtime_concurrent_traces"),
        "runtime_concurrent_users": trace_payload.get("runtime_concurrent_users"),
        "effective_question_concurrency": max_concurrent_questions,
        "question_concurrency": max_concurrent_questions,
        "llm_concurrency": MAX_CONCURRENT_LLM_REQUESTS,
        "vllm_url": VLLM_URL,
        "vllm_model": MODEL,
    }
