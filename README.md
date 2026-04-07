# Story2Audio

Ứng dụng **FastAPI** chuyển văn bản / truyện tiếng Việt thành audio MP3, hỗ trợ:

- **Live streaming** khi đang tạo audio (qua `MediaSource` + endpoint `/tts/stream/{cache_id}`)
- **Cache audio** theo nội dung + engine + giọng đọc để phát lại nhanh
- Hỗ trợ 2 engine TTS:
  - **Edge TTS** (mặc định, chất lượng cao)
  - **gTTS** (Google TTS, làm phương án dự phòng)
- Giao diện web đơn giản, dễ dùng
- Có thể triển khai local, Docker hoặc Coolify

---

## 1) Cấu trúc project

```text
story2audio/
├─ audio_cache/                # Cache MP3 và metadata JSON (nên mount volume khi deploy)
├─ static/
│  └─ favicon.svg
├─ templates/
│  └─ index.html
├─ .env.example
├─ .gitignore
├─ .python-version
├─ Dockerfile                 # dùng khi deploy bằng Docker / Coolify
├─ docker-compose.yml         # dùng cho local / Coolify stack
├─ main.py
├─ pyproject.toml
├─ README.md
└─ uv.lock                    # nếu dùng uv để lock dependency
```

---

## 2) Cài đặt và Chạy Local

### Cách 1: dùng `uv` (Khuyến nghị)

Cài dependency:

```bash
uv sync
```

Chạy app:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Cách 2: dùng `pip`

Tạo virtual env và cài:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# hoặc .venv\Scripts\activate trên Windows

pip install -U pip
pip install fastapi edge-tts gtts python-dotenv "uvicorn[standard]"
```

Chạy app:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Mở trình duyệt tại: `http://localhost:8000`

---

## 3) Triển khai với Docker

### Build image

```bash
docker build -t story2audio:latest .
```

### Chạy container

```bash
docker run -d \
  --name story2audio \
  -p 8000:8000 \
  -v story2audio_cache:/app/audio_cache \
  story2audio:latest
```

### Chạy bằng Docker Compose

```bash
docker compose up -d --build
```

---

## 4) Triển khai trên Coolify

1. Push source code lên Git repository.
2. Trong Coolify, tạo **Docker Compose Resource**.
3. Kết nối với repo và chọn file `docker-compose.yml`.
4. Thiết lập biến môi trường nếu cần (ví dụ `PROXY`).
5. Deploy.

---

## 5) Cấu hình Biến môi trường

Tạo file `.env` từ `.env.example`:

```env
PROXY=http://user:password@proxy-host:8080  # Nếu cần proxy để gọi API TTS
```

---

## 6) Tính năng chính

- **Streaming hỗ trợ MediaSource**: Cho phép nghe audio ngay khi backend vẫn đang generate file, giảm thời gian chờ đợi.
- **Dọn dẹp cache lỗi**: Tự động xóa các file tạm nếu quá trình generate bị ngắt quãng.
- **Hỗ trợ đa engine**: Linh hoạt chuyển đổi giữa Microsoft Edge TTS và Google TTS.
- **Tương thích Docker & Coolify**: Đã tối ưu hóa cho việc triển khai bằng container.

---

## 7) Checklist Production

- [x] `main.py` bản mới nhất.
- [x] Thư mục `audio_cache/` đã được mount volume.
- [x] Biến môi trường đã được thiết lập đúng.
- [x] Healthcheck hoạt động (endpoint `/`).
