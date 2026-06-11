# Báo cáo Monitoring & Evaluation với Langfuse

## 1. Trạng thái

Tài liệu này là khung báo cáo cho phần Monitoring & Evaluation của bài thực hành 1.
Phần nội dung chi tiết sẽ được hoàn thiện sau, nhưng file được tạo sẵn để nhóm có thể
liên kết từ README và nộp dần theo tiến độ.

## 2. Mục tiêu theo dõi

- Trace theo session và user.
- Quan sát input/output của từng stage trong pipeline sinh đề.
- Theo dõi latency, token usage và accepted/rejected score.
- Phân tích reject reason theo stage.
- So sánh single-user và multi-user khi hệ thống chịu tải.

## 3. Tài liệu liên quan hiện có

- [Báo cáo Optimization Strategy trực quan](optimization_summary.md)
- `monitoring/langfuse_tracing.py`

## 4. Nội dung sẽ bổ sung sau

- Chi tiết trace hierarchy.
- Cách đọc sessions và user tracking.
- Dashboard/metrics cần quan sát.
- Cách đối chiếu rejected questions với Langfuse trace.
- So sánh giữa các run của cùng một user và nhiều user đồng thời.
