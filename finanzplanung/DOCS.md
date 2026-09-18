# Nutzung

## Übersicht
Zeigt Monatssummen, Töpfe und die Jahresplanung.

## Buchungen
Hier werden variable Buchungen erfasst oder bestehende Buchungen bearbeitet.

## Fixkosten
Wiederkehrende monatliche Vorlagen.

## Töpfe
Rücklagen wie Strom oder BARF mit monatlichen Zuweisungen.

## Jahr
Jahresposten und Grundeinstellungen.


## Zugriffsschutz
Wenn ein Passwort gesetzt werden soll, in der Add-on-Konfiguration `web_password` befüllen. Danach verlangt die Webapp beim Öffnen zuerst dieses Passwort.


## Jahresplanung ab 0.1.49

- Die Jahresplanung öffnet standardmäßig mit allen Monaten des ausgewählten Jahres.
- „Zum aktuellen Monat“ scrollt zum ersten sichtbaren Jahresposten des aktuellen Monats; ohne passenden Posten zum Monatsverlauf.
- Jeder Jahresposten kann eine optionale Notiz enthalten.
- Der Vorjahresabgleich vergleicht Monat, Titel, Kategorie und Bar-Kennzeichnung mit dem direkten Vorjahr.
- Fehlende Positionen können einzeln übernommen werden; bei abweichenden Beträgen wird ausschließlich der Betrag im Zieljahr aktualisiert.


### Mehrfachbearbeitung im Vorjahresabgleich
Mehrere Hinweise lassen sich markieren und in einem Schritt übernehmen/aktualisieren oder löschen. Gelöschte Hinweise bleiben für das jeweilige Zieljahr ausgeblendet. „Mit Vorjahr neu prüfen“ hebt diese Ausblendungen wieder auf. Jahresposten werden beim Löschen eines Hinweises nicht entfernt.
