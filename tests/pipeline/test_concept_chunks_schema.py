"""Schema test cho concept_chunks.jsonl (nguồn chính cho embedding/RAG)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = ("chunk_id", "chapter_id", "source_type", "text")
FILE = "concept_chunks.jsonl"


def _find(filename):
    for base in (ROOT / "data" / "processed", ROOT / "src" / "mcqgen" / "data" / "processed"):
        p = base / filename
        if p.exists():
            return p
    return None


@pytest.fixture(scope="module")
def records():
    path = _find(FILE)
    if path is None:
        pytest.skip(f"Chưa có {FILE} (chạy `dvc repro` trước)")
    recs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def test_not_empty(records):
    assert len(records) > 0


def test_required_fields_present_and_text_nonempty(records):
    for r in records:
        for fld in REQUIRED_FIELDS:
            assert fld in r, f"thiếu field {fld}"
        assert r["text"].strip(), "text rỗng"


def test_no_duplicate_chunk_id(records):
    ids = [r["chunk_id"] for r in records]
    assert len(ids) == len(set(ids)), "có chunk_id trùng"


def test_source_types_known(records):
    allowed = {"slide_pdf", "video_transcript"}
    seen = {r.get("source_type") for r in records}
    assert seen.issubset(allowed), f"source_type lạ: {seen - allowed}"
