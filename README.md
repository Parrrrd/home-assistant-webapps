# Home-Assistant-WebApps

Dieses Repository enthält ausschließlich den versionierten Quellcode der lokalen Home-Assistant-WebApps. Laufzeitdaten bleiben auf dem jeweiligen Home-Assistant-System in `/data` und werden nie eingecheckt.

## Apps

- `einkaufsliste/` – Einkaufsliste, Slug `eigene_einkaufsliste`, Port 8156.
- `webapp_updater/` – Übernimmt neue GitHub-Versionen in bereits installierte lokale WebApps, ohne deren Daten oder Einstellungen zu ändern.

Jede App besitzt ihre eigene Versionsnummer, Konfiguration, Tests und ihr eigenes GHCR-Image. GitHub Actions prüft und veröffentlicht nur die App, deren Verzeichnis geändert wurde.

## Lokale Apps ohne Datenumzug aktualisieren

Der **WebApp-Updater** hält die vorhandenen lokalen Apps aktuell. Er ersetzt nur ihren
versionierten Quellordner unter `/addons`; deren Home-Assistant-Kennung (`local_…`),
Optionen und Laufzeitdaten unter `/data` bleiben bestehen. Für die Einkaufsliste ist
`local_eigene_einkaufsliste` bereits hinterlegt. Bei einer neuen App wird nur ein
weiterer Eintrag in `webapp_updater/rootfs/managed-apps.json` ergänzt.

Nach der einmaligen Installation prüft der Updater GitHub standardmäßig jede
Minute. Dabei lädt er den vollständigen Quellstand nur nach einer tatsächlichen
Änderung. Bei einer höheren Versionsnummer lädt er die lokale App-Quelle neu und stößt
das normale Home-Assistant-Update an. Über `auto_apply_updates` kann das automatische
Anwenden bei Bedarf ausgeschaltet werden.

Für jede verwaltete WebApp schaltet der Updater außerdem die Home-Assistant-Option
„Automatische Updates“ ein. Damit ist weder „Alle Apps“ noch „Nach Updates suchen"
für diese WebApps nötig.

## Direkte Browser-Oberfläche

Alle eigenen WebApps öffnen ausschließlich über ihre direkte Browser-Adresse. Eine
App-Konfiguration mit Home-Assistant-Ingress wird beim Sicherheitscheck abgelehnt.
So bleibt die Oberfläche unabhängig von Home Assistant; Home Assistant verwaltet nur
Installation, Betrieb und Updates.

## Schutz von Daten

Die `.gitignore` und der CI-Check schließen Datenbanken, Listeninhalte, Backups, hochgeladene/generierte Dateien, Sitzungen, Schlüssel und lokale Konfigurationen aus. App-Optionen wie Tokens oder API-Schlüssel werden weiterhin ausschließlich in Home Assistant hinterlegt.

## Google-Drive-Codeeingang

Neben der direkten Bearbeitung im Work-Modus kann ein normaler Chat ein neues **Quellpaket** in den dafür vorgesehenen Google-Drive-Ordner legen. Eine kleine Google-Automatisierung meldet das Paket innerhalb einer Minute an GitHub. Der Workflow `Google-Drive-Import` übernimmt ausschließlich ein Paket, das genau den Ordner `einkaufsliste/` enthält und eine höhere Version besitzt. Ein stündlicher Abgleich dient nur als Rückfallebene.

Vor einem Commit werden Dateipfade, Größe, symbolische Links sowie Daten- und Schlüsseldateien geprüft. Anschließend startet der bestehende Mehrarchitektur-Build. Die Drive-Verbindung verwendet einen eigenen, nur lesenden Service-Account-Zugang, der als GitHub Secret hinterlegt wird; weder Zugangsdaten noch Home-Assistant-Laufzeitdaten gelangen ins Repository.

### Einmalige Einrichtung

1. In Google Cloud einen Service Account nur für den Codeeingang erstellen und einen JSON-Schlüssel erzeugen.
2. Den Google-Drive-Ordner **Home Assistant WebApp – Codeeingang** mit der Service-Account-E-Mail als **Betrachter** teilen.
3. In GitHub unter `Settings → Secrets and variables → Actions` ein Secret `GOOGLE_DRIVE_IMPORTER_CREDENTIALS` mit dem vollständigen JSON-Schlüssel und eine Variable `GOOGLE_DRIVE_IMPORT_FOLDER_ID` mit der Ordner-ID hinterlegen.
4. In Google Cloud die **Google Drive API** für dieses Projekt aktivieren.
5. In GitHub einen Fine-grained Token erstellen, auf dieses Repository beschränken und ihm nur `Contents: Write` geben. Den Token im [Google-Apps-Script](automation/google-drive-dispatch/Code.gs) als Script Property `GITHUB_DISPATCH_TOKEN` eintragen und `install()` einmal ausführen. Der Script-Trigger erkennt neue ZIPs im Codeeingang innerhalb einer Minute und meldet die konkrete Datei an GitHub.

Danach genügt ein ZIP mit genau diesem Aufbau:

```text
einkaufsliste/
  config.yaml
  package.json
  app/
  …
```

Die Versionsnummer in `einkaufsliste/config.yaml` muss höher sein als die bereits veröffentlichte Version.
