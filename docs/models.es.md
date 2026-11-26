---
source_sha: "b4f01f7af48e"
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

## Claves personales de modelos { #personal-model-keys }

En **Model access** del Builder, conserva **Use the organization’s key** (predeterminado) o selecciona **Each user connects their own key**. El formulario de clave privada envía el perfil, provider, endpoint y modelo esperados que vio el usuario. Si el destino cambia antes de guardar, el servidor rechaza la clave con un conflicto; el formulario recarga el destino y borra la clave escrita antes de otro intento.

El modo personal mantiene fijos el modelo y el destino del administrador. Admite proveedores de chat con clave API, sin modelos alternativos ni cambios de modelo por conversación.

Un miembro con sesión iniciada conecta su clave en el formulario privado sobre el campo de mensajes o en los ajustes del chat. Las claves nunca entran en mensajes, prompts ni instrucciones del agente. La conexión se reutiliza entre agentes de esta organización con el mismo proveedor y destino. Sin clave, la ejecución se bloquea antes de solicitar el modelo; los fallos de autenticación nunca cambian a la clave de la organización. Sustituye la clave en los ajustes del chat o elimina la conexión en **Vault → Your model connection**. Guardar la clave no la comprueba con el proveedor.

El modo personal no admite canales privados ni grupales, widgets, páginas públicas, ejecuciones por HTTP API, horarios, triggers, temas en segundo plano, voz, revisores ni modelos separados para capacidades. Pausa o elimina canales, superficies públicas y rutinas activos antes de publicar. Se rechaza crear o reactivar una superficie incompatible; la misma regla se aplica al ejecutar. Las páginas públicas y los JWT de widgets no identifican a un miembro con sesión iniciada en la instancia.

La delegación funciona en el chat web con sesión iniciada. Un subagente personal debe usar el mismo perfil de modelo que el agente principal en modo personal. Un agente principal con claves de organización no puede gastar claves personales mediante delegación; los subagentes personales no pueden elegir otro modelo ni endpoint. Estas reglas se comprueban al publicar, habilitar superficies, promover versiones y ejecutar, incluidas las delegaciones anidadas y las reanudaciones.

Los subagentes de organización conservan sus credenciales. Los especialistas inline heredan el modo del padre; los dinámicos en modo personal mantienen su modelo. Los límites de acceso MCP personal no cambian.

Si falta la conexión de un subagente, el mensaje identifica el agente y la conexión del modelo. Abre la configuración de chat de ese agente para conectar tu clave; pide acceso a su propietario si no aparece. El runner comprueba el árbol de delegación antes de llamar a los modelos y de nuevo al reanudar. Nunca sustituye una conexión ausente por la clave de otro endpoint, otro miembro o la persona que aprueba.

Las claves se cifran para su propietario en el almacén y se eliminan al borrar su membresía o cuenta. Cambiar el destino aprobado requiere una nueva conexión. Rotar la clave de un miembro no cambia las claves de otros ni el perfil de modelo compartido.

Suplantar la identidad de otro miembro no concede acceso a sus conexiones personales de modelos: las solicitudes de lectura, modificación o uso de la clave se rechazan antes de acceder al vault.

