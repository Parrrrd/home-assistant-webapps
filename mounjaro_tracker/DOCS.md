# Mounjaro Tracker

Port: 8140

Die App speichert Daten lokal unter `/data`. Gewicht kann automatisch über den konfigurierten Home-Assistant-Sensor, standardmäßig `sensor.withings_gewicht_4`, übernommen werden.

Der Wirkstoffverlauf ist eine rechnerische Näherung anhand der eingestellten Halbwertszeit und kein gemessener medizinischer Wert.

## Version 0.1.11
Freie Dosiswerte werden im Verlauf sichtbar angezeigt; neue Spritzen nutzen die aktuelle lokale Gerätezeit.
