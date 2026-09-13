---
source_sha: 1fd2c8097097
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
