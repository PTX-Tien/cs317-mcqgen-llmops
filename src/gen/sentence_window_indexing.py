"""
sentence_window_indexing.py — Rebuild index với Sentence-Window technique
Mỗi sentence được index riêng, kèm window_text để dùng khi generate MCQ.

Chạy: python src/gen/sentence_window_indexing.py
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, ".")

from src.mcqgen.common import Config, config, save_jsonl

WINDOW_SIZE = 2  # ±2 sentences xung quanh

def split_sentences(text: str) -> list[str]:
    """Tách text thành sentences, filter quá ngắn."""
    # Split theo dấu câu tiếng Việt + tiếng Anh
    sentences = re.split(r'(?<=[.!?])\s+|(?<=\n)\s*•\s*|(?<=\n)-\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip().split()) >= 6]
    return sentences


def build_sentence_windows(chunks: list[dict]) -> list[dict]:
    """
    Từ chunk gốc → list sentence chunks với window_text.
    Mỗi sentence chunk:
    - text: 1 sentence (dùng để embed + retrieve)
    - window_text: ±WINDOW_SIZE sentences (dùng để generate MCQ)
    - parent_chunk_id: chunk gốc
    """
    sw_chunks = []

    for chunk in chunks:
        text = chunk.get("text", "").strip()
        if not text:
            continue

        sentences = split_sentences(text)
        if len(sentences) < 2:
            # Chunk quá ngắn → giữ nguyên, không tách
            sw_chunks.append({
                **chunk,
                "window_text": text,
                "parent_chunk_id": chunk["chunk_id"],
                "sentence_index": 0,
                "is_sentence_window": False,
            })
            continue

        for i, sent in enumerate(sentences):
            # Expand window ±WINDOW_SIZE
            start = max(0, i - WINDOW_SIZE)
            end   = min(len(sentences), i + WINDOW_SIZE + 1)
            window = " ".join(sentences[start:end])

            sw_chunk = {
                **chunk,
                "chunk_id":         f"{chunk['chunk_id']}_sw{i:03d}",
                "text":             sent,          # nhỏ → embed chính xác
                "window_text":      window,        # lớn → dùng khi generate
                "parent_chunk_id":  chunk["chunk_id"],
                "sentence_index":   i,
                "is_sentence_window": True,
            }
            sw_chunks.append(sw_chunk)

    return sw_chunks


def run_sw_indexing():
    config.makedirs()

    # Load concept_chunks.jsonl đã có
    chunks_file = Config.CONCEPT_CHUNKS_FILE
    if not chunks_file.exists():
        print(f"❌ {chunks_file} not found — chạy indexing.py trước")
        return

    print(f"Loading chunks from {chunks_file}...")
    with open(chunks_file, "r", encoding="utf-8") as f:
        chunks = [json.loads(l) for l in f if l.strip()]
    print(f"  Loaded: {len(chunks)} original chunks")

    # Build sentence windows
    print("Building sentence windows...")
    sw_chunks = build_sentence_windows(chunks)
    print(f"  Generated: {len(sw_chunks)} sentence-window chunks")
    print(f"  Expansion ratio: {len(sw_chunks)/len(chunks):.1f}×")

    # Save sw chunks
    sw_file = Config.PROCESSED_DIR / "concept_chunks_sw.jsonl"
    save_jsonl(sw_chunks, sw_file)
    print(f"  Saved: {sw_file}")

    # Embed và store vào collection riêng
    from sentence_transformers import SentenceTransformer
    import chromadb

    client = chromadb.PersistentClient(path=str(Config.INDEX_DIR))

    # Xóa collection cũ nếu có
    try:
        client.delete_collection("concept_chunks_sw")
    except Exception:
        pass
    collection = client.get_or_create_collection("concept_chunks_sw")

    print("Loading BGE-m3...")
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")

    # Embed TEXT (sentence nhỏ) — không phải window_text
    texts = [c["text"][:512] for c in sw_chunks]
    print(f"Embedding {len(texts)} sentences...")
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=True)

    # Store với metadata đầy đủ
    ids       = [c["chunk_id"] for c in sw_chunks]
    documents = [c["window_text"] for c in sw_chunks]  # store window_text làm document
    metadatas = []
    for c in sw_chunks:
        metadatas.append({
            "chunk_id":        c["chunk_id"],
            "parent_chunk_id": c.get("parent_chunk_id", ""),
            "chapter_id":      c.get("chapter_id", ""),
            "chapter_title":   c.get("chapter_title", ""),
            "topic":           "|".join(c.get("topics", [])) if c.get("topics") else "",
            "source_type":     c.get("source_type", ""),
            "source_file":     c.get("source_file", ""),
            "sentence_index":  c.get("sentence_index", 0),
            "is_sentence_window": c.get("is_sentence_window", False),
        })

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings.tolist(),
    )
    print(f"✅ Stored {len(sw_chunks)} sentence-window chunks in ChromaDB")
    print(f"   Collection: concept_chunks_sw")

    # Quick stats
    sw_count  = sum(1 for c in sw_chunks if c.get("is_sentence_window"))
    kept_count = len(sw_chunks) - sw_count
    print(f"\n📊 Stats:")
    print(f"   Sentence-window chunks : {sw_count}")
    print(f"   Kept-as-is chunks      : {kept_count}")
    print(f"   Total                  : {len(sw_chunks)}")


if __name__ == "__main__":
    run_sw_indexing()
