# Energieplaner

Ab Version 0.1.58 hat die Wallbox eine echte Speicherpriorität: Die PV-Automatik nutzt nur den nach Haus und laufender Speicherladung tatsächlich verfügbaren Überschuss und reserviert im Tagesbudget zuerst genug Rest-PV, damit der Hausspeicher voraussichtlich noch 100 % erreichen kann. Bei deutlich hinter der Prognose liegendem PV-Tag bzw. kurz vor PV-Ende bleibt die automatische Fahrzeugladung unter 95 % Speicher-SOC zusätzlich gesperrt. Auf der Übersicht gibt es eine manuelle Ladepause, beide Fahrzeug-SOCs/Kabelzustände und eine kompakte Ist-/Soll-/Rest-PV-Zeile. Die iPhone-Kopfzeile berücksichtigt die Safe Area.

Ab Version 0.1.47 plant der Speicher das 05:00-Ziel für die Morgenbrücke aus der separat gelernten Standby-/Restlast und dem stündlichen PV-Profil. Gemini schätzt den Zeitpunkt der stabilen PV-Übernahme; die App berechnet den Nettoenergiebedarf von 05:00 bis dahin selbst und lernt Zeit- und Energieabweichungen getrennt. Die Tagesgrundlast (Start 0,85 kW) bleibt für die Resttag- und Tagesbilanz zuständig. Die Mindestreserve lernt weiterhin langsam; eine manuelle SOC-Korrektur bleibt möglich. Die PV-Hochstufung auf 2/3 Phasen wartet 30 Minuten, die Herabstufung bleibt schnell. Die geplanten 20:00-/07:00-Läufe besitzen Catch-up-Logik und die Push-Nachrichten sind kompakter.
Ab Version 0.1.57 zeigt auch die iPhone-Ansicht in jedem Energiefluss-Knoten den Tageswert. Die mobilen Karten sind bewusst kompakter, damit die gerichteten und animierten Flussverbindungen zwischen Quellen, Haus und Verbrauchern sichtbar bleiben.


Ab Version 0.1.53 zeigt die Übersicht den Live-Energiefluss als Ebenenmodell: Quellen und Speicher oben, das Haus als zentraler Verteiler in der Mitte und die direkt erfassten Verbraucher darunter. Aktive Verbindungen zeigen Richtung und Menge; Netz und Speicher sind bidirektional.

Lokale Home-Assistant-App für eine lernende PV-Prognose und die gemeinsame Planung von Speicher, Wallbox, Fahrzeugen und Warmwasser.

Ab Version 0.1.4 arbeitet die gemeinsame Wallbox nur noch mit „Auto an Wallbox: Ja/Nein“. ID.7 und e-Golf bleiben beide für die 48-Stunden-Entscheidung sichtbar; beim Nachtladen erkennt die App das tatsächlich ladende Fahrzeug automatisch daran, welcher SOC ansteigt, und stoppt dieses Fahrzeug am eingestellten gemeinsamen Nachtziel.

Die PV-Wallbox erhält ein konservatives Restenergie-Budget. Hausverbrauch, gelernte Speicher-Abendreserve, Warmwasser und Sicherheitsreserve werden zuerst abgezogen. Nur der verbleibende PV-Anteil wird dem Auto freigegeben. Bei genügend Überschuss schaltet die App dynamisch von einer auf zwei beziehungsweise drei Phasen; Phase 1 bleibt immer eingeschaltet.

Die Übersicht zeigt den heutigen Tag live; die separaten Tageskarten darunter zeigen nur noch morgen und übermorgen mit Stundenachse unter der PV-Kurve. Direktsteuerung ist einklappbar, technische Lernwerte liegen unter Einstellungen. Automatische Nachtladung von Speicher, Wallbox und Nacht-Warmwasser endet weiterhin spätestens um 05:00 Uhr.


Ab Version 0.1.5 ist die Übersicht weiter verdichtet: Gemini-Status und aktuelle Aktionen sind kompakter, die drei PV-Tageskarten besitzen einen Seitenindikator und die PV-Budgetkarte zeigt zusätzlich die voraussichtlich geschützte Speicherreserve am Abend sowie das Risiko für Netzbezug vor 00:00. Das temporäre Nachtziel des tatsächlich ladenden Autos lässt sich über Prozent-Schnellwahltasten setzen.
Seit 0.1.6 arbeitet der Energieplaner mit begrenztem Gemini-Kontingent. Ab 0.1.33 läuft die vollständige Gemini-Prognose jeweils fünf Minuten vor dem 07:00- und dem 20:00-Push (standardmäßig 06:55 und 19:55). Diese beiden festen Termine werden gegenüber manuellen oder Startup-Aufrufen im Tageskontingent priorisiert. Live-PV-Nachführung und normale Einstellungsänderungen lösen weiterhin keinen Gemini-Aufruf aus.


