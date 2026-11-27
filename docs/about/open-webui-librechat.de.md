---
title: "AgenticOS vs Open WebUI und LibreChat"
seo_title: "AgenticOS vs Open WebUI und LibreChat: Chat oder Agents"
description: "Open WebUI, LibreChat und AgenticOS im Vergleich: selbst gehosteter Firmen-Chat gegen eine Plattform für gesteuerte Agents, Lizenzen, Budgets, Kanäle."
source_sha: "041b493e450a"
---

# AgenticOS vs Open WebUI und LibreChat { #agenticos-vs-open-webui-and-librechat }

Open WebUI und LibreChat sind die selbst gehosteten Chat-Oberflächen, die IT-Teams meist zuerst einführen, damit Mitarbeiter keine Firmendaten mehr in private KI-Konten kopieren. Beide sind ausgereift, verbinden sich mit vielen Modellen und ergänzen Werkzeuge, Wissen und Agents. AgenticOS beantwortet eine andere Frage: nicht „welches Chatfenster geben wir den Leuten“, sondern „welche Agents gehören dem Unternehmen, wer verantwortet sie und was dürfen sie ausgeben“.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang: die öffentlichen Repositories, Lizenzdateien und Dokumentation von Open WebUI und LibreChat, keine getesteten Bereitstellungen.

## Auf einen Blick { #at-a-glance }

