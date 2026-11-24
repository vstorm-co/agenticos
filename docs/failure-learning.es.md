---
source_sha: "d80cae6dae16"
---

# Aprender de los errores { #failure-learning }

Un agente que sigue fallando igual no está aprendiendo — está repitiendo.
El bucle de aprendizaje de errores extrae los fallos repetidos de las
ejecuciones que tus agentes ya hicieron, los organiza en un registro y
prueba una corrección contra el comportamiento anterior antes de aplicar
nada.

La fase 1 cubre la minería, el registro, los casos de evaluación y los
intentos. La fase 2 añade propuestas y la aplicación de una corrección: una
propuesta guarda un cambio de texto de regla con su evidencia de evaluación,
y un publicador la aplica en una sola acción auditada. La fase 3 añade las
páginas de la consola, el resumen diario y los recuentos de reglas por agente.

## Qué extrae { #what-it-mines }

La minería es SQL en vivo sobre `agent_runs` y `message_ratings` — sin ETL
ni trabajo en segundo plano. Mira siete días atrás por defecto y detecta
cuatro señales:

| Señal | Qué cuenta | Umbral |
|---|---|---|
| Ejecuciones fallidas | Ejecuciones de nivel superior, no de prueba, agrupadas por agente, modelo, estado y clase de error | 3 por agente |
| Un fallo que sigue a un modelo | La misma clase de error para un modelo en varios agentes | 5 entre agentes |
| Ejecuciones atascadas | Una ejecución todavía `running` cuyo latido tiene más de 10 minutos | 1 |
| Respuestas con voto negativo | Respuestas del asistente valoradas con −1 | 3 |

La clase de error de una ejecución fallida se deduce de la frase que
registró la ejecución: `ModelHTTPError` conserva su código de estado, una
aprobación o pregunta caducada es su propia clase, un límite de uso es su
propia clase, y las paradas por bucle y por presupuesto también son clases.
Todo lo demás es `other`.

Conviene conocer dos límites. Una ejecución atascada en una llamada al
modelo sigue enviando latidos, así que un bloqueo con el latido al día
**no es detectable** — atascado solo significa que el latido está obsoleto.
Y una respuesta con voto negativo se atribuye a la ejecución más cercana
iniciada antes en la misma conversación; un mensaje sin ejecución anterior
no tiene atribución y se descarta.

## El registro { #the-ledger }

Un patrón que merece actuar se convierte en una entrada del registro: un
título, un resumen, la evidencia y un estado — `draft`, `open`, `dismissed`
o `resolved`. Una entrada está abierta mientras sea `draft` u `open`, y
solo puede existir una entrada abierta por patrón y ámbito. Lo impone un
índice único parcial, no una convención.

Las entradas tienen ámbito de agente o de modelo. Una entrada de modelo es
un registro para toda la organización y aparece junto a las entradas de
cada agente. Un patrón con una entrada abierta se marca como
`already_tracked` al extraer, para que el mismo fallo no se organice dos
veces.

Resolver una entrada es trabajo de aplicar la corrección: un simple cambio
de estado a `resolved` se rechaza, y solo aplicar una propuesta contra la
entrada la resuelve.

## Casos de evaluación { #eval-cases }

Un caso de evaluación es la prueba que una corrección debe pasar: una
entrada y lo que su respuesta debería decir. Un agente tiene como máximo 50
casos. Un caso nombra una expectativa — `equals`, `contains` o
`not_contains` sobre el texto de la respuesta o el estado de la ejecución —
y puede nombrar la entrada del registro de la que procede, una ejecución de
origen que mostró el fallo y un perfil de modelo bajo el que probarlo.

## Probar una corrección { #trying-a-fix }

Un intento ejecuta cada caso dos veces por muestra: una con la
especificación publicada actual (el lado antiguo) y otra con la misma
especificación y las instrucciones sustituidas (el lado nuevo). Cada
ejecución abre una conversación de prueba nueva, corre como ejecución de
prueba y queda excluida de la minería por el filtro `is_test`. Las muestras
son 1 por defecto y 5 como máximo.

La puerta es estricta. Un lado pasa solo cuando su ejecución se completó
**y** la expectativa se cumple — una ejecución que falló no puede pasar por
fallar. Un caso pasa solo cuando el lado antiguo falla y el lado nuevo pasa,
por mayoría de muestras cuando hay más de una. Un intento pasa solo cuando
pasan todos los casos. Cuando el lado antiguo ya pasa, el caso se informa
como no reproducible: «case does not reproduce - the old text already
passes».

