---
source_sha: "e2efe341a181"
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
nombre de una persona, una dirección postal — no tienen forma de patrón, así que ninguna expresión regular las encuentra: eso requiere un
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
chunks preparados; las estrategias son `recursive`, `fixed` y `markdown`, y una
cuarta grafía se rechaza en vez de tratarse en silencio como `recursive`.

`chunk_overlap` tiene que ser **menor** que `chunk_size`. Igual se rechaza, y no
por prolijidad: el splitter lo acepta y entonces avanza más o menos un separador
por chunk mientras conserva una copia casi completa del anterior, así que una
subida legítima responde con un documento multiplicado muchas veces.

Un documento del que no se puede leer nada se rechaza en lugar de responderse con
una lista de páginas vacía, y el rechazo dice que se llame a OCR — que es lo que
un escaneo parseado por su capa de texto siempre necesita.

### OCR { #ocr }

`POST /api/v1/ml/documents/ocr` reconoce el texto de cada página, lleve o no la
página una capa de texto. Esa es la diferencia con la ingesta, que lo
autodetecta y se salta el reconocimiento donde el texto ya está: quien pidió OCR
pidió que las páginas se leyeran como imágenes.

`language` es un código de Tesseract, es decir tres letras — `pol`, no `pl`. La
imagen que se distribuye instala **`eng` y `pol`**, y esos dos son los que el
endpoint acepta: un código sin paquete de idioma detrás falla dentro del parseo,
así que se rechaza en la frontera. Un despliegue que instale más paquetes amplía
la lista en el mismo cambio.

`ocr_service_id` nombra un servidor OCR registrado entre los
[servicios locales](configuration.md), de modo que un despliegue con su propio
sidecar de reconocimiento envía allí las páginas; omítelo y las lee el motor
incluido con el parser. En cualquier caso las páginas se quedan en la red del
propio despliegue.

**Un `.docx` se rechaza aquí**, aunque el parser lea uno. La ingesta encamina los
documentos de ofimática al lector nativo antes de consultar el parser de OCR, así
que aceptar uno extraería sus párrafos existentes, se saltaría sus páginas
escaneadas y no diría nada de la diferencia. Conviértelo a PDF.

Una llamada reconoce como mucho **200 páginas** y tiene **120 segundos**, ambos
más estrechos que los de la ingesta, porque aquí alguien espera y a una ingesta no
la espera nadie.

### Transcripción de voz { #speech-to-text }

