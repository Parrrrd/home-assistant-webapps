FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8146
CMD ["/run.sh"]
