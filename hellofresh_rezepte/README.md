# Rezeptverwaltung

Lokale Home-Assistant-WebApp für HelloFresh- und eigene Rezepte.

## 0.8.19

- Eingeplante Rezepte tragen eine dunkelgrüne Banderole mit „Geplant heute“, „Geplant morgen“ oder dem jeweiligen Wochentag.

## 0.8.18

- In „Offen“ zeigt Vorhanden alle bereits gelieferten, noch nicht gekochten Rezepte; Unterwegs zeigt nur ausstehende Lieferungen.

## 0.8.17

- „Alle Rezepte“ zeigt ausschließlich Zutatenfilter.
- „Offen“ zeigt ausschließlich Alle, Vorhanden und Unterwegs; „Alle“ enthält dort nur noch nicht gekochte Rezepte.

## 0.8.16

- Die Rezeptbibliothek zeigt nur noch die klaren Bereiche Alle, Vorhanden und Unterwegs.
- Zutatenfilter bleiben ohne seitliches Scrollen sichtbar; Kartoffeln ergänzt die wichtigsten Schnellfilter.
- Noch nicht gelieferte Rezepte stehen in „Alle“ unter den verfügbaren Rezepten, bleiben ausgegraut und tragen ein rotes schräges Lieferband mit den verbleibenden Tagen.

## 0.8.15

- HelloFresh-Rezepte übernehmen ihren ausgewählten Liefertermin.
- Noch ausstehende Lieferungen bleiben lesbar, sind als bald lieferbar markiert und erst ab dem Lieferdatum planbar.

## 0.8.14

- Bereits vorhandene HelloFresh-Rezepte werden auf Wunsch als Varianten übernommen und sind in der Vorschau direkt vorausgewählt.
- Die Liefertermin-Auswahl zeigt nahe Termine relativ und weiter entfernte Termine als kompaktes Datum.
- Die Importübersicht ist auf HelloFresh-Übertragung und eigene Rezepte reduziert.

## 0.8.13

- Hintergrundabruf verwendet einen normalen Chromium im geschützten virtuellen Bildschirm, damit die erfolgreiche sichtbare Sitzung nicht durch den Headless-Modus abweicht.
- Die CAPTCHA-Erkennung bewertet nur noch sichtbare Challenges oder eindeutige Challenge-Seiten. Eingebundene CAPTCHA-Skripte auf normalen HelloFresh-Seiten führen nicht mehr zu einem Fehlalarm.
- Supervisor-Protokolle enthalten sichere Abrufdiagnosen ohne Cookies, Storage-Inhalte, Zugangsdaten oder URL-Parameter.

## 0.8.12

- HelloFresh-Zugangsdaten werden jetzt über echte X11-Tastatureingaben in den sichtbaren Chromium geschrieben statt über synthetische JavaScript-Events. Das verhindert, dass die Werte zwar sichtbar sind, HelloFresh/React beim manuellen Login aber einen abweichenden internen Formularzustand verarbeitet.
- Die Zugangsdaten stammen weiterhin ausschließlich aus den Home-Assistant-App-Einstellungen; der Login-Button sowie CAPTCHA/MFA bleiben manuell.

## 0.8.11

- Behebt, dass automatisch eingetragene HelloFresh-Zugangsdaten nach dem ersten Seiten-Render wieder verschwinden konnten. Das Login-Formular wird jetzt bis zum stabilen finalen Render nachgeführt; E-Mail und Passwort bleiben aus den Home-Assistant-App-Einstellungen übernommen.

## 0.8.10

- Der sichtbare HelloFresh-Browser wird nicht mehr mit Selenium/ChromeDriver verbunden. Die in Home Assistant hinterlegten Zugangsdaten werden automatisch vorbefüllt; Anmelden/CAPTCHA/MFA bleiben im sichtbaren Browser.
- Hintergrundabrufe arbeiten nur noch auf einer temporären Profilkopie, damit das je Konto gespeicherte Chromium-Profil nicht durch Root-/Headless-Zugriffe beschädigt wird. Vor dem sichtbaren Login werden Besitzrechte und HOME/XDG-Pfade des Browserbenutzers repariert.

## 0.8.7

- Browserstart vom Web-Aufruf entkoppelt: Das noVNC-Fenster öffnet sofort, während das Eintragen der Zugangsdaten im Hintergrund erfolgt.

