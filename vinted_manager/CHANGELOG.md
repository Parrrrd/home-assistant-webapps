## 0.13.119 — 21.09.2026, 01:14 CEST

- Eine sichtbar erfolgreich abgeschlossene Vinted-DataDome-Prüfung mit grünem Haken setzt die wartende Veröffentlichung jetzt auch dann fort, wenn der `datadome`-Cookie nicht sofort sichtbar rotiert. Nach einer kurzen Beruhigungsphase wird exakt derselbe Prüfungs-Tab zurück zu Vinted geführt; erst eine tatsächlich geladene Vinted-Seite gibt den wartenden Upload wieder frei.
- Bleibt oder erscheint stattdessen erneut eine echte Sicherheitsprüfung, wird nicht blind veröffentlicht: Der Manager wartet weiter auf genau diesen Prüfungs-Tab. Eine später neu erforderliche Sicherheitsprüfung darf nach einer vorher erfolgreich abgeschlossenen Prüfung wieder einen kritischen Push an das primäre iPhone auslösen.
- Im sichtbaren Vinted-Browser wird eine echte Sicherheitsprüfung nicht mehr irreführend als „Veröffentlichung fehlgeschlagen“ dargestellt, sondern als wartende Sicherheitsprüfung mit dem Hinweis, dass die Veröffentlichung nach dem Slider automatisch fortgesetzt wird.
- Mehrfachveröffentlichung unter „Nicht veröffentlicht“, Wiederaufnahme fehlgeschlagener Neu-Einstellungen, Automatik-Schutz, Live-Bearbeitung, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.118 — 21.09.2026, 00:59 CEST

- Fehlgeschlagene Neu-Einstellungen, deren alte Vinted-Anzeige bereits entfernt wurde, erscheinen wieder unter „Nicht veröffentlicht“. Sie bleiben dort als bereits „BEARBEITET“ erhalten und werden nicht auf „UNBEARBEITET“ zurückgesetzt.
- „Nicht veröffentlicht“ kann jetzt mehrere bearbeitete Anzeigen in einer Auswahl wirklich nacheinander einstellen. Unterbrochene Erneuerungen werden dabei automatisch als Fortsetzung der bestehenden Neu-Einstellung behandelt, normale Entwürfe als Erstveröffentlichung; eine offene Erneuerung wird zuerst abgearbeitet.
- Ein abgelaufener alter Sicherheitsprüfungs-Zustand blockiert einen manuellen Sammel-Wiederholungsversuch nicht mehr mit der irreführenden Meldung „Sicherheitsprüfung wurde nicht rechtzeitig abgeschlossen“. Der neue Versuch prüft Vinted frisch; verlangt Vinted tatsächlich DataDome/Captcha, wird die echte Prüfung geöffnet und der bestehende kritische Push an das primäre iPhone ausgelöst.
- Unbearbeitete neue Entwürfe werden in der Sammelveröffentlichung ausgelassen, statt den gesamten Lauf beim ersten Entwurf zu stoppen. Die normale manuelle Prüfung bleibt erforderlich.
- Einzelnes erneutes Einstellen, Automatik-Schutz vor weiteren Löschungen, Live-Bearbeitung, Push-Zuordnung, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.117 — 20.09.2026, 20:43 CEST

- Unterbrochene Neu-Einstellungen werden nicht mehr als neue „unbearbeitete“ Anzeigen behandelt. Ein bereits zuvor online verwalteter Artikel mit `renewal_upload_pending` bleibt in „Meine Anzeigen“ als „ERNEUERUNG WARTET“ sichtbar und verschwindet aus „Nicht veröffentlicht“ sowie aus dessen Badge-Zähler.
- Solange auch nur eine Erneuerung nach Löschen der Altanzeige noch offen ist, darf keine andere Online-Anzeige für eine weitere Erneuerung gelöscht werden. Das gilt für automatische, manuelle und Sammel-Erneuerungen und verhindert eine Kaskade aus mehreren verschwundenen Anzeigen.
- Die Automatik verarbeitet ab jetzt höchstens eine fällige Erneuerung pro Prüfzyklus. Bei einer Sicherheitsprüfung oder einem echten Fehler werden weitere Erneuerungen sicher pausiert, bis der offene Vorgang geklärt ist. Dadurch werden Schreibzugriffe auf Vinted deutlich entzerrt.
- Auch Sammelaktionen erhalten mehr Abstand: standardmäßig 60 statt 30 Sekunden zwischen Vinted-Schreibvorgängen.
- Für bereits betroffene Anzeigen gibt es in „Meine Anzeigen“ direkt „Erneut versuchen“. Ein Sicherheitsprüfungs-Timeout bleibt dabei ausdrücklich ein Erneuerungs-/Wiederherstellungszustand und setzt die Anzeige nicht zurück auf „unbearbeitet“.
- DataDome-Freigabe, Push-Regeln, Sichtprüfung, Live-Zeitangabe, Live-Bearbeitung und Personen-Zuordnung bleiben unverändert.

