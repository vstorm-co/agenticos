---
source_sha: "67523cafdf32"
---

# Die HTTP-API { #the-http-api }

Alles, was die Konsole tut, tut sie über diese API. Es gibt keine private
Oberfläche: dieselben Endpunkte stehen Ihnen offen.

Die interaktive Referenz wird aus dem Code erzeugt und vom Deployment selbst
unter **`/docs`** ausgeliefert, das Schema unter `/api/v1/openapi.json`. Beides
ist in der Entwicklung an und in der Produktion aus — `ENVIRONMENT` entscheidet
darüber, damit ein Produktions-Deployment nicht seine eigene Routenliste
veröffentlicht.

## Authentifizierung { #authenticating }

Drei Wege hinein, für drei verschiedene Aufrufer.

| | Header | Für |
|---|---|---|
| **API-Schlüssel der Organisation** | `Authorization: Bearer aos_…` | Ein Skript, einen HTTP-Client wie Postman oder einen MCP-Client. Handelt als das Mitglied, das ihn ausgestellt hat, beschränkt auf die Berechtigungen, mit denen er ausgestellt wurde |
| **JWT** | `Authorization: Bearer <access token>` | Eine Person oder etwas, das für sie handelt. Kurzlebig, erneuert mit einem Refresh-Token |
| **Sitzungs-Cookie** | von der Konsole gesetzt | Nur den Browser — das Token ist HttpOnly und erreicht nie JavaScript |

### API-Schlüssel der Organisation { #organization-api-keys }

Ein Schlüssel wird von einem Mitglied in einer Organisation ausgestellt, unter
**Einstellungen → API** (oder mit `POST /api/v1/api-keys` aus einer
angemeldeten Sitzung). Er trägt die Befugnisse dieses Mitglieds, zweifach
eingeschränkt:

- **Auf die Berechtigungen, mit denen er ausgestellt wurde.** Wählen Sie eine
  Vorlage — *Nur lesen*, *Wissen einspeisen*, *Voller Zugriff* — oder haken Sie
  Berechtigungen aus dem [Katalog](permissions.md) an. Sie können nur vergeben,
  was Sie selbst haben.
- **Auf das, was der Aussteller jetzt darf.** Jede Anfrage liest die Mitgliedschaft
  des Ausstellers neu, sodass eine Herabstufung jeden seiner Schlüssel sofort
  einschränkt. Seine Entfernung aus der Organisation, oder sein Austritt, widerruft
  jeden von ihm ausgestellten Schlüssel und jede von ihm verbundene App - endgültig,
  sodass eine erneute Einladung keinen davon wieder weckt. Eine Freigabe auf einer Ressource erweitert, was eine *Person*
  mit einer Zeile tun darf; einen Schlüssel erweitert sie nie über seine
  Berechtigungen hinaus.

Der Schlüssel wird **einmal** angezeigt, in der Antwort, die ihn erstellt.
Gespeichert wird nur sein SHA-256, und er erscheint nie in einer Logzeile, einem
Audit-Eintrag oder einem Fehlertext. Listen zeigen sein Präfix (`aos_1a2b3c4d`),
und so nennt auch ein Audit-Eintrag den Schlüssel, der gehandelt hat — jeder
Eintrag, der während einer mit einem Schlüssel authentifizierten Anfrage
geschrieben wird, trägt `via_api_key` in seinen Details. Ein Schlüssel kann ein
Ablaufdatum haben, und sein Widerruf (`DELETE /api/v1/api-keys/{id}`) wirkt ab
seiner nächsten Anfrage.

