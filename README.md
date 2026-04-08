# Story2Audio 🎧

Story2Audio là một ứng dụng API và Web Interface hiệu năng cao được viết bằng **FastAPI**, giúp chuyển đổi văn bản và truyện thành âm thanh (Text-to-Speech) chuyên nghiệp. Điểm nổi bật nhất của Story2Audio là khả năng **phát trực tiếp (Live Streaming) ngay khi âm thanh đang được tạo**, giúp người dùng có thể nghe ngay lập tức mà không cần chờ toàn bộ quá trình chuyển đổi hoàn tất.

## ✨ Tính năng nổi bật

- **Live Streaming với MediaSource:** Không còn độ trễ chờ đợi! Backend stream audio chunks dưới dạng byte và Frontend ghép nối phát ngay theo thời gian thực.
- **Hỗ trợ đa ngôn ngữ (Multi-language & i18n):** Hỗ trợ 7 ngôn ngữ: Tiếng Việt, Tiếng Anh, Tiếng Nhật, Tiếng Trung, Tiếng Hàn, Tiếng Pháp, Tiếng Đức. Giao diện thay đổi tức thì, hệ thống cung cấp các giọng đọc bản địa chất lượng cao tương ứng.
- **Hệ thống Cache thông minh:** Âm thanh được tạo ra sẽ được lưu lại (theo mã hash của văn bản + ngôn ngữ + engine + giọng đọc). Nếu người dùng yêu cầu lại cùng văn bản đó, ứng dụng sẽ phát ngay từ cache, tiết kiệm tối đa CPU và băng thông.
- **Tối ưu hóa In-memory & i18n:** Ngôn ngữ mặc định (Tiếng Việt) và danh sách giọng đọc được Server inject thẳng vào HTML lúc tải trang giúp **Zero-fetch** (không cần request API lúc tải trang). Dữ liệu ngôn ngữ khác sẽ được cache trên RAM trình duyệt để đảm bảo việc chuyển tab/ngôn ngữ mượt mà nhất.
- **Bảo mật và Quản lý lỗi:** Tự động loại bỏ cache bị lỗi, có cơ chế chặn Race Condition (không xóa nhầm file đang tạo). API Stream báo lỗi 503 để Client tự retry (Retry-After). Debug API được bảo vệ bởi biến môi trường.
- **Tùy chọn Engine mạnh mẽ:**
  - **Edge-TTS:** Engine chính với giọng đọc tự nhiên chuẩn Neural, đa dạng giọng điệu cho từng quốc gia.
  - **Google TTS (gTTS):** Hoạt động ổn định như phương án dự phòng.

## 📁 Cấu trúc dự án

```text
story2audio/
├─ audio_cache/              # (Tự sinh) Thư mục lưu trữ file audio .mp3 và file metadata .json
├─ static/                   # File tĩnh (ảnh, icon, locales...)
│  ├─ locales/               # Các file i18n JSON (en.json, vi.json, ja.json...)
│  └─ favicon.svg
├─ templates/
│  └─ index.html             # Giao diện người dùng duy nhất (Single Page)
├─ main.py                   # Chứa toàn bộ logic FastAPI, API routing và TTS Generator
├─ pyproject.toml / uv.lock  # Quản lý dependency dự án
├─ Dockerfile                # File build Docker container
├─ docker-compose.yml        # Triển khai dễ dàng bằng Compose
└─ .env.example              # File biến môi trường mẫu
```

## 🛠 Cài đặt và Chạy ứng dụng

Bạn có thể chạy dự án trực tiếp (Local) hoặc thông qua Docker.

### Cách 1: Sử dụng `uv` (Khuyến nghị, siêu tốc)

1. Cài đặt các gói phụ thuộc:
   ```bash
   uv sync
   ```
2. Chạy server (hỗ trợ tự động tải lại khi sửa code):
   ```bash
   uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Cách 2: Sử dụng `pip` truyền thống

1. Khởi tạo môi trường ảo (Virtual Env) và kích hoạt:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Trên Linux/macOS
   # hoặc: .venv\Scripts\activate trên Windows
   ```
2. Cài đặt thư viện:
   ```bash
   pip install -U pip
   pip install fastapi edge-tts gtts python-dotenv "uvicorn[standard]"
   ```
3. Chạy server:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

> Truy cập giao diện ứng dụng tại: **http://localhost:8000**

---

## 🐳 Triển khai với Docker & Coolify

Ứng dụng Story2Audio được tối ưu sẵn cho môi trường Container (Docker/Coolify).

### Chạy bằng Docker Compose (Dễ nhất)
Chỉ cần chạy lệnh sau tại thư mục gốc của dự án:
```bash
docker compose up -d --build
```

### Triển khai trên Coolify
1. Thêm dự án từ GitHub/GitLab vào Coolify.
2. Chọn loại ứng dụng là **Docker Compose**.
3. Cấu hình biến môi trường tại thẻ **Environment Variables** (nếu cần thiết).
4. Nhấn **Deploy**. Hệ thống sẽ tự động map port và mount thư mục `audio_cache` thông qua volume.

---

## ⚙️ Cấu hình Biến môi trường (.env)

Tạo một file `.env` (dựa trên `.env.example`) tại thư mục gốc để tuỳ biến cấu hình ứng dụng:

```env
# Cấu hình Proxy nếu máy chủ bị chặn truy cập Edge TTS
PROXY=http://user:password@proxy-host:8080

# Cấu hình cổng và host cho Uvicorn (Mặc định 0.0.0.0 và 8000)
HOST=0.0.0.0
PORT=8000

# Bật Debug mode (cho phép xem API chia nhỏ Chunk văn bản) - Không dùng trên Production
ENABLE_DEBUG_TTS=false
```

---

## 📜 Luồng hoạt động (Workflow) của ứng dụng

1. **Client gửi văn bản:** Người dùng nhập truyện và chọn tuỳ chọn trên Web (Ngôn ngữ, Giọng, Engine, Tốc độ) -> Bấm Chuyển đổi.
2. **Backend tiếp nhận (`/tts/start`):**
   - Phân tích và chia nhỏ văn bản (Chunking) dựa theo quy tắc ngắt câu của từng ngôn ngữ.
   - Hash nội dung để sinh ra `cache_id` duy nhất.
   - Nếu audio đã tồn tại (cached), trả về URL file cache ngay lập tức.
   - Nếu chưa có, đưa vào hàng đợi chạy ngầm (Background Task) và trả về trạng thái `started` + `cache_id`.
3. **Quá trình tạo Audio (`generate_chunks`):**
   - Xử lý từng đoạn văn bản, gọi API Edge-TTS hoặc gTTS.
   - Ghi nối tiếp vào file `.mp3` trên server để có thể stream lập tức.
   - Trừ chunk đầu tiên, các chunk tiếp theo bị cắt header `ID3v2` để loại bỏ nhiễu khi ghép nối.
4. **Client nhận Audio (`/tts/stream/{cache_id}`):**
   - Trình duyệt liên tục yêu cầu file thông qua Live Stream chunk.
   - Sử dụng `MediaSource API` trên Javascript để ghép nối và phát trực tiếp đoạn MP3 vừa được tải về (tải đến đâu, phát đến đó).
5. **Hoàn thành:** Cập nhật Metadata cache. Người dùng có thể nhấn nút "Tải MP3" để lưu file.

---
**Giấy phép (License):** MIT
