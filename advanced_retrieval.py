"""
advanced_retrieval.py — HyDE + Sentence-Window + Cross-Encoder Reranker
Thay thế retrieve_context() trong pipeline_mcq.py
"""
import asyncio
from pathlib import Path
from openai import AsyncOpenAI
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb

# ── Config ────────────────────────────────────────────────────────
INDEX_DIR  = Path("data/indexes")
VLLM_URL   = "http://localhost:8000/v1"
MODEL      = "mcqgen"

# ── Models (load 1 lần) ───────────────────────────────────────────
print("Loading embedding + reranker models...")
emb_model  = SentenceTransformer("BAAI/bge-m3", device="cpu")
reranker   = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu")
chroma     = chromadb.PersistentClient(path=str(INDEX_DIR))
collection = chroma.get_collection("concept_chunks")
llm_client = AsyncOpenAI(base_url=VLLM_URL, api_key="x")
print("Models ready.\n")


# ── Step 1: HyDE — generate hypothetical question ─────────────────
async def generate_hyde_query(topic: str) -> str:
    """Dùng LLM tạo câu hỏi giả định → embed thay vì embed raw topic."""
    resp = await llm_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            f'[QUAN TRỌNG: Trả lời HOÀN TOÀN bằng tiếng Việt]\n'
            f'Môn CS116 tại ĐH CNTT TP.HCM sử dụng: Python, NumPy, Pandas, Scikit-learn, PyTorch, Matplotlib.\n'
            f'KHÔNG đề cập TensorFlow, Keras, R, MATLAB.\n'
            f'Viết 1 câu hỏi trắc nghiệm ngắn bằng TIẾNG VIỆT về "{topic}".\n'
            f'Yêu cầu: chỉ câu hỏi stem tiếng Việt, đề cập tên hàm/thư viện/thuật toán cụ thể trong môn học.\n'
            f'Ví dụ tốt: "Tầng Convolution trong mạng CNN với PyTorch sử dụng lớp nào để thực hiện tích chập?"\n'
            f'Ví dụ tốt: "Tham số max_depth trong DecisionTreeClassifier của sklearn có tác dụng gì?"'}],
        max_tokens=100,
        temperature=0.2,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    )
    return resp.choices[0].message.content.strip()


# ── Step 2: Dual embedding (topic + HyDE) ─────────────────────────
def dual_embed(topic: str, hypo_question: str) -> list[float]:
    """Ensemble embedding: 0.5*topic + 0.3*hypo + 0.2*combined."""
    import numpy as np
    combined = f"{topic}: {hypo_question}"
    embs = emb_model.encode([topic, hypo_question, combined])
    # Weighted average: ưu tiên topic gốc
    avg = 0.5 * embs[0] + 0.3 * embs[1] + 0.2 * embs[2]
    avg = avg / (np.linalg.norm(avg) + 1e-8)
    return avg.tolist()


# ── Step 3: Retrieve + CRAG check ─────────────────────────────────
def retrieve_candidates(
    embedding: list[float],
    chapter_id: str,
    top_k: int = 12
) -> tuple[list[str], list[dict], list[float]]:
    """Retrieve top-k chunks, trả về docs, metas, distances."""
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where={"chapter_id": chapter_id},
        include=["documents", "metadatas", "distances"]
    )
    docs   = results["documents"][0]
    metas  = results["metadatas"][0]
    dists  = results["distances"][0]
    return docs, metas, dists


def crag_needs_rewrite(distances: list[float], threshold: float = 0.25) -> bool:
    """Nếu top chunk vẫn quá xa → cần rewrite query."""
    if not distances:
        return True
    best_score = 1 - min(distances)  # convert distance → similarity
    return best_score < threshold  # threshold=0.25: chỉ trigger khi retrieval thực sự kém


# ── Step 4: Cross-Encoder Rerank ──────────────────────────────────
def rerank(query: str, docs: list[str], top_k: int = 5) -> list[int]:
    """Rerank docs bằng cross-encoder, trả về indices của top_k tốt nhất."""
    if not docs:
        return []
    pairs  = [(query, doc[:512]) for doc in docs]
    scores = reranker.predict(pairs)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_k]


