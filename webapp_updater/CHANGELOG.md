# WebApp-Updater – Versionsverlauf

Die aktuelle Version steht oben.

## 0.1.16 — 25.09.2026, 00:41 CEST

- Normale App-Updates werden nach dem geprüften Wiederherstellungspunkt wieder vom Supervisor selbst bis zum bestätigten Abschluss ausgeführt. Damit kann ein ablaufender Hintergrundjob-Eintrag kein erfolgreiches Update mehr endlos als offen erscheinen lassen.
- Nur das Selbst-Update des Updaters bleibt bewusst asynchron; die nach dem Neustart laufende neue Instanz bestätigt die Zielversion aus dem persistenten Vorgangszustand.

## 0.1.15 — 24.09.2026, 22:21 CEST

- Die Sicherungsprüfung unterstützt jetzt das aktuelle Home-Assistant-Backup-Detailformat, in dem enthaltene Apps als Objekte unter `addons` geliefert werden.
- Ein fehlgeschlagener oder nicht verifizierbarer Wiederherstellungspunkt sperrt weiterhin genau das betroffene Update, blockiert aber nicht mehr alle nachfolgenden vorgemerkten App-Updates.
- Die Tests decken sowohl Backup-Detail- als auch Übersichtsformat ab und sichern ab, dass die Warteschlange nach einem blockierten Update weiter verarbeitet wird.

## 0.1.14 — 24.09.2026, 21:47 CEST

- App-Updates werden über einen Supervisor-Hintergrundjob gestartet und bis zum tatsächlichen Abschluss überwacht; erst die bestätigte installierte Zielversion gilt als erfolgreich.
- Laufende oder nach einem Neustart fortgesetzte Updates bleiben persistent vorgemerkt. Warteschlange, Verlauf und iPhone-Mitteilung werden erst nach bestätigter Zielversion abgeschlossen.
- Bereits laufende Supervisor-Updates werden nicht blind erneut gestartet: Bei einer parallelen Installation wartet der Updater auf die Zielversion und lässt die Warteschlange bei einem Timeout erhalten.
- `vinted_carsten_erfassung` ist zusätzlich in der eingebauten Fallback-Zuordnung enthalten.

## 0.1.13 — 24.09.2026, 20:14 CEST

- Die Versionsprüfung akzeptiert auch ältere lokale Konfigurationsformate mit Einrückung, einfachen Anführungszeichen, Kommentar oder Windows-Zeilenende.
- Eine einzelne unlesbare Alt-App blockiert nicht mehr die Aktualisierung und den Wiederherstellungsschutz aller anderen Apps. Sie wird unverändert übersprungen und eindeutig protokolliert.

## 0.1.12 — 24.09.2026, 19:43 CEST

- Die Versionsprüfung läuft wieder mit der in Home Assistant verfügbaren `awk`-Variante. Damit wird die automatische Sicherungskette bei jeder Prüfung tatsächlich erreicht.

## 0.1.11 — 24.09.2026, 19:38 CEST

- Vor jedem automatischen Update einer verwalteten WebApp wird jetzt ein passwortgeschützter, geprüfter Home-Assistant-Wiederherstellungspunkt ausschließlich für diese App erstellt. Fehlt die Sicherung oder enthält sie nicht die App-Daten, bleibt das Update gesperrt.
- Die eingebaute Home-Assistant-Auto-Aktualisierung wird für verwaltete Apps deaktiviert, damit kein Update den geprüften Sicherungsschritt umgehen kann.

## 0.1.10 — 24.09.2026, 18:48 CEST

- Neue, ausdrücklich über den Google-Drive-Codeeingang freigegebene WebApps können erstmals automatisch in den lokalen Home-Assistant-App-Store übernommen und installiert werden.
- Die verwalteten WebApps werden aus `managed-webapps.json` im aktuellen GitHub-Stand gelesen. Neue Apps können dadurch registriert werden, ohne den WebApp-Updater für jede neue Zuordnung erneut bauen zu müssen.
- Neue Apps müssen als vollständiges ZIP mit Version `0.1.0`, passendem Slug, festem freien Host-Port und vorgesehenem GHCR-Imagepfad geliefert werden.
- Erstinstallationen besitzen eine eigene dauerhafte Warteschlange. Der Updater wartet auf ein installierbares Image, installiert die App über den Home-Assistant-Supervisor, aktiviert automatische Updates, startet die App, protokolliert den Vorgang und sendet eine Home-Assistant-Mitteilung.
- Die bisherige Update- und Bootstrap-Logik vorhandener Apps bleibt erhalten.

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
