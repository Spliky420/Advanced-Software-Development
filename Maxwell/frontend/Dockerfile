FROM python:3.11-slim
WORKDIR /app
COPY shared/index.html ./index.html
COPY shared/styles.css ./styles.css
EXPOSE 80
CMD ["python", "-m", "http.server", "80"]
