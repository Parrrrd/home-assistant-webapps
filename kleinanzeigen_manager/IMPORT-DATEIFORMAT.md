# Kleinanzeigen-Importdatei (.kaanzeige)

Eine `.kaanzeige`-Datei ist ein ZIP-Archiv mit eigener Dateiendung.

## Aufbau

```text
anzeige.json
bilder/
  01.jpg
  02.jpg
```

## Beispiel für `anzeige.json`

```json
{
  "format": "kleinanzeigen-manager-import",
  "version": 1,
  "title": "Titel mit maximal 65 Zeichen",
  "description": "Vollständiger Anzeigentext",
  "price": 25,
  "price_type": "NEGOTIABLE",
  "category": "Haus & Garten",
  "folder": "",
  "ad_type": "OFFER",
  "shipping_type": "SHIPPING",
  "shipping_options": ["Hermes_Päckchen", "Hermes_S", "DHL_2"],
  "active": true,
  "images": ["bilder/01.jpg", "bilder/02.jpg"]
}
```

Unterstützte Preisarten: `NEGOTIABLE`, `FIXED`, `GIVE_AWAY`.
Unterstützte Versandarten: `SHIPPING`, `PICKUP`.
Unterstützte Bilder: JPG, JPEG, PNG, WEBP und GIF; maximal 20 Bilder.

## Export

Bestehende Anzeigen können im Aktionsmenü als `.kaanzeige` exportiert werden. Der Export verwendet dasselbe Schema wie der Import, legt `anzeige.json` auf oberster Ebene ab und kopiert die vorhandenen Bilder in ihrer Anzeigenreihenfolge unverändert nach `bilder/`. Reine Laufzeitdaten aus `app-state.json` sind nicht Bestandteil des Pakets.

## Import-Trigger ab 1.5.24.5

Neue `.kaanzeige`-Dateien werden ereignisgesteuert verarbeitet, sobald sie vollständig in `/media/Import/Kleinanzeigen` angekommen sind. Google Drive dient nur als Transportquelle und schreibt zunächst eine versteckte `.part`-Datei; erst der atomare Rename auf `.kaanzeige` löst den Import aus. Ein Push wird erst nach erfolgreichem Import in den Manager ausgelöst.
