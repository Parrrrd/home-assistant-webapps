## 0.8.20 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

# Changelog

## 0.8.15

- Der beim HelloFresh-Import ausgewählte Liefertermin wird jetzt am Rezept gespeichert.
- Bereits unmittelbar vor dem Update importierte HelloFresh-Rezepte erhalten den zuletzt ausgewählten Liefertermin beim ersten Start automatisch nachgetragen.
- Noch nicht gelieferte Rezepte sind im Bereich „Offen“ ausgegraut und mit „Wird bald geliefert“ gekennzeichnet. Sie bleiben vollständig öffnbar.
- Die Planung lässt diese Rezepte erst am Lieferdatum und danach zu; dies gilt für die Übersicht, die Rezeptdetailseite und den Essensplan selbst.

## 0.8.14

- Bereits vorhandene HelloFresh-Rezepte können jetzt ausgewählt werden und werden als Varianten importiert; sie sind standardmäßig mit ausgewählt.
- Liefertermine zeigen für nahe Termine verständliche Bezeichnungen wie „Letzten Samstag“ oder „Kommenden Samstag“ und für weiter entfernte Termine ein kurzes Datum.
- Die Importseite enthält nur noch „HelloFresh-Rezepte übertragen“ und „Eigenes Rezept“. Die HelloFresh-Ansicht wurde auf Konto, Liefertermin, Status und Rezeptauswahl reduziert.

## 0.8.13

- Hintergrundabruf: Der temporäre Browser läuft jetzt als normaler Chromium im vorhandenen virtuellen Bildschirm statt als Headless-Browser. Dadurch erhält HelloFresh dieselbe Browserart wie beim sichtbaren Login, ohne das dauerhafte Profil anzutasten.
- Der Abruf verwendet wie der sichtbare Browser ausdrücklich `--password-store=basic` und `Default` als Profil. Cookies, Local Storage und Session Storage aus dem je Konto gespeicherten Profil werden vollständig in die kurzlebige Kopie übernommen.
- CAPTCHA-Erkennung präzisiert: allgemeine, auf normalen Seiten eingebundene CAPTCHA-/Challenge-Skripte lösen keinen Fehlalarm mehr aus. Abgebrochen wird nur bei einer sichtbaren Challenge oder eindeutigen Challenge-Seitentexten.
- Sichere Supervisor-Diagnosen ergänzt: je Abruf werden Kontoslot, Zustand der kopierten Sitzungsdateien sowie bereinigte URL und Seitentitel protokolliert. Cookies, Storage-Inhalte, Zugangsdaten und URL-Parameter werden nie ausgegeben.

## 0.8.12

- HelloFresh-Login: sichtbare, aber beim Absenden von HelloFresh trotzdem abgelehnte Zugangsdaten behoben.
- E-Mail und Passwort werden nicht mehr per JavaScript/CDP direkt in die DOM-Felder geschrieben. CDP liest nur noch Position und aktuellen Inhalt der Felder.
- Die eigentliche Eingabe erfolgt jetzt über echte X11-Maus-/Tastaturereignisse (`xdotool`) im sichtbaren Chromium. Dadurch erhält React den normalen Formular-State wie bei manueller Eingabe; Login-Button, CAPTCHA und MFA bleiben weiterhin manuell.
- Wenn HelloFresh das Formular während der Hydrierung ersetzt, wird die X11-Eingabe erneut ausgeführt, bis beide Felder stabil stehen.

## 0.8.11

- HelloFresh-Login: kurz sichtbare und anschließend wieder verschwindende Zugangsdaten behoben.
- Das automatische Befüllen aktualisiert nun auch den State von React/controlled inputs und wartet, bis E-Mail und Passwort mehrere Sekunden stabil im final gerenderten Login-Formular stehen.
- Wenn HelloFresh das Formular während der Hydrierung ersetzt, werden die Zugangsdaten automatisch erneut aus den geschützten Home-Assistant-App-Einstellungen eingetragen; der Login-Button bleibt weiterhin manuell.

## 0.8.10

- HelloFresh-Login: automatisches Befüllen von E-Mail und Passwort robuster gemacht.
- Login-Felder werden nicht mehr über starre CSS-Selektoren gesucht, sondern anhand von Typ, Name, ID, Placeholder, Autocomplete und Labels erkannt.
- CDP-Autofill prüft zusätzlich eingebettete iframe-Targets, damit geänderte HelloFresh-Login-Layouts nicht zu leeren Feldern führen.
- Der sichtbare Browser bleibt weiterhin ohne Selenium/ChromeDriver-Anbindung; der eigentliche Login-Button sowie CAPTCHA/MFA bleiben manuell.

