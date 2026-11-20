---
source_sha: "ac197a8b5ef6"
---

# Babysit PR { #babysit-pr }

Observar un pull request en CI y bots de revisión, informar solo lo
que cambió y parar cuando los bots están en verde en el último commit.
Esta es la skill babysit-pr como capability: el procedimiento vive en
la skill `babysit-pr`
(`backend/app/core/catalog/skills/babysit-pr/SKILL.md`), que dice
cuándo observar; esta página dice qué hace la capability con una
instantánea.

## How a watch works { #how-a-watch-works }

El agente observa con la capability monitor — `start_monitor` sobre
`gh pr checks --watch` — y entrega cada instantánea nueva a
`babysit_pr_check` con el repo, el número de PR, el SHA del head y
los checks tal como se informaron. La herramienta clasifica la
instantánea: solo cuentan los checks del commit actual, cada check
fallido se nombra real o flake con su motivo, y solo se informan los
checks que cambiaron desde la última instantánea. Cuando nada cambió
y la observación continúa, el informe está vacío y el agente termina
su turno sin mensaje — nunca publica ni dice «sigo esperando».

La observación termina cuando la herramienta dice verde en el último
commit, cuando la observación supera su máximo configurado sin verde,
o cuando el agente la para con `babysit_pr_stop` — listo, bloqueado
o con una pregunta al usuario. Un merge o un cierre termina la
observación por sí solo. Antes de observar de nuevo, el agente
consulta `gh api rate_limit` y pasa lo que dice a
`babysit_pr_rate_limit`: mientras queden llamadas, observa de nuevo;
cuando están casi agotadas, espera al reset.

## Configuration { #configuration }

| Campo | Predeterminado | Qué es |
|---|---|---|
| `poll_interval_seconds` | `300` | Segundos entre revisiones del pull request (60–1800) |
| `max_watch_minutes` | `240` | Minutos que una observación puede durar antes de parar e informar bloqueo (30–1440) |

Las consultas están separadas por al menos 60 segundos, así el
watcher nunca consulta en un bucle cerrado ni agota el límite
compartido de GitHub. Una observación que supera su máximo sin verde
no ha sido aprobada — ha caducado.

## The watch log { #the-watch-log }

Cada check que cambió queda registrado en el manifiesto del run, con
su clasificación y la decisión a la que llevó. Una clasificación
flake es una heurística sobre el propio texto de fallo del check, no
un veredicto: el agente verifica cada hallazgo en la fuente antes de
descartarlo con un motivo escrito, y un fallo cuyo texto no coincide
con ninguna señal de infraestructura es real hasta que se demuestre
lo contrario.

## What it does not do { #what-it-does-not-do }

- **Fusionar, comentar o hacer cualquier otra acción en el PR.**
  Solo observar e informar. Un aviso es noticia, no una decisión de
  merge; el agente comprueba el merge gate, y fusionar necesita la
  petición explícita del usuario.
- **Ejecutar `gh` por sí misma.** Leer los checks es trabajo del
  agente, bajo la capability monitor. Esta capability clasifica
  instantáneas que recibe, así que no necesita credenciales de
  GitHub ni scope de sandbox.
- **Observar un PR que no le pertenece.** Un watcher por PR, y solo
  el hilo dueño del PR lo observa. Un hijo delegado nunca observa;
  empezar un segundo PR mientras uno está activo se rechaza.
- **Guardar eventos de observación fuera del manifiesto.** Los
  eventos viven en el JSONB del manifiesto del run, junto a las
  peticiones. No hay tabla que migrar ni evento que consultar entre
  runs.
