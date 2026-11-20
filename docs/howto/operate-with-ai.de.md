---
source_sha: "d2ccce975127"
---

# AgenticOS mit einem KI-Client bedienen { #operate-agenticos-with-an-ai-client }

Das [AgenticOS-Plugin](https://github.com/vstorm-co/agenticos/tree/main/plugins/agenticos)
ergänzt die MCP-Werkzeuge um Verfahren für Bereitstellung, Abhängigkeiten,
Lösungen und getestete Agenten. Es handelt mit den Rechten des verbundenen
Mitglieds in einer Organisation. Die Installation benötigt ein Terminal oder CI.

## Installieren und verbinden { #install-and-connect }

```bash
claude plugin marketplace add vstorm-co/agenticos
claude plugin install agenticos@agenticos
claude mcp add --transport http agenticos https://<api-host>/mcp
```

Schließen Sie OAuth im Browser ab und wählen Sie Organisation und Scopes.
Einstellungen → MCP-Clients zeigt die Befehle für jeden Client. Das Plugin
enthält keine feste Serveradresse. [MCP](../mcp.md) beschreibt Zugriff und Freigaben.

Die Basis wurde mit 1.82.2 getestet. Neue Werkzeuge für Abhängigkeiten, Qualität
und Pakete verwenden MCP-Vertrag 1, den `get_platform_context` meldet. Ein älterer
Server bietet weiterhin seine vorhandenen Werkzeuge an. Der Client muss Funktionen
und Scopes ermitteln; Versionsnummern gewähren keine Rechte. Assistentenrouten
benötigen OAuth. Normale Organisationsschlüssel bleiben auf die öffentliche API begrenzt.

## Eine Lösung erstellen und freigeben { #build-and-release-a-solution }

Beschreiben Sie Ergebnis, Benutzer, Quellen und erlaubte Auswirkungen in eigenen
Worten. Der Client ermittelt Capabilities, Workflow-Knoten, Verbindungen und
vorhandene Ressourcen vor dem Entwurf. Support, Repository-Arbeit und Onboarding
sind Beispiele und keine abschließende Liste unterstützter Anwendungsfälle.

Modellprofile können vorhandene Vault-IDs verwenden. `list_secret_references`
zeigt nur zugängliche Namen, IDs, Arten und Zwecke, keine Werte oder Hinweise.
Die Endpunktsuche ermittelt lokale Embedding-Dienste. `get_setup_link` übergibt
Geheimniseingabe und OAuth-Zustimmung an die eigene Konsolensitzung der Person.
Fügen Sie weder Zugangsdaten noch OAuth-Callback-Adressen in Unterhaltung oder Paket ein.

`plan_solution` validiert ein Manifest und liefert Hash und benötigte Rechte.
`install_solution` benötigt diesen Hash, das genaue Manifest und einen
Installationsschlüssel. Es erstellt private Ressourcen und den Installationsbeleg
in einer Transaktion, ohne Veröffentlichung, Ausführung, Indexierung oder Zeitplan.
Gleiche Wiederholungen liefern den Beleg; ein anderes Manifest für denselben
Benutzer, dieselbe Organisation und denselben Schlüssel wird abgelehnt. Eine
weitere Kopie benötigt einen anderen Schlüssel und konfliktfreie Ressourcennamen.

Logische Referenzen verbinden Agenten mit neuem Context, Skills und Wissen.
Die Workflow-Vorbereitung kann eine Tabelle mit Platzhalter enthalten. Externe
Modelle, Embeddings und Verbindungen bleiben explizite IDs dieser Bereitstellung.
Lesen Sie Ressourcen nach der Installation erneut: Der Beleg ist Historie, kein
Nachweis gegen spätere Änderungen oder Löschung. Bearbeiten Sie installierte
Ressourcen über ihre normalen Operationen; die Installation überschreibt sie
nicht als Paketaktualisierung.

Erstellen Sie für eine Freigabe ein Dataset mit bewertbaren Fällen, schätzen und
starten Sie Evals, prüfen Sie das Ergebnis und veröffentlichen Sie dann eine
Version und promoten eine Umgebung. Fixieren Sie Produktion vor der Veröffentlichung,
wenn sie der neuesten Version folgt und Staging nötig ist. Testverbindungen,
Gates und Override-Regeln gelten weiter. Ein Rollback setzt die Umgebung auf
eine vorhandene Version zurück und bewahrt die Historie. Siehe [Umgebungen](../environments.md).

## Bereitstellung oder Fork prüfen { #verify-a-deployment-or-fork }

Der Bereitstellungs-Skill nutzt das bestehende [Einzelhost-Verfahren](../deploy.md),
Bootstrap und Doctor. Der Entwicklungs-Skill verwaltet den Image-Präfix des Forks
und Upstream-Update-PRs. Plattform-MCP gewährt keine SSH- oder Cloud-Berechtigung.

Für eine isolierte lokale Prüfung aus einem Checkout:

```bash
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0
# Den angezeigten Plan ausführen und den Bericht außerhalb des Teststacks speichern:
uv run --directory backend python ../scripts/agenticos_smoke.py --version 1.84.0 --run --report /tmp/agenticos-smoke.json
```

Der Test nutzt veröffentlichte Images, ein eigenes Compose-Projekt, generierte
lokale Zugangsdaten und ein deterministisches lokales Modell. Er initialisiert
eine Organisation, prüft Konsole und API und schließt einen Agentenlauf über einen
echten MCP-Client ab. Danach entfernt er seine Container und Volumes. Das prüft
die Plattformverbindung, nicht Modellqualität, einen bezahlten Anbieter, externes
DNS oder produktives TLS.
