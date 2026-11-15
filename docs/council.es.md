---
source_sha: "5e91e7483c03"
---

# Consejo { #council }

Tres delegados revisan el trabajo antes de que salga: un modelo potente de
cada uno de tres proveedores distintos, con alto esfuerzo de razonamiento, en
paralelo. Cada delegado puntúa el trabajo sobre 10, y una revisión nueva
después de corregir es una ronda nueva. El ciclo continúa hasta que todos los
delegados queden satisfechos.

Esto es la skill del consejo como capability. El procedimiento está en la
skill `council-review`
(`backend/app/core/catalog/skills/council-review/SKILL.md`), que dice cuándo
pedir una revisión; esta página dice qué hace la capability con la respuesta.

## Cómo funciona una ronda { #how-a-round-works }

El agente llama a `run_council_review` con el trabajo y el contexto que
necesita. Una llamada es una ronda: la llamada reparte el trabajo entre los
delegados, cada uno en el modelo de su propio proveedor, y devuelve sus
puntuaciones con sus hallazgos.

Tras una ronda, el agente corrige lo que encontraron los delegados y vuelve a
llamar para pedir una ronda nueva, hasta que cada delegado puntúe por encima
del umbral de acuerdo. El límite de rondas es lo que impide que las revisiones
repetidas hagan crecer el trabajo: corrige lo que se pidió, nada más.

La revisión de un delegado es de solo lectura. Juzga el trabajo tal como
está; no lo edita ni propone trabajo fuera de su alcance.

## Configuración { #configuration }

| Campo | Predeterminado | Qué es |
|---|---|---|
| `members` | — | Exactamente tres delegados, cada uno con un nombre, un proveedor distinto y un perfil de modelo |
| `agreement_threshold` | `8` | La puntuación sobre 10 que cada delegado debe alcanzar para que una ronda satisfaga al consejo |
| `max_rounds` | `3` | Cuántas rondas de revisión puede pedir un run (1–5) |

Cada miembro revisa únicamente con el modelo **principal** de su perfil. La
cadena de reserva de un perfil nunca se usa aquí: una reserva sustituiría en
silencio a otro proveedor cuando el primero falla, y un consejo con dos
delegados en un proveedor no es un consejo.

## La tabla { #the-table }

Cada ronda queda registrada en el manifiesto del run y se muestra como la
tabla que la skill del consejo pone en la descripción de un PR:

```markdown
## Council review

Rounds: 2

| Delegate | Round 1 | Round 2 |
| --- | --- | --- |
| Claude Opus | 7/10 | 9/10 |
| GPT Sol | 8/10 | 10/10 |
| Gemini Pro | 7/10 | 9/10 |
```

Un delegado que no da puntuación se lee como `no score`. Uno al que no se
pudo llegar se lee como `unavailable`, con el motivo. A ninguno se le asigna
jamás una puntuación que no haya dado, y un miembro no disponible nunca se
sustituye.

## Lo que no hace { #what-it-does-not-do }

- **Corregir lo que encuentra.** El consejo juzga; el agente corrige y luego
  pide una ronda nueva.
- **Guardar puntuaciones fuera del manifiesto.** Las puntuaciones viven en el
  JSONB del manifiesto del run, junto a las peticiones. No hay tabla que
  migrar ni puntuación que consultar entre runs.
- **Ejecutarse en una llamada en vivo.** Una revisión lleva minutos que una
  llamada no puede esperar, así que la capability se ejecuta en el gemelo de
  texto del agente, transferido desde la llamada.

La capability necesita el scope `agents:delegate`, porque sus delegados son
llamadas de modelo a las que el agente entrega trabajo.
