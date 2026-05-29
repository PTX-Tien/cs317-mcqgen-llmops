"""
chunk_transcript_with_timestamps.py — Step 01b: Chunk JSON Transcripts with YouTube Timestamps

Input:
  - input/transcribe_data/*.json       (Whisper JSON: segments with word-level timestamps)
  - input/video/videos1.txt           (line-indexed YouTube URL mapping)

Output:
  - data/processed/transcript_chunks_with_timestamps.jsonl
    Mỗi chunk có: chunk_id, text, timestamp_start, timestamp_end, youtube_url,
    chapter_id, source_file, source_type="video_transcript", topics, text_clean

Logic:
  1. Parse videos1.txt → sequential line_number → youtube_url mapping
  2. Parse JSON transcript → flatten word-level timestamps per segment
  3. Deduplicate: loại bỏ đoạn lặp do lỗi nối file ASR
  4. Chunk by words (target=200, min=80, overlap=30) — gom câu nguyên vẹn
     HOẶC Semantic chunking (CHUNKING_MODE=semantic) — cắt theo embedding similarity
  5. Map timestamp → youtube_url
  6. Save JSONL

Phase 1 v2 fixes:
  - Fix #1: Sentence splitter dùng word-count fallback khi Whisper thiếu dấu câu
  - Fix #2: Merge/split chunks enforce min=80, max=400 words nghiêm ngặt
  - Fix #3: Split mega-sentences tại word-level khi sentence chỉ có 1 phần tử
"""

from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path

import numpy as np

from .common import Config, save_jsonl


# ─── Mapping video → YouTube URL ────────────────────────────────────────────
VIDEO_META_MAP: dict[tuple[str, int], dict] = {}


def _parse_slide_metadata(raw: str) -> tuple[str, int]:
    raw = raw.strip()
    if not raw or raw.lower() == "none":
        return "", 0
    slide_match = re.search(r"slide:\s*([^,]+)", raw, re.IGNORECASE)
    page_match  = re.search(r"trang\s+(\d+)", raw, re.IGNORECASE)
    slide_file    = slide_match.group(1).strip() if slide_match else ""
    slide_start_page = int(page_match.group(1)) if page_match else 0
    return slide_file, slide_start_page


def _build_video_url_map() -> None:
    videos1 = Config.INPUT_DIR / "videos1.txt"
    if not videos1.exists():
        print(f"⚠️  {videos1} not found — youtube_url will be empty")
        return
    lines = videos1.read_text(encoding="utf-8").strip().split("\n")
    current_chapter: int | None = None
    sub_index: int = 0
    for line in lines:
        if "|" not in line:
            continue
        parts = line.split("|")
        url = parts[1].strip().split(",")[0].strip()
        extra = parts[2].strip() if len(parts) > 2 else ""
        slide_file, slide_start_page = _parse_slide_metadata(extra)
        try:
            ch_int = int(parts[0].strip())
        except ValueError:
            continue
        if ch_int != current_chapter:
            current_chapter = ch_int
            sub_index = 1
        else:
            sub_index += 1
        chapter_id = f"ch{ch_int:02d}"
        VIDEO_META_MAP[(chapter_id, sub_index)] = {
            "url": url, "slide_file": slide_file, "slide_start_page": slide_start_page,
        }
        if slide_file:
            print(f"  [video_map] {chapter_id} sub={sub_index}: {url} → slide={slide_file} page={slide_start_page}")


# ─── Deduplication ────────────────────────────────────────────────────────────

