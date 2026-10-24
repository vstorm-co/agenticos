---
source_sha: "2e7dc8326cce"
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
  negativamente y fallidos.
- **Verificar** tus propios cambios: comparar el draft con la versión en la que
  se basa - la última publicada - con la misma evidencia y decir qué mejoran los
  cambios, qué arriesgan y qué quitaron.
- **Mejorar un skill** o un **archivo de contexto**: sugerir un cuerpo nuevo a
  partir de los runs que lo leyeron.

El asistente es un [agent de sistema](datasets.md#judge) propio, que aparece con
los demás agents de sistema de la organización. Sus instrucciones se editan como
las de cualquier agent, y sus runs son runs normales: con budget, con precio y
visibles en Activity.

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

**Nunca lee evals.** Los runs que respondieron un caso de [eval](evals.md), los
runs del juez y los propios runs del asistente quedan fuera de lo que lee, y
nunca ve puntuaciones. Un cambio comprobado con evals no debe estar ajustado a
los casos que lo comprueban.

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

## Sugerencias { #suggestions }

Mejorar y Verificar abren la **barra del asistente** en la pestaña Build del
agent. Cada sugerencia muestra el fragmento que cambia en su contexto, el porqué
y la evidencia, y cada una se decide por separado:

| Acción | Qué ocurre |
|---|---|
| **Aceptar** | El cambio se escribe en el draft. No se publica nada. |
| **Editar** | Se acepta tu propia redacción en lugar de la sugerencia. |
| **Descartar** | Queda registrado; una petición posterior no lo vuelve a sugerir. |
| **Deshacer** | Revierte la decisión mientras aún encaja en el draft. |

Una sugerencia se ancla en dónde estaba su fragmento y en lo que lo rodeaba, no
solo en el texto, así que una línea que aparece dos veces se cambia donde se
pretendía. Si el draft ha cambiado - el fragmento se eliminó o la descripción de
una herramienta se cambió a mano -, la sugerencia dice que **ya no encaja en el
draft** y solo se puede descartar. Deshacer se niega igual cuando el texto
aceptado se editó después a mano: tiraría esa edición.

Un Mejorar más reciente sustituye a las sugerencias pendientes; Verificar añade
las suyas en su lugar. Publicar el draft las cierra: sus decisiones son
definitivas y la barra las conserva como registro.

Un cambio que propone el asistente y que no se puede guardar no desaparece en
silencio. La barra lo enumera bajo **cambios propuestos que no se guardaron**,
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

Los casos tomados de las conversaciones de las que salieron las sugerencias
quedan fuera, y el run dice cuántos: un cambio nunca se mide con los datos a los
que se ajustó. Un dataset hecho solo de esos casos se rechaza.

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
mientras se comprueban. Una notificación lleva al creador a la sesión lista o
detenida.
