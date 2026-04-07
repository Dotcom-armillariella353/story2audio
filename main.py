import os
import io
import json
import hashlib
import asyncio
import re
import sys
import time
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, AsyncGenerator, Optional
import edge_tts
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

# Suppress the benign Windows asyncio ProactorEventLoop socket shutdown error
if sys.platform == "win32":
    import asyncio.proactor_events

    _original_call_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost

    def _patched_call_connection_lost(self, exc):
        try:
            _original_call_connection_lost(self, exc)
        except OSError:
            pass

    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost

app = FastAPI(title="Story to Audio Streaming & Caching API")
app.mount("/static", StaticFiles(directory="static"), name="static")

PROXY = os.getenv("PROXY")
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

if PROXY:
    os.environ['HTTP_PROXY'] = PROXY
    os.environ['HTTPS_PROXY'] = PROXY

generation_status: Dict[str, dict] = {}
_generation_locks: Dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def split_text_into_chunks(text: str) -> List[str]:
    """
    Split text into progressively larger chunks:
    - Chunk 1: first sentence only  -> fastest first audio
    - Chunk 2: up to 400 chars
    - Chunk 3: up to 800 chars
    - Chunk 4: up to 1200 chars
    - Chunk 5+: up to 1800 chars (max)
    Always split on sentence boundaries.
    """
    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r'(?<=[.!?\u2026])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return []
    if len(sentences) == 1:
        return sentences

    chunks = [sentences[0]]  # chunk 1: first sentence only

    current = ""
    chunk_sizes = [400, 800, 1200, 1600, 1800]
    size_idx = 0

    for sentence in sentences[1:]:
        max_len = chunk_sizes[min(size_idx, len(chunk_sizes) - 1)]
        candidate = (current + " " + sentence).strip() if current else sentence

        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
                size_idx += 1
            current = sentence

    if current:
        chunks.append(current)

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def get_cache_id(text: str, voice: str, engine: str) -> str:
    return hashlib.md5(f"{text}_{voice}_{engine}".encode()).hexdigest()


def get_meta_path(cache_id: str) -> str:
    """Path to metadata file for a cache entry."""
    return os.path.join(CACHE_DIR, f"{cache_id}.json")


def save_cache_meta(cache_id: str, data: dict) -> None:
    """Save metadata for a cache entry."""
    meta_path = get_meta_path(cache_id)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def load_cache_meta(cache_id: str) -> Optional[dict]:
    """Load metadata for a cache entry. Returns None if not found or invalid."""
    meta_path = get_meta_path(cache_id)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def is_cache_valid(cache_id: str) -> bool:
    """Check if cache is complete and valid.
    
    A valid cache must have:
    1. Both .mp3 and .json files exist
    2. Metadata shows status='completed'
    3. Actual file size matches expected size (if recorded)
    """
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    if not os.path.exists(final_path):
        return False
    
    meta = load_cache_meta(cache_id)
    if not meta:
        return False
    
    if meta.get("status") != "completed":
        return False
    
    # Verify file size if we have it recorded
    expected_size = meta.get("file_size")
    if expected_size is not None:
        actual_size = os.path.getsize(final_path)
        if actual_size != expected_size:
            return False
    
    return True


