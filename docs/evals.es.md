---
source_sha: "7d204fe63485"
title: "Eval runs"
description: "Un eval run responde a cada caso de un dataset con una versión de un agent o su borrador, puntúa cada respuesta y compara el resultado con un baseline."
---

# Eval runs { #eval-runs }

Un **eval run** hace que un agent responda a cada caso de una versión de un
[dataset](datasets.md), puntúa cada respuesta como indica la
[puntuación](datasets.md#scoring) del dataset y conserva lo que pasó. Responde a
la pregunta que de verdad tiene quien edita un agent: ¿este cambio ha mejorado
el agent, lo ha empeorado o ninguna de las dos cosas, y cuánto ha costado?

Un run se compone de cuatro elecciones: el **agent** y qué parte de él se
ejecuta (una versión publicada o el borrador tal como está), la **versión del
dataset**, el **entorno** cuyas conexiones de prueba usan los casos y,
opcionalmente, **varios modelos** en paralelo. También puede ejecutar un
**baseline** - una versión anterior - en el mismo run, para que ambos lados se
encuentren con el mismo provider el mismo día.

## En la consola { #in-the-console }

La pestaña **Evals** de un agent se abre con un gráfico de líneas de su tasa de
aprobados run a run, el más antiguo a la izquierda, una línea por dataset, cada
una con su propio trazo. Un punto es rojo donde el run rompió casos, verde donde
los arregló, ámbar donde hizo ambas cosas y hueco para un borrador; al pasar el
cursor dice qué se ejecutó, frente a qué y cuándo, y un clic abre el run. El
gráfico se abre con los últimos 12 runs; arrastra los tiradores del rango de
debajo, o muévelos con las flechas, para ver más o menos.

Debajo están sus runs, agrupados por dataset, cada uno indicando qué se probó
frente a qué, su veredicto (Breaks 2, Worse overall · 4 broke, First result,
Pending) y la tasa de aprobados de cada modelo, con la tasa de las primeras
respuestas al pasar el ratón.

**Run evals** abre el diálogo de inicio con la respuesta obvia: el borrador
frente a la versión publicada actual cuando el borrador difiere de ella, la
versión publicada sola cuando no, y el borrador solo para un agent que nadie ha
publicado. El dataset con el que se midió el agent por última vez - o el único
que hay - ya está elegido; el entorno, las grabaciones y las repeticiones están
en **Advanced**. El coste se calcula a medida que se asientan los campos y dice
qué califica las respuestas y lo que conservan después los budgets del agent y
de la organización; el run solo empieza desde el botón que indica el importe.
**Draft differs from vN** en la página del agent lleva un botón **Test draft**
que abre el mismo diálogo, y el diálogo de publicación dice lo que encontró el
último run del borrador - o que no se ha probado desde su último cambio - sin
frenar la publicación.

La página de un run se abre con su veredicto en unas pocas frases - los casos
que el candidato rompe o arregla cada vez que se le preguntan, uno citado con
cuántos intentos lo repitieron, si es mejor o peor en conjunto cuando los
cambios confirmados permiten decirlo, y la tasa de aprobados antes y después -
junto con qué hacer a continuación: ver qué cambió entre las dos versiones
(History se abre en esa comparación, frente al spec probado, no al borrador
actual), mostrar los casos rotos, volver a Build o publicar el borrador.

Publish es la acción principal solo sin ninguna regresión confirmada ni caso del
candidato sin responder o sin calificar, y el run de un borrador modificado
desde entonces ofrece **Test again** en su lugar. Mientras el run responde, la
página dice cuántas primeras respuestas hay, y la comparación espera a los dos
lados. Las respuestas que el juez no logró calificar dicen por qué y no cuentan
ni como aprobadas ni como fallidas, y **Grade again**, en el encabezado, las
vuelve a calificar sin preguntar al agent, para quien pueda ejecutar el dataset.

Bajo el veredicto están los lados uno junto al otro, cómo se comparan y los
casos - cada fila con un punto de aprobado o fallido por lado, filtrados por
resultado o etiqueta, cada uno abriendo lo que espera el caso y las respuestas,
llamadas y motivos de los evaluadores de cada lado. Al elegir una etiqueta, los
lados, los cambios y los casos se leen dentro de ella; el veredicto sigue
abarcando todos los casos.

Una vez que están sus repeticiones, un run envía a la [cola de
revisión](datasets.md#review) del dataset lo que puede respaldar - cada
regresión que confirmó y cada respuesta en cuya calificación falló su juez, una
por caso - y dice cuántas son (`routed_to_review`). Un juez omitido no envía
nada: sus respuestas esperan en la página del run a **Grade again**. Si el envío
se rechaza, el run termina igual y su página dice por qué (`routing_error`). **Send failed to review** envía
el resto de las respuestas fallidas de un lado, para quien pueda editar el
dataset, y un caso cuya calificación anuló una persona queda marcado como
corregido.

En ambos casos una respuesta ocupa el lugar de una más antigua del mismo caso
que aún espera, que sale de la cola sin decisión - un run dice cuántas como
`routed_replacing` - y una respuesta más antigua que la que espera no se envía.

La propia pestaña **Evals** de un dataset lista cada agent medido en él, cada
uno con su tendencia y sus runs, y **Run evals** en su encabezado abre el
diálogo de inicio en el dataset y pregunta qué agent probar.

La tarjeta **Eval runs** del dashboard lista los runs más recientes de la
organización con su agent y su veredicto. Los casos de un eval y la
calificación del juez quedan fuera de cualquier otra cifra del dashboard, y
Activity los oculta salvo que su filtro de superficie pida todas las
superficies o solo los evals. Su lista muestra lo preguntado a cada run - su
primer mensaje de usuario, la pregunta del caso o, para el run del juez, lo que
calificó -, para reencontrarlo y convertirlo en caso. Allí un caso de eval abre
su eval run en ese caso, y su **See what the model saw**, lo que recibió el
modelo.

## Iniciar un run { #starting-a-run }

Iniciarlo son dos llamadas, para que no se gaste nada antes de que alguien haya
visto lo que costará.

```text
POST /api/v1/agents/{agent_id}/eval-runs/estimate   the estimate, nothing written
POST /api/v1/agents/{agent_id}/eval-runs            the same body; starts the run
```

El body indica el dataset (`dataset_id`, `dataset_version`), el candidato
(`candidate: "version"` con una `version` opcional, o `candidate: "draft"`), el
`environment_id`, los `model_profile_ids` que se comparan y `paired_baseline`.
La estimación es el coste medio de un run del agent en cada modelo, según sus
runs completados recientes, por el número de casos, más una llamada al juez por
caso cuando un juez puntúa el dataset y AI assistance está activado.

AI assistance está desactivado en una organización hasta que alguien con
`org:settings` lo activa. Mientras está desactivado el juez no se ejecuta: un
caso se decide por sus checks y sus llamadas a herramientas esperadas, los
criterios del juez se registran como omitidos y la estimación no cuenta el
juez.

Un agent sin historial en un modelo se estima como un caso típico -
`EVAL_FALLBACK_INPUT_TOKENS` de entrada, `EVAL_FALLBACK_OUTPUT_TOKENS` de
salida - al precio propio del modelo, o en `EVAL_FALLBACK_CASE_COST_USD` para un
modelo sin precio conocido, y la estimación dice que es una suposición aproximada
(`basis: "fallback"`). Un juez sin historial se calcula igual, en el modelo que
nombra su spec publicado; la estimación avisa si es el modelo probado, y la
página de un run si lo fue. El coste del baseline forma parte del total, salvo
que se reutilice un baseline reciente que coincida; en ese caso sus primeras
respuestas no cuestan nada y la estimación nombra el run del que provienen.

### El budget que deja { #the-budget-it-leaves }

Un eval gasta de los mismos budgets mensuales que el tráfico real: el límite
del agent y el de la organización. No hay un budget aparte para evals. Un
dataset grande puede por tanto dejar la producción sin budget el resto del mes,
así que la estimación muestra lo que conserva cada límite una vez que el run ha
gastado su total: `agent_after_usd` y `org_after_usd`.

Iniciarlo se rechaza con `402` antes de escribir nada cuando el total supera lo
que le queda a cualquiera de los dos límites. Las repeticiones de confirmación
(más abajo) no entran en esa comprobación, porque solo afectan a los casos que
cambian; la estimación muestra lo máximo que pueden añadir - todo caso
cambiado, repetido en cada lado, baseline reutilizado incluido - como
`rerun_ceiling_usd`, que el run conserva para que un run que gastó más de lo
estimado diga por qué. Cada caso se sigue comprobando contra ambos límites antes
de cada petición al modelo, como cualquier run, y un caso que choca con un
límite detiene todo el eval run como `budget_exceeded`.

### Qué se rechaza { #what-is-refused }

Un run que no podría decirle nada a nadie se rechaza antes de estimarse:

- una versión del dataset sin casos;
- una puntuación sin ningún evaluador obligatorio que pueda decidir algún caso
  de la versión: ningún check que aplicar, ninguna llamada a herramienta
  esperada y ningún juez. Cuando el juez es el único evaluador y AI assistance
  está desactivado, el rechazo lo dice: el juez necesita AI assistance, que está
  desactivado en esta organización, así que actívalo en los ajustes de la
  organización o añade un check;
- un agent que nunca se publicó, para el que se pide una versión: ejecuta su
  borrador en su lugar;
- un baseline para una primera versión, que no tiene nada antes.

## Cómo se ejecuta cada caso { #what-each-case-runs-as }

Cada caso es un run normal del agent con la superficie `eval`. Se comprueba
contra los budgets antes de cada petición al modelo y se registra su coste.
Queda fuera de las cifras de uso del dashboard, que cuentan solo la producción e
informan del coste del tráfico de evals a su lado (`cost.eval_usd`), y el
historial de runs lo omite cuando se le pide (`?exclude_surface=eval`). Su
lectura individual nombra el eval run y el caso al que respondió (`eval_case`),
para un lector que pueda ver el dataset. Se ejecuta como la persona que inició
el eval, con su rol actual, y no lee ni escribe su memoria personal.

Cada caso se ejecuta **aislado**, como describe [Entornos](environments.md):
una herramienta con una conexión de prueba en el entorno del run se ejecuta
contra ella, una herramienta de la que se sabe que solo lee se ejecuta en la
conexión normal, y todo lo que escribe sin conexión de prueba no se ejecuta: la
llamada y sus argumentos se guardan como una llamada prevista, que la
puntuación de trayectoria sigue juzgando.

Un caso tomado de una conversación puede responderse **desde la grabación** del
run del que salió (`from_recordings`): una llamada que coincide con la
grabación recibe el resultado grabado, y una que no coincide se retiene y se
marca como divergente. Un caso sin grabación utilizable se ejecuta aislado sin
ella.

### Un borrador nunca cuenta como versión { #a-draft-is-never-counted-as-a-version }

Un borrador sigue el mismo camino, con dos diferencias. Primero se valida
contra el acceso de quien lo inicia - todo lo que comprobaría una publicación -,
porque un borrador nunca se validó al guardarse. Y sus runs no se atribuyen a
ninguna versión: no aparecen en el uso de una versión, y las cifras de una
versión nunca incluyen respuestas que dio su borrador.

El borrador se copia al iniciar el run, así que cada caso responde al mismo
contenido aunque alguien siga editando.

## Ejecución y cancelación { #running-and-cancelling }

Un run se ejecuta en segundo plano, en un flow de worker propio, así que
sobrevive a un reinicio de la API. Los casos se ejecutan de pocos en pocos: como
mucho `EVAL_RUN_CONCURRENCY` por run y como mucho `EVAL_ORG_CONCURRENCY` entre
todos los eval runs de una organización, para que un dataset de 500 casos no
ocupe todas las peticiones que un provider permite a la organización.

Cancelar (`POST /api/v1/eval-runs/{id}/cancel`, quien lo inició o cualquiera que
pueda editar el agent) detiene lo que no ha empezado: los casos que ya se están
ejecutando terminan y se conservan, y no empieza ningún otro. El worker de un
run en marcha avisa cada `EVAL_HEARTBEAT_SECONDS` de que sigue vivo; un run cuyo
worker calla y cuyos casos no han avanzado durante
`EVAL_ABANDONED_AFTER_MINUTES` se da por fallido en el barrido horario de runs
colgados, que además libera sus plazas. Un run en cola aún no tiene worker -
espera un runner libre - así que el barrido lo abandona solo tras
`EVAL_QUEUED_ABANDONED_AFTER_HOURS`.

Mientras un run está en cola o en marcha, no se pueden eliminar el entorno que
nombra ni el perfil de modelo en que corre alguno de sus lados: sus casos
restantes responderían contra las conexiones de producción, o con otro modelo
que los casos anteriores.

## Resultados { #results }

Cada intento conserva la respuesta, las llamadas que hizo - cada una marcada
como ejecutada, bloqueada, reproducida o divergente -, el veredicto y el motivo
de cada evaluador, su coste, sus tokens y su latencia. La respuesta y las
llamadas se copian al resultado, porque el run de un caso no tiene una
conversación donde guardar una transcripción.

Cada brazo del run se resume en dos ejes, y por etiqueta:

| Eje | Mide |
|---|---|
| Calidad | Tasa de aprobados entre los casos decididos, cada uno según cómo salió la mayoría de sus intentos; a su lado, la tasa de las primeras respuestas; cuántos no pudieron decidirse |
| Eficiencia | Coste por caso aprobado, tokens por caso y latencia en p50 y p95 |

Un caso cuyo evaluador obligatorio no pudo ejecutarse queda **sin decidir**,
nunca aprobado. Uno en el que el juez falló o que omitió queda **sin
calificar**: el run lista esas puntuaciones como `ungraded_score_ids`, y
volver a calificarlas (`POST /api/v1/datasets/{id}/scores/rescore`) lee la
respuesta guardada en el intento en lugar de preguntar al agent. El veredicto
de una persona en la [cola de revisión](datasets.md#review) sustituye el
resultado de los evaluadores para ese caso, y las cifras del run lo siguen.

Un run terminado conserva el veredicto, los recuentos y las tasas de aprobados
de su primer candidato como `outcome`, para que un listado los lea sin volver a
comparar cada run. Se vuelve a comparar cuando, desde entonces, una persona ha
decidido alguna de las puntuaciones en las que se basa, o se ha vuelto a
calificar alguna.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first; ?draft=current
GET /api/v1/datasets/{dataset_id}/eval-runs  a dataset's runs over the agents the reader may see
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary and its outcome
GET /api/v1/eval-runs/{id}/cases             cases, what each expects, and every attempt;
                                             ?outcome=, ?tag=, ?arm_id=, ?case_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
GET /api/v1/eval-runs/{id}/arms/{arm}/spec   the spec one side ran; needs agents:edit
```

`?draft=current` conserva los runs que probaron el borrador tal como está
ahora - el mismo spec, sea cual sea el orden en que se guardaron sus claves -,
que es lo que lee el diálogo de publicación.

## Comparar con un baseline { #comparing-with-a-baseline }

Una comparación empareja los dos lados caso por caso según el id estable del
caso, e informa de cada caso como **regresión** (aprobaba, ahora no),
**arreglado** (no aprobaba, ahora sí), sin cambios o incompleto. Los casos que
solo respondió un lado cuentan como no comparados.

**El baseline por defecto es barato**: el último run completado del mismo
dataset en la versión anterior al candidato - la versión publicada, para un
borrador. Ambos lados llevan su fecha, su modelo y su versión del dataset,
porque pueden diferir en cualquiera de ellos.

Un run puede nombrar en su lugar un **run anterior** del mismo agent sobre el
mismo dataset como baseline (`baseline_run_id`). Sus cambios se repiten y se
confirman entonces frente a ese run: así una [suite de evals](#suites) que
comprueba la misma versión cada día ve la deriva.

### Un baseline en el mismo run { #a-baseline-in-the-same-run }

Cuando una decisión depende del resultado - una puerta de promoción, un cambio
propuesto comprobado con evals, una comparación de modelos -, el baseline se
ejecuta **en el mismo run** (`paired_baseline`, y siempre con
`purpose: "gate"`). Los providers cambian de un día a otro, y una regresión
medida frente a las respuestas de la semana pasada puede ser del provider, no
del agent.

Un brazo de baseline completado sustituye a ejecutar uno nuevo solo cuando
coinciden su versión, la versión del dataset, el modelo, la puntuación y el
juez, y terminó dentro de `EVAL_BASELINE_CACHE_HOURS`. El run dice qué run
reutilizó. Solo se reutilizan sus primeras respuestas: a un caso que cambia se
le vuelve a preguntar en este run.

### Un cambio se confirma antes de contar { #a-flip-is-confirmed-before-it-counts }

Un caso que cambió se repite `EVAL_RERUNS` veces (2 por defecto) cuando ya
están las primeras respuestas. Una regresión está **confirmada** cuando cada
repetición del candidato vuelve a fallar y, con un baseline en el mismo run,
cada repetición del baseline vuelve a aprobar; si no, se informa como **no
confirmada**. Un arreglo se confirma igual. Un baseline en el mismo run - uno
que respondió aquí o cuyas primeras respuestas se reutilizaron - se repite junto
al candidato, así que ambos lados confirman un cambio el mismo día. Un baseline
de un run anterior, comparado cuando nada se ejecutó junto al candidato, no
puede repetirse: frente a él solo confirma el lado del candidato.

Las repeticiones suben el listón en vez de bajarlo: un cambio solo se confirma
cuando se mantiene en cada repetición, así que más repeticiones confirman menos
cambios. Un modelo pequeño o barato que responde a un caso de forma distinta de
un intento a otro deja sus cambios sin confirmar, y el veredicto es
`no_difference` aunque la tasa de aprobados se haya movido: significa que el
modelo es inestable en esos casos, no que nada haya cambiado. Ayudan más casos
en el dataset, un modelo más estable o una `temperature` más baja en sus
[ajustes del modelo](models.md#model-settings), y revisar en la tabla los casos
no confirmados.

La página del run lo dice cuando nada se mantuvo pero tres o más casos cambiaron
una vez, o las dos tasas de aprobados distan 20 puntos o más.

### Qué dice el veredicto { #what-the-verdict-says }

El veredicto se basa solo en los cambios confirmados. Una regresión confirmada
hace al candidato `worse` - un caso que rompe cada vez es razón suficiente para
no publicar -, solo arreglos confirmados lo hacen `better`, ambos lo hacen
`mixed`, y ningún cambio confirmado en absoluto es `no_difference`. Cada cambio
nombra la pregunta del caso.

Por separado, una prueba exacta de McNemar sobre los cambios confirmados da
`overall`: `worse` o `better` cuando distingue los dos lados al nivel
`EVAL_SIGNIFICANCE`, y null cuando hay demasiado pocos cambios, como ocurre en
la mayoría de los datasets pequeños.

La tasa de aprobados cuenta cada caso por la mayoría de sus intentos
decididos - solo su primera respuesta cuando no se repitió, y el veredicto de
una persona sobre esa respuesta por encima de ambos -, así que coincide con los
cambios confirmados. La tasa propia de las primeras respuestas se conserva a su lado
como `first_pass_rate`.

### Otro juez invalida la comparación { #a-different-judge-invalidates-the-comparison }

Cada puntuación registra el [juez que la puso](datasets.md#judge): su modelo, su
versión, una huella de la rúbrica y la versión del propio prompt del juez.
Cuando los dos lados se puntuaron con ajustes de puntuación distintos, o los
calificó otro juez, modelo, rúbrica o prompt, la comparación es `invalid` y no
da veredicto: ahí un cambio dice algo de la calificación, no del agent. Un
baseline calificado con un prompt del juez anterior lo dice, y no se reutiliza
como baseline en caché.

Un run cuyo juez cambió mientras se calificaban sus casos también es `invalid`:
un caso cuyos intentos llevan calificaciones de dos jueces se decide por el que
calificó más de ellos.

### Dos ejes, primero la calidad { #two-axes-quality-first }

El veredicto trata de la calidad. La eficiencia se informa a su lado y nunca se
mezcla con ella: el coste por caso aprobado, los tokens y la latencia son cada
uno `better`, `worse` o `unchanged`, y un cambio dentro de
`EVAL_EFFICIENCY_TOLERANCE` cuenta como sin cambios.

## Comparar modelos { #comparing-models }

Indicar varios `model_profile_ids` ejecuta el candidato una vez por modelo en
el mismo run, cada uno como un brazo propio. Cada brazo muestra su tasa de
aprobados, su coste y su latencia en paralelo. Con un baseline en el mismo run,
el baseline se ejecuta en el primer modelo indicado y cada brazo se compara con
él.

## Suites { #suites }

Una **suite** es un eval run que nadie tiene que acordarse de iniciar. Nombra
el agent, el dataset, el entorno cuya versión comprueba y un umbral que debe
cumplir cada resultado, y se ejecuta sola. La tarjeta **Suites** encabeza la
pestaña Evals de un agent: el dataset de cada suite, cuándo se ejecuta y cómo
le fue la última vez. Al abrir una se listan todos sus resultados, por qué no
pasaron, los casos que se rompieron y un enlace al eval run detrás; la página
de ese run nombra la suite que lo inició.

### Cuándo se ejecuta una suite { #when-a-suite-runs }

Cualquier combinación de:

- **Con un horario** - una expresión cron leída en el reloj de una zona
  horaria, así que `0 6 * * *` en `Europe/Madrid` son las seis en Madrid a
  ambos lados de un cambio de hora. Comprueba la versión que sirve su entorno:
  la versión de producción comprobada cada día detecta cuándo cambia el modelo
  del proveedor o una base de conocimiento por debajo. Una ejecución perdida
  mientras el worker estaba caído se hace una vez.
- **Al publicar** - cada versión nueva, con la versión anterior ejecutada al
  lado en el mismo eval run.
- **Al promocionar** - una versión promocionada al entorno de la suite (el
  predeterminado cuando no nombra ninguno), medida frente a la versión a la que
  sustituyó.
- **Cuando cambia una dependencia** - se edita un skill que enlaza la versión
  comprobada, o se añade, se vuelve a procesar o se borra un documento de una
  base de conocimiento que consulta. Los especialistas que define la versión
  cuentan como la versión. Una ráfaga de cambios es una ejecución, que toca
  `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` después del primero. Un perfil de
  modelo no se puede cambiar en su sitio - apuntar un agent a otro es una
  publicación - y un proveedor que cambia el modelo detrás es lo que detecta el
  horario.
- **Ejecutar ahora** - a mano, como quien lo pulsa.

Una suite que espera comprobar una versión absorbe el siguiente disparador para
esa misma versión, así que una publicación seguida de la promoción de esa
versión es una sola ejecución. Una suite ejecuta un eval run a la vez; un
cambio que llega mientras tanto espera al siguiente. Una suite en pausa no se
ejecuta, ni por un disparador ni a mano.

### Qué debe cumplir un resultado { #what-a-result-must-meet }

Un resultado **no pasa** cuando más casos de los que la suite permite se rompen
de forma reproducible frente al baseline - ninguno por defecto, así que una
regresión confirmada lo suspende - o cuando la tasa de aprobados, cada caso
contado por la mayoría de sus intentos, cae por debajo del mínimo de la suite.
La dirección de la prueba de McNemar se muestra al lado y nunca decide. Dos
límites opcionales comprueban la eficiencia: la subida del coste por caso
aprobado y de la latencia p95 frente al baseline; vacíos, no comprueban nada.

Un resultado cuya comparación es
[no válida](#a-different-judge-invalidates-the-comparison), o en el que no se
pudo puntuar algún caso, queda **sin conclusión** - nunca aprobado - salvo que
algo haya fallado claramente, y nombra los casos que nadie puntuó. Volver a
publicar el juez cambia cómo se puntúan las respuestas, así que el siguiente
resultado de cada suite que puntúa queda una vez sin conclusión, y se avisa a su
propietario. Una tasa de aprobados por debajo del mínimo suspende el resultado
sea cual sea su comparación: el mínimo no necesita baseline.

Un resultado **no se ejecutó** cuando costaría
más de lo que le queda a un presupuesto o más que el límite propio de la
suite, cuando solo el juez podría puntuarlo y la asistencia de IA está
desactivada, o cuando no hay una versión publicada que comprobar.

Las
ejecuciones por horario y por dependencia se comparan con la última ejecución
aprobada de la suite sobre la misma versión - el último estado que se sabe
bueno, así que un caso que se rompió sigue roto hasta que alguien lo arregla -
y así miden la deriva; una publicación o una promoción ejecutan su baseline en
el mismo run. Tras un resultado que no se pudo comparar con esa ejecución, la
siguiente no tiene baseline: se mide por sus propios números y, si aprueba, es
la ejecución con la que se comparan las siguientes.

### Como quién se ejecuta y a quién se avisa { #who-it-runs-as-and-who-is-told }

Una suite se ejecuta como quien la guardó por última vez - su
**propietario** - con la autoridad que tenga cuando empieza el run. Nadie mira
cómo arranca una ejecución programada, así que guardar una suite es aceptar su
gasto, y el formulario muestra antes el precio de una ejecución y de un mes de
horario. Otra persona que cambie la suite pasa a ser su propietaria. Una suite
cuyo propietario deja la organización, o ya no puede ejecutarla, queda en pausa
con el motivo, igual que una cuyo entorno se elimina, ya en pausa o no, en lugar
de comprobar en silencio otra versión. Se reanuda solo cuando alguien vuelve a
elegirle un entorno.

Al propietario se le avisa cuando un resultado no pasa, queda sin conclusión o
no se ejecuta - una vez por serie de esos resultados sobre una versión, con los
casos que se rompieron o quedaron sin puntuar - en el centro de notificaciones y por correo si lo tiene activado.
Slack todavía no es un canal de notificaciones.

## Ajustes { #settings }

| Ajuste | Por defecto | Qué decide |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Casos que un run ejecuta a la vez |
| `EVAL_ORG_CONCURRENCY` | `6` | Casos que una organización ejecuta a la vez, entre todos sus runs |
| `EVAL_RERUNS` | `2` | Repeticiones de un caso que cambió; un run puede pedir de 0 a 5 |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | Qué antigüedad puede tener un baseline coincidente para reutilizarse |
| `EVAL_SIGNIFICANCE` | `0.05` | El nivel por debajo del cual los cambios confirmados son un veredicto |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | Un cambio relativo de coste, tokens o latencia que cuenta como ninguno |
| `EVAL_FALLBACK_INPUT_TOKENS` | `2000` | Los tokens de entrada con los que se calcula el precio de un caso en un modelo sin historial |
| `EVAL_FALLBACK_OUTPUT_TOKENS` | `400` | Los tokens de salida con los que se calcula el precio de un caso en un modelo sin historial |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | La estimación por caso en un modelo sin historial ni precio conocido |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Cuántos runs recientes promedia la estimación |
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | Cuánto puede estar parado un run en marcha, con su worker callado, antes de que el barrido lo dé por fallido |
| `EVAL_HEARTBEAT_SECONDS` | `60` | Cada cuánto avisa un run que trabaja de que sigue vivo |
| `EVAL_QUEUED_ABANDONED_AFTER_HOURS` | `24` | Cuánto puede esperar un run a un worker antes de que el barrido lo dé por fallido |
| `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` | `600` | Cuánto espera una suite tras cambiar un skill o una base de conocimiento, para que una ráfaga de cambios sea una ejecución |

## Acceso { #access }

Iniciar un run requiere `datasets:run` en el dataset y `agents:run` en el
agent, cada uno resuelto con los grants del recurso. Ejecutar el borrador
requiere además `agents:edit` en el agent, porque el borrador es el trabajo en
curso de los editores. El juez, cuando puntúa el dataset, requiere lo que dice
la [puntuación](datasets.md#scoring).

Leer un run requiere `runs:view` y que el lector pueda ver tanto el agent como
el dataset: un run sobre un dataset que el lector no puede abrir no se lista, y
pedirlo por id responde `404`, igual que un run de otra organización. Los runs
de un dataset requieren además `datasets:view` sobre él, y solo listan los
agents que el lector puede ver.

Crear, cambiar, pausar o ejecutar una suite requiere `agents:edit` y
`agents:run` en el agent, `datasets:run` en el dataset y `runs:view`, y una
persona que haya iniciado
sesión como ella misma: una suite gasta como quien la guarda, así que no puede
hacerlo ni una clave de API ni un administrador que actúe en nombre de otro.
Leer las suites de un agent requiere `runs:view` y el agent; las preguntas de
los casos que nombra un resultado solo las ve quien puede abrir el dataset.

## Qué conserva un run { #what-a-run-keeps }

Un resultado contiene la respuesta del agent y los argumentos de cada llamada
que hizo, así que puede contener datos personales del caso que respondió y de
la grabación desde la que se respondió. Se borra con su run, y un run con su
agent o su dataset; borrar la conversación de la que se tomó un caso no borra
los resultados ya producidos a partir de él. [Protección de
datos](data-protection.md) lo enumera junto a los demás almacenes.
