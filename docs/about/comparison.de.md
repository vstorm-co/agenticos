---
source_sha: "5881de747c1a"
title: "AgenticOS vergleichen"
seo_title: "AgenticOS im Vergleich: souveräne Schicht für KI-Agents"
description: "AgenticOS im Vergleich mit Claude, ChatGPT, Copilot Studio, Dify, n8n, Kortix, LobeHub, Onyx, Open WebUI, Langdock, Dust, deepset und Agents in Slack."
---

# AgenticOS vergleichen { #compare-agenticos }

Die meisten Produkte in diesem Bereich sind eines von fünf Dingen: eine Assistenten-App, ein Agent-Builder, ein Teammate-Dienst, eine gelieferte Enterprise-Plattform oder ein Coding-Agent. AgenticOS ist eine souveräne Schicht für die Agents eines Unternehmens, die Sie selbst betreiben. Der Ausgangspunkt ist meist derselbe: Mitarbeiter nutzen eigene KI-Konten, sodass Wissen, Gedächtnis und Ausgaben außerhalb des Unternehmens liegen, und die IT will stattdessen einen gesteuerten Ort. Diese Leitfäden zeigen, wo jede Option passt und was AgenticOS ergänzt.

Verantwortlich: das AgenticOS-Team. Anbieterquellen geprüft am 21. Oktober 2026 für die ursprünglichen Leitfäden (OpenAI Frontier am 14. Oktober), am 2. November für Muse, Claude Duet, Grok Bot und OpenBot und am 26. November 2026 für die damals hinzugefügten Leitfäden: Open-Source-Plattformen, europäische Anbieter, Agents in Slack, der DIY-Stack und Lizenzbedingungen. Nächste Prüfung bis 27. Februar 2027 oder früher, wenn ein Anbieter das in einem Leitfaden beschriebene Angebot ändert. Jeder Leitfaden nennt seine Quellen. Für diese Leitfäden wurde kein Konto eines Mitbewerbers genutzt.

Die AgenticOS-Funktionsangaben wurden am 27. November 2026 anhand von v1.95.0 in allen Leitfäden aktualisiert. Ältere Prüfdaten der Anbieterquellen bleiben unverändert; diese Aktualisierung ist keine neue Preisprüfung.

## Den Leitfaden für Ihre Entscheidung wählen { #pick-the-guide-for-your-decision }

| Sie wägen ab | Produkte | Leitfaden |
| --- | --- | --- |
| Einen Chat-Assistenten für das Unternehmen oder Agents, die Ihrer Organisation gehören | Claude Team und Enterprise, ChatGPT Business und Enterprise | [Claude](claude-apps.md) · [ChatGPT](chatgpt.md) |
| Einen Builder in der Cloud-Suite eines Anbieters | Microsoft Copilot Studio, Google Gemini Enterprise | [Copilot Studio](copilot-studio.md) · [Gemini Enterprise](gemini-enterprise.md) |
| Einen selbst gehosteten Builder oder ein Automatisierungswerkzeug | Dify, n8n | [Dify](dify.md) · [n8n](n8n.md) |
| Eine Open-Source-Plattform für Unternehmens-Agents | Kortix CompanyOS, LobeHub, Agno AgentOS, OpenAgents, OpenHuman | [Kortix](kortix.md) · [LobeHub](lobehub.md) · [Agno](agno.md) · [OpenAgents](openagents.md) · [OpenHuman](openhuman.md) |
| Einen selbst gehosteten Firmen-Chat oder eine Firmensuche | Open WebUI, LibreChat, Onyx | [Open WebUI und LibreChat](open-webui-librechat.md) · [Onyx](onyx.md) |
| Den Eigenbau aus Open-Source-Bausteinen | Open WebUI, LiteLLM, Langfuse, n8n, Keycloak | [DIY-Stack](diy-stack.md) · [Lizenzbedingungen](licence-terms.md) |
| Eine europäische KI-Plattform | Langdock, Dust, Mistral, deepset | [Langdock](langdock.md) · [Dust](dust.md) · [Mistral](mistral.md) · [deepset](deepset.md) |
| Einen Agent in Slack | Claude Tag, Slackbot | [Agents in Slack](slack-agents.md) |
| Ein dauerhaft laufendes KI-Teammate mit eigenem Computer | OpenAI dots, Grok Bot, Viktor, Sauna | [dots](openai-dots.md) · [Grok Bot](grok-bot.md) · [Viktor](viktor.md) · [Sauna](sauna.md) |
| Eine Plattform oder Steuerungsebene eines Anbieters für Unternehmens-Agents | OpenAI Frontier, Microsoft Agent 365 | [Frontier](openai-frontier.md) · [Agent 365](microsoft-agent-365.md) |
| Eine gehostete Agent-Laufzeit für Entwickler | Claude Managed Agents | [Managed Agents](claude-managed-agents.md) |
| Einen persönlichen Open-Source-Agent | OpenClaw, NVIDIA NemoClaw | [OpenClaw](openclaw.md) |
| Eine gelieferte Enterprise-Plattform | Wonderful | [Wonderful](wonderful.md) |
| Einen Coding-Agent oder eine Schicht für alle anderen | Claude Code, OpenAI Codex, OpenCode | [Claude Code](claude-code.md) · [Codex](codex.md) · [OpenCode](opencode.md) |

