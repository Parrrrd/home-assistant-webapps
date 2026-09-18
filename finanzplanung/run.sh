#!/usr/bin/with-contenv bashio
set -e

mkdir -p /share/Finanzen
export FINANZ_DATA_DIR=/data
export PORT=8133

if bashio::config.has_value 'web_password'; then
  export FINANZ_WEB_PASSWORD="$(bashio::config 'web_password')"
else
  export FINANZ_WEB_PASSWORD=""
fi

python /opt/finanzplanung/app/app.py
