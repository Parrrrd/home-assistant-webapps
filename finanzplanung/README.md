# Finanzen & Budget

Eine Home-Assistant-Webapp für:

- monatliche Buchungen
- wiederkehrende Fixkosten
- Rücklagentöpfe
- Jahresplanung

Die App speichert ihre Daten in `/share/Finanzen/finanzplanung-data.json`.

## Neu in 0.1.3

- Kategorien sind bei Buchungen, Fixkosten-Vorlagen und Jahresposten auswählbar
- Neue Kategorien können direkt beim Speichern ergänzt werden
- Die Topf-Karten im Überblick zeigen kein „Geplant“ mehr


Optional kann die Webapp mit einem Passwort geschützt werden. Dafür in der Add-on-Konfiguration `web_password` setzen.


## Jahresplanung ab 0.1.49

- Die Jahresplanung öffnet standardmäßig mit allen Monaten des ausgewählten Jahres.
- „Zum aktuellen Monat“ scrollt zum ersten sichtbaren Jahresposten des aktuellen Monats; ohne passenden Posten zum Monatsverlauf.
- Jeder Jahresposten kann eine optionale Notiz enthalten.
- Der Vorjahresabgleich vergleicht Monat, Titel, Kategorie und Bar-Kennzeichnung mit dem direkten Vorjahr.
- Fehlende Positionen können einzeln übernommen werden; bei abweichenden Beträgen wird ausschließlich der Betrag im Zieljahr aktualisiert.


### Vorjahresabgleich
Hinweise können einzeln oder gesammelt übernommen, aktualisiert und gelöscht werden. Das Löschen betrifft nur den Hinweis, nicht den eigentlichen Jahresposten. Der Button „Mit Vorjahr neu prüfen“ setzt die gelöschten Hinweise des ausgewählten Jahres zurück und berechnet den Vergleich erneut.
