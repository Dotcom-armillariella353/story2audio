import os
import io
import json
import hashlib
import asyncio
import re
import sys
import time
from typing import List, Dict, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import edge_tts
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

# Suppress benign Windows asyncio ProactorEventLoop socket shutdown errors
if sys.platform == "win32":
    import asyncio.proactor_events

    _original_call_connection_lost = (
        asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost
    )

    def _patched_call_connection_lost(self, exc):
        try:
            _original_call_connection_lost(self, exc)
        except OSError:
            pass

    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = (
        _patched_call_connection_lost
    )

app = FastAPI(title="Story to Audio Streaming & Caching API")
app.mount("/static", StaticFiles(directory="static"), name="static")

PROXY = os.getenv("PROXY")
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Language & Voice Registry
# ---------------------------------------------------------------------------

# Edge TTS voices per language: { lang_code: [ {value, label}, ... ] }
EDGE_VOICES: Dict[str, List[Dict[str, str]]] = {
    "vi": [
        {"value": "vi-VN-HoaiMyNeural",  "label": "Hoài Mỹ (Nữ)"},
        {"value": "vi-VN-NamMinhNeural", "label": "Nam Minh (Nam)"},
    ],
    "en": [
        {"value": "en-US-AriaNeural",    "label": "Aria (Female, US)"},
        {"value": "en-US-GuyNeural",     "label": "Guy (Male, US)"},
        {"value": "en-US-JennyNeural",   "label": "Jenny (Female, US)"},
        {"value": "en-GB-SoniaNeural",   "label": "Sonia (Female, UK)"},
        {"value": "en-GB-RyanNeural",    "label": "Ryan (Male, UK)"},
        {"value": "en-AU-NatashaNeural", "label": "Natasha (Female, AU)"},
    ],
    "ja": [
        {"value": "ja-JP-NanamiNeural",  "label": "Nanami (女性)"},
        {"value": "ja-JP-KeitaNeural",   "label": "Keita (男性)"},
    ],
    "zh": [
        {"value": "zh-CN-XiaoxiaoNeural","label": "晓晓 (女, 普通话)"},
        {"value": "zh-CN-YunxiNeural",   "label": "云希 (男, 普通话)"},
        {"value": "zh-TW-HsiaoChenNeural","label": "曉臻 (女, 台灣)"},
    ],
    "ko": [
        {"value": "ko-KR-SunHiNeural",   "label": "선히 (여성)"},
        {"value": "ko-KR-InJoonNeural",  "label": "인준 (남성)"},
    ],
    "fr": [
        {"value": "fr-FR-DeniseNeural",  "label": "Denise (Femme, FR)"},
        {"value": "fr-FR-HenriNeural",   "label": "Henri (Homme, FR)"},
        {"value": "fr-CA-SylvieNeural",  "label": "Sylvie (Femme, CA)"},
    ],
    "de": [
        {"value": "de-DE-KatjaNeural",   "label": "Katja (Weiblich)"},
        {"value": "de-DE-ConradNeural",  "label": "Conrad (Männlich)"},
    ],
}

# gTTS language code mapping
GTTS_LANG_MAP: Dict[str, str] = {
    "vi": "vi",
    "en": "en",
    "ja": "ja",
    "zh": "zh",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
}

SUPPORTED_LANGUAGES = list(EDGE_VOICES.keys())

if PROXY:
    os.environ["HTTP_PROXY"] = PROXY
    os.environ["HTTPS_PROXY"] = PROXY

# In-memory runtime status (best effort); metadata file remains source of truth across restarts
generation_status: Dict[str, dict] = {}
_generation_locks: Dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def split_text_into_chunks(text: str) -> List[str]:
    """
    Split text into progressively larger chunks while preserving sentence boundaries.

    - Chunk 1: first sentence only  -> fastest first audio
    - Chunk 2: up to 400 chars
    - Chunk 3: up to 800 chars
    - Chunk 4: up to 1200 chars
    - Chunk 5+: up to 1800 chars
    """
    text = (text or "").strip()
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?…])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return []
    if len(sentences) == 1:
        return sentences

    chunks: List[str] = [sentences[0]]
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
# Cache helpers
# ---------------------------------------------------------------------------

def get_cache_id(text: str, voice: str, engine: str) -> str:
    return hashlib.md5(f"{text}_{voice}_{engine}".encode("utf-8")).hexdigest()


