---
title: "Evaluación de recuperación"
description: "Un conjunto de preguntas sobre la documentación con respuestas conocidas, y el harness que mide la recuperación por categoría, top_k y expansión."
source_sha: "4a39f7cb19a0"
---

# Evaluación de recuperación { #retrieval-evaluation }

Un agent de conocimiento vale lo que su búsqueda le entrega al modelo. Un cambio
en el troceado, en `top_k` o en la expansión de la consulta mueve eso, y una
respuesta que se lee bien no dice nada sobre si se recuperó la página correcta.
Por eso hay un conjunto de preguntas con respuestas conocidas sobre esta
documentación, y un harness que mide la recuperación sobre él, en
`evals/retrieval/`. Esta página explica qué mide, cómo ejecutarlo y cuánto cuesta
una ejecución.

Empezó con una pregunta ([#2482](https://github.com/vstorm-co/agenticos/issues/2482)).
Ante *"Does AgenticOS support SAML single sign-on?"*, un agent sobre la
documentación recuperó solo la página de comparación con Dify y respondió que la
documentación no lo dice. [El inicio de sesión de directorio](directory.md) dice
claramente que no hay SAML, y cómo llegar a AgenticOS a través de Keycloak en su
lugar.

## El conjunto de preguntas { #the-question-set }

`evals/retrieval/docs_questions.yaml` contiene 34 preguntas en tres categorías:

| Categoría | Qué prueba | Ejemplo |
|---|---|---|
| `factual` | Un ajuste, un valor por defecto o un nombre enunciado | "If I never set a vault master key, what does the platform encrypt credentials with?" |
| `negative` | Una pregunta del tipo "¿soportáis X?" a la que la documentación responde con un no rotundo | "Does AgenticOS support SAML single sign-on?" |
| `cross_language` | Una pregunta en polaco respondida solo desde las páginas en inglés, o una pregunta en inglés solo desde las páginas en polaco | "Czy da się logować do AgenticOS przez SAML?" |

Cada pregunta nombra sus páginas esperadas y, para la comprobación de la
respuesta, los hechos que contiene una respuesta correcta. Una entrada tiene este
aspecto:

```yaml
- id: saml-single-sign-on
  category: negative
  language: en
  question: Does AgenticOS support SAML single sign-on?
  expected_pages: [directory.md]
  expected_facts:
    - ["no", "not", "nie"]
    - [Keycloak*]
  evidence: "directory.md: **No SAML.** A SAML-only identity provider can reach AgenticOS through Keycloak"
```

Una página se nombra sin su idioma: `directory.md` es también `directory.pl.md`,
así que un fragmento de cualquiera de las dos traducciones cuenta como haberla
encontrado. Una pregunta `cross_language` añade `search_locales`, el único idioma
que su búsqueda puede leer, que nunca es el idioma en que se formula. El archivo
está versionado, y un cambio en lo que significa un campo incrementa `version`.
El cargador rechaza una página esperada que no existe o no está publicada, así que
renombrar una página hace fallar las pruebas unitarias en vez de convertirse en un
fallo en una ejecución que alguien pagó.

## Qué mide una ejecución { #what-a-run-measures }

El corpus es el sitio publicado: cada página Markdown bajo `docs/` excepto lo que
`mkdocs.yml` deja fuera (`plans/`, `design/`, `audits/`, la hoja de ruta) y
esta página, que cita las preguntas y sus respuestas. Cada idioma se indexa en
su propia colección, nombrada según el modelo de embeddings y un digest de los
ajustes de embeddings e ingesta: una ejecución que cambia el tamaño de fragmento
o el modelo indexa desde cero. Una ejecución posterior reutiliza una colección
mientras contenga cada página en su versión actual, y la reconstruye cuando se
añadió, eliminó, renombró o editó una página. Una pregunta normal busca en
todas a la vez, como hace un agent vinculado a varias colecciones.

Cada configuración es una pasada sobre las 34 preguntas. La búsqueda sigue el
propio camino de la herramienta de conocimiento: la consulta se expande según
`query_analysis_mode`, se recupera cada consulta, y los resultados se fusionan y
se recortan a `top_k`. Las consultas expandidas de una pregunta se generan una
vez por modo y se reutilizan para cada `top_k`, así que dos valores de `top_k` se
comparan sobre las mismas reformulaciones. Por categoría, la ejecución informa
de:

| Número | Significado |
|---|---|
| hit@k | La proporción de preguntas con al menos un fragmento de una página esperada entre los `top_k` devueltos |
| recall@k | La proporción de las páginas esperadas de cada pregunta que se alcanzaron, promediada |
| MRR | La media de 1/rango del primer fragmento de una página esperada, 0 cuando no se devolvió ninguno |
| Respuestas correctas | Con `--answers`: cuántas respuestas contienen todos los hechos esperados |

Tras cada tabla, la ejecución lista las preguntas que falló y las páginas que
obtuvo en su lugar, que es donde está la información útil.

La comprobación de la respuesta es deliberadamente simple. Un hecho coincide
como palabra completa, las mayúsculas no importan, y una alternativa que termina
en `*` coincide como prefijo (`Keycloak*` coincide con "Keycloaka"). Los
marcadores de cita como `[5]` se ignoran, así que un número de pasaje nunca
cuenta como número de la respuesta. Un simple "no" no basta: cada pregunta
negativa necesita también la alternativa que nombra la documentación, así que
"la documentación no lo dice" nunca pasa. La comprobación sigue sin distinguir
una respuesta correcta de una confundida con las mismas palabras, así que tómala
como señal aproximada.

`--json` escribe las páginas recuperadas y la respuesta de cada pregunta para
quien quiera leerlas, y las consultas que un modo `multi_query` o `hyde` buscó
para ella. El archivo también registra qué produjo la ejecución: cuándo empezó,
un SHA-256 del conjunto de preguntas, el modelo de embeddings y su dimensión,
los ajustes de fragmentación y los parsers, y el digest que llevan los nombres
de las colecciones.

## Ejecutarlo { #running-it }

Una ejecución necesita una base de datos migrada con pgvector (`make dev` te da
una), un endpoint de embeddings y, para `multi_query`, `hyde` y `--answers`, un
modelo. Usa una base de datos de desarrollo, no la de un despliegue. El harness
elimina y reconstruye sus propias colecciones, y se niega a arrancar cuando una
base de conocimiento ya usa uno de sus nombres.

!!! warning "Cada llamada es una llamada real y facturada"
    El harness genera los embeddings del corpus y de cada consulta con el endpoint
    que le indiques, y llama al modelo que nombres. Nada se almacena en caché ni se
    simula. Lee [Coste](#cost) antes de la primera ejecución.

```bash
export OPENAI_API_KEY=sk-...
make eval-retrieval EVAL_ARGS="--top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --llm-model openai:gpt-4.1-mini --answers --json /tmp/retrieval.json"
```

Las opciones:

| Opción | Valor por defecto | |
|---|---|---|
| `--top-k` | `5` | Repetible, 1–50. Fragmentos por búsqueda, el `default_top_k` de la capability de conocimiento |
| `--mode` | `off` | Repetible. `off`, `multi_query` o `hyde`, el `query_analysis_mode` de la capability |
| `--chunk-size` | `2500` | Caracteres por fragmento, como los fijan los ajustes de ingesta de una colección |
| `--chunk-overlap` | `200` | Caracteres que un fragmento repite del anterior. Debe ser menor que `--chunk-size` |
| `--chunking-strategy` | `recursive` | `recursive`, `markdown` o `fixed` |
| `--max-variants` | `3` | Reformulaciones que `multi_query` puede añadir, 1–5 |
| `--locale` | `en`, `pl` | Repetible. Los idiomas indexados; debe incluir el de cada pregunta `cross_language` |
| `--embedding-model` | `text-embedding-3-small` | Cualquier modelo del catálogo de embeddings, u otro con `--embedding-dim` |
| `--embedding-dim` | del catálogo de modelos | Dimensión positiva para un modelo fuera del catálogo |
| `--embedding-base-url` | `https://api.openai.com/v1` | Cualquier endpoint `/v1/embeddings` compatible con OpenAI |
| `--embedding-api-key-env` | `OPENAI_API_KEY` | La variable de la que se lee la clave |
| `--keyless` | desactivado | El endpoint no requiere clave |
| `--llm-model` | ninguno | Un nombre de modelo de Pydantic AI. Su provider lee su propia variable de clave. `openai:` usa la Responses API de OpenAI; otros endpoints, más abajo |
| `--answers` | desactivado | Además responde cada pregunta a partir de lo recuperado y comprueba los hechos |
| `--reingest` | desactivado | Elimina las colecciones e indexa el corpus de nuevo. Una ejecución lo hace por sí sola cuando cambia una página o un ajuste de fragmentación; páselo tras un cambio en el código del parser |
| `--json` | ninguno | Además escribe los resultados por pregunta en este archivo |

Las opciones de fragmentación se comprueban como los ajustes de ingesta de una
base de conocimiento, y cualquier otro ajuste de ingesta tiene el valor por
defecto de ese formulario. El corpus es Markdown, que el lector integrado
analiza sea cual sea el parser de PDF configurado, así que no hay opción de
parser. El harness no lee estos ajustes de ninguna variable de entorno.

Un conjunto de preguntas que el loader rechaza detiene la ejecución antes de
indexar nada, con un único mensaje que nombra cada pregunta y su problema.

El informe va a la salida estándar y el progreso a la salida de error estándar,
así que `> results.md` conserva solo el informe. El harness se detiene antes de
medir si una página no se indexa, y una ejecución interrumpida elimina lo que
indexó, porque un corpus con huecos mide los huecos.

### Sin una clave de pago { #without-a-paid-key }

Un servidor compatible con OpenAI en tu propia máquina sirve para los embeddings.
Con [Ollama](https://ollama.com), tras `ollama pull bge-m3`:

```bash
make eval-retrieval EVAL_ARGS="--embedding-base-url http://localhost:11434/v1 \
    --embedding-model bge-m3 --keyless"
```

`bge-m3` es multilingüe, lo que importa para las preguntas `cross_language`. Los
números describen ese modelo, no el que usan las colecciones de un despliegue, así
que compara solo ejecuciones con el mismo modelo de embeddings.

Un modelo local para `multi_query`, `hyde` y `--answers` necesita el prefijo
`openai-chat:`, porque `openai:` llama a la Responses API, que la mayoría de los
servidores compatibles con OpenAI no tienen. `OPENAI_BASE_URL` dirige el
provider al servidor. Defínela solo para ese comando, como abajo: exportada,
enviaría cada llamada `openai:` posterior, con su clave, al servidor local. Sin
`OPENAI_API_KEY`, el provider envía una clave de relleno. Tras
`ollama pull qwen3:8b`:

```bash
OPENAI_BASE_URL=http://localhost:11434/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url http://localhost:11434/v1 --embedding-model bge-m3 --keyless \
    --mode multi_query --llm-model openai-chat:qwen3:8b"
```

Lo mismo vale para cualquier endpoint que solo ofrezca chat completions.

## Coste { #cost }

El corpus publicado tiene unos 0,6 millones de tokens en inglés y 1,0 millones en
polaco, medidos con el tokenizador `cl100k_base` que usan los modelos de
embeddings de OpenAI. Con el solapamiento de fragmentos de 200 caracteres, indexar
ambos idiomas supone unos 1,7 millones de tokens. Se paga una vez, y de nuevo
para un idioma cuando cambia una de sus páginas o con `--reingest`.

| Parte | Tokens por ejecución | A precio de lista |
|---|---|---|
| Indexación, `text-embedding-3-small` | ~1,7M, una vez | ~$0.03 |
| Indexación, `text-embedding-3-large` | ~1,7M, una vez | ~$0.22 |
| Embeddings de las preguntas | menos de 10k por configuración | menos de $0.01 |
| `multi_query` o `hyde`, `gpt-4.1-mini` | ~34 llamadas, ~10k tokens por configuración | menos de $0.01 |
| `--answers` con `top_k` 5, `gpt-4.1-mini` | ~34 llamadas, ~150k tokens de entrada y ~5k de salida | ~$0.07 |
| `--answers` con `top_k` 10, `gpt-4.1-mini` | ~300k tokens de entrada y ~5k de salida | ~$0.13 |

Los precios son precios de lista por millón de tokens en el momento de escribir
esto: `text-embedding-3-small` $0.02, `text-embedding-3-large` $0.13,
`gpt-4.1-mini` $0.40 de entrada y $1.60 de salida. Comprueba los precios actuales
de tu provider. Con estos precios, la matriz completa de dos valores de `top_k`,
tres modos y respuestas cuesta menos de un dólar. Al final, la ejecución imprime
las llamadas al modelo que hizo y sus tokens.

## Comparación medida { #measured-comparison }

El 10 de noviembre de 2026, una ejecución real usó la conexión existente GPT-6
Luna mediante OpenRouter: `openai/gpt-6-luna` para ampliar consultas y responder,
y `openai/text-embedding-3-small` con 1536 dimensiones para embeddings. El corpus
en la revisión `e8e782562` contenía 128 páginas en inglés (1452 fragmentos) y 128
en polaco (1553 fragmentos). La fragmentación fue `recursive`, con tamaño 2500 y
solapamiento 200. Las 34 preguntas se ejecutaron en cada configuración; las
consultas ampliadas se reutilizaron en las dos profundidades de búsqueda.

| `top_k` | Modo | hit@k | recall@k | MRR | Comprobaciones de hechos en las respuestas |
|---|---|---|---|---|---|
| 5 | `off` | 73.5% | 70.6% | 0.571 | 23/34 |
| 5 | `multi_query` | 76.5% | 73.5% | 0.581 | 25/34 |
| 5 | `hyde` | 88.2% | 83.8% | 0.698 | 25/34 |
| 10 | `off` | 85.3% | 83.8% | 0.588 | 28/34 |
| 10 | `multi_query` | 79.4% | 77.9% | 0.621 | 24/34 |
| 10 | `hyde` | 94.1% | 92.6% | 0.705 | 27/34 |

Las dos preguntas sobre SAML, en inglés y polaco, recuperaron la página de
directorio y respondieron que SAML no se admite directamente y Keycloak sirve
de puente, en las seis configuraciones. `10/hyde` alcanzó una página esperada
para las diez preguntas entre idiomas. `10/off` superó más comprobaciones de
respuestas y mejoró cinco respuestas respecto a `5/off`, sin añadir otro fallo
ni necesitar una llamada de ampliación.

Para un agente de documentación con este corpus, empieza con `default_top_k: 10`
y `query_analysis_mode: off`. Elige `hyde` expresamente cuando alcanzar más
páginas esperadas, sobre todo entre idiomas, importe más que su llamada adicional
al modelo y sus búsquedas. Conserva los valores por defecto de la plataforma,
`default_top_k: 5` y `query_analysis_mode: off`: un corpus pequeño y un modelo
no justifican aumentar el contexto ni añadir llamadas de ampliación para todos
los despliegues.

La [ejecución completa](https://github.com/vstorm-co/agenticos/blob/main/evals/retrieval/results/2026-11-10-openrouter-gpt6-luna.json)
contiene los resultados por categoría, cada página recuperada, consulta ampliada
y respuesta, hashes del corpus, versiones de paquetes y consumo de tokens.
Realizó 272 solicitudes al modelo con 872.567 tokens de entrada y 41.553 de
salida, además de los embeddings. Son medidas de una sola ejecución, no una
garantía de calidad ni una comparación estadística repetida. Seis respuestas de
`10/off` aún omitieron hechos requeridos, como el rol que aprueba, el tamaño por
defecto del fragmento y el puente stdio. Siguen vigentes las limitaciones de la
comprobación de respuestas descritas arriba.

Para repetir los ajustes del modelo y la búsqueda con tu propia clave autorizada:

```bash
OPENAI_BASE_URL=https://openrouter.ai/api/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url https://openrouter.ai/api/v1 \
    --embedding-model openai/text-embedding-3-small --embedding-dim 1536 \
    --llm-model openai-chat:openai/gpt-6-luna \
    --top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --answers --json /tmp/retrieval.json"
```

## Qué no decide { #what-it-does-not-decide }

La herramienta nunca cambia los ajustes de un agente. La recomendación anterior
se aplica al corpus de documentación medido; evalúa tu propio corpus antes de
cambiar un agente. La suite tampoco prueba permisos. Sus colecciones no
pertenecen a ninguna organización y se buscan sin ámbito, como hace `rag-search`.
Las páginas de [procesamiento de archivos](file-processing.md) y de la
[capability de conocimiento](reference/capabilities.md#query-analysis-and-expansion)
describen la búsqueda con ámbito.
