## 1.6.48 — 24.09.2026, 00:14 CEST

- Die drei echten Publish-Diagnosen belegen, dass Kleinanzeigen’ langsamer Astro-/Legacy-Wechsel noch aktiv fortschreitet: Kategorie und „Weiter“ wurden korrekt bedient, bevor der in 1.6.46 neu eingeführte Gesamt-Watchdog nach 120 Sekunden den Vorgang zu früh abbrach. Der Bot erhält daher jetzt bis zu acht Minuten pro Veröffentlichungsversuch.
- Der übergeordnete Manager-Timeout beträgt neun Minuten und liegt damit bewusst über dem Bot-Watchdog einschließlich der begrenzten ZIP-Erstellung. Echte Hänger enden weiterhin sicher mit mindestens einem bereinigten Diagnose-ZIP; langsame, aber funktionierende Anzeigenabläufe werden nicht mehr abgeschnitten.

## 1.6.47 — 23.09.2026, 23:56 CEST

- Der Manager erzeugt jetzt vor jedem fehlgeschlagenen Bot- oder Login-Start ein eigenes, atomar geschriebenes Diagnose-ZIP unter `/share/Kleinanzeigen/debug` – auch wenn der Bot nie bis `publish_ad` oder zu seinem eigenen Watchdog gelangt.
- Die Pakete enthalten den bereinigten Manager- und Vorgangsstatus, Anzeigendaten, Bot-Konfiguration, Output- und Log-Ausschnitt, Exitcode/Signal/Timeout, Chromium-Prozessstatus und Laufzeitdaten. Browserprofil, Local Storage, Cookies, E-Mail-Anmeldung, Passwörter, Tokens und andere Geheimnisse werden nicht übernommen.
- Der bisher endlose sichere Vorab-Retry für „Bot/Login-Prüfung fehlgeschlagen“ ist auf drei sichtbare Versuche begrenzt. Nach dem dritten Fehlschlag wird der Vorgang eindeutig beendet und nicht erneut durch den Scheduler gestartet; das zuletzt erzeugte ZIP ist in der Historie benannt.
- Der bestehende Bot-Watchdog bleibt aktiv und verwendet denselben Manager-Diagnosepfad als zweite, unabhängig vom Browser funktionierende Sicherung.

## 1.6.46 — 23.09.2026, 23:18 CEST

- Ein kompletter Veröffentlichungsversuch erhält einen harten 120-Sekunden-Watchdog. Bleibt Chromium/nodriver innerhalb eines einzelnen Schritts hängen, wird der Versuch beendet statt bis zum bisherigen 10-Minuten-Prozesslimit weiterzulaufen; ein Watchdog-Hänger wird in diesem Lauf bewusst nicht blind erneut versucht.
- Das Publish-Debug-ZIP wird bei einem Fehler zunächst sofort mit Zusammenfassung und Exception angelegt und danach um DOM-Zustand, bereinigte Konfiguration, Laufzeitdaten, Log-Ausschnitt und – sofern der Browser noch reagiert – Screenshot ergänzt. Damit bleibt selbst bei einem während der Diagnose blockierenden Browser mindestens ein verwertbares ZIP erhalten.
- Browser-/Screenshot-Diagnosen sind selbst zeitlich begrenzt. Als zweite Sicherung erzeugt der Manager nach 240 Sekunden einen eigenen bereinigten Watchdog-ZIP mit partiellem Bot-Output, falls der Bot-Prozess seinen internen Watchdog nicht mehr ausführen kann.

## 1.6.45 — 23.09.2026, 22:40 CEST