def _deduplicate_text(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\b(.{2,100}?)(?:\s+\1\b)+", r"\1", text)
    return text.strip()


# ─── Core chunking (LEGACY — word-count based) ──────────────────────────────

CHUNK_CONFIG = {
    "target_words": 200,
    "min_words": 80,
    "overlap_words": 30,
}


def _chunk_segments(
    all_words: list[dict],
    chapter_id: str,
    video_sub: str,
    source_file: str,
    topics: list[str],
    chapter_title: str,
) -> list[dict]:
    target = CHUNK_CONFIG["target_words"]
    min_w = CHUNK_CONFIG["min_words"]
    overlap = CHUNK_CONFIG["overlap_words"]
    chunks = []
    n = len(all_words)
    pos = 0
    seq = 1
    while pos < n:
        end_pos = min(pos + target, n)
        start_ts = all_words[pos]["start"]
        end_ts = all_words[end_pos - 1]["end"]
        best_cut = end_pos
        if end_pos < n:
            candidates = []
            for i in range(pos, min(pos + target + 20, n)):
                w = all_words[i]["word"].strip()
                if w and w[-1] in ".?!":
                    dist = i - pos
                    candidates.append((abs(dist - target), dist, i + 1))
            if candidates:
                candidates.sort()
                _, _, best_cut = candidates[0]
                best_cut = min(best_cut, n)
        chunk_words = all_words[pos:best_cut]
        raw_text = " ".join(w["word"].strip() for w in chunk_words)
        clean_text = _deduplicate_text(raw_text)
        if len(clean_text.split()) < min_w and raw_text.strip():
            clean_text = raw_text.strip()
        if clean_text and len(clean_text.split()) >= min_w:
            video_meta = VIDEO_META_MAP.get((chapter_id, int(video_sub)), {})
            youtube_url = video_meta.get("url", "")
            slide_file = video_meta.get("slide_file", "")
            slide_start_page = video_meta.get("slide_start_page", 0)
            chunk_id = f"cs116_{chapter_id}_transcript_{video_sub}_s{seq:03d}"
            chunk = {
                "chunk_id": chunk_id,
                "course_id": "CS116",
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "topics": topics,
                "source_type": "video_transcript",
                "source_file": source_file,
                "page_number": int(video_sub),
                "section_title": "",
                "text": clean_text,
                "timestamp_start": round(start_ts, 3),
                "timestamp_end": round(end_ts, 3),
                "youtube_url": youtube_url,
                "youtube_timestamp_start": _format_youtube_ts(start_ts),
                "youtube_timestamp_end": _format_youtube_ts(end_ts),
                "slide_file": slide_file,
                "slide_start_page": slide_start_page,
                "word_count": len(clean_text.split()),
                "embedding_ready": True,
            }
            chunks.append(chunk)
            seq += 1
        advance = target - overlap
        pos += advance
        if pos >= end_pos - 1:
            pos = end_pos
    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 v2: Semantic Chunking — FIXED
# ═══════════════════════════════════════════════════════════════════════════════

_emb_model = None


def _get_emb_model():
    global _emb_model
    if _emb_model is None:
        from sentence_transformers import SentenceTransformer
        print("  🔄 [Semantic Chunking] Loading BGE-m3 embedding model...")
        _emb_model = SentenceTransformer("BAAI/bge-m3", device="cpu")
        print("  ✅ [Semantic Chunking] BGE-m3 ready")
    return _emb_model


# ─────────────────────────────────────────────────────────────────────────────
# FIX #1: Sentence splitter — dùng word-count fallback khi thiếu dấu câu
#
# Vấn đề gốc: Whisper tiếng Việt rất ít dấu câu (giảng viên nói liên tục,
# Whisper không chèn dấu chấm). Nên dùng chỉ ".?!" tạo ra "câu" dài 200-500 từ
# → breakpoint detection vô hiệu vì mỗi "câu" đã là 1 đoạn lớn.
#
# Fix: Thêm word-count ceiling — nếu câu tích lũy > MAX_SENTENCE_WORDS từ
# mà chưa gặp dấu câu, cắt tại pause gần nhất hoặc cắt cứng.
# ─────────────────────────────────────────────────────────────────────────────

MAX_SENTENCE_WORDS = 40  # Ceiling: mỗi "sentence" tối đa ~40 từ


def _build_sentences_from_words(all_words: list[dict]) -> list[dict]:
    """
    Ghép word-level dicts thành sentence-level dicts.

    Cắt câu dựa trên (ưu tiên từ trên xuống):
      1. Dấu câu: . ? ! 。
      2. Pause dài (> 1.5 giây giữa 2 từ liền kề)
      3. Word-count ceiling: tối đa MAX_SENTENCE_WORDS từ
         → tìm pause ngắn nhất gần vị trí ceiling để cắt tự nhiên hơn
    """
    if not all_words:
        return []

    sentences = []
    current_words: list[dict] = []
    current_start_idx = 0

    def _emit_sentence(words: list[dict], start_idx: int, end_idx: int):
        """Helper: tạo sentence dict từ accumulated words."""
        if not words:
            return
        text = " ".join(w["word"].strip() for w in words)
        text = _deduplicate_text(text)
        if text and len(text.split()) >= 3:
            sentences.append({
                "text": text,
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "word_start_idx": start_idx,
                "word_end_idx": end_idx,
            })

    for i, w in enumerate(all_words):
        current_words.append(w)
        word_text = w["word"].strip()

        # ── Điều kiện 1: Dấu câu ──
        is_punctuation_end = word_text and word_text[-1] in ".?!。"

        # ── Điều kiện 2: Pause dài (giảm từ 2.0 → 1.5s để tạo câu ngắn hơn) ──
        is_long_pause = (
            i + 1 < len(all_words)
            and all_words[i + 1]["start"] - w["end"] > 1.5
        )

        # ── Điều kiện 3: Word-count ceiling ──
        hit_word_ceiling = len(current_words) >= MAX_SENTENCE_WORDS

        # Nếu hit ceiling nhưng chưa gặp dấu câu/pause → tìm pause gần nhất
        # trong nửa sau của current_words để cắt tự nhiên hơn
        force_cut_at = None
        if hit_word_ceiling and not is_punctuation_end and not is_long_pause:
            # Tìm pause lớn nhất trong nửa sau
            half = len(current_words) // 2
            best_pause = 0.0
            best_pause_idx = None
            for j in range(half, len(current_words) - 1):
                w_cur = current_words[j]
                w_next = current_words[j + 1]
                pause = w_next["start"] - w_cur["end"]
                if pause > best_pause:
                    best_pause = pause
                    best_pause_idx = j
            # Nếu tìm được pause > 0.3s → cắt tại đó, ngược lại cắt cứng
            if best_pause_idx is not None and best_pause > 0.3:
                force_cut_at = best_pause_idx
            else:
                force_cut_at = len(current_words) - 1  # cắt cứng tại vị trí hiện tại

        # ── Quyết định cắt ──
        should_cut = is_punctuation_end or is_long_pause or i == len(all_words) - 1

        if force_cut_at is not None:
            # Cắt tại force_cut_at, giữ phần còn lại cho câu tiếp
            emit_words = current_words[:force_cut_at + 1]
            remaining_words = current_words[force_cut_at + 1:]
            emit_end_idx = current_start_idx + force_cut_at + 1
            _emit_sentence(emit_words, current_start_idx, emit_end_idx)
            current_words = remaining_words
            current_start_idx = emit_end_idx
        elif should_cut:
            _emit_sentence(current_words, current_start_idx, i + 1)
            current_words = []
            current_start_idx = i + 1

    # Phần còn lại
    if current_words:
        _emit_sentence(current_words, current_start_idx, len(all_words))

    return sentences


def _compute_adjacent_similarities(sentences: list[dict]) -> list[float]:
    model = _get_emb_model()
    texts = [s["text"] for s in sentences]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)
    similarities = []
    for i in range(len(embeddings) - 1):
        a, b = embeddings[i], embeddings[i + 1]
        cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
        similarities.append(float(cos))
    return similarities


