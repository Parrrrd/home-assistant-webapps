## 0.13.110 — 19.09.2026, 19:26 CEST

- Verifizierter Referenzstand: Das Bearbeiten bereits veröffentlichter Vinted-Anzeigen funktioniert wieder vollständig, einschließlich des Speicherns der Änderungen über die bestehende Live-Bearbeitung.
- Die beiden persönlichen Profile und Push-Empfänger werden wieder korrekt als Patrick und Katharina angezeigt. Die technischen Schlüssel `primary` und `secondary` bleiben intern unverändert.
- Gegenüber 0.13.109 gibt es keine funktionalen Änderungen. Dieser Stand ist bewusst als bekannte funktionierende Basis markiert, damit ein späterer Rückschritt bei Bearbeitung oder Personen-Zuordnung in GitHub sofort erkennbar ist.

## 0.13.109 — 19.09.2026, 17:51 CEST

- Die sichtbaren Bezeichnungen der beiden Push-Profile werden nun vorrangig aus den lokalen Home-Assistant-Personen ermittelt. Technische Geräte-Slugs wie `iphone_a` oder `secondary_iphone` können dadurch nicht mehr als Personenname in der Oberfläche erscheinen.
- Die Zuordnung nutzt nur die bereits vorhandenen neutralen Profil-Initialen und die lokale Home-Assistant-API. Ermittelte Namen werden nicht in Repository oder Update-Paket geschrieben.
- Unter Einstellungen können die beiden Anzeigenamen zusätzlich lokal überschrieben werden; diese Werte bleiben ausschließlich in `/data` und werden weiterhin von den bestehenden Backups erfasst. Interne Schlüssel, Push-Geräte, Such-Empfänger, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.108 — 19.09.2026, 17:36 CEST

- Technischer Neuaufbau des unveränderten Funktionsstands von 0.13.107, nachdem der erste amd64-Image-Build bereits beim Start von Docker Buildx durch einen externen Docker-Hub-Verbindungsabbruch (`connection reset by peer`) beendet wurde.
- Es gibt keine funktionalen Änderungen gegenüber 0.13.107. Die neue Versionsnummer sorgt für einen frischen regulären Image-Build; Daten, Slug, Ports, Persistenzpfade und die bestehende Profilzuordnung bleiben unverändert.

## 0.13.107 — 19.09.2026, 16:37 CEST

- Sichtbare Personen- und Push-Empfängerbezeichnungen werden wieder aus den ausschließlich lokal unter `/data` gespeicherten Home-Assistant-Push-Zielen abgeleitet. Dadurch erscheinen statt der technischen Schlüssel `primary` und `secondary` wieder die persönlichen Gerätenamen, ohne diese Namen im Repository oder Update-Paket zu hinterlegen.
- Die Anzeige gilt einheitlich für Push-Geräte, Registrierungs- und Test-Push-Hinweise, Suchaufträge sowie die persönlichen Nachrichtenprofile. Interne Schlüssel, bestehende Gerätezuordnungen, Such-Empfänger und gespeicherte Daten bleiben unverändert.

## 0.13.105 — 19.09.2026, 12:26 CEST

- Der vollständige funktionale Rücksprung auf 0.13.93 bleibt erhalten.
- Die öffentliche Push-Adresse wird jetzt aus der lokalen Home-Assistant-Option `push_public_host`, dem von 0.13.104 bereits lokal erkannten Host oder – falls noch nichts bekannt ist – ausschließlich aus einem dedizierten `vinted-push.*`-Cloudflare-Aufruf bestimmt.
- Bei Cloudflare wird zusätzlich `X-Forwarded-Host` berücksichtigt, falls der Tunnel den Origin-Host überschreibt. Dadurch kann die Push-PWA wieder erreichbar sein, ohne den Vinted Manager öffentlich freizugeben.
- Über die öffentliche Verbindung bleiben weiterhin ausschließlich die Push-PWA und ihre expliziten Push-Endpunkte erlaubt; Einstellungen, Anzeigen, Nachrichten, Suchen, Live und alle übrigen Manager-Seiten bleiben extern gesperrt.