Ab Version 0.1.7 wird das sichere PV-Budget fürs Auto strenger priorisiert: Die verbleibende PV-Energie wird zuerst für den erwarteten Hausverbrauch bis PV-Ende, die benötigte Speicherenergie für PV-Ende bis 00:00, gegebenenfalls Warmwasser und die Sicherheitsreserve reserviert. Der Hausverbrauch startet mit 0,70 kW Grundlast und bleibt einstellbar. Die Budgetkarte zeigt diese Abzüge transparent.


Ab Version 0.1.8 ist das Speicherziel um 05:00 nicht mehr über feste PV-kWh-Stufen definiert. Die normale Morgenbasis startet bewusst knapp bei 35 % und lernt täglich aus dem realen Nettoverbrauch zwischen 05:00 und stabiler PV-Deckung. Ziel ist ungefähr 16 % Rest-SOC beim Übergang auf PV. Ist regelmäßig zu viel übrig, sinkt die Basis schrittweise; reicht sie nicht, steigt sie. Schlechte Folgetage erhalten zusätzlich eine stufenlose Tagesreserve bis hin zu 100 % bei sehr wenig erwarteter PV. Die Nachtübersicht zeigt Basis und Tagesreserve getrennt sowie eine Empfehlung „Spülmaschine heute Nacht günstig“ oder „morgen mit PV“.


Ab Version 0.1.9 lädt die Oberfläche Home-Assistant-Zustände gebündelt statt mit vielen einzelnen Sensorabfragen. Dadurch öffnen Dashboard und Bedienelemente deutlich schneller. „Was passiert gerade?“ und „Was passiert heute Nacht?“ stehen direkt oben, Heute/Morgen/Übermorgen bilden eine gemeinsame seitlich scrollbare PV-Zeile und ein kompakter Energiefluss zeigt PV, Haus, Speicher, Netz und Wallbox. Die Trennung von Nachtziel und Wallbox-Modus wurde anschließend in 0.1.10 korrigiert.


## Wallbox-Modi 0.1.10

- **Automatik:** tagsüber PV-Überschussladen ohne SOC-Untergrenze; 00:00–05:00 wird nur bis zum gewählten Mindest-SOC ergänzt.
- **Nacht schnell:** 00:00–05:00 Schnellladen bis zum gewählten Ziel.
- **Nur PV:** ausschließlich PV-Überschussladen; nachts niemals Schnellladen.

Der Prozentwert ist unabhängig vom Modus und beschreibt den gewünschten Mindest-SOC für die Nacht.


## Oberfläche 0.1.13

Der Dashboard-Abruf funktioniert sowohl über den festen Port als auch über Home-Assistant-Ingress mit einem automatischen Pfad-Fallback. Lade- und Frontendfehler werden sichtbar angezeigt; außerdem werden die einzelnen Dashboard-Bereiche unabhängig gerendert, damit ein einzelner Darstellungsfehler nicht mehr die komplette Übersicht leer lässt.


## 0.1.12
- Oberfläche wieder näher am bewährten Stand 0.1.8, ohne großes Energiefluss-Diagramm.
- Kompakte Leistungsbilanz mit +/− für PV, Speicher, Netz, Haus und Wallbox.
- Dashboard wird serverseitig im Hintergrund gecacht und beim Öffnen sofort ausgeliefert.
- Nachtziel- und Modus-Buttons reagieren sofort; Nachtziel und Modus bleiben unabhängig.


## 0.1.13
- Nacht-Modus- und Mindest-SOC-Buttons behalten den neuen Zustand sofort sichtbar, auch solange der Dashboard-Cache noch den alten Serverzustand liefert.
- „Was passiert gerade?“ zeigt keinen Fahrzeugnamen und kein Nachtziel mehr, außer während tatsächlicher Schnellladung.
- „Was passiert heute Nacht?“ zeigt bei Automatik und Unterschreitung klar „Schnellladung bis X %“; der Text „erkannt“ wurde entfernt.
- Energie jetzt ergänzt Wärmepumpe; PV wird ohne Pluszeichen dargestellt.
- Neue Tagesbilanz für PV, Netzbezug, Einspeisung, Wallbox, Wärmepumpe sowie Speicher laden/entladen.
- PV Heute live, Morgen und Übermorgen sind eine gemeinsame horizontal wischbare Kartenleiste.


## 0.1.17
- 20:00-Energieplan im kompakten Push-Format, kritisch aber lautlos (Volume 0).
- 07:00 nur bei Änderungen an PV, Speicher-Nachtladung, Autos, Überschussladen, Spülmaschine oder Warmwasser.
- Test-Push direkt unter Einstellungen.
- Obere Dashboard-Karten kompakter, PV-Rest direkt neben Warmwasser, Nachtplanung in zwei Zeilen.

## 0.1.18
- Responsive Kartenaufteilung für Desktop, Tablet und iPhone.
- Aktuelle Wallbox zeigt Leistung und Phasen direkt aus den bestehenden drei Phasenschaltern.
- „Was passiert gerade?“ und Nacht-/Morgenplanung auf die kompakten gewünschten Informationen reduziert.
