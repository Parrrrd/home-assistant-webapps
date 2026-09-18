#!/usr/bin/env sh
set -eu

archive=${1:?ZIP-Paket fehlt}
package_name=${2:?Paketname fehlt}
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$archive" ]; then
  echo "Kein neues Quellpaket im Codeeingang; nichts zu übernehmen."
  exit 0
fi
if ! printf '%s\n' "$package_name" | grep -Eq '^([a-z][a-z0-9_]*)-([0-9]+\.[0-9]+\.[0-9]+)\.zip$'; then
  echo "Der Name des Quellpakets muss APPNAME-X.Y.Z.zip lauten." >&2
  exit 1
fi
app_directory=$(printf '%s\n' "$package_name" | sed -E 's/^([a-z][a-z0-9_]*)-[0-9]+\.[0-9]+\.[0-9]+\.zip$/\1/')
if [ "$app_directory" = 'webapp_updater' ] || [ ! -f "$repository_root/$app_directory/config.yaml" ] || [ ! -f "$repository_root/$app_directory/Dockerfile" ]; then
  echo "Das Paket bezieht sich nicht auf eine verwaltete WebApp." >&2
  exit 1
fi
if ! unzip -tq "$archive" >/dev/null; then
  echo "Das ZIP enthält kein gültiges Quellpaket." >&2
  exit 1
fi

stage=$(mktemp -d)
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT HUP INT TERM
entries=$(unzip -Z1 "$archive")
entry_count=$(printf '%s\n' "$entries" | sed '/^$/d' | wc -l | tr -d ' ')
if [ "$entry_count" -eq 0 ] || [ "$entry_count" -gt 5000 ] || printf '%s\n' "$entries" | grep -Eq '(^/|(^|/)\.\.(/|$)|^\.git(/|$))'; then
  echo "Das ZIP enthält ungültige Pfade oder zu viele Dateien." >&2
  exit 1
fi
unzip -q "$archive" -d "$stage"
if find "$stage" -type l -print -quit | grep -q . || [ "$(find "$stage" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" -ne 1 ] || [ ! -d "$stage/$app_directory" ]; then
  echo "Das ZIP muss genau den Ordner der betreffenden WebApp enthalten." >&2
  exit 1
fi
if [ ! -f "$stage/$app_directory/config.yaml" ] || [ ! -f "$stage/$app_directory/Dockerfile" ] || [ "$(du -sk "$stage" | cut -f1)" -gt 200000 ]; then
  echo "Das Quellpaket ist unvollständig oder zu groß." >&2
  exit 1
fi

old_version=$(awk '/^version: / { print $2; exit }' "$repository_root/$app_directory/config.yaml" | tr -d '"')
new_version=$(awk '/^version: / { print $2; exit }' "$stage/$app_directory/config.yaml" | tr -d '"')
if ! printf '%s\n' "$new_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || [ "$package_name" != "${app_directory}-${new_version}.zip" ]; then
  echo "Paketname und Versionsnummer müssen übereinstimmen." >&2
  exit 1
fi
if [ "$(printf '%s\n%s\n' "$old_version" "$new_version" | sort -V | tail -n1)" != "$new_version" ] || [ "$old_version" = "$new_version" ]; then
  echo "Paket $new_version wurde übersprungen: Die vorhandene Version ist $old_version."
  exit 0
fi

rm -rf "$repository_root/$app_directory"
cp -a "$stage/$app_directory" "$repository_root/$app_directory"
cd "$repository_root"
sh ./scripts/check-repository-safety.sh
if git diff --quiet -- "$app_directory"; then
  echo "Das Paket enthält keine Änderung."
  exit 0
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'imported=true\nversion=%s\napp_directory=%s\n' "$new_version" "$app_directory" >> "$GITHUB_OUTPUT"
fi
echo "Paket ${app_directory} $new_version ist geprüft und bereit zur Übernahme."
