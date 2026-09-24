## 0.13.142 — 24.09.2026, 08:56 CEST

- Bei importierten, noch nicht bestätigten Vinted-Anzeigen öffnet sich beim Bearbeiten wieder automatisch der vollständige Vinted-Katalog. Das gilt auch nach „Prüfen & korrigieren“ und nach eigenen Textänderungen, solange noch keine Kategorie verbindlich bestätigt wurde.
- „Prüfen & korrigieren“ zeigt keine bloße Anzahl interner Kategorie-Vorschläge mehr an. Sichtbar bleiben nur konkrete Korrekturen bzw. noch offene Pflichtangaben; die internen Vorschlagsdaten bleiben für die automatische Prüfung erhalten.

## 0.13.141 — 23.09.2026, 09:06 CEST

- Nach einer erfolgreich abgeschlossenen Vinted-Sicherheitsprüfung wird die wartende Veröffentlichung im tatsächlich geprüften Browser-Tab bzw. in genau einem eindeutig neu entstandenen Vinted-Rückkehrtab fortgesetzt. Es wird dafür kein frischer Veröffentlichungstab mehr geöffnet, der unmittelbar wieder eine neue DataDome-Prüfung auslösen kann. Wenn der geprüfte Tab nicht eindeutig ermittelt werden kann, bleibt der Auftrag sicher wartend statt einen weiteren Tab zu erzeugen.

## 0.13.140 — 22.09.2026, 22:16 CEST

- Rollback auf den vollständigen Funktionsstand von 0.13.135. Die Änderungen aus 0.13.136 bis 0.13.139 werden bewusst zurückgenommen; Slug, Ports, Persistenzpfade und bestehende Nutzerdaten bleiben unverändert.

## 0.13.139 — 22.09.2026, 21:48 CEST

- Wenn nach der Sicherheitsprüfung nur noch der geprüfte Browser-Tab offen ist, setzt der Manager zunächst genau diesen Tab zu Vinted fort und prüft danach die Sitzung. So scheitert die Fortsetzung nicht bereits daran, dass vorübergehend kein normaler Vinted-Tab vorhanden ist. Ohne den zugehörigen Tab bleibt der Auftrag wartend, statt einen weiteren Tab zu öffnen.

## 0.13.138 — 22.09.2026, 21:39 CEST

- Nach einer manuell abgeschlossenen Vinted-Sicherheitsprüfung setzt der Manager die wartende Veröffentlichung im bereits geprüften Browser-Tab oder dessen Vinted-Folgetab fort. Er erzeugt dafür keinen neuen Veröffentlichungstab mehr, der erneut in dieselbe Prüfung führen kann. Auch bereits wartende Aufträge aus der vorherigen Version werden so behandelt.

## 0.13.137 — 22.09.2026, 20:08 CEST

- „Nicht veröffentlicht“ lässt sich jetzt auch dann zuverlässig löschen, wenn für den Entwurf noch eine Prüfung oder Veröffentlichung vorgemerkt ist. Beim Löschen wird der lokale Entwurf sofort als beendet markiert und aus den Prüf- und Veröffentlichungswarteschlangen entfernt; ein alter Hintergrundauftrag kann ihn dadurch nicht weiterverarbeiten. Eine bereits bestehende Vinted-Onlineanzeige wird durch das lokale Löschen weiterhin nicht entfernt.

## 0.13.136 — 22.09.2026, 18:26 CEST

- Das Löschen einer einzelnen nicht veröffentlichten Anzeige speichert die Entfernung jetzt zuerst. Falls ihr Bildordner gerade noch gesperrt ist oder bereits fehlt, wird nur das Aufräumen später übersprungen; die Anzeige verschwindet trotzdem zuverlässig aus dem Manager. Dasselbe gilt für „Ausgewählte löschen“.

## 0.13.135 — 22.09.2026, 18:22 CEST

- Beim Öffnen einer neuen Anzeige steht der lokale Vinted-Katalog direkt bereit, ohne dafür einen leeren Entwurf anzulegen. Eine unangetastete importierte Kleinanzeigen-Anzeige bereitet denselben Katalog beim ersten Klick auf „Bearbeiten“ automatisch vor. Nach einer eigenen Bearbeitung bleibt der Katalog geschlossen, bis er bewusst geöffnet wird.

