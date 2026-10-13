---
source_sha: "921578018ea4"
title: "Responde preguntas de nuevas incorporaciones con archivos de contexto y skills"
description: "Vincula a un agent un archivo de contexto breve con datos fijos y una skill con un procedimiento, y comprueba cuál de los dos responde a cada tipo de pregunta."
---

# Responde preguntas de nuevas incorporaciones con archivos de contexto y skills { #answer-new-hire-questions-with-context-files-and-skills }

Construye un servicio de ayuda para nuevas incorporaciones que siempre conoce unos pocos datos pequeños y estables y solo recurre a un procedimiento escrito cuando la pregunta lo necesita de verdad. Detrás hay dos capabilities, [los archivos de contexto](../context.md) y [las skills](../skills.md), y esta página existe porque elegir la equivocada es el motivo habitual por el que un agent ignora lo que se le dijo o nunca abre lo que necesitaba. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Cuál encaja { #which-one-fits }

| | Contiene | El modelo lo ve |
| --- | --- | --- |
| **Archivo de contexto** | Datos fijos, pequeños y estables: la fecha de la nómina, el canal de TI | Siempre (`inject`) o a demanda (`link`) |
| **Skill** | Un procedimiento para un tipo de tarea: cómo pedir acceso | Solo cuando el modelo decide que esa es la tarea en curso |
| **Colección de conocimiento** | Un corpus demasiado grande para leerlo entero: un manual completo, cada PDF de políticas | Solo los fragmentos que devuelve una búsqueda |

La guía de incorporación de abajo es corta y siempre relevante, así que es un archivo de contexto. "Cómo consigo acceso a un sistema" es un procedimiento con pasos y una excepción, así que es una skill. Si tu material de incorporación es en cambio un manual de cincuenta páginas, vincúlalo como [colección de conocimiento](set-up-knowledge-base.md) y reserva el patrón de esta página para los datos fijos y breves. Consulta [¿skills o conocimiento?](../skills.md#skills-or-knowledge) para la misma distinción vista desde las skills.

## Qué necesitas { #what-you-need }

Una [instalación en marcha](../install.md) con un perfil de modelo. Sin sandbox y sin modelo de embeddings: los dos archivos son lo bastante pequeños para inyectarlos o cargarlos enteros.

## Prepara la entrada { #prepare-the-input }

Un archivo de contexto con datos fijos:

```markdown
# Acme Robotics — new-hire quick facts

- Payroll runs on the last business day of the month.
- The standard laptop is a MacBook Pro; loaner laptops are requested from IT, not HR.
- The internal help channel for IT questions is #it-help.
- Health insurance enrollment is open during your first 30 days; after that, only
  during the November open-enrollment window.
```

Una skill para el procedimiento por el que más preguntan las nuevas incorporaciones:

```markdown
# Requesting access

Most access requests go through the #it-help channel, not a person directly.

1. Post in #it-help naming the system and the reason you need it.
2. IT grants standard tools (chat, email, laptop) within one business day.
3. Anything touching customer data (the CRM, production databases) needs your
   manager's written approval first - tag them in the same thread.
4. Access to the payroll system is never granted through chat; email
   payroll@acme-example.com instead.
```

Acme Robotics es inventada. Los datos de referencia: la nómina el último día hábil, un MacBook Pro por defecto y el acceso al CRM que necesita antes la aprobación del responsable.

## Construye el agent { #build-the-agent }

1. En **Context → New**, crea un archivo llamado `onboarding-guide`, pega los datos de arriba, pon **Mode** en `inject` y añade una descripción que una persona reconozca más tarde.
2. En **Skills → New**, crea `request-access` con el procedimiento de arriba y una descripción escrita para el modelo: *"When somebody asks how to get access to a tool, a repository, a system, or is not sure who grants it."* Una skill enlazada se elige solo por su nombre y esta línea.
3. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
4. En **Toolbox**, activa **Context** y vincula `onboarding-guide`. Activa **Skills** y vincula `request-access`.
5. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You are Acme Robotics' new-hire helpdesk assistant.
Answer from the standing facts you were given, and use a bound skill's
procedure when a question is about how to do something.
If you are not sure, say so rather than guessing.
```

## Ejecútalo { #run-it }

Pregunta primero por un dato fijo y después por un procedimiento:

```text
When does payroll run, and what laptop will I get?
```

```text
How do I get access to the CRM?
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Pregunta sobre la nómina y el portátil | Respondida directamente, sin llamada a herramientas: el archivo de contexto ya está en el prompt |
| Pregunta sobre el acceso al CRM | Llama a `load_capability` para `request-access` antes de responder |
| La respuesta sobre el CRM | Nombra como primer paso la aprobación por escrito del responsable, no solo "post in #it-help" |
| Una pregunta que el archivo de contexto no cubre (p. ej. "what's the dress code?") | Dice que no lo sabe, en lugar de inventarse una norma |
| Editar después el archivo de contexto | El siguiente run refleja el cambio sin volver a publicar nada en el agent |

Las dos primeras filas son la comprobación que importa: una respuesta sale de un texto que está en cada prompt, la otra de una llamada a herramienta que el modelo decidió hacer. Si alguna ocurre al revés, se recurrió a la capability equivocada.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. La pregunta sobre la nómina y el portátil usó 914 tokens de entrada **sin ninguna llamada a herramientas** y respondió: *"Payroll runs on the last business day of the month... The standard laptop is a MacBook Pro"*. Coste: 0,004 USD.

    La pregunta sobre el CRM llamó a `load_capability` con `{"id": "request-access"}`, recibió el contenido completo de la skill y respondió: *"Since the CRM touches customer data, there's a specific process... Get your manager's written approval first... Post in #it-help. Tag your manager in the same thread"*. Coste: 0,009 USD.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Falta un dato fijo en una respuesta.** Revisa el **Mode** del archivo de contexto. Un archivo `link` no está en el prompt hasta que el modelo decide leerlo; para datos que nunca deben faltar, usa `inject`.
- **La skill nunca se carga.** El modelo la elige solo por nombre y descripción; una descripción que suena a título ("Access requests") le dice menos que una escrita como *cuándo recurrir a esto*.
- **El agent recita la skill en cada pregunta.** La descripción de la skill es demasiado amplia, o las instrucciones no distinguen "dato fijo" de "procedimiento" con la claridad suficiente para que el modelo sepa cuál es la pregunta.
- **Editar el archivo de contexto no cambia la respuesta.** Confirma que editaste el archivo de la organización y no una copia: los archivos de contexto se vinculan por id y no hay una versión propia por agent.
- **Aparece una propuesta de skill en lugar de una respuesta directa.** El agent puede intentar *mejorar* la skill en mitad de la conversación; eso es una propuesta que aplica o descarta una persona con `skills:edit`, no algo que un run aplique por su cuenta. Consulta [las skills](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Registra la prueba { #record-the-trial }

Guarda el contenido y los ids de ambos archivos, la versión del agent, las dos preguntas y respuestas, y si cada una usó una llamada a herramientas. Una persona sigue escribiendo y editando los datos fijos y el procedimiento; este patrón solo decide dónde vive cada texto, no quién tiene razón sobre la fecha de la nómina.

## Siguientes pasos { #next-steps }

El mismo agent puede vincularse a un bot de Slack para un canal del equipo en lugar de a la consola; consulta [responde una pregunta sobre el manual en Slack](slack-handbook-assistant.md), que recorre la vinculación, la conexión de cuentas y cómo comprobar a quién pertenece cada run. Si el material de incorporación supera una o dos páginas, pásalo a una [colección de conocimiento](set-up-knowledge-base.md) en lugar de estirar un archivo de contexto inyectado.
