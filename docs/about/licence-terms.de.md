---
title: "Lizenzbedingungen im Vergleich"
seo_title: "Lizenzbedingungen: Open-Source-Plattformen für KI-Agents"
description: "Welche KI-Agent-Plattformen sind ohne Bedingungen Open Source? Apache-2.0 im Vergleich mit modifiziertem Apache, Elastic License 2.0, Sustainable Use und ee."
source_sha: "733a5072cfd8"
---

# Lizenzbedingungen im Vergleich { #licence-terms-compared }

„Open Source“ auf einer Produktseite heißt oft öffentlicher Code mit Bedingungen. Für ein Unternehmen, das die Software ändern will, oder einen Integrator, der eine Instanz für mehrere Kunden betreiben will, entscheiden diese Bedingungen, was erlaubt ist. Diese Seite ordnet die Plattformen aus diesen Vergleichen danach, was ihre Lizenz erlaubt, mit der maßgeblichen Klausel zitiert oder zusammengefasst aus der Lizenzdatei.

Verantwortlich: das AgenticOS-Team. Lizenzdateien geprüft am 26. November 2026 im Hauptrepository jedes Projekts. Dies ist eine Zusammenfassung zur Orientierung, keine Rechtsberatung; lesen Sie die Lizenz selbst, bevor Sie sich darauf verlassen.

## Die Klassen auf einen Blick { #the-classes-at-a-glance }

| Klasse | Was sie erlaubt | Projekte |
| --- | --- | --- |
| Freizügige OSI-Lizenz, nichts zurückgehalten | Nutzen, ändern, unter eigener Marke führen und für andere hosten | **AgenticOS** (Apache-2.0), Agno-Framework, Sim, OpenAgents, RAGFlow, LangBot (Apache-2.0); LibreChat-Kern, AnythingLLM, Langflow, Hermes Agent, OpenClaw (MIT) |
| Copyleft | Nutzen und ändern; verbreitete Änderungen, bei AGPL auch die Netzwerknutzung, müssen unter derselben Lizenz geteilt werden | OpenHuman, MaxKB (GPL-3.0); Khoj, Cherry Studio, Nextcloud (AGPL-3.0); das Admin-Panel von LibreChat (AGPL-3.0) |
| Open Core mit Enterprise-Verzeichnis | Der Kern ist freizügig; Funktionen in `ee`- oder `enterprise`-Verzeichnissen brauchen eine kommerzielle Lizenz | Onyx, LiteLLM, Langfuse, Activepieces, Chatwoot, Mastra, Windmill |
| Modifiziertes Apache 2.0 | Apache 2.0 plus Bedingungen zu Mandantenbetrieb oder Branding | Dify, FastGPT |
| Source-available | Öffentlicher Code unter Bedingungen, die konkurrierende oder gehostete Nutzung verbieten | Kortix CompanyOS (Elastic License 2.0), n8n (Sustainable Use License), AutoGPT Platform (Polyform Shield), Arize Phoenix (Elastic License 2.0) |
| Eigene Lizenz mit Bedingungen | Öffentlicher Code mit zusätzlichen kommerziellen oder Branding-Bedingungen | LobeHub (LobeHub Community License), Open WebUI (BSD-3 mit Branding-Klausel), NocoBase (eigener Lizenzvertrag) |

Unter den Open-Source-Plattformen für Unternehmens-Agents und den selbst gehosteten Buildern ist eine Lizenz ohne Bedingungen und ohne Enterprise-Verzeichnis die Minderheit.

## Die maßgeblichen Klauseln { #the-clauses-that-matter }

### Kortix CompanyOS: Elastic License 2.0 { #kortix-companyos-elastic-license-20 }

Sie dürfen die Software Dritten nicht als gehosteten oder verwalteten Dienst bereitstellen und die Funktion des Lizenzschlüssels nicht verschieben, ändern, deaktivieren oder umgehen. Das Repository stand bis Dezember 2025 unter Apache-2.0 und wechselte am 18. Februar 2026 zur Elastic License 2.0. Siehe [AgenticOS vs Kortix](kortix.md).

### Dify: Apache 2.0 mit Bedingungen { #dify-apache-20-with-conditions }

Der Betrieb einer mandantenfähigen Umgebung, in der ein Mandant ein Workspace ist, braucht eine schriftliche Genehmigung, und Logo und Copyright-Hinweise im Frontend dürfen nicht entfernt oder geändert werden. Siehe [AgenticOS vs Dify](dify.md).

### n8n: Sustainable Use License { #n8n-sustainable-use-license }

Die Nutzung ist auf interne Geschäftszwecke, nicht kommerzielle oder private Nutzung beschränkt. Kostenpflichtige Funktionen liegen in `.ee.`-Dateien und brauchen einen Lizenzschlüssel. Siehe [AgenticOS vs n8n](n8n.md).

