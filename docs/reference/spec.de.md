---
source_sha: "892833d0bab5"
---

# Der Agent-Spec { #the-agent-spec }

Der tragendste Typ der Plattform: der Builder bearbeitet ihn, die Datenbank
versioniert ihn, die Factory instanziiert ihn, und Kunden exportieren ihn als
YAML in ihre eigenen Git-Repositories.

Aus der Quelle generiert, weil die Begründung in den Docstrings steht — und
deshalb bleibt die generierte Felddokumentation unten englisch.

::: app.agents.spec.AgentSpec

## Variablen { #variables }

`{{name}}` in `instructions` wird zu Beginn jedes Runs ausgefüllt: mit einer
Systemvariable, die die Plattform kennt (Datum und Uhrzeit, die angemeldete
Person und ihre [Gruppen](../departments.md), die Organisation, der Agent, der
Kanal), oder mit einer der eigenen
`variables` des Agents. `time_zone` bestimmt, welche Uhr `{{current_time}}` liest.
Die Veröffentlichung lehnt einen Namen ab, der keines von beiden ist.

::: app.agents.spec.PromptVariableSpec

## Delegation { #delegation }

Zwei Formen, und [Konzepte](../concepts.md#delegate-vs-inline-specialist)
erklärt, zu welcher man greift. `subagents` hält die erste; die zweite steht in
der Konfiguration der [Capability `subagents`](capabilities.md#delegation)
selbst.

::: app.agents.spec.SubagentRef

`external_agents` nennt in der Organisation registrierte Remote Agents über A2A, die die
[Delegation](capabilities.md#remote-agents) neben diesen aufruft.

::: app.agents.spec.ExternalAgentRef

::: app.agents.spec.SpecialistSpec

## Budgets { #budgets }

::: app.agents.spec.BudgetSpec

## Benachrichtigungen { #alerts }

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Modelleinstellungen { #model-settings }

::: app.agents.spec.ModelSettingsSpec

## Observability { #observability }

::: app.agents.spec.ObservabilitySpec

## Spracherkennung { #speech-to-text }

Der Anbieter, das Modell, der Schlüssel und die Sprache, mit denen das Diktieren
an einen Agent und die von ihm geerbten Sprachnachrichten aus Kanälen
transkribiert werden, wo sie von denen der Organisation abweichen. Der Schlüssel
ist die ID eines Vault-Secrets, nie der Schlüssel selbst.
[ML-Dienste](../ml-services.md#which-engine-a-recording-reaches) nennt die
Reihenfolge, in der sie sich auflösen. Ein Spec, der diesen Block trägt, lässt
sich nicht in ein Deployment importieren, das älter ist als der Block: dessen
Spec lehnt Felder ab, die er nicht kennt.

::: app.agents.spec.SpeechToTextSpec

## Stimme { #voice }

Wie der Agent einen [Sprachanruf](../voice.md) führt: das Realtime-Modell, der
Vault-Schlüssel, die Stimme und die eigenen Limits des Anrufs. Optional, und ein
vollständig leerer Block gilt als kein Block, also laden Specs, die vor ihm
geschrieben wurden, unverändert, und `SPEC_VERSION` hat sich nicht bewegt. Wie
beim Block zur Spracherkennung lässt sich ein Spec, der ihn trägt, nicht in ein
Deployment importieren, das älter ist als der Block.

| Feld | Was es hält |
|---|---|
| `provider` | Ein Provider aus dem Realtime-Katalog: `openai`, `azure`, `google` oder `xai` |
| `model` | Ein Realtime-Modell dieses Providers. Für Azure leer lassen und die beiden folgenden Felder verwenden |
| `deployment` | Nur Azure: der Name des Deployments, an das Anrufe gehen |
| `base_model` | Nur Azure: das Katalogmodell, das dieses Deployment ausführt und das seine Stimmen und seinen Preis bestimmt |
| `secret_id` | Der Vault-Schlüssel, mit dem Anrufe gehalten werden - eine ID, nie der Schlüssel |
| `voice` | Eine der Stimmen des Modells; leer verwendet die Standardstimme des Modells |
| `language` | Ein ISO-639-1-Code der Sprache, die der Agent spricht; leer folgt dem Anrufer |
| `max_call_seconds` | Der längste Anruf, 60 bis 3000; leer sind 600 (10 Minuten) |
| `voice_note` | Bis zu 1000 Zeichen, die nur in Anrufen an die Anweisungen des Agents angehängt werden |

Jede Regel, die mehrere Felder umfasst, wird beim Veröffentlichen der Version
geprüft, nicht beim Speichern des Entwurfs, denn der Builder speichert
automatisch zwischen der Wahl eines Providers und der Wahl seines Modells. Das
Veröffentlichen wird abgelehnt, unter Nennung des Abschnitts Stimme (Voice), wenn:

- ein Provider fehlt oder der Katalog dieses Deployments keinen solchen Provider
  hat;
- das Modell fehlt oder kein Realtime-Modell ist, das der Katalog für diesen
  Provider anbietet (bei Azure das Basismodell), oder ein Azure-Abschnitt kein
  Deployment benennt;
- die Stimme keine der Stimmen des Modells ist;
- kein Schlüssel gewählt ist oder der Schlüssel die gemeinsame Prüfung nicht
  besteht: Sein Zweck ist nicht der Provider, seine Art ist nicht die des
  Providers (`api_key`, oder `azure_openai` für Azure), er gehört einer anderen
  Organisation, oder der Veröffentlichende kann ihn nicht sehen;
- die Sprache kein Code ist, den Anrufe annehmen.

Capabilities, die ein Anruf nicht ausführen kann, blockieren das Veröffentlichen
nicht; sie werden aus Anrufen weggelassen, und der Builder listet sie auf.

::: app.agents.spec.VoiceSpec
