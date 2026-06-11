# Báo cáo Data Validation

- Thời điểm chạy: `2026-06-11 21:46:46`
- Input dir: `input`
- Processed dir: `data/processed`
- Kết quả tổng: **PASS (có cảnh báo) ⚠️**
- Số ERROR: **0** | Số WARNING: **2**

Script: `scripts/validate_data_pipeline.py`. Chạy lại từ root repo bằng: `python scripts/validate_data_pipeline.py`.

## 1. Input

| Hạng mục | Giá trị |
| --- | --- |
| Transcript JSON (`input/transcribe_data/*.json`) | 79 |
| `input/videos1.txt` tồn tại | True |
| Slide PDF (`input/slide/*.pdf`) | 11 |
| Transcript JSON lỗi parse | 0 |
| Transcript JSON thiếu `segments` | 1 |

## 2. `transcript_chunks_with_timestamps.jsonl`

| Chỉ số | Giá trị |
| --- | --- |
| Số dòng (chunk) | 924 |
| Dòng lỗi JSON | 0 |
| Chunk text rỗng | 0 |
| chunk_id trùng | 0 |
| Field bắt buộc bị thiếu | không |
| Word count (min/avg/median/max) | 80 / 190.0 / 199.0 / 218 |
| Transcript chunk | 924 |
| Tỷ lệ có timestamp | 100% |
| Tỷ lệ có youtube_url | 100% |
| Phân bố source_type | {'video_transcript': 924} |

## 3. `concept_chunks.jsonl`

| Chỉ số | Giá trị |
| --- | --- |
| Số dòng (chunk) | 1220 |
| Dòng lỗi JSON | 0 |
| Chunk text rỗng | 0 |
| chunk_id trùng | 0 |
| Field bắt buộc bị thiếu | không |
| Word count (min/avg/median/max) | 5 / 153.6 / 196.0 / 264 |
| Transcript chunk | 924 |
| Tỷ lệ có timestamp | 100% |
| Tỷ lệ có youtube_url | 100% |
| Phân bố source_type | {'slide_pdf': 296, 'video_transcript': 924} |

## 4. Danh sách ERROR

- Không có ERROR.

## 5. Danh sách WARNING

- ⚠️ Transcript không có 'segments': transcription_summary.json
- ⚠️ concept_chunks.jsonl: 65 chunk < 20 từ (ngắn bất thường)
