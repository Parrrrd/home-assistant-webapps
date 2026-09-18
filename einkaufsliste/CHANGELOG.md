# Einkaufsliste – Versionsverlauf

Die aktuellsten Änderungen stehen oben. Ältere Versionen bleiben unten eingeklappt erhalten.

## 0.3.57 — 18.09.2026, 17:44 CEST

- Der Hinweis im Eingabefeld zum Hinzufügen wurde verständlicher formuliert.

## 0.3.55 — 18.09.2026, 15:45 CEST

- Test der automatischen Google-Drive-Übernahme nach GitHub.

## 0.3.54 — 18.09.2026, 13:01 CEST

- Die Einkaufsliste öffnet sich ausschließlich über ihre direkte Browser-Adresse und nicht mehr innerhalb von Home Assistant.

## 0.3.53 — 18.09.2026, 10:06 CEST

- Die Home-Assistant-Ingress-Oberfläche verwendet ihre API- und Sicherungspfade nun innerhalb der App. Listen und Kategorien laden dadurch auch beim Öffnen über Home Assistant korrekt.

<details>
<summary>Ältere Versionen anzeigen</summary>

## 0.3.52

- Technische Umstellung auf das vorgebaute, mehrarchitekturfähige Home-Assistant-Image. Einstellungen, Listen, Bilder und Sicherungen bleiben unverändert im lokalen /data-Verzeichnis.

## 0.3.51

- Unbearbeitete Stammartikel werden beim tatsächlichen Hinzufügen wieder automatisch bebildert; bestehende unbearbeitete Artikel wie Zucker oder Kartoffeln bleiben nicht mehr dauerhaft im Status „Unbearbeitet“.
- Vor jeder neuen Gemini-Bilderstellung wird grundartikelweit geprüft, ob derselbe Artikel in einer anderen Kategorie bereits bearbeitet ist. In diesem Fall werden Bild und Bearbeitungsstatus lokal übernommen, ohne neue KI-Erstellung.
- Wird ein neues Bild erzeugt, wird es direkt auf alle bereits vorhandenen noch unbearbeiteten Varianten desselben Grundartikels übertragen, z. B. Normal/Firma/REWE/DM/Rossmann/Müller.
- Auch manuell hochgeladene Produktbilder werden grundartikelweit auf noch unbearbeitete Varianten übernommen.
- Parallele Bildjobs desselben Grundartikels werden zusammengeführt, damit nicht mehrere KI-Bilder gleichzeitig entstehen.
- Die Spezialziel-, Mengen-, Dubletten- und Sofort-Push-Logik der 0.3.50 bleibt unverändert.

## 0.3.49

- Spezialziele werden vor der Stammartikelsuche zerlegt: Menge und Zielwörter wie `Firma`, `REWE`, `DM`, `Rossmann` und `Müller` landen nie im Stammartikelnamen. `Firma` wird dabei auch auf Kategorien wie „Firma (extra Rechnung)“ aufgelöst.
- Vorhandene Grundartikel werden für Spezialziele einmalig als eigene Zielvariante geklont. Originalkategorie bleibt erhalten; Bild/Icon, Standardmenge und bearbeitete Stammdaten werden übernommen. Für solche Klone startet keine neue Gemini-Klassifizierung oder Bildgenerierung.
- Normale Eingaben wie `Butter 10x` verwenden den vorhandenen Stammartikel und speichern nur die Menge am Listeneintrag. Nur wirklich unbekannte Grundartikel dürfen die normale KI-/Bildpipeline starten.
- Dubletten werden pro Grundartikel und Zielvariante erkannt; Menge, Notiz und Produktunterteilung ändern die Identität nicht. Ein vorhandenes „Hähnchen · Geschnetzeltes“ blockiert daher ein zweites „Hähnchen“.
- Der Integrationsimport übernimmt strukturierte Mengen und Spezialziele verlustfrei. Alte Fehlkonstrukte wie `Butter 10x Firma` oder `Bananen 15x Firma` werden auf saubere Zielvarianten migriert, soweit ein Grundartikel sicher zugeordnet werden kann.

