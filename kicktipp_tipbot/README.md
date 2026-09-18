# Kicktipp TipBot 0.1.42

Lokale Home-Assistant-WebApp für Kicktipp-Tippabgabe, Tabellen-Pushs und einen Fußball-Wettbewerbsmonitor.



## Neu in 0.1.42

- Doppelte Google-Drive-Uploads mit identischem Tippinhalt werden zusätzlich per Inhalts-Fingerprint dedupliziert. Dadurch wird derselbe Tipp-Satz nicht mehrfach an Kicktipp übertragen und erzeugt nur einen Erfolgs-Push.
- Matchcenter-Pushsteuerung erweitert: Tore, Karten, 30-Minuten-Hinweis, Halbzeit und Spielende lassen sich pro Spiel steuern; zusätzlich gibt es „Benachrichtigungen für genau dieses Spiel ausschalten“. Die Steuerung bleibt auch während eines Live-Spiels sichtbar.
- Für VfL Osnabrück und Bayer 04 Leverkusen ist der 30-Minuten-Hinweis standardmäßig aktiv. Tore bleiben für beide Favoriten standardmäßig aktiv; HZ/Ende folgen weiterhin der bestehenden Wettbewerbslogik und können pro Spiel unterdrückt werden.
- Torschützen-Erkennung robuster: Kicktipp-Zwischenstände werden direkt aus den Torereignissen übernommen; falls `score_after` fehlt, wird der letzte Torschütze nur dann verwendet, wenn die Ereignisanzahl exakt zum aktuellen Spielstand passt. API-Football besitzt denselben abgesicherten Fallback.

## Neu in 0.1.41

- Im Kicktipp-Bereich zeigt die Weboberfläche jetzt einen sichtbaren **Automatischer-Import-Status** mit letztem Drive-Check, gefundenen JSON-Dateien, neuen Downloads, Drive-Fehlern, letzter Datei, Drive-ID und Importstatus.
- Fehlgeschlagene Google-Drive-Datei-IDs werden direkt angezeigt.
- Über **Erneut versuchen** kann eine fehlgeschlagene Drive-ID gezielt aus der Fehlerliste freigegeben und unmittelbar neu importiert werden. Bereits erfolgreich verarbeitete IDs bleiben geschützt und können nicht versehentlich doppelt übertragen werden.
- Der Retry prüft vorab, ob die Quelldatei noch im konfigurierten Drive-Ordner vorhanden ist, startet sofort einen Drive-Sync und verarbeitet neu geladene Importdateien direkt.

## Neu in 0.1.40

- Hotfix: verwaisten Frontend-Aufruf `openPendingMatchIfReady()` aus dem 0.1.39-Redesign entfernt. Dadurch erscheint im Tagesfeed kein JavaScript-Fehler mehr und die nachfolgenden UI-Aktualisierungen laufen vollständig weiter.
- Fußball-Startseite erneut grundlegend beruhigt: keine CL/EL/Conference-Filterchips mehr. Stattdessen eine klare Tagesübersicht mit Spielanzahl, Live-/Beendet-Status und automatisch gruppierten Wettbewerben.
- iPhone-/Mac-Layout reduziert: kompaktere Tagesnavigation, ruhigere Wettbewerbskarten und klarere Favoriten-Hervorhebung ohne zusätzliche Bedienebenen.
- Kicktipp-Tabellen-Push korrigiert: Spieltagspunkte kommen direkt aus der Kicktipp-Spalte „Spieltag“ und werden nicht mehr aus zwei unmittelbar aufeinanderfolgenden Polls berechnet.
- Platzveränderung wird gegen den zu Beginn des Spieltags gespeicherten Tabellenstand berechnet. Mehrere Polls während eines laufenden Spieltags setzen die Vergleichsbasis nicht mehr zurück.
- Tabellen-Push für Apple Watch/iPhone kompakter: z. B. `⚽ +8 Pkt. · ↑2 Plätze · 🏁 Platz 5`.
- Tabellenbild benennt die Kennzahlen jetzt eindeutig als „Spieltagspunkte“ und „seit Spieltagstart“.