def get_audio_path(cache_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{cache_id}.mp3")


def get_meta_path(cache_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{cache_id}.json")


def save_cache_meta(cache_id: str, data: dict) -> None:
    meta_path = get_meta_path(cache_id)
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, meta_path)


def load_cache_meta(cache_id: str) -> Optional[dict]:
    meta_path = get_meta_path(cache_id)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def remove_audio_file(cache_id: str) -> None:
    audio_path = get_audio_path(cache_id)
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass


def cleanup_incomplete_cache(cache_id: str) -> None:
    audio_path = get_audio_path(cache_id)
    meta_path = get_meta_path(cache_id)

    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass

    if os.path.exists(meta_path):
        try:
            os.remove(meta_path)
        except OSError:
            pass


def is_cache_valid(cache_id: str) -> bool:
    audio_path = get_audio_path(cache_id)
    if not os.path.exists(audio_path):
        return False

    meta = load_cache_meta(cache_id)
    if not meta:
        return False

    if meta.get("status") != "completed":
        return False

    expected_size = meta.get("file_size")
    if expected_size is None:
        return False

    try:
        actual_size = os.path.getsize(audio_path)
    except OSError:
        return False

    return actual_size == expected_size and actual_size > 0


def get_effective_status(cache_id: str) -> Optional[dict]:
    """Return current status using in-memory state first, then metadata on disk."""
    audio_path = get_audio_path(cache_id)
    file_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0

    if cache_id in generation_status:
        status = dict(generation_status[cache_id])
        status["file_size"] = file_size
        return status

    meta = load_cache_meta(cache_id)
    if meta:
        status = dict(meta)
        status["file_size"] = file_size
        return status

    if is_cache_valid(cache_id):
        return {"status": "completed", "progress": 1, "total": 1, "file_size": file_size}

    return None


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def strip_id3v2(data: bytes) -> bytes:
    """Remove ID3v2 header so concatenated MP3 frames are seamless."""
    if len(data) >= 10 and data[:3] == b"ID3":
        size = (
            ((data[6] & 0x7F) << 21)
            | ((data[7] & 0x7F) << 14)
            | ((data[8] & 0x7F) << 7)
            | (data[9] & 0x7F)
        )
        return data[size + 10 :]
    return data


async def edge_tts_to_bytes(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, proxy=PROXY)
    parts: List[bytes] = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            parts.append(chunk["data"])
    return b"".join(parts)


def gtts_to_bytes(text: str, lang: str = "vi") -> bytes:
    """
    Synchronous gTTS -> bytes (run in executor).
    Retries transient network/socket failures.
    """
    last_exc = None
    for attempt in range(3):
        try:
            tts = gTTS(text=text, lang=lang, timeout=15)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            return buf.getvalue()
        except Exception as exc:
            last_exc = exc
            error_type = type(exc).__name__
            print(f"[WARN] gTTS attempt {attempt + 1} failed with {error_type}: {exc}")
            if attempt < 2:
                delay = 3 * (attempt + 1) if any(
                    x in error_type.lower() for x in ("socket", "connection", "timeout")
                ) else 2 * (attempt + 1)
                time.sleep(delay)
    raise last_exc


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------

async def generate_chunks(text: str, voice: str, engine: str, cache_id: str, language: str = "vi"):
    if cache_id not in _generation_locks:
        _generation_locks[cache_id] = asyncio.Lock()

    async with _generation_locks[cache_id]:
        audio_path = get_audio_path(cache_id)

        if is_cache_valid(cache_id):
            generation_status[cache_id] = {"status": "completed", "progress": 1, "total": 1}
            return

        chunks = split_text_into_chunks(text)
        if not chunks:
            generation_status[cache_id] = {"status": "failed", "error": "Text must not be empty"}
            save_cache_meta(
                cache_id,
                {
                    "status": "failed",
                    "error": "Text must not be empty",
                    "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest()[:16],
                    "voice": voice,
                    "engine": engine,
                },
            )
            return

        total = len(chunks)
        generation_status[cache_id] = {"status": "processing", "progress": 0, "total": total}
        save_cache_meta(
            cache_id,
            {
                "status": "processing",
                "progress": 0,
                "total": total,
                "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest()[:16],
                "voice": voice,
                "engine": engine,
            },
        )

        remove_audio_file(cache_id)
        loop = asyncio.get_running_loop()

        try:
            for i, chunk_text in enumerate(chunks):
                if engine == "edge":
                    audio = await edge_tts_to_bytes(chunk_text, voice)
                else:
                    gtts_lang = GTTS_LANG_MAP.get(language, "en")
                    audio = await loop.run_in_executor(None, gtts_to_bytes, chunk_text, gtts_lang)

                if not audio:
                    continue

                if i > 0:
                    audio = strip_id3v2(audio)

                with open(audio_path, "ab") as f:
                    f.write(audio)
                    f.flush()

                current_size = os.path.getsize(audio_path)
                generation_status[cache_id]["progress"] = i + 1
                save_cache_meta(
                    cache_id,
                    {
                        "status": "processing",
                        "progress": i + 1,
                        "total": total,
                        "current_file_size": current_size,
                        "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest()[:16],
                        "voice": voice,
                        "engine": engine,
                    },
                )

            final_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
            if final_size <= 0:
                raise RuntimeError("Generated audio file is empty")

            generation_status[cache_id] = {"status": "completed", "progress": total, "total": total}
            save_cache_meta(
                cache_id,
                {
                    "status": "completed",
                    "progress": total,
                    "total": total,
                    "file_size": final_size,
                    "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest()[:16],
                    "voice": voice,
                    "engine": engine,
                },
            )
        except Exception as exc:
            print(f"[ERROR] generate_chunks engine={engine}: {type(exc).__name__}: {exc}")
            generation_status[cache_id] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            remove_audio_file(cache_id)
            save_cache_meta(
                cache_id,
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "text_hash": hashlib.md5(text.encode("utf-8")).hexdigest()[:16],
                    "voice": voice,
                    "engine": engine,
                },
            )
        finally:
            _generation_locks.pop(cache_id, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join("templates", "index.html")
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
    language: str = "vi"


@app.get("/tts/voices")
async def get_voices():
    """Return the voice registry and supported languages for the frontend."""
    return {"voices": EDGE_VOICES, "languages": SUPPORTED_LANGUAGES}


@app.post("/tts/start")
async def start_tts(background_tasks: BackgroundTasks, request: TTSRequest):
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty")

    engine = (request.engine or "edge").lower().strip()
    if engine not in {"edge", "gtts"}:
        raise HTTPException(status_code=400, detail="Unsupported engine")

    language = (request.language or "vi").lower().strip()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    voice = request.voice.strip() if engine == "edge" else ""
    cache_id = get_cache_id(text, voice, engine)

    if is_cache_valid(cache_id):
        return {"cache_id": cache_id, "status": "completed", "url": f"/tts/file/{cache_id}"}

    current = generation_status.get(cache_id)
    if current and current.get("status") == "processing":
        return {"cache_id": cache_id, "status": "processing"}

    # Clean up stale or incomplete cache before restarting generation
    audio_path = get_audio_path(cache_id)
    meta_path = get_meta_path(cache_id)
    if os.path.exists(audio_path) or os.path.exists(meta_path):
        cleanup_incomplete_cache(cache_id)

    background_tasks.add_task(generate_chunks, text, voice, engine, cache_id, language)
    return {"cache_id": cache_id, "status": "started"}


@app.get("/tts/status/{cache_id}")
async def get_status(cache_id: str):
    status = get_effective_status(cache_id)
    if not status:
        raise HTTPException(status_code=404, detail="Not found")
    return status


@app.get("/tts/file/{cache_id}")
async def get_audio_file(cache_id: str, request: Request):
    """
    Serve only completed, verified cache files.
    Live playback while generating must use /tts/stream/{cache_id}.
    """
    if not is_cache_valid(cache_id):
        status = get_effective_status(cache_id)
        if status and status.get("status") == "processing":
            raise HTTPException(status_code=409, detail="Audio is still being generated. Use /tts/stream for live playback.")
        raise HTTPException(status_code=404, detail="Audio not ready")

    audio_path = get_audio_path(cache_id)
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
        filename=f"{cache_id}.mp3",
    )


