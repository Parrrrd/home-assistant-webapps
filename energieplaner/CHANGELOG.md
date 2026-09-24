## 0.1.60 — 24.09.2026, 10:15 CEST

- Persönliche Energieplan-Pushes verwenden wieder den kritischen iOS-Hinweis bei Lautstärke 0 – auch über den aktuellen, zuverlässigen `notify.send_message`-Versandweg.
- Die getrennten Empfänger und die jeweils eigenen Planinhalte bleiben unverändert.

## 0.1.59 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

# 0.1.58

- iPhone-Kopfzeile berücksichtigt jetzt die obere Safe Area; App-Titel und Einstellungsbutton liegen nicht mehr unter Statusleiste/Dynamic Island.
- PV-Wallbox priorisiert den Hausspeicher jetzt auch in der Live-Leistungsregelung: maßgeblich ist der tatsächlich nach Haus und Speicher verfügbare Überschuss aus Netzbilanz plus laufender Wallboxleistung, nicht mehr nur PV minus Haus.
- Zusätzlich reserviert das Tagesbudget vor jeder Auto-Freigabe genug Rest-PV, um den Hausspeicher voraussichtlich bis 100 % zu füllen (plus Haus, Warmwasser und Sicherheitsreserve). Reicht der Tag dafür nicht, bleibt das Auto automatisch aus.
- Zusätzlicher Schwach-/Spättag-Schutz: liegt die PV deutlich hinter dem Tages-Soll oder endet das PV-Fenster in höchstens zwei Stunden, startet die Auto-PV-Ladung unter 95 % Speicher-SOC nicht.
- Neue manuelle Auto-Ladepause auf der Übersicht. Sie stoppt die laufende automatische Wallboxladung und verhindert neue automatische PV-/Nachtstarts; Direktsteuerung bleibt möglich.
- Wallbox-Karte auf der Übersicht zeigt ID.7 und e-Golf mit SOC und Kabelstatus direkt unter Leistung/Phasen, ohne die Karte höher zu machen.
- Direkt nach dem Energiefluss neue schmale PV-Tageszeile: bisher erzeugt, Soll bis jetzt und noch erwartete Erzeugung.
- Bestehende Einstellungen, Lernwerte und sonstige persistente Daten bleiben erhalten.

# 0.1.57

- primary-Push auf robusten aktuellen Home-Assistant-Notify-Weg erweitert: eindeutige `notify`-Entity wird bevorzugt über `notify.send_message` angesprochen, ältere `notify.mobile_app_*`-Dienste bleiben Fallback.
- primary-Pushes werden als normale Mobile-App-Mitteilung statt als kritischer Lautstärke-0-Payload versendet; secondary funktionierender Push bleibt unverändert.
- Test primary ist jetzt ein kurzer reiner Transporttest und baut nicht mehr erst den kompletten Energieplan. Die Rückmeldung nennt den tatsächlich gewählten Notify-Weg.
- Morgenlernen wartet nicht mehr pauschal bis 13:10. Sobald PV die reale Hauslast 20 Minuten stabil deckt, werden heutiger Übernahmezeitpunkt, 05:00-SOC und Morgenbedarf sofort gespeichert und angezeigt.
- Erst wenn bis 13:00 keine stabile PV-Deckung erkannt wurde, wird der Tag ab 13:10 ohne Übernahmepunkt abgeschlossen.
- Keine Änderung an PV-Prognose, Speicherzielrechnung, Wallbox- oder Nacht/Tag-Festschreibung.

# 0.1.56

- 07:00-Neuberechnung darf Nacht/Tag-Entscheidungen von 20:00 nicht mehr rückwirkend ändern; Vorabendentscheidung wird pro Kalendertag eingefroren.
- Tages-PV-Fenster für Warmwasser/Spülmaschine darf morgens weiterhin zeitlich optimiert werden, die Grundentscheidung Nacht vs. PV bleibt unverändert.
- Morgen-Push nutzt den Vorabend-Snapshot auch dann, wenn nur secondary Push zugestellt wurde.
- primary-Push robuster: gespeicherter Mobile-App-Notify-Service wird gegen Home Assistant geprüft und bei eindeutigem primary-iPhone-Service automatisch korrigiert. Test-Push zeigt den tatsächlich verwendeten Service.
- iPhone-Einstellungsbutton mit direkter Navigation abgesichert.
- Keine Änderung an PV-, Speicher-, Wallbox- oder Lernberechnung außerhalb dieser Planungsgrenzen.

# 0.1.55

- Energiefluss-Karten auf Desktop und iPhone weiter verkleinert: Haus deutlich kompakter, Verbraucher moderat kompakter.
- Inhalte aller Energiefluss-Knoten vollständig zentriert (Icon, Bezeichnung, Live-Wert und Tageswert).
- Mobile Flusswege bleiben durch kleinere Karten und größere Zwischenräume deutlich sichtbar.
- Keine Änderung an Energie-, Prognose-, Speicher- oder Lernlogik.

# 0.1.54

- iPhone-Energiefluss kompakter gestaltet: kleinere Quellen-, Haus- und Verbraucherkarten schaffen sichtbar mehr Raum für die Flusslinien und deren Richtung.
- Tageswerte werden auf dem iPhone jetzt wie auf dem Desktop direkt in jedem Energiefluss-Knoten angezeigt.
- Mobile Leitungsgeometrie neu ausgerichtet, damit aktive Energieflüsse zwischen den Ebenen deutlich sichtbar bleiben.
- Desktop-Energiefluss und Berechnungs-/Automatiklogik unverändert.

# 0.1.53

- Energiefluss neu als Ebenenmodell aufgebaut: PV, Netz und bidirektionaler Speicher oben; Haus als zentraler Knoten in der Mitte; Wallbox, Wärmepumpe, Spülmaschine und Klimageräte gesammelt darunter.
- Aktive Flüsse zeigen Richtung und aktuelle Menge direkt auf den Leitungen; Speicher- und Netzfluss bleiben bidirektional.
- iPhone-Darstellung mit derselben logischen Hierarchie, aber kompakter 2-Spalten-Verbraucheranordnung.
- Speicher aus „Nächste Aktionen“ entfernt, da das 05:00-Speicherziel direkt daneben bereits sichtbar ist.
- Keine Änderung an Energie-, Speicher-, PV-, Wallbox- oder Lernlogik.

# 0.1.52

- Übersicht als echtes Live-Energiefluss-Cockpit neu aufgebaut: Haus im Zentrum, PV, Speicher, Netz, Wallbox, Wärmepumpe, Spülmaschine und Klimageräte mit animierter Flussrichtung.
- „Was passiert gerade?“ auf vier gleich große Karten reduziert; der separate PV-Überschuss entfällt.
- Kompakte Zeile „Nächste Aktionen“ ergänzt und mit der ausführlichen Planungsseite verknüpft.
- 05:00-Zielkarte gegen Abschneiden auf schmaleren Desktop-Breiten abgesichert.
- Morgenberechnung transparenter: jeder Abschnitt von 05:00 bis zur stabilen PV-Übernahme wird einzeln mit Restlast, PV-Anteil und Speicherbedarf gezeigt.
- Direktsteuerung ist auf ihrer eigenen Seite standardmäßig geöffnet.
- Mobile Darstellung des Energieflusses für iPhone optimiert.