## Neu in 0.1.37

- Internationale Spielpläne robuster: Champions League und Europa League werden nicht mehr nur bei komplett leerem UEFA-Cache über OpenLigaDB ergänzt. OpenLigaDB wird nun bei jedem aktuellen Abruf als zweite Spielplanquelle gegengeprüft; fehlende Partien werden dedupliziert ergänzt. Dadurch kann ein teilweise veralteter UEFA-Cache keine heutigen Spiele mehr ausblenden.
- UEFA-Spielplan-Cache auf Schema 4 angehoben, damit bestehende Installationen nach dem Update sofort neu laden. Das hilft insbesondere auch der Conference League, für die OpenLigaDB aktuell keinen gleichwertigen 2026/27-Spielplan bereitstellt.
- Die 0.1.36-Fixes für Torschützen, Heute-Start, Nationalmannschaft, Push-Lautstärke und das neue PWA-Icon bleiben unverändert erhalten.


## Neu in 0.1.36

- Neues Fußball-Live-PWA-Icon für Home-Screen, Manifest und Favicon.

- Torschützen-Pushs für Favoriten werden jetzt exakt dem neu erreichten Spielstand (`score_after`) zugeordnet; ein verzögerter Eventfeed kann nicht mehr den vorherigen Torschützen wiederholen.
- Die Fußball-Startseite beginnt bei normalem App-Start immer auf **Heute**; Match-Deep-Links aus Pushs dürfen weiterhin gezielt den Spieltag des Ereignisses öffnen.
- UEFA-Spielplan robuster: Europa-League-ID korrigiert, paginierte 100er-Abfragen, Cache-Migration und OpenLigaDB-Fallback für Champions League/Europa League. Die Liveansicht zeigt weiterhin alle Spiele, Pushs international nur bei deutscher Beteiligung.
- Deutschland-Herren bleibt als eigener Wettbewerb aktiv.
- Kritische Pushs bleiben standardmäßig Lautstärke 0; VfL-Osnabrück-Spielereignisse (Tor/Karte/Halbzeit/Abpfiff) nutzen Lautstärke 1.
- Neues PWA-/Home-Screen-Icon und Manifest.

## Neu in 0.1.34

- Team-Matching robuster gemacht: typische Vereinspräfixe wie `SG`, `DSC`, `VfL`, `FC` usw. werden beim Abgleich generell ignoriert.
- Vierstellige Gründungsjahre wie `1848` oder `1846` werden beim Matching ebenfalls ignoriert. Dadurch passen z. B. `SG Dynamo Dresden – VfL Bochum 1848` zuverlässig zu `Dynamo Dresden – VfL Bochum`.
- Die gleiche tolerante Normalisierung wird auch für öffentliche Kicktipp-Spiel-/Live-Daten verwendet.

## Neu in 0.1.33

- Teamnamen-Matching robuster gemacht: Das Vereinspräfix `DSC` wird jetzt wie `FC`, `VfL`, `SG` usw. normalisiert.
- Dadurch werden z. B. `DSC Arminia Bielefeld`, `Arminia Bielefeld` und `Bielefeld` beim automatischen Kicktipp-Ausfüllen zuverlässig als dieselbe Mannschaft erkannt.
- Behebt den Fehler `Zeile nicht gefunden` bei Tipps wie `DSC Arminia Bielefeld – FC St. Pauli`.

## Neu in 0.1.32
- Fester **Heute**-Sprung in der Datumsnavigation, unabhängig vom aktuell gewählten Tag.
- Bei zukünftigen Spielen können im Matchcenter Pushs pro Spiel einzeln aktiviert werden: **Tore**, **Karten** und **Erinnerung 30 Minuten vor Anpfiff**.
- Die Auswahl wird persistent pro Spiel gespeichert.
- Tor-/Karten-Pushs der individuellen Spielauswahl werden über Kicktipp überwacht und verbrauchen keine zusätzlichen API-Football-Requests.
- Individuelle Spiel-Pushs öffnen direkt das jeweilige Matchcenter.
- Für VfL Osnabrück/Bayer 04 Leverkusen werden doppelte Tor-Pushs vermieden, weil deren bestehender Favoriten-Torpush Vorrang hat.

