#!/usr/bin/with-contenv sh
set -eu

REPOSITORY_URL="https://github.com/Parrrrd/home-assistant-webapps.git"

MANAGED_APPS_REPOSITORY="managed-webapps.json"
MANAGED_APPS_FALLBACK="/managed-apps.json"

SUPERVISOR_URL="http://supervisor"

PENDING_UPDATES="/data/pending-updates"
PENDING_INSTALLS="/data/pending-installs"

LAST_HEAD_FILE="/data/last-github-head"
HISTORY_FILE="/data/update-history.log"

INITIAL_BASELINES="/data/initial-mapping-baselines"
UPDATE_BACKUP_PASSWORD_FILE="/data/update-backup-password"
UPDATE_BACKUP_INDEX="/data/pre-update-backups.json"
AUTO_UPDATE_POLICY_FILE="/data/native-auto-update-policy"

now() {
  date '+%Y-%m-%d %H:%M:%S %Z'
}

log() {
  printf \
    '[WebApp-Updater] %s | %s\n' \
    "$(now)" \
    "$*"
}

fail() {
  log \
    "FEHLER: $*" \
    >&2

  return 1
}

options() {
  cat \
    /data/options.json \
    2>/dev/null ||
    printf '%s' \
      '{"check_interval_minutes":1,"auto_apply_updates":true}'
}

option_number() {
  options |
    jq -er '
      .check_interval_minutes // 1
      | if type == "number"
        then floor
        else error("keine Zahl")
        end
    ' \
      2>/dev/null ||
    printf '1'
}

option_seconds() {
  options |
    jq -er '
      .check_interval_seconds // 20
      | if type == "number"
        then floor
        else error("keine Zahl")
        end
    ' \
      2>/dev/null ||
    printf '20'
}

option_boolean() {
  options |
    jq -er '
      .auto_apply_updates // true
      | if type == "boolean"
        then .
        else error("kein Wahrheitswert")
        end
    ' \
      2>/dev/null ||
    printf 'true'
}

supervisor_post() {
  endpoint=$1
  payload=${2:-\{\}}

  curl \
    --fail \
    --silent \
    --show-error \
    --request POST \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    --header \
      'Content-Type: application/json' \
    --data "$payload" \
    "${SUPERVISOR_URL}${endpoint}"
}

supervisor_post_file() {
  endpoint=$1
  payload_file=$2

  curl \
    --fail \
    --silent \
    --show-error \
    --request POST \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    --header \
      'Content-Type: application/json' \
    --data "@${payload_file}" \
    "${SUPERVISOR_URL}${endpoint}"
}

supervisor_get() {
  endpoint=$1

  curl \
    --fail \
    --silent \
    --show-error \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    "${SUPERVISOR_URL}${endpoint}"
}

supervisor_update() {
  local_slug=$1

  response=$(mktemp)

  status=$(
    curl \
      --silent \
      --show-error \
      --output "$response" \
      --write-out '%{http_code}' \
      --request POST \
      --header \
        "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
      --header \
        'Content-Type: application/json' \
      --data \
        '{"backup":false,"background":false}' \
      "${SUPERVISOR_URL}/store/addons/${local_slug}/update" ||
      true
  )

  if
    printf '%s\n' "$status" |
      grep -Eq '^2[0-9][0-9]$'
  then
    rm -f "$response"
    return 0
  fi

  detail=$(
    tr '\n' ' ' \
      < "$response" |
      cut -c1-400
  )

  rm -f "$response"

  if [ -n "$detail" ]; then
    log \
      "${local_slug}: Home Assistant antwortete beim Update HTTP ${status:-unbekannt}: ${detail}"
  else
    log \
      "${local_slug}: Home Assistant antwortete beim Update HTTP ${status:-unbekannt}."
  fi

  return 1
}

update_backup_password() {
  if [ -s "$UPDATE_BACKUP_PASSWORD_FILE" ]; then
    cat "$UPDATE_BACKUP_PASSWORD_FILE"
    return 0
  fi

  umask 077
  temporary_password_file="${UPDATE_BACKUP_PASSWORD_FILE}.new-$$"
  head -c 48 /dev/urandom | base64 | tr -d '\n' > "$temporary_password_file"
  [ -s "$temporary_password_file" ] || {
    rm -f "$temporary_password_file"
    return 1
  }
  mv "$temporary_password_file" "$UPDATE_BACKUP_PASSWORD_FILE"
  cat "$UPDATE_BACKUP_PASSWORD_FILE"
}

