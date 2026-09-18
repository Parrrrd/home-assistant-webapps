ARG BUILD_VERSION
ARG BUILD_ARCH

FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

COPY requirements.txt /app/requirements.txt

# http-ece currently has no wheel on PyPI, but is pure Python. Install it first.
# Everything else (including native dependencies such as cryptography/aiohttp)
# is then forced to install from binary wheels only.
RUN python3 -m pip install --no-cache-dir http-ece==1.2.1 \
    && python3 -m pip install --no-cache-dir --only-binary=:all: -r /app/requirements.txt

COPY server.py /app/server.py
COPY static /app/static
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8142
CMD ["/run.sh"]
