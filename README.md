# Home-Assistant-WebApps

Dieses Repository enthält ausschließlich den versionierten Quellcode der lokalen Home-Assistant-WebApps. Laufzeitdaten bleiben auf dem jeweiligen Home-Assistant-System in `/data` und werden nie eingecheckt.

## Apps

- `einkaufsliste/` – Einkaufsliste, Slug `eigene_einkaufsliste`, Port 8156.

Jede App besitzt ihre eigene Versionsnummer, Konfiguration, Tests und ihr eigenes GHCR-Image. GitHub Actions prüft und veröffentlicht nur die App, deren Verzeichnis geändert wurde.

## Schutz von Daten

Die `.gitignore` und der CI-Check schließen Datenbanken, Listeninhalte, Backups, hochgeladene/generierte Dateien, Sitzungen, Schlüssel und lokale Konfigurationen aus. App-Optionen wie Tokens oder API-Schlüssel werden weiterhin ausschließlich in Home Assistant hinterlegt.

## Google-Drive-Codeeingang

Neben der direkten Bearbeitung im Work-Modus kann ein normaler Chat ein neues **Quellpaket** in den dafür vorgesehenen Google-Drive-Ordner legen. Der Workflow `Google-Drive-Import` prüft alle 15 Minuten das neueste ZIP und übernimmt ausschließlich ein Paket, das genau den Ordner `einkaufsliste/` enthält und eine höhere Version besitzt.

Vor einem Commit werden Dateipfade, Größe, symbolische Links sowie Daten- und Schlüsseldateien geprüft. Anschließend startet der bestehende Mehrarchitektur-Build. Die Drive-Verbindung verwendet einen eigenen, nur lesenden Service-Account-Zugang, der als GitHub Secret hinterlegt wird; weder Zugangsdaten noch Home-Assistant-Laufzeitdaten gelangen ins Repository.

### Einmalige Einrichtung

1. In Google Cloud einen Service Account nur für den Codeeingang erstellen und einen JSON-Schlüssel erzeugen.
2. Den Google-Drive-Ordner **Home Assistant WebApp – Codeeingang** mit der Service-Account-E-Mail als **Betrachter** teilen.
3. In GitHub unter `Settings → Secrets and variables → Actions` ein Secret `GOOGLE_DRIVE_IMPORTER_CREDENTIALS` mit dem vollständigen JSON-Schlüssel und eine Variable `GOOGLE_DRIVE_IMPORT_FOLDER_ID` mit der Ordner-ID hinterlegen.
4. In Google Cloud die **Google Drive API** für dieses Projekt aktivieren.

Danach genügt ein ZIP mit genau diesem Aufbau:

```text
einkaufsliste/
  config.yaml
  package.json
  app/
  …
```

Die Versionsnummer in `einkaufsliste/config.yaml` muss höher sein als die bereits veröffentlichte Version.
