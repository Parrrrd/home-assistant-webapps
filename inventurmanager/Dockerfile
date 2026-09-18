FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt /app/
RUN set -eux; \
    arch="$(apk --print-arch)"; \
    case "$arch" in \
      x86_64|aarch64|x86) \
        pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
        ;; \
      armv7|armhf) \
        apk add --no-cache --virtual .build-deps gcc musl-dev; \
        pip install --no-cache-dir --prefer-binary -r requirements.txt; \
        apk del .build-deps \
        ;; \
      *) \
        echo "Unsupported architecture: $arch" >&2; exit 1 \
        ;; \
    esac

COPY app /app/app
COPY seed /app/seed
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

CMD ["/app/run.sh"]
