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

if grep -R -n -E '^[[:space:]]*pull_request_target:' .github/workflows; then
  echo "pull_request_target ist in diesem Repository nicht zulässig." >&2
  exit 1
fi

for workflow in .github/workflows/*.yml; do
  [ -f "$workflow" ] || continue
  if grep -E '^[[:space:]]*-[[:space:]]+uses:' "$workflow" | grep -Ev '@[0-9a-f]{40}([[:space:]]+#.*)?$'; then
    echo "${workflow}: GitHub Actions müssen auf vollständige Commit-IDs festgeschrieben sein." >&2
    exit 1
  fi
done

# Aufrufer des gemeinsamen Build-Workflows dürfen dessen minimale Rechte nicht
# einschränken. GitHub prüft diese Regel sonst erst beim Start eines einzelnen
# App-Builds.
for workflow in .github/workflows/*.yml; do
  [ -f "$workflow" ] || continue
  if ! grep -Fq 'uses: ./.github/workflows/reusable-addon-build.yml' "$workflow"; then
    continue
  fi
  if ! awk '
    /^  build:[[:space:]]*$/ { in_build = 1; next }
    in_build && /^  [[:alnum:]_-]+:[[:space:]]*$/ { in_build = 0 }
    in_build && /^    uses: \.\/\.github\/workflows\/reusable-addon-build\.yml[[:space:]]*$/ { reusable = 1 }
    in_build && /^      contents:[[:space:]]*read[[:space:]]*$/ { contents = 1 }
    in_build && /^      packages:[[:space:]]*write[[:space:]]*$/ { packages = 1 }
    in_build && /^      id-token:[[:space:]]*write[[:space:]]*$/ { id_token = 1 }
    END { exit !(reusable && contents && packages && id_token) }
  ' "$workflow"; then
    echo "${workflow}: Der gemeinsame Add-on-Build benötigt contents: read, packages: write und id-token: write im Job build." >&2
    exit 1
  fi
done

# Eigene WebApps werden ausschließlich über ihre direkte Browser-Adresse geöffnet.
# Der Updater selbst hat keine Benutzeroberfläche und ist deshalb ausgenommen.
for app_config in */config.yaml; do
  [ -f "$app_config" ] || continue
  app_dir=${app_config%/config.yaml}
  app_version=$(awk '/^version: / { print $2; exit }' "$app_config" | tr -d '"')
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