## 0.8.9
- Sichtbarer HelloFresh-Login vollständig von ChromeDriver/Selenium getrennt: Chromium läuft als normaler `hf-browser`; E-Mail-Adresse und Passwort werden nur vorbefüllt, der Login-Button bleibt für CAPTCHA/MFA bewusst manuell.
- Hintergrundabrufe verwenden jetzt wie beim bewährten Kleinanzeigen-Ablauf ausschließlich eine kurzlebige Kopie des gespeicherten Browserprofils. Dadurch verändert der Root-/Headless-Browser das dauerhafte Profil nicht mehr.
- Das je Konto gespeicherte Chromium-Profil wird vor dem sichtbaren Start rekursiv auf `hf-browser` zurückgesetzt; `HOME` sowie XDG-Konfigurations-/Cachepfade laufen ebenfalls unter `/data/hellofresh-browser`. Verwaiste Chromium-Locks werden entfernt. Damit wird der bisherige „Your preferences can not be read“-Fehler behoben.

## 0.8.7
- Der Browserstart blockiert die Weboberfläche nicht mehr. noVNC öffnet sofort, auch wenn HelloFresh beim Anmelden langsam antwortet.

## 0.8.6
- Sichtbaren HelloFresh-Browser auf einen eigenen unprivilegierten Linux-Benutzer umgestellt. Die bisherige `--no-sandbox`-Warnung entfällt.

## 0.8.5
- Der sichtbare Chromium-Browser läuft unabhängig von ChromeDriver. Dadurch verschwindet die sichtbare Automatisierungs-Kennung, die den HelloFresh-Login pauschal ablehnen konnte.

## 0.8.4
- Der sichtbare Browser füllt E-Mail-Adresse und Passwort aus den geschützten App-Einstellungen des gewählten Kontos ein und löst die Anmeldung aus. Nur CAPTCHA, MFA und Rückfragen bleiben beim Nutzer.

## 0.8.3
- Port-Konflikt mit dem Vinted Manager behoben: Das HelloFresh-Anmeldefenster verwendet jetzt Port 6082 statt 6081.

## 0.8.2
- Sichtbaren HelloFresh-Browser über Xvfb, x11vnc und noVNC ergänzt, analog zum etablierten Vinted-Manager-Ablauf.
- Jede der vier Konto-Sitzungen kann nun im eigenen Browserfenster manuell angemeldet werden; CAPTCHA und MFA bleiben vollständig durch den Nutzer bedienbar.
- Der Hintergrundabruf startet nicht parallel zu einem sichtbaren Browser und fordert bei fehlender Sitzung verständlich zum manuellen Login auf.

## 0.8.1
- Bis zu vier separat konfigurierbare HelloFresh-Konten ergänzt. Jedes Konto erhält ein eigenes Chrome-Profil unter `/data`, damit Sitzungen beim Kontowechsel nicht überschrieben werden.
- Abruf der verfügbaren Liefertermine vor der Rezeptvorschau ergänzt. Der gewünschte Termin wird anschließend explizit ausgewählt.
- Die Oberfläche zeigt das aktive Konto nach erfolgreicher Anmeldung beziehungsweise anhand des hinterlegten Kontonamens an.

## 0.8.0
- Neuer HelloFresh-Transfer mit geführter Auswahl der bald liefernden oder bereits gelieferten Woche, Vorschau der gefundenen Rezepte, Auswahl einzelner Karten, Fortschrittsanzeige und Abschlussbericht.
- Der geprüfte aktuelle HelloFresh-Ablauf verwendet die Wochenansicht unter „Meine Lieferungen“, die Rezeptkarten im Bereich „Deine Bestellung“ und den Link „Herunterladen“ in der Rezeptdetailansicht.
- Die Rezeptkarten werden als PDFs abgelegt und über den bestehenden lokalen Importweg übernommen.
- Bereits vorhandene Titel werden in der Vorschau markiert und beim Import zusätzlich abgesichert übersprungen; bestehende Varianten- und manuelle Importfunktionen bleiben unverändert.
- Zugangsdaten werden ausschließlich über die als Passwort markierten Home-Assistant-App-Einstellungen verwendet. Browserprofil und Sitzung liegen unter `/data` mit eingeschränkten Rechten.
- CAPTCHA, MFA/Anmeldeprobleme und unbekannte Seitenzustände brechen einmalig mit einer klaren Meldung ab.
- Browser-Unterstützung über die Alpine-Pakete `chromium` und `chromium-chromedriver`; Python-Paket `selenium` ist rein Python-basiert.

