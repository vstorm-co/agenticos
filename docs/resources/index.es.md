---
source_sha: "586f51917e7c"
---

# Recursos { #resources }

Todo lo que rodea al producto en lugar de estar dentro de él: cómo conseguir
ayuda, cómo contribuir y cómo extender la plataforma.

## Ayuda a AgenticOS { #help-agenticos }

El proyecto es joven y la forma más rápida de ayudarlo es usarlo y contar qué se
ha roto.

<div class="grid cards" markdown>

- :material-bug:{ .lg .middle } **[Informa de un fallo](https://github.com/vstorm-co/agenticos/issues/new)**

    Qué se rompe, la secuencia que lo provoca y cómo sabrías que está arreglado.
    Esa tercera parte es la que le falta a la mayoría de los issues.

- :material-lightbulb-on:{ .lg .middle } **[Sugiere algo](https://github.com/vstorm-co/agenticos/issues)**

    Mira antes [el mapa de issues](https://github.com/vstorm-co/agenticos/issues/168):
    dice qué está ya planificado y qué no tiene aún alcance definido.

- :material-star:{ .lg .middle } **[Dale una estrella al repositorio](https://github.com/vstorm-co/agenticos)**

    Es la señal más barata de que vale la pena seguir con esto.

</div>

## Desarrollo — contribuir { #development-contributing }

Lee la página que corresponda a lo que estés tocando. Son las propias notas de
ingeniería del repositorio, publicadas en lugar de reescritas, así que lo que
lees es lo que leen quienes contribuyen.

| Si trabajas en | Lee |
|---|---|
| Cualquier cosa, lo primero | [Arquitectura](../architecture.md) · [El código de la consola](../frontend.md) — rutas → servicios → repositorios, y la transacción de la petición |
| Una forma que ya has visto antes | [Patrones](../patterns.md) |
| Una funcionalidad, de principio a fin | [Añadir funcionalidades](../adding_features.md) |
| Un test, o un coverage gate en rojo | [Tests](../testing.md) |
| Una pull request | [Revisión de código](../code-review.md) y [Ramas](../branching.md) |

!!! warning "Tres cosas que te van a morder"

    Un repositorio confirma con `db.flush()`, nunca con `db.commit()`. El trabajo
    en segundo plano que lee una fila que la petición acaba de escribir se entrega
    con `spawn_after_commit`, nunca con `spawn`. Y la capa de plataforma se
    mantiene al 100 % de cobertura, impuesto en CI. Las tres están en
    [Arquitectura](../architecture.md) y [Tests](../testing.md), y en las tres se
    ha metido la pata aquí al menos una vez.

## Extender la plataforma { #extending-the-platform }

Ampliar lo que el propio AgenticOS sabe hacer, en Python. Son recetas para quien
contribuye: necesitas el repositorio clonado.

- [Añade una capability](../howto/add-capability.md) — una herramienta nueva que el modelo puede llamar
- [Añade un servidor al catálogo MCP](../howto/add-mcp-server.md)
- [Añade un endpoint de la API](../howto/add-api-endpoint.md)
- [Añade una tarea en segundo plano](../howto/add-background-task.md)
- [Añade un conector de sincronización](../howto/add-sync-connector.md)

!!! tip "Antes de escribir una capability"

    Pregúntate si en realidad no es una [conexión MCP](../mcp.md). Una capability
    que sería un cliente de la API de un único producto SaaS es un servidor que
    alguien ya ha escrito, y traerlo a este repositorio significa mantenerlo
    contra la API de ese producto para siempre.

## Construido sobre { #built-on }

AgenticOS se genera a partir de
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
y se apoya en:

- [Pydantic AI](https://ai.pydantic.dev) — el runtime del agent
- [FastAPI](https://fastapi.tiangolo.com) y [Pydantic](https://docs.pydantic.dev) — el backend
- [pgvector](https://github.com/pgvector/pgvector) — la recuperación
- [Prefect](https://www.prefect.io) — el trabajo en segundo plano
- [Next.js](https://nextjs.org) — la consola
- [Model Context Protocol](https://modelcontextprotocol.io) — todas las integraciones

## Licencia { #licence }

Apache 2.0. Consulta
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
