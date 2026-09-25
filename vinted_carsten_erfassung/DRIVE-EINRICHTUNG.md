# Google Drive einrichten

Die App speichert jede Abgabe zuerst vollständig in ihrem persistenten `/data/outbox`-Ordner. Ohne Drive-Zugang gehen keine Fotos verloren; die Anzeige lautet dann **„Gespeichert – Übergabe wartet“** und der Hintergrunddienst versucht es später erneut.

Für die Übergabe in **„Vinted Carsten – Eingang“** wird der bereits für Kleinanzeigen und den primären Kicktipp-Bot vorhandene Google-Service-Account wiederverwendet. Es wird keine zweite Schlüsseldatei benötigt.

1. Der vorhandene Service Account `kleinanzeigen@gen-lang-client-0177267091.iam.gserviceaccount.com` muss als Bearbeiter für den Zielordner **„Vinted Carsten – Eingang“** freigegeben sein.
2. Die bestehende lokale Schlüsseldatei bleibt unverändert unter `/share/Kleinanzeigen/google-drive-service-account.json`. Carstens App bindet `/share` ausschließlich lesend ein.
3. In den Home-Assistant-Optionen der App die Ordner-ID von `Vinted Carsten – Eingang` in `drive_folder_id` eintragen.
4. `drive_service_account_file` auf `/share/Kleinanzeigen/google-drive-service-account.json` belassen. Ein noch gespeicherter alter Standardwert `/data/drive-service-account.json` oder `/config/drive-service-account.json` wird automatisch auf die vorhandene gemeinsame Datei umgeleitet, sofern keine eigene Datei unter `/config` existiert.
5. Danach die App neu starten. Bereits wartende Pakete in `/data/outbox` bleiben erhalten und werden automatisch erneut übertragen.

Die Service-Account-Datei darf niemals in ein ZIP, nach GitHub oder in einen Chat-Upload gelangen. Die Anwendung lädt ausschließlich die jeweiligen `carsten-vinted-YYYYMMDD-HHMMSS-<id>.vintake.zip`-Pakete in den konfigurierten Zielordner und lässt die lokale Outbox auch nach Erfolg als nachvollziehbare Kopie erhalten.
