# Stundenplanung Home-Assistant-Add-on

Version 0.3.72 für Arbeitszeit-Screenshots aus `/share/Stunden`.

Die AI liest nur Rohdaten aus dem Screenshot. Die Web-App rechnet fachlich selbst.

## Aktueller Funktionsstand

- automatischer Screenshot-Import aus `/share/Stunden`
- AI-Erkennung per Gemini oder alternativ lokal per Ollama
- automatische Anlage oder Aktualisierung des passenden Arbeitstags
- Arbeitsblöcke werden gespeichert und für Berechnung sowie Anzeige verwendet
- Gesamtarbeitszeit wird ausschließlich aus den Arbeitsblöcken berechnet
- Sollzeit-Buchung mit festen Standardzeiten:
  - Mo/Di/Do/Fr: `08:00–15:58`
  - Mi: `08:00–15:56`
- Import-Vorschau sowohl auf der Import-Seite als auch im Tag-Bearbeiten
- letzter Analysezeitpunkt direkt im Import sichtbar
- automatische Warteschlange bei Gemini-Limit oder Überlastung
- Telegram-Rückfrage nach Bildimport über zwei kleine API-Endpunkte
- Telegram-Antwort mit Minuten oder Zeitblock wird direkt als Nachlauf-Buchung übernommen
- Werte bleiben jederzeit manuell bearbeitbar

## Fachlogik

- Mittwoch Sollzeit: `7:56`
- alle anderen Arbeitstage: `7:58`
- Gesamtarbeitszeit = Summe der gespeicherten Arbeitsblöcke
- Tagesplus/-minus = Gesamtarbeitszeit - Sollzeit
- Effektiver Tageswert = Tagesplus/-minus + Restpausenabzug - Nachlauf/manuelle Korrektur
- Nachlauf-Budget führt den importierten Restpausenabzug separat mit

## Hinweis

Diese Version ist auf das aktuell verwendete Screenshot-Layout des Stempelsystems abgestimmt. Falls sich das Layout ändert, können Tags weiterhin manuell korrigiert werden.


## Telegram-Nachlauf

Für Home-Assistant-Automationen gibt es zwei API-Endpunkte:

- `POST /api/telegram/import-prompt` → liefert die Rückfrage zum gerade gesendeten Bild
- `POST /api/telegram/reply` → übernimmt die Antwort direkt im Arbeitstag als Nachlauf / manuelle Korrektur (Fallback ohne passenden Tag: separate Nachlauf-Buchung)

Antwortformate:

- `30 Minuten`
- `30`
- `17:32-18:05`
- `0` oder `nein`

Die Buchung wird als `catchup` gespeichert und vom effektiven Tageswert abgezogen.


Telegram-Nachlauf-Antworten werden ab Version 0.3.69 bei noch laufender Analyse vorgemerkt und nach Abschluss automatisch in den passenden Arbeitstag übernommen.


Hinweis Stand 0.3.71: Neue Telegram-Bilder werden nach dem Verschieben nach `processed` sofort als Import gespeichert, sodass sie auch bei späteren Folgefehlern in der Web-App sichtbar bleiben.
