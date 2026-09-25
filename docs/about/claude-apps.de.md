---
source_sha: "6541bd2e459e"
title: "AgenticOS vs Claude"
description: "Vergleich von Claude Team und Enterprise, dem Assistenten-Workspace von Anthropic, mit einer selbst gehosteten Plattform für Unternehmens-Agents."
---

# AgenticOS vs Claude { #agenticos-vs-claude }

Claude Team und Claude Enterprise geben jedem Mitarbeiter den Assistenten von Anthropic: Chat, Projects, Research, Cowork, Konnektoren, Skills und Office-Add-ins, auf Claude-Modellen, in der Cloud von Anthropic. AgenticOS baut Agents für Ihre Organisation, keine Nutzerlizenzen für Ihre Mitarbeiter. Jeder Agent hat eine eigene Aufgabe, ein eigenes Modell, eigenes Wissen, ein eigenes Budget und eigene Zugriffsregeln und antwortet auf Ihrer Website, in Ihren Chat-Werkzeugen und über Ihre API.

Sie schließen einander nicht aus. AgenticOS kann Claude-Modelle über die Anthropic API, Amazon Bedrock oder Google Vertex AI nutzen, daher stehen ein Claude-Abonnement und eine AgenticOS-Bereitstellung oft nebeneinander.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 25. September 2026. AgenticOS-Basis: v0.0.504. Umfang bei Claude: die Preis-, Produkt- und Help-Center-Seiten von Anthropic zu den Tarifen Team und Enterprise, kein getestetes Konto.

## Auf einen Blick { #at-a-glance }

