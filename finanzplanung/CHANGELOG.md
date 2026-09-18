## 0.1.50 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

## 0.1.49
- Vorjahreshinweise in der Jahresplanung können per Checkbox mehrfach ausgewählt werden
- Ausgewählte fehlende Positionen und Betragsabweichungen lassen sich gemeinsam übernehmen beziehungsweise aktualisieren
- Einzelne oder mehrere Hinweise können gelöscht werden, ohne Jahresposten zu verändern
- Gelöschte Hinweise werden je Zieljahr gespeichert
- Mit „Mit Vorjahr neu prüfen“ lassen sich gelöschte Hinweise wiederherstellen und der Abgleich neu berechnen

## 0.1.48
- Jahresplanung zeigt standardmäßig das komplette ausgewählte Jahr.
- Neuer Button „Zum aktuellen Monat“ springt innerhalb der Jahresplanung direkt zum aktuellen Monatsbereich.
- Jahresposten unterstützen jetzt optionale Notizen; sie werden in Liste, Suche, Kopien, Wiederholungen und Jahres-PDF übernommen.
- Neuer Vorjahresabgleich zeigt fehlende Positionen und abweichende Beträge gegenüber dem direkten Vorjahr.
- Fehlende Vorjahrespositionen können mit einem Klick übernommen und abweichende Beträge auf den Vorjahreswert aktualisiert werden.

## 0.1.47
- Einzelne Vorratsvarianten können gelöscht werden; zugehörige Endbestände, Nachkäufe und Verbrauchsbuchungen werden dabei bereinigt.
- Ganze Vorratspositionen können jetzt auch direkt aus dem Bearbeiten-Bereich und in der mobilen Ansicht gelöscht werden.
- Die Neuberechnung der Vorrats-Verbrauchsbuchungen nach Änderungen wurde robuster gemacht.

## 0.1.46
- Vorratspositionen unterstützen mehrere Varianten je Position, z. B. Dose und Tüte mit eigener Menge, Einheit und eigenem Preis.
- Endbestandserfassung zeigt Varianten getrennt und speichert mehrere Endbestände pro Vorratsposition in einem Schritt.
- Zusätzliche Einkäufe werden einer konkreten Variante zugeordnet.
- Optionales Leergewicht je Variante ergänzt; es wird bei der Endbestandserfassung nur angezeigt, wenn ein Wert hinterlegt ist.
- Bestehende Vorratsdaten werden automatisch als Standard-Variante übernommen.

## 0.1.45
- Offene Summen in Übersicht/Buchungen korrigiert: Einnahmen werden bei „Offen“ und „Konto offen“ mitgerechnet.
- Offene Ausgaben werden wieder als Minus angezeigt statt als positiver Betrag.

## 0.1.43
- Vorräte können jetzt zusätzliche Einkäufe pro bestehender Position speichern.
- Verbrauch und Restwert werden mit Startbestand plus Zugängen im Monat berechnet.
- Verbrauchsbuchungen werden nach Einkäufen/Korrekturen ab dem betroffenen Monat neu synchronisiert.

## 0.1.42
- Hauptnavigation neu strukturiert: Übersicht, Buchungen, Planung und Verwaltung
- Planung bündelt Töpfe, Vorräte und Jahr
- Verwaltung bündelt Fixkosten, Grundeinstellungen, Jahresstart, Kategorien, Backup und Papierkorb
- Vorratsverwaltung ergänzt: Vorratspositionen anlegen, monatlichen Endbestand erfassen und Verbrauch automatisch als Monatsbuchung buchen
- Jahresansicht zeigt wahlweise ausgewählten Monat oder gesamtes Jahr
- Topf-Detailseite bietet direkt „Neue Topfbewegung" und „Zurück zu Töpfe"

## 0.1.41 - Fixkosten-Filter
- Filter in der Fixkosten-Verwaltung: Aktiv, Beendet und Alle.
- Standardansicht zeigt aktive/nicht beendete Vorlagen, alte beendete Vorlagen sind über „Beendet“ oder „Alle“ erreichbar.

## 0.1.40 - Zeitgueltige Fixkosten

- Fixkosten-Vorlagen koennen jetzt ab einem gewaehlten Monat neu angelegt werden, ohne vergangene Monate zu erzeugen.
- Bestehende Fixkosten werden beim Bearbeiten ab dem gewaehlten Monat als neue Version fortgefuehrt; alte Monate bleiben unveraendert.
- Fixkosten koennen ab einem gewaehlten Monat beendet werden; vergangene Buchungen bleiben erhalten.
- Zukuenftig bereits erzeugte alte Fixkosten-Buchungen werden beim Aendern/Beenden ab dem Stichtag entfernt, damit keine Doppelungen entstehen.

