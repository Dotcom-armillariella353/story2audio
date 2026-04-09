# Story2Audio 🎧

Story2Audio là một ứng dụng API và Web Interface hiệu năng cao được viết bằng **FastAPI**, giúp chuyển đổi văn bản và truyện thành âm thanh (Text-to-Speech) chuyên nghiệp. Điểm nổi bật nhất của Story2Audio là khả năng **phát trực tiếp (Live Streaming) ngay khi âm thanh đang được tạo** kết hợp với **phụ đề trực tiếp (Live Subtitles)**, giúp người dùng vừa nghe vừa đọc theo thời gian thực mà không cần chờ toàn bộ quá trình chuyển đổi hoàn tất.

## ✨ Tính năng nổi bật

- **Live Streaming với MediaSource:** Không còn độ trễ chờ đợi! Backend stream audio chunks dưới dạng byte và Frontend ghép nối phát ngay theo thời gian thực.
- **Phụ đề trực tiếp (Live Subtitles):** Tự động tạo phụ đề theo từng từ (word-level) khi sử dụng Edge TTS. Phụ đề được hiển thị song song với audio trên giao diện web và cập nhật theo thời gian thực thông qua SSE (Server-Sent Events). Hỗ trợ tải về định dạng **SRT** và **WebVTT**.
- **Đa định dạng phụ đề:** Phụ đề được xuất tự động dưới 3 định dạng:
  - **SRT** (SubRip) — Phổ biến cho trình phát video và bộ chỉnh sửa phụ đề.
  - **WebVTT** — Định dạng chuẩn cho web, tương thích với thẻ `<track>` của HTML5 `<video>`.
  - **Cues JSON** — Dữ liệu cấu trúc `{start, end, text}` để tích hợp vào ứng dụng bên thứ ba.
- **Hỗ trợ đa ngôn ngữ (Multi-language & i18n):** Hỗ trợ 7 ngôn ngữ: Tiếng Việt, Tiếng Anh, Tiếng Nhật, Tiếng Trung, Tiếng Hàn, Tiếng Pháp, Tiếng Đức. Giao diện thay đổi tức thì, hệ thống cung cấp các giọng đọc bản địa chất lượng cao tương ứng.
- **Hệ thống Cache thông minh:** Âm thanh và phụ đề được tạo ra sẽ được lưu lại (theo mã hash của văn bản + ngôn ngữ + engine + giọng đọc). Nếu người dùng yêu cầu lại cùng văn bản đó, ứng dụng sẽ phát ngay từ cache, tiết kiệm tối đa CPU và băng thông.
- **Giao diện hiện đại:** Bố cục card-based, bảng màu tươi mới, responsive trên mọi thiết bị. Bộ chuyển đổi ngôn ngữ tích hợp sẵn trên giao diện (client-side i18n).
- **Bảo mật và Quản lý lỗi:** Tự động loại bỏ cache bị lỗi, có cơ chế chặn Race Condition (không xóa nhầm file đang tạo). API Stream báo lỗi 503 để Client tự retry (Retry-After). Debug API được bảo vệ bởi biến môi trường.
- **Tùy chọn Engine mạnh mẽ:**
  - **Edge-TTS:** Engine chính với giọng đọc tự nhiên chuẩn Neural, hỗ trợ phụ đề trực tiếp (word boundary), đa dạng giọng điệu cho từng quốc gia.
  - **Google TTS (gTTS):** Hoạt động ổn định như phương án dự phòng (không hỗ trợ phụ đề).

## 📁 Cấu trúc dự án

```text
story2audio/
├─ audio_cache/              # (Tự sinh) Thư mục lưu trữ file .mp3, .srt, .vtt, .cues.json, .cues.jsonl và .json (metadata)
├─ static/
│  └─ favicon.svg            # Icon ứng dụng
├─ templates/
│  └─ index.html             # Giao diện người dùng duy nhất (Single Page) — tích hợp player + phụ đề
├─ main.py                   # Chứa toàn bộ logic FastAPI, API routing, TTS Generator và Subtitle Engine
├─ pyproject.toml / uv.lock  # Quản lý dependency dự án
├─ Dockerfile                # File build Docker container
├─ docker-compose.yml        # Triển khai dễ dàng bằng Compose
├─ .env.example              # File biến môi trường mẫu
├─ LICENSE                   # Giấy phép MIT
├─ CONTRIBUTING.md           # Hướng dẫn đóng góp
└─ RELEASE_NOTES.md          # Lịch sử phát hành
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

## 📡 Tài liệu API Endpoints

### Core Endpoints

| Phương thức | Endpoint | Mô tả |
|:---:|---|---|
| `GET` | `/` | Giao diện Web chính |
| `GET` | `/health` | Kiểm tra trạng thái hệ thống |
| `GET` | `/tts/voices` | Danh sách giọng đọc theo ngôn ngữ |

### TTS Endpoints

| Phương thức | Endpoint | Mô tả |
|:---:|---|---|
| `POST` | `/tts/start` | Bắt đầu chuyển đổi văn bản thành audio. Nhận JSON `{text, language, voice, engine}`. Trả về `cache_id` và trạng thái. |
| `GET` | `/tts/status/{cache_id}` | Trạng thái chuyển đổi hiện tại (queued / processing / completed / failed). |
| `GET` | `/tts/file/{cache_id}` | Tải file audio MP3 hoàn chỉnh (chỉ khi đã tạo xong). |
| `GET` | `/tts/stream/{cache_id}` | Stream audio trực tiếp theo thời gian thực (chunked transfer). Dùng cho MediaSource API trên Frontend. |
| `POST` | `/tts/debug/chunks` | (Chỉ khi `ENABLE_DEBUG_TTS=true`) Xem kết quả chia nhỏ văn bản thành các chunk. |

### Subtitle Endpoints (Phiên bản 3.0+)

> Tính năng phụ đề chỉ hoạt động khi sử dụng **Edge TTS** engine.

| Phương thức | Endpoint | Mô tả |
|:---:|---|---|
| `GET` | `/tts/subtitle/srt/{cache_id}` | Tải file phụ đề định dạng **SRT** (SubRip). Trả về 404 nếu dùng gTTS hoặc phụ đề chưa sẵn sàng. |
| `GET` | `/tts/subtitle/vtt/{cache_id}` | Tải file phụ đề định dạng **WebVTT**. Tương thích với HTML5 `<video>` và các trình phát web. |
| `GET` | `/tts/cues/{cache_id}` | Lấy danh sách cues dưới dạng JSON `{cues: [{start, end, text}], done: bool}`. Trả về partial cues khi đang tạo, full cues khi hoàn tất. |
| `GET` | `/tts/cues/stream/{cache_id}` | **SSE (Server-Sent Events)** stream cues trực tiếp theo thời gian thực. Frontend nhận từng cue ngay khi được tạo, bao gồm các event type: `cue` (dữ liệu phụ đề mới), `complete` (hoàn tất), `error` (lỗi). |

### Ví dụ Response `/tts/start`

```json
{
  "cache_id": "a1b2c3d4e5f6",
  "status": "started",
  "estimated_chunks": 5,
  "subtitle_supported": true,
  "subtitle_ready": false
}
```

### Ví dụ SSE Event `/tts/cues/stream/{cache_id}`

```
event: cue
data: {"index": 1, "start": 0.0, "end": 1.52, "text": "Ngày xửa ngày xưa,"}