## Neu in 0.1.31
- Tabellen-Push erkennt die eigene Zeile ausschließlich über `table_user_name` (standardmäßig Hauptprofil).
- Nur die eigene Zeile wird farbig markiert; `(Du)` wird nicht mehr an Namen angehängt.
- Zahlenparser korrigiert: numerische Snapshot-Werte wie `26.0` werden nicht mehr fälschlich zu `260`.
- Blockpunkte und Platzveränderung werden nur aus einem echten vorherigen Tabellenstand berechnet; ohne Vergleich wird `Noch kein Vergleich` angezeigt.
- Kein Fallback mehr auf die erste Tabellenzeile, wenn die eigene Zeile nicht eindeutig gefunden wird.

## Neu in 0.1.30
- Freie Tagesnavigation: beliebig vor/zurück; zusätzlicher Spieltag-Modus Freitag bis Sonntag.
- Favoriten VfL Osnabrück und Bayer 04 Leverkusen werden in Spielübersicht und Ligatabellen hervorgehoben.
- Favoriten erhalten bei jeder Spielstandsänderung einen kritischen lautlosen Push; Torschütze wird via API-Football best-effort ergänzt.
- UEFA-Wettbewerbe zeigen nun alle Spiele im Dashboard; Halbzeit-/End-Pushs bleiben auf deutsche Mannschaften begrenzt.
- Einzelspiel-Pushs öffnen direkt das Matchcenter; Sammel-Pushs die Wettbewerbsansicht.
- Matchcenter-Kopf, Aufstellungs-Pager und 4-2-3-1-Platzierung verbessert.
- Diagnosebereich mit Kicktipp/API-Zeitstempeln, API-Football-Kontingent und letzten Statuswechseln.

## Neu in 0.1.29

- Wettbewerbsübersicht zeigt standardmäßig ausschließlich die Spiele des heutigen Kalendertags.
- Tagesnavigation direkt oberhalb der Spiele: `← Gestern`, `Heute`, `Morgen →`.
- Live-Spiele des gewählten Tages bleiben wettbewerbsübergreifend ganz oben.
- Unter 1. und 2. Bundesliga gibt es jeweils einen `Tabelle`-Button mit einer kompakten In-App-Ligatabelle aus OpenLigaDB.
- Spielverlauf bleibt als gemeinsame Timeline; die Mannschaft wird innerhalb einzelner Ereignisse nicht noch einmal wiederholt, da Heim/Auswärts bereits links/rechts fest zugeordnet sind.
- Zwei Spieler in einer Formationsreihe werden deutlich zentraler platziert; das verbessert besonders Systeme mit zwei Spitzen, ohne gut funktionierende 4er-/5er-Reihen zu verändern.
- Datenfenster für die Oberfläche wurde auf bis zu 36 Stunden rückwärts erweitert, damit `Gestern` auch spät am Abend vollständig funktioniert. Pushs bleiben auf aktuelle Spielblöcke begrenzt.

## Neu in 0.1.28

