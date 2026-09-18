#!/usr/bin/env sh
set -eu

blocked_paths='(^|/)(data|backups|preview-data|generated-product-images)(/|$)|(^|/)(shopping-list\.json|options\.json|secrets\.ya?ml)$|\.(db|sqlite|sqlite3|pem|key|p12|pfx)$'
if git ls-files --cached --others --exclude-standard | grep -E "$blocked_paths"; then
  echo "Laufzeitdaten oder geheime Dateien dürfen nicht versioniert werden." >&2
  exit 1
fi

if git grep -I -n -E -e '-----BEGIN( [A-Z]+)? PRIVATE KEY-----|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{20,}' -- .; then
  echo "Möglicher Zugangsschlüssel im Repository gefunden." >&2
  exit 1
fi

# Eigene WebApps werden ausschließlich über ihre direkte Browser-Adresse geöffnet.
# Der Updater selbst hat keine Benutzeroberfläche und ist deshalb ausgenommen.
for app_config in */config.yaml; do
  [ -f "$app_config" ] || continue
  app_dir=${app_config%/config.yaml}
  app_version=$(awk '/^version: / { print $2; exit }' "$app_config")
  if [ ! -f "$app_dir/CHANGELOG.md" ] || ! grep -Eq "^## ${app_version} — [0-9]{2}\\.[0-9]{2}\\.[0-9]{4}, [0-9]{2}:[0-9]{2} [A-Z]+$" "$app_dir/CHANGELOG.md"; then
    echo "${app_config}: Der GitHub-Verlauf benötigt einen Changelog-Eintrag mit Datum und Uhrzeit für Version ${app_version}." >&2
    exit 1
  fi
  [ "$app_config" = "webapp_updater/config.yaml" ] && continue
  if grep -Eq '^ingress:[[:space:]]*true[[:space:]]*$|^ingress_port:' "$app_config"; then
    echo "${app_config}: WebApps dürfen nicht über Home-Assistant-Ingress geöffnet werden." >&2
    exit 1
  fi
  if ! grep -Eq '^webui:[[:space:]]*"?http://\[HOST\]:\[PORT:[0-9]+\]/?"?[[:space:]]*$' "$app_config"; then
    echo "${app_config}: WebApps benötigen eine direkte Browser-Adresse mit webui." >&2
    exit 1
  fi
done
