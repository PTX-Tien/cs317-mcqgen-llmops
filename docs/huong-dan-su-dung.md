# Hướng dẫn sử dụng MCQGen

Tài liệu này tách riêng phần hướng dẫn thao tác để README chính gọn hơn.

## 1. Tài khoản admin mặc định

Hệ thống khởi tạo sẵn một tài khoản admin duy nhất. Tài khoản người dùng thông thường (giảng viên, sinh viên) được tạo qua giao diện đăng ký.

| Role  | Username | Password     | Quyền                                 |
| ----- | -------- | ------------ | ------------------------------------- |
| Admin | `admin`  | (xem `.env`) | Quản lý hệ thống, xem toàn bộ lịch sử |

> Lưu ý: nếu triển khai thực tế, nên đổi mật khẩu admin mặc định.

## 2. Đăng ký tài khoản

1. Truy cập `http://SERVER_IP:8081`
2. Tại trang đăng nhập, chọn **Đăng ký**
3. Điền họ tên, tên đăng nhập, mật khẩu
4. Chọn **Tạo tài khoản**
5. Đăng nhập bằng tài khoản vừa tạo

## 3. Sinh đề thi

1. Đăng nhập bằng tài khoản người dùng
2. Chọn **Sinh câu hỏi** trên thanh điều hướng
3. Nhập tên đề thi
4. Thêm chương/topic, độ khó và số câu
5. Chọn **Sinh câu hỏi**
6. Theo dõi tiến trình qua UI và Langfuse
7. Tải JSON, PDF đề thi hoặc PDF đáp án

## 4. Làm bài

1. Mở đề thi từ lịch sử
2. Chọn **Bắt đầu làm đề**
3. Trả lời từng câu hỏi
4. Nộp bài để xem kết quả

## 5. Admin

1. Đăng nhập bằng tài khoản admin
2. Mở tab **Admin**
3. Xem tổng quan hệ thống, lịch sử đề thi, và trạng thái người dùng