## 0.7.3
- Desktop-Übersicht: zukünftige Essensplan-Karten deutlich kompakter; Freitext- und Rezeptkarten haben identische Außenmaße.
- Essensplan: vergangene Tage der aktuellen Woche bleiben sichtbar und sind auf Desktop und iPhone deutlich dunkelgrau markiert.
- iPhone-Essensplan: schwebender „Heute“-Button springt direkt zum aktuellen Tag.
- iPhone-Übersicht bleibt in ihrer bisherigen 0.7.2-Darstellung unverändert.

## 0.7.2
- Übersicht vollständig auf den Essensplan reduziert: nur noch die Überschrift „Die nächsten geplanten Essen“ und alle zukünftigen, tatsächlich eingetragenen Essen.
- Keine Begrenzung auf zehn Einträge und keine zusätzlichen Kennzahlen, Schnellzugriffe oder Erklärungstexte auf der Übersicht.
- Essensplan bereinigt: doppelte Einleitung entfernt und „Alle Änderungen speichern“ nur noch einmal als gemeinsame Speicheraktion.
- Varianten auf dem iPhone wischen jetzt jeweils kartenweise; die Rezeptvorschau ist am oberen Bildrand ausgerichtet, damit der Rezeptname auf der HelloFresh-Karte nicht abgeschnitten wird.
- Unter „Offen“ kann jedes Rezept direkt einem freien Tag von heute bis zum Ende der nächsten Woche zugewiesen werden. Vergangene Tage werden nicht angeboten.
- Mehrere Tag-Zuweisungen lassen sich gesammelt mit einer einzigen Aktion speichern.

## 0.7.1
- Übersicht kompakter und stärker auf den Essensplan fokussiert.
- Essensplan kann jetzt über mehrere Tage bearbeitet und mit einem gemeinsamen Speichern übernommen werden.
- Mobile Hauptnavigation: Favoriten durch „Offen“ mit aktuellem Zähler ersetzt; Favoriten bleiben als Bibliotheksfilter erhalten.

## 0.7.0

- Komplettes neues Desktop-/iPhone-Design mit Sidebar bzw. Bottom-Navigation.
- Startseite auf den Essensplan fokussiert; die vollständige Rezeptbibliothek ist ein eigener Bereich.
- Bis zu 10 tatsächlich geplante kommende Essen auf der Übersicht; leere Tage werden nicht angezeigt.
- Jeder PDF-/Ordner-Import wird immer als eigener Rezeptdatensatz gespeichert.
- Gleich erkannte Rezepte werden als Varianten gruppiert und horizontal durchwischbar dargestellt.
- Einzelne Varianten können dauerhaft mit „Nicht dasselbe“ aus einer Gruppe gelöst werden.
- Alte vorgemerkte Duplikate werden beim ersten Start als normale Varianten übernommen.
- Zutatenübertragung verwendet die eigene Einkaufsliste und automatisch dieselbe Ziel-Liste wie Alexa Einkaufsliste Sync; die alte Home-Assistant-Todo-/Ringbuch-Liste wird nicht mehr verwendet.
- Buildbasis auf Home-Assistant base-python 3.14 / Alpine 3.24 festgelegt; native Python-Abhängigkeiten werden ausschließlich als Binärpakete installiert.

## 0.6.5

- Doppelte manuelle Import-Aktualisierung entfernt.
- Das Aktualisieren-Symbol oben rechts ist jetzt die einzige manuelle Importprüfung.
- Das Symbol prüft weiterhin `/media/Import/Rezepte` und aktualisiert anschließend die Übersicht.
- Beschriftung und Hinweise in der Oberfläche entsprechend vereinheitlicht.

## 0.6.4

- Importordner auf `/media/Import/Rezepte` umgestellt.
- Importablauf an den Kleinanzeigen-Manager angeglichen: automatische stündliche Prüfung, manuelle Aktualisierung und sichtbarer Importstatus.
- Fehlerhafte PDFs werden nach `/media/Import/Rezepte/Fehler` verschoben und erhalten eine `.fehler.txt` mit der Ursache.
- Erfolgreich übernommene PDF-Dateien werden nach der sicheren Speicherung aus dem Importordner entfernt.
- Media-Freigabe in `config.yaml` ergänzt.

## 0.6.3