## Das Feld im Überblick { #the-field-at-a-glance }

| Produkt | Was es ist | Wo es läuft | Quellcode | Modelle |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Eine souveräne Schicht für Unternehmens-Agents, im Browser aufgebaut | Ihre Infrastruktur | Apache-2.0 | 28 Provider, darunter lokale |
| Claude Team / Enterprise | Der Assistenten-Workspace von Anthropic | Die Cloud von Anthropic | Proprietär | Nur Claude |
| ChatGPT Business / Enterprise | Der Assistenten-Workspace von OpenAI, mit Workspace-Agents | Die Cloud von OpenAI | Proprietär | Nur OpenAI |
| Copilot Studio | Ein Low-Code-Agent-Builder auf der Power Platform | Die Cloud von Microsoft | Proprietär | Modelle von OpenAI und Anthropic, dazu Azure Foundry |
| Gemini Enterprise | Die Agent-Plattform und Suche von Google für Mitarbeiter | Google Cloud | Proprietär | Gemini in der App |
| Dify | Ein visueller Builder für LLM-Apps und Workflows | Selbst gehostet oder Dify Cloud | Modifizierte Apache 2.0 mit Bedingungen | Viele, darunter Ollama |
| n8n | Workflow-Automatisierung mit KI-Agent-Knoten | Selbst gehostet oder n8n Cloud | Sustainable Use License | Viele, darunter Ollama |
| Kortix CompanyOS | Ein Unternehmen als Git-Repository aus Agents, Skills und Konnektoren | Kortix-Cloud oder selbst gehostet mit Sessions in der Kortix-Cloud | Elastic License 2.0 | Beliebige |
| LobeHub | Ein KI-Workspace, dessen Agents Team-Chats beitreten | LobeHub-Cloud oder selbst gehostet | LobeHub Community License | Über 90 Provider |
| Agno AgentOS | Ein Python-Framework und Runtime mit gehosteter Control Plane | Runtime selbst gehostet; Control Plane als SaaS | Runtime Apache-2.0; geschlossene Control Plane | Beliebige |
| OpenAgents | Ein gemeinsamer Workspace für Menschen und Agents aus vielen Runtimes | Gehostet oder selbst gehostet | Apache-2.0 | Die der verbundenen Agents |
| OpenHuman | Ein persönlicher Agent-Harness und eine Desktop-App | Desktop, Terminal oder Server | GPL-3.0 | 26 Provider und lokale Modelle |
| Open WebUI | Eine selbst gehostete KI-Chat-Oberfläche | Selbst gehostet | BSD-3 mit Branding-Klausel | OpenAI-kompatibel und Ollama |
| LibreChat | Ein selbst gehosteter Chat mit Agents und MCP | Selbst gehostet | MIT; Admin-Panel AGPL-3.0 | Alle großen Provider |
| Onyx | Firmensuche und Chat mit Agents | Selbst gehostet oder Onyx-Cloud | MIT mit `ee`-Verzeichnissen | Beliebige |
| Langdock | Ein KI-Workspace pro Arbeitsplatz mit Agents und Workflows | SaaS auf Azure in der EU | Proprietär | Mehrere Modelle, in der EU gehostet |
| Dust | Ein gehosteter Workspace für Unternehmens-Agents | Dust-Cloud, Region USA oder EU | Proprietär | Mehrere Provider |
| Mistral AI Studio | Modelle, Assistent und Agent-Plattform von einem Anbieter | Cloud, Serverless oder selbst gehostet | Proprietäre Plattform | Vor allem Mistral |
| deepset Haystack Enterprise Platform | Eine souveräne Plattform für Haystack-Agents und -Pipelines | Cloud, selbst gehostet, netzwerkisoliert, STACKIT | Proprietär; Haystack Apache-2.0 | Beliebige |
| Claude Tag / Slackbot | Anbieter-Agents in Slack | Cloud von Anthropic oder Salesforce | Proprietär | Nur Claude / Wahl von Salesforce |
| Viktor | Ein KI-Teammate pro Slack- oder Teams-Workspace | Die Cloud von Viktor | Proprietär | OpenAI, Anthropic, Google, xAI |
| Sauna | Ein proaktiver KI-Assistent pro Person, mit Gedächtnis | Die Cloud von Sauna | Proprietär | Das eigene Lite-Modell oder alle Modelle ab dem Tarif Basic |
| OpenAI dots | Dauerhaft laufende Agents in ChatGPT, jeder mit einem Cloud-Computer | Die Cloud von OpenAI | Proprietär | Nur OpenAI |
| Grok Bot | Benannte Teammates auf einem gemeinsamen Cloud-Computer | Die Cloud von xAI | Proprietär | Nur Grok |
| OpenAI Frontier | Eine Plattform zur Verwaltung von KI-Kollegen im Unternehmen | Lokal, Ihre Cloud oder OpenAI | Proprietär | OpenAI |
| Microsoft Agent 365 | Eine Steuerungsebene über Agents in Microsoft 365 | Die Cloud von Microsoft | Proprietär | Über die Agents, die es steuert |
| Claude Managed Agents | Eine gehostete Agent-Laufzeit für Entwickler | Die Cloud von Anthropic | Proprietär | Nur Claude |
| OpenClaw / NemoClaw | Ein persönlicher Open-Source-Agent; die Enterprise-Distribution von NVIDIA | Ihr Rechner oder Server | Open Source | Viele |
| Wonderful | Eine Enterprise-KI-Plattform mit Deployment-Teams | SaaS, Single-Tenant, Ihre Cloud oder On-Premises | Proprietär | Modellunabhängig, pro Aufgabe geroutet |
| Claude Code | Ein Coding-Agent für Entwickler | Entwicklerrechner, Anthropic-Cloud | Proprietär | Nur Claude |
| OpenAI Codex | Ein Coding-Agent für Entwickler | Entwicklerrechner, OpenAI-Cloud | CLI Apache-2.0, Cloud proprietär | OpenAI; die CLI nimmt auch andere |
| OpenCode | Ein Open-Source-Coding-Agent | Entwicklerrechner | MIT | Über 75 Provider |

