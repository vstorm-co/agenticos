---
source_sha: "bfce080544ad"
title: "Infórmate sobre una empresa antes de una llamada"
description: "Investiga una organización pública con búsqueda web y descarga de páginas, y obtén un informe de una página en el que cada dato lleva su fuente y su fecha."
---

# Infórmate sobre una empresa antes de una llamada { #brief-yourself-on-a-company-before-a-call }

Construye un agent que investiga una organización y escribe un informe de una página antes de una llamada con ella: a qué se dedica, noticias recientes, la dirección actual y lo que no pudo confirmar. El ejemplo es una fundación de código abierto conocida, así que puedes comprobar el informe con fuentes que cualquiera puede abrir. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Búsqueda web: el método por defecto es DuckDuckGo y no necesita cuenta ni clave.
- Sin colección de conocimiento, sin sandbox y sin conexión MCP.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Web search** (método DuckDuckGo) y **Web fetch**.
3. Fija un budget y un límite de pasos para la prueba. El run registrado usó 20 pasos y costó unos 0,26 USD.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You write a one-page brief on an organization before a call with them.
Research it with web search and web fetch before writing anything.

Rules:

- Every fact in the brief carries the source URL it came from, next to the
  fact, not collected in a list at the end.
- Next to each fact, name the date: either the date the source page itself
  states (an article date, a filing date) or, when the source carries none,
  the date you fetched it, marked as "(fetched)".
- Never state a person's name, title or any personal detail unless a source
  confirms it. If you cannot confirm who currently holds a role, say so
  instead of guessing, and do not use a plausible-sounding name.
- Do not repeat a home address, personal phone number or other private
  contact detail even if a source shows one. The brief covers the
  organization, not the people in it.
- End with a section called "Could not confirm" naming anything you looked
  for but did not find a source for. An empty section still gets the heading,
  with one line saying nothing was left unconfirmed.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent y envía:

```text
Brief me on the Python Software Foundation before a call with them.
```

Cualquier organización pública conocida funciona igual. Una gran fundación de código abierto es una buena opción por defecto, porque sus finanzas, su junta y su misión están publicadas y son lo bastante estables para comprobarlas.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Cada afirmación factual | Tiene la URL de su fuente justo al lado |
| La fecha de cada afirmación | Indica la fecha propia de la fuente, o "(fetched)" cuando la fuente no tiene ninguna |
| Personas nombradas | Solo las que confirma una fuente, citadas desde la página de la propia organización y no supuestas |
| Un cargo que nadie pudo confirmar | Lo dice claramente en lugar de nombrar a una persona plausible |
| Datos de contacto personales | Ausentes, aunque alguna fuente mostrara uno |
| Sección "Could not confirm" | Presente y con una laguna real, no vacía por omisión |
| La misma pregunta sobre una organización casi sin presencia pública | Lo dice y produce un informe breve y honestamente escaso en lugar de inventar detalles para llenar la página |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent hizo tres llamadas a `web_search` y luego `web_fetch` sobre las páginas propias de la PSF sobre la organización, la junta y el informe anual de 2024, además de una entrada sobre el programa de subvenciones y un agregador de formularios 990. Un `web_fetch` (un sitio de declaraciones) falló y no se reintentó con otra fuente para ese dato.

    El informe citó una fuente junto a cada afirmación: misión, programas, finanzas del ejercicio 2024, el total de subvenciones de 2024 y la lista completa de la junta, cada una fechada según la fuente o marcada como "(fetched)". Nombró la junta solo a partir de la página de la PSF con su composición. Se negó expresamente a dar el nombre de la persona mejor remunerada que aparecía en un fragmento de búsqueda de un formulario 990, porque la declaración en sí no era accesible directamente, y anotó esa laguna, junto con el desglose exacto de ingresos y las fechas de la próxima PyCon, en "Could not confirm". Coste: 0,26 USD.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Aparece una persona sin fuente al lado.** Endurece las instrucciones para exigir la fuente en el punto de la afirmación, no solo en algún lugar de la respuesta. Un modelo que leyó un nombre de pasada mientras investigaba otra cosa puede repetirlo sin querer.
- **El informe no tiene sección "Could not confirm".** No se siguieron las instrucciones, o no se buscó nada que pudiera faltar de forma plausible. Revisa las llamadas a herramientas en la transcripción antes de fiarte de un informe que lo encontró todo.
- **Un `web_fetch` falla y el dato simplemente desaparece.** El modelo siguió adelante en lugar de probar una segunda fuente. Pídele que nombre lo que no pudo descargar, que es exactamente como se vio la laguna del formulario 990 en el run registrado.
- **Los datos financieros o de dirección parecen actuales pero tienen un año.** Comprueba la fecha junto a cada uno. Una página sin fecha de publicación con una fecha de descarga añadida no es la misma afirmación que una fechada según la fuente.
- **La misma organización tiene otra junta en un run repetido.** Los resultados de búsqueda no son estables entre runs. Comprueba de qué página salió cada nombre antes de fiarte de cualquiera de las versiones, y prefiere la página de la propia organización a un fragmento de búsqueda.

## Registra la prueba { #record-the-trial }

Guarda la pregunta, el informe, las fuentes que citó, el run en Activity con sus llamadas a herramientas y el coste. Una persona sigue leyendo el informe frente a sus fuentes antes de la llamada, decide si una laguna de "could not confirm" importa lo suficiente para buscarla a mano y nunca repite un detalle personal no confirmado, aunque un run posterior lo afirme con seguridad.