existing_backup_slug() {
  local_slug=$1
  from_version=$2
  to_version=$3

  [ -f "$UPDATE_BACKUP_INDEX" ] || return 0

  jq -r \
    --arg slug "$local_slug" \
    --arg from "$from_version" \
    --arg to "$to_version" \
    '[.[] | select(.addon == $slug and .from_version == $from and .to_version == $to) | .backup_slug] | last // empty' \
    "$UPDATE_BACKUP_INDEX" \
    2>/dev/null || true
}

record_pre_update_backup() {
  local_slug=$1
  app_name=$2
  from_version=$3
  to_version=$4
  backup_slug=$5

  mkdir -p "$(dirname "$UPDATE_BACKUP_INDEX")"
  index_temporary_file="${UPDATE_BACKUP_INDEX}.new-$$"
  existing_index='[]'
  if [ -f "$UPDATE_BACKUP_INDEX" ]; then
    existing_index=$(cat "$UPDATE_BACKUP_INDEX" 2>/dev/null || printf '[]')
  fi
  printf '%s' "$existing_index" | jq -e 'type == "array"' >/dev/null 2>&1 || existing_index='[]'
  printf '%s' "$existing_index" | jq \
    --arg addon "$local_slug" \
    --arg name "$app_name" \
    --arg from "$from_version" \
    --arg to "$to_version" \
    --arg backup "$backup_slug" \
    --arg created "$(now)" \
    '. + [{addon:$addon, app_name:$name, from_version:$from, to_version:$to, backup_slug:$backup, created_at:$created}]' \
    > "$index_temporary_file" || {
      rm -f "$index_temporary_file"
      return 1
    }
  mv "$index_temporary_file" "$UPDATE_BACKUP_INDEX"
}

create_pre_update_backup() {
  local_slug=$1
  app_name=$2
  from_version=$3
  to_version=$4

  existing_slug=$(existing_backup_slug "$local_slug" "$from_version" "$to_version")
  if printf '%s\n' "$existing_slug" | grep -Eq '^[a-zA-Z0-9_-]+$'; then
    existing_info=$(supervisor_get "/backups/${existing_slug}/info" 2>/dev/null || true)
    if printf '%s' "$existing_info" | jq -e \
      --arg addon "$local_slug" \
      '(.data.content.addons // .content.addons // []) | index($addon) != null' \
      >/dev/null 2>&1
    then
      log "${local_slug}: geprüfter Wiederherstellungspunkt ${from_version} → ${to_version} ist bereits vorhanden."
      return 0
    fi
    log "${local_slug}: früherer Wiederherstellungspunkt ist nicht mehr verfügbar; neuer wird erstellt."
  fi

  password=$(update_backup_password) || {
    fail "${local_slug}: Sicherungskennwort konnte nicht erstellt werden."
    return 1
  }
  payload_file=$(mktemp)
  response_file=$(mktemp)
  backup_name="WebApp vor Update – ${app_name} ${from_version} → ${to_version}"
  if ! jq -n \
    --arg name "$backup_name" \
    --arg password "$password" \
    --arg addon "$local_slug" \
    '{name:$name,password:$password,homeassistant:false,addons:[$addon],folders:[],compressed:true,background:false}' \
    > "$payload_file"
  then
    rm -f "$payload_file" "$response_file"
    fail "${local_slug}: Sicherungsauftrag konnte nicht vorbereitet werden."
    return 1
  fi
  if ! supervisor_post_file /backups/new/partial "$payload_file" > "$response_file"; then
    rm -f "$payload_file" "$response_file"
    fail "${local_slug}: Wiederherstellungspunkt konnte nicht erstellt werden; Update bleibt gesperrt."
    return 1
  fi
  backup_slug=$(jq -er '.data.slug // .slug // empty' "$response_file" 2>/dev/null || true)
  rm -f "$payload_file" "$response_file"
  if ! printf '%s\n' "$backup_slug" | grep -Eq '^[a-zA-Z0-9_-]+$'; then
    fail "${local_slug}: Sicherung lieferte keine gültige Kennung; Update bleibt gesperrt."
    return 1
  fi
  backup_info=$(supervisor_get "/backups/${backup_slug}/info") || {
    fail "${local_slug}: Wiederherstellungspunkt konnte nicht geprüft werden; Update bleibt gesperrt."
    return 1
  }
  if ! printf '%s' "$backup_info" | jq -e \
    --arg addon "$local_slug" \
    '(.data.content.addons // .content.addons // []) | index($addon) != null' \
    >/dev/null
  then
    fail "${local_slug}: Sicherung enthält nicht die App-Daten; Update bleibt gesperrt."
    return 1
  fi
  record_pre_update_backup "$local_slug" "$app_name" "$from_version" "$to_version" "$backup_slug" || {
    fail "${local_slug}: Sicherungsindex konnte nicht geschrieben werden; Update bleibt gesperrt."
    return 1
  }
  log "${local_slug}: Wiederherstellungspunkt ${backup_slug} für ${from_version} → ${to_version} geprüft."
}

