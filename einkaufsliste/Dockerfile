ARG BUILD_VERSION=0.3.62
FROM ghcr.io/home-assistant/base:3.24-2026.06.1
ARG BUILD_VERSION
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="aarch64|amd64"
RUN apk add --no-cache apache2-utils nodejs radicale
WORKDIR /app
COPY app/ /app/
COPY rootfs/ /
RUN chmod a+x /etc/services.d/eigene-einkaufsliste/run /etc/services.d/einkaufsliste-caldav/run