- Funktional wieder auf dem vollständigen Stand von 1.6.43; die zwischenzeitliche 1.6.44-Rollback-Version wird damit regulär durch eine höhere Version ersetzt.
- Navigation zum Astro-Inserierformular und zur Startseite toleriert unvollständig ladende Drittanbieter-Ressourcen, sobald der benötigte Kleinanzeigen-DOM tatsächlich bedienbar ist; dadurch entfallen unnötige komplette Bot-Neustarts nach `readyState`-Timeouts.
- Die Kategorieauswahl wartet bis zu 25 Sekunden auf die schwere Legacy-Kategorieseite, prüft nach jedem Klick den tatsächlichen Navigationsfortschritt und behandelt einen beim Hash-/Seitenwechsel verlorenen CDP-Kontext nicht mehr als sicheren Fehlklick. Auch der Rückweg über „Weiter“ wird anhand des wieder nutzbaren Formulars bestätigt.
- Veröffentlichungs- und Login-Diagnosen werden wie bei Vinted als jeweils ein bereinigtes ZIP unter `/share/Kleinanzeigen/debug` erzeugt. Enthalten sind strukturierter Seitenzustand, Fehler, bereinigte Bot-/Anzeigendaten, Laufzeitinformationen, Log-Ausschnitt und Screenshot; Passwörter, E-Mail-Anmeldung, Tokens, Cookies, Browserprofil und Local Storage werden nicht übernommen. Die früheren losen `source`, `staged`, `bot-config`, HTML-, JSON- und Log-Dateien werden nicht mehr dauerhaft erzeugt.

## 1.6.44 — 23.09.2026, 22:03 CEST

- Funktionaler Rollback auf den Stand von 1.6.39: App-Code, Oberflächen und Kleinanzeigen-Bot-Verhalten entsprechen wieder dem zuletzt stabilen 1.6.39-Stand.
- Die reine Docker-Mehrarch-Build-Korrektur aus 1.6.41 bleibt erhalten, damit amd64 und aarch64 weiterhin gebaut werden können.
- Die Änderungen aus 1.6.40, 1.6.42 und 1.6.43 wurden aus dem Laufzeitcode zurückgenommen; bestehende Daten und Persistenzpfade bleiben unverändert.

## 1.6.43 — 23.09.2026, 21:28 CEST

- Ein Seitenlade-Timeout beim neuen Astro-Inserierformular löst keinen kompletten Veröffentlichungs-Neustart mehr aus, wenn das Formular bereits vollständig bedienbar im DOM vorhanden ist.
- Die Kategorieauswahl bleibt in der von Kleinanzeigen eröffneten Formularsitzung und arbeitet mit stabilen IDs/DOM-Abfragen statt der fehleranfälligen XPath-Suche; dadurch werden die beobachteten CDP-Fehler `No search session with given id found (-32000)` vermieden.
- Der abschließende Veröffentlichen-/Speichern-Klick nutzt ebenfalls den aktuellen React-DOM statt XPath; verschwindet der Browserkontext während des Klicks, wird nicht blind erneut veröffentlicht und damit ein mögliches Duplikat vermieden.

## 1.6.42 — 23.09.2026, 20:36 CEST

- Die persönliche Profilauswahl zeigt wieder lokal aus Home Assistant ermittelte Personennamen statt der technischen Schlüssel `primary` und `secondary`; die internen IDs und Lesestände bleiben unverändert.
- In Nachrichten können alle aktuell ungelesenen Unterhaltungen eines Profils mit einem Klick als gelesen markiert werden.
- In der Live-Ansicht zeigen heute und gestern eingestellte Anzeigen zusätzlich die jeweilige Uhrzeit.
- Unter „Nicht veröffentlicht“ ist die Mehrfachauswahl direkt sichtbar; mehrere Entwürfe lassen sich markieren und gemeinsam inklusive ihrer lokalen Bilder löschen.

## 1.6.41 — 23.09.2026, 20:11 CEST

- Docker-Basisimage für den Mehrarch-Build verbindlich festgelegt, damit amd64 und aarch64 wieder gebaut und veröffentlicht werden können.

## 1.6.40 — 23.09.2026, 18:26 CEST

- Bestehende Anzeigen lassen sich im Aktionsmenü als reimportierbare `.kaanzeige` exportieren. Das Paket übernimmt die Importfelder und kopiert alle vorhandenen Anzeigenbilder in derselben Reihenfolge bytegenau mit; reine Laufzeitdaten bleiben ausgeschlossen.

## 1.6.39 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 1.6.37 — 18.09.2026, 20:51 CEST

- App-Code erstmals bereinigt in das zentrale GitHub-Repository übernommen. Laufzeitdaten und persönliche Einstellungen bleiben ausschließlich in Home Assistant.

# Changelog
