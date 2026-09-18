## 0.1.33 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

# 0.1.31
- „＋ Serie eintragen“ bleibt jetzt oben dauerhaft erreichbar, auch wenn bereits Serienkarten angezeigt werden.
- Das Eingabeformular öffnet sich direkt und die alte Rohkartenliste wird nicht doppelt eingeblendet.

# 0.1.30
- Allgemeine Endtermin-Logik für jede laufende Serie, statt einzelner fest eingetragener Sonderfälle.
- Gemini liefert künftig Veröffentlichungsrhythmus und Folgen pro Termin; damit wird ein bestätigtes oder klar als voraussichtlich markiertes Staffelende angezeigt.
- Als Übergang nutzt die App bei bekanntem nächsten Termin und Restfolgen einen wöchentlichen Rhythmus, bis Gemini einen abweichenden Rhythmus bestätigt.

# 0.1.29
- Bestätigte deutsche Staffelfinal-Termine werden jetzt direkt aus dem veröffentlichten Episodenplan übernommen und nicht mehr nur von Gemini erwartet.
- Korrigiert die Anzeige für 9-1-1 Staffel 9, Chicago Med Staffel 11, Chicago Fire Staffel 14 und Fire Country Staffel 4.
- Alte Staffelfinal-Texte einer vorherigen Staffel können nicht mehr bei einer laufenden Staffel erscheinen.

# 0.1.28
- Jede Serienkarte kann jetzt einzeln mit „Bei Gemini prüfen“ aktualisiert werden, ohne den kompletten Serienplan neu zu prüfen.
- Die Einzelprüfung recherchiert gezielt den deutschen Sendetermin der letzten Episode der laufenden Staffel und übernimmt nur bestätigte Daten.
- Kein Termin wird aus Restfolgen oder einem Ausstrahlungsrhythmus geschätzt; bei fehlender Veröffentlichung bleibt der Hinweis transparent.

# 0.1.27
- Veraltete freie Staffelende-Schätzungen werden bei laufenden Staffeln nicht mehr angezeigt.
- Laufende Staffeln übernehmen nur noch ein plausibles, strukturiertes deutsches Staffelfinale.
- Wenn eine Einzelprüfung keine Antwort liefert, bleibt der letzte bestätigte Stand erhalten statt fälschlich „noch nicht geprüft“ zu erscheinen.

# 0.1.26
- Offene laufende Staffeln zeigen jetzt direkt das Datum der vollständig ausgestrahlten letzten deutschen Folge.
- Das Staffelfinale wird aus den belegten deutschen Episodendaten übernommen; ältere `estimated_complete`-Ergebnisse bleiben kompatibel.
- Wenn kein belastbares Staffelfinale veröffentlicht ist, wird dies ausdrücklich angezeigt.

# 0.1.25
- Staffelfinale und "Komplett verfügbar ab" Anzeige erweitert.
- Statuslogik für abgeschlossene Staffeln verbessert.
- Interne Prüfhinweise nicht mehr in der Oberfläche.

## 0.1.22

- Chicago P.D. Staffel 12 wird als bereits vollständig auf Deutsch ausgestrahlt (22/22) geschützt; Staffel 13 bleibt bis 02.09.2026 angekündigt.
- Fire Country Staffel 4 verwendet belastbar 20 Gesamtfolgen.
- Bereits belegte vollständige deutsche Staffeln können durch spätere schwächere Gemini-Antworten nicht mehr zurück auf "laufend" oder weniger Folgen fallen.
- Push-Baseline wird nach der Korrektur einmal still neu aufgebaut.

## 0.1.21
- 9-1-1 Staffel 9 nutzt als Schutz gegen US-Verwechslungen den veroeffentlichten deutschen Disney+-Episodenplan: am 23.08.2026 14/18, noch 4, naechste Folge 26.08.2026.
- Der Guardrail entwickelt sich anhand der bekannten deutschen Episodentermine bis zum Finale am 16.09.2026 automatisch weiter und markiert die Staffel erst danach als komplett.
- Chicago Med Staffel 11 verwendet die belastbare Gesamtfolgenzahl 21; bei 13 verfuegbaren Folgen werden daher 13/21 und noch 8 angezeigt.
- Push-Baseline wird einmalig ohne Alt-Pushs neu aufgebaut, damit die vorherige falsche 9-1-1-Komplettmeldung spaetere echte Ereignisse nicht blockiert.
- Keine Layout-Aenderungen; Gemini-Einzelpruefung und Dienstag/Freitag-Rhythmus bleiben unveraendert.

