---
source_sha: "b6170683f77a"
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
| **JWT** | `Authorization: Bearer <access token>` | Eine Person oder etwas, das als eine handelt. Kurzlebig, wird mit einem Refresh-Token erneuert |
| **API-Key** | `X-API-Key: <key>` | Dienst zu Dienst. Kein Nutzer dahinter |
| **Session-Cookie** | von der Konsole gesetzt | Nur der Browser — das Token ist HttpOnly und erreicht JavaScript nie |

Keys werden mit `secrets.compare_digest` verglichen, nie mit `==`, und ein Key
wird so gespeichert wie [alle anderen Zugangsdaten](secrets.md) auch.

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

**`X-Organization-Id` reist auf jeder Anfrage mit**, und es ist keine optionale
Verzierung: er entscheidet, in welchem Tenant der Aufruf handelt.

Ein Aufrufer, der zu drei Organisationen gehört, ist in jeder ein anderer
Principal, mit einer anderen Rolle und anderen Grants. Lassen Sie den Header
weg, hat die Anfrage keinen Tenant, in dem sie handeln könnte; senden Sie den
falschen, bekommen Sie eine Ablehnung, die genau so aussieht, als gäbe es die
Ressource nicht — absichtlich, damit Ids nicht abtastbar werden.

## Einen Agent ausführen { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

Die Antwort trägt die Id des Runs, die Ausgabe und den Status. Zwei optionale
Felder im Body sind wissenswert: `conversation_id` setzt einen bestehenden
Thread fort, und `environment_id` wählt, [welche Umgebung](environments.md)
antwortet.

!!! info "Ein API-Aufrufer kann die Governance nicht umgehen"

    Dieser Endpunkt geht durch denselben Runner wie die Konsole, Slack und das
    Widget. Der Run wird aufgezeichnet, das Budget wird vor der Modellanfrage
    geprüft, das Tor für Freigaben gilt, und die Kosten landen im selben
    Dashboard.

    Das ist der Sinn eines einzigen Runners, und deshalb gibt es keinen
    "schnellen Weg", der ihn überspringt.

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

## Einen Workflow ausführen { #running-a-workflow }

```bash
curl -X POST "$BASE/api/v1/workflow-runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "'"$WORKFLOW_ID"'", "input": {"question": "How long do refunds take?"}, "deadline_seconds": 3600}'
```

