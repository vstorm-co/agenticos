---
source_sha: "8f017c44c86c"
---

# Integrierte Integrationen { #built-in-integrations }

Unter **Einstellungen → Vault → Verbundene Konten** verbinden Sie ein Konto. Jedes Google-, Microsoft- und Slack-Produkt ist eine eigene Capability in der **Toolbox** eines Agenten, mit eigener Kontowahl und einzelnen Werkzeugschaltern. Die Integrationen nutzen Anbieter-APIs direkt. Anbieter-MCP-Server, Google Workspace MCP Preview und eine Microsoft-Copilot-Lizenz sind nicht erforderlich.

## Ein Konto einrichten { #set-up-an-account }

Der Assistent zeigt die genaue Callback-URL dieser Installation, den Konsolenlink und angeforderte Berechtigungen. Wählen Sie zuerst Produkte. Standard ist Lesezugriff; Schreibrechte werden ausdrücklich aktiviert. Ein Administrator speichert eine organisationsweit sichtbare OAuth-App im Vault; Mitglieder verwenden sie für ihre persönlichen Konten. Bei mehreren App-Zugangsdaten muss der Administrator die Zuordnung klären.

Google: Cloud-Projekt anlegen, die aufgeführten APIs aktivieren (`gcloud services enable` steht im Assistenten), Zustimmungsbildschirm konfigurieren und einen OAuth-Client **Web application** erstellen. Callback exakt kopieren und `google_oauth_app` speichern. Internal gilt für die Workspace-Organisation des Projekts. Bei External/Testing können Refresh-Tokens nach sieben Tagen ablaufen. Der normale API-Zugriff braucht weder einen AI-powered-agent-Client noch gehostete MCP-APIs.

Microsoft: Entra-App registrieren, Kontotypen und Tenant wählen, Web-Weiterleitung und angezeigte delegierte Graph-Rechte hinzufügen und `microsoft_oauth_app` speichern. Private und geschäftliche Konten funktionieren nur, soweit das jeweilige Graph-Produkt sie unterstützt; Teams benötigt ein Geschäftskonto. Die Tenant-Richtlinie kann Administratorzustimmung verlangen.

Slack: **Slack-App erstellen** öffnet ein Manifest mit Callback und Benutzer-Leserechten. Für Schreibzugriff die Rechte ergänzen und neu installieren/autorisieren. `slack_oauth_app` speichern und Zustimmung abschließen. Eine bestehende Channel-Bot-App kann durch Benutzerrechte und Callback ergänzt werden. Workspace-App-Limits und Administratorfreigaben bleiben bestehen. **Agents → MCP Server** wird nur für den separat verwendeten gehosteten Slack-MCP-Server benötigt.

## Alternativen zu OAuth { #alternatives-to-oauth }

Die Wahl der Anwendungsidentität erfordert Bearbeitungszugriff auf ihren Vault-Zugang, auch bei persönlichen Konten. Lesezugriff auf einen geteilten Zugang erlaubt keine Identitätsübernahme. Persönliche Konten prüfen diesen Bearbeitungszugriff vor jedem Tokenaustausch erneut.

Google unterstützt `gcp_service_account` aus dem Vault und ein Subject für die domänenweite Workspace-Delegierung. Der Workspace-Administrator muss die angezeigten Scopes freigeben. Ein normales Dienstkonto erreicht nur freigegebene Ressourcen und wird nicht zu einem persönlichen Gmail-Konto.

Microsoft unterstützt ein `entra_app`-Client-Geheimnis und Anwendungsrechte mit Administratorzustimmung. Für Mail/Kalender das Postfach angeben, für Teams die Verzeichnisobjekt-ID des Benutzers, damit Erwähnungen ohne umfassenden Verzeichniszugriff erkannt werden. Excel-Arbeitsmappen erfordern delegiertes OAuth. Normale Teams-Nachrichten können nicht mit Anwendungsrechten gesendet werden; dafür delegiertes OAuth verwenden. Der Assistent zeigt die passenden delegierten oder Anwendungsrechte.

Microsoft-Anwendungskonten speichern nur die vom Tenant zurückgegebenen Graph-Rollen für die ausgewählten Produkte. Der schreibgeschützte Modus blockiert Schreibvorgänge zusätzlich lokal, auch wenn Entra eine umfassendere Rolle erteilt hat. Jede Erneuerung prüft die gespeicherten Rollen erneut; nach geänderter Zustimmung das Konto neu verbinden.

Diese Einrichtung benötigt einen lesbaren Graph-Rollen-Claim im Token des festen Microsoft-Token-Endpunkts. Opake oder verschlüsselte Anwendungstoken werden mit einem Hinweis auf delegiertes OAuth abgelehnt; AgenticOS fordert keine verzeichnisweiten Rechte zur Prüfung der Zustimmung an. Der Claim ist Konfigurationsmetadatum und authentifiziert keinen Plattformbenutzer; Microsoft Graph validiert das Bearer-Token.

