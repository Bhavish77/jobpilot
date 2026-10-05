FROM python:3.11-slim

WORKDIR /app

# WeasyPrint (Phase 4, chunk 6 — resume PDF compile/verify loop) needs its
# native rendering stack; nothing else in this image needs apt at all.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    libffi8 shared-mime-info fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY shared /shared
COPY job-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY job-worker/worker.py .

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
