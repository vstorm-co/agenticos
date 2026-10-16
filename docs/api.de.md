---
source_sha: "ba34a88c524a"
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

Beide streamen Token, sobald sie eintreffen (ein Agent mit Ausgabe-Guardrail streamt
Schritt für Schritt, siehe [Guardrails](reference/capabilities.md#guardrails)), und
beide erzeugen einen gewöhnlichen Run, mit derselben Buchführung wie alles andere.

## Sprachanrufe { #voice-calls }

Ein [Sprachanruf](voice.md) hat ein eigenes Socket, weil ein Anruf keine
Schleife aus Runden ist: **`/api/v1/ws/voice`** für ein Mitglied und
**`/api/v1/embed/{public_key}/voice/ws`** für einen Besucher auf einem Widget
oder einer gehosteten Seite ([Zulassung](channels.md#the-call-socket)). Beide
sprechen dieselben Frames, definiert in `backend/app/schemas/voice.py`.

Das Socket der Konsole authentifiziert sich wie `/ws/agent`: das Token als
Eintrag `access_token.<JWT>` in `Sec-WebSocket-Protocol` (oder das
Same-Origin-Cookie), nie im Query-String, und die Organisation als
`?organization_id=`. Es schließt mit `4001` ohne gültige Session und mit `4003`,
wenn der Aufrufer kein Mitglied ist. Das Embed-Socket schließt mit `4029`
jenseits eines Rate-Limits und mit `4003` bei jeder Ablehnung, die das Embed
betrifft. Jeder Heartbeat prüft die Session erneut, sodass ein Anruf eine
Abmeldung nicht überdauert.

**Der Client sendet** JSON-Frames und über das Relay auch binäres Audio:

| Frame | Felder | Wann |
|---|---|---|
| `start` | `agent_id`, `conversation_id`, `sdp_offer` (WebRTC), `resume_of` und `resume_token` (eine Wiederverbindung), `context` (die Variablen eines Embeds) | Zuerst, innerhalb von 10 Sekunden |
| `approval` | `id`, `decision` (`approve` oder `deny`) | Entscheidung über eine Freigabe, auf die der Anruf wartet |
| `mute` | `muted` | Das Relay: das Mikrofon stummgeschaltet |
| `played` | `bytes` | Das Relay: wie viel vom Audio des Agents abgespielt wurde |
| `end` | - | Auflegen |
| *binär* | 16-Bit-PCM mit der Eingangsrate des Modells | Das Relay: das Audio des Anrufers |

**Der Server sendet:**

| Frame | Felder | Bedeutet |
|---|---|---|
| `answer` | `sdp` | WebRTC: die Antwort des Providers für die Peer-Verbindung des Browsers |
| `ready` | `call_id`, `run_id`, `conversation_id`, `transport`, `input_sample_rate`, `output_sample_rate`, `cap_seconds`, `minutes_left`, `resume_token` | Der Anruf ist eingerichtet. `resume_token` wird nur hier gesendet, nur an diesen Anrufer; eine Wiederverbindung schickt es zurück |
| `state` | `state`: `connecting`, `listening`, `user_speaking`, `thinking`, `agent_speaking`, `interrupted`, `tool_running`, `awaiting_approval` | Wer spricht oder was der Agent gerade tut |
| `caption` | `role`, `turn_id`, `part` und eines von `delta` (anhängen), `text` (durch den bisher geprüften Text ersetzen) oder `final` | Ein Live-Untertitel |
| `turn_saved` | `message` | Eine abgeschlossene Runde, als die Nachricht, als die sie gespeichert wurde; sie ersetzt die Untertitel mit ihrer `turn_id` |
| `tool` | `name`, `status` (`running` oder `done`) | Ein Tool, das der Agent ausführt |
| `approval_required` | `id`, `tool`, `args`, `said`, `timeout_seconds` | Eine Freigabe für die Person im Anruf: die exakten Argumente und was von ihr verstanden wurde |
| `approval_unavailable` | `tool`, `args` | Ein Tool-Aufruf, den dieser Anrufer per Stimme nicht freigeben kann |
| `approval_settled` | `id`, `outcome` (`approved`, `denied` oder `expired`) | Wie eine Freigabe ausgegangen ist |
| `notice` | `kind`, `message` (optional) | Etwas, das in Worten zu sagen ist: ein Guardrail-Treffer, ein erreichtes Limit |
| `limit` | `seconds_left` | Die Zeit des Anrufs ist fast um |
| `clear_playback` | - | Das Relay: das eingereihte Audio des Agents verwerfen |
| `ended` | `reason`, `message` | Der Anruf ist vorbei |
| *binär* | 16-Bit-PCM mit der Ausgangsrate des Modells | Das Relay: das Audio des Agents |

**Ein Besucher eines Widgets oder einer gehosteten Seite erfährt weniger.** Sein
`ready` enthält kein `run_id`, `minutes_left` kommt als `null`, und
`cap_seconds` ist das eigene Limit des Anrufs - der längste Anruf der
Organisation, der des Agents oder was von einem fortgesetzten Anruf übrig ist -
statt eines Limits, das die Minuten der Organisation verrät. Der Server beendet
den Anruf trotzdem am echten Limit. Die Tool-Frames folgen den Schaltern
`show_tool_steps` und `show_tool_results` des Embeds, wie die einer getippten
Antwort. Ohne Tool-Schritte wird kein `tool`-Frame gesendet, und
`tool_running` kommt als `thinking`. Ohne Tool-Ergebnisse kommt
`approval_unavailable` mit leeren `args`. Das `turn_saved` eines Besuchers
enthält, unabhängig von den Schaltern, nur `id`, `role`, `content`,
`interrupted` und `turn_id` der Nachricht: nie die IDs von Run, Agent oder
Version, nie ihre Kosten oder Tool-Aufrufe.

**Eine Wiederverbindung muss beweisen, dass ihr der Anruf gehört.** Ein `start`
mit `resume_of` muss auch das `resume_token` aus dem `ready` jener Verbindung
mitschicken. Ohne es oder mit einem falschen wird die Wiederverbindung als
`resume_refused` abgelehnt, und der genannte Anruf bleibt unberührt. Der Server
speichert nur einen Hash des Tokens. Ein Anruf, der schon aus 20 Verbindungen
besteht, wird nicht mehr fortgesetzt: Auch seine nächste Wiederverbindung wird
als `resume_refused` abgelehnt.

Ein Socket, das innerhalb von 10 Sekunden kein `start` sendet, bekommt `ended`
mit `no_start`. Ein Anruf, der nicht startet, antwortet mit `ended` und einem
stabilen `reason`: `voice_off`, `no_agent`, `forbidden`, `not_configured`,
`bad_offer`, `data_channel`, `resume_refused`, `minutes_exhausted`,
`call_limit`, `not_priced`, `budget`, `busy` oder `line_busy`, mit einer
`message`, die sich gefahrlos anzeigen lässt. Ein Start, der aus irgendeinem
anderen Grund scheitert, antwortet mit `ended` und `error`. Ein Besucher, der
als `not_configured`, `not_priced`, `minutes_exhausted` oder `budget` abgelehnt
wird, bekommt denselben Grund mit der Meldung "Calls are not available right
now.", denn die vollständige Meldung ist für den Betreiber des Agents
geschrieben. Ein Anruf in eine archivierte Unterhaltung wird als `forbidden`
abgelehnt, so wie eine getippte Nachricht dorthin.

Ein Anruf, der gelaufen ist, endet mit `user`, `time_limit`, `budget`,
`minutes`, `disconnected`, `revoked`, `shutdown` oder `error`. Er endet mit
`minutes`, wenn die Minuten des Monats sein Limit gesetzt haben, und mit
`time_limit`, wenn die Einstellung für den längsten Anruf es gesetzt hat. Der Anruf eines Besuchers
endet mit `revoked`, wenn sein Embed pausiert wird, seine Anrufe abgeschaltet
werden oder es auf einen anderen Agent zeigt. Kein Frame trägt je Zugangsdaten
eines Providers.

Vier HTTP-Routen gehören dazu:

| Route | Gate | Antwortet |
|---|---|---|
| `GET /api/v1/agents/{agent_id}/voice?surface=web` | `agents:run` auf diesem Agent, ein Grant eingeschlossen; sonst `404` | Ob ein Anruf starten würde, warum nicht, der Transport, der längste Anruf und die verbleibenden Minuten. `surface=embed` fragt für ein Widget oder eine gehostete Seite |
| `GET /api/v1/providers/realtime-models` | `agents:view` | Der Realtime-Katalog, aus dem der Abschnitt Stimme auswählt |
| `GET /api/v1/voice/usage?start=…&end=…` | `runs:view` | Anrufsekunden und Anrufe für Anrufe, die zu oder nach `start` und vor `end` begonnen haben, nach Agent (die Anrufe eines gelöschten Agents als eine Zeile ohne ID oder Namen), und die Sekunden dieses Monats gegenüber den monatlichen Minuten der Organisation. Ein `end`, das nicht nach `start` liegt, wird mit `422` abgelehnt |
| `GET /api/v1/runs?modality=voice` | `runs:view` | Nur Anrufe (`text` nur für getippte Runs); ein Anruf, der sich neu verbunden hat, ist eine Zeile mit `voice_chain`, alle Verbindungen summiert |

Eine Freigabe, die zu einem laufenden Anruf gehört, wird im Anruf entschieden:
`POST /api/v1/approvals/{id}` lehnt sie mit `400` ab.

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
