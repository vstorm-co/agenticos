---
source_sha: "c2598611c808"
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
  RAG, Skills, Kontextdateien, Artefakte, die ML-Dienste, `/me/permissions`
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

## Streaming { #streaming }

Zwei WebSocket-Endpunkte, für zwei Zielgruppen.

- **`/api/v1/ws/agent`** — der authentifizierte, den die Konsole nutzt. Ein
  Frame mit `agent_id` führt diesen veröffentlichten Agent aus; ein Frame ohne
  sie erreicht den allgemeinen Assistenten. Authentifizieren Sie sich mit dem
  Subprotokoll `access_token.<token>`, wobei das Token ein Sitzungs-JWT oder ein
  API-Schlüssel der Organisation ist; der Socket eines Schlüssels handelt in
  dessen Organisation, führt jeden Zug innerhalb der Berechtigungen des Schlüssels
  aus und schließt sich beim nächsten Frame, nachdem der Schlüssel widerrufen
  wurde.
- **`/api/v1/embed/{public_key}/ws`** — der öffentliche hinter einem
  [Embed](channels.md), für einen Besucher, der kein Konto hat.

Beide streamen Token, sobald sie eintreffen (ein Agent mit Ausgabe-Guardrail streamt
Schritt für Schritt, siehe [Guardrails](reference/capabilities.md#guardrails)), und
beide erzeugen einen gewöhnlichen Run, mit derselben Buchführung wie alles andere.

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
- **Noch keine Kompatibilitätszusage und kein SDK** (R10); der Spec des Agents ist
  das eine versionierte Format.
