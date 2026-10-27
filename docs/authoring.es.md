---
source_sha: "01dd91a1fa89"
title: "Asistente de autoría"
description: "El asistente de autoría lee lo que la gente valoró negativamente y cómo acabaron los runs, y sugiere cambios a las instrucciones, las herramientas, la configuración, los skills y los archivos de contexto de un agent. Una persona decide cada uno."
---

# Asistente de autoría { #authoring-assistant }

El **asistente de autoría** mejora agents a partir de evidencia. Lee lo que la
gente valoró negativamente y cómo acabaron los runs, y sugiere cambios a las
instrucciones de un agent, a los nombres y descripciones de sus herramientas, a su
[configuración](#configuration) y a los skills y archivos de contexto que usa.
Nunca cambia nada por su cuenta: cada sugerencia espera a una
persona, una aceptada pasa al [draft](concepts.md), y nada llega a nadie hasta
que se publica el draft.

Hace tres cosas:

- **Mejorar** un agent: sugerir cambios a partir de sus runs valorados
  negativamente y fallidos. En la consola, cada **Improve** abre el [asistente Improve](#the-improve-wizard);
  una solicitud puntual sigue disponible por la API.
- **Verificar** tus propios cambios: comparar el draft con la versión en la que
  se basa - la última publicada - con la misma evidencia y decir qué mejoran los
  cambios, qué arriesgan y qué quitaron.
- **Mejorar un skill** o un **archivo de contexto**: sugerir un cuerpo nuevo a
  partir de los runs que lo leyeron.

El asistente es un [agent de sistema](concepts.md#system-agents) propio, que
aparece con los demás agents de sistema de la organización. Un administrador
edita sus instrucciones como las de cualquier agent - cambiar un agent de
sistema requiere `org:settings` -, y sus runs son runs normales: con budget, con
precio y visibles en Activity. Nunca es el agent del que trata un Improve o un
Verify. Configurado para
[buscar en la base de conocimiento](concepts.md#system-agent-spec), lee las
bases de conocimiento del agent que mejora.

Expande **Asistente de mejora** al mejorar o verificar para elegir un
asistente publicado. Cambiar la selección borra la estimación anterior, de modo
que el consentimiento corresponde al precio y presupuesto elegidos.
`improver_agent_id` se conserva en la tarea; las sesiones en segundo plano aceptan
la misma selección. El worker vuelve a comprobar tipo, publicación y acceso
actual. Una selección eliminada falla en lugar de volver al valor predeterminado.

## Qué lee { #what-it-reads }

El asistente no tiene herramientas. Lo que lee se reúne para él, de los runs del
agent de los últimos 30 días:

- respuestas valoradas negativamente, primero las que tienen comentario;
- runs que fallaron, alcanzaron un budget o fueron bloqueados por un guardrail;
- respuestas valoradas positivamente, como contraste.

Un run sin valorar que salió bien no dice nada y no se lee. Tampoco una prueba
del panel de pruebas del Builder ni el run de un delegado.

**Aprende solo de casos de entrenamiento.** Además de chats valorados, el asistente lee respuestas de entrenamiento fallidas, regresiones confirmadas, razones del juez y notas de Review de [datasets](datasets.md) accesibles. Recibe tasas de acierto de entrenamiento por etiqueta y criterio del juez, y cantidades de fallos corregidos y nuevos. Las preguntas de control, respuestas y puntuaciones nunca entran en su prompt. Los runs del juez y del propio asistente siguen excluidos.

Cuando hay más que leer de lo que cabe en una petición, los runs se leen primero
en grupos y las sugerencias se escriben a partir de lo que mostró cada grupo.

### Cada cita se comprueba { #every-quote-is-checked }

Cada sugerencia lleva una justificación y la evidencia que la respalda: los runs
en los que se apoya y citas de ellos. Antes de que nadie vea una sugerencia, cada
cita se compara palabra por palabra con el run que nombra. Una cita que no está
ahí, un run que no está entre los que leyó el asistente y todo lo que pase de
doce elementos o seiscientos caracteres se descarta, y la sugerencia dice
cuántos fueron. Quien no tiene `runs:view` ve en qué runs se apoya una
sugerencia, no lo que se dijo en ellos.

La comprobación demuestra que una cita está en su run, no que tenga que ver con
lo que respalda: una cita real sobre otra cosa la supera. Por eso un hallazgo de
Verificar nombra la línea de la edición a la que se refiere, y esa línea tiene
que formar parte de la edición. La barra muestra esa línea encima de las citas
del hallazgo, para que el lector juzgue si la respaldan. Un hallazgo de que la
edición está respaldada sin ninguna cita que se pueda comprobar no se muestra.

Cuando termina una solicitud al asistente - Verificar, o Mejorar por la API - con el Builder abierto, un diálogo muestra la cantidad de respuestas revisadas, cambios propuestos y guardados, y propuestas rechazadas con sus motivos. **Ver resultado** permite abrirlo de nuevo. Un resultado vacío explica que no se pudo aplicar nada, sin efecto esperado. El texto del efecto que contiene identificadores de runs se sustituye por una descripción con la cantidad de respuestas fuente enlazadas.

Cada texto cambiado - instrucciones, la descripción de una herramienta, un archivo de contexto - aparece como diff: líneas eliminadas y añadidas con las palabras cambiadas marcadas, unas pocas líneas sin cambios alrededor de cada cambio y el resto plegado, unificado o lado a lado en una pantalla ancha. Cada cambio conserva su justificación y la evidencia enlazada; los identificadores de runs en una justificación aparecen como conversaciones numeradas.

Tras completar una comprobación, las personas con `runs:view` pueden comparar respuestas de ambos lados en el diálogo y abrir la comprobación completa. Antes, el diálogo propone ejecutarla. Un agente sin chats valorados ni evidencia de entrenamiento muestra una línea compacta del asistente sobre sus instrucciones.

## Sugerencias { #suggestions }

Las sugerencias de una sesión de mejora, de Verificar o de la API esperan en la
**barra del asistente** de la pestaña Build del agent. Cada sugerencia muestra el fragmento que cambia en su contexto, el porqué
y la evidencia, y cada una se decide por separado:

| Acción | Qué ocurre |
|---|---|
| **Aceptar** | El cambio se escribe en el draft. No se publica nada. |
| **Editar** | Se acepta tu propia redacción en lugar de la sugerencia. Para las instrucciones se abre el texto completo: la versión actual junto a la propuesta, que editas, con el diff redibujado mientras escribes. Solo se guarda el pasaje sugerido; el texto de fuera se cambia en el editor de instrucciones. |
| **Descartar** | Queda registrado; una petición posterior no lo vuelve a sugerir. |
| **Deshacer** | Revierte la decisión mientras aún encaja en el draft. |

Una sugerencia se ancla en dónde estaba su fragmento y en lo que lo rodeaba, no
solo en el texto, así que una línea que aparece dos veces se cambia donde se
pretendía. Si el draft ha cambiado - el fragmento se eliminó o la descripción de
una herramienta se cambió a mano -, la sugerencia dice que **ya no encaja en el
draft** y solo se puede descartar. Deshacer se niega igual cuando el texto
aceptado se editó después a mano: tiraría esa edición.

La barra tiene dos pestañas, cada una con su número. **To review** muestra entera
cada sugerencia que sigue pendiente. **Decided** pliega cada una aceptada, editada
o descartada en una línea que dice qué clase de cambio es - instrucciones, la
descripción de una herramienta, un ajuste, un skill nuevo -, cómo se decidió y para
qué servía; al abrir la línea se ven el cambio y Deshacer. Las dos pestañas agrupan
los cambios por clase. La barra se abre en To review, o en Decided cuando ya no
queda nada por revisar.

Un Mejorar más reciente sustituye a las sugerencias pendientes; Verificar añade
las suyas en su lugar. Publicar el draft las cierra: sus decisiones son
definitivas y la barra deja de mostrarlas, junto con el resto de lo que el
asistente informó antes de la publicación, porque todo ello trataba de un draft que
ahora es una versión. Se conservan guardadas con sus decisiones. Una solicitud que
sigue en curso cuando se publica la versión muestra lo que encuentra al terminar.

Un cambio que propone el asistente y que no se puede guardar no desaparece en
silencio. La barra lo enumera bajo **ideas que el asistente no añadió**,
con el motivo: el pasaje que cambia no está en las instrucciones o aparece más de
una vez, el agent no tiene esa herramienta, ese ajuste no es algo que pueda
cambiar. El worker registra los mismos motivos. Un pasaje copiado con las
comillas enderezadas, sin backticks o con las líneas unidas sigue encontrando el
texto del draft.

### Comprobar con evals { #check-with-evals }

**Comprobar con evals** ejecuta un [dataset](datasets.md) contra la base del
draft - la última versión publicada - con todas las sugerencias pendientes
aplicadas, junto a esa versión en el mismo
[eval run](evals.md#a-baseline-in-the-same-run). Una guardiana puede retener
producción en una versión anterior; la comprobación nunca mide contra ella, así
que lo que cambió la última versión está en ambos lados y nunca se atribuye a una
sugerencia. Cuando el draft se ha alejado de su base - con cambios tuyos o con
sugerencias aceptadas antes -, el baseline es el propio draft, ejecutado de nuevo
en lugar de tomado de un run anterior, para que las sugerencias sean la única
diferencia; la estimación también pone precio a ese lado. Los lados se nombran
por lo que son, en el diálogo y en el run: "v2 + 1 suggestion" frente a "v2", o
"Draft + 2 suggestions" frente a "Draft". Comprobar no acepta nada y el draft no
cambia. Mientras una sugerencia pendiente ya no
encaje en el draft, o choque con otra, la comprobación se rechaza hasta que se
acepte o se descarte: el run mide exactamente lo que espera.

En lugar de un dataset, la comprobación puede ejecutar una de las
[suites](evals.md#suites) del agente: su dataset, en su entorno. El run compara
los dos lados como cualquier comprobación y, cuando termina, también dice qué
habría dicho la suite: aprobado, suspendido o sin conclusión, y por qué, según el
umbral que la suite tenía al empezar la comprobación. Se ve en el run y junto a
la comprobación en la franja, con la misma redacción que los resultados de la
propia suite.

La franja resume cada comprobación terminada en una frase que enlaza su run -
"audit-smoke would fail: breaks “Do you ship to Canada?”", o lo que rompió y
arregló en el dataset.

La comprobación no es uno de los runs de la suite: no está en ningún historial
de suite, no avisa a nadie, y Aceptar se guía por el veredicto del propio run.
Un cambio de skill o de contexto comprobado en una suite del agente en el que
funciona recibe lo mismo.

Cada caso tiene una asignación fija a entrenamiento o control, conservada entre versiones del dataset. Los ajustes del dataset eligen la proporción de control solo para casos futuros (50% por defecto). Las comprobaciones de sugerencias y sesiones de mejora miden solo casos de control y requieren al menos cinco preguntas evaluables.

Se excluyen copias de preguntas de entrenamiento o evidencia mediante el texto normalizado y la identidad del run de origen, incluso si se introducen a mano o se generan. Bajo el mínimo, la sesión se detiene con `no_data` e indica cuántas preguntas añadir. El run identifica ambas partes y las copias excluidas. Las suites normales y las puertas de promoción siguen contando todos los casos.

Una sesión de mejora fija la versión del dataset y las identidades de los chats fuente. Las rondas posteriores pueden aprender de sus resultados de entrenamiento; nuevos chats y casos no cambian la muestra de control.

Una comprobación cuenta como la prueba del draft en cuanto el draft es
exactamente lo que comprobó - cada sugerencia comprobada aceptada y nada más
cambiado -, así que el diálogo de publicación informa de su veredicto; tras otro
cambio, dice que esa prueba está desactualizada. Una comprobación medida contra
el propio draft nunca cuenta: no dice nada del draft frente a la versión
publicada que sustituiría. Una comprobación no envía nada
por sí sola a la [cola de revisión](datasets.md#review) de un dataset, ya que no
se aceptó nada; la página de su run lo dice junto a **Send failed to review**.

Cada sugerencia indica el efecto que espera. La barra lo muestra junto a los eval
runs que comprobaron las sugerencias, para que puedas comparar la predicción con
lo que encontraron los runs.

## Configuración { #configuration }

Además del texto, el asistente puede sugerir un cambio en algunas partes de la
configuración de un agent. Cada uno es una sugerencia como cualquier otra, que se
decide por separado en la barra y se muestra por su nombre: el modelo, la base de
conocimiento, el archivo de contexto, la capability o el servidor MCP al que se
refiere, nunca un identificador.

| Parte | Qué puede hacer una sugerencia |
|---|---|
| Descripción | Fijarla |
| Modelo | Cambiar el perfil de modelo |
| Ajustes del modelo | Fijar la temperatura, top-p, el máximo de tokens, el timeout o las llamadas paralelas a herramientas |
| Límite de pasos | Fijar `max_steps` |
| Capabilities | Añadir o quitar una, o cambiar sus ajustes - solo donde los ajustes tratan únicamente de calidad, como cuánto conocimiento recuperar o cuándo compactar; los ajustes que llegan a una URL, un dominio, una conexión, un proveedor o datos personales nunca cambian, y Subagents nunca se añade ni se reconfigura. Una salvaguarda - Guardrails - solo se puede añadir: nunca quitar ni reconfigurar, se nombre como se nombre en la sugerencia |
| Aprobación | Hacer que una capability o una de sus herramientas pregunte antes |
| Especialistas | Reescribir la descripción de un [especialista](reference/capabilities.md#delegation) integrado |
| Bases de conocimiento | Vincular o desvincular una |
| Archivos de contexto | Vincular o desvincular uno |
| Herramientas MCP | Cambiar qué herramientas de un servidor vinculado puede llamar el agent |

Nada más es una sugerencia: las suites de evals y sus umbrales, los datasets, los
budgets, la observabilidad y un delegado fijado nunca los cambia el asistente.
**Editar** funciona sobre un único valor o un texto - un ajuste, el límite de
pasos, una descripción; todo lo demás se acepta o se descarta tal como se
sugirió.

### Ampliar el acceso { #widening-access }

El asistente puede sugerir dar al agent más a lo que llegar: una capability, una
base de conocimiento, un archivo de contexto, más herramientas MCP. Una
sugerencia así se marca como **Añade acceso** y nombra cada cosa que añade.
Nunca amplía lo que se ejecuta sin una persona:

- Una capability que añade llega con cada una de sus herramientas que cambia
  algo configurada para pedir aprobación, sea cual sea el valor que les dio la
  propia sugerencia.
- Permitir más herramientas de un servidor MCP hace que una vinculación que no
  pedía nada pida aprobación para las herramientas que escriben. **Deshacer**
  devuelve las herramientas y las deja preguntando: volver a bajar la aprobación
  es decisión de una persona. En un servidor al que cada persona llega con su
  propia cuenta, una herramienta cuya descripción el asistente no puede ver
  cuenta como una que escribe.
- La aprobación solo se endurece: una sugerencia puede hacer que una capability
  o una herramienta pregunte antes, nunca que deje de preguntar.

Una sugerencia que vincula una base de conocimiento, un archivo de contexto, un
perfil de modelo o un servidor MCP, o que deja al agent llamar a más herramientas
MCP, solo la acepta quien podría hacer ese cambio a mano: aceptarla como
cualquier otra persona se rechaza, como lo rechazaría el Builder.

### Un cambio de modelo { #a-change-of-model }

Una sugerencia de cambiar el modelo dice cuánto costaría un run con cada modelo,
calculado a partir de los runs recientes del agent. Si se calcula con menos de
cinco, dice que es una estimación aproximada y con cuántos runs.

Un cambio de modelo solo se acepta cuando ha dado resultado. **Aceptar** sigue
desactivado, y dice por qué, hasta que una
[comprobación con evals](#check-with-evals) de exactamente lo que deja aceptar -
el draft con todas las sugerencias aún en espera aplicadas - se haya ejecutado
con ese modelo sin encontrar ninguna regresión confirmada. Descartar otra
sugerencia o editar el draft deja desactualizada la última comprobación, y hace
falta una nueva.

Una comprobación que dejó un caso sin decidir - nada lo calificó, o el provider o un
evaluador fallaron en él - o que no llegó a un veredicto también lo retiene:
califica las respuestas o vuelve a ejecutar la comprobación. Igual una
comprobación en la que el agent se cayó: corrige lo que falló y vuelve a
ejecutarla.

## Skills { #skills }

Un skill se mejora desde su banco de trabajo en Skills. Lo que sugiere el
asistente es un cuerpo nuevo completo, que espera con los demás cambios de
[skills](skills.md) en Skills, con su justificación y evidencia.

Aplicar un cambio a un skill es inmediato: cada agent vinculado al skill lee el
cuerpo nuevo en su siguiente run. Por eso un cambio a un skill se puede comprobar
antes con evals, en un agent que lo usa: los dos lados ejecutan la versión
publicada de ese agent, y solo cambia el cuerpo del skill. Un cambio escrito para
una versión anterior del skill se rechaza si alguien ha cambiado el skill desde
entonces.

## Archivos de contexto { #context-files }

Un [archivo de contexto](context.md) se mejora desde su editor en la página
Context, a partir de los runs de los agents que lo leen. Lo que sugiere el
asistente es un cuerpo nuevo, y espera encima de la lista en esa página, con su
justificación y su evidencia, y con los agents vinculados al archivo - en la medida
en que puedas verlos. Por cada archivo espera un cambio a la vez.

Aplicarlo tiene efecto inmediato, como con un skill: cada agent vinculado al
archivo lee el cuerpo nuevo en su siguiente run. Por eso la primera acción es
**Comprobar con evals**, en un agent que usa el archivo, con solo el cuerpo del
archivo distinto, y **Aplicar** dice antes de pulsarlo para qué agents y
entornos entra en vigor el cambio, qué suites de evals pone en cola y qué
guardianas lo comprueban solo en la siguiente promoción. Aplicar avisa a los
propietarios de esos agents. Un archivo editado después de proponerse el cambio
no admite que se aplique: compara los dos y edita el archivo a mano, o vuelve a
pedírselo al asistente.

El asistente nunca propone el cuerpo tal como está, y una petición nueva
reescribe el cambio que ya espera. Aplicar y Descartar nombran la versión del
cambio que leíste, y se rechazan si ha cambiado desde entonces, tanto para un
cambio a un skill como para un archivo.

## Describir un agent nuevo { #describing-a-new-agent }

El diálogo de creación ofrece describir el agent en lugar de rellenar el
formulario. La descripción va al [Architect](console.md#the-assistant), que crea
drafts de agents y pregunta antes de crear uno; el resultado es un draft normal.

## Coste y budget { #cost-and-budget }

Mejorar y Verificar dicen qué leerían y cuánto costaría antes de gastar nada, y
empiezan con un segundo clic. El asistente tiene su propio budget mensual, cinco
dólares al crearse, que puede cambiar quien edita el agent. Una petición que
costaría más de lo que les queda al asistente o a la organización se rechaza
antes de escribir nada.

En el dashboard, la línea de gasto indica aparte lo que costó el asistente **en
mejoras**, separado de lo que costaron los evals.

La retención de actividad conserva el coste total de los runs pagados eliminados de una sesión, sin conservar preguntas ni respuestas. Eliminar actividad antigua no restablece el límite de gasto. Las comprobaciones nuevas y los reintentos se suman al importe conservado; la cancelación mantiene visibles los costes ya incurridos.

## Acceso { #access }

| Para | Necesitas |
|---|---|
| Iniciar Mejorar o Verificar en un agent | `runs:view`, permiso de edición del agent y poder usar el asistente |
| Mejorar un skill | `runs:view`, permiso de edición del skill y poder usar el asistente |
| Mejorar un archivo de contexto | `runs:view`, `context:edit` en el archivo y poder usar el asistente |
| Aceptar, descartar o deshacer una sugerencia | Permiso de edición del agent |
| Aceptar una sugerencia que vincula algo o da alcance a algo | También el acceso para vincularlo a mano |
| Aplicar o descartar un cambio a un skill | `skills:edit` en el skill |
| Aplicar o descartar un cambio a un archivo de contexto | `context:edit` en el archivo |
| Comprobar con evals | Lo que pide un [eval run](evals.md#access), y permiso de edición del agent |

Los grants cuentan: un miembro con un grant de edición sobre un agent puede
mejorar ese agent.

## Cuando la asistencia de IA está desactivada { #when-ai-assistance-is-off }

Con el interruptor de **asistencia de IA** de la organización desactivado, el
asistente no se ejecuta: el servidor rechaza Mejorar, Verificar y mejorar un
skill o un archivo de contexto, y la consola los muestra desactivados con un enlace al interruptor. Las
sugerencias que ya esperan se pueden seguir aceptando, descartando y deshaciendo,
y un eval run que no necesita juez sigue ejecutándose.

## Sesiones de mejora en segundo plano { #background-improvement-sessions }

La API coordina mejoras en segundo plano. Envía primero un dataset o suite y el
límite de rondas a `/agents/{agent_id}/improvements/estimate`, y después el mismo
objetivo con `budget_usd` a `/agents/{agent_id}/improvements`. La estimación total
incluye propuestas, ambos lados de la evaluación, juez, intentos de confirmación
y una repetición de una comparación inconclusa por ronda. Cada paso de pago solo
empieza si su estimación completa cabe en el presupuesto restante. Un paso ya
iniciado puede terminar; el coste real sigue visible incluso tras cancelar.

La colección o sesión muestra los pasos guardados, identificadores de tareas,
veredictos y costes. El creador o un administrador puede enviar una petición a
`/{run_id}/cancel` dentro de la colección. El worker comprueba antes de cada paso
los permisos actuales del creador, borrador, última publicación, puntuación y
versión fijada de la suite. Los cambios invalidan la sesión; perder permisos la
detiene. Solo puede ejecutarse una sesión por agente.

Una mejora comprobada termina en `ready` y su candidato se convierte en el paquete
de sugerencias pendiente. La sesión nunca acepta, publica ni promueve cambios.
Los candidatos previos no sustituyen las sugerencias pendientes de una persona
mientras se comprueban. Una notificación lleva al creador a la sesión en cada uno
de sus finales, una vez por final: lista, detenida, fallida u obsoleta, detenida por
un administrador, decidida fuera del asistente, y cuando termina una comprobación de
conocimiento o de atribución de una sesión en espera. Una página de sesión abierta sigue cada etapa mediante eventos de cambio
en vivo, y una propuesta o comprobación terminada hace avanzar su sesión al instante.

Las sesiones realizan como máximo tres rondas. Una regresión o un resultado sin cambios inicia otra propuesta solo si su previsión completa cabe en el presupuesto restante. Dos rondas sin cambios, una comparación inconclusa y su repetición, un candidato ya probado o el límite de rondas detienen el ciclo con un motivo registrado. Las respuestas de entrenamiento antes y después informan la siguiente ronda; el contenido de control sigue oculto. Los costes se separan por ronda. La mejor ronda medida prioriza mejoras, menos fallos nuevos y luego mayor éxito decidido.

Tras finalizar, `/{run_id}/rounds/{number}/select` convierte una ronda medida en la propuesta pendiente, comprobando de nuevo la base y el acceso. La atribución opcional usa `.../attribution/estimate` y `.../attribution`. Iniciarla requiere `confirmed: true` y el importe revisado `estimate_usd`; se rechaza una nueva estimación superior. Prueba cada cambio pendiente por separado frente a la misma base y preguntas fijadas. El coste cuenta para el presupuesto de la sesión. La atribución no acepta, publica ni sustituye el veredicto conjunto de la ronda.

### El asistente Improve { #the-improve-wizard }

Abra **Improve** en la cabecera del agente o en la barra del asistente de la pestaña Build, desde la insignia **Needs attention** de la lista de agentes, desde la tarjeta del dashboard o desde la pestaña **Knowledge gaps** del agente. Está entre las demás acciones de la cabecera; cuando la versión que el agente sirve ahora tuvo respuestas valoradas negativamente o runs fallidos en los últimos 30 días, lleva un punto y su nombre dice por qué.

Cada **Improve** abre la sesión del agente mientras sigue trabajando o espera una decisión - un candidato comprobado que aceptar, o una sesión detenida o fallida que continuar, reintentar o descartar - y empieza una nueva cuando la sesión se guarda como borrador, se publica, se descarta, se cancela o se aparta; esa sesión queda en el [historial de mejoras](#improvement-history) del agente.

Una sesión vive en `/agents/<agent>/improve/<session>`; la página puede cerrarse y volver a abrirse mientras el trabajo continúa. Cada pantalla pide como mucho una decisión, indica quién decidió qué en ella y deja las opciones avanzadas bajo **Show details**. Cada pantalla empieza con cifras y gráficos pequeños, y cada estado se marca con un icono, no solo con un color; las respuestas completas, las citas y los motivos esperan en tarjetas que se abren. Una línea sobre los pasos da el estado de la sesión y lo que ha gastado de su límite.

Un paso se abre cuando tiene trabajo que mostrar o una decisión que pedir. La página sigue el paso en el que está la sesión y, tras abrir otro, **Go to the current step** vuelve a él.

1. **Inicio.** Tres cifras de los últimos 30 días y luego las preguntas de prueba propias del agente, ya elegidas y estimadas: la estimación, con la duración aproximada de la sesión, aparece sin hacer clic y no gasta nada, así que **Start improving** es la única decisión. Otras preguntas de prueba, el límite de gasto, el agente auxiliar y una prueba de las respuestas actuales están bajo **Show details**. Un agente sin preguntas de prueba recibe **Write test questions for me**: las respuestas valoradas se convierten en preguntas, se escriben más para temas sin ejemplo y la estimación llega cuando están listas. La sugerencia tras la primera publicación abre esta pantalla para fijar una referencia.
2. **Comprender.** Una frase y una barra cuentan los problemas que corregir en el agente y la información que falta en la base de conocimiento. Los ejemplos cuyas carencias se unieron a un mismo tema de lagunas de conocimiento forman una tarjeta, que muestra la pregunta y se abre a la respuesta, los comentarios y el motivo por el que el clasificador la puso ahí. Las columnas las decide el clasificador. **Ignore this** y **Put it back** se guardan en la sesión mediante `PUT /{run_id}/evidence/{evidence_run_id}` con `decision` igual a `ignored` o `null`. Los intentos posteriores dejan fuera de los cambios del agente los ejemplos ignorados; nada ya propuesto o medido cambia.
3. **Conjunto de prueba.** Las preguntas, en una barra por origen: respuestas valoradas negativamente, respuestas que gustaron, preguntas escritas para temas sin ejemplo y preguntas añadidas a mano, y en una segunda barra las que ayudan a escribir los cambios y las apartadas. Cuando quedan demasiado pocas preguntas para medir un cambio, ofrece escribir tantas como le faltan a la sesión y luego empezar una sesión nueva con ellas.
4. **Hoy.** Una barra de las preguntas que el agente maneja bien ahora, las que no maneja bien y las que no se pudieron calificar; cada pregunta débil se abre a su respuesta y la frase del evaluador.
5. **Cambios.** Cuántos cambios se propusieron y cuántos se incluyen, y luego cada cambio como diff con Debería corregir, Por qué y Basado en plegados debajo, y **Include in the test**. Los borradores de conocimiento forman su propia columna. Un tema recibe borrador aunque haya preguntado poca gente, porque una persona revisa cada borrador antes de añadirlo; un borrador escrito a partir de la pregunta de una sola persona lo indica. Si no se encontró ningún cambio, la pantalla enumera lo que probó cada intento.
6. **Comprobación.** Las etapas de la prueba, cada una marcada como hecha, en curso o sin empezar: preguntar al agente mejorado, calificar y volver a preguntar las respuestas cuyo resultado cambió.
7. **Resultado.** Primero, a qué llegó la sesión, en frases construidas a partir de los veredictos - qué intento mejoró el agente, o que ninguno lo hizo y cuál lo empeoró - con los temas que faltan en la base de conocimiento y por qué se detuvo la sesión. Bajo **What you can do** hay una acción principal: **Review and accept the changes** cuando espera un candidato comprobado, **Try again** mientras quedan intentos o presupuesto, **Draft the ones you need** cuando solo falta conocimiento y, si no, **End without changes**, junto a **Start a new session** y una pista para añadir preguntas de prueba donde el agente responde mal. Un paso fallido ofrece primero **Retry this step within the spending limit**. Después, las cifras: arregladas y rotas cuentan solo los cambios confirmados al preguntar de nuevo, con los aún no confirmados en letra pequeña debajo, y el recuento de temas sin conocimiento lleva a su lista. Cada intento es una fila cerrada: su veredicto, lo que arregló y rompió, las preguntas apartadas antes y después, su coste, y el mejor intento marcado. Una fila se abre a las barras de preguntas manejadas bien antes y después, el coste por respuesta cuando cambió y cada pregunta cambiada con sus respuestas antes y después; un cambio que las respuestas repetidas no confirmaron espera bajo **Not confirmed yet**, marcado solo como posiblemente arreglado o posiblemente roto. Las comprobaciones de cambios individuales y la prueba de un borrador de conocimiento están bajo **Show details** en la fila.
8. **Aceptar.** Cifras de lo que la nueva versión corrige, rompe y cuesta por respuesta, y con cuántas preguntas se probó. Cada documento de conocimiento de esta sesión ofrece **Review and add** o **Not now**, que lo aparta durante la sesión (`PUT /{run_id}/topics/{topic_id}/later`). Cada lugar donde la gente usa el agente dice si cambia en el acto, tras superar su comprobación automática o se queda en su versión. Después, **Publish version N** o **Keep as draft**. Cualquiera de las dos termina la sesión, y este paso dice entonces qué se decidió, quién y cuándo, con un enlace a la versión. Si no hay nada que aceptar, el paso se omite.

Un paso de propuestas o eval fallido se reintenta explícitamente con `/{run_id}/retry`; varios clics no crean otro trabajo. Los reintentos automáticos nunca repiten llamadas pagadas. Las decisiones humanas actualizan la sesión a aceptada, publicada o descartada. La acción confirmada `/{run_id}/finish` acepta los cambios comprobados y opcionalmente los publica en una transacción.

Una sesión guardada como borrador está terminada: el borrador se publica con el **Publish** del propio agente y, cuando esa versión es la que midió la sesión, queda registrada en ella. Terminar puede crear una suite que se ejecute al publicar, sin regresiones permitidas. Se mantienen los permisos y validaciones habituales, y los entornos protegidos esperan a sus comprobaciones. Los cambios editados después de la medición deben comprobarse de nuevo.

En la pantalla Cambios, seleccione un subconjunto con **Incluir en la prueba**. Calcule y confirme la nueva prueba antes de gastar; cambiar la selección o una propuesta invalida la estimación. Los cambios seleccionados se miden con la misma base y las preguntas fijadas. Las pruebas anteriores permanecen en el historial de la ronda. Las propuestas excluidas o añadidas después quedan pendientes; solo se puede aceptar la selección medida. Esta prueba no solicita automáticamente otra propuesta. Los resultados individuales atribuyen únicamente diferencias confirmadas al repetir las respuestas; una prueba inválida o incompleta no atribuye efectos.

La estimación incluye clasificar respuestas de chat incorrectas con las bases de conocimiento editables del agente, agrupar sus carencias y reservar hasta tres pasajes propuestos por base. El worker conserva los permisos actuales de la clave API del solicitante y comprueba de nuevo la estimación completa del paso antes de iniciarlo. Solo los chats fuente fijados y no borrados llegan a clasificación, agrupación o redacción; los fallos de entrenamiento siguen como evidencia del agente, sin textos de control para estos asistentes.

Un fallo del clasificador se muestra y conserva las conversaciones fuente. Una sesión solo de conocimiento termina con borradores para revisar, sin una versión vacía. Probar un borrador exige su propia estimación y confirmación; añadir contenido sigue siendo una decisión humana.

Una decisión humana y su retirada recalculan la ronda medida actual en la misma transacción que los resultados del test y de las comprobaciones automáticas. Se conservan la ronda seleccionada y su coste. Las mediciones anteriores y las pruebas individuales no reemplazan el veredicto conjunto actual. Una revisión no inicia llamadas al modelo, publicaciones ni cambios de entorno. Si el solicitante original ya no puede leer la comparación, la ronda queda inconclusa en vez de conservar un resultado favorable. Los eventos del dataset actualizan las vistas de pruebas, comprobaciones, sesión y entorno.

La barra distingue el trabajo terminado, en curso, pendiente de su decisión, omitido y aún no iniciado. Seleccione cualquier paso para inspeccionarlo; esto no inicia una acción de pago. Al abrir de nuevo la sesión aparece el trabajo actual, mientras cada paso conserva su estado. En el teléfono, el paso actual y su estado aparecen debajo de los indicadores.

Elija **Try again** en el resultado para otra ronda o **Aumentar el límite y continuar** si un paso no cabía en el presupuesto. Antes de gastar más se muestran una estimación completa nueva y una confirmación; fuentes, preguntas fijadas y límite de rondas no cambian. Un paso fallido se reintenta en la misma ronda. Una prueba reanudada reserva solo las mediciones pendientes y la repetición inconclusa disponible. Reiniciar trabajo de pago, las comprobaciones de atribución y las de borradores de conocimiento exigen el solicitante y la identidad de clave API originales, con permisos actuales verificados.

**End without changes** en el resultado, **Descartar** en los demás pasos, confirma solo las propuestas pendientes de esta sesión. Conserva otros lotes y rechaza deshacer cambios aplicados. Las estimaciones no anuncian escrituras; las decisiones confirmadas actualizan las vistas abiertas.

#### Historial de mejoras { #improvement-history }

La pestaña **History** del agente lista sus sesiones de mejora, de la más reciente a la más antigua: cuándo empezó cada una y quién la inició, cómo salió su ronda elegida, qué se decidió y cuánto costó.

Una sesión terminada - guardada como borrador, publicada, descartada, cancelada o apartada porque cambió su punto de partida - abre su asistente solo para leer: cada paso y sus detalles se pueden abrir, y nada se puede cambiar ni pagar. Su último paso dice qué se decidió, quién y cuándo, lista los cambios que midió con su decisión, dice qué fue de cada documento de conocimiento que redactó y si una comprobación automática vigila el agente. Una sesión detenida o fallida sigue abierta: **Improve** y su entrada en el historial llevan de vuelta a ella para subir su límite y continuar, elegir una ronda, reintentar el paso fallido o descartarla.

La API responde `409` a cualquier cambio en una sesión terminada, salvo repetir la cancelación o el descarte que la terminó. `GET /{run_id}/changes` lee los cambios que midió su ronda elegida. Leer una sesión requiere acceso de lectura al agente y `runs:view`; cambiarla o empezarla requiere además permiso de edición del agente.

### Proponer un skill nuevo { #proposing-a-new-skill }

El asistente puede proponer **Worth creating a skill** cuando un procedimiento reutilizable aparece en al menos tres respuestas distintas de las evidencias. Cada cita debe figurar en la respuesta misma; los comentarios no demuestran por sí solos un procedimiento repetido. La tarjeta muestra nombre, descripción, contenido completo, motivo y citas verificadas. Una evaluación vincula un skill temporal solo al candidato: no crea ningún registro ni versión publicada.

**Accept** crea el skill privado y lo vincula al borrador del agente en la misma transacción. Requiere `skills:edit` y acceso de edición al agente. Sin permiso de creación se puede leer y comprobar la propuesta, pero Accept queda deshabilitado y explica el motivo. **Dismiss** no crea nada. **Undo** elimina el vínculo y conserva el skill independiente; una nueva aceptación lo reutiliza solo si conserva su nombre y contenido. Los skills contienen instrucciones y no conceden herramientas. El acceso adicional necesita propuestas independientes verificadas por la política; las herramientas de escritura requieren aprobación.

Un procedimiento que procede de menos de tres respuestas distintas no se propone como sugerencia. Espera en **To review**, en el grupo New skills, con su texto completo. **Dismiss** lo pasa a **Decided** y Deshacer lo devuelve. **Create skill** abre una vista previa: el nombre, la descripción y el contenido se pueden editar, y un aviso indica en cuántas respuestas se basa. **Create skill** en la vista previa crea el skill en la biblioteca y lo vincula al borrador del agente, nunca a una versión publicada. Requiere los mismos permisos que Accept y no llama a ningún modelo. Un segundo clic devuelve el skill ya creado.

La estimación reserva el contenido completo propuesto para cada respuesta candidata y sus repeticiones de confirmación, además del precio histórico por respuesta.

### Comprobar un borrador de conocimiento { #checking-a-knowledge-draft }

En una sesión terminada, elige un borrador y preguntas independientes sobre su tema. La estimación y la confirmación son independientes de aceptar los cambios del agente. La prueba compara **A**, los cambios seleccionados, con **B**, los mismos cambios más el borrador. Su resultado separado dice **suponiendo que la búsqueda encuentre este pasaje**: esta etapa inyecta el texto como contexto y no comprueba la búsqueda.

Se excluyen los casos de entrenamiento, las conversaciones y turnos de origen y las copias normalizadas de sus preguntas. Se necesitan al menos cinco preguntas de control independientes y evaluables; de lo contrario, el borrador **no se puede medir** y no comienza ninguna prueba de pago. La estimación completa incluye ambas variantes y repeticiones, cuenta contra el límite de la sesión y corresponde al borrador actual y las preguntas elegidas.

**Sin respaldo — verifica los hechos** significa que no queda ningún documento fuente del borrador en su base de conocimiento. Superar una prueba de respuestas no demuestra los hechos. Revisa el pasaje en el diálogo existente del tema y decide expresamente si lo añades. La prueba no crea archivos de contexto ni documentos y no publica nada. Las suites dependientes siguen ejecutándose cuando una persona añade un documento.

Los contenidos temporales se eliminan al terminar la prueba o cambiar el borrador. Un cambio invalida el resultado anterior. El borrado de los datos de una persona fuente también elimina las respuestas derivadas, las explicaciones de puntuación y los manifiestos de modelos. Cancelar la sesión cancela sus pruebas de conocimiento. Los costes incurridos se conservan tras cancelar o borrar datos.

El borrador registra huellas de todas las preguntas de entrada, incluidas las no citadas. Los borradores antiguos sin procedencia completa no se pueden medir; escribe uno nuevo primero. Las huellas y las identidades de los runs fuente se eliminan con el borrador al borrar los datos personales.

#### Comprobar la búsqueda real { #checking-real-retrieval }

Elige **Comprobar si la búsqueda lo encuentra** para comparar A con B mediante una superposición exclusiva de búsqueda. El borrador se vectoriza con el modelo elegido de la base de conocimiento y se añade a los candidatos solo durante ese run. Se mantienen las restricciones de organización, las listas de documentos permitidos, los filtros, el ranking y los límites finales. No se crea ninguna tabla vectorial, documento ni archivo de contexto. El contenido temporal también se elimina tras fallos o cancelaciones.

Una nueva corrección solo se considera demostrada si el borrador llegó a cada respuesta confirmatoria del candidato a través del resultado final de búsqueda. En caso contrario, el resultado no es concluyente, aunque la respuesta obtenga buena puntuación; se conservan las respuestas y evaluaciones reales. Ignorar un error de herramienta no convierte un fallo de búsqueda en éxito. La estimación incluye búsquedas adicionales de embeddings y repeticiones confirmatorias. Un modelo no disponible o sin precio conocido impide empezar trabajo de pago. Una persona debe seguir verificando los hechos y añadir expresamente el documento.

Las pruebas manuales y la generación de preguntas notifican a quien las inició cuando terminan, también si fallan. Repetir la entrega del trabajo no duplica el aviso. Las pruebas subordinadas de una suite o sesión de mejora utilizan la notificación del proceso principal. Las preferencias están en **Configuración → Notificaciones**. Las páginas abiertas de pruebas y conjuntos de datos se actualizan mediante el flujo de cambios tras confirmar el resultado.

El paso Comprender muestra una muestra limitada de fuentes, la causa registrada, la respuesta, los comentarios de evaluación y un enlace a la conversación. Las causas desconocidas permanecen explícitamente sin clasificar. El paso Preguntas de prueba lee la versión fijada de la sesión e identifica las preguntas de entrenamiento y reservadas. Hoy muestra la referencia solo después de completar correctamente la prueba; una ejecución parcial o fallida no se presenta como una medición de referencia. La vista de fuentes requiere `runs:view`, comprueba el acceso actual a las bases de conocimiento y oculta credenciales en todos los campos de texto.


El paso de aceptación muestra el número de la siguiente versión y repite el resultado medido de la ronda seleccionada. La comprobación automática se ofrece solo si el agente no tiene ninguna suite. Publicar guarda la identidad y el número de versión en la sesión: al volver a abrirla, el enlace sigue apuntando a esa publicación. Las sesiones antiguas sin este dato muestran su estado sin adivinar una versión. Un error al leer sugerencias permite reintentar; las sugerencias sustituidas no permanecen cargando indefinidamente. Los entornos protegidos esperan sus comprobaciones y los fijados conservan su versión actual.