# 0.1.51
- Modern-Light-Design konsequent an den freigegebenen Entwurf angenähert.
- Sämtliche Informations- und Auswertungstexte auf dunkle/schwarze Schrift vereinheitlicht; Farbe dient nur noch als gezielter Status-/Energieakzent.
- Gemini-Statusleiste auf schwarze Schrift mit Statuspunkt umgestellt.
- Übersicht, Planung, PV & Laden, Prognose & Lernen, Steuerung und Einstellungen optisch neu hierarchisiert.
- Prognose & Lernen als moderne Kennzahlenkarten mit separaten Detailkarten aufgebaut; Berechnung bleibt vollständig aufklappbar.
- Mobile Darstellung und Bottom-Tabs kontrastreicher und ruhiger gestaltet.

## 0.1.50

- Modernes helles Cockpit nach finalem Designentwurf.
- Kontrast und Lesbarkeit in allen Bereichen vereinheitlicht; Haupttexte konsequent dunkel/schwarz, Farben nur noch als gezielte Energie-/Statusakzente.
- Übersicht um eine kompakte 05:00-Zielkarte mit Morgenbedarf, PV-Übernahme, Reserve und direktem Sprung zur Berechnung ergänzt.
- Planung, PV & Laden, Prognose & Lernen, Steuerung und Einstellungen visuell vereinheitlicht und alte dunkle Reststile entfernt.

## 0.1.49

- Helles Desktop-/iPhone-Design nochmals vereinheitlicht und optisch verfeinert.
- Verbliebene dunkle Alt-Komponenten in Planung und PV-/Wallbox-Bereich vollständig ins Light-Theme überführt; Kontrast und Lesbarkeit korrigiert.
- Kartenhierarchie, Navigation, Abstände, Schatten und mobile Tab-Leiste ruhiger und konsistenter gestaltet.
- Keine Änderung an Prognose-, Speicher-, Wallbox- oder Lernlogik.

# Changelog

## 0.1.48

- Neues eigenständiges helles Energieplaner-Design für Desktop und iPhone.
- Desktop-Navigation links: Übersicht, Planung, PV & Laden, Prognose & Lernen, Steuerung.
- iPhone-Navigation als feste untere Tab-Leiste; Hauptbereiche können zusätzlich horizontal gewischt werden.
- Alle bisherigen Dashboard-Funktionen auf die neuen Bereiche verteilt; keine Planungs- oder Steuerfunktion entfernt.
- Unter Prognose & Lernen: „Berechnung öffnen“ mit stundenanteiliger Rechnung des 05:00-Speicherziels.
- Morgenbrücke zeigt transparent Restlast, PV-Anteil, Netto-Speicherbedarf, Lernpuffer, Mindestreserve und Resttag-Puffer.
- Morgenbrücke verwendet weiterhin die gelernte Standby-/Restlast; die 0,85-kW-Grundlast bleibt der Resttag-/Tagesbilanz vorbehalten.

## 0.1.47

- Morgen-Speicherziel nutzt jetzt die gelernte Standby-/Restlast statt der Tagesgrundlast für die Strecke 05:00 bis zur stabilen PV-Übernahme.
- Gemini bewertet zusätzlich anhand des stündlichen Morgenwetters, ab wann die PV die Restlast voraussichtlich stabil trägt; die App berechnet den Strombedarf bis dahin selbst stundenanteilig aus Restlast minus prognostizierter PV.
- Für die Morgenbrücke wird der konservative PV-Planwert verwendet, damit ein schwacher Morgen nicht durch späteren Tagesertrag schöngerechnet wird.
- Neuer getrennt lernender Zeitpuffer für Abweichungen zwischen prognostizierter und realer PV-Übernahme sowie ein langsam wachsender/sinkender Energiepuffer für Abweichungen beim tatsächlichen Morgenbedarf.
- Mindestreserve, Zeitfehler und Energiefehler bleiben getrennte Lernwerte und werden migrationssicher fortgeführt.
- „Prognose & Lernen“ zeigt prognostizierte und angepasste PV-Übernahme, berechneten Morgenbedarf sowie Zeit- und Energiepuffer.

## 0.1.46

- Neues Energyplaner-App-Icon für Home Assistant, iPhone-Homescreen und macOS/PWA ergänzt.
- Apple-Touch-Icon, Favicon und Web-App-Manifest hinzugefügt.

## 0.1.45

- Nachtladung wieder in den aktiven Scheduler aufgenommen; bei 0 % wird die Speicherladung bis mindestens 25 % zuverlässig geplant und gestartet.
- Schaltbefehl der Speicher-Netzladung wird anschließend verifiziert und mit Zeitstempel sowie Fehlerstatus protokolliert.
- Ein veralteter gespeicherter Abschluss kann eine neue Unterladung nicht mehr blockieren.
- Morgen-/PV-Übernahme zeigt bei einem neuen Tag ausdrücklich den heutigen Erfassungsstatus statt unbemerkt den gestrigen Zeitstempel weiterzuführen.

## 0.1.44

- Die Anzeige trennt jetzt die Dauer der aktuellen Phasenzahl von der gesamten PV-Ladesitzung: links etwa „Lädt mit 2 Phasen seit 2 Min.“, rechts „Ladung gesamt 13 Min.“.
- Für einen Phasenwechsel darf die Wallbox kurz gesperrt werden, ohne dass die Gesamtdauer zurückgesetzt wird. Erst nach mindestens fünf Minuten durchgehender Sperre beginnt eine neue Ladesitzung.

## 0.1.43

- PV-Zeitblöcke verwenden jetzt echte, gespeicherte Zeitstempel statt einer nur innerhalb des Add-ons gültigen Laufzeit. Nach Neuladen der Seite oder einem Add-on-Neustart wird die korrekte bisherige Dauer angezeigt.
- „Lädt seit …“ ist von den einzelnen Phasen getrennt und läuft durchgehend weiter, auch wenn später Phase 2 oder 3 ergänzt beziehungsweise wieder entfernt wird.
- Beim ersten Update wird ein eventuell noch alter interner Zeitwert einmalig sauber in einen echten Startzeitpunkt überführt; danach bleiben die Zeiten dauerhaft stabil.

## 0.1.42

