# Home-Assistant-WebApps

Private Sammlung der eigenen WebApps. Der Quellcode liegt hier, während Listen,
Einstellungen, Bilder und Zugangsdaten ausschließlich auf Home Assistant bleiben.

## Apps

Alle hier geführten Anwendungen verwenden ihren eigenen Ordner als alleinige Quelle. Laufzeitdaten und Zugangsdaten bleiben in Home Assistant.

| App | Version | Öffnen | Verlauf |
| --- | --- | --- | --- |
| [Alexa Einkaufsliste Sync](alexa_bring_sync/) | 0.6.10 | Direkte Browser-Adresse | [Änderungen](alexa_bring_sync/CHANGELOG.md) |
| [Amazon Preiswächter](amazon_preiswaechter/) | 0.1.54 | Direkte Browser-Adresse | [Änderungen](amazon_preiswaechter/CHANGELOG.md) |
| [BARF-Portionsrechner](barf_portionsrechner/) | 0.1.12 | Direkte Browser-Adresse | [Änderungen](barf_portionsrechner/CHANGELOG.md) |
| [BarfußKompass](barfusskompass/) | 0.1.3 | Direkte Browser-Adresse | [Änderungen](barfusskompass/CHANGELOG.md) |
| [Center Parcs Preisüberwachung](center_parcs_preisueberwachung/) | 0.3.20 | Direkte Browser-Adresse | [Änderungen](center_parcs_preisueberwachung/CHANGELOG.md) |
| [Drogerie Bestandsvergleich](drogerie_bestandsvergleich/) | 0.1.4 | Direkte Browser-Adresse | [Änderungen](drogerie_bestandsvergleich/CHANGELOG.md) |
| [Einkaufsliste](einkaufsliste/) | 0.3.58 | Direkte Browser-Adresse | [Änderungen](einkaufsliste/CHANGELOG.md) |
| [Energieplaner](energieplaner/) | 0.1.59 | Direkte Browser-Adresse | [Änderungen](energieplaner/CHANGELOG.md) |
| [Finanzen & Budget](finanzplanung/) | 0.1.50 | Direkte Browser-Adresse | [Änderungen](finanzplanung/CHANGELOG.md) |
| [Rezeptverwaltung](hellofresh_rezepte/) | 0.8.20 | Direkte Browser-Adresse | [Änderungen](hellofresh_rezepte/CHANGELOG.md) |
| [InventurManager](inventurmanager/) | 0.10.44 | Direkte Browser-Adresse | [Änderungen](inventurmanager/CHANGELOG.md) |
| [Jarvis AI](jarvis_ai/) | 0.1.6 | Direkte Browser-Adresse | [Änderungen](jarvis_ai/CHANGELOG.md) |
| [Kicktipp TipBot](kicktipp_tipbot/) | 0.1.43 | Direkte Browser-Adresse | [Änderungen](kicktipp_tipbot/CHANGELOG.md) |
| [Kicktipp Bot für secondary](kicktipp_tipbot2/) | 0.1.7 | Direkte Browser-Adresse | [Änderungen](kicktipp_tipbot2/CHANGELOG.md) |
| [Kinder-Finanzen](kinderbudget/) | 0.7.3 | Direkte Browser-Adresse | [Änderungen](kinderbudget/CHANGELOG.md) |
| [Kleinanzeigen-Manager](kleinanzeigen_manager/) | 1.6.39 | Direkte Browser-Adresse | [Änderungen](kleinanzeigen_manager/CHANGELOG.md) |
| [Mietbewerber-Manager](mietbewerber_manager/) | 0.2.23 | Direkte Browser-Adresse | [Änderungen](mietbewerber_manager/CHANGELOG.md) |
| [Mounjaro Tracker](mounjaro_tracker/) | 0.1.13 | Direkte Browser-Adresse | [Änderungen](mounjaro_tracker/CHANGELOG.md) |
| [MOVA OG Protokoll](mova_og_protokoll/) | 0.1.1 | Direkte Browser-Adresse | [Änderungen](mova_og_protokoll/CHANGELOG.md) |
| [MOVA Protokoll](mova_protokoll/) | 0.4.4 | Direkte Browser-Adresse | [Änderungen](mova_protokoll/CHANGELOG.md) |
| [PAYBACK Coupons](payback_coupons/) | 0.1.13 | Direkte Browser-Adresse | [Änderungen](payback_coupons/CHANGELOG.md) |
| [Post & DHL Frankierung](post_dhl_frankierung/) | 0.1.41 | Direkte Browser-Adresse | [Änderungen](post_dhl_frankierung/CHANGELOG.md) |
| [Rezeptverwaltung](rezeptverwaltung/) | 0.8.19 | Direkte Browser-Adresse | [Änderungen](rezeptverwaltung/CHANGELOG.md) |
| [Serienplaner](serienplaner/) | 0.1.33 | Direkte Browser-Adresse | [Änderungen](serienplaner/CHANGELOG.md) |
| [Stay Informed Speiseplan](stayinformed_speiseplan/) | 0.2.1 | Direkte Browser-Adresse | [Änderungen](stayinformed_speiseplan/CHANGELOG.md) |
| [Stundenplanung](stundenplanung/) | 0.3.95 | Direkte Browser-Adresse | [Änderungen](stundenplanung/CHANGELOG.md) |
| [TerraMow Protokoll](terramow_protokoll/) | 0.1.10 | Direkte Browser-Adresse | [Änderungen](terramow_protokoll/CHANGELOG.md) |
| [Vinted Manager](vinted_manager/) | 0.13.94 | Direkte Browser-Adresse | [Änderungen](vinted_manager/CHANGELOG.md) |
| [WebApp Sync Manager](webapp_sync_manager/) | 0.3.8 | Direkte Browser-Adresse | [Änderungen](webapp_sync_manager/CHANGELOG.md) |
| [WebApp Übersicht](webapp_uebersicht/) | 0.1.4 | Direkte Browser-Adresse | [Änderungen](webapp_uebersicht/CHANGELOG.md) |
| [WebApp-Updater](webapp_updater/) | 0.1.12 | – | [Änderungen](webapp_updater/CHANGELOG.md) |

## So funktioniert es

1. Eine neue Version wird auf GitHub geprüft und veröffentlicht.
2. Der WebApp-Updater prüft GitHub standardmäßig alle 20 Sekunden.
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

Der WebApp-Updater ersetzt ausschließlich den versionierten Quellordner einer bereits installierten lokalen App. Ihre Home-Assistant-Kennung, Optionen und Daten unter `/data` bleiben erhalten. Alle vorhandenen eigenen WebApps sind dort hinterlegt. Beim ersten Erkennen wird ihr vorhandener Stand nur als Ausgangspunkt gespeichert; eine spätere höhere Version wird automatisch übernommen.

Ein normaler Chat kann eine Text-Änderung als `.patch` in den Google-Drive-Codeeingang legen. Die Google-Automatisierung meldet sie innerhalb einer Minute an GitHub. Der Workflow wendet sie nur auf den aktuellen Quellstand an, prüft Versionsnummer, Daten, Schlüssel und Tests und veröffentlicht anschließend das Mehrarchitektur-Image. ZIP-Pakete bleiben für Work-Modus und bestehende Übergaben unterstützt.

</details>
