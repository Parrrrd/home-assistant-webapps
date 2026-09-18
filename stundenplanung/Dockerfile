FROM ghcr.io/home-assistant/base:latest

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

COPY app/requirements.txt /tmp/requirements.txt

RUN apk add --no-cache \
      python3 \
      py3-pip \
      tesseract-ocr \
      tesseract-ocr-data-deu \
      tesseract-ocr-data-eng \
      zlib \
      libjpeg-turbo \
      freetype \
      lcms2 \
      openjpeg \
      tiff \
      libwebp \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir --only-binary=Pillow -r /tmp/requirements.txt \
    && rm -rf /root/.cache /tmp/*

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY app /opt/stundenplanung/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/stundenplanung/app
CMD [ "/run.sh" ]
