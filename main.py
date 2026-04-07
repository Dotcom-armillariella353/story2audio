import os
import hashlib
import asyncio
import re
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from typing import List, Dict
import edge_tts
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Story to Audio Streaming & Caching API")

# Cấu hình cache và proxy
PROXY = os.getenv("PROXY")
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

if PROXY:
    os.environ['HTTP_PROXY'] = PROXY
    os.environ['HTTPS_PROXY'] = PROXY

# Lưu trạng thái tiến trình
generation_status: Dict[str, dict] = {}

def split_text_into_chunks(text: str) -> List[str]:
    """Chia văn bản thành các chunk với kích thước tăng dần:
    - Chunk 1: Câu đầu tiên (phản hồi nhanh nhất)
    - Chunk 2+: Tăng dần từ 500 -> 1000 -> 1500 -> tối đa 2000 ký tự
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        return []

    chunks = []
    # Chunk đầu tiên: chỉ lấy câu đầu để có audio ngay lập tức
    chunks.append(sentences[0])

    current_chunk = ""
    max_len = 500  # Bắt đầu từ 500 ký tự, tăng dần

    for sentence in sentences[1:]:
        if len(current_chunk) + len(sentence) + 1 < max_len:
            current_chunk = (current_chunk + " " + sentence).strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence
            # Tăng giới hạn cho chunk tiếp theo, tối đa 2000 ký tự
            max_len = min(2000, max_len + 500)

    if current_chunk:
        chunks.append(current_chunk)

    return [c for c in chunks if c.strip()]

def get_cache_id(text: str, voice: str, engine: str):
    hash_input = f"{text}_{voice}_{engine}".encode('utf-8')
    return hashlib.md5(hash_input).hexdigest()

def strip_id3(data: bytes) -> bytes:
    """Loại bỏ header ID3v2 nếu có để nối MP3 mượt mà hơn."""
    if data.startswith(b'ID3'):
        # Size của ID3 nằm ở byte 6-9, là 4 bytes 7-bit (synchsafe)
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        return data[size + 10:]
    return data

async def generate_chunks(text: str, voice: str, engine: str, cache_id: str):
    chunks = split_text_into_chunks(text)
    total_chunks = len(chunks)
    
    generation_status[cache_id] = {
        "status": "processing",
        "progress": 0,
        "total": total_chunks
    }
    
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    
    try:
        # Xóa file cũ nếu có để tránh nối đè
        if os.path.exists(final_path):
            os.remove(final_path)
            
        for i, chunk in enumerate(chunks):
            temp_chunk_file = os.path.join(CACHE_DIR, f"{cache_id}_temp_{i}.mp3")
            
            # Generate chunk
            if engine == "edge":
                communicate = edge_tts.Communicate(chunk, voice, proxy=PROXY)
                await communicate.save(temp_chunk_file)
            else:
                tts = gTTS(text=chunk, lang='vi')
                tts.save(temp_chunk_file)
            
            # Đọc bytes và ghi vào file tổng
            if os.path.exists(temp_chunk_file):
                with open(temp_chunk_file, 'rb') as infile:
                    chunk_data = infile.read()
                    
                # Chỉ giữ ID3 cho chunk đầu tiên, các chunk sau strip bỏ để nối mượt
                if i > 0:
                    chunk_data = strip_id3(chunk_data)
                
                with open(final_path, 'ab') as outfile:
                    outfile.write(chunk_data)
                
                # Xóa temp
                os.remove(temp_chunk_file)
            
            # Cập nhật tiến trình
            generation_status[cache_id]["progress"] = i + 1
                
        generation_status[cache_id]["status"] = "completed"
    except Exception as e:
        print(f"Error at chunk {i}: {e}")
        generation_status[cache_id]["status"] = "failed"

@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = "templates/index.html"
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    return "Template index.html not found."

@app.get("/tts/start")
async def start_tts(
    background_tasks: BackgroundTasks,
    text: str = Query(..., description="Nội dung văn bản cần chuyển đổi"),
    voice: str = Query("vi-VN-HoaiMyNeural", description="Giọng đọc (ví dụ: vi-VN-HoaiMyNeural)"),
    engine: str = Query("edge", description="Công cụ chuyển đổi (edge hoặc gtts)")
):
    cache_id = get_cache_id(text, voice, engine)
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    
    if os.path.exists(final_path) and (cache_id not in generation_status or generation_status[cache_id]["status"] == "completed"):
        return {"cache_id": cache_id, "status": "completed", "url": f"/tts/file/{cache_id}"}
    
    if cache_id in generation_status and generation_status[cache_id]["status"] == "processing":
        return {"cache_id": cache_id, "status": "processing"}

    background_tasks.add_task(generate_chunks, text, voice, engine, cache_id)
    return {"cache_id": cache_id, "status": "started"}

@app.get("/tts/status/{cache_id}")
async def get_status(cache_id: str):
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    file_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
    
    if cache_id not in generation_status:
        if os.path.exists(final_path):
             return {"status": "completed", "progress": 1, "total": 1, "file_size": file_size}
        raise HTTPException(status_code=404, detail="Not found")
    
    status = dict(generation_status[cache_id])
    status["file_size"] = file_size
    return status

@app.get("/tts/file/{cache_id}")
async def get_audio_file(cache_id: str, request: Request):
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    if not os.path.exists(final_path):
        raise HTTPException(status_code=404, detail="Audio not ready")
    
    file_size = os.path.getsize(final_path)
    range_header = request.headers.get("range")
    
    if range_header:
        # Parse range header: "bytes=start-end"
        range_val = range_header.replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        
        # Clamp end to file size
        end = min(end, file_size - 1)
        
        if start >= file_size:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        
        chunk_size = end - start + 1
        
        async def iter_file():
            with open(final_path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        # Nếu đang trong quá trình xử lý, có thể đợi thêm dữ liệu
                        if cache_id in generation_status and generation_status[cache_id]["status"] == "processing":
                             await asyncio.sleep(0.5)
                             continue
                        break
                    remaining -= len(data)
                    yield data
        
        # Nếu đang processing, báo với trình duyệt là file rất lớn để nó không dừng lại
        effective_file_size = file_size
        if cache_id in generation_status and generation_status[cache_id]["status"] == "processing":
            effective_file_size = file_size + 10 * 1024 * 1024 # Giả định thêm 10MB
            
        headers = {
            "Content-Range": f"bytes {start}-{end}/{effective_file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-cache"
        }
        return StreamingResponse(iter_file(), status_code=206, headers=headers)
    
    # No range header - return full file
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
    }
    return FileResponse(final_path, media_type="audio/mpeg", headers=headers)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
