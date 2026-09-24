## 0.1.13 — 24.09.2026, 19:31 CEST

- BARF-Konfiguration und Urlaubsmodus liegen jetzt vorrangig im geschützten App-Datenspeicher. Bestehende Daten aus `/share/Barf` werden beim ersten Start übernommen und anschließend nur noch zusätzlich dorthin gespiegelt.
- Jede Speicherung erfolgt atomar. Damit kann ein abgebrochener Schreibvorgang weder eine halbe Konfiguration noch wieder Standardwerte erzeugen.

## 0.1.12 — 18.09.2026, 21:50 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 0.1.11

- Gekochter Reis wird nicht mehr als eigene Zutat geführt.
- Roher Reis ist im normalen Modus und im Urlaubsmodus direkt bearbeitbar.
- Alte gespeicherte Werte mit gekochtem Reis werden beim Laden automatisch in rohen Reis umgerechnet.
- Tagesportionen werden weiterhin ohne Omega-3-Kapseln berechnet.

## 0.1.10

- Urlaubsmodus kann separat bearbeitet und gespeichert werden.
- Tagesportion je Hund ergänzt: Gesamtgewicht ohne Omega-3-Kapseln geteilt durch die Anzahl der Tage.

## 0.1.9

- Halbe Tage ergänzt: Tagesanzahlen wie 7,5 oder 7.5 funktionieren im Normalmodus und im Urlaubsmodus.

## 0.1.8

- Fehler im Urlaubsmodus behoben: Geänderte Tage werden beim Berechnen nicht mehr durch alte URL-Werte auf 30 zurückgesetzt.

## 0.1.7

- Urlaubsmodus ergänzt: Rind/Pansen/Innereien werden durch Hähnchen ersetzt.
- dog_two bleibt im Urlaubsmodus mit Zusatzfett.
- /health ergänzt.