## 0.3.47
- Strukturierte Import-Kategorien werden jetzt fail-closed behandelt: angeforderte unbekannte Kategorie führt zu Fehler statt stiller normaler Einsortierung und KI-Erstellung.
- Firma-Import normalisiert Basisname und Menge defensiv; eingebettete Mengen-/Firma-Suffixe können keinen falschen Stammartikel mehr erzeugen.
- Sehr spezifische Altfehler wie „Butter 10x Firma“ werden beim Start auch dann repariert, wenn der Stammartikel zwischenzeitlich als manuell markiert wurde.

## 0.3.47

- Der Integrationsimport kann eine Kategorie jetzt zusätzlich strukturiert über `categoryName` oder `categoryId` erhalten. Alexa-Sync muss damit `Firma` nicht mehr ausschließlich als Teil des Artikelnamens transportieren.
- Strukturierte Firma-Imports verwenden den bereinigten Stammnamen und die separat übergebene Menge. Dadurch wird z. B. `Butter 10x Firma` als `Butter`, 10 Stück, Kategorie `Firma` angelegt.
- Beim Anlegen einer Kategorievariante wird ein bereits bearbeitetes gleichnamiges Produkt aus einer anderen Kategorie weiterhin lokal wiederverwendet; dafür startet keine zusätzliche Gemini-Klassifizierung oder Bildgenerierung.
- Die bestehende Reparatur falsch angelegter Firma-Artikel übernimmt bei einem vorhandenen bearbeiteten Stammartikel jetzt auch dessen Bild. Ein zuvor automatisch erzeugtes falsches Icon wird dadurch beim Neustart ersetzt; manuell hochgeladene Icons bleiben unangetastet.

## 0.3.45

- Bereits bearbeitete Produktbilder werden jetzt auch über Kategorien hinweg wiederverwendet; für denselben Artikel startet dadurch keine neue automatische KI-Bild-/Klassifizierungsrunde.
- Alexa-Fehlhörer für `Firma` erkennen zusätzlich Ziffernformen wie `4 mal`; `Butter 3x 4 mal` wird als Butter, 3 Stück, Kategorie Firma übernommen.
- Bei erkannten Firma-Fehlhörern hat die im Artikelnamen enthaltene Menge Vorrang vor einer widersprüchlichen externen Mengenangabe.
- Alexa-/Integration-Importe behandeln denselben Stammartikel in derselben Kategorie unabhängig von der Menge als Duplikat und legen ihn nicht ein zweites Mal an.

## 0.3.44

- Alexa-/Sync-Import für die Kategorie „Firma“ korrigiert: explizite Mengen aus der Integration überschreiben die Mengenangabe jetzt erst nach der Kategorieerkennung, sodass „… drei Stück vier mal“ zuverlässig in „Firma“ landet.
- Bereits falsch einsortierte automatische Firma-Artikel wie „Hafermilch 1x Firma“ werden beim Versionswechsel automatisch bereinigt, in die Kategorie „Firma“ verschoben und eine im Namen steckende Menge wiederhergestellt.
- Manuell angelegte Stammartikel bleiben von dieser Reparatur unberührt; ein echtes „Butter vier mal“ ohne vorherige Mengenangabe bleibt weiterhin eine normale Mengenangabe.

## 0.3.43

- Favoriten vollständig aus der sichtbaren Oberfläche entfernt; gespeicherte Favoriten-Daten bleiben für Rückwärtskompatibilität unangetastet.
- „Favoriten & zuletzt“ heißt jetzt überall nur noch „Zuletzt“; Desktop-Übersicht und Navigation wurden entsprechend bereinigt.
- Abgehakte Artikel werden ohne störende Wiederherstellen-Meldung direkt nach „Zuletzt“ verschoben und können dort per Plus wieder auf die Liste gesetzt werden.
- Abhaken auf iPhone/iPad ist zuverlässiger: jede Artikelkarte hat jetzt eine große, eindeutige Ein-Tipp-Hakenfläche mit kurzer Ausblendanimation.
- Touch-Ziele wurden gegen unbeabsichtigten Doppeltipp-Zoom gehärtet; Formfelder behalten auf kleinen iPhones eine zoombeständige Schriftgröße.
- Alexa-Fehlhörer für die Kategorie „Firma“ werden gezielt abgefangen: z. B. „Butter drei Stück vier mal“ wird als „Butter“, 3 Stück, Kategorie „Firma“ verarbeitet. Ein alleinstehendes „Butter vier mal“ bleibt weiterhin eine Mengenangabe und wird nicht in „Firma“ umgedeutet.

