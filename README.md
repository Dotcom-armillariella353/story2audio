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

## 1) Cấu trúc project đề xuất

Cấu trúc hiện tại của bạn **về cơ bản là ổn**. Nên giữ theo dạng sau:

```text
story2audio/
├─ audio_cache/                # Cache MP3 và metadata JSON (nên mount volume khi deploy)
├─ static/
│  └─ favicon.svg
├─ templates/
│  └─ index.html
├─ .env
├─ .env.example
├─ .gitignore
├─ .python-version            # nếu dùng uv/pyenv/asdf
├─ Dockerfile                 # dùng khi deploy bằng Docker / Coolify
├─ docker-compose.yml         # dùng cho local / Coolify stack
├─ main.py
├─ pyproject.toml
├─ README.md
└─ uv.lock                    # nếu dùng uv để lock dependency
```

### Nên giữ
- `main.py`: entrypoint chính của FastAPI
- `templates/index.html`: giao diện web
- `static/favicon.svg`: favicon
- `audio_cache/`: thư mục cache, **nên mount persistent volume** khi chạy production
- `.env`: cấu hình môi trường
- `pyproject.toml`: quản lý dependency
- `uv.lock`: khóa phiên bản dependency nếu dùng `uv`

### Không nên commit lên git
- `__pycache__/`
- `.venv/`
- file cache thật trong `audio_cache/` (trừ khi cố ý demo)

### Khuyến nghị `.gitignore`
Nếu chưa có đầy đủ, nên thêm:

```gitignore
__pycache__/
*.pyc
.venv/
.env
audio_cache/*.mp3
audio_cache/*.json
```

> Nếu muốn giữ thư mục `audio_cache/` trong repo nhưng không giữ file bên trong, có thể thêm file rỗng `audio_cache/.gitkeep`.

---

## 2) Có cần cập nhật `pyproject.toml` không?

**Có, nên cập nhật.**

Lý do:
1. Một số dependency hiện tại trong ảnh của bạn **không còn dùng** trong code mới:
   - `aiofiles`
   - `jinja2`
   - `pydub`
2. Nên mô tả project rõ hơn (`description`, `readme`)
3. Nên thêm `build-system` để file `pyproject.toml` hoàn chỉnh hơn
4. Nếu bạn dùng `uv`, sau khi chỉnh `pyproject.toml` nên chạy lại:

```bash
uv lock
```

### Nội dung `pyproject.toml` đề xuất

```toml
[project]
name = "story2audio"
version = "0.1.0"
description = "Ứng dụng FastAPI chuyển văn bản tiếng Việt thành audio MP3 với streaming và cache"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
  "edge-tts>=7.2.8",
  "fastapi>=0.115.0",
  "gtts>=2.5.4",
  "python-dotenv>=1.1.0",
  "uvicorn[standard]>=0.34.0",
]

[build-system]
requires = ["hatchling>=1.25.0"]
build-backend = "hatchling.build"
```

### Ghi chú
- Nếu bạn **thật sự không đóng gói app như một package**, `build-system` không bắt buộc 100%, nhưng **nên có**.
- Nếu deploy Docker và cài dependency trực tiếp bằng `uv sync` hoặc `pip`, project vẫn chạy tốt.

---

## 3) Biến môi trường (`.env`)

File `.env` tối thiểu:

```env
PROXY=
```

### Ý nghĩa
- `PROXY`: proxy HTTP/HTTPS nếu môi trường mạng nội bộ cần đi qua proxy
- Nếu không dùng proxy thì để trống

### Ví dụ có proxy
```env
PROXY=http://user:password@proxy-host:8080
```

> Lưu ý: nếu dùng proxy chứa ký tự đặc biệt trong username/password, nên URL-encode trước.

---

## 4) Chạy local không dùng Docker

### Cách 1: dùng `uv`

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

### Truy cập

Mở trình duyệt tại:

```text
http://localhost:8000
```

---

## 5) Cách ứng dụng hoạt động

### Luồng xử lý chính
1. Người dùng nhập văn bản tại giao diện web
2. Frontend gọi `POST /tts/start`
3. Backend:
   - tính `cache_id`
   - kiểm tra cache hợp lệ
   - nếu chưa có cache thì bắt đầu generate theo chunk
4. Frontend polling `GET /tts/status/{cache_id}` để cập nhật tiến độ
5. Nếu trình duyệt hỗ trợ `MediaSource`, frontend phát live qua:
   - `GET /tts/stream/{cache_id}`
6. Khi file hoàn tất, frontend có thể phát từ cache ổn định qua:
   - `GET /tts/file/{cache_id}`

### Endpoint chính

#### `GET /`
Trả về giao diện web.

#### `POST /tts/start`
Khởi động quá trình tạo audio.

**Body mẫu**
```json
{
  "text": "Xin chào, đây là một câu chuyện ngắn.",
  "engine": "edge",
  "voice": "vi-VN-HoaiMyNeural"
}
```

**Lưu ý**
- Với `gtts`, trường `voice` không cần thiết
- `engine` hỗ trợ: `edge`, `gtts`

#### `GET /tts/status/{cache_id}`
Kiểm tra trạng thái tạo audio.

Ví dụ response:

```json
{
  "status": "processing",
  "progress": 2,
  "total": 5,
  "file_size": 183420
}
```

#### `GET /tts/stream/{cache_id}`
Streaming audio khi file vẫn đang được tạo.

#### `GET /tts/file/{cache_id}`
Trả về file MP3 **chỉ khi cache đã hoàn chỉnh và hợp lệ**.