# v0.1.39
- Buchungen-Seite: neuer Schnellfilter „Ohne Fixkosten“ zeigt für den gewählten Monat alle Buchungen außer Kategorie Fixkosten.
- Jahresposten: der Typ „Ausgabe (−)“ oder „Einnahme (+)“ bestimmt jetzt zuverlässig das Vorzeichen, auch wenn der Betrag ohne Minuszeichen eingegeben wird.

# v0.1.38
- Auf der Übersichtsseite wurde „Konto offen“ wieder entfernt; dort bleiben Monatsergebnis und Offen.
- Auf der Buchungen-Seite gibt es jetzt zusätzlich einen Zahlwegfilter für Alle Zahlwege, Konto und Kreditkarte.

# v0.1.37
- Offen und Konto offen rechnen jetzt einheitlich nur offene Ausgaben. Einnahmen werden nicht mehr mit offenen Ausgaben verrechnet, damit Konto offen nicht größer als Offen werden kann.

## 0.1.36
- Übersicht zeigt jetzt unter Einnahmen/Ausgaben eine eigene Dreier-Zeile: Monatsergebnis, Offen und Konto offen.
- Mobile Darstellung der drei Karten verdichtet, damit sie in einer Zeile bleiben.

## 0.1.35

- Buchungen und Fixkosten-Vorlagen haben jetzt den Zahlweg „Konto“ oder „Kreditkarte“.
- Fixkosten-Vorlagen werden standardmäßig als „Konto“ angelegt; variable Buchungen standardmäßig als „Kreditkarte“.
- Die Buchungen-Seite zeigt zusätzlich „Konto offen“ neben Monatsergebnis und offenen Buchungen.
- Die Passwortseite erscheint nicht mehr beim normalen Öffnen; sie wird erst nach manuellem Sperren über das Schloss benötigt.

## 0.1.34
- Standardmonat beim Öffnen auf aktuellen Monat gesetzt statt entferntester Zukunftsmonat.
- Auf Töpfe/Fixkosten zusätzlicher Schnellbutton Topfbewegung ergänzt.
- Topf-Bewegungsformular auf der Töpfe-Seite per focus=payment direkt geöffnet.

## 0.1.33
- Neues Icon mit Variante 3 eingebaut
- Home-Bildschirm-Name und Panel-Titel auf „Finanzen & Budget“ angepasst
- Apple-Icon, Manifest und Favicon ergänzt
- Dockerfile für aktuellen Home-Assistant-Build angepasst

## 0.1.32
- Jahresposten übernehmen jetzt das Vorzeichen korrekt aus dem Feld Typ. `Ausgabe` wird automatisch negativ gespeichert, auch wenn beim Betrag kein Minus eingegeben wird.

## 0.1.31
- Übersicht neu sortiert: nach den Kennzahlen zuerst offene Buchungen, dann Monat im Überblick
- Bereich Jahr neu sortiert: zuerst Verlauf, dann Jahresposten, dann Jahresplanung, der Rest darunter
- Navigationspunkt „Fixkosten“ in „Töpfe/Fixkosten“ umbenannt
- Seite Töpfe/Fixkosten zeigt oben jetzt zuerst die Töpfe
- Eigene Seite für Topf-Bewegungen ergänzt, damit die Bewegungen nicht mehr unten auf der Töpfe-Seite erscheinen

## 0.1.30
- Backups nur noch höchstens einmal pro Stunde bei Änderungen
- Offene Buchungen farblich deutlicher markiert
- Neue Buchungen und Jahresposten mit Typ-Auswahl Ausgabe/Einnahme, Standard Ausgabe

## 0.1.28
- Sperren jetzt als Schloss-Symbol direkt rechts neben der Überschrift in der Kopfzeile
- Buchungsseite oben zeigt statt Fixkosten und Variabel jetzt Monatsergebnis und Offen

## 0.1.27
- Optionalen Passwortschutz für die Webapp ergänzt
- Neue Login-Seite vor allen geschützten Ansichten
- Add-on-Konfiguration um `web_password` erweitert

## 0.1.26
- Buchungen mobil: Aktionsbuttons „Wieder offen“, „Bearbeiten“ und „Löschen“ in einer Zeile

## 0.1.25
- Töpfe-Bereich und Bewegungen auf der Töpfe-Seite als einklappbare Abschnitte ergänzt
- Mobile Listen für Buchungen, Topfstände und Topf-Bewegungen deutlich kompakter gemacht
- Lange Titel und Notizen in Buchungen und Bewegungen auf 2–3 Zeilen gekürzt
- Navigationspunkt „Töpfe“ oben entfernt; Zugriff weiter über Übersicht und Direktlinks

