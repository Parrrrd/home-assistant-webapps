ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24
FROM ${BUILD_FROM}

WORKDIR /app
COPY app /app
COPY rootfs /
RUN chmod a+x /etc/services.d/barfusskompass/run
