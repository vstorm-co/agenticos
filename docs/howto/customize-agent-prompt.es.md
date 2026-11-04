---
source_sha: "f3bfbd97d90e"
---

# Escribe las instrucciones de un agent { #write-an-agents-instructions }

!!! danger "Las instrucciones son datos, no código"

    No hay ningún `prompts.py` que editar, ni una constante
    `DEFAULT_SYSTEM_PROMPT` que sobrescribir. El comportamiento de un agent es el
    campo `instructions` de su [spec](../reference/spec.md) — se edita en el
    Builder, se versiona al publicar y se exporta como YAML al repositorio del
    propio cliente. Editar Python para cambiar lo que dice un agent es la
    suposición equivocada más habitual sobre este código.

## Dónde vive el texto { #where-the-text-lives }

| | Dónde | Quién lo edita |
|---|---|---|
| Las instrucciones de un agent | `AgentSpec.instructions`, editado en el Builder | Quien pueda editar el agent |
| Las instrucciones de un especialista en línea | `InlineSpecialistSpec.instructions`, en el mismo spec | Los mismos |
| El texto de partida que recibe un agent nuevo | La plantilla AgenticOS, `backend/app/core/catalog/agent_templates/general/agenticos/AGENT.md` | Un deploy — es la idea de asistente que tiene este despliegue |
| Lo que se le dice al agent sobre lo que puede y no puede hacer | Montado a partir de sus capabilities en cada run, bajo **Your setup** | Nadie — cambiar una capability lo cambia |
| Lo que se le dice al agent sobre la persona | Su idioma, zona horaria, rol y trabajo, de su cuenta, tras las instrucciones en cada run | La propia persona, en **Settings → Profile** |
| Un procedimiento que comparten muchos agents | Un [skill](../skills.md), una fila en la base de datos | Un responsable de soporte, un martes por la tarde, sin ningún deploy |

La última fila es la que conviene aprovechar. Veinte procedimientos en un solo
campo `instructions` significan que cada run paga por los veinte; veinte skills no
cuestan casi nada, porque el modelo ve los nombres y carga solo lo que necesita.

## Qué va dentro de las instrucciones { #what-belongs-in-instructions }

Lee las instrucciones de la plantilla AgenticOS antes de escribir las tuyas — un
agent nuevo empieza con ellas, así que son el ejemplo trabajado. Empiezan por el
propio `{{agent_name}}` del agent, guían a la persona paso a paso, ofrecen un
siguiente paso después de una tarea y no nombran ninguna herramienta que no
traiga una capability. Dos decisiones deciden buena parte de la calidad:

- **Escribe pensando en los rechazos.** Los párrafos que se ganan su sitio son los
  que hablan de no inventar hechos, de decir de qué fuente salió una respuesta y
  de pararse a preguntar en lugar de aventurar algo destructivo. "Sé útil" es
  decoración: el modelo ya está intentando ser útil, y lo que necesita es saber
  dónde están los bordes.
- **Pon arriba lo que es específico de *este* agent.** Quien lo abra después
  reescribirá el primer párrafo y conservará el resto.

```text
You are a customer support agent for Acme.

Answer questions about our products, help people troubleshoot, and escalate
anything involving a refund over £500 — the refund-policy skill has the rule.

Never quote a price you have not read from the knowledge base. If a question
needs an account change, say what you would do and ask them to confirm.
```

!!! warning "No enumeres las herramientas del agent en sus instrucciones"

    Un agent obtiene sus capabilities de su spec y las herramientas llevan sus
    propias descripciones desde la librería. Un prompt que las enumera queda
    equivocado en cuanto alguien activa o desactiva una — y el fallo es un agent
    que se niega con toda seguridad a hacer algo que ya puede hacer.

!!! tip "Tampoco repitas las reglas de una capability"

    Una capability que necesita que el modelo se comporte de cierta manera aporta
    eso ella misma. El formato de citas de la recuperación, cómo usar la sandbox,
    cuándo preguntar a una persona — eso llega con la capability, en todos los
    agents que la habilitan.

## Conocimiento, skills y archivos de contexto { #knowledge-skills-and-context-files }

Tres maneras de dar a un agent texto que no tenía, y no son intercambiables:

| | Para | Se recupera con |
|---|---|---|
| `collection_ids` — [conocimiento](../file-processing.md) | Miles de documentos: lo que sabemos | Búsqueda semántica, con cita |
| `skill_ids` — [skills](../skills.md) | Decenas de procedimientos: cómo hacemos esto | El modelo eligiendo un nombre y cargando después el cuerpo |
| `context_ids` — archivos de contexto | Un puñado de archivos lo bastante pequeños para estar siempre presentes | Inyectados en las instrucciones, sin búsqueda de por medio |

Los tres se comprueban contra el acceso de **quien publica** en el momento de
publicar, no en el momento de ejecutar. Consulta
[Permisos](../permissions.md).

## Iterar sobre ellas { #iterating-on-it }

- **Un `draft` solo se ejecuta como prueba.** Allí donde está disponible, un
  agent responde con su versión publicada; el panel de pruebas del Builder - y
  `POST /agents/{id}/run` con `"draft": true`, que llama el `test_agent_draft`
  del Architect - responden como el `draft` sin publicar, en un run de prueba.
  Publicar es barato por diseño, y una vuelta atrás es una promoción y no una
  restauración. Itera en un
  [entorno](../concepts.md#version) `dev` que siga cada publicación, y deja
  `production` esperando a que promocionen algo sobre él.
- **Prueba con consultas reales, no con las ideales.**
- **Mantenlas tan cortas como el comportamiento exija.** Un prompt más largo se
  paga en cada turno de cada run, y saca antes la conversación de la ventana.
- **Publica cuando esté bien.** Publicar congela la versión, así que "qué hizo
  este agent el martes pasado" sigue teniendo respuesta después de una docena de
  ediciones — y una vuelta atrás publica una *nueva* versión copiada de la
  antigua en lugar de borrar la historia.
- **La temperatura y lo demás son `model_settings`**, por agent y por
  especialista, encima del perfil del modelo. No son una variable de entorno.