## 0.1.24
- Korrektur: "Offen" auf der Übersichtsseite zeigt jetzt die echte Summe der offenen Buchungen im gewählten Monat statt der absoluten Beträge.

## 0.1.23
- Neue Buchungen haben jetzt standardmäßig das heutige Datum vorausgewählt und bleiben dabei änderbar
- Übersicht oben zeigt statt „Ins Jahr" jetzt den offenen Monatsbetrag
- Monat im Überblick auf der Übersicht weiter entschlackt und die Zusatzboxen entfernt
- Direkt neben der Monatsauswahl gibt es jetzt einen Sprung zum aktuellen Monat
- Jahresverlauf und Jahresstand übernehmen keine Werte mehr aus Monatsbuchungen

## 0.1.22
- Buchungen lassen sich jetzt direkt nach alle, offen oder bezahlt filtern
- Mehrfachauswahl für sichtbare Buchungen ergänzt
- Sammelaktion „Ausgewählte als bezahlt markieren“ hinzugefügt
- Filter, Suche und Kategorie bleiben nach Aktionen auf der Buchungsseite erhalten

## 0.1.21
- Eingabe- und Bearbeitungsbereiche außerhalb der Übersichtsseite standardmäßig eingeklappt
- Betrifft jetzt Buchungen, Fixkosten, Töpfe sowie Jahresposten auf der Jahr-Seite
- Beim Bearbeiten eines vorhandenen Eintrags öffnet sich der jeweilige Bereich automatisch

## 0.1.20
- Jahr-Seite: Bereiche `Grundeinstellungen` und `Jahr auswählen` als standardmäßig eingeklappte Klappbereiche umgesetzt, damit `Jahresposten hinzufügen` schneller erreichbar ist.

## 0.1.19
- Suchfeld ergänzt auf den Seiten Buchungen, Fixkosten und Jahr
- Einzelne automatisch erzeugte Monatsbuchungen lassen sich jetzt wirklich löschen, ohne sofort wieder aus der Fixkosten-Vorlage zu erscheinen
- In den Bewegungen der Töpfe wird jetzt zusätzlich der Status bezahlt/offen angezeigt

## 0.1.18
- Topf-Stände werden jetzt nur noch aus tatsächlich bezahlten Ein- und Auszahlungen berechnet
- Alte Monatszuweisungen aus pot_plans fließen nicht mehr in den angezeigten Stand ein und verfälschen damit Einzahlungen und Saldo nicht mehr

## 0.1.17
- Bearbeitete Fixkosten-Vorlagen übernehmen Änderungen ab dem gewählten Startmonat jetzt auch in bereits erzeugte Monatsbuchungen
- Nicht mehr passende automatisch erzeugte Fixkosten-Buchungen ab diesem Startmonat werden entfernt, damit Monatsansicht und Vorlage wieder zusammenpassen

## 0.1.16
- Topf-Bewegungen in der Detailansicht werden jetzt nur noch bis zum oben ausgewählten Monat angezeigt
- Monatsbuchungen mit Topf-Zuordnung werden in der Topf-Sicht jetzt mit umgedrehter Richtung ausgewertet: Konto-Ausgabe wird zur Topf-Einzahlung, Konto-Einnahme zur Topf-Auszahlung
- Summen für Einzahlungen, Auszahlungen und Stand der Töpfe folgen jetzt derselben Topf-Logik

## 0.1.15
- Topf-Bewegungen können jetzt wahlweise auch in den Monatsbuchungen erscheinen oder nur im Topf bleiben
- In der Topf-Detailansicht werden jetzt auch Monatsbuchungen mit Topf-Zuordnung angezeigt
- Monatsbuchungen mit Topf-Zuordnung lassen sich direkt aus der Topfansicht in der Buchungsseite öffnen

## 0.1.14
- Topf-Bereich unterstützt jetzt manuelle Einzahlungen und Auszahlungen direkt in der Oberfläche
- Manuelle Topf-Bewegungen können bearbeitet und gelöscht werden
- Detailansicht der Töpfe zeigt jetzt alle manuellen Bewegungen mit Art und Betrag

## 0.1.13
- Jahresseite unten auf den ausgewählten Monat gefiltert: In der Liste der Jahresposten werden jetzt nur noch die Posten des oben gewählten Monats angezeigt.
- Bearbeiten funktioniert weiterhin auch für vorhandene Jahresposten außerhalb der gefilterten Monatsliste.