def _find_breakpoints(
    similarities: list[float],
    percentile: int = 25,
    min_similarity: float = 0.3,
) -> list[int]:
    if not similarities:
        return []
    threshold = max(
        float(np.percentile(similarities, percentile)),
        min_similarity,
    )
    breakpoints = [i for i, sim in enumerate(similarities) if sim < threshold]
    return breakpoints


# ─────────────────────────────────────────────────────────────────────────────
# FIX #2: Group → Chunks với enforce min/max nghiêm ngặt
#
# Vấn đề gốc:
#   - Merge chỉ merge vào group trước → group đầu tiên nếu nhỏ vẫn sống sót
#   - Split dùng object identity (gs is s) để match → fragile, có thể fail
#   - Chunk < min_words vẫn được emit (filter chỉ > 5 words)
#
# Fix:
#   - Multi-pass merge: forward pass + backward pass
#   - Final enforcement: mọi chunk < min_words bị merge, mọi chunk > max_words bị split
#   - Split dùng index tracking thay vì object identity
# ─────────────────────────────────────────────────────────────────────────────

def _group_sentences_to_chunks(
    sentences: list[dict],
    breakpoints: list[int],
    chapter_id: str,
    video_sub: str,
    source_file: str,
    topics: list[str],
    chapter_title: str,
    min_chunk_words: int,
    max_chunk_words: int,
    similarities: list[float],
) -> list[dict]:
    """
    Nhóm sentences thành chunks dựa trên breakpoints.
    Sau đó post-process: merge chunk nhỏ, split chunk lớn — ENFORCE nghiêm ngặt.
    """
    # ─── Bước 1: Nhóm câu giữa các breakpoints ────────────────────
    # Track global sentence indices cho mỗi group
    bp_set = set(breakpoints)
    groups: list[list[int]] = []  # list of [global_sentence_indices]
    current_indices: list[int] = []

    for i in range(len(sentences)):
        current_indices.append(i)
        if i in bp_set or i == len(sentences) - 1:
            if current_indices:
                groups.append(current_indices[:])
                current_indices = []

    if current_indices:
        groups.append(current_indices[:])

    def _group_wc(indices: list[int]) -> int:
        return sum(len(sentences[i]["text"].split()) for i in indices)

    # ─── Bước 2: Multi-pass merge (nhỏ → merge vào neighbor gần nhất) ──
    changed = True
    max_iterations = 10
    iteration = 0
    while changed and iteration < max_iterations:
        changed = False
        iteration += 1
        new_groups = []
        for g in groups:
            wc = _group_wc(g)
            if wc < min_chunk_words and new_groups:
                # Merge vào group trước
                new_groups[-1].extend(g)
                changed = True
            elif wc < min_chunk_words and not new_groups:
                # Đầu tiên, giữ tạm — sẽ merge forward ở pass sau
                new_groups.append(g)
            else:
                new_groups.append(g)
        groups = new_groups

        # Backward pass: nếu group đầu vẫn nhỏ → merge vào group sau
        if groups and _group_wc(groups[0]) < min_chunk_words and len(groups) > 1:
            groups[1] = groups[0] + groups[1]
            groups = groups[1:]
            changed = True

    # ─── Bước 3: Split groups quá lớn ─────────────────────────────
    final_groups: list[list[int]] = []
    for g in groups:
        wc = _group_wc(g)
        if wc <= max_chunk_words:
            final_groups.append(g)
        else:
            # Split tại điểm similarity thấp nhất bên trong group
            split_result = _split_large_group_v2(g, sentences, similarities, max_chunk_words, min_chunk_words)
            final_groups.extend(split_result)

    # ─── Bước 4: Final enforcement — không cho chunk nào vi phạm min/max ──
    # Pass cuối: merge bất kỳ chunk < min_words còn sót
    enforced = []
    for g in final_groups:
        wc = _group_wc(g)
        if wc < min_chunk_words and enforced:
            enforced[-1].extend(g)
        else:
            enforced.append(g)
    # Nếu group cuối quá nhỏ → merge vào trước
    if len(enforced) > 1 and _group_wc(enforced[-1]) < min_chunk_words:
        enforced[-2].extend(enforced[-1])
        enforced = enforced[:-1]
    final_groups = enforced

    # ─── Bước 5: Build chunk dicts ─────────────────────────────────
    video_meta = VIDEO_META_MAP.get((chapter_id, int(video_sub)), {})
    youtube_url = video_meta.get("url", "")
    slide_file = video_meta.get("slide_file", "")
    slide_start_page = video_meta.get("slide_start_page", 0)

    chunks = []
    for seq, g_indices in enumerate(final_groups, 1):
        group_sents = [sentences[i] for i in g_indices]
        text = " ".join(s["text"] for s in group_sents).strip()
        wc = len(text.split())
        if wc < 5:
            continue

        start_ts = group_sents[0]["start"]
        end_ts = group_sents[-1]["end"]

        chunk_id = f"cs116_{chapter_id}_transcript_{video_sub}_s{seq:03d}"
        chunks.append({
            "chunk_id": chunk_id,
            "course_id": "CS116",
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "topics": topics,
            "source_type": "video_transcript",
            "source_file": source_file,
            "page_number": int(video_sub),
            "section_title": "",
            "text": text,
            "timestamp_start": round(start_ts, 3),
            "timestamp_end": round(end_ts, 3),
            "youtube_url": youtube_url,
            "youtube_timestamp_start": _format_youtube_ts(start_ts),
            "youtube_timestamp_end": _format_youtube_ts(end_ts),
            "slide_file": slide_file,
            "slide_start_page": slide_start_page,
            "word_count": wc,
            "embedding_ready": True,
            "chunking_method": "semantic",
        })

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# FIX #3: Split large group — dùng index tracking, hỗ trợ single-sentence groups
# ─────────────────────────────────────────────────────────────────────────────