## 0.3.42

- Artikelbearbeitung: klare, beschriftete Kopfaktionen mit Haken für „Speichern“ und Box-Symbol für „Artikelstamm“ statt der bisherigen schwer verständlichen Icon-Buttons.
- Spracheingaben und Alexa-Importe erkennen einen vorhandenen Kategorienamen am Ende der Eingabe, z. B. „Banane Firma“ -> Artikel „Banane“ in Kategorie „Firma“.
- Gleiche Artikelnamen dürfen bewusst in verschiedenen Kategorien parallel existieren; die Kombination aus Artikel und Kategorie bleibt getrennt.
- Ein Kategorienwechsel eines Listeneintrags verschiebt den bisherigen Stammartikel nicht mehr global, sondern verwendet bzw. erzeugt einen eigenen Stammartikel in der Zielkategorie.
- Alexa-Namen werden vor dem Speichern stärker bereinigt (u. a. bekannte Marken/Begriffe, „Alverde Rasierer sensitiv“ -> „Alverde Rasiergel sensitiv“, „Shampoo patrick“ -> „Shampoo Patrick“).
- Bei explizit genannten Kategorien bleibt die Kategorie auch bei Gemini-Nachbearbeitung gesperrt; Gemini darf nur Namen und Darstellung säubern.

## 0.3.41

- Versionsnummer auf 0.3.41 korrigiert, da 0.3.40 bereits vergeben war; Funktionsumfang entspricht dem zuvor vorbereiteten 0.3.40-Stand.
- Doppeltipp auf Artikelkarten hakt weiter ab, ohne den Safari-Doppeltipp-Zoom auszulösen.
- Long-Press zum Bearbeiten reagiert erst nach 800 ms und wird bei Scroll-/Fingerbewegung sofort abgebrochen.
- Wirklich neue Artikel werden bei konfiguriertem Gemini fachlich kategorisiert; Produktart hat Vorrang vor Zutaten/Geschmacksbegriffen. Shop-, Hard- und gelernte Regeln bleiben verbindlich.
- Statusanzeige vereinfacht auf grünes „Online“ bzw. rotes „Offline“ und „Offline · x offene Änderungen“.
- Artikelbearbeitung aufgeräumt: Kategorie zuerst, Hilfetexte entfernt, Speichern und Artikelstamm als obere Icon-Aktionen.

</details>
- Artikelstamm und Kategorieeditoren vereinheitlicht, Hilfetexte reduziert und Speichern als hervorgehobene obere Icon-Aktion.
- „Bearbeitet“ ist grün, „Unbearbeitet“ rot.

# 0.3.39

- Startpfad gegen Safari-/Cloudflare-Hänger gehärtet: `/api/...` wird immer explizit same-origin ab der Domainwurzel geladen und bekommt einen Netzwerk-Timeout.
- Online-Daten laden jetzt vollständig unabhängig von IndexedDB. Ein blockierter oder träger Offline-Speicher kann die Einkaufsliste nicht mehr mit leerem Inhalt stehen lassen.
- IndexedDB-Öffnen sowie Lese-/Schreibzugriffe besitzen kurze Timeouts und fallen automatisch auf LocalStorage zurück, statt den App-Start unbegrenzt zu blockieren.
- Der lokale Cache wird parallel geladen; sobald der Server erreichbar ist, hat der aktuelle Serverzustand Vorrang. Offline-Warteschlangen werden anschließend weiterhin synchronisiert.
- Backup-Download verwendet ebenfalls einen expliziten Root-Pfad.

# 0.3.38

