---
source_sha: d4f249f20433
---

# Modelos y providers { #models-and-providers }

!!! tip "¿Decidir en vez de configurar?"

    Esta página es la maquinaria. [Elegir un modelo](choosing-models.md) responde
    a *qué* modelo debería usar un agent — pesos abiertos o cerrados, qué es lo
    que de verdad dispara la factura, y por qué la elección es reversible.

La plantilla de la que creció esta plataforma construía un modelo a partir de
variables de entorno.

Eso deja de funcionar en cuanto varias organizaciones comparten un despliegue:
cada una necesita su propia clave, su propio valor por defecto y poder rotar
cualquiera de los dos sin volver a desplegar.

Así que un modelo se construye **por run**, a partir de la base de datos:

```
model profile → credential → unsealed secret → provider client → Model
```

Nada sobre qué modelo usa un agent vive en `.env`.

## Un perfil de modelo { #a-model-profile }

Una fila dentro de una organización: una etiqueta, un provider, un id de modelo,
ajustes por defecto y con qué [secreto del vault](secrets.md) autenticarse.

El spec de un agent nombra uno con `model_profile_id`, y el run lo resuelve.

!!! tip "El id de modelo es texto libre a propósito"

    Hay un selector que ayuda, pero el campo acepta cualquier cosa que escribas.

    Un provider publica algo la mañana siguiente a que se calentara cualquier
    lista de aquí, y un campo que no puede expresar «ese» es un campo que la
    gente esquiva editando el spec a mano.

### Fallbacks { #fallbacks }

Un perfil puede listar perfiles de fallback, probados en orden. La caída de un
provider no debería tumbar los agents de una organización cuando esta tiene una
segunda clave o un segundo provider configurados.

!!! warning "Un fallback es invisible en el registro del run"

    La fila del run se escribe antes de la primera petición, y lleva la etiqueta,
    el provider y el id de secreto del perfil **primario**. Si un fallback
    atendió el turno, el run sigue nombrando al primario.

    Así que «cuánto gastamos en OpenAI» y «qué clave está costando más» responden
    con el perfil al que se *preguntó* primero, no con el que respondió. Conviene
    saberlo antes de fiarte de esos números durante una caída.

### Ajustes del modelo { #model-settings }

