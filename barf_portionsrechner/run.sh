#!/usr/bin/with-contenv bashio
set -e

export BARF_DATA_DIR=/data
export PORT=8132

python /opt/barf_portionsrechner/app/app.py
