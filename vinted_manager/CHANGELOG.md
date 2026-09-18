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
