---
source_sha: "df924dfc3bb7"
---

<div class="agenticos-hero" markdown>

![AgenticOS](assets/mark.svg){ .agenticos-hero__mark }

<p class="agenticos-hero__name">AgenticOS</p>

<p class="agenticos-hero__tagline">
Un solo lugar para construir, ejecutar y gobernar los agents de IA de tu empresa. Autoalojado, de código abierto y tuyo.
Por qué se llama sistema operativo está
<a href="#why-it-is-called-an-operating-system">siete funciones más abajo</a>.
</p>

<p class="agenticos-hero__badges">
<a href="https://github.com/vstorm-co/agenticos/actions"><img src="https://img.shields.io/github/actions/workflow/status/vstorm-co/agenticos/ci.yml?branch=main&label=tests" alt="Tests"></a>
<a href="https://github.com/vstorm-co/agenticos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="Licence"></a>
<a href="https://github.com/vstorm-co/agenticos"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat" alt="Stars"></a>
<img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

<p class="agenticos-hero__links" markdown>
**Documentación**: <a href="https://vstorm-co.github.io/agenticos/">vstorm-co.github.io/agenticos</a><br>
**Código fuente**: <a href="https://github.com/vstorm-co/agenticos">github.com/vstorm-co/agenticos</a>
</p>

</div>

---

AgenticOS es una plataforma autoalojada y multiinquilino para construir,
gobernar y ejecutar los agents de IA de una empresa.

El punto clave es este:

!!! quote "El código define, la configuración compone"

    Un equipo de negocio compone agents en un navegador — instrucciones, un
    modelo, un conjunto de capabilities, un budget — y el resultado se ejecuta
    igual en todas partes: chat web, API HTTP, Slack, Telegram, un widget
    incrustado. La consola en sí es una aplicación web; la
    [aplicación de escritorio](desktop.md) es esa misma consola en una ventana
    propia, un añadido para quien la quiera en el dock.

    Los ingenieros amplían lo que hay para componer, en Python tipado. La
    configuración nunca puede alcanzar más que lo que el código registró, y eso
    es lo que hace seguro poner un Builder sin código en manos de alguien que no
    es ingeniero.

Todo lo demás en este sitio se deriva de esa única frase. El techo no es un
archivo de configuración — es lo que tus ingenieros pongan en el registro, y el
código fuente es tuyo.

## Empieza donde estás { #start-where-you-are }

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **Quiero probarlo**

    [La instalación](install.md) son cuatro comandos, y luego
    [tu primer agent](first-agent.md) funciona en unos diez minutos.

- :material-account-tie:{ .lg .middle } **Estoy decidiendo si lo adoptamos**

    [La implantación](rollout.md) — quién hace qué, cuánto cuesta y las
    preguntas que hará tu revisión de seguridad. Sin terminal.

- :material-code-braces:{ .lg .middle } **Quiero integrarme con él**

    [La API HTTP](api.md) para llamarlo, [MCP](mcp.md) para dar tus herramientas
    a los agents y [el código de la consola](frontend.md) si vas a cambiar la
    UI.

- :material-cog:{ .lg .middle } **Ya lo tengo en marcha y algo va mal**

    [La consola](console.md) recorre cada pantalla, y el *Resumen* de cada
    página es la versión corta. [Configuración](configuration.md) son todos los
    ajustes.

</div>

## Por qué se llama sistema operativo { #why-it-is-called-an-operating-system }

Porque la palabra hace un trabajo real. Un sistema operativo ejecuta y aísla
procesos, impone límites de recursos, controla el acceso, alcanza el hardware a
través de controladores, mantiene un sistema de archivos, da una sola shell a
muchas interfaces y escribe un registro de auditoría.

AgenticOS hace cada una de esas cosas para los agents: runs, budgets
comprobados antes de la petición al modelo, un catálogo de permisos con las
aprobaciones como su `sudo`, MCP y los perfiles de modelo como sus
controladores, colecciones en tu propio Postgres, un solo runner detrás de cada
superficie y un rastro de auditoría que se escribe incluso cuando un run falla.

