---
source_sha: "95d57516d759"
title: "Revisa un contrato con tu lista de comprobación"
description: "Vincula a un agent una skill de revisión inicial, adjunta un breve contrato de servicios sintético y comprueba que encuentra los dos problemas plantados y la cláusula que falta sin dar asesoramiento jurídico."
---

# Revisa un contrato con tu lista de comprobación { #review-a-contract-against-your-checklist }

Construye un agent que lee un contrato adjunto y produce un extracto estructurado y una lista de desviaciones respecto a una lista de comprobación, no una opinión sobre si firmarlo. El ejemplo es un breve contrato de servicios sintético con dos problemas plantados y una cláusula que falta por completo. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- La capability **skills**, vinculada a una skill con la lista de revisión. Esta página instala `legal/document-review-first-pass` de la galería; consulta [skills](../skills.md#getting-skills-into-an-organization) para escribir la tuya. La galería incluye también `legal/contract-clause-library`, para consultar una cláusula aprobada y su posición alternativa cuando tengas una con la que comparar; este ejemplo no la necesita. La plantilla de agent `legal/contract-reviewer` combina ambas.
- Sin sandbox. Un archivo de texto adjunto se lee directamente desde el prompt; consulta [el procesamiento de archivos](../file-processing.md#chat-file-uploads).

## Prepara la entrada { #prepare-the-input }

Un breve contrato de servicios, inventado para esta página, guardado como `services-agreement.txt` y adjuntado en el chat:

```text
MASTER SERVICES AGREEMENT

This Agreement is made between Acme Consulting Ltd ("Provider") and Nimbus
Retail Ltd ("Client"), effective 1 January 2027.

1. Term
The initial term is 12 months from the effective date.

2. Services
Provider will deliver monthly analytics reporting as described in Schedule A.

3. Fees and Payment
Client will pay Provider 5,000 EUR per month, payable within 30 days of
invoice.

4. Confidentiality
Each party will keep the other's confidential information confidential
during the term and for 3 years after termination.

5. Liability
Each party's liability under this Agreement is unlimited.

6. Termination
Either party may terminate this Agreement for uncured material breach on 30
days' written notice.

7. Renewal
This Agreement automatically renews for successive 12-month terms.

8. Assignment
Neither party may assign this Agreement without the other party's prior
written consent.
```

Dos problemas plantados: la cláusula 5 no limita nada (responsabilidad ilimitada) y la cláusula 7 se renueva automáticamente sin ningún plazo de preaviso para detenerla. Falta una cláusula por completo: nada en el contrato indica la ley aplicable ni la jurisdicción.

## Construye el agent { #build-the-agent }

1. En **Skills → Skill gallery**, instala `Document review first pass` desde la sección legal.
2. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
3. En **Toolbox**, activa **Skills** y vincula la skill que acabas de instalar.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You produce a structured extract and a list of deviations from the bound
review checklist skill. You do not advise, do not conclude a clause is
acceptable, and do not redraft. Everything you produce is checked by the
person who reviews it before it is relied on.

Use the Document review first pass skill for what to extract and how to flag
deviations. Cite the clause number for every extracted term and every
deviation. Flag anything the checklist expects that the agreement does not
contain.
```

## Ejecútalo { #run-it }

Adjunta `services-agreement.txt` a una conversación nueva y envía:

```text
Review this services agreement against the checklist.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Responsabilidad | Marcada como desviación: sin límite, cl. 5 |
| Renovación | Marcada como desviación: sin plazo de preaviso para salir, cl. 7 |
| Ley aplicable y jurisdicción | Marcadas como ausentes por completo, no inventadas |
| Cada término extraído y cada desviación | Cita un número de cláusula |
| Tono | Expone hechos y desviaciones; no concluye que el contrato sea seguro, arriesgado o apto para firmar |
| Una pregunta sobre si firmar | Se niega a asesorar y remite al abogado responsable que revisa el resultado |

Lee tú mismo las desviaciones frente a las cláusulas de origen. Una desviación con un número de cláusula equivocado, o una lista de cláusulas ausentes que inventa algo que el contrato sí tiene, parecen trabajo minucioso en el chat.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El extracto calificó la responsabilidad de la cl. 5 como "unlimited" con "no exclusion of indirect/consequential loss", la renovación de la cl. 7 como sin "no opt-out/break notice mechanism", y enumeró "Governing law & jurisdiction" como ausente tanto en las desviaciones como en una tabla aparte de elementos que faltan, junto a indemnizaciones y cambio de control, elementos que la lista espera y que este breve ejemplo nunca incluyó. Terminó indicando que el extracto "requires verification by the fee earner responsible for this matter before being relied upon". Coste: 0,0249 USD.

    El primer intento falló antes de producir nada: el modelo llamó a `load_capability` con el id supuesto `document-review-first-pass` (con guiones, como el nombre de la galería), que no existe. El id de una skill vinculada es su nombre guardado exacto, "Document review first pass". Reintentó con una segunda suposición errónea y el run terminó con "the agent could not finish this turn", tras gastar 0,0083 USD en las dos suposiciones. Un intento nuevo en otra conversación usó el id correcto a la primera. Reintentar una vez es la solución práctica; si sigue adivinando mal, poner en las instrucciones el nombre guardado exacto de la skill elimina la suposición por completo.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El run falla con "could not finish this turn" antes de producir nada.** Consulta el run registrado arriba: una llamada a `load_capability` adivinó el id de la skill en lugar de copiarlo del catálogo. Reintenta en una conversación nueva o indica en las instrucciones el nombre exacto de la skill.
- **El agent te dice si firmar.** Endurece "you do not advise" y pruébalo directamente con una pregunta de seguimiento. Una herramienta de lista de comprobación que responde "sí, está bien" en cuanto alguien pregunta va más allá de su encargo.
- **Una desviación no tiene número de cláusula.** Las instrucciones lo piden en cada elemento; aun así merece la pena señalar una cita que falta en un hallazgo correcto, porque el siguiente lector no puede comprobarlo sin ella.
- **La lista de cláusulas ausentes inventa algo que el contrato tiene.** Lee el original directamente. La lista espera alrededor de una docena de elementos estándar; a un ejemplo corto siempre le faltarán varios, y el modelo tiene que acertar con los que de verdad faltan, no solo producir una lista larga.
- **Dos agents vinculados a la misma skill dan listas distintas.** La skill es una sola fila, compartida por nombre; comprueba en **Skills** que nadie tenga una propuesta sin publicar pendiente sobre ella. Consulta [un agent puede proponer un cambio; una persona lo hace](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Registra la prueba { #record-the-trial }

Guarda el texto exacto del contrato, la respuesta, la versión del agent, la versión de la propia skill y el modelo. Una persona sigue comprobando cada cita frente al original y decide qué hacer con cada desviación: el encargo del agent es sacarlas a la luz, no resolverlas.

## Siguientes pasos { #next-steps }

Añade `legal/contract-clause-library` cuando tengas una posición aprobada con la que comparar las cláusulas, para que una desviación pueda comunicarse con la alternativa real y no solo como "esto difiere del estándar". Para un contrato más largo con varios documentos que contrastar, [la búsqueda en el conocimiento](knowledge-base-assistant.md) responde a otra pregunta distinta de esta página: recuperar un fragmento de un corpus grande, en lugar de revisar de principio a fin un solo documento adjunto.
