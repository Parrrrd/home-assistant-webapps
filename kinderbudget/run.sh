#!/usr/bin/with-contenv bashio
set -e

export KINDERBUDGET_DATA_DIR=/data
export PORT=8128

python /opt/kinderbudget/app/app.py