# ── Step 5: Format context ────────────────────────────────────────
def format_context(docs: list[str], metas: list[dict], selected_indices: list[int]) -> str:
    blocks = []
    for rank, idx in enumerate(selected_indices, 1):
        if idx >= len(docs):
            continue
        doc  = docs[idx]
        meta = metas[idx]
        src  = f"[{meta.get('source_type','?')}|{meta.get('source_file','?')}]"
        blocks.append(f"--- Context {rank} {src} ---\n{doc[:1500]}")
    return "\n\n".join(blocks)


# ── Main entry point ──────────────────────────────────────────────
async def advanced_retrieve(
    topic: str,
    chapter_id: str,
    top_k_final: int = 5
) -> tuple[str, dict]:
    """
    Full pipeline: HyDE → Dual Embed → Retrieve → CRAG → Rerank → Format.
    Returns: (context_str, debug_info)
    """
    debug = {}

    # Step 1: HyDE
    hypo_q = await generate_hyde_query(topic)
    debug["hyde_query"] = hypo_q

    # Step 2: Dual embed
    embedding = dual_embed(topic, hypo_q)

    # Step 3: Retrieve
    docs, metas, dists = retrieve_candidates(embedding, chapter_id, top_k=12)
    debug["top_scores_before_rerank"] = [round(1 - d, 3) for d in dists[:5]]

    # CRAG check — nếu retrieval kém → thêm query không filter chapter
    if crag_needs_rewrite(dists):
        debug["crag_triggered"] = True
        docs2, metas2, dists2 = retrieve_candidates(embedding, chapter_id, top_k=6)
        # Merge và deduplicate
        seen = set()
        for d, m, dist in zip(docs2, metas2, dists2):
            key = d[:80]
            if key not in seen:
                seen.add(key)
                docs.append(d)
                metas.append(m)
                dists.append(dist)
    else:
        debug["crag_triggered"] = False

    # Step 4: Rerank với cross-encoder
    rerank_query = f"{topic} {hypo_q}"
    selected_idx = rerank(rerank_query, docs, top_k=top_k_final)
    debug["top_scores_after_rerank"] = [
        round(1 - dists[i], 3) for i in selected_idx if i < len(dists)
    ]

    # Step 5: Format
    context = format_context(docs, metas, selected_idx)
    return context, debug


# ── Benchmark so sánh naive vs advanced ──────────────────────────
async def benchmark():
    import time
    from sentence_transformers import SentenceTransformer
    import chromadb as _chroma

    test_cases = [
        ("Missing Data",       "ch04"),
        ("Decision Trees",     "ch07b"),
        ("CNN Neural Networks","ch08"),
        ("Outlier Detection",  "ch04"),
    ]

    print("=" * 60)
    print("BENCHMARK: Naive vs Advanced RAG")
    print("=" * 60)

    for topic, chapter_id in test_cases:
        # Naive
        emb_n = emb_model.encode([topic])[0].tolist()
        r_n   = collection.query(
            query_embeddings=[emb_n], n_results=5,
            where={"chapter_id": chapter_id},
            include=["distances"]
        )
        naive_scores = [round(1 - d, 3) for d in r_n["distances"][0]]

        # Advanced
        t0 = time.time()
        ctx, dbg = await advanced_retrieve(topic, chapter_id)
        elapsed = time.time() - t0

        print(f"\nTopic: {topic}")
        print(f"  Naive top-3 scores : {naive_scores[:3]}")
        print(f"  Advanced top-3     : {dbg['top_scores_after_rerank'][:3]}")
        print(f"  HyDE query         : {dbg['hyde_query'][:80]}")
        print(f"  CRAG triggered     : {dbg['crag_triggered']}")
        print(f"  Retrieval time     : {elapsed:.1f}s")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(benchmark())