## 0.8.6

- Der sichtbare Browser läuft als eigener normaler Linux-Benutzer statt als root. Dadurch ist kein `--no-sandbox`-Startschalter mehr nötig.

## 0.8.5

- Sichtbarer Browser wird unabhängig gestartet und nur lokal zur Formulareingabe verbunden, damit HelloFresh keine sichtbare ChromeDriver-Kennung erhält.

## 0.8.4

- Der sichtbare Browser trägt die als geschützte App-Einstellungen hinterlegten Zugangsdaten für das gewählte Konto ein und startet die Anmeldung; CAPTCHA, MFA und Rückfragen bleiben manuell bedienbar.

## 0.8.3

- Eigenen Browser-Port 6082 verwendet, damit die Rezeptverwaltung parallel zum Vinted Manager auf Port 6081 starten kann.

## 0.8.2

- Sichtbarer HelloFresh-Browser wie beim Vinted Manager: Die App öffnet pro Konto ein eigenes Browserfenster, das in Safari über noVNC bedient wird.
- Login, MFA und CAPTCHA werden einmalig im sichtbaren Browser erledigt. Danach verwendet der Abruf die geschützte, je Konto gespeicherte Sitzung.
- Für den Browser-Login sind keine Zugangsdaten in den App-Einstellungen erforderlich; hinterlegte Zugangsdaten bleiben nur eine optionale Ergänzung.

## 0.8.1

- Bis zu vier HelloFresh-Konten mit getrennten Zugangsdaten und getrennten gespeicherten Browser-Sitzungen.
- Aktives Konto wird im Transfer sichtbar angezeigt; Account-Namen können in den App-Einstellungen frei vergeben werden.
- Liefertermine werden vor der Rezeptvorschau direkt von HelloFresh abgerufen und zur Auswahl angeboten.
- Einrichtung: Konto 1 nutzt die bestehenden Felder `hellofresh_email`, `hellofresh_password` und optional `hellofresh_account_1_label`; Konten 2–4 nutzen jeweils `hellofresh_account_<n>_label`, `_email` und `_password`.

## 0.8.0

- Neuer geführter Ablauf: „Rezepte übertragen“ → Woche auswählen → Vorschau → Import → Fortschritt und Abschlussbericht.
- Überträgt die Rezeptkarten der gewählten HelloFresh-Woche direkt aus der aktuellen Wochenansicht als PDF.
- Bereits vorhandene Rezepte werden vor der Übertragung und nach dem PDF-Download noch einmal erkannt und übersprungen.
- HelloFresh-Zugangsdaten sind ausschließlich als geschützte App-Einstellungen vorgesehen; die Browser-Sitzung bleibt im geschützten App-Datenbereich erhalten.
- Bei Login, CAPTCHA oder einer geänderten HelloFresh-Seite endet der Vorgang verständlich ohne automatische Wiederholung.

## 0.7.3

- Desktop-Übersicht mit deutlich kompakteren Karten für zukünftige Essen; Rezept- und Freitextkarten haben identische Außenmaße.
- Vergangene Tage der laufenden Woche bleiben im Essensplan sichtbar und sind auf Desktop und iPhone dunkelgrau hervorgehoben.
- Auf dem iPhone gibt es im Essensplan einen festen „Heute“-Button zum direkten Sprung auf den aktuellen Tag.
- Die iPhone-Übersicht bleibt unverändert kompakt.

## 0.7.1

- neue Desktop- und iPhone-Oberfläche
- Startseite mit Essensplan und bis zu 10 tatsächlich geplanten Essen
- eigene Bibliothek „Alle Rezepte“ mit Suche, Status-, Favoriten-, Tag- und Sternefiltern
- jeder PDF-/Ordnerimport wird immer als eigenes Rezept gespeichert
- gleich erkannte Rezepte werden als horizontal durchwischbare Varianten gruppiert
- falsch gruppierte Varianten können über „Nicht dasselbe“ dauerhaft gelöst werden
- bestehende Rezept-, Favoriten-, Bewertungs-, Status-, PDF-, Planungs-, Archiv- und Zutatenfunktionen bleiben erhalten
- Zutaten werden bevorzugt an die eigene Einkaufsliste übertragen; Ziel und Token werden automatisch aus Alexa Einkaufsliste Sync bzw. der Einkaufsliste übernommen
- direkter Zugriff: Port 8131
