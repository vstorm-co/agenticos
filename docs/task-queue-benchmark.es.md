---
source_sha: "2d65da37dcb6"
---

# El benchmark de jobs en segundo plano { #the-background-job-benchmark }

Hasta la 1.9.0, cada job en segundo plano de AgenticOS se ejecutaba en Prefect,
que arrancaba un proceso de Python nuevo para cada run. El 18 de octubre de 2026
se acumularon unos 1.650 runs atrasados en un host que ya perdía CPU por steal, y
el sitio se cayó. Antes de sustituir Prefect, pasamos diez motores, en diecisiete
configuraciones, por las mismas cargas, medidas de la misma forma. Esta página
explica qué se midió, qué decidió la elección y qué no muestran los números. El
harness es `experiments/task-queues` en el commit `a239dfdd7` de la rama
`spike/task-queue-benchmark`; allí están también los eventos en bruto de cada
ejecución.

## Qué se comparó { #what-was-compared }

| Variante | Motor | Cómo ejecuta el trabajo |
|---|---|---|
| `prefect-serve` | Prefect 3 `serve`, límite 5; probado también con límite 20 y con la base de datos de Prefect en Postgres | Un proceso de Python nuevo por run: AgenticOS antes de la 1.9.0 |
| `prefect-tasks` | Tareas en segundo plano de Prefect | Un worker de tareas de larga duración |
| `celery-prefork`, `celery-threads` | Celery 5.6 y Beat, sobre Redis | Un pool de procesos o de hilos |
| `taskiq` | Taskiq sobre Redis Streams, con su planificador | Asíncrono, un bucle de eventos por proceso |
| `dramatiq` | Dramatiq sobre Redis | Procesos por hilos |
| `saq` | SAQ sobre Redis | Asíncrono, un bucle de eventos por proceso |
| `procrastinate` | Procrastinate 3.10 sobre Postgres | Asíncrono, un bucle de eventos |
| `pgqueuer` | PgQueuer 1.6.0 sobre Postgres | Asíncrono, un bucle de eventos |
| `dbos`, `dbos-poll100` | DBOS 3.3.0 sobre Postgres; `-poll100` consulta cada 0,1 s en vez de cada segundo | Workflows duraderos |
| `hatchet`, `hatchet-fair` | Hatchet Lite sobre Postgres; `-fair` rota entre organizaciones | Slots asíncronos de worker |
| `pgqueue`, `pgqueue-fair` | Una cola simple en Postgres: `SKIP LOCKED`, `LISTEN/NOTIFY`, leases | Slots asíncronos; `-fair` toma por turnos de cada organización |

Cada proceso de tareas importa primero la aplicación real de AgenticOS. Esa
importación es el coste que Prefect pagaba en cada run, así que un benchmark sin
ella ocultaría justo el coste que se estudia. Los workers tuvieron 3 CPU y 4 GB,
la parte del host de producción para el trabajo en segundo plano. Un servicio que
trae un motor, como el servidor de Prefect o el motor de Hatchet, tuvo sus propios
límites, y su CPU y su memoria cuentan como coste de ese motor.

## Los escenarios { #the-scenarios }

- **`workflow`**: 50 runs de 10 pasos ligeros secuenciales, lanzados a la vez.
  Cada paso hace una ida y vuelta a la base de datos y encola el siguiente. Mide
  el overhead del motor por salto.
- **`mix`**: 5 minutos de llamadas al modelo (2 por segundo, cada una espera de 2
  a 10 s) y de parseo de PDF (uno cada 2 s, cerca de 1 s de CPU cada uno), más el
  sweep programado del propio motor cada minuto. Mide cómo se reparten los workers
  el trabajo que espera y el trabajo de CPU, y lo puntual que es la planificación.
- **`tenants`**: una organización encola 1.000 jobs de golpe y otra envía un job
  por segundo durante 90 s. A los 20 s se matan todos los workers y vuelven a
  arrancar 10 s después. Mide la equidad y lo que cuesta un fallo.
- **`oom`**: un job hace crecer su memoria hasta que el kernel mata a su worker al
  llegar a 1 GB, mientras 210 jobs normales se ejecutan a su lado. Un worker
  muerto vuelve a arrancar a los 3 s, la ejecución se observa durante 240 s y cada
  motor con límite de reintentos tiene 3 intentos.

Cada tarea escribe una fila `started` y otra `finished`, y quien la envía una fila
`enqueued`, en una tabla de Postgres con un único reloj. Las esperas, los huecos
entre pasos y los jobs perdidos y duplicados salen de esas filas. El driver toma
`docker stats` una vez por segundo y lee el contador de WAL de Postgres antes y
después.

