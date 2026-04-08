import os
import io
import json
import hashlib
import asyncio
import re
import sys
import time
import unicodedata
from typing import List, Dict, AsyncGenerator, Optional, Tuple

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import edge_tts
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Windows asyncio patch (suppress benign socket shutdown errors)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Basic directories
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
CACHE_DIR = os.path.join(BASE_DIR, "audio_cache")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Story to Audio Streaming & Caching API")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROXY = os.getenv("PROXY")
ENABLE_DEBUG_TTS = os.getenv("ENABLE_DEBUG_TTS", "").lower() in {"1", "true", "yes"}

if PROXY:
    os.environ["HTTP_PROXY"] = PROXY
    os.environ["HTTPS_PROXY"] = PROXY

# In-memory runtime status (best effort)
generation_status: Dict[str, dict] = {}
_generation_locks: Dict[str, asyncio.Lock] = {}

# ---------------------------------------------------------------------------
# Language & Voice Registry
# ---------------------------------------------------------------------------
EDGE_VOICES: Dict[str, List[Dict[str, str]]] = {
    "vi": [
        {"value": "vi-VN-HoaiMyNeural", "label": "Hoài Mỹ (Nữ)"},
        {"value": "vi-VN-NamMinhNeural", "label": "Nam Minh (Nam)"},
    ],
    "en": [
        {"value": "en-US-AriaNeural", "label": "Aria (Female, US)"},
        {"value": "en-US-GuyNeural", "label": "Guy (Male, US)"},
        {"value": "en-US-JennyNeural", "label": "Jenny (Female, US)"},
        {"value": "en-GB-SoniaNeural", "label": "Sonia (Female, UK)"},
        {"value": "en-GB-RyanNeural", "label": "Ryan (Male, UK)"},
        {"value": "en-AU-NatashaNeural", "label": "Natasha (Female, AU)"},
    ],
    "ja": [
        {"value": "ja-JP-NanamiNeural", "label": "Nanami (女性)"},
        {"value": "ja-JP-KeitaNeural", "label": "Keita (男性)"},
    ],
    "zh": [
        {"value": "zh-CN-XiaoxiaoNeural", "label": "晓晓 (女, 普通话)"},
        {"value": "zh-CN-YunxiNeural", "label": "云希 (男, 普通话)"},
        {"value": "zh-TW-HsiaoChenNeural", "label": "曉臻 (女, 台灣)"},
    ],
    "ko": [
        {"value": "ko-KR-SunHiNeural", "label": "선히 (여성)"},
        {"value": "ko-KR-InJoonNeural", "label": "인준 (남성)"},
    ],
    "fr": [
        {"value": "fr-FR-DeniseNeural", "label": "Denise (Femme, FR)"},
        {"value": "fr-FR-HenriNeural", "label": "Henri (Homme, FR)"},
        {"value": "fr-CA-SylvieNeural", "label": "Sylvie (Femme, CA)"},
    ],
    "de": [
        {"value": "de-DE-KatjaNeural", "label": "Katja (Weiblich)"},
        {"value": "de-DE-ConradNeural", "label": "Conrad (Männlich)"},
    ],
}

GTTS_LANG_MAP: Dict[str, str] = {
    "vi": "vi",
    "en": "en",
    "ja": "ja",
    "zh": "zh-CN",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
}

SUPPORTED_LANGUAGES = list(EDGE_VOICES.keys())
CJK_LANGUAGES = {"ja", "zh", "ko"}

# ---------------------------------------------------------------------------
# Chunking profiles
# ---------------------------------------------------------------------------
# Default profile for languages with spaces (vi/en/fr/de, etc.)
# We start with a very small first chunk (1 sentence / 100 chars) for ultra-fast time-to-first-byte
# then ramp up to avoid having too many chunks overall.
DEFAULT_CHUNK_SIZES = [100, 400, 1000, 2000, 3500]
DEFAULT_HARD_MAX_CHUNK = 3500
DEFAULT_MAX_SENTENCES_PER_CHUNK = [1, 5, 15, 30, 50]