- Der PV-Zeitblock läuft nun im Browser durchgehend mit einer monotonen Uhr. Ein Statusabgleich kann die angezeigte Zeit niemals mehr zurücksetzen oder den Countdown verlängern.
- Alle fünf Sekunden werden nur noch die kleinen PV-Statusdaten abgeglichen; die vollständige Dashboardansicht wird wieder nur alle 15 Sekunden aktualisiert.
- Neue schlanke Statusschnittstelle für den PV-Timer. Sie benötigt keine neue Prognose- oder Dashboardberechnung.

## 0.1.41

- Scheduler-Abbruch behoben: Der Minutenplan referenzierte fälschlich `live_pv_correction_tick`, obwohl diese Funktion nicht existiert. Dadurch brach der gesamte Minutenlauf immer wieder ab.
- Die bereits vorhandene Live-PV-Erfassung und -Korrektur bleibt über `record_live_pv_sample()` und `live_pv_analysis()` aktiv. Entfernt wurde ausschließlich der ungültige Aufruf.
- Nachtladung, Warmwasser, Lernroutinen und die übrigen Minuten-Automatiken laufen damit wieder zuverlässig weiter.

## 0.1.40

- Die PV-Freigabe, der 120-Sekunden-Countdown und die Phasenwechsel laufen jetzt in einem eigenen 5-Sekunden-Takt. Sie sind damit vollständig vom Minutenplan für Prognosen, Lernen und Nachtplanung getrennt.
- Ein hängender oder länger dauernder anderer Planlauf kann die Wallbox nicht mehr daran hindern, nach zwei Minuten stabilem Überschuss von `locked` auf `optimized` zu wechseln.
- Das PV-Budget wird für die schnelle Steuerung höchstens eine Minute zwischengespeichert. Fehlt es wirklich, bleibt die Wallbox weiterhin sicher gesperrt; die Live-Überschussprüfung selbst wird dadurch aber nicht blockiert.
- Dashboard und Browser rufen den Steuerstatus nun alle fünf Sekunden ab. Der sekundengenaue Countdown läuft dazwischen lokal weiter.
- Falls die erste Statusantwort unmittelbar nach einem Neustart noch fehlt, wird bei genug Überschuss klar „Startzeit wird synchronisiert“ statt des irreführenden allgemeinen Prüftextes angezeigt.

## 0.1.39

- PV-Status und Timer sind von der Prognose-/Budgetberechnung entkoppelt. Auch bei einer kurzfristig fehlgeschlagenen Planung zeigt die Wallbox jetzt einen eindeutigen Status statt „PV-Überschuss wird geprüft“.
- Bei zu wenig Überschuss erscheint „zu wenig seit …“; bei stabilem Überschuss läuft ein sekundengenauer Countdown bis zum Entsperren. Dasselbe gilt für Phase 2 und 3.
- Die Anzeige nennt nun auch ein fehlendes PV-Budget oder einen temporären Planungsfehler konkret. Ein zusätzliches Browser-Fallback verhindert wieder den allgemeinen Leerstatus.
- Der Wächter verwendet auch im seltenen Fallback-Fall die aktuelle Abschaltschwelle von 1.400 W.

## 0.1.38

- Die Phase-1-Abschaltschwelle liegt jetzt bei 1.400 W statt 900 W. Das gilt identisch für die normale PV-Automatik und den unabhängigen Sicherheitswächter.
- Bestehende Einstellungen mit dem bisherigen Standardwert 900 W werden bei der Aktualisierung automatisch auf 1.400 W angehoben.

## 0.1.37

- PV-Start von `locked` nach `optimized` erfolgt wieder nach exakt 120 Sekunden stabil mindestens 1.600 W PV minus Hauslast; Phase 1 bleibt dabei wie vorgesehen dauerhaft eingeschaltet.
- Die Anzeige erklärt jetzt konkret, weshalb ein Start ausbleibt (Automatik aus, kein Auto, fehlende Prognose oder fehlende Leistungswerte), statt nur „wird geprüft“ zu zeigen.
- Ein manueller Wechsel auf `locked` oder zurück auf PV setzt die Laufzeit sauber zurück. Dadurch kann keine alte PV-Laufzeit wie „seit 16 Std.“ weiter angezeigt werden.
- PV-Laden wird außerhalb des Tagesfensters sauber gesperrt. Nachtladung bleibt ausschließlich dem separaten Schnellladen-Modus vorbehalten.
- Der Akku-SOC wird gegen einzelne falsche Sprünge – insbesondere 0-%-Ausreißer – abgesichert. Drei ähnliche Messungen sind erforderlich, bevor ein großer Sprung übernommen wird.
- Nachts wird Startzeit und Ziel der Speicherladung eingefroren. Sobald sie beginnt, bleibt sie bis zum Ziel aktiv; spätere Rohwerte dürfen sie nicht mehr ein- und ausschalten lassen.

## 0.1.36
- Zeitgrenze des Wallbox-Sicherheitswächters entfernt: Er überwacht `optimized` jetzt rund um die Uhr und ausschließlich anhand des tatsächlichen PV-/Überschussmodus.
- `fast` ist ausdrücklich vom Sicherheitswächter ausgenommen; bewusst gestartetes Schnellladen bleibt daher auch tagsüber ohne PV-Überschuss möglich.
- Die normale PV-Automatik respektiert einen manuell gesetzten `fast`-Modus und überschreibt ihn tagsüber nicht automatisch wieder mit `optimized`.
- Nachtlogik und 05:00-Hard-Cutoff bleiben unverändert.

## 0.1.35
- Scheduler-Regression behoben: Nacht-Wallbox, Warmwasser und PV-Wallbox rufen wieder die tatsächlich vorhandenen Automatikfunktionen auf.
- Automatik-Ticks voneinander isoliert, damit ein einzelner Fehler die übrigen Steuerungen nicht mehr stoppt.
- Unabhängigen Wallbox-Sicherheitswächter im 10-Sekunden-Takt ergänzt. Er nutzt dieselbe Phase-1-Abschaltschwelle und Stabilitätszeit wie die normale PV-Regelung.
- Bei dauerhaft zu geringem PV-Überschuss wird `locked` redundant erzwungen und anschließend verifiziert; bei Bedarf erfolgt genau ein zweiter Versuch.
- Bei längerem Ausfall der Leistungswerte wird eine laufende PV-Ladung nach mindestens 180 Sekunden fail-safe gesperrt.
- Kann die Wallbox nach zwei Sperrversuchen nicht bestätigt werden, wird eine normale Fehler-Pushmeldung gesendet.

# Changelog

## 0.1.34