- Offline-Start blockiert nicht mehr auf `navigator.serviceWorker.ready`; Serverzustand und UI laden sofort, die Offline-Vorbereitung läuft parallel.
- Service-Worker-Shell und Produkt-/Kategorie-Bilder nutzen getrennte Caches. Beim Update werden bereits vorhandene Bilder aus dem alten Shell-Cache in den neuen dauerhaften Bildcache übernommen; danach bleibt dieser über weitere App-Updates erhalten.
- Aktuell verwendete Artikel- und Kategorie-Bilder werden nach erfolgreichem Online-Laden gezielt für Offline-Nutzung vorgeladen.
- Der Status `Offline-Speicher wird vorbereitet` wurde entfernt; stattdessen werden nur aussagekräftige Zustände wie `Synchronisiert`, `Offline bereit` oder `Offline` gezeigt.
- Die mobile Bottom-Navigation wurde nach dem bewährten Kleinanzeigen-Prinzip neu aufgebaut: feste Höhe, monochrome SVG-Icons, saubere Safe-Area und gleichmäßige Zentrierung.
- Eingabezeile, Snack und Auswahlleiste sitzen sauber oberhalb der neuen Bottom-Navigation.

# 0.3.37

- Kategorienverwaltung auf Mobilgeräten gegen horizontales Verschieben abgesichert; Aktionsknöpfe brechen sauber in eine eigene Zeile um.
- Kopfbereich und untere Navigation nochmals verdichtet; Sync-Status steht platzsparend neben der Zusammenfassung.
- Kategorieblöcke sind flacher, lange Kategorienamen werden zweizeilig und kleiner dargestellt.
- Einkaufsorte REWE, Meyerhof und DM/Rossmann/Müller erhalten in der Liste eine dezente Kennzeichnung als Einkaufsort.
- Einkaufsmenge, Produktgröße/Variante und Freitext-Notiz sind optisch klarer voneinander unterscheidbar.
- Die Eingabezeile ist im Ruhezustand flacher und wächst beim Fokussieren wieder auf komfortable Höhe.
- In den Einstellungen gibt es jetzt „Liste durchsuchen“ für offene Artikel; Treffer springen direkt zum Artikel in der Einkaufsliste.

# 0.3.36

- Ladenbezogene Artikel (REWE, Meyerhof, DM/Rossmann/Müller) übernehmen ein vorhandenes Artikelbild nur noch dann, wenn der Quellartikel bereits bearbeitet ist.
- Übernommene Bilder werden als eigene lokale Kopie gespeichert und im Artikelstamm transparent als „Bild übernommen aus dem Artikel …“ gekennzeichnet.
- Ist der passende Quellartikel noch unbearbeitet, läuft für den neuen Ladenartikel stattdessen die normale individuelle Bildverarbeitung.
- Bereits vorhandene Ladenartikel mit einem nur provisorisch übernommenen Stammbild werden beim Start automatisch nach dieser Regel repariert.
- Der mobile Kopfbereich der Einkaufsliste ist deutlich kompakter.
- Der Artikelstamm besitzt jetzt eine direkte Artikelsuche über Name, Schlüssel und gelernte Alexa-Namen.
- Die untere Navigation ist flacher und platzsparender.
- Doppeltippen in freien Zwischenbereichen löst keinen Browser-Zoom mehr aus; Doppeltipp auf einem Artikel bleibt weiterhin die Abhak-Geste.

# 0.3.35

- Ladenkürzel aus Alexa-Namen werden lokal erkannt: `DM`, `D. M.`, `Rossmann` und `Müller` landen in der gemeinsamen Kategorie `DM/Rossmann/Müller`; der Laden bleibt sichtbar als Zusatz wie `Starkes Deo (DM)`.
- Frühere automatisch falsch einsortierte Ladenartikel werden bei der Migration korrigiert und fehlende/pending Icons erneut durch die normale Gemini-Pipeline verarbeitet.
- Der Alexa-/Integration-Import verwendet für wirklich neue Artikel jetzt dieselbe vollständige Verarbeitung wie das manuelle Hinzufügen, statt nur eine Klassifizierung anzustoßen.
- REWE-Sonderlogik ergänzt: `Gouda REWE`, `REWE Gouda` oder `Gouda (REWE)` werden als eigener REWE-Stammartikel behandelt, sichtbar zu `Gouda` bereinigt und automatisch in die Kategorie `REWE` einsortiert.
- Falls die Kategorie `REWE` bei einem REWE-Artikel noch fehlt, wird sie automatisch in der betroffenen Liste angelegt. Ein eigenes lokales REWE-Kategorie-Icon ist enthalten.
- REWE bleibt intern im Stammschlüssel/Alias erhalten, damit z. B. normaler `Gouda` und `Gouda REWE` getrennte Stammartikel bleiben.

