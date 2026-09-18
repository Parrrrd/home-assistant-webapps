FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

WORKDIR /app

COPY app /app
COPY rootfs /

RUN chmod +x /etc/services.d/amazon_preiswaechter/run \
    && python3 -m compileall -q /app
