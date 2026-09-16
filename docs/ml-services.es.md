---
source_sha: "b0683ad2a99c"
---

# Los servicios de ML { #the-ml-services }

Cuatro servicios de esta plataforma se pueden llamar por su cuenta, sin empezar
una conversación y sin ejecutar un agent: análisis de documentos, OCR,
transcripción de voz y detección de datos personales. Son las mismas
implementaciones que usan los agents, alcanzadas directamente — un conjunto de
parsers, un conjunto de detectores, un cliente de transcripción.

Existen porque otro componente puede necesitarlos. Una cola que tiene que leer un
formulario escaneado, un proceso por lotes que redacta una exportación, un
servicio que quiere una transcripción — ninguno quiere una ventana de chat, y
ninguno debería tener que fingir que lo es.

## Qué está entregado y qué no { #what-is-delivered-and-what-is-not }

Cada familia de servicios es una fila. **served** significa que un endpoint de
este despliegue la responde con el motor nombrado al lado. **dependency**
significa que la familia es obligatoria y falta algo, y la nota dice qué.
**prepared** es preparación de arquitectura: no se entrega ningún motor, y la
costura por la que llegaría está nombrada.

`GET /api/v1/ml/services` responde con esta misma tabla, de modo que una
integración puede leerla en lugar de fiarse de una página.

| Servicio | Requisitos | Endpoint | Estado | Motor |
|---|---|---|---|---|
| `document_analysis` | FA-069, FA-070 | `POST /api/v1/ml/documents/analyze` | served | LiteParse o PyMuPDF, en local |
| `ocr` | FA-069, FA-071 | `POST /api/v1/ml/documents/ocr` | served | OCR de LiteParse: Tesseract incluido, o un servidor OCR registrado |
| `speech_to_text` | FA-069, FA-072 | `POST /api/v1/ml/audio/transcriptions` | served | El endpoint de transcripción propio de la organización |
| `pii_detection` | FA-069, FA-073 | `POST /api/v1/ml/privacy/pii` | served | Los detectores de patrones que usan los guardrails |
| `pii_named_entities` | FA-073, DA-007 | — | dependency | Ninguno en este despliegue |
| `image_analysis` | FA-074 | — | prepared | Ninguno en este despliegue |

Dos filas dicen que no, y ambas dicen por qué. Las **entidades nombradas** — el
nombre de una persona, una dirección postal, un número de teléfono — no tienen
forma de patrón, así que ninguna expresión regular las encuentra: eso requiere un
modelo de reconocimiento de entidades por cada idioma del alcance. El endpoint de
detección llevará las categorías adicionales el día que se provea uno, y hasta
entonces no las reclama. El **análisis de imagen** está marcado como alcance
futuro en los propios requisitos.

## Cómo llamar a uno { #calling-one }

La autenticación, la cabecera de organización y el sobre de error son los de la
[API HTTP](api.md). No hay clave aparte, ni host aparte, ni una segunda entrada,
y es deliberado: una superficie con su propia puerta principal es una superficie
con sus propios errores.

Un permiso controla los cuatro: **`ml:invoke`**. Deliberadamente no es
`agents:run` — una integración que parsea documentos no debería por ello poder
gastar el presupuesto de modelo de la organización. Lo tienen todos los roles
salvo Viewer.

```bash
curl -X POST "$BASE/api/v1/ml/documents/ocr" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -F "file=@scan.pdf" \
  -F "language=deu"
```

La respuesta lleva las páginas en orden, los chunks preparados, y el tamaño y el
hash del archivo:

```json
{
  "filename": "scan.pdf",
  "filetype": "pdf",
  "byte_size": 184320,
  "content_hash": "9f2c…",
  "pages": [{"page_num": 1, "content": "Antrag auf …"}],
  "chunks": ["Antrag auf …"]
}
```

### Análisis de documentos { #document-analysis }

`POST /api/v1/ml/documents/analyze` lee lo que el documento ya lleva. El campo
`parser` elige entre `liteparse`, que conserva la maquetación y lee formatos de
ofimática donde LibreOffice está instalado, y `pymupdf`, que lee PDF y es más
rápido. `chunk_size`, `chunk_overlap` y `chunking_strategy` dan forma a los
chunks preparados; las estrategias son `recursive`, `fixed` y `markdown`.

Un documento del que no se puede leer nada se rechaza en lugar de responderse con
una lista de páginas vacía, y el rechazo dice que se llame a OCR — que es lo que
un escaneo parseado por su capa de texto siempre necesita.

### OCR { #ocr }

`POST /api/v1/ml/documents/ocr` reconoce el texto de cada página, lleve o no la
página una capa de texto. Esa es la diferencia con la ingesta, que lo
autodetecta y se salta el reconocimiento donde el texto ya está: quien pidió OCR
pidió que las páginas se leyeran como imágenes.