# 0.3.34

- Produktgröße/Variante wird getrennt von der tatsächlichen Einkaufsmenge gespeichert und angezeigt. Automatisch erkannte Gewichts-/Volumenangaben wie „1 Liter“ oder „500 g“ bleiben vollständig erhalten, erscheinen aber nicht mehr als Einkaufsmenge.
- Sprachkombinationen wie „2 Packungen Zip Tiefkühlbeutel ein Liter“ werden in Artikel, Einkaufsmenge und Produktgröße getrennt.
- Sichere Namensnormalisierung für „Zip Tiefkühlbeutel“/„Zip Gefrierbeutel“ ergänzt, ohne den ursprünglichen Alexa-Text zu verlieren.
- Bearbeiten-Dialog um „Produktgröße / Variante“ ergänzt; Freitext-Notiz und Mengenfelder bleiben unabhängig davon bestehen.
- Duplikat-, Zuletzt- und Listenverschiebe-Logik berücksichtigt Produktgröße/Variante, sodass unterschiedliche Größen desselben Stammartikels getrennt bleiben können.

# 0.3.33

- Einkaufsliste auf ein ruhigeres Ein-Zeile-pro-Artikel-Layout mit deutlich größeren Produktbildern umgestellt; vorhandene Kategorie-Icons bleiben erhalten.
- Abhaken erfolgt per Doppeltipp auf die Artikelzeile; einfacher Tipp bleibt ohne Aktion, langes Drücken öffnet weiterhin die Bearbeitung.
- Freitext-Notiz pro Einkaufslisteneintrag ergänzt und getrennt von Menge/Einheit dargestellt; alte Notiz-Hacks in der Einheit werden bei der Migration übernommen.
- Meyerhof-Sonderlogik ergänzt: Schreibvarianten wie „Gouda Meyerhof“ oder „Bunte Nudeln (Meyerhof)“ werden in die vorhandene Kategorie Meyerhof einsortiert und der Hofname aus dem Artikelnamen entfernt.
- Neues lokales Meyerhof-Kategorie-Icon auf Basis des Hof-Emblems mitgeliefert.
- Gemini-Bildpipeline für wirklich neue Artikel repariert: Bildgenerierung läuft auch nach fehlgeschlagener Klassifizierung weiter und wird auch für neue Artikel aus dem Alexa-/Import-Sync gestartet.
- Ausstehende Gemini-Bilder werden nach Neustart wieder aufgenommen; Verarbeitungszustände bleiben nicht dauerhaft auf „KI Erstellung“ hängen.

# 0.3.32
- Artikelstamm und Kategorie-Editor unterstützen jetzt „Eigenes Icon hochladen“ zusätzlich zur Gemini-Erstellung.
- Hochgeladene Bilder werden im Browser auf eine quadratische 1024×1024-Iconfläche mit weißem Hintergrund vorbereitet, persistent unter /data gespeichert und sofort verwendet.
- Eigene Uploads verursachen keine Gemini-Kosten und setzen Artikel-Icons auf „Bearbeitet“.
- Laufende Gemini-Bildjobs dürfen ein zwischenzeitlich hochgeladenes eigenes Icon nicht mehr überschreiben.
- PNG, JPEG und WebP werden serverseitig validiert; große Originalbilder werden vor dem Upload im Browser verkleinert.

# 0.3.31
- Gemini-Kostenübersicht zusätzlich direkt unter Einstellungen/Listen verwalten.
- Letzte Gemini-Erstellung zeigt neben dem tatsächlichen Euro-Preis auch den zuletzt erzeugten Artikel oder die zuletzt erzeugte Kategorie.

# 0.3.30

