---
source_sha: "a434e301f063"
---

# Pruebas de carga y resiliencia { #load-and-resilience-testing }

AgenticOS transmite, ejecuta trabajo en segundo plano y mantiene sockets
abiertos, y nada de eso dice cuánto de todo ello puede hacer a la vez un
despliegue. El código asíncrono no es un resultado de capacidad, y una suite
unitaria en verde no es una prueba de carga. Por eso hay una suite que lo mide,
en `loadtest/`, y esta página dice qué mide, qué llama aprobado y cómo repetirla.

Los números de una ejecución pertenecen a la máquina en la que corrió. Nada de
esto demuestra el objetivo arquitectónico de mil usuarios de NFA-006, y una sola
ejecución en un host demuestra el objetivo de latencia de NFA-001 solo para ese
host — ambas cosas quedan anotadas donde tocan un umbral en vez de darse por
supuestas en silencio.

## La carga { #the-workload }

El tráfico de un despliegue es sobre todo gente leyendo listas, algunos hablando
con un agent, unos pocos subiendo un documento y un goteo de eventos disparando
rutinas que nadie mira. La mezcla lo dice en números:

| Carga | Cuota | Qué es una petición |
|---|---|---|
| `api_read` | 45% | Una lista autenticada — agents, runs, conversaciones |
| `chat_stream` | 20% | Un turno de chat por WebSocket, uno de cada cinco cancelado a medias |
| `agent_run` | 15% | `POST /agents/{id}/run` — el mismo runner sin socket |
| `rag_query` | 12% | Retrieval: un embedding, una búsqueda vectorial |
| `ingest` | 5% | Un documento subido, que esta API acepta y un worker indexa |
| `trigger_fire` | 3% | Una entrega de webhook firmada que dispara una rutina |

Las cuotas están en `loadtest/scenario.py`, son una línea cada una, y son la parte
con la que discrepar. Un despliegue con otro tráfico las edita y vuelve a medir;
lo que no puede pasar es que se cite un número de una mezcla que nadie miró.

### Tasa de llegada, no un pool de workers { #arrival-rate-not-a-worker-pool }

Las peticiones se ofrecen según un **calendario**. Un bucle cerrado de N workers,
cada uno esperando a su predecesor, reduce su propia tasa de llegada justo cuando
el servidor se ralentiza — así que un servidor que se ha caído informa de
latencias cómodas y de un rendimiento que se ha reducido a la mitad en silencio.
Un modelo de llegada abierto sigue ofreciendo trabajo a la tasa indicada y deja
crecer la cola, que es lo que se está probando.

Qué carga es cada petición viene de una secuencia de baja discrepancia y no de un
dado, así que dos ejecuciones a la misma tasa envían el mismo número de subidas y
cualquier diferencia entre ellas es de la plataforma.

### Las fases { #the-phases }

| Fase | Segundos | Ofrecidas por segundo | Para qué |
|---|---|---|---|
| `ramp` | 60 | 4 | Una caché fría no es régimen permanente |
| `sustain` | 180 | 12 | **Todos los umbrales se juzgan contra esta** |
| `burst` | 45 | 36 | Tres veces la tasa, que es a lo que se parece un fan-out |
| `recover` | 60 | 12 | Una plataforma que se recupera y otra que queda degradada son idénticas durante el burst |

## Qué cuenta como aprobado { #what-counts-as-a-pass }

Estos umbrales están **propuestos, no acordados**. La aceptación de NFA-004 pide
acordados; enunciarlos aquí da a una ejecución un veredicto en lugar de un muro de
números, y hace que la conversación trate de una cifra concreta en vez de tratar
de si debería haber alguna. Nada de esto es un compromiso en nombre de nadie.

| Carga | Métrica | Límite | Por qué ahí |
|---|---|---|---|
| `api_read` | p95 | 300 ms | Una consulta detrás de una comprobación de permisos; por encima es cola, no trabajo |
| `api_read` | tasa de error | 0,1% | Sitio para una conexión reciclada y para nada más |
| `chat_stream` | p95 primer token | 1500 ms | La parte de la plataforma: socket, auth, spec, capacidades, fila de run |
| `chat_stream` | tasa de error | 1% | Un socket caído le cuesta a alguien su respuesta |
| `agent_run` | p95 | 5000 ms | Todo el camino del run contra el stub, de extremo a extremo |
| `rag_query` | p95 | 1200 ms | Lo que acota es pgvector y el pool que hay delante |
| `ingest` | tasa de error | 0% | Una subida aceptada y luego perdida es el peor fallo de esta lista |
| `trigger_fire` | tasa de error | 0% | Un 2xx ya ha asumido la responsabilidad del evento |

