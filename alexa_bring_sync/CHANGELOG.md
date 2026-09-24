## 0.6.11 — 24.09.2026, 10:13 CEST

- Korrigiert die Erkennung neuer Einträge in der eigenen Einkaufsliste: Besitzt ein Eintrag eine eindeutige ID, wird er nicht mehr durch eine alte, nur namensbasierte Historie fälschlich als bereits bekannt behandelt. Dadurch lösen insbesondere über Siri/CalDAV neu angelegte Artikel wieder zuverlässig genau den bestehenden Push mit Ausrufezeichen aus.
- Der direkte Alexa-Push und die Duplikat-Benachrichtigung bleiben unverändert.

## 0.6.10 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 0.6.9

- Push wird unmittelbar nach dem Ergebnis der Einkaufsliste gesendet — vor dem Erledigen des Alexa-Eintrags und vollständig unabhängig von Gemini-/Bildverarbeitung. Das gilt für erfolgreiche neue Einträge ebenso wie für Duplikate.
- Mobile-App-Notify-Dienste werden aus Array- und Objektformen der Home-Assistant-Serviceantwort erkannt. Wenn keine Geräte aufgelistet werden, wird der bekannte iPhone-Mobile-App-Dienst vor `notify.notify` als Fallback versucht; ein fehlgeschlagener Rich-Push wird einmal als Minimal-Text-Push wiederholt.
- Alexa-Eingaben werden vor dem Import strukturiert: Mengen wie `10x`/`10 Stück` werden vom Artikelnamen getrennt; `Firma`, `REWE`, `DM`, `Rossmann`, `Müller` und Meyerhof werden als Ziel übergeben. Dadurch erhält die Einkaufsliste z. B. `Bananen`, 15 Stück, Ziel `Firma` statt `Bananen 15x Firma`.
- Die bestehende Stabilisierung für den Alexa-Fehlhörer `Firma` → `vier mal` bleibt erhalten; ein alleinstehendes `Butter 4 Stück` wird weiterhin nicht als Firma geraten.

## 0.6.7
- Firma-Import sendet bei strukturierter Erkennung nur noch den bereinigten Basisnamen an die Einkaufsliste.
- Alexa-Diagnose behält den letzten nichtleeren Rohwert und das tatsächlich gesendete Import-Payload, statt beim nächsten leeren Poll alles zu überschreiben.
- ALEXA_IMPORT-Log ergänzt.

## 0.6.6

- Direkte Alexa-Listenwerte wie `Butter 10x Firma` werden jetzt bereits im Sync selbst strukturiert erkannt. Die Menge `10x` bleibt erhalten und `Firma` wird zusätzlich als Kategoriehinweis an die Einkaufsliste übergeben.
- Der Sync verlässt sich damit für diesen Fall nicht mehr darauf, dass die Einkaufsliste den vollständigen Alexa-Rohtext nachträglich korrekt zerlegt. Die bisherigen Varianten `vier mal`, `4 mal`, `viermal` und die Übergangs-Erkennung bleiben erhalten.
- Kategoriehinweise werden zusätzlich als `categoryName` mitgesendet; ältere Einkaufsliste-Versionen bleiben durch den weiterhin kompatiblen Namen `Butter Firma` funktionsfähig.

## 0.6.5

- Alexa-Einträge werden erst importiert, wenn derselbe Eintrag mindestens 10 Sekunden bzw. drei Polls unverändert geblieben ist. Dadurch werden Zwischenstände wie `Butter 10x` nicht mehr sofort als eigener Artikel angelegt oder per KI bebildert.
- Beobachtete Alexa-Änderungen desselben Eintrags werden zusammengeführt. Ändert sich z. B. `Butter 10x` kurz darauf zu `Butter 4 Stück`, wird dies als typischer `Firma`→`vier mal`-Fehlhörer rekonstruiert und als `Butter`, 10 Stück, Kategorie `Firma` übertragen.
- Direkte Formen wie `Butter 10x 4 mal` werden ebenfalls als 10 Stück + `Firma` interpretiert; ein alleinstehendes `Butter 4 Stück` bleibt unverändert und wird nicht als Firma geraten.
- Bei der V2-Alexa-API hat `itemName` jetzt Vorrang vor Legacy-Feldern wie `value`.
- Diagnose speichert vor dem Import einen bereinigten Roh-Snapshot des Alexa-Listeneintrags, zeigt den Stabilisierungs-/Interpretationsstatus in der Weboberfläche und schreibt Logs mit dem ASCII-Marker `ALEXA_RAW`.

## 0.6.4

- Diagnose protokolliert den unveränderten Alexa-Listenwert vor jeder weiteren Verarbeitung als `Alexa roh`.
- Die letzten nichtleeren Alexa-Rohwerte werden zusätzlich in der Diagnoseansicht angezeigt, damit Mengen-/Spracherkennungsfehler ohne Rateversuche nachvollzogen werden können.
- Es werden nur die Namensfelder `value`, `itemName` und `name` protokolliert; keine Kunden-/Sessiondaten.

## 0.6.3

- Push-Benachrichtigungen verwenden jetzt den von der Einkaufsliste bereinigten Artikelnamen statt des rohen Alexa-Texts.
- Auch Duplikat-Pushs zeigen den bereits verarbeiteten Artikelnamen an.
- Die Duplikatentscheidung selbst kommt weiterhin aus der Einkaufsliste; Alexa-Einträge werden erst danach erledigt.