## 0.13.134 — 22.09.2026, 18:05 CEST

- Bei genau einem neuen Suchtreffer verwendet die Web-Push jetzt das öffentliche Vinted-Foto des Artikels als Benachrichtigungs-Icon und als großes Bild beim Aufziehen. Bei mehreren Treffern bleibt die neutrale Sammelmeldung ohne Bild. Es werden ausschließlich HTTPS-Bildadressen von Vinted-CDNs verwendet; der Manager stellt keine Bilder, Cookies oder Daten öffentlich bereit.
- Der private Vinted Manager besitzt nun ein eigenes Web-App-Manifest und übernimmt das bestehende grüne Vinted-Manager-Symbol für den iPhone-Homescreen. Nach dem erneuten Speichern auf dem Homescreen erscheint er als „Vinted Manager“ statt mit einem Safari-Vorschaubild.

## 0.13.133 — 22.09.2026, 17:50 CEST

- Das Livebild folgt während einer Veröffentlichung nun dem genau dafür geöffneten Vinted-Tab. Der allgemeine Browser-Haupttab wird nach dem Auftrag weiter zurückgestellt und kann deshalb kein fremdes Katalogbild mehr in der Manager-Vorschau erzeugen. Nach Abschluss bleibt das zuletzt bearbeitete Anzeigenbild als Standbild verfügbar.

## 0.13.132 — 22.09.2026, 17:02 CEST

- „Live bei Vinted“ steht jetzt ausschließlich auf „Meine Anzeigen“ und ist im Ruhezustand auf die drei nötigen Angaben reduziert: Zeitpunkt, verbundenes Vinted-Konto und leere Warteschlange. Die ausführlichen Bereitschaftstexte und die Tabanzahl entfallen.
- Die Karte lässt sich zu einem lokalen Browserbild aufklappen. Während eines laufenden Uploads öffnet sie sich selbst und aktualisiert das Bild einmal pro Sekunde; sobald der Auftrag endet oder die Manager-Seite nicht sichtbar ist, wird die Bildabfrage sofort gestoppt. Außerhalb eines Auftrags wird nur beim bewussten Aufklappen ein einzelnes Standbild geladen; Bilder werden nicht auf die Festplatte geschrieben.
- „Vinted-Fenster öffnen“ nutzt in der als iPhone-Web-App geöffneten Ansicht einen externen Safari-Link, damit sich die Manager-Ansicht nicht ersetzt. In einem normalen Browser bleibt es ein neuer Tab.
- Der Nachrichtenabgleich bleibt für Unterhaltungen, Bewertungen und Verkaufsinformationen aktiv, markiert neue Nachrichten im Manager aber nicht mehr und sendet dafür keine Manager-Pushs. Die Vinted-App bleibt damit die einzige Quelle für Chat-Benachrichtigungen.
- Die für den Build mitgelieferten Python-Hilfsbibliotheken sind auf verfügbare, passende feste Versionen korrigiert; dadurch muss beim Update nichts aus dem Quellcode kompiliert werden.

## 0.13.131 — 22.09.2026, 04:19 CEST

- Die laufende Vinted-Arbeit erscheint im Manager nur noch in einer gemeinsamen Karte „Live bei Vinted“. Die doppelte violette Bot-Meldung, die zusätzliche Sammelstatus-Zeile und die gleichlautende Startmeldung entfallen; Anmeldung, Sicherheitsprüfung, aktueller Auftrag, Warteschlange und offene Tabs bleiben an einer Stelle sichtbar.
- Während des echten Foto-Uploads zeigt die Karte nun den bestätigten Fortschritt wie „Foto 5 von 9 wird hochgeladen“ beziehungsweise „Fotos: 5 von 9 hochgeladen“. Nach dem letzten Bild wechselt sie zu „Anzeige wird veröffentlicht“. Der Fortschritt stammt nur aus dem lokalen Auftragsstand; temporäre Upload-IDs, Sitzungsdaten, Browserinhalte und URLs werden nie angezeigt.
- Auch beim Start direkt aus dem Bearbeitungsformular wird dieselbe Live-Karte sofort aktualisiert. Der Vinted-Browser, die Warteschlange, die Sicherheitsprüfung und vorhandene Persistenzpfade bleiben unverändert.

