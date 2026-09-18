#!/usr/bin/with-contenv bashio
set -e

export KA_DATA_DIR=/data
export PORT=8139
export REPUBLISH_INTERVAL=$(bashio::config 'republish_interval_days' 3)
export AUTO_REPUBLISH=$(bashio::config 'auto_republish' false)
export KA_GOOGLE_DRIVE_IMPORT_ENABLED=$(bashio::config 'google_drive_import_enabled' false)
export KA_GOOGLE_DRIVE_FOLDER_ID=$(bashio::config 'google_drive_folder_id' '')
export KA_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=$(bashio::config 'google_drive_service_account_file' '/share/Kleinanzeigen/google-drive-service-account.json')
export KA_GOOGLE_DRIVE_POLL_SECONDS=$(bashio::config 'google_drive_poll_seconds' 5)
export KA_NOTIFY_SERVICE=$(bashio::config 'notify_service' '')
export KA_PUBLIC_BASE_URL=$(bashio::config 'public_base_url' 'https://kleinanzeigen.Hauptprofil-digital.de')

mkdir -p /data/ads /data/images /data/logs /media/Import/Kleinanzeigen/Fehler /share/Kleinanzeigen

python /opt/kleinanzeigen_manager/app/app.py
