---
source_sha: "9d46f3e89ce9"
title: "Traduce documentos con tu propia terminología"
description: "Vincula a un agent un glosario de diez términos y comprueba que se aplica cada término, que los términos que no se traducen y los números se conservan, y que una ambigüedad se señala en lugar de resolverse en silencio."
---

# Traduce documentos con tu propia terminología { #translate-documents-with-your-terminology }

Dale a un agent un documento breve en inglés y una skill con tu glosario, y haz que lo traduzca a otro idioma manteniendo en inglés los nombres de producto, los nombres de funciones y los demás términos que no se traducen. El ejemplo incluye una fecha realmente ambigua, para que puedas comprobar si el agent la señala en lugar de adivinar en silencio. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Sin sandbox ni modelo de embeddings: este agent solo necesita la [capability skills](../reference/capabilities.md#skills) y un archivo adjunto en el chat.

## Prepara la entrada { #prepare-the-input }

Guarda esto como una skill en **Skills → New skill**. Llámala `fenwick-glossary` y dale una descripción como "Which terms in a Fenwick Ledger document stay in English, and the preferred Polish translation for the rest." Fenwick Ledger es un producto de contabilidad sintético inventado para esta prueba.

```text
Fenwick Ledger is a synthetic accounting product used only for this test.

## Keep in English, never translate

- Fenwick Ledger (product name)
- Quick Close (feature name)
- workspace
- API key
- sandbox

## Translate using these terms

| English | Polish |
|---|---|
| ledger | księga |
| invoice | faktura |
| reconciliation | uzgadnianie |
| dashboard | pulpit |
| audit trail | ślad audytu |

Numbers, dates and currency amounts are copied exactly as they appear in the
source — do not reformat a date or convert a currency. If a sentence in the
source could be read two ways, translate the more likely reading and add one
line after the translation flagging the ambiguity and both readings.
```

Después guarda este documento sintético como `release-notes.md`. La fecha `03/04/2026` es ambigua a propósito entre la lectura con el día primero y con el mes primero: es el caso que este ejemplo quiere comprobar.

```text
Fenwick Ledger 4.2 release notes

This release adds Quick Close, a one-click way to close the monthly ledger
once every invoice is matched. Quick Close runs the reconciliation for the
current period and shows the results on the dashboard.

Every action Quick Close takes is written to the audit trail, so a
controller can see which invoices were matched automatically and which
needed a manual review.

To use Quick Close in a shared workspace, generate an API key from Settings
and add it to your sandbox environment before running your first close.

The reconciliation step handles invoices up to EUR 50,000 automatically;
anything above that amount is queued for manual approval.

Close the March books by 03/04/2026, before the quarterly audit begins.

Fenwick Ledger is a synthetic product created for this test; no real company
or software is described here.
```

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Skills** y vincula la skill `fenwick-glossary`.
3. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You translate documents into Polish.
Follow the bound glossary skill: never translate the terms it lists as
English-only, and use its preferred Polish translation for the rest.
Copy every number, date and currency amount exactly as it appears in the
source.
If a sentence could be read two ways, translate the more likely reading and
add one line after the translation flagging the ambiguity and both readings.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent, adjunta `release-notes.md` y envía:

```text
Translate the attached release notes into Polish.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Cinco términos del glosario traducidos | ledger→księga, invoice→faktura, reconciliation→uzgadnianie, dashboard→pulpit, audit trail→ślad audytu |
| Cinco términos que no se traducen conservados | Fenwick Ledger, Quick Close, workspace, API key y sandbox aparecen en inglés |
| Importe sin cambios | `EUR 50,000` aparece exactamente así, sin convertir ni reformatear |
| Fecha sin cambios | `03/04/2026` aparece exactamente así, sin pasar a un formato de fecha polaco |
| Ambigüedad señalada | Una nota aparte nombra las dos lecturas de `03/04/2026` |
| La misma petición sin archivo adjunto | El agent pide el documento en lugar de traducir nada |

Lee el texto polaco frente al glosario término a término; no te fíes de un resumen que solo enumera los términos encontrados.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent llamó a `load_capability` para `fenwick-glossary` y luego tradujo todo el documento en una sola respuesta. Los cinco términos del glosario se tradujeron correctamente y los cinco que no se traducen (incluidos `workspace`, `API key` y `sandbox` dentro de frases en polaco) se dejaron en inglés. `EUR 50,000` y `03/04/2026` se copiaron sin cambios. Coste: 0,017 USD.

    El agent añadió una nota señalada después de la traducción: leída con el día primero, 03/04/2026 es el 3 de abril de 2026 (la usada en la traducción); leída con el mes primero, es el 4 de marzo de 2026. Recomendó confirmar cuál se quería decir. Sin archivo adjunto, cargó el glosario y luego pidió el documento en lugar de traducir nada.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Un término que no se traduce acaba traducido.** Puede que el modelo lo trate como vocabulario corriente y no como nombre propio; pon la lista al principio del contenido de la skill y repite la indicación en las instrucciones del propio agent.
- **Cambia un número.** Pide al agent que cite la frase de origen junto a su traducción; una discrepancia se ve de inmediato.
- **La ambigüedad se resuelve en silencio.** Endurece las instrucciones para exigir una línea de aviso aparte en lugar de dejar la elección a la redacción por defecto de la skill.
- **El agent traduce sin archivo adjunto.** Endurece las instrucciones para exigir que se niegue cuando no haya documento.

## Registra la prueba { #record-the-trial }

Guarda el documento de origen, el contenido del glosario, la traducción, la versión del agent y el run en Activity. Una persona que lea el idioma de destino sigue comprobando la fluidez de la traducción y confirma qué lectura de una ambigüedad señalada se quería de verdad: el glosario y las comprobaciones de arriba detectan la terminología y los valores conservados, no si la frase suena natural.

## Siguientes pasos { #next-steps }

Para un glosario de producción, mantén una skill por par de idiomas en lugar de una sola skill con todos los idiomas mezclados, para que cada traductor pueda revisar y editar solo su par. [La entrada de DeepL](../mcp.md#automation-storage-productivity-media) del catálogo MCP es un motor de traducción alternativo que puedes conectar en lugar de usar el modelo directamente; esta página no lo usa.