- Fehler behoben: Wenn ein gekochtes Rezept über den Status-Button wieder auf offen gestellt wird, wird jetzt wirklich der Status `offen` gespeichert. Dadurch erscheint es wieder im Bereich „Offen“.

## 0.6.2
- Button-Beschriftung korrigiert: „Rezept als vorhanden markieren“ heißt jetzt „Rezept als offen markieren“.
- Funktion bleibt unverändert: gekochte Rezepte können wieder auf Offen gesetzt werden.


## 0.6.1
- Mögliche Duplikate zeigen jetzt neuen Import und vorhandenes Rezept nebeneinander an.
- Duplikat verwerfen markiert das vorhandene Rezept wieder als offen.
- Rezept-Aktionsbuttons sind klarer als Buttons erkennbar und ausführlicher beschriftet.

## 0.5.9
- Mögliche Duplikate werden nicht mehr nur verworfen, sondern vorgemerkt.
- Auf der Übersicht können falsch erkannte Duplikate per „Trotzdem behalten“ importiert werden.
- PDF-Prüfung und Verwerfen vorgemerkter Duplikate ergänzt.

## 0.4.22
- Bereits vorhandene Rezepte werden beim erneuten Upload nicht doppelt angelegt, aber automatisch wieder auf **Offen** gesetzt.

## 0.4.21
- Home-Bildschirm-Icon und Name für iPhone/iPad ergänzt
- Neues Rezeptverwaltung-Icon eingebaut
- Web-App-Manifest und Apple-Touch-Icon hinzugefügt
- Dockerfile auf direktes Home-Assistant-Basisimage umgestellt

## 0.4.20
- Fehler beim Button "Speichern" auf der Einkaufslisten-Seite behoben
- Rezeptsuchtext wird nach Zutaten-Korrekturen wieder korrekt neu aufgebaut

## 0.4.19
- Manuelle Zutaten-Korrekturen auf der Einkaufslisten-Seite werden jetzt nach erfolgreicher Übertragung auch direkt im Rezept gespeichert.
- Korrigierte Zutaten-Namen werden dadurch sowohl für künftige Rezepte gelernt als auch im aktuellen Rezept dauerhaft bereinigt.

## 0.4.17
- Übersicht zeigt den Block "Zuletzt gekocht" nicht mehr an.
- Neuer dritter Rezeptstatus "Vorhanden" ergänzt: Rezepte können gespeichert sein, ohne in der offenen Liste zu erscheinen oder als gekocht zu gelten.
- Import von PDFs und Anlegen eigener Rezepte erlauben jetzt direkt die Auswahl zwischen "Offen" und "Vorhanden".
- Planung bietet jetzt offene und vorhandene Rezepte an; gekocht bleibt getrennt.

## 0.4.16
- Basiszutaten wie Salz, Pfeffer, Wasser, Öl und Butter bleiben auf der Einkaufslisten-Seite sichtbar, sind aber standardmäßig nicht angehakt.
- Zutaten können vor dem Übertragen weiterhin manuell bearbeitet werden; manuelle Korrekturen werden jetzt für spätere Rezepte gemerkt.
- Zutaten-Normalisierung verbessert, u. a. für Länderkürzel am Wortende, fehlende Leerzeichen und mehrere typische OCR-Fehler.
- Erfolgsrückmeldung beim Übertragen auf die Einkaufsliste erweitert.
- Texte in der Oberfläche weiter auf die allgemeine Rezeptverwaltung vereinheitlicht.

## 0.4.15
- Fehler beim Übertragen auf `todo.add_item` behoben: ungültiges Feld entfernt und robusten Fallback für unterschiedliche Service-Aufrufe ergänzt.
- Auf der Einkaufsliste-Seite können Zutaten vor dem Übertragen jetzt direkt manuell korrigiert werden.
- App, Panel und Beschreibungen neutraler auf „Rezeptverwaltung“ umbenannt.

## 0.4.14
- OCR-Fallback greift jetzt auch dann, wenn die PDF-Tabellen nur unplausible Treffer wie „Kochutensilien“ oder einzelne Schrittüberschriften liefern.
- Zutaten aus problematischen HelloFresh-PDFs mit zusätzlichem Block „Kochutensilien“ auf Seite 2 werden jetzt wieder übernommen.
- Automatische Nachkorrektur für typische OCR-Fehler bei Zutatennamen ergänzt, z. B. Länderkürzel am Wortende, „Hähnchenbrustfilet in Lake“, „Maisstärke“, „Sesamöl“ und „Zitronenthymian“.

