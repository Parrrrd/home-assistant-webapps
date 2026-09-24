# Google Drive einrichten

Die App speichert jede Abgabe zuerst vollständig in ihrem persistenten `/data/outbox`-Ordner. Ohne Drive-Zugang gehen keine Fotos verloren; die Anzeige lautet dann **„Gespeichert – Übergabe wartet“** und der Hintergrunddienst versucht es später erneut.

Für die Übergabe in **„Vinted Carsten – Eingang“**:

1. Eine Google-Service-Account-Datei mit ausschließlich den nötigen Drive-Rechten erzeugen und ihren Account als Bearbeiter dieses Zielordners freigeben.
2. Die JSON-Datei ausschließlich lokal als `/data/drive-service-account.json` in den Datenbereich dieser App legen (Dateirechte: nur Besitzer lesbar). Sie darf niemals in ein ZIP, GitHub oder einen Chat-Upload.
3. In den Home-Assistant-Optionen der App die Ordner-ID von `Vinted Carsten – Eingang` in `drive_folder_id` eintragen. Die ID ist der Teil hinter `folders/` in der Google-Drive-Ordneradresse.
4. `drive_service_account_file` nur ändern, wenn die Datei weiterhin unter `/data` liegt. Danach die App neu starten.

Die Anwendung braucht keine ChatGPT- oder Browser-Drive-Verbindung. Sie lädt ausschließlich die jeweiligen `carsten-vinted-YYYYMMDD-HHMMSS-<id>.vintake.zip`-Pakete hoch und lässt die lokale Outbox auch nach Erfolg als nachvollziehbare Kopie erhalten.