## 0.13.130 — 22.09.2026, 04:12 CEST

- Nach einer bestätigten Vinted-Abmeldung prüft der Manager den sichtbaren lokalen Browser nun alle fünf Sekunden, aber ausschließlich während die manuelle Anmeldung offen ist. Sobald Vinted wieder angemeldet ist, wird die verifizierte Sitzung sofort unter `/data` gesichert; während der Eingabe werden keine zusätzlichen Vinted-Anfragen ausgelöst.
- Der Chromium-Ruhezustand ist für den echten Verkaufsbetrieb jetzt standardmäßig ausgeschaltet. Der sichtbare Vinted-Browser bleibt aktiv, damit Vinteds eigene Sitzungs-Erneuerung nicht durch ein Einfrieren nach wenigen Sekunden gestört wird. Die Option kann bei Bedarf weiterhin bewusst wieder eingeschaltet werden.
- Über jeder Manager-Seite gibt es jetzt „Live bei Vinted“: klarer Zustand der Anmeldung, offene Vinted-Tabanzahl, laufende Veröffentlichung beziehungsweise Sicherheitsprüfung und der nächste Schritt. Der Status aktualisiert sich lokal alle fünf Sekunden und liest weder Browserinhalt, URLs, Kontodaten noch Cookies aus. Ein Button öffnet bei Bedarf das vorhandene Vinted-Fenster.
- Die Wiederaufnahme einer abgelaufenen Sicherheitsprüfung aus 0.13.129, der Schutz gegen Tab-Schleifen, die bestehende Warteschlange, Ports, Slug und alle Persistenzpfade bleiben erhalten.

## 0.13.128 — 21.09.2026, 15:48 CEST

- Der aktuelle Fehler nach „Prüfung erledigt – fortsetzen“ wurde auf die nächste Stufe eingegrenzt: Der neue Vinted-Veröffentlichungstab wurde bereits geöffnet, konnte aber direkt wieder in eine DataDome-Prüfung umgeleitet werden. Diese echte zweite Sicherheitsprüfung wurde bisher 25 Sekunden lang nur als nicht fertige `/items/new`-Seite behandelt, anschließend geschlossen und fälschlich als „Die Vinted-Seite wurde nicht vollständig geladen“ gemeldet.
- Ein frischer Veröffentlichungstab nach einer bestätigten Sicherheitsprüfung erkennt eine Weiterleitung zu `captcha-delivery.com`/DataDome jetzt sofort als neue Sicherheitsprüfung. Der Tab bleibt sichtbar geöffnet, wird exakt dieser Anzeige zugeordnet und der normale Sicherheits-Push/Fortsetzungsablauf greift erneut; der Auftrag wird nicht als allgemeiner Ladefehler beendet.
- Für genau diesen Fortsetzungsfall wartet der Manager bis zu 45 Sekunden auf `/items/new`. Landet der neue Tab nach Vinteds clientseitigen Übergängen zunächst stabil auf einer normalen Vinted-Seite, wird derselbe Tab genau einmal kontrolliert zu `/items/new` zurückgeführt. Ein sinnvoll geladener Vinted-Tab wird bei einem verbleibenden Timeout nicht mehr automatisch geschlossen, damit die echte Browserlage sichtbar bleibt.
- Die bereits vorhandenen Aktionen „Prüfung erledigt – fortsetzen“ und „Sicherheitsabfrage öffnen“, die Sicherheits-Pushs, die Schutzlogik gegen mehrere destruktive Erneuerungen sowie die seit 0.13.123 korrigierte Überfällig-Anzeige und das Nachholen fälliger Erneuerungen bleiben unverändert.

## 0.13.127 — 21.09.2026, 13:10 CEST

