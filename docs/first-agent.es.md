---
source_sha: "86db3a8931da"
---

# Tu primer agent { #your-first-agent }

Esto recorre el camino entero una vez: una clave de provider, un modelo, un agent
que responde, una versión publicada y un run con un coste apuntado.

Quince minutos, y alrededor de un céntimo de tokens.

Antes necesitas un stack en marcha — consulta [Instalación](install.md).

!!! tip "El producto también te guía por esto"

    La primera vez que alguien inicia sesión se abre un recorrido guiado en el
    dashboard, y al terminarlo se ofrece a construir el primer agent *contigo*,
    manejando los diálogos reales.

    El camino manual merece una lectura de todas formas, y eso es esta página.
    El guiado se describe [al final](#the-guided-walkthrough).

## 1. Guarda una clave de provider { #1-store-a-provider-key }

**Settings → Vault → Add credential.**

Elige un provider, pega la clave, ponle una etiqueta. El valor se sella al
instante, y no hay ningún endpoint que lo devuelva — lo que vuelve es una
etiqueta y los últimos cuatro caracteres.

!!! info "Por qué un vault y no un archivo de configuración"

    Una clave en el entorno pertenece al despliegue. Una clave en el vault
    pertenece a una **organización**, y eso es lo que permite que un solo
    despliegue sirva a varios inquilinos sin que ninguno pueda gastar el budget
    del otro.

    El texto cifrado queda ligado a la organización que lo guardó, y no puede
    descifrarse para otra.

## 2. Añade un modelo { #2-add-a-model }

**Agents → cualquier agent → Build → Model.**

Elige un provider, luego un modelo, y luego qué clave guardada lo paga.

La lista de modelos viene del provider allí donde este publica una, y de una
preselección incluida allí donde no. Es una sugerencia, nunca una restricción —
un provider saca un modelo la mañana siguiente al precalentado de cualquier
catálogo, así que se acepta cualquier cosa que escribas.

Lo que acabas de crear es un **perfil de modelo**: un modelo con nombre
respaldado por una clave con nombre.

Ponerle nombre es justo el objetivo. Te deja rotar la clave, o reapuntar todos
los agents a un modelo nuevo, sin tocar ni un solo agent.

## 3. Construye el agent { #3-build-the-agent }

**Agents → New agent.**

!!! tip "O parte de una plantilla"

    **Agents → Agent templates** trae veintiocho agents listos agrupados por
    sector, cada uno con sus instrucciones escritas, sus capabilities activadas
    y los skills que necesita instalados a su lado.

    Llega como **borrador** y no publicado, y es deliberado: una plantilla no
    puede elegir tu modelo, y nunca ha visto tu colección de conocimiento. El
    resto de esta página es lo que haces a continuación en cualquier caso.

El nombre pasa a ser el identificador por el que se le llama desde Slack y desde
la API, y queda congelado al crearlo — `Support Copilot` se convierte en
`@support-copilot`.

La pestaña **Build** son instrucciones y un modelo, y las instrucciones son todo
el comportamiento del agent:

```markdown
You are Support Copilot.

Answer from the product wiki and cite the document you used.
If the wiki does not cover it, say so rather than guessing.
Never quote a price - route those to sales.
```

Escríbelas en Markdown. El modelo lee la estructura, y los encabezados y las
listas son lo que hace seguible un prompt largo.

!!! note "No hay ningún botón de guardar"

    El borrador se guarda solo mientras escribes. Un Builder con botón de
    guardar es un Builder en el que la pestaña se cerró sobre veinte minutos de
    instrucciones.

## 4. Dale capabilities { #4-give-it-capabilities }

**Toolbox.**

Cada capability muestra exactamente qué aporta — cada tool, su descripción y los
argumentos que el modelo tiene que rellenar — *antes* de que la actives. Leer una
capability no es concederla.

Aquí hay dos cosas que conviene saber:

- **El nombre y la descripción de una tool son prompt.** Se echa mano de
  `search_refund_policy` en preguntas en las que `search_documents` se queda sin
  usar. Ambos son editables por agent.
- **Todo lo que tiene efectos pide aprobación por defecto.** El run se aparca y
  espera a una persona. Configúralo por capability, o por tool.

## 5. Dale algo que leer { #5-give-it-something-to-read }

**Knowledge → Collections** para documentos. **Skills** para el saber hacer
escrito.

La diferencia importa:

| | |
|---|---|
| Una **colección** se *busca* | El modelo elige qué buscar, y nunca puede ampliar dónde busca |
| Un **skill** se *lee* | El agent lo carga solo cuando decide que el skill viene al caso, así que veinte skills no cuestan casi nada de contexto |

Cada colección dice cuántos documentos contiene, porque adjuntar una vacía
produce un agent que busca, no encuentra nada y lo dice — lo cual se lee como un
agent roto y no como una colección vacía.

## 6. Pon un límite, y di a quién se avisa { #6-set-a-limit-and-say-who-is-told }

**Limits.** Un tope mensual en dólares, un límite de pasos, y quién se entera.

El límite de pasos es el que se olvida. Atrapa el otro tipo de desbocamiento: un
bucle de tools que es barato por llamada y no termina nunca. Un budget solo
factura ese; un límite de pasos lo detiene.

Bajo **Alerts**, decide a quién se avisa cuando este agent se para en su tope o
se aparca en una aprobación. Por defecto, los admins y el owner del agent se
enteran del budget, y quien arrancó el run más los admins se enteran de las
aprobaciones — para que un run que arrancó un horario no se aparque sin que nadie
lo mire.

[Governance](governance.md) cuenta cómo encajan budgets, aprobaciones y alertas.

## 7. Publica { #7-publish }

**Publish** valida primero el borrador, así que también es aquí donde te enteras
de que el spec referencia una colección que alguien borró.

!!! success "Un spec que referencia algo que falta se rechaza aquí, nunca en tiempo de ejecución"

    Y esa es toda la razón de que la validación ocurra al publicar: hay alguien
    mirando un formulario que puede arreglarlo, en lugar de enterarse tres
    semanas después en un run que arrancó un horario.

Publicar congela una **versión**. Los runs registran qué versión se ejecutó, así
que lo que un agent hizo el martes pasado sigue teniendo respuesta después de una
docena de ediciones.

## 8. Ejecútalo { #8-run-it }

**Test**, en la cabecera, abre un chat contra el agent publicado. Pregúntale
algo.

Luego mira **Activity**: el run, la versión que ejecutó, el modelo que resolvió,
los tokens y lo que costó. Si una tool necesitó aprobación, está ahí en la cola.

## 9. Ponlo en algún sitio { #9-put-it-somewhere }

**Availability** es donde un agent deja de ser una cosa dentro de un Builder:

| | |
|---|---|
| **Exposures** | Quién puede ejecutarlo, y cómo — claves de API, enlaces públicos |
| **Channel bots** | Slack y Telegram. `@support-copilot` en un canal se ejecuta como el *remitente*, nunca como el bot |
| **Embeds** | Un widget para tus propias páginas |
| **Environments** | Punteros con nombre a versiones, para que staging y producción puedan diferir |

## Expórtalo { #export-it }

**Download** te da el spec en YAML.

Nombra referencias — un perfil de modelo, una colección, un secreto — y nunca
valores, que es lo que hace seguro subirlo a tu propio repositorio y revisarlo
como código.

```yaml
name: Support Copilot
instructions: |
  You are Support Copilot.
  Answer from the product wiki and cite the document you used.
model_profile_id: 8f1c...
capabilities:
  - id: knowledge
    config: { default_top_k: 8 }
collection_ids: [b2a9...]
budget:
  monthly_usd: 50
```

## Recapitulación { #recap }

Nueve pasos, y su forma es la forma de la plataforma:

1. Sellaste una **clave** en el vault, por organización.
2. Nombraste un **perfil de modelo**, para que la clave y el modelo puedan
   cambiar sin que cambie el agent.
3. Escribiste **instrucciones**.
4. Activaste **capabilities**, y dejaste que las que tienen efectos pidan
   aprobación.
5. Adjuntaste **conocimiento** para buscar y **skills** para leer.
6. Pusiste un **budget** y un **límite de pasos**, y dijiste a quién se avisa.
7. **Publicaste**, lo que congeló una versión y validó el spec.
8. Lo **ejecutaste**, y viste lo que costó.
9. Lo hiciste **alcanzable** desde algún sitio que no fuera el Builder.

Todo lo que viene después es más de los pasos 4, 5 y 9.

## El recorrido guiado { #the-guided-walkthrough }

El producto se enseña a sí mismo, y merece la pena saber cómo — porque el
recorrido es también la forma en la que lo aprenderá cualquiera a quien le pases
esto.

**Se muestra una vez, y el ? lo reproduce.** Que se termine, se salte o se cierre
queda recordado en la cuenta y no en el navegador, así que no vuelve en el
siguiente dispositivo. El **?** de la cabecera de cualquier página recorrida
reproduce los avisos de esa página siempre que se quieran.

Solo se ofrece donde hay algo que reproducir. Una sección sin paradas — las
páginas de administración del despliegue — **no tiene ?** en absoluto, en lugar
de uno que abra un recorrido vacío. Al salir, el recorrido dice exactamente eso,
para que nadie descubra el **?** por accidente o no lo descubra nunca.

**Al terminarlo se ofrece a construir el primer agent juntos.** Eso es un flujo
interactivo, no un foco: señala los controles reales, tú manejas los diálogos
reales, y avanza en el momento en que la cosa queda realmente creada.

Mientras corre, la página está **congelada** — todo se atenúa salvo el único
control del que trata el paso, así que no puedes irte por ahí a mitad de flujo y
dejar varado un paso guiado en la página equivocada. La congelación se aparta
sola en cuanto se abre un diálogo o un selector, para que el control que señala
el paso siempre se pueda usar.

Es adaptativo. Recorre el camino de arriba, comprueba qué tiene ya la
organización y solo se para donde falta algo — enseñando a un workspace sin
modelo cómo añadir uno, o diciéndole eso mismo a un builder que no tiene el
permiso para añadirlo, en lugar de llevarlo en silencio hasta un publish que
rechazará un agent sin modelo.

**Donde más trabajo hace es en Knowledge, Skills y MCP.** Si ya hay uno, el flujo
se limita a señalar dónde se adjunta. Si no hay ninguno, primero cruza a la
pantalla propia de esa sección y *pregunta allí* — "todavía no hay base de
conocimiento, ¿creamos una?" — para que la pregunta aterrice donde ocurre la
respuesta.

Un sí guía la creación en el sitio, y no solo hasta el botón: el recorrido te
sigue dentro del propio diálogo, encuadrando cada campo por turnos con lo que va
en él — el nombre de un skill por el que lo llama el modelo, la descripción que
decide cuándo se lee, el cambio a Source donde se escribe el saber hacer — y
sigue adelante cuando la cosa queda realmente creada.

Luego te lleva de vuelta *señalando*: a **Agents** en la barra lateral, al lápiz
de edición del mismísimo agent que acabas de construir, a la pestaña Knowledge
donde se adjunta la base nueva. El tramo de vuelta espera tu clic en lugar de
navegar por ti, así que enseña el camino por la aplicación en vez de recorrerlo
él. Saltárselo vuelve al builder por su cuenta.

MCP se bifurca igual, pero se queda en el builder. Un servidor se conecta con un
diálogo en línea ahí mismo, en la Toolbox, así que un sí señala ese botón y el
flujo retoma en el momento en que la conexión aterriza — ni un viaje a otra
página, ni otro de vuelta.

**No termina en Publish.** Después de que Publish aterrice, el flujo te lleva al
chat, te hace elegir el agent que acabas de construir y solo se cierra cuando le
has mandado un primer mensaje. Un primer agent que nadie ha ejecutado es una
visita guiada que se paró a un paso de lo que importaba.

**Cada una de las demás secciones tiene el suyo.** Rechazarlo no guía a nadie, y
la oferta vuelve al final del recorrido del **?** de Agents. El **?** de cada una
de las demás secciones termina igual, ofreciendo crear el recurso de esa
sección — un skill, una base de conocimiento, una conexión MCP, una
organización, una rutina.

Dos de ellos tienen a propósito otra forma:

- **Routines** termina *más allá* de su propia creación. Un horario que se queda
  esperando al reloj no enseña nada, así que la última parada del recorrido es el
  **Run now** de la fila recién creada, y el primer disparo aterriza en el
  registro de runs mientras miras.
- **Chat** ofrece un recorrido guiado por la propia superficie de chat: empezar
  una conversación, cambiar qué agent responde, cambiar el modelo o el esfuerzo
  de razonamiento para un solo chat. Chat solo puede hablar con un agent
  *publicado*, así que sin ninguno abre ofreciendo construir uno primero, y pasa
  directamente al flujo del agent. Pasado eso no crea nada, así que avanza con
  Next.

!!! tip "Reproduce una vez el ? del dashboard"

    Su parada de personalización explica el editor entero: añadir tarjetas del
    catálogo (la misma tarjeta más de una vez, si la quieres por agent),
    arrastrarlas entre secciones, redimensionar, ocultar, renombrar y dar color a
    las secciones mismas, disposiciones con nombre, y el reinicio.

    Cada disposición es por persona, así que experimentar no mueve la página de
    nadie más.

## Siguiente { #next }

<div class="grid cards" markdown>

- :material-lightbulb:{ .lg .middle } **[Conceptos](concepts.md)**

    Spec, versión, exposición, trigger, run — los cinco sustantivos que acabas
    de usar.

- :material-shield-check:{ .lg .middle } **[Governance](governance.md)**

    Budgets, aprobaciones, alertas, auditoría.

- :material-account-key:{ .lg .middle } **[Permisos](permissions.md)**

    Quién puede hacer qué, y sobre qué filas.

</div>
