# Übergabe / Fachkonzept – InventurManager 0.1.0

## Ziel
Home-Assistant-WebApp zur einfachen Inventur, Preisverfolgung und Sammelerfassung von Rechnungen.

## Schwerpunkt
- leichte Bedienung auf iPhone
- viele Positionen pro Rechnung in einem Schritt
- Varianten/Gebindegrößen pro Artikel
- Inventur pro Jahr
- Preisverlauf pro Variante
- Startjahr 2025 direkt vorbereitet

## Bedienlogik
### Artikel
- Artikelgruppe = Oberbegriff, z. B. Kinderschokolade
- Variante = Gebinde, z. B. 100 g oder 300 g

### Neue Rechnung
- einmal Rechnungsdatum
- optional Rechnungsnummer und Lieferant
- dann mehrere Positionen
- pro Position:
  - bestehende Variante wählen oder neue anlegen
  - Menge
  - Nettopreis
  - Notiz

### Inventur
- eigener Jahresbildschirm
- Anfangsbestand
- Endbestand
- Inventurpreis netto
- Folgejahr bekommt automatisch den Anfangsbestand aus dem Endbestand des Vorjahres

### Auswertung
- Preisverlauf je Variante
- Historie mit Datum
- sichtbare prozentuale Preisänderung

## Seed
Die Seed-Datei basiert auf der hochgeladenen Inventurliste 2024 und übernimmt:
- Artikel
- Gebinde
- Inventur 2024
- Anfangsbestand 2025 = Endbestand 2024
- Start-Preisverlauf über einen Seed-Eintrag vom 2024-12-31

## Installationspfade
- ZIP: /share/InventurManager/inventurmanager-v0.1.0.zip
- Temp: /tmp/inventurmanager-update
- Add-on: /addons/inventurmanager

## Terminal
rm -rf /tmp/inventurmanager-update
mkdir -p /tmp/inventurmanager-update

unzip -o /share/InventurManager/inventurmanager-v0.1.0.zip -d /tmp/inventurmanager-update

rm -rf /addons/inventurmanager
mkdir -p /addons/inventurmanager

cp -a /tmp/inventurmanager-update/. /addons/inventurmanager/

grep '^version:' /addons/inventurmanager/config.yaml
