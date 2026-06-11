# Báo cáo Evaluation (MCQGen)

- Thời điểm sinh báo cáo: `2026-06-11 15:50:39`
- Nguồn câu accepted: **mcqs.jsonl** (`/mmlab_students/storageStudents/nguyenvd/thanhhn/cs317-mcqgen-llmops/output/exam_01/mcqs.jsonl`)
- Script: `scripts/eval_report.py`

## 1. Cấu hình run

| Thông tin | Giá trị |
| --- | --- |
| Task ID | `2476191c-b231-467f-86ea-d656a0767845` |
| Tên đề | exam_01 |
| Trạng thái | success |
| Người tạo | giaovien |
| Thời điểm tạo | 2026-05-19 07:36:33.253321 |
| Thời điểm hoàn tất | 2026-05-19 07:43:13.657155 |
| Model serving | Qwen2.5-7B-Instruct (vLLM, served-name `mcqgen`) |
| Prompt version (trên câu accepted) | v1.0×8 |
| RAG strategy ghi nhận | sw_hyde+rerank, sw_naive+rerank |
| Chapters xuất hiện | ch08 |

## 2. Kết quả tổng quan

| Metric | Giá trị |
| --- | --- |
| Requested questions | 18 |
| Accepted questions | 8 |
| Rejected / failed questions | 10 |
| **Acceptance rate** | **44.4%** |
| Quality score trung bình (accepted) | (không có điểm trong dữ liệu) |
| Duplicate trong accepted (theo stem) | 0 câu (0.0%) |
| PDF export | kiểm tra thủ công: `GET /export/pdf/2476191c-b231-467f-86ea-d656a0767845` |

> Khớp Langfuse scores: `accepted_questions`, `failed_questions`, `acceptance_rate`, `reject_stage.<stage>` (mục 3).

## 3. Rejection theo stage và reason

Không có bản ghi failure cho run này (cột `failure_info_json` rỗng). Các câu không đạt ở pipeline này không được lưu lại chi tiết stage/reason.

## 4. Phân tích nguyên nhân reject

| Câu hỏi phân tích | Số câu |
| --- | --- |
| Reject do JSON format? | 0 |
| Reject do distractor? | 0 |
| Reject do relevance / RAG context? | 0 |
| Reject do opening style? | 0 |
| Reject do trùng câu (dedup)? | 0 |

## 5. Phân bố câu hỏi được chấp nhận

- Theo độ khó: {'G2': 8}
- Theo chương: {'ch08': 8}
- Theo loại câu: {'single_correct': 8}
- Theo RAG strategy: {'sw_hyde+rerank': 5, 'sw_naive+rerank': 3}
- Theo prompt version: {'v1.0': 8}

## 6. Nhận xét & đề xuất cải thiện

- Run này không lưu chi tiết reject. Để phân tích reject đầy đủ, generate đề mới với pipeline hiện tại rồi chạy lại script (cột `failure_info_json` sẽ có dữ liệu).
- Không phát hiện câu trùng trong 8 câu accepted → cơ chế dedup theo lịch sử hoạt động tốt.
