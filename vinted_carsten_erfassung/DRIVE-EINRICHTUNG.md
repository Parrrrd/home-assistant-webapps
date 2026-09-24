# Google Drive einrichten

Die App speichert jede Abgabe zuerst vollständig in ihrem persistenten `/data/outbox`-Ordner. Ohne Drive-Zugang gehen keine Fotos verloren; die Anzeige lautet dann **„Gespeichert – Übergabe wartet“** und der Hintergrunddienst versucht es später erneut.

Für die Übergabe in **„Vinted Carsten – Eingang“**:

1. Eine Google-Service-Account-Datei mit ausschließlich den nötigen Drive-Rechten erzeugen und ihren Account als Bearbeiter dieses Zielordners freigeben.
2. Die JSON-Datei ausschließlich im app-eigenen Home-Assistant-Konfigurationsordner ablegen. Bei der lokalen Installation lautet der Pfad außerhalb der App `/addon_configs/local_vinted_carsten_erfassung/drive-service-account.json`. Home Assistant bindet diesen Ordner innerhalb der App schreibgeschützt als `/config` ein.
3. In den Home-Assistant-Optionen der App die Ordner-ID von `Vinted Carsten – Eingang` in `drive_folder_id` eintragen. Die ID ist der Teil hinter `folders/` in der Google-Drive-Ordneradresse.
4. `drive_service_account_file` auf `/config/drive-service-account.json` belassen. Ein noch gespeicherter alter Standardwert `/data/drive-service-account.json` wird aus Kompatibilitätsgründen automatisch auf den neuen `/config`-Pfad umgeleitet.
5. Danach die App neu starten. Bereits wartende Pakete in `/data/outbox` bleiben erhalten und werden automatisch erneut übertragen.

Die Service-Account-Datei darf niemals in ein ZIP, nach GitHub oder in einen Chat-Upload gelangen. Die Anwendung braucht keine ChatGPT- oder Browser-Drive-Verbindung. Sie lädt ausschließlich die jeweiligen `carsten-vinted-YYYYMMDD-HHMMSS-<id>.vintake.zip`-Pakete hoch und lässt die lokale Outbox auch nach Erfolg als nachvollziehbare Kopie erhalten.
