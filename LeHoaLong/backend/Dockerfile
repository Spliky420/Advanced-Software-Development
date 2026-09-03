# Le Hoa Long's backend/API microservice -- Goals and Budgeting.
#
# Flask behind gunicorn, listening on 5000 inside the container (published as
# 8061 by compose). Build context is this directory:
#
#   docker build -t lehoalong-backend LeHoaLong/backend
#
# The SQLite file is NOT in this image. It lives on the lehoalong-db-data
# volume, created and seeded by the database service; this container only
# opens it. That is why there is no schema.sql here.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Requirements first, so the pip layer is only rebuilt when dependencies
# change rather than on every source edit.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unprivileged. The UID matches the one the database service chowns /data
# to, so this process can write goals.db and its -journal sibling.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 5000

# Defaults so `docker run` alone produces a working container; compose
# overrides all four. OLLAMA_MODEL is read from the environment and never
# hardcoded in code -- this is the image's fallback, not a code constant.
ENV DB_PATH=/data/goals.db \
    OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:0.5b \
    CORS_ORIGINS=http://localhost:8060,http://127.0.0.1:8060

# --timeout 180 must stay above config.py's OLLAMA_TIMEOUT_SECONDS (120) and
# matches nginx's proxy_read_timeout. The gunicorn default of 30s would kill
# the worker mid-generation on POST /plan or POST /replan.
#
# threads, not extra workers: the request that takes time is a blocking HTTP
# call to Ollama, and threads share one SQLite connection pool per process
# rather than multiplying writers against the same file.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "180", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
