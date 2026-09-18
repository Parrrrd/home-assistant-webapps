# Lieferketten-Sicherheit

Dieses private Repository enthält ausschließlich versionierten Quellcode. Betriebsdaten,
Home-Assistant-Optionen, Zugangsdaten, Sitzungen, Bilder und Sicherungen bleiben lokal.

## Schutzmaßnahmen

- GitHub Actions sind auf vollständige Commit-IDs festgeschrieben. Dependabot meldet neue
  Action-Versionen wöchentlich zur gezielten Prüfung.
- Workflows starten mit keinen Rechten. Jeder Job erhält nur die Rechte, die er tatsächlich
  benötigt; Tests erhalten nur Lesezugriff.
- Der Google-Drive-Import akzeptiert nur ein ZIP aus dem freigegebenen Codeeingang. Er prüft
  Elternordner, Dateityp, Größe, ZIP-Integrität, Google-Drive-Prüfsumme, erwarteten Namen,
  Ordnerstruktur, App-Slug, Versionsnummer und den Repository-Sicherheitscheck.
- Der Google-Servicezugang ist auf `drive.readonly` beschränkt. Sein JSON-Schlüssel liegt nur
  als GitHub-Secret. Der Apps-Script-Token ist auf dieses eine Repository begrenzt.
- Neue Home-Assistant-Images entstehen erst nach Tests und Sicherheitsprüfung. Der Updater
  übernimmt nur höhere, gültige Versionen und behält die lokalen App-Daten bei.

## Falls ein Zugang verloren geht

1. Den GitHub-Token sofort widerrufen.
2. Das GitHub-Secret für den Google-Servicezugang löschen oder durch einen neuen Schlüssel ersetzen.
3. Den Google-Drive-Zugriff des Servicekontos entfernen.
4. Den Apps-Script-Trigger deaktivieren und die letzten GitHub-Actions prüfen.
