#!/usr/bin/env sh
set -eu

archive=${1:?ZIP-Paket fehlt}
package_name=${2:?Paketname fehlt}

repository_root=$(
  CDPATH= cd -- "$(dirname -- "$0")/.." &&
    pwd
)

managed_apps="$repository_root/managed-webapps.json"

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

config_value() {
  key=$1
  file=$2

  awk -F: -v key="$key" '
    $1 == key {
      value = substr(
        $0,
        index($0, ":") + 1
      )

      gsub(
        /^[[:space:]]+|[[:space:]]+$/,
        "",
        value
      )

      gsub(
        /^"|"$/,
        "",
        value
      )

      print value
      exit
    }
  ' "$file"
}

host_ports() {
  sed -n \
    '/^ports:[[:space:]]*$/,/^[^[:space:]]/p' \
    "$1" |
    sed -nE \
      's/^[[:space:]]+[0-9]+\/(tcp|udp):[[:space:]]*([0-9]+)[[:space:]]*$/\2/p'
}

if [ ! -f "$archive" ]; then
  echo \
    "Kein neues Quellpaket im Codeeingang; nichts zu übernehmen."

  exit 0
fi

if ! printf '%s\n' "$package_name" |
  grep -Eq \
    '^([a-z][a-z0-9_]*)-([0-9]+\.[0-9]+\.[0-9]+)\.zip$'
then
  fail \
    "Der Name des Quellpakets muss APPNAME-X.Y.Z.zip lauten."
fi

app_directory=$(
  printf '%s\n' "$package_name" |
    sed -E \
      's/^([a-z][a-z0-9_]*)-[0-9]+\.[0-9]+\.[0-9]+\.zip$/\1/'
)

if [ "$app_directory" = "webapp_updater" ]; then
  fail \
    "Der WebApp-Updater darf nicht über den Codeeingang ersetzt werden."
fi

existing_app=false

if [ -e "$repository_root/$app_directory" ]; then
  if
    [ -f "$repository_root/$app_directory/config.yaml" ] &&
      [ -f "$repository_root/$app_directory/Dockerfile" ]
  then
    existing_app=true
  else
    fail \
      "Der App-Name kollidiert mit einem bereits vorhandenen Repository-Pfad."
  fi
fi

if ! unzip -tq "$archive" >/dev/null; then
  fail \
    "Das ZIP enthält kein gültiges Quellpaket."
fi

stage=$(mktemp -d)

cleanup() {
  rm -rf "$stage"
}

trap cleanup EXIT HUP INT TERM

entries=$(unzip -Z1 "$archive")

entry_count=$(
  printf '%s\n' "$entries" |
    sed '/^$/d' |
    wc -l |
    tr -d ' '
)

if
  [ "$entry_count" -eq 0 ] ||
    [ "$entry_count" -gt 5000 ] ||
    printf '%s\n' "$entries" |
      grep -Eq \
        '(^/|(^|/)\.\.(/|$)|(^|/)\.git(/|$))'
then
  fail \
    "Das ZIP enthält ungültige Pfade oder zu viele Dateien."
fi

unzip -q "$archive" -d "$stage"

if
  find "$stage" \
    -type l \
    -print \
    -quit |
    grep -q . ||
    [ "$(
      find "$stage" \
        -mindepth 1 \
        -maxdepth 1 |
        wc -l |
        tr -d ' '
    )" -ne 1 ] ||
    [ ! -d "$stage/$app_directory" ]
then
  fail \
    "Das ZIP muss genau den Ordner der betreffenden WebApp enthalten."
fi

if
  [ ! -f "$stage/$app_directory/config.yaml" ] ||
    [ ! -f "$stage/$app_directory/Dockerfile" ] ||
    [ "$(
      du -sk "$stage" |
        cut -f1
    )" -gt 200000 ]
then
  fail \
    "Das Quellpaket ist unvollständig oder zu groß."
fi

new_config="$stage/$app_directory/config.yaml"

new_version=$(
  config_value \
    version \
    "$new_config"
)

if
  ! printf '%s\n' "$new_version" |
    grep -Eq \
      '^[0-9]+\.[0-9]+\.[0-9]+$' ||
    [ "$package_name" != "${app_directory}-${new_version}.zip" ]
then
  fail \
    "Paketname und Versionsnummer müssen übereinstimmen."
fi

bootstrap=false

if [ "$existing_app" = "true" ]; then
  old_version=$(
    config_value \
      version \
      "$repository_root/$app_directory/config.yaml"
  )

  if
    [ "$(
      printf '%s\n%s\n' \
        "$old_version" \
        "$new_version" |
        sort -V |
        tail -n1
    )" != "$new_version" ] ||
      [ "$old_version" = "$new_version" ]
  then
    echo \
      "Paket $new_version wurde übersprungen: Die vorhandene Version ist $old_version."

    exit 0
  fi
