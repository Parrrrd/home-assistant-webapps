ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app.py /app/app.py
COPY run.sh /app/run.sh
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
