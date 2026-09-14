---
source_sha: "ff4961c85112"
---

# Acerca de AgenticOS { #about-agenticos }

AgenticOS es el sistema operativo para los agents de IA de una empresa:
autoalojado, de código abierto, multiinquilino.

Existe por una observación. La mayoría de los frameworks de agents te dan una
biblioteca — escribes Python, lo despliegas, y cada cambio en el comportamiento
de un agent es un pull request, una revisión y una release. Eso es exactamente lo
correcto para una funcionalidad de producto y exactamente lo incorrecto para los
cuarenta agents pequeños que una empresa quiere de verdad, porque quien sabe lo
que el agent debería decir no es quien tiene acceso de commit.

Así que aquí **el código define y la configuración compone**. Un equipo de
negocio monta agents en un navegador — instrucciones, un modelo, un conjunto de
capabilities, un budget — y los ingenieros amplían lo que hay para montar, en
Python tipado. La configuración solo puede alcanzar aquello que el código
registró, y eso es lo que hace seguro poner un Builder sin código en manos de
alguien que no es ingeniero.

El spec es un documento, así que se versiona al publicarlo y se exporta como YAML
a tu propio repositorio git. El techo no es ese documento: es lo que tus
ingenieros pongan en el registro.

## Qué convierte algo en un sistema operativo para agents { #what-makes-something-an-operating-system-for-agents }

La palabra se usa a la ligera en esta categoría, y la queja es justa. Vale la
pena decir qué tiene que significar, porque un sistema operativo no es un estado
de ánimo: son siete funciones, y un producto o las cumple o no las cumple.

Úsala como prueba. Aplícala a AgenticOS, y aplícala a cualquier cosa con la que
lo estés comparando.

| Un sistema operativo… | …y para agents eso es |
|---|---|
| **Ejecuta procesos y los aísla** | Un run es el proceso. Arranca, se puede parar, está aislado de otros inquilinos y deja constancia de lo que hizo |
| **Impone límites de recursos** — cuotas, cgroups | Un budget, comprobado *antes* de permitir el trabajo en vez de sumado después, sobre una unidad de la que alguien responde |
| **Controla el acceso** — usuarios, permisos, `sudo` | Permisos comprobados en el punto de llamada, no nombres de rol; y una vía de escalado para todo lo que actúa sobre el mundo exterior |
| **Llega al hardware a través de drivers** | Una sola interfaz hacia muchos providers de modelos y muchos servidores de tools, de modo que cambiar cualquiera de ellos no reescribe lo que los usa |
| **Mantiene un sistema de ficheros** | Un sitio duradero para el conocimiento propio de la organización, con las reglas de acceso pegadas a él |
| **Da una sola shell a muchas interfaces** | El mismo agent respondiendo en cada superficie a través de un único camino de ejecución, en vez de que cada superficie monte el suyo |
| **Escribe un registro de auditoría** | Quién ejecutó qué, cuándo, cuánto costó, quién lo aprobó — escrito tanto si el run tuvo éxito como si no |

### Cómo responde AgenticOS a cada una { #how-agenticos-answers-each-one }

| | |
|---|---|
| Procesos | Los runs son de primera clase: historial, coste, estado, y un aislamiento entre inquilinos que imponen restricciones de base de datos en vez del código de servicio |
| Límites de recursos | [Budgets mensuales](../governance.md) por agent, comprobados antes de cada petición al modelo. Un run que falla registra igualmente lo que gastó, porque un budget que ignora los fallos no es un budget |
| Control de acceso | Un [catálogo de permisos](../permissions.md) en código, roles compuestos a partir de él, grants por recurso que amplían y nunca reducen. `approval: required` es el `sudo` — el run se aparca y espera a una persona |
| Drivers | [27 providers de modelos](../models.md) detrás de un perfil de modelo, y [cualquier servidor MCP por URL](../mcp.md). Cambia el perfil y todos los agents que lo usan se mueven con él, sin republicar ninguno |
| Sistema de ficheros | [Colecciones, skills y context](../file-processing.md) en tu propio Postgres, con embeddings que usan una clave por organización |
| Shell | Un único runner detrás del [chat web, la API, Slack, Telegram, un widget, una página alojada y un horario](../channels.md) |
| Registro de auditoría | Cada run, cada decisión de aprobación, cada rotación de secreto — con valores, nunca con filas, y nunca con una clave en texto plano |

!!! info "Por qué la prueba está escrita para aplicárnosla también a nosotros"

    Una lista de comprobación que solo produce una respuesta es marketing. Esta
    es de verdad aplicable a cualquier producto de la categoría, y es como nos
    gustaría que se nos juzgara — incluida la fila de abajo, donde la respuesta
    aún no es lo bastante buena.

### En qué no está terminado este { #where-this-one-is-not-finished }

