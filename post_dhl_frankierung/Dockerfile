FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

WORKDIR /app
COPY rootfs/app/ /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin

EXPOSE 8151
ENTRYPOINT ["python3", "/app/server.py"]
