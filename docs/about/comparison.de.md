---
source_sha: "b0bf2e34ec50"
title: "AgenticOS vergleichen"
description: "Wie AgenticOS im Vergleich zu Assistenten-Apps, Agent-Buildern, Teammate-Diensten, gelieferten Plattformen und Coding-Agents abschneidet."
---

# AgenticOS vergleichen { #compare-agenticos }

Die meisten Produkte in diesem Bereich sind eines von fünf Dingen: eine Assistenten-App, ein Agent-Builder, ein Teammate-Dienst, eine gelieferte Enterprise-Plattform oder ein Coding-Agent. AgenticOS ist eine Plattform für die Agents eines Unternehmens, die Sie selbst betreiben. Diese Leitfäden zeigen, wo jede Option passt und was AgenticOS ergänzt.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 25. September 2026. AgenticOS-Basis: v0.0.504. Nächste Prüfung bis 25. Oktober 2026 oder früher, wenn ein Anbieter das in einem Leitfaden beschriebene Angebot ändert. Jeder Leitfaden nennt seine Quellen. Für diese Leitfäden wurde kein Konto eines Mitbewerbers genutzt.

## Den Leitfaden für Ihre Entscheidung wählen { #pick-the-guide-for-your-decision }

| Sie wägen ab | Produkte | Leitfaden |
| --- | --- | --- |
| Einen Chat-Assistenten für das Unternehmen oder Agents, die Ihrer Organisation gehören | Claude Team und Enterprise, ChatGPT Business und Enterprise | [Claude](claude-apps.md) · [ChatGPT](chatgpt.md) |
| Einen Builder in der Cloud-Suite eines Anbieters | Microsoft Copilot Studio, Google Gemini Enterprise | [Copilot Studio](copilot-studio.md) · [Gemini Enterprise](gemini-enterprise.md) |
| Einen selbst gehosteten Builder oder ein Automatisierungswerkzeug | Dify, n8n | [Dify](dify.md) · [n8n](n8n.md) |
| Einen Teammate-Dienst in Slack oder Teams | Viktor | [Viktor](viktor.md) |
| Eine gelieferte Enterprise-Plattform | Wonderful | [Wonderful](wonderful.md) |
| Einen Coding-Agent oder eine Plattform für alle anderen | Claude Code, OpenAI Codex, OpenCode | [Claude Code](claude-code.md) · [Codex](codex.md) · [OpenCode](opencode.md) |

## Das Feld im Überblick { #the-field-at-a-glance }

| Produkt | Was es ist | Wo es läuft | Quellcode | Modelle |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Eine Plattform für Unternehmens-Agents, im Browser aufgebaut | Ihre Infrastruktur | Apache-2.0 | 27 Provider, darunter lokale |
| Claude Team / Enterprise | Der Assistenten-Workspace von Anthropic | Die Cloud von Anthropic | Proprietär | Nur Claude |
| ChatGPT Business / Enterprise | Der Assistenten-Workspace von OpenAI, mit Workspace-Agents | Die Cloud von OpenAI | Proprietär | Nur OpenAI |
| Copilot Studio | Ein Low-Code-Agent-Builder auf der Power Platform | Die Cloud von Microsoft | Proprietär | Modelle von OpenAI und Anthropic, dazu Azure Foundry |
| Gemini Enterprise | Die Agent-Plattform und Suche von Google für Mitarbeiter | Google Cloud | Proprietär | Gemini in der App |
| Dify | Ein visueller Builder für LLM-Apps und Workflows | Selbst gehostet oder Dify Cloud | Modifizierte Apache 2.0 mit Bedingungen | Viele, darunter Ollama |
| n8n | Workflow-Automatisierung mit KI-Agent-Knoten | Selbst gehostet oder n8n Cloud | Sustainable Use License | Viele, darunter Ollama |
| Viktor | Ein KI-Teammate pro Slack- oder Teams-Workspace | Die Cloud von Viktor | Proprietär | OpenAI, Anthropic, Google, Kimi |
| Wonderful | Eine Enterprise-KI-Plattform mit Deployment-Teams | SaaS, Single-Tenant, Ihre Cloud oder On-Premises | Proprietär | Modellunabhängig, pro Aufgabe geroutet |
| Claude Code | Ein Coding-Agent für Entwickler | Entwicklerrechner, Anthropic-Cloud | Proprietär | Nur Claude |
| OpenAI Codex | Ein Coding-Agent für Entwickler | Entwicklerrechner, OpenAI-Cloud | CLI Apache-2.0, Cloud proprietär | OpenAI; die CLI nimmt auch andere |
| OpenCode | Ein Open-Source-Coding-Agent | Entwicklerrechner | MIT | Über 75 Provider |