## 0.1.20
- Deutschen Veröffentlichungsstand strikt von US/Originalausstrahlung getrennt.
- Zukünftiger deutscher Folgentermin verhindert hart eine falsche "komplett"-Einstufung.
- Bestätigte zukünftige Staffeln bleiben als Zusatzinfo erhalten.
- Stabile bestätigte Fakten (Staffel-Gesamtzahl/Folgestaffel) gehen bei schwächeren Folgeläufen nicht mehr verloren.
- Gemini-Suche priorisiert exakte deutsche Folgenzahlen; zweite Suche schließt zuerst fehlende Gesamtfolgenzahlen.
- Push-Baseline wird nach der Korrektur einmalig ohne Alt-Pushs neu aufgebaut.

# 0.1.19

- Unbekannte Episodenzahlen bleiben `null`; vollständige Staffel nur bei belegtem `verfügbar == gesamt`.
- Zukunftsstarts können nicht mehr fälschlich als laufend einsortiert werden.
- Restfolgen werden nur aus belastbaren Zahlen berechnet.
- Gemini-Suche 1 fokussiert konkrete deutsche Episodentermine; weiterhin maximal zwei Suchen pro Serie.
- Begonnene alte Staffeln zeigen z.B. `ab Folge 20 verfügbar` statt irreführend nur `Staffel komplett`.
- Family Law wird aus dem falschen 0.1.18-Autoarchiv zurückgeholt. Autoarchiv verlangt künftig offiziellen Beleg plus zwei getrennte Prüftage.
- Push-Baseline wird einmal neu aufgebaut, ohne Alt-Pushs.
- Fehlgeschlagene Einzelprüfungen lassen Serien nicht mehr aus der Oberfläche verschwinden.
- `Warten` wird nur noch bei aktuell laufenden Staffeln angeboten.
- Automatische Gemini-Prüfung bleibt Dienstag/Freitag, manuell jederzeit.

# Changelog

## 0.1.18
- Automatischer Gemini-Check nur noch dienstags und freitags; manuelle Prüfung bleibt jederzeit möglich und weiterhin Serie für Serie mit sichtbarem Fortschritt.
- Empfehlungen samt Feedback-/Detailoberfläche aus dem aktiven Serienplaner entfernt; Gemini wird ausschließlich für vorhandene Serien genutzt.
- Gemini liefert Staffel-Fakten; Python bestimmt daraus die Kategorie und Restfolgen. Laufende spätere Staffeln haben Vorrang vor älteren komplett verfügbaren Staffeln.
- Plausibilitätsregeln verhindern u. a. "zukünftige Staffel gleichzeitig verfügbar", "komplett trotz X/Y" und "Serie beendet trotz bestätigter Folgestaffel".
- Neue Kategorien: Bereit zum Schauen, Läuft gerade, Aktuell auf Stand / angekündigt und Aktuell auf Stand.
- Benachrichtigungsoptionen für vollständig verfügbare Staffel, neue Staffel bestätigt, Staffel gestartet und Serienende; Starttermin optional. Neue Einzel-Folgen erzeugen keinen Push.
- Erster vollständiger 0.1.18-Check setzt nur die Push-Baseline, damit bekannte Ereignisse keine Benachrichtigungsflut auslösen.
- Pro Serie optional "Warten bis Staffel komplett"; vollständig gewordene Staffeln werden in "Bereit zum Schauen" hervorgehoben.
- Persönlicher Sehstand bleibt ausschließlich manuell und wird nie durch Gemini überschrieben.
- Prüfdaten und Plausibilitätskorrekturen werden in den Seriendetails sichtbar gemacht.

## 0.1.17

