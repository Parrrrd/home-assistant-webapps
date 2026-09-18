ARG BUILD_FROM=python:3.12-slim-bookworm
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN set -eux; \
    python --version; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl fonts-liberation; \
    pip install --upgrade pip; \
    pip install --only-binary=:all: --prefer-binary -r /tmp/requirements.txt; \
    python -m playwright install --with-deps chromium; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

COPY rootfs/app /app

EXPOSE 8149
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8149"]