Jede Zelle stammt von den eigenen Seiten des Anbieters; die Leitfäden verlinken sie. "Proprietär" beschreibt die Lizenz, nicht die Qualität.

## Wie viel bei Ihnen bleibt { #how-much-stays-yours }

Souveränität bedeutet hier vier Dinge, die Sie entscheiden: wo das Produkt läuft, welche Modelle es nutzen darf, was die Lizenz Ihnen erlaubt und ob die Kontrollen, nach denen eine IT- und Sicherheitsprüfung fragt, ohne kostenpflichtigen Tarif verfügbar sind. Jede Zelle stammt aus den Leitfäden oben oder den Anbieterseiten, die sie verlinken.

| Produkt | Wo es läuft | Welche Modelle Sie nutzen dürfen | Was die Lizenz erlaubt | Anmeldung, Audit und Kostenkontrolle |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Ihre Infrastruktur; eine frische Installation sendet keine Prompts oder Dokumente nach außen, und die Diagnose ist standardmäßig aktiv und abschaltbar | Jeder der 28 Provider oder ausschließlich lokale Modelle | Apache-2.0: lesen, ändern, unter eigener Marke anbieten und für andere betreiben; der Standard-PDF-Parser steht unter AGPL-3.0, sodass ein verändertes Image, das Sie anderen bereitstellen, ihnen seinen Quellcode schuldet ([Details](../licenses.md#the-agpl-component)) | Anmeldung: OIDC-SSO, LDAP und Kerberos · Audit: Log mit Manipulationsnachweis · Ausgaben: Budgets pro Agent und pro Organisation · alles in jedem Deployment |
| Claude Team / Enterprise | Cloud von Anthropic | Nur Claude | Proprietär | Anmeldung: SSO in Team und Enterprise · Audit: Enterprise, 180 Tage Ereignisse · Ausgaben: Limits pro Organisation und Nutzer |
| ChatGPT Business / Enterprise | Cloud von OpenAI; in Enterprise Speicherort in zehn Regionen wählbar | Nur OpenAI | Proprietär | Anmeldung: SAML-SSO in Business; SCIM und rollenbasierte Zugriffskontrollen in Enterprise · Audit: Compliance API in Enterprise und Edu · Ausgaben: Credit-Pools und Überziehungslimits |
| Copilot Studio | Cloud von Microsoft, in Power-Platform-Umgebungen | Standardmäßig GPT-Modelle, Claude-Modelle, Azure-Foundry-Modelle separat abgerechnet | Proprietär | Anmeldung: Entra ID · Audit: Purview · Ausgaben: monatliche Limits pro Agent |
| Gemini Enterprise | Google Cloud, in den Regionen global, US, EU und einigen nationalen | Gemini; andere Modelle nur in Custom Agents auf der Agent Platform | Proprietär | Anmeldung: Google Cloud IAM · Audit: Audit-Logs von Google Cloud · Ausgaben: monatliche Limits auf dem Rechnungskonto |
| Dify | Selbst gehostet oder Dify Cloud | Viele, darunter Ollama | Apache 2.0 mit Bedingungen: ein mandantenfähiger Dienst braucht eine schriftliche Erlaubnis, und das Logo darf nicht geändert werden | Anmeldung: E-Mail; SSO in Enterprise · Audit: Enterprise · Ausgaben: Abrechnung beim Provider oder Nachrichten-Credits in der Cloud |
| Kortix CompanyOS | Kortix-Cloud oder selbst gehostet, mit Agent-Sessions in Cloud-Sandboxes von Kortix | Beliebige, mit eigenen Schlüsseln | Elastic License 2.0: kein gehosteter Dienst für Dritte, kein Umgehen des Lizenzschlüssels | Anmeldung: SAML und SCIM mit Enterprise-Schlüssel · Audit: Lesen braucht Enterprise · Ausgaben: Budget pro Workspace |
| LobeHub | LobeHub-Cloud oder selbst gehostet | Über 90 Provider | LobeHub Community License: kommerzielle Nutzung ohne Codeänderung; Ableitungen brauchen eine kommerzielle Lizenz | Anmeldung: SAML in Enterprise · Audit: Business-Plan · Ausgaben: Kreditpool |
| Onyx | Selbst gehostet, auch netzwerkisoliert, oder Onyx-Cloud | Beliebige | MIT-Kern; `ee`-Verzeichnisse brauchen in Produktion eine Lizenz pro Arbeitsplatz | Anmeldung: SCIM in Enterprise · Audit: OCSF-Stream · Ausgaben: pro Workspace in Business, pro Person und Gruppe in Enterprise |
| Open WebUI | Selbst gehostet, auch netzwerkisoliert | OpenAI-kompatibel und Ollama | BSD-3 mit Branding-Klausel ab 50 Nutzern in 30 Tagen | Anmeldung: OIDC, LDAP und SCIM · Audit: nicht angegeben · Ausgaben: nicht angegeben |
| LibreChat | Selbst gehostet | Alle großen Provider | MIT; Admin-Panel mit eigenen Rollen unter AGPL-3.0 | Anmeldung: OIDC, SAML, LDAP · Audit: Berechtigungsänderungen · Ausgaben: Token-Guthaben pro Person |
| Langdock | SaaS auf Azure in der EU; Single-Tenant und On-Premises bei großen Verträgen | Mehrere Modelle in der EU, eigene Schlüssel | Proprietär | Anmeldung: SAML und SCIM in jedem Plan · Audit: API, 90 Tage · Ausgaben: Limits pro Workspace, Person, Gruppe, Agent und Workflow |
| Dust | Dust-Cloud, Region USA oder EU; kein Selbsthosting | Mehrere Provider | Proprietär | Anmeldung: für diesen Leitfaden nicht geprüft · Audit: manipulationssicher in Enterprise · Ausgaben: Kredite pro Person, Gruppe und API-Schlüssel |
| deepset Haystack Enterprise Platform | Cloud, selbst gehostet, netzwerkisoliert oder STACKIT | Beliebige | Proprietäre Plattform; Haystack-Framework Apache-2.0 | Zugriffskontrolle und Observability; Details über den Vertrieb |
| n8n | Selbst gehostet oder n8n Cloud in Frankfurt | Viele, darunter Ollama | Sustainable Use License: interne Geschäftszwecke, nicht kommerzielle oder private Nutzung; kostenpflichtige Funktionen brauchen einen Lizenzschlüssel, der täglich den Lizenzserver von n8n kontaktiert | Anmeldung: SSO in kostenpflichtigen Plänen · Audit: Log-Streaming in Enterprise · Ausgaben: Ausführungskontingente pro Plan |
| Viktor | Cloud von Viktor, standardmäßig in den USA gehostet | Modelle von OpenAI, Anthropic, Google und xAI oder ein eigener OpenRouter-Schlüssel | Proprietär | Anmeldung: SAML-SSO · Audit: Audit-Logs in Enterprise · Ausgaben: Credit-Pool mit monatlicher Obergrenze für Aufladungen, Limits pro Nutzer in Enterprise |
| Sauna | Cloud von Sauna; US-Infrastruktur für US-Kunden | Das eigene Lite-Modell oder alle Modelle ab dem Tarif Basic | Proprietär | Anmeldung: E-Mail oder Google · Audit: nicht angegeben · Ausgaben: Credits pro Tarif |
| OpenAI dots | Cloud von OpenAI; der Pro-Tarif war zum Start nicht im EWR, in der Schweiz und im Vereinigten Königreich verfügbar | Nur OpenAI | Proprietär | Anmeldung: ChatGPT-Konten · Audit: für dots nicht angegeben · Ausgaben: im Tarif enthalten |
| Grok Bot | xAI-Cloud | Grok-Bot-Dienst | Proprietär | Enterprise: Audit-Logs, OpenTelemetry-Export, MCP-Freigabeliste und SCIM; [aktueller Umfang](grok-bot.md) |
| OpenAI Frontier | Lokal, Ihre Cloud oder OpenAI | OpenAI | Proprietär | Anmeldung, Audit und Ausgaben: nicht öffentlich angegeben; Berechtigungen pro Agent und Dashboards angekündigt |
| Microsoft Agent 365 | Cloud von Microsoft | Über die Agents, die es steuert | Proprietär | Anmeldung: Entra ID · Audit: Purview · Ausgaben: Microsoft-365-Lizenzen |
| Claude Managed Agents | Cloud von Anthropic | Nur Claude | Proprietär | Anmeldung: Anthropic-API-Schlüssel · Audit: nicht angegeben · Ausgaben: Tokens plus Gebühr pro Sitzungsstunde, Organisationslimits |
| OpenClaw / NemoClaw | Ihr Rechner oder Server | Viele | Open Source; NemoClaw ist die Distribution von NVIDIA | Anmeldung, Audit und Zugriffskontrolle: minimal in OpenClaw; ergänzt durch NemoClaw |
| Wonderful | Mandantenfähiges SaaS, Single-Tenant, Ihre Cloud oder netzwerkisoliert on-premises | Pro Aufgabe von der Plattform geroutet | Proprietär; Agents und Konfiguration lassen sich über UI oder API exportieren | Anmeldung: auf seinen Seiten nicht angegeben · Audit: Audit-Logs im AI Gateway · Ausgaben: Budgetgrenzen pro Team |

Dify, n8n, Onyx, Open WebUI, LibreChat und deepset laufen ebenfalls auf Ihren eigenen Servern, und Wonderful bietet eine netzwerkisolierte On-Premises-Bereitstellung. Unter den Produkten in dieser Tabelle ist AgenticOS das einzige, bei dem alle vier Antworten bei Ihnen bleiben.

Wer AgenticOS selbst betreibt, macht damit nicht jedes Modell, jeden Parser und jedes Werkzeug lokal. Jeden externen Dienst fügen Sie selbst hinzu; siehe [standardmäßig verlässt nichts das System](../data-protection.md#nothing-leaves-by-default).

## Ausgabenlimits sind verbreitet; wo sie greifen, nicht { #spend-limits-are-common-where-they-apply-is-not }

Ausgabenlimits allein heben ein Produkt nicht mehr ab. Claude Tag begrenzt Ausgaben pro Organisation und Slack-Kanal, Notion pro Mitglied, Hermes Business pro Teammitglied, Amazon Quick pro Nutzer, LiteLLM pro Schlüssel, Team und Tag, Kortix pro Workspace, Onyx pro Workspace oder Person, Dust pro Person und Gruppe und Langdock sogar pro Agent, in seinem kostenpflichtigen SaaS.

AgenticOS kombiniert ein [Budget pro Agent](../governance.md#budgets), geprüft [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request), gleich über welchen Provider und Kanal die Anfrage kommt, [delegierte Arbeit](../governance.md#delegation-spends-the-parents-budget), die dem delegierenden Agent angerechnet wird, im kostenlosen Open-Source-Produkt auf Ihren eigenen Servern, und dasselbe Audit-Log wie für [Freigaben](../governance.md#approvals).

## Open Source, mit Bedingungen { #open-source-with-conditions }

Die meisten Open-Source-Mitbewerber knüpfen Bedingungen daran: modifizierte Apache-Lizenz (Dify, FastGPT), Sustainable Use License (n8n), Elastic License 2.0 (Kortix seit Februar 2026), eigene Lizenzen (LobeHub, Open WebUI) oder Enterprise-Verzeichnisse (Onyx, LiteLLM, Langfuse). AgenticOS steht unter Apache-2.0 und hält nichts für eine bezahlte Edition zurück. [Lizenzbedingungen im Vergleich](licence-terms.md) zitiert die Klauseln.

## Was AgenticOS in jeden Vergleich einbringt { #what-agenticos-brings-to-every-comparison }

Diese Punkte ziehen sich durch jeden Leitfaden und stehen deshalb einmal hier.

- **Die Bereitstellung gehört Ihnen.** Sie läuft auf Ihrer Hardware mit Ihrem eigenen Postgres und Speicher, und eine frische Installation sendet keine Prompts oder Dokumente nach außen; die Deployment-Diagnose ist standardmäßig aktiv und lässt sich abschalten. Eine vollständig lokale Einrichtung ist möglich, mit lokalen Chat-Modellen, lokalen Embeddings und lokalem Parsing. Siehe [was standardmäßig das System verlässt](../data-protection.md#nothing-leaves-by-default).
- **Jedes Modell, an einer Stelle umgestellt.** [28 Provider](../models.md#providers) stehen hinter einem [Modellprofil](../models.md#a-model-profile) mit [Fallbacks](../models.md#fallbacks). Ändern Sie das Profil, und jeder Agent, der es nutzt, zieht mit, ohne erneute Veröffentlichung.
- **Ein Agent ist ein versioniertes Dokument.** Die Veröffentlichung friert eine [Version](../concepts.md#version) ein, [Umgebungen](../environments.md#what-an-environment-is) verweisen auf Versionen, und der Spec [wird als YAML exportiert](../features.md#exportable-into-your-own-repository), in Ihr eigenes Git-Repository.
- **Governance steckt im Open-Source-Produkt.** [Budgets](../governance.md#enforcement-is-before-the-request) werden vor jeder Modellanfrage geprüft. [Freigaben](../governance.md#approvals) halten einen Run an, bis jemand entscheidet. Das [Audit-Log](../governance.md#audit) macht Manipulationen nachweisbar. Nichts davon wartet auf eine Enterprise-Stufe.
- **Viele Teams, eine Bereitstellung.** Organisationen sind Mandanten, im Schema isoliert. Das [Berechtigungsmodell](../permissions.md#the-built-in-roles) hat sechs Rollen und Grants pro Ressource. [OIDC Single Sign-on, LDAP und Kerberos](../directory.md#signing-in-with-a-directory-account) ordnen Verzeichnisgruppen Rollen zu.
- **Ein Agent, jede Oberfläche.** Derselbe veröffentlichte Agent antwortet im Web-Chat, in einem Widget, auf einer gehosteten Seite, über die HTTP-API, einen WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail und iMessage, nimmt [Telefonanrufe](../voice.md#telephone-calls) an, und andere Agents erreichen ihn über [A2A](../channels.md#a2a). Siehe [Oberflächen](../channels.md).
- **Desktop- und Telefon-App.** Die [Desktop-App](../desktop.md) ergänzt Quick Ask, Arbeit in einem freigegebenen Ordner auf Ihrem Rechner und lokale Coding-Agents wie Claude Code und Codex. Die [Telefon-App](../mobile.md) zeigt offene Freigaben in einem Widget und nimmt Inhalte aus anderen Apps entgegen.
- **Getestet, bevor es live geht.** [Eval-Runs](../evals.md) bewerten eine Version gegen ein versioniertes Dataset und eine Baseline, [Suites](../evals.md#suites) können die Promotion sperren, und der [Authoring-Assistent](../authoring.md) schlägt Änderungen auf Basis von Belegen vor.
- **Menschen und Agents an einem Ort.** Ein [Projekt](../projects.md) gibt einem Team und seinen Agents gemeinsame Dateien, Instruktionen und Chats, und der [Coding Agent](../reference/capabilities.md#coding-agent) übergibt Softwarearbeit an Claude Code oder Codex in einer Sandbox. [AgenticOS ist auch ein MCP-Server](../mcp.md#agenticos-as-an-mcp-server), sodass diese Werkzeuge die Agents des Unternehmens auflisten und ausführen können.
- **Im Code erweiterbar.** Eine [Capability](../howto/add-capability.md) ist typisiertes Python, und [jeder MCP-Server](../mcp.md) wird per URL verbunden. Konfiguration erreicht nur, was der Code registriert hat.
- **Keine Gebühr pro Nutzer.** Sie bezahlen Ihre Modell-Provider direkt und betreiben die Infrastruktur. Vstorm bietet Implementierungshilfe als separate Vereinbarung an; siehe [Betrieb und Implementierung](../rollout.md).

## Was AgenticOS noch nicht kann { #what-agenticos-does-not-do-yet }

Ein Vergleich, der die eigenen Lücken verschweigt, ist Werbung. Prüfen Sie diese Punkte vor einem Pilotprojekt gegen Ihre Anforderungen.

- Es gibt nur die sechs eingebauten Rollen; benutzerdefinierte Rollen sind noch nicht verfügbar.
- Die Anmeldung hat noch kein SAML und kein SCIM; SAML funktioniert über einen Identity-Broker wie Keycloak. Siehe [was die Verzeichnisanmeldung noch nicht kann](../directory.md#what-this-does-not-do-yet).
- Es gibt kein Trace-Dashboard und keinen Reranker. Run-Verlauf, Kosten und Eval-Ergebnisse gibt es, und Traces werden nach Logfire exportiert. Siehe [wo es noch nicht fertig ist](index.md#where-this-one-is-not-finished).
- Es gibt keinen WhatsApp-Kanal. Telefonanrufe brauchen Ihre eigene Twilio-Nummer.
- Es gibt keinen Marktplatz für Community-Plugins oder -Nodes und weniger fertige Konnektoren als in den größten Suiten.
- Es gibt keine Sicherheitszertifizierungen für einen verwalteten Dienst: Sie zertifizieren Ihre eigene Bereitstellung, und die [Sicherheitsseite](../security.md) ordnet ihre Kontrollen zu.
- AgenticOS enthält inzwischen eine visuelle Workflow-Arbeitsfläche mit typisierten Schritten, Verzweigungen und Schleifen. Vergleichen Sie die benötigten Knotentypen und Integrationen, statt identische Funktionen vorauszusetzen.
- Eine MCP-Bindung mit `writes` vertraut den Nur-Lesen-Markierungen des Servers selbst, also läuft ein Werkzeug, das er fälschlich als nur lesend markiert, ungefragt; `all` hält jeden Aufruf an. Siehe [was MCP Ihnen nicht bietet](../mcp.md#what-mcp-does-not-get-you).
- OpenShift ist nicht validiert. Ein gepflegtes [Kubernetes-Helm-Chart](../kubernetes.md) deployt API, Worker und Konsole mit externen Datendiensten; Docker Compose bleibt der Weg für einen einzelnen Host.
- Sie betreiben es selbst, oder Sie vereinbaren den Betrieb mit Vstorm oder einem anderen Partner.

## Ein gemeinsamer Versuch { #a-shared-trial }

Verwenden Sie das Beispiel [erster Dokumenten-Agent](../howto/first-document-agent.md) in beiden Produkten. Stellen Sie die beantwortbare Frage und die Frage zur fehlenden Regel. Ändern Sie den Verantwortlichen für die Anfrage, verarbeiten Sie die Quelle erneut und wiederholen Sie den Versuch. Bewahren Sie die tatsächlichen Antworten und die Konfiguration auf, einschließlich der Fehlschläge.

Erfassen Sie Produktversion oder Servicetarif, Modell, Quellenverarbeitung, Identität, Werkzeugzugriff, Freigabekonfiguration, Kanal, Kosten und Betriebsverantwortung. Beginnen Sie nur mit Retrieval. Falls eine Werkzeugaktion wichtig ist, vereinbaren Sie eine harmlose Testaktion und die erwartete Freigabe, bevor Sie sie hinzufügen.

## Was die Belege aussagen { #what-the-evidence-means }

Eine Herstellerbeschreibung belegt eine dokumentierte Option, nicht deren Qualität bei Ihrer Arbeitslast. Für diese Leitfäden wurde kein Konto eines Mitbewerbers genutzt. Ungetestetes Verhalten bleibt unbekannt und wird nicht zu einer Markierung als fehlende Funktion. Preise und Tarifinhalte ändern sich oft; bestätigen Sie sie daher auf der verlinkten Seite, bevor Sie sie zitieren.

Nennen Sie bei einem veröffentlichten Versuch die genauen Eingaben, die tatsächlichen Ausgaben, die fehlgeschlagenen Versuche und die Konfiguration. Trennen Sie den Modellverbrauch von Infrastruktur, Implementierung und laufendem Betrieb. Prüfen Sie [Lizenzen](../licenses.md), Provider-Bedingungen und die Edition, die Sie bereitstellen würden.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS Open Source? { #is-agenticos-open-source }

Ja. AgenticOS steht unter Apache-2.0 und läuft mit Docker Compose auf Ihrer eigenen Infrastruktur. Einige mitgelieferte Komponenten haben eigene Lizenzen, die auf der Seite [Lizenzen](../licenses.md) aufgeführt sind.

### Ist AgenticOS eine selbst gehostete Alternative zu ChatGPT Enterprise oder Claude Enterprise? { #is-agenticos-a-self-hosted-alternative-to-chatgpt-enterprise-or-claude-enterprise }

Für Agents, die Ihrer Organisation gehören, ja. Es betreibt Agents auf jedem von 28 Modell-Providern, OpenAI und Anthropic eingeschlossen, mit Budgets, Freigaben und Audit-Logs in jeder Bereitstellung. Es ist kein persönlicher Assistent für jeden Mitarbeiter; siehe die Leitfäden zu [ChatGPT](chatgpt.md) und [Claude](claude-apps.md).

### Was kostet AgenticOS? { #how-much-does-agenticos-cost }

Es gibt keine Lizenzgebühr und keine Gebühr pro Nutzer. Sie bezahlen Ihre Modell-Provider zu deren eigenen Tarifen und betreiben die Infrastruktur: [4 vCPU und 8 GB RAM](../deploy.md) genügen dafür. Implementierungshilfe von Vstorm wird separat vereinbart.

### Welchen Vergleich sollte ich zuerst lesen? { #which-comparison-should-i-read-first }

Beginnen Sie mit der Art von Produkt, die Sie abwägen: einer Assistenten-App, einem Builder in einer Cloud-Suite, einem selbst gehosteten Builder, einem Teammate-Dienst, einer gelieferten Plattform oder einem Coding-Agent. Die [Tabelle oben](#pick-the-guide-for-your-decision) verweist auf jeden Leitfaden.

### Ist AgenticOS dasselbe wie Agno AgentOS oder andere „Agent OS“-Produkte? { #is-agenticos-the-same-as-agno-agentos-or-other-agent-os-products }

Nein. 2026 verwenden viele Anbieter „Agent OS“ und „agentic OS“, darunter Agno, Kortix und aiXplain. AgenticOS ist die Apache-2.0-Plattform, die Vstorm unter github.com/vstorm-co/agenticos pflegt. Siehe [AgenticOS vs Agno AgentOS](agno.md).

### Welche Open-Source-Plattformen stehen AgenticOS am nächsten? { #which-open-source-platforms-are-closest-to-agenticos }

Kortix CompanyOS und LobeHub beschreiben dieselbe Idee von Agents, die in den Kanälen eines Unternehmens arbeiten; Onyx, Open WebUI und LibreChat sind die selbst gehosteten Chats, die die IT oft zuerst einführt; und OpenAgents koordiniert Agents aus vielen Runtimes. Die [Tabelle oben](#pick-the-guide-for-your-decision) verlinkt zu jedem einen Leitfaden.

## Weitere Ausgangspunkte { #other-starting-points }

Eine Bibliothek wie [Pydantic AI](https://ai.pydantic.dev/) passt zu einem Agent, der in Ihre eigene Anwendung eingebettet ist; AgenticOS läuft darauf und ergänzt die Anwendung zum Konfigurieren und Betreiben von Agents. [OpenClaw](https://github.com/openclaw/openclaw) dokumentiert persönliche und gemeinsame Team-Bereitstellungen. [Lindy](https://www.lindy.ai/) bietet einen Teammate-Dienst. Das sind weitere Kandidaten, keine hier ausgeschlossenen Produkte.

Beginnen Sie mit der [Dokumentenaufgabe](../howto/first-document-agent.md) und prüfen Sie dann [Betrieb und Implementierung](../rollout.md). Die AgenticOS-Maintainer betreuen diese Leitfäden.

[Muse](muse.md) · [Claude Duet](claude-duet.md) — Quellen am 2. November 2026 geprüft; AgenticOS v1.35.0.

[AgenticOS vs OpenBot](openbot.md)
