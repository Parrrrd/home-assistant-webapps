# Patrick's Home-Assistant-WebApps

Private Sammlung der eigenen WebApps. Der Quellcode liegt hier, während Listen,
Einstellungen, Bilder und Zugangsdaten ausschließlich auf Home Assistant bleiben.

## Apps

| App | Verwendung | Versionsverlauf |
| --- | --- | --- |
| [Einkaufsliste](einkaufsliste/) | Öffnet direkt im Browser über „Benutzeroberfläche öffnen“. | [Änderungen ansehen](einkaufsliste/CHANGELOG.md) |
| [WebApp-Updater](webapp_updater/) | Installiert neue Versionen automatisch und meldet sie auf Patricks iPhone. | [Änderungen ansehen](webapp_updater/CHANGELOG.md) |

## So funktioniert es

1. Eine neue Version wird auf GitHub geprüft und veröffentlicht.
2. Der WebApp-Updater prüft GitHub jede Minute.
3. Er installiert die neue Version automatisch, schreibt den Zeitpunkt ins Home-Assistant-Protokoll und sendet eine iPhone-Mitteilung.
4. Eigene WebApps öffnen immer direkt im Browser. Home Assistant verwaltet nur Installation, Betrieb und Updates.

## Verlässlicher Verlauf

- **GitHub:** Jede veröffentlichte Version steht mit Datum und Uhrzeit im jeweiligen Änderungsprotokoll.
- **Home Assistant:** Das Protokoll des WebApp-Updaters zeigt, wann die Version tatsächlich installiert wurde.
- **Lieferkette:** [Schutzmaßnahmen ansehen](SECURITY.md).

## Datenschutz

Dieses Repository enthält keinen Betriebsstand und keine Zugangsdaten. Der Sicherheitscheck blockiert Datenbanken, Listen, Backups, Bilder, Sitzungen, Schlüssel und lokale App-Optionen vor jedem Commit.

<details>
<summary>Technik und Google-Drive-Codeeingang</summary>

Der WebApp-Updater ersetzt ausschließlich den versionierten Quellordner einer bereits installierten lokalen App. Ihre Home-Assistant-Kennung, Optionen und Daten unter `/data` bleiben erhalten. Für jede weitere eigene WebApp wird ein Eintrag in `webapp_updater/rootfs/managed-apps.json` ergänzt.

Ein normaler Chat kann eine Text-Änderung als `.patch` in den Google-Drive-Codeeingang legen. Die Google-Automatisierung meldet sie innerhalb einer Minute an GitHub. Der Workflow wendet sie nur auf den aktuellen Quellstand an, prüft Versionsnummer, Daten, Schlüssel und Tests und veröffentlicht anschließend das Mehrarchitektur-Image. ZIP-Pakete bleiben für Work-Modus und bestehende Übergaben unterstützt.

</details>