## Overhead por paso { #overhead-per-step }

| Variante | Salto p50 | Salto p95 | Pasos por segundo | Pico de memoria de los workers |
|---|---|---|---|---|
| `taskiq` | 0,01 s | 0,02 s | 948 | 184 MB |
| `saq` | 0,01 s | 0,05 s | 818 | 564 MB |
| `dramatiq` | 0,02 s | 0,05 s | 1.338 | 583 MB |
| `pgqueue` | 0,03 s | 0,06 s | 506 | 288 MB |
| `pgqueuer` | 0,03 s | 0,08 s | 609 | 584 MB |
| `procrastinate` | 0,05 s | 0,06 s | 829 | 294 MB |
| `celery-prefork` | 0,05 s | 0,13 s | 485 | 1.294 MB |
| `hatchet` | 0,42 s | 0,82 s | 92 | 642 MB |
| `dbos-poll100` | 0,56 s | 1,11 s | 71 | 601 MB |
| `dbos` | 2,51 s | 3,12 s | 19 | 1.488 MB |
| `prefect-tasks` | 2,60 s | 6,82 s | 11 | 861 MB |
| `prefect-serve` | 218 s | 246 s | 0,2 | 1.736 MB |

`prefect-serve` no terminó: a los 20 minutos llevaba 273 de los 500 pasos. Con el
límite subido a 20 procesos no completó ninguno, porque 20 copias de la aplicación
no cabían en 4 GB. De `dbos-poll100` hacia abajo, cada motor añade al menos medio
segundo a cada paso de un workflow.

## Trabajo que espera junto a trabajo de CPU { #waiting-work-beside-cpu-work }

| Variante | Espera de una llamada al modelo p50 | Espera de una llamada al modelo p95 | Arranque más tardío del sweep |
|---|---|---|---|
| `taskiq` | 0,00 s | 0,01 s | 0,0 s |
| `pgqueue` | 0,01 s | 0,57 s | 0,0 s |
| `pgqueuer` | 0,01 s | 0,41 s | 0,6 s |
| `celery-threads` | 0,01 s | 0,04 s | 0,0 s |
| `hatchet` | 0,01 s | 0,27 s | 1,0 s |
| `procrastinate` | 0,01 s | 0,61 s | 29,4 s |
| `dbos` | 0,60 s | 1,48 s | 3,7 s |
| `prefect-tasks` | 0,10 s | 2,15 s | No se ejecutó ningún sweep |
| `celery-prefork` | 148 s | 279 s | 63,1 s |

Una llamada al modelo pasa casi todo su tiempo esperando, así que un motor que
ocupa un proceso entero por llamada pone las siguientes en cola detrás: con
`celery-prefork` las llamadas esperaron más de dos minutos. Postgres usó entre el
3 y el 6 % de una CPU con `pgqueue`, `pgqueuer` y `dbos`. DBOS escribió 2,3 veces
más WAL que `pgqueue` (4,4 MB frente a 1,9 MB), porque cada uno de sus workflows
son varias filas de estado y de pasos.

## Una avalancha y un fallo { #a-flood-and-a-crash }

| Variante | Perdidos | Duplicados | Espera de la organización pequeña p95 | Parón más largo |
|---|---|---|---|---|
| `pgqueue` | 0 | 0 | 11,1 s | 17,5 s |
| `pgqueuer` | 0 | 0 | 11,0 s | 16,8 s |
| `taskiq` | 0 | 0 | 12,0 s | 17,5 s |
| `procrastinate` | 0 | 0 | 14,0 s | 20,4 s |
| `dbos-poll100` | 0 | 0 | 14,1 s | 18,3 s |
| `hatchet-fair` | 0 | 0 | 18,3 s | 24,0 s |
| `dbos` | 0 | 0 | 64,8 s | 18,8 s |
| `celery-prefork` | 0 | 0 | 50,3 s | 39,5 s |
| `saq` | 0 | 0 | 10,0 s | 551,5 s |
| `pgqueue-fair` | 0 | 137 | 10,1 s | 15,4 s |

Ningún motor de la tabla perdió un job; a `prefect-tasks` le quedaban dos jobs sin
terminar cuando su ejecución agotó el tiempo. La mayoría de los motores ejecutó un
job por segunda vez: el que tenía un worker muerto. Es lo que tiene que hacer
cualquier cola que devuelve el job de un worker muerto. El prototipo
`pgqueue-fair` terminó 137 jobs dos veces. Su toma por turnos no llegó al
producto, y esos duplicados son el motivo. SAQ dejó los jobs de los workers
muertos más de nueve minutos antes de recuperarlos.

## El job que mata a su worker { #the-job-that-kills-its-worker }

