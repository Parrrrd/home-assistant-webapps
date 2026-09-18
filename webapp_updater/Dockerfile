ARG BUILD_VERSION=0.1.5
FROM ghcr.io/home-assistant/base:3.24-2026.06.1
ARG BUILD_VERSION

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="aarch64|amd64"

RUN apk add --no-cache curl git jq

COPY rootfs /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
