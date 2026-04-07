# Story to Audio (TTS Streaming)

Ứng dụng chuyển đổi văn bản truyện thành audio với tính năng streaming real-time. Sử dụng FastAPI làm backend và HTML/JavaScript làm frontend.

## Tính năng

- **Streaming real-time**: Audio được phát ngay khi có dữ liệu mà không cần chờ toàn bộ file hoàn thành
- **Chunking thông minh**: Tách văn bản thành các đoạn nhỏ, đoạn đầu tiên được xử lý nhanh nhất để phát sớm
- **Hai engine TTS**:
  - **Edge-TTS**: Chất lượng cao, giọng nói tự nhiên (Tiếng Việt)
  - **Google TTS (gTTS)**: Miễn phí, không cần API key
- **Cache thông minh**: Audio đã generate được lưu cache, không cần tạo lại
- **Hai chế độ phát**:
  - **MediaSource API**: Phát liên tục không gián đoạn (ưu tiên)
  - **Fallback**: Polling và reload khi MediaSource không được hỗ trợ

## Cài đặt

### Yêu cầu

- Python 3.10+
- uv (recommended) hoặc pip

### Cài đặt dependencies

```bash
# Sử dụng uv (khuyến nghị)
uv sync

# Hoặc sử dụng pip
pip install -r pyproject.toml
```

### Cấu hình (tùy chọn)

Copy file `.env.example` thành `.env` và cấu hình proxy nếu cần:

```bash
cp .env.example .env
```

Chỉnh sửa `.env`:
```
PROXY=http://your-proxy-address:port
```

## Chạy ứng dụng

```bash
python main.py
```

Server sẽ chạy tại: `http://localhost:8000`

## API Endpoints

### `POST /tts/start`

Bắt đầu generate audio từ văn bản.

**Request Body:**
```json
{
  "text": "Nội dung truyện...",
  "voice": "vi-VN-HoaiMyNeural",  // Chỉ dùng với edge-tts
  "engine": "edge"  // hoặc "gtts"
}
```

**Response:**
```json
{
  "cache_id": "abc123...",
  "status": "started"  // hoặc "completed" nếu có trong cache
}
```

### `GET /tts/status/{cache_id}`

Lấy trạng thái generation.

**Response:**
```json
{
  "status": "processing",  // hoặc "completed", "failed"
  "progress": 2,
  "total": 5,
  "file_size": 123456
}
```

### `GET /tts/file/{cache_id}`

Download file audio (hỗ trợ Range header cho streaming).

### `GET /tts/stream/{cache_id}`

Stream audio real-time sử dụng chunked transfer encoding.

## Cấu trúc project

```
story2audio/
├── main.py              # Backend FastAPI
├── templates/
│   └── index.html       # Frontend UI
├── static/
│   └── favicon.svg      # Favicon
├── audio_cache/         # Thư mục cache audio (tự tạo)
├── .env.example         # Template cấu hình
├── pyproject.toml       # Dependencies
└── README.md           # File này
```

## Cách hoạt động

### Backend

1. **Text Chunking**: Văn bản được chia thành các đoạn nhỏ, đoạn đầu tiên chỉ có 1 câu để phát nhanh nhất có thể.

2. **Background Generation**: Các chunk được generate tuần tự trong background task. Mỗi chunk được append vào file audio ngay khi hoàn thành.

3. **Streaming**: Frontend có thể stream audio qua `/tts/stream/{cache_id}` hoặc download qua `/tts/file/{cache_id}` với Range header.

4. **Cache**: Audio hoàn thành được lưu vào `audio_cache/` với metadata JSON để xác nhận tính hợp lệ.

### Frontend

1. **MSE Mode** (MediaSource API): Ưu tiên sử dụng, cho phép phát liên tục không gián đoạn. Stream dữ liệu từ `/tts/stream/` và append vào SourceBuffer.

2. **Fallback Mode**: Nếu trình duyệt không hỗ trợ MediaSource, sử dụng polling để kiểm tra file size và reload src định kỳ.

3. **Xử lý khi phát hết đoạn**: Nếu audio phát hết mà generation còn đang xử lý, frontend tự động fetch thêm dữ liệu để tiếp tục phát.

## Giọng đọc (Edge-TTS)

| Giọng | Mã |
|------|-----|
| Hoài Mỹ (Nữ) | vi-VN-HoaiMyNeural |
| Nam Minh (Nam) | vi-VN-NamMinhNeural |

## Tốc độ phát

Có thể điều chỉnh tốc độ phát: 0.75x, 1x, 1.25x, 1.5x, 2x

## Khắc phục sự cố

### Lỗi kết nối TTS

- Kiểm tra kết nối internet
- Thử cấu hình proxy trong `.env`
- Với gTTS: Có thể thử lại sau

### Audio bị gián đoạn

- Kiểm tra tốc độ mạng
- Đợi generation hoàn thành

### Trình duyệt không hỗ trợ MediaSource

- Sử dụng trình duyệt hiện đại (Chrome, Firefox, Edge)
- Ứng dụng会自动 fallback sang chế độ polling