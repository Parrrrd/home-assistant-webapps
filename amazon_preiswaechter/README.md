# Amazon Preiswächter

Lokale Home-Assistant-WebApp für Amazon.de-Preisüberwachung und freie MyDealz-Beobachtungen.

Version 0.1.53 nutzt intern und extern Port 8100. Persistente Daten liegen unter `/data` und bleiben bei Updates erhalten.

## Preisquellen

- **Amazon Neu und Gebraucht:** werden getrennt regelmäßig geprüft.
- **MyDealz:** RSS, öffentliche Suche und die jeweilige Thread-Aktivität stellen sicher, dass nur bestätigte aktive Deals angezeigt werden.
- **Idealo:** die Zuordnung erfolgt beim Anlegen eines Artikels einmalig per Gemini mit Google Search. Akzeptiert werden nur bestätigte konkrete Idealo-Produktseiten.

### Idealo ab Version 0.1.53

Reader und Browser werden für Idealo nicht mehr verwendet. Sie konnten durch Idealos Bot-Schutz keine verlässlichen Preise liefern und durften deshalb keine Zuordnung mehr beeinflussen.

- Ein bereits gespeicherter Idealo-Link wird ausschließlich mit Gemini URL Context geprüft. Dabei wird keine Google-Suche ausgeführt und die Zuordnung niemals automatisch geändert.
- Schlägt eine Linkprüfung fehl oder passt das Produkt nicht eindeutig, bleibt der bisherige Link samt letztem sicheren Preis erhalten. primary erhält einmalig eine wichtige, lautlose iPhone-Mitteilung zur Prüfung beziehungsweise Neu-Zuordnung.
- Eine Google-Suche zur Idealo-Zuordnung gibt es nur beim Anlegen eines Artikels oder beim ausdrücklich ausgelösten Button **„Idealo neu zuordnen“**.
- **„Alle Preise aktualisieren“** prüft gespeicherte Idealo-Links mit URL Context, ohne neue Zuordnungen zu suchen.
- Die Einzelaktionen **„Alles jetzt prüfen“** und **„Idealo neu zuordnen“** laufen im Hintergrund. Dadurch führt eine längere Antwort von Amazon, MyDealz oder Gemini nicht mehr zu einem Browser-Timeout; nach Abschluss werden Ergebnis und Fehler direkt angezeigt.
- Eine URL-Context-Prüfung darf bis zu zwei Minuten dauern. Bei einer einzelnen Lese-Zeitüberschreitung wird derselbe gespeicherte Link einmalig erneut gelesen; es wird dabei keine Google-Suche gestartet und keine Zuordnung verändert.
- Eine vorübergehende Gemini-Überlastung (HTTP 5xx) wird ebenfalls einmalig erneut versucht. Erst danach erscheint ein kurzer verständlicher Hinweis statt der technischen Google-Fehlermeldung.
- Bei einer zuvor sicher bestätigten, unveränderten Idealo-Produktseite darf ein generischer oder fehlender Seitentitel die Preisprüfung nicht mehr fälschlich blockieren. Eine ausdrücklich andere Produktvariante bleibt weiterhin eine harte Sperre; es wird dann weder ein Preis übernommen noch die Zuordnung geändert.
- Für die laufende Preisprüfung fordert Gemini nur noch die bestätigte Produktidentität, den nach der Preisregel berechneten Endpreis und den Shop an. Die fehleranfällige vollständige Angebotstabelle wird nicht mehr abgefragt; das reduziert Antwortumfang und Ausfälle erheblich.
- Automatisch wird standardmäßig einmal täglich um **12:00 Uhr** geprüft. In der App-Konfiguration kann `idealo_checks_per_day` auf **4** gestellt werden; dann sind die Zeiten **08:00, 12:00, 16:00 und 20:00 Uhr** (Europe/Berlin).

## Preisbenachrichtigungen

In jedem Artikeldetail kann **„Push bei jeder Preisänderung“** aktiviert werden. Die darunter gewählte Mindeständerung in Euro gilt jeweils für Amazon und Idealo. So löst beispielsweise ein Wert von `2,00 €` keine Nachricht bei kleinen Schwankungen von zehn oder zwanzig Cent aus.

Bestehende Tiefpreis- und Wunschpreisbenachrichtigungen bleiben unabhängig davon erhalten.

## Gemini

Unter der Home-Assistant-App-Konfiguration stehen zur Verfügung:

- `gemini_api_key`: API-Key aus Google AI Studio (optional, Passwortfeld)
- `gemini_model`: Standard `gemini-3.7-flash`
- `idealo_checks_per_day`: `1` (Standard, 12:00 Uhr) oder `4` (08:00, 12:00, 16:00, 20:00 Uhr)

Für die Idealo-Zuordnung beim Anlegen wird Google Search verwendet. Danach nutzt die laufende Prüfung nur noch den gespeicherten Link per URL Context. Die Übersicht zeigt getrennt die Google-Suchen und die heutigen Linkprüfungen an.

## Build

Die App basiert auf `ghcr.io/home-assistant/base-python:3.14-alpine3.24` und verwendet ausschließlich die Python-3.14-Standardbibliothek. Es gibt keine externen oder nativen Python-Abhängigkeiten und keinen installierten Headless-Browser.