### LobeHub: LobeHub Community License { #lobehub-lobehub-community-license }

Kommerzielle Nutzung ist als Frontend- und Backend-Dienst ohne Änderung des Quellcodes erlaubt. Ein abgeleitetes Werk zu entwickeln und zu verbreiten braucht eine kommerzielle Lizenz, und Mitwirkende stimmen zu, dass der Hersteller die Bedingungen verschärfen darf. Siehe [AgenticOS vs LobeHub](lobehub.md).

### Open WebUI: BSD-3 mit Branding-Klausel { #open-webui-bsd-3-with-a-branding-clause }

Branding ändern oder entfernen ist nur für Bereitstellungen mit höchstens 50 Nutzern in einem Zeitraum von 30 Tagen erlaubt; darüber ist eine Enterprise-Lizenz nötig. Siehe [AgenticOS vs Open WebUI und LibreChat](open-webui-librechat.md).

### Onyx, LiteLLM, Langfuse: Enterprise-Verzeichnisse { #onyx-litellm-langfuse-enterprise-directories }

Der Kern ist MIT. Code in den `ee`- oder `enterprise`-Verzeichnissen steht unter einer kommerziellen Lizenz; bei Onyx braucht sein Produktionseinsatz eine Lizenz für die Zahl der Arbeitsplätze. Meist liegen dort Single Sign-on, SCIM, eigene Rollen und Audit-Funktionen. Siehe [AgenticOS vs Onyx](onyx.md) und [AgenticOS vs DIY-Stack](diy-stack.md).

### AutoGPT Platform: Polyform Shield { #autogpt-platform-polyform-shield }

Das Verzeichnis `autogpt_platform` steht unter der Polyform-Shield-Lizenz, die verbietet, es zur Konkurrenz mit dem Lizenzgeber zu nutzen; der Rest des Repositorys ist MIT.

## AgenticOS { #agenticos }

AgenticOS steht unter Apache-2.0, ohne Enterprise-Verzeichnis und ohne Funktion, die für eine bezahlte Edition zurückgehalten wird. Sie dürfen es ändern, unter eigener Marke führen und für andere Organisationen aus einer Bereitstellung betreiben. Einige enthaltene Komponenten haben eigene Lizenzen: Der Standard-PDF-Parser steht unter AGPL-3.0, ein geändertes Image, das Sie anderen bereitstellen, verpflichtet Sie also, ihnen den Quellcode zu geben. Die [Lizenzseite](../licenses.md) listet jede Komponente, und [die AGPL-Komponente](../licenses.md#the-agpl-component) erklärt die Ausnahme.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Welche KI-Agent-Plattformen sind vollständig Open Source? { #which-ai-agent-platforms-are-fully-open-source }

Unter den hier verglichenen nutzen AgenticOS, das Agno-Framework, Sim, OpenAgents, der LibreChat-Kern, AnythingLLM und Langflow OSI-Lizenzen ohne Enterprise-Verzeichnis. Dify, n8n, Kortix, LobeHub und Open WebUI fügen Bedingungen hinzu.

### Darf ein Integrator AgenticOS für mehrere Kunden hosten? { #can-an-integrator-host-agenticos-for-several-clients }

Ja. Apache-2.0 erlaubt es, und Organisationen in einer Bereitstellung sind isolierte Mandanten. Die Lizenzen von Dify und FastGPT verlangen für mandantenfähige Nutzung eine Genehmigung, und die Elastic License 2.0 verbietet, Kortix als gehosteten Dienst anzubieten.

### Ersetzt diese Seite eine rechtliche Prüfung? { #does-this-page-replace-a-legal-review }

Nein. Lizenzen ändern sich, wie die von Kortix dreimal in einem Jahr. Lesen Sie die Lizenzdatei der Version, die Sie bereitstellen.

## Verwandte Vergleiche { #related-comparisons }

[Alle Vergleiche](comparison.md) · [Lizenzen der AgenticOS-Komponenten](../licenses.md)

## Quellen { #sources }

- [Kortix-Lizenz](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) · [Dify-Lizenz](https://github.com/langgenius/dify/blob/main/LICENSE) · [n8n-Lizenz](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- [LobeHub-Lizenz](https://github.com/lobehub/lobehub/blob/main/LICENSE) · [Open-WebUI-Lizenz](https://docs.openwebui.com/license) · [Onyx-Lizenz](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE)
- [Langfuse-Lizenz](https://github.com/langfuse/langfuse/blob/main/LICENSE) · [LiteLLM Enterprise](https://docs.litellm.ai/docs/enterprise) · [AutoGPT-Lizenz](https://github.com/Significant-Gravitas/AutoGPT/blob/master/LICENSE)