| Bereich | Claude Team / Enterprise | AgenticOS |
| --- | --- | --- |
| Kaufeinheit | Eine Nutzerlizenz pro Mitarbeiter | Eine Bereitstellung; keine Gebühr pro Nutzer |
| Wo es läuft | Die Cloud von Anthropic | Ihre Infrastruktur |
| Quellcode | Proprietär | Apache-2.0 |
| Modelle | Nur Claude | 27 Provider, Claude eingeschlossen, und lokale Modelle |
| Was Sie bauen | Projects, Skills und Plugins für Menschen, die chatten | Veröffentlichte Agents, jeder ein versionierter Spec |
| Wer es nutzt | Mitarbeiter mit einer Nutzerlizenz | Mitarbeiter, Kunden und Systeme, auf acht Oberflächen |
| Oberflächen | Web, Desktop, Mobil, Chrome, Office-Add-ins, Slack in der Beta | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Ausgabenkontrolle | Ausgabenlimits für Organisation, Gruppe und Benutzer | Ein Budget pro Agent und pro Organisation, vor jeder Modellanfrage geprüft |
| Freigaben | Der handelnde Benutzer oder ein automatischer Modus | Ein Run wartet, bis eine Person mit `approvals:decide` entscheidet |
| Audit-Log | Enterprise; Ereignisse von 180 Tagen als CSV | In jedem Tarif; mit Manipulationsnachweis, als CSV oder JSONL exportiert |
| Preise | Team 20 $ pro Nutzer und Monat bei jährlicher Zahlung, 25 $ bei monatlicher; Enterprise 20 $ pro Nutzer und Monat plus Nutzung zu API-Preisen, ab 20 Nutzerlizenzen | Modellnutzung zu den Preisen Ihres Providers, plus Infrastruktur |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Agents für eine Aufgabe, nicht Assistenten für eine Person { #agents-for-a-job-not-assistants-for-a-person }

Claude Projects enthalten Instruktionen und Wissen für die Menschen, die darin chatten. Ein AgenticOS-Agent ist ein veröffentlichtes Objekt mit eigenem [Versionsverlauf](../concepts.md#version), [Umgebungen](../environments.md#what-an-environment-is) zum Testen und einem [YAML-Export](../features.md#exportable-into-your-own-repository) in Ihr Repository. Derselbe Agent antwortet auf [jeder Oberfläche](../channels.md), auch in einem [einbettbaren Widget](../channels.md#the-website-widget) für anonyme Besucher und auf einer [gehosteten Seite](../channels.md#a-hosted-page). Die Apps von Anthropic haben kein Widget und keinen Endpunkt pro Assistent für die Öffentlichkeit.

### Jedes Modell und die Option, lokal zu bleiben { #any-model-and-the-option-to-keep-it-local }

Claude-Tarife nutzen nur Claude-Modelle. AgenticOS erreicht [27 Provider](../models.md#providers), darunter Anthropic, Bedrock und Vertex für Claude, dazu OpenAI, Google, Mistral sowie Ollama oder LiteLLM auf Ihrer eigenen Hardware. Ein [Modellprofil](../models.md#a-model-profile) mit [Fallbacks](../models.md#fallbacks) lässt einen Agent ohne erneute Veröffentlichung zu einem anderen Modell oder Provider wechseln.

### Freigabe durch jemand anderen als den Anfragenden { #approval-by-someone-other-than-the-requester }

In Cowork gibt die Person, die die Aufgabe ausführt, schreibende Aktionen frei oder schaltet die automatische Freigabe ein. Die Seiten von Anthropic beschreiben keine Freigabe, die an jemand anderen weitergeleitet wird. In AgenticOS [hält ein Werkzeug mit Nebenwirkungen den Run an](../governance.md#approvals). Die [Benachrichtigung](../governance.md#alerts) geht an die Mitglieder Ihrer Wahl, und nur jemand mit `approvals:decide` kann darüber entscheiden, und zwar einmal.

### Kosten pro Agent, nicht pro Nutzer { #cost-per-agent-not-per-seat }

Claude begrenzt Ausgaben pro Organisation, Gruppe und Benutzer. Ein Budget pro Agent gibt es nicht, weil die Apps kein Agent-Objekt haben. AgenticOS gibt jedem Agent ein [monatliches Budget](../governance.md#budgets), das [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) geprüft wird. Sie sehen, [was jeder Agent ausgegeben hat](../governance.md#what-the-cost-screen-shows), und bezahlen den Provider direkt, ohne Gebühr pro Nutzer.

### Enterprise-Kontrollen ohne Enterprise-Stufe { #enterprise-controls-without-an-enterprise-tier }

Bei Claude sind Audit-Logs, eigene Rollen, SCIM, individuelle Aufbewahrung und die Compliance API nur im Enterprise-Tarif enthalten, mit mindestens 20 Nutzerlizenzen. AgenticOS liefert sie in jeder Bereitstellung: ein [Audit-Log mit Manipulationsnachweis](../governance.md#audit), [Rollen und Grants](../permissions.md#layer-3-visibility-and-grants), die [Zuordnung von Verzeichnisgruppen](../directory.md#directory-group-mappings) und [Aufbewahrung pro Datenklasse](../governance.md#retention). SCIM gibt es noch nicht; siehe [die Lücken](comparison.md#what-agenticos-does-not-do-yet).

### Wissen, das Sie abstimmen können { #knowledge-you-can-tune }

Claude Projects wechseln automatisch zu Retrieval, wenn das Projektwissen wächst, und bieten keine Einstellungen dafür. In AgenticOS wählen Sie [Parser](../file-processing.md#parser-selection-rag), [Chunking](../file-processing.md#chunking-configuration), OCR und Bildbeschreibung pro Sammlung. Dokumente und Vektoren bleiben in [Ihrem Postgres](../file-processing.md#vector-storage), und [Sync-Konnektoren](../howto/configure-sync-sources.md#what-a-sync-removes) halten Sammlungen aktuell.

## Wann Claude allein genügt { #when-claude-alone-is-enough }

- Sie möchten einen starken Assistenten für jeden Mitarbeiter, ohne etwas betreiben zu müssen.
- Cowork, Claude Code, die Office-Add-ins und Chrome unter einer Nutzerlizenz decken Ihren Bedarf ab.
- Sie brauchen die Zertifizierungen von Anthropic, vom Kunden verwaltete Schlüssel oder die Partnerintegrationen seiner Compliance API.
- Sie brauchen heute SAML oder SCIM. AgenticOS bietet OIDC, LDAP und Kerberos, aber noch kein SAML und kein SCIM.

## Beide zusammen nutzen { #use-them-together }

Behalten Sie Claude für die alltägliche Arbeit der Mitarbeiter. Nutzen Sie AgenticOS für die Agents, die einen Verantwortlichen, ein Budget, einen Freigabeschritt oder eine öffentliche Oberfläche brauchen. Fügen Sie ein Anthropic-Modellprofil hinzu und veröffentlichen Sie den Agent: ein Support-Widget, einen Telegram-Bot, einen internen Agent für Richtlinien. Jeder davon läuft auf Claude-Modellen unter Ihrer eigenen Governance.

## Eine Handbuchfrage ausprobieren { #try-one-handbook-question }

Legen Sie das [gemeinsame Dokumentenbeispiel](../howto/first-document-agent.md) in ein Claude Project und in eine AgenticOS-Sammlung, beide auf demselben Claude-Modell. Stellen Sie die beantwortbare Frage und die Frage zur fehlenden Regel, und geben Sie dieselbe Antwort dann jemandem außerhalb der Organisation. Bei Claude braucht das eine Nutzerlizenz; bei AgenticOS ist es ein Link auf eine [gehostete Seite](../channels.md#a-hosted-page). Erfassen Sie mit der [Vergleichsmethode](comparison.md#a-shared-trial), was jedes Produkt erlaubt.

## Quellen { #sources }

- [Claude-Preise](https://claude.com/pricing): Preise pro Nutzer für Team und Enterprise und die Funktionsliste von Enterprise.
- [Was ist der Enterprise-Tarif](https://support.claude.com/en/articles/9797531-what-is-the-enterprise-plan): Nutzung zu API-Preisen abgerechnet, Mindestanzahl an Nutzerlizenzen.
- [Was ist der Team-Tarif](https://support.claude.com/en/articles/9266767-what-is-the-team-plan): Nutzerlizenzen, SSO und Ausgabenobergrenzen.
- [Audit-Logs](https://support.claude.com/en/articles/9970975-access-audit-logs): nur Enterprise, Export über 180 Tage.
- [Modellzugriff](https://support.claude.com/en/articles/15694740-manage-model-access-for-your-organization): nur Claude-Modelle.
- [Cowork in Team und Enterprise](https://support.claude.com/en/articles/13455879-use-claude-cowork-on-team-and-enterprise-plans): Freigaben und Admin-Kontrollen.
- [RAG für Projects](https://support.claude.com/en/articles/11473015-retrieval-augmented-generation-rag-for-projects): automatisches Retrieval in Projekten.
- [Vorstellung von Claude Tag](https://www.anthropic.com/news/introducing-claude-tag): Slack-Beta.
