#!/usr/bin/with-contenv bashio
set -e

export JARVIS_GEMINI_API_KEY="$(bashio::config 'gemini_api_key')"
export JARVIS_GEMINI_MODEL="$(bashio::config 'gemini_model')"
export JARVIS_ENABLE_GOOGLE_SEARCH="$(bashio::config 'enable_google_search')"
export JARVIS_TEMPERATURE="$(bashio::config 'temperature')"
export JARVIS_MAX_OUTPUT_TOKENS="$(bashio::config 'max_output_tokens')"
export JARVIS_REQUEST_TIMEOUT_SECONDS="$(bashio::config 'request_timeout_seconds')"
export JARVIS_COOLDOWN_SECONDS_AFTER_ERROR="$(bashio::config 'cooldown_seconds_after_error')"
export JARVIS_MAX_ANSWER_CHARS="$(bashio::config 'max_answer_chars')"
export JARVIS_RETRY_INCOMPLETE_ANSWERS="$(bashio::config 'retry_incomplete_answers')"
export JARVIS_DEFAULT_LOCATION="$(bashio::config 'default_location')"
export JARVIS_SYSTEM_PROMPT="$(bashio::config 'system_prompt')"

if [ -z "$JARVIS_GEMINI_API_KEY" ]; then
  bashio::log.warning "Kein Gemini API-Key gesetzt. Das Add-on startet, /ask liefert aber einen Fehler."
fi

bashio::log.info "Starte Jarvis AI mit Modell: ${JARVIS_GEMINI_MODEL}"
bashio::log.info "Google Search Grounding: ${JARVIS_ENABLE_GOOGLE_SEARCH}"
bashio::log.info "Maximale Antwortlänge: ${JARVIS_MAX_ANSWER_CHARS} Zeichen"
bashio::log.info "Retry bei unvollständiger Antwort: ${JARVIS_RETRY_INCOMPLETE_ANSWERS}"
bashio::log.info "Standardstandort: ${JARVIS_DEFAULT_LOCATION}"
bashio::log.info "System-Prompt aus Konfiguration gesetzt: $([ -n "${JARVIS_SYSTEM_PROMPT}" ] && echo ja || echo nein)"

exec gunicorn \
  --bind 0.0.0.0:8099 \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  app:app
