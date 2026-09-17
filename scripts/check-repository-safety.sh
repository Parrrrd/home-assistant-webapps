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
