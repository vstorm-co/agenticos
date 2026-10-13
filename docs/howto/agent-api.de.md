---
source_sha: "dbf40f028eaa"
title: "Einen Agent aus Ihrer eigenen Anwendung aufrufen"
description: "Authentifizieren Sie sich, senden Sie den Organisations-Header und führen Sie einen veröffentlichten Agent über HTTP aus. Danach lesen Sie denselben Fehlerumschlag, dasselbe Budget und dasselbe Rate-Limit, die jede andere Oberfläche bekommt."
---

# Einen Agent aus Ihrer eigenen Anwendung aufrufen { #call-an-agent-from-your-own-application }

Rufen Sie einen veröffentlichten Agent so auf, wie es die Konsole, Slack und jede andere Oberfläche tun: mit einem authentifizierten `POST`, der durch denselben Runner, dieselbe Budgetprüfung und dieselbe Genehmigungsschranke läuft. Diese Seite geht die [HTTP-API](../api.md) mit einem kleinen Agent durch und zeigt echte, gekürzte Antworten von ihm. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil und ein Mitgliedskonto zum Anmelden.
- Einen veröffentlichten Agent ohne Capability, die ein Konto braucht, das Sie nicht haben. Der festgehaltene Run unten nutzt einen Agent ganz ohne Capabilities, sodass hier nichts von einer Sandbox, einer Sammlung oder einer MCP-Verbindung abhängt.

## Den Agent bauen { #build-the-agent }

Erstellen Sie unter **Agents → New agent** einen Agent, wählen Sie Ihr Modellprofil, lassen Sie die Toolbox leer, setzen Sie ein kleines Budget und Schrittlimit und kurze Instruktionen:

```text
You are a small support assistant reachable over the HTTP API.
Answer briefly, in two or three sentences.
If asked something you cannot know, say so plainly rather than guessing.
```

Klicken Sie auf **Publish** und kopieren Sie seine ID aus der URL oder aus `GET /agents`.

## Authentifizieren und ausführen { #authenticate-and-run-it }

Melden Sie sich für ein Access-Token an und rufen Sie dann den Run-Endpunkt mit dem Token und dem Organisations-Header auf:

```bash
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL&password=$PASSWORD" | jq -r .access_token)

curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "In one sentence, what is a model profile?"}'
```

```python
import httpx

login = httpx.post(f"{BASE}/api/v1/auth/login",
                    data={"username": EMAIL, "password": PASSWORD})
token = login.json()["access_token"]

resp = httpx.post(
    f"{BASE}/api/v1/agents/{AGENT_ID}/run",
    headers={"Authorization": f"Bearer {token}", "X-Organization-Id": ORG_ID},
    json={"prompt": "In one sentence, what is a model profile?"},
)
resp.raise_for_status()
print(resp.json()["output"])
```

`X-Organization-Id` entscheidet, in welchem Mandanten der Aufruf läuft. Siehe [den Organisations-Header](../api.md#the-organization-header). Ein `X-API-Key`-Header funktioniert genauso für einen Dienst, hinter dem keine Person steht. Die beiden Aufrufe oben nutzen das JWT eines Mitglieds.

## Stattdessen streamen { #stream-it-instead }

`ws://…/api/v1/ws/agent` ist derselbe authentifizierte Socket, den der Chat der Konsole selbst nutzt. Das Token steht im Subprotokoll (`access_token.<JWT>` und `chat`) statt in einem Header, weil ein `WebSocket` im Browser keinen setzen kann. Ein Frame enthält `message`, `agent_id` und optional `conversation_id`. Der Socket antwortet mit `text_delta`-Ereignissen, während das Modell schreibt, mit `tool_call` und `tool_result` für jeden Schritt, mit `tool_approval_required`, wenn etwas geparkt wird, und am Ende mit `complete` samt der Nutzung des Runs. Siehe [Streaming](../api.md#streaming).

## Fehler, Budgets und Rate-Limits behandeln { #handle-errors-budgets-and-rate-limits }

Jede Ablehnung kommt im selben Umschlag zurück, `error.code`, `error.message` und `error.details`:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "prompt: Field required",
  "details": {"fields": [{"field": "prompt", "message": "Field required"}]}}}