## 0.4.13
- Zutaten-Erkennung für HelloFresh-PDFs auf OCR für den linken Zutatenblock von Seite 2 umgestellt.
- Es wird gezielt die 3P-Spalte gelesen, damit keine Kochschritte mehr im Zutatenfeld landen.
- OCR wird als Fallback genutzt, wenn die normale PDF-Textschicht leer oder verdächtig ist.

## 0.4.7
- Bestehende Rezepte werden beim Start aus den PDFs neu analysiert, damit Titel wie 'Limone Zitronige' oder 'Oregano dazu' korrigiert werden.
- Kalorien werden in der Essensplanung angezeigt.

0.4.6
- Fehlende Leerzeichen in Rezepttiteln an Zeilenumbrüchen besser repariert (z. B. Kumindazu -> Kumin dazu, Krustenschinkenund -> Krustenschinken und)
- Bestehende Titel/Subtitel werden bei der Anzeige ebenfalls bereinigt

## 0.4.4
- OCR-Titel verbessert: fehlende Leerzeichen an Zeilenumbrüchen wie „Kumin dazu“ oder „Krustenschinken und“ werden repariert.
- Titel/Subtitel-Erkennung bei zusammengezogenen OCR-Zeilen robuster gemacht.

## 0.4.3
- Falsche Rezeptnummern-Anzeigen entfernt.
- Keine Nummern-Badges mehr auf Übersicht und Detailseite.
- Feld Rezeptnummer aus der Verwaltung entfernt.

## 0.4.2
- Übersichts-Titel auf Rezeptverwaltung geändert
- Freitext in der Essensplanung auf der Übersicht nicht mehr anklickbar
- In der Planung werden nur noch offene HF-Rezepte angeboten
- Detailseite vereinfacht: Status nur noch offen/gekocht, Empfehlung entfernt
- Eingabefelder für Lieferdatum und Gekocht am optisch angeglichen

# Changelog

## 0.4.1
- Übersicht verschlankt: Statistik ohne "Diese Woche", keine mittlere Filterzeile, kein "Zuletzt importiert" auf der Startseite
- Essenplanung-Vorschau zeigt jetzt Wochentag + Datum; HF-Einträge sind direkt anklickbar
- Upload-Seite zeigt zuletzt importierte Rezepte
- Favoriten mit Top 10 und Stern-Filter
- Rezept-Detailseite kann direkt einem Planungstag zugeordnet werden
- Planungsliste zeigt alle HF-Rezepte, auch bereits gekochte

## 0.4.0
- Neue Essenplanung für aktuelle und kommende Woche
- Rezepte oder Freitext pro Wochentag planen
- Planung jetzt auch auf der Übersicht sichtbar

## 0.3.0
- Duplikat-Erkennung jetzt anhand des Rezepttitels statt Dateinamen
- mittlere Filterleiste auf der Übersicht entfernt
- Detailseite: Titel/Untertitel im Kopf schwarz für lange Titel
- Detailseite: PDF-Vorschau-Bereich entfernt

## 0.2.6
- Fix für Syntaxfehler in recipe_save, der das Add-on direkt nach dem Start beendet hat.
- Kompakte Statistikzeile bleibt erhalten.
- PDF-Vorschau-Logik unverändert.

## 0.2.5
- PDF-Vorschau robuster: erste Seite wird als PNG gerendert.
- Bestehende alte Vorschaubilder werden automatisch neu erzeugt.
- Kompakte Statistik-Zeile oben bleibt erhalten.

## 0.2.4
- Kompaktere Zähler oben als eine Zeile statt großer Karten
- Vorschau-Bilder mit korrektem MIME-Typ ausliefern

## 0.2.3
- Fix für Dashboard-/Detail-Template bei Tag-Anzeige.
- Vorschau-Bilder und Auto-Import bleiben erhalten.

# Changelog

## 0.2.2
- Stabiles Build-Setup wie beim funktionierenden Kinderbudget-Add-on
- Automatischer Import aus /share/HelloFresh/import alle 30 Minuten
- Kleine Vorschau-Bilder aus dem größten eingebetteten Bild der ersten PDF-Seite
- Weboberfläche auf Port 8131

## 0.4.10
- Eigene Rezepte ohne Platzhalterbild in den Listen.
- Zutaten-Erkennung aus HelloFresh-PDFs über linke Zutaten-Spalte verbessert.
- Verdächtige Alt-Zutaten werden beim Start neu erzeugt.