## 0.13.116 — 20.09.2026, 18:10 CEST

- Sammelaktionen werden jetzt beim ersten echten Veröffentlichungs- oder Erneuerungsfehler sicher gestoppt. Insbesondere nach einer bereits gelöschten Altanzeige werden keine weiteren ausgewählten Online-Anzeigen mehr gelöscht, solange der fehlgeschlagene Upload nicht geklärt ist.
- Der Fehlergrund des gestoppten Vorgangs und die Zahl der deshalb nicht gestarteten weiteren Anzeigen werden direkt im Manager angezeigt. So ist ein Laufzeitfehler sichtbar, ohne erst Home-Assistant-Protokolle suchen zu müssen.
- Während ein Wiederholungsversuch tatsächlich läuft, zeigt der obere Bot-Status nicht mehr den alten Zustand „Fehlgeschlagen – erneut versuchen“, sondern eindeutig „wird verarbeitet“ beziehungsweise bei Bedarf „Sicherheitsprüfung erforderlich“.
- Die DataDome-Sicherheitsprüfung, Push-Regeln, Sichtprüfung, Live-Zeitangabe, Live-Bearbeitung und Personen-Zuordnung aus 0.13.115 bleiben unverändert.

## 0.13.115 — 20.09.2026, 13:38 CEST

- Erfolgreiche Erstveröffentlichungen erzeugen jetzt genau einen normalen Push auf Patricks primärem iPhone: „Vinted · Anzeige veröffentlicht“. Die anschließend erfolgreiche Sichtprüfung läuft weiterhin vollständig, sendet aber keinen zweiten Erfolgs-Push mehr.
- Nur wenn die Sichtprüfung die neue Anzeige nicht sicher im frischen Vinted-Live-Bestand bestätigen kann, bleibt der zusätzliche kritische, lautlose Push „Vinted · Sichtprüfung kritisch“ mit `critical: 1` und `volume: 0.0` erhalten.
- Sicherheitsprüfung/DataDome, Live-Zeitangabe, funktionierende Live-Bearbeitung und Personen-Zuordnung aus 0.13.114 bleiben unverändert.

## 0.13.114 — 20.09.2026, 11:18 CEST

- Die manuelle DataDome-Sicherheitsprüfung erkennt nun auch den tatsächlich erfolgreichen Slider-Zustand, wenn die Seite nach dem grünen Haken noch auf `captcha-delivery.com` stehen bleibt. Entscheidend ist dabei zusätzlich die von DataDome nach erfolgreicher Prüfung erneuerte `datadome`-Sitzung im selben Chromium-Profil; die Prüfung wird nicht allein anhand eines sichtbaren Hakens als erledigt gewertet.
- Nach bestätigter Freigabe wird exakt der betroffene Prüfungs-Tab kontrolliert zu Vinteds Veröffentlichungsseite zurückgeführt. Erst wenn dieser Tab wieder wirklich auf `vinted.de` angekommen ist, darf der wartende Auftrag mit derselben Upload-Sitzung und den bereits hochgeladenen Bildern fortgesetzt werden.
- Eine erneute DataDome-Prüfung mit neuer Challenge-ID wird als neue manuelle Prüfung behandelt statt automatisch weiterzulaufen. Dadurch werden weder nach einem bloßen grünen Haken unnötig neue Veröffentlichungsversuche gestartet noch bleibt ein erfolgreich bestätigter Slider bis zum Timeout hängen.
- Die Änderungen aus 0.13.113 zur festen Tab-Zuordnung sowie Sichtprüfung, Push-Regeln, Live-Zeitangabe, Live-Bearbeitung und Personen-Zuordnung bleiben erhalten.

## 0.13.113 — 20.09.2026, 10:30 CEST

