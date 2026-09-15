---
source_sha: "bd9c21e1a80b"
---

# Monta una base de conocimiento { #set-up-a-knowledge-base }

Cómo conseguir que un agent responda a partir de tus propios documentos, de
principio a fin. Unos veinte minutos, sin terminal, y una decisión por el camino
que no se puede deshacer.

[Procesamiento de archivos](../file-processing.md) explica la pipeline; esto es
la receta.

## 1. Crea la colección { #1-create-the-collection }

**Knowledge → New**. Ponle un nombre que una persona reconozca — es lo que
alguien elegirá de una lista más adelante — y un alcance, que decide si es tuya
o de la organización.

!!! danger "El modelo de embeddings queda congelado al crearla"

    Es la única elección de esta página que no puedes cambiar después. La columna
    vectorial se crea con la anchura de ese modelo, y dos modelos de la misma
    anchura escriben aun así en espacios *distintos* — de modo que la búsqueda
    seguiría comparando vectores que no significan lo mismo.

    Cambiar de idea más adelante significa crear una colección nueva y volver a
    ingerirlo todo. El formulario ofrece los modelos que sirve el provider
    elegido y preselecciona el primero; déjalo así salvo que tengas un motivo
    para no hacerlo, y si lo tienes, consulta
    [Elegir un modelo](../choosing-models.md#embeddings-are-a-separate-permanent-choice).

En **Embeddings**, elige el provider que sirve el modelo y el secreto del vault
que lo paga. Ambos son obligatorios: no hay clave de embeddings a nivel de
deployment, así que una colección sin ella se rechaza aquí en lugar de crearse y
quedarse sin poder indexar su primer documento. La clave tiene que ser una del
provider elegido; si la organización todavía no tiene ninguna, el formulario
junto al selector guarda una. El provider y la clave se pueden cambiar después,
el modelo no — consulta [Procesamiento de archivos](../file-processing.md#embeddings-the-model-whose-endpoint-answers-and-whose-key-pays).

**Ollama** también está en la lista de providers. No toma clave: elígela, uno de
sus modelos y el **servidor** donde responde — un servicio local registrado en
Knowledge → Integrations, el propio de la organización o uno que el
administrador del deployment haya registrado para todos — y los documentos de la
colección no salen nunca de la red del propio deployment. La misma pestaña
guarda los servidores OCR para LiteParse, que se eligen en los ajustes de
parseo.

Una knowledge base creada sobre un nombre de colección que ya existe adopta en
su lugar el provider y la clave de esa colección — la ausencia de clave
incluida, porque toda fila de una misma colección tiene que embeber igual. A esa
colección dale la clave después, en su propia página.

## 2. Decide cómo se leen los documentos { #2-decide-how-documents-are-read }

Cada colección lleva sus propios ajustes de ingesta, y cada subida puede
anularlos. Los valores por defecto son razonables; estos son los tres que merecen
una reflexión.

**Qué parser lee un PDF.**

| | Qué es | Elígelo cuando |
|---|---|---|
| `pymupdf` | Local, rápido, gratuito — y el único que extrae las imágenes incrustadas para describirlas | Documentos en los que manda el texto. Empieza aquí |
| `liteparse` | Local, atento al diseño, mantiene las tablas como rejillas ASCII en vez de aplanarlas | Documentos cuyo significado está en sus tablas |
| `llamaparse` | Un servicio en la nube, facturado por página, devuelve markdown | Documentos escaneados o difíciles que los dos locales destrozan — y aceptas que las páginas salgan de casa |

**Si usar OCR o no.** Activado para escaneos y fotografías de documentos,
desactivado en los demás casos. Es más lento y sobre texto limpio se inventa
caracteres.

**Cómo se cortan las páginas en fragmentos.** `recursive` divide por la
estructura y es el valor por defecto correcto; `markdown` sigue los encabezados,
lo que va mejor cuando tus documentos los tienen de verdad; `fixed` es un recuento
tosco de caracteres, para cuando los otros dos producen disparates.

!!! tip "Cambia una cosa cada vez"

    Estos ajustes interactúan entre sí. Si la recuperación es mala, cambia el
    parser *o* la fragmentación, vuelve a ingerir un documento y haz la misma
    pregunta otra vez.

## 3. Mete documentos { #3-put-documents-in }

Dos maneras, y puedes usar las dos en una misma colección.

**Sube** archivos directamente — el parser que elegiste los lee, los fragmenta,
los convierte en embeddings, y el documento figura como `processing` hasta que
eso termina.

**Sincroniza una fuente** — una carpeta de Google Drive o un bucket de S3, releída
según un horario, de modo que la colección sigue a la carpeta en vez de a una
copia suya. Consulta
[Configura las fuentes de sincronización](configure-sync-sources.md).

!!! warning "Si la ingesta falla en una instalación nueva, revisa la imagen de la base de datos"

    El almacén lanza `CREATE EXTENSION IF NOT EXISTS vector` la primera vez que se
    escribe en una colección, y un Postgres de serie responde *extension "vector"
    is not available* — un 500 antes de que se haya confirmado ninguna fila. La
    imagen tiene que ser `pgvector/pgvector:pg16`.

## 4. Dásela a un agent { #4-give-it-to-an-agent }

En el Builder, sobre el agent:

1. Activa la capability **Knowledge search**.
2. Vincula la colección — un agent busca en las colecciones que tú nombres y en
   ninguna otra.
3. Fija `default_top_k`, el número de fragmentos que devuelve una búsqueda.

**Empieza por tres.** Ocho fragmentos donde bastarían tres son el sobrecoste
silencioso más habitual de este producto: el texto recuperado se lee en el turno
en que llega, y en cada turno en que se arrastra, y suele ser lo más voluminoso
del prompt.

Después dilo en las instructions. La recuperación pone el texto delante del
modelo; las instructions deciden qué hace con él:

```
Answer from the knowledge collection and cite the document you used.
If the collection does not cover it, say so rather than guessing.
```

Esa segunda frase es la que convierte una invención segura de sí misma en un "eso
no lo tengo" — y merece la pena probarla a propósito, preguntando algo que sabes
que no está en los documentos.

## 5. Pruébala { #5-test-it }

Publica, abre la pestaña **Test** del agent y haz tres preguntas:

| Pregunta | Qué estás comprobando |
|---|---|
| Algo que está claramente en los documentos | Que la recuperación funciona siquiera, y que la respuesta lleva una cita |
| Algo que claramente *no* está en ellos | Que rechaza en vez de inventar |
| Algo en el límite — un dato en una tabla, o en un escaneo | Si el parser leyó de verdad esa parte |

La tercera es la que encuentra los problemas reales, y por eso merece la pena
revisar la elección de parser del paso 2 en lugar de fiarse de ella.

## Cuando no encuentra algo que sin duda está ahí { #when-it-cannot-find-something-that-is-definitely-there }

Recorre esta lista; está aproximadamente ordenada según la frecuencia con que
cada punto es la causa.

1. **¿El documento está en `processing` o ha fallado?** El error de un documento
   fallido está en el propio documento y dice qué etapa se rindió.
2. **¿La colección está vinculada a *este* agent?** La vinculación es por agent, y
   una versión publicada lleva las vinculaciones que tenía al publicarse.
3. **¿Leyó el parser esa parte?** Abre el documento y mira el texto extraído. Una
   tabla aplanada en prosa o un escaneo sin OCR es invisible para la búsqueda,
   por muy claramente que tú lo veas.
4. **¿`default_top_k` es demasiado pequeño?** Tres está bien para un corpus
   acotado y es demasiado poco para uno amplio.
5. **¿La página está realmente vacía, o falló la petición?** Ambas cosas dibujan
   el mismo "aquí no hay nada". Mira la pestaña de red antes de concluir nada.

## Resumen { #recap }

- El **modelo de embeddings queda congelado al crear la colección**. Es la única
  elección irreversible de aquí.
- **`pymupdf` primero**, `liteparse` para documentos cargados de tablas,
  `llamaparse` cuando las páginas puedan salir de casa y los otros no den abasto.
- **Empieza `default_top_k` en tres** y súbelo solo si a las respuestas les falta
  contexto de verdad.
- Las instructions tienen que decir **"say so rather than guessing"** — la
  recuperación por sí sola no frena la invención.
- Prueba con algo que **no** esté en los documentos, y con algo enterrado en una
  tabla.

[La pipeline en detalle →](../file-processing.md) ·
[Sincronizar una carpeta →](configure-sync-sources.md)