Por perfil, y sobrescribibles por agent a través de `model_settings` del spec:
`temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `timeout`. Ver
[la referencia del spec](reference/spec.md#model-settings).

El esfuerzo de razonamiento **no** está aquí. Es
[la capability `thinking`](reference/capabilities.md#thinking), porque «razona
más» es una decisión sobre para qué *sirve* el agent y no un mando de una
conexión — y porque un spec que lo fija como ajuste del modelo deja de ser
portable al cambiar de modelo.

## Providers { #providers }

Veintisiete, que es todo lo que trae Pydantic AI a lo que un perfil de chat puede
apuntar.

Aquí no hay un constructor por provider. Pydantic AI infiere la clase del
provider y el envoltorio del modelo a partir del id, y lo que esta plataforma
sigue teniendo que saber es la parte que la inferencia no puede: **qué forma de
credencial quiere un provider.**

!!! info "Qué significa Custom URL"

    El SDK del provider nombra un parámetro de endpoint, así que puedes apuntar
    un perfil a un gateway, a un proxy de LiteLLM o a un servidor de modelos en
    tu propia red en vez de a la API pública del proveedor.

    Es un campo del **perfil**, no de la clave. Una clave dice qué autentica, un
    endpoint dice adónde va la petición — así que la misma clave puede estar
    delante de un proxy de staging y de uno de producción como dos perfiles.

    Configúralo en **Agents → add a model → Endpoint**, que aparece solo para los
    providers marcados abajo. Guardar uno para un provider que no tiene ninguno
    se rechaza, en vez de aceptarse y descartarse.

### Alojados { #hosted }

| Provider | id | Credencial | Custom URL |
|---|---|---|---|
| OpenAI | `openai` | clave de API, o ninguna | ✓ |
| Anthropic | `anthropic` | clave de API | ✓ |
| Google Gemini | `google` | clave de API | ✓ |
| OpenRouter | `openrouter` | clave de API | |
| Alibaba Cloud | `alibaba` | clave de API | ✓ |
| Cerebras | `cerebras` | clave de API | |
| DeepSeek | `deepseek` | clave de API | |
| Fireworks AI | `fireworks` | clave de API | |
| GitHub Models | `github` | clave de API | |
| Groq | `groq` | clave de API | |
| Heroku AI | `heroku` | clave de API | ✓ |
| Mistral | `mistral` | clave de API | |
| Moonshot AI | `moonshotai` | clave de API | |
| Nebius AI Studio | `nebius` | clave de API | |
| OVHcloud AI Endpoints | `ovhcloud` | clave de API | |
| SambaNova | `sambanova` | clave de API | ✓ |
| Together AI | `together` | clave de API | |
| Vercel AI Gateway | `vercel` | clave de API | |
| Z.AI | `zai` | clave de API | |
| xAI (Grok) | `xai` | clave de API | ✓ (`api_host`) |
| Cohere | `cohere` | clave de API | |
| Hugging Face | `huggingface` | clave de API | ✓ |

### Autoalojados { #self-hosted }

| Provider | id | Credencial | Custom URL |
|---|---|---|---|
| Ollama | `ollama` | ninguna | ✓ |
| LiteLLM proxy | `litellm` | ninguna | ✓ (`api_base`) |

Estos dos son la razón de que «sin credencial» sea un **kind** almacenado y no
una cadena vacía. Un servidor de modelos en tu propia red no suele tener nada
contra lo que autenticarse, y el vault rechaza un secreto vacío — así que el
resolver decide sobre un conjunto completo en vez de tratar un valor ausente como
un caso especial.

**Un perfil sin clave necesita su endpoint, y eso es lo único que necesita.** El
campo de la clave pasa a ser opcional en cuanto se rellena uno. Sin endpoint el
perfil se rechaza: no hay una API pública a la que recurrir ni nada con lo que
autenticarse.

!!! note "Lo que marca un perfil como autoalojado es el endpoint, no `keyless`"

    `keyless` también es cierto de `openai`. Los servidores compatibles con
    OpenAI (vLLM, LM Studio, un proxy de LiteLLM) hablan su API de Chat
    Completions, que es por lo que un perfil `openai` se construye como
    `openai-chat`.

    Así que «sin clave» por sí solo no distingue un modelo local deliberado de un
    perfil al que le borraron la clave — y la clave ajena del secreto es
    `ON DELETE SET NULL`, lo que hace que el segundo caso sea corriente. Un run
    resuelve un perfil sin clave solo cuando este lleva un endpoint; si no, se
    rechaza con el mismo mensaje de «no key configured» que ha tenido siempre.

### Cuando la credencial no es una clave de API { #when-the-credential-is-not-an-api-key }

| Provider | id | Credencial |
|---|---|---|
| Azure OpenAI | `azure` | clave **+** endpoint **+** versión de API fijada |
| AWS Bedrock | `bedrock` | id de clave de acceso, clave secreta, región, token de sesión opcional |
| Google Vertex AI | `google_cloud` | JSON de la cuenta de servicio |

Estos tres son la razón de que un secreto tenga un *kind*. Un formulario que
recogiera un único token opaco para Azure recogería algo que se puede rellenar
correctamente y que aun así falla en el primer run. Ver
[los kinds de secreto](secrets.md#kinds).

!!! note "Dos ids se reescriben de camino al SDK"

    Un perfil `openai` se construye como `openai-chat`, porque `openai` a secas
    infiere la Responses API y los servidores compatibles con OpenAI — vLLM, LM
    Studio, un proxy de LiteLLM — no la implementan.

    `google_cloud` se construye como `google-cloud`. Ninguno de los dos cambia lo
    que guardas.

### Ausentes a propósito { #deliberately-absent }

Cuatro nombres que Pydantic AI conoce no están aquí. `sentence-transformers` y
`voyageai` son modelos de embeddings, `bedrock-mantle` no es un provider de chat
al que un perfil pueda apuntar, y `gateway` no resuelve a una clase de provider —
es un prefijo de enrutado sobre los demás.

`tests/test_model_profiles.py` construye cada entrada del catálogo, así que un
provider no puede ser seleccionable en el Builder sin ser construible en tiempo
de ejecución.

## Qué lista responde a qué pregunta { #which-list-answers-which-question }

Seis cosas de este repositorio saben algo sobre modelos y providers, y **no** son
seis copias de una misma lista. Cada una responde a una pregunta distinta, y
aquella de la que se derivan todas es la primera:

| Pregunta | Respondida por |
|---|---|
| ¿A qué providers puede apuntar un perfil, y qué credencial quiere cada uno? | `PROVIDERS` en `backend/app/agents/model_resolver.py` — **la fuente de verdad**, y solo para la parte que la inferencia del modelo no puede saber |
| ¿Cómo construyo el cliente? | El propio `infer_provider_class` / `infer_model` de `pydantic_ai`. No es asunto de esta plataforma, y deliberadamente no se repite aquí |
| ¿Cómo leo la lista de modelos en vivo de este provider? | `backend/app/core/catalog/model_listings.json` |
| ¿Qué sugiero cuando no se le puede preguntar al provider? | `backend/app/core/catalog/curated_models.json` |
| ¿Cuánto cuesta este modelo, y cuánto contexto acepta? | el snapshot de `genai-prices`, a través de `model_catalog.priced_model` |
| ¿Qué modelos dibujan imágenes? | `backend/app/core/catalog/image_models.json`, más la propia respuesta del SDK sobre qué providers pueden dibujar |

!!! info "Todo lo que hay bajo la primera fila se deriva de ella"

    Una copia derivada que se desvía no falla nada en tiempo de ejecución.
    Muestra un selector para un provider que no existe, o deja fuera uno que sí.

    `tests/test_model_catalog.py::TestOneAnswerPerQuestion` es lo que en su lugar
    convierte eso en una build fallida — y exige que cada provider aparezca en
    **esta página**.

Cada clave de cualquiera de los dos archivos de catálogo tiene que nombrar un
provider que `PROVIDERS` tenga. También cada entrada del catálogo de imágenes. Y
cada provider tiene que aparecer en esta página. Añadir el vigesimoctavo es una
edición más lo que ese test pida después.

Merece la pena conocer dos cruces, porque son búsquedas que pueden no responder
nada:

- El snapshot de precios escribe tres providers de otra forma — `xai` es `x-ai`,
  `bedrock` es `aws`, `google_cloud` es `google` — y `_PRICE_PROVIDER_ALIASES`
  los puentea.
- El catálogo de imágenes lleva su propio par `provider` y `prefix`, que es un
  tercer vocabulario otra vez.

## Qué modelos ofrece un provider { #which-models-a-provider-offers }

El campo del id de modelo se rellena desde dos fuentes, en este orden — y desde
ninguna de las dos para siete providers, cosa que la respuesta dice en voz alta.

### En vivo { #live }

Veinte providers publican un endpoint de listado, y es la única fuente que sabe
de un modelo publicado esta mañana:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`.

