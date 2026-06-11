# Báo cáo Data Validation

- Thời điểm chạy: `2026-06-11 13:58:20`
- Input dir: `/mmlab_students/storageStudents/nguyenvd/thanhhn/cs317-mcqgen-llmops/input`
- Processed dir: `/mmlab_students/storageStudents/nguyenvd/thanhhn/cs317-mcqgen-llmops/data/processed`
- Kết quả tổng: **PASS (có cảnh báo) ⚠️**
- Số ERROR: **0** | Số WARNING: **2**

Script: `scripts/validate_data_pipeline.py`. Chạy lại bằng: `python scripts/validate_data_pipeline.py`.

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
| Số dòng (chunk) | 780 |
| Dòng lỗi JSON | 0 |
| Chunk text rỗng | 0 |
| chunk_id trùng | 0 |
| Field bắt buộc bị thiếu | không |
| Word count (min/avg/median/max) | 28 / 206.0 / 191.5 / 400 |
| Transcript chunk | 780 |
| Tỷ lệ có timestamp | 100% |
| Tỷ lệ có youtube_url | 100% |
| Phân bố source_type | {'video_transcript': 780} |

## 2. `concept_chunks.jsonl`

| Chỉ số | Giá trị |
| --- | --- |
| Số dòng (chunk) | 993 |
| Dòng lỗi JSON | 0 |
| Chunk text rỗng | 0 |
| chunk_id trùng | 0 |
| Field bắt buộc bị thiếu | không |
| Word count (min/avg/median/max) | 11 / 173.5 / 163 / 476 |
| Transcript chunk | 780 |
| Tỷ lệ có timestamp | 100% |
| Tỷ lệ có youtube_url | 100% |
| Phân bố source_type | {'slide_pdf': 213, 'video_transcript': 780} |

## 3. Danh sách ERROR

- Không có ERROR.

## 4. Danh sách WARNING

- ⚠️ Transcript không có 'segments': transcription_summary.json
- ⚠️ concept_chunks.jsonl: 30 chunk < 20 từ (ngắn bất thường)
