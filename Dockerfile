FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Cài uv để quản lý dependency từ pyproject.toml
RUN pip install --no-cache-dir --upgrade pip uv

# Copy file dependency trước để tối ưu layer cache
COPY pyproject.toml README.md ./
COPY uv.lock ./

# Đồng bộ dependency (không yêu cầu frozen để tránh fail khi lock chưa đồng bộ 100%)
RUN uv sync --no-dev

# Copy source code
COPY . .

# Đảm bảo thư mục cache tồn tại
RUN mkdir -p /app/audio_cache

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
