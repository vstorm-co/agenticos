---
source_sha: "1c871ba742e1"
title: "Conversaciones de voz"
seo_title: "Conversaciones de voz: habla con un agent publicado"
description: "Llama a un agent publicado y habla con él: modelos realtime, aprobaciones en la llamada, límites de tiempo y minutos, redes de seguridad y transcripciones."
---

# Conversaciones de voz { #voice-conversations }

Una **llamada de voz** es una conversación hablada con un agent publicado. Tú
hablas, el agent responde en voz alta y puedes interrumpirlo a mitad de frase. El
agent conserva lo que tiene en el chat de texto: sus herramientas, su
conocimiento, sus aprobaciones y sus budgets. Cada turno de la llamada se guarda
como texto en la misma conversación, así que puedes releerlo o continuarlo
escribiendo. No se guarda audio en ningún sitio.

Las llamadas se hacen desde `/chat` en la consola, y desde un widget o una
página alojada cuando el interruptor propio del embed está activado. Cada llamada
es un [run](concepts.md), con el nombre del modelo realtime, así que Activity, la
pantalla de coste y el registro de auditoría la ven como cualquier otro run.

!!! note "La vista de llamada llega por separado"

    La parte del servidor, los ajustes, la comprobación de disponibilidad y la API
    descritos aquí ya están en su sitio. La vista de llamada en sí - en `/chat`,
    en el widget y en la página alojada - todavía se está diseñando, y hasta que
    llegue ninguna superficie muestra un botón de llamada.

## Activarlo { #turn-it-on }

Dos interruptores y una sección Voice tienen que coincidir antes de que nadie
pueda llamar.

**La organización.** Las llamadas están **desactivadas** hasta que un admin las
activa, en la tarjeta Voice de la página de la organización, bajo «Voice
conversations»:

| Ajuste | Por defecto | Qué hace |
|---|---|---|
| Allow voice conversations | desactivado | El interruptor general. Desactivado rechaza cada llamada, en cada superficie |
| Offer calls in chat | activado | Si `/chat` ofrece llamadas una vez permitidas. El widget y la página alojada se activan por embed |
| Longest call | 10 min | Cualquier número entero de minutos de 1 a 50 (guardado como 60–3000 s). Un agent puede fijar un límite más corto, nunca uno más largo |
| Monthly call minutes | 600 | Cuenta cada llamada de la organización, desde su primer segundo. Vacíalo para depender solo de los budgets |

Los tres primeros necesitan `org:settings`. Los minutos mensuales son un límite
de gasto, así que cambiarlos necesita `budgets:manage`, como el budget mensual de
la organización; un miembro sin él ve la cifra en solo lectura.

