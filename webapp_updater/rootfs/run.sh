#!/usr/bin/with-contenv sh
set -eu

REPOSITORY_URL="https://github.com/Parrrrd/home-assistant-webapps.git"

MANAGED_APPS_REPOSITORY="managed-webapps.json"
MANAGED_APPS_FALLBACK="/managed-apps.json"

SUPERVISOR_URL="http://supervisor"

PENDING_UPDATES="/data/pending-updates"
PENDING_INSTALLS="/data/pending-installs"
PENDING_UPDATE_STATE_DIR="/data/pending-update-state"

LAST_HEAD_FILE="/data/last-github-head"
HISTORY_FILE="/data/update-history.log"

INITIAL_BASELINES="/data/initial-mapping-baselines"
UPDATE_BACKUP_PASSWORD_FILE="/data/update-backup-password"
UPDATE_BACKUP_INDEX="/data/pre-update-backups.json"
AUTO_UPDATE_POLICY_FILE="/data/native-auto-update-policy"
VERSION_CATALOG_FILE="/data/version-catalog.json"
VERSION_STATUS_FILE="/data/version-status.json"
VERSION_HISTORY_REPOSITORY="/data/version-history-repository"
VERSION_CATALOG_LOCK="/data/version-catalog.lock"
VERSION_PINS_FILE="/data/version-pins.json"
ROLLBACK_REQUESTS_DIR="/data/rollback-requests"

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

addon_version_is() {
  local_slug=$1
  expected_version=$2

  app_info=$(
    supervisor_get "/addons/${local_slug}/info" 2>/dev/null ||
      true
  )

  installed_version=$(
    printf '%s' "$app_info" |
      jq -r '.data.version // empty' 2>/dev/null ||
      true
  )

  [ "$installed_version" = "$expected_version" ]
}

pending_update_state_file() {
  local_slug=$1
  printf '%s/%s.json\n' "$PENDING_UPDATE_STATE_DIR" "$local_slug"
}

remember_pending_update() {
  local_slug=$1
  app_name=$2
  from_version=$3
  to_version=$4
  operation=${5:-update}
  restore_backup_slug=${6:-}
  state_file=$(pending_update_state_file "$local_slug")
  state_tmp="${state_file}.new-$$"

  mkdir -p "$PENDING_UPDATE_STATE_DIR"

  jq -n \
    --arg slug "$local_slug" \
    --arg app_name "$app_name" \
    --arg from_version "$from_version" \
    --arg to_version "$to_version" \
    --arg operation "$operation" \
    --arg restore_backup_slug "$restore_backup_slug" \
    --arg created_at "$(now)" \
    '{
      local_slug: $slug,
      app_name: $app_name,
      from_version: $from_version,
      to_version: $to_version,
      created_at: $created_at,
      updated_at: $created_at,
      job_id: "",
      job_status: "backup-confirmed",
      job_stage: "waiting-to-start",
      job_progress: null,
      last_error: "",
      operation: $operation,
      restore_backup_slug: $restore_backup_slug,
      restore_status: (if $restore_backup_slug == "" then "not-requested" else "pending" end)
    }' \
    > "$state_tmp" || {
      rm -f "$state_tmp"
      return 1
    }

  mv "$state_tmp" "$state_file"
}

pending_update_state() {
  local_slug=$1
  state_file=$(pending_update_state_file "$local_slug")

  [ -f "$state_file" ] ||
    return 1

  cat "$state_file"
}

clear_pending_update_state() {
  local_slug=$1
  rm -f "$(pending_update_state_file "$local_slug")"
}

