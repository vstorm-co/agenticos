---
source_sha: "1fe0c9faf3be"
---

# Sol-loop { #sol-loop }

Un revisor juzga el trabajo antes de que salga, en rondas, hasta que pasa
o se agota el presupuesto. La ronda 1 revisa todo el cambio; las rondas
posteriores revisan solo el código cambiado y los hallazgos abiertos. El
agente corrige lo que el revisor encontró y vuelve a llamar para una ronda
nueva.

Esta es la skill sol-loop como capability. El procedimiento está en la skill
`sol-loop` (`backend/app/core/catalog/skills/sol-loop/SKILL.md`), que dice
cuándo pedir una revisión; esta página dice qué hace la capability con la
respuesta.

## Cómo funciona una ronda { #how-a-round-works }

El agente llama a `run_sol_loop_review` con el trabajo y el contexto que
necesita. Una llamada es una ronda: la llamada pide al único revisor
configurado un veredicto y hallazgos con ids estables.

Después de una ronda, el agente corrige lo que el revisor encontró y vuelve
a llamar para una ronda nueva, hasta que el veredicto sea APPROVE sobre el
diff actual. El límite de rondas es lo que impide que las revisiones
repetidas hagan crecer el trabajo: corrige lo que se pidió, nada más. Una
ronda cuyos hallazgos son todos nits se detiene antes: no hay ronda nueva
para los nits rechazados.

La revisión de un revisor es de solo lectura. Juzga el trabajo tal como
está; no lo edita, no hace commit, no comenta, ni inicia subagentes o
revisores.

## Configuración { #configuration }

| Campo | Predeterminado | Qué es |
|---|---|---|
| `reviewer` | — | El único revisor: nombre, proveedor y perfil de modelo |
| `max_rounds` | `3` | Cuántas rondas de revisión puede pedir un run como máximo (1–5) |

El revisor revisa solo con el modelo **principal** de su perfil. La cadena
de fallback de un perfil nunca se usa aquí: un fallback sustituiría en
silencio otro modelo cuando el primero falla, y una revisión por un sustituto
no es la revisión que el operador configuró. El código no exige que el
modelo sea un modelo Sol: el operador apunta el perfil del revisor a su
modelo Sol, y nombrar una versión en el código quedaría obsoleto en cuanto
salga un Sol más nuevo.

## El registro { #the-ledger }

Cada ronda queda registrada en el manifiesto del run, y se muestra como el
registro de hallazgos que lleva la skill sol-loop:

```markdown
## Sol-loop review

Rounds: 2

| Round | Scope | Verdict | Stop |
| --- | --- | --- | --- |
| 1 | full | CHANGES | — |
| 2 | changed-only | APPROVE | approved |

| Finding | Severity | File | Outcome |
| --- | --- | --- | --- |
| S1 | blocker | app/x.py | agree-fixed |
```

Un hallazgo al que nadie ha respondido aún se lee como `open`. Un revisor al
que no se pudo llegar se lee como `unavailable`, con el motivo: nunca un
veredicto que no dio, y nunca una aprobación. El fin del presupuesto se lee
como `budget_exhausted`, y tampoco es una aprobación. Un hallazgo que sigue
en disputa después de dos respuestas se lee como `stuck`: decide el usuario.
El uso de la revisión se lee como `not exposed`: la llamada de revisión
devuelve solo la revisión, nunca su consumo de tokens.

## Qué no hace { #what-it-does-not-do }

- **Corregir lo que encuentra.** Sol-loop juzga; el agente corrige, y luego
  pide una ronda nueva.
- **Guardar rondas fuera del manifiesto.** Las rondas viven en el JSONB del
  manifiesto del run, junto a las peticiones. No hay tabla que migrar ni
  ronda que consultar entre runs.
- **Sustituir a un revisor.** Un revisor cuyo modelo no se resolvió se
  reporta como no disponible, nunca se reemplaza por otro modelo.
- **Adivinar el uso.** El registro dice que el uso no está expuesto, en lugar
  de inventar un número.
- **Correr en una llamada en vivo.** Una revisión lleva minutos que una
  llamada no puede esperar, así que la capability corre en el gemelo de texto
  del agente, entregada desde la llamada.

La capability necesita el scope `agents:delegate`, porque su revisor es una
llamada de modelo a la que el agente entrega trabajo.
