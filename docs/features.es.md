---
source_sha: "bf54d6dd6a38"
---

# Funciones { #features }

AgenticOS te da lo siguiente.

## El código define, la configuración compone { #code-defines-configuration-composes }

Esa única frase es todo el diseño, y describe dos mitades que a propósito no son
el mismo trabajo.

**Un equipo de negocio compone agents en un navegador.** Instrucciones, un
modelo, un conjunto de capabilities, un budget — nada de Python, ni pull request,
ni release. El spec es un documento, así que se versiona al publicarlo y se
exporta como YAML a tu propio repositorio de git.

A la consola le basta con un navegador. La [aplicación de escritorio](desktop.md)
envuelve esa misma consola para quien la quiera en el dock - con una mascota y un
atajo de captura de pantalla - y es un complemento, no una segunda forma de
ejecutar la plataforma.

**Los ingenieros amplían lo que hay para componer.** Una capability es Python
tipado y probado en este repositorio: una tool que el modelo puede llamar, un
guardrail, una estrategia de compactación, un conector. Añades una y, desde ese
momento, es un interruptor en el Builder de todo el mundo.

La regla entre las dos mitades es la parte que sostiene el edificio:

!!! quote "La configuración solo puede alcanzar lo que el código registró"

    Que es exactamente lo que hace seguro poner un Builder no-code en manos de
    alguien que no es ingeniero. No puede inventarse una tool, ampliar un scope
    ni alcanzar un sistema que nadie ha cableado — lo peor que puede hacer es
    montar cosas que ya estaban aprobadas.

Así que el techo no es un archivo de configuración. Es lo que tus ingenieros
pongan en el registry, y la plataforma es Apache-2.0, así que eso incluye todo lo
que escribas para tu propio caso de uso.