update_pending_job_state() {
  local_slug=$1
  job_id=$2
  job_status=$3
  job_stage=$4
  job_progress=$5
  last_error=$6
  state_file=$(pending_update_state_file "$local_slug")
  state_tmp="${state_file}.new-$$"

  [ -f "$state_file" ] || return 1

  jq \
    --arg job_id "$job_id" \
    --arg status "$job_status" \
    --arg stage "$job_stage" \
    --arg progress "$job_progress" \
    --arg error "$last_error" \
    --arg updated_at "$(now)" \
    '
      .job_id = $job_id
      | .job_status = $status
      | .job_stage = $stage
      | .job_progress = (if $progress == "" then null else ($progress | tonumber? // null) end)
      | .last_error = $error
      | .updated_at = $updated_at
    ' \
    "$state_file" \
    > "$state_tmp" || {
      rm -f "$state_tmp"
      return 1
    }

  mv "$state_tmp" "$state_file"
}

update_pending_restore_state() {
  local_slug=$1
  restore_status=$2
  state_file=$(pending_update_state_file "$local_slug")
  state_tmp="${state_file}.new-$$"
  [ -f "$state_file" ] || return 1
  jq \
    --arg restore_status "$restore_status" \
    --arg updated_at "$(now)" \
    '.restore_status = $restore_status | .updated_at = $updated_at' \
    "$state_file" > "$state_tmp" || {
      rm -f "$state_tmp"
      return 1
    }
  mv "$state_tmp" "$state_file"
}

supervisor_running_update_job() {
  local_slug=$1

  supervisor_get /jobs/info 2>/dev/null |
    jq -r \
      --arg slug "$local_slug" '
        (.data.jobs // .jobs // [])
        | map(
            select(
              (.done // false) != true
              and (.reference // "") == $slug
              and ((.uuid // .job_id // .id // "") | type == "string")
            )
          )
        | first
        | (.uuid // .job_id // .id // empty)
      ' \
      2>/dev/null || true
}

supervisor_job_snapshot() {
  job_id=$1

  supervisor_get "/jobs/${job_id}" 2>/dev/null |
    jq -r '
      (.data // .)
      | [
          (.done // false | tostring),
          (.stage // "unbekannt" | tostring),
          (.progress // "" | tostring),
          ([.errors[]? | (.message // .type // tostring)] | join(" | "))
        ]
      | @tsv
    ' \
      2>/dev/null || true
}

supervisor_start_update() {
  local_slug=$1
  response=$(mktemp)

  status=$(
    curl \
      --silent \
      --show-error \
      --max-time 900 \
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

  SUPERVISOR_UPDATE_JOB_ID=$(
    jq -r '.data.job_id // .job_id // empty' "$response" 2>/dev/null ||
      true
  )
  SUPERVISOR_UPDATE_STATUS=$status
  SUPERVISOR_UPDATE_DETAIL=$(tr '\n' ' ' < "$response" | cut -c1-400)
  rm -f "$response"

  if
    printf '%s\n' "$SUPERVISOR_UPDATE_JOB_ID" |
      grep -Eq '^[A-Za-z0-9_-]+$'
  then
    return 0
  fi

  if
    printf '%s\n' "$status" |
      grep -Eq '^2[0-9][0-9]$'
  then
    return 0
  fi

  return 1
}

supervisor_start_data_restore() {
  local_slug=$1
  backup_slug=$2
  password=$(update_backup_password) || return 1
  response=$(mktemp)
  payload=$(mktemp)
  jq -n \
    --arg addon "$local_slug" \
    --arg password "$password" \
    '{addons:[$addon],folders:[],homeassistant:false,password:$password,background:true}' > "$payload" || {
      rm -f "$response" "$payload"
      return 1
    }
  status=$(curl \
    --silent --show-error --output "$response" --write-out '%{http_code}' \
    --request POST \
    --header "Authorization: Bearer ${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN fehlt}" \
    --header 'Content-Type: application/json' \
    --data "@${payload}" \
    "${SUPERVISOR_URL}/backups/${backup_slug}/restore/partial" || true)
  SUPERVISOR_RESTORE_JOB_ID=$(jq -r '.data.job_id // .job_id // empty' "$response" 2>/dev/null || true)
  SUPERVISOR_RESTORE_STATUS=$status
  SUPERVISOR_RESTORE_DETAIL=$(tr '\n' ' ' < "$response" | cut -c1-400)
  rm -f "$response" "$payload"
  printf '%s\n' "$SUPERVISOR_RESTORE_JOB_ID" | grep -Eq '^[A-Za-z0-9_-]+$'
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

backup_contains_addon() {
  local_slug=$1
  backup_info=$2

  printf '%s' "$backup_info" |
    jq -e \
      --arg addon "$local_slug" '
        (
          [
            ((.data // .).addons // [])[]?
            | if type == "string"
              then .
              else (.slug // empty)
              end
          ]
          | index($addon) != null
        )
        or
        (
          (((.data // .).content // {}).addons // [])
          | index($addon) != null
        )
      ' \
      >/dev/null \
      2>&1
}

create_pre_update_backup() {
  local_slug=$1
  app_name=$2
  from_version=$3
  to_version=$4
  force_new=${5:-false}

  existing_slug=''
  if [ "$force_new" != "true" ]; then
    existing_slug=$(existing_backup_slug "$local_slug" "$from_version" "$to_version")
  fi
  if printf '%s\n' "$existing_slug" | grep -Eq '^[a-zA-Z0-9_-]+$'; then
    existing_info=$(supervisor_get "/backups/${existing_slug}/info" 2>/dev/null || true)
    if backup_contains_addon "$local_slug" "$existing_info"
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
  if ! backup_contains_addon "$local_slug" "$backup_info"
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

version_from_text() {
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
  '
}

catalog_notes_at_commit() {
  history_repository=$1
  commit=$2
  source=$3
  version=$4

  git -C "$history_repository" show "${commit}:${source}/CHANGELOG.md" 2>/dev/null |
    awk -v heading="## ${version} — " '
      index($0, heading) == 1 { collecting=1; next }
      collecting && /^## / { exit }
      collecting { sub(/^[[:space:]]*[-*][[:space:]]*/, ""); if (length($0)) print }
    ' |
    head -n 4 |
    paste -sd ' ' -
}

refresh_version_catalog() {
  remote_head=$1
  mappings_file=$2
  catalog_head=$(jq -r '.head // empty' "$VERSION_CATALOG_FILE" 2>/dev/null || true)

  [ "$catalog_head" = "$remote_head" ] && return 0

  if [ ! -d "$VERSION_HISTORY_REPOSITORY/.git" ]; then
    rm -rf "$VERSION_HISTORY_REPOSITORY"
    if ! git \
      -c credential.helper= \
      -c core.askPass= \
      clone --filter=blob:none --no-checkout "$REPOSITORY_URL" "$VERSION_HISTORY_REPOSITORY" \
      >/dev/null 2>&1
    then
      fail "Versionsverlauf konnte nicht aus GitHub geladen werden."
      return 1
    fi
  elif ! git \
    -C "$VERSION_HISTORY_REPOSITORY" \
    -c credential.helper= \
    -c core.askPass= \
    fetch --filter=blob:none origin main:refs/remotes/origin/main \
    >/dev/null 2>&1
  then
    fail "Versionsverlauf konnte nicht aus GitHub aktualisiert werden."
    return 1
  fi

  catalog_workspace=$(mktemp -d)
  catalog_apps='[]'
  while IFS="$(printf '\t')" read -r source local_folder local_slug bootstrap install_if_missing; do
    [ -n "$source" ] || continue
    commits_file="$catalog_workspace/${local_slug}.commits"
    git -C "$VERSION_HISTORY_REPOSITORY" log \
      --format='%H%x09%cI' origin/main -- "${source}/config.yaml" > "$commits_file" || continue
    versions='[]'
    while IFS="$(printf '\t')" read -r commit committed_at; do
      [ -n "$commit" ] || continue
      config=$(git -C "$VERSION_HISTORY_REPOSITORY" show "${commit}:${source}/config.yaml" 2>/dev/null || true)
      version=$(printf '%s\n' "$config" | version_from_text)
      valid_version "$version" || continue
      if printf '%s' "$versions" | jq -e --arg version "$version" 'any(.[]; .version == $version)' >/dev/null 2>&1; then
        continue
      fi
      if ! git -C "$VERSION_HISTORY_REPOSITORY" cat-file -e "${commit}:${source}/Dockerfile" 2>/dev/null; then
        continue
      fi
      notes=$(catalog_notes_at_commit "$VERSION_HISTORY_REPOSITORY" "$commit" "$source" "$version")
      versions=$(printf '%s' "$versions" | jq \
        --arg version "$version" \
        --arg commit "$commit" \
        --arg committed_at "$committed_at" \
        --arg notes "$notes" \
        '. + [{version:$version, commit:$commit, committed_at:$committed_at, notes:$notes}]') || continue
    done < "$commits_file"
    app_name=$(printf '%s' "$source" | tr '_' ' ')
    catalog_apps=$(printf '%s' "$catalog_apps" | jq \
      --arg source "$source" \
      --arg local_folder "$local_folder" \
      --arg local_slug "$local_slug" \
      --arg name "$app_name" \
      --argjson versions "$versions" \
      '. + [{source:$source, local_folder:$local_folder, local_slug:$local_slug, name:$name, versions:$versions}]') || {
        rm -rf "$catalog_workspace"
        return 1
      }
  done <<EOF
$(jq -r '
  .[]
  | [
      .source,
      .local_folder,
      .local_slug,
      (if .bootstrap == true then "true" else "false" end),
      (if .install_if_missing == true then "true" else "false" end)
    ]
  | @tsv
' "$mappings_file")
EOF

  catalog_new="${VERSION_CATALOG_FILE}.new-$$"
  umask 077
  jq -n \
    --arg head "$remote_head" \
    --arg generated_at "$(now)" \
    --argjson apps "$catalog_apps" \
    '{head:$head, generated_at:$generated_at, apps:$apps}' > "$catalog_new" || {
      rm -f "$catalog_new"
      rm -rf "$catalog_workspace"
      return 1
    }
  mv "$catalog_new" "$VERSION_CATALOG_FILE"
  rm -rf "$catalog_workspace"
  log "Versionsverlauf für $(printf '%s' "$catalog_apps" | jq 'length') WebApps aktualisiert."
}

schedule_version_catalog() {
  remote_head=$1
  catalog_head=$(jq -r '.head // empty' "$VERSION_CATALOG_FILE" 2>/dev/null || true)
  [ "$catalog_head" = "$remote_head" ] && return 0
  if mkdir "$VERSION_CATALOG_LOCK" 2>/dev/null; then
    (
      trap 'rmdir "$VERSION_CATALOG_LOCK" 2>/dev/null || true' EXIT
      refresh_version_catalog "$remote_head" "$MANAGED_APPS_FALLBACK" || true
    ) &
  fi
}

pinned_version() {
  local_slug=$1
  jq -r --arg slug "$local_slug" '.[$slug].version // empty' "$VERSION_PINS_FILE" 2>/dev/null || true
}

pin_version() {
  local_slug=$1
  version=$2
  commit=$3
  pins_new="${VERSION_PINS_FILE}.new-$$"
  pins=$(cat "$VERSION_PINS_FILE" 2>/dev/null || printf '{}')
  printf '%s' "$pins" | jq -e 'type == "object"' >/dev/null 2>&1 || pins='{}'
  umask 077
  printf '%s' "$pins" | jq \
    --arg slug "$local_slug" \
    --arg version "$version" \
    --arg commit "$commit" \
    --arg pinned_at "$(now)" \
    '.[$slug] = {version:$version, commit:$commit, pinned_at:$pinned_at}' > "$pins_new" || {
      rm -f "$pins_new"
      return 1
    }
  mv "$pins_new" "$VERSION_PINS_FILE"
}

unpin_version() {
  local_slug=$1
  pins_new="${VERSION_PINS_FILE}.new-$$"
  pins=$(cat "$VERSION_PINS_FILE" 2>/dev/null || printf '{}')
  printf '%s' "$pins" | jq -e 'type == "object"' >/dev/null 2>&1 || pins='{}'
  printf '%s' "$pins" | jq --arg slug "$local_slug" 'del(.[$slug])' > "$pins_new" || {
    rm -f "$pins_new"
    return 1
  }
  mv "$pins_new" "$VERSION_PINS_FILE"
}

write_version_status() {
  status_apps='[]'
  [ -f "$MANAGED_APPS_FALLBACK" ] || return 0
  while IFS="$(printf '\t')" read -r source local_folder local_slug bootstrap install_if_missing; do
    [ -n "$local_slug" ] || continue
    app_info=$(supervisor_get "/addons/${local_slug}/info" 2>/dev/null || true)
    app_name=$(printf '%s' "$app_info" | jq -r '.data.name // empty' 2>/dev/null || true)
    version=$(printf '%s' "$app_info" | jq -r '.data.version // empty' 2>/dev/null || true)
    latest_version=$(printf '%s' "$app_info" | jq -r '.data.version_latest // empty' 2>/dev/null || true)
    pending=$(pending_update_state "$local_slug" 2>/dev/null || true)
    operation=$(printf '%s' "$pending" | jq -r '.operation // "bereit"' 2>/dev/null || true)
    job_status=$(printf '%s' "$pending" | jq -r '.job_status // empty' 2>/dev/null || true)
    job_stage=$(printf '%s' "$pending" | jq -r '.job_stage // empty' 2>/dev/null || true)
    job_progress=$(printf '%s' "$pending" | jq -r '.job_progress // empty' 2>/dev/null || true)
    error=$(printf '%s' "$pending" | jq -r '.last_error // empty' 2>/dev/null || true)
    pinned=$(pinned_version "$local_slug")
    status_apps=$(printf '%s' "$status_apps" | jq \
      --arg source "$source" \
      --arg slug "$local_slug" \
      --arg name "$app_name" \
      --arg version "$version" \
      --arg latest_version "$latest_version" \
      --arg operation "$operation" \
      --arg job_status "$job_status" \
      --arg job_stage "$job_stage" \
      --arg job_progress "$job_progress" \
      --arg error "$error" \
      --arg pinned_version "$pinned" \
      '. + [{source:$source, local_slug:$slug, name:$name, version:$version, latest_version:$latest_version, operation:$operation, job_status:$job_status, job_stage:$job_stage, job_progress:(if $job_progress == "" then null else ($job_progress | tonumber? // null) end), error:$error, pinned_version:$pinned_version}]') || return 1
  done <<EOF
$(jq -r '.[] | [.source,.local_folder,.local_slug,(if .bootstrap then "true" else "false" end),(if .install_if_missing then "true" else "false" end)] | @tsv' "$MANAGED_APPS_FALLBACK")
EOF
  status_new="${VERSION_STATUS_FILE}.new-$$"
  umask 077
  jq -n --arg generated_at "$(now)" --argjson apps "$status_apps" '{generated_at:$generated_at, apps:$apps}' > "$status_new" || return 1
  mv "$status_new" "$VERSION_STATUS_FILE"
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

  pinned=$(pinned_version "$local_slug")
  if [ -n "$pinned" ] && [ "$incoming_version" != "$pinned" ]; then
    log "${local_folder}: Version ${pinned} ist bewusst angeheftet; GitHub-Stand ${incoming_version} wird erst nach Freigabe wieder verfolgt."
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

mapping_for_local_slug() {
  local_slug=$1
  jq -r --arg slug "$local_slug" '
    .[] | select(.local_slug == $slug)
    | [.source,.local_folder,.local_slug] | @tsv
  ' "$MANAGED_APPS_FALLBACK" 2>/dev/null | head -n 1
}

backup_for_version() {
  local_slug=$1
  version=$2
  jq -r \
    --arg slug "$local_slug" \
    --arg version "$version" \
    '[.[] | select(.addon == $slug and .from_version == $version) | .backup_slug] | last // empty' \
    "$UPDATE_BACKUP_INDEX" 2>/dev/null || true
}

restore_historical_source() {
  source=$1
  local_folder=$2
  commit=$3
  expected_version=$4
  stage="/addons/.webapp-rollback-${local_folder}.new-$$"
  previous="/addons/.webapp-rollback-${local_folder}.previous-$$"
  target="/addons/${local_folder}"
  rm -rf "$stage" "$previous"
  mkdir "$stage"
  if ! git -C "$VERSION_HISTORY_REPOSITORY" archive "${commit}:${source}" | tar -x -C "$stage"; then
    rm -rf "$stage"
    return 1
  fi
  if ! safe_source "$stage" || [ "$(version_from "$stage")" != "$expected_version" ]; then
    rm -rf "$stage"
    return 1
  fi
  [ -d "$target" ] || {
    rm -rf "$stage"
    return 1
  }
  mv "$target" "$previous"
  if ! mv "$stage" "$target"; then
    mv "$previous" "$target" 2>/dev/null || true
    rm -rf "$stage"
    return 1
  fi
  rm -rf "$previous"
}

process_rollback_requests() {
  [ -d "$ROLLBACK_REQUESTS_DIR" ] || return 0
  [ -s "$VERSION_CATALOG_FILE" ] || return 0
  for request_file in "$ROLLBACK_REQUESTS_DIR"/*.json; do
    [ -f "$request_file" ] || continue
    request=$(cat "$request_file" 2>/dev/null || true)
    action=$(printf '%s' "$request" | jq -r '.action // empty' 2>/dev/null || true)
    local_slug=$(printf '%s' "$request" | jq -r '.local_slug // empty' 2>/dev/null || true)
    if ! printf '%s\n' "$local_slug" | grep -Eq '^(local_[a-z0-9][a-z0-9_-]*|webapp_updater)$'; then
      log "Ungültige Wiederherstellungsanfrage wurde verworfen."
      rm -f "$request_file"
      continue
    fi
    if [ "$action" = "follow-latest" ]; then
      if [ -n "$(pending_update_state "$local_slug" 2>/dev/null || true)" ] || \
        [ -n "$(supervisor_running_update_job "$local_slug")" ]; then
        log "${local_slug}: Rückkehr zur neuesten Version wartet auf den laufenden Vorgang."
        continue
      fi
      unpin_version "$local_slug" || {
        log "${local_slug}: Anheftung konnte nicht entfernt werden."
        continue
      }
      rm -f "$LAST_HEAD_FILE" "$request_file"
      log "${local_slug}: folgt wieder der neuesten geprüften GitHub-Version."
      continue
    fi
    if [ "$action" != "rollback" ]; then
      log "${local_slug}: unbekannte Wiederherstellungsanfrage wurde verworfen."
      rm -f "$request_file"
      continue
    fi
    if [ "$local_slug" = "webapp_updater" ]; then
      log "Der Updater kann seine eigene Version nicht über den Supervisor ändern; Anfrage wurde verworfen."
      rm -f "$request_file"
      continue
    fi
    target_version=$(printf '%s' "$request" | jq -r '.version // empty' 2>/dev/null || true)
    restore_data=$(printf '%s' "$request" | jq -r '.restore_data == true' 2>/dev/null || true)
    valid_version "$target_version" || {
      log "${local_slug}: ungültige Zielversion in Wiederherstellungsanfrage."
      rm -f "$request_file"
      continue
    }
    mapping=$(mapping_for_local_slug "$local_slug")
    IFS="$(printf '\t')" read -r source local_folder mapped_slug <<EOF
$mapping
EOF
    if [ -z "$source" ] || [ "$mapped_slug" != "$local_slug" ]; then
      log "${local_slug}: gehört nicht zur verwalteten App-Zuordnung."
      rm -f "$request_file"
      continue
    fi
    catalog_entry=$(jq -c \
      --arg slug "$local_slug" \
      --arg version "$target_version" '
        .apps[] | select(.local_slug == $slug)
        | .versions[] | select(.version == $version)
      ' "$VERSION_CATALOG_FILE" 2>/dev/null | head -n 1 || true)
    commit=$(printf '%s' "$catalog_entry" | jq -r '.commit // empty' 2>/dev/null || true)
    if ! printf '%s\n' "$commit" | grep -Eq '^[0-9a-f]{40}$'; then
      log "${local_slug}: Zielversion ${target_version} wartet auf den geprüften Git-Verlauf."
      continue
    fi
    saved_rollback=$(pending_update_state "$local_slug" 2>/dev/null || true)
    if printf '%s' "$saved_rollback" | jq -e --arg target "$target_version" \
      '.operation == "rollback" and .to_version == $target' >/dev/null 2>&1; then
      queue_update "$local_slug"
      rm -f "$request_file"
      log "${local_slug}: bereits gespeicherte Wiederherstellung nach Neustart wieder aufgenommen."
      continue
    fi
    if [ -n "$saved_rollback" ] || \
      [ -n "$(supervisor_running_update_job "$local_slug")" ]; then
      log "${local_slug}: Wiederherstellung wartet, weil bereits ein Vorgang läuft."
      continue
    fi
    app_info=$(supervisor_get "/addons/${local_slug}/info" 2>/dev/null || true)
    app_name=$(printf '%s' "$app_info" | jq -r '.data.name // empty' 2>/dev/null || true)
    from_version=$(printf '%s' "$app_info" | jq -r '.data.version // empty' 2>/dev/null || true)
    valid_version "$from_version" || {
      log "${local_slug}: installierte Version ist nicht lesbar; Wiederherstellung bleibt gesperrt."
      continue
    }
    if [ "$from_version" = "$target_version" ]; then
      pin_version "$local_slug" "$target_version" "$commit"
      rm -f "$request_file"
      log "${local_slug}: Version ${target_version} war bereits installiert und wurde angeheftet."
      continue
    fi
    restore_backup=''
    if [ "$restore_data" = "true" ]; then
      restore_backup=$(backup_for_version "$local_slug" "$target_version")
      backup_info=$(supervisor_get "/backups/${restore_backup}/info" 2>/dev/null || true)
      if ! printf '%s\n' "$restore_backup" | grep -Eq '^[A-Za-z0-9_-]+$' || ! backup_contains_addon "$local_slug" "$backup_info"; then
        log "${local_slug}: für ${target_version} ist kein geprüfter Datenstand vorhanden; Wiederherstellung bleibt unverändert."
        rm -f "$request_file"
        continue
      fi
    fi
    if ! create_pre_update_backup "$local_slug" "${app_name:-$source}" "$from_version" "$target_version" true; then
      log "${local_slug}: Rollback bleibt wegen fehlendem aktuellen Wiederherstellungspunkt gesperrt."
      continue
    fi
    if ! restore_historical_source "$source" "$local_folder" "$commit" "$target_version"; then
      log "${local_slug}: historischer Quellstand ${target_version} konnte nicht sicher vorbereitet werden."
      rm -f "$request_file"
      continue
    fi
    pin_version "$local_slug" "$target_version" "$commit" || {
      log "${local_slug}: Version konnte nicht angeheftet werden; Quellstand bleibt zur Prüfung stehen."
      continue
    }
    if ! supervisor_post /store/reload >/dev/null; then
      log "${local_slug}: lokaler Store konnte nach der Wiederherstellung nicht neu geladen werden."
      continue
    fi
    remember_pending_update "$local_slug" "${app_name:-$source}" "$from_version" "$target_version" "rollback" "$restore_backup" || {
      log "${local_slug}: Rollback-Zustand konnte nicht gespeichert werden."
      continue
    }
    queue_update "$local_slug"
    rm -f "$request_file"
    log "${local_slug}: Wiederherstellung ${from_version} → ${target_version} ist sicher vorgemerkt."
  done
}

complete_confirmed_update() {
  local_slug=$1
  app_name=$2
  from_version=$3
  to_version=$4

  saved_state=$(pending_update_state "$local_slug" 2>/dev/null || true)
  operation=$(printf '%s' "$saved_state" | jq -r '.operation // "update"' 2>/dev/null || true)
  restore_backup=$(printf '%s' "$saved_state" | jq -r '.restore_backup_slug // empty' 2>/dev/null || true)
  restore_status=$(printf '%s' "$saved_state" | jq -r '.restore_status // "not-requested"' 2>/dev/null || true)

  if [ "$operation" = "rollback" ] && [ -n "$restore_backup" ]; then
    if [ "$restore_status" = "pending" ]; then
      if ! supervisor_start_data_restore "$local_slug" "$restore_backup"; then
        error="HTTP ${SUPERVISOR_RESTORE_STATUS:-unbekannt}: ${SUPERVISOR_RESTORE_DETAIL:-keine Antwort}"
        update_pending_job_state "$local_slug" "" "restore-submission-unconfirmed" "restore-request-failed" "" "$error" || return 1
        update_pending_restore_state "$local_slug" "submission-unconfirmed" || return 1
        log "${local_slug}: Datenwiederherstellung wurde nicht bestätigt (${error}); kein zweiter Auftrag wird gestartet."
        return 1
      fi
      update_pending_job_state "$local_slug" "$SUPERVISOR_RESTORE_JOB_ID" "restoring-data" "restore-started" "" "" || return 1
      update_pending_restore_state "$local_slug" "running" || return 1
      log "${local_slug}: Datenwiederherstellung aus ${restore_backup} läuft als Supervisor-Job ${SUPERVISOR_RESTORE_JOB_ID}."
      return 0
    fi
    if [ "$restore_status" = "running" ]; then
      restore_job=$(printf '%s' "$saved_state" | jq -r '.job_id // empty' 2>/dev/null || true)
      snapshot=$(supervisor_job_snapshot "$restore_job")
      if [ -z "$snapshot" ]; then
        log "${local_slug}: Datenwiederherstellungsjob ist noch nicht lesbar."
        return 0
      fi
      IFS="$(printf '\t')" read -r restore_done restore_stage restore_progress restore_errors <<EOF
$snapshot
EOF
      if [ "$restore_done" != "true" ]; then
        update_pending_job_state "$local_slug" "$restore_job" "restoring-data" "$restore_stage" "$restore_progress" "$restore_errors" || return 1
        return 0
      fi
      if [ -n "$restore_errors" ]; then
        update_pending_job_state "$local_slug" "$restore_job" "restore-failed" "$restore_stage" "$restore_progress" "$restore_errors" || return 1
        update_pending_restore_state "$local_slug" "failed" || return 1
        fail "${local_slug}: Datenwiederherstellung ist fehlgeschlagen: ${restore_errors}"
        return 1
      fi
      update_pending_restore_state "$local_slug" "completed" || return 1
      log "${local_slug}: Datenwiederherstellung ist bestätigt."
      return 0
    fi
    if [ "$restore_status" != "completed" ]; then
      log "${local_slug}: Datenwiederherstellung ist unbestätigt; Vorgang bleibt zur Prüfung vorgemerkt."
      return 0
    fi
  fi

  if ! ensure_addon_started "$local_slug"; then
    fail "${local_slug}: Zielversion ist installiert, die App konnte aber nicht gestartet werden."
    return 1
  fi

  complete_update "$local_slug"
  clear_pending_update_state "$local_slug"
  if [ "$operation" = "rollback" ]; then
    log "${local_slug}: Wiederherstellung ${from_version} → ${to_version} vollständig bestätigt."
  else
    log "${local_slug}: Update ${from_version} → ${to_version} vollständig bestätigt."
  fi
  record_update "$app_name" "$from_version" "$to_version"
  send_iphone_notification "$app_name" "$from_version" "$to_version"
}

monitor_pending_update_job() {
  local_slug=$1
  expected_version=$2
  saved_state=$3
  job_id=$(printf '%s' "$saved_state" | jq -r '.job_id // empty' 2>/dev/null || true)
  job_status=$(printf '%s' "$saved_state" | jq -r '.job_status // "pending"' 2>/dev/null || true)

  if [ "$job_status" = "failed" ]; then
    log "${local_slug}: fehlgeschlagener Supervisor-Updatejob bleibt zur Prüfung vorgemerkt; es wird kein zweiter Job gestartet."
    return 0
  fi

  if [ -z "$job_id" ]; then
    running_job=$(supervisor_running_update_job "$local_slug")
    if printf '%s\n' "$running_job" | grep -Eq '^[A-Za-z0-9_-]+$'; then
      update_pending_job_state "$local_slug" "$running_job" "running" "discovered" "" "" || return 1
      log "${local_slug}: bereits laufender Supervisor-Updatejob ${running_job} übernommen."
      return 10
    fi

    if [ "$job_status" = "submission-unconfirmed" ]; then
      last_error=$(printf '%s' "$saved_state" | jq -r '.last_error // empty' 2>/dev/null || true)
      update_pending_job_state "$local_slug" "" "failed" "request-rejected" "" "${last_error:-Supervisor bestätigte den Updateauftrag nicht.}" || return 1
      log "${local_slug}: Supervisor bestätigte den Updateauftrag nicht; er bleibt zur Prüfung vorgemerkt und blockiert keine weiteren Updates."
      return 0
    fi

    if [ "$job_status" = "submitted" ]; then
      # A missing job ID must never cause an immediate duplicate update.  Keep
      # the verified backup and require a second clean /jobs/info observation
      # before the request may be safely resubmitted.
      update_pending_job_state "$local_slug" "" "submission-unavailable" "no-job" "" "Supervisor meldet keinen laufenden Updatejob." || return 1
      log "${local_slug}: Updateauftrag ohne lesbare Job-ID ist nicht in der Supervisor-Übersicht; prüfe ihn noch einmal vor einer sicheren Wiederaufnahme."
      return 10
    fi

    if [ "$job_status" = "submission-unavailable" ]; then
      log "${local_slug}: Updateauftrag ohne lesbare Job-ID bleibt nach zwei Supervisor-Prüfungen unsichtbar; Auftrag wird sicher erneut eingereiht."
      return 2
    fi

    return 2
  fi

  snapshot=$(supervisor_job_snapshot "$job_id")
  if [ -z "$snapshot" ]; then
    running_job=$(supervisor_running_update_job "$local_slug")
    if printf '%s\n' "$running_job" | grep -Eq '^[A-Za-z0-9_-]+$'; then
      update_pending_job_state "$local_slug" "$running_job" "running" "rediscovered" "" "" || return 1
      log "${local_slug}: nicht lesbaren Supervisor-Updatejob durch laufenden Job ${running_job} ersetzt."
      return 10
    fi

    # A job that is absent both from its detail endpoint and the current job
    # overview is no longer active. Preserve the verified backup and retry on
    # the following cycle; this avoids a permanently stuck queue without ever
    # submitting a duplicate while Supervisor still reports a live job.
    if [ "$job_status" = "job-unavailable" ]; then
      log "${local_slug}: Supervisor-Updatejob ${job_id} ist nicht mehr vorhanden und keine Zielversion ist installiert; Auftrag wird sicher erneut eingereiht."
      return 2
    fi

    update_pending_job_state "$local_slug" "$job_id" "job-unavailable" "unavailable" "" "Supervisor-Job konnte nicht gelesen werden." || return 1
    log "${local_slug}: Supervisor-Updatejob ${job_id} ist momentan nicht lesbar; Warteschlange bleibt erhalten."
    return 10
  fi

  IFS="$(printf '\t')" read -r job_done job_stage job_progress job_errors <<EOF
$snapshot
EOF

  if [ "$job_done" = "true" ] && [ -n "$job_errors" ]; then
    update_pending_job_state "$local_slug" "$job_id" "failed" "$job_stage" "$job_progress" "$job_errors" || return 1
    log "${local_slug}: Supervisor-Updatejob ${job_id} ist in Phase ${job_stage} fehlgeschlagen: ${job_errors}"
    return 0
  fi

  if [ "$job_done" = "true" ]; then
    update_pending_job_state "$local_slug" "$job_id" "finished-awaiting-version" "$job_stage" "$job_progress" "" || return 1
    log "${local_slug}: Supervisor-Updatejob ${job_id} abgeschlossen; bestätige in einem folgenden Prüfzyklus Zielversion ${expected_version}."
    return 10
  fi

  update_pending_job_state "$local_slug" "$job_id" "running" "$job_stage" "$job_progress" "$job_errors" || return 1
  if [ -n "$job_progress" ]; then
    log "${local_slug}: Supervisor-Updatejob ${job_id} läuft (Phase ${job_stage}, Fortschritt ${job_progress}%)."
  else
    log "${local_slug}: Supervisor-Updatejob ${job_id} läuft (Phase ${job_stage})."
  fi
  return 10
}

process_pending_update() {
  local_slug=$1

  if ! addon_is_installed "$local_slug"; then
    fail "${local_slug}: Update vorgemerkt, die App ist jedoch nicht installiert."
    return 1
  fi

  app_info=$(supervisor_get "/addons/${local_slug}/info") || {
    fail "${local_slug}: Versionsinformationen konnten nicht gelesen werden."
    return 1
  }
  app_name=$(printf '%s' "$app_info" | jq -r '.data.name // empty' 2>/dev/null || true)
  [ -n "$app_name" ] || app_name=$local_slug
  from_version=$(printf '%s' "$app_info" | jq -r '.data.version // empty' 2>/dev/null || true)
  available_version=$(printf '%s' "$app_info" | jq -r '.data.version_latest // empty' 2>/dev/null || true)

  if ! valid_version "$from_version"; then
    fail "${local_slug}: installierte Versionsnummer ist ungültig; Update bleibt gesperrt."
    return 1
  fi

  saved_state=$(pending_update_state "$local_slug" 2>/dev/null || true)
  if [ -n "$saved_state" ]; then
    saved_from=$(printf '%s' "$saved_state" | jq -r '.from_version // empty' 2>/dev/null || true)
    to_version=$(printf '%s' "$saved_state" | jq -r '.to_version // empty' 2>/dev/null || true)
    saved_name=$(printf '%s' "$saved_state" | jq -r '.app_name // empty' 2>/dev/null || true)
    if ! valid_version "$saved_from" || ! valid_version "$to_version"; then
      fail "${local_slug}: gespeicherter Updatezustand ist ungültig; Update bleibt gesperrt."
      return 1
    fi
    if [ "$from_version" = "$to_version" ]; then
      complete_confirmed_update "$local_slug" "${saved_name:-$app_name}" "$saved_from" "$to_version"
      return $?
    fi

    if monitor_pending_update_job "$local_slug" "$to_version" "$saved_state"; then
      monitor_result=0
    else
      monitor_result=$?
    fi
    if [ "$monitor_result" -eq 10 ]; then
      return 10
    fi
    if [ "$monitor_result" -ne 2 ]; then
      return "$monitor_result"
    fi
  else
    to_version=$available_version
    if ! valid_version "$to_version"; then
      fail "${local_slug}: Zielversionsnummer ist ungültig; Update bleibt gesperrt."
      return 1
    fi
    if [ "$from_version" = "$to_version" ]; then
      complete_update "$local_slug"
      log "${local_slug}: Zielversion ${to_version} ist bereits installiert; Warteschlange bereinigt."
      return 0
    fi
    if ! create_pre_update_backup "$local_slug" "$app_name" "$from_version" "$to_version"; then
      log "${local_slug}: Update bleibt wegen fehlendem geprüftem Wiederherstellungspunkt gesperrt."
      return 1
    fi
    remember_pending_update "$local_slug" "$app_name" "$from_version" "$to_version" || {
      fail "${local_slug}: Updatezustand konnte nicht persistent vorgemerkt werden."
      return 1
    }
  fi

  # The state is committed before this request. If this container restarts in
  # between, /jobs/info is consulted before another update request is possible.
  if ! supervisor_start_update "$local_slug"; then
    error="HTTP ${SUPERVISOR_UPDATE_STATUS:-unbekannt}: ${SUPERVISOR_UPDATE_DETAIL:-keine Antwort}"
    update_pending_job_state "$local_slug" "${SUPERVISOR_UPDATE_JOB_ID:-}" "submission-unconfirmed" "request-failed" "" "$error" || return 1
    log "${local_slug}: Updateauftrag nicht bestätigt (${error}); kein zweiter Job wird gestartet."
    return 1
  fi

  if printf '%s\n' "${SUPERVISOR_UPDATE_JOB_ID:-}" | grep -Eq '^[A-Za-z0-9_-]+$'; then
    update_pending_job_state "$local_slug" "$SUPERVISOR_UPDATE_JOB_ID" "running" "started" "" "" || return 1
    log "${local_slug}: Supervisor-Updatejob ${SUPERVISOR_UPDATE_JOB_ID} gestartet; Überwachung erfolgt nicht blockierend in den nächsten Prüfzyklen."
    return 11
  fi

  # Home Assistant may complete a foreground store update without retaining a
  # queryable Job object. Verify the installed version immediately instead of
  # treating an accepted request without a job ID as an indefinitely pending
  # background job.
  confirmed_info=$(supervisor_get "/addons/${local_slug}/info" 2>/dev/null || true)
  confirmed_version=$(printf '%s' "$confirmed_info" | jq -r '.data.version // empty' 2>/dev/null || true)
  if [ "$confirmed_version" = "$to_version" ]; then
    complete_confirmed_update "$local_slug" "$app_name" "$from_version" "$to_version"
    return $?
  fi

  update_pending_job_state "$local_slug" "" "failed" "completed-without-target" "" "Supervisor bestätigte den Updateauftrag, aber die Zielversion wurde nicht installiert." || return 1
  log "${local_slug}: Supervisor bestätigte das Update ohne Zielversion ${to_version}; Update bleibt zur Prüfung vorgemerkt."
  return 0
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

  # The catalog only contains commits reachable from main. It is therefore a
  # stable allow-list for UI-selected historic sources, never arbitrary Git
  # revisions supplied by a browser request.
  schedule_version_catalog "$remote_head"
  process_rollback_requests

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
    write_version_status || true
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

    write_version_status || true
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

      if process_pending_update "$local_slug"; then
        update_result=0
      else
        update_result=$?
      fi

      case "$update_result" in
        10|11)
          # A running, submitted or freshly started update owns the Supervisor
          # pipeline. Resume the remaining queue only after the next safe
          # status check.
          write_version_status || true
          return 0
          ;;
        0)
          ;;
        *)
          log "${local_slug}: dieses Update bleibt vorgemerkt; weitere Updates werden trotzdem verarbeitet."
          ;;
      esac
    done < "$PENDING_UPDATES"
  fi

  write_version_status || true
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

rmdir "$VERSION_CATALOG_LOCK" 2>/dev/null || true
python3 /ui_server.py &
log "Versionsoberfläche ist über Port 8160 bereit."

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