else
  bootstrap=true

  if [ "$new_version" != "0.1.0" ]; then
    fail \
      "Eine neue WebApp muss mit Version 0.1.0 beginnen."
  fi

  if [ ! -f "$managed_apps" ]; then
    fail \
      "Die zentrale WebApp-Zuordnung managed-webapps.json fehlt."
  fi

  if ! jq -e \
    'type == "array"' \
    "$managed_apps" \
    >/dev/null 2>&1
  then
    fail \
      "Die zentrale WebApp-Zuordnung ist ungültig."
  fi

  slug=$(
    config_value \
      slug \
      "$new_config"
  )

  image=$(
    config_value \
      image \
      "$new_config"
  )

  if [ "$slug" != "$app_directory" ]; then
    fail \
      "Bei einer neuen WebApp müssen Ordnername und slug identisch sein."
  fi

  if
    [ "$image" != "ghcr.io/parrrrd/home-assistant-webapps/$app_directory" ]
  then
    fail \
      "Bei einer neuen WebApp muss image auf den vorgesehenen GHCR-Pfad der App zeigen."
  fi

  architectures=$(
    awk '
      /^arch:[[:space:]]*$/ {
        in_arch = 1
        next
      }

      in_arch &&
      /^[[:space:]]*-[[:space:]]*[A-Za-z0-9_-]+[[:space:]]*$/ {
        line = $0

        sub(
          /^[[:space:]]*-[[:space:]]*/,
          "",
          line
        )

        sub(
          /[[:space:]]*$/,
          "",
          line
        )

        print line
        next
      }

      in_arch &&
      /^[^[:space:]]/ {
        exit
      }
    ' "$new_config"
  )

  if [ -z "$architectures" ]; then
    fail \
      "Die neue WebApp benötigt mindestens eine unterstützte Architektur."
  fi

  if
    printf '%s\n' "$architectures" |
      grep -Ev \
        '^(aarch64|amd64|armhf|armv7|i386)$' |
      grep -q .
  then
    fail \
      "Die neue WebApp enthält eine nicht unterstützte Architektur."
  fi

  webui_port=$(
    sed -nE \
      's/^webui:[[:space:]]*"?http:\/\/\[HOST\]:\[PORT:([0-9]+)\]\/?"?[[:space:]]*$/\1/p' \
      "$new_config" |
      head -n1
  )

  if [ -z "$webui_port" ]; then
    fail \
      "Die neue WebApp benötigt eine direkte webui-Adresse mit festem Port."
  fi

  if
    [ "$webui_port" -lt 1024 ] 2>/dev/null ||
      [ "$webui_port" -gt 65535 ] 2>/dev/null
  then
    fail \
      "Der WebUI-Port der neuen WebApp ist ungültig."
  fi

  incoming_ports=$(
    host_ports \
      "$new_config"
  )

  if [ -z "$incoming_ports" ]; then
    fail \
      "Die neue WebApp benötigt mindestens eine feste Port-Zuordnung."
  fi

  if ! printf '%s\n' "$incoming_ports" |
    grep -Fxq "$webui_port"
  then
    fail \
      "Der WebUI-Port muss in ports als fester Host-Port eingetragen sein."
  fi

  duplicates=$(
    printf '%s\n' "$incoming_ports" |
      sort |
      uniq -d
  )

  if [ -n "$duplicates" ]; then
    fail \
      "Die neue WebApp enthält doppelte Host-Ports."
  fi

  used_ports=$(
    for config in "$repository_root"/*/config.yaml; do
      [ -f "$config" ] ||
        continue

      host_ports \
        "$config"
    done |
      sort -u
  )

  for port in $incoming_ports; do
    if
      printf '%s\n' "$used_ports" |
        grep -Fxq "$port"
    then
      fail \
        "Host-Port $port wird bereits von einer anderen WebApp verwendet."
    fi
  done

  local_slug="local_${app_directory}"

  if jq -e \
    --arg source "$app_directory" \
    --arg folder "$app_directory" \
    --arg slug "$local_slug" \
    '
      .[]
      | select(
          .source == $source
          or .local_folder == $folder
          or .local_slug == $slug
        )
    ' \
    "$managed_apps" \
    >/dev/null
  then
    fail \
      "Für diese neue WebApp existiert bereits eine Updater-Zuordnung."
  fi
fi

if [ "$existing_app" = "true" ]; then
  rm -rf \
    "$repository_root/$app_directory"

  cp -a \
    "$stage/$app_directory" \
    "$repository_root/$app_directory"
else
  cp -a \
    "$stage/$app_directory" \
    "$repository_root/$app_directory"

  registry_tmp=$(mktemp)

  jq \
    --arg source "$app_directory" \
    --arg folder "$app_directory" \
    --arg slug "local_${app_directory}" \
    '
      . + [
        {
          source: $source,
          local_folder: $folder,
          local_slug: $slug,
          install_if_missing: true
        }
      ]
    ' \
    "$managed_apps" \
    > "$registry_tmp"

  mv \
    "$registry_tmp" \
    "$managed_apps"
fi

cd "$repository_root"

sh \
  ./scripts/check-repository-safety.sh

if
  [ -z "$(
    git status \
      --porcelain \
      -- "$app_directory" managed-webapps.json
  )" ]
then
  echo \
    "Das Paket enthält keine Änderung."

  exit 0
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf \
    'imported=true\nversion=%s\napp_directory=%s\nbootstrap=%s\n' \
    "$new_version" \
    "$app_directory" \
    "$bootstrap" \
    >> "$GITHUB_OUTPUT"
fi

if [ "$bootstrap" = "true" ]; then
  echo \
    "Neue WebApp ${app_directory} ${new_version} ist geprüft, registriert und bereit zur Erstaufnahme."
else
  echo \
    "Paket ${app_directory} ${new_version} ist geprüft und bereit zur Übernahme."
fi