Los veredictos se juzgan al leer el intento, nunca se guardan. Una
ejecución que sigue en curso deja su caso pendiente.

Un intento puede nombrar una propuesta en borrador en lugar de una
sustitución de instrucciones: ejecuta sus instrucciones nuevas o el contenido
del skill y sirve como evidencia de esa propuesta exacta. Registra el id de la
propuesta y el SHA-256 del contenido probado. La aplicación se rechaza si el
intento aprobado vinculado no corresponde a esa propuesta y a ese hash.

Un intento se ejecuta de forma síncrona dentro de la petición y tiene un
límite de diez runs del agente (dos lados por caso y muestra). Cada run puede
hacer varias peticiones al provider, por lo que no es un límite de peticiones
al provider. Las solicitudes mayores se rechazan antes de iniciar los runs.
La ejecución en segundo plano queda como trabajo futuro independiente.

## Propuestas { #proposals }

Una propuesta es un cambio de texto de regla: el texto que sustituye, el
texto que lo sustituye, por qué, y el intento de evaluación que la evidencia.
Nombra su objetivo — las instrucciones del agente o un skill — y la entrada
del registro de la que procede, si la hay. Una propuesta es `draft` hasta
que se aplica o se rechaza; aplicar es la aprobación, y no hay un paso de
aprobación separado.

Una propuesta de instrucciones se escribe contra la versión publicada
actual del agente, salvo que el cuerpo nombre una. Una propuesta de skill se
escribe contra el contenido del skill tal como está, y registra su hash
SHA-256 como base. La lista de cambios aplicados es la lista de propuestas
filtrada a `status=applied`: cada entrada lleva la versión que publicó y el
intento que la evidenció.

Las propuestas de skill también requieren un intento de evaluación
aprobado. El contenido propuesto se ejecuta como una sustitución en memoria
en el lado de prueba; el skill guardado no cambia.

## Aplicar una propuesta { #applying-a-proposal }

Aplicar es un acto humano de un publicador, en la transacción de la
petición, y queda auditado. Para un objetivo de instrucciones, la aplicación
se niega salvo que el intento vinculado exista y haya pasado la puerta,
juzgado tal como están sus ejecuciones en ese momento — un intento que falta,
sigue pendiente o ha fallado no puede aplicarse. Esa es la puerta,
comprobada al aplicar en lugar de guardada.

Dos guardas protegen la publicación. La concurrencia optimista se niega con
409 salvo que la versión actual del agente siga siendo la versión contra la
que se escribió la propuesta — alguien publicó desde entonces, así que quien
propuso vuelve a basar la propuesta en lugar de sobrescribir una publicación
más reciente. La guarda del borrador se niega con 409 si el agente tiene
ediciones de borrador sin publicar — el trabajo en curso de un constructor
debe publicarse o descartarse primero, porque la aplicación guarda por
encima del borrador.

Pasadas las guardas, la aplicación carga la especificación del borrador,
pone sus instrucciones en el texto nuevo de la propuesta, guarda el borrador
y lo publica, anotando el id de la propuesta. La versión publicada es el
texto nuevo congelado, y la propuesta la registra como asa de reversión. La
entrada del registro vinculada, si la hay, se marca resuelta, y la entrada
de auditoría registra la propuesta, la versión, el intento y la versión
base.

Aplicar un skill requiere que el intento vinculado haya pasado y registra el
hash exacto del contenido nuevo. Devuelve 409 si el skill actual ya no coincide
con el hash base de la propuesta. Antes de editarlo, guarda el contenido anterior
en la propuesta. El endpoint de reversión, disponible una vez, restaura esa copia
solo si el skill aún coincide con el hash aplicado; registra quién lo revirtió
y una entrada de auditoría, y nunca sobrescribe cambios posteriores.

Deshacer una aplicación de instrucciones es la reversión existente:
publica una versión nueva copiada de la versión base que registró la
propuesta. No hay un endpoint especial del bucle para ello. Un rechazo se
registra en el rastro de auditoría con su motivo — la propia fila de la
propuesta no lleva nota de decisión.

## La consola { #the-console }

El bucle vive en la consola, en la página del agente y en una página para
toda la organización. La página del agente lleva una pestaña Aprender de
los errores; la página de la organización lista los patrones de todos los
agentes en un solo lugar, en la navegación bajo Monitorización. Leer
necesita `agents:view`; curar necesita `agents:edit`, aplicar una
propuesta de instrucciones necesita `agents:publish`, y aplicar una
propuesta de skill necesita `skills:edit` en ese skill.