- Die Fortsetzung einer Sicherheitsprüfung ist nicht mehr auf „wirklich unveröffentlicht“ beschränkt. Eine Prüfung kann bereits während einer Erneuerung auftreten, solange die alte `published_item_id` noch vorhanden ist; genau dieser Fall führte bei „Prüfung erledigt – fortsetzen“ fälschlich zu „Diese unveröffentlichte Anzeige wurde nicht gefunden“. Der Button akzeptiert jetzt jede tatsächlich wartende Anzeige und übernimmt die ursprünglich laufende Publish-/Renew-Aktion.
- Nach einer bestätigten bzw. automatisch erkannten DataDome-Freigabe wird wieder genau einmal ein frischer Vinted-Tab für `/items/new` geöffnet, während der gelöste Captcha-Tab stehen bleiben darf. Das Einmal-Flag wird beim Öffnen verbraucht; verlangt Vinted im neuen Tab erneut eine echte Prüfung, stoppt der Auftrag wieder sicher statt weitere Tabs zu erzeugen.
- „Prüfung erledigt – fortsetzen“ und „Sicherheitsabfrage öffnen“ erscheinen auch dann direkt an einer noch als veröffentlicht geführten Anzeige, wenn die Sicherheitsprüfung schon vor dem Löschen der Altanzeige aufgetreten ist. „Sicherheitsabfrage öffnen“ fokussiert den exakt zu dieser Anzeige gespeicherten Captcha-Tab und öffnet die noVNC-Ansicht extern in Safari.
- Die Schutzlogik für fällige automatische Erneuerungen bleibt erhalten: Solange eine Erneuerung auf eine Sicherheitsprüfung wartet, werden keine weiteren Live-Anzeigen gelöscht. Nach erfolgreicher Fortsetzung werden überfällige Erneuerungen wieder nach ihrem ältesten Fälligkeitstermin abgearbeitet.

## 0.13.126 — 21.09.2026, 12:54 CEST

- Ein bereits wartender Erneuerungsauftrag übernimmt ein ausdrücklich angeklicktes „Erneut versuchen“ jetzt sofort. Dadurch verlässt er die alte Sicherheits-Warteschleife und verwendet den vorhandenen Vinted-Tab; zusätzliche Tabs bleiben ausgeschlossen.

## 0.13.125 — 21.09.2026, 12:35 CEST

- Eine im Browser nicht mehr vorhandene Sicherheitsabfrage blockiert eine ausdrücklich angeklickte „Erneut versuchen“-Aktion nicht länger. Der Manager verwendet dafür ausschließlich den bereits sichtbaren Vinted-Tab und öffnet keinen weiteren Tab.
- Erscheint dabei erneut eine echte Vinted-/DataDome-Prüfung, bleibt sie genau diesem vorhandenen Tab und derselben Anzeige zugeordnet. Ohne ausdrückliches „Erneut versuchen“ bleibt der Schutz gegen Tab-Schleifen unverändert aktiv.

## 0.13.124 — 21.09.2026, 12:01 CEST

- Die live beobachtete DataDome-Schleife nach einem grünen Slider ist behoben: Öffnet DataDome nach der Prüfung einen mit dem Captcha-Tab verknüpften Vinted-Tab, verwendet der Manager genau diesen Tab für die Fortsetzung. Der alte Captcha-Tab bleibt dabei unangetastet.
- Ist die Vinted-Rückkehr noch nicht sichtbar, wird der Auftrag sicher wieder auf „Sicherheitsprüfung wartet“ gesetzt. Es wird ausdrücklich kein frischer Veröffentlichungs-Tab erzeugt und dadurch keine weitere Sicherheitsabfrage ausgelöst.
- Auch bei einer unterbrochenen Neu-Einstellung unter „Meine Anzeigen“ stehen jetzt direkt „Prüfung erledigt – fortsetzen“ und „Sicherheitsabfrage öffnen“ bereit. Die explizite Fortsetzung betrifft nur diese Anzeige und bleibt im vorhandenen Prüfungs-Tab.
- Sicherheitsprüfung, bestehende Upload-Sitzung, Schutz vor weiteren Löschungen, Push-Zuordnung, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.123 — 21.09.2026, 11:24 CEST

