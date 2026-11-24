---
source_sha: "eacd467a0b5c"
---

# Ajuste de herramientas con evals { #eval-tool-tuning }

Puntúa una herramienta con casos de eval ya juzgados y redacta propuestas
de ajuste a partir de los fallos. Una ejecución de ajuste toma los
resultados juzgados de un intento de eval - los casos que probó el bucle
de aprendizaje de fallos (#32) - y pregunta cómo se comportó una
herramienta en ellos: si se llamó, si se eligió la herramienta correcta,
si dio error, si la respuesta siguió sin dar en el blanco.

Este es el skill de ajuste de herramientas con evals como capability. El
procedimiento vive en el skill `eval-tool-tuning`
(`backend/app/core/catalog/skills/eval-tool-tuning/SKILL.md`), que dice
cuándo puntuar una herramienta; esta página dice qué hace la capability
con la respuesta.

## Cómo funciona una ejecución de ajuste { #how-a-tuning-run-works }

El agente llama a `record_eval_tool_tuning` con la herramienta y los casos
juzgados - cada caso con lo que su respuesta debía decir, si el juez dijo
que pasó, lo que dijo la respuesta y cada llamada a herramientas que hizo
la ejecución del caso. Una llamada es una ejecución de ajuste: puntúa la
herramienta, clasifica cada fallo, redacta una propuesta por clase de fallo
y registra la ejecución en el manifiesto.

Un fallo pertenece a una de cuatro clases:

| Clase | Qué significa |
|---|---|
| `not_called` | Ninguna herramienta se ejecutó en el caso - nunca se llegó a la herramienta |
| `wrong_tool` | Se eligió otra herramienta en su lugar |
| `bad_arguments` | Se llamó a la herramienta y dio error |
| `wrong_answer` | La herramienta se ejecutó sin errores, pero la respuesta siguió sin cumplir la expectativa |

Cada clase redacta un tipo de propuesta:

| Fallo | Propuesta | Qué cambia |
|---|---|---|
| `not_called`, `wrong_tool` | `tool_choice` | Qué herramienta se elige - una regla de enrutado, o preferir esta herramienta sobre la elegida |
| `bad_arguments` | `tool_parameters` | Los argumentos de la herramienta - sus campos obligatorios, rangos y qué cuenta como válido |
| `wrong_answer` | `prompt_wording` | Qué debe decir la respuesta - una línea en las instrucciones del agente |

Una propuesta por clase, no por caso: cinco casos que fallan igual son un
problema de ajuste, no cinco. Una puntuación sin fallos no redacta nada.

## Configuración { #configuration }

| Campo | Por defecto | Qué es |
|---|---|---|
| `max_tuning_runs` | `3` | Cuántas ejecuciones de ajuste puede registrar una ejecución (1–5) |

El límite evita que puntuar una y otra vez haga crecer el trabajo:
puntuar, mostrar los borradores, dejar decidir a una persona. Una nueva
ejecución de ajuste tras aplicar una propuesta es una ejecución nueva.

## El registro { #the-record }

Cada ejecución de ajuste se registra en el manifiesto de la ejecución y se
muestra en el cajón de la ejecución:

```markdown
## Ajuste de herramientas con evals

Herramienta: search · 1/2 superados · fallo más común: not_called

| Caso | Clasificación |
| --- | --- |
| total | passed |
| missing | not_called |

| Propuesta | Tipo | Evidencia |
| --- | --- | --- |
| Route these requests to search | tool_choice | missing |
```

## Qué no hace { #what-it-does-not-do }

- **Juzgar una respuesta.** El veredicto de cada caso llega ya juzgado,
  por el `judge()` del bucle de aprendizaje de fallos
  (`app/services/eval_judging.py`, compartido con los evals de flujo de
  trabajo). La puntuación consume pares `(passed, shown)`; un segundo juez
  se desviaría del primero, y la puerta de eval dejaría de significar una
  sola cosa.
- **Ejecutar evals.** Pasar casos por la ruta de ejecución de prueba es el
  corredor de intentos del bucle (#32). Hasta que #32 llegue, la
  herramienta toma casos juzgados como entrada; cuando #32 llegue, sus
  resultados de intento alimentarán esta herramienta.
- **Aplicar una propuesta.** Cada propuesta es un borrador con sus casos
  fallidos como evidencia, para que una persona lo apruebe. Aplicar un
  cambio de instrucciones pasa por la aplicación de propuestas del bucle
  (con puerta de eval, auditada); un cambio de skill por la ruta de
  skills aprendidos (#9). Aquí no hay función de aplicación.
- **Guardar ejecuciones de ajuste fuera del manifiesto.** Las ejecuciones
  viven en el JSONB del manifiesto de la ejecución, junto a las
  peticiones. No hay tabla que migrar ni ejecución de ajuste que consultar
  entre ejecuciones - las propias tablas del bucle guardan los casos, una
  vez que #32 llegue.

La capability no necesita ningún ámbito: su herramienta registra en el
propio manifiesto de la ejecución y no llama a ningún modelo, no delega
nada y no toca ningún servicio.