### Patrones { #patterns }

El panel de patrones lista lo que extrajo la minería de los últimos
siete días, con el recuento y si el patrón ya está en seguimiento. Las
advertencias de la minería se muestran junto a los números, no ocultas:
los patrones por modelo son aproximados, un bloqueo con un latido fresco
no es detectable, y una respuesta con mala valoración solo se atribuye
aproximadamente. Seguir un patrón desde el panel abre el formulario del
registro con el patrón ya rellenado.

### Entradas del registro { #ledger-entries }

El registro lista entradas con un filtro de estado, y al seleccionar una
se ven sus casos de evaluación y sus propuestas. Aceptar un borrador lo
abre; descartarlo pide un motivo, y el motivo queda en la entrada para
que el registro sobreviva. Eliminar una entrada la quita — sus casos de
evaluación conservan lo que decían, y registran la entrada como
eliminada.

### Casos de evaluación e intentos { #eval-cases-and-tries }

El panel de casos lista cada caso con el veredicto de su último intento.
Un caso se crea a partir de la ejecución que mostró el fallo: da el id
de la ejecución origen y carga su último mensaje de usuario, con los
turnos anteriores como historial, luego recorta el mensaje hasta la
parte que falla y escribe lo que debería decir la respuesta.

Un intento corre sobre los casos marcados, con un número de muestras y o
bien el texto nuevo de una propuesta en borrador o bien una sustitución
escrita — nunca ambos. Las solicitudes de más de diez runs del agente se
rechazan antes de ejecutarse. Un intento que pasa
la puerta ofrece su texto como propuesta, prerrellenada con el intento
como su evidencia.

### Revisión de propuestas { #proposal-review }

Seleccionar una propuesta muestra el cambio como una diferencia, la
evidencia de evaluación con sus veredictos de puerta por caso, y las
acciones de aplicar y rechazar. Una propuesta de instrucciones se aplica
solo cuando su intento ha pasado la puerta, y solo quien tiene
`agents:publish` ve el control de aplicar. Una propuesta de skill
también necesita un intento aprobado para su contenido exacto. Su reversión
restaura el contenido anterior guardado si nadie cambió el skill desde que
se aplicó. Una propuesta aplicada registra la versión que publicó y la
indicación para deshacerla: volver a la versión base guardada.

### Cuántas reglas están vivas { #how-many-rules-are-live }

La parte superior de la pestaña cuenta las reglas que el bucle ha puesto
en este agente: propuestas aplicadas, entradas abiertas y entradas
resueltas, como tres cifras separadas. Las propuestas aplicadas son las
reglas vivas ahora en las instrucciones. Las entradas abiertas son las
reglas en las que aún se trabaja — una entrada está abierta mientras es
borrador o está abierta. Una entrada resuelta es su propuesta aplicada,
así que las dos se cuentan por separado, nunca se suman: sumarlas
contaría una regla dos veces.

Ese recuento es una invitación, no un veredicto. Las reglas se acumulan
— cada propuesta aplicada es una frase que el agente debe respetar junto
a todas las demás — así que revisa las reglas vivas una vez al trimestre:
lee la lista de cambios aplicados, y retira las que el agente ya no
necesita editando las instrucciones, en lugar de dejarlas para que se
vuelvan a aprender.

## El resumen diario { #the-daily-digest }

Una vez al día, un trabajo programado — `failure-ledger-digest` — extrae
los últimos siete días para cada organización y guarda cada patrón nuevo
como una entrada en borrador en el registro, luego envía un resumen por
organización que tenga algo nuevo al destinatario configurado del
despliegue. Una organización sin nada nuevo no recibe correo. Las
entradas son borradores, nunca abiertas: un borrador es un patrón que
encontró la minería, no uno que aceptó un curador.

