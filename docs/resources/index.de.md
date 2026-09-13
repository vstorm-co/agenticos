---
source_sha: 586f51917e7c
---

# Ressourcen { #resources }

Alles rund um das Produkt statt in ihm: wie Sie Hilfe bekommen, wie Sie
beitragen, und wie Sie die Plattform erweitern.

## AgenticOS helfen { #help-agenticos }

Das Projekt ist jung, und der schnellste Weg, ihm zu helfen, ist, es zu benutzen
und zu sagen, was kaputtgegangen ist.

<div class="grid cards" markdown>

- :material-bug:{ .lg .middle } **[Einen Fehler melden](https://github.com/vstorm-co/agenticos/issues/new)**

    Was kaputtgeht, die Abfolge, die es auslöst, und woran Sie merken würden,
    dass es behoben ist. Das Dritte ist der Teil, der den meisten Issues fehlt.

- :material-lightbulb-on:{ .lg .middle } **[Etwas vorschlagen](https://github.com/vstorm-co/agenticos/issues)**

    Sehen Sie zuerst in [die Issue-Landkarte](https://github.com/vstorm-co/agenticos/issues/168)
    — sie sagt, was schon geplant ist und was noch keinen Zuschnitt hat.

- :material-star:{ .lg .middle } **[Dem Repository einen Stern geben](https://github.com/vstorm-co/agenticos)**

    Es ist das billigste Signal dafür, dass sich das Weitermachen lohnt.

</div>

## Entwicklung — Mitwirken { #development-contributing }

Lesen Sie die Seite, die zu dem passt, was Sie anfassen. Es sind die eigenen
Entwicklungsnotizen des Repositories, veröffentlicht statt neu geschrieben; was
Sie lesen, lesen also auch die Mitwirkenden.

| Sie arbeiten an | Lesen Sie |
|---|---|
| Überhaupt irgendetwas, zuerst | [Architektur](../architecture.md) · [Der Code der Konsole](../frontend.md) — Routes → Services → Repositories, und die Transaktion der Anfrage |
| Einer Form, die Sie schon einmal gesehen haben | [Patterns](../patterns.md) |
| Einem Feature, von Anfang bis Ende | [Ein Feature hinzufügen](../adding_features.md) |
| Einem Test oder einem roten Coverage-Gate | [Testen](../testing.md) |
| Einem Pull Request | [Code-Review](../code-review.md) und [Branching](../branching.md) |

!!! warning "Drei Dinge, die Sie beißen werden"

    Ein Repository committet mit `db.flush()`, nie mit `db.commit()`.
    Hintergrundarbeit, die eine Zeile liest, die die Anfrage gerade geschrieben
    hat, wird mit `spawn_after_commit` übergeben, nie mit `spawn`. Und die
    Plattformschicht wird bei 100 % Coverage gehalten, erzwungen in CI. Alle drei
    stehen in [Architektur](../architecture.md) und [Testen](../testing.md), und
    alle drei sind hier mindestens einmal falsch gemacht worden.

## Die Plattform erweitern { #extending-the-platform }

Erweitern, was AgenticOS selbst kann, in Python. Das sind Rezepte für
Mitwirkende — Sie brauchen das ausgecheckte Repository.

- [Eine Capability hinzufügen](../howto/add-capability.md) — ein neues Tool, das das Modell aufrufen kann
- [Einen Server zum MCP-Katalog hinzufügen](../howto/add-mcp-server.md)
- [Einen API-Endpunkt hinzufügen](../howto/add-api-endpoint.md)
- [Einen Hintergrund-Task hinzufügen](../howto/add-background-task.md)
- [Einen Sync-Connector hinzufügen](../howto/add-sync-connector.md)

!!! tip "Bevor Sie eine Capability schreiben"

    Fragen Sie sich, ob es nicht in Wahrheit eine
    [MCP-Verbindung](../mcp.md) ist. Eine Capability, die ein API-Client für ein
    einziges SaaS-Produkt wäre, ist ein Server, den schon jemand geschrieben hat,
    und ihn in dieses Repository zu holen heißt, ihn für immer gegen die API
    dieses Produkts zu pflegen.

## Gebaut auf { #built-on }

AgenticOS wird aus dem
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template)
erzeugt und steht auf:

- [Pydantic AI](https://ai.pydantic.dev) — der Agent-Runtime
- [FastAPI](https://fastapi.tiangolo.com) und [Pydantic](https://docs.pydantic.dev) — dem Backend
- [pgvector](https://github.com/pgvector/pgvector) — dem Retrieval
- [Prefect](https://www.prefect.io) — der Hintergrundarbeit
- [Next.js](https://nextjs.org) — der Konsole
- [Model Context Protocol](https://modelcontextprotocol.io) — jeder Integration

## Lizenz { #licence }

Apache 2.0. Siehe
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