- Dashboard-Dichte weiter optimiert: „Was passiert gerade?“ und „Was passiert heute Nacht / morgen?“ sind flacher und farblich klar voneinander getrennt.
- „Was passiert gerade?“ behält die vier Kernkarten und die PV-Ladeautomatik direkt darunter, benötigt aber deutlich weniger Höhe.
- Nacht/Morgen-Planung bleibt 2×2; Modus und SOC-Steuerung bleiben in genau einer kompakten Bedienzeile.
- „Energie · jetzt“ bleibt vollständig mit neun Karten sichtbar, ist aber niedriger und nach drei Themen gruppiert: Energiefluss (PV/Haus/Netz), Systemtechnik (Speicher/Wallbox/Wärmepumpe) und Einzelverbraucher (Spülmaschine/Klima Büro/Klima KiZi).
- Reihenfolge im 3×3-Raster auf PV–Haus–Netz / Speicher–Wallbox–Wärmepumpe / Spülmaschine–Klima Büro–Klima KiZi geändert.
- PV-Laden-Karte deutlich verdichtet: Kernaussage und sicher verfügbare Autoenergie oben, kompakter Überschuss-/Phasenstatus, kleinere Budgetfelder und technische Schaltschwellen standardmäßig eingeklappt.
- Fahrzeug-Anwesenheit im PV-Laden-Bereich auf einen kompakten Auto-Ja/Nein-Schalter reduziert.

## 0.1.33

- Feste Tagesplanung: Gemini läuft automatisch fünf Minuten vor den Push-Terminen (standardmäßig 06:55 und 19:55), die Energieplan-Pushes folgen um 07:00 und 20:00 immer – auch ohne Planänderung. Verpasste Morgenläufe werden nur bis 09:00 nachgeholt; der Abend bis Mitternacht.
- Push-Zustellung wird für primary und – sofern aktiviert – secondary bestätigt; bei einem fehlgeschlagenen Notify-Aufruf wird der Termin im Catch-up-Fenster erneut versucht statt sofort als erledigt markiert.
- Gemini-Status ist tagesrein: Ein gestriger erfolgreicher Lauf erzeugt am Folgetag kein falsches Häkchen mehr.
- Der kompakte PV-Ladeautomatik-/Countdownblock sitzt jetzt direkt unter „Was passiert gerade?“ und benötigt deutlich weniger Höhe.
- Nacht/Morgen-Steuerung auf eine Zeile reduziert: Automatik, Nacht schnell, Nur PV und ein SOC-Button. Die SOC-Auswahl 40–100 % öffnet sich erst beim Antippen.
- „Energie · jetzt“ zeigt neun gleichzeitig sichtbare Felder im 3×3-Raster: PV, Haus, Speicher, Netz, Wärmepumpe, Wallbox, Spülmaschine, Klima Büro und Klima Kinderzimmer. Netzbezug/-einspeisung sind zweizeilig formatiert.
- Wallbox zeigt wieder aktuelle Leistung und Tagesverbrauch. Spülmaschine nutzt `sensor.pool_switch_0_power`; ihr Tagesverbrauch wird aus dem Leistungsverlauf integriert.
- Klima Büro (`sensor.klima_buro_strom_heute`) und Kinderzimmer (`sensor.klima_kinderzimmer_strom_heute`) zeigen Tages-kWh sowie eine aus den Zähleranstiegen abgeleitete Live-Leistung (≈ W).
- Neues separates Standby-/Restlast-Lernen aus sauberen 5-Minuten-Fenstern: messbare Großverbraucher werden abgezogen; bei eingeschalteter Klima Wohnzimmer (`climate.klimaanlage_wohnzimmer`) oder Schlafzimmer (`climate.klimaanlage_schlafzimmer`) wird das Messfenster nicht gelernt. Hohe unbekannte Restlasten werden ebenfalls verworfen.

## 0.1.32

- Sowohl vor dem 07:00-Push als auch vor dem 20:00-Push läuft jetzt eine vollständige Gemini-Prognose; der Push wird erst danach erzeugt.
- Die beiden festen Gemini-Termine werden innerhalb des Tageslimits priorisiert. Manuelle oder Startup-Aufrufe dürfen das für 07:00/20:00 benötigte Kontingent nicht mehr verbrauchen.
- Das effektive Gemini-Tageslimit ist deshalb mindestens 2; der Standard bleibt 3 und lässt damit normalerweise noch einen zusätzlichen erfolgreichen Gemini-Lauf zu.
- Migration korrigiert alte gespeicherte Morgenzeiten `0`, `00`, `0:00` oder `00:00` automatisch auf `07:00`, damit kein unbeabsichtigter Mitternachts-Push mehr entsteht.
- Bei Gemini-Fehler oder nicht verfügbarem API-Zugriff greift weiterhin der vorhandene Wetter-/Forecast-Fallback; auch dann wird der Push erst nach dem Prognoseversuch erstellt.

## 0.1.31

- primary-Push 20:00: 05:00-Speicherziel in die zweite Zeile verschoben, „05:00 Uhr“ ausgeschrieben und PV-Auto-Hinweis mit 🔌 direkt hinter den Fahrzeug-SOCs ohne zusätzlichen Punkttrenner.
- primary-Push 07:00: PV-Auto-Hinweis ebenfalls mit 🔌 direkt hinter dem eGolf-SOC.
- secondary-Push 20:00: Morgen- und Übermorgen-Sonnenlage stehen jeweils in einer eigenen Zeile.
- Speicher-Nachtladung startet mit einem lernenden Zeitpuffer von zunächst 10 Minuten früher. Wird das 05:00-Ziel trotz tatsächlicher Nachtladung um mindestens 1 Prozentpunkt verfehlt, wächst der Puffer um 5 Minuten bis maximal 30 Minuten; bei wieder erreichtem Ziel sinkt ein erhöhter Puffer langsam um 1 Minute bis zum Basiswert 10 Minuten.
- Die effektive gelernte Speicher-Laderate bleibt zusätzlich aktiv; am Ziel-SOC wird weiterhin sofort abgeschaltet. Der aktuelle Ladepuffer wird unter „Prognose & Lernen“ sichtbar angezeigt.

## 0.1.30

- Korrektur der 0.1.29-Dashboarddarstellung: Die bereits vorhandenen Lernwerte werden jetzt auch direkt unten unter „Prognose & Lernen“ sichtbar angezeigt.
- Sichtbar sind gelernte Grundlast und Tagesbasis, Mindestreserve, nächstes 05:00-Ziel sowie der letzte Morgen mit tatsächlichem 05:00-SOC, Zeitpunkt der stabilen PV-Übernahme, SOC bei PV-Übernahme und Bedarf bis dahin.
- Keine Änderung an Heizungssteuerung oder der in 0.1.29 eingeführten Speicher-/Wallbox-/Prognoselogik.

## 0.1.29

