# Home-Assistant-WebApps

Dieses Repository enthält ausschließlich den versionierten Quellcode der lokalen Home-Assistant-WebApps. Laufzeitdaten bleiben auf dem jeweiligen Home-Assistant-System in `/data` und werden nie eingecheckt.

## Apps

- `einkaufsliste/` – Einkaufsliste, Slug `eigene_einkaufsliste`, Port 8156.

Jede App besitzt ihre eigene Versionsnummer, Konfiguration, Tests und ihr eigenes GHCR-Image. GitHub Actions prüft und veröffentlicht nur die App, deren Verzeichnis geändert wurde.

## Schutz von Daten

Die `.gitignore` und der CI-Check schließen Datenbanken, Listeninhalte, Backups, hochgeladene/generierte Dateien, Sitzungen, Schlüssel und lokale Konfigurationen aus. App-Optionen wie Tokens oder API-Schlüssel werden weiterhin ausschließlich in Home Assistant hinterlegt.