event: cue
data: {"index": 2, "start": 1.52, "end": 3.18, "text": "có một cô bé ở làng ven núi."}

event: complete
data: {"done": true}
```

---

## 📜 Luồng hoạt động (Workflow) của ứng dụng

1. **Client gửi văn bản:** Người dùng nhập truyện và chọn tuỳ chọn trên Web (Ngôn ngữ, Giọng, Engine) → Bấm Chuyển đổi.
2. **Backend tiếp nhận (`POST /tts/start`):**
   - Phân tích và chia nhỏ văn bản (Chunking) dựa theo quy tắc ngắt câu của từng ngôn ngữ.
   - Hash nội dung để sinh ra `cache_id` duy nhất.
   - Nếu audio và phụ đề đã tồn tại (cached), trả về URL ngay lập tức.
   - Nếu chưa có, đưa vào hàng đợi chạy ngầm (Background Task) và trả về trạng thái `started` + `cache_id`.
3. **Quá trình tạo Audio & Phụ đề (`generate_chunks`):**
   - Xử lý từng đoạn văn bản, gọi API Edge-TTS hoặc gTTS.
   - Với Edge TTS: thu thập dữ liệu `WordBoundary` / `SentenceBoundary` (thời gian bắt đầu, kết thúc, nội dung từng từ).
   - Gom các word boundary thành **cue** có ý nghĩa (mỗi cue chứa một cụm từ hoàn chỉnh) và ghi追加 vào file `.cues.jsonl`.
   - Tính toán thời lượng MP3 của từng chunk để căn chỉnh thời gian phụ đề chính xác.
   - Ghi nối tiếp audio vào file `.mp3`, ghi cues incremental vào `.cues.jsonl`.
   - Trừ chunk đầu tiên, các chunk tiếp theo bị cắt header `ID3v2` để loại bỏ nhiễu khi ghép nối.
4. **Client nhận Audio (`/tts/stream/{cache_id}`):**
   - Trình duyệt liên tục yêu cầu file thông qua Live Stream chunk.
   - Sử dụng `MediaSource API` trên Javascript để ghép nối và phát trực tiếp đoạn MP3 vừa được tải về (tải đến đâu, phát đến đó).
5. **Client nhận Phụ đề trực tiếp (`/tts/cues/stream/{cache_id}`):**
   - Frontend mở kết nối SSE và nhận từng cue ngay khi được tạo.
   - Phụ đề được hiển thị song song trên giao diện, tự động cuộn và bôi sáng theo tiến độ audio.
6. **Hoàn thành:** Tạo file phụ đề cuối cùng (`.srt`, `.vtt`, `.cues.json`). Cập nhật Metadata cache. Người dùng có thể nhấn nút "Tải MP3" hoặc "Tải phụ đề" để lưu file.

---

## 🗂 Cache & File Formats

Mỗi lần chuyển đổi tạo ra các file được lưu trong thư mục `audio_cache/`, định danh bởi `cache_id`:

| File | Định dạng | Mô tả |
|---|---|---|
| `{cache_id}.mp3` | Audio | File audio MP3 hoàn chỉnh |
| `{cache_id}.json` | JSON Metadata | Thông tin cache: trạng thái, kích thước file, engine, ngôn ngữ, giọng đọc, thông tin phụ đề |
| `{cache_id}.srt` | SRT Subtitle | File phụ đề định dạng SubRitp (chỉ Edge TTS) |
| `{cache_id}.vtt` | WebVTT Subtitle | File phụ đề định dạng WebVTT (chỉ Edge TTS) |
| `{cache_id}.cues.json` | JSON Array | Danh sách cues hoàn chỉnh `[{start, end, text, index}]` (chỉ Edge TTS) |
| `{cache_id}.cues.jsonl` | JSONL | File cues ghi theo từng dòng, dùng cho streaming incremental (chỉ Edge TTS) |

> **Lưu ý:** File `.cues.jsonl` là file tạm dùng trong quá trình tạo. Sau khi hoàn tất, dữ liệu được gom đầy đủ vào `.cues.json`, `.srt` và `.vtt`.

---

**Giấy phép (License):** MIT
