FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

# Read by app.py (see its config block). Set here so the image also works when
# run without docker-compose; compose passes the same values through.
ENV OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=qwen2.5:0.5b

CMD ["python", "app.py"]
