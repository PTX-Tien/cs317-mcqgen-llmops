import sys
sys.path.insert(0, '.')
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer

INDEX_DIR = Path("data/indexes")
client = chromadb.PersistentClient(path=str(INDEX_DIR))
collection = client.get_collection("concept_chunks")
model = SentenceTransformer("BAAI/bge-m3", device="cpu")

def retrieve(topic: str, top_k: int = 5):
    query_emb = model.encode([topic])[0].tolist()
    results = collection.query(
        query_embeddings=[query_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]
    print(f"\n=== Top {top_k} chunks for: '{topic}' ===")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        print(f"\n[{i+1}] score={1-dist:.3f} | {meta['source_type']} | {meta['chapter_id']}")
        print(f"     {doc[:200]}...")

retrieve("Missing Data")
retrieve("CNN Neural Networks")
retrieve("Decision Trees")