def cleanup_incomplete_cache(cache_id: str) -> None:
    """Remove incomplete cache files (both .mp3 and .json)."""
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    meta_path = get_meta_path(cache_id)
    
    if os.path.exists(final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
    
    if os.path.exists(meta_path):
        try:
            os.remove(meta_path)
        except OSError:
            pass


def strip_id3v2(data: bytes) -> bytes:
    """Remove ID3v2 header so concatenated MP3 frames are seamless."""
    if len(data) >= 10 and data[:3] == b'ID3':
        size = (
            ((data[6] & 0x7F) << 21) |
            ((data[7] & 0x7F) << 14) |
            ((data[8] & 0x7F) << 7) |
            (data[9] & 0x7F)
        )
        return data[size + 10:]
    return data


async def edge_tts_to_bytes(text: str, voice: str) -> bytes:
    """Stream edge-tts directly into memory (no temp file)."""
    communicate = edge_tts.Communicate(text, voice, proxy=PROXY)
    parts = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            parts.append(chunk["data"])
    return b"".join(parts)


def gtts_to_bytes(text: str) -> bytes:
    """Synchronous gTTS -> bytes (run in executor).

    gTTS.stream() picks up proxy via urllib.request.getproxies() which reads
    HTTP_PROXY / HTTPS_PROXY env vars (already set at startup when PROXY is
    configured).  We add a retry loop with specific handling for socket/connection
    errors to handle transient Google API failures.
    """
    last_exc = None
    for attempt in range(3):
        try:
            tts = gTTS(text=text, lang='vi', timeout=15)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            return buf.getvalue()
        except Exception as exc:
            last_exc = exc
            # Log specific error types for better debugging
            error_type = type(exc).__name__
            if "socket" in error_type.lower() or "connection" in error_type.lower():
                print(f"[WARN] gTTS attempt {attempt + 1} failed with {error_type}: {exc}")
            else:
                print(f"[WARN] gTTS attempt {attempt + 1} failed: {exc}")
            
            if attempt < 2:
                # Longer delay for socket/connection errors
                delay = 3 * (attempt + 1) if "socket" in error_type.lower() or "connection" in error_type.lower() else 2 * (attempt + 1)
                time.sleep(delay)
    raise last_exc


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------

async def generate_chunks(text: str, voice: str, engine: str, cache_id: str):
    if cache_id not in _generation_locks:
        _generation_locks[cache_id] = asyncio.Lock()

    async with _generation_locks[cache_id]:
        final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
        
        # Double-check after acquiring lock - verify cache is truly complete
        if is_cache_valid(cache_id):
            generation_status[cache_id] = {
                "status": "completed",
                "progress": 1,
                "total": 1
            }
            return

        chunks = split_text_into_chunks(text)
        total = len(chunks)
        generation_status[cache_id] = {"status": "processing", "progress": 0, "total": total}
        
        # Save initial metadata
        save_cache_meta(cache_id, {
            "status": "processing",
            "progress": 0,
            "total": total,
            "text_hash": hashlib.md5(text.encode()).hexdigest()[:16],
            "voice": voice,
            "engine": engine,
        })

        # Clean up any incomplete files from previous attempts
        if os.path.exists(final_path):
            os.remove(final_path)

        try:
            for i, chunk_text in enumerate(chunks):
                if engine == "edge":
                    audio = await edge_tts_to_bytes(chunk_text, voice)
                else:
                    loop = asyncio.get_event_loop()
                    audio = await loop.run_in_executor(None, gtts_to_bytes, chunk_text)

                if not audio:
                    continue

                # Strip ID3v2 from chunk 2+ so frames concatenate cleanly
                if i > 0:
                    audio = strip_id3v2(audio)

                with open(final_path, 'ab') as f:
                    f.write(audio)

                generation_status[cache_id]["progress"] = i + 1
                
                # Update metadata with progress
                save_cache_meta(cache_id, {
                    "status": "processing",
                    "progress": i + 1,
                    "total": total,
                    "text_hash": hashlib.md5(text.encode()).hexdigest()[:16],
                    "voice": voice,
                    "engine": engine,
                })

            # Mark as completed with final file size
            final_size = os.path.getsize(final_path)
            generation_status[cache_id]["status"] = "completed"
            save_cache_meta(cache_id, {
                "status": "completed",
                "progress": total,
                "total": total,
                "file_size": final_size,
                "text_hash": hashlib.md5(text.encode()).hexdigest()[:16],
                "voice": voice,
                "engine": engine,
            })

        except Exception as exc:
            print(f"[ERROR] generate_chunks chunk={i} engine={engine}: {type(exc).__name__}: {exc}")
            generation_status[cache_id]["status"] = "failed"
            generation_status[cache_id]["error"] = f"{type(exc).__name__}: {exc}"
            save_cache_meta(cache_id, {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "text_hash": hashlib.md5(text.encode()).hexdigest()[:16],
            })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    path = "templates/index.html"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "Template not found."


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


class TTSRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    engine: str = "edge"


@app.post("/tts/start")
async def start_tts(
    background_tasks: BackgroundTasks,
    request: TTSRequest,
):
    text = request.text
    engine = request.engine
    # gTTS doesn't use voice - use empty string for cache consistency
    voice = request.voice if engine == "edge" else ""
    cache_id = get_cache_id(text, voice, engine)
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")

    # Check if cache is valid (complete file with matching metadata)
    if is_cache_valid(cache_id):
        return {"cache_id": cache_id, "status": "completed", "url": f"/tts/file/{cache_id}"}
    
    # Clean up any incomplete cache from previous failed attempts
    if os.path.exists(final_path) or os.path.exists(get_meta_path(cache_id)):
        cleanup_incomplete_cache(cache_id)

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
    """
    Serve audio with Range support.
    While generating: reports an inflated Content-Length so the browser
    keeps reading, and the generator waits for new data to arrive.
    """
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")
    if not os.path.exists(final_path):
        raise HTTPException(status_code=404, detail="Audio not ready")

    file_size = os.path.getsize(final_path)
    is_processing = (
        cache_id in generation_status
        and generation_status[cache_id]["status"] == "processing"
    )

    range_header = request.headers.get("range")

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end_req = int(parts[1]) if len(parts) > 1 and parts[1] else None

        if start >= file_size:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")

        # Inflate reported size while still generating
        reported_size = file_size
        if is_processing:
            st = generation_status[cache_id]
            progress = max(st["progress"], 1)
            total = max(st["total"], 1)
            estimated = int(file_size * total / progress * 1.1)
            reported_size = max(estimated, file_size + 5 * 1024 * 1024)

        end = end_req if end_req is not None else file_size - 1
        end = min(end, file_size - 1)
        resp_len = end - start + 1
        # Use a mutable container so the inner async generator can update it
        _window = [resp_len]

        async def iter_range() -> AsyncGenerator[bytes, None]:
            READ = 65536
            sent = 0
            with open(final_path, "rb") as f:
                f.seek(start)
                while sent < _window[0]:
                    data = f.read(READ)
                    if data:
                        sent += len(data)
                        yield data
                    else:
                        # No data yet - wait if still generating
                        still = (
                            cache_id in generation_status
                            and generation_status[cache_id]["status"] == "processing"
                        )
                        if still:
                            await asyncio.sleep(0.25)
                            new_size = os.path.getsize(final_path)
                            if new_size > start + sent:
                                f.seek(start + sent)
                                # Expand window if no explicit end was requested
                                if end_req is None:
                                    _window[0] = new_size - start
                                continue
                        else:
                            break

        headers = {
            "Content-Range": f"bytes {start}-{end}/{reported_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(resp_len),
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-cache",
        }
        return StreamingResponse(iter_range(), status_code=206, headers=headers)

    # No Range header - serve full file
    return FileResponse(
        final_path,
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "no-cache"},
    )


