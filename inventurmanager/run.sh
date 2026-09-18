#!/bin/sh
set -e
mkdir -p /data
export PORT="${PORT:-8130}"
exec python /app/app/app.py