La monitorización es la más floja de las siete. Cada run registra un
`logfire_trace_id` y todavía nadie lo lee, así que lo que obtienes hoy es
historial de runs, coste y estado en lugar de una tendencia sobre la que actuar.
Está en [la hoja de ruta](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md)
como R11.

Otras dos lagunas que conviene conocer antes de comparar: todavía no hay SAML ni
SCIM — el inicio de sesión es JWT, claves de API, Google OAuth y enlaces mágicos
— y no hay un entorno de evaluación, así que probar un agent antes de publicarlo
es algo que haces a mano.

## Para quién es { #who-it-is-for }

Para una empresa que quiere más de tres agents, y los quiere gobernados.

- **Quien construye el agent** no escribe Python. Escribe instrucciones, activa
  capabilities, apunta a una colección de conocimiento y fija un budget.
- **Quien responde de la factura** obtiene budgets que detienen un run,
  aprobaciones para todo lo que tenga efectos secundarios y un rastro de
  auditoría.
- **El ingeniero** obtiene un spec que se exporta como YAML a su propio
  repositorio git, una API HTTP y una plataforma cuyo código fuente puede leer.

## Lo que deliberadamente no es { #what-it-deliberately-is-not }

**No es un framework para escribir un solo agent.**
[Pydantic AI](https://ai.pydantic.dev) es el runtime que hay debajo, y si lo que
quieres es un único agent en Python como parte de un producto, úsalo
directamente.

Eso no equivale a decir que esto esté cerrado al código. Ampliarlo *es* Python —
una [capability](../howto/add-capability.md) es código tipado y probado en este
repositorio, y un connector, un canal o una estrategia de ingesta siguen el mismo
patrón. La diferencia es que escribes la tool una vez y después todo el mundo
compone con ella.

**No es un servicio alojado.** Nada llama a casa. Los precios de los modelos
vienen de una instantánea incluida con la release, y las únicas peticiones
salientes son las que hacen tus agents. Un sistema operativo se instala en tu
propia máquina; nadie alquila un kernel por puesto.

**No es un sitio donde escribir integraciones.** Una integración con un producto
SaaS es una [conexión MCP](../mcp.md), no un módulo de Python que alguien de este
repositorio mantiene contra la API de ese producto. Por eso el catálogo de
capabilities es corto y sigue siéndolo.

## La parte que realmente es el producto { #the-part-that-is-actually-the-product }

Casi todo el valor está aquí en lo que la plataforma **rechaza**: una lectura
entre inquilinos, un scope no concedido, una superación del budget, una segunda
decisión sobre una aprobación ya decidida, un spec que no pasa la validación al
publicarse.

El camino feliz — una llamada al modelo con unas cuantas tools enganchadas — es
la mitad fácil, y una docena de bibliotecas lo hacen bien. Los rechazos son la
mitad que decide si puedes poner un agent en manos de alguien que no eres tú.

## Cuándo usar otra cosa { #when-to-use-something-else }

Cuatro de las siete funciones son cosas que una biblioteca nunca hará por ti, y
tres de ellas son cosas que una plataforma alojada hace sin darte la máquina.
Ninguna de las dos opciones merece un reproche; son productos distintos.

[Cuál elegir, y cuándo →](comparison.md)

## De dónde viene { #where-it-came-from }

Generado a partir de la
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
y por eso "la capa de plataforma" y "heredado de la plantilla" son distinciones
que aparecen en la documentación para quien contribuye. La capa de plataforma —
todo lo que AgenticOS añade encima — se mantiene al 100 % de cobertura de tests
en CI. Los subsistemas heredados se reportan pero no bloquean la build, porque
someter código que no diseñamos al mismo listón compra un número de cobertura en
lugar de confianza.

Las seis decisiones que hay detrás de su forma — por qué un agent es un fichero,
por qué el formato del spec solo avanza hacia adelante, por qué la validación
ocurre al publicar — están escritas para quien contribuye en
[`docs/about/design.md`](https://github.com/vstorm-co/agenticos/blob/main/docs/about/design.md).

## Quién lo construye { #who-builds-it }

[Vstorm](https://vstorm.co), y quienquiera que envíe un pull request.

## Resumen { #recap }

- **El código define, la configuración compone** — un equipo de negocio monta
  agents, los ingenieros amplían lo que hay para montar, y ninguno espera al
  otro.
- "Sistema operativo" es aquí una **especificación, no una etiqueta** — siete
  funciones, cada una con un mecanismo detrás.
- La prueba está pensada para **aplicarse también a otros productos**, y a este:
  la monitorización es la fila donde la respuesta honesta es "todavía no".
- El producto son sobre todo los **rechazos**, no el camino feliz.
- Se ejecuta en **tu máquina**, porque eso es lo que hace un sistema operativo.

[Cuándo usar otra cosa →](comparison.md) · [Instálalo →](../install.md)
