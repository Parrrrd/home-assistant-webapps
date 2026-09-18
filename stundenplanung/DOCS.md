# Nutzung

1. Add-on installieren.
2. Optional ein Web-Passwort setzen.
3. Screenshots wie bisher nach `/share/Stunden` speichern.
4. Neue Bilder werden automatisch nach `/share/Stunden/processed` verschoben.
5. Der Import analysiert das Bild und legt direkt einen Arbeitstag an oder aktualisiert ihn.
6. Falls Gemini im Limit ist, wird der Import automatisch auf einen Neuversuch vorgemerkt.
7. Auf der Import-Seite ist der letzte Analysezeitpunkt sichtbar.
8. Falls etwas nicht exakt erkannt wurde, den Tag einfach bearbeiten.

## Parserlogik

- relevant ist nur der aktuell sichtbare Tag
- angeschnittene Reste vom Vortag werden ignoriert
- die Spalte `06:00 - 20:00` wird ignoriert
- sichtbare Arbeitsblöcke werden in zeitlicher Reihenfolge gespeichert
- erster Beginn = Kommen
- letztes sichtbares Ende der Hauptzeile = Gehen
- ein sichtbarer Restpausenabzug wird separat gelesen
- wenn unten in der Restpausenabzug-Zeile links eine Klammerzeit wie `(17:55)` steht, wird diese intern als letztes Arbeitsende vor Restpausenabzug verwendet
- die sichtbaren Arbeitsblöcke selbst bleiben dabei unverändert
- Plus/Minus und Gesamtarbeitszeit werden nicht aus dem Bild übernommen, sondern serverseitig aus den Arbeitsblöcken berechnet

## Formeln

`gesamtarbeitszeit = summe(arbeitsbloecke)`

`tageplusminus = gesamtarbeitszeit - sollzeit`

`effektiver_tageswert = tageplusminus + restpausenabzug - manuelle_korrektur`

`nachlauf_budget = manueller_anteil + importierter_restpausenabzug`

## Sollzeit-Buchung

Der Button `Sollzeit buchen` setzt direkt einen Standard-Arbeitsblock:

- Montag, Dienstag, Donnerstag, Freitag: `08:00–15:58`
- Mittwoch: `08:00–15:56`

## Import-Status

- `Automatisch verarbeitet`: Import wurde erfolgreich übernommen
- `Bitte prüfen`: Import wurde übernommen, sollte aber kontrolliert werden
- `Wartet auf Neuversuch`: Import wurde wegen Gemini-Limit oder Überlastung automatisch in die Warteschlange gelegt
- `Fehler`: Verarbeitung ist fehlgeschlagen
- `Duplikat`: Dateiinhalt war bereits bekannt


## Telegram-Rückfrage für Nachlauf

Das Add-on stellt zwei lokale API-Endpunkte bereit:

### 1. Rückfrage nach Bildimport

`POST /api/telegram/import-prompt`

Beispiel-Payload:

```json
{
  "chat_id": "123456",
  "user_id": "123456",
  "filename": "stunden_2026-04-12_08-30-00.jpg",
  "token": "DEIN_TOKEN"
}
```

Antwort:

```json
{
  "ok": true,
  "reply_text": "Vielen Dank für das Bild. Hast du heute Zeit nachlaufen lassen? Schicke mir die exakten Minuten oder den Zeitblock. (z.B. 30 Minuten oder 17:32-18:05)",
  "work_date": "2026-04-12",
  "import_id": 42
}
```

### 2. Antwort des Nutzers übernehmen

`POST /api/telegram/reply`

Wenn zum Datum bereits ein Arbeitstag existiert, wird der Nachlauf direkt in `manual_correction_min` des Tags übernommen und der effektive Tageswert neu berechnet. Nur ohne passenden Tag fällt das Add-on auf eine separate Nachlauf-Buchung zurück.


Beispiel-Payload:

```json
{
  "chat_id": "123456",
  "user_id": "123456",
  "text": "17:32-18:05",
  "token": "DEIN_TOKEN"
}
```

Erlaubte Antworten:

- Minuten: `30`, `30 Minuten`, `1:15`
- Zeitblock: `17:32-18:05`
- kein Nachlauf: `0`, `nein`, `keine`

Der Zeitblock wird in Minuten umgerechnet. Die Buchung wird als `catchup` gespeichert und reduziert den effektiven Tageswert des passenden Tages.

## Home-Assistant-Hinweis

Für die Absicherung kann in den Add-on-Optionen `telegram_api_token` gesetzt werden. Derselbe Wert muss dann in den HTTP-Aufrufen mitgegeben werden.


Telegram-Nachlauf-Antworten werden ab Version 0.3.69 bei noch laufender Analyse vorgemerkt und nach Abschluss automatisch in den passenden Arbeitstag übernommen.


Hinweis Stand 0.3.71: Neue Telegram-Bilder werden nach dem Verschieben nach `processed` sofort als Import gespeichert, sodass sie auch bei späteren Folgefehlern in der Web-App sichtbar bleiben.