**Ein Schlüssel ist nicht die Person, die ihn ausgestellt hat.** Ein Run, den er
startet, gehört der ausstellenden Person, läuft über ihr Budget und ihr Audit,
erreicht aber nichts Persönliches von ihr: kein
[Gedächtnis](reference/capabilities.md#whose-notes-and-who-may-hear-them), keine
Suche in ihren früheren Unterhaltungen, keine Seiten, auf denen der Browser ihre
Anmeldungen hält, und keinen benutzerbezogenen Sandbox-Arbeitsbereich. Wer den
Schlüssel hält, ist ein Skript, nicht diese Person, also antwortet der Run wie
auf einem öffentlichen Widget.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Zwei Ablehnungen sollten Sie kennen:

- **`403` "API keys are not accepted on this endpoint"** — Schlüssel werden nur in
  der öffentlichen API angenommen: Agents, Runs und Freigaben, Wissensbasen und
  RAG, Skills, Kontextdateien, Projekte, Apps, die ML-Dienste, `/me/permissions`
  sowie Mitglieder, Einladungen, Gruppen und Einstellungen einer Organisation.
  Die eigenen Routen der Konsole, Ihr Konto, das Verlassen oder Übergeben einer
  Organisation und die Schlüsselverwaltung selbst bleiben Sitzungen vorbehalten,
  damit ein geleakter Schlüssel keinen Nachfolger erzeugen kann.
- **`401` "Invalid, expired or revoked API key"** — derselbe Satz in jedem Fall,
  damit ein falscher Schlüssel nichts darüber erfährt, welche Schlüssel existieren.

Jeder Schlüssel hat außerdem sein eigenes Limit, `RATE_LIMIT_API_KEY_PER_MINUTE`
Anfragen pro Minute (standardmäßig 600), und ein Run oder ein ML-Aufruf, den er
auslöst, zählt gegen diese Limits für den Schlüssel statt für seinen Aussteller. Beide
Prüfungen laufen, bevor der Schlüssel nachgeschlagen wird, bei einer Anfrage wie beim
Öffnen eines WebSockets: Ein Schlüssel wird nach einem Digest des ganzen Tokens
gezählt - nie nach seinem Präfix, das Listen zeigen - und eine Adresse, die bereits
`RATE_LIMIT_AUTH_PER_MINUTE` nicht existierende Schlüssel geschickt hat, erhält bis
zum Ende ihrer Minute `429` ohne Nachschlagen.

### Ohne Browser { #without-a-browser }

Ein Skript kann sich seinen eigenen Schlüssel holen, ohne dass eine Konsole offen
ist. Melden Sie sich mit einem Formular-Body an (der OAuth2 Password Grant, JSON
bekommt also `422`), wählen Sie die Organisation, stellen Sie den Schlüssel mit
dem Session-Token aus und widerrufen Sie ihn genauso, wenn er fertig ist:

```bash
SESSION=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL" --data-urlencode "password=$PASSWORD" | jq -r .access_token)

ORG_ID=$(curl -s "$BASE/api/v1/orgs" -H "Authorization: Bearer $SESSION" \
  | jq -r '[.items[] | select(.is_personal)][0].id')

curl -s -X POST "$BASE/api/v1/api-keys" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "nightly import", "scopes": ["collections:view", "collections:edit"]}'
# -> {"id": "...", "key": "aos_...", "prefix": "aos_1a2b3c4d", ...}

curl -s -X DELETE "$BASE/api/v1/api-keys/$KEY_ID" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID"
```

`GET /api/v1/api-keys/scopes` listet, was das angemeldete Mitglied einem
Schlüssel geben darf, und die Presets darüber. Ein Deployment, das Menschen nur
über SSO anmeldet, hat kein Passwort zum Senden; dort stellt ein Mitglied den
Schlüssel in der Konsole aus.

[`examples/public-api.sh`](examples/public-api.sh) ist der ganze Weg als ein
Skript: Es stellt einen Nur-Lese-Schlüssel aus, listet damit Agents und Runs,
zeigt das `403` für eine Route außerhalb der Berechtigungen des Schlüssels, führt
einen Agent aus und liest den Run zurück, wenn `AGENT_ID` gesetzt ist, und
widerruft den Schlüssel am Ende.

```bash
BASE=http://localhost:8000 EMAIL=you@example.com PASSWORD=... bash docs/examples/public-api.sh
```


### Sessions und Widerruf { #sessions-and-revocation }

Ein JWT-Access-Token ist an die Session gebunden, die seine Anmeldung geöffnet
hat — die Id der Session reist im Token mit. Eine Abmeldung überall
(`DELETE /sessions`) deaktiviert diese Sessions, und ein gebundenes Token wird
danach bei der nächsten Verwendung abgelehnt, statt seine wenigen verbleibenden
Minuten auszuleben. Das erreicht auch ein offenes Chat-WebSocket: der nächste
Frame auf einer widerrufenen Session schließt den Socket, nicht erst die nächste
HTTP-Anfrage.

Ein Refresh startet keine neue Session — das Refresh-Token rotiert an Ort und
Stelle und das Access-Token nennt weiterhin dieselbe —, sodass eine langlebige
Verbindung von einem routinemäßigen Refresh nicht gekappt wird.

## Der Organisations-Header { #the-organization-header }

**Ein API-Schlüssel handelt in seiner eigenen Organisation** und braucht keinen
Header. `X-Organization-Id` mit einem Schlüssel zu senden ist nur erlaubt, wenn
er dieselbe Organisation nennt; nennt er eine andere, antwortet die API mit `400`
und `details.header = "X-Organization-Id"`, statt den Tenant zu wechseln.

**Ein Sitzungs-Token nimmt den Tenant aus `X-Organization-Id`.** Ein Aufrufer,
der drei Organisationen angehört, ist in jeder ein anderer Akteur, mit einer
anderen Rolle und anderen Freigaben, also senden Sie den Header bei jeder Anfrage.
Fehlt er, fällt die Anfrage auf die **persönliche Organisation** des Aufrufers
zurück — ein Skript, das ihn vergisst, handelt dort, mit den Agents, Freigaben
und dem Budget dieser Organisation, und bekommt keinen Fehler. Senden Sie den
falschen, erhalten Sie eine Ablehnung, die genau wie eine nicht existierende
Ressource aussieht — absichtlich, damit sich IDs nicht abtasten lassen.

## Einen Agent ausführen { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

Die Antwort trägt die Id des Runs, die Ausgabe, den Status, die Tokens und die
Kosten. `environment_id` im Body wählt, [welche Umgebung](environments.md)
antwortet.

**Ein Run setzt eine Unterhaltung fort.** Ein Aufruf ohne `conversation_id`
öffnet eine neue Unterhaltung für den Aussteller des Schlüssels und gibt ihre Id
als `conversation_id` zurück; senden Sie sie mit dem nächsten Aufruf, und der
Agent liest, was zuvor gesagt wurde - die letzten Züge oder die Zusammenfassung
älterer und was danach kam. Ein pro Unterhaltung geteilter Workspace, der
Standard, ist der dieser Unterhaltung. Eine unbekannte Id oder die Unterhaltung
eines anderen antwortet `404`; eine eigene Unterhaltung des Ausstellers aus der
Konsole oder einem Kanal antwortet `400` - ein Schlüssel, der Agenten ausführen
darf, hat die Chats der Person nicht erhalten. Ebenso ein geparkter Durchlauf:
Ein Schlüssel setzt nur einen Durchlauf fort oder beantwortet ihn, den ein
Schlüssel gestartet hat; einer, den die Person gestartet hat, antwortet `403`,
weil die Fortsetzung in ihrem Namen handelt. Die Unterhaltung landet in der Chatliste des
Ausstellers mit dem Label **API** und bleibt ausgeblendet, bis er solche
Unterhaltungen dort per Schalter einblendet.

`GET /api/v1/conversations/{id}/transcript` liest eine der Unterhaltungen des
Ausstellers Zug für Zug, mit den Tools, die jeder Zug aufgerufen hat, und den
Kosten, für einen Schlüssel mit `runs:view`.

!!! info "Ein API-Aufrufer kann die Governance nicht umgehen"

    Dieser Endpunkt geht durch denselben Runner wie die Konsole, Slack und das
    Widget. Der Run wird aufgezeichnet, das Budget wird vor der Modellanfrage
    geprüft, das Tor für Freigaben gilt, und die Kosten landen im selben
    Dashboard.

    Das ist der Sinn eines einzigen Runners, und deshalb gibt es keinen
    "schnellen Weg", der ihn überspringt.

### Ohne die Verbindung zu halten { #without-holding-the-connection }

Ein Run von Minuten - ein Browse, eine lange Tool-Kette - hält die Anfrage die
ganze Zeit offen, und das Lese-Timeout eines Proxys kann sie abschneiden,
während der Run weiterläuft. Senden Sie `Prefer: respond-async`, und der Aufruf
antwortet sofort mit `202` und einer Run-Anfrage zum Abfragen:

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -H "Prefer: respond-async" \
  -H "Idempotency-Key: ticket-4711" \
  -d '{"prompt": "Summarise this quarter for the board"}'
# 202, Location: /api/v1/run-requests/{id}, Preference-Applied: respond-async

curl "$BASE/api/v1/run-requests/$REQUEST_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

Die Anfrage steht auf `queued`, `running`, dann `completed` mit `result` -
demselben Body, mit dem der synchrone Aufruf antwortet - oder `failed` mit
`error`. Ihre `conversation_id` ist ab der ersten Antwort bekannt, eine
Folgenachricht kann also gesendet werden, bevor der Run endet. Ein Worker führt
sie aus, durch denselben Runner, dasselbe Budget und dieselben Freigaben wie
jede andere Oberfläche.

Was sich sofort prüfen lässt, wird sofort geprüft: Eine unbekannte Konversation
oder Anlage ist ein `404` auf den `POST`, kein Fehler, auf den man warten muss.
Die Rechte des Schlüssels werden beim Start des Runs erneut geprüft, ein
Schlüssel, der widerrufen wurde, während sein Run wartete, führt ihn also nicht
aus. Nur die Person, die angefragt hat, oder ein Schlüssel von ihr kann eine
Run-Anfrage lesen; die eines anderen antwortet `404`. Ein asynchroner Run hat
einen Versuch - ein gescheiterter Run wird mit dem festgehalten, was er
ausgegeben hat, und nicht wiederholt, um es nicht zweimal auszugeben.

Die Route trägt eine **Rate-Limitierung und kein Berechtigungs-Tor**. Über die
Berechtigung entscheidet der Service, anhand der Grants genau dieses Agents — ein
Rollen-Tor auf einer Route für eine einzelne Ressource
[kann sie nicht sehen](permissions.md).

`PATCH /api/v1/agents/{id}/metadata` setzt die **Categories** und **Tags** eines
Agents mit einem Body wie `{"categories": [...], "tags": [...]}`, wobei eine leere
Liste den jeweiligen Aspekt löscht. Die Werte werden normalisiert — getrimmt,
Leerraum zusammengefasst, in der Groß-/Kleinschreibung gefaltet und dedupliziert
— und begrenzt: höchstens 10 Categories und 20 Tags, jeweils höchstens 32
Zeichen, ein längeres Element antwortet mit `422`. Wie die Run-Route trägt sie
kein Rollen-Tor; es entscheidet die grant-bewusste Prüfung `agents:edit` im
Service, sodass ein Viewer mit einem Edit-Grant auf einem Agent diesen mit Tags
versehen darf.

`GET /api/v1/agents` filtert diesen Katalog über die wiederholbaren
Query-Parameter `category` und `tag`: Werte verknüpfen **OR innerhalb eines
Aspekts** und **AND über Aspekte hinweg**, ohne Rücksicht auf Groß-/Kleinschreibung
(ein Query-Wert wird so gefaltet wie ein gespeicherter, und ein leerer Wert wird
ignoriert). Der Filter engt nur ein, was Sie ohnehin schon sehen konnten — er
überschreitet nie eine Tenant- oder Grant-Grenze.

Die Antwort trägt außerdem
`categories` und `tags`: jedes eindeutige Label auf den Agents, die Sie auflisten
können, unabhängig von Filter und Seite — die Auswahl, die ein Filtermenü anbietet.
Ein privater Agent, den Sie nicht sehen, trägt keines bei.
## Agents über A2A { #agents-over-a2a }

Ein Agent, den seine Organisation über A2A anbietet, beantwortet JSON-RPC unter
`POST /api/v1/a2a/{agent_id}`, mit denselben Keys wie `/run`; seine Agent Card liegt
unter `GET /api/v1/a2a/{agent_id}/.well-known/agent-card.json` und braucht keinen.
`PUT /api/v1/agents/{id}/a2a` mit `{"enabled": true}` schaltet es ein, für einen
Aufrufer mit `agents:publish` auf diesem Agent.

```bash
curl -X POST "$BASE/api/v1/a2a/$AGENT_ID" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "message/send",
       "params": {"message": {"role": "user", "messageId": "m1",
                              "parts": [{"kind": "text", "text": "Review clause 7"}]}}}'
```

Die Antwort ist ein `Task`, dessen ID die des Runs ist und dessen `contextId` das
Gespräch fortsetzt. `tasks/get` liest einen erneut. Den Rest beschreiben die
[Kanäle](channels.md#a2a).

Remote Agents, an die diese Organisation delegiert, werden unter
`/api/v1/external-agents` registriert: `GET` listet sie (`agents:view`); `POST` mit
einer `card_url`, optional einem `slug` und optional der `secret_id` eines API-Keys
liest die Karte und registriert ihn, und `POST /{id}/refresh` liest sie erneut;
`DELETE /{id}` entfernt einen (`agents:edit` für alle drei).

## Die ML-Dienste { #the-ml-services }

Vier Dienste der Plattform antworten für sich allein, ohne Unterhaltung und ohne
Agent dahinter: Dokumentanalyse, OCR, Spracherkennung und Erkennung
personenbezogener Daten. Sie hängen an `ml:invoke` statt an `agents:run`, und
[Die ML-Dienste](ml-services.md) ist ihre Referenz.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Beispiele Schritt für Schritt { #worked-examples }

Jedes läuft mit einem Organisationsschlüssel in `$AGENTICOS_KEY` und dem Ursprung
der API in `$BASE`. Erstellen Sie den Schlüssel unter **Einstellungen → API** mit den Berechtigungen, die das Beispiel nennt; die Konsole zeigt
ihn einmal.

**Ein Dokument in eine Wissensbasis legen und sie durchsuchen** — ein Schlüssel
mit `collections:view` und `collections:edit` (die Vorlage *Wissen einspeisen*).
Das Einlesen läuft im Hintergrund, eine Suche direkt nach dem Hochladen findet das
Dokument also womöglich noch nicht; `GET /api/v1/kb/$KB_ID/documents` zeigt seinen
Status.

```bash
# Find the knowledge base, upload a file into it, and search it.
curl "$BASE/api/v1/kb" -H "Authorization: Bearer $AGENTICOS_KEY"

curl -X POST "$BASE/api/v1/kb/$KB_ID/documents" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -F "file=@policy.pdf"

curl -X POST "$BASE/api/v1/rag/search" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION_NAME\", \"query\": \"refund window\"}"
```

**Einen Agent ausführen und lesen, was er gekostet hat** — `agents:run` und
`runs:view`. Das Lesen des Runs liefert Status, Tokens und Kosten.

```bash
RUN_ID=$(curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this week'"'"'s tickets"}' | jq -r .run_id)

curl "$BASE/api/v1/runs/$RUN_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

**Ein Mitglied einladen** — `members:manage`. Die Einladung geht per E-Mail; die
Antwort trägt ihr Token einmal, für einen Einladenden, dessen Mail nicht ankommt.

```bash
curl -X POST "$BASE/api/v1/orgs/$ORG_ID/invitations" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.hire@example.com", "role": "member"}'
```

**Nur wiederholen, was am Limit scheiterte.** Ein `429` trägt `Retry-After`; jede
andere Ablehnung ist für diese Anfrage endgültig, und ein `401` heißt, dass der
Schlüssel weg ist — widerrufen, abgelaufen oder sein Aussteller entfernt —, eine
Wiederholung verbraucht also nur das Limit.

```python
import time

import httpx


def call(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    for _ in range(5):
        response = client.request(method, path, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(int(response.headers.get("Retry-After", "60")))
    response.raise_for_status()
    return response


client = httpx.Client(
    base_url="https://agenticos.example.com/api/v1",
    headers={"Authorization": f"Bearer {KEY}"},
)
print(call(client, "GET", "/me/permissions").json())
```

## Streaming { #streaming }

Zwei WebSocket-Endpunkte, für zwei Zielgruppen.

- **`/api/v1/ws/agent`** — der authentifizierte, den die Konsole nutzt. Ein
  Frame mit `agent_id` führt diesen veröffentlichten Agent aus; ein Frame ohne
  sie erreicht den allgemeinen Assistenten. Die `conversation_id` eines Frames
  setzt diese Unterhaltung fort; `null` beginnt eine neue, und ein Frame ohne den
  Schlüssel setzt die fort, in die dieser Socket zuletzt geschrieben hat.
  Authentifizieren Sie sich mit dem
  Subprotokoll `access_token.<token>`, wobei das Token ein Sitzungs-JWT ist. Ein
  API-Schlüssel der Organisation wird hier abgelehnt: Ein Zug auf diesem Socket ist
  eine Person an der Tastatur, mit ihren persönlichen Verbindungen. Integrationen
  führen Agents über `POST /api/v1/agents/{id}/run` aus.
- **`/api/v1/embed/{public_key}/ws`** — der öffentliche hinter einem
  [Embed](channels.md), für einen Besucher, der kein Konto hat.

Beide streamen Token, sobald sie eintreffen (ein Agent mit Ausgabe-Guardrail streamt
Schritt für Schritt, siehe [Guardrails](reference/capabilities.md#guardrails)), und
beide erzeugen einen gewöhnlichen Run, mit derselben Buchführung wie alles andere.

Ein dritter, **`/api/v1/ws/events`**, hört nur zu. Über ihn
[hält eine offene Konsole mit Änderungen von anderswo Schritt](console.md#changes-made-elsewhere):
genauso authentifiziert, mit der Organisation in `?organization_id=`, sendet er
pro erfolgreichem Schreibvorgang über die öffentliche API in dieser Organisation
einen JSON-Frame — `resource`, `id`, `action` (`created`, `updated` oder
`deleted`), `surface` (`console`, `api_key`, `mcp` oder `assistant`) und wer ihn
ausgeführt hat — und nur für Zeilen, die der Aufrufer lesen darf.

## Fehler { #errors }

Überall ein Umschlag:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "..." }
  }
}
```

`details` trägt Werte statt Zeilen, nennt also das Feld, das eine Ablehnung
erklärt, und nie einen Datenbankeintrag. Geht eine Ablehnung um etwas, das der
Aufrufer eingereicht hat, ist `details.fields` eine Liste aus
`{field, message}` — und genau das lässt ein Formular die Eingabe markieren,
statt einen Satz zu zeigen, für den jemand die Seite erneut absuchen muss.

Ein `401` trägt `WWW-Authenticate: Bearer`. Ein Lesezugriff über Tenant-Grenzen
hinweg antwortet mit `404`, nicht mit `403`, aus dem oben genannten Grund.

**Ein Run, der begann und dann scheiterte, nennt sich selbst.**
`POST /agents/{id}/run` antwortet `502` mit `MODEL_CALL_FAILED`, wenn der
Modellanbieter die Anfrage abgelehnt oder nicht abgeschlossen hat, und `500` mit
`RUN_FAILED` bei jedem anderen Fehler, nachdem der Run begonnen hatte - ein
Fallback, dessen Modelle alle scheiterten, zählt als Fehler des Modells. Beide
tragen `details.run_id` und `details.status`, dazu `details.conversation_id`, wenn
der Run in eine Unterhaltung schrieb, damit ein erneuter Versuch diesen Thread
fortsetzt statt einen neuen zu öffnen, und `message` sagt den Grund in
den Worten der Plattform statt in der rohen Antwort des Anbieters. Der Run ist
als fehlgeschlagen erfasst, mit dem, was er verbraucht hat, sodass
`GET /api/v1/runs/{run_id}` ihn liest; die Anfrage erneut zu senden startet einen
neuen Run.

## Wiederholungen, Idempotenz und Revisionen { #retries-idempotency-and-revisions }

v1 hat keine Revisions-Vorbedingungen: kein `ETag`, kein `If-Match`. Ein
Schreibzugriff wird angewendet, wenn er ankommt, und der letzte gewinnt.
`Idempotency-Key` wird auf einer Route beachtet, dem asynchronen Run.

- **`GET`, `PUT` und `DELETE` lassen sich gefahrlos wiederholen.** Zweimal lesen
  liest zweimal; etwas zu löschen, das schon weg ist, antwortet `404`, was eine
  Wiederholung als erledigt werten kann.
- **`PATCH` lässt sich mit demselben Body wiederholen**, und nur dann: Zwei
  Clients, die ein Feld ändern, überschreiben einander, statt zu kollidieren.
- **`POST` nicht.** Ein wiederholtes `POST /agents/{id}/run` startet einen
  zweiten Run und wird wie einer abgerechnet; ein wiederholtes Anlegen erzeugt
  eine zweite Zeile. Nach einem Timeout oder einer abgebrochenen Verbindung
  schauen Sie nach, bevor Sie wiederholen: `GET /api/v1/runs?agent_id=…&surface=api`
  listet die Runs, neueste zuerst, und ein Listenabruf findet eine Zeile, die der
  erste Versuch doch angelegt hat.
- **Ein asynchroner Run schon, mit einem `Idempotency-Key`.** Senden Sie
  `Prefer: respond-async` und einen Schlüssel Ihrer Wahl, höchstens 255 Zeichen,
  und eine Wiederholung mit demselben Schlüssel und demselben Body antwortet mit
  derselben Run-Anfrage, in welchem Zustand sie auch ist. Derselbe Schlüssel mit
  einem anderen Body ist ein `409`, nie ein zweiter Run. Schlüssel gelten pro
  Organisation. Ein synchroner Aufruf mit dem Header wird mit `400` abgelehnt,
  statt glauben zu lassen, eine Wiederholung sei sicher.
- **`429` ist die einzige Ablehnung zum Wiederholen**, nach dem `Retry-After`,
  das sie trägt. Jedes andere `4xx` ist für diese Anfrage endgültig.

## Konventionen { #conventions }

| | |
|---|---|
| Präfix | `/api/v1` |
| Anlegen | `POST`, `201` |
| Teilweises Aktualisieren | `PATCH` |
| Löschen | `DELETE`, `204`, kein Body |
| Seitenaufteilung | Query-Parameter `skip` (≥ 0) und `limit` (1–100); Listenantworten tragen `items` und `total` |
| Pfade | kebab-case |

## Stabilität, ehrlich gesagt { #stability-honestly }

**Die öffentliche API hat ein schriftliches Kompatibilitätsversprechen, der Rest
von `/api/v1` nicht.** Die Routen, die ein API-Schlüssel aufrufen darf, stehen in
einem eigenen OpenAPI-Dokument unter **`/api/v1/public/openapi.json`**, das in
jeder Umgebung ausgeliefert wird. Innerhalb von v1 ist eine Änderung an einer
davon additiv — eine neue Route, ein neues optionales Feld, ein neues Antwortfeld
oder Enum-Wert —, und ein Client muss Antwortfelder ignorieren, die er nicht
kennt. Entfernen oder Umbenennen geschieht erst, nachdem es dort mindestens 90 Tage
als `deprecated` markiert und in den [Release Notes](release-notes.md) aufgeführt
war; eine Änderung, die so nicht geht, kommt in `/api/v2`, neben v1.

Die Konsole zeigt dasselbe Dokument als Seite: **Einstellungen → API → API-Referenz** listet jeden Endpunkt mit Parametern, Body, Antworten und einem fertigen `curl`-Aufruf.

Die erste Umbenennung nach dieser Regel sind Apps (#2071): Was Artefakte waren,
wird unter `/api/v1/apps` und `/api/v1/public/apps` ausgeliefert, und die alten
Pfade `/api/v1/artifacts` und `/api/v1/public/artifacts` antworten genauso,
markiert als `deprecated`, bis die 90 Tage um sind. Die Namen der Berechtigungen
(`artifacts:view`, `artifacts:edit`), die Namen der Tools und die Adressen, von
denen eine veröffentlichte Seite ausgeliefert wird, behalten ihre Namen.

Die eigenen Routen der Konsole haben kein solches Versprechen und ändern sich mit
der Konsole; ein Schlüssel kann sie nicht aufrufen. Eine Client-Bibliothek gibt es
noch nicht.

Was die öffentliche API noch nicht kann, damit niemand einen Client darauf baut:

- **Virtual Tables** sind nicht darin; eine Tabelle mit einem Schlüssel zu lesen
  und zu schreiben ist [#1795](https://github.com/vstorm-co/agenticos/issues/1795).
- **Kein Streaming für einen Schlüssel.** Der Chat-Socket nimmt nur die Session
  einer Person.
- **Keine Idempotenz-Schlüssel und keine Revisionen**, wie oben.

Der [Spec des Agents](reference/spec.md) hat sein eigenes Versprechen: Er ist
versioniert und bewegt sich nur vorwärts.

## Zusammenfassung { #recap }

- **`/docs`** auf dem Deployment ist die erzeugte Referenz; in der Produktion
  ist sie bewusst aus.
- Drei Wege hinein: **ein API-Schlüssel der Organisation, ein JWT oder das
  Cookie der Konsole**.
- Ein Schlüssel trägt die Befugnisse seines Ausstellers, **eingeschränkt auf
  seine Berechtigungen und die aktuelle Rolle des Ausstellers**, wird einmal
  angezeigt und funktioniert nur in der öffentlichen API.
- **Ein Schlüssel handelt in seiner eigenen Organisation; eine Sitzung liest
  `X-Organization-Id`** und fällt ohne ihn auf die persönliche Organisation
  zurück. Der falsche sieht aus wie eine fehlende Ressource.
- Einen Agent über HTTP auszuführen ist **derselbe Runner** — Budget, Freigabe
  und Audit gelten alle.
- Ein Skript holt sich seinen eigenen Schlüssel **ohne Browser** — anmelden,
  ausstellen, widerrufen — und `examples/public-api.sh` geht diesen Weg ganz.
- **Nur `429` lohnt eine Wiederholung**; ein `POST` ist nicht idempotent, also
  schauen Sie nach, bevor Sie ihn wiederholen - außer bei einem asynchronen Run
  mit `Idempotency-Key`.
- **`Prefer: respond-async`** macht aus einem Run ein `202` und eine Run-Anfrage
  zum Abfragen, ein langer Run hält also keine Verbindung offen.
- **Die öffentliche API steht in `/api/v1/public/openapi.json`** und ändert
  sich in v1 nur additiv, mit 90 Tagen Deprecation; ein SDK gibt es noch nicht.
