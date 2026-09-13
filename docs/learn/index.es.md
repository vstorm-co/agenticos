---
source_sha: 80ee04abded5
---

# Aprende { #learn }

Las secciones de abajo son la forma recomendada de aprender AgenticOS, en orden.
Léelas como un curso: cada una da por leídas las anteriores, y ninguna da por
supuesto que hayas leído el código.

## Primeros pasos { #get-started }

Necesitas un stack en marcha y un agent que te responda. Unos veinte minutos.

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Instalación](../install.md)**

    Docker Compose, o los servicios a mano. Cinco minutos hasta un stack que
    puedes abrir en un navegador.

- :material-rocket-launch:{ .lg .middle } **[Tu primer agent](../first-agent.md)**

    Una clave de provider, un agent, una versión publicada, un run que costó algo.

- :material-lightbulb:{ .lg .middle } **[Conceptos](../concepts.md)**

    Spec, versión, exposición, disparador, run. Cinco sustantivos. Todo lo demás
    se construye con ellos, así que esta es la página a la que volver cuando algo
    te sorprenda.

</div>

!!! tip

    Lee **Conceptos** aunque tengas prisa. Casi toda la confusión sobre esta
    plataforma es uno de esos cinco sustantivos tomado por otro — un *spec* por
    una *versión*, una *exposición* por un *disparador*.

!!! tip "¿Perdido en la consola?"

    [La consola](../console.md) es el mapa de todas las áreas — para qué sirve
    cada una y qué página la explica.

## Construye el agent { #build-the-agent }

Ahora hazlo bueno. Cada página de aquí es una cosa que le das al agent, y son
independientes — coge las que tu agent necesite.

<div class="grid cards" markdown>

- :material-compass-outline:{ .lg .middle } **[Elegir un modelo](../choosing-models.md)**

    Qué modelo debería usar este agent — de pesos abiertos o cerrados, qué
    dispara la factura, y cómo cambiar de opinión más adelante.

- :material-brain:{ .lg .middle } **[Modelos y providers](../models.md)**

    27 providers, perfiles de modelo, alternativas de reserva, y lo que cuesta de
    verdad un token.

- :material-school:{ .lg .middle } **[Skills](../skills.md)**

    Saber hacer escrito que el agent carga solo cuando decide que es relevante.

- :material-text-box-outline:{ .lg .middle } **[Archivos de contexto](../context.md)**

    Conocimiento permanente escrito una vez y ligado a muchos agents — un
    glosario, una guía de tono, una matriz de escalado.

- :material-file-document-multiple:{ .lg .middle } **[Conocimiento](../file-processing.md)**

    Subir, parsear, trocear, embeber. Colecciones, y sincronizar en una de ellas
    una carpeta de Drive o un bucket.

- :material-connection:{ .lg .middle } **[Conexiones MCP](../mcp.md)**

    Cualquier servidor MCP por URL, y 59 en el selector con OAuth ya montado.

- :material-console:{ .lg .middle } **[La sandbox](../sandbox.md)**

    Archivos y una shell, aislados, con un tiempo de vida.

- :material-clock-outline:{ .lg .middle } **[Disparadores](../triggers.md)**

    Un run que ocurre según un horario o ante un evento, sin que nadie escriba
    nada.

</div>

## Ponlo delante de las personas { #put-it-in-front-of-people }

Un agent al que nadie puede llegar es un draft. Así es como sale de la consola.

<div class="grid cards" markdown>

- :material-source-branch:{ .lg .middle } **[Entornos](../environments.md)**

    `staging` y `production` como nombres fijados a versiones, para que publicar
    y lanzar sean dos decisiones.

- :material-forum:{ .lg .middle } **[Superficies](../channels.md)**

    Chat web, una página alojada, un widget embebible, la API HTTP, Slack,
    Telegram y Mattermost — un único runner detrás de todos ellos.

- :material-server:{ .lg .middle } **[El despliegue en sí](../deployment.md)**

    Su identidad, su política de registro, sus avisos. Las cosas que son de la
    instalación y no de un agent.

- :material-cloud-upload:{ .lg .middle } **[Desplegar](../deploy.md)**

    Llevar la plataforma a un servidor.

- :material-account-group:{ .lg .middle } **[Implantarlo](../rollout.md)**

    Quién hace qué, unos primeros noventa días realistas, lo que cuesta, y las
    preguntas que hará tu revisión de seguridad.

</div>

## Mantenlo bajo control { #keep-it-under-control }

La parte que la mayoría de frameworks de agentes te deja a ti. Léela antes de dar
a un agent una herramienta que gasta dinero o que escribe en algún sitio.

<div class="grid cards" markdown>

- :material-account-key:{ .lg .middle } **[Permisos](../permissions.md)**

    Tres capas: lo que permite un rol, lo que amplía un grant, lo que un scope
    deja alcanzar a una herramienta.

- :material-shield-check:{ .lg .middle } **[Governance](../governance.md)**

    Budgets comprobados antes de la petición, aprobaciones decididas una sola
    vez, alertas, y un rastro de auditoría que guarda el valor y no la fila.

- :material-lock:{ .lg .middle } **[Los secretos y el vault](../secrets.md)**

    Un único mecanismo para cada credencial en reposo, y deliberadamente ningún
    segundo.

</div>

## Guías prácticas — recetas { #how-to-recipes }

Respuestas cortas a preguntas concretas, una vez que te manejas por aquí.

- [Escribe las instrucciones de un agent](../howto/customize-agent-prompt.md)
- [Configura las fuentes de sincronización](../howto/configure-sync-sources.md)
- [Usa las valoraciones de los mensajes](../howto/use-ratings.md)

¿Buscas cómo *ampliar* la plataforma en Python — una capability nueva, un
conector nuevo, un endpoint nuevo? Eso está en
[Recursos](../resources/index.md#extending-the-platform).

## Adónde ir después { #where-to-go-next }

Cuando ya sabes cómo se comporta la plataforma y quieres saber exactamente qué
hace un ajuste, un comando o un campo del spec, eso es la
[Referencia](../configuration.md).
