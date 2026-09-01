FROM python:3.11-slim

WORKDIR /app

# Install the backend packages.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Flask application.
COPY app.py db.py calculations.py review.py ./

ENV DB_PATH=/data/bills.db
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "app:app"]
