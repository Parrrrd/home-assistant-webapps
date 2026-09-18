## 0.1.41 — 18.09.2026, 21:12 CEST

- Übernahme in das bereinigte GitHub-Repository; öffnet ausschließlich über die direkte Browser-Adresse.

# 0.1.40

- Sicherheitskorrektur für Briefmarken: Die DHL-Produktnummer wird nicht mehr als vermeintliche Briefart interpretiert. Sichtbar und kaufbar sind ausschließlich live gelesene Produkte, deren exakte DHL-Bezeichnung, Inlandseigenschaft, Preis und Gewichtsgrenze gemeinsam zur gewünschten Briefart passen.
- Einschreiben-/Zusatzleistungsvarianten (z. B. Standardbrief Integral + Einschreiben Einwurf) werden zuverlässig verworfen. Direkt vor dem Kauf wird die Auswahl erneut gegen den geprüften Live-Katalog abgeglichen; eine alte oder unbestätigte Auswahl wird abgelehnt.

# 0.1.39

- Briefmarken zeigen ausschließlich nationale Produkte. Internationale Varianten werden nicht mehr durch den Namensteil `national` in `international` fälschlich akzeptiert.
- Die Auswahl enthält wieder die sechs gewünschten Briefarten: Standard-, Kompakt-, Groß- und Maxibrief sowie Warensendung bis 1 kg und bis 2 kg. Auch die DHL-Bezeichnung „Bücher- und Warensendung“ wird erkannt.

# 0.1.38

- Die sechs Briefprodukte werden zusätzlich über ihre aktuellen DHL-Katalognamen erkannt. Dadurch bleiben Standard-, Kompakt-, Groß- und Maxibrief sowie beide Warensendungen auch dann kaufbar, wenn DHL mit einer neuen Preisliste andere Produktnummern liefert.
- Für den Kauf wird weiterhin ausschließlich der live aus dem DHL-Katalog gelesene Produktcode verwendet.

# 0.1.37

- Briefprodukte werden jetzt ausschließlich aus einer DHL-Products-API-Antwort übernommen, die tatsächlich kaufbare Produktcodes und Preise enthält. Der dokumentierte DHL-Pfad hat Vorrang; eine bloße HTTP-200-Antwort ohne verwertbare Preise reicht nicht mehr aus.
- Preisfelder werden robust aus den von DHL dokumentierten Schreibweisen gelesen. Fehlt ein Preisfeld ausnahmsweise, greift eine geprüfte nationale Preisreserve nur für einen real von DHL gelieferten Produktcode.
- Die sechs Briefarten können nicht mehr als reine Bildschirm-Ersatzprodukte mit ungültigem Produktcode erscheinen. Dadurch ist der Kaufweg identisch zur sichtbaren Auswahl.
- Preisreserve Stand August 2026: Standardbrief 0,95 €, Kompaktbrief 1,10 €, Großbrief 1,80 €, Maxibrief 2,90 €, Warensendung bis 1 kg 2,70 €, mit Gewichtszuschlag bis 2 kg 3,55 €.

# 0.1.36

- Portokassen-Guthaben wird zusätzlich aus der Anmeldeantwort gelesen, falls es im Benutzerprofil nicht enthalten ist.

# 0.1.35

- „Drucken“ öffnet für gespeicherte INTERNETMARKEN eine App-eigene Druckansicht und ruft den Systemdruckdialog auf; „PDF öffnen“ bleibt unverändert eine Vorschau.
- Portokassen-Guthaben im Briefmarkenbereich ergänzt, inklusive manueller Aktualisierung über die lesende Profilabfrage.

# 0.1.34

- Druckzeilen der INTERNETMARKE bereinigt: Kein leeres zweites Adressfeld mehr beim Absender und Adresszusätze stehen unter Name/Firma.

# 0.1.33

- INTERNETMARKE-Kaufaufruf korrigiert: `validate` wird nicht mehr zusammen mit `directCheckout=true` gesendet. Das behebt die DHL-Ablehnung `invalidCombination` / `PCF-A1031`.

# 0.1.32

- Gesamtpreis (`total`) für den INTERNETMARKE-PDF-Checkout aus dem offiziellen Brutto-Produktpreis in Cent ergänzt. Das behebt die DHL-Ablehnung `total: must not be null` / `PCF-A1033`.

# 0.1.31

- INTERNETMARKE-PDF-Checkout verwendet jetzt den erforderlichen Typ `AppShoppingCartPDFPosition` einschließlich PDF-Positionierung. Das behebt die DHL-Ablehnung `InvalidTypeId` / `PCF-A1034` unabhängig von der gewählten Empfänger-Adressart.

# 0.1.30

- Oberfläche für Paket und Brief als klarer Arbeitsablauf überarbeitet.
- Absenderauswahl und -verwaltung als lesbare Adresskarten gestaltet.
- Neuer Empfänger-Modus „Postfach / Zustellzeile“ für Adressen ohne Straße und Hausnummer.
- Status- und Fehlermeldungen stehen vor der Vorgangshistorie.