Las formas de la respuesta no coinciden — el array está en `data`, en `models` o
en la raíz del documento; el id es `id`, `name` o `model`; Gemini lo prefija con
`models/` — así que cada uno se describe con datos y no con una rama. Se cachean
en el proceso durante una hora; estas listas se mueven en el orden de semanas.

**Cinco de ellos no necesitan credencial alguna** — `openrouter`, `sambanova`,
`vercel`, `ovhcloud` y `huggingface` — que es lo que los hace valiosos: el
selector se rellena antes de que nadie haya guardado una clave para ese provider.
A los otros quince se les pregunta con la clave propia de la organización cuando
la hay.

Seis providers siguen sin publicar nada que esto pueda leer: `github` (su ruta de
catálogo ya no está), `heroku`, `azure`, `bedrock`, `google_cloud`, y un proxy
`litellm` cuya lista es lo que el despliegue haya puesto detrás. `ollama`
responde en la red del propio despliegue y no en un host fijo, así que tampoco
está en la lista.

!!! warning "Una lista de modalidades vacía significa *no declarado*, nunca «solo texto»"

    `openrouter` y el router de Hugging Face llevan los dos
    `architecture.output_modalities`, y una entrada de listado puede nombrar esa
    ruta. Nadie más lo declara.

    Un cliente que filtre por ella tiene que tratar la ausencia como desconocido,
    o esconderá modelos que funcionan. Son metadatos por los que un cliente puede
    estrechar; *no* son cómo la capability de imagen elige sus modelos, que es un
    archivo de catálogo más la propia respuesta del SDK sobre qué providers
    pueden dibujar — ver
    [Generación de imágenes](reference/capabilities.md#image-generation).

### Curados { #curated }

Una lista corta por provider, usada cuando el provider no publica nada, cuando la
llamada falla, o cuando no hay clave con la que hacerla.

Vive en `backend/app/core/catalog/curated_models.json` junto a los demás
catálogos del despliegue, así que añadir un modelo es una entrada y no una
edición de Python — y los propios listados son `model_listings.json` en el mismo
directorio, que es lo que convierte también en datos el endpoint de un provider
nuevo.

Es deliberadamente corta y deliberadamente **no** se toma de `genai-prices`, que
ya es una dependencia y sí lista modelos.

Ese es un conjunto de datos de *precios*. Lleva `ada` y `babbage` bajo OpenAI,
`claude-2` bajo Anthropic, 690 filas bajo OpenRouter, y no marca casi nada como
obsoleto — ordenado alfabéticamente, lo primero que un selector ofrecería para
OpenAI es `ada`. Una lista corta y actual gana a una larga y engañosa.

Para lo que la biblioteca *sí* se usa es para la mitad que se pudre. **Cada
longitud de contexto sale del snapshot en el momento de leerla**, así que aquí no
se escribe ninguna ventana; dos que lo estaban ya se habían quedado obsoletas,
una de ellas anotada dos veces con dos cifras distintas.

Y un id curado del que el snapshot nunca ha oído hablar hace fallar la suite de
tests, que es como se pilla una errata o un modelo retirado en vez de publicarlo
como un desplegable al que el provider responde 404. Un modelo que el snapshot
conoce pero no tarifa simplemente no tiene ventana, que es el nulo descrito más
abajo.

| Provider | ids curados |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `google` | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| `deepseek` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `xai` | `grok-4.5`, `grok-4.3` |
| `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `openrouter` | cinco ids comunes entre providers |

### Ninguna de las dos, y lo dice { #neither-and-it-says-so }

Siete providers no publican ningún listado que esta plataforma pueda leer y no
tienen entrada curada — `github`, `heroku`, `ollama`, `litellm`, `azure`,
`bedrock` y `google_cloud`.

Para esos, el `source` de la respuesta es `unlisted`, **no** `curated`. Una lista
corta vacía no es una lista corta, y afirmar que lo es es lo que convierte «esta
plataforma no puede enumerar este provider» en «este provider no tiene modelos»
(#923). El selector pide el id en su lugar.

`ollama` y `litellm` son los que merece la pena conectar — los dos publican un
`/v1/models` con forma de OpenAI en el endpoint que el perfil ya guarda — y eso
exige decirle al listado una URL base, cosa que un `ListingSpec.url` fijo no
puede ser.

Ninguna de las dos fuentes es autoritativa, que es por lo que el campo sigue
siendo texto libre.

## La ventana que acepta un modelo se lee una vez y se guarda { #the-window-a-model-accepts-is-read-once-and-kept }

Un listado suele llevar cuántos tokens acepta el modelo, y el perfil lo anota
como `context_length` cuando se crea.

Ese número es sobre el que se dispara
[la gestión de contexto](reference/capabilities.md#context-management):
compactar a una fracción de la ventana es el único ajuste que sigue siendo
correcto cuando un agent se muda a otro modelo.

!!! danger "Por qué se guarda en vez de resolverse por run"

    El camino de la petición no debe llamar a un provider, y lo único que podría
    consultar si no es el snapshot de precios incluido — que aquí se equivoca en
    la dirección que rompe un run.

    Ese snapshot registra 1.000.000 para `anthropic:claude-sonnet-4-5` frente a
    unos 200.000 reales, así que un disparo al 90 % cae por encima del techo real
    y la compactación nunca se activa antes de que el provider rechace la
    petición. Un perfil con fallbacks es peor: construye un `FallbackModel` cuyo
    id compuesto no resuelve a nada en absoluto.

Nulo significa **no anotado**, no cero: un perfil más antiguo que la columna, un
provider que no publica longitud, una lista curada, o un listado al que no se
pudo llegar. La capability resuelve entonces la ventana ella misma, exactamente
como hacía antes.

Si sabes más que las dos, pon `context_window` en el binding. Un provider publica
el máximo que se *puede* hacer aceptar a un modelo, y un despliegue limitado por
beta o por nivel obtiene menos.

Una cadena de fallbacks lleva el número del **primario**. Un `FallbackModel` no
tiene ventana propia, y a qué modelo llega un run no se sabe hasta que uno ha
rechazado.

## Lo que cuesta un run { #what-a-run-costs }

Los precios vienen de un snapshot de
[`genai-prices`](https://github.com/pydantic/genai-prices) incluido en el
paquete. Nada llama a casa para conseguirlos, lo que significa dos cosas que
conviene saber:

- Un modelo demasiado nuevo para el snapshot está **sin tarifar**, y un run que
  contenga uno se registra como *parcialmente tarifado* y no como si no costara
  nada. Un budget que tratara en silencio un modelo desconocido como gratis sería
  un budget con un agujero.
- Actualizar los precios es subir una dependencia.

!!! warning "Un provider sin clave no registra gasto"

    El gasto se atribuye al [secreto del vault](secrets.md) al que resolvió el
    run, y un provider sin clave no tiene ninguno al que atribuirlo.

El coste se comprueba *antes* de cada petición al modelo y se registra incluso
cuando el run falla. Ver [Budgets](governance.md#budgets).

### Una delegación resuelve su propio perfil { #a-delegation-resolves-its-own-profile }

Un run puede implicar varios modelos.

Un [delegate](concepts.md#delegate-vs-inline-specialist) funciona sobre el perfil
que nombra *su propio* spec, resuelto cuando el runner recorre el árbol de
delegación. Un especialista inline que no nombra ninguno funciona sobre el perfil
del agent que lo llamó — a la vez la respuesta menos sorprendente y la única que
funciona cuando el del padre es el único perfil que eligió el autor.

Esas peticiones se miden contra el único libro de cuentas del run padre, pero se
**tarifan por provider**: el guard del delegate comparte el libro, los topes y
las líneas base del mes, y toma su propio provider.

Compartir directamente el del padre tarifaría un delegate de Anthropic contra el
catálogo de OpenAI — en silencio, y normalmente como sin tarifar, lo que
subestima el run y marca uno perfectamente tarifable como un suelo.

La fila del run hijo que escribe una delegación nombra el modelo que la
respondió, así que el panel de costes agrupa un turno delegado bajo el modelo que
realmente se ejecutó y no bajo el del padre.

## Resumen { #recap }

- Un **perfil** es un modelo con nombre más una clave con nombre, y los agents
  apuntan a perfiles para que rotar cualquiera de los dos toque una sola fila.
- **27 providers**, y lo único que esta plataforma sabe de cada uno es la forma
  de la credencial — construirlo es trabajo de Pydantic AI.
- El id de modelo es **texto libre**, porque ninguna lista es autoritativa.
- La **longitud de contexto** se lee una vez y se guarda, porque el snapshot de
  precios se equivoca sobre ella en la dirección que rompe un run.
- El **coste** viene de un snapshot incluido, un modelo desconocido se registra
  como sin tarifar y no como gratis, y un provider sin clave no registra gasto
  alguno.

## Configurar uno { #setting-one-up }

El [recorrido del primer agent](first-agent.md) hace esto de principio a fin. En
resumen: guarda una clave de provider en **Settings → Secrets**, añade un perfil
de modelo que la nombre y después apunta el spec de un agent a ese perfil.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

hace las tres cosas para un despliegue nuevo.
