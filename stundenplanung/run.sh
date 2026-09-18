#!/usr/bin/with-contenv bashio
set -e

mkdir -p /share/Stunden
mkdir -p /share/Stunden/processed
mkdir -p /share/Stunden/debug

export STUNDEN_DATA_DIR=/data
export STUNDEN_IMPORT_DIR=/share/Stunden
export PORT=8134

export STUNDEN_WEB_PASSWORD="$(bashio::config 'web_password')"
export STUNDEN_PARSER_MODE="$(bashio::config 'parser_mode')"
export STUNDEN_AI_PROVIDER="$(bashio::config 'ai_provider')"
export STUNDEN_OLLAMA_URL="$(bashio::config 'ollama_url')"
export STUNDEN_OLLAMA_MODEL="$(bashio::config 'ollama_model')"
export STUNDEN_GEMINI_API_KEY="$(bashio::config 'gemini_api_key')"
export STUNDEN_GEMINI_MODEL="$(bashio::config 'gemini_model')"
export STUNDEN_API_TOKEN="$(bashio::config 'telegram_api_token')"
export STUNDEN_PUSH_NOTIFY_ENABLED="$(bashio::config 'push_notify_on_import')"
export STUNDEN_PUSH_NOTIFY_SERVICE="$(bashio::config 'push_notify_service')"
export STUNDEN_PUSH_NOTIFY_TITLE="$(bashio::config 'push_notify_title')"

python /opt/stundenplanung/app/app.py
