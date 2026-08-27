FROM python:3.11-slim
WORKDIR /app
# Use Maxwell‑specific homepage (located at Maxwell/frontend/index.html relative to build context)
COPY Maxwell/frontend/index.html ./index.html
# Shared stylesheet lives at shared/styles.css relative to build context (repo root)
COPY shared/styles.css ./styles.css
EXPOSE 80
CMD ["python", "-m", "http.server", "80"]