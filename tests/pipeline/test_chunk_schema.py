"""Schema test cho transcript_chunks_with_timestamps.jsonl."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = ("chunk_id", "chapter_id", "source_type", "text")
FILE = "transcript_chunks_with_timestamps.jsonl"


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
                recs.append(json.loads(line))  # đồng thời kiểm tra JSON hợp lệ
    return recs


def test_not_empty(records):
    assert len(records) > 0


def test_required_fields(records):
    for r in records:
        for fld in REQUIRED_FIELDS:
            assert fld in r and r[fld] not in (None, ""), f"thiếu/empty field {fld}"


def test_no_duplicate_chunk_id(records):
    ids = [r["chunk_id"] for r in records]
    assert len(ids) == len(set(ids)), "có chunk_id trùng"


def test_transcript_has_timestamp_and_youtube(records):
    ts = [r for r in records if r.get("source_type") == "video_transcript"]
    assert ts, "không có transcript chunk"
    with_ts = sum(1 for r in ts if r.get("timestamp_start") not in (None, ""))
    with_yt = sum(1 for r in ts if r.get("youtube_url"))
    assert with_ts / len(ts) >= 0.95
    assert with_yt / len(ts) >= 0.5
