FROM python:3.11-slim

WORKDIR /app

# Shared package lives one level up in the build context (repo root).
COPY shared /shared
COPY agent-core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent-core/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