- Neue 05:00-Speicherplanung: Start-Grundlast 0,85 kW (16,15 kWh von 05:00–24:00), kalibriertes stündliches PV-Profil und gelernte Morgenbrücke werden gemeinsam berücksichtigt.
- Mindestreserve bei stabiler PV-Übernahme startet bei 5 %, lernt höchstens in 1-Prozentpunkt-Schritten und fällt nie unter 5 %.
- Manuelle 05:00-SOC-Korrektur von -10 bis +10 Prozentpunkten inklusive Reset auf 0.
- Grundlast lernt täglich sehr langsam aus dem realen Tagesergebnis; ein tagsüber voll gewordener Speicher verhindert ausdrücklich ein falsches Hochlernen wegen späterer Sonderlasten.
- Dashboard zeigt Grundlast, Tagesbasis, Mindestreserve, 05:00-Ziel, tatsächlichen 05:00-SOC, Zeitpunkt stabiler PV-Übernahme, SOC bei PV-Übernahme und Morgenbedarf.
- PV-Wallbox: Herabstufung bleibt bei 120 Sekunden; nur 1→2 und 2→3 Phasen benötigen künftig 30 Minuten stabilen Überschuss.
- Laufender Phasen-/Schalt-Countdown zählt im Browser sekundengenau herunter.
- 20:00- und 07:00-Prognoseläufe besitzen Catch-up-Logik und werden pro Termin/Tag nur einmal ausgeführt.
- Push-Nachrichten für primary und secondary kompakter und an die neue 05:00-Planung angepasst; Sonnenbegriffe jetzt <10 kaum, 10–<28 etwas, 28–<42 viel, ab 42 kWh sehr viel Sonne.
- Heizungssteuerung bleibt bewusst außerhalb des Energieplaners.

## 0.1.27

- Der PV-Phasenstatus zeigt nur noch den gerade zutreffenden Zustand – mit der Zeit im Mittelpunkt: seit wann Überschuss fehlt bzw. lädt oder wie lange bis zum Start, Abschalten oder Phasenwechsel verbleibt.

## 0.1.26

- Die Übersicht basiert wieder auf dem bevorzugten, kompakten Layout aus 0.1.24.
- Die große Überschusskarte oben entfällt. Stattdessen erklärt „Energie · jetzt“ live, ob Phase 1, 2 oder 3 erreicht ist und wie lange der Wert bereits stabil ist.
- Die Wallbox wird nicht mehr doppelt unter „Energie · jetzt“ gezeigt.
- Die Nacht-/Morgenplanung bleibt auch auf dem iPhone als übersichtliches 2×2-Feld erhalten.

## 0.1.25

- Die tatsächliche Übersicht folgt jetzt dem neuen Cockpit-Entwurf: drei große Live-Karten, ein ruhiger PV-Überschussbereich, ein separater Planbereich und verständliche Phasenregeln.
- Die Direktsteuerung bleibt aus Sicherheits- und Übersichtsgründen zunächst eingeklappt; ihr Status ist trotzdem sofort sichtbar.
- Ein laufender Phasenwechsel zeigt nun an, wie lange der Überschuss bereits stabil ist.

## 0.1.24

- Die sichtbare Kennzahl „PV-Überschuss“ und sämtliche Phasenschwellen verwenden nun dieselbe Berechnung: PV-Erzeugung minus Hauslast; der SENEC-Bilanzsensor ist nur noch eine Rückfallebene.
- Direktsteuerung ist wieder standardmäßig eingeklappt. Die responsive Übersicht priorisiert auf Mac und iPhone Überschuss, Wallbox und Speicher gleich klar.

## 0.1.23

- PV-Phasenwerte bleiben beim Bearbeiten erhalten und werden nach dem Speichern serverseitig geprüft, gespeichert und direkt bestätigt.
- PV-Überschussladung schaltet Phase 1 ein bzw. die Wallbox aus nach 2 Minuten stabiler Lage; Phase 2 und 3 werden erst nach 10 Minuten stabilen Mehrüberschusses ergänzt. Die Zeiten sind klar benannt und weiterhin anpassbar.
- Jeder Phasenwechsel sperrt die Wallbox zuerst, setzt danach die benötigten Phasen und gibt PV-Laden erst anschließend wieder frei.
- Live-Karte „PV-Überschuss“ ergänzt: aktuelle PV-Erzeugung minus Hauslast.
- Direktsteuerung: 1, 2 oder 3 PV-Phasen sind direkt antippbar.

## 0.1.22
- Visuelle Eigenständigkeit als kompaktes Energie-Cockpit verstärkt: dezentes Energieraster, technische Abschnittsmarkierung und eigene Blitz-Kennung; Funktionen und Layoutlogik unverändert.

## 0.1.21

- PV-Ladeplan: die 35-%-Planungsannahme wird nicht mehr irreführend als „Speicher aktuell“ bezeichnet, sondern als „Mindestreserve“.

## 0.1.20
- PV-Ladeblock wechselt nach Ende des heutigen PV-Fensters automatisch auf den morgigen PV-Ladeplan.
- Zusätzlicher vereinfachter Energieplan für secondary: Sonnenlage in Worten, ausschließlich e-Golf, klare Anschluss-/Ladeempfehlung, Spülmaschinen- und Warmwasser-Hinweis.
- e-Golf nutzt vorhandene Entitäten `sensor.e_golf_ladezustand` und `binary_sensor.wvwzzzauzlw913717_charging_cable_connected`.
- Separater Notify-Service `notify.mobile_app_secondary_iphone`, eigener Test-Push und eigener Ein/Aus-Schalter.
- 07:00-Uhr-Push für secondary nur, wenn sich ihr vereinfachter Plan tatsächlich ändert.

# Changelog

## 0.1.19

- Anzeige „PV-Laden geplant“ im Nacht-/Morgenblock verwendet jetzt das PV-Budget des Folgetags statt des Restbudgets des aktuellen Tages.
- 20:00-/07:00-/Test-Push kompakter formuliert, damit insbesondere die Warmwasserzeile auf iOS nicht abgeschnitten wird.
- Einstellungen speichern und Test-Push zeigen direkt am Button sichtbar „läuft“, „erfolgreich“ oder „fehlgeschlagen“; zusätzlich echte Druckreaktion beim Antippen.

## 0.1.18
- „Was passiert gerade?“ vereinfacht: Speicher nur noch mit SOC; Wallbox zusätzlich mit aktueller Ladeleistung und aus den drei vorhandenen Phasenschaltern ermittelten aktiven/freigegebenen Phasen; Warmwasser mit Temperatur plus „Heute erledigt“ oder Zeitfenster.
- Nacht-/Morgenplanung neu strukturiert: Speicher mit aktuellem SOC und Nacht-Mindestwert; Autos gemeinsam mit ID.7/e-Golf-SOC, Nachtladung und geplantem PV-Überschussladen; Spülmaschine und Warmwasser mit PV-/Nachtfenster.
- Überschrift auf „Was passiert heute Nacht / morgen?“ angepasst.
- Responsives Dashboard mit gestuften Karten-Teilern: 4/2 Spalten auf großen Displays, 2/2 auf mittleren Displays und 2/1 auf iPhone-/kleinen Displays, damit Inhalte nicht mehr gequetscht werden.

