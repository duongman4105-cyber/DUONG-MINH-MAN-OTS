# G3.10 — Hệ thống truy vết phương tiện qua nhiều camera 

> Hệ thống hỗ trợ phát hiện, tìm kiếm và liên kết các lần xuất hiện của phương tiện trong mạng lưới camera bằng trí tuệ nhân tạo.

## Tổng quan

Trong môi trường có nhiều camera, thông tin về một phương tiện thường được ghi nhận rời rạc theo từng vị trí và thời điểm. Việc tra cứu thủ công mất nhiều thời gian, đặc biệt khi hình ảnh không rõ hoặc biển số không thể nhận diện đầy đủ.

Hệ thống hướng đến việc tổng hợp các dấu hiệu nhận dạng và thông tin thời gian để hỗ trợ tìm kiếm, đối chiếu và liên kết các sự kiện phương tiện trên toàn mạng lưới camera.

## Vai trò của Trí tuệ nhân tạo

AI được tích hợp vào quy trình phân tích hình ảnh và hỗ trợ đối chiếu sự kiện. Tùy theo dữ liệu và mô hình được lựa chọn, hệ thống có thể:

- Phát hiện phương tiện trong hình ảnh hoặc video từ camera.
- Nhận diện và trích xuất biển số để phục vụ tìm kiếm.
- Phân loại phương tiện và ước lượng màu sắc.
- Tạo thông tin đặc trưng để hỗ trợ so khớp các lần xuất hiện giữa nhiều camera.
- Kết hợp kết quả AI với thời gian và vị trí camera để xây dựng chuỗi sự kiện truy vết.

Kết quả AI có thể chưa chính xác trong mọi điều kiện, chẳng hạn khi hình ảnh mờ, thiếu sáng hoặc biển số bị che khuất. Vì vậy, hệ thống cần lưu thông tin sự kiện rõ ràng và hiển thị kết quả theo hướng hỗ trợ người dùng kiểm tra, thay vì coi mọi kết quả nhận diện là khẳng định tuyệt đối.

## Mục tiêu

- Phát hiện phương tiện từ hình ảnh hoặc video camera.
- Trích xuất biển số, loại xe, màu sắc và các đặc trưng liên quan.
- Ghi nhận sự kiện cùng camera, vị trí và thời điểm xuất hiện.
- Tìm kiếm theo biển số, thuộc tính phương tiện và khoảng thời gian.
- Liên kết các sự kiện có khả năng thuộc cùng một phương tiện.
- Hiển thị các lần xuất hiện theo trình tự thời gian để hỗ trợ tra cứu.

## Quy trình xử lý

```text
Camera
  ↓
Phát hiện phương tiện
  ↓
Nhận diện biển số và đặc trưng
  ↓
Lưu sự kiện (phương tiện, camera, thời gian)
  ↓
Đối chiếu và liên kết sự kiện
  ↓
Tìm kiếm, xem kết quả và truy vết
```

## Chức năng chính

### Phân tích dữ liệu bằng AI

- Phát hiện phương tiện trong ảnh hoặc video.
- Nhận diện và trích xuất biển số khi chất lượng hình ảnh cho phép.
- Phân loại phương tiện và ước lượng màu sắc.
- Tạo các đặc trưng phục vụ việc so khớp giữa nhiều camera.

### Quản lý và truy vấn sự kiện

- Tiếp nhận sự kiện từ nhiều camera.
- Lưu thông tin phương tiện, camera và thời điểm ghi nhận.
- Tìm kiếm theo biển số, màu sắc, loại xe và khoảng thời gian.
- Sắp xếp, liên kết và hiển thị chuỗi sự kiện theo thời gian.

## Kiến trúc dự kiến

Hệ thống được tổ chức theo các nhóm thành phần sau:

1. **Nguồn dữ liệu:** hình ảnh hoặc video từ các camera.
2. **Tầng AI:** phát hiện phương tiện, nhận diện biển số và trích xuất đặc trưng.
3. **Tầng xử lý nghiệp vụ:** chuẩn hóa, đối chiếu và liên kết các sự kiện.
4. **Cơ sở dữ liệu:** lưu sự kiện, thông tin camera và kết quả phân tích.
5. **Giao diện tra cứu:** tìm kiếm, xem chi tiết và theo dõi hành trình.

> Công nghệ và cấu trúc thư mục sẽ được cập nhật khi các thành phần của sản phẩm được triển khai.

## Trạng thái dự án

Dự án đang trong giai đoạn xây dựng và hoàn thiện. Các tính năng, hướng dẫn cài đặt và tài liệu kỹ thuật sẽ được bổ sung cùng với tiến độ phát triển.

## Hướng dẫn phát triển

Hiện tại repository mới tập trung vào việc mô tả phạm vi và yêu cầu của sản phẩm. Khi mã nguồn ứng dụng được bổ sung, phần này sẽ bao gồm:

- Yêu cầu môi trường và phiên bản runtime.
- Cách cài đặt dependencies.
- Cách cấu hình biến môi trường và cơ sở dữ liệu.
- Lệnh chạy ứng dụng ở môi trường phát triển.
- Lệnh kiểm thử và đóng gói sản phẩm.

## Phạm vi và giới hạn

Kết quả nhận diện và liên kết chỉ có tính chất hỗ trợ tra cứu. Độ chính xác phụ thuộc vào chất lượng hình ảnh, điều kiện ánh sáng, góc quay, độ rõ của biển số, dữ liệu đầu vào và cấu hình mô hình.

Việc triển khai thực tế cần:

- Có quy trình kiểm tra và xác minh kết quả bởi người có thẩm quyền.
- Bảo vệ dữ liệu hình ảnh, biển số và thông tin liên quan.
- Tuân thủ các quy định hiện hành về quyền riêng tư và quản lý dữ liệu.
- Kiểm soát quyền truy cập, thời hạn lưu trữ và việc sử dụng dữ liệu.

## Thông tin dự án

| Hạng mục | Nội dung |
| --- | --- |
| Mã đề tài | G3.10 |
| Tên đề tài | Xây dựng hệ thống truy vết phương tiện qua nhiều camera |
| Sản phẩm | Mô hình truy vết, cơ sở dữ liệu sự kiện và giao diện tìm kiếm |

## Thành viên nhóm

| STT | Họ và tên | MSSV |
| --- | --- | --- |
| 1 | Dương Minh Mẫn | 079205005433 |
| 2 | Triệu Thị Bảo Trâm | 082305000715 |
| 3 | Nguyễn Tấn Phát | 079205027571 |
| 4 | Nguyễn Phúc An | 079205014935 |
| 5 | Nguyễn Hoàng Khiêm | 080205014003 |