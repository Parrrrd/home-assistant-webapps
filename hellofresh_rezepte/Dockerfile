FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-data-deu \
      tesseract-ocr-data-eng \
      chromium \
      chromium-chromedriver \
      xvfb \
      x11vnc \
      xdotool \
      git

# Chromium darf nicht als root mit --no-sandbox laufen. Der sichtbare
# HelloFresh-Browser erhält daher einen eigenen, unprivilegierten Benutzer.
RUN adduser -D -h /data/hellofresh-browser hf-browser

# Der sichtbare HelloFresh-Browser wird über noVNC in einem normalen Safari-Tab
# bedient. Damit können Login, MFA und CAPTCHA einmalig vom Nutzer erledigt
# werden; das Chromium-Profil bleibt danach geschützt unter /data erhalten.
RUN git clone --depth=1 https://github.com/novnc/noVNC.git /opt/noVNC \
    && git clone --depth=1 https://github.com/novnc/websockify.git /opt/noVNC/utils/websockify

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: pillow==12.3.0 pypdfium2==5.12.1 \
    && pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt

COPY app /opt/hellofresh_rezepte/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/hellofresh_rezepte/app
CMD [ "/run.sh" ]