supervisor_install() {
  local_slug=$1

  response=$(mktemp)

  status=$(
    curl \
      --silent \
      --show-error \
      --output "$response" \
      --write-out '%{http_code}' \
      --request POST \
      --header \
        "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
      --header \
        'Content-Type: application/json' \
      --data \
        '{"background":false}' \
      "${SUPERVISOR_URL}/store/addons/${local_slug}/install" ||
      true
  )

  if
    printf '%s\n' "$status" |
      grep -Eq '^2[0-9][0-9]$'
  then
    rm -f "$response"
    return 0
  fi

  detail=$(
    tr '\n' ' ' \
      < "$response" |
      cut -c1-400
  )

  rm -f "$response"

  if [ -n "$detail" ]; then
    log \
      "${local_slug}: Home Assistant antwortete beim Installieren HTTP ${status:-unbekannt}: ${detail}"
  else
    log \
      "${local_slug}: Home Assistant antwortete beim Installieren HTTP ${status:-unbekannt}."
  fi

  return 1
}

store_addon_available() {
  local_slug=$1

  curl \
    --fail \
    --silent \
    --show-error \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    "${SUPERVISOR_URL}/store/addons/${local_slug}/availability" \
    >/dev/null \
    2>&1
}

homeassistant_get() {
  endpoint=$1

  curl \
    --fail \
    --silent \
    --show-error \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    "${SUPERVISOR_URL}/core/api${endpoint}"
}

homeassistant_post() {
  endpoint=$1
  payload=${2:-\{\}}

  curl \
    --fail \
    --silent \
    --show-error \
    --request POST \
    --header \
      "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    --header \
      'Content-Type: application/json' \
    --data "$payload" \
    "${SUPERVISOR_URL}/core/api${endpoint}"
}

record_update() {
  app_name=$1
  from_version=$2
  to_version=$3

  mkdir -p \
    "$(dirname "$HISTORY_FILE")"

  entry="$(
    now
  ) | ${app_name} | ${from_version} → ${to_version} | installiert"

  printf '%s\n' "$entry" \
    >> "$HISTORY_FILE"

  log \
    "Verlauf: ${entry}"
}

record_install() {
  app_name=$1
  to_version=$2

  mkdir -p \
    "$(dirname "$HISTORY_FILE")"

  entry="$(
    now
  ) | ${app_name} | neu → ${to_version} | installiert"

  printf '%s\n' "$entry" \
    >> "$HISTORY_FILE"

  log \
    "Verlauf: ${entry}"
}

iphone_notification_service() {
  homeassistant_get \
    /services \
    2>/dev/null |
    jq -r '
      [
        .[]
        | select(.domain == "notify")
        | (
            .services
            | keys[]
            | select(test("^mobile_app_"))
          )
      ] as $services

      | (
          (
            $services
            | map(
                select(
                  test("iphone"; "i")
                )
              )
            | .[0]
          )
          // ($services | .[0])
          // empty
        )
    ' \
      2>/dev/null
}