---

## 6) Tại sao bản code mới ổn định hơn?

Bản đã chỉnh sửa khắc phục các vấn đề thường gặp:

- Không còn dùng **HTTP Range giả** cho file đang tăng dần kích thước
- Không còn nhầm lẫn giữa:
  - **backend generate xong**
  - **frontend tải đủ dữ liệu**
  - **audio phát xong**
- `/tts/file/{cache_id}` chỉ phục vụ file cache **hoàn chỉnh**
- Dọn dẹp cache lỗi / file dở dang khi generate thất bại
- Tránh báo **“Hoàn thành” quá sớm** trên frontend

---

## 7) Docker

### Build image

```bash
docker build -t story2audio:latest .
```

### Chạy container

```bash
docker run -d \
  --name story2audio \
  -p 8000:8000 \
  --env-file .env \
  -v story2audio_cache:/app/audio_cache \
  story2audio:latest
```

---

## 8) Docker Compose / Coolify

Repo này có sẵn file `docker-compose.yml` để triển khai.

### Chạy local bằng Docker Compose

```bash
docker compose up -d --build
```

### Với Coolify

#### Cách triển khai khuyến nghị
1. Push source code lên Git repository
2. Trong Coolify, tạo **Docker Compose Resource**
3. Trỏ tới repo chứa project này
4. Chọn file `docker-compose.yml`
5. Khai báo biến môi trường nếu cần (`PROXY`)
6. Thiết lập **Port = 8000** nếu Coolify yêu cầu
7. Deploy

### Vì sao cần volume cho `audio_cache`
Nếu không mount volume persistent:
- mỗi lần redeploy / recreate container sẽ mất cache audio

Vì vậy `docker-compose.yml` đã có:
- volume named cho `/app/audio_cache`

---

## 9) Healthcheck

Container có healthcheck để Coolify/Docker biết ứng dụng đang sống.

Endpoint kiểm tra là:

```text
GET /
```

Nếu cần chuẩn production hơn, bạn có thể thêm endpoint riêng như `/healthz` trong `main.py`.

Ví dụ:

```python
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
```

Sau đó đổi lại `healthcheck` trong compose cho sạch hơn.

---

## 10) Cập nhật dependency sau khi sửa `pyproject.toml`

Nếu bạn đang dùng `uv`, hãy chạy lại:

```bash
uv lock
uv sync
```

Nếu dùng Docker với `uv sync`, nên commit cả:
- `pyproject.toml`
- `uv.lock`

để môi trường build nhất quán hơn.

---

## 11) Checklist trước khi deploy production

- [ ] `main.py` đã là bản mới
- [ ] `templates/index.html` đã là bản mới
- [ ] `pyproject.toml` đã dọn dependency thừa
- [ ] `uv.lock` đã update lại (nếu dùng `uv`)
- [ ] Có `.env` hợp lệ
- [ ] `audio_cache/` dùng persistent volume
- [ ] Đã cấu hình domain / reverse proxy trên Coolify nếu cần
- [ ] Đã kiểm tra quyền ghi thư mục `/app/audio_cache`

---

## 12) Troubleshooting

### 1. Trình duyệt không phát live được
Nguyên nhân có thể:
- trình duyệt không hỗ trợ `MediaSource` cho `audio/mpeg`
- mạng chậm
- stream bị proxy trung gian buffer

Cách xử lý:
- kiểm tra console browser
- nếu cần, app sẽ tự fallback sang chế độ phát sau khi file hoàn tất

### 2. gTTS lỗi mạng / timeout
- kiểm tra internet outbound
- kiểm tra proxy trong `.env`
- thử lại bằng engine `edge`

### 3. Redeploy xong mất cache
- kiểm tra volume `audio_cache`
- chắc chắn `docker-compose.yml` có mount volume persistent

### 4. Coolify deploy thành công nhưng không vào được web
- kiểm tra service port là `8000`
- kiểm tra container log
- kiểm tra domain / ingress / reverse proxy trong Coolify

---

## 13) Gợi ý cải tiến tiếp theo

Nếu muốn nâng cấp thêm, bạn có thể làm tiếp:

- Thêm nút **Download MP3**
- Thêm endpoint **xóa cache cũ**
- Thêm cơ chế **TTL cho cache**
- Thêm **/healthz** riêng cho healthcheck
- Thêm nhiều giọng đọc hơn
- Thêm tùy chọn tốc độ nói thực sự ở backend (không chỉ playback speed ở frontend)
- Giới hạn độ dài text tối đa để bảo vệ tài nguyên server

---

## 14) Giấy phép / ghi chú

Bạn có thể tự bổ sung phần license theo nhu cầu nội bộ hoặc public repo.

Nếu đây là project dùng nội bộ trong công ty, nên ghi chú thêm:
- môi trường proxy
- policy lưu cache audio
- giới hạn nội dung đầu vào

---

## 15) Tóm tắt khuyến nghị cho project hiện tại

### Cấu trúc project
**Ổn**, chỉ cần lưu ý không commit `.venv`, `__pycache__`, cache audio thật.

### `pyproject.toml`
**Nên cập nhật** để bỏ dependency thừa và mô tả project rõ ràng hơn.

### README
Đã viết lại đầy đủ trong file này.

### Docker Compose cho Coolify
Đã chuẩn bị sẵn file `docker-compose.yml` và `Dockerfile` để triển khai.

Chúc bạn triển khai thuận lợi 🚀
