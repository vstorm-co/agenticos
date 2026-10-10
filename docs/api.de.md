---
source_sha: "d0d20e768913"
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
**Einstellungen → API-Schlüssel** (oder mit `POST /api/v1/api-keys` aus einer
angemeldeten Sitzung). Er trägt die Befugnisse dieses Mitglieds, zweifach
eingeschränkt:

- **Auf die Berechtigungen, mit denen er ausgestellt wurde.** Wählen Sie eine
  Vorlage — *Nur lesen*, *Wissen einspeisen*, *Voller Zugriff* — oder haken Sie
  Berechtigungen aus dem [Katalog](permissions.md) an. Sie können nur vergeben,
  was Sie selbst haben.
- **Auf das, was der Aussteller jetzt darf.** Jede Anfrage liest die Mitgliedschaft
  des Ausstellers neu, sodass eine Herabstufung jeden seiner Schlüssel sofort
  einschränkt und seine Entfernung aus der Organisation jeden von ihm ausgestellten
  Schlüssel stoppt. Eine Freigabe auf einer Ressource erweitert, was eine *Person*
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

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Zwei Ablehnungen sollten Sie kennen:

- **`403` "API keys are not accepted on this endpoint"** — Schlüssel werden nur in
  der öffentlichen API angenommen: Agents, Runs und Freigaben, Wissensbasen und
  RAG, Skills, Kontextdateien, Apps, die ML-Dienste, `/me/permissions`
  sowie Mitglieder, Einladungen, Gruppen und Einstellungen einer Organisation.
  Die eigenen Routen der Konsole, Ihr Konto, das Verlassen oder Übergeben einer
  Organisation und die Schlüsselverwaltung selbst bleiben Sitzungen vorbehalten,
  damit ein geleakter Schlüssel keinen Nachfolger erzeugen kann.
- **`401` "Invalid, expired or revoked API key"** — derselbe Satz in jedem Fall,
  damit ein falscher Schlüssel nichts darüber erfährt, welche Schlüssel existieren.

Jeder Schlüssel hat außerdem sein eigenes Limit, `RATE_LIMIT_API_KEY_PER_MINUTE`
Anfragen pro Minute (standardmäßig 600), und ein Run oder ein ML-Aufruf, den er
auslöst, zählt gegen diese Limits für den Schlüssel statt für seinen Aussteller.

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

Die Antwort trägt außerdem
`categories` und `tags`: jedes eindeutige Label auf den Agents, die Sie auflisten
können, unabhängig von Filter und Seite — die Auswahl, die ein Filtermenü anbietet.
Ein privater Agent, den Sie nicht sehen, trägt keines bei.
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
der API in `$BASE`. Erstellen Sie den Schlüssel unter **Einstellungen →
API-Schlüssel** mit den Berechtigungen, die das Beispiel nennt; die Konsole zeigt
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
  sie erreicht den allgemeinen Assistenten. Authentifizieren Sie sich mit dem
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

Die erste Umbenennung nach dieser Regel sind Apps (#2071): Was Artefakte waren,
wird unter `/api/v1/apps` und `/api/v1/public/apps` ausgeliefert, und die alten
Pfade `/api/v1/artifacts` und `/api/v1/public/artifacts` antworten genauso,
markiert als `deprecated`, bis die 90 Tage um sind. Die Namen der Berechtigungen
(`artifacts:view`, `artifacts:edit`), die Namen der Tools und die Adressen, von
denen eine veröffentlichte Seite ausgeliefert wird, behalten ihre Namen.

Die eigenen Routen der Konsole haben kein solches Versprechen und ändern sich mit
der Konsole; ein Schlüssel kann sie nicht aufrufen. Eine Client-Bibliothek gibt es
noch nicht.

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
- **Die öffentliche API steht in `/api/v1/public/openapi.json`** und ändert
  sich in v1 nur additiv, mit 90 Tagen Deprecation; ein SDK gibt es noch nicht.
