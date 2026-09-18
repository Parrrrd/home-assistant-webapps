#!/usr/bin/with-contenv bashio
set -e

mkdir -p /share/Mounjaro
export MOUNJARO_DATA_DIR=/data
export PORT=8140

if bashio::config.has_value 'weight_sensor'; then
  export MOUNJARO_WEIGHT_SENSOR="$(bashio::config 'weight_sensor')"
else
  export MOUNJARO_WEIGHT_SENSOR="sensor.withings_gewicht_4"
fi

if bashio::config.has_value 'half_life_days'; then
  export MOUNJARO_HALF_LIFE_DAYS="$(bashio::config 'half_life_days')"
else
  export MOUNJARO_HALF_LIFE_DAYS="5"
fi



if bashio::config.has_value 'auto_save_weight'; then
  export MOUNJARO_AUTO_SAVE_WEIGHT="$(bashio::config 'auto_save_weight')"
else
  export MOUNJARO_AUTO_SAVE_WEIGHT="true"
fi

if bashio::config.has_value 'auto_weight_interval_hours'; then
  export MOUNJARO_AUTO_WEIGHT_INTERVAL_HOURS="$(bashio::config 'auto_weight_interval_hours')"
else
  export MOUNJARO_AUTO_WEIGHT_INTERVAL_HOURS="6"
fi

python /opt/mounjaro_tracker/app/app.py
