---
source_sha: "e7ffb37fb1d6"
title: "Mantén los datos personales fuera de los prompts y respuestas del agent"
description: "Configura la capability guardrails para que oculte correos, números de teléfono, números de tarjeta y secretos, y compara después lo que recibió de verdad el modelo con lo que vio el visitante."
---

# Mantén los datos personales fuera de los prompts y respuestas del agent { #keep-personal-data-out-of-an-agents-prompts-and-answers }

Activa la [capability guardrails](../reference/capabilities.md#guardrails) en un pequeño agent de prueba y envíale datos personales sintéticos. El resultado que buscas son dos textos distintos: lo que la transcripción del run muestra para el modelo y lo que el run pagó realmente al proveedor por leer. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

Una [instalación en marcha](../install.md) con un perfil de modelo. No hace falta sandbox ni modelo de embeddings. La capability no añade herramientas, así que en el Toolbox solo se necesita **Guardrails**.

## Prepara la entrada { #prepare-the-input }

Esta vez no hay archivo: la entrada es el propio mensaje del chat. Usa esta línea, que lleva un ejemplo de cada tipo de dato personal que la capability reconoce:

```text
My email is jane.doe@example.com, my card number is 4111 1111 1111 1111,
my SSN is 123-45-6789, and my phone number is 415-555-0132.
```

Los datos de referencia: `redact_pii_*` elimina correo electrónico, IBAN, tarjeta de crédito (con comprobación de Luhn), SSN de EE. UU. y número de teléfono. Un número de teléfono se comprueba frente al plan de numeración de su país: uno escrito con `+` se detecta para cualquier país, y uno nacional como `415-555-0132` solo para los países de **phone_regions**, que por defecto vale `US, GB, DE, PL`.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Guardrails**. No aporta ninguna herramienta: aquí no hay nada que una persona tenga que aprobar, solo una comprobación del texto.
3. En la configuración de la capability, activa **Redact API keys and tokens from the user's prompt**, **Redact emails, phone numbers, IBANs, cards and SSNs from the prompt**, **Redact API keys and tokens from the agent's answer** y **Redact emails, phone numbers, IBANs, cards and SSNs from the answer**. Deja **phone_regions** en su valor por defecto, que incluye `US`. Pon **Block the run if the prompt contains any of these terms (comma or newline separated)** en `wire transfer`.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You are a signup-support assistant.
When the user gives you account details, confirm receipt by repeating them back in a bulleted list.
End every answer with a new line reading exactly: Reference key: sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
```

Pedir al agent que repita los datos es lo que da algo que mostrar al borde de entrada: lo que llega al modelo ya ocultado solo puede repetirse ocultado. La clave de referencia fija está ahí para que el borde de salida tenga algo determinista que atrapar, porque obligar a un modelo a inventarse su propio secreto no es fiable.

## Ejecútalo { #run-it }

Envía el mensaje de ejemplo en una conversación de prueba nueva y luego un segundo mensaje sin relación:

```text
I need to send a wire transfer today, can you help?
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| La respuesta | No repite en claro el correo, el número de tarjeta, el SSN ni el número de teléfono |
| El número de teléfono en la respuesta | No aparece, o se cita como `[redacted:phone]` |
| La línea `Reference key:` de la respuesta | Dice `Reference key: [redacted:openai_key]`, no el valor real |
| La transcripción del run (Activity) para el turno del usuario | Muestra el mensaje original sin ocultar que escribiste, número de teléfono incluido |
| El mensaje sobre la transferencia | El estado del run es `guardrail_blocked`, coste `0` y no se produce ninguna respuesta |
| El mismo mensaje sobre la transferencia sin la palabra clave configurada | Se ejecuta con normalidad: lo que bloquea es la palabra clave, no el tema |

Merece la pena detenerse en la segunda fila de la tabla: el número de teléfono es nacional, así que solo se detecta porque `US` está en **phone_regions**. Quita `US` y llega al modelo exactamente como se escribió. La cuarta fila es la otra: una persona que revisa Activity para ver "qué pasó" ve la entrada real del visitante, porque la guardrail reescribe lo que lee el *modelo*, nunca el turno de conversación guardado.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026, antes de ocultar números de teléfono"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. Primera respuesta: *"some of your details were automatically redacted for your security before they reached me, so I was not able to see your email, card number, or SSN"*, seguida de `Phone Number: 415-555-0132` citado sin cambios y `Reference key: [redacted:openai_key]`. Coste: 0,003 USD. Ese run es anterior al detector de teléfonos ([#1901](https://github.com/vstorm-co/agenticos/issues/1901)); con él, el número llega al modelo como `[redacted:phone]`.

    La transcripción del run guardó el turno del usuario como `My email is jane.doe@example.com, my card number is 4111 1111 1111 1111, my SSN is 123-45-6789, and my phone number is 415-555-0132.`, el texto original completo y sin ocultar, mientras que el turno guardado del asistente ya llevaba `[redacted:openai_key]`.

    Hubo otra cosa que solo se vio en la conexión: los frames `text_delta` del WebSocket transmitieron la clave de referencia real, carácter a carácter, antes de que el frame `final_result` sustituyera la respuesta completa por la versión ocultada. La ocultación actúa sobre la respuesta terminada, no sobre cada token transmitido. `widget.js` sobrescribe su texto con `final_result.output` justo por esto, pero un cliente que solo añade deltas mostraría el secreto durante uno o dos segundos antes del cambio.

    El mensaje sobre la transferencia: `error`, *"This request was blocked by an input guardrail."*, sin frame `complete` después. El run registró el estado `guardrail_blocked`, `0` tokens de entrada y de salida y un coste de `0.000000`.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Un valor que esperabas ocultar pasa intacto.** Compáralo con los cinco detectores: correo, IBAN, tarjeta de crédito (con suma de control), SSN de EE. UU. y número de teléfono. Un número de teléfono nacional necesita su país en **phone_regions**, y un número que no es válido en el plan de numeración de su país se deja intacto. Una dirección postal o un nombre no están cubiertos: es una capa de patrones, no un modelo que entienda qué son datos personales.
- **Un cliente con streaming muestra un secreto por un momento.** La ocultación de la salida actúa sobre la respuesta terminada, cuando los frames `text_delta` ya han salido. Muestra el texto de `final_result`, como hace `widget.js`, en lugar de limitarte a añadir deltas. Almacenar la respuesta en búfer cuando está activada la comprobación de la salida se sigue en [#1900](https://github.com/vstorm-co/agenticos/issues/1900).
- **El bloqueo no se activó.** `blocked_keywords_*` busca una subcadena literal sin distinguir mayúsculas y minúsculas. Un bloqueo también necesita el interruptor propio del borde: una lista de palabras clave en el borde de salida no hace nada con la entrada.
- **La transcripción sigue mostrando el valor en bruto.** En el borde de entrada es lo esperado: solo se reescribe lo que llega al modelo, no el turno guardado que una persona revisa después. Ocultar antes de guardar es otra función distinta de esta.
- **Un run muestra un `guardrail_blocked` que no pretendías.** Lee el campo `error` del run: nombra el borde (`input`, `output` o `tool_result`) pero, a propósito, nunca el texto que coincidió, así que revisa la propia lista de palabras clave.
- **La comprobación de resultados de herramientas parece no usarse.** Solo importa cuando un agent tiene una herramienta que lee contenido no fiable: una página descargada, un archivo, una respuesta MCP. Esta prueba no tiene ninguna, así que ese borde estaba configurado pero nunca se ejercitó.

## Registra la prueba { #record-the-trial }

Guarda el mensaje exacto, la versión del agent, qué bordes y palabras clave se configuraron, la transcripción del run para ambos turnos y el `status` y el coste del run en Activity. Una persona decide si estos cinco detectores bastan para un agent concreto, qué países van en su **phone_regions** y si la comprobación de resultados de herramientas debe estar activada antes de añadir cualquier herramienta que lea el mundo exterior.

## Siguientes pasos { #next-steps }

[La referencia de guardrails](../reference/capabilities.md#guardrails) enumera los patrones exactos y los tres bordes en una tabla. Si el agent va a leer algo descargado de fuera (una página web, un servidor MCP, un archivo subido), activa el borde de resultados de herramientas antes de que esa capability entre en uso, no después.
