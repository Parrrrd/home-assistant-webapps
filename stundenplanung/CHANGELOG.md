## 0.3.95 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 0.3.94 - Pillow für Python 3.14 aktualisiert

- Pillow von 10.4.0 auf 12.3.0 aktualisiert.
- Für Pillow wird ausdrücklich ein fertiges Binärpaket verwendet.
- Dadurch wird Pillow unter Python 3.14 nicht mehr aus dem Quellcode kompiliert.
- Die Push-Funktion an alle Mobilgeräte aus Version 0.3.92 bleibt enthalten.

## 0.3.93 - Build mit Python 3.14 repariert

- Fehlende Alpine-Buildabhängigkeiten für Pillow ergänzt, insbesondere `zlib-dev`.
- Weitere benötigte Bildbibliotheken und Header werden beim Build installiert.
- Temporäre Compiler-Pakete werden nach der Installation wieder entfernt.
- Push an alle Mobilgeräte aus Version 0.3.92 bleibt unverändert enthalten.

## 0.3.92 - Push an alle Mobilgeräte

- Import- und Nachlauf-Ergebnisse werden jetzt an alle in Home Assistant registrierten `notify.mobile_app_*`-Dienste gesendet.
- Jedes Gerät wird einzeln benachrichtigt; ein Fehler bei einem Gerät verhindert die Zustellung an die übrigen Geräte nicht.
- Der bisher konfigurierte einzelne Benachrichtigungsdienst bleibt als zusätzlicher Fallback kompatibel.

## 0.3.91
- Laptop-/Desktop-Layout der Übersicht verbreitert und Wochenkarten optisch aufgeräumt.
- Wochenkarten brechen auf mittelbreiten Displays sauberer um.

## 0.3.87 - Push nach Telegram-Nachlauf korrigiert

- Die Push-Zeile berechnet den effektiven Tageswert jetzt immer aus Tagesplus, Restpausenabzug/Zuschlag und Nachlauf/Korrektur neu.
- Wenn ein Telegram-Nachlauf nach dem Import beantwortet wird, wird danach zusätzlich die finale Dashboard-Zeile per Push gesendet, z. B. `Di, 28.04, Effektiver Tageswert: -0:42, geplant war: -0:58`.

## 0.3.86 - Push mit Tagesdatum

- Push-Nachricht nach erfolgreichem Import enthält jetzt den Tag und das Datum vor der Tageswert-Zeile, z. B. `Mo, 27.04, Effektiver Tageswert: +1:15, geplant war: +1:02`.

## 0.3.85
- Push-Benachrichtigung nach erfolgreichem Import ergänzt. Die Nachricht enthält die Dashboard-Zeile `Effektiver Tageswert: …, geplant war: …`.
- Home-Assistant-API-Zugriff für den Notify-Service aktiviert; Standard ist `mobile_app_iphone_Hauptprofil`.

- 0.3.84: In Planung bearbeiten zusätzlichen Button „Sollzeit planen“ ergänzt; setzt die Planung des Tages direkt auf die Sollzeit (08:00–15:58, mittwochs 08:00–15:56).
## 0.3.83 - Planned-vs-actual text on overview
- In der Übersicht zeigen gebuchte Tage mit vorhandener Planung jetzt zusätzlich den geplanten Tageswert an: "Effektiver Tageswert: X, geplant war: Y".

## 0.3.82
- Gemini/Ollama-Prompt für Ein-Zeilen-Tage geschärft: Restpausenabzug darf nur gesetzt werden, wenn wirklich eine eigene Restpausenabzug-/Zuschlag-Zeile oder ein eigener Rohwert sichtbar ist.
- Zusätzliche Sicherheitslogik: Wenn der erkannte Restpausenabzug exakt der Dauer eines sichtbaren Arbeitsblocks oder bei Ein-Zeilen-Tagen der gesamten Arbeitszeit entspricht, wird er als verdächtig behandelt und per OCR gegengeprüft.

## 0.3.78
- Buchungen zeigt Arbeitstage jetzt im selben Kartenstil wie Übersicht.

- 0.3.77: „Tag löschen“ im Arbeitstag-Bearbeiten optisch in dieselbe Aktionszeile wie „Abbrechen“ verschoben; keine Extra-Zeile mehr unter dem Formular.
- 0.3.76: Arbeitstag-Bearbeiten hat jetzt einen direkten „Tag löschen“-Button; bestehende Buchungstage lassen sich mit Bestätigung direkt aus dem Formular löschen.
- 0.3.75: Sollzeit-Buchen-Button im Plan-Bearbeiten repariert; keine verschachtelten Formulare mehr, sodass der Klick wieder zuverlässig einen Arbeitstag mit Sollzeit anlegt.
## 0.3.74 - Sollzeit-Button aus Übersicht in Plan-Bearbeitung verschoben
- Der Button "Sollzeit buchen" wurde aus den Tageskarten der Übersicht entfernt.
- Beim Bearbeiten eines geplanten Tages gibt es jetzt stattdessen einen eigenen Button "Sollzeit buchen".

## 0.3.73 - Planung in Übersicht verbessert
- Übersicht zeigt bei geplanten Tagen jetzt die echten Zeitblöcke aus der Planung statt nur Start- und Endzeit als Gesamtzeitraum.
- Geplante Tageskarten in der Übersicht farblich stärker hervorgehoben.
- Der Text "Geplant" ist in der Übersicht jetzt unterstrichen.