## 0.1.17
- Oberer Dashboard-Bereich weiter verdichtet: vier Karten inklusive verbleibender PV-Energie; separate „Nächste Aktion“-Leiste entfernt.
- Nachtplanung auf zwei Zeilen / vier kompakte Felder reduziert; kein irreführendes Speicher-Ziel bei nicht benötigter Netzladung.
- Energie-„Jetzt“-Karten kompakter; Speicher-SOC-Zusatz entfernt, Netz-Tageswerte in einer Zeile.
- 20:00-Push neu formatiert und als kritische, lautlose Mitteilung mit Lautstärke 0 versendet.
- Überschussladen im 20:00-Push nutzt das PV-Budget des Folgetags statt des Restbudgets des aktuellen Tages.
- 23:30-Spätpush entfernt; 07:00-Änderungscheck sendet nur bei Änderungen an PV, Speicher-Nachtladung, Autos, Überschussladen, Spülmaschine oder Warmwasser.
- Spülmaschine erhält ein konkretes 3-Stunden-Zeitfenster.
- Einstellungen: Test-Push-Button und konfigurierbarer 07:00-Morgencheck.

## 0.1.16

- Live-Energieblock vereinfacht: keine ERZEUGT/VERBRAUCHT-Badges mehr.
- PV-Leistung gelb, Hausleistung weiß.
- Speicher: Entladung mit rotem Minus, Ladung mit grünem Plus; Tagesladung/-entladung dort entfernt.
- Netz: Bezug mit rotem Minus, Einspeisung mit grünem Plus; Tageswerte für Bezug und Einspeisung bleiben direkt in der Karte.
- Wallbox und Wärmepumpe im gleichen kompakten Kartenstil mit Tageswert.
- Erklärungssatz unter dem Live-Energieblock entfernt.
- Oberer Dashboard-Bereich, Nachtplanung und Bedienelemente kompakter gestaltet, ohne Planungslogik zu ändern.

## 0.1.15
- Live-Karten in „Energie · jetzt“ zeigen die Flussrichtung nun direkt als gut sichtbaren Status: PV „ERZEUGT“, Haus/Wärmepumpe „VERBRAUCHT“, Speicher „LIEFERT/LÄDT“, Netz „BEZUG/SPEIST EIN“ und Wallbox „LÄDT/AUS“.
- Tageswerte bleiben kompakt in derselben Kartenzeile integriert.
- Die Leistungsbilanz darunter verwendet ebenfalls klare Verben statt nur nackter Plus-/Minuswerte.

## 0.1.14
- Bereich „Energie · jetzt“ auf genau eine horizontale Kartenzeile umgestellt; auf kleinen Displays horizontal wischbar statt Umbruch in eine zweite Zeile.
- Separate Sektion „Heute gesamt“ entfernt.
- Tageswerte direkt in die passenden Live-Karten integriert: PV, Netzbezug/Einspeisung, Wallbox, Wärmepumpe sowie Speicher geladen/entladen.
- Haus-Tagesverbrauch wird, sofern alle Tageszähler verfügbar sind, aus der Tagesenergiebilanz näherungsweise mit angezeigt.

## 0.1.13
- Optimistische Nachtsteuerungs-Buttons gegen stale Cache abgesichert: kein sichtbares Zurückspringen mehr.
- Aktuelle Wallbox-Anzeige vereinfacht; Fahrzeugname entfernt, Ziel nur bei wirklicher Schnellladung.
- Nachtplanungstext für Automatik unter Ziel auf „Schnellladung bis X %“ vereinfacht.
- Wärmepumpe live (`sensor.wp_verbrauch_pro_stunde`) und heute (`sensor.wp_verbrauch_tag`) ergänzt.
- Tagesbilanz: PV, Netzbezug (`sensor.netztagneu`), Einspeisung (`sensor.einspeisung_tag`), Wallbox (`sensor.wallbox_verbrauch_tag`), Wärmepumpe und Speicher.
- PV Live / Morgen / Übermorgen zu einer wischbaren Kartenleiste zusammengeführt.


## 0.1.12
- UI auf die kompakte 0.1.8-Linie zurückgeführt.
- Großes Energieflussdiagramm entfernt; neue einfache +/− Leistungsbilanz.
- "Was passiert gerade?" und "Was passiert heute Nacht?" wieder kompakt oben.
- Dashboard-Stale-while-revalidate-Cache: Seitenaufruf blockiert nicht mehr auf Home-Assistant-Sensorabrufen.
- Nachtziel-/Modus-Buttons mit sofortigem optischem Feedback ohne synchronen Dashboard-Neuaufbau.
- Wallboxlogik aus 0.1.10/0.1.11 unverändert: Automatik tagsüber PV ohne Mindest-SOC-Begrenzung; nachts Mindest-SOC, Nur PV niemals Nacht-Schnellladen.


## 0.1.11
- Frontend-Datenabruf robuster für Direktzugriff und Home-Assistant-Ingress: API-Pfad mit Fallback.
- Sichtbare Lade- und Fehlermeldung statt leerer Karten, falls ein Browser-Aufruf scheitert.
- Dashboard-Bereiche rendern unabhängig voneinander; ein einzelner JavaScript-Fehler leert nicht mehr die gesamte Oberfläche.
- Aktionen verwenden denselben robusten API-Zugriff und aktualisieren nach 250 ms.
- Wallbox-Nachtziel bleibt ausschließlich für 00:00–05:00 relevant; die bestehende Tages-PV-Überschusssteuerung bleibt davon unabhängig.

## 0.1.10
- Wallbox-Modi korrigiert und klar getrennt: Automatik, Nacht schnell und Nur PV.
- Automatik lädt tagsüber ausschließlich nach sicherem PV-Überschuss; der gewählte Mindest-SOC begrenzt das PV-Laden tagsüber ausdrücklich nicht.
- Automatik ergänzt zwischen 00:00 und 05:00 per Schnellladen nur dann, wenn das angeschlossene Auto unter dem gewählten Mindest-SOC liegt, unabhängig von der PV-Prognose.
- Nur PV ist nachts absolut: kein Schnellladen, auch wenn der Mindest-SOC unterschritten ist.
- Nacht schnell erzwingt im günstigen Nachtfenster Schnellladen bis zum gewählten Ziel.
- Prozentziel und Betriebsmodus sind jetzt unabhängige echte Buttons; ein Prozent-Klick schaltet nicht mehr versehentlich auf Nacht schnell.
- Upgrade von 0.1.9 setzt den durch die alte Prozent-Button-Logik möglicherweise gesetzten Fast-Override einmalig auf Automatik zurück, behält das gewählte Prozentziel aber bei.
- Kabel-/Fahrzeugerkennung erweitert; vorhandene Kabelsensoren haben Vorrang, danach Sitzungserkennung und robuster SOC-Fallback.
- Geschwindigkeits-, Kompakt- und Energiefluss-Änderungen aus 0.1.9 unverändert beibehalten.