```

Ein Run, den dieser Endpunkt annimmt, durchläuft trotzdem die Governance: Das [Budget](../governance.md#budgets) wird vor der Modellanfrage geprüft, und der Run schlägt fehl, statt zu viel auszugeben. Ein geschütztes Tool [parkt zur Genehmigung](../governance.md#approvals) genau wie im Chat. Ein API-Aufrufer kann keines davon überspringen. Die Route selbst hat ein Rate-Limit statt einer Berechtigungsschranke, gezählt pro Aufrufer: standardmäßig 30 Runs pro Minute (`RATE_LIMIT_RUN_PER_MINUTE`), abgelehnt mit der Bitte zu warten statt in eine Warteschlange gestellt.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Ein normaler Run | `status: "completed"`, ein `output`-String, `cost_usd` und Token-Zahlen |
| Kein `Authorization`-Header | `401`, `www-authenticate: Bearer` |
| Ein falscher `X-Organization-Id` | `404`, `NOT_FOUND`, dieselbe Form wie bei einem Agent, der nicht existiert |
| Eine unbekannte `agent_id` | `404`, mit `agent_id` in `details` |
| Ein Body ohne `prompt` | `422` (`VALIDATION_ERROR`), `details.fields` nennt das Feld |
| Zwei Organisationen, ein Aufrufer | Der Run sieht immer nur den Mandanten, den der Header dieses Aufrufs nennt |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, Agent `uc-api-demo`. `POST /run` mit einem echten Prompt antwortete `{"status": "completed", "cost_usd": "0.000582", "output": "A model profile is a structured description of an AI model's key characteristics, capabilities, limitations, and intended use cases."}`.

    Das Weglassen von `X-Organization-Id` lehnte den Aufruf hier **nicht** ab: Die API fiel auf die persönliche Organisation des angemeldeten Mitglieds zurück und führte den Run dort aus, statt mit "no tenant to act in" zu antworten. Eine erfundene Organisations-ID kam als `404` mit `"Organization not found or access denied"` zurück. Ohne `Authorization` kam `401` mit `www-authenticate: Bearer`. Ein leerer Body kam als `422` mit `details.fields: [{"field": "prompt", "message": "Field required"}]` zurück, genau wie im Umschlag oben.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **`404` für eine Agent-ID, von der Sie wissen, dass sie existiert.** Prüfen Sie zuerst den Organisations-Header. Ein mandantenübergreifender Lesezugriff antwortet absichtlich mit `404`, identisch mit einem fehlenden Agent.
- **`429` mitten im Integrationstest.** Das Rate-Limit der Run-Route gilt pro Aufrufer, nicht pro Agent. Warten Sie, statt sofort erneut zu senden.
- **Ein Run antwortet, erreicht aber nie ein aktiviertes Tool.** Prüfen Sie Activity auf eine geparkte Genehmigung. Der HTTP-Pfad parkt genau wie der Chat, und `POST /run` setzt sich nicht selbst fort.
- **Die angezeigten Kosten stimmen nicht mit dem Dashboard Ihres Anbieters überein.** `cost_is_partial` in der Antwort sagt, ob die Zahl eine Untergrenze statt eines Endwerts ist. `true` bedeutet, dass ein Teil des Runs nicht bepreist werden konnte.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie Anfrage und Antwort für jede Prüfung, die Agent-Version und das Modellprofil auf. Ein Mensch entscheidet weiterhin, welche Capability ein Server-zu-Server-Agent haben darf, ob er einen eigenen API-Schlüssel statt eines geteilten braucht und welches Budget ihn begrenzt. Der Endpunkt setzt diese Entscheidungen durch, er trifft sie nicht.

## Nächste Schritte { #next-steps }

Für ein Token, das niemand erneuern muss, verwenden Sie einen API-Schlüssel statt einer Anmeldung per JWT. [Authentifizierung](../api.md#authenticating) beschreibt beides. Wie die Tool-Aufrufe und Kosten eines Runs im Produkt aussehen, zeigt [Governance](../governance.md#budgets).
