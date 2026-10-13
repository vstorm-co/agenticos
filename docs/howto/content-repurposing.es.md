---
source_sha: "bc3d361ee1d5"
title: "Convierte un artículo en publicaciones sociales con la voz de tu marca"
description: "Adjunta un artículo sintético breve y haz que un agent escriba una publicación por canal, cada una trazable a la fuente y dentro de los límites de su canal."
---

# Convierte un artículo en publicaciones sociales con la voz de tu marca { #turn-one-article-into-social-posts-in-your-brand-voice }

Dale a un agent un artículo y una skill con las reglas de tu voz y los límites de cada canal, y haz que escriba una publicación para LinkedIn, otra para X y un texto breve para el boletín. El ejemplo es lo bastante corto para comprobar a mano cada afirmación de las publicaciones frente al artículo. Es un procedimiento para ejecutar, con un run registrado como referencia. No mide lo bien que la voz se parece a la tuya.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Sin sandbox, modelo de embeddings ni conexión MCP: este agent solo necesita la [capability skills](../reference/capabilities.md#skills) y un archivo adjunto en el chat.

## Prepara la entrada { #prepare-the-input }

Guarda esto como una skill en **Skills → New skill**. Llámala `brand-voice`, dale una descripción como "Tone, banned phrases and per-channel limits for turning an article into social posts" y pega este contenido:

```text
Plain, confident, specific. Say what happened and what it means for the
reader. Use second person when addressing the reader, and "we" when
describing what the company did. State only facts, numbers and outcomes that
appear in the source article — never round a figure or add an outcome the
article does not give.

## Banned phrases

Never use any of: "game-changer", "revolutionize", "cutting-edge", "seamless",
"unlock your potential", "at the end of the day", "in today's fast-paced
world".

## Channel limits

| Channel | Limit | Shape |
|---|---|---|
| LinkedIn | 80-150 words | Open with the concrete result, two or three short paragraphs, at most one hashtag |
| X | 280 characters or fewer, counting spaces | One idea, no thread, no hashtag needed |
| Newsletter blurb | 40-60 words | One sentence hook, one sentence of detail, end with the placeholder [link] |

Write one post per channel from the attached article. Every claim in a post
must trace to a sentence in the article. If the article does not state a
number or outcome, the post does not state one either.
```

Después guarda este artículo sintético, de unas 400 palabras, como `article.md`. Las cifras son inventadas para esta prueba: una empresa ficticia, un piloto ficticio, nada es real.

```text
Northwind Robotics cuts warehouse pick times in six-week pilot

Northwind Robotics, a fictional logistics-robotics company, ran a six-week pilot
of its updated picking robot, the Pallox-3, across three regional warehouses.
The pilot measured the time from an order arriving to an item leaving the pick
station.

Average pick time fell from 12 seconds to 9 seconds per item, a 25 percent
reduction, measured across 40,000 picks during the pilot. The Pallox-3's
battery lasts 8 hours per charge, up from 5 hours on the previous model,
which let two of the three sites run a full shift without a midday swap.

No worker injuries were recorded at any of the three pilot sites during the
six weeks, according to the internal safety log Northwind shared with pilot
staff. The robot's new obstacle sensor, added after last year's design
review, stops the unit within 4 centimeters of an unexpected object, compared
with 15 centimeters on the previous sensor.

Warehouse staff at the pilot sites were surveyed at the end of the six weeks.
68 percent said the robot's new charging dock was easier to use than the old
one; 12 percent reported no opinion; the remainder did not respond to that
question.

Based on the pilot results, Northwind plans to roll the Pallox-3 update out
to 40 additional warehouses during the fourth quarter. The rollout will
happen in four batches of ten sites, starting with the two regions that ran
the pilot. Each batch is expected to take one week to install and configure,
based on the installation time recorded during the pilot.

The Pallox-3 hardware itself did not change during the pilot; the
improvement came from a software update to the picking algorithm, which
Northwind's engineering team had been testing internally for four months
before the pilot began. The update is delivered over the air to existing
Pallox-3 units, so warehouses do not need to replace hardware to get the
faster pick times.

Northwind has not yet published pricing for warehouses outside the original
three pilot sites, and a company spokesperson said in the pilot debrief that
a decision on pricing for the Q4 rollout is still under review. The company
also declined to say whether the update would be offered to older Pallox-2
units.

This is a synthetic case study; Northwind Robotics, the Pallox-3 and every
figure above are invented for this test.
```

Datos de referencia para comprobar después: un 25 % más rápido (de 12 s a 9 s), 40.000 recogidas, una batería de 8 horas, un sensor que detiene el robot a 4 cm, un 68 % del personal que encontró más fácil la nueva base de carga, una actualización solo de software, ninguna lesión y un despliegue en el cuarto trimestre en 40 sedes en cuatro tandas. El artículo también dice lo que *aún no* se sabe: el precio del despliegue y si las unidades Pallox-2 más antiguas recibirán la actualización.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Skills** y vincula la skill `brand-voice` que acabas de crear.
3. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You repurpose one article into social posts.
Follow the bound brand-voice skill for tone, banned phrases and channel limits.
Write exactly one post per channel: LinkedIn, X and the newsletter blurb.
Every claim must trace to a sentence in the attached article. Do not invent a
fact, a number or an outcome the article does not state.
Label each post with its channel name.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent, adjunta `article.md` y envía:

```text
Turn the attached article into one post per channel: LinkedIn, X and the
newsletter blurb.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Longitud de la publicación de X | 280 caracteres o menos, espacios incluidos |
| Longitud de la publicación de LinkedIn | 80–150 palabras |
| Longitud del texto del boletín | 40–60 palabras |
| Frases prohibidas | Ninguna de las siete frases de la skill aparece en ninguna publicación |
| Cada número y cada resultado | Se remonta a una frase de `article.md`: 25 %, de 12 s a 9 s, 40.000 recogidas, 4 cm, ninguna lesión, despliegue en el cuarto trimestre en 40 sedes |
| La misma petición sin archivo adjunto | El agent pide el artículo en lugar de inventarse uno |

Cuenta los caracteres de la publicación de X a mano o con un script corto; no te fíes de lo que el modelo diga sobre la longitud.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent llamó a `load_capability` para `brand-voice` y luego respondió directamente con las tres publicaciones. La de X tenía 185 caracteres. La de LinkedIn tenía 113 palabras y el texto del boletín 50, ambos dentro de sus límites. No apareció ninguna frase prohibida. Cada número de las tres publicaciones (25 %, de 12 s a 9 s, 40.000 recogidas, los 4 cm de parada del sensor y el despliegue en el cuarto trimestre en 40 sedes en cuatro tandas) coincidía con el artículo. Coste: 0,016 USD.

    Sin archivo adjunto, el agent cargó igualmente la skill, luego dijo "I don't see any article attached to your message" y pidió el artículo, en lugar de escribir publicaciones de la nada.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Una publicación supera su límite.** La skill da el límite como regla, no como sugerencia. Endurece las instrucciones para que el agent tenga que contar antes de responder, o acorta las longitudes de ejemplo de la propia skill.
- **Se cuela una frase prohibida.** Comprueba que está vinculado exactamente ese contenido de la skill y que no lo tapa una versión anterior. Skills guarda una versión por skill, y una conversación antigua puede haber cargado una respuesta previa antes de una edición.
- **El agent se inventa una estadística.** Pídele que cite la frase de la que sale un número; un número que no puede citar es un número inventado.
- **El agent escribe publicaciones sin artículo adjunto.** Si no se niega, endurece las instrucciones para exigir que se niegue cuando no haya archivo.

## Registra la prueba { #record-the-trial }

Guarda el artículo, el contenido de la skill, las tres publicaciones, la versión del agent y el run en Activity. Guarda también un run en el que se superó un límite: muestra si el fallo fue de la redacción de la skill o de la aritmética del modelo.

Una persona sigue decidiendo si la voz suena de verdad a la marca y si una publicación está lista para publicarse. Contar caracteres y buscar frases prohibidas es mecánico; juzgar la voz no lo es.

## Siguientes pasos { #next-steps }

Añade la voz de una segunda marca como una skill aparte y vincula la que necesite cada conversación, en lugar de ampliar una sola skill con una variante por cliente. Consulta [Skills](../skills.md) para ver cómo se delimita y comparte una skill.