`language` es un código de Tesseract, es decir tres letras — `deu`, no `de`.
`ocr_service_id` nombra un servidor OCR registrado entre los
[servicios locales](configuration.md), de modo que un despliegue con su propio
sidecar de reconocimiento envía allí las páginas; omítelo y las lee el motor
incluido con el parser. En cualquier caso las páginas se quedan en la red del
propio despliegue.

### Transcripción de voz { #speech-to-text }

`POST /api/v1/ml/audio/transcriptions` transcribe una grabación con las
credenciales propias de la organización. `provider` y `model` nombran qué usar, y
omitirlos toma el primer par ofrecido por el despliegue.

El motor es el endpoint que nombre el model profile de la organización para ese
proveedor. Esa es la respuesta para un despliegue que no puede enviar audio a un
proveedor: apunta el profile a un servidor propio que hable la misma API y el
endpoint de aquí no cambia. Una organización sin credenciales utilizables recibe
un rechazo que lo dice — nada se da por existente si un operador no lo ha
configurado.

### Detección de datos personales { #personal-data-detection }

`POST /api/v1/ml/privacy/pii` toma JSON en lugar de un archivo:

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com", "categories": ["email"]}'
```

```json
{
  "counts": [{"category": "email", "count": 1}],
  "total": 1,
  "redacted_text": "write to [redacted:email]"
}
```

Se informa de cada categoría pedida, incluidas las que no encontraron nada —
"buscada y ausente" y "no buscada" son respuestas distintas. Las categorías son
`email`, `iban`, `credit_card` y `us_ssn`, y cada una se empareja por forma y
después se comprueba: Luhn para una tarjeta, ISO 7064 para un IBAN, de modo que
una tira de dígitos no se reporte como una cuenta.

Lo que vuelve son recuentos y el texto redactado, no los desplazamientos de cada
coincidencia. Los detectores responden con texto reescrito, y recuperar las
posiciones supondría copiar su tabla de patrones y sus sumas de comprobación —
una copia que deja de coincidir en silencio con el original es peor que un
contrato más estrecho.

## Qué queda registrado { #what-is-recorded }

Cada llamada deja una fila: qué servicio, qué organización, quién pidió, cuántos
bytes entraron, cuánto salió, cuánto tardó y cómo terminó.
`GET /api/v1/ml/calls` las lee de vuelta, las más recientes primero, y
`GET /api/v1/ml/calls/{id}` lee una.

**No se guarda ningún contenido.** El resultado vuelve en la respuesta y no se
almacena, así que un documento parseado aquí no se convierte en un documento que
este despliegue guarda, y el texto enviado para buscar datos personales no se
retiene en una tabla que nadie pensó como almacén de documentos. El registro de
una llamada hecha por otra organización no se encuentra, igual que cualquier otra
fila de esta API.

El uso se cuenta en la unidad en la que trabaja el servicio — páginas en un
parseo, caracteres en un escaneo — y no en dinero. Los servicios entregados
corren o bien en las máquinas del propio operador, donde no hay precio de
proveedor, o bien en la cuenta de proveedor propia de la organización, que le
factura directamente. Una cifra que nadie puede conciliar con una factura es peor
que un recuento honesto de unidades.

## Límites { #limits }

Una sola llamada acepta hasta `ML_MAX_UPLOAD_SIZE_MB` megabytes, 25 por defecto,
y un escaneo lee como mucho 200000 caracteres. Un llamante puede hacer
`RATE_LIMIT_ML_PER_MINUTE` llamadas por minuto, 30 por defecto, contadas por
llamante y no por dirección.

La ejecución es síncrona: la respuesta es el resultado, y no hay cola que
consultar. Eso es honesto sobre lo que hay aquí en lugar de aspiracional — un
modo encolado añadiría sus propios estados al registro de llamada, que es la
forma en la que llegaría.

## Desplegarlos por separado { #deploying-them-separately }

Los servicios escalan de forma distinta a la consola. Una pasada de OCR son
segundos de CPU en un hilo; servir un dashboard no es ni lo uno ni lo otro. Así
que `deploy/profiles/ml-services/` ejecuta la imagen de la API una segunda vez
como una réplica que solo responde a estas rutas, con sus propios recursos y su
propio escalado, y el ingress de delante enruta `/api/v1/ml/` hacia ella.

Es la misma imagen y la misma base de datos, que es lo que mantiene una sola
implementación al servicio tanto de los agents como de quien llama directamente.
Lo que está separado es el proceso, los límites y el reinicio — que es lo que
pide "desplegado, actualizado y escalado de forma independiente".

`deploy/profiles/ml-services/README.md` describe el overlay y lo que espera.