def _split_large_group_v2(
    g_indices: list[int],
    sentences: list[dict],
    similarities: list[float],
    max_words: int,
    min_words: int,
) -> list[list[int]]:
    """
    Split 1 group quá lớn. Dùng global sentence indices (không phải object identity).
    Nếu group chỉ có 1 sentence quá dài → cắt theo word-count tại ranh giới từ.
    """
    wc = sum(len(sentences[i]["text"].split()) for i in g_indices)

    # Base case: đã đủ nhỏ
    if wc <= max_words:
        return [g_indices]

    # Nếu chỉ có 1 sentence → cắt sentence theo word-count
    if len(g_indices) <= 1:
        return _split_single_sentence_by_words(g_indices, sentences, max_words, min_words)

    # Tìm split point: similarity thấp nhất giữa các sentence liền kề trong group
    best_split_local = None
    best_sim = float("inf")
    for local_i in range(len(g_indices) - 1):
        gi = g_indices[local_i]
        if gi < len(similarities):
            if similarities[gi] < best_sim:
                best_sim = similarities[gi]
                best_split_local = local_i + 1

    if best_split_local is None or best_split_local == 0:
        # Không tìm được → cắt ở giữa
        best_split_local = len(g_indices) // 2

    left = g_indices[:best_split_local]
    right = g_indices[best_split_local:]

    results = []
    for sub in [left, right]:
        sub_wc = sum(len(sentences[i]["text"].split()) for i in sub)
        if sub_wc > max_words:
            results.extend(_split_large_group_v2(sub, sentences, similarities, max_words, min_words))
        else:
            results.append(sub)
    return results