## 0.13.104 — 19.09.2026, 11:51 CEST


- Der vollständige funktionale Rücksprung auf 0.13.93 aus Version 0.13.103 bleibt unverändert erhalten.
- Die öffentliche Push-PWA akzeptiert nach einem privaten Cloudflare-Hostwechsel wieder ausschließlich ihre bekannten Push-Routen, übernimmt den tatsächlich aufgerufenen Push-Host und speichert ihn nur lokal unter `/data`. Der normale Vinted Manager bleibt über Cloudflare weiterhin gesperrt.
- Dadurch funktionieren Registrierungslinks und die Such-Pushs für die bereits bestehende `primary`-/`secondary`-Empfängerlogik wieder mit dem tatsächlich verwendeten Push-Host.


## 0.13.103 — 19.09.2026, 11:22 CEST


- Vollständiger funktionaler Rücksprung auf den letzten bereinigten Stand 0.13.93. Vinted-, Browser-, Such-, Push- und Einstellungslogik entsprechen wieder diesem Stand.
- Die ab 0.13.94 eingeführten Änderungen an Sitzungs-, Bearbeitungs- und Benachrichtigungslogik wurden zurückgenommen. Vorhandene Laufzeitdaten unter /data bleiben unverändert erhalten.
- Der spätere Docker-/GitHub-Build-Unterbau bleibt ausschließlich für die heutige Build-Kompatibilität erhalten; er verändert das Verhalten der App nicht.


## 0.13.102 — 19.09.2026, 09:44 CEST


- Die Live-Bearbeitung vergleicht Titel, Beschreibung und Preis jetzt vor dem Öffnen des Editors direkt mit dem bestehenden Vinted-Artikel. Nur tatsächlich abweichende Felder müssen im Editor gefunden und geändert werden.
- Für die Bearbeitung wird derselbe stabile sichtbare Vinted-Tab verwendet wie bei den bereits funktionierenden Verkäuferaktionen; isolierte Hintergrund-Tabs werden für diesen Schreibvorgang nicht mehr verwendet.
- Wenn Vinted im Verkäufermenü eine echte Bearbeiten-URL bereitstellt, wird genau diese URL geöffnet. Der Chromium-Mausklick bleibt nur als Fallback für Button-Varianten erhalten.
- Editor- und Speichern-Erkennung verlangen nur noch die Felder, die in diesem Vorgang tatsächlich geändert werden; eine reine Beschreibungsänderung hängt nicht mehr von Titel- oder Preisfeld ab.


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
- Eine bestätigte Vinted-Abmeldung löst wieder eine kritische, lautlose Push-Mitteilung auf dem primären iPhone aus. Der Dienst kann in der Home-Assistant-App-Konfiguration angepasst werden.
- E-Mail-Adresse und Passwort können optional in der lokalen Home-Assistant-App-Konfiguration hinterlegt werden. Bei einer nötigen erneuten Anmeldung trägt der sichtbare Browser sie vorab ein; Anmeldung, Zwei-Faktor-Code und Sicherheitsprüfungen bleiben bewusst manuell.
- Bei „Prüfen & korrigieren“ wird der Katalog vorbereitet, ohne eine Kategorie auszuwählen. Beim anschließenden Bearbeiten steht er sofort bereit.
- Die Live-Bearbeitung sucht den Speichern-Button jetzt auch nach dem Nachladen weiter unten im Vinted-Formular.


## 0.13.93 — 18.09.2026, 21:12 CEST


- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.


## 0.13.92 — 18.09.2026, 20:51 CEST


- App-Code erstmals bereinigt in das zentrale GitHub-Repository übernommen. Laufzeitdaten und persönliche Einstellungen bleiben ausschließlich in Home Assistant.


# Changelog