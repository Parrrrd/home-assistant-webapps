#!/usr/bin/with-contenv bashio
set -e

export WEBAPP_DATA_DIR=/data
export PORT=8139
export REPUBLISH_INTERVAL=$(bashio::config 'republish_interval_days' 3)
export AUTO_REPUBLISH=$(bashio::config 'auto_republish' false)
export WEBAPP_GOOGLE_DRIVE_IMPORT_ENABLED=$(bashio::config 'google_drive_import_enabled' false)
export WEBAPP_GOOGLE_DRIVE_FOLDER_ID=$(bashio::config 'google_drive_folder_id' '')
export WEBAPP_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=$(bashio::config 'google_drive_service_account_file' '/share/Webapp/google-drive-service-account.json')
export WEBAPP_GOOGLE_DRIVE_POLL_SECONDS=$(bashio::config 'google_drive_poll_seconds' 5)
export WEBAPP_NOTIFY_SERVICE=$(bashio::config 'notify_service' '')

mkdir -p /data/ads /data/images /data/logs /media/Import/Webapp/Fehler /share/Webapp

python /opt/webapp_manager/app/app.py