| Lo que quieres | Lo que haces |
|---|---|
| Otra respuesta de un agent | Edita las instrucciones y publica. Segundos, sin ingeniero |
| Una tool para un producto SaaS | Apunta a [un servidor MCP](mcp.md). Normalmente, nada de código |
| Una tool que no ha escrito nadie | [Añade una capability](howto/add-capability.md) — Python tipado, y aparece en el Builder |
| Otra ingesta, otro canal u otro conector | [Amplía la plataforma](resources/index.md#extending-the-platform); el mismo patrón cada vez |
| Todo el conjunto amoldado a un proceso | Fórkalo. Es tu despliegue y tu código fuente |

!!! tip "La separación es justo el objetivo"

    Quien sabe lo que el agent debería decir rara vez es quien tiene acceso de
    commit — y quien sabe escribir una tool no debería pasarse la semana
    cambiando redacciones. Esta es la línea que permite a los dos trabajar sin
    esperar al otro.

!!! info "Por qué esto se llama un sistema operativo"

    Porque la palabra es una especificación y no una etiqueta: procesos, límites
    de recursos, control de acceso, drivers, un sistema de archivos, una sola
    shell para muchas interfaces y un registro de auditoría. De cada uno hay un
    mecanismo en esta página.
    [Los siete, y cómo medir cualquier otro producto con ellos →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Construido en una UI, versionado al publicar { #built-in-a-ui-versioned-on-publish }

Construyes el agent en el navegador. Cuando lo publicas, el spec se congela como
una versión y esa versión es la que se ejecuta — un borrador que sigues editando
no llega nunca a nadie.

Toda versión publicada sigue siendo legible, así que *qué aspecto tenía este
agent en marzo* es una pregunta con respuesta.

## Exportable a tu propio repositorio { #exportable-into-your-own-repository }

El spec se exporta como YAML. Haz commit de él, revísalo en un pull request,
compara dos versiones, restaura una. Es tu archivo, en tu historial de git, en un
formato que no necesita AgenticOS para leerse.

La importación va en sentido contrario, así que un spec escrito a mano es un
agent de pleno derecho.

## Lo que un agent puede hacer de verdad { #what-an-agent-can-actually-do }

Lo decides tú activando cosas, de una en una, en el Builder. Nada de esto es un
plugin que alguien instala, un archivo de Python que alguien despliega ni un
prompt que alguien espera que el modelo obedezca — un agent no puede alcanzar una
capability que está desactivada, diga lo que diga en sus instrucciones.

| El agent puede… | Qué activar |
|---|---|
| **Responder a partir de lo que tu empresa sabe** — tus documentos, tus procedimientos escritos y lo que se haya adjuntado a esta conversación | Knowledge search · Skills · Context |
| **Recordar, y consultarlo** — llevar notas de una conversación a otra, recuperar un dato por su significado, o encontrar lo que se dijo realmente en una conversación pasada y releerlo | Memory files · Memory (mem0) · Conversation search |
| **Ir a averiguarlo** — buscar en la web, leer una página como es debido, o conducir un navegador real por un sitio que exige clics | Web search · Web fetch · Browser automation |
| **Hacer el trabajo, no describirlo** — ejecutar Python sobre un archivo, mantener un workspace con una shell, dibujar un gráfico, generar una imagen | Run Python · Files & shell · Charts · Image generation |
| **Afrontar trabajo demasiado grande para una sola respuesta** — delegar en especialistas, llevar una lista de tareas, pensar más antes de responder, sostener una conversación larga sin perder su principio | Delegation · Planning · Thinking · Context management |
| **No salirse de la raya** — censurar o bloquear lo que no debe pasar, limitar lo que una tool puede devolver, saber qué día es hoy | Guardrails · Tool output limits · Date and time |

Cada una trae sus propios ajustes, su propio scope de permisos y — cuando actúa
sobre el mundo exterior — su propio ajuste de aprobación. Activar una es una
decisión que alguien toma sobre *este* agent, no un cambio en la plataforma.

[Cada capability, sus tools y su configuración →](reference/capabilities.md)

## Cualquier modelo, de 27 providers { #any-model-from-27-providers }

OpenAI, Anthropic, Google, Groq, Mistral, Bedrock, Vertex, un Ollama en tu propio
hardware, un proxy LiteLLM por delante de todo ello.

Un **perfil de modelo** nombra el modelo, sus parámetros y sus fallbacks; los
agents apuntan al perfil. Cambia el perfil y todos los agents que lo usan se
mueven con él — sin republicar un solo spec.

Las claves son por organización, están selladas en el vault y ningún endpoint las
devuelve jamás.

[Modelos y providers →](models.md)

## Cualquier servidor MCP, por URL { #any-mcp-server-by-url }

Conecta un servidor y sus tools aparecen en la Toolbox, con espacio de nombres
propio para que dos servidores que ofrecen `search` no choquen.

**Hay 5.802 servidores en el selector.** 99 de los más habituales — GitHub,
Linear, Notion, Slack, Stripe, Postgres — llegan con sus flujos de OAuth ya
cableados, porque aquí alguien conectó cada uno de ellos y lo comprobó. Los
otros 5.703 están replicados del registro público de MCP y se pueden buscar por
nombre: a esos no los ha revisado nadie de aquí, y la lista dice de qué tipo es
cada fila.

!!! info

    Por eso el catálogo de capabilities es corto y seguirá siéndolo. Una
    integración con un producto SaaS es una conexión MCP, no un módulo de Python
    que alguien de este repositorio tenga que mantener contra la API de ese
    producto.

[Conexiones MCP →](mcp.md)

## Conocimiento que se queda en tu hardware { #knowledge-that-stays-on-your-hardware }

Sube documentos, o sincroniza una carpeta de Google Drive o un bucket de S3.
AgenticOS los parsea, los trocea en chunks, los embebe en pgvector y los guarda
en *tu* Postgres.

**Cómo los lee lo decides tú**, por colección y con posibilidad de anularlo en
cada subida — algo poco habitual, y donde de verdad se gana la calidad del
retrieval:

| | |
|---|---|
| **Parser de PDF** | `pymupdf` — local, rápido y el único que extrae las imágenes incrustadas para describirlas · `liteparse` — local y consciente del layout, mantiene las tablas como rejillas ASCII en lugar de aplanarlas · `llamaparse` — un servicio en la nube que se factura por página y devuelve markdown |
| **Chunking** | `recursive`, `markdown` o `fixed`, con tu propio tamaño y solapamiento |
| **OCR** | A demanda o automático, con un idioma |
| **Imágenes en documentos** | Descritas por un perfil de modelo que tú eliges, con tu propio prompt |

Los embeddings llevan una clave por organización. Un vector escrito para un
tenant no lo puede leer otro, y eso lo impone el esquema en lugar de una cláusula
`WHERE` que alguien tenga que recordar.

El modelo de embedding queda fijado al crear una colección, porque dos modelos
del mismo ancho escriben en espacios distintos que la búsqueda seguiría
comparando.

[Procesamiento de archivos →](file-processing.md) · [Skills →](skills.md)

## Un agent, todas las superficies { #one-agent-every-surface }

Publica una vez. El mismo runner responde en todas estas:

- **Chat web** en la consola
- **Una página alojada** cuyo enlace puedes mandarle a alguien
- **Un widget embebible** para tu propio sitio
- **La API HTTP**, y un WebSocket en crudo para streaming
- **Slack**, **Telegram** y **Mattermost**, donde una `@mention` se ejecuta como
  la persona que la envió — no como el bot

[Superficies →](channels.md)

## Budgets que de verdad paran un run { #budgets-that-actually-stop-a-run }

Se comprueba **antes** de cada petición al modelo, no se suma después.

Un run que falla registra igualmente lo que gastó, porque un budget que solo
cuenta los éxitos no es un budget. Las alertas se disparan en los umbrales que tú
fijes, por agent.

## Aprobación para cualquier cosa con efectos secundarios { #approval-for-anything-side-effecting }

Una tool que cambia el mundo exterior aparca el run y espera a una persona.
Configúralo por capability, anúlalo por tool.

Una aprobación se decide una sola vez. Una segunda decisión sobre una aprobación
ya decidida se rechaza — lo que suena obvio hasta que has visto la race condition
que lo hace necesario.

[Governance →](governance.md)

## Permisos en el código, roles compuestos a partir de ellos { #permissions-in-code-roles-composed-from-them }

Los puntos de llamada comprueban permisos, nunca nombres de rol. Un rol es un
conjunto de permisos sacados de un catálogo, y una **concesión** (*grant*) amplía
lo que una persona puede hacer con una fila.

Una concesión nunca reduce. Un Viewer con una concesión explícita de `edit` sobre
un agent puede editar ese agent — y nada más.

[Permisos →](permissions.md)

## Secretos sellados por organización { #secrets-sealed-per-organization }

Claves de provider, tokens de bot, credenciales MCP — un solo mecanismo,
`app/core/vault.py`, y deliberadamente ningún segundo.

Un texto cifrado copiado de la fila de base de datos de un tenant no se puede
descifrar para otro. Ninguna respuesta, línea de log ni entrada de auditoría
lleva jamás una clave en claro.

[Secretos y el vault →](secrets.md)

## Multi-tenant, en el esquema { #multi-tenant-in-the-schema }

El aislamiento entre organizaciones son constraints y claves, no convención. Los
tests interesantes de este repositorio son los que comprueban un *rechazo*: una
lectura entre tenants, un scope no concedido, un budget superado, una segunda
decisión sobre una aprobación ya decidida.

## Triggers, para que un agent se ejecute sin ti { #triggers-so-an-agent-runs-without-you }

Programa un run, o dispara uno con un evento. El mismo spec, el mismo budget, el
mismo rastro de auditoría — solo que sin nadie tecleando.

[Triggers →](triggers.md)

## Autoalojado, y silencioso { #self-hosted-and-quiet }

Docker Compose, tu Postgres, tu Redis, tu hardware.

Nada llama a casa. Los precios de los modelos vienen de una instantánea incluida
en la release, y las únicas peticiones salientes son las que hacen tus agents.

## Código abierto { #open-source }

Apache 2.0, auditable y forkable. El formato del spec está versionado, así que un
documento que exportes hoy seguirá cargando mañana.

[Instálalo →](install.md) · [Construye tu primer agent →](first-agent.md)