# Smaller, more conservative profile for CJK
# effective_len() counts most CJK chars ~2 units,
# so 50 here ~= ~25 Japanese chars, 200 ~= ~100 Japanese chars, etc.
CJK_CHUNK_SIZES = [50, 200, 600, 1200, 2000]
CJK_HARD_MAX_CHUNK = 2000
CJK_MAX_SENTENCES_PER_CHUNK = [1, 3, 10, 20, 30]

# Sentence regex:
# - Supports . ! ? … 。 ！ ？
# - Allows closing quotes/brackets after sentence end
MULTILANG_SENTENCE_RE = re.compile(
    r'.+?(?:[.!?…。！？]+(?:["\'”’»」』）】]*)|$)',
    re.S,
)

# Paragraph split: blank lines are strong boundaries
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+", re.M)

# Soft clause separators
SOFT_SPLIT_RE = re.compile(r"(?<=[,;:，、；：])")

# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    engine: str = "edge"   # edge | gtts
    language: str = "vi"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def md5_short(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def get_cache_id(text: str, voice: str, engine: str, language: str) -> str:
    """
    Include language in cache_id to avoid collisions, especially for gTTS.
    """
    raw = f"{text}_{voice}_{engine}_{language}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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
    path = get_audio_path(cache_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def remove_meta_file(cache_id: str) -> None:
    path = get_meta_path(cache_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def cleanup_incomplete_cache(cache_id: str) -> None:
    remove_audio_file(cache_id)
    remove_meta_file(cache_id)


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

    return actual_size > 0 and actual_size == expected_size


def get_effective_status(cache_id: str) -> Optional[dict]:
    """
    Return current status: in-memory only for active (queued/processing) jobs,
    disk metadata for terminal (completed/failed) states.
    """
    audio_path = get_audio_path(cache_id)
    file_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0

    # Only use in-memory state for active jobs; terminal states are persisted to disk
    # and removed from generation_status to avoid returning stale data.
    in_mem = generation_status.get(cache_id)
    if in_mem and in_mem.get("status") in {"queued", "processing"}:
        status = dict(in_mem)
        status["file_size"] = file_size
        return status

    meta = load_cache_meta(cache_id)
    if meta:
        status = dict(meta)
        status["file_size"] = file_size
        return status

    if is_cache_valid(cache_id):
        return {
            "status": "completed",
            "progress": 1,
            "total": 1,
            "file_size": file_size,
        }

    return None


def strip_id3v2(data: bytes) -> bytes:
    """
    Remove ID3v2 header so concatenated MP3 frames are cleaner.
    """
    if len(data) >= 10 and data[:3] == b"ID3":
        size = (
            ((data[6] & 0x7F) << 21)
            | ((data[7] & 0x7F) << 14)
            | ((data[8] & 0x7F) << 7)
            | (data[9] & 0x7F)
        )
        return data[size + 10:]
    return data


def normalize_text(text: str) -> str:
    """
    Normalize line endings and trim outer whitespace.
    Do not aggressively NFKC-normalize content to avoid altering TTS reading.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text


def is_cjk_script_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= code <= 0x4DBF   # CJK Extension A
        or 0x3040 <= code <= 0x309F   # Hiragana
        or 0x30A0 <= code <= 0x30FF   # Katakana
        or 0xFF66 <= code <= 0xFF9D   # Halfwidth Katakana
        or 0xAC00 <= code <= 0xD7AF   # Hangul Syllables
        or 0x1100 <= code <= 0x11FF   # Hangul Jamo
    )


def char_weight(ch: str) -> int:
    """
    Weighted length for chunking:
    - newline: 0
    - other whitespace: 1
    - full-width / wide / CJK-like chars: 2
    - others: 1
    """
    if ch in "\r\n":
        return 0
    if ch.isspace():
        return 1

    east = unicodedata.east_asian_width(ch)
    if east in {"W", "F"} or is_cjk_script_char(ch):
        return 2

    return 1


def effective_len(text: str) -> int:
    return sum(char_weight(ch) for ch in (text or ""))


def is_cjk_language(language: str) -> bool:
    return (language or "").lower().strip() in CJK_LANGUAGES


def is_mostly_cjk(text: str, threshold: float = 0.25) -> bool:
    chars = [ch for ch in (text or "") if not ch.isspace()]
    if not chars:
        return False
    cjk_count = sum(1 for ch in chars if is_cjk_script_char(ch))
    return (cjk_count / len(chars)) >= threshold


def get_chunk_profile(language: str, text: str) -> Tuple[List[int], int, List[int]]:
    """
    Choose chunk profile by explicit language first, then fallback to script detection.
    """
    if is_cjk_language(language) or is_mostly_cjk(text):
        return CJK_CHUNK_SIZES, CJK_HARD_MAX_CHUNK, CJK_MAX_SENTENCES_PER_CHUNK
    return DEFAULT_CHUNK_SIZES, DEFAULT_HARD_MAX_CHUNK, DEFAULT_MAX_SENTENCES_PER_CHUNK


def smart_join(left: str, right: str) -> str:
    """
    Join two text pieces without forcing a space for CJK languages.
    """
    left = (left or "").strip()
    right = (right or "").strip()

    if not left:
        return right
    if not right:
        return left

    if left[-1].isspace() or right[0].isspace():
        return left + right

    if is_cjk_script_char(left[-1]) or is_cjk_script_char(right[0]):
        return left + right

    return f"{left} {right}"


def split_paragraphs(text: str) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []
    return [p.strip() for p in PARAGRAPH_SPLIT_RE.split(text) if p.strip()]


def split_sentences_multilang(text: str) -> List[str]:
    """
    Multilingual sentence splitter:
    - Does not rely on spaces after punctuation
    - Supports . ! ? … 。 ！ ？
    """
    text = normalize_text(text)
    if not text:
        return []

    matches = [m.group().strip() for m in MULTILANG_SENTENCE_RE.finditer(text)]
    sentences = [s for s in matches if s]

    if not sentences:
        return [text]

    return sentences


def hard_cut_text(text: str, limit: int) -> List[str]:
    """
    Hard cut by effective length, guaranteed each piece <= limit
    (except extremely pathological cases of single char weight > limit, which won't happen here).
    """
    text = (text or "").strip()
    if not text:
        return []

    pieces: List[str] = []
    current_chars: List[str] = []
    current_weight = 0

    for ch in text:
        w = char_weight(ch)
        if current_chars and current_weight + w > limit:
            piece = "".join(current_chars).strip()
            if piece:
                pieces.append(piece)
            current_chars = [ch]
            current_weight = w
        else:
            current_chars.append(ch)
            current_weight += w

    if current_chars:
        piece = "".join(current_chars).strip()
        if piece:
            pieces.append(piece)

    return pieces


def pack_units_by_limit(units: List[str], limit: int) -> List[str]:
    """
    Greedily pack text units into chunks using effective_len().
    """
    chunks: List[str] = []
    current = ""

    for unit in units:
        unit = (unit or "").strip()
        if not unit:
            continue

        if not current:
            if effective_len(unit) <= limit:
                current = unit
            else:
                chunks.extend(hard_cut_text(unit, limit))
            continue

        candidate = smart_join(current, unit)
        if effective_len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current.strip())
            if effective_len(unit) <= limit:
                current = unit
            else:
                sub = hard_cut_text(unit, limit)
                if sub:
                    chunks.extend(sub[:-1])
                    current = sub[-1]
                else:
                    current = ""

    if current.strip():
        chunks.append(current.strip())

    return chunks


def split_long_text_gently_by_space(text: str, limit: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    if effective_len(text) <= limit:
        return [text]

    # Keep trailing spaces with the token when possible
    tokens = re.findall(r"\S+\s*", text)
    if not tokens:
        return hard_cut_text(text, limit)

    chunks: List[str] = []
    current = ""

    for token in tokens:
        token = token.strip()
        if not token:
            continue

        if not current:
            if effective_len(token) <= limit:
                current = token
            else:
                chunks.extend(hard_cut_text(token, limit))
            continue

        candidate = smart_join(current, token)
        if effective_len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current.strip())
            if effective_len(token) <= limit:
                current = token
            else:
                sub = hard_cut_text(token, limit)
                if sub:
                    chunks.extend(sub[:-1])
                    current = sub[-1]
                else:
                    current = ""

    if current.strip():
        chunks.append(current.strip())

    return chunks


def split_long_text_gently(text: str, limit: int) -> List[str]:
    """
    Split long text by priority:
    1) soft punctuation (comma/semicolon/colon in multiple languages)
    2) whitespace
    3) hard cut by weighted length
    """
    text = (text or "").strip()
    if not text:
        return []

    if effective_len(text) <= limit:
        return [text]

    # Step 1: split by clause delimiters
    parts = [p.strip() for p in SOFT_SPLIT_RE.split(text) if p.strip()]
    if len(parts) > 1:
        packed = pack_units_by_limit(parts, limit)
        final_chunks: List[str] = []
        for ch in packed:
            if effective_len(ch) <= limit:
                final_chunks.append(ch)
            else:
                final_chunks.extend(split_long_text_gently_by_space(ch, limit))
        return [c for c in final_chunks if c]

    # Step 2: split by whitespace
    by_space = split_long_text_gently_by_space(text, limit)
    final_chunks: List[str] = []
    for ch in by_space:
        if effective_len(ch) <= limit:
            final_chunks.append(ch)
        else:
            final_chunks.extend(hard_cut_text(ch, limit))

    return [c for c in final_chunks if c]


def split_text_into_chunks(text: str, language: str = "vi") -> List[str]:
    """
    Language-aware chunking:
    - Split paragraphs first (strong boundary)
    - Use weighted length for CJK
    - Use smaller chunk profile for ja/zh/ko
    - Limit sentence count per chunk to avoid overly long spoken chunks
    """
    text = normalize_text(text)
    if not text:
        return []

    chunk_sizes, hard_max, max_sentences_profile = get_chunk_profile(language, text)
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: List[str] = []
    size_idx = 0
    current = ""
    sentence_count = 0

    for para_idx, para in enumerate(paragraphs):
        sentences = split_sentences_multilang(para)
        if not sentences:
            continue

        normalized_units: List[str] = []
        for sentence in sentences:
            if effective_len(sentence) > hard_max:
                normalized_units.extend(split_long_text_gently(sentence, hard_max))
            else:
                normalized_units.append(sentence)

        if not normalized_units:
            continue

        for unit_idx, unit in enumerate(normalized_units):
            max_len = chunk_sizes[min(size_idx, len(chunk_sizes) - 1)]
            max_sentences = max_sentences_profile[min(size_idx, len(max_sentences_profile) - 1)]

            if not current:
                if effective_len(unit) <= max_len:
                    current = unit
                    sentence_count = 1
                else:
                    sub = split_long_text_gently(unit, max_len)
                    if sub:
                        current = sub[0]
                        sentence_count = 1
                        for rest in sub[1:]:
                            chunks.append(current.strip())
                            size_idx += 1
                            current = rest
                            sentence_count = 1
                    else:
                        current = ""
                        sentence_count = 0
                continue

            # Paragraph boundary join: Always use double newline when merging separate
            # paragraphs into the same chunk to preserve the natural TTS pause.
            if unit_idx == 0:
                candidate = current + "\n\n" + unit
            else:
                candidate = smart_join(current, unit)

            candidate_sentences = sentence_count + 1

            if effective_len(candidate) <= max_len and candidate_sentences <= max_sentences:
                current = candidate
                sentence_count = candidate_sentences
            else:
                chunks.append(current.strip())
                size_idx += 1

                max_len = chunk_sizes[min(size_idx, len(chunk_sizes) - 1)]
                if effective_len(unit) <= max_len:
                    current = unit
                    sentence_count = 1
                else:
                    sub = split_long_text_gently(unit, max_len)
                    if sub:
                        current = sub[0]
                        sentence_count = 1
                        for rest in sub[1:]:
                            chunks.append(current.strip())
                            size_idx += 1
                            current = rest
                            sentence_count = 1
                    else:
                        current = ""
                        sentence_count = 0

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]


def validate_language(language: str) -> str:
    language = (language or "vi").lower().strip()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")
    return language


def validate_engine(engine: str) -> str:
    engine = (engine or "edge").lower().strip()
    if engine not in {"edge", "gtts"}:
        raise HTTPException(status_code=400, detail="Unsupported engine")
    return engine


def validate_voice(language: str, voice: str, engine: str) -> str:
    if engine == "gtts":
        return ""

    available = EDGE_VOICES.get(language, [])
    if not available:
        raise HTTPException(
            status_code=400,
            detail=f"No voices available for selected language: {language}",
        )

    voice = (voice or "").strip()
    valid_voices = {v["value"] for v in available}
    if voice not in valid_voices:
        raise HTTPException(
            status_code=400,
            detail=f"Voice does not belong to selected language: {language}",
        )
    return voice


# ---------------------------------------------------------------------------
# Audio engine helpers
# ---------------------------------------------------------------------------
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
                if any(x in error_type.lower() for x in ("socket", "connection", "timeout")):
                    delay = 3 * (attempt + 1)
                else:
                    delay = 2 * (attempt + 1)
                time.sleep(delay)

    raise last_exc


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------
async def generate_chunks(
    text: str,
    voice: str,
    engine: str,
    cache_id: str,
    language: str = "vi",
    chunks: Optional[List[str]] = None,
):
    if cache_id not in _generation_locks:
        _generation_locks[cache_id] = asyncio.Lock()

    async with _generation_locks[cache_id]:
        audio_path = get_audio_path(cache_id)

        if is_cache_valid(cache_id):
            generation_status[cache_id] = {
                "status": "completed",
                "progress": 1,
                "total": 1,
            }
            return

        # Use pre-computed chunks if provided to avoid duplicate CPU work
        if chunks is None:
            chunks = split_text_into_chunks(text, language=language)
        if not chunks:
            err = "Text must not be empty"
            save_cache_meta(
                cache_id,
                {
                    "status": "failed",
                    "error": err,
                    "text_hash": md5_short(text),
                    "voice": voice,
                    "engine": engine,
                    "language": language,
                },
            )
            # Remove from in-memory so get_effective_status reads persisted terminal state
            generation_status.pop(cache_id, None)
            return

        total = len(chunks)
        generation_status[cache_id] = {
            "status": "processing",
            "progress": 0,
            "total": total,
        }
        save_cache_meta(
            cache_id,
            {
                "status": "processing",
                "progress": 0,
                "total": total,
                "text_hash": md5_short(text),
                "voice": voice,
                "engine": engine,
                "language": language,
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

                # Strip ID3 header from subsequent chunks to reduce concatenation artifacts
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
                        "text_hash": md5_short(text),
                        "voice": voice,
                        "engine": engine,
                        "language": language,
                    },
                )

            final_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
            if final_size <= 0:
                raise RuntimeError("Generated audio file is empty")

            save_cache_meta(
                cache_id,
                {
                    "status": "completed",
                    "progress": total,
                    "total": total,
                    "file_size": final_size,
                    "text_hash": md5_short(text),
                    "voice": voice,
                    "engine": engine,
                    "language": language,
                },
            )
            # Remove from in-memory so get_effective_status reads persisted terminal state
            generation_status.pop(cache_id, None)

        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] generate_chunks engine={engine}: {err}")

            remove_audio_file(cache_id)
            save_cache_meta(
                cache_id,
                {
                    "status": "failed",
                    "error": err,
                    "text_hash": md5_short(text),
                    "voice": voice,
                    "engine": engine,
                    "language": language,
                },
            )
            # Remove from in-memory so get_effective_status reads persisted terminal state
            generation_status.pop(cache_id, None)
        finally:
            _generation_locks.pop(cache_id, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(TEMPLATES_DIR, "index.html")
    if not os.path.exists(path):
        return HTMLResponse(
            content="<h3>Template not found.</h3><p>Please create templates/index.html</p>",
            status_code=200,
        )
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    # Inject voice registry so the frontend needs no /tts/voices API call on load
    voices_json = json.dumps(EDGE_VOICES, ensure_ascii=False)
    html = html.replace(
        "/* __VOICE_REGISTRY_PLACEHOLDER__ */",
        f"voiceRegistry = {voices_json};",
    )
    # Inject default (vi) locale so the first paint needs no locale fetch
    vi_locale_path = os.path.join(STATIC_DIR, "locales", "vi.json")
    if os.path.exists(vi_locale_path):
        with open(vi_locale_path, "r", encoding="utf-8") as lf:
            vi_locale_json = json.dumps(json.load(lf), ensure_ascii=False)
        html = html.replace(
            "/* __LOCALE_VI_PLACEHOLDER__ */",
            f"t = {vi_locale_json}; _injectedLang = 'vi';",
        )
    return HTMLResponse(content=html)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    path_svg = os.path.join(STATIC_DIR, "favicon.svg")
    if os.path.exists(path_svg):
        return FileResponse(path_svg, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="favicon not found")


@app.get("/tts/voices")
async def get_voices():
    return {
        "voices": EDGE_VOICES,
        "languages": SUPPORTED_LANGUAGES,
    }


@app.post("/tts/start")
async def start_tts(background_tasks: BackgroundTasks, request: TTSRequest):
    text = normalize_text(request.text)
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty")

    engine = validate_engine(request.engine)
    language = validate_language(request.language)
    voice = validate_voice(language, request.voice, engine)

    cache_id = get_cache_id(text, voice, engine, language)

    if is_cache_valid(cache_id):
        return {
            "cache_id": cache_id,
            "status": "completed",
            "url": f"/tts/file/{cache_id}",
        }

    # Use get_effective_status (checks both in-memory and persisted state) to avoid
    # a race condition where we clean up a cache that is actively being generated.
    current = get_effective_status(cache_id)
    if current and current.get("status") in {"queued", "processing"}:
        return {
            "cache_id": cache_id,
            "status": current.get("status"),
        }

    # If stale or incomplete cache exists -> clean it before re-generating
    audio_path = get_audio_path(cache_id)
    meta_path = get_meta_path(cache_id)
    if os.path.exists(audio_path) or os.path.exists(meta_path):
        cleanup_incomplete_cache(cache_id)

    # Mark queued immediately to avoid race between requests before background task starts
    chunk_preview = split_text_into_chunks(text, language=language)
    generation_status[cache_id] = {
        "status": "queued",
        "progress": 0,
        "total": len(chunk_preview),
    }
    save_cache_meta(
        cache_id,
        {
            "status": "queued",
            "progress": 0,
            "total": len(chunk_preview),
            "text_hash": md5_short(text),
            "voice": voice,
            "engine": engine,
            "language": language,
        },
    )

    background_tasks.add_task(generate_chunks, text, voice, engine, cache_id, language, chunk_preview)
    return {
        "cache_id": cache_id,
        "status": "started",
        "estimated_chunks": len(chunk_preview),
    }


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
        if status and status.get("status") in {"queued", "processing"}:
            raise HTTPException(
                status_code=409,
                detail="Audio is still being generated. Use /tts/stream for live playback.",
            )
        raise HTTPException(status_code=404, detail="Audio not ready")

    audio_path = get_audio_path(cache_id)
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"{cache_id}.mp3",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@app.get("/tts/stream/{cache_id}")
async def stream_audio_live(cache_id: str):
    """
    True live-streaming endpoint using chunked transfer encoding.
    Sends bytes as soon as they are appended to disk.
    Intended for MediaSource API or audio player on frontend.
    """
    audio_path = get_audio_path(cache_id)

    # Wait for first bytes to appear
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
        if st and st.get("status") in {"queued", "processing", "generating"}:
            raise HTTPException(
                status_code=503,
                detail="Audio is still being generated, retry later.",
                headers={"Retry-After": "5"},
            )
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


# ---------------------------------------------------------------------------
# Optional debug route: inspect chunking result
# Enabled only when ENABLE_DEBUG_TTS=true (not for production use)
# Uses TTSRequest for input; gated to prevent accidental exposure.
# ---------------------------------------------------------------------------
@app.post("/tts/debug/chunks")
async def debug_chunks(request: TTSRequest):
    if not ENABLE_DEBUG_TTS:
        raise HTTPException(status_code=404, detail="Not found")

    text = normalize_text(request.text)
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty")

    language = validate_language(request.language)
    chunk_sizes, hard_max, max_sentences_profile = get_chunk_profile(language, text)
    chunks = split_text_into_chunks(text, language=language)

    return {
        "language": language,
        "chunk_profile": {
            "chunk_sizes": chunk_sizes,
            "hard_max": hard_max,
            "max_sentences_per_chunk": max_sentences_profile,
        },
        "total_chunks": len(chunks),
        "chunks": [
            {
                "index": i + 1,
                "effective_len": effective_len(ch),
                "char_len": len(ch),
                "text": ch,
            }
            for i, ch in enumerate(chunks)
        ],
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"ok": True}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)