@app.get("/tts/stream/{cache_id}")
async def stream_audio_live(cache_id: str):
    """
    True live-streaming endpoint using chunked transfer encoding.
    Sends audio bytes as soon as they are written to disk.
    Designed for use with the MediaSource API on the frontend.
    """
    final_path = os.path.join(CACHE_DIR, f"{cache_id}.mp3")

    # Wait up to 10 s for the file to appear, bail early if generation failed
    for _ in range(100):
        if os.path.exists(final_path):
            break
        # Bail early if generation already failed
        if (
            cache_id in generation_status
            and generation_status[cache_id]["status"] == "failed"
        ):
            err = generation_status[cache_id].get("error", "generation failed")
            raise HTTPException(status_code=503, detail=f"Generation failed: {err}")
        await asyncio.sleep(0.1)
    else:
        # Final check: maybe it failed right at the end
        if (
            cache_id in generation_status
            and generation_status[cache_id]["status"] == "failed"
        ):
            err = generation_status[cache_id].get("error", "generation failed")
            raise HTTPException(status_code=503, detail=f"Generation failed: {err}")
        raise HTTPException(status_code=404, detail="Audio not ready")

    async def generate() -> AsyncGenerator[bytes, None]:
        READ = 8192  # small chunks -> low latency
        sent = 0

        while True:
            cur_size = os.path.getsize(final_path)

            if cur_size > sent:
                with open(final_path, "rb") as f:
                    f.seek(sent)
                    while True:
                        data = f.read(READ)
                        if not data:
                            break
                        sent += len(data)
                        yield data

            # Check if generation finished
            # Priority: in-memory status > metadata file
            is_processing = False
            
            # Check in-memory status first
            if cache_id in generation_status:
                status = generation_status[cache_id].get("status")
                is_processing = status == "processing"
                if status == "failed":
                    break
                if status == "completed":
                    # Verify file size matches
                    meta = load_cache_meta(cache_id)
                    expected_size = meta.get("file_size") if meta else None
                    if expected_size is None or sent >= expected_size:
                        break
                    # Wait for remaining data
            else:
                # Not in memory - check metadata
                meta = load_cache_meta(cache_id)
                if meta:
                    meta_status = meta.get("status")
                    if meta_status == "completed":
                        # Already completed from previous run
                        expected_size = meta.get("file_size")
                        if expected_size and sent >= expected_size:
                            break
                    elif meta_status == "failed":
                        break
                    # If processing, continue waiting
                    is_processing = meta_status == "processing"
            
            # If still processing or no status info, wait for more data
            await asyncio.sleep(0.2)

    return StreamingResponse(
        generate(),
        headers={
            "Content-Type": "audio/mpeg",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