Das startet einen Run der veröffentlichten Version des Workflows und antwortet
sofort mit `201`; die Knoten laufen im Hintergrund. `input` ist das, was der Trigger [`core.input`](reference/workflow-nodes.md#core-input) des Graphen weitergibt, höchstens `WORKFLOW_RUN_MAX_INPUT_BYTES` als JSON (darüber `413`). Hier startet nur eine Version, die mit diesem Trigger oder ohne einen startet: jede andere antwortet `409
WORKFLOW_TRIGGER_MISMATCH`, weil ein Webhook, ein Zeitplan, eine Chatnachricht oder ein Tabellen-Datensatz sie startet. `"mode": "test"` führt
stattdessen den aktuellen Entwurf aus, mit jedem Trigger, und verlangt `workflows:edit`.

`deadline_seconds` (bis zu dreißig Tage) setzt eine Deadline, die jedes Mal
geprüft wird, bevor ein Knoten ausgeführt wird: Der erste nach Ablauf fällige
Knoten lässt den Run mit `DEADLINE_EXCEEDED` fehlschlagen, während ein bereits
laufender Knoten oder ein Run, der auf eine Freigabe wartet, davon nicht
unterbrochen wird. Die
Route ist wie die Agent-Run-Route je Aufrufer begrenzt und antwortet jenseits des
Kontingents mit `429` und `Retry-After`.

`GET /api/v1/workflow-runs/{id}` liefert Status, `spent_cost`, `error` und, sobald sein Knoten [`core.output`](reference/workflow-nodes.md#core-output) gelaufen ist, `output` des
Runs, und `POST /api/v1/workflow-runs/{id}/cancel` stoppt ihn. `GET
/api/v1/workflow-runs/{id}/events?after=<cursor>` liefert den Ereignisstrom des
Runs, älteste zuerst, mit einem `next_cursor`, den Sie als `after` zurückgeben:
Er bleibt gleich, solange nichts Neueres existiert, sodass Abfragen damit einem
laufenden Run folgen. Wer was davon darf, steht unter
[Berechtigungen](permissions.md#workflow-runs).

`GET /api/v1/workflow-runs/{id}/nodes` listet jeden Schritt, den der Run gemacht
hat, Schleifeniterationen eingeschlossen, jeden mit seinem `scope_path`, Status,
seinen Versuchen, Kosten und dem typisierten Fehler, mit dem er zuletzt
fehlschlug, und `GET /api/v1/workflow-runs/{id}/graph` liefert den Graphen, den der
Run ausführt: den seiner Version oder den Draft-Snapshot eines Test-Runs.

### Einem Run über einen WebSocket folgen { #following-a-run-over-a-websocket }

`/api/v1/ws/workflow-runs?organization_id=<org>` authentifiziert sich wie der Socket
des Chats, mit dem Access Token als Subprotokoll `access_token.<token>`. Sende
`{"type": "start", "workflow_id": ..., "input": {...}}`, um einen Run zu starten,
oder `{"type": "attach", "run_id": ..., "after": <cursor>}`, um einem zu folgen. Der
Server sendet `{"type": "run", "run": {...}}`, wenn er zu folgen beginnt, und erneut,
wenn der Run endet, und `{"type": "event", "event": {...}, "cursor": ...}` für jedes
Ereignis dazwischen. Ein abgelehnter Frame bekommt `{"type": "error", "code": ...,
"message": ...}`, und eine widerrufene Sitzung schließt den Socket mit `4001`. Ein
Socket folgt einem Run; ein neuer Frame ersetzt den Run, dem er gefolgt ist.

Ein `start`-Frame verbraucht dasselbe Kontingent pro Minute wie `POST /workflow-runs` und
bekommt darüber hinaus `RATE_LIMIT_EXCEEDED`.

### Webhooks und Zeitpläne { #workflow-webhooks-and-schedules }

Ein Workflow, dessen Trigger-Knoten ein Webhook oder ein Zeitplan ist, erhält seine
Exposure, wenn diese Version veröffentlicht wird, und die Antwort der
Veröffentlichung trägt sie als `exposure`. Das Signatur-Secret eines Webhooks steht im
`webhook_secret` der Veröffentlichung, die ihn zum ersten Mal einschaltet, und
nirgendwo sonst. `GET /api/v1/workflows/{id}/exposure` liest sie zurück, oder `null`
für einen Workflow, der anders startet. `PATCH .../exposures/{exposure_id}` mit
`{"is_active": false}` pausiert sie, und `POST .../exposures/{exposure_id}/rotate-secret`
ersetzt das Secret eines Webhooks und gibt das neue einmal zurück. Beide verlangen
`workflows:edit` und `workflows:run` auf dem Workflow. Die `webhook_url` eines
Webhooks ist die Adresse, an die der Absender zustellt:

```bash
BODY='{"lead": 42}'
SIGNATURE="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"
curl -X POST "$WEBHOOK_URL" \
  -H "X-Signature-256: $SIGNATURE" \
  -H "X-Delivery-Id: lead-42" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

Es antwortet mit `202` und `{"run_id": ..., "duplicate": false}`, sobald der Run
zugelassen ist, und wartet nie auf den Run selbst. Eine bereits zugelassene
Zustellungs-ID antwortet mit `"duplicate": true` und der ID des ersten Runs. Eine
Signatur, die sich nicht verifizieren lässt, ist ein `403`, eine Zustellung ohne ID
oder mit einem Body, der kein JSON-Objekt ist, ein `400`, und ein pausierter oder
unbekannter Webhook ein `404`.

## Mit Tabellen arbeiten { #working-with-tables }

Die `values` eines Datensatzes sind nach Spalten-id geschlüsselt; `GET
/api/v1/tables/{id}` listet die Spalten. Jeder Schreibzugriff nimmt einen
`Idempotency-Key`: Eine Wiederholung mit demselben Schlüssel und Body antwortet mit dem
Ergebnis des ersten Schreibzugriffs und `Idempotent-Replayed: true`, statt erneut zu
schreiben, und derselbe Schlüssel mit anderem Body ist `422`.

```bash
curl -X POST "$BASE/api/v1/tables/$TABLE_ID/records" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Idempotency-Key: lead-ada-2026-09-29" \
  -H "Content-Type: application/json" \
  -d '{"external_id": "ada@example.com", "values": {"'"$EMAIL_COLUMN"'": "ada@example.com"}}'
```

`PATCH .../records/{record_id}` ändert einige Zellen und braucht die
`expected_revision`, die Sie zuletzt gelesen haben; eine veraltete ist `409
REVISION_CONFLICT`. `PUT .../records/by-external-id/{external_id}` legt den Datensatz
an oder aktualisiert ihn, mit `expected_revision`, sobald er existiert. `POST
.../records/query` filtert und sortiert seitenweise.

Ein Workflow, dessen Trigger-Knoten **New table record** ist, läuft nach der
Veröffentlichung für jeden Datensatz, der seiner Tabelle hinzugefügt wird. `GET
.../triggers` listet die Workflows, die mit einer Tabelle starten, `PATCH
.../triggers/{trigger_id}` mit `{"is_active": false}` pausiert einen, und `GET
.../triggers/{trigger_id}/admissions` listet, was er über jeden Datensatz entschieden
hat. Siehe [Trigger](virtual-tables.md#triggers).

## Die ML-Dienste { #the-ml-services }

Vier Dienste der Plattform antworten für sich allein, ohne Unterhaltung und ohne
Agent dahinter: Dokumentanalyse, OCR, Spracherkennung und Erkennung
personenbezogener Daten. Sie hängen an `ml:invoke` statt an `agents:run`, und
[Die ML-Dienste](ml-services.md) ist ihre Referenz.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Streaming { #streaming }

Zwei WebSocket-Endpunkte, für zwei Zielgruppen.

- **`/api/v1/ws/agent`** — der authentifizierte, den die Konsole verwendet. Ein
  Frame mit `agent_id` führt diesen veröffentlichten Agent aus; ein Frame ohne
  sie bekommt den allgemeinen Assistenten.
- **`/api/v1/embed/{public_key}/ws`** — der öffentliche hinter einem
  [Embed](channels.md), für einen Besucher, der kein Konto hat.

Beide streamen Token, sobald sie eintreffen, und beide erzeugen einen gewöhnlichen
Run, mit derselben Buchführung wie alles andere.

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

**Es gibt noch keine veröffentlichte Kompatibilitätszusage und keine
Client-Bibliothek.** Die API ist seit dem ersten Commit öffentlich, und der
Vertrag über die Versionierung ist Arbeit auf der
[Roadmap](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md)
(R10).

In der Praxis sind die Formen stabil geblieben, und das Präfix `/api/v1`
bedeutet, dass eine brechende Änderung neben der jetzigen landen würde statt auf
ihr — aber bis das aufgeschrieben ist, behandeln Sie sie als das, was sie ist:
eine API, gegen die Sie die Tests Ihrer Integration festnageln sollten.

Das eine Format, das *sehr wohl* eine Zusage trägt, ist der
[Spec des Agents](reference/spec.md): er ist versioniert und bewegt sich nur
vorwärts.

## Zusammenfassung { #recap }

- **`/docs`** auf dem Deployment ist die erzeugte Referenz; in der Produktion
  ist sie bewusst aus.
- Drei Wege hinein: **JWT, `X-API-Key` oder das Cookie der Konsole**.
- **`X-Organization-Id` entscheidet über den Tenant** bei jeder Anfrage, und der
  falsche sieht aus wie eine fehlende Ressource.
- Einen Agent über HTTP auszuführen ist **derselbe Runner** — Budget, Freigabe
  und Audit gelten alle.
- **Noch keine Kompatibilitätszusage und kein SDK** (R10); der Spec des Agents ist
  das eine versionierte Format.
