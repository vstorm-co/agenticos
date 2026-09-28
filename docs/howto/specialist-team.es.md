---
source_sha: "62fe6a8232a7"
title: "Enruta solicitudes a un equipo de agents especialistas"
description: "Construye un agent de recepción que delega una pregunta de facturación o técnica en un especialista publicado, y pregunta cuando la duda es ambigua."
---

# Enruta solicitudes a un equipo de agents especialistas { #route-requests-to-a-team-of-specialist-agents }

Construye tres agents: un especialista en facturación, un especialista técnico y una recepción que envía cada pregunta al que le corresponde o pregunta cuando no está claro. Cada especialista se publica por separado, así que se revisa, se versiona y otras recepciones pueden reutilizarlo. Es un procedimiento para ejecutar, con tres preguntas registradas como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo para los tres agents.
- `agents:run` sobre ambos especialistas, para fijarlos desde la recepción: es el mismo permiso que resuelve una mención en un canal o una comprobación de delegación en cualquier otra parte del producto. Consulta [los permisos](../permissions.md#delegation-is-not-a-privilege-boundary).
- Sin colección de conocimiento, sandbox ni conexión MCP para este ejemplo.

## Prepara la entrada { #prepare-the-input }

Un pequeño producto sintético, para que los datos de los especialistas se puedan comprobar:

**Datos de facturación**: plan Basic a 9 USD/mes, Pro a 29 USD/mes, ambos facturados mensualmente. Reembolso completo en los 14 días siguientes a un cargo, sin dar motivos; ninguno después. Las facturas se envían por correo en la fecha del cargo y siempre están disponibles en la página Billing de la cuenta.

**Datos técnicos**: la clave de API está en Settings → API keys; generar una nueva revoca la anterior de inmediato. El límite es de 60 peticiones por minuto por clave; un `429` indica los segundos que hay que esperar. El estado y el historial de incidencias se publican en una página de estado.

## Construye los dos especialistas { #build-the-two-specialists }

Publica cada uno como su propio agent, sin capabilities: cada uno responde solo con los datos que le diste.

1. **uc-billing-specialist**: en las instrucciones, los datos de facturación de arriba y que una pregunta fuera de ellos no es algo que cubra este agent.
2. **uc-tech-specialist**: en las instrucciones, los datos técnicos de arriba, con la misma negativa para todo lo demás.

Publica ambos antes de construir la recepción: un delegado debe ser un agent publicado que puedas ejecutar, referenciado por su slug.

## Construye la recepción { #build-the-front-desk }

1. Crea un tercer agent, **uc-front-desk**, y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Delegation**. Deja `allow_dynamic` desactivado: este agent solo llama a los dos especialistas que nombras, nunca a uno que se invente.
3. En **Delegates**, añade los dos especialistas publicados, fijados a su versión actual.
4. Fija un budget y un límite de pasos para la prueba.
5. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You are the front desk for this product's support. You never answer a billing
or technical question yourself.
Route a billing question (pricing, refunds, invoices, charges) to the billing
specialist with task(description=..., subagent_type="uc-billing-specialist").
Route a technical question (the API, keys, rate limits, uptime) to the
technical specialist with task(description=..., subagent_type="uc-tech-specialist").
If a question could be either, or names neither, ask the user one short
question to tell which team it belongs to before delegating anything.
Relay the specialist's answer; do not add facts of your own.
```

`task` no tiene efectos secundarios, así que ninguna de las dos delegaciones pide aprobación por defecto: lo que una persona aprobaría son las herramientas del propio especialista, en la spec del especialista.

## Quién paga y qué ve el usuario { #who-pays-and-what-the-user-sees }

El run de la recepción paga todo el intercambio: un único libro de gastos compartido cubre al padre y a cada especialista al que llama, y el budget que se aplica en mitad de la conversación es el de la recepción. Aun así, cada especialista tiene su propia fila en Activity, con `parent_run_id` apuntando al run de la recepción, de modo que "cuánto costó este mes el especialista en facturación" tiene una respuesta que no duplica la factura de la organización. Consulta [cómo se registra un run delegado](../governance.md#what-a-delegated-run-is-recorded-as).

La persona que pregunta ve una única respuesta continua. La recepción transmite lo que dijo el especialista; nada en la transcripción parece un traspaso a menos que abras el run en Activity y veas la delegación debajo.

## Una aprobación dentro de una delegación { #an-approval-inside-a-delegation }

Aquí ningún especialista tiene una herramienta protegida, así que no se aparca nada. Si uno la tuviera (por ejemplo una capability `send_email` en el especialista en facturación), la aprobación llegaría igualmente a la misma cola que vigila quien habla con la recepción, indicando **qué delegado** propuso la llamada y no solo qué herramienta. Aprobarla reanuda a ese especialista desde donde se detuvo, en lugar de volver a delegar desde cero. Consulta [una aprobación dentro de una delegación](../governance.md#an-approval-inside-a-delegation).

## Ejecútalo { #run-it }

Haz tres preguntas a la recepción, cada una en una conversación distinta:

```text
I was charged twice this month, can I get a refund on the extra charge?
```

```text
My integration keeps getting 429s, what's the limit and where do I check status?
```

```text
Something changed and now it doesn't work like before.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Pregunta de facturación | Delega en `uc-billing-specialist`; la respuesta indica la regla del reembolso en 14 días |
| Pregunta técnica | Delega en `uc-tech-specialist`; la respuesta indica el límite de 60 por minuto y la página de estado |
| Pregunta ambigua | No hay delegación; la recepción pregunta a qué equipo corresponde |
| Activity, run de facturación | Un run hijo bajo el de la recepción, con `parent_run_id` y su propio coste |
| Activity, run técnico | La misma forma, bajo `uc-tech-specialist` |
| Una pregunta que no nombra ningún equipo y quien pregunta se niega a aclarar | La recepción sigue preguntando en lugar de adivinar a qué especialista llamar |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, en los tres agents. La pregunta sobre el reembolso produjo una llamada a `task` a `uc-billing-specialist` (coste de 0,0236 USD para el run de la recepción, delegado incluido), cuya respuesta nombró el plazo de 14 días y remitió a la página Billing. La pregunta sobre el límite produjo una llamada a `task` a `uc-tech-specialist` (0,0227 USD), cuya respuesta nombró las 60 peticiones por minuto y la página de estado. El mensaje ambiguo no produjo ninguna delegación: "Could you tell me a bit more about what changed - is this related to billing... or something technical...?" (0,0066 USD). La fila de run propia del especialista en facturación registró 0,0057 USD, como hijo del run de la recepción, lo que confirma la forma de libro compartido y fila aparte descrita arriba.

## Cuando algo sale mal { #when-it-goes-wrong }

- **La recepción responde directamente, sin delegar.** No se siguieron las instrucciones, o `subagents` no está vinculado; revisa el Toolbox antes de releer el prompt.
- **Publicar la recepción se rechaza nombrando a un delegado.** Uno de los especialistas no está publicado, o no puedes ejecutarlo: fijarlo comprueba `agents:run` sobre la fila de ese especialista.
- **La recepción siempre pregunta, incluso ante una pregunta de facturación clara.** La regla de enrutamiento de las instrucciones es demasiado estricta, o el modelo interpreta "could be either" de forma demasiado amplia; acota los ejemplos del prompt.
- **Un especialista responde a una pregunta fuera de sus datos en lugar de negarse.** Sus propias instrucciones no dicen que se niegue; añade la línea de negativa explícita usada arriba.
- **La versión de un delegado cambió sin que lo pidieras.** No cambió: un pin solo se mueve cuando la spec de la recepción se vuelve a publicar contra la versión nueva. Consulta [un delegado fijado no se mueve solo](../governance.md#a-pinned-delegate-does-not-move-on-its-own).

## Registra la prueba { #record-the-trial }

Guarda cada pregunta, qué especialista respondió, la respuesta, el run hijo en Activity con su propio coste y el total de la recepción. Una persona sigue decidiendo qué es lo bastante ambiguo como para preguntar, revisa los datos de cada especialista antes de publicarlo y juzga si una respuesta transmitida refleja de verdad lo que dijo el especialista.

## Siguientes pasos { #next-steps }

Añade un tercer especialista y verás lo difícil que se vuelve mantener inequívocas las instrucciones de enrutamiento de la recepción: una buena señal de que el equipo está superando las reglas de enrutamiento escritas a mano. `allow_questions` permite que un especialista pregunte, en mitad de la respuesta, a la misma persona con la que habla la recepción, en lugar de adivinar; consulta [la delegación](../reference/capabilities.md#delegation).
