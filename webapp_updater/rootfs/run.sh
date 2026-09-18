#!/bin/sh
set -eu

REPOSITORY_URL="https://github.com/Parrrrd/home-assistant-webapps.git"
MANAGED_APPS="/managed-apps.json"
SUPERVISOR_URL="http://supervisor"
PENDING_UPDATES="/data/pending-updates"

log() { echo "[WebApp-Updater] $*"; }
fail() { log "FEHLER: $*" >&2; return 1; }

options() {
  cat /data/options.json 2>/dev/null || printf '%s' '{"check_interval_minutes":5,"auto_apply_updates":true}'
}

option_number() {
  options | jq -er '.check_interval_minutes // 5 | if type == "number" then floor else error("keine Zahl") end' 2>/dev/null || printf '5'
}

option_boolean() {
  options | jq -er '.auto_apply_updates // true | if type == "boolean" then . else error("kein Wahrheitswert") end' 2>/dev/null || printf 'true'
}

supervisor_post() {
  endpoint=$1
  curl --fail --silent --show-error --request POST \
    --header "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    --header 'Content-Type: application/json' \
    --data '{}' "${SUPERVISOR_URL}${endpoint}"
}

version_from() {
  awk '/^version: / { print $2; exit }' "$1/config.yaml"
}

valid_version() {
  printf '%s\n' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'
}

version_is_newer() {
  incoming=$1
  current=$2
  [ -z "$current" ] && return 0
  awk -F. -v incoming="$incoming" -v current="$current" '
    BEGIN {
      split(incoming, i); split(current, c)
      for (part = 1; part <= 3; part++) {
        if ((i[part] + 0) > (c[part] + 0)) exit 0
        if ((i[part] + 0) < (c[part] + 0)) exit 1
      }
      exit 1
    }
  '
}

safe_source() {
  source_dir=$1
  [ -f "$source_dir/config.yaml" ] || return 1
  [ -f "$source_dir/Dockerfile" ] || return 1
  ! find "$source_dir" -type l -print -quit | grep -q . || return 1
  ! find "$source_dir" -type f \( -name 'options.json' -o -name 'shopping-list.json' -o -name 'secrets.yaml' -o -name 'secrets.yml' -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \) -print -quit | grep -q .
}

safe_mapping() {
  source=$1
  local_folder=$2
  local_slug=$3
  printf '%s\n' "$source" | grep -Eq '^[a-z0-9][a-z0-9_-]*$' || return 1
  printf '%s\n' "$local_folder" | grep -Eq '^[a-z0-9][a-z0-9_-]*$' || return 1
  printf '%s\n' "$local_slug" | grep -Eq '^local_[a-z0-9][a-z0-9_-]*$'
}

queue_update() {
  local_slug=$1
  mkdir -p "$(dirname "$PENDING_UPDATES")"
  touch "$PENDING_UPDATES"
  grep -Fqx "$local_slug" "$PENDING_UPDATES" 2>/dev/null || printf '%s\n' "$local_slug" >> "$PENDING_UPDATES"
}

complete_update() {
  local_slug=$1
  pending_new="${PENDING_UPDATES}.new"
  grep -Fvx "$local_slug" "$PENDING_UPDATES" > "$pending_new" || true
  mv "$pending_new" "$PENDING_UPDATES"
}

sync_app() {
  source_dir=$1
  source=$2
  local_folder=$3
  local_slug=$4
  target="/addons/${local_folder}"
  safe_mapping "$source" "$local_folder" "$local_slug" || fail "Ungültiger App-Eintrag in der Updater-Konfiguration."

  [ -f "$target/config.yaml" ] || {
    log "${local_folder}: keine bestehende lokale App gefunden; übersprungen."
    return 0
  }
  safe_source "$source_dir" || fail "${local_folder}: Quellpaket enthält keine gültige App oder enthält gesperrte Dateien."

  incoming_version=$(version_from "$source_dir")
  current_version=$(version_from "$target")
  valid_version "$incoming_version" || fail "${local_folder}: ungültige eingehende Versionsnummer."
  valid_version "$current_version" || fail "${local_folder}: ungültige lokale Versionsnummer."

  if [ "$incoming_version" = "$current_version" ]; then
    log "${local_folder}: bereits auf ${incoming_version}."
    return 0
  fi
  if ! version_is_newer "$incoming_version" "$current_version"; then
    log "${local_folder}: GitHub-Version ${incoming_version} ist nicht neuer als ${current_version}; übersprungen."
    return 0
  fi

  stage="/addons/.webapp-update-${local_folder}.new-$$"
  backup="/addons/.webapp-update-${local_folder}.previous-$$"
  rm -rf "$stage" "$backup"
  mkdir "$stage"
  cp -a "$source_dir/." "$stage/"
  safe_source "$stage" || {
    rm -rf "$stage"
    fail "${local_folder}: das kopierte Quellpaket ist ungültig."
  }

  mv "$target" "$backup"
  if ! mv "$stage" "$target"; then
    mv "$backup" "$target" || true
    fail "${local_folder}: Quellstand konnte nicht übernommen werden; bisheriger Stand wurde wiederhergestellt."
  fi
  rm -rf "$backup"
  log "${local_folder}: Quellstand ${current_version} → ${incoming_version} übernommen."
  printf '%s\n' "$local_slug" >> /tmp/changed-apps
  queue_update "$local_slug"
}

sync_all() {
  workspace=$(mktemp -d)
  if ! git -c credential.helper= -c core.askPass= clone --depth=1 "$REPOSITORY_URL" "$workspace/repository" >/dev/null 2>&1; then
    rm -rf "$workspace"
    fail "GitHub-Repository konnte nicht geladen werden."
  fi
  if ! jq -e 'type == "array" and length > 0' "$MANAGED_APPS" >/dev/null 2>&1; then
    rm -rf "$workspace"
    fail "Updater-Konfiguration ist ungültig."
  fi

  : > /tmp/changed-apps
  mappings="$workspace/mappings.tsv"
  jq -er '.[] | [.source,.local_folder,.local_slug] | @tsv' "$MANAGED_APPS" > "$mappings" || {
    rm -rf "$workspace"
    fail "Updater-Konfiguration enthält keinen lesbaren App-Eintrag."
  }
  while IFS="$(printf '\t')" read -r source local_folder local_slug; do
    sync_app "$workspace/repository/$source" "$source" "$local_folder" "$local_slug" || {
      rm -rf "$workspace"
      return 1
    }
  done < "$mappings"
  rm -rf "$workspace"

  if [ ! -s /tmp/changed-apps ] && [ ! -s "$PENDING_UPDATES" ]; then
    return 0
  fi
  supervisor_post /store/reload >/dev/null || fail "Home Assistant konnte den lokalen App-Store nicht neu laden."

  if [ "$(option_boolean)" != "true" ]; then
    log "Neue Versionen sind im lokalen Store sichtbar und warten auf ein manuelles Update."
    return 0
  fi
  while IFS= read -r local_slug; do
    [ -n "$local_slug" ] || continue
    supervisor_post "/addons/${local_slug}/update" >/dev/null && {
      complete_update "$local_slug"
      log "${local_slug}: Update gestartet."
    } || fail "${local_slug}: Update konnte nicht gestartet werden; neuer Versuch folgt automatisch."
  done < "$PENDING_UPDATES"
}

interval=$(option_number)
[ "$interval" -ge 5 ] 2>/dev/null || interval=5
[ "$interval" -le 1440 ] 2>/dev/null || interval=1440
log "Bereit. Prüfung alle ${interval} Minuten."
while :; do
  sync_all || true
  sleep "$((interval * 60))"
done