Slack akzeptiert vorhandene Benutzertokens `xoxp-` und Bottokens `xoxb-`. Ein Bot schreibt als App, kann aber keine benutzerexklusive Suche verwenden. Tatsächliche Scopes werden vor jeder Operation geprüft. Tokens und Schlüssel bleiben verschlüsselt im Vault, niemals in der Agentenspezifikation.

Vor dem Speichern eines Slack-Triggers, Watches oder einer Wissensquelle prüft AgenticOS den Verlaufzugriff jeder ausgewählten Unterhaltung. So werden die passenden Rechte für öffentliche/private Kanäle und Direkt-/Gruppennachrichten sowie die Mitgliedschaft ohne zusätzliche Verzeichnisrechte geprüft. Unlesbare Unterhaltungen werden bei der Einrichtung abgelehnt.

**IMAP** ist eine getrennte, nur lesende Mailverbindung: Host, Port mit geprüftem TLS, Benutzername, App-Passwort und fester Ordner. Der Betreiber muss den exakten Host in `MIRAGE_ALLOWED_HOSTS` zulassen. Der installierte Mirage-Mailclient wird wiederverwendet. Microsoft-365-IMAP mit Basic Auth wird hier nicht als OAuth-Alternative angeboten.

## Was ein Agent tun darf { #choose-what-an-agent-can-do }

Google: Gmail (Suche, Lesen, Labels, Entwurf/Versand), Calendar (Termine und Verfügbarkeit), Drive (Suche, Metadaten, Lesen, Upload und Kopien), Docs, Sheets und Slides (Lesen/Erstellen/Ändern). Sheets bietet Bereiche, angehängte Zeilen und Zelländerungen.

Microsoft: Outlook-Mail, Calendar, OneDrive/SharePoint-Dateien, Excel, Word-Dokumente sowie Teams-Chats und -Kanäle. Slack bietet Suche, eigene Erwähnungen, Verlauf/Threads, Kanäle/Benutzer, Nachschlagen, Beiträge/Antworten, DMs und Reaktionen. IMAP liest und sucht, ohne Nachrichten als gelesen zu markieren.

**personal** wählt das Konto der aktuellen Person nach exaktem Namen, Label oder Adresse. Ein leerer Name funktioniert nur bei genau einem Treffer. Persönliche Werkzeuge benötigen einen privaten Chat und aktive Organisationsmitgliedschaft. Für gemeinsame Automatisierung **organization** und Verbindungs-ID wählen. Ein Agent leiht kein Konto eines anderen Mitglieds aus.

Jeder Schreibzugriff in Agentenläufen benötigt menschliche Freigabe, auch bei einer schwächeren Werkzeugüberschreibung. Deaktivierte Werkzeuge werden nicht angeboten. Workflows nutzen dieselben Operationen als `integration.<product>.<operation>` mit denselben Konto- und Transportprüfungen. Schreibzugriffe werden nicht automatisch wiederholt; für menschliche Prüfung im Workflow davor einen Approval-Knoten setzen.

Dateiknoten nehmen Base64-Inhalt an, niemals einen lokalen Serverpfad. Word erstellt `.docx` aus Titel und Absätzen. Upload/Download sind auf 20 MB begrenzt, JSON auf 2 MB und extrahierter Text auf 100.000 Zeichen. Ein fehlgeschlagener Schreibzugriff kann bereits angekommen sein: vor erneutem Senden den Anbieter prüfen.

Die Veröffentlichung einer Organisationskontobindung prüft die Bereiche jedes aktivierten Werkzeugs. Bei einem reinen Lesekonto Schreibwerkzeuge vor der Veröffentlichung deaktivieren oder das Konto mit Schreibrechten neu verbinden.

## Wissen, Trigger und Watches { #knowledge-triggers-and-watches }

Drive- und SharePoint-Quellen können dieselbe Organisationsverbindung statt separater Zugangsdaten verwenden. OneDrive nutzt den SharePoint-Connector mit gewähltem Laufwerk/Ordner. Slack indexiert nur gewählte Kanäle und Threads. Jede Synchronisierung prüft die Autorisierung erneut; gemeinsame Wissensquellen verwenden keine privaten Mitgliederkonten.

Routine-Trigger verwenden die bestehende transaktionale Warteschlange, Deduplizierung und genehmigte Quellenrichtlinie. Gmail-/Outlook-Filter, Terminvorlauf und Dateiänderungen funktionieren mit nativen Konten. Slack ergänzt Nachrichten, Erwähnungen und DMs; Teams Nachrichten/Erwähnungen; IMAP neue Mail. Sheets verfolgt **angehängte Zeilen** einer gewählten Tabelle und eines Blatts. Die Basis ist die letzte belegte Zeile im Spaltenbereich A:ZZ; Einfügen/Löschen und Änderungen bestehender Zeilen sind keine Anhänge.

Eine Watch wählt eine persönliche Verbindung und ein Produkt und erhält nur ein festes, lesendes Änderungswerkzeug. Das Produkt zuerst am Agenten aktivieren. Slack-Unterhaltungen und delegierte Teams-Chats werden in der Capability gewählt. Teams-Kanäle heißen `channel/team-id/channel-id`; eine Teams-App-Watch ohne Unterhaltungen liest alle Chats des konfigurierten Benutzers.