- Bei einer festhängenden Vinted-Sicherheitsprüfung erscheinen direkt an der betroffenen Anzeige unter „Nicht veröffentlicht“ jetzt zwei eindeutige Aktionen: „Prüfung erledigt – fortsetzen“ sowie „Sicherheitsabfrage öffnen“. Der Öffnen-Link startet den vorhandenen sichtbaren Vinted-Browser wie beim Sicherheits-Push in einem neuen Safari-Tab; die Fortsetzen-Aktion gilt ausschließlich für den aktuell wartenden Auftrag.
- Die Fortsetzen-Aktion funktioniert unabhängig von DataDomes DOM-/Cookie-/Netzwerksignalen. Ein noch laufender Worker übernimmt die explizite Freigabe sofort; ist der Worker zwischenzeitlich beendet worden, wird genau derselbe Publish-/Renew-Auftrag wieder in die Warteschlange aufgenommen. Beim Wiederholungsversuch wird wie im früher funktionierenden Ablauf ein frischer Vinted-Veröffentlichungstab geöffnet, solange der Captcha-Tab selbst noch auf der Sicherheitsprüfung steht. Eine erneut von Vinted verlangte Prüfung wird nicht übersprungen.
- Laufende Sammel-/Bot-Anzeigen leiten ihren Status zusätzlich aus dem gespeicherten Sicherheitsprüfungszustand der betroffenen Anzeige ab. Während auf den Nutzer gewartet wird, steht deshalb nicht mehr irreführend „Vinted-Bot läuft / wird verarbeitet“, sondern „Sicherheitsprüfung wartet“. Persistierte Warteschlangen werden beim Öffnen von „Meine Anzeigen“ oder „Nicht veröffentlicht“ erneut an den Worker angebunden.
- Fällige automatische Erneuerungen bleiben während einer unterbrochenen Neu-Einstellung weiterhin absichtlich geschützt, statt weitere Live-Anzeigen zu löschen. Die Übersicht erklärt diesen Blocker jetzt sichtbar und weist darauf hin, dass überfällige Erneuerungen danach automatisch nachgeholt werden. Bei mehreren überfälligen Anzeigen wird anschließend zuerst der älteste Termin verarbeitet.
- Erneuerungstermine, die am selben Tag bereits verstrichen sind, werden nun wirklich als überfällig angezeigt (Minuten/Stunden statt weiterhin „heute um … Uhr“). Automatik-, Preis-, Live-, Push-, Slug-, Port- und Persistenzpfade bleiben ansonsten unverändert.

## 0.13.122 — 21.09.2026, 10:12 CEST

- Die Fortsetzung nach einer manuellen Vinted-DataDome-Prüfung hängt nicht mehr ausschließlich an DOM- oder Cookie-Heuristiken. Während der sichtbare Slider offen ist, lauscht der Manager jetzt direkt auf die Chromium-Netzwerkereignisse des betroffenen Prüfungs-Tabs und erkennt eine erfolgreich beantwortete DataDome-Verifikationsanfrage als bevorzugtes Freigabesignal. Statische Captcha-Ressourcen werden dabei ausdrücklich ignoriert.
- Cookie-Änderung und vorhandenes DataDome-Erfolgselement bleiben als zusätzliche automatische Signale erhalten. Dadurch bleibt die Fortsetzung auch dann möglich, wenn eine einzelne DataDome-Variante eines der Signale nicht liefert.
- Als bewusster Notfall-Fallback wird im sichtbaren Captcha-Tab ein eigener Button „Prüfung abgeschlossen – fortsetzen“ eingeblendet. Er löst lediglich den bereits wartenden Veröffentlichungsauftrag erneut aus; akzeptiert Vinted die Sicherheitsprüfung noch nicht, erscheint wieder die echte Prüfung statt einer blinden Veröffentlichung.
- Mehrfachveröffentlichung, Wiederaufnahme fehlgeschlagener Neu-Einstellungen, Push-Regeln, Sichtprüfung, Schutz vor weiteren Löschungen, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.121 — 21.09.2026, 02:13 CEST

