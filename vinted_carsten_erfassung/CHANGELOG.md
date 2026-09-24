# Carstens Vinted Importeur – Versionsverlauf

## 0.1.4 — 25.09.2026, 01:29 CEST

- Google-Drive-Zugangsdaten werden jetzt über Home Assistants app-eigenen `addon_config`-Ordner eingebunden und innerhalb der App ausschließlich aus `/config` gelesen.
- Der Standardpfad lautet `/config/drive-service-account.json`; der bisherige Standardwert `/data/drive-service-account.json` wird für bestehende Installationen automatisch auf den neuen Pfad umgeleitet.
- Die persistente `/data`-Outbox, wartende Abgaben und der automatische Wiederholungsversuch bleiben unverändert erhalten; die Einrichtungsanleitung wurde auf den sicheren App-Konfigurationsordner aktualisiert.

## 0.1.3 — 24.09.2026, 21:47 CEST

- Die Fotoauswahl wurde auf einen einzigen Button „Foto hinzufügen“ vereinfacht; iPhone/iPad können darüber die systemeigene Auswahl für Fotomediathek, Kamera oder Dateien öffnen.
- Neue Kamera- oder Mediathek-Auswahlen werden zu den bereits gewählten Fotos hinzugefügt, statt sie zu ersetzen.
- Jedes ausgewählte Foto kann vor dem Absenden einzeln wieder entfernt werden.

## 0.1.2 — 24.09.2026, 21:21 CEST

- Korrigiert die Fotoauswahl auf mobilen Browsern: Bereits gewählte oder aufgenommene Fotos bleiben bei weiteren Auswahlen erhalten.
- „Fotos aufnehmen“ kann beliebig oft nacheinander verwendet werden; jedes neue Kamerafoto wird zur bestehenden Auswahl hinzugefügt.
- „Aus Mediathek auswählen“ unterstützt weiterhin die Mehrfachauswahl und zusätzliche spätere Auswahlen ohne Überschreiben.

## 0.1.1 — 24.09.2026, 21:21 CEST

- Die Oberfläche heißt jetzt „Carstens Vinted Importeur“ und wurde für die mobile Erfassung optisch geglättet.
- Der erklärende Pflichtfeld-Hinweis sowie Titelbild- und Reihenfolge-Steuerung wurden entfernt.
- Fotos können wahlweise direkt aufgenommen oder als Mehrfachauswahl aus der Mediathek hinzugefügt werden; HEIC/HEIF wird ebenfalls akzeptiert.
- Die Verkaufsautomatik ist standardmäßig aktiviert: Neu-Einstellen alle 7 Tage und spätere Preisreduzierung sind vorausgewählt.
- Die drei Felder der Preisreduzierung sind auch auf schmalen Displays sauber ausgerichtet.

## 0.1.0 — 24.09.2026, 20:15 CEST

- Erste mobile Erfassung für Fotos und optionale Vinted-Verkaufsdaten mit lokaler, ausfallsicherer `.vintake.zip`-Outbox und Google-Drive-Übergabe.