| Bereich | Open WebUI | LibreChat | AgenticOS |
| --- | --- | --- | --- |
| Was es ist | Eine selbst gehostete KI-Oberfläche mit RBAC, Gruppen, Werkzeugen und RAG | Ein „erweiterter ChatGPT-Klon“ mit Agents, MCP und Skills | Eine Plattform für versionierte Unternehmens-Agents, Workflows, Apps und Tabellen |
| Lizenz | BSD-3 mit Branding-Klausel: Branding-Änderung bis 50 Nutzer in 30 Tagen erlaubt, darüber Enterprise-Lizenz nötig | MIT; das Admin-Panel (eigene Rollen, Gruppen) unter AGPL-3.0 | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Eigentümer | Open WebUI Inc. | ClickHouse, seit November 2025 | Vstorm |
| Anmeldung | OIDC, LDAP und SCIM enthalten | OIDC, SAML und LDAP | OIDC-SSO, LDAP und Kerberos; noch kein SAML oder SCIM |
| Ausgabenkontrolle | Nicht beschrieben | Ein Token-Guthaben pro Nutzer | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | Nicht beschrieben | Vom Nutzer bestätigt | Freigabe pro Capability, Werkzeug und MCP-Verbindung, entschieden von den Personen Ihrer Wahl |
| Lebenszyklus eines Agents | Modelle und Presets | Agents mit Zugriffskontrolllisten | Veröffentlichte Versionen, Umgebungen, Eval-Runs und YAML-Export |
| Kanäle | Nur Web; keine Bots in externen Messengern | Web; Slack in Beta | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe |
| Mandanten | Eine Organisation | Mandantenisolation über ein Proxy-Setup | Viele Organisationen in einer Bereitstellung |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Ein Chatfenster ist kein Agent, der dem Unternehmen gehört { #a-chat-window-is-not-an-agent-the-company-owns }

Beide Chat-Oberflächen lassen eine Person ein Modell oder Preset wählen und damit sprechen. In AgenticOS hat ein Agent einen Besitzer, eine [veröffentlichte Version](../concepts.md#version), [Umgebungen](../environments.md#what-an-environment-is), [Eval-Runs](../evals.md) gegen ein versioniertes Dataset und einen Spec, der sich [als YAML exportieren](../features.md#exportable-into-your-own-repository) lässt. Wenn sich der Agent ändert, wissen Sie, wer ihn geändert hat, können ihn vor dem Veröffentlichen testen und zurückrollen.

### Ausgaben und Freigaben pro Agent { #spend-and-approvals-per-agent }

Ein [Budget](../governance.md#budgets) in AgenticOS stoppt die nächste Modellanfrage eines Agents, wenn seine Obergrenze oder die der Organisation erreicht ist; LibreChat zählt ein Guthaben pro Nutzer, und Open WebUI beschreibt keine Ausgabengrenze. Ein Werkzeugaufruf kann auf die [Freigabe](../governance.md#approvals) durch jemand anderen als die chattende Person warten, und jede Entscheidung steht im [Audit-Log mit Manipulationsnachweis](../governance.md#audit).

### Derselbe Agent dort, wo Menschen schon arbeiten { #the-same-agent-where-people-already-work }

Ein veröffentlichter AgenticOS-Agent antwortet in [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), per [E-Mail](../channels.md#email), in einem [Website-Widget](../channels.md#the-website-widget) und über die [HTTP-API](../channels.md#the-public-api), nicht nur in seiner eigenen Weboberfläche. Die [Desktop-](../desktop.md) und [Telefon-App](../mobile.md) ergänzen Quick Ask und Freigaben unterwegs.

### Lizenzbedingungen ohne Branding-Klauseln { #licence-terms-without-branding-conditions }

Die Lizenz von Open WebUI verbietet Branding-Änderungen ab 50 Nutzern in 30 Tagen ohne Enterprise-Lizenz. Der Kern von LibreChat ist MIT, das Admin-Panel mit eigenen Rollen und Gruppen aber AGPL-3.0. AgenticOS steht unter Apache-2.0. Siehe [Lizenzbedingungen im Vergleich](licence-terms.md).

## Wann Open WebUI oder LibreChat besser passt { #when-open-webui-or-librechat-is-the-better-fit }

- Sie brauchen einen Firmen-Chat mit Modellwahl für alle Mitarbeiter, und Agents mit Besitzern und Budgets sind noch nicht das Ziel.
- Sie brauchen SAML oder SCIM heute. Open WebUI enthält SCIM und LibreChat SAML; AgenticOS hat beides noch nicht.
- Ihre Nutzer betreiben lokale Modelle über Ollama und schätzen die große Community dieser Oberflächen.

Beide können auch nebeneinander bestehen: Behalten Sie eine Chat-Oberfläche für den Alltag und betreiben Sie Unternehmens-Agents in AgenticOS, erreichbar über die [HTTP-API](../channels.md#the-public-api) und als [MCP-Server](../mcp.md#agenticos-as-an-mcp-server).

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Wählen Sie eine Aufgabe, die etwas verändert, etwa das Anlegen eines Tickets. Konfigurieren Sie sie in beiden Produkten, geben Sie sie zwei Teams, verlangen Sie die Freigabe einer zweiten Person und begrenzen Sie die Ausgaben. Ändern Sie dann die Instruktionen und prüfen Sie, wer sehen kann, was sich wann geändert hat. Halten Sie die Ergebnisse nach der [Vergleichsmethode](comparison.md#a-shared-trial) fest.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS ein selbst gehostetes ChatGPT wie Open WebUI? { #is-agenticos-a-self-hosted-chatgpt-like-open-webui }

Es enthält einen Web-Chat, ist aber um Unternehmens-Agents herum gebaut: jeder mit Besitzer, Versionen, Budget, Freigaben und Kanälen. Open WebUI und LibreChat sind um die Chat-Oberfläche selbst herum gebaut.

### Kann ich Open WebUI behalten und AgenticOS ergänzen? { #can-i-keep-open-webui-and-add-agenticos }

Ja. Viele Teams behalten eine Chat-Oberfläche und betreiben daneben gesteuerte Agents. AgenticOS-Agents antworten über die HTTP-API, Slack, Teams und die anderen Oberflächen, und AgenticOS ist zudem ein MCP-Server.

### Welche Lizenz ist freizügiger? { #which-licence-is-more-permissive }

Der eigene Code von AgenticOS steht unter Apache-2.0, ohne Enterprise-Verzeichnis und Branding-Klausel; enthaltene Komponenten behalten ihre Lizenzen, und der Standard-PDF-Parser steht unter AGPL-3.0 ([Details](../licenses.md#the-agpl-component)). Der Kern von LibreChat ist MIT mit einem Admin-Panel unter AGPL-3.0. Die BSD-3-Lizenz von Open WebUI ergänzt eine Branding-Klausel ab 50 Nutzern.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs DIY-Stack](diy-stack.md) · [AgenticOS vs Onyx](onyx.md) · [AgenticOS vs LobeHub](lobehub.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Open-WebUI-Repository](https://github.com/open-webui/open-webui) und [Lizenz](https://docs.openwebui.com/license): Funktionen, Anmeldeoptionen und die Branding-Klausel.
- [LibreChat-Repository](https://github.com/LibreChat-AI/LibreChat): Agents, MCP, Anmeldeoptionen und das AGPL-3.0-Admin-Panel.
- [LibreChat-Guthabeneinstellungen](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/balance): Token-Guthaben pro Nutzer.
- [ClickHouse übernimmt LibreChat](https://clickhouse.com/blog/clickhouse-acquires-librechat): Eigentümer seit November 2025.