## 0.1.12
- Eigener Barbestand pro Jahr ergänzt, zusätzlich zum Startsaldo ohne Bar
- Jahresverlauf zeigt den Stand jetzt getrennt ohne Bar und mit Bar
- Jahresposten können als Barzahlung markiert werden und wirken dann nur auf den Barbestand

## 0.1.11
- Jahre bekommen eigene Startsalden pro Jahr statt nur eines globalen Werts.
- Folgejahre können manuell aus dem aktuellen Jahr aktualisiert werden. Dabei werden nur Planung und Jahreskosten übernommen.
- Startsalden der Folgejahre werden dabei aus dem Jahresende des Vorjahres fortgeschrieben.

## 0.1.10
- Jahresplanung mobil deutlich kompakter als kurze Karten mit Titel, Monat, Status, Betrag und Aktionen in einer kompakten Zeile/Gruppe
- Bereich „Töpfe“: Formular für Monatszuweisungen entfernt und durch direkte Topf-Zahlungen ersetzt
- Topf-Stände berücksichtigen jetzt neben alten Zuweisungen auch bezahlte positive Buchungen mit Topf-Zuordnung

## 0.1.9
- Kategorien im Bereich „Monat im Überblick“ mobil kompakter gemacht: Kategorie und Betrag wieder direkt nebeneinander statt untereinander
- Kategorieliste auf kleinen Displays dichter dargestellt und rechte Leerfläche besser genutzt
- Bereich „Jahresplanung“ / Jahreszahlungen am Seitenende mobil auf ein scrollfreies Kartenlayout umgestellt

# Changelog

## 0.1.7
- Jahresverlauf auf Mobilgeräten ohne horizontalen Scrollbereich neu formatiert
- Leeren rechten Bereich in der Jahresübersicht entfernt
- Spaltenbreiten und Tabellenlayout für kleine Displays fest verdrahtet
- Tabellenköpfe und Werte im Jahresverlauf kompakter abgestimmt

## 0.1.6
- Seitliches Scrollen der gesamten Seite auf Mobilgeräten behoben
- Bereich „Monat im Überblick“ neu ausgerichtet, damit Text und Buttons nicht mehr übereinander liegen
- Offene Buchungen noch kompakter als echte Ein-Zeilen-Liste umgesetzt
- Mobile Abstände und Breiten der Dashboard-Bereiche weiter bereinigt

## 0.1.5
- Mobile Ansicht deutlich kompakter gemacht
- Offene Buchungen auf der Übersicht als kurze Zeilen statt großer Karten
- Monatsübersicht und Kennzahlen auf kleinen Displays verkleinert
- Jahresverlauf und Jahresplanung mobil wieder als kompakte Tabellen dargestellt
- Buttons und Abstände auf iPhone kompakter abgestimmt

## 0.1.4
- Monat oben direkt anklickbar und per Monatsauswahl anspringbar
- Mobile Navigation und Karten so angepasst, dass Inhalte sauber in die Felder passen
- Kategorien auf der Übersicht verlinkt; Zahlungen einer Kategorie lassen sich direkt gefiltert ansehen
- Topf-Karten auf der Übersicht direkt anklickbar
- Offene Buchungen können direkt in der Übersicht als bezahlt markiert werden
- Jahresverlauf auf der Übersicht bis Dezember erweitert
- Jahresplanung um Barbestand ergänzt
- Fixkosten-Vorlagen unterstützen jetzt monatlich oder alle 3 Monate mit Startmonat
- PDF-Export für Monatsauswertung und Jahresauswertung ergänzt

## 0.1.3
- Kategorien sind bei Buchungen, Fixkosten-Vorlagen und Jahresposten auswählbar
- Neue Kategorien können direkt beim Speichern angelegt und für spätere Auswahl gespeichert werden
- Auf der Überblick-Seite zeigen die Topf-Karten kein „Geplant“ mehr, sondern nur noch Zahlungen und bezahlte Summe

## 0.1.2
- In der Topf-Übersicht die Spalte „Geplant“ entfernt
- Töpfe können jetzt direkt angeklickt werden
- Detailansicht mit allen zugeordneten Zahlungen pro Topf ergänzt

## 0.1.1
- Optik der Jahresansicht verbessert
- Jahresstand bis zum aktuellen Monat plus Prognose bis Jahresende
- Jahresposten können jetzt monatlich oder quartalsweise wiederholt angelegt werden

## 0.1.0
- Erste Version
- Monatsbuchungen
- Fixkosten-Vorlagen
- Töpfe mit Monatszuweisungen
- Jahresplanung