send_iphone_notification() {
  app_name=$1
  from_version=$2
  to_version=$3

  service=$(
    iphone_notification_service ||
      true
  )

  if [ -z "$service" ]; then
    log \
      "${app_name}: keine mobile Home-Assistant-Mitteilung gefunden."

    return 0
  fi

  printf '%s\n' "$service" |
    grep -Eq \
      '^[a-z0-9_]+$' ||
    return 0

  payload=$(
    jq -n \
      --arg title \
        'WebApp aktualisiert' \
      --arg message \
        "${app_name} wurde von ${from_version} auf ${to_version} aktualisiert." \
      '{
        title: $title,
        message: $message
      }'
  )

  homeassistant_post \
    "/services/notify/${service}" \
    "$payload" \
    >/dev/null ||
    log \
      "${app_name}: iPhone-Mitteilung konnte nicht zugestellt werden."
}

send_iphone_install_notification() {
  app_name=$1
  to_version=$2

  service=$(
    iphone_notification_service ||
      true
  )

  if [ -z "$service" ]; then
    log \
      "${app_name}: keine mobile Home-Assistant-Mitteilung gefunden."

    return 0
  fi

  printf '%s\n' "$service" |
    grep -Eq \
      '^[a-z0-9_]+$' ||
    return 0

  payload=$(
    jq -n \
      --arg title \
        'WebApp installiert' \
      --arg message \
        "${app_name} wurde neu in Version ${to_version} installiert." \
      '{
        title: $title,
        message: $message
      }'
  )

  homeassistant_post \
    "/services/notify/${service}" \
    "$payload" \
    >/dev/null ||
    log \
      "${app_name}: iPhone-Mitteilung konnte nicht zugestellt werden."
}