Jede Zelle stammt von den eigenen Seiten des Anbieters; die Leitfäden verlinken sie. "Proprietär" beschreibt die Lizenz, nicht die Qualität.

## Was AgenticOS in jeden Vergleich einbringt { #what-agenticos-brings-to-every-comparison }

Diese Punkte ziehen sich durch jeden Leitfaden und stehen deshalb einmal hier.

- **Die Bereitstellung gehört Ihnen.** Sie läuft auf Ihrer Hardware mit Ihrem Postgres, und eine frische Installation sendet nichts nach außen. Eine vollständig lokale Einrichtung ist möglich, mit lokalen Chat-Modellen, lokalen Embeddings und lokalem Parsing. Siehe [standardmäßig verlässt nichts das System](../data-protection.md#nothing-leaves-by-default).
- **Jedes Modell, an einer Stelle umgestellt.** [27 Provider](../models.md#providers) stehen hinter einem [Modellprofil](../models.md#a-model-profile) mit [Fallbacks](../models.md#fallbacks). Ändern Sie das Profil, und jeder Agent, der es nutzt, zieht mit, ohne erneute Veröffentlichung.
- **Ein Agent ist ein versioniertes Dokument.** Die Veröffentlichung friert eine [Version](../concepts.md#version) ein, [Umgebungen](../environments.md#what-an-environment-is) verweisen auf Versionen, und der Spec [wird als YAML exportiert](../features.md#exportable-into-your-own-repository), in Ihr eigenes Git-Repository.
- **Governance steckt im Open-Source-Produkt.** [Budgets](../governance.md#enforcement-is-before-the-request) werden vor jeder Modellanfrage geprüft. [Freigaben](../governance.md#approvals) halten einen Run an, bis jemand entscheidet. Das [Audit-Log](../governance.md#audit) macht Manipulationen nachweisbar. Nichts davon wartet auf eine Enterprise-Stufe.
- **Viele Teams, eine Bereitstellung.** Organisationen sind Mandanten, im Schema isoliert. Das [Berechtigungsmodell](../permissions.md#the-built-in-roles) hat sechs Rollen und Grants pro Ressource. [OIDC Single Sign-on, LDAP und Kerberos](../directory.md#signing-in-with-a-directory-account) ordnen Verzeichnisgruppen Rollen zu.
- **Ein Agent, jede Oberfläche.** Derselbe veröffentlichte Agent antwortet im Web-Chat, in einem Widget, auf einer gehosteten Seite, über die HTTP-API, einen WebSocket, Slack, Telegram und Mattermost. Siehe [Oberflächen](../channels.md).
- **Im Code erweiterbar.** Eine [Capability](../howto/add-capability.md) ist typisiertes Python, und [jeder MCP-Server](../mcp.md) wird per URL verbunden. Konfiguration erreicht nur, was der Code registriert hat.
- **Keine Gebühr pro Nutzer.** Sie bezahlen Ihre Modell-Provider direkt und betreiben die Infrastruktur. Vstorm bietet Implementierungshilfe als separate Vereinbarung an; siehe [Betrieb und Implementierung](../rollout.md).

## Was AgenticOS noch nicht kann { #what-agenticos-does-not-do-yet }

Ein Vergleich, der die eigenen Lücken verschweigt, ist Werbung. Prüfen Sie diese Punkte vor einem Pilotprojekt gegen Ihre Anforderungen.

- Die Anmeldung hat noch kein SAML und kein SCIM; SAML funktioniert über einen Identity-Broker wie Keycloak. Siehe [was die Verzeichnisanmeldung noch nicht kann](../directory.md#what-this-does-not-do-yet).
- Es gibt keine Evaluierungsumgebung und kein Trace-Dashboard. Bewertungen und Run-Verlauf gibt es. Siehe [wo es noch nicht fertig ist](index.md#where-this-one-is-not-finished).
- Es gibt keinen Konversationskanal für Microsoft Teams, WhatsApp, Sprache oder E-Mail.
- Es gibt keine visuelle Workflow-Arbeitsfläche. Mehrstufige Arbeit nutzt Delegation, Planung und Trigger.
- Freigabeeinstellungen erreichen die Werkzeuge von Capabilities. MCP-Werkzeuge werden pro Konversation freigegeben, nicht pro Werkzeug. Siehe [was MCP Ihnen nicht bietet](../mcp.md#what-mcp-does-not-get-you).
- Die Bereitstellung erfolgt mit Docker Compose auf einem Host. Es gibt keine Kubernetes-Manifeste.
- Sie betreiben es selbst, oder Sie vereinbaren den Betrieb mit Vstorm oder einem anderen Partner.

## Ein gemeinsamer Versuch { #a-shared-trial }

Verwenden Sie das Beispiel [erster Dokumenten-Agent](../howto/first-document-agent.md) in beiden Produkten. Stellen Sie die beantwortbare Frage und die Frage zur fehlenden Regel. Ändern Sie den Verantwortlichen für die Anfrage, verarbeiten Sie die Quelle erneut und wiederholen Sie den Versuch. Bewahren Sie die tatsächlichen Antworten und die Konfiguration auf, einschließlich der Fehlschläge.

Erfassen Sie Produktversion oder Servicetarif, Modell, Quellenverarbeitung, Identität, Werkzeugzugriff, Freigabekonfiguration, Kanal, Kosten und Betriebsverantwortung. Beginnen Sie nur mit Retrieval. Falls eine Werkzeugaktion wichtig ist, vereinbaren Sie eine harmlose Testaktion und die erwartete Freigabe, bevor Sie sie hinzufügen.

## Was die Belege aussagen { #what-the-evidence-means }

Eine Herstellerbeschreibung belegt eine dokumentierte Option, nicht deren Qualität bei Ihrer Arbeitslast. Für diese Leitfäden wurde kein Konto eines Mitbewerbers genutzt. Ungetestetes Verhalten bleibt unbekannt und wird nicht zu einer Markierung als fehlende Funktion. Preise und Tarifinhalte ändern sich oft; bestätigen Sie sie daher auf der verlinkten Seite, bevor Sie sie zitieren.

Nennen Sie bei einem veröffentlichten Versuch die genauen Eingaben, die tatsächlichen Ausgaben, die fehlgeschlagenen Versuche und die Konfiguration. Trennen Sie den Modellverbrauch von Infrastruktur, Implementierung und laufendem Betrieb. Prüfen Sie [Lizenzen](../licenses.md), Provider-Bedingungen und die Edition, die Sie bereitstellen würden.

## Weitere Ausgangspunkte { #other-starting-points }

Eine Bibliothek wie [Pydantic AI](https://ai.pydantic.dev/) passt zu einem Agent, der in Ihre eigene Anwendung eingebettet ist; AgenticOS läuft darauf und ergänzt die Anwendung zum Konfigurieren und Betreiben von Agents. [OpenClaw](https://github.com/openclaw/openclaw) dokumentiert persönliche und gemeinsame Team-Bereitstellungen. [Lindy](https://www.lindy.ai/) bietet einen Teammate-Dienst. Das sind weitere Kandidaten, keine hier ausgeschlossenen Produkte.

Beginnen Sie mit der [Dokumentenaufgabe](../howto/first-document-agent.md) und prüfen Sie dann [Betrieb und Implementierung](../rollout.md). Die AgenticOS-Maintainer betreuen diese Leitfäden.