Este escenario decidió la elección. En un incidente de producción anterior, en
otro proyecto con Celery, un job que el OOM killer mataba arrancaba una y otra
vez, y su fallo nunca quedó registrado. La nueva cola no podía hacer ninguna de
las dos cosas.

| Variante | Arranques del job en 240 s | Qué pasó | Jobs normales |
|---|---|---|---|
| `pgqueue` | 3 | Marcado como `dead` tras su tercer intento, con el fallo registrado por el sweeper | Todos terminados |
| `dbos` | 3 | `MAX_RECOVERY_ATTEMPTS_EXCEEDED`, registrado por el proceso reiniciado | Todos terminados |
| `procrastinate` | 4 | Arrancó cada minuto; la receta documentada para jobs atascados cuenta intentos pero no limita nada | Todos terminados |
| `taskiq` | 5 | Arrancó cada 60 s; el contenedor nunca murió, porque su gestor de procesos reinicia el hijo, así que desde fuera no se veía nada | Todos terminados |
| `pgqueuer` | 8 | Tomado de nuevo cada vez que caducaba su heartbeat, sin contar un intento; 7 workers muertos | Todos terminados |

DBOS también se detuvo en 3, pero una segunda prueba encontró el otro resultado
prohibido. Cuando un worker murió con tres jobs y volvió como contenedor nuevo,
como ocurre en cada deploy, a los 120 s los tres seguían `PENDING` con el
identificador del executor antiguo. El proceso nuevo no los ve. DBOS Conductor
detecta un executor muerto, pero para el self-hosting comercial tiene una licencia
aparte. Celery no pasó por este escenario. Su documentación describe ambos
fallos: un mensaje vuelve sin límite de entregas, o el job se pierde en silencio.

## Qué llegó al producto { #what-shipped }

La 1.9.0 sustituyó Prefect por la cola simple en Postgres (`pgqueue`) y workers
asyncio de larga duración. Cuenta un intento cuando se toma un job, no cuando
termina. Cada worker ejecuta además un rescuer: cuando uno muere, el
siguiente rescuer - en un worker que sigue vivo o en el mismo tras reiniciarse -
encuentra su lease caducado y registra la muerte, sin importar cómo murió el
worker. Oban, River y Solid Queue siguen la misma regla.

La ingestion se ejecuta además en procesos hijos vigilados por memoria, así que un
documento pesado no tumba a su worker. [Delegar trabajo en segundo plano desde
una petición](architecture.md#dispatching-background-work-from-a-request)
muestra cómo el código encola un job, y [Escalar más allá de un
host](scaling.md#more-workers), cómo añadir workers.

La equidad entre organizaciones queda como se midió. La cola simple dio a la
organización pequeña casi el mismo p95 que el prototipo por turnos (11,1 s frente
a 10,1 s), sin sus duplicados.

## Lo que no dicen los números { #what-the-numbers-do-not-say }

- **Una sola máquina.** Todas las ejecuciones fueron en Docker Desktop sobre Apple
  silicon. En un servidor, los números absolutos cambian. El CPU steal en un host
  compartido ralentiza cada arranque de proceso, lo que solo agranda la diferencia
  en contra de un proceso por run.
- **Una ejecución por celda.** Las diferencias entre motores son lo bastante
  grandes para ordenarlos con una ejecución. Donde dos motores están cerca, como
  `pgqueue` y `pgqueuer` en overhead, las tablas no dicen que uno sea más rápido.
- **Cada motor en su configuración habitual.** Todos los motores tuvieron el mismo
  presupuesto de CPU y memoria, no la misma concurrencia, porque un pool de
  procesos y un bucle de eventos no tienen una unidad común. Otro ajuste puede
  cambiar una cifra, sobre todo en la prueba OOM.
- **Un error del harness, corregido.** La primera ejecución de `tenants` con
  Procrastinate perdió un job, porque el harness llamaba a un método que la 3.10 ya
  no tiene. Fue un error nuestro, no de Procrastinate. La ejecución repetida de la
  tabla terminó los 1.090 jobs.

## Volver a ejecutarlo { #run-it-again }

```bash
# Desde la raíz del repositorio, en el commit medido.
git switch --detach a239dfdd7
docker build -f backend/Dockerfile -t agenticos-backend:bench-base .
cd experiments/task-queues
docker build -t tqbench:latest .
./run.sh pgqueue oom          # una variante, un escenario, en un proyecto nuevo
./matrix.sh                   # todas las celdas; unas horas
python3 -m bench.report results > results/TABLES.md
```

Las [pruebas de carga](load-testing.md) responden a otra pregunta: cuánto puede
atender un despliegue de AgenticOS, no qué motor debería ejecutar sus jobs.
