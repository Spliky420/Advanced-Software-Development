FROM python:3.11-slim

WORKDIR /app

# Install the backend packages.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Flask application.
COPY app.py db.py calculations.py review.py llm.py integrations.py provider_references.py multi_agent.py ./

ENV DB_PATH=/data/bills.db
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENV MCP_SERVER_URL=http://host.docker.internal:8071/mcp
ENV RAG_SERVER_URL=http://host.docker.internal:5003
ENV MULTI_AGENT_URL=http://host.docker.internal:5004
ENV MULTI_AGENT_ENABLED=false
ENV OLLAMA_MODEL=qwen2.5:0.5b
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Leave time for the three agents and allow MCP callbacks.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "240", "app:app"]
