FROM python:3.11-slim

WORKDIR /app

# WeasyPrint (Phase 4, chunk 6) needs its native rendering stack here too —
# agent-core imports jobpilot_shared.graph.prepare_graph at startup
# (main.py's lifespan), which transitively imports the PDF-compile node
# even though agent-core itself never executes it (job-worker does).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    libffi8 shared-mime-info fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Shared package lives one level up in the build context (repo root).
COPY shared /shared
COPY agent-core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent-core/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
