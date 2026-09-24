ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_PREFER_BINARY=1

COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple --timeout 60 --retries 3 -r /tmp/requirements.txt

COPY app /opt/vinted_carsten_erfassung/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/vinted_carsten_erfassung/app
CMD ["/run.sh"]
