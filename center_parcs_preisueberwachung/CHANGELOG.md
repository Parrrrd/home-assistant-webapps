## 0.3.27 — 24.09.2026, 14:53 CEST

- Der Preisverlauf ist ruhiger: dünne Anbieterlinien bleiben auch bei vielen identischen Prüfungen glatt; Punkte erscheinen nur noch an tatsächlichen Preisänderungen. Wiederholte unveränderte Stundenwerte erzeugen keine Punktwolke mehr.
- Nicht verfügbare Anbieter werden im Diagramm als echte Lücke behandelt und nicht mehr versehentlich als 0-€-Wert in die Y-Achse aufgenommen. Die Achse richtet sich nur nach real vorhandenen Preisen.
- Die Tabelle kennzeichnet den ersten Wert nach einem Preissprung direkt in der Anbieterzelle: Preiserhöhungen rot mit `↑ Betrag`, Preissenkungen grün mit `↓ Betrag`, zum Beispiel `496 € ↑ 26 €`. Unveränderte Folgeprüfungen bleiben ohne Zusatz.
- Die drei aktuellen Anbieterpreise rechts am Diagramm und der feste Vergleich aller Anbieter bleiben erhalten.

## 0.3.26 — 24.09.2026, 14:31 CEST

- Der Preisverlauf nutzt jetzt die gewählte kompakte Punktdarstellung: alle Prüfzeitpunkte erscheinen als farbige Punkte, die Verbindungslinien treten deutlich in den Hintergrund und echte Preisänderungen werden zusätzlich mit einem Ring markiert. Die jeweils letzten Anbieterpreise stehen direkt rechts am Diagramm.
- Die Umschalter oberhalb des Verlaufs wurden entfernt. Der Verlauf zeigt jetzt immer gleichzeitig Center Parcs direkt, Felicitas und Benefits; nur die kompakten Hinweise „Aktuell“ und „Bisher günstigster“ bleiben stehen.

## 0.3.25 — 24.09.2026, 12:19 CEST

- Preisänderungs-Pushs sind jetzt bewusst sehr kurz: Der Titel nennt den jeweiligen Park als `CP <Park>: Preis gefallen/gestiegen`; der Nachrichtentext enthält nur Haustyp, kompakten Zeitraum und die vorzeichenbehaftete Differenz, zum Beispiel `Premium-Ferienhaus - 15. - 18.01 -30€`.
- Der bestehende Deep-Link zum betroffenen Preisverlauf und der Vergleich aller Anbieter bleiben unverändert.

## 0.3.24 — 24.09.2026, 11:28 CEST

- Preisänderungs-Pushs enthalten jetzt den betroffenen Haustyp, Zeitraum, alten und neuen Bestpreis, die Differenz sowie den aktuell günstigsten Anbieter. Ein Tipp auf die Push öffnet direkt den Anbieter-Preisvergleich des betroffenen Aufenthalts in der WebApp statt nur eine allgemeine Übersichtsadresse.
- Die WebApp merkt sich ausschließlich ihre zuletzt direkt verwendete Basisadresse auf Port 8102, damit automatische Pushs auf die lokale WebApp zurückführen können; als neutrale lokale Rückfalladresse dient `homeassistant.local:8102`.
- „Verlauf“ startet grundsätzlich mit dem Vergleich aller Anbieter. Der reine Bestpreis-Verlauf bleibt als Umschalter verfügbar.
- Die Übersicht zeigt die letzte Bestpreisänderung mit Pfeil und Betrag direkt am betroffenen Reisezeitraum und zusätzlich am betroffenen Haustyp; unter „Alle ansehen“ wird auch der exakt betroffene Aufenthalt markiert.

## 0.3.23 — 24.09.2026, 10:23 CEST

- Preisänderungen lösen pro Reise nur noch eine kurze Push-Nachricht für den Gesamtbestpreis aus, zum Beispiel „15.–18. Jan. +120 €“.
- Der Push öffnet die betreffende Reise in der Übersicht; der aktuelle Bestpreis zeigt dort die letzte Änderung unaufdringlich direkt darunter.
- Der Verlauf startet nun mit dem klaren Bestpreis-Verlauf; der detaillierte Anbieter-Vergleich bleibt per Umschalter verfügbar.
- Unter „Alle ansehen“ hat jeder exakte Aufenthalt einen eigenen Verlauf. Neue Verlaufspunkte werden nur bei Preis- oder Statusänderungen gespeichert.

## 0.3.22 — 24.09.2026, 00:32 CEST

- Center-Parcs-Direktpreise verwenden jetzt den im exakten Suchlink sichtbaren Gesamtpreis inklusive Steuer statt eines Vorsteuerfelds.
- Jeder erfolgreich geprüfte Aufenthalt wird sofort gespeichert und angezeigt, während weitere Zeiträume noch geprüft werden.
- Anbieterpreise werden fest stündlich geprüft; unter jedem Preis steht nun die relative Aktualisierungszeit.
- Der Push-Dienst für Patricks iPhone ist auf `notify.mobile_app_iphone_patrick` korrigiert.

## 0.3.21 — 23.09.2026, 22:14 CEST

- Teilweise erfolgreiche Zeitraum-Prüfungen übernehmen neue Ergebnisse jetzt sofort; nur technisch offene Aufenthalte bleiben als nicht aktuell markiert.
- „Alle ansehen“ kennzeichnet aktuelle, unvollständige und veraltete Zeiträume und erlaubt die gezielte Wiederholung nur des betroffenen Aufenthalts.
- Günstigste Preise und Zeiträume werden ausschließlich aus aktuell vollständig geprüften Aufenthalten ermittelt.
- Preis- und Haustyp-Links öffnen eine vollständige Center-Parcs-Suche mit exaktem Zeitraum, Belegung und Haustyp statt des sitzungsanfälligen Detailkontexts.
- Jede einzelne Zeitraum-Prüfung hat ein hartes Zeitlimit; doppelte Gesamtprüfungen werden nicht mehr hintereinander aufgestapelt.
- Die bestehende Preisermittlung bleibt in dieser Version bewusst unverändert.

## 0.3.20 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.
