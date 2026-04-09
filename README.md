# Story2Audio 🎧

**Miễn phí · Không giới hạn · Không cần đăng ký**

Story2Audio chuyển đổi văn bản, truyện, bài báo... thành âm thanh tự nhiên với **phụ đề trực tiếp**. Bạn có thể dán bất kỳ nội dung nào — từ một câu ngắn đến cả cuốn tiểu thuyết — và bắt đầu nghe ngay lập tức.

> 🌐 **Demo trực tiếp:** [story2audio.hoctuthien.com](https://story2audio.hoctuthien.com)

## ✨ Tại sao nên dùng Story2Audio?

- 🆓 **Hoàn toàn miễn phí** — Sử dụng công nghệ Edge TTS của Microsoft, không tốn phí, không cần API key.
- 📝 **Không giới hạn độ dài văn bản** — Dán một câu hay cả cuốn tiểu thuyết đều được. Văn bản dài sẽ được chia nhỏ tự động.
- 🎧 **Nghe ngay lập tức** — Âm thanh được phát theo thời gian thực (live streaming) ngay khi đang tạo, không cần chờ hoàn tất.
- 📜 **Phụ đề trực tiếp (Live Subtitles)** — Phụ đề hiện song song với audio, cập nhật từng câu theo thời gian thực. Hỗ trợ tải về định dạng SRT và WebVTT.
- 🌍 **Đa ngôn ngữ** — Hỗ trợ 7 ngôn ngữ với giọng đọc bản địa chất lượng cao: Tiếng Việt, Anh, Nhật, Trung, Hàn, Pháp, Đức.
- 🎙️ **Nhiều giọng đọc** — Hàng chục giọng đọc Neural tự nhiên cho mỗi ngôn ngữ (nam, nữ, trẻ em...).
- 💾 **Tải về dễ dàng** — Tải file MP3, file phụ đề SRT và WebVTT chỉ bằng một cú click.
- ⚡ **Lưu cache thông minh** — Văn bản đã chuyển đổi sẽ được lưu lại, lần sau mở lại là phát ngay không cần tạo lại.
- 🐳 **Dễ dàng tự host** — Hỗ trợ Docker, Docker Compose, triển khai trên Coolify, Railway, VPS...

## 🚀 Sử dụng

### Trực tuyến
Truy cập [story2audio.hoctuthien.com](https://story2audio.hoctuthien.com), dán văn bản, chọn ngôn ngữ và giọng đọc, rồi bấm **Chuyển thành audio**.

### Tự host (Self-host)

**Docker Compose (Khuyến nghị):**
```bash
git clone https://github.com/dvchd/story2audio.git
cd story2audio
docker compose up -d --build
```
Truy cập `http://localhost:8000` để sử dụng.

**Cài đặt thủ công:**
```bash
# Cài đặt dependency
pip install fastapi edge-tts gtts python-dotenv "uvicorn[standard]"

# Chạy server
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Tùy chỉnh

Tạo file `.env` tại thư mục gốc (xem `.env.example`) để cấu hình:

```env
PROXY=http://user:password@proxy-host:8080   # Proxy nếu cần
HOST=0.0.0.0
PORT=8000
ENABLE_DEBUG_TTS=false                          # Bật debug trên production
```

---

## 🛠 Cho nhà phát triển

### Cài đặt với `uv` (Khuyến nghị)
```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### API
Ứng dụng cung cấp REST API đầy đủ. Xem tài liệu API tự động tại `/docs` (Swagger UI) sau khi chạy server.

### Triển khai trên Coolify
1. Thêm dự án từ GitHub vào Coolify.
2. Chọn loại **Docker Compose**.
3. Cấu hình biến môi trường (nếu cần).
4. Nhấn **Deploy**.

---

## 📄 Giấy phép

MIT — Sử dụng tự do cho mục đích cá nhân và thương mại.
