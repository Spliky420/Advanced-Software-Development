FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rag_pipeline.py rag_http_server.py ./
COPY corpus/ ./corpus/
COPY chroma/ ./chroma/

EXPOSE 5003

ENV OLLAMA_BASE_URL=http://ollama:11434
ENV OLLAMA_MODEL=qwen2.5:0.5b

CMD ["python", "rag_http_server.py"]