## 0.3.72 - Nachlauf-Budget rechnet Nachlaufen gegen Restpausenabzug
- Nachlauf-Budget wird jetzt als importierter Restpausenabzug minus Nachlauf / manuelle Korrektur geführt.
- Telegram-Nachlauf reduziert dadurch nicht nur den effektiven Tageswert, sondern auch das verbleibende Nachlauf-Budget.
- Beim manuellen Speichern eines importierten Tags wird das Nachlauf-Budget automatisch neu berechnet, solange das Budget-Feld nicht bewusst separat überschrieben wurde.
- Konto-/Budget-Summen verwenden jetzt das tatsächliche Nachlauf-Budget statt nur den importierten Restpausenabzug.

## 0.3.71 - Import-Transaktion gegen Telegram-Follow-up-Fehler gehärtet
- Import-Datensatz wird direkt nach dem Verschieben des Bildes in `processed` sofort committed.
- Doppelte Nachlauf-Verarbeitung nach `analyze_import_and_store()` in `scan_import_dir()` entfernt.
- Doppelte Nachlauf-Verarbeitung nach `analyze_import_and_store()` in `retry_pending_imports()` entfernt.
- Dadurch bleibt ein neuer Import auch dann in der Web-App sichtbar, wenn die Telegram-Nachlauf-Verarbeitung im selben Lauf einen Fehler wirft.

## 0.3.69 - Telegram reply queue fix

- Telegram-Nachlauf-Antworten werden nicht mehr verworfen, wenn der Import/Arbeitstag beim Antworten noch nicht fertig verarbeitet ist.
- Gültige Antworten wie `22` oder `17:32-18:05` werden zunächst vorgemerkt und nach erfolgreicher Analyse automatisch in den passenden Tag übernommen.
- Nach erfolgreicher Screenshot-Analyse werden offene Telegram-Nachlauf-Antworten sofort nachgezogen.

## 0.3.68
- Telegram-Nachlauf robuster zugeordnet: Wenn Dateiname oder Import-ID in der Follow-up-Zuordnung fehlen, wird jetzt der zeitlich passende aktuelle Telegram-Import als Fallback gesucht.
- Dadurch sollen Minuten-Antworten nach der Bot-Rückfrage auch dann noch im richtigen Tag landen, wenn die Import-Prompt-Aktion vor der vollständigen Verarbeitung des Bildes ausgelöst wurde.

## 0.3.67
- Telegram-Follow-up-Suche robuster gemacht: Antworten finden offene Rückfragen jetzt auch dann, wenn chat_id/user_id zwischen Bild und Text unterschiedlich übergeben werden.
- Telegram-Reply-API akzeptiert zusätzlich reply/content/data als Textfelder, damit Home-Assistant-Events toleranter verarbeitet werden.

## 0.3.66
- Telegram-Follow-up repariert: fehlende Auflösung von Import -> Arbeitstag ergänzt.
- Neuer Hilfsparser liest das erkannte Datum direkt aus der Import-Zusammenfassung.
- Telegram-Antworten landen dadurch wieder beim richtigen Tag statt wirkungslos zu verpuffen.

## 0.3.65 - Telegram reply race fix
- Telegram-Nachlauf wird nicht mehr versehentlich einem älteren Import zugeordnet, wenn die Rückfrage vor dem vollständigen Bildimport ausgelöst wurde.
- Bei der Telegram-Rückfrage wird kein Fallback mehr auf den zuletzt importierten Screenshot verwendet.
- Vor der Verarbeitung einer Telegram-Antwort werden wartende Importe erneut gescannt.
- Wenn der passende Screenshot oder Arbeitstag noch nicht fertig verarbeitet ist, wird nichts falsch verbucht.

- 0.3.64: Überblick/Buchungen rechnen Tageswerte wieder konsistent mit dem geöffneten Arbeitstag; vorhandene manuelle Nachlaufwerte im Tag werden in Übersicht und Buchungen nicht mehr zusätzlich durch datumsbezogene Nachlauf-Buchungen doppelt abgezogen.
# Changelog

- 0.3.64: Telegram-Nachlauf wird beim Antworten erneut sauber dem richtigen Import/Tag zugeordnet; Nachlauf bleibt fachlich ein Minuswert in der Oberfläche, wird intern aber korrekt als Abzug berechnet.
- 0.3.61: Telegram-Nachlauf-Rückfrage per API ergänzt; Bild-Import kann automatisch eine Bot-Rückfrage auslösen und eine Antwort mit Minuten oder Zeitblock direkt als Nachlauf-Buchung übernehmen.
- 0.3.60: Automatische Neuversuch-Warteschlange bei Gemini-Limit/Überlastung ergänzt; letzter Analysezeitpunkt wird im Import und im Tag-Bearbeiten angezeigt; README und DOCS auf den aktuellen Funktionsstand gebracht.
- 0.3.59: Sollzeit-Buchung setzt jetzt feste Standardzeiten (08:00–15:58, mittwochs 08:00–15:56) statt leerer Zeiten; Import-Bildausschnitt wird auch im Tag-Bearbeiten angezeigt.
- 0.3.58: Bearbeiten von Arbeitstagen verursacht keinen Internal Server Error mehr; fehlende Funktion zum Auslesen der Arbeitsblöcke aus dem Formular ergänzt.
- 0.3.57: Import-Update löscht fälschlich stehengebliebene Restpausenabzüge wieder sauber und synchronisiert Import-Restkomponente/Budget beim Bearbeiten.
- 0.3.54: Anzeige/Speicherung der Arbeitsblöcke bleibt beim sichtbaren Endzeitpunkt; Restpausenabzug wirkt nur intern auf die Berechnung.