- Gemini prüft offene Serien jetzt einzeln statt als eine große Anfrage.
- Die Oberfläche zeigt währenddessen den Fortschritt, z. B. „Gemini prüft 3/9“.
- Pro Lauf werden höchstens 12 Serien geprüft; pro Serie wird genau eine Gemini-Anfrage gestellt.
- Der Prompt begrenzt die Recherche auf maximal zwei Google-Suchen pro Serie und verzichtet im Tagescheck auf Empfehlungen.
- Fehler bei einzelnen Serien blockieren nicht mehr die komplette Prüfung; nach mehreren Fehlern in Folge wird abgebrochen, um Anfragen zu sparen.

## 0.1.16

- Der Statuskasten laufender Staffeln heißt jetzt klar „Staffel fertig“ statt „Vollständigkeit“.
- Gemini wird ausdrücklich angewiesen, bei laufenden Staffeln die Gesamtfolgenzahl, die bereits deutsch verfügbaren Folgen und den erwarteten Termin der letzten Folge der aktuellen Staffel zu prüfen.
- Die Oberfläche rechnet „noch X Folgen“ jetzt auch selbst aus, wenn Gemini „Folgen 1–11 von 18“ liefert.

## 0.1.15

- Laufende Staffeln zeigen jetzt einheitlich „Weiter geht es“, „Noch offen“ und „Vollständigkeit“ im Statuskasten.
- Bestätigte oder angekündigte Folgestaffeln stehen zusätzlich unten bei den Karten neben der Online-Dauer.
- Gemini wird angewiesen, `remaining` einheitlicher zu liefern: komplett, noch X Folgen oder Anzahl noch unklar.

## 0.1.14

- Der eigene Sehstand hat Vorrang vor späteren Staffelankündigungen: offene verfügbare Staffeln bleiben im offenen Bereich.
- Angekuendigte Folgestaffeln werden als Zusatzinfo gezeigt, ohne Rückstände in „angekündigt“ zu verschieben.
- Empfehlungen sind anklickbar und zeigen Details, Quelle und eine Trailer-Suche.

## 0.1.13

- Gemini prüft jetzt ausdrücklich auch bestätigte Folgestaffeln, Produktionsstatus und erwartete Starts, wenn noch nichts deutsch streambar ist.
- Laufende Staffeln sollen nur noch als laufend erscheinen, wenn es nach dem heutigen Datum eine bestätigte nächste Folge gibt.
- Family Law und ähnliche Fälle werden über den Originalstatus der Serie geprüft; offiziell beendete und vollständig gesehene Serien werden abgelegt.
- Angekuendigte Staffeln bleiben sichtbar als „angekündigt“ statt grob als „nichts neu“.

## 0.1.12

- Gemini-Prüfungen haben jetzt zusätzlich ein hartes Gesamt-Zeitlimit, damit die Oberfläche nicht dauerhaft bei „prüft gerade“ stehen bleibt.
- Der Gemini-Prompt ist gestrafft, damit die Recherche schneller und zuverlässiger zurückkommt.
- Poster-Nachladen ist deutlich kürzer begrenzt und kann den Tagescheck nicht mehr lange ausbremsen.

## 0.1.11

- Laufende Gemini-Prüfungen können direkt in der Oberfläche abgebrochen werden.
- Ein App-Neustart räumt einen alten „Gemini prüft gerade“-Status zuverlässig auf.
- Abgebrochene Antworten werden verworfen; die maximale Wartezeit für Gemini ist auf zwei Minuten begrenzt.

## 0.1.10

- Offiziell beendete Serien werden nach dem Tagescheck automatisch abgelegt, wenn ihr die letzte Staffel vollständig gesehen habt.
- Nicht angekündigte, pausierende oder noch laufende Serien bleiben ausdrücklich offen.

## 0.1.9

- Eine Serie ohne neue Staffel bleibt zuverlässig unter „Noch nichts Neues“ – auch wenn Gemini die vorhandene, bereits gesehene Staffel beschreibt.
- Laufende Staffeln sind einheitlich als „läuft gerade“ markiert; der irreführende grüne Streambar-Hinweis entfällt dort.
- Online-Dauer ist bei jeder geprüften Staffel sichtbar: bestätigtes Ablaufdatum oder der klare Hinweis, dass der Anbieter keines veröffentlicht.
- Die doppelte offene Serienliste wird ausgeblendet, sobald die Tagesübersicht vorliegt.
- Will Trent ist korrigiert: bis Staffel 4 gesehen und weiterhin eine offene Serie.