def _split_single_sentence_by_words(
    g_indices: list[int],
    sentences: list[dict],
    max_words: int,
    min_words: int,
) -> list[list[int]]:
    """
    Khi group chỉ có 1 sentence quá dài (>max_words), tách sentence đó
    thành nhiều pseudo-sentences bằng cách cắt theo word-count.

    Chèn pseudo-sentences vào sentences list, trả về new indices.
    """
    if not g_indices:
        return [g_indices]

    idx = g_indices[0]
    sent = sentences[idx]
    words = sent["text"].split()

    if len(words) <= max_words:
        return [g_indices]

    # Cắt thành chunks ~target_words, tối thiểu min_words
    target = (max_words + min_words) // 2  # nhắm giữa min và max
    result_indices = []
    pos = 0

    while pos < len(words):
        end = min(pos + target, len(words))
        # Nếu phần còn lại < min_words → gộp hết vào chunk cuối
        if len(words) - end < min_words and end < len(words):
            end = len(words)
        chunk_text = " ".join(words[pos:end])

        # Tính timestamp xấp xỉ (chia đều)
        total_words = len(words)
        duration = sent["end"] - sent["start"]
        approx_start = sent["start"] + (pos / total_words) * duration
        approx_end = sent["start"] + (end / total_words) * duration

        # Tạo pseudo-sentence mới, thêm vào cuối sentences list
        new_idx = len(sentences)
        sentences.append({
            "text": chunk_text,
            "start": approx_start,
            "end": approx_end,
            "word_start_idx": sent.get("word_start_idx", 0) + pos,
            "word_end_idx": sent.get("word_start_idx", 0) + end,
        })
        result_indices.append([new_idx])
        pos = end

    return result_indices


def _chunk_segments_semantic(
    all_words: list[dict],
    chapter_id: str,
    video_sub: str,
    source_file: str,
    topics: list[str],
    chapter_title: str,
    similarity_percentile: int = 25,
    min_similarity: float = 0.3,
    min_chunk_words: int = 80,
    max_chunk_words: int = 400,
) -> list[dict]:
    """
    Semantic chunking v2: cắt transcript dựa trên embedding similarity.

    Fixes so với v1:
      - Sentence splitter dùng word-count ceiling (MAX_SENTENCE_WORDS=40)
      - Multi-pass merge enforce min_chunk_words nghiêm ngặt
      - Split hỗ trợ cắt word-level cho mega-sentences
    """
    # Bước 1: words → sentences (với word-count ceiling)
    sentences = _build_sentences_from_words(all_words)

    if len(sentences) <= 1:
        return _chunk_segments(
            all_words, chapter_id, video_sub, source_file, topics, chapter_title
        )

    # Bước 2-3: embed + tính similarity
    similarities = _compute_adjacent_similarities(sentences)

    if not similarities:
        return _chunk_segments(
            all_words, chapter_id, video_sub, source_file, topics, chapter_title
        )

    # Bước 4: tìm breakpoints
    breakpoints = _find_breakpoints(similarities, similarity_percentile, min_similarity)

    # Bước 5-6: nhóm + post-process → chunks (v2 logic)
    chunks = _group_sentences_to_chunks(
        sentences=sentences,
        breakpoints=breakpoints,
        chapter_id=chapter_id,
        video_sub=video_sub,
        source_file=source_file,
        topics=topics,
        chapter_title=chapter_title,
        min_chunk_words=min_chunk_words,
        max_chunk_words=max_chunk_words,
        similarities=similarities,
    )

    # Log stats
    if chunks:
        wcs = [c["word_count"] for c in chunks]
        print(
            f"     [semantic-v2] {len(sentences)} sentences → {len(chunks)} chunks | "
            f"avg={sum(wcs)/len(wcs):.0f}w | "
            f"range=[{min(wcs)},{max(wcs)}]w | "
            f"breakpoints={len(breakpoints)}"
        )
    else:
        print(f"     [semantic-v2] {len(sentences)} sentences → 0 chunks (fallback to legacy)")
        return _chunk_segments(
            all_words, chapter_id, video_sub, source_file, topics, chapter_title
        )

    return chunks


