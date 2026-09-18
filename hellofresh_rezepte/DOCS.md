# Rezeptverwaltung – Hinweise

Die App speichert importierte Rezepte unter `/share/HelloFresh` und überwacht `/media/Import/Rezepte`.

## Varianten
Jeder neue Import wird gespeichert. Rezepte mit demselben normalisierten Titel erscheinen in „Alle Rezepte“ als Varianten einer Gruppe. Mit „Nicht dasselbe“ kann eine falsch zugeordnete Variante dauerhaft getrennt werden.

## Einkaufsliste
Die Zutatenübertragung verwendet die Integrations-API der eigenen Einkaufsliste auf Port 8156. Standardmäßig wird dieselbe Ziel-Liste verwendet wie in `alexa_bring_sync`; wenn dort keine explizite Liste hinterlegt ist, wird `syncListId` der Einkaufsliste verwendet. Optional können Host, Port, Token und Listen-ID in den App-Optionen überschrieben werden. Die frühere Home-Assistant-Todo-/Ringbuch-Liste wird nicht mehr verwendet; bei einem Verbindungsfehler wird stattdessen eine Fehlermeldung angezeigt.
