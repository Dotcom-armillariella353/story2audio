# 🌟 Lịch sử Phát triển (Release Notes) - Story2Audio

Dưới đây là tài liệu tổng hợp lại toàn bộ các tính năng, cải tiến và bản vá lỗi từ lúc khởi tạo dự án cho tới nay.

---

## [v2.0.0] - Bản cập nhật Đa ngôn ngữ & Tối ưu hoá Hệ thống (Mới nhất)

Bản cập nhật lớn đánh dấu sự hỗ trợ vươn ra quốc tế, tối ưu hóa giao diện người dùng và cải tiến hiệu năng server.

### ✨ Tính năng mới (Features)
- **Hỗ trợ 7 Ngôn ngữ (i18n):** Mở rộng hỗ trợ từ tiếng Việt sang tiếng Anh (EN), Nhật (JA), Trung (ZH), Hàn (KO), Pháp (FR) và Đức (DE).
- **Hỗ trợ giọng đọc Bản địa (Native Voices):** Tích hợp danh sách các giọng đọc Neural chất lượng cao của Edge-TTS tương ứng cho từng quốc gia (ví dụ: Xiaoxiao cho tiếng Trung, Nanami cho tiếng Nhật...).
- **In-memory Locale Cache & Zero-fetch:**
  - Nhúng trực tiếp (inject) file ngôn ngữ tiếng Việt (`vi.json`) và Danh sách giọng đọc (`EDGE_VOICES`) thẳng vào HTML từ server. Trình duyệt không cần gọi API lúc tải trang đầu tiên.
  - Sử dụng In-memory cache cho các file ngôn ngữ khác, loại bỏ tình trạng tải lại file JSON (redundant fetches) khi người dùng chuyển đổi qua lại giữa các tab ngôn ngữ.
- **Biến môi trường linh hoạt:** Bổ sung cấu hình `HOST` và `PORT` cho Uvicorn, giúp dễ dàng deploy ứng dụng trên đa nền tảng.

### 🚀 Cải tiến hiệu năng & Tối ưu hóa (Enhancements)
- **Cải tiến Text Chunking:** Ngăn chặn việc chạy thuật toán phân tách đoạn (split chunks) hai lần. Chuyển kết quả tính toán (chunk_preview) trực tiếp vào Background Task.
- **Tối ưu UTF-8 HTML Injection:** Sửa lỗi `json.dumps()` mặc định mã hóa các ký tự Unicode sang ASCII (`\uXXXX`), tối ưu hóa băng thông bằng cách trả về raw UTF-8 thuần túy (`ensure_ascii=False`).
- **Nâng cấp Debug API:** Ẩn endpoint `/tts/debug/chunks` phía sau cờ môi trường `ENABLE_DEBUG_TTS`, tự động block (HTTP 404) khi chạy trên Production.
- **Nâng cấp HTTP Stream Exception:** Thay vì trả về 404 hay 425 khi audio đang chạy, API nay trả về `HTTP 503 Service Unavailable` kèm theo header `Retry-After: 5`, thông báo cho client thời điểm nên thử tải lại.

### 🐛 Sửa lỗi (Bug Fixes)
- Sửa lỗi **Mất Tiếng Việt khi chuyển Tab:** Khắc phục lỗi logic bị ghi đè biến global khiến ngôn ngữ tiếng Việt hiển thị sai sau khi người dùng đổi qua ngôn ngữ khác rồi đổi lại.
- Fix **Race Condition trong Xóa Cache:** Đảm bảo hệ thống ưu tiên đọc trạng thái trên ổ đĩa (`get_effective_status`) thay vì chỉ dùng RAM để chặn tình trạng xóa nhầm cache file đang trong quá trình tạo.
- Ngăn chặn lỗi **Stale State:** Buộc gỡ bỏ trạng thái của job khỏi bộ nhớ RAM ngay khi tiến trình xử lý Terminal (Completed/Failed) được lưu xuống ổ cứng.
- Fix **Redundant JS aria-label:** Loại bỏ vòng lặp gán `aria-label` thừa thãi trên Javascript vì chúng đã được cài đặt cứng trên DOM HTML.

---

## [v1.1.0] - Bản cập nhật Trải nghiệm Người dùng & Quản lý Download

Tập trung nâng cao trải nghiệm tải tệp và tinh chỉnh hệ thống phân tách văn bản.

### ✨ Tính năng mới (Features)
- Bổ sung nút **"Tải xuống MP3" (Download MP3)** trên giao diện người dùng.

### 🚀 Cải tiến & Sửa lỗi (Enhancements & Fixes)
- **Quản lý Nút tải xuống thông minh:** Chỉ cho phép người dùng nhìn thấy nút Tải xuống MP3 **sau khi** quá trình nối file Audio hoàn thành hoàn toàn (hoặc ngay ở chunk đầu tiên của MediaSource Stream).
- **Cải tiến thuật toán Text Normalization & Chunking:** Tinh chỉnh mạnh mẽ logic cắt câu chữ để hỗ trợ các ký tự xuống dòng đặc biệt và từ ngữ dài, giúp giọng đọc tự nhiên, liền mạch hơn.
- Cấu hình hỗ trợ chạy qua **HTTP/HTTPS Proxy** thông qua biến môi trường `PROXY` (hữu ích cho các server bị chặn port/Edge-TTS).

---

## [v1.0.0] - Phiên bản Khởi tạo (Initial Release)

Phiên bản đầu tiên của Story2Audio với kiến trúc Core FastAPI và Live Streaming.

### ✨ Tính năng cốt lõi (Core Features)
- Xây dựng thành công hệ thống **Text-to-Speech (TTS) Web App** dùng **FastAPI**.
- Tích hợp 2 Engine TTS phổ biến: **Edge-TTS** (Chính) và **Google TTS** (Phụ).
- Hỗ trợ **Phát trực tiếp theo thời gian thực (Live Streaming)** thông qua giao thức **MediaSource Extension (MSE)** của Javascript. Hệ thống sẽ cắt nhỏ văn bản, tạo audio từng khúc và stream ngay lập tức dưới dạng bytes thay vì phải chờ nguyên bài.
- Xây dựng cơ chế **Cache & Metadata Management:** Tính toán mã Hash `md5` của nội dung và lưu trữ `.mp3` kèm metadata `.json` (Tiến độ xử lý, kích thước file).
- Cấu hình **Docker** và `docker-compose.yml` để dễ dàng triển khai.

### 🐛 Sửa lỗi (Bug Fixes)
- Sửa lỗi **Premature Termination** (Dừng đột ngột) khi stream audio trên trình duyệt.
- Thay đổi method `/tts/start` sang `POST` để ngăn giới hạn độ dài của URL khi người dùng gửi tiểu thuyết/truyện quá dài.
- Nâng cấp Endpoint `/tts/stream` bằng tính năng Stability Checking giúp quá trình gửi data xuống Frontend không bị ngắt quãng nửa chừng.
