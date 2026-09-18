ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24
FROM golang:1.24.3-alpine AS uploader-builder
RUN apk add --no-cache git \
    && git clone https://github.com/JakobAIOdev/vinted-product-uploader.git /src/vinted-uploader \
    && cd /src/vinted-uploader \
    && git checkout 69bf4307d701c481239a3e9b3f4220d2075b36df \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/vinted-uploader ./cmd

ARG BUILD_FROM
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
RUN apk add --no-cache chromium xvfb x11vnc pulseaudio pulseaudio-utils ffmpeg git font-noto ttf-freefont \
    && git clone --depth 1 https://github.com/novnc/noVNC.git /opt/noVNC \
    && git clone --depth 1 https://github.com/novnc/websockify.git /opt/noVNC/utils/websockify \
    && pip install --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple --timeout 60 --retries 3 -r /tmp/requirements.txt
COPY app/chromium-master-preferences /etc/chromium/master_preferences
COPY --from=uploader-builder /out/vinted-uploader /opt/vinted-uploader/vinted-uploader

COPY app /opt/vinted_manager/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh /opt/vinted-uploader/vinted-uploader

WORKDIR /opt/vinted_manager/app
CMD [ "/run.sh" ]