`POST /api/v1/ml/audio/transcriptions` transcribe una grabación con una clave
del vault de la organización. `provider` y `model` nombran qué usar; omitir
**ambos** toma la configuración por defecto de voz a texto de la organización,
de la [tarjeta Voz (Voice)](console.md#the-voice-card), o el primer par ofrecido
por el despliegue si no la tiene, y nombrar un proveedor sin modelo toma el
primer modelo de ese proveedor. Lo que nunca hace es recurrir al proveedor por
defecto cuando se nombró un proveedor.

Una grabación se somete además al techo propio de 25 MB del cliente de
transcripción aunque `ML_MAX_UPLOAD_SIZE_MB` sea mayor, de modo que una grabación
demasiado grande se rechaza por ser demasiado grande y no llega al motor para
volver como un 503 sobre una clave.

**La clave se nombra, nunca se busca.** `secret_id` nombra la clave del vault con
la que se envía la grabación: una clave de API cuyo propósito es el proveedor y
que quien llama puede ver. Si se omite, se usa la clave por defecto de la
organización, pero solo para el proveedor para el que se eligió; cualquier otro
proveedor sin `secret_id` se rechaza como `not_configured`. Una clave de otro
proveedor, de otro tipo o que quien llama no ve se rechaza en el campo
`secret_id`. La `OPENAI_API_KEY` del despliegue no se usa nunca.

Cada nivel que configura la voz a texto funciona igual: el modelo es una elección
del catálogo de voz a texto y la clave es un secreto del vault nombrado a su
lado. No se lee ningún model profile - los profiles son lo que usa un run de
texto - y nada elige una clave por ser la única de un proveedor. Con dos claves
de OpenAI en el vault, paga la nombrada.

!!! note "Todavía no hay un servidor propio de voz a texto"

    Cada proveedor del catálogo se alcanza en su propia dirección, con una
    clave. Un servidor sin clave en tu propia red - un Whisper detrás de una API
    compatible con OpenAI - no es alcanzable hoy. Es un paso previsto: un
    [servicio local](configuration.md) de un tipo nuevo, `speech`, nombrado en
    lugar de una clave, como las colecciones ya nombran un servidor de
    embeddings o de OCR.

Un rechazo dice por qué en `details.reason`, aquí y en el
[dictado](#dictation-in-chat) por igual. El texto de error del propio proveedor
se registra en el log y nunca se devuelve, porque un cliente de proveedor pone en
su mensaje la URL de la petición, clave incluida.

| `reason` | Estado | Qué ha pasado |
|---|---|---|
| `not_configured` | 503 | No hay una clave utilizable nombrada para el proveedor - no se eligió, se borró o ese nivel ya no puede usarla; en el dictado, también que el dictado en servidor no está configurado |
| `empty` | 400 | El motor no oyó voz, o la grabación no tiene bytes |
| `unsupported_type` | 400 | Solo dictado: la grabación no es WAV PCM de 16 bits, mono y 16 kHz - ni, donde el despliegue acepta audio comprimido, WebM, Ogg o MP4 -, o, en una página alojada o un widget, no se puede leer la duración de una grabación comprimida. `details.accepted` enumera los tipos aceptados |
| `too_large` | 400 | Más de 25 MB, o por encima del límite de dictado de la organización en bytes o en duración medida; `details.limit_seconds` indica el límite |
| `provider_error` | 503 | El proveedor rechazó la petición o falló al atenderla |
| `timeout` | 503 | El proveedor no respondió en 60 segundos |

#### Dictado en el chat { #dictation-in-chat }

`POST /api/v1/agents/{agent_id}/dictation` es el micrófono del
[cuadro de mensaje de `/chat`](console.md#dictation) cuando la organización
transcribe en el servidor. Recibe una grabación como `file` y responde
`{"text": "..."}`, que el cuadro de mensaje inserta para editarlo; nada se envía
hasta que la persona pulsa Enviar. Quien llama no nombra proveedor, modelo ni
idioma —se [resuelven](#which-engine-a-recording-reaches) a partir del agent y
de la organización— y la persona puede dictar a cualquier agent que pueda
ejecutar, incluido un Viewer con un grant `use` sobre él. Un agent que no puede
ejecutar responde 404, como en todas partes.

Lo que lee de la organización, configurado en la
[tarjeta Voice](console.md#the-voice-card) por alguien con `org:settings`:
`chat_dictation` (`off`, `browser` o `server`; todo lo que no sea `server` se
rechaza como `not_configured`), `speech_to_text_provider` y
`speech_to_text_model` (un par del catálogo de speech-to-text),
`speech_to_text_language` (un código ISO-639-1, o null para que el motor lo
detecte) y `dictation_max_seconds` (de 10 a 600, 300 por defecto). El motor y
el dictado más largo son siempre de la organización; el agent solo puede cambiar
el proveedor, el modelo y el idioma.

`GET /api/v1/agents/{agent_id}/dictation`, con el mismo acceso, dice si el
micrófono funcionará antes de que nadie grabe: `engine`, `max_seconds`,
`provider`, `format`, `ready`, `server_available` y `unavailable`.
`server_available` exige un par que se resuelva para este agent, que el catálogo
lo siga ofreciendo y una clave utilizable nombrada junto al par — se comprueba
que existe, nunca se abre; `ready` es eso más el motor `server` y un agent que
no esté archivado.

Cuando es falso, `unavailable` dice qué falta: `no_provider`
(ningún nivel nombra un par), `not_offered` (el catálogo lo retiró) o `no_key`
(no hay una clave utilizable nombrada - elige una). El formulario del embed lee
`server_available`, porque una [página alojada o un widget](channels.md#dictation-on-a-widget-or-a-hosted-page)
no depende del motor de `/chat`.

`provider` es aquel al que llegaría una grabación, y `format` en qué grabar para
él: `wav`, salvo que el despliegue
[acepte audio comprimido](deployment.md#what-a-dictation-may-be-uploaded-as)
y el catálogo de speech-to-text diga que el proveedor admite lo que produce
`MediaRecorder`, en cuyo caso `webm`. Se decide aquí, así que ningún cliente
mantiene una lista propia. Un agent sin nada publicado responde con los ajustes
de la organización.

**Por defecto un dictado es PCM en crudo**: `audio/wav` (o `audio/x-wav`,
`audio/wave`) con PCM entero de 16 bits, mono y 16 kHz, que cualquier navegador
graba desde Web Audio. El archivo se lee de forma estricta - un único chunk
`fmt ` que diga exactamente eso, un único chunk `data` de muestras completas,
tamaños que cuadren con el archivo - y cualquier otro WAV, uno estéreo, de
48 kHz, de 24 bits o de coma flotante incluido, se rechaza como
`unsupported_type`. Al proveedor se le envían las muestras contadas tras una
cabecera que construye el servidor, nunca la cabecera del cliente ni ningún otro
chunk que tuviera el archivo, como `recording.wav`.

Donde el despliegue acepta audio comprimido, se aceptan también `audio/webm`,
`audio/ogg` y `audio/mp4`, con sufijo de códec permitido, y `audio/x-m4a` y
`audio/m4a` se leen como `audio/mp4`, y `audio/opus` y `audio/x-ogg` como
`audio/ogg`. Son lo que produce el `MediaRecorder` de los navegadores, y el
proveedor los recibe como `recording.webm`, `recording.ogg` o `recording.m4a`,
según la misma tabla que nombra `voice.<ext>` a una nota de voz de un canal.

La ruta lee como mucho 25 MB del cuerpo; el límite de bytes de la organización -
los bytes que ocupan `dictation_max_seconds` más tres segundos de PCM, 32.000 por
segundo, y 4 KB para el contenedor - se aplica a lo leído. Un cuerpo que el límite
de peticiones del despliegue rechaza antes de que la ruta se ejecute recibe un
413 sin `reason`, que el cuadro de mensaje lee como `too_large`.

Después **se mide la duración** antes de llamar al proveedor, y una grabación
más larga que `dictation_max_seconds` se rechaza como `too_large`, con tres
segundos de margen porque el cuadro de mensaje la detiene cada segundo. En PCM
la duración son las muestras contadas, exactamente. La de una grabación comprimida se lee de su propia cabecera - la última página Ogg, las
marcas de tiempo de los bloques WebM, las cabeceras de película o de fragmento
de MP4 -, que un archivo hecho a mano puede falsear a la baja. Una cuya
duración no se puede leer se acepta aquí, dentro del límite de bytes;
[una página alojada o un widget](channels.md#what-it-costs-and-what-bounds-it)
la rechaza.

Cada persona puede dictar `RATE_LIMIT_DICTATION_PER_MINUTE` veces por minuto, 10
por defecto, en un contador propio, así que dictar no gasta la cuota de ML de una
integración. Cada dictado deja un [registro de llamada](#what-is-recorded), bajo
`speech_to_text` y contado en segundos de audio - en PCM, la duración contada.
El compositor envía la duración que grabó como campo de formulario `duration`
junto a `file`, que solo se usa para una grabación comprimida cuya duración no
indica nada más.

**El audio nunca se guarda**: se
descarta cuando la llamada vuelve, y el texto solo existe en la respuesta.
Cancelar en el navegador no cancela una grabación ya enviada: el proveedor la
transcribe igualmente, la cobra a la cuenta de la organización, y la llamada
queda registrada.

!!! note "Con Mistral el navegador graba siempre WAV, y se transcriben menos idiomas"

    Mistral documenta entrada WAV y MP3 para Voxtral, no WebM ni Opus, que es lo
    que graban Chrome y Firefox. Por eso, cuando el proveedor al que se resuelve
    una grabación es Mistral, el cuadro de mensaje graba en su lugar
    WAV de 16 kHz, mono y 16 bits en todos los navegadores, incluso donde el
    despliegue acepta audio comprimido. Una subida PCM pesa más o menos el doble
    que el WebM al que sustituye —32.000 bytes por segundo—, y el límite de
    duración es el mismo.

    La lista de idiomas es la de Whisper, que aceptan OpenAI y Groq. Mistral
    indica 13 idiomas para Voxtral, así que un idioma fijado que no acepte
    vuelve como `provider_error`. En Mistral, deja el idioma en detección
    automática y prueba una grabación antes de confiar en ello.

#### A qué motor llega una grabación { #which-engine-a-recording-reaches }

Tres sitios pueden nombrar un motor de speech-to-text: la
[tarjeta Voice](console.md#the-voice-card) de la organización, la anulación
[`speech_to_text`](reference/spec.md#speech-to-text) de un agent, configurada en
su propia [tarjeta Voice](console.md#an-agents-own-engine) y en vigor una vez
publicada, y un [bot de canal](channels.md#what-every-channel-shares). Se
resuelven en dos mitades:

| Qué | Viene del primero que lo fija |
|---|---|
| Proveedor, modelo y clave, juntos | El bot, después el agent, después la organización |
| Idioma | El agent, después la organización, después lo detecta el motor |

**La clave viaja con su par.** Cada nivel nombra una clave junto a su propio
proveedor y modelo, y los tres se resuelven como una unidad: un agent con par
propio lo envía con su propia clave, nunca con la de la organización. Así una
clave nunca llega a un proveedor que no la emitió. Qué claves puede nombrar cada
nivel:

| Nivel | La clave tiene que ser |
|---|---|
| La configuración por defecto de la organización | Una clave de API del proveedor, **visible para toda la organización** - la plataforma la gasta por todos. Se comprueba al guardar la tarjeta Voz y otra vez en cada grabación |
| El par propio de un bot de canal | Lo mismo: visible para la organización, porque las notas de voz de un bot se pagan en nombre de quien le escriba |
| La sobrescritura de un agent | Una clave de API del proveedor que quien publica pueda ver, la regla que sigue toda clave nombrada en una spec de agent. Se comprueba al publicar |

Una clave que se vuelve privada después de elegirse en la organización o en un
bot deja de usarse, en lugar de seguir pagando las grabaciones de otros. Una
clave borrada vacía la referencia en esos dos niveles, y la spec de un agent
conserva el id hasta que se vuelva a publicar con otra: en ambos casos la
tarjeta Voz y la comprobación de disponibilidad dicen «elige una clave», y las
grabaciones se rechazan como `not_configured` hasta que alguien lo haga.

Así, un agent en polaco dentro de una organización configurada para inglés fija
`language: pl` y conserva el proveedor y la clave de la organización. Un bot no tiene idioma
propio; el del agent o el de la organización se aplica también a su propio par.
Que no se resuelva nada significa que no se transcribe nada: el dictado responde
`not_configured`, y un bot dice que no puede escuchar.

El dictado lee la versión publicada por defecto del agent, la que ejecuta
`/chat`. Un bot lee el agent al que sirve su vinculación —nunca un agent que
alguien menciona con `@slug`, porque una grabación se transcribe antes de que se
enruten las menciones— en la versión que fija el entorno de esa vinculación, la
que usará el run. Un agent en borrador o archivado no tiene ninguna versión que
alguien ejecute, y responde solo la organización.

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
`email`, `iban`, `credit_card`, `us_ssn` y `phone`, y cada una se empareja por
forma y después se comprueba: Luhn para una tarjeta, ISO 7064 para un IBAN, el
plan de numeración del país y la agrupación de los dígitos para un número de
teléfono, de modo que una tira de dígitos no se reporte como una cuenta ni como
un número.

Un número de teléfono escrito con `+` se encuentra sea cual sea su país; uno
nacional, como `415-555-0132`, se lee frente a los países por defecto de los
guardrails, `US, GB, DE, PL`. El campo `phone_regions`, que cambia esa lista,
pertenece a los guardrails de un agente, no a este endpoint.

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

Una llamada rechazada también queda registrada, y su fila se confirma antes de que
el rechazo desenrolle la petición: una fila meramente añadida a esa transacción
sería deshecha por el propio rechazo que describe, y a un operador que pregunta por
qué falla una integración se le diría que el tenant no hizo ninguna llamada.

**No se guarda ningún contenido.** El resultado vuelve en la respuesta y no se
almacena, así que un documento parseado aquí no se convierte en un documento que
este despliegue guarda, y el texto enviado para buscar datos personales no se
retiene en una tabla que nadie pensó como almacén de documentos. El registro de
una llamada hecha por otra organización no se encuentra, igual que cualquier otra
fila de esta API.

El uso se cuenta en la unidad en la que trabaja el servicio — páginas en un
parseo, caracteres en un escaneo, segundos de audio en una transcripción — y no
en dinero. Los servicios entregados corren o bien en las máquinas del propio
operador, donde no hay precio de proveedor, o bien en la cuenta de proveedor
propia de la organización, que le factura directamente. Una cifra que nadie
puede conciliar con una factura es peor que un recuento honesto de unidades. La
transcripción tampoco cuenta contra el [budget](governance.md#budgets) de un
agent.

### Transcripciones { #transcriptions }

A la voz a texto se llega por tres caminos, y cada uno deja la misma fila: la API (`surface: api`), el [dictado](#dictation-in-chat) (`chat`) y
los [mensajes de voz de un bot de canal](channels.md#what-every-channel-shares)
(`channel`). La fila añade el `provider` y el `model`, el `secret_id` de la clave
del vault con la que se envió - igual que un run registra su clave, para que
«qué clave cuesta más» tenga una sola respuesta -, el `agent_id` para el que fue
- el agent al que se dictó, o el agent al que sirve el bot -, el
`channel_bot_id` y `audio_ms`, la duración de la grabación.

Borrar la clave
conserva la fila y vacía su `secret_id`. El `requested_by` de
un mensaje de voz es la persona con la que está vinculado el remitente mientras
siga siendo miembro de la organización, o nadie.

Solo se registra una grabación entregada al proveedor; un bot desactivado o sin
motor que heredar no preguntó a nadie.

La duración es la primera de estas que se conoce:

| Fuente | Quién la da |
|---|---|
| La propia grabación | Solo el dictado: la duración leída de su contenedor, como arriba |
| La respuesta del proveedor | OpenAI `whisper-1` (`usage.seconds`), Groq (`duration`, pedida con `response_format=verbose_json`), Mistral (`usage.prompt_audio_seconds`) |
| Los metadatos de la plataforma | Una nota de voz o un archivo de audio de Telegram, un clip de Slack |
| El navegador | Solo el dictado: la `duration` que envía el compositor, recortada al dictado más largo de la organización, porque es la palabra del cliente |

`gpt-4o-transcribe` y `gpt-4o-mini-transcribe` de OpenAI informan tokens, no
segundos, y Mattermost no indica duración, así que un mensaje de voz allí con
esos modelos no la tiene. Una fila con éxito cuenta entonces `0` segundos con
`audio_ms` nulo - sin medir, no en silencio.

`GET /api/v1/ml/calls` filtra también por `agent_id`, `channel_bot_id`,
`surface`, `since` y `until`, además de `ml_service`, siempre dentro de la
organización de quien llama: el id de un agent de otro tenant no coincide con
nada. El agent, el bot y el camino - como filtros y como columnas - piden
`runs:view`, como el resumen de abajo. Con `ml:invoke` solo, un filtro por ellos
se rechaza con 403 y los tres vuelven nulos en cada fila.

`GET /api/v1/ml/calls/summary?days=30` suma las transcripciones con éxito en
una ventana: `seconds` - las `units` propias de cada fila, la grabación
redondeada hacia arriba al segundo, sumadas, para que el resumen coincida con la
lista - y `count`, `count_unknown_length` para las grabaciones que los segundos
dejan fuera, y lo mismo por agent, por bot de canal y por camino
(`surface`). Pide `runs:view`, como
[`GET /spend`](governance.md#what-the-cost-screen-shows), en lugar de
`ml:invoke`: el desglose nombra agents y bots que un Member puede no ver. La
[tarjeta Voice](console.md#the-voice-card) de la organización lo muestra en una
línea.

## Límites { #limits }

Una sola llamada acepta hasta `ML_MAX_UPLOAD_SIZE_MB` megabytes, 25 por defecto,
y solo esa cantidad de bytes se lee del cuerpo: una entrega demasiado grande se
rechaza sin haberse copiado antes a memoria. Un escaneo lee como mucho 200000
caracteres, y un escaneo que incluye `phone` como mucho 10.000 dígitos: buscar
números de teléfono cuesta decenas de microsegundos por dígito, así que un texto
más largo se rechaza en lugar de leerse. Un llamante puede hacer `RATE_LIMIT_ML_PER_MINUTE` llamadas por
minuto, 30 por defecto, contadas por llamante y no por dirección.

Un límite de tasa cuenta **arranques** y no ve lo que sigue en marcha, que es la
forma equivocada para un trabajo medido en minutos. Por eso un worker parsea como
mucho `ML_MAX_CONCURRENT_PARSES` documentos a la vez, 4 por defecto, y una llamada
que llega con todas las plazas ocupadas se rechaza con un `Retry-After` en lugar
de encolarse: a quien se le dice que vuelva en un momento puede volver, y quien
queda aparcado detrás de cuatro escaneos ya se ha rendido en algún sitio que aquí
nadie ve.

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
