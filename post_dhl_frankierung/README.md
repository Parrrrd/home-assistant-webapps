# Post & DHL Frankierung

Lokale Home-Assistant-App für schnelle Deutsche-Post- und DHL-Frankierung.

## Version 0.1.36

- Fester Port 8151 plus Home-Assistant-Ingress.
- Guthabenabfrage robuster gemacht: Die App prüft jetzt sowohl die Portokassen-Anmeldung als auch das Benutzerprofil, weil DHL den Betrag je nach API-Antwort an unterschiedlicher Stelle liefert.
- INTERNETMARKE-PDFs erhalten eine eigene Druckansicht: „Drucken“ öffnet direkt den Systemdruckdialog, „PDF öffnen“ bleibt eine reine Vorschau.
- Das Portokassen-Guthaben wird im Briefmarkenbereich über die vorhandene, nur lesende INTERNETMARKE-Profilabfrage angezeigt und kann aktualisiert werden.
- Drucklayout der INTERNETMARKE verbessert: Leerzeilen werden nicht mehr übermittelt und der Adresszusatz wird unter Name/Firma gedruckt.
- Beim tatsächlichen Kauf wird nur noch `directCheckout=true` übergeben. Der reine Vorschau-Parameter `validate` wird nicht mehr unzulässig mitgesendet.
- Der Gesamtpreis der INTERNETMARKE wird aus dem offiziellen Produktpreis ermittelt und als Cent-Betrag an DHL übergeben. Dadurch wird die Pflichtfeld-Ablehnung `total: must not be null` behoben.
- INTERNETMARKE-PDF-Anfrage auf den von DHL erwarteten PDF-Positions-Typ korrigiert; dadurch wird der Fehler `InvalidTypeId` / `PCF-A1034` bei Straßen- und Postfachadressen behoben.
- DHL Parcel DE Private Shipping nutzt weiterhin die offizielle Production-Base-URL `https://api-eu.dhl.com/parcel/de/shipping/of/v1/public`.
- Die Paketansicht zeigt bewusst nur: Päckchen S, Päckchen M sowie DHL Paket 2 kg, 5 kg, 10 kg und 20 kg. Preise kommen weiterhin live aus dem offiziellen DHL-Katalog.
- Für Paket und Brief gibt es eine Schnell-Eingabe mit drei Zeilen: Name / Straße Hausnummer / PLZ Ort. Die Werte werden automatisch auf die Einzelfelder verteilt.
- Das gemeinsame Adressbuch kann Empfänger direkt in Paket oder Brief übernehmen.
- Products-API-Endpunkt für INTERNETMARKE korrigiert auf `https://api-eu.dhl.com/post/de/information/products/v1/products?profile=IM-PARTNER&shortVersion=true`.
- Die Oberfläche enthält eine kostenfreie Diagnose für API-Healthcheck, Products API, Portokassen-Token und Benutzerprofil. Es wird dabei keine Marke gekauft oder Portokasse belastet.
- INTERNETMARKE: Portokassen-Anmeldung über `POST /user` und Profilprüfung bleiben unverändert.
- Die Briefmarkenerstellung zeigt Fortschritt, Erfolg und Fehler direkt im Briefmarken-Bereich an.
- Für Briefempfänger kann zwischen Straßenadresse und Postfach / Zustellzeile gewählt werden.
- Lokales Absenderprofil und Empfänger-Adressbuch unter `/data` bleiben erhalten.
- API-Schlüssel werden ausschließlich über die Home-Assistant-App-Konfiguration eingelesen und niemals an den Browser zurückgegeben.
- Keine externen Python-Abhängigkeiten.

## Einrichtung

In Home Assistant unter **Einstellungen > Apps > Post & DHL Frankierung > Konfiguration**:

- `dhl_private_api_key`: API Key der App mit **Parcel DE Private Shipping**.
- `internetmarke_api_key`: API Key / Client-ID der INTERNETMARKE-App.
- `internetmarke_api_secret`: API Secret / Client-Secret der INTERNETMARKE-App.
- `portokasse_username`: Benutzername/E-Mail der Portokasse.
- `portokasse_password`: Passwort der Portokasse.

Bei der ersten INTERNETMARKE-Tokenanforderung kann die Deutsche Post zusätzlich verlangen, dass die Geschäftsanwendung in der Portokasse unter **Meine Daten > Geschäftsanwendungen** einmalig freigegeben wird.


## Design
Die Oberfläche ist als eigenständiger Versand-/Frankierarbeitsplatz gestaltet: gelber Post-/DHL-Kopf, helle Formularflächen, klare Arbeitsreiter und versandtypische Produktkarten statt des dunklen Dashboard-Kartenstils anderer Apps.
