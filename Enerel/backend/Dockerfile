# Enerel's backend/API microservice (Flask, served by gunicorn).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so pip layer caches independently of source changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unprivileged. UID matches the one the database service chowns /data to.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 5000

# DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL and OLLAMA_EMBED_MODEL are supplied
# by compose.
ENV DB_PATH=/data/library.db \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:0.5b \
    OLLAMA_EMBED_MODEL=nomic-embed-text

# --timeout 120 must stay above llm.py's 60s Ollama timeout; the gunicorn
# default of 30s would kill the worker mid-generation on a slow model. A
# map-reduce summarize call can make several sequential Ollama calls, so a
# short timeout here would kill a legitimate long-document summary too.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