# ── Adaptive RAG — entry point chính thức ─────────────────────────
async def adaptive_retrieve(
    topic: str,
    chapter_id: str,
    naive_threshold: float = 0.25,
    top_k_final: int = 5
) -> tuple[str, dict]:
    """
    Adaptive RAG:
    - Nếu naive retrieval đủ tốt (best score >= threshold) → dùng naive + rerank
    - Nếu kém → dùng HyDE + dual embed + rerank
    """
    import numpy as np
    debug = {}

    # Step 1: Thử naive trước
    emb_naive = emb_model.encode([topic])[0].tolist()
    docs, metas, dists = retrieve_candidates(emb_naive, chapter_id, top_k=12)
    best_naive = 1 - min(dists) if dists else 0.0
    debug["naive_best_score"] = round(best_naive, 3)

    if best_naive >= naive_threshold:
        # Naive đã tốt → chỉ rerank
        debug["strategy"] = "naive+rerank"
        debug["hyde_query"] = None
        debug["crag_triggered"] = False
    else:
        # Naive kém → dùng HyDE
        debug["strategy"] = "hyde+rerank"
        hypo_q = await generate_hyde_query(topic)
        debug["hyde_query"] = hypo_q

        # Ensemble: 60% topic + 40% hypo (ưu tiên topic hơn)
        embs = emb_model.encode([topic, hypo_q])
        avg  = 0.6 * embs[0] + 0.4 * embs[1]
        avg  = avg / (np.linalg.norm(avg) + 1e-8)
        docs2, metas2, dists2 = retrieve_candidates(avg.tolist(), chapter_id, top_k=12)

        # Merge naive + HyDE, deduplicate
        seen = set()
        for d, m, dist in zip(docs, metas, dists):
            key = d[:80]
            if key not in seen:
                seen.add(key); docs2.append(d); metas2.append(m); dists2.append(dist)
        docs, metas, dists = docs2, metas2, dists2
        debug["crag_triggered"] = True

    # Step 2: Rerank với cross-encoder
    selected_idx = rerank(topic, docs, top_k=top_k_final)
    debug["top_scores_after_rerank"] = [
        round(1 - dists[i], 3) for i in selected_idx if i < len(dists)
    ]

    context = format_context(docs, metas, selected_idx)
    return context, debug


# ── Benchmark Adaptive vs Naive ───────────────────────────────────
async def benchmark_adaptive():
    test_cases = [
        ("Missing Data",        "ch04"),
        ("Decision Trees",      "ch07b"),
        ("CNN Neural Networks", "ch08"),
        ("Outlier Detection",   "ch04"),
    ]

    print("=" * 60)
    print("BENCHMARK: Naive vs Adaptive RAG")
    print("=" * 60)

    for topic, chapter_id in test_cases:
        # Naive score (reference)
        emb_n = emb_model.encode([topic])[0].tolist()
        r_n   = collection.query(
            query_embeddings=[emb_n], n_results=3,
            where={"chapter_id": chapter_id},
            include=["distances"]
        )
        naive_scores = [round(1 - d, 3) for d in r_n["distances"][0]]

        # Adaptive
        import time
        t0 = time.time()
        ctx, dbg = await adaptive_retrieve(topic, chapter_id)
        elapsed = time.time() - t0

        best_naive    = max(naive_scores)
        best_adaptive = max(dbg["top_scores_after_rerank"]) if dbg["top_scores_after_rerank"] else 0
        delta = best_adaptive - best_naive
        verdict = "✅" if delta >= -0.01 else "❌"

        print(f"\nTopic: {topic}")
        print(f"  Strategy           : {dbg['strategy']}")
        print(f"  Naive top-3        : {naive_scores}")
        print(f"  Adaptive top-3     : {dbg['top_scores_after_rerank'][:3]}")
        print(f"  Best: {best_naive:.3f} → {best_adaptive:.3f} ({delta:+.3f}) {verdict}")
        print(f"  Time               : {elapsed:.1f}s")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import asyncio, sys
    if len(sys.argv) > 1 and sys.argv[1] == "adaptive":
        asyncio.run(benchmark_adaptive())
    else:
        asyncio.run(benchmark())