## 0.1.9
- Dashboard beschleunigt: Home-Assistant-Zustände werden pro Snapshot gebündelt über `/states` geladen und kurz gecacht statt viele einzelne Sensor-Endpunkte nacheinander abzufragen.
- Nachtziel- und Auto-an-Wallbox-Schaltflächen antworten sofort; unnötige synchrone Plan-Neuberechnungen aus den POST-Handlern entfernt und Oberfläche optimistisch aktualisiert.
- Übersicht deutlich kompakter: „Was passiert gerade?“ und „Was passiert heute Nacht?“ direkt nebeneinander bzw. mobil untereinander am Seitenanfang.
- Manuelles Nachtziel präzisiert: Auswahl 40–100 % aktiviert für diese Nacht explizit Schnellladen 00:00–05:00 bis zum Ziel; „Automatik“ setzt den manuellen Override zurück, „Nur PV“ verhindert Nacht-Schnellladen.
- Neue Live-Energieflusskarte für PV, Haus, Speicher, Netz und Wallbox mit Richtungsanzeige und aktuellen Leistungen.
- Heute, Morgen und Übermorgen in einer gemeinsamen horizontal scrollbaren PV-Zeile zusammengeführt; Heute enthält weiterhin die lokale Live-Korrektur.
- Nachtziel, Nachtmodus, Fahrzeug-Präsenz und Direktsteuerung als größere echte Buttons mit sofortigem visuellen Feedback.
- Zusätzliche Live-Sensoren für Hausleistung, Speicherleistung, Netzleistung und Wallboxleistung.
- Port 8150, Python-Basisimage und bestehende Lern-/Schutzlogik bleiben unverändert.

## 0.1.8
- Speicherziel um 05:00 vollständig auf dynamische Lernlogik umgestellt; die bisherigen festen PV-kWh-Zielstufen werden nicht mehr verwendet.
- Startbasis bewusst knapp bei 35 %, mit Ziel von etwa 16 % Rest-SOC sobald die PV das Haus 20 Minuten stabil trägt.
- Tägliche lokale Auswertung der Home-Assistant-Historie von Hausleistung, Gesamt-PV und Speicher-SOC; kein Gemini-Aufruf dafür.
- Morgenbasis regelt sich an vergleichbaren guten PV-Tagen in kleinen Schritten selbst hoch oder runter; Startwert Netto-Morgenbedarf 1,55 kWh wird gleitend nachgeführt.
- Schlechte Folgetage erhalten getrennt eine stufenlose Tagesreserve; unter 10 kWh erwarteter PV wird bis 100 % geladen.
- Nachtkarte zeigt gelernte Morgenbasis und zusätzliche Tagesreserve getrennt.
- Neue Spülmaschinen-Empfehlung in der Nachtkarte: günstiges 00–05-Uhr-Fenster bei schwacher PV oder morgen mit PV bei ausreichender Prognose.
- Technische Lernansicht ergänzt um Morgenbasis, gelernten Netto-Morgenbedarf, letzten SOC bei PV-Deckung und Anzahl Morgen-Lerntage.

## 0.1.7
- PV-Tageskarten zeigen nur noch Morgen und Übermorgen; Heute bleibt ausschließlich in der Live-PV-Karte.
- Hausverbrauch bis PV-Ende wird über die tatsächliche Restzeit bis zum prognostizierten PV-Ende berechnet statt nur über die Anzahl Solarstunden.
- Haus-Grundlast als Startwert auf 0,70 kW angehoben; bestehender alter Standardwert 0,55 kW wird migrationssicher auf 0,70 kW gesetzt, individuelle Werte bleiben erhalten.
- Speicherreserve berücksichtigt den gelernten Abendbedarf und eine aus PV-Ende bis 00:00 abgeleitete Mindestreserve.
- Sicheres Auto-PV-Budget entsteht erst nach Hausverbrauch, benötigter Speicherladung, ggf. Warmwasser und Sicherheitsreserve.
- PV-Laden-Karte zeigt die komplette Budgetrechnung transparent.

## 0.1.6
- Gemini-Sparmodus: regulär ein Hauptaufruf um 20:00; 23:30 nur bei relevanter Wetteränderung.
- Kein Gemini-Aufruf mehr bei normalen App-Neustarts mit vorhandener Prognose.
- Manuelle Gemini-Neuberechnung mit 30-Minuten-Cooldown und Tageslimit.
- Bei 503/Fehler nur noch ein Wiederholungsversuch; danach gespeicherte Prognose/Physik-Fallback.
- Speichern von Einstellungen löst keine Gemini-Prognose mehr aus.
- Neue Live-PV-Karte mit Ist-vs.-Forecast, laufend korrigierter Restprognose und gemischtem Ist/Forecast-Tagesprofil.
- PV-Budget fürs Auto berücksichtigt die laufende Tagesabweichung ohne zusätzlichen Gemini-Aufruf.
- Neue kompakte Anzeige „Nächste Aktion“.

## 0.1.5

- Statuszeile weiter verdichtet: Gemini wird auf der Übersicht nur noch als ✓/Fallback angezeigt; konkretes Modell bleibt unter Einstellungen/Diagnose.
- „Was passiert gerade?“ neu aufgebaut: kurze Titel und klare Zustände für Speicher, Wallbox und Warmwasser ohne abgeschnittene Texte.
- PV-Tageskarten erhalten einen Seitenindikator für Heute/Morgen/Übermorgen; Stundenachse bleibt erhalten.
- PV-Laden zeigt zusätzlich „Voraussichtlich heute Abend“ mit geschützter Speicherreserve, noch verfügbarem PV-Budget fürs Auto und Risiko für Netzbezug vor 00:00.
- Nachtziel fürs Auto als kompakte Prozent-Schnellwahl statt Zahlen-Spinner.
- Auto-Status im Nachtplan ist zustandsabhängig: Empfehlung, laufendes Schnellladen oder erreichtes Ziel.
- „Bilanz“ in der Live-Ansicht in „Leistungsbilanz“ umbenannt.
- Keine Änderung an den harten Schutzregeln: Phase 1 bleibt immer an; automatische Nachtaktionen enden spätestens 05:00.

## 0.1.4