- Alexa-/Spracheingaben lernen bestätigte Artikelnamen als lokale Aliase. Auch eindeutige reine Schreib-/Abstandsvarianten werden lokal einem vorhandenen Stammartikel zugeordnet und anschließend als Alias gespeichert.
- Artikel können optional eine Standardmenge und Standardeinheit erhalten. Diese wird nur verwendet, wenn beim Hinzufügen keine Menge genannt wurde; eine ausdrücklich angegebene Menge hat immer Vorrang.
- Manuelle Kategorie-Korrekturen werden vorsichtig stärker lokal genutzt: exakte bestätigte Beispiele sofort, eindeutige mehrteilige Begriffe bereits nach einer Bestätigung, einzelne allgemeine Wörter weiterhin erst nach wiederholter Bestätigung.
- Gemini ist bei der automatischen Klassifizierung jetzt die letzte Stufe: harte lokale Regeln, gelernte Kategorien und bekannte Katalogzuordnungen werden nicht erneut zur Klassifizierung an Gemini geschickt.
- Bereits bearbeitete Stammartikel mit verarbeitetem Icon lösen beim erneuten Hinzufügen keine weitere Gemini-Icon-Erstellung aus. Unbearbeitete bekannte Artikel dürfen weiterhin einmalig vervollständigt werden; ein bearbeitetes Icon wird nur über den ausdrücklichen Button „Icon neu erstellen“ neu erzeugt.
- Datenmigration ergänzt die neuen Standardmengen- und Aliasfelder rückwärtskompatibel; bestehende Artikel, Kategorien, Icons und Listeneinträge bleiben erhalten.

# 0.3.29

- Artikelliste vereinfacht: Favoriten-Stern und Artikelstamm-Zahnrad aus den normalen Artikelzeilen entfernt; der grüne Erledigt-Haken bleibt.
- Artikelstamm-Editor vereinfacht: Produktart, Motiv und Icon-Text entfernt; neu ist ein optionaler Freitext „Icon-Hinweis“ für konkrete Darstellungswünsche wie „frischer Rosmarin“ oder „getrocknet im Gewürzglas“.
- Bearbeitungsstatus (Bearbeitet / Unbearbeitet / In Bearbeitung) wird direkt im geöffneten Artikelstamm angezeigt.
- Gemini-Iconkosten werden nicht mehr pauschal geschätzt. Nach erfolgreicher Erstellung werden die tatsächlich gemeldeten API-Tokens nach Modalität bepreist und mit dem ECB-Tagesreferenzkurs in Euro gespeichert. Anzeige: letzte Erstellung, heute und Gesamt seit 0.3.29.
- Icon-Hinweise werden vor einer manuellen Neuerstellung gespeichert und direkt in den Gemini-Bildprompt übernommen.
- Kategorie-Icons verwenden dieselbe verbrauchsbasierte Euro-Kostenlogik; vor der Erstellung wird kein geschätzter Einzelpreis mehr angezeigt.

# 0.3.28

- Artikelstamm: dauerhafte Löschfunktion mit Sicherheitsabfrage; offene und zuletzt erledigte Listeneinträge bleiben als Snapshot lesbar.
- Listenartikel: Löschbutton aus dem Bearbeiten-Dialog entfernt und direkter Sprung zum zugehörigen Artikelstamm ergänzt.
- Alexa/Mengenparser: Verpackungseinheiten wie „Nachfüllbeutel“ werden getrennt vom Artikelnamen als Menge/Einheit übernommen.
- Gemini-Icons: geschätzte Kosten pro Erstellung sowie Tages- und Gesamtsumme (ab 0.3.28) werden angezeigt und persistent gezählt.
- Kategorien: Beschreibungen für die automatische Zuordnung, klarere Trennung Haushalt/Drogerie und Gemini-Kategorie-Icons ergänzt.

# 0.3.27
- Bisherige Produktbilder als Ausgangspunkt; vorhandene bearbeitete Einzelbilder werden übernommen.
- Unbearbeitete Artikel erhalten beim Hinzufügen im Hintergrund ein eigenes Gemini-Bild im realistischen Mini-Produktfotostil.
- Bearbeitungsstatus wird nach erfolgreicher Speicherung dauerhaft gesetzt. Mehrfaches Hinzufügen löst keine doppelten Aufträge aus. Aufträge werden nacheinander verarbeitet.
- Fehler behalten das bisherige Bild; beim nächsten Hinzufügen kann erneut versucht werden.
- Bekannte Artikel behalten ihre Kategorien; unbekannte Artikel nutzen weiterhin die Gemini-Klassifizierung.
- Hintergrund-Sync ohne unnötiges Neurendern, persistente Stammartikellöschung und Kategorieabstand bleiben erhalten.
- Kein Zurücksetzen bestehender Einkaufsdaten. Gemini-Schlüssel weiterhin aus der App-Konfiguration.
