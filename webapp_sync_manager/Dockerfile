ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv /app/venv && /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY run /etc/services.d/webapp-sync/run

RUN chmod +x /etc/services.d/webapp-sync/run

ENV PATH="/app/venv/bin:$PATH"