El destinatario es configuración, no un valor por defecto. Configura
`FAILURE_LEARNING_DIGEST_RECIPIENT` con la dirección a la que van los
resúmenes; mientras esté vacía el trabajo registra un no-op y no crea
entradas en borrador ni envía correo. Es una sola dirección para
todo el despliegue, así que ve el resumen de cada organización: haz que
sea una dirección de operador, no de un miembro. Véase
[la referencia de ajustes](configuration.md#email-smtp).

## Permisos { #permissions }

| Ruta | Permiso |
|---|---|
| `GET /v1/failure-learning/patterns` | `runs:view` |
| Lecturas de patrones, registro y evaluación por agente | `agents:view` |
| Escrituras de registro, casos e intentos por agente | `agents:edit` |
| Proponer un cambio, rechazar una propuesta | `agents:edit` (instrucciones) / `skills:edit` (objetivo de skill) |
| Aplicar una propuesta de instrucciones | `agents:publish` |
| Aplicar una propuesta de skill | `skills:edit` sobre el skill |

Solo la lista de patrones de toda la organización lleva una puerta en la
ruta. Las rutas por agente resuelven el acceso al agente dentro del
servicio, y un rechazo se lee como no encontrado — así, un observador con
una concesión explícita sobre un agente no es rechazado antes de consultar
la concesión.

## API { #api }

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/v1/failure-learning/patterns` | Patrones de toda la organización |
| `GET` | `/v1/agents/{agent_id}/failure-learning/patterns` | Patrones de un agente |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger` | Listar entradas del registro |
| `POST` | `/v1/agents/{agent_id}/failure-learning/ledger` | Organizar un patrón |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Una entrada |
| `PATCH` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Aceptar, descartar, reescribir |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Eliminar una entrada |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Listar casos de evaluación |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Añadir un caso |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/eval-cases/{case_id}` | Eliminar un caso |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-runs` | Iniciar un intento |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-runs/{try_id}` | Leer un intento, juzgado tal como está |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals` | Proponer un cambio |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals` | Listar propuestas; `status=applied` es la lista de cambios aplicados |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}` | Una propuesta, con su evidencia de evaluación |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/apply` | Aplicar una propuesta, auditado |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/reject` | Rechazar una propuesta, con un motivo |

Iniciar un intento está limitado en la superficie `agent_eval_run`, y cada
ejecución de un lado cuenta contra el presupuesto de quien llama como
cualquier ejecución. Un intento que nombra una `proposal_id` ejecuta el
texto nuevo de esa propuesta; nombrar a la vez una propuesta y una
sustitución se rechaza.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Por qué un fallo que puedo ver no aparece como patrón? { #why-does-a-failure-i-can-see-not-appear-as-a-pattern }

Está por debajo de un umbral, fuera de la ventana de siete días, es una
ejecución de prueba o una ejecución delegada. Las delegaciones se cuentan
dentro de su ejecución padre, y las ejecuciones de prueba son los propios
intentos del bucle — extraer cualquiera de las dos sería aprender de sí
mismo.

### ¿Por qué tardó tanto mi intento? { #why-did-my-try-take-so-long }

Los intentos son síncronos: cada caso se ejecuta dos veces por muestra, un
run del agente tras otro, dentro de la petición. Un intento puede iniciar
como máximo diez runs; cada run puede hacer varias peticiones al provider.

### ¿Puede un intento cambiar lo que dice mi agente? { #can-a-try-change-what-my-agent-says }

No. Ambos lados corren como ejecuciones de prueba contra una copia
congelada de la especificación. El agente publicado queda intacto hasta que
se aplica una propuesta.

### ¿Qué pasa si el agente se publicó de nuevo desde que propuse? { #what-if-the-agent-was-republished-since-i-proposed }

La aplicación se niega con 409. Vuelve a basar la propuesta en la versión
nueva — en lo que el agente publica ahora — en lugar de sobrescribir la
publicación más reciente.

### ¿Cómo deshago una aplicación? { #how-do-i-undo-an-apply }

Vuelve a la versión base guardada en la propuesta: la reversión existente
publica una versión nueva copiada de ella, por lo que la cronología muestra
que ocurrió. Una aplicación de skill se puede revertir una vez desde su copia
guardada si el skill todavía tiene el contenido aplicado.

### ¿Qué pasa cuando aplico un cambio de skill? { #what-happens-when-i-apply-a-skill-change }

Cada agente vinculado al skill ejecuta el contenido nuevo en su próxima
ejecución. La propuesta requiere un intento aprobado para ese contenido
exacto y se puede revertir una vez si nadie cambió el skill desde entonces.

### ¿Dónde veo los patrones nuevos cada día? { #where-do-i-see-the-new-patterns-each-day }

En tu bandeja de entrada, si el despliegue configuró un destinatario para el
resumen — un correo por organización con algo nuevo. Si no hay destinatario o
novedades, se registra que no se hizo nada. También aparecen en la página de
patrones de la organización, que reúne los de todos los agentes.
