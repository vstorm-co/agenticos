---
source_sha: "dfc8e7b908eb"
title: "Escribe descripciones de producto a partir de un archivo de catálogo"
description: "Adjunta un pequeño products.csv sintético y haz que un agent escriba una descripción de ficha por fila, señalando la fila a la que le falta un atributo obligatorio en lugar de inventarlo."
---

# Escribe descripciones de producto a partir de un archivo de catálogo { #write-product-descriptions-from-a-catalogue-file }

Adjunta un pequeño archivo de catálogo a un agent de chat sencillo vinculado a una skill de textos para fichas, y comprueba que escribe una descripción por producto sin inventarse nada que no diga la ficha técnica. A una fila le falta a propósito un atributo obligatorio, para que puedas comprobar si el agent señala el hueco en lugar de rellenarlo. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Sin sandbox ni modelo de embeddings: basta un agent de chat con la [capability skills](../reference/capabilities.md#skills), y el CSV es lo bastante pequeño para pegarse en el prompt como texto.
- Lectura opcional: **Skills → Skill gallery → e-commerce** tiene una skill `Product description writer` con las mismas reglas que usa esta página, y la plantilla de agent `ecommerce/listing-writer` de la misma galería muestra un agent más completo construido en torno a ella, con conocimiento y conexiones MCP. La skill de esta página está escrita a partir del contenido de esa entrada.

## Prepara la entrada { #prepare-the-input }

Guarda esto como `products.csv`. Cuatro filas están completas; la columna `material` de `FW-104` está vacía a propósito: es el hueco que este ejemplo quiere comprobar.

```csv
sku,name,category,material,size_run,weight_g,fit_note,care,box_contents
FW-101,Harbor Rain Jacket,Outerwear,recycled nylon 100%,S-XXL,410,true to size,machine wash cold,jacket and stuff sack
FW-102,Harbor Wool Beanie,Accessories,merino wool 100%,one size,80,one size fits most,hand wash cold,beanie only
FW-103,Harbor Steel Water Bottle,Drinkware,stainless steel,650 ml,320,not applicable,dishwasher safe lid only,bottle and lid
FW-104,Harbor Canvas Tote,Bags,,38 x 42 x 10 cm,260,not applicable,spot clean,tote bag only
FW-105,Harbor Trail Socks (2-pack),Apparel,merino wool blend 60%,S/M and L/XL,60,true to size,machine wash cold,two pairs of socks
```

Guarda esto como una skill en **Skills → New skill**, con el nombre `listing-copy-from-spec`, adaptada de `ecommerce/product-description-writer` de la galería:

```text
Copy that describes a product the customer does not receive is the most
expensive sentence in e-commerce.

## Work only from the spec

Every claim traces to the spec sheet, the supplier data or a photograph. If
the material is not stated, the description does not name a material.

## The shape

One line saying what it is and who it is for; three to five bullets of
concrete attributes with numbers; one short paragraph on use; then the full
specification as given.

## Concrete beats enthusiastic

"320 gsm, pre-shrunk, fits true to size" outperforms "premium quality".
Numbers survive translation, reduce returns and answer the question that
would otherwise become a support ticket.

## Always include

Dimensions with units, materials, care, what is in the box, and — for
anything worn — the fit note. Missing fit information is the single largest
driver of apparel returns.

## Never

Claim a certification, a country of origin, a health benefit or a
compatibility that the source does not state.
```

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Skills** y vincula `listing-copy-from-spec`.
3. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You write product listing descriptions from an attached catalogue file.
Follow the bound listing-copy-from-spec skill for shape and rules.
Write one description per row of the attached CSV.
If a row is missing an attribute the skill says to always include, do not
invent it: name it as missing in that product's description instead.
Return the result as a markdown table: sku, name, then the description.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent, adjunta `products.csv` y envía:

```text
Write listing descriptions for every product in the attached catalogue.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Número de filas | Cinco descripciones, una por SKU |
| Números | Pesos, medidas y capacidades coinciden exactamente con el CSV, con sus unidades |
| El material que falta en FW-104 | Señalado como ausente en esa descripción, sin nombrar ningún material |
| Nota de talla presente | En FW-101, FW-102 y FW-105, los tres artículos que se llevan puestos |
| Atributos que nunca se afirman | Ninguna certificación, país de origen, beneficio para la salud ni afirmación de compatibilidad en ningún sitio |
| La misma petición sin archivo adjunto | El agent dice que falta el archivo y no se inventa ningún catálogo |

Comprueba primero FW-104: un atributo que falta y se rellena en silencio es el fallo que este ejemplo existe para detectar.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent cargó la skill vinculada y luego escribió cinco descripciones en una sola respuesta, una por fila. Cada número (650 ml, 320 g, 38 x 42 x 10 cm, 60 % merino, S/M y L/XL) coincidía con el CSV. Para FW-104 escribió "Material composition is not specified in the product data and has not been stated in this listing" en lugar de nombrar un tejido. Las notas de talla aparecieron en la chaqueta, el gorro y los calcetines; no apareció ninguna afirmación de certificación, origen ni salud. Coste: 0,053 USD.

    Sin archivo adjunto, el agent cargó igualmente la skill, luego dijo "I don't see any attached catalogue file or CSV in your message" y pidió el archivo, en lugar de escribir descripciones de la nada.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Se inventa un material o una medida para FW-104.** Se está ignorando la sección "Never" de la skill; repite la indicación en el campo de instrucciones del propio agent, no solo en la skill.
- **El agent llama a `load_capability` con un id equivocado y el turno termina en error.** Ocurrió durante la verificación, cuando la skill estaba vinculada con el nombre y las mayúsculas exactos de la entrada de la galería (`Product description writer`): el modelo adivinó dos veces un id distinto y el turno terminó en `UnexpectedModelBehavior` en lugar de una negativa normal. Volver a crear el mismo contenido como una skill nueva con un nombre sencillo, en minúsculas y con guiones, lo resolvió en cada reintento. Poner el nombre guardado exacto de la skill en las instrucciones del agent elimina la suposición, como describe [la revisión de contratos](contract-review.md); si una skill instalada desde la galería sigue fallando, copia su contenido en una skill nueva con un nombre sencillo.
- **Falta la nota de talla en un artículo que se lleva puesto.** Pregunta qué atributo nombra para esa fila la sección "Always include" de la skill; una nota de talla ausente es el motivo de devolución que la skill existe para evitar.
- **La respuesta se salta una fila.** Pide el número de filas antes de fiarte de la tabla: entran cinco filas, salen cinco descripciones.

## Registra la prueba { #record-the-trial }

Guarda el CSV, el contenido de la skill, las cinco descripciones, la versión del agent y el run en Activity. Guarda también un run en el que se inventara el atributo que falta, si llega a ocurrir: es la prueba más clara de que hay que endurecer la redacción de la skill.

Una persona sigue decidiendo si una descripción está lista para publicarse y resuelve el hueco señalado antes de que la ficha salga; la comprobación de arriba detecta un dato inventado, no una descripción sosa.

## Siguientes pasos { #next-steps }

Para un catálogo real, vincula una [colección de conocimiento](set-up-knowledge-base.md) con las fichas técnicas de los proveedores en lugar de pegar filas, y añade la skill `ecommerce/review-response` de la misma sección de la galería para responder preguntas de clientes sobre un producto con la misma disciplina de fuentes.
