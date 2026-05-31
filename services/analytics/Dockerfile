# Build context = repo root. Phase 1: lightweight scaffold (sessions/funnel/conversion in Phase 2).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/common /tmp/common
RUN pip install --no-cache-dir /tmp/common

# Phase 2 will need DB + CSV deps; analytics writes to Postgres.
COPY services/analytics/app ./app

CMD ["python", "-m", "app.main"]