[Las siete, una a una, y qué comprobar en cualquier otro producto →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Por qué existe { #why-it-exists }

La mayoría de los frameworks de agents te dan una biblioteca. Escribes Python,
lo despliegas, y cada cambio en el comportamiento de un agent es un pull
request, una revisión y una release.

Esa es la forma correcta para una función de producto. Es la forma equivocada
para los cuarenta agents pequeños que una empresa quiere de verdad, porque **la
persona que sabe qué debe decir el agent no es la persona con acceso de
commit.**

Así que AgenticOS saca el agent del código y, en su lugar, pone gobernanza a su
alrededor.

<div class="grid cards" markdown>

- :material-shield-check:{ .lg .middle } **Budgets que detienen un run**

    Comprobados *antes* de cada petición al modelo, no después. Un run que falla
    registra igualmente lo que gastó, porque un budget que ignora los fallos no
    es un budget.

- :material-hand-back-right:{ .lg .middle } **Aprobación para todo lo que tiene efectos**

    Una herramienta que actúa sobre el mundo exterior aparca el run y espera a
    una persona. Se fija por capability y se puede anular por herramienta.

- :material-account-key:{ .lg .middle } **Permisos en el código, roles compuestos a partir de ellos**

    Los puntos de llamada comprueban permisos, nunca nombres de rol. Una
    concesión amplía lo que una persona puede hacer con una fila; nunca lo
    reduce.

- :material-database-lock:{ .lg .middle } **Aislamiento de inquilinos en el esquema**

    No solo en la capa de servicios. Un texto cifrado de una organización no se
    puede descifrar para otra.

</div>

## Requisitos { #requirements }

Docker y Docker Compose. Esa es la lista entera — Postgres (con pgvector),
Redis, la API, el worker y la consola arrancan todos juntos.

¿Prefieres ejecutar los servicios a mano? Python 3.12, Node con
[bun](https://bun.sh), PostgreSQL 16 con
[pgvector](https://github.com/pgvector/pgvector) y Redis.

## Instalación { #installation }

```bash
git clone https://github.com/vstorm-co/agenticos.git
cd agenticos
make dev
```

Eso levanta Postgres, Redis, la API, el worker y el frontend.

Luego crea una organización, un owner, un modelo y un primer agent:

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

Y abre la consola:

```bash
open http://localhost:3000
```

Inicia sesión con `admin@example.com` / `admin123`.

!!! tip

    ¿No estás seguro de que el despliegue pueda ejecutar realmente un agent?
    Pregúntaselo.

    ```bash
    uv run agenticos cmd doctor
    ```

## De qué está hecho un agent { #what-an-agent-is-made-of }

Seis decisiones, y ninguna de ellas es código. Quien sabe qué debe decir el
agent toma las seis en un navegador; publicar congela la combinación como una
versión, y esa versión es la que responde.

| | Qué decide |
|---|---|
| **Instrucciones** | Qué hace el agent, en lenguaje llano — y qué debe negarse a hacer |
| **Un perfil de modelo** | Qué modelo responde, con qué parámetros, y a qué recurre durante una caída |
| **Capabilities** | Qué puede hacer siquiera: buscar en tu conocimiento, leer una página, ejecutar Python, dibujar un gráfico |
| **Conocimiento** | Qué colecciones puede buscar, y nada fuera de ellas |
| **Aprobación** | Cuáles de esas acciones esperan a una persona antes de tocar el mundo exterior |
| **Un budget** | Cuánto puede gastar en un mes, comprobado *antes* de cada petición en lugar de contado después |

Cambia cualquiera de ellas y nada sale a producción hasta que publiques. La
versión que estaba en vivo sigue siendo legible, así que *qué aspecto tenía este
agent en marzo* tiene respuesta.

=== "Lo que alguien edita"

    ![Agents — cada uno con la versión que está en vivo y quién puede alcanzarlo](assets/screens/light/agents.webp#only-light)
    ![Agents — cada uno con la versión que está en vivo y quién puede alcanzarlo](assets/screens/dark/agents.webp#only-dark)

=== "En qué se convierte"

    Una versión congelada, y un archivo que puedes exportar a tu propio
    repositorio git, revisar en un pull request y restaurar:

    ```yaml
    name: Support Copilot
    instructions: |
      Answer from the product wiki and cite the document you used.
      If the wiki does not cover it, say so rather than guessing.
    model_profile_id: 8f1c...
    capabilities:
      - id: knowledge
        config: { default_top_k: 8 }
      - id: web_research
        approval: required
    collection_ids: [b2a9...]
    budget:
      monthly_usd: 50
    ```

## Compruébalo { #check-it }

Publícalo y se ejecuta igual en todas las superficies: el chat de la consola,
una página alojada, un widget incrustado, la API HTTP, Slack, Telegram,
Mattermost.

```bash
curl -X POST http://localhost:8000/api/v1/agents/$AGENT_ID/run \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Organization-Id: $ORG_ID" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "How do I rotate a provider key?"}'
```

Un solo runner detrás de todas ellas, así que una respuesta no depende de dónde
vino la pregunta.

## Qué obtienes { #what-you-get }

| | |
|---|---|
| **Agents** | Construidos en una UI, versionados al publicar, exportables como YAML a tu propio repositorio git |
| **[Capabilities](reference/capabilities.md)** | Retrieval, búsqueda y descarga web, un navegador de verdad, Python, una sandbox con archivos y una shell, gráficos, imágenes, delegación, planificación, guardrails — activados por agent |
| **[Integraciones](mcp.md)** | Cualquier servidor MCP por URL, con 59 de los más habituales en el selector — GitHub, Linear, Notion, Slack, Stripe, Postgres |
| **[Modelos](models.md)** | 27 providers, claves por organización, fallbacks y Ollama autoalojado o un proxy LiteLLM |
| **[Conocimiento](file-processing.md)** | Retrieval sobre tus documentos con tres parsers de PDF, tu propio chunking, OCR y descripción de imágenes — por colección, anulable por subida. Sincronización con Google Drive y S3 |
| **[Skills](skills.md)** | Conocimiento escrito que el agent carga solo cuando decide que es relevante |
| **[Gobernanza](governance.md)** | Budgets mensuales, aprobación humana, un rastro de auditoría, alertas por agent |
| **[Superficies](channels.md)** | Chat web, una página alojada sin inicio de sesión, un widget incrustable, la API HTTP, un WebSocket en crudo para tu propio frontend, Slack, Telegram, Mattermost — un solo runner detrás de todas |
| **[Secretos](secrets.md)** | Sellados por organización. Ninguna respuesta, línea de log ni entrada de auditoría lleva jamás una clave en texto plano |

[La lista completa de funciones →](features.md)

## Resumen { #recap }

- Un agent es **un archivo**, no un módulo. Instrucciones, un modelo,
  capabilities, un budget.
- Se **publica como una versión**, y esa versión es la que se ejecuta.
- Es **exportable como YAML** a tu repositorio, revisable en un pull request.
- Está **gobernado**: budgets que detienen un run, aprobaciones que esperan a
  una persona, permisos comprobados en cada punto de llamada.
- Es **tuyo**: tu Postgres, tu hardware, nada llamando a casa.

## Siguiente { #next }

<div class="grid cards" markdown>

- :material-school:{ .lg .middle } **[Aprender](learn/index.md)**

    El recorrido recomendado, en orden: instalación, primer agent, conceptos y
    después las piezas.

- :material-star-four-points:{ .lg .middle } **[Funciones](features.md)**

    Todo lo que hace la plataforma, en una sola página.

- :material-book-open-variant:{ .lg .middle } **[Referencia](configuration.md)**

    Ajustes, comandos de la CLI, el spec del agent, los catálogos de
    capabilities y de permisos.

- :material-account-group:{ .lg .middle } **[La implantación](rollout.md)**

    Para quien tiene la decisión y no la instalación: quién hace qué, cuánto
    cuesta y qué preguntará tu revisión de seguridad.

- :material-information-outline:{ .lg .middle } **[Acerca de](about/index.md)**

    Por qué existe, qué no es a propósito, y las seis decisiones que lo
    moldean.

</div>

## Stack { #stack }

FastAPI y Pydantic v2 sobre PostgreSQL, [Pydantic AI](https://ai.pydantic.dev)
para el runtime del agent, pgvector para retrieval, Prefect para el trabajo en
segundo plano y Next.js 15 para la consola.

Nada de esto llama a casa: los precios de los modelos vienen de una instantánea
incluida, y las únicas llamadas salientes son las que hacen tus agents.

## Licencia { #licence }

Apache-2.0. Consulta
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
