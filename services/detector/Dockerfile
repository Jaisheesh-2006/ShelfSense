# Build context = repo root. Detector: YOLO + ByteTrack -> ENTRY/EXIT behavioural events (JSONL).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/app/.ultralytics

WORKDIR /app

# opencv-python-headless needs libglib2.0-0 (libgthread) but NOT libgl1 — it's built without OpenGL.
# Dropping libgl1 avoids pulling the whole mesa/LLVM GL stack (the bulk of this apt step's download).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Shared library first (best layer caching).
COPY services/common /tmp/common
RUN --mount=type=cache,target=/root/.cache/pip pip install /tmp/common

# CPU-only PyTorch (ADR-0017) — the single biggest BUILD win. We run YOLO + ByteTrack on CPU, so the
# default CUDA build pulls ~2 GB of NVIDIA libs we never use; the CPU wheel is ~200 MB. Installing it
# first (from PyTorch's CPU index) means ultralytics reuses it instead of pulling the GPU build.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Cache mount is a minor convenience for repeat builds; a fresh reviewer run still downloads once.
COPY services/detector/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# ultralytics depends on the FULL opencv-python (needs libGL + X11/libxcb). Replace it with the
# headless build so cv2 imports with only libglib2.0-0 — keeps the image GL/X-free and slim.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip uninstall -y opencv-python opencv-python-headless \
    && pip install opencv-python-headless

# Pre-bake the YOLO weights into the image so there's no model download at runtime
# (keeps `docker compose up` working offline / reliably — acceptance-gate friendly).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY services/detector/app ./app

CMD ["python", "-m", "app.main"]
