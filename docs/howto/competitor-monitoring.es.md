---
source_sha: "a28e7805a24a"
title: "Vigila páginas web en busca de cambios con una programación"
description: "Consulta dos páginas según una programación, compara cada una con lo que se registró la última vez, e informa solo de lo que cambió."
---

# Vigila páginas web en busca de cambios con una programación { #watch-web-pages-for-changes-on-a-schedule }

Crea un agent que consulte un pequeño conjunto de páginas, guarde un resumen
breve de lo que vio y, en el siguiente run, diga qué cambió — o que no cambió
nada. El fixture vigila dos páginas que no controlas pero que cambian poco: la
página de releases de GitHub de un proyecto y `example.com`. Es un
procedimiento que ejecutar, con dos disparos registrados como referencia.

Dos disparos prueban dos cosas distintas. **Run now** prueba que la lógica de
comparación funciona. No prueba que un cambio *real* llegue a detectarse nunca
— solo un disparo que llega después de que la página cambiara de verdad
demuestra eso, y esta página no puede registrar uno a voluntad.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Ninguna colección de knowledge, ninguna conexión MCP y ninguna conexión de
  sandbox: el workspace que usa esta receta no necesita nada de eso. Ver más
  abajo.

## Por qué no los archivos de memoria { #why-not-memory-files }

