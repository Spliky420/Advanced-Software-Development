# Joshua's backend/API microservice (Flask, served by gunicorn).
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

# DB_PATH, OLLAMA_BASE_URL and OLLAMA_MODEL are supplied by compose.
ENV DB_PATH=/data/portfolio.db \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:0.5b

# --timeout 210 must stay above the longest outbound call: the Multi-Agent
# Server client waits up to 190s (multi_agent_client.py), and llm.py's Ollama
# call 60s. gunicorn's default 30s would kill the worker mid-request. The
# frontend nginx proxy_read_timeout (220s) sits above this in turn.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "210", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