Cada uno se juzga por carga a propósito. Un número sobre una ejecución mixta no
describe nada: una subida y una lista no son la misma petición.

Una carga que no produjo muestras se lee como **no medida**, nunca como aprobada.
Una ejecución que se saltó un escenario y dio verde para él es justamente el fallo
que todo este archivo existe para evitar.

## El modelo es un stub, y lento a propósito { #the-model-is-a-stub-and-slow-on-purpose }

`loadtest/stub_model.py` sirve la API de Chat Completions y un endpoint de
embeddings, con un retardo hasta el primer token y un ritmo por token que la
ejecución declara. Una prueba de carga cuyo modelo responde al instante mide una
plataforma bajo una carga que no puede existir: todo proveedor real tarda cientos
de milisegundos, y cuánta concurrencia aguanta un despliegue lo decide cuánto
tiempo un run retiene sus recursos mientras espera.

También se le puede decir que falle — `--error-rate` rechaza esa cuota con un 500 y
`--timeout-rate` las deja abiertas — y esa es la mitad de resiliencia de NFA-004.
Lo que hace la plataforma cuando su proveedor falla es una propiedad de la
plataforma, y no se puede medir contra un proveedor que se porta bien.

Nada en una ejecución por defecto toca un proveedor de pago. Los embeddings también
son del stub, alcanzados como se alcanza un endpoint de Ollama sin clave, así que
un despliegue sin ninguna clave de proveedor sigue siendo medible. Una medición de
extremo a extremo contra un proveedor real es un acto deliberado: apunta ahí el
model profile de la fixture y cuenta con su propia latencia y sus límites de tasa
dentro de los números.

## Ejecutarla { #running-it }

Cuatro cosas tienen que estar en su sitio, y `run.py` se niega a arrancar sin
cualquiera de ellas en vez de medir un despliegue que no puede hacer el trabajo:

1. una base de datos migrada y Redis;
2. el modelo stub respondiendo, **en una dirección que la API alcance** — ver abajo;
3. la fixture — `make load-seed`, una vez;
4. Prefect, si la carga `trigger_fire` va a significar algo. Sin él un webhook se
   acepta y su despacho falla, cosa que el informe muestra como 500 en esa carga en
   lugar de esconderlo.

### Dónde tiene que escuchar el stub { #where-the-stub-has-to-listen }

Es la *API* la que llama al stub, no el driver, así que la dirección sembrada en
el model profile tiene que funcionar desde donde corre la API. Dos topologías:

| La API corre | Bind | Seed |
|---|---|---|
| En este host (`uv run uvicorn …`) | `127.0.0.1` (por defecto) | `http://127.0.0.1:4020` (por defecto) |
| En el stack de Compose (`make dev`) | `LOAD_STUB_BIND=0.0.0.0` | `LOAD_STUB_URL=http://host.docker.internal:4020` |

El loopback dentro del contenedor `app` es el contenedor, no el host, así que allí
la segunda fila no es opcional — y equivocarse hace fallar el preflight con un
mensaje sobre una colección vacía en lugar de sobre una dirección, porque los
embeddings tampoco llegan al stub.

```bash
make load-stub-model                       # terminal uno
make load-seed                             # una vez
make load-test API_PID=$(pgrep -f uvicorn | head -1) \
  DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/agenticos \
  > loadtest/results/$(date +%F)-thismachine.md
```

`API_PID` y `DATABASE_URL` son opcionales. Sin ellos la ejecución mide peticiones y
**nombra en el informe las sondas que no pudo tomar**, en lugar de imprimir ceros
para ellas.

El archivo de fixture no guarda **ninguna credencial**. La ejecución se autentica
por su cuenta con `--email` y `--password` (los valores sembrados), así que ningún
token llega al disco y una fixture sembrada ayer sigue funcionando hoy — un token
que caduca dentro de un archivo era a la vez un secreto en reposo y una ejecución
que se negaba sin motivo.

Vale la pena subir dos ajustes para una ejecución de capacidad, y la línea de
topología del informe debería decir cuándo se hizo:

- **`RATE_LIMIT_RUN_PER_MINUTE`**. El límite es por llamante y el driver es una
  identidad que hace de muchas, así que con los 30 por defecto el experimento mide
  el limitador en vez de la plataforma.
- **`UVICORN_WORKERS`**, si la pregunta es sobre el host y no sobre un worker.

`--scale 0.1` acorta cada fase y no cambia nada más, para comprobar el propio
harness. Acortar una ejecución bajando su *tasa* sería otro experimento con el
mismo nombre.

