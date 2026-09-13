---
source_sha: 5d457ec305b9
---

# Elegir un modelo { #choosing-a-model }

[Modelos](models.md) explica la maquinaria — qué es un perfil, cómo se dispara un
fallback, cómo se calcula el coste de un run. Esta página responde a la pregunta
que la gente hace de verdad primero: **¿qué modelo debería usar este agent?**

La respuesta corta es que no es una sola decisión. Es una decisión *por agent*,
y se espera que cambies de idea más adelante — para eso está un
[perfil de modelo](models.md#a-model-profile).

## Tres preguntas lo deciden { #three-questions-decide-it }

Hazlas en este orden. Gana la primera que dé una respuesta rotunda.

| | Pregunta | Si la respuesta es… |
|---|---|---|
| 1 | **¿Adónde pueden ir estos datos?** | «A ninguna parte» — estás eligiendo entre modelos que puedes ejecutar tú mismo. Párate aquí; nada de lo que sigue lo anula |
| 2 | **¿Cuán difícil es el razonamiento?** | La extracción y la reescritura rutinarias son un budget distinto del razonamiento en varios pasos sobre un corpus desordenado |
| 3 | **¿Con qué frecuencia se ejecutará?** | Cien conversaciones al mes y cien mil son productos distintos, aunque las instrucciones sean las mismas |

La mayoría de los agents de una empresa son la pregunta 3 con una respuesta fácil
a la pregunta 2 — una respuesta de soporte, el resumen de un documento, un
formulario rellenado a partir de un correo. Esos no necesitan un modelo de
frontera, y pagar por uno es la forma más común de que el budget de un agent se
evapore.

## Qué elegir, según lo que hace el agent { #what-to-pick-by-what-the-agent-does }

| El agent… | Recurre a | Por qué |
|---|---|---|
| Responde a partir de tus documentos y los cita | Un modelo de **gama media** con una ventana de contexto grande | La recuperación hace la parte difícil. El trabajo del modelo es leer lo que se le ha entregado y no adornarlo |
| Clasifica, extrae, enruta, reescribe | El modelo **más barato** que pase tu propia prueba | La tarea tiene una respuesta correcta, así que la calidad es medible y el listón está más bajo de lo que parece |
| Planifica a lo largo de muchos pasos y herramientas | Un modelo **de frontera** | Decidir *qué* herramienta llamar a continuación es donde fallan los modelos baratos, y fallan entrando en bucle |
| Escribe algo que lee un cliente | Un modelo **de frontera o de gama media potente** | El tono y el comportamiento ante una negativa son donde se nota la diferencia, y ambos son visibles para la persona a la que menos quieres molestar |
| Maneja datos que no pueden salir del edificio | Un modelo de **pesos abiertos** alojado por ti | Mira más abajo — esta es la pregunta 1, y no es un intercambio de calidad que puedas discutir |

!!! tip "Empieza un nivel por encima y luego baja"

    Construye el agent sobre un modelo potente hasta que se comporte como quieres,
    luego cambia el perfil a uno más barato y mira si alguien lo nota. Hacerlo al
    revés significa depurar tus instrucciones y el modelo al mismo tiempo, y le
    echarás la culpa al que no es.

## Modelos cerrados o pesos abiertos { #closed-models-or-open-weights }

Los dos son de primera clase aquí. Los 27 providers incluyen los laboratorios de
frontera cerrados, los hosts de pesos abiertos y dos entradas sin clave —
[Ollama](models.md) y un proxy LiteLLM — para modelos que corren en hardware
tuyo.

| | Modelos cerrados (API) | Pesos abiertos (alojados) | Pesos abiertos (tu hardware) |
|---|---|---|---|
| Ejemplos en el selector | Anthropic, OpenAI, Google, xAI | Groq, Together, Fireworks, Nebius, DeepSeek | Ollama, un proxy LiteLLM |
| La mejor calidad disponible | Sí, en la frontera | Cerca, y acercándose | Limitada por tu GPU |
| Los datos salen de tu red | Sí, hacia ese proveedor | Sí, hacia ese host | **No** |
| Forma del coste | Por token, sin suelo | Por token, normalmente más barato | Fijo — compraste el hardware |
| Quién arregla una regresión | El proveedor, en su propio calendario | El host | Tú, y solo si te moviste |
| Buen motivo para elegirlo | El trabajo es genuinamente difícil | Volumen alto, trabajo ordinario | Residencia de los datos, o un volumen que empequeñece el hardware |

El resumen honesto: **los modelos cerrados siguen por delante en el razonamiento
más difícil, y esa diferencia no importa para la mayor parte de lo que una
empresa automatiza.** Un agent que lee un documento de políticas y responde una
pregunta sobre él no es una tarea de frontera, y ejecutarlo sobre pesos abiertos
alojados por ti suele ser la mejor decisión de ingeniería además de la más
barata.

!!! warning "Alojar un modelo tú mismo es un compromiso real"

    Una GPU inactiva se sigue facturando, alguien tiene que mantener el runtime
    parcheado, y un modelo que alojas tú no tiene proveedor al que escalar.
    Elígelo cuando la residencia de los datos lo exija o cuando tu volumen
    empequeñezca de verdad al hardware — no para ahorrar dinero en cuarenta
    conversaciones al día.

## Poner una pasarela delante { #putting-a-gateway-in-front }

Tres de los 27 no son fabricantes de modelos sino enrutadores: **OpenRouter**,
**Vercel AI Gateway** y un **proxy LiteLLM** que ejecutas tú. Cada uno te da una
clave y un endpoint delante de muchos modelos.

Merece la pena cuando quieres control central del gasto entre equipos también
fuera de AgenticOS, o cuando todavía estás decidiendo y quieres probar varios
modelos sin un ciclo de compras por proveedor. Te cuesta un salto, un segundo
sitio donde una petición puede fallar y — en el caso de un enrutador alojado —
una segunda empresa viendo el tráfico.

## Qué encarece de verdad la factura { #what-actually-drives-the-bill }

El nombre del modelo no. **El contexto.**

El coste de un run está dominado por cuántos tokens entran, y lo que entra son
tus instrucciones, los documentos recuperados, la conversación hasta ese momento
y cada resultado de herramienta. Un agent con un system prompt de 4.000 palabras
y ocho fragmentos recuperados por turno es caro en cualquier modelo.

Así que antes de cambiar el modelo, comprueba tres cosas:

- **`default_top_k` en la capability de conocimiento.** Ocho fragmentos donde
  bastarían tres es el sobrecoste silencioso más común.
- **Instrucciones que se repiten.** Se leen en cada turno, sin excepción.
- **[La gestión del contexto](reference/capabilities.md)**, que mantiene una
  conversación larga dentro de la ventana en lugar de reenviarla entera.

[Los budgets](governance.md#budgets) son la red de seguridad, no el plan: un
budget detiene un run antes de la petición al modelo, así que un modelo mal
elegido aparece como un agent que dejó de responder y no como una factura a fin
de mes.

## Cambiar de idea más adelante { #changing-your-mind-later }

Un perfil de modelo nombra el modelo; los agents apuntan al perfil. **Cambia el
perfil y todos los agents que lo usan se mueven, sin que ninguno de ellos tenga
que republicarse.**

Esa es toda la razón de que exista la indirección, y es lo que hace seguro seguir
el consejo de esta página: elige algo razonable ahora, mide lo que tu propio
trabajo necesita de verdad, y muévete.

Los fallbacks viven en ese mismo perfil. Pon un segundo provider detrás del
primero y una caída se convierte en una respuesta más lenta en lugar de en un
incidente — merece la pena en cualquier agent al que pueda llegar un cliente.

## Los embeddings son una elección aparte y permanente { #embeddings-are-a-separate-permanent-choice }

La recuperación usa un modelo de embeddings, y queda **fijado cuando se crea una
colección**. Dos modelos de la misma anchura escriben en espacios vectoriales
distintos, y la búsqueda seguiría comparándolos como si fueran el mismo — así que
cambiarlo significa volver a generar los embeddings de toda la colección.

Elígelo una vez, por colección, y consulta
[Procesamiento de archivos](file-processing.md) antes de hacerlo.

## Resumen { #recap }

- La elección es **por agent**, no por empresa, y un perfil de modelo existe para
  que puedas cambiarla más adelante sin republicar nada.
- **Adónde pueden ir los datos** pesa más que cualquier otra consideración.
- La mayoría de los agents de una empresa **no** necesitan un modelo de frontera;
  constrúyelo sobre uno, luego baja y mira si alguien lo nota.
- **El contexto encarece la factura**, no el nombre del modelo — comprueba
  `default_top_k` y tus instrucciones antes de cambiar de provider.
- El **modelo de embeddings es permanente por colección**. Elige ese con cuidado.

[La mecánica: perfiles, providers, fallbacks y coste →](models.md)
