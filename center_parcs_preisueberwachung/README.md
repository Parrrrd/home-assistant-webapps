# Center Parcs Preisüberwachung

Home-Assistant-App zur Verwaltung mehrerer Center-Parcs-Reisezeiträume und zur
Preisbeobachtung einzelner, eindeutig gekennzeichneter Unterkünfte.

## Funktionen

- unter „Neue Suche“ zwischen festem Reisedatum und flexiblem Suchzeitraum wählen
- bei flexibler Zeitraum-Suche 3, 4 oder 7 Übernachtungen festlegen; pro Haustyp wird nur dessen günstigster Aufenthalt innerhalb des Fensters angezeigt
- Ferienpark, Anreise, Abreise, Erwachsene, Kinderalter und Haustiere flexibel ändern
- eigener Zwei-Monats-Kalender mit allen zukünftigen Reisetagen wie auf der Center-Parcs-Seite
- bearbeitbare Standardbelegung für neue Suchen; voreingestellt sind 2 Erwachsene, Kinder im Alter von 5 und 8 Jahren sowie 2 Haustiere
- fertigen Center-Parcs-Ergebnislink übernehmen
- alle 28 Center-Parcs-Ferienparks nach Ländern gruppiert auswählen
- alle verfügbaren Unterkünfte laden und einzelne Haustypen auswählen
- pro Reise Center Parcs direkt, Felicitas und Corporate Benefits getrennt prüfen und den günstigeren Preis hervorheben
- Partnerangebote über die jeweiligen Felicitas-/Benefits-Suchseiten mit den von Center Parcs verwendeten Partner-Portal-Codes prüfen; Kartenbeschriftungen wie „Frühbucher“ verändern die Anbieterzuordnung nicht
- Partnerangebote bei jeder manuellen und automatischen Prüfung für den exakten Ferienpark und Reisezeitraum neu kontrollieren
- für nicht verfügbare Felicitas- oder Benefits-Zeiträume „Aktuell nicht im Angebot“ statt eines fremden oder geschätzten Preises anzeigen
- beim Bearbeiten sofort weitere zuletzt gefundene Haustypen auswählen
- passendes Vorschaubild direkt an jeder Unterkunft anzeigen
- Hausbild und Hausname öffnen direkt die Center-Parcs-Hausinformationen mit Bildern, Grundriss und Ausstattung
- Reiseordner frei wählen, neue Ordner beim Speichern anlegen und bestehende Beobachtungen jederzeit in einen anderen Ordner verschieben
- mehrere Reisezeiträume nach Anreisedatum sortiert verwalten und wieder löschen
- kompakte Zeitraum-Vergleichsansicht mit direkter Hervorhebung des aktuell günstigsten Urlaubs
- große Unterkunftsdetails einzeln auf- und zuklappen
- Preis, ursprünglichen Preis, Rabatt, Haustierkosten und Restverfügbarkeit speichern
- getrennte Preisverläufe für Center Parcs direkt, Felicitas und Benefits je Unterkunft anzeigen
- automatische Prüfung im einstellbaren Intervall; flexible Beobachtungen durchsuchen bei jeder Prüfung wieder das gesamte gespeicherte Zeitfenster
- eigener Einstellungsbereich für Standardbelegung und Prüfintervall
- Push-Mitteilungen bei Preisänderungen, neu verfügbaren/wegfallenden Partnerangeboten und bei flexiblen Beobachtungen auch bei einem Wechsel des günstigsten Zeitraums
- eine Home-Assistant-Entität je Reise sowie eine zusammenfassende Entität anlegen

## Home-Assistant-Entitäten

- `sensor.center_parcs_preisueberwachung`
- pro Reise eine dynamische Entität nach dem Muster `sensor.center_parcs_<name>_<kennung>`

Push-Mitteilungen werden fest an `notify.mobile_app_iphone A` gesendet. Das Ziel ist nicht mehr änderbar; über „Test-Push senden“ kann die Zustellung geprüft werden.

Die Weboberfläche steht sowohl über Home-Assistant-Ingress als auch direkt über
Port `8102` zur Verfügung.

## Version 0.3.8

- Partnerseiten laden jetzt auch Unterkunftskarten nach, die Center Parcs erst hinter „Mehr Ergebnisse anzeigen“, „Mehr Unterkünfte anzeigen“ oder „Mehr anzeigen“ einblendet.
- Das Nachladen wird wiederholt, bis keine weiteren Karten mehr hinzukommen; dadurch können auch Häuser hinter der ersten 10er-Liste Felicitas-/Benefits-Preise erhalten.
- Die bestehende Partner-, Kalender-, Preis- und Ordnerlogik aus 0.3.7 bleibt unverändert.
- Diagnose-Logs zeigen, wie oft nachgeladen wurde und wie viele Unterkunftskarten danach vorhanden sind.


## 0.3.7
- Felicitas- und Benefits-Preissuche bleibt auf der jeweiligen Partner-Aktionsseite statt auf der allgemeinen `/search`-Seite.
- Corporate-Benefits-Treffer mit regulären Center-Parcs-Aktionskennzeichnungen wie Frühbucher/Last Minute werden nicht mehr als Benefits-Preis akzeptiert.
- Wenn der Partnerkalender einen Anreisetag bestätigt, aber keine exakt passende Unterkunft gefunden wird, wird nicht mehr fälschlich „Aktuell nicht im Angebot“ ausgegeben.
- Erweiterte Diagnose-Logs für Partnerpreis-Kandidaten.

## Version 0.3.19

- Zeitraum-Suche: Auswahl der Aufenthaltsdauer verständlicher benannt als „Wochenende • 3 Übernachtungen“, „Wochenmitte • 4 Übernachtungen“ und „Woche • 7 Übernachtungen“.
- Die technische Logik bleibt unverändert bei 3, 4 oder 7 Übernachtungen.

## Version 0.3.18

- Zeitraum-Suche lädt zuerst nur die Haustypen und speichert die Beobachtung sofort.
- Die vollständige Prüfung des gesamten Suchfensters läuft anschließend im Hintergrund und wird nicht mehr an die Antwortzeit der Weboberfläche gekoppelt.
- Fortschritt der Hintergrundprüfung wird gespeichert und in der Übersicht angezeigt.
- Einzelne technisch problematische Aufenthalte oder Anbieter brechen die gesamte Zeitraum-Prüfung nicht mehr ab.
- Nach der ersten vollständig abgeschlossenen Zeitraum-Prüfung wird einmalig eine Push-Benachrichtigung mit dem günstigsten Treffer gesendet.
- Automatische Folgeprüfungen durchsuchen weiterhin jedes Mal das komplette Suchfenster. Bei unvollständigen Folgeprüfungen bleiben die zuletzt vollständig ermittelten Bestpreise bestehen.

## Version 0.3.15

- Neue Suche enthält die Auswahl „Festes Datum“ oder „Zeitraum“.
- Zeitraum-Suchen unterstützen 3, 4 oder 7 Übernachtungen.
- Nur Aufenthalte, deren An- und Abreise vollständig innerhalb des gewählten Suchfensters liegen, werden berücksichtigt.
- Jeder Haustyp erhält unabhängig seinen eigenen günstigsten Termin und Anbieter.
- Automatische Prüfungen scannen immer wieder das vollständige Zeitfenster und nicht nur den zuletzt günstigsten Termin.
- Partnerkalender werden pro Zeitraum-Prüfung nur einmal geladen und anschließend für alle möglichen Anreisen wiederverwendet.