## 0.1.8

- Der Tagescheck ist übersichtlich getrennt: komplette neue Staffeln, noch laufende Staffeln und Serien ohne Neuigkeit.
- Laufende Staffeln zeigen den nächsten bestätigten Termin und – nur wenn belastbar ableitbar – einen ausdrücklich als voraussichtlich markierten Fertigstellungstermin.
- Fortschritt, Streaminganbieter und bestätigte Ablaufhinweise bleiben direkt an der jeweiligen Serie verfügbar.

## 0.1.7

- Jede tägliche Serienkarte zeigt jetzt deutlich den persönlichen Stand („Bis Staffel … gesehen“ bzw. Folge).
- „Nächste Folge gesehen“ und „Stand ändern“ stehen direkt bei der jeweiligen Serienkarte.
- Nach einer vollständig gesehenen Staffel beginnt „Nächste Folge gesehen“ automatisch mit Folge 1 der nächsten Staffel.
- Ablaufdaten werden ausdrücklich recherchiert und bei bestätigten Angaben in Karte und Staffelansicht gezeigt.

## 0.1.6

- Täglicher Serien-Check nutzt die aktuelle Gemini-Interactions-Suche mit Google Search.
- Pro offener Serie gibt es einen Staffel-Überblick: deutsch streambar, derzeit nicht streambar oder angekündigt.
- Klick auf eine Serienkarte öffnet die zugehörigen Staffel- und Anbieter-Details.
- Serien- und Empfehlungsbilder werden automatisch ergänzt, wenn ein passendes Poster gefunden wird.
- Neue Kategorie „Für euch ausgesucht“ mit „Merken“, „Nicht interessant“ und „Schon gesehen“; die Rückmeldungen fließen in spätere Empfehlungen ein.
- Will Trent als komplett gesehen ergänzt und daher von künftigen Empfehlungen ausgeschlossen.

## 0.1.5

- Gemini darf für die Recherche mit Google-Suche bis zu drei Minuten antworten statt nach 55 Sekunden abzubrechen.
- Niedrige Denkstufe verkürzt die Recherchezeit.
- Die Oberfläche aktualisiert sich während einer laufenden Prüfung automatisch bis zum Ergebnis.

## 0.1.4

- Wechsel auf `gemini-3.6-flash`, weil `gemini-2.5-flash` für neue Gemini-API-Nutzer nicht mehr verfügbar ist.

## 0.1.3

- Gemini-Aufrufe schreiben für die gemeinsame Fehlersuche den HTTP-Status und die Antwort in die Add-on-Protokolle – ohne API-Schlüssel.

## 0.1.2

- Automatische Gemini-Prüfung bleibt auf einmal pro Kalendertag begrenzt.
- „Jetzt prüfen“ startet jederzeit eine zusätzliche manuelle Prüfung und zählt nicht gegen die automatische Tagesgrenze.
- Während einer laufenden Abfrage verhindert die App parallele Prüfungen.

## 0.1.1

- Gemini prüft mit Google-Suche maximal einmal pro Kalendertag auf neue Folgen, Staffeln und passende neue Serien.
- Der Schlüssel wird ausschließlich aus den Add-on-Einstellungen gelesen und nicht in der Serienliste gespeichert oder angezeigt.
- Gefundene Neuigkeiten werden im Bereich „Heute im Serienregal“ gespeichert und angezeigt.
- Auch ein fehlgeschlagener Tageslauf zählt als Tageslauf, damit niemals mehrfach am selben Tag abgefragt wird.

## 0.1.0

- Erste Version des Serienplaners mit den bereits genannten Serien.
- Schneller Fortschritt pro Serie: eine Folge abhaken oder Staffel/Folge direkt setzen.
- Getrennte Bereiche für laufende und eingestellte Serien.
- Vorbereitung für den täglichen Neuigkeiten-Check und spätere Empfehlungen.
