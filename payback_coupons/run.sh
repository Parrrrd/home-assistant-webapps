#!/usr/bin/with-contenv bashio
export DATA_DIR=/data
export PORT=${PORT:-8141}
python3 /app/app.py