La capability obvia para "recuerda lo que vi la última vez" son los
[archivos de memoria](../reference/capabilities.md#memory-files). Aquí no
funciona, y vale la pena saber por qué antes de recurrir a ella en una
programación.

Un disparo de trigger se ejecuta como su creador a efectos de budgets,
aprobaciones y el rastro de auditoría, pero no a efectos de memoria: la
*audiencia* del run — quién va a oír la respuesta — está deliberadamente
vacía en la superficie `schedule`, así que un run sin nadie escuchando no
puede leer ni escribir las notas personales de su creador. `write_memory` y
`read_memory` responden ambas:

```text
This conversation has no memory. It has no identified person and is not a
group chat, so a note would have to land somewhere other people read. Answer
from what you have rather than saving.
```

El mismo agent, al que se le hace la misma pregunta en un chat normal, guarda
la nota sin problema — el almacén existe ahí porque hay una persona real
escuchando. En una programación, nadie escucha.

## Qué usar en su lugar { #what-to-use-instead }

Un workspace de [sandbox](../sandbox.md) con ámbito de **conversación**
persiste a través de cada disparo de un trigger, porque un trigger abre una
conversación para toda su vida y añade cada disparo a ella — el
`conversation_id` del que depende un workspace no depende de quién esté
escuchando. El backend `state` no necesita ninguna conexión de sandbox: es un
pequeño almacén en la propia base de datos de este deployment, sin shell y
sin contenedor.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Web fetch**. Restringe `allowed_domains` a
   `github.com` y `example.com`, para que al agent no se le pueda pedir que
   consulte ninguna otra cosa.
3. Activa **Files & shell**. Deja el backend en **Files** (el backend
   `state` — sin shell, sin conexión de sandbox) y el ámbito en **This
   conversation** — los valores por defecto son exactamente lo que necesita
   esta receta.
4. Define un budget y un límite de pasos para la prueba. Cada disparo
   registrado costó entre 0,07 y 0,14 USD.
5. Pon las instrucciones de abajo y pulsa **Publish**.

```text
You watch two pages for changes, once per run:
- https://github.com/vstorm-co/agenticos/releases
- https://example.com/

Each run:

1. Fetch both pages with web_fetch.
2. For the GitHub page, keep only the latest (topmost) release: its tag and
   title. For example.com, keep its heading and first paragraph. Ignore
   everything else on each page - star counts, timestamps, navigation.
3. Look for a file named watch-state.txt in your workspace.
4. If it does not exist, write it now with today's two summaries, one line
   per page, and report that you recorded a baseline - not a change.
5. If it exists, read it and compare each page's new summary to the line
   stored for it. Report, page by page, either the old and new value or
   "no change". Then overwrite watch-state.txt with the new summaries.
Never say a page changed unless the two lines you compared actually differ.
```

## Crea la programación { #create-the-schedule }

Abre **Routines → New schedule**, o la pestaña **Availability** del agent,
elige el agent y define una cadencia diaria. El prompt solo necesita nombrar
la tarea:

```text
Run today's page check.
```

## Ejecútalo { #run-it }

Pulsa **Run now** en la programación dos veces, con unos minutos de
diferencia. El primer disparo no encuentra ningún `watch-state.txt` y escribe
una base de referencia. El segundo la lee y compara.

!!! warning "Publicar un arreglo no mueve una programación en marcha hasta él"

    Publicar acuña una versión pero no reapunta el
    [entorno](../environments.md) del que lee una programación, a menos que
    ese entorno siga la última versión — cosa que `production` no hace por
    defecto. Si editas el agent después de crear el trigger, promociona la
    versión nueva a ese entorno (**Promote v2 to…**, con tu número de
    versión) antes del siguiente **Run now**, o el disparo sigue ejecutando
    la versión que acabas de sustituir.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Primer **Run now** | Informa de una base de referencia, no de un cambio, y ninguna página se dice distinta |
| `watch-state.txt` tras el primer disparo | Existe, con una línea por página |
| Segundo **Run now** | Lee el mismo archivo y dice "sin cambios" para ambas páginas |
| Una página que editaste entre dos disparos | Informa del valor antiguo y el nuevo solo para esa página |
| La superficie del run en Activity | `schedule` en ambos disparos, mismo trigger, misma conversación de registro |
| Un run con `web_fetch` apuntado a un tercer dominio | Rechazado — `allowed_domains` no lo incluye |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El primer **Run now**
    llamó a `web_fetch` sobre ambas páginas, después a `read_file` sobre
    `watch-state.txt`, que falló porque el archivo aún no existía, y después
    a `write_file`. Informó de que el último release de la página de GitHub
    era `v0.0.504` y del encabezado y párrafo de example.com, y dijo que esto
    era una base de referencia. Coste: 0,13 USD. El segundo **Run now**, un
    minuto después, leyó el mismo archivo, hizo coincidir ambos resúmenes e
    informó "No change" para las dos páginas, y después reescribió el archivo
    con el mismo contenido. Coste: 0,14 USD.

    El primer intento usó `memory_files` en vez de una sandbox, exactamente
    como advierte esta página: ambos disparos llamaron a `read_memory` y
    recibieron el rechazo de "sin memoria" de arriba, y el agent le dijo
    correctamente a la persona que leía el informe que no había podido
    guardar una base de referencia — en vez de afirmar que lo había hecho.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Cada disparo dice "sin estado previo", nunca una comparación.** El
  workspace no está persistiendo. Comprueba que el ámbito es **This
  conversation**, no **Nobody** — el ámbito `run` abre un workspace nuevo y
  vacío en cada disparo.
- **`read_memory` o `write_memory` aparece en la transcripción.** Los
  archivos de memoria siguen vinculados. Quítalos; no pueden hacer este
  trabajo en una programación.
- **Un cambio real de la página no se informa.** Solo lo detecta un disparo
  que se ejecuta después del cambio y después de un disparo que registró el
  estado previo. Revisa en Activity los dos disparos a cada lado del cambio,
  no solo el último.
- **Cada disparo informa de un cambio, aunque nada se haya movido.** El
  resumen es demasiado amplio — una consulta directa de la página incluye
  contadores de estrellas, marcas de tiempo relativas o un nonce cambiante
  que difiere en cada consulta. Reduce lo que las instrucciones conservan al
  único dato que importa.
- **El disparo se sigue comportando como la versión antigua después de volver
  a publicar.** Ver la advertencia sobre el entorno de arriba.

## Registra la prueba { #record-the-trial }

Conserva las dos URL de página, las instrucciones, la versión del agent,
`watch-state.txt` tras cada disparo, y cada run en Activity con su superficie
y coste. Una persona sigue decidiendo qué cuenta como un cambio que merece
actuar, y observa el primer disparo que llega tras una edición real para
confirmar que la comparación lo detecta — un par de `Run now` solo prueba la
lógica, nunca ese disparo.
