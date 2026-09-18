ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=0.6.9
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:3.24-2026.06.1

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Node.js is provided by the pinned Alpine base repository. The app has no
# Python/native dependency; npm packages are pure JavaScript and require Node >=18.
RUN apk add --no-cache nodejs npm

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --ignore-scripts --no-audit --no-fund
COPY app/ /app/
COPY rootfs/ /
RUN chmod a+x /etc/services.d/alexa-bring-sync/run
