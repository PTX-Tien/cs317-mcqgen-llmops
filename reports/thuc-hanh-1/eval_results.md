# Báo cáo Evaluation (MCQGen)

- Thời điểm sinh báo cáo: `2026-06-11 21:46:46`
- Nguồn câu accepted: **bảng question (DB)**
- Script: `scripts/eval_report.py`

## 1. Cấu hình run

| Thông tin | Giá trị |
| --- | --- |
| Task ID | `9d72c2c3-7d93-44e5-a4f3-c0428fb78586` |
| Tên đề | Đề số 3 |
| Trạng thái | success |
| Người tạo | thanh |
| Thời điểm tạo | 2026-06-07 12:29:06.083652 |
| Thời điểm hoàn tất | 2026-06-07 12:31:28.142445 |
| Model serving | Qwen2.5-7B-Instruct (vLLM, served-name `mcqgen`) |
| Prompt version (trên câu accepted) | v1.0×3 |
| RAG strategy ghi nhận | sw_hyde+rerank |
| Chapters xuất hiện | ch05, ch06 |

## 2. Kết quả tổng quan

| Metric | Giá trị |
| --- | --- |
| Requested questions | 4 |
| Accepted questions | 3 |
| Rejected / failed questions | 1 |
| **Acceptance rate** | **75.0%** |
| Quality score trung bình (accepted) | (không có điểm trong dữ liệu) |
| Duplicate trong accepted (theo stem) | 0 câu (0.0%) |
| PDF export | kiểm tra thủ công: `GET /export/pdf/9d72c2c3-7d93-44e5-a4f3-c0428fb78586` |

> Khớp Langfuse scores: `accepted_questions`, `failed_questions`, `acceptance_rate`, `reject_stage.<stage>` (mục 3).

## 3. Rejection theo stage và reason

**Theo stage** (khớp score `reject_stage.<stage>`):

| Stage | Số câu bị loại |
| --- | --- |
| `P4_option_candidates` | 1 |

**Theo reason:**

| Reason | Ý nghĩa | Số câu |
| --- | --- | --- |
| `json_parse_error` | Lỗi định dạng JSON (model trả output sai format) | 1 |

## 4. Phân tích nguyên nhân reject

| Câu hỏi phân tích | Số câu |
| --- | --- |
| Reject do JSON format? | 1 |
| Reject do distractor? | 0 |
| Reject do relevance / RAG context? | 0 |
| Reject do opening style? | 0 |
| Reject do trùng câu (dedup)? | 0 |

## 5. Phân bố câu hỏi được chấp nhận

- Theo độ khó: {'G2': 2, 'G3': 1}
- Theo chương: {'ch06': 2, 'ch05': 1}
- Theo loại câu: {'single_correct': 3}
- Theo RAG strategy: {'sw_hyde+rerank': 3}
- Theo prompt version: {'v1.0': 3}

## 6. Nhận xét & đề xuất cải thiện

- Có câu rớt do `json_parse_error`: siết format trong prompt P1/P4/P8 (yêu cầu JSON thuần, thêm ví dụ), hoặc giảm temperature cho stage sinh JSON.
- Không phát hiện câu trùng trong 3 câu accepted → cơ chế dedup theo lịch sử hoạt động tốt.
