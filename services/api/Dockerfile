# Build context = repo root (see docker-compose.yml) so we can copy the shared `common` package.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the shared library first (changes least often → better layer caching).
COPY services/common /tmp/common
RUN pip install --no-cache-dir /tmp/common

COPY services/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api/shelfsense_api ./shelfsense_api

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=12 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "shelfsense_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