El historial privado queda vinculado a los destinos aprobados de los modelos, incluidos los de respaldo; consulte el [historial del chat](console.md#chat) para cambiar conexiones y reanudar ejecuciones en espera.

## Un perfil de modelo { #a-model-profile }

Una fila dentro de una organización: una etiqueta, un provider, un id de modelo,
ajustes por defecto y con qué [secreto del vault](secrets.md) autenticarse.

El spec de un agent nombra uno con `model_profile_id`, y el run lo resuelve.

!!! tip "El id de modelo es texto libre a propósito"

    Hay un selector que ayuda, pero el campo acepta cualquier cosa que escribas.

    Un provider publica algo la mañana siguiente a que se calentara cualquier
    lista de aquí, y un campo que no puede expresar «ese» es un campo que la
    gente esquiva editando el spec a mano.

### Un perfil en el que un agent no puede ejecutarse { #a-profile-an-agent-cannot-run-on }

Un perfil puede nombrar un modelo que no mantiene una conversación: un modelo de
texto a voz como `gpt-4o-mini-tts`, un modelo de voz en tiempo real, un modelo de
transcripción, un modelo de
imágenes, un modelo de vídeo o un modelo de embeddings. Un agent en uno de ellos
falla en su primer turno. El texto a voz, la generación de imágenes y la
transcripción no usan perfiles: cada función nombra su propio provider y su propio
modelo.

La plataforma conoce estos modelos por sus propios catálogos (las listas de texto
a voz, voz en tiempo real, transcripción, imágenes, vídeo y embeddings).
`GET /providers/model-profiles` marca cada perfil con `chat_capable` y
`output_modalities`, y `GET /providers/{provider}/models` marca cada sugerencia
con `chat_capable`. Esos dos campos también leen el listado de un provider que
indica qué emite cada modelo (OpenRouter y el router de Hugging Face lo hacen),
cuando el proceso de la API ya lo ha obtenido. Ese listado solo cambia lo que
ofrece un selector. Nunca rechaza una publicación, porque otro proceso de la API
puede no haberlo obtenido.

La consola también actualiza los perfiles guardados
cuando el listado llega después. Los alias de provider como `openai_codex` y
`google_cloud` usan los catálogos del proveedor correspondiente. Entonces:

- El panel de modelo del Builder, los selectores de revisor y de especialista, los
  campos del modelo de los pasos siguientes y del modelo de pasos del navegador y
  el selector del modelo que describe imágenes en la base de conocimiento no
  ofrecen un modelo así. Si un agent ya nombra uno, el Builder lo sigue mostrando,
  marcado como un modelo que no es de chat. A un miembro que gestiona conexiones,
  el Builder también le lista los demás, marcados y sin poder elegirse, para que
  se puedan eliminar.
- El selector de modelo del chat y el formulario para añadir un modelo del Builder
  no sugieren un modelo así y rechazan uno escrito a mano.
- La publicación rechaza un modelo así como modelo del agent, de un revisor o de
  un especialista, como modelo de pasos del navegador o como modelo de los pasos
  siguientes, y lo nombra. También rechaza un perfil cuyos fallbacks incluyen un
  modelo así. La misma comprobación se ejecuta al volver a una versión, en la
  comprobación del borrador, en la prueba del Builder y al activar una capability
  desde el chat. Una versión guardada en un modelo así sigue cargándose, pero no se
  puede restaurar mientras su perfil nombre un modelo que no es de chat o lo liste
  como fallback. Apunta ese perfil a un modelo de chat o publica una versión nueva.
- Un run deja un fallback así fuera de su cadena, igual que uno eliminado, cuando
  se añadió al perfil después de publicar.
- Una conversación que nombra un modelo así en lugar del modelo del agent, desde
  el chat o a través de la API, se rechaza antes de que empiece el run.
- Un modelo que los catálogos no clasifican, como un modelo de Ollama o un modelo
  publicado esta mañana, está permitido. Un modelo desconocido no es un rechazo.
  Un perfil con su propio endpoint (`base_url`) nunca se clasifica, sea cual sea
  el id del modelo: los catálogos describen la API propia del provider, y un
  servidor compatible con OpenAI puede servir un modelo de chat con cualquier
  nombre.

El selector de modelo de proactividad sigue la misma regla. La comprobación de los
catálogos estables también se aplica al configurar la proactividad y al resolver
un perfil para una petición de texto normal, incluida la descripción de imágenes
al configurar y en el worker. Las configuraciones antiguas siguen cargándose;
hay que sustituir un modelo incompatible antes de usarlas. Sigue siendo posible
desactivar la función. Los nombres de despliegues de Azure no se clasifican a
partir de los identificadores de modelos base del catálogo.

### El modelo con el que empieza un agent nuevo { #the-model-a-new-agent-starts-on }

No hay un modelo predeterminado para toda la organización. El spec de un agent
nombra su modelo, y la publicación rechaza un spec que no nombra ninguno.

Un agent nuevo que no nombra un modelo empieza con el modelo de la organización
cuando la organización tiene exactamente un modelo en el que un agent puede
ejecutarse. Es un modelo de chat con clave, o uno autoalojado guardado para
ejecutarse sin clave, que la publicación acepta tal como está, fallbacks incluidos.
Se aplica a todas las formas de crear un agent: **New agent** en la consola, `POST
/agents` sin `model_profile_id`, una plantilla, una copia de un borrador sin modelo
y un especialista promovido.

El Architect, el asistente de la organización, elige su propio modelo al publicarse:
el primer modelo de chat que la publicación acepta, y nunca un modelo con un [inicio
de sesión de ChatGPT](#running-on-a-chatgpt-subscription). El Architect sirve a toda
la organización, y un inicio de sesión es la suscripción de una persona: las
ejecuciones de los miembros que no pueden verlo en el vault se rechazan, y las de
quienes sí pueden, como los propietarios y administradores de la organización, la
gastan. Con solo un inicio de sesión, el Architect espera a otro modelo.

Un inicio de sesión que alguien elige en su borrador, o un modelo con un fallback
a uno, se queda ahí, pero solo se publica cuando alguien que puede cambiar la configuración de la organización lo
publica en el Builder. Un Architect ya publicado con un inicio de sesión conserva
ese modelo hasta que alguien que puede cambiar la configuración de la organización
elige otro en **Build > Model** y lo publica.

El modelo se escribe en el borrador, así que el agent se publica sin que nadie abra
**Model**, y su historial muestra con qué modelo se publicó. Un spec que nombra un
modelo lo conserva. El borrador cuenta entonces como uso del modelo: el modelo no se
puede borrar hasta que el agent pase a otro modelo o se borre; archivarlo no basta.
Para cambiar solo la clave o el endpoint del modelo, edítalo en su sitio ([Cambiar
la clave o el endpoint de un perfil](#changing-a-profiles-key-or-endpoint)).

El borrador se queda sin modelo cuando la organización no tiene ninguno o tiene más
de uno. Los perfiles en los que un agent no puede ejecutarse no cuentan: un perfil
sin clave, un modelo de texto a voz y los demás modelos de [Un perfil en el que un
agent no puede ejecutarse](#a-profile-an-agent-cannot-run-on), ni un perfil que la
publicación rechazaría, como uno con un fallback a uno de esos modelos. Un modelo con un
[inicio de sesión de ChatGPT](#running-on-a-chatgpt-subscription) nunca se elige en
nombre de nadie, porque es la suscripción de una persona, pero cuenta como modelo.

Tampoco se elige un modelo cuyos fallbacks incluyen un inicio de sesión entre los
tres primeros, los que prueba un run: cuando el modelo falla, el run de cualquiera
que pueda ver el inicio de sesión pasaría a esa suscripción. El Architect tampoco
elige un modelo así. Un autor todavía puede elegirlo a
propósito y publicarlo.

La publicación rechaza entonces el borrador con *No model selected - pick one under
Build > Model before publishing*. El rechazo también marca el campo
(`model_profile_id` en `details.fields`), y la consola muestra al lado **Go to
Model**, que abre la pestaña **Build** en la tarjeta **Model**.

### Cambiar la clave o el endpoint de un perfil { #changing-a-profiles-key-or-endpoint }

Los agents nombran un perfil por su id. Para mover un modelo a otra clave, otro
endpoint u otra API de OpenAI, edita el perfil en su sitio:
`PATCH /providers/model-profiles/{id}` cambia `secret_id`, `base_url`, `api`,
`params` o `label` y conserva el id. Cada agent sobre el perfil usa el cambio
desde su siguiente run. Nadie tiene que volver a publicar nada.

En el panel de modelo del Builder, cambia la clave, el endpoint o la API del
modelo en uso. El botón pasa a decir **Update model**, y el panel indica que cada
agent sobre este modelo cambia con él. **Add model** sigue siendo el botón para
otro provider u otro modelo, y para un modelo al que das un nombre propio. Usa
**Name it something else** para dar solo a este agent un modelo aparte.

Una edición sigue las mismas reglas que la creación y necesita el mismo permiso
`connections:manage`. Una clave nueva debe estar en el vault de esta
organización, ser visible para ti y estar guardada para el provider del perfil.
Un endpoint nuevo comprueba la clave guardada del mismo modo, porque el endpoint
es adonde se envía la clave. Un provider que necesita clave no puede perderla. Un
provider keyless sin clave conserva un endpoint. La etiqueta debe seguir siendo
única.

Si cambias el endpoint y no envías `api`, una API que solo era la
predeterminada del endpoint anterior pasa a la predeterminada del nuevo, y una
API elegida a propósito se mantiene. El registro de auditoría guarda
`model_profile.updated` con los nombres de los campos cambiados, no sus valores.
No puedes cambiar el provider ni el id del modelo. Otro modelo es otro perfil.

`connections:manage` es, por tanto, la autoridad para mover a cada agent sobre un
modelo, incluidos los agents que no puedes editar: un endpoint nuevo recibe sus
peticiones desde el siguiente run. Concédelo a quienes gestionan los modelos de
la organización.

### Un perfil sin clave { #a-profile-without-a-key }

Si borras una clave del vault, sus perfiles se quedan con `secret_id` a null.
`GET /providers/model-profiles` los marca con `missing_key: true`. Un perfil
guardado sin clave a propósito es otra cosa: un modelo autoalojado o un gateway
que no autentica nada, en un provider keyless con endpoint, como un Ollama en tu
red o un servidor compatible con OpenAI. Lo registra como `runs_without_key` y
sigue ejecutándose. Un perfil de gateway que tenía clave y la perdió se marca con
`missing_key` como cualquier otro. Entonces:

- Los selectores de modelo del agent y del chat no lo ofrecen. Si un agent ya lo
  nombra, el Builder lo muestra con la marca **no key** y te pide que le des una
  clave.
- La publicación lo rechaza y nombra el modelo. También rechaza un perfil cuyos
  tres primeros fallbacks incluyen uno sin clave, porque un run lo saltaría. Un run sobre él falla con
  "no key configured".
- Para repararlo, abre un agent sobre ese modelo, elige una clave en **Model** y
  pulsa **Update model**. Cada agent sobre el modelo vuelve a funcionar.

### Borrar un perfil { #deleting-a-profile }

`DELETE /providers/model-profiles/{id}` rechaza un perfil que usan agents. La
respuesta es `409 IN_USE`, y `details.agents` lista cada agent que puedes ver, con
id y nombre. `details.hidden_agents` cuenta los agents que no puedes ver. Un
perfil está en uso cuando el borrador de un agent, su versión servida o una
versión que fija un entorno nombra el perfil en cualquier lugar: como modelo del
agent, de un revisor o de un especialista, o en una capability, como el modelo de
follow-ups o el modelo de los pasos del navegador.

Los agents archivados cuentan,
porque desarchivarlos restaura la versión que servían. El rechazo los marca con
`archived`: un agent archivado no puede publicar, así que bórralo, o
restáuralo y muévelo. Las versiones antiguas que nada sirve no cuentan. Mueve
primero los demás agents a otro modelo. Para cambiar solo la clave, edita el perfil.

### Fallbacks { #fallbacks }

El runner usa solo los tres primeros fallbacks; solo esos se comprueban al publicar.

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

**El caché de prompts está activado por defecto**, mediante el ajuste `cache` de
Pydantic AI, neutral respecto al proveedor. Cada petición de un run vuelve a enviar
las instrucciones, los esquemas de herramientas y todo el historial, así que el
prefijo estable y la conversación se marcan como puntos de caché y cada petición
lee la anterior desde la caché. Se aplica donde un proveedor admite caché
explícita - Anthropic, los modelos Anthropic y Nova de Bedrock, los modelos
Anthropic y Gemini de OpenRouter, OpenAI desde GPT-5.6 - y no cambia nada en uno
que cachea por su cuenta, como Google. Un perfil lo apaga con `cache: false`, o
cachea solo instrucciones y herramientas con `cache: {"messages": false}`. Un
indicador propio de un proveedor que el perfil ya fija, como
`anthropic_cache_messages`, sigue mandando para ese perfil.

El resumen diario, las sugerencias y el mantenimiento de memoria muestran estos
valores y el esfuerzo de razonamiento en el selector de modelo de la organización.
Los cambios se guardan explícitamente en el perfil compartido y afectan a todos
sus consumidores. Los controles sin configurar no envían una modificación; deja
los parámetros no admitidos con los valores del proveedor. Los agents pueden
modificar el esfuerzo mediante [la capability `thinking`](reference/capabilities.md#thinking),
que utiliza el ajuste independiente del proveedor de Pydantic AI. Los roles en
segundo plano no tienen spec de agent y usan directamente el `thinking` del perfil.

### Responses o Chat Completions { #responses-or-chat-completions }

OpenAI publica dos APIs para los mismos modelos, y un perfil en `openai`,
`azure` o `stav` guarda a cuál de ellas van sus peticiones: `responses` o `chat`. Cualquier
otro provider sirve una sola API y aquí no guarda nada.

Ninguna es la correcta en todas partes. Los modelos más nuevos de OpenAI solo se
sirven por Responses y a Chat Completions responden con un 400, mientras que la
mayoría de los servidores compatibles con OpenAI - vLLM, LM Studio, un proxy de
LiteLLM - solo implementan Chat Completions. Por eso la elección es un campo del
perfil, en **Agents → add a model → API**, y el formulario empieza en el valor
por defecto:

| Perfil | Por defecto |
|---|---|
| `openai`, sin endpoint (la API propia de OpenAI) | `responses` |
| `openai` con endpoint | `chat` |
| `azure` | `chat`, porque la Responses API necesita una `api_version` reciente y el secreto puede fijar una anterior |
| `stav` | del modelo: `chat` donde se sirve, si no `responses` |

El valor por defecto es solo donde empieza el formulario. Un endpoint regional de
OpenAI como `https://eu.api.openai.com/v1` es un endpoint que sirve Responses, así
que elígela ahí. Una elección omitida se guarda como su valor por defecto, así que
cambiar el valor por defecto más adelante no mueve un perfil existente.

**Un perfil en Responses no deja conversaciones en OpenAI.** La Responses API
guarda cada respuesta del lado de OpenAI salvo que se le indique lo contrario,
mientras que Chat Completions no guarda nada por defecto, así que un modelo en
Responses envía `store: false`. El razonamiento pasa entre turnos como contenido
cifrado y no mediante un id de respuesta guardado, así que nada necesita la copia
guardada. Un perfil que la quiera pone `openai_store` a `true` en sus ajustes.

### Dónde se ejecutan las peticiones de un perfil de Stav { #where-a-stav-profiles-requests-run }

Un perfil en `stav` guarda una región: `eu`, `eea` o `global`. Stav responde solo
desde endpoints que calculan en esa región, solo conmuta por error dentro de ella
y rechaza una petición que no puede servir allí. `global` no pone ningún límite
propio. La región solo reduce lo que permite la política del workspace de Stav.

Se configura en **Agents → add a model → Region**. El formulario empieza en `eu`, y
una región omitida se guarda como `eu`, así que un perfil solo sale de la UE si se
guardó con `eea` o `global`.

La región se envía en cada petición como la cabecera `X-Stav-Runs-In`, no en el
cuerpo, así que un `extra_body` en los ajustes del perfil no puede sustituirla.

Un catálogo personalizado de Stav utiliza la clave del vault seleccionada en el formulario. El usuario debe tener acceso a esa clave; nunca se elige una clave oculta de la organización para una URL personalizada. La caché de catálogos autenticados se separa por credencial. Los `extra_headers` de una solicitud no pueden reemplazar la restricción EU o EEA del perfil.

### Gateway Otari { #otari-gateway }

Selecciona **Otari** al añadir un modelo, guarda una clave API de Otari en el vault y selecciónala en el perfil. **Endpoint** es obligatorio: introduce `https://api.otari.ai/api/v1` para Otari alojado. Para una cuenta de Otari en la región UE, configura `https://eu.api.otari.ai/api/v1`; para un gateway autogestionado, usa su raíz API terminada en `/api/v1`, accesible desde la API y los workers.

Después de elegir el endpoint y la clave, pulsa **Load models**. Cualquier cambio requiere confirmar de nuevo el destino; escribir una dirección no envía la clave.

Las sugerencias de modelos proceden del endpoint autenticado `/models` de ese gateway con la clave seleccionada. Un endpoint personalizado requiere `connections:manage` y acceso a esa clave. La caché se separa por endpoint y credencial; un fallo del catálogo personalizado nunca lo sustituye por el alojado. El campo de modelo también acepta un selector como `anthropic:claude-sonnet-4-6`, o un alias o política de routing configurados en Otari.

La integración utiliza [`pydantic-ai-otari`](https://github.com/mozilla-ai/otari/tree/main/integrations/pydantic-ai-otari): `OtariProvider` entrega el perfil de la familia del modelo al modelo Chat Completions de Pydantic AI, igual que `OtariModel`. Las peticiones siempre usan Chat Completions; el formulario no ofrece Responses ni los controles regionales de Stav. La clave y el endpoint se pasan explícitamente desde el perfil, sin recurrir a las variables `OTARI_*` o `OPENAI_API_KEY`. Los presupuestos y el routing del gateway Otari son controles adicionales; AgenticOS mantiene sus propios presupuestos y aprobaciones.

Los selectores directos `provider:model` usan el precio de catálogo del proveedor para los presupuestos de AgenticOS; los alias de routing sin prefijo y los modelos desconocidos siguen registrados como parcialmente valorados. Son estimaciones de precios del proveedor: consulta los cargos del gateway en la vista de uso de Otari.

## Providers { #providers }

Providers de chat compatibles con Pydantic AI, además de Otari mediante su paquete de integración, Stav con routing regional y MiniMax mediante su API compatible.

Los providers estándar usan la inferencia de modelos y providers de Pydantic AI. La plataforma describe la forma de las credenciales e integra paquetes de providers cuando es necesario.

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
| TypeSafe (Jev) | `typesafe` | API key | ✓ |
| OpenRouter | `openrouter` | clave de API |  ✓ |
| Otari | `otari` | clave de API | ✓ |
| Alibaba Cloud | `alibaba` | clave de API | ✓ |
| Cerebras | `cerebras` | clave de API | |
| DeepSeek | `deepseek` | clave de API | |
| Fireworks AI | `fireworks` | clave de API | |
| GitHub Models | `github` | clave de API | |
| GitHub Copilot | `github_copilot` | token de cuenta / inicio personal | |
| Groq | `groq` | clave de API | |
| Heroku AI | `heroku` | clave de API | ✓ |
| LLMTR | `llmtr` | clave de API | |
| Mistral | `mistral` | clave de API | |
| MiniMax | `minimax` | clave de API | ✓ |
| Kimi Code (plan) | `kimi_code` | clave de API | ✓ |
| Alibaba Coding Plan | `alibaba_coding_plan` | clave de API | ✓ |
| OpenCode Go | `opencode_go` | clave de API | ✓ |
| Ollama Cloud | `ollama_cloud` | clave de API | ✓ |
| Nous Portal | `nous_portal` | clave de API | ✓ |
| Inception | `inception` | clave de API | ✓ |
| Cline | `cline` | clave de API | ✓ |
| Chutes | `chutes` | clave de API | ✓ |
| Synthetic | `synthetic` | clave de API | ✓ |
| CLIProxyAPI (subscription gateway) | `cliproxyapi` | clave de API | ✓ |
| Moonshot AI | `moonshotai` | clave de API | |
| Nebius AI Studio | `nebius` | clave de API | |
| OVHcloud AI Endpoints | `ovhcloud` | clave de API | |
| SambaNova | `sambanova` | clave de API | ✓ |
| Stav.ai | `stav` | clave de API | ✓ |
| Together AI | `together` | clave de API | |
| Vercel AI Gateway | `vercel` | clave de API | |
| Z.AI | `zai` | clave de API | ✓ |
| xAI (Grok) | `xai` | clave de API | ✓ (`api_host`) |
| Cohere | `cohere` | clave de API | |
| Hugging Face | `huggingface` | clave de API | ✓ |

LLMTR solo muestra modelos que anuncian `CHAT_COMPLETIONS`. Un modelo sin precio revisado en el snapshot incluido solo puede ejecutarse sin un límite activo en dólares; su coste sigue marcado como incompleto. Con un límite activo también se rechazan nuevas llamadas a LLMTR si el coste del uso anterior es desconocido.

Selecciona **MiniMax** para su API Chat Completions compatible con OpenAI. Guarda la clave API de M Plan como clave MiniMax en el almacén; una clave API de pago por uso utiliza su propia facturación. Un Endpoint vacío usa `https://api.minimax.io/v1`; configura otro solo para la región o el gateway de tu clave. Escribe el ID exacto del modelo de tu cuenta, por ejemplo `MiniMax-M3.1-Flash`; esta integración no enumera un catálogo del plan. El historial MiniMax tiene identidad propia y no recibe razonamiento cifrado de OpenAI. Los precios conocidos de tokens estiman el presupuesto, no la factura de suscripción.

Para un **Z.AI GLM Coding Plan**, selecciona **Z.AI** y configura **Endpoint** explícitamente como `https://api.z.ai/api/coding/paas/v4` (global) o `https://open.bigmodel.cn/api/coding/paas/v4` (China), con una clave del plan y la región correspondientes. Un Endpoint vacío conserva la API habitual facturada por uso; los perfiles existentes no cambian.

**Claves de planes de suscripción.** Cuatro providers más facturan un plan de suscripción mediante una clave del plan para un endpoint compatible con OpenAI. Guarda la clave del plan con el propósito correspondiente de la bóveda; la lista de modelos procede del catálogo de esa clave, y un Endpoint vacío usa el predeterminado del plan.

| Provider | Endpoint predeterminado | Otra región o nota |
|---|---|---|
| Kimi Code (plan) | `https://api.kimi.ai/coding/v1` | China: `https://api.kimi.com/coding/v1` |
| Alibaba Coding Plan | `https://coding-intl.dashscope.aliyuncs.com/v1` | China: `https://coding.dashscope.aliyuncs.com/v1` |
| OpenCode Go | `https://opencode.ai/inference/go/openai/v1` | El endpoint rechaza los modelos que no sirve con este protocolo |
| Ollama Cloud | `https://ollama.com/v1` | Modelos en la nube de tu cuenta de Ollama |

Una clave de plan no es intercambiable con la clave de API facturada por uso del proveedor. Algunos proveedores limitan las claves de plan a herramientas de programación; usarla desde una plataforma de agentes es tu decisión y puede limitar o suspender el plan. Los presupuestos de AgenticOS tratan este uso como uso de suscripción sin precio.

**Más cuentas compatibles con OpenAI.** Nous Portal, Inception, Cline, Chutes y Synthetic usan la clave de la consola de cada servicio. Un Endpoint vacío usa el predeterminado de abajo, y la lista de modelos procede del catálogo de la clave. Las suscripciones de Nous Portal, Chutes y Synthetic se tratan sin precio; los créditos de Cline y el uso de Inception tienen precio solo cuando AgenticOS conoce el del modelo.

| Provider | Endpoint predeterminado |
|---|---|
| Nous Portal | `https://inference-api.nousresearch.com/v1` |
| Inception | `https://api.inceptionlabs.ai/v1` |
| Cline | `https://api.cline.bot/api/v1` |
| Chutes | `https://llm.chutes.ai/v1` |
| Synthetic | `https://api.synthetic.new/openai/v1` |

**Tu propia pasarela CLIProxyAPI.** Las cuentas cuyos proveedores no emiten clave de plan (Antigravity, Grok Build, Devin, Muse Code, inicio de sesión de Kimi Code y otras) se pueden usar mediante una pasarela [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) que ejecutes tú o tu operador fuera del stack. Las [cuentas de suscripción](#subscription-accounts) son la misma idea integrada, con las cuentas de cada persona separadas. Inicia sesión en las cuentas con los comandos propios de la pasarela, añade una clave de cliente en `access.api-keys` y crea un perfil **CLIProxyAPI (subscription gateway)** con su Endpoint (por ejemplo `http://cliproxyapi:8317/v1` para un contenedor de la pasarela en la red del despliegue) y esa clave de cliente. Cada cuenta de la pasarela está disponible para quien pueda usar el perfil, así que ejecuta una pasarela personal para una cuenta personal. Añade el host de la pasarela a `OUTBOUND_PRIVATE_ALLOWLIST`; las direcciones de loopback nunca son accesibles desde el servidor. Los proveedores pueden limitar o suspender cuentas usadas así; ese riesgo es del titular de la cuenta.

El ámbito también incluye el ID de membresía: volver a unirse crea un ámbito nuevo, por lo que un trabajo de limpieza antiguo no puede borrar cuentas recién conectadas. La eliminación de credenciales se encola incluso con el gateway desactivado. Un gateway desactivado o con fallos deja un trabajo fallido visible en lugar de confirmar la eliminación; reintente ese trabajo tras restaurar el gateway. Si falla la consulta del estado de inicio de sesión, se muestra un error y un botón para reintentar.

Selecciona la clave del almacén y confirma el destino antes de cargar modelos. Un catálogo personalizado utiliza solo esa clave y ese endpoint. Si la lista no está disponible, puedes escribir el modelo manualmente; no se sustituye por el catálogo general de la API. Las estimaciones de presupuesto de AgenticOS no miden la cuota restante de tu suscripción.

### Cuentas de suscripción { #subscription-accounts }

En el editor del agente y el selector de modelos del chat, empieza por **Your subscriptions**, elige un proveedor conocido como **Claude Code (Pro, Max)** o **ChatGPT (Codex)** y pulsa **Connect**. El inicio de sesión se abre allí mismo y vuelve al selector; la lista procede de las cuentas conectadas de ese proveedor, sin deducirla de los nombres de modelos. Las cuentas no disponibles permiten volver a iniciar sesión. Puedes administrar y desconectar cuentas en **Configuración → Suscripciones**. Las claves API de la organización tienen un grupo separado; los gateways y endpoints configurados manualmente están en **Advanced / custom endpoint**. Los perfiles existentes `subscription_accounts` y `cliproxyapi` conservan sus identificadores API.

Los catálogos de chat muestran todas las entradas compatibles con chat, sin limitar la lista silenciosamente a 100 modelos. El selector muestra el número de opciones, si el catálogo está actualizado o es una lista alternativa limitada y permite actualizarlo. OpenRouter muestra la región actual del catálogo; cambiarla es explícito y el nuevo modelo guardado conserva esa región. Los modelos guardados conservan su propia conexión.

Durante la incorporación, **¿Qué suscripciones tienes ya?** permite seleccionar los planes existentes e iniciar sesión antes del primer chat. Es opcional y está disponible para los miembros; estas cuentas siguen siendo personales y no configuran el modelo inicial compartido de la organización.

Si hay varias cuentas personales conectadas, abre la pestaña **Cuenta** y elige la cuenta igual que una clave API guardada. Los modelos de suscripción usan la misma lista con búsqueda que los proveedores API; seleccionar un modelo lo aplica inmediatamente. Al aplicar un modelo se vincula a esa cuenta mediante una ruta opaca; no cambia silenciosamente a otra cuenta. Los perfiles vinculados requieren que la persona tenga esa cuenta conectada. Al reabrir el selector se recuperan la cuenta y el modelo, sin mostrar las rutas de cuenta en los nombres.

**Configuración → Suscripciones** muestra cada cuenta conectada por separado con ventanas de cuota, porcentaje restante, barras de progreso y reinicios. La pestaña **Cuenta** utiliza la misma vista para todas las cuentas del proveedor elegido.

Claude, Codex, Antigravity y ambas regiones de Kimi Code leen metadatos sin llamar a un modelo. Claude incluye ventanas de cinco horas, semanales y por familia. Antigravity conserva los grupos de modelos; Kimi, las ventanas semanales y móviles. Devin muestra observaciones diarias y semanales. Las cuotas de Grok y Meta no pueden consultarse mediante esta conexión del gateway.

Los datos se actualizan cada minuto con la vista abierta, o cada cinco minutos para Claude, y también manualmente. Los datos antiguos se marcan como desactualizados. Los errores permanecen visibles; la falta de datos nunca significa cuota completa. Kimi Code (kimi.com) y Kimi Code (kimi.ai) son accesos regionales separados, no planes de chat de consumo.

Todos los grupos de conexiones se muestran inmediatamente. Las suscripciones conectadas muestran un indicador de estado y la identidad de la cuenta; añadir otra cuenta es una acción secundaria. Al volver a abrir el selector se recuperan el origen de la suscripción y el modelo del perfil de suscripción guardado.

Los modelos de suscripción utilizan las instrucciones y herramientas de AgenticOS en el runtime de Pydantic AI. No inician Claude Code ni otro harness de programación. En Capabilities, **Delegate to agents** agrupa subagentes, **Claude Code & Codex** y **Other installed agents**. Coding Agent sigue activado en la plantilla predeterminada de AgenticOS. Los grupos siguen trabajo diario, conocimiento, investigación, resultados, delegación, automatización y canales; los ajustes avanzados quedan plegados al final. En cada grupo aparecen primero las capabilities activadas y después las recomendadas.

Las personas inician sesión en sus propias suscripciones desde la consola, y los
modelos del proveedor **Subscription accounts** se ejecutan con ellas. En
**Ajustes → Suscripciones**, cada persona conecta cuentas de
Claude (Pro, Max), ChatGPT (Codex), Google Antigravity, Grok, Kimi, Devin o Meta
AI. Un inicio de sesión muestra un código para introducir en la página del
proveedor, o pide la dirección en la que terminó el navegador tras aprobarlo.

Un perfil de este proveedor solo admite un id de modelo, sin clave y sin
endpoint. **Add model** lista los modelos que sirven tus propias cuentas. Cuando
una persona chatea con un agente sobre ese perfil, la ejecución usa las cuentas
de esa persona y de nadie más. Una ejecución iniciada por una clave de API, por
un visitante de un agente publicado o por trabajo en segundo plano no tiene una
persona detrás, así que se rechaza. Por el mismo motivo, la plataforma nunca
elige ese modelo para un agente nuevo.

El servicio `subscription-gateway` viene con el stack y ejecuta
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (MIT) una vez por
persona y organización. El proceso de una persona arranca en el primer uso y se
detiene tras diez minutos inactivo. Cada proceso escucha en loopback con sus
propias claves y su directorio de inicios de sesión, y la API deduce a cuál
llega una petición a partir de la organización y la persona; un navegador nunca
lo nombra. Cuando un miembro se va, un trabajo en segundo plano borra sus
inicios de sesión; borrar una organización borra los de todos sus miembros.
Iniciar sesión en la misma cuenta en dos organizaciones significa hacerlo dos
veces.

Los proveedores pueden limitar el uso de una suscripción fuera de sus propias
aplicaciones y suspender la cuenta por ello. La consola indica este riesgo, y lo
asume el titular de la cuenta. Cursor y Qwen Code no tienen un inicio de sesión
que la pasarela admita, así que no se ofrecen. Los presupuestos de AgenticOS
registran estas ejecuciones sin precio, porque el cupo restante de una
suscripción no se mide por tokens. Consulta la
[configuración](configuration.md#subscription-accounts) para ejecutar la
pasarela.

### Autoalojados { #self-hosted }

| Provider | id | Credencial | Custom URL |
|---|---|---|---|
| System One API | `system-one` | API key, or none | ✓ |
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
    Completions, que es por lo que un perfil `openai` con endpoint la usa por
    defecto - ver [Responses o Chat Completions](#responses-or-chat-completions).

    Así que «sin clave» por sí solo no distingue un modelo local deliberado de un
    perfil al que le borraron la clave — y la clave ajena del secreto es
    `ON DELETE SET NULL`, lo que hace que el segundo caso sea corriente. Un run
    resuelve un perfil sin clave solo cuando este lleva un endpoint; si no, se
    rechaza con el mismo mensaje de «no key configured» que ha tenido siempre.

### Tu propio endpoint { #your-own-endpoint }

| Provider | id | Credencial | Custom URL |
|---|---|---|---|
| Custom (OpenAI-compatible) | `openai_compatible` | clave de API | ✓ |
| Custom (Anthropic-compatible) | `anthropic_compatible` | clave de API | ✓ |

Estos dos son una *forma* de API y no un proveedor. Escribes la dirección de un
servidor que gestionas tú o de una pasarela en la que confías, y la clave que lo
autentica. Elige el que corresponda a lo que responde tu endpoint:

| Tu endpoint responde | Elige | La dirección que hay que escribir |
|---|---|---|
| `POST /chat/completions` — vLLM, LM Studio, un proxy LiteLLM, casi todas las pasarelas | `openai_compatible` | la raíz `/v1`, por ejemplo `https://llm.example/v1` |
| `POST /v1/messages` — la forma de API propia de Anthropic | `anthropic_compatible` | la raíz de la API, por ejemplo `https://llm.example` |

Los dos necesitan un endpoint y una clave. No hay ninguna API pública a la que
recurrir, así que un perfil sin ellos se rechaza en lugar de enviarse a otro
sitio.

La clave se guarda en la bóveda bajo el nombre del propio provider, lo que allí
dice que autentica *ese* endpoint y no la API pública de un proveedor. Por eso
son entradas propias y no un perfil `openai` o `anthropic` con un endpoint: una
clave archivada bajo el nombre de un proveedor habla de ese proveedor.

!!! info "La dirección de Anthropic no lleva `/v1`"

    El SDK de Anthropic envía a `<endpoint>/v1/messages`, así que el endpoint es
    la raíz de la API. Una dirección que ya termina en `/v1` se recorta por ti,
    de modo que ambas formas funcionan, pero la raíz es lo que pide la
    plataforma.

**Load models** lee la lista del mismo endpoint, con la misma clave, así que el
desplegable ofrece lo que tu servidor sirve de verdad. El identificador del
modelo sigue siendo texto libre: un servidor que no publica ninguna lista se
puede usar escribiendo el identificador a mano.

### Cuando la credencial no es una clave de API { #when-the-credential-is-not-an-api-key }

| Provider | id | Credencial |
|---|---|---|
| Azure OpenAI | `azure` | clave **+** endpoint **+** versión de API fijada |
| AWS Bedrock | `bedrock` | id de clave de acceso, clave secreta, región, token de sesión opcional |
| Google Vertex AI | `google_cloud` | JSON de la cuenta de servicio |
| ChatGPT (suscripción de Codex) | `openai_codex` | un inicio de sesión de ChatGPT, guardado iniciando sesión en vez de tecleado |
| ChatGPT (uso oficial del plan) | `openai_chatgpt` | una autorización de aplicación con consentimiento separado del plan, creada al iniciar sesión |
| Cuentas de suscripción | `subscription_accounts` | los inicios de sesión de suscripción de cada persona, a través de la pasarela incluida; sin clave |

Los tres primeros son la razón de que un secreto tenga un *kind*. Un formulario que
recogiera un único token opaco para Azure recogería algo que se puede rellenar
correctamente y que aun así falla en el primer run. Ver
[los kinds de secreto](secrets.md#kinds).

!!! note "Dos ids se reescriben de camino al SDK"

    Un perfil `openai` se construye como `openai-chat` u `openai-responses`, y uno
    `azure` como `azure` o `azure-responses`, según la API que guarda, en lugar de
    tomar la Responses API que infiere `openai` a secas. Ver
    [Responses o Chat Completions](#responses-or-chat-completions).

    `google_cloud` se construye como `google-cloud`. Ninguno de los dos cambia lo
    que guardas.

### Ejecutar con una suscripción de ChatGPT { #running-on-a-chatgpt-subscription }

`openai_codex` ejecuta modelos de OpenAI en el backend de Codex a través de una
suscripción de ChatGPT, en vez de a través de una clave de API medida. Está
pensado para **uso personal**: el inicio de sesión es la suscripción de una
persona, y cada run en un perfil que lo usa cuenta contra los límites de ChatGPT
de esa persona.

Nadie puede teclear la credencial. En su lugar inicias sesión con ChatGPT, de
forma predeterminada con un código corto:

1. En **Vault → add a secret** (o en **Agents → add a model**, con **ChatGPT
   (Codex subscription)** seleccionado, o en **Settings → Coding accounts**), elige
   **Sign in with a code**. La página de dispositivos de ChatGPT se abre en una
   pestaña nueva y el formulario muestra un código.
2. Introduce el código en esa página y aprueba el inicio de sesión. El formulario
   detecta la aprobación por sí mismo y termina; no hay que pegar nada.

El código funciona durante 15 minutos, solo para la persona que inició el inicio
de sesión. Si tu cuenta no admite códigos de dispositivo, abre **Paste an address
instead**: elige **Sign in with ChatGPT**, apruébalo y pega en el formulario la
dirección a la que ChatGPT envía el navegador (`http://localhost:1455/...`, que no
carga). Esa dirección también funciona una sola vez, solo para la persona que
inició el inicio de sesión, y solo durante 15 minutos.

El access token caduca y se renueva mientras los modelos se ejecutan. Cada
renovación gasta el refresh token, así que el par nuevo se vuelve a sellar en el
mismo secreto del vault de inmediato. Dos runs que renuevan en el mismo momento
aún pueden competir. El que pierde se rechaza, y la solución es **Reconnect** en
el secreto, que vuelve a iniciar sesión sin cambiar su id.

!!! warning "Lo que no es un inicio de sesión de ChatGPT"

    - **No es el `auth.json` de la CLI de Codex.** Ese archivo guarda la
      concesión propia de la CLI. Los refresh tokens son de un solo uso, así que
      cualquiera de los dos que renovara primero cerraría la sesión del otro.
    - **No es una credencial de la organización.** Un secreto se crea privado por
      defecto, y un modelo sobre él solo funciona para quien puede ver ese inicio de
      sesión en el vault y pregunta él mismo. Para cualquier otro - un visitante de
      una página pública o un embed, quien llama con una clave API - y para el
      trabajo en segundo plano como describir las imágenes de un documento, el
      modelo se rechaza y un fallback sobre él se omite.
    - **No cualquiera puede publicar sobre él.** Publicar, hacer rollback a o
      promover una versión de un agente se rechaza para quien no puede ver el
      inicio de sesión en el vault cuando funciona sobre él un modelo al que
      llegan sus runs: el modelo del agente, el de un revisor, el de un
      especialista inline o el de una capability activada, el modelo de un
      [delegado que fija](reference/capabilities.md#delegation) y de lo que ese
      delegado alcanza a su vez, o uno de los tres primeros fallbacks de
      cualquiera de ellos. Pueden hacerlo el dueño del inicio de sesión, los
      owners y admins, y cualquiera con quien se haya compartido. Una clave de
      API no puede, vea lo que vea quien la emitió, porque un run con una clave
      nunca gasta un inicio de sesión. Una versión publicada antes sobre él
      sigue funcionando.
    - **No se ofrece a un especialista que invente el modelo.** Con
      [`allow_dynamic`](reference/capabilities.md#delegation) el modelo de un run
      puede elegir el modelo de un especialista entre los perfiles de la
      organización. Un perfil sobre un inicio de sesión, o uno cuyos tres
      primeros fallbacks llegan a uno, solo está en esa lista cuando el spec del
      agent nombra exactamente ese perfil como uno de los modelos de arriba.
    - **El gasto mostrado no es tu factura.** Un run se tarifa a los precios de
      la API de OpenAI para el mismo modelo, que es lo que un
      [budget](governance.md#budgets) puede razonar. La suscripción en sí la
      factura OpenAI a tarifa plana.
    - **Algunos ajustes se ignoran.** El backend de Codex descarta `max_tokens`,
      `temperature` y `top_p`.

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
cada provider tiene que aparecer en esta página. Añadir el vigesimonoveno es una
edición más lo que ese test pida después.

Merece la pena conocer dos cruces, porque son búsquedas que pueden no responder
nada:

- El snapshot de precios escribe cuatro providers de otra forma — `xai` es
  `x-ai`, `bedrock` es `aws`, `google_cloud` es `google`, y `openai_codex` se
  tarifa como `openai` — y `_PRICE_PROVIDER_ALIASES` los puentea.
- El catálogo de imágenes lleva su propio par `provider` y `prefix`, que es un
  tercer vocabulario otra vez.

## Qué modelos ofrece un provider { #which-models-a-provider-offers }

El campo del id de modelo se rellena desde dos fuentes, en este orden — y desde
ninguna de las dos para siete providers, cosa que la respuesta dice en voz alta.

### En vivo { #live }

Treinta providers publican un endpoint de listado, y es la única fuente que sabe
de un modelo publicado esta mañana:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`,
`kimi_code`, `alibaba_coding_plan`, `opencode_go`, `ollama_cloud`, `cliproxyapi`, `nous_portal`,
`inception`, `cline`, `chutes`, `synthetic`.

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

Al abrir el selector de la suscripción se carga la lista incluida en el despliegue. El selector no consulta un catálogo en directo para cada cuenta. Las entradas de GPT-6.2 se verificaron en el servidor de Codex y dejan el contexto vacío hasta que se incorpore al catálogo de precios.

| Provider | ids curados |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | GPT-6.2 Sol y Astra, GPT-6.1 Sol y Terra, GPT-6 Sol, Astra y Luna, y los identificadores anteriores de Codex |
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
- Un `vendor/model` de un agregador que el snapshot no conoce se tarifa como el
  modelo propio del proveedor, y una versión con punto se prueba también con
  guiones: el `anthropic/claude-sonnet-5.5` de OpenRouter cuesta lo que el
  `claude-sonnet-5-5` de Anthropic.
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

## Modelos realtime { #realtime-models }

Una [llamada de voz](voice.md) no usa un perfil de modelo. Su modelo se elige de
un catálogo que trae este despliegue, `backend/app/core/catalog/realtime_models.json`,
que lee `backend/app/services/realtime_models.py` y que se sirve al Builder en
`GET /api/v1/providers/realtime-models`. La clave se nombra en la sección Voice
del agent como un secreto del vault, no en un perfil. Es la misma forma que usa
la voz a texto: una elección del catálogo más una clave explícita.

Cada entrada nombra un provider, sus modelos y, para cada modelo:

| Campo | Qué decide |
|---|---|
| `transport` | `webrtc` (el navegador habla con el provider; este despliegue mantiene un sideband) o `relay` (el audio pasa por el socket de este despliegue) |
| `input_sample_rate`, `output_sample_rate` | Las frecuencias PCM a las que el navegador graba y reproduce, a través del relay |
| `voices`, `default_voice` | Lo que ofrece la sección Voice, y lo que significa no elegir nada |
| `supports_thinking` | Si la capability de thinking del agent se traduce al ajuste de razonamiento propio del modelo |
| `context_window` | Dónde una reconexión pasa de reproducir los turnos a un resumen de los más antiguos |
| `pricing` | `kind` (`tokens` o `per_minute`), `worst_case_usd_per_minute` para la comprobación previa a una llamada, y `usd_per_minute` para un modelo por minuto |

La familia `gpt-realtime` de OpenAI funciona sobre WebRTC y es el único provider
probado en vivo. Azure OpenAI, Gemini Live y xAI funcionan sobre el relay y **no
están verificados en vivo**. GPT-Live no está en el catálogo: no puede recibir
historial después de que empiece una sesión, así que una reconexión no podría
continuar una llamada.

**Azure es un deployment más un modelo base.** El nombre de un deployment lo
elige su propietario y no dice nada de lo que ejecuta, así que la sección Voice
toma el nombre del deployment como texto libre y el modelo del catálogo que
ejecuta como `base_model`. El modelo base decide las voces y el precio: los
tokens de una llamada de Azure se tarifan como ese modelo en OpenAI. El endpoint
y la versión de la API vienen del secreto `azure_openai`.

**Precios.** Los modelos tarifados por token se tarifan por respuesta a partir
del mismo snapshot incluido que los runs de texto. Un modelo por minuto (xAI) se
factura por el tiempo conectado al `usd_per_minute` del catálogo. Un modelo
tarifado por token que el snapshot no sabe tarifar se rechaza cuando empieza una
llamada, en vez de funcionar con un budget que no puede hacer cumplir.

## Resumen { #recap }

- Un **perfil** es un modelo con nombre más una clave con nombre, y los agents
  apuntan a perfiles para que rotar cualquiera de los dos toque una sola fila.
- **28 providers**, y lo único que esta plataforma sabe de cada uno es la forma
  de la credencial — construirlo es trabajo de Pydantic AI.
- El id de modelo es **texto libre**, porque ninguna lista es autoritativa.
- La **longitud de contexto** se lee una vez y se guarda, porque el snapshot de
  precios se equivoca sobre ella en la dirección que rompe un run.
- El **coste** viene de un snapshot incluido, un modelo desconocido se registra
  como sin tarifar y no como gratis, y un provider sin clave no registra gasto
  alguno.
- Los **modelos realtime** de las llamadas de voz son una elección del catálogo
  más una clave con nombre, sin perfil; solo los de OpenAI están verificados en
  vivo.

## Configurar uno { #setting-one-up }

El [recorrido del primer agent](first-agent.md) hace esto de principio a fin. En
resumen: guarda una clave de provider en **Settings → Secrets**, añade un perfil
de modelo que la nombre y después apunta el spec de un agent a ese perfil.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

hace las tres cosas para un despliegue nuevo.

Para usar la API regional de OpenRouter, conserva **OpenRouter** como proveedor e introduce `https://eu.openrouter.ai/api/v1` en **Endpoint** del formulario del modelo. El perfil mantiene su clave OpenRouter del Vault, el tratamiento nativo de modelos y los controles de caché. Las sugerencias se obtienen de ese endpoint y se almacenan en una caché independiente; si falla la lista regional, no se utiliza el catálogo global. En las bases de conocimiento, configura el endpoint de embeddings por separado al crear la colección o editar su proveedor de embeddings. Las configuraciones existentes mantienen el endpoint global. El enrutamiento EU requiere un plan OpenRouter Business o Enterprise adecuado; el [enrutamiento regional](https://openrouter.ai/docs/guides/get-started/sovereign-ai) y ZDR son políticas distintas de OpenRouter.

Un endpoint regional sirve menos modelos de embeddings que el global: `eu.openrouter.ai` sirve `mistralai/mistral-embed-2312`, `mistralai/codestral-embed-2505` y `google/gemini-embedding-2`, y ninguno de OpenAI. El formulario de creación ofrece solo los modelos que lista el endpoint, y se rechaza una colección cuyo modelo el endpoint no sirve, tanto al crearla como al moverla a él. Los dos modelos de Mistral no están en la instantánea de precios incluida, así que su gasto se registra como valorado en parte.

Actualiza todos los procesos de API y workers antes de configurar endpoints regionales. Las versiones anteriores ignoran el endpoint personalizado de OpenRouter.

Para otro endpoint con el mismo proveedor y modelo, elija **Añadir modelo separado** en el Builder. El nombre automático incluye el endpoint y el perfil existente no cambia. **Actualizar modelo** modifica el perfil compartido. Los catálogos personalizados están limitados a 2 MiB, 2048 modelos y longitudes de campos acotadas, con un máximo de 16 catálogos en caché por proceso. Una respuesta comprimida o demasiado grande permite escribir el ID del modelo sin recurrir a una lista global.

## Modelos de decisión { #decision-models }

Los perfiles de decisión usan la API nativa `decisions` en lugar de generar texto. Elige proveedor, modelo y clave del almacén en el formulario del modelo. OpenAI, Google y OpenRouter ofrecen APIs de chat y decisiones; TypeSafe y un endpoint System One propio sirven decisiones. Un perfil de decisión no puede ser el modelo conversacional de un agente ni recurrir a un modelo de chat como alternativa.

Los adaptadores proceden de Pydantic AI. Las sugerencias actuales incluyen OpenAI `gpt-6-luna`, Google `gemini-decision-1` y TypeSafe `jev-1.14.0` / `jev-latest`. OpenRouter consulta el catálogo de decisiones por separado del catálogo de texto. System One propio requiere URL e identificador de modelo. La disponibilidad depende del proveedor y de la cuenta; una sugerencia no garantiza acceso.

Los pasos **Decision models** de los workflows eligen un perfil nativo. Los identificadores `decide.*` y las configuraciones existentes con clave TypeSafe siguen siendo válidos. Por debajo del umbral de confianza se utiliza el puerto `unsure`. Cada ejecución comprueba de nuevo permisos y claves; el coste cuenta para los presupuestos del workflow y la organización.

La participación automática en canales admite un modelo nativo o un LLM habitual con salida estructurada. La decisión nativa sí/no devuelve la probabilidad de intervenir; un campo numérico acotado conserva ese valor. Un LLM devuelve una valoración de utilidad de 0 a 100, no una probabilidad calibrada. Ambos se comparan con el control deslizante del umbral, incluyendo la igualdad. El clasificador no tiene herramientas. La función requiere activación y respeta los intervalos; el agente principal puede usar cuentas MCP de la organización, nunca credenciales privadas de un participante.

Referencias: [Pydantic AI](https://pydantic.dev/docs/ai/models/decision/), [OpenAI](https://developers.openai.com/api/docs/guides/decisions), [Google](https://ai.google.dev/gemini-api/docs/decisions-api), [TypeSafe](https://docs.typesafe.ai/models), [OpenRouter](https://github.com/OpenRouterTeam/skills/tree/main/skills/openrouter-decisions).

ElevenLabs Realtime incorpora `eleven_realtime_v1_mini` y `eleven_realtime_v1_max` mediante el relay PCM de 24 kHz, con la voz predeterminada `brian` y detección semántica de turnos.

El SDK no informa los cargos por tokens. Las llamadas con un presupuesto de gasto se rechazan antes de conectar. Las llamadas sin presupuesto conservan el límite de tiempo y registran el coste de audio como límite inferior, no como factura completa. La tarifa de audio es de 0,08 USD/minuto (0,16 USD con burst); los tokens se cobran aparte. El contexto de 16k es un límite conservador de historial de la plataforma, no una ventana de contexto publicada por el proveedor. La integración se ha probado sin conexión mediante la construcción de modelos SDK y transportes controlados, no con cuentas reales. [SDK](https://pydantic.dev/docs/ai/api/realtime/elevenlabs/), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api).

## Cuentas GitHub Copilot { #github-copilot-accounts }

**GitHub Copilot** (`github_copilot`) usa el dialecto Copilot de Pydantic AI, distinto de GitHub Models (`github`). Envía credenciales explícitas del vault al gateway fijo `https://api.githubcopilot.com`, con identidad AgenticOS y sin cabeceras de editor VS Code. Los ajustes de petición no pueden sustituir cuenta ni identidad. No se admiten gateways personalizados o Enterprise.

Un administrador puede configurar un perfil aprobado con un token bearer Copilot en el vault. Un token general de API GitHub no prueba acceso a Copilot. Elige credenciales personales en un agente compartido para que cada miembro conecte su cuenta desde el chat. El operador debe establecer `GITHUB_COPILOT_OAUTH_CLIENT_ID` con la aplicación OAuth propia de AgenticOS y device flow habilitado. El miembro abre GitHub, aprueba el código mostrado en AgenticOS y comprueba la autorización. Código de dispositivo y token nunca aparecen en una URL. Reconectar repite el proceso; desconectar elimina el token privado guardado, mientras que la revocación OAuth se hace aparte en GitHub.

La autorización GitHub no basta: antes de guardar el token, AgenticOS comprueba que cuenta y aplicación ofrecen el modelo elegido por `/chat/completions`. Los catálogos son propios de cada cuenta, filtran endpoints compatibles y no usan un catálogo global de respaldo. No se ofrecen Responses, Messages, embeddings ni realtime de Copilot. Las conexiones personales siguen limitadas al chat web autenticado, sin sustituirlas por claves de organización u otro proveedor.

El device flow admite concesiones OAuth App sin caducidad. Rechaza expresamente concesiones GitHub App caducables o renovables; no implementa renovación ni descarta refresh tokens silenciosamente. Permisos, políticas, revocación y cuotas requieren reconectar o actuar en la cuenta. El nombre del modelo no determina la factura: el uso del plan Copilot queda sin precio hasta verificar la facturación en USD; las cuotas no se interpretan como dólares. La aceptación con cuenta real, aplicación propia e identidad AgenticOS sigue pendiente. Consulta [Pydantic AI Copilot](https://pydantic.dev/docs/ai/models/github-copilot/) y [GitHub OAuth](https://docs.github.com/en/copilot/how-tos/copilot-sdk/setup/github-oauth).

## Uso oficial del plan ChatGPT { #official-chatgpt-plan-usage }

**ChatGPT plan usage (official)** utiliza una autorización propia de la aplicación y la API pública Responses. **ChatGPT (Codex subscription)** sigue siendo la integración separada del backend Codex. Sus inicios de sesión, tipos de bóveda y tokens no son intercambiables.

La función está desactivada por defecto. El operador debe verificar la elegibilidad, establecer `OPENAI_CHATGPT_PLAN_USAGE_ENABLED=true` y conservar un UUID en `OPENAI_CHATGPT_HOST_ID` entre reinicios y réplicas. Las aplicaciones de pago o alojadas remotamente necesitan aprobación de OpenAI. La configuración confirma la decisión del operador; no obtiene aprobación. Restaura el UUID original antes de reconectar una instalación existente.

Elige el proveedor oficial en la bóveda o selector de modelos, inicia sesión y pega la dirección final `http://127.0.0.1:1455/auth/callback?...`. La autorización se guarda como privada. Solo su propietario puede usarla; perfiles compartidos, claves API y tareas en segundo plano no la prestan a otra persona. Rechazar compartir el plan conserva registro y autorización, muestra una advertencia e impide inferencia. Reconecta para solicitar consentimiento. El registro emitido sobrevive a errores del intercambio de tokens. Cada callback es de un solo uso y pertenece al miembro y organización iniciadores; otro inicio invalida los anteriores.

Elige un modelo del catálogo actual de la cuenta seleccionada. No se sustituye por un catálogo global de claves API. La rotación usa escritura condicional en la bóveda. Cada petición comprueba revocación y pertenencia actual del propietario. Elimina la autorización de la bóveda para desconectar localmente; revoca acceso en la configuración ChatGPT para hacerlo en OpenAI. Los metadatos del registro se conservan para reconectar.

Pydantic AI impone streaming, `store=false`, historial local y el protocolo preview admitido. No se ofrecen recuperación de respuestas suspendidas, Batch API ni herramientas alojadas incompatibles. El plan oficial no participa en fallbacks automáticos de modelos. Los cargos no tienen precio calculado en AgenticOS; un precio API no demuestra el cargo del plan. Elegibilidad, cuota y facturación necesitan pruebas con una cuenta apta. Consulta [el flujo OpenAI](https://developers.openai.com/siwc/token-sharing-open-source) y [el adaptador Pydantic AI](https://pydantic.dev/docs/ai/models/openai-chatgpt/).