`--connections` acota los sockets del propio driver y por defecto se deriva del
escenario: la tasa pico por la petición más lenta, 3240 con las fases incluidas.
Un tope por debajo convierte una ejecución de llegada abierta en una cerrada justo
durante el burst, es decir cuando importa: las peticiones se encolan dentro del
cliente y parte de la latencia que informa es del propio driver.

## Leer el informe { #reading-the-report }

Cuatro secciones, en el orden en que se hacen las preguntas: qué se ejecutó, qué
pasó durante `sustain`, qué pasó durante `recover`, y si aprobó. El veredicto va
al final a propósito — un veredicto arriba invita a leer solo eso, y los recuentos
de muestras que hay debajo son los que dicen si una cola es un hallazgo o tres
peticiones.

La cabecera lleva dos números que conviene mirar antes que nada. **Ofrecidas
frente a registradas** tiene que cuadrar: toda petición ofrecida deja una muestra,
con éxito o no, incluida una abandonada al terminar la ejecución, y un déficit
significa que las tasas de error se calculan sobre un denominador menor que la
carga — el informe lo dice en un aviso y se declara inservible. **Envíos tardíos**
es el driver admitiendo que se quedó atrás de su propio calendario y pasó a ser
parte de la medición.

El rendimiento de la fase sostenida se muestra dos veces: las finalizaciones que
cayeron dentro de la ventana y las peticiones ofrecidas durante ella. Divergen
cuando el despliegue va por detrás, que es la única vez que el número interesa.

Los percentiles son de **rango más cercano**, no interpolados: un p99 interpolado
sobre noventa muestras es un número entre dos mediciones que nada observó. Y la
latencia se mide solo sobre las peticiones **con éxito**. Una petición rechazada en
3 ms no es una petición rápida, y dejarla entrar en la distribución es como una
ejecución que se cayó informa de sus mejores percentiles de la historia; los fallos
se cuentan aparte y se nombran.

La CPU es una diferencia del tiempo de CPU acumulado del proceso en cada intervalo
de muestreo, no el `%CPU` de `ps` — procps lo define como tiempo de CPU sobre toda
la vida del proceso y dice abiertamente que no es utilización, así que muestrearlo
promediaría justo la saturación corta que un burst busca provocar. La resolución
es por tanto la del reloj de `ps` sobre el intervalo de muestreo, que en Linux es
un segundo de cada dos.

## Qué no mide esta suite { #what-this-suite-does-not-measure }

Dicho en vez de dejado al descubrimiento:

- **El rendimiento del worker.** Las cargas `ingest` y `trigger_fire` miden la
  *admisión* — la API responde 202 y entrega el trabajo a un flow. Lo rápido que el
  worker vacía esa cola es una medición allí donde está el worker, y aquí no se
  afirma.
- **Nada sobre un proveedor real.** Toda latencia en una ejecución por defecto es la
  de la plataforma más el retardo declarado del stub.
- **La consola.** El frontend no se ejercita; esto son rutas de API.
- **Un clúster.** Un despliegue, una base de datos. El objetivo de NFA-006 es
  arquitectónico y una ejecución en un solo host no dice nada al respecto en ningún
  sentido.

## Las ejecuciones medidas { #the-measured-runs }

Se guardan en `loadtest/results/`, cada una con la máquina, la topología y la fecha
arriba, porque un número sin eso no es un resultado.

Por ahora hay dos ejecuciones, en la misma máquina, con un solo ajuste distinto:

| | `2026-09-16-macbook-default-pool.md` | `2026-09-16-macbook-pool-raised.md` |
|---|---|---|
| Pool | 5 + 10 de overflow (por defecto) | 20 + 30 de overflow |
| Sostenido 12/s | todos los umbrales cumplidos, sin fallos | todos los umbrales cumplidos |
| Ejecución completa, con el burst | **fallaron 1537 de 4740**, 6559 timeouts de pool | fallaron 13, ni un solo timeout de pool |
| **Después del burst** | **66–100% sigue fallando** | **ningún fallo; la latencia drena** |

El hallazgo, y la razón de que haya dos: **la restricción que ata esta carga es el
pool de conexiones, no la CPU.** Ambas ejecuciones llegaron a cerca del 90% de *un*
núcleo en una máquina de diez, porque había un worker. Así que el orden para subir
cosas es el pool y después `UVICORN_WORKERS` — y su producto tiene que quedar por
debajo del `max_connections` de la base de datos, ya que un solo worker llegó a 84
de los 100 por defecto.

La fila de la recuperación es la primera que hay que leer. Con el pool por defecto,
una petición que no consigue conexión espera los treinta segundos completos de
`DB_POOL_TIMEOUT`, así que el atasco sobrevive al burst que lo creó y el despliegue
sigue fallando a un ritmo que diez minutos antes llevaba con holgura. Cada archivo
de resultado lleva todo el razonamiento.