**El agent.** Su tarjeta Voice en el Builder gana una sección «Voice
conversations», que se escribe en el [campo `voice`](reference/spec.md#voice) del
spec. Nombra el provider, el modelo (o, para Azure, el nombre del deployment y el
modelo base que ejecuta), la clave del vault con la que se sostienen las
llamadas, la voz, un idioma opcional, una llamada más larga opcional y una nota
de voz opcional. La nota se añade a las instrucciones del agent solo en las
llamadas. La sección surte efecto cuando se publica el agent.

**El embed.** Un widget o una página alojada solo ofrece llamadas cuando su
propio interruptor «Voice calls» está activado. Guardar el interruptor activado
se rechaza mientras el interruptor de la organización esté desactivado o el agent
no tenga una voz con la que pueda llamar. Ver
[Canales](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

## Modelos y claves { #models-and-keys }

Los modelos que puede usar una llamada vienen de un único archivo de catálogo,
`backend/app/core/catalog/realtime_models.json`, descrito en
[Modelos](models.md#realtime-models). No hay perfil de modelo para la voz ni un
valor por defecto de la organización: la sección Voice del agent es el único
sitio donde se nombra un modelo realtime.

| Provider | Modelos | Transporte | Verificado |
|---|---|---|---|
| OpenAI | `gpt-realtime`, `gpt-realtime-2.1`, `gpt-realtime-2.1-mini` | WebRTC | Probado en vivo |
| Azure OpenAI | un deployment de `gpt-realtime` | Relay | **No verificado en vivo** |
| Google | Gemini Live: `gemini-2.5-flash-native-audio-latest`, `gemini-3.1-flash-live-preview` | Relay | **No verificado en vivo** |
| xAI | `grok-voice-latest`, facturado por minuto | Relay | **No verificado en vivo** |

Solo OpenAI se pudo probar contra una cuenta real. Azure, Gemini y xAI están
construidos a partir de la documentación de los providers y de Pydantic AI, y
probados con dobles. Espera que funcionen, y compruébalos en tu propia cuenta
antes de depender de ellos.

**La clave es un secreto explícito del vault.** Su propósito tiene que ser el
provider y su tipo tiene que coincidir: una `api_key`, o un secreto
`azure_openai` para Azure, que además lleva el endpoint y la versión de la API.
Quien publica tiene que poder ver la clave, como en cualquier vinculación. Ver
[Secretos](secrets.md#where-they-are-used).

**GPT-Live no se ofrece.** Solo recibe el historial de la conversación cuando
empieza una sesión y no se puede reconfigurar, así que una reconexión no podría
continuar la llamada que retoma.

## Cómo funciona una llamada { #how-a-call-runs }

El navegador abre un socket hacia este despliegue, `/api/v1/ws/voice`, y envía
una trama `start` que nombra el agent y, opcionalmente, la conversación. Todo lo
relativo a la llamada pasa por ese socket: las tramas están enumeradas en
[la página de la API](api.md#voice-calls).

**OpenAI, sobre WebRTC.** El navegador construye una conexión peer con su
micrófono y envía la oferta SDP dentro de `start`. El servidor la responde con el
provider, devuelve la respuesta y luego mantiene una conexión *sideband* a la
misma llamada mientras el socket siga abierto. El audio fluye entre el navegador
y OpenAI; las herramientas, las aprobaciones, las transcripciones y la medición
corren en el servidor.

```mermaid
sequenceDiagram
    participant B as Browser
    participant S as AgenticOS
    participant P as OpenAI
    B->>S: start (agent, SDP offer)
    S->>S: refusals, run and call row, commit
    S->>P: answer the offer
    P-->>S: SDP answer, call id
    S-->>B: answer, then ready
    B->>P: audio over WebRTC
    S->>P: sideband: tools, approvals, transcripts
    B->>S: end, or the socket closes
    S->>P: hang up the call
    S-->>B: ended
```

Dos cosas se rechazan a propósito. Una oferta que abre un **canal de datos** (una
sección `m=application`) se rechaza: el navegador nunca lo necesita, y un canal
de datos permitiría a la página enviar eventos al provider a espaldas del
servidor. Y **nunca se emite un client secret**, así que el navegador nunca tiene
una credencial que pudiera abrir una llamada propia.

**Azure, Gemini y xAI, sobre el relay.** El navegador envía audio PCM de 16 bits
por el mismo socket, a la frecuencia de entrada del modelo, y reproduce lo que
vuelve a su frecuencia de salida. Cuando hablas por encima del agent, el servidor
corta su respuesta y le dice al navegador que descarte lo que tiene en cola. El
audio que llega mucho más rápido de lo que nadie habla se descarta, y una
avalancha sostenida termina la llamada.

## Qué puede usar una llamada { #what-a-call-can-use }

Una llamada ejecuta el agent que describe su spec publicado, construido por la
misma factory que un run de texto. Las diferencias vienen de la sesión realtime:
sus herramientas quedan fijadas cuando se conecta la llamada, no puede pausarse
para una aprobación y algunas capabilities no pueden ejecutarse en ella en
absoluto.

| Por voz | Capabilities |
|---|---|
| Tal cual | reloj (la hora de las instrucciones queda fijada cuando se conecta la llamada), contexto, conocimiento, investigación web, lectura de páginas web, gráficos, artefactos, ejecución de código, búsqueda de conversaciones, archivos de memoria, memoria mem0, planificación, límites de salida de herramientas, generación de imágenes |
| Adaptada | skills: se cargan como instrucciones bajo demanda, sin las herramientas que usa un run de texto para leerlos |
| Eliminada | búsqueda de herramientas: las herramientas MCP que habría diferido se pasan directamente a la llamada |
| Traducida | razonamiento (thinking): se convierte en el ajuste de razonamiento propio del modelo realtime, cuando el modelo lo tiene |
| No disponible | sandbox, automatización del navegador, elección de navegador, subagents |

La tarjeta Voice del Builder enumera las capabilities que este agent no puede
usar en llamadas. No bloquean la publicación; al agent se le indica que diga
claramente que no puede hacer eso en una llamada y que sugiera el chat de texto.

**Estilo hablado integrado.** Cada llamada añade la misma guía a las
instrucciones del agent: frases cortas; nada de markdown, listas, tablas ni
enlaces leídos en voz alta; números y fechas dichos como los dice una persona;
nombres, importes, direcciones y fechas repetidos en voz alta antes de actuar
sobre ellos; y decir que está esperando una aprobación, en vez de afirmar antes
un resultado. La nota de voz propia del agent va a continuación.

Sobre WebRTC el agent se resuelve dos veces, una para responder a la oferta y
otra para el sideband. Los servidores MCP se conectan dos veces y las
instrucciones dinámicas se ejecutan dos veces, así que una consulta a la memoria
mem0 se paga dos veces; ambas se miden en el run.

## Aprobaciones en una llamada { #approvals-in-a-call }

Una sesión realtime no puede pausarse, así que una aprobación se decide dentro de
la llamada.

Cuando el agent llama a una herramienta que necesita aprobación, el servidor
escribe la fila de aprobación al instante y muestra a la persona que está en la
llamada una tarjeta: la herramienta, **los argumentos exactos con los que se
ejecutará** y lo que se oyó decir a quien llama. El riesgo aquí es un nombre mal
oído («Acme» oído como «Ahmad»), y la tarjeta es la comprobación. Aprobar ejecuta
exactamente esos argumentos, una vez; la misma herramienta llamada de nuevo
necesita una aprobación nueva.

- **60 segundos** sin decisión caducan la solicitud, sin nadie que decida, y el
  agent lo dice.
- Solo decide **la persona que está en la llamada**, y solo con
  `approvals:decide`. La cola de aprobaciones rechaza una solicitud que pertenece
  a una llamada en curso, y el barrido de caducadas la deja en paz.
- Un miembro **sin** `approvals:decide` conserva la herramienta. Cuando el agent
  recurre a ella, la llamada muestra un aviso, la herramienta se rechaza y el
  agent dice que esto necesita una aprobación que quien llama no puede dar por
  voz y sugiere el chat de texto.
- Un **visitante anónimo** en un widget o una página alojada nunca ve una
  herramienta que necesite aprobación: esas herramientas se dejan fuera de la
  llamada por completo.

Una llamada que termina, por el motivo que sea, caduca todo lo que todavía
estuviera esperando.

## Límites y coste { #limits-and-cost }

**Tiempo.** Una llamada dura como mucho la llamada más larga del agent, la
llamada más larga de la organización o 50 minutos, lo que sea más corto, y nunca
más que los minutos que le quedan al mes. Un minuto antes del final se avisa a la
vista de llamada. Al final el agent dice una frase corta sobre el motivo y la
llamada se detiene.

**Minutos.** Los minutos mensuales de la organización se cuentan a partir de las
filas de llamada (`voice_calls`): cada llamada hasta su fin, o hasta su último
heartbeat mientras sigue en curso. Cuando se agotan, las llamadas nuevas se
rechazan, y a una llamada en curso se le avisa y se termina en su siguiente
heartbeat. La cifra «Voice minutes» del dashboard y la tarjeta Voice de la
organización leen las mismas filas.

**Dinero.** Las llamadas cuentan contra los budgets del agent y de la
organización, como los runs de texto:

- Antes de que empiece una llamada, su duración máxima posible multiplicada por
  el precio por minuto del peor caso del modelo se comprueba contra el budget
  restante. Una llamada que no se podría pagar se rechaza, en vez de empezar y
  cortarse a medias.
- Durante la llamada, cada respuesta se anota en el run cuando termina, y el
  budget se vuelve a leer en cada heartbeat. El límite de coste de la sesión
  puede sobrepasarse como mucho en una respuesta (dos en Azure, cuyo deployment
  se tarifa aquí como su modelo base).
- xAI se factura por minuto conectado, a la tarifa del catálogo.
- Un modelo cuyo precio no se puede calcular se rechaza al configurarlo, así que
  un budget nunca queda sin aplicar en silencio.
- Transcribir lo que dice quien llama no se tarifa, así que el coste registrado
  de una llamada queda algo por debajo de lo que factura el provider.

**Concurrencia.** Una persona mantiene una llamada a la vez
(`VOICE_MAX_CALLS_PER_USER`, 1 por defecto). Un embed mantiene como mucho tres
llamadas abiertas, de todos los visitantes juntos (`VOICE_MAX_CALLS_PER_EMBED`);
un cuarto llamante se rechaza como `line_busy`. Ver
[Configuración](configuration.md#voice-calls).

## Terminar una llamada, y qué acota una perdida { #ending-a-call-and-what-bounds-a-lost-one }

Cerrar el socket no termina una llamada WebRTC de OpenAI: el audio es del
navegador y del provider, y la llamada sigue hablando y facturando hasta que se
cuelga o alcanza el límite de una hora del propio provider. Así que colgar es
trabajo del servidor, en cada camino:

1. **Un `finally` en cada salida.** Colgar, un límite, un socket perdido, un
   error, un acceso revocado o un apagado terminan todos en el mismo teardown.
   Registra el fin de la llamada, para que una reconexión que lo espera no
   espere también al colgado, después cuelga la llamada del provider (el
   endpoint de colgado de OpenAI; una llamada por relay termina cuando el
   servidor cierra su socket hacia el provider) y después termina el run con su
   coste.
2. **Heartbeats.** El proceso que mantiene una llamada escribe su coste y sus
   segundos cada 15 segundos. Cada heartbeat vuelve a comprobar además la sesión
   de quien llama, su membresía, el estado publicado del agent y el interruptor
   de la organización, y termina la llamada cuando falla cualquiera de ellos.
3. **El barrido.** Un trabajo programado, cada minuto y una vez al arrancar,
   cuelga toda llamada cuyo heartbeat tenga más de 45 segundos, o cuyo fin se
   registró pero cuyo colgado falló. Solo necesita el id de la llamada y la
   clave.
4. **Apagado.** Un servidor al que se le ordena parar cuelga sus propias llamadas
   antes de irse.
5. **El navegador** cierra su conexión peer cuando la pestaña se oculta
   definitivamente (`pagehide`) o el socket se cierra. Es una comodidad; las
   cuatro de arriba son la garantía.

!!! danger "El peor caso de una llamada de OpenAI perdida"

    Si fallaran todas las redes de seguridad, una llamada en silencio cuesta casi
    nada y una con mucha conversación unos 5–15 $ por su hora. El riesgo mayor no
    es el dinero: es la clave de tu organización mantenida abierta sin
    herramientas, sin aprobaciones y sin auditoría. El barrido reduce esa ventana
    a cerca de un minuto.

## Reconexión { #reconnecting }

Una conexión caída recibe **un reintento automático en 10 segundos**. La conexión
nueva solo se acepta para la misma persona, el mismo agent y la misma
conversación, y solo dentro de los 10 segundos posteriores al fin de la
anterior; termina la anterior si sigue medio abierta. El tiempo y el budget se
arrastran: una reconexión continúa el reloj de la llamada en vez de reiniciarlo.

La sesión nueva empieza desde los turnos guardados hasta ese momento, como
**texto**, así que no se repite nada, ninguna herramienta se ejecuta dos veces y
el audio no se vuelve a facturar. Cuando esos turnos llenarían más de la mitad
del context window del modelo, los más antiguos se convierten en un resumen
breve escrito por el modelo de chat del agent (facturado al run) y los recientes
siguen palabra por palabra.

Cada conexión es su propio run, enlazado con el que retomó. Activity muestra la
cadena como una sola llamada, con el tiempo y el coste de cada conexión sumados.

!!! note "La reanudación propia de Gemini"

    Gemini termina sus conexiones tras unos diez minutos y las reanuda dentro del
    proceso, dentro de una misma llamada. Una reconexión desde el navegador es una
    sesión nueva sembrada con texto, como con cualquier otro provider.

## Transcripciones { #transcripts }

Cada turno se guarda en el momento en que termina, como un mensaje normal de la
conversación: las palabras de quien llama a partir de la transcripción de
entrada, las del agent a partir de lo que dijo. Las llamadas a herramientas
aparecen en línea, como en el chat de texto. Un fallo pierde como mucho el turno
en curso, y una reconexión no puede guardar un turno dos veces.

Cuando hablas por encima del agent, su respuesta se corta hasta lo que oíste y se
marca como interrumpida. Sobre el relay el servidor sabe exactamente qué se
reprodujo. Sobre WebRTC no lo sabe, así que el corte es una estimación, hecha a
partir de cuándo empezaste a hablar. Los subtítulos en directo pueden ir
ligeramente por delante del audio.

Los **guardrails** se ejecutan sobre las transcripciones. Una activación sobre
las palabras del agent lo corta a mitad de frase y muestra un aviso; una
activación sobre las palabras de quien llama no se anuncia. En ambos casos la
activación se cuenta en la llamada y el turno entero se guarda como
`[withheld by a guardrail]`, y un guardrail que oculta en lugar de bloquear
guarda el texto ocultado. Las palabras habladas no se pueden filtrar antes de
que se oigan - la tarjeta Voice lo dice.

Las herramientas se revisan a la vuelta: el resultado de una herramienta se
revisa, y se bloquea, antes de que el agent lo lea. La comprobación antes de
que una herramienta se ejecute es la aprobación, para las herramientas que la
necesitan. Los guardrails no revisan los argumentos de una herramienta.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Se graba el audio? { #is-audio-recorded }

No. La llamada solo conserva texto: la transcripción de cada turno se guarda como
un mensaje de la conversación, y este despliegue no guarda audio, ni en la base
de datos, ni en disco, ni en memoria después de la llamada. Lo que conserva el
provider lo rige tu acuerdo con ese provider.

### ¿Por qué un visitante no puede aprobar una herramienta? { #why-cant-a-visitor-approve-a-tool }

Un visitante en un widget o una página alojada es anónimo, y una aprobación es
una decisión de la que alguien tiene que responder. Así que las herramientas que
necesitan aprobación se dejan fuera de la llamada de un visitante por completo, y
el agent dice claramente cuándo no puede hacer algo ahí.

### ¿Qué pasa si mi pestaña se cierra a mitad de llamada? { #what-happens-if-my-tab-closes-mid-call }

El socket se cierra, y el servidor cuelga la llamada del provider y registra su
tiempo y su coste. Si el propio servidor se detuvo, el barrido cuelga la llamada
en cerca de un minuto desde su último heartbeat. Los turnos dichos antes de que
se cerrara la pestaña ya están guardados en la conversación.
