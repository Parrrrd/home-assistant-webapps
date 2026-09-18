# WebApp-Updater – Versionsverlauf

Die aktuelle Version steht oben.

## 0.1.9 — 18.09.2026, 21:58 CEST

- Nach einer GitHub-Freigabe prüft der Updater standardmäßig alle 20 Sekunden statt nur einmal pro Minute. Der einstellbare Wert `check_interval_seconds` liegt zwischen 15 Sekunden und einer Stunde.

## 0.1.8 — 18.09.2026, 21:45 CEST

- Alle vorhandenen eigenen WebApps sind dem Updater zugeordnet. Beim ersten Erkennen wird jede App nur als Ausgangsstand registriert; erst eine spätere neue Version wird automatisch installiert.

## 0.1.7 — 18.09.2026, 21:14 CEST

- Die iPhone-Mitteilung wird ohne personenspezifischen Dienstnamen automatisch an einen verfügbaren mobilen Home-Assistant-Dienst gesendet.
 Jeder Eintrag enthält den Zeitpunkt der Freigabe auf GitHub.

## 0.1.6 — 18.09.2026, 13:21 CEST

- Jede Protokollmeldung enthält Datum und Uhrzeit.
- Fehlgeschlagene Home-Assistant-Updates enthalten die sichere Supervisor-Antwort statt nur eines allgemeinen HTTP-Fehlers.

## 0.1.5 — 18.09.2026, 13:07 CEST

- Eigene WebApps werden ausschließlich über ihre direkte Browser-Adresse geöffnet.

## 0.1.4 — 18.09.2026, 13:01 CEST

- Der Updater protokolliert installierte Versionen dauerhaft, sendet eine Mitteilung an einem eingerichteten iPhone und hält sich künftig selbst aktuell.

## 0.1.3 — 18.09.2026, 09:57 CEST

- Der Home-Assistant-Steuerzugriff wurde repariert; vorhandene lokale WebApps können automatisch aktualisiert werden.