- Die manuelle Vinted-Sicherheitsprüfung bleibt jetzt exakt an den Chromium-Tab gebunden, dessen Upload-Anfrage von DataDome blockiert wurde. Der Manager wartet wirklich auf genau diesen Tab, statt nach dem Öffnen der Prüfung versehentlich einen anderen Vinted-Tab als „fertig“ zu interpretieren.
- Nach erfolgreich gelöster Prüfung wird derselbe freigegebene Tab für den wartenden Veröffentlichungsauftrag wiederverwendet. Bereits hochgeladene Fotos und die laufende Upload-Sitzung bleiben erhalten; es wird kein neuer paralleler Veröffentlichungsversuch und kein weiterer Captcha-Tab gestartet.
- Verschwindet der zugehörige Prüfungs-Tab unerwartet, wird sicher bis zum begrenzten Timeout gewartet statt blind erneut zu veröffentlichen. Dadurch entsteht bei einer noch nicht wirklich abgeschlossenen Prüfung keine wiederholte Sicherheitsprüfungs-Schleife.
- Die mit 0.13.112 ergänzte Sichtprüfung sowie die Push-Regeln, Live-Zeitangabe, funktionierende Live-Bearbeitung und Personen-Zuordnung bleiben unverändert erhalten.

## 0.13.112 — 20.09.2026, 10:07 CEST

- Nach jeder erfolgreichen Erstveröffentlichung wird die neue Vinted-Anzeige wieder zusätzlich gegen einen frisch abgerufenen Live-Bestand geprüft. Sobald die neue Artikel-ID dort bestätigt ist, erhält ausschließlich das lokal konfigurierte primäre iPhone den normalen Push „Vinted · Sichtprüfung erfolgreich“.
- Kann die neue Anzeige nach mehreren begrenzten, frischen Live-Prüfungen nicht bestätigt werden, folgt „Vinted · Sichtprüfung kritisch“ ausschließlich an das primäre iPhone als kritischer, lautloser Push mit `critical: 1` und `volume: 0.0`. Der bereits erfolgreiche Veröffentlichungsstatus wird dadurch nicht nachträglich als fehlgeschlagen umgedeutet.
- Die mit 0.13.111 wiederhergestellten normalen Pushs für erfolgreiche beziehungsweise fehlgeschlagene Veröffentlichungen sowie die kritischen Pushs bei Sicherheitsprüfung und bestätigter Abmeldung bleiben unverändert. Ebenso bleiben Live-Zeitangabe, funktionierende Live-Bearbeitung und Personen-Zuordnung erhalten.

## 0.13.111 — 20.09.2026, 09:44 CEST

- System-Pushs für Veröffentlichungen werden wieder ausschließlich an das lokal konfigurierte primäre iPhone gesendet. Eine erfolgreich neu veröffentlichte Anzeige und eine fehlgeschlagene Veröffentlichung erzeugen jeweils einen normalen Push; ein Broadcast über `notify.notify` ist für diese Ereignisse ausgeschlossen.
- Eine erforderliche Vinted-Sicherheitsprüfung sowie eine bestätigte Abmeldung bleiben kritische, lautlose iPhone-Pushs mit `critical: 1` und `volume: 0.0`. Das konkrete Mobile-App-Ziel wird wieder ausschließlich aus der lokalen Home-Assistant-App-Konfiguration beziehungsweise den lokalen Manager-Einstellungen unter `/data` gelesen und nicht im Repository gespeichert.
- In „Live bei Vinted“ steht die Veröffentlichungszeit jetzt klein direkt neben „aktiv“ und „verknüpft“: am selben Tag z. B. `heute 03:35 Uhr`, am Vortag `gestern 03:35 Uhr`, danach relativ wie `vor 5 Tagen`.
- Der mit 0.13.110 verifizierte Stand der funktionierenden Live-Bearbeitung und der korrekten Personen-Zuordnung bleibt unverändert erhalten.

## 0.13.110 — 19.09.2026, 19:26 CEST

- Verifizierter Referenzstand: Das Bearbeiten bereits veröffentlichter Vinted-Anzeigen funktioniert wieder vollständig, einschließlich des Speicherns der Änderungen über die bestehende Live-Bearbeitung.
- Die beiden persönlichen Profile und Push-Empfänger werden wieder mit den lokal ermittelten Anzeigenamen korrekt dargestellt. Die technischen Schlüssel `primary` und `secondary` bleiben intern unverändert.
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