version_from() {
  awk '
    /^[[:space:]]*version:[[:space:]]*/ {
      value=$0
      sub(/^[[:space:]]*version:[[:space:]]*/, "", value)
      sub(/[[:space:]]*#.*/, "", value)
      gsub(/"/, "", value)
      gsub(sprintf("%c", 39), "", value)
      gsub(/\r/, "", value)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      print value
      exit
    }
  ' "$1/config.yaml"
}

valid_version() {
  printf '%s\n' "$1" |
    grep -Eq \
      '^[0-9]+\.[0-9]+\.[0-9]+$'
}

version_is_newer() {
  incoming=$1
  current=$2

  [ -z "$current" ] &&
    return 0

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

  [ -f "$source_dir/config.yaml" ] ||
    return 1

  [ -f "$source_dir/Dockerfile" ] ||
    return 1

  ! find "$source_dir" \
    -type l \
    -print \
    -quit |
    grep -q . ||
    return 1

  ! find "$source_dir" \
    -type f \
    \( \
      -name 'options.json' \
      -o -name 'shopping-list.json' \
      -o -name 'secrets.yaml' \
      -o -name 'secrets.yml' \
      -o -name '*.pem' \
      -o -name '*.key' \
      -o -name '*.p12' \
      -o -name '*.pfx' \
    \) \
    -print \
    -quit |
    grep -q .
}

safe_mapping() {
  source=$1
  local_folder=$2
  local_slug=$3

  printf '%s\n' "$source" |
    grep -Eq \
      '^[a-z0-9][a-z0-9_-]*$' ||
    return 1

  printf '%s\n' "$local_folder" |
    grep -Eq \
      '^[A-Za-z0-9][A-Za-z0-9_-]*$' ||
    return 1

  printf '%s\n' "$local_slug" |
    grep -Eq \
      '^(local_[a-z0-9][a-z0-9_-]*|webapp_updater)$'
}

addon_is_installed() {
  local_slug=$1

  supervisor_get \
    "/addons/${local_slug}/info" \
    2>/dev/null |
    jq -e '
      (.data.installed == true)
      or
      (
        (
          .data.version // ""
        )
        | tostring
        | length
      ) > 0
    ' \
      >/dev/null \
      2>&1
}

ensure_addon_started() {
  local_slug=$1

  app_info=$(
    supervisor_get \
      "/addons/${local_slug}/info"
  ) ||
    return 1

  state=$(
    printf '%s' "$app_info" |
      jq -r \
        '.data.state // "unknown"'
  )

  if [ "$state" = "started" ]; then
    return 0
  fi

  supervisor_post \
    "/addons/${local_slug}/start" \
    '{}' \
    >/dev/null
}

queue_item() {
  queue_file=$1
  local_slug=$2

  mkdir -p \
    "$(dirname "$queue_file")"

  touch \
    "$queue_file"

  grep -Fqx \
    "$local_slug" \
    "$queue_file" \
    2>/dev/null ||
    printf '%s\n' "$local_slug" \
      >> "$queue_file"
}

complete_item() {
  queue_file=$1
  local_slug=$2

  queue_new="${queue_file}.new"

  grep -Fvx \
    "$local_slug" \
    "$queue_file" \
    > "$queue_new" ||
    true

  mv \
    "$queue_new" \
    "$queue_file"
}

queue_update() {
  queue_item \
    "$PENDING_UPDATES" \
    "$1"
}

complete_update() {
  complete_item \
    "$PENDING_UPDATES" \
    "$1"
}

queue_install() {
  queue_item \
    "$PENDING_INSTALLS" \
    "$1"
}

complete_install() {
  complete_item \
    "$PENDING_INSTALLS" \
    "$1"
}

queue_if_installed_version_is_older() {
  source_version=$1
  local_slug=$2

  if ! addon_is_installed "$local_slug"; then
    return 0
  fi

  installed_version=$(
    supervisor_get \
      "/addons/${local_slug}/info" |
      jq -er \
        '.data.version // empty'
  ) ||
    fail \
      "${local_slug}: installierte Version konnte nicht gelesen werden."

  valid_version \
    "$installed_version" ||
    fail \
      "${local_slug}: installierte Versionsnummer ist ungültig."

  if
    version_is_newer \
      "$source_version" \
      "$installed_version"
  then
    queue_update \
      "$local_slug"

    log \
      "${local_slug}: installierte Version ${installed_version} wartet auf ${source_version}."
  fi
}

disable_native_auto_update() {
  local_slug=$1

  supervisor_post \
    "/addons/${local_slug}/options" \
    '{"auto_update":false}' \
    >/dev/null ||
    fail \
      "${local_slug}: Home-Assistant-Auto-Update konnte nicht deaktiviert werden."
}

enforce_native_auto_update_policy() {
  # Native Supervisor auto-updates would skip the verified checkpoint. The
  # bundled mapping covers installed apps immediately after this release.
  [ -f "$MANAGED_APPS_FALLBACK" ] || return 0
  slugs=$(jq -er '.[] | .local_slug' "$MANAGED_APPS_FALLBACK") || {
    fail "Updater-Konfiguration enthält keinen lesbaren lokalen App-Slug."
    return 1
  }
  fingerprint=$(printf '%s\n' "$slugs" | cksum | awk '{print $1 ":" $2}')
  [ "$(cat "$AUTO_UPDATE_POLICY_FILE" 2>/dev/null || true)" = "$fingerprint" ] && return 0
  while IFS= read -r local_slug; do
    [ -n "$local_slug" ] || continue
    printf '%s\n' "$local_slug" | grep -Eq '^(local_[a-z0-9][a-z0-9_-]*|webapp_updater)$' || {
      fail "Ungültiger lokaler App-Slug in der Updater-Konfiguration."
      return 1
    }
    if addon_is_installed "$local_slug"; then
      disable_native_auto_update "$local_slug" || return 1
    fi
  done <<EOF
$slugs
EOF
  umask 077
  policy_temporary_file="${AUTO_UPDATE_POLICY_FILE}.new-$$"
  printf '%s\n' "$fingerprint" > "$policy_temporary_file"
  mv "$policy_temporary_file" "$AUTO_UPDATE_POLICY_FILE"
}

sync_app() {
  source_dir=$1
  source=$2
  local_folder=$3
  local_slug=$4
  bootstrap=${5:-false}
  install_if_missing=${6:-false}

  target="/addons/${local_folder}"

  safe_mapping \
    "$source" \
    "$local_folder" \
    "$local_slug" ||
    fail \
      "Ungültiger App-Eintrag in der Updater-Konfiguration."

  safe_source \
    "$source_dir" ||
    fail \
      "${local_folder}: Quellpaket enthält keine gültige App oder enthält gesperrte Dateien."

  incoming_version=$(
    version_from \
      "$source_dir"
  )

  valid_version \
    "$incoming_version" ||
    fail \
      "${local_folder}: ungültige eingehende Versionsnummer."

  if [ ! -f "$target/config.yaml" ]; then
    if [ -e "$target" ]; then
      fail \
        "${local_folder}: lokaler Zielordner existiert, enthält aber keine gültige App."

      return 1
    fi

    if [ "$install_if_missing" != "true" ]; then
      log \
        "${local_folder}: keine bestehende lokale App gefunden; übersprungen."

      return 0
    fi

    stage="/addons/.webapp-install-${local_folder}.new-$$"

    rm -rf "$stage"

    mkdir "$stage"

    cp -a \
      "$source_dir/." \
      "$stage/"

    if ! safe_source "$stage"; then
      rm -rf "$stage"

      fail \
        "${local_folder}: der kopierte Quellstand für die Erstinstallation ist ungültig."

      return 1
    fi

    if ! mv "$stage" "$target"; then
      rm -rf "$stage"

      fail \
        "${local_folder}: Quellstand für die Erstinstallation konnte nicht übernommen werden."

      return 1
    fi

    log \
      "${local_folder}: Quellstand ${incoming_version} für Erstinstallation übernommen."

    printf '%s\n' \
      "$local_slug" \
      >> /tmp/changed-apps

    queue_install \
      "$local_slug"

    return 0
  fi

  current_version=$(
    version_from \
      "$target"
  )

  if ! valid_version "$current_version"; then
    # A manually altered legacy add-on must not stop updates and checkpoints for
    # every other app. It remains untouched and is reported until its own source
    # receives a later version or it is repaired locally.
    log \
      "FEHLER: ${local_folder}: ungültige lokale Versionsnummer; diese App wurde übersprungen."

    return 0
  fi

  if
    [ "$bootstrap" = "true" ] &&
      [ ! -f "$INITIAL_BASELINES/$source" ]
  then
    mkdir -p \
      "$INITIAL_BASELINES"

    printf '%s\n' \
      "$incoming_version" \
      > "$INITIAL_BASELINES/$source"

    log \
      "${local_folder}: vorhandenen Stand ${incoming_version} als Ausgangsstand registriert; kein Erst-Update."

    if
      ! addon_is_installed "$local_slug" &&
        [ "$install_if_missing" = "true" ]
    then
      queue_install \
        "$local_slug"
    fi

    return 0
  fi

  if [ "$incoming_version" = "$current_version" ]; then
    log \
      "${local_folder}: bereits auf ${incoming_version}."

    if addon_is_installed "$local_slug"; then
      queue_if_installed_version_is_older \
        "$incoming_version" \
        "$local_slug"
    elif [ "$install_if_missing" = "true" ]; then
      queue_install \
        "$local_slug"

      log \
        "${local_folder}: Quellstand vorhanden, Erstinstallation steht noch aus."
    fi

    return 0
  fi

  if
    ! version_is_newer \
      "$incoming_version" \
      "$current_version"
  then
    log \
      "${local_folder}: GitHub-Version ${incoming_version} ist nicht neuer als ${current_version}; übersprungen."

    return 0
  fi

  stage="/addons/.webapp-update-${local_folder}.new-$$"
  backup="/addons/.webapp-update-${local_folder}.previous-$$"

  rm -rf \
    "$stage" \
    "$backup"

  mkdir "$stage"

  cp -a \
    "$source_dir/." \
    "$stage/"

  if ! safe_source "$stage"; then
    rm -rf "$stage"

    fail \
      "${local_folder}: das kopierte Quellpaket ist ungültig."

    return 1
  fi

  mv \
    "$target" \
    "$backup"

  if ! mv "$stage" "$target"; then
    mv \
      "$backup" \
      "$target" ||
      true

    fail \
      "${local_folder}: Quellstand konnte nicht übernommen werden; bisheriger Stand wurde wiederhergestellt."

    return 1
  fi

  rm -rf "$backup"

  log \
    "${local_folder}: Quellstand ${current_version} → ${incoming_version} übernommen."

  printf '%s\n' \
    "$local_slug" \
    >> /tmp/changed-apps

  if addon_is_installed "$local_slug"; then
    queue_update \
      "$local_slug"
  elif [ "$install_if_missing" = "true" ]; then
    queue_install \
      "$local_slug"
  else
    log \
      "${local_folder}: Quellstand wurde aktualisiert, die App ist aber nicht installiert."
  fi
}

sync_all() {
  : > /tmp/changed-apps

  enforce_native_auto_update_policy || return 1

  remote_head=$(
    git \
      -c credential.helper= \
      -c core.askPass= \
      ls-remote \
      "$REPOSITORY_URL" \
      refs/heads/main \
      2>/dev/null |
      awk \
        'NR == 1 { print $1 }'
  )

  printf '%s\n' "$remote_head" |
    grep -Eq \
      '^[0-9a-f]{40}$' ||
    fail \
      "GitHub-Repository konnte nicht geprüft werden."

  previous_head=$(
    cat \
      "$LAST_HEAD_FILE" \
      2>/dev/null ||
      true
  )

  if [ "$remote_head" != "$previous_head" ]; then
    workspace=$(mktemp -d)

    if ! git \
      -c credential.helper= \
      -c core.askPass= \
      clone \
      --depth=1 \
      "$REPOSITORY_URL" \
      "$workspace/repository" \
      >/dev/null \
      2>&1
    then
      rm -rf "$workspace"

      fail \
        "GitHub-Repository konnte nicht geladen werden."

      return 1
    fi

    managed_apps="$workspace/repository/$MANAGED_APPS_REPOSITORY"

    if [ ! -f "$managed_apps" ]; then
      managed_apps="$MANAGED_APPS_FALLBACK"
    fi

    if ! jq -e \
      'type == "array" and length > 0' \
      "$managed_apps" \
      >/dev/null \
      2>&1
    then
      rm -rf "$workspace"

      fail \
        "Updater-Konfiguration ist ungültig."

      return 1
    fi

    mappings="$workspace/mappings.tsv"

    jq -er '
      .[]
      | [
          .source,
          .local_folder,
          .local_slug,
          (
            if .bootstrap == true
            then "true"
            else "false"
            end
          ),
          (
            if .install_if_missing == true
            then "true"
            else "false"
            end
          )
        ]
      | @tsv
    ' \
      "$managed_apps" \
      > "$mappings" ||
      {
        rm -rf "$workspace"

        fail \
          "Updater-Konfiguration enthält keinen lesbaren App-Eintrag."

        return 1
      }

    while
      IFS="$(printf '\t')" \
        read -r \
          source \
          local_folder \
          local_slug \
          bootstrap \
          install_if_missing
    do
      if ! sync_app \
        "$workspace/repository/$source" \
        "$source" \
        "$local_folder" \
        "$local_slug" \
        "$bootstrap" \
        "$install_if_missing"
      then
        rm -rf "$workspace"

        return 1
      fi

      if addon_is_installed "$local_slug"; then
        if ! disable_native_auto_update "$local_slug"; then
          rm -rf "$workspace"

          return 1
        fi
      fi
    done < "$mappings"

    rm -rf "$workspace"

    mkdir -p \
      "$(dirname "$LAST_HEAD_FILE")"

    printf '%s\n' \
      "$remote_head" \
      > "$LAST_HEAD_FILE"
  fi

  if
    [ ! -s /tmp/changed-apps ] &&
      [ ! -s "$PENDING_UPDATES" ] &&
      [ ! -s "$PENDING_INSTALLS" ]
  then
    return 0
  fi

  supervisor_post \
    /store/reload \
    >/dev/null ||
    fail \
      "Home Assistant konnte den lokalen App-Store nicht neu laden."

  if [ "$(option_boolean)" != "true" ]; then
    log \
      "Neue Versionen oder Erstinstallationen sind im lokalen Store sichtbar und warten auf eine manuelle Installation."

    return 0
  fi

  if [ -s "$PENDING_INSTALLS" ]; then
    while
      IFS= read -r local_slug
    do
      [ -n "$local_slug" ] ||
        continue

      if ! addon_is_installed "$local_slug"; then
        if ! store_addon_available "$local_slug"; then
          log \
            "${local_slug}: App ist im Store noch nicht installierbar; Erstinstallation bleibt vorgemerkt."

          continue
        fi

        if ! supervisor_install "$local_slug"; then
          fail \
            "${local_slug}: Erstinstallation konnte nicht gestartet werden; neuer Versuch folgt automatisch."

          return 1
        fi
      fi

      if ! disable_native_auto_update "$local_slug"; then
        return 1
      fi

      if ! ensure_addon_started "$local_slug"; then
        fail \
          "${local_slug}: App wurde installiert, konnte aber noch nicht gestartet werden."

        return 1
      fi

      app_info=$(
        supervisor_get \
          "/addons/${local_slug}/info"
      ) ||
        {
          fail \
            "${local_slug}: Informationen nach der Installation konnten nicht gelesen werden."

          return 1
        }

      app_name=$(
        printf '%s' "$app_info" |
          jq -er \
            '.data.name // empty'
      ) ||
        app_name="$local_slug"

      to_version=$(
        printf '%s' "$app_info" |
          jq -er \
            '.data.version // .data.version_latest // empty'
      ) ||
        to_version='unbekannt'

      complete_install \
        "$local_slug"

      log \
        "${local_slug}: Erstinstallation abgeschlossen."

      record_install \
        "$app_name" \
        "$to_version"

      send_iphone_install_notification \
        "$app_name" \
        "$to_version"
    done < "$PENDING_INSTALLS"
  fi

  if [ -s "$PENDING_UPDATES" ]; then
    while
      IFS= read -r local_slug
    do
      [ -n "$local_slug" ] ||
        continue

      if ! addon_is_installed "$local_slug"; then
        fail \
          "${local_slug}: Update vorgemerkt, die App ist jedoch nicht installiert."

        return 1
      fi

      app_info=$(
        supervisor_get \
          "/addons/${local_slug}/info"
      ) ||
        {
          fail \
            "${local_slug}: Versionsinformationen konnten nicht gelesen werden."

          return 1
        }

      app_name=$(
        printf '%s' "$app_info" |
          jq -er \
            '.data.name // empty'
      ) ||
        app_name="$local_slug"

      from_version=$(
        printf '%s' "$app_info" |
          jq -er \
            '.data.version // empty'
      ) ||
        from_version='unbekannt'

      to_version=$(
        printf '%s' "$app_info" |
          jq -er \
            '.data.version_latest // empty'
      ) ||
        to_version='neue Version'

      valid_version "$from_version" || {
        fail "${local_slug}: installierte Versionsnummer ist ungültig; Update bleibt gesperrt."
        return 1
      }
      valid_version "$to_version" || {
        fail "${local_slug}: Zielversionsnummer ist ungültig; Update bleibt gesperrt."
        return 1
      }
      if ! create_pre_update_backup "$local_slug" "$app_name" "$from_version" "$to_version"; then
        return 1
      fi
      if ! supervisor_update "$local_slug"; then
        fail \
          "${local_slug}: Update konnte nicht gestartet werden; neuer Versuch folgt automatisch."

        return 1
      fi

      complete_update \
        "$local_slug"

      log \
        "${local_slug}: Update gestartet."

      record_update \
        "$app_name" \
        "$from_version" \
        "$to_version"

      send_iphone_notification \
        "$app_name" \
        "$from_version" \
        "$to_version"
    done < "$PENDING_UPDATES"
  fi
}

if [ "${WEBAPP_UPDATER_LIBRARY_MODE:-false}" = "true" ]; then
  return 0 2>/dev/null || exit 0
fi

interval_seconds=$(
  option_seconds
)

[ "$interval_seconds" -ge 15 ] \
  2>/dev/null ||
  interval_seconds=15

[ "$interval_seconds" -le 3600 ] \
  2>/dev/null ||
  interval_seconds=3600

log \
  "Bereit. Prüfung alle ${interval_seconds} Sekunden."

if [ -s "$HISTORY_FILE" ]; then
  log \
    "Letzte installierte Updates:"

  tail \
    -n 30 \
    "$HISTORY_FILE" |
    while
      IFS= read -r entry
    do
      log \
        "Verlauf: ${entry}"
    done
fi

while :; do
  sync_all ||
    true

  sleep \
    "$interval_seconds"
done
