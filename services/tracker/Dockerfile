# Build context = repo root. Phase 1: lightweight scaffold (ByteTrack added in Phase 2).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/common /tmp/common
RUN pip install --no-cache-dir /tmp/common

COPY services/tracker/app ./app

CMD ["python", "-m", "app.main"]
