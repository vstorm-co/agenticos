---
source_sha: "7588e57ff61c"
title: "Revisa un cambio en un repositorio"
description: "Haz que un agent monte un pequeño repositorio git en su sandbox, revise un diff con la skill code-review incluida y comprueba que encuentra los dos errores plantados en las líneas correctas."
---

# Revisa un cambio en un repositorio { #review-a-change-in-a-repository }

Dale a un agent una [sandbox](../sandbox.md) y la skill `code-review` incluida, haz que monte un pequeño repositorio git y que revise el diff de un commit. El diff lleva dos errores plantados, un off-by-one y un `None` sin controlar, en posiciones file:line que puedes comprobar a mano. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo y una [conexión de sandbox](../sandbox.md) registrada cuyo runtime por defecto sea `workbench`, que incluye `git`.
- La skill `code-review`, que viene con cada organización; consulta [Skills](../skills.md#getting-skills-into-an-organization).
- Nada más que adjuntar: el propio agent crea el repositorio en la sandbox a partir del contenido exacto de los archivos del prompt de abajo.

## Prepara la entrada { #prepare-the-input }

Aquí no hay archivo que adjuntar. El "repositorio" son dos pequeños archivos de Python que el agent escribe por su cuenta siguiendo tu indicación, así que controlas exactamente lo que contiene el diff. La versión 1 es una calculadora de carrito sencilla:

```python
# utils.py (version 1)
def compute_total(prices):
    total = 0
    for p in prices:
        total += p
    return total


def find_discount_tier(count):
    tiers = [(10, 0.05), (20, 0.10), (50, 0.15)]
    for threshold, rate in tiers:
        if count >= threshold:
            return rate
    return 0.0
```

```python
# main.py (version 1)
from utils import compute_total, find_discount_tier


def checkout(cart):
    prices = [item["price"] for item in cart]
    total = compute_total(prices)
    rate = find_discount_tier(len(cart))
    return total * (1 - rate)
```

La versión 2 añade un descuento para socios y una función auxiliar `apply_discount`, con dos errores plantados: el nuevo parámetro `member_rate` de `main.py` vale `None` por defecto y se usa sin comprobarlo, y `apply_discount` de `utils.py` descuenta todos los artículos, incluido el más caro, y luego vuelve a añadir ese mismo artículo, contándolo dos veces.

```python
# utils.py (version 2, adds apply_discount)
def apply_discount(prices, rate):
    """Discount every item except the single most expensive one."""
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    discounted = [sorted_prices[i] * (1 - rate) for i in range(n)]
    discounted.append(sorted_prices[-1])
    return discounted
```

```python
# main.py (version 2)
from utils import compute_total, find_discount_tier, apply_discount


def checkout(cart, member_rate=None):
    prices = [item["price"] for item in cart]
    tier_rate = find_discount_tier(len(cart))
    discounted_prices = apply_discount(prices, tier_rate)
    total = compute_total(discounted_prices)
    return total * (1 - member_rate)
```

Referencia: el diff entre las dos versiones tiene exactamente dos defectos reales. `return total * (1 - member_rate)` en `main.py` lanza `TypeError` siempre que `member_rate` se queda en su valor por defecto, y `apply_discount` en `utils.py` devuelve un artículo de más, porque su bucle ya incluye el último índice antes de volver a añadir ese mismo artículo. Ni `compute_total` ni `find_discount_tier` cambian entre versiones, así que una revisión correcta no dice nada sobre ellas.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Files & shell**. Elige **Container**, selecciona tu conexión de sandbox y el runtime `workbench`, y mantén el alcance de conversación.
3. Activa **Skills** y vincula `code-review`.
4. Fija un budget para la prueba. El run registrado usó unos 40 pasos y costó unos 0,18 USD, sobre todo por las aprobaciones repetidas de la shell.
5. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You review a change in a git repository using the bound code-review skill.
Follow that skill: read the whole change before commenting, say what is wrong
and why it matters, and separate what blocks from what does not.
Only report issues that are actually in the diff. Do not report a problem in a
line the diff did not touch.
Cite every finding as file:line and give a concrete fix.
```

## Ejecútalo { #run-it }

Abre un chat nuevo y pega las dos versiones de arriba junto con las instrucciones para montar el repositorio y revisar el cambio:

```text
Set up a tiny git repository in your workspace and review one change in it.

1. Create a directory `grocery_calc`, write utils.py and main.py exactly as
   given above (version 1), then git init, configure a throwaway user, and
   commit them as the initial version.
2. Replace both files with version 2 exactly as given above, and commit that
   as a second commit.
3. Run `git diff HEAD~1 HEAD` to get the exact change, then review that diff
   using the bound code-review skill. Report every real defect the diff
   introduces, each as file:line with a concrete fix. Do not report anything
   about a line the diff did not change.
```

Cada llamada a `execute` que hace el agent (`git init`, cada commit, el diff) muestra **Tool approval required** en el chat. Lee el comando y pulsa **Approve** en cada una; el run continúa desde donde se detuvo. Para saltarte esto con un agent de prueba de confianza, cambia la configuración de aprobación de `execute` en el Builder. Consulta [las aprobaciones](../governance.md#approvals).

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| `None` sin controlar encontrado | `main.py:9`, `return total * (1 - member_rate)` falla cuando `member_rate` se queda en su valor por defecto `None` |
| Off-by-one encontrado | `utils.py:20-21`, la comprehension ya cubre todos los índices, incluido el último, y después ese artículo se añade por segunda vez |
| Ambos citados como file:line | No solo "hay un error en apply_discount" |
| La corrección es concreta | Un fragmento corregido, no solo una descripción del problema |
| Código sin cambios | Ningún hallazgo sobre `compute_total` ni `find_discount_tier`, que el diff no tocó |
| Bloqueante o no | Los dos errores se marcan como bloqueantes; lo estilístico lleva el prefijo "nit" |

Lee el diff tú mismo antes de fiarte de la revisión: `git diff HEAD~1 HEAD` en el panel de archivos del workspace muestra exactamente lo que revisó el agent.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent cargó la skill `code-review`, luego leyó con `read_skill_resource` su `checklist.md` y `review-comment.md`, después escribió los dos archivos, hizo dos commits y ejecutó el diff: tres llamadas a `execute`, cada una aparcada para aprobación. Tras aprobarlas respondió con tres hallazgos bloqueantes y un nit.

    Citó `main.py:9` para el `TypeError` con un `member_rate` ausente, con una corrección de dos líneas, y `utils.py:20-21` para el artículo contado dos veces, con un `apply_discount` corregido, coincidiendo exactamente con los dos errores plantados. También señaló que el diff no tenía pruebas, siguiendo la regla de la lista de la skill de que un cambio de comportamiento necesita una prueba. No dijo nada sobre `compute_total` ni `find_discount_tier`. Coste: 0,18 USD en 40 pasos, la mayor parte por las tres rondas de aprobación.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent dice que no tiene shell.** La capability usa **Files** en lugar de **Container**. Cambia a Container y elige el runtime `workbench`.
- **El run se detiene después de `git init` o de un commit.** Está esperando la aprobación de `execute`. Abre el chat o la pestaña **Approvals** en **Activity**.
- **La revisión informa de algo en código sin cambios.** Endurece las instrucciones: debe revisar solo lo que muestra `git diff`, no el archivo entero.
- **Un hallazgo no tiene file:line.** Pídele que vuelva a leer las plantillas de comentario de la lista, que siempre nombran una ubicación.
- **El primer turno es lento.** Se está construyendo la imagen `workbench`; las sesiones posteriores la reutilizan. Consulta [la sandbox](../sandbox.md#when-a-build-is-paid-for).

## Registra la prueba { #record-the-trial }

Guarda las dos versiones exactas, el diff, la revisión, la versión del agent y cada comando aprobado en Activity. Una persona sigue decidiendo si las correcciones son acertadas y si "no hay prueba para esto" debe bloquear de verdad el merge. La skill enuncia esa regla, pero aplicarla a un pull request real es decisión de una persona, igual que con [el estándar de revisión local](../code-review.md) que este proyecto sigue en sus propios PR.

## Siguientes pasos { #next-steps }

Conecta el mismo agent a una sandbox con acceso a red y haz que revise un diff de un repositorio público clonado en lugar de uno que le dictes. El runtime `workbench` tiene `git` y red, así que `git clone` funciona igual que aquí `git diff`.