- Fahrzeugauswahl ID.7/e-Golf entfernt; nur noch „Auto an Wallbox: Ja/Nein“.
- Beide Fahrzeug-SOCs fließen weiterhin in die 48-Stunden-Nachtladeentscheidung ein.
- Beim Nacht-Schnellladen erkennt die App das tatsächlich angeschlossene Fahrzeug am SOC-Anstieg und stoppt genau dieses Fahrzeug beim gemeinsamen Nachtziel.
- PV-Prognose zeigt heute, morgen und übermorgen; kompakte Tageskarten mit Uhrzeiten unter dem Balkendiagramm.
- Tages-PV-Automatik nutzt immer den heutigen Forecast, während Nachtplanung separat morgen/übermorgen berücksichtigt.
- Neues PV-Energiebudget: Hauslast, gelernte Speicher-Abendreserve, Warmwasser und Sicherheitsreserve haben Vorrang vor der Wallbox.
- Dynamische PV-Phasensteuerung: Phase 1 ab ca. 1,6 kW, Phase 2 ab 3,6 kW, Phase 3 ab 5,2 kW; einstellbare Hysterese und Haltezeiten.
- Gelernte Abendreserve des Hausspeichers, damit vor dem günstigen Nachtfenster möglichst kein teurer Netzbezug nötig wird.
- Hauptansicht deutlich kompakter: Statuszeile in einer Reihe, Nachtplan komprimiert, Direktsteuerung einklappbar, Energie-Status als Kachelraster.
- 05:00-Hard-Cutoff und unveränderliche Phase-1-Schutzregel bleiben bestehen.

## 0.1.3
- Fahrzeug an der gemeinsamen Wallbox wird nicht mehr automatisch geraten, sondern direkt in der Übersicht als **ID.7 / e-Golf / kein Auto** ausgewählt und dauerhaft gespeichert.
- Nacht- und PV-Ladeentscheidung berücksichtigt ausschließlich das ausgewählte Fahrzeug.
- Temporäres Nachtziel kann direkt in der Nachtkarte für genau eine Nacht gesetzt werden; Rücksetzung automatisch um 05:00.
- Neue prominente **PV-Laden**-Karte mit bestem vierstündigen Strahlungsfenster, erwarteter PV, PV-Automatikstatus und klarer Ladeeinschätzung.
- Neue Karte **Was passiert gerade?** für Wallbox, Speicher und Warmwasser mit aktuellem Zustand und nächster geplanter Aktion.
- Lernmodell auf der Übersicht kompakt; Detailwerte in den Einstellungsbereich verschoben.
- PV-Überschussautomatik startet nur noch, wenn bewusst ein Fahrzeug an der Wallbox ausgewählt ist.
- Ohne ausgewähltes Fahrzeug startet die Nacht-Automatik niemals Schnellladen.
- Push-Text nennt nur noch das ausgewählte Fahrzeug und zusätzlich das beste PV-Ladefenster.
- Harte Regeln unverändert: Phase 1 nie aus; automatische Nachtaktionen spätestens 05:00 beendet.

## 0.1.2
- Mitternachtslogik korrigiert: 00:00–04:59 plant die laufende Nacht weiterhin mit **heute + morgen** statt morgen + übermorgen.
- Vor Mitternacht berechnete HEUTE-Prognose bleibt bis 05:00 erhalten, auch nach App-Neustart oder temporärem Gemini-Fehler.
- Gemini wird bei temporären Fehlern bis zu drei Mal versucht, bevor der physikalische Fallback greift.
- Speicherstaffel basiert jetzt auf der **erwarteten kalibrierten PV-Tagesmenge**: <20 kWh 100 %, 20–30 kWh 60 %, 30–40 kWh 40 %, ab 40 kWh 20 %.
- Speicher-Startzeit/Restladezeit wird live aus aktuellem SOC berechnet; Ziel weiterhin möglichst erst um 05:00.
- Bei sehr schwachem unmittelbar bevorstehendem PV-Tag (<20 kWh Planwert) wird für ein Auto unter Nachtziel Schnellladen empfohlen.
- Nacht-Warmwasser startet bei schwachem PV-Tag ab 00:00 und endet nach der eingestellten Dauer, spätestens 05:00.
- Übersicht zeigt vor 05:00 korrekt **Heute / Morgen**.

## 0.1.1
- Speicherziel nach PV-Planwert: <20 kWh = 100 %, 20–30 kWh = 60 %, 30–40 kWh = 40 %, ab 40 kWh = 20 %.
- Speicher-Netzladung wird dynamisch so spät gestartet bzw. pausiert, dass der Ziel-SOC möglichst erst gegen 05:00 erreicht wird; gelernte Netto-Laderate wird berücksichtigt.
- Nachtlade-Ziel-SOC getrennt für ID.7 und e-Golf einstellbar; Schnellladung endet beim Ziel oder spätestens um 05:00.
- Warmwasser unterhalb des einstellbaren PV-Planwerts nachts bis 05:00, sonst im besten PV-Fenster.
- PV-Überschuss-Wallbox mit einstellbarer Start-/Stoppschwelle und Hysterese.
- Konfliktprüfung vollständig aus der App entfernt.
- Gesamtautomatik und Teilautomatiken nach Freigabe standardmäßig aktiv.
- Direktsteuerung optisch neu gestaltet: Wallbox-Moduskacheln, feste Phasenanzeige sowie große Speicher-/Warmwasser-Schalter.
- Harte Sicherheitsregeln unverändert: Phase 1 nie aus; automatische Nachtaktionen spätestens 05:00 beendet.

## 0.1.0
- Erste Version des Energieplaners.
- Gemini-basierte PV-Prognose für morgen und übermorgen.
- Lernende Kalibrierung auf Basis vorhandener Blindtestdaten und neuer Tageswerte.
- Planung für Speicher, Wallbox und Warmwasser.
- 20:00-Hauptmeldung und 23:30-Änderungscheck.
- Harte 05:00-Sicherheitsgrenze für automatische Nachtaktionen.
- Phase 1 der Wallbox wird durch die App nie ausgeschaltet.
- Separate Einstellungsseite und manuelle Nacht-Overrides.
## 0.1.45

- Nachtladung wieder in den aktiven Scheduler aufgenommen; bei 0 % wird die
  Speicherladung bis mindestens 25 % zuverlässig geplant und gestartet.
- Schaltbefehl der Speicher-Netzladung wird anschließend verifiziert und mit
  Zeitstempel sowie Fehlerstatus protokolliert.
- Ein veralteter gespeicherter Abschluss kann eine neue Unterladung nicht mehr
  blockieren.
- Morgen-/PV-Übernahme zeigt bei einem neuen Tag ausdrücklich den heutigen
  Erfassungsstatus statt unbemerkt den gestrigen Zeitstempel weiterzuführen.
## 0.1.45

- Nachtladung wieder in den aktiven Scheduler aufgenommen; bei 0 % wird die
  Speicherladung bis mindestens 25 % zuverlässig geplant und gestartet.
- Schaltbefehl der Speicher-Netzladung wird anschließend verifiziert und mit
  Zeitstempel sowie Fehlerstatus protokolliert.
- Ein veralteter gespeicherter Abschluss kann eine neue Unterladung nicht mehr
  blockieren.
- Morgen-/PV-Übernahme zeigt bei einem neuen Tag ausdrücklich den heutigen
  Erfassungsstatus statt unbemerkt den gestrigen Zeitstempel weiterzuführen.
