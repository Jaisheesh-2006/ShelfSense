# Build context = repo root. Detector: YOLO person detection -> detection.created events.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/app/.ultralytics

WORKDIR /app

# OpenCV (headless) still needs these shared libs on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Shared library first (best layer caching).
COPY services/common /tmp/common
RUN pip install --no-cache-dir /tmp/common

COPY services/detector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake the YOLO weights into the image so there's no model download at runtime
# (keeps `docker compose up` working offline / reliably — acceptance-gate friendly).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY services/detector/app ./app

CMD ["python", "-m", "app.main"]
