---
source_sha: "eb529dfb0b4c"
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

Un agent sin historial en un modelo se estima en `EVAL_FALLBACK_CASE_COST_USD`
por caso, y la estimación dice que es una suposición (`basis: "fallback"`). El
coste del baseline forma parte del total, salvo que se reutilice un baseline
reciente que coincida; en ese caso no cuesta nada y la estimación nombra el run
que reutiliza.

### El budget que deja { #the-budget-it-leaves }

Un eval gasta de los mismos budgets mensuales que el tráfico real: el límite
del agent y el de la organización. No hay un budget aparte para evals. Un
dataset grande puede por tanto dejar la producción sin budget el resto del mes,
así que la estimación muestra lo que conserva cada límite una vez que el run ha
gastado su total: `agent_after_usd` y `org_after_usd`.

Iniciarlo se rechaza con `402` antes de escribir nada cuando el total supera lo
que le queda a cualquiera de los dos límites. Las repeticiones de confirmación
(más abajo) no entran en esa comprobación, porque solo afectan a los casos que
cambian; la estimación muestra lo máximo que pueden añadir como
`rerun_ceiling_usd`. Cada caso se sigue comprobando contra ambos límites antes
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
contra los budgets antes de cada petición al modelo, se registra su coste y
aparece en Activity, donde el filtro de superficie lo separa del tráfico de
producción. Se ejecuta como la persona que inició el eval, con su rol actual, y
no lee ni escribe su memoria personal.

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
| Calidad | Tasa de aprobados entre los casos decididos, y cuántos no pudieron decidirse |
| Eficiencia | Coste por caso aprobado, tokens por caso y latencia en p50 y p95 |

Un caso cuyo evaluador obligatorio no pudo ejecutarse queda **sin decidir**,
nunca aprobado. El veredicto de una persona en la
[cola de revisión](datasets.md#review) sustituye el resultado de los
evaluadores para ese caso, y las cifras del run lo siguen.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary
GET /api/v1/eval-runs/{id}/cases             cases and every attempt; ?outcome=, ?tag=, ?arm_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
```

## Comparar con un baseline { #comparing-with-a-baseline }

Una comparación empareja los dos lados caso por caso según el id estable del
caso, e informa de cada caso como **regresión** (aprobaba, ahora no),
**arreglado** (no aprobaba, ahora sí), sin cambios o incompleto. Los casos que
solo respondió un lado cuentan como no comparados.

**El baseline por defecto es barato**: el último run completado del mismo
dataset en la versión anterior al candidato - la versión publicada, para un
borrador. Ambos lados llevan su fecha, su modelo y su versión del dataset,
porque pueden diferir en cualquiera de ellos.

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
reutilizó.

### Un cambio se confirma antes de contar { #a-flip-is-confirmed-before-it-counts }

Un caso que cambió se repite `EVAL_RERUNS` veces (2 por defecto) cuando ya
están las primeras respuestas. Una regresión está **confirmada** cuando cada
repetición del candidato vuelve a fallar y, con un baseline en el mismo run,
cada repetición del baseline vuelve a aprobar; si no, se informa como **no
confirmada**. Un arreglo se confirma de la misma manera. Un baseline pasado no
puede repetirse, así que frente a él solo confirma el lado del candidato.

### Pocos cambios no son un veredicto { #too-few-flips-are-not-a-verdict }

El veredicto se basa solo en los cambios confirmados, probados con una prueba
exacta de McNemar. Cuando la prueba no distingue los dos lados al nivel
`EVAL_SIGNIFICANCE`, el veredicto es `inconclusive` - la diferencia está dentro
del ruido o la muestra es demasiado pequeña - en lugar de mejor o peor. No hay
un número mínimo de casos; un dataset pequeño simplemente da `inconclusive` más
a menudo. Sin ningún cambio confirmado, el veredicto es `no_difference`.

### Otro juez invalida la comparación { #a-different-judge-invalidates-the-comparison }

Cada puntuación registra el [juez que la puso](datasets.md#judge): su modelo, su
versión y una huella de la rúbrica. Cuando los dos lados se puntuaron con
ajustes de puntuación distintos, o los calificó otro juez, modelo o rúbrica, la
comparación es `invalid` y no da veredicto: ahí un cambio dice algo de la
calificación, no del agent.

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

## Ajustes { #settings }

| Ajuste | Por defecto | Qué decide |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Casos que un run ejecuta a la vez |
| `EVAL_ORG_CONCURRENCY` | `6` | Casos que una organización ejecuta a la vez, entre todos sus runs |
| `EVAL_RERUNS` | `2` | Repeticiones de un caso que cambió; un run puede pedir de 0 a 5 |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | Qué antigüedad puede tener un baseline coincidente para reutilizarse |
| `EVAL_SIGNIFICANCE` | `0.05` | El nivel por debajo del cual los cambios confirmados son un veredicto |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | Un cambio relativo de coste, tokens o latencia que cuenta como ninguno |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | La estimación por caso en un modelo sin historial |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Cuántos runs recientes promedia la estimación |
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | Cuánto puede estar parado un run en marcha, con su worker callado, antes de que el barrido lo dé por fallido |
| `EVAL_HEARTBEAT_SECONDS` | `60` | Cada cuánto avisa un run que trabaja de que sigue vivo |
| `EVAL_QUEUED_ABANDONED_AFTER_HOURS` | `24` | Cuánto puede esperar un run a un worker antes de que el barrido lo dé por fallido |

## Acceso { #access }

Iniciar un run requiere `datasets:run` en el dataset y `agents:run` en el
agent, cada uno resuelto con los grants del recurso. Ejecutar el borrador
requiere además `agents:edit` en el agent, porque el borrador es el trabajo en
curso de los editores. El juez, cuando puntúa el dataset, requiere lo que dice
la [puntuación](datasets.md#scoring).

Leer un run requiere `runs:view` y que el lector pueda ver tanto el agent como
el dataset: un run sobre un dataset que el lector no puede abrir no se lista, y
pedirlo por id responde `404`, igual que un run de otra organización.

## Qué conserva un run { #what-a-run-keeps }

Un resultado contiene la respuesta del agent y los argumentos de cada llamada
que hizo, así que puede contener datos personales del caso que respondió y de
la grabación desde la que se respondió. Se borra con su run, y un run con su
agent o su dataset; borrar la conversación de la que se tomó un caso no borra
los resultados ya producidos a partir de él. [Protección de
datos](data-protection.md) lo enumera junto a los demás almacenes.
