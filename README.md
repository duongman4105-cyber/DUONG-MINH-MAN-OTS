# G3.10 - Hệ thống truy vết phương tiện qua nhiều camera

## Giới thiệu

Đề tài xây dựng hệ thống ứng dụng trí tuệ nhân tạo (AI) để hỗ trợ truy vết phương tiện xuất hiện tại nhiều camera trong một khu vực. AI phân tích hình ảnh từ camera để nhận diện phương tiện, hỗ trợ đọc biển số và xác định các đặc trưng như màu sắc, loại xe. Từ những thông tin này kết hợp với camera và thời gian ghi nhận, hệ thống tìm và liên kết những lần xuất hiện có khả năng thuộc cùng một phương tiện.

Kết quả truy vết được lưu thành các sự kiện có thông tin camera và thời điểm ghi nhận, giúp người dùng tra cứu hành trình phương tiện nhanh chóng và có hệ thống.

## Bài toán

Trong môi trường có nhiều camera, dữ liệu phương tiện thường được ghi nhận rời rạc theo từng vị trí và thời điểm. Việc tìm lại một phương tiện cụ thể bằng cách xem thủ công từng nguồn hình ảnh tốn thời gian, đặc biệt khi biển số không đọc được rõ ràng hoặc phương tiện xuất hiện ở nhiều camera khác nhau.

Hệ thống hướng đến việc tổng hợp các dấu hiệu nhận dạng và thông tin thời gian để hỗ trợ tìm kiếm, đối chiếu và liên kết các sự kiện phương tiện trên toàn mạng lưới camera.

## Vai trò của AI

AI được tích hợp vào quy trình phân tích hình ảnh và hỗ trợ đối chiếu sự kiện. Tùy theo dữ liệu và mô hình được lựa chọn, hệ thống có thể:

- Phát hiện phương tiện trong hình ảnh hoặc video từ camera.
- Nhận diện và trích xuất biển số để phục vụ tìm kiếm.
- Phân loại phương tiện và ước lượng màu sắc.
- Tạo thông tin đặc trưng để hỗ trợ so khớp các lần xuất hiện giữa nhiều camera.
- Kết hợp kết quả AI với thời gian và vị trí camera để xây dựng chuỗi sự kiện truy vết.

Kết quả AI có thể chưa chính xác trong mọi điều kiện, chẳng hạn khi hình ảnh mờ, thiếu sáng hoặc biển số bị che khuất. Vì vậy, hệ thống cần lưu thông tin sự kiện rõ ràng và hiển thị kết quả theo hướng hỗ trợ người dùng kiểm tra, thay vì coi mọi kết quả nhận diện là khẳng định tuyệt đối.

## Mục tiêu

- Ghi nhận sự kiện phương tiện từ các camera, gồm biển số, màu sắc, loại xe, camera và thời gian.
- Đối chiếu các sự kiện để xác định những lần xuất hiện có khả năng thuộc cùng một phương tiện.
- Lưu trữ dữ liệu sự kiện phục vụ tra cứu và truy vết.
- Cung cấp giao diện tìm kiếm theo thông tin nhận dạng và khoảng thời gian.
- Hiển thị các lần xuất hiện đã tìm được theo thứ tự thời gian và camera.

## Quy trình tổng quát

1. Camera ghi nhận hình ảnh hoặc video có phương tiện.
2. AI phân tích dữ liệu để phát hiện phương tiện và trích xuất các thông tin nhận dạng có thể sử dụng.
3. Hệ thống kết hợp kết quả phân tích với camera và thời gian, sau đó lưu thành sự kiện trong cơ sở dữ liệu.
4. Khi có truy vấn, hệ thống đối chiếu các sự kiện theo biển số, đặc trưng phương tiện và thời gian.
5. Giao diện trả về các lần xuất hiện phù hợp để người dùng xem và kiểm tra hành trình.

## Chức năng dự kiến

- Phân tích hình ảnh camera bằng AI để phát hiện và nhận diện các thuộc tính phương tiện.
- Tiếp nhận và quản lý sự kiện phương tiện từ nhiều camera.
- Tìm kiếm theo biển số hoặc các thuộc tính như màu sắc, loại xe và thời gian.
- Liên kết các sự kiện có khả năng thuộc cùng phương tiện.
- Xem thông tin từng lần xuất hiện và chuỗi sự kiện theo thời gian.
- Lưu trữ dữ liệu để hỗ trợ truy vấn và rà soát lại.

## Sản phẩm dự kiến

- **Mô hình AI và truy vết:** phân tích hình ảnh, trích xuất đặc trưng và hỗ trợ liên kết các lần xuất hiện dựa trên thông tin nhận dạng và thời gian.
- **Cơ sở dữ liệu sự kiện:** lưu thông tin phương tiện, camera và thời điểm ghi nhận.
- **Giao diện tìm kiếm:** cho phép nhập tiêu chí, xem kết quả và theo dõi các sự kiện liên quan.

## Phạm vi và lưu ý

Kết quả liên kết là cơ sở hỗ trợ tra cứu, không mặc nhiên khẳng định các sự kiện chắc chắn thuộc cùng một phương tiện. Độ chính xác phụ thuộc vào chất lượng hình ảnh, độ rõ của biển số, tính đầy đủ của dữ liệu và cách cấu hình đối chiếu. Việc triển khai thực tế cần tuân thủ các quy định hiện hành về quyền riêng tư và quản lý dữ liệu.

## Thông tin dự án

- **Mã đề tài:** G3.10
- **Tên đề tài:** Xây dựng hệ thống truy vết phương tiện qua nhiều camera
- **Sản phẩm:** Mô hình truy vết, cơ sở dữ liệu sự kiện và giao diện tìm kiếm

## Thành viên nhóm

| STT | Họ và tên | MSSV |
| --- | --- | --- |
| 1 | Dương Minh Mẫn | 079205005433 |
| 2 | Triệu Thị Bảo Trâm | 082305000715 |
| 3 | Nguyễn Tấn Phát | 079205027571 |
| 4 | Nguyễn Phúc An | 079205014935 |
| 5 | Nguyễn Hoàng Khiêm | 080205014003 |