@app.get("/tts/stream/{cache_id}")
async def stream_audio_live(cache_id: str):
    """
    True live-streaming endpoint using chunked transfer encoding.
    Sends bytes as soon as they are appended to disk.
    Intended for MediaSource API on the frontend.
    """
    audio_path = get_audio_path(cache_id)

    # Wait a bit for the first chunk to appear, or fail early if generation failed
    for _ in range(150):  # up to 15 seconds
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            break
        st = get_effective_status(cache_id)
        if st and st.get("status") == "failed":
            err = st.get("error", "generation failed")
            raise HTTPException(status_code=503, detail=f"Generation failed: {err}")
        await asyncio.sleep(0.1)
    else:
        st = get_effective_status(cache_id)
        if st and st.get("status") == "failed":
            err = st.get("error", "generation failed")
            raise HTTPException(status_code=503, detail=f"Generation failed: {err}")
        raise HTTPException(status_code=404, detail="Audio not ready")

    async def generate() -> AsyncGenerator[bytes, None]:
        read_size = 64 * 1024
        sent = 0
        stable_completed_checks = 0

        while True:
            if os.path.exists(audio_path):
                cur_size = os.path.getsize(audio_path)
                if cur_size > sent:
                    with open(audio_path, "rb") as f:
                        f.seek(sent)
                        while sent < cur_size:
                            chunk = f.read(min(read_size, cur_size - sent))
                            if not chunk:
                                break
                            sent += len(chunk)
                            yield chunk
                    stable_completed_checks = 0

            st = get_effective_status(cache_id)
            state = st.get("status") if st else None

            if state == "failed":
                break

            if state == "completed":
                expected_size = st.get("file_size") or 0
                if expected_size > 0 and sent >= expected_size:
                    stable_completed_checks += 1
                    if stable_completed_checks >= 2:
                        break
                else:
                    stable_completed_checks = 0

            await asyncio.sleep(0.2)

    return StreamingResponse(
        generate(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
