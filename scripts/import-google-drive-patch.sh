#!/usr/bin/env sh
set -eu

patch_file=${1:?Text-Patch fehlt}
package_name=${2:?Patchname fehlt}
repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$patch_file" ]; then
  echo "Kein Text-Patch im Codeeingang; nichts zu übernehmen."
  exit 0
fi

if ! printf '%s\n' "$package_name" | grep -Eq '^einkaufsliste-[0-9]+\.[0-9]+\.[0-9]+\.patch$'; then
  echo "Der Patchname muss einkaufsliste-X.Y.Z.patch lauten." >&2
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
if [ -z "$touched_paths" ] || printf '%s\n' "$touched_paths" | grep -Ev '^einkaufsliste/' | grep -q .; then
  echo "Ein Text-Patch darf nur Dateien der Einkaufsliste ändern." >&2
  exit 1
fi

old_version=$(awk '/^version: / { print $2; exit }' einkaufsliste/config.yaml)
git apply --recount --whitespace=error "$patch_file"

if [ ! -f einkaufsliste/config.yaml ] || [ ! -f einkaufsliste/package.json ]; then
  echo "Dem geänderten Quellstand fehlen config.yaml oder package.json." >&2
  exit 1
fi

new_version=$(awk '/^version: / { print $2; exit }' einkaufsliste/config.yaml)
expected_name="einkaufsliste-${new_version}.patch"
if ! printf '%s\n' "$new_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || [ "$package_name" != "$expected_name" ]; then
  echo "Patchname und erhöhte Versionsnummer müssen übereinstimmen." >&2
  exit 1
fi
if [ "$(awk '/^slug: / { print $2; exit }' einkaufsliste/config.yaml)" != "eigene_einkaufsliste" ]; then
  echo "Der Slug im geänderten Quellstand ist nicht zulässig." >&2
  exit 1
fi
if [ "$(printf '%s\n%s\n' "$old_version" "$new_version" | sort -V | tail -n1)" != "$new_version" ] || [ "$old_version" = "$new_version" ]; then
  echo "Patch $new_version wurde übersprungen: Die vorhandene Version ist $old_version."
  exit 0
fi

sh ./scripts/check-repository-safety.sh
if git diff --quiet -- einkaufsliste; then
  echo "Der Text-Patch enthält keine Änderung."
  exit 0
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'imported=true\nversion=%s\n' "$new_version" >> "$GITHUB_OUTPUT"
fi
echo "Text-Patch $new_version ist geprüft und bereit zur Übernahme."
