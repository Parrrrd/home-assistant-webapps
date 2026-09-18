#!/usr/bin/env sh
set -eu

archive=${1:?ZIP-Paket fehlt}
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$archive" ]; then
  echo "Kein neues Quellpaket im Codeeingang; nichts zu übernehmen."
  exit 0
fi

stage=$(mktemp -d)
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT HUP INT TERM

entries=$(unzip -Z1 "$archive")
entry_count=$(printf '%s\n' "$entries" | sed '/^$/d' | wc -l | tr -d ' ')
if [ "$entry_count" -eq 0 ] || [ "$entry_count" -gt 5000 ]; then
  echo "Das ZIP enthält keine gültige oder zu viele Dateien." >&2
  exit 1
fi
if printf '%s\n' "$entries" | grep -Eq '(^/|(^|/)\.\.(/|$)|^\.git(/|$))'; then
  echo "Das ZIP enthält einen unzulässigen Pfad." >&2
  exit 1
fi

unzip -q "$archive" -d "$stage"
if find "$stage" -type l -print -quit | grep -q .; then
  echo "Symbolische Links sind im Quellpaket nicht erlaubt." >&2
  exit 1
fi
if [ "$(find "$stage" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" -ne 1 ] || [ ! -d "$stage/einkaufsliste" ]; then
  echo "Das ZIP muss genau den Ordner einkaufsliste enthalten." >&2
  exit 1
fi
if [ ! -f "$stage/einkaufsliste/config.yaml" ] || [ ! -f "$stage/einkaufsliste/package.json" ]; then
  echo "Dem Quellpaket fehlen config.yaml oder package.json." >&2
  exit 1
fi
if [ "$(du -sk "$stage" | cut -f1)" -gt 200000 ]; then
  echo "Das entpackte Quellpaket ist größer als 200 MB." >&2
  exit 1
fi

old_version=$(awk '/^version: / { print $2; exit }' "$repository_root/einkaufsliste/config.yaml")
new_version=$(awk '/^version: / { print $2; exit }' "$stage/einkaufsliste/config.yaml")
if ! printf '%s\n' "$new_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "Die neue Versionsnummer ist ungültig." >&2
  exit 1
fi
if [ "$(printf '%s\n%s\n' "$old_version" "$new_version" | sort -V | tail -n1)" != "$new_version" ] || [ "$old_version" = "$new_version" ]; then
  echo "Paket $new_version wurde übersprungen: Die vorhandene Version ist $old_version." 
  exit 0
fi

rm -rf "$repository_root/einkaufsliste"
cp -a "$stage/einkaufsliste" "$repository_root/einkaufsliste"
cd "$repository_root"
sh ./scripts/check-repository-safety.sh

if git diff --quiet -- einkaufsliste; then
  echo "Das Paket enthält keine Änderung." 
  exit 0
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'imported=true\nversion=%s\n' "$new_version" >> "$GITHUB_OUTPUT"
fi
echo "Paket $new_version ist geprüft und bereit zur Übernahme."
