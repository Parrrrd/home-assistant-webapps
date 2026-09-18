FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /app

COPY app.py /app/app.py
COPY index.html /app/index.html
COPY run.sh /run.sh

RUN chmod a+x /run.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8147/health', timeout=3).read()" || exit 1

CMD [ "/run.sh" ]