- Die Sicherheitsprüfungs-Fortsetzung wurde gezielt mit der bereitgestellten funktionierenden Altversion 0.13.62 verglichen. Der entscheidende Unterschied war die spätere Zusatzbedingung, dass der DataDome-Prüfungs-Tab selbst wieder auf `vinted.de` zurücknavigieren musste. Der alte Stand setzte den wartenden Auftrag dagegen über das gemeinsam genutzte Chromium-Profil fort; genau diese starre Tab-Rückkehr konnte beim heutigen Slider trotz grünem Haken dauerhaft hängen bleiben.
- Nach einer tatsächlich gelösten Prüfung gibt der Manager den wartenden Auftrag deshalb wieder unabhängig von einer Weiterleitung des sichtbaren Captcha-Tabs frei. Als Freigaben gelten DataDomes Erfolgssignal oder eine echte Änderung der `datadome`-Cookies im gemeinsam genutzten Chromium-Profil. Der nächste Versuch nutzt weiterhin dieselbe gespeicherte Upload-/Foto-Sitzung und das gleiche Browserprofil; bleibt die Freigabe bei Vinted ungültig, entsteht wieder eine echte Sicherheitsprüfung statt einer blinden Veröffentlichung.
- Die Cookie-Erkennung wertet jetzt alle Vinted-`datadome`-Cookies aus, nicht nur den ersten von Chromium gelieferten Eintrag. Dadurch blockiert ein parallel noch vorhandener alter Host-/Domain-Cookie die Erkennung einer neu ausgestellten DataDome-Sitzung nicht mehr. Der Cookie-Stand vor Öffnen der Prüfung wird je Auftrag gespeichert und nur eine danach neu auftauchende Sitzung gilt als Änderung.
- Mehrfachveröffentlichung, Wiederaufnahme fehlgeschlagener Neu-Einstellungen, Push-Regeln, Sichtprüfung, Automatik-Schutz, Live-Bearbeitung, Slug, Ports und Persistenzpfade bleiben unverändert.

## 0.13.120 — 21.09.2026, 01:45 CEST

- Die bereits in 0.13.114 eingeführte DataDome-Fortsetzung wurde gegen den heute sichtbaren Slider-Zustand abgeglichen. Der bisherige Code verlangte beim Erfolgselement `#captcha-success` zusätzlich eine eigene sichtbare Fläche; DataDome kann dieses interne Erfolgssignal jedoch verborgen bzw. ohne eigene Größe halten, obwohl der Slider bereits den grünen Haken zeigt. Der Manager erkennt deshalb jetzt das vorhandene Erfolgssignal selbst und nicht mehr dessen CSS-Sichtbarkeit.
- Zusätzlich gilt eine nach der manuellen Prüfung tatsächlich erneuerte `datadome`-Sitzung wieder als eigenständiges Freigabesignal. Nach einem dieser beiden Signale wird ausschließlich der exakt betroffene Prüfungs-Tab kontrolliert zu Vinted zurückgeführt. Erst wenn dort wieder eine echte Vinted-Seite geladen ist, wird derselbe wartende Upload fortgesetzt.
- Die Lockerung kann keine Sicherheitsprüfung überspringen: Sollte Vinted die Sitzung noch nicht akzeptieren, erscheint unmittelbar wieder eine neue DataDome-Prüfung und der Manager wartet erneut. Bereits hochgeladene Bilder, Mehrfachveröffentlichung, Wiederaufnahme fehlgeschlagener Neu-Einstellungen, Push-Regeln, Automatik-Schutz, Slug, Ports und Persistenzpfade bleiben unverändert.

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
## 0.13.129 — 22.09.2026, 03:17 CEST

- Der Klick auf „Erneut versuchen“ bei einer abgelaufenen Sicherheitsprüfung verliert den Wiederanlauf jetzt nicht mehr: Der explizite Wiederanlauf bleibt am wartenden Erneuerungsauftrag erhalten, verlässt dessen alte Prüfungswartezeit und verwendet den sichtbaren Vinted-Tab erneut.
- Ein nach einem Browser-/Prozessneustart nur noch als „aktueller Auftrag“ gespeicherter Erneuerungsauftrag wird beim ausdrücklichen Wiederanlauf einmal sicher zurück in die Warteschlange gelegt. Ein noch lebender Auftrag wird nicht dupliziert und öffnet keinen zusätzlichen Tab.
- Die abgelaufene Prüfungszeit blockiert diesen ausdrücklich angeforderten Wiederanlauf nicht länger vor dem Upload. Verlangt Vinted erneut eine Prüfung, wird sie wieder als echte neue Sicherheitsabfrage erkannt und angehalten.
