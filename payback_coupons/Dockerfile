ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip tzdata zbar

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app.py /app/app.py
COPY run.sh /app/run.sh
COPY templates /app/templates
COPY static /app/static

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
