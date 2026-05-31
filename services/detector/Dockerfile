# Build context = repo root. Phase 1: lightweight scaffold.
# Phase 2 will add CV deps (ultralytics, opencv-python-headless) and bind-mount the CCTV clips.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/common /tmp/common
RUN pip install --no-cache-dir /tmp/common

COPY services/detector/app ./app

CMD ["python", "-m", "app.main"]
