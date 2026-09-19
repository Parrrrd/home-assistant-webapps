## 0.13.101 — 19.09.2026, 09:24 CEST

- Die Live-Bearbeitung öffnet „Angebot bearbeiten“ jetzt über einen echten Chromium-Mausklick statt über einen synthetischen JavaScript-Klick.
- Das bestehende Bearbeitungsformular wird nicht mehr nur dann akzeptiert, wenn die Artikel-ID in der Editor-URL steht. Der Manager verfolgt den eigens geöffneten Vinted-Tab und erkennt das Formular zusätzlich über die eindeutigen Titel-, Beschreibungs- und Preisfelder. Dadurch funktionieren auch Vinted-Editorrouten ohne Artikel-ID in der URL.
- Die Schutzmechanismen aus den vorherigen Versionen bleiben erhalten: Nur tatsächlich geänderte Felder werden geschrieben und der gespeicherte Stand wird anschließend direkt bei Vinted zurückgeprüft.

## 0.13.100 — 19.09.2026, 08:55 CEST

- Bei der Live-Bearbeitung werden Titel, Beschreibung und Preis vor dem Schreiben mit den bereits in Vinted vorhandenen Formularwerten verglichen. Unveränderte Felder werden nicht mehr neu eingegeben; bei einer reinen Beschreibungsänderung bleibt der Titel vollständig unangetastet.
- Die Erfolgsmeldung nennt nur noch die tatsächlich geänderten Felder. Die abschließende Rückprüfung von Titel, Beschreibung und Preis bleibt bestehen.

## 0.13.99 — 19.09.2026, 08:37 CEST

- Der Manager erkennt Vinteds Sperrseite „Your session has been blocked“ für ungewöhnliche oder automatisierte Aktivität und pausiert dann sämtliche automatischen Vinted-Abfragen und Schreibaktionen.
- Während einer solchen Sperre werden weder Sitzungswiederherstellung noch automatische Browser-Recovery oder Hintergrundabfragen weiter ausgeführt. Erst nach einer regulär wieder erreichbaren Seite und bestätigter Anmeldung wird die Vinted-Automatik fortgesetzt.

## 0.13.98 — 19.09.2026, 08:00 CEST

- Die Live-Bearbeitung akzeptiert eine Vinted-Artikelseite jetzt bereits, sobald ihr Dokument interaktiv und nicht mehr im Ladezustand ist. Offene Bild- oder Hintergrundanfragen können dadurch nicht mehr fälschlich den Fehler „Die Vinted-Seite wurde nicht vollständig geladen“ auslösen.

## 0.13.97 — 19.09.2026, 01:38 CEST

- Die Live-Bearbeitung verwendet für Titel, Beschreibung und Preis jetzt dieselben eindeutigen Vinted-Feldselektoren wie der bewährte Veröffentlichungsweg. Dadurch kann kein anderes Eingabefeld mehr fälschlich als Titel erkannt werden.

## 0.13.96 — 19.09.2026, 01:10 CEST

- Live-Änderungen werden jetzt über echte Chromium-Tastatur- und Mausereignisse in Vinteds Bearbeitungsformular eingegeben und gespeichert, damit Vinteds React-Zustand die Werte tatsächlich übernimmt.
- Nach dem Speichern werden Titel, Beschreibung und Preis direkt an der bestehenden Vinted-Anzeige zurückgelesen. Eine reine Beschreibungsänderung kann dadurch nicht mehr fälschlich als erfolgreich gemeldet werden.

## 0.13.95 — 19.09.2026, 00:53 CEST

- Die Live-Bearbeitung scrollt jetzt auch Vinteds interne Formularbereiche bis zum Ende und erkennt den zugehörigen Speichern- bzw. Submit-Button zuverlässig, wenn er erst ganz unten eingeblendet wird.

## 0.13.94 — 18.09.2026, 22:28 CEST

- Der Vinted-Browser bleibt standardmäßig aktiv, damit eine Sitzungswiederherstellung nicht durch einen Ruhezustand gestört wird.
- Eine bestätigte Vinted-Abmeldung löst wieder eine kritische, lautlose Push-Mitteilung auf Patricks iPhone aus. Der Dienst kann in der Home-Assistant-App-Konfiguration angepasst werden.
- E-Mail-Adresse und Passwort können optional in der lokalen Home-Assistant-App-Konfiguration hinterlegt werden. Bei einer nötigen erneuten Anmeldung trägt der sichtbare Browser sie vorab ein; Anmeldung, Zwei-Faktor-Code und Sicherheitsprüfungen bleiben bewusst manuell.
- Bei „Prüfen & korrigieren“ wird der Katalog vorbereitet, ohne eine Kategorie auszuwählen. Beim anschließenden Bearbeiten steht er sofort bereit.
- Die Live-Bearbeitung sucht den Speichern-Button jetzt auch nach dem Nachladen weiter unten im Vinted-Formular.

## 0.13.93 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 0.13.92 — 18.09.2026, 20:51 CEST

- App-Code erstmals bereinigt in das zentrale GitHub-Repository übernommen. Laufzeitdaten und persönliche Einstellungen bleiben ausschließlich in Home Assistant.

# Changelog
