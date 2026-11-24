---
source_sha: "30a1fb9a1506"
---

# Burst { #burst }

Una tarea se divide en subtareas independientes, se ejecutan en paralelo y
sus resultados se fusionan en un solo resultado: una ráfaga de trabajo
paralelo en lugar de una ejecución secuencial. El agente divide primero la
tarea y muestra la división a la persona, como `/burst` de OpenMausBot
muestra las partes por adelantado; luego una llamada reparte las partes
entre trabajadores en paralelo y devuelve la fusión.

Esto es el modo Burst de OpenMausBot v0.1.153 como capacidad: el concepto —
mostrar la división, ejecutar las partes en paralelo, combinar los
resultados — reconstruido sobre la ramificación que council (#5) y sol-loop
(#6) ya usan. El procedimiento vive en la skill `burst-mode`
(`backend/app/core/catalog/skills/burst-mode/SKILL.md`), que dice cuándo
dividir; esta página dice qué hace la capacidad con las partes.

## Cómo funciona una ráfaga { #how-a-burst-works }

El agente llama a `run_burst` con la tarea y las partes, cada parte un
prompt para su propio trabajador. Una llamada es una ráfaga: la llamada
ejecuta cada parte en paralelo con el propio modelo del run y fusiona lo
que vuelve, en orden de parte, bajo el encabezado propio de cada parte.

Después de una ráfaga, el agente actúa sobre las partes fallidas — las
reintenta, las hace directamente o reduce la tarea — y vuelve a llamar para
una ráfaga nueva. El límite de ráfagas evita que las ráfagas repetidas
amplíen el trabajo: corrige lo que falló, nada más. No vuelvas a ejecutar
toda la ráfaga para arreglar una parte: haz burst solo de las partes
fallidas.

Un trabajador de burst hace solo su parte y nada más. No rehace el trabajo
de otra parte ni amplía la tarea.

## Configuración { #configuration }

| Campo | Predeterminado | Qué es |
|---|---|---|
| `max_subtasks` | `3` | Cuántas subtareas ejecuta una ráfaga como máximo a la vez (2–10) |
| `max_bursts` | `3` | Cuántas ráfagas puede pedir un run como máximo (1–5) |

El límite de subtareas refleja el límite `max_fanout` de subagents —
predeterminado 3, máximo 10 — en lugar de elevarlo. Los trabajadores son
agentes ambientales de un solo uso con el propio modelo del run, medidos
contra el presupuesto del run; un rechazo por presupuesto registra la parte
como fallida en lugar de gastar más allá del límite.

## La fusión { #the-merge }

Cada ráfaga se registra en el manifiesto del run y se muestra como el
resultado fusionado que la skill de burst pone en la descripción de un PR:

```markdown
## Burst

Task: Write the guide

Parts: 3 - 3 completed, 0 failed.

| B1 | Part 1 | completed |
| B2 | Part 2 | completed |
| B3 | Part 3 | completed |
```

Una parte que falló se lee como `failed` con su motivo, y la fusión la
nombra bajo un encabezado `FAILED` con un pie que cuenta — nunca como una
parte que terminó, y nunca eliminada de la fusión. Una ráfaga que perdió
una parte nunca se lee como una que la terminó.

## Lo que no hace { #what-it-does-not-do }

- **Descartar una parte fallida.** Un trabajador que lanza una excepción o
  no devuelve nada utilizable se registra como `failed` con el motivo. La
  fusión lo dice.
- **Inventar un resultado.** La fusión son los resultados reales de las
  partes bajo sus propios encabezados. Nada se resume hasta desaparecer.
- **Elevar el límite de ramificación.** El límite de subtareas es el límite
  de subagents, no uno nuevo.
- **Delegar con una spec.** Los trabajadores de burst son agentes de un solo
  uso con el propio modelo del run, sin spec propia. Una parte que necesita
  sus propias herramientas, credenciales o un agente permanente es una
  delegación a través de la capacidad de subagents, no una parte de burst.
- **Puntuar el trabajo.** Las partes de burst trabajan; no juzgan. Una
  ráfaga que necesita ser juzgada es una ronda de council después de la
  fusión.
- **Arreglar lo que falló.** La ráfaga no arregla ni itera por sí sola. El
  agente reintenta, hace la parte directamente o reduce la tarea, y luego
  pide una ráfaga nueva.
- **Guardar ráfagas fuera del manifiesto.** Las ráfagas viven en el JSONB
  del manifiesto del run, junto a las peticiones, y se leen de vuelta a
  través del esquema del manifiesto. No hay tabla que migrar ni ráfaga que
  consultar entre runs.
- **Ejecutarse en una llamada en vivo.** Una ráfaga tarda minutos que una
  llamada no puede esperar, así que la capacidad se ejecuta en el gemelo de
  texto del agente, transferida desde la llamada.

La capacidad necesita el scope `agents:delegate`, porque sus trabajadores
son llamadas de modelo a las que el agente entrega trabajo.