Jede Watch hat einen eigenen dauerhaften Cursor, der erst nach erfolgreicher Verarbeitung fortschreitet. Neue/zurückgesetzte Cursor starten still. Gmail nutzt History-IDs, Outlook/Kalender Anbieter-Cursor, Slack Zeitstempel pro Unterhaltung und IMAP UIDVALIDITY/UID. Delegierte Teams-Chats nutzen `lastModifiedDateTime`, Kanal- und Anwendungsfeeds Graph Delta. Bei einem zu großen Rückstand die Quelle eingrenzen.

Siehe [Capabilities](reference/capabilities.md), [Trigger](triggers.md), [Governance und Watches](governance.md#proactive-work) und [MCP](mcp.md).

Vergeben Sie beim Verbinden ein Label wie Arbeit; verwenden Sie es für das entsprechende Konto jeder Person.

Native Trigger benötigen beim Erstellen über die API `connection_id`. Filteränderungen prüfen Konto, Rechte und Gesprächsauswahl erneut. Jede eigene Slack-/Teams-Gesprächsauswahl hat einen eigenen Cursor und versorgt nur die zugehörigen Trigger; eine Auswahl kann bis zu 20 Gespräche umfassen.

## Odoo { #odoo }

Verbinde Odoo 19+ über JSON-2 mit HTTPS-Ursprung, Datenbankname und API-Schlüssel eines Geschäftsbenutzers. Der Betreiber muss den genauen Host in `ODOO_ALLOWED_HOSTS` freigeben; Pfade, Weiterleitungen und eigene Ports werden abgelehnt. Odoo Online benötigt einen Custom-Tarif für externe APIs. Installiere die benötigten Module und beschränke die Odoo-Zugriffsrechte und Datensatzregeln des Benutzers. Schlüssel laufen ab: nach Rotation erneut verbinden. Schreibzugriff ist optional; jeder Agent-Schreibzugriff braucht eine Genehmigung.

Capabilities decken Kontakte, CRM, Verkauf, Rechnungen, Lager und Projekte ab. Sie bieten Feldmetadaten, begrenzte Suche/Lesezugriffe und getrennte Werkzeuge zum Erstellen/Ändern, soweit unterstützt. Lagerbestände sind schreibgeschützt; Lageroperationen nutzen Transfers und Bewegungen. Werkzeuge und Workflow-Knoten verwenden dasselbe Konto und denselben JSON-2-Adapter. Beliebige Modelle, Methoden und benutzerdefinierter Kontext sind nicht erlaubt.

Watches und Routine-Trigger lesen neue/geänderte Datensätze ihres Geschäftsbereichs. Jedes Modell hat einen eigenen `(write_date, id)`-Cursor; der erste Abruf setzt eine stille Basis. Weitere Abrufe lesen bis zu 100 Datensätze je Modell und behalten den Rückstand. Löschungen sind keine Ereignisse. Odoo-Zeitstempel haben Sekundenauflösung; mehrere Änderungen eines Datensatzes innerhalb einer Sekunde können zusammenfallen. Wissenssynchronisation indexiert nur ausgewählte Felder über ein Organisationskonto; begrenzte Listen löschen keine ungesehenen Dokumente.

Verkaufsbestätigung, Rechnungsbuchung sowie Bestätigung/Reservierung/Validierung von Transfers haben eigene genehmigungspflichtige Werkzeuge. Nutze diese Geschäftsaktionen statt Statusfelder zu schreiben. Aktionen können einen in Odoo abzuschließenden Assistenten zurückgeben; lies den Datensatz vor einer Erfolgsmeldung erneut. Rechnungen erfordern einen expliziten `move_type` (Kunde, Lieferant, Gutschrift oder Beleg). Skalare Felder und Verknüpfen/Ersetzen/Leeren von Beziehungs-IDs werden unterstützt. Erstelle oder ändere zugehörige Datensätze mit deren eigenen Werkzeugen; verschachtelte ORM-Mutationen und JSON-Objektwerte werden abgelehnt.

Der Odoo-Cursor behält außerdem einen deduplizierten Snapshot seiner Zeitstempelgrenze, damit eine spätere Änderung an einem Datensatz mit kleinerer ID erneut gelesen wird. Fingerabdrücke enthalten die zurückgegebene ID, den Anzeigenamen und das Schreibdatum. Snapshots sind auf 2000 Datensätze je Modell/Zeitstempel begrenzt; bei Überschreitung Massenänderungen aufteilen.

## Exchange Online { #exchange-online }

Outlook mail und Outlook Calendar verbinden Microsoft Exchange Online über Microsoft Graph. Nutze den Microsoft-Assistenten mit delegiertem OAuth oder ein Entra-Anwendungskonto mit Administratorzustimmung und Zielpostfach. Ein separates IMAP-Passwort oder eine Work-IQ-Lizenz ist nicht erforderlich. Dieser Weg unterstützt Exchange Online, nicht lokales Exchange oder EWS.
