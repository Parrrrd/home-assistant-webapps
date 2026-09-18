#!/usr/bin/env sh
set -eu

patch_file=${1:?Text-Patch fehlt}
package_name=${2:?Patchname fehlt}
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$patch_file" ]; then
  echo "Kein Text-Patch im Codeeingang; nichts zu übernehmen."
  exit 0
fi

# Normale Chats liefern Textdateien häufig mit BOM, Windows-Zeilenenden oder
# ohne abschließenden Zeilenumbruch. Git-Patches bleiben dabei inhaltlich gleich.
normalized_patch=$(mktemp)
trap 'rm -f "$normalized_patch"' EXIT HUP INT TERM
node - "$patch_file" "$normalized_patch" <<'NODE'
const fs = require('node:fs');
const [source, destination] = process.argv.slice(2);
let text = fs.readFileSync(source, 'utf8');
text = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
if (!text.endsWith('\n')) text += '\n';
fs.writeFileSync(destination, text, { mode: 0o600 });
NODE
patch_file=$normalized_patch

if ! printf '%s\n' "$package_name" | grep -Eq '^([a-z][a-z0-9_]*)-([0-9]+\.[0-9]+\.[0-9]+)\.patch$'; then
  echo "Der Patchname muss APPNAME-X.Y.Z.patch lauten." >&2
  exit 1
fi
app_directory=$(printf '%s\n' "$package_name" | sed -E 's/^([a-z][a-z0-9_]*)-[0-9]+\.[0-9]+\.[0-9]+\.patch$/\1/')

if [ "$app_directory" = 'webapp_updater' ] || [ ! -f "$repository_root/$app_directory/config.yaml" ] || [ ! -f "$repository_root/$app_directory/Dockerfile" ]; then
  echo "Der Patch bezieht sich nicht auf eine verwaltete WebApp." >&2
  exit 1
fi

if grep -Eq '(^GIT binary patch$|^Binary files )' "$patch_file"; then
  echo "Binärdateien sind in Text-Patches nicht zulässig." >&2
  exit 1
fi

cd "$repository_root"
if ! git apply --check --recount --whitespace=error "$patch_file"; then
  echo "Der Text-Patch passt nicht zum aktuellen GitHub-Quellstand." >&2
  exit 1
fi

touched_paths=$(git apply --numstat "$patch_file" | awk -F '\t' '{ print $3 }')
if [ -z "$touched_paths" ] || printf '%s\n' "$touched_paths" | grep -Ev "^${app_directory}/" | grep -q .; then
  echo "Ein Text-Patch darf nur Dateien der betreffenden WebApp ändern." >&2
  exit 1
fi

old_version=$(awk '/^version: / { print $2; exit }' "$app_directory/config.yaml" | tr -d '"')
git apply --recount --whitespace=error "$patch_file"

if [ ! -f "$app_directory/config.yaml" ] || [ ! -f "$app_directory/Dockerfile" ]; then
  echo "Dem geänderten Quellstand fehlen config.yaml oder Dockerfile." >&2
  exit 1
fi

new_version=$(awk '/^version: / { print $2; exit }' "$app_directory/config.yaml" | tr -d '"')
expected_name="${app_directory}-${new_version}.patch"
if ! printf '%s\n' "$new_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || [ "$package_name" != "$expected_name" ]; then
  echo "Patchname und erhöhte Versionsnummer müssen übereinstimmen." >&2
  exit 1
fi
if [ "$(printf '%s\n%s\n' "$old_version" "$new_version" | sort -V | tail -n1)" != "$new_version" ] || [ "$old_version" = "$new_version" ]; then
  echo "Patch $new_version wurde übersprungen: Die vorhandene Version ist $old_version."
  exit 0
fi

sh ./scripts/check-repository-safety.sh
if git diff --quiet -- "$app_directory"; then
  echo "Der Text-Patch enthält keine Änderung."
  exit 0
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'imported=true\nversion=%s\napp_directory=%s\n' "$new_version" "$app_directory" >> "$GITHUB_OUTPUT"
fi
echo "Text-Patch ${app_directory} $new_version ist geprüft und bereit zur Übernahme."