def _format_youtube_ts(seconds: float) -> str:
    seconds = max(0, round(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


# ─── Parse Whisper JSON ────────────────────────────────────────────────────────

def _parse_whisper_json(json_path: str) -> tuple[list[dict], str, str]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    all_words: list[dict] = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            word = w.get("word", "").strip()
            if word:
                all_words.append({
                    "word": word,
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                })
        if not seg.get("words") and seg.get("text"):
            txt = seg["text"]
            dur = seg.get("end", 0) - seg.get("start", 0)
            s = seg.get("start", 0)
            for w_txt in txt.split():
                all_words.append({
                    "word": w_txt,
                    "start": s,
                    "end": s + dur / max(1, len(txt.split())),
                })
    video_file = data.get("video_file", Path(json_path).stem + ".mp4")
    return all_words, video_file, Path(json_path).name


# ─── Chapter metadata ─────────────────────────────────────────────────────────

SLIDE_NAME_MAP: dict[str, tuple[str, str, str]] = {
    "ch02": ("CS116-Bai02-Popular Libs.pdf",             "ch02", "Popular Libraries"),
    "ch03": ("CS116-Bai03-Pipeline & EDA.pdf",           "ch03", "Pipeline & EDA"),
    "ch04": ("CS116-Bai04-Data preprocessing.pdf",        "ch04", "Tiền xử lý dữ liệu"),
    "ch05": ("CS116-Bai05-Eval model.pdf",               "ch05", "Đánh giá mô hình"),
    "ch06": ("CS116-Bai06-Unsupervised learning.pdf",    "ch06", "Unsupervised Learning"),
    "ch07a": ("CS116-Bai07a-Supervised learning-Regression.pdf", "ch07a", "Supervised Learning - Regression"),
    "ch07b": ("CS116-Bai07b-Supervised learning-Classification.pdf", "ch07b", "Supervised Learning - Classification"),
    "ch08": ("CS116-Bai08-Deep learning với CNN.pdf",    "ch08", "Deep Learning với CNN"),
    "ch09": ("CS116-Bai09-Parameter tuning.pdf",         "ch09", "Parameter Tuning"),
    "ch10": ("CS116-Bai10-Ensemble model.pdf",            "ch10", "Ensemble Models"),
    "ch11": ("CS116-Bai11-Model Deployment.pdf",         "ch11", "Model Deployment"),
}

SLIDE_TOPICS: dict[str, list[str]] = {
    "ch04": ["Missing Data", "Outlier Detection", "Feature Extraction",
             "Feature Transformation", "Feature Selection"],
    "ch02": ["NumPy", "Pandas", "Matplotlib", "Scikit-learn"],
    "ch03": ["Pipeline", "Exploratory Data Analysis"],
    "ch05": ["Classification Metrics", "Regression Metrics", "Cross-validation"],
    "ch06": ["Clustering", "Dimensionality Reduction"],
    "ch07a": ["Linear Regression", "Regularization"],
    "ch07b": ["Logistic Regression", "Decision Trees", "SVM"],
    "ch08": ["Neural Networks", "CNN"],
    "ch09": ["Grid Search", "Random Search", "Bayesian Optimization"],
    "ch10": ["Bagging", "Boosting", "Random Forest"],
    "ch11": ["Model Serving", "API", "Monitoring"],
}


def _get_chapter_id(video_sub: str) -> tuple[str, int]:
    try:
        if "." in video_sub:
            parts = video_sub.split(".")
            ch = int(parts[0])
            sub = int(parts[1])
        else:
            ch = int(video_sub)
            sub = 1
        return f"ch{ch:02d}", sub
    except (ValueError, IndexError):
        return "ch00", 1


# ═══════════════════════════════════════════════════════════════════════════════
# Config + Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

SEMANTIC_CHUNK_CONFIG = {
    "similarity_percentile": int(os.getenv("SEMANTIC_PERCENTILE", "25")),
    "min_similarity": float(os.getenv("SEMANTIC_MIN_SIM", "0.3")),
    "min_chunk_words": int(os.getenv("SEMANTIC_MIN_WORDS", "80")),
    "max_chunk_words": int(os.getenv("SEMANTIC_MAX_WORDS", "400")),
}


def run_chunking() -> list[dict]:
    """
    Entry point: chunk all JSON transcripts.

    Toggle:
      CHUNKING_MODE=semantic  → semantic chunking v2
      CHUNKING_MODE=legacy    → word-count chunking (mặc định)
    """
    _build_video_url_map()
    chunking_mode = os.getenv("CHUNKING_MODE", "legacy").lower()
    print(f"📋 Chunking mode: {chunking_mode}")

    transcript_dir = Config.INPUT_DIR / "transcribe_data"
    out_file = Config.PROCESSED_DIR / "transcript_chunks_with_timestamps.jsonl"
    Config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    all_chunks: list[dict] = []
    json_files = sorted(transcript_dir.glob("*.json"))
    print(f"📂 Found {len(json_files)} JSON transcript files")

    for json_path in json_files:
        fname = json_path.name
        video_sub_raw = fname.replace(".json", "")
        chapter_id, sub_idx = _get_chapter_id(video_sub_raw)
        chapter_title = SLIDE_NAME_MAP.get(chapter_id, (None, chapter_id, "Unknown"))[2]
        topics = SLIDE_TOPICS.get(chapter_id, [])

        print(f"  📝 {fname} → chapter={chapter_id}, sub={sub_idx}")
        try:
            all_words, video_file, source_file = _parse_whisper_json(str(json_path))
        except Exception as e:
            print(f"  ❌ Error parsing {fname}: {e}")
            traceback.print_exc()
            continue

        if not all_words:
            print(f"  ⚠️  No words found in {fname}")
            continue

        if chunking_mode == "semantic":
            chunks = _chunk_segments_semantic(
                all_words=all_words,
                chapter_id=chapter_id,
                video_sub=str(sub_idx),
                source_file=source_file,
                topics=topics,
                chapter_title=chapter_title,
                **SEMANTIC_CHUNK_CONFIG,
            )
        else:
            chunks = _chunk_segments(
                all_words=all_words,
                chapter_id=chapter_id,
                video_sub=str(sub_idx),
                source_file=source_file,
                topics=topics,
                chapter_title=chapter_title,
            )

        if chunks:
            print(f"     → {len(chunks)} chunks | first: {chunks[0]['timestamp_start']:.1f}s | last: {chunks[-1]['timestamp_end']:.1f}s")
        else:
            print(f"     → 0 chunks (skipped)")
            continue

        for c in chunks:
            c["video_sub"] = str(sub_idx)
            c["video_file"] = video_file
        all_chunks.extend(chunks)

    print(f"\n📊 Total transcript chunks: {len(all_chunks)}")
    save_jsonl(all_chunks, out_file)
    print(f"✅ Saved: {out_file} ({out_file.stat().st_size / 1024:.0f} KB)")

    if all_chunks:
        wc = [c["word_count"] for c in all_chunks]
        print(f"   avg words/chunk: {sum(wc)/len(wc):.0f} | min: {min(wc)} | max: {max(wc)}")
        print(f"   chunks < 80w: {sum(1 for w in wc if w < 80)} | chunks > 400w: {sum(1 for w in wc if w > 400)}")
        if chunking_mode == "semantic":
            semantic_count = sum(1 for c in all_chunks if c.get("chunking_method") == "semantic")
            print(f"   semantic: {semantic_count} | legacy fallback: {len(all_chunks) - semantic_count}")

    return all_chunks


if __name__ == "__main__":
    run_chunking()