---
source_sha: "c51412640202"
title: "Fragen aus Ihrer Datenbank beantworten"
description: "Verbinden Sie einen selbst gehosteten Postgres-MCP-Server hinter einer reinen Leserolle und einem reinen View-Schema, und lassen Sie einen Agent ihn abfragen."
---

# Fragen aus Ihrer Datenbank beantworten { #answer-questions-from-your-database }

Verbinden Sie einen Postgres-MCP-Server, damit ein Agent Fragen aus Ihrer eigenen Datenbank beantworten kann, und schieben Sie vorher eine reine Leserolle und ein reines View-Schema zwischen den Agent und Ihre Tabellen. Dies ist eine Anleitung zum Durchführen, kein Bericht über ein gemessenes Deployment: Der MCP-Server, den dieses Rezept braucht, ist von dieser Installation aus nicht erreichbar, aus einem unten erklärten Grund, sodass hier nichts end-to-end gegen einen laufenden Agent ausgeführt wurde.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Ein selbst betriebener Postgres-MCP-Server, erreichbar unter einer URL, die dieses Deployment anwählen kann. Der Eintrag `postgres` im Katalog ist genau das: keine gehostete URL, ein Bearer-Token, das *Ihr eigener Server* prüft, und eine Warnung, ihn auf reine Leseansichten statt auf eine Primärdatenbank mit Schreibzugriff zu richten. Siehe [den Katalog](../mcp.md#data-and-analytics).
- `connections:manage`, um die Organisationsverbindung zu registrieren.

## Warum eine reine Leserolle und ein reines View-Schema { #why-a-read-only-role-and-a-views-only-schema }

**MCP-Tools liegen außerhalb des Genehmigungs-Gates.** Die Tools einer Capability können zur Genehmigung durch eine Person zurückgehalten werden; die eines MCP-Servers nicht; es gibt keine Prüfung pro Aufruf für das SQL, das das Abfrage-Tool eines Agents ausführt. Was auch immer der verbundene Server kann, kann der Agent, ohne zu fragen - siehe [MCP-Tools liegen außerhalb des Genehmigungs-Gates](../governance.md#an-approval-inside-a-delegation). Die Datenbank-Zugangsdaten selbst müssen die Grenze sein, keine Einstellung am Agent.

Zwei Entscheidungen leisten das:

- **Eine Rolle ohne Schreibrechte**, sodass das Schlimmste, was eine falsche oder manipulierte Abfrage anrichten kann, ist, etwas zu lesen, das sie nicht sollte - nie eine Zeile zu ändern oder zu löschen.
- **Ein Schema aus Views, nicht aus den Basistabellen**, das dieser Rolle gewährt wird statt der Tabellen selbst. Eine View kann Spalten weglassen, die ein Modell nicht sehen sollte, und vorab aggregieren, was sie zurückgibt - das ist zugleich eine Datenschutzgrenze und eine günstigere Abfrage, die der Agent schreiben muss.

## Die Eingabe vorbereiten { #prepare-the-input }

Eine kleine synthetische Tabelle `orders`, in einer eigenen Datenbank:

```sql
CREATE TABLE orders (
    id           serial PRIMARY KEY,
    customer     text NOT NULL,
    status       text NOT NULL CHECK (status IN ('paid', 'refunded', 'pending')),
    amount_cents integer NOT NULL,
    created_at   date NOT NULL
);

INSERT INTO orders (customer, status, amount_cents, created_at) VALUES
    ('Ada',     'paid',     4200, '2026-09-01'),
    ('Grace',   'paid',     1800, '2026-09-02'),
    ('Ada',     'refunded', 4200, '2026-09-03'),
    ('Rex',     'paid',     9900, '2026-09-05'),
    ('Grace',   'pending',  2500, '2026-09-06'),
    ('Linus',   'paid',     3300, '2026-09-06'),
    ('Rex',     'paid',     1500, '2026-09-08'),
    ('Ada',     'paid',     6000, '2026-09-09');
```

Das reine View-Schema und die Rolle, mit der sich der Connection-String des MCP-Servers authentifiziert:

```sql
CREATE SCHEMA reporting;

CREATE VIEW reporting.daily_paid_totals AS
SELECT created_at, count(*) AS paid_orders, sum(amount_cents) AS paid_amount_cents
FROM orders
WHERE status = 'paid'
GROUP BY created_at
ORDER BY created_at;

CREATE VIEW reporting.status_counts AS
SELECT status, count(*) AS orders, sum(amount_cents) AS amount_cents
FROM orders
GROUP BY status
ORDER BY status;

CREATE ROLE shop_readonly LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE shop_demo TO shop_readonly;
GRANT USAGE ON SCHEMA reporting TO shop_readonly;
GRANT SELECT ON reporting.daily_paid_totals, reporting.status_counts TO shop_readonly;
REVOKE ALL ON SCHEMA public FROM shop_readonly;
```

Die Referenzantwort, damit Sie eine Antwort mit den Quellzeilen abgleichen können: `status_counts` ergibt paid 6 Bestellungen / 26700 Cent, pending 1 / 2500, refunded 1 / 4200. Fragt `shop_readonly` direkt `orders` ab, wird das mit `permission denied for table orders` abgelehnt - die Views sind die einzige Tür.

## Den Server verbinden { #connect-the-server }

1. Wählen Sie unter **Toolbox → MCP servers** eines Agents **Connect a server** und wählen Sie **PostgreSQL** aus dem Katalog, oder verbinden Sie ihn einmal unter **MCP servers** in den Organisationseinstellungen, damit mehr als ein Agent ihn binden kann.
2. Richten Sie die Verbindung auf Ihren eigenen laufenden Postgres-MCP-Server (zum Beispiel [`crystaldba/postgres-mcp`](https://github.com/crystaldba/postgres-mcp)), konfiguriert mit dem Connection-String von `shop_readonly` und seinem eingeschränkten, reinen Lesemodus. Fügen Sie das Bearer-Token ein, das dieser Server prüft - nicht das Datenbankpasswort - als Token der Verbindung.
3. Schränken Sie in der Bindung des Agents `allowed_tools` auf die reinen Lese-Tools ein, die der Server anbietet, zusätzlich zu dem, was die Verbindung selbst bereits erlaubt.
4. Binden Sie nur diese Verbindung, setzen Sie ein Budget, und setzen Sie Instruktionen, die die beiden Views nennen und dem Agent sagen, dass er sagen soll, wenn eine Frage eine Spalte oder eine Tabelle braucht, die die Views nicht führen, statt zu raten.

## Warum das hier nicht durchgeführt werden konnte { #why-this-could-not-be-run-here }

Das Verbinden des Servers wurde gegen diese Installation versucht und abgelehnt:

```text
This MCP server URL cannot be used: Blocked: 'localhost' resolves to
private/internal address '::1'. SSRF protection does not allow requests to
internal networks.
```

Die URL einer MCP-Verbindung wird für jede Loopback-, private, Link-Local- oder Shared-CGNAT-Adresse bedingungslos abgelehnt - es gibt keine Ausnahme für die lokale Entwicklung, weil derselbe Check auch eine `cdp_url` und jeden OAuth-Discovery-Hop absichert. Siehe [eine URL, die dieses Deployment nicht erreichen darf, wird abgelehnt](../mcp.md#a-connection). Ein Postgres-MCP-Server, der nur unter `localhost` oder einer privaten Netzwerkadresse erreichbar ist - der gewöhnliche Ort, einen zum ersten Mal laufen zu lassen - kann von der eigenen Maschine dieses Deployments aus nicht verbunden werden. Ihn zu erreichen braucht eine routbare Adresse: einen kleinen Host mit einer öffentlichen oder per VPN erreichbaren IP, oder einen Tunnel, davor.

Das obige SQL wurde direkt gegen Postgres ausgeführt und geprüft; die Rollenablehnung und die zitierten View-Summen sind echt. Nicht verifiziert wurde, dass ein Agent tatsächlich über den verbundenen Server abfragt, weil der Server nie erreichbar war, um ihn zu verbinden.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Eine Frage, die die bezahlte Summe nennt | 26700 (sechs bezahlte Bestellungen) |
| Eine Frage zu ausstehenden Bestellungen | 2500 (eine Bestellung) |
| Eine Frage, die eine Spalte nennt, die keine View zeigt (z. B. der Kundenname) | Der Agent sagt, dass er das aus dem, woran er gebunden ist, nicht beantworten kann |
| Eine Abfrage, die die Rolle nicht ausführen kann (ein Update, ein Delete) | Von der Datenbank abgelehnt, `permission denied` |
| `allowed_tools` auf reine Lese-Tools eingeschränkt | Ein Schreib-Tool, das der Server anbietet, steht im Toolset des Modells überhaupt nicht |

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Die Verbindung wird mit einer SSRF-Meldung abgelehnt.** Die Adresse des Servers ist Loopback, privat oder anderweitig intern für das eigene Netzwerk dieses Deployments - siehe oben. Stellen Sie eine routbare Adresse davor.
- **Der Agent liest die Basistabelle statt der Views.** `shop_readonly` wurde sowohl auf `public` als auch auf `reporting` gewährt, oder das Schema der Basistabelle wurde ihr nie entzogen. Führen Sie das obige `REVOKE` erneut aus.
- **Eine Abfrage, die der Agent ausführt, sieht aus, als hätte sie etwas geändert.** Das kann nicht sein, wenn die Rolle wirklich kein Schreibrecht hat - prüfen Sie die Rechte der Rolle, bevor Sie annehmen, der Agent habe sich falsch verhalten.
- **Die Verbindung wird erfolgreich geprüft, aber der Builder listet keine Tools.** Sie wurde noch nicht geprüft, oder die letzte Prüfung ist fehlgeschlagen - `POST /mcp-connections/{id}/test` aktualisiert sie.
- **Zwei Agents brauchen unterschiedlichen Zugriff auf dieselbe Datenbank.** Verbinden Sie den Server zweimal, unter zwei Namen, jeweils mit eigener Rolle und eigenen Views - ein Server, zwei Zugangsdaten, nie eine Rolle für den strengeren Agent aufgeweitet.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie das SQL, das das Test-Setup erstellt hat, die Rechte der Rolle, die View-Definitionen, das `allowed_tools` der Verbindung und das `allowed_tools` auf Ebene der Agent-Bindung auf. Eine Person entscheidet weiterhin, welche Spalten in eine View gehören, bevor ein Agent sie je erreicht - den Zugriff einzuschränken, nachdem ein Agent schon Fragen stellt, ist ein sehr viel schwierigeres Gespräch, als es zuerst zu entscheiden.
