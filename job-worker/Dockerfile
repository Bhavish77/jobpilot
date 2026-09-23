FROM python:3.11-slim

WORKDIR /app

COPY shared /shared
COPY job-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY job-worker/worker.py .

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