- Live-Spiele stehen wettbewerbsübergreifend immer ganz oben in einem eigenen Live-Block.
- Die große Info-/Statusbox über der Wettbewerbsübersicht wurde entfernt; technische Hinweise erscheinen nur noch bei echten Fehlern.
- Aufstellungen werden auf dem iPhone als eine Mannschaft pro Seite angezeigt und können horizontal zwischen Heim und Auswärts gewischt werden.
- Die sichtbaren Positionskürzel G/D/M/F wurden entfernt.
- Die offizielle API-Football-Formation hat bei der grafischen Anordnung Vorrang; Grid-Daten dienen als Fallback. Dadurch stimmt die sichtbare Reihenstruktur mit z. B. 4-2-3-1 oder 4-4-2 überein.
- Ersatzspieler werden deutlich kompakter in einem zweispaltigen Raster angezeigt.
- Tore, Karten und Auswechslungen werden in einem gemeinsamen Spielverlauf dargestellt: Heim links, Auswärts rechts.
- Bei Toren wird der laufende Zwischenstand (z. B. 1:0 / 1:1) angezeigt.
- API-Football-Ereignisbezeichnungen werden bereinigt/übersetzt: z. B. Normal Goal → Tor, Own Goal → Eigentor, Penalty → Elfmeter; Yellow Card/Red Card werden nicht mehr als englischer Zusatztext wiederholt.
- Der Detailcache wurde versioniert, damit alte Ereignisdaten ohne Teamseite/Zwischenstand nicht weiterverwendet werden.

## Neu in 0.1.27

- Halbzeit-Push korrigiert: +45 Minuten startet nur noch die API-Football-Prüfung, löst aber niemals selbst einen Push aus.
- `score.halftime` allein zählt nicht mehr als Halbzeit. Der Push wird erst freigegeben, wenn API-Football für jedes Spiel des Anstoßblocks `HT` oder einen nachweislich späteren Status (`2H`/`FT` usw.) gemeldet hat.
- Alte Halbzeit-Caches werden per Schema-Version verworfen, damit ein unter 0.1.26 zu früh gespeicherter Halbzeitstand keinen erneuten Fehl-Push auslösen kann.
- Bei versetzten Halbzeitpfiffen bleibt die Logik korrekt: Ein bereits in `2H` befindliches Spiel zählt als bestätigte Halbzeit, während auf das letzte Spiel des Blocks weiter gewartet wird.

## Neu in 0.1.26
- Detailansicht nutzt API-Football nun bevorzugt für komplette Fixture-Details: echte Formation/Grid-Positionen, Tore, Karten und Auswechslungen inklusive Mannschaft.
- Keine erfundene 4-3-3-Grafik mehr: ohne belastbare Grid-/Formationsdaten wird eine saubere Spielerliste angezeigt.
- Tore, Karten und Wechsel zeigen Mannschaft und – sofern vorhanden – Teamlogo.
- Auswechslungen werden über API-Football zuverlässig mit rein/raus und Team angezeigt.
- Detaildaten werden live 5 Minuten gecacht, nach Spielende dauerhaft; Kicktipp bleibt Live-/Endstandquelle und Detail-Fallback.

## Neu in 0.1.25
- API-Football wird jetzt zusätzlich für exakte grafische Aufstellungen je Spiel genutzt.
- Spieler werden auf Basis von Formation und Grid-Position auf dem Spielfeld platziert.
- Kicktipp bleibt Quelle für Live-Spielstand, Tore, Karten und Wechsel.
- Detailansicht optisch überarbeitet und robuster gegen fehlende Detail-Links.

## Neu in 0.1.24

- Detail-Cache ist parser-versioniert. Falsch zerlegte Daten aus älteren Versionen werden nach dem Update automatisch ignoriert – auch bei bereits beendeten Spielen mit langem Cache.
- Tore und Karten werden jetzt zeilenweise gruppiert: Minute, Symbol und nachfolgender Spielername gehören zu einem Ereignis. Dadurch bleiben Torschützen/Kartenspieler nicht mehr leer.
- Kicktipp-Aufstellungen werden als Vier-Spalten-Tabelle erkannt (`Heimspieler | Heim-Nr. | Gast-Nr. | Gastspieler`) und sauber in beide Mannschaften getrennt.
- Beide Startelfen werden grafisch jeweils auf einem eigenen Spielfeld dargestellt; unbekannte Formation wird ausdrücklich nur schematisch angeordnet.
- Unstrukturierte Aufstellungsdaten werden nicht mehr blind als falsche Formation einer einzelnen Mannschaft dargestellt.

- Live-Minuten werden in der Wettbewerbsansicht jetzt direkt am LIVE-Status angezeigt. Wenn Kicktipp keine Minute liefert, wird eine robuste Minuten-Anzeige aus der Anstoßzeit abgeleitet.
- Halbzeit wird in der UI klar als `Halbzeit · x:y` dargestellt, sobald der Halbzeitstand vorliegt.
- Aufstellungen werden nicht mehr nur als lange Liste gerendert, sondern aus typischen Kicktipp-Tabellenzeilen strukturiert erkannt und grafisch auf einem Spielfeld dargestellt.
- Ersatzbank wird getrennt als kompakte Karten unter der grafischen Aufstellung angezeigt.
- Die bisherige 0.1.22-Logik für Livebox-Status, Detail-Link-Fallback und Halbzeit-Sensor bleibt erhalten.

- Fix der Livebox-Farberkennung: zusammengesetzte CSS-Selektoren wie `.result.live` werden jetzt als Kombination ausgewertet. Dadurch werden schwarze Endstände nicht mehr fälschlich als LIVE erkannt.
- `livebox` als Seiten-/Containerklasse kann nicht mehr versehentlich alle Spiele als live markieren.
- Klickziele der Kicktipp-Spielpaarungen werden jetzt auch aus `onclick`/`data-*`-Attributen und Spiel-IDs erkannt. Fehlt der Link im Livebox-Abruf, wird er beim Öffnen eines Spiels einmalig über die öffentliche Wettbewerbs-/Livebox-Seite aufgelöst und 5 Minuten gecacht.
- Bei technisch unsicherem Kicktipp-Status zeigt die UI `Status offen` statt aufgrund der Uhrzeit fälschlich `LIVE`.
- Öffentliche Kicktipp-Livebox ist Primärquelle für Live-Spielstände und Spielende.
- Ergebnisstatus: `-:-` = geplant, rotes Ergebnis = live, schwarzes Ergebnis = beendet. Bei unsicherer Farberkennung wird kein FT geraten.
- Kicktipp-Livebox wird serverseitig höchstens alle 60 Sekunden aktualisiert.
- API-Football wird nicht mehr für laufende Spielstände oder Endstände gepollt.
- API-Football dient ausschließlich als Halbzeit-Sensor: ab geplantem Anpfiff +45 Minuten höchstens einmal pro 60 Sekunden, bis für alle Spiele des Anstoßblocks ein Halbzeitstand vorliegt. Danach endet das API-Polling für diesen Block.
- Spieldetails werden über den öffentlichen Kicktipp-Spiel-Link geladen und 5 Minuten gecacht; nach Spielende 12 Stunden. Angezeigt werden – soweit Kicktipp sie für das Spiel liefert – Tore/Torschützen, Karten, Auswechslungen und Aufstellungen.
- Wettbewerbe: 1. Bundesliga, 2. Bundesliga, DFB-Pokal, Supercup, Deutschland Herren sowie deutsche Teams in Champions League, Europa League und Conference League.
- Halbzeit- und End-Pushs bleiben kritisch und lautlos; Antippen öffnet die Wettbewerbsansicht.
- Mobile-first Oberfläche und separater Kicktipp-Bereich bleiben erhalten.

## Datenquellen

- Kicktipp: Live-Spielstände, Endstatus, öffentliche Spieldetails.
- OpenLigaDB/UEFA: Spielplan und Fallback/Zuordnung der überwachten Wettbewerbe.
- API-Football: ausschließlich zuverlässige Halbzeiterkennung.

## API-Football

Der Key wird über `api_football_key` in der Add-on-Konfiguration hinterlegt. Das automatische Halbzeit-Polling verwendet `api_football_halftime_poll_seconds` (Standard 60 Sekunden). Der Key wird nicht an das Browser-Frontend ausgegeben.

## Weboberfläche

Direktport: 8148

Die Wettbewerbsansicht ist die Startseite. Der Kicktipp-Bot ist über die Bottom-Navigation erreichbar.
