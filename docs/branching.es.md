---
source_sha: "c8b11ff21e6a"
---

# Ramas y qué las protege { #branches-and-what-protects-them }

Una sola rama de larga vida.

```
feat/… fix/… ──pull request──▶ main
```

`main` es lo que clona quien lee este repositorio y de donde se cortan los tags.
Todo lo que llega ahí lo hace como un commit aplastado desde una rama de vida
corta, después de que la CI haya corrido sobre la pull request.

Un push a `main` y un tag `v*` publican además, cada uno, las dos imágenes de
contenedor - `ghcr.io/vstorm-co/agenticos-backend` y `-frontend`, `edge` y
`sha-<short>` desde la rama, la versión y `latest` desde el tag - a través de
`.github/workflows/images.yml`. No tiene disparador de pull request, así que un
fork no puede publicar bajo el nombre de la organización, y rechaza un commit que
no esté en `main`, de modo que un tag empujado desde una rama tampoco puede mover
`latest`; [Deploy](deploy.md#the-images) dice qué las descarga.

No hay `dev`. Lo hubo, brevemente: el trabajo aterrizaba allí y llegaba a `main`
en pull requests de release. A este tamaño compraba una rama de staging que nadie
necesitaba y costaba un segundo sitio donde cada cambio tenía que esperar, así
que se eliminó.

## Qué se impone, y mediante qué { #what-is-enforced-and-by-what }

| Regla | Impuesta por |
|---|---|
| Ningún push directo a `main` | Ruleset — se exige una pull request |
| CI en verde antes del merge | Status checks obligatorios: `lint`, `test`, `test-frontend`, `e2e`, `docs`, `Security Scan` |
| Squash al hacer merge | Ruleset — el único método de merge permitido |
| Conversaciones resueltas | Ruleset |
| Aprobaciones caducadas descartadas al llegar un push nuevo | Ruleset |
| Ni force push ni borrado | Ruleset |
| Ningún commit hecho estando sobre `main` | `no-commit-to-branch` en `.pre-commit-config.yaml` |
| Ortografía, en todos los ficheros versionados | codespell — como hook sobre los ficheros que toca un commit, y como `make lint-spelling` en el job `lint` de la CI sobre todo el árbol |
| Las rutas solo contienen routers, sin comentarios de cabecera, sin código muerto | `check_routes.py`, `check_comments.py` y `vulture` — hooks en `.pre-commit-config.yaml` (cada uno escanea todo el árbol, `pass_filenames: false`) y pasos de `make lint-backend` en el job `lint` de la CI |
| Ninguna dependencia declarada que nadie importe | `deptry` — un paso de `make lint-backend` en el job `lint` de la CI, que bloquea sobre DEP002 y DEP004. No es un hook de pre-commit: lee el manifiesto entero contra el árbol entero, así que no existe una versión por fichero de la pregunta |
| Formato del YAML, seguridad de los workflows, lo básico de pre-commit, en todos los ficheros versionados | yamlfmt, zizmor y `pre-commit-hooks` (`end-of-file-fixer`, `trailing-whitespace`, `check-yaml/json/toml`, `detect-private-key` …) — como hooks sobre los ficheros que toca un commit, y como `make lint-precommit` en el job `lint` de la CI sobre todo el árbol. Igual que la ortografía, por naturaleza van por fichero, así que una subida de `rev:` que traiga una regla nueva rompe todos los ficheros existentes sin que nada lo note hasta que una edición ajena es rechazada por ella |

Un hook solo lee lo que toca un commit, lo que lo convierte por sí solo en una
mala barrera: una falta de ortografía que se fusiona junto a su fichero se queda
ahí hasta que alguien edita ese fichero por un motivo ajeno, y su commit es
rechazado por una palabra que no escribió. Por eso la comprobación ortográfica
aparece dos veces en la tabla — el hook es la respuesta rápida, `make
lint-spelling` es lo que mantiene cierta la afirmación para todo el árbol.

Hoy los status checks están listados uno a uno. Deberían colapsar en un único job
agregador `All Checks Passed`, para que añadir un job de CI deje de significar
"acordarse de editar un ruleset" — una lista de checks obligatorios que se
desvía del workflow es la manera en que un build acaba aprobando sobre nada.

### Un check obligatorio puede legítimamente informar `skipped` { #a-required-check-may-legitimately-report-skipped }

!!! info "Un check obligatorio en `skipped` es un aprobado, no un problema"

    GitHub da por satisfecho un status check obligatorio con `success`, `skipped`
    **o** `neutral`. Así que una rama que solo toca el backend no recibe respuesta
    alguna del frontend - lo que significa que "verde" en una rama así es una
    afirmación sobre menos jobs de los que corre `make check`.

Tres de esos seis no corren en cada pull request. `test`, `test-frontend` y `e2e`
cuestan 8,2, 5,3 y 5,1 minutos facturados cada uno, y un job `changes` decide a
cuáles de ellos un conjunto de cambios no puede afectar de forma demostrable —
`scripts/ci_changed_scope.py`, para que la regla sea comprobable en lugar de un
glob en un fichero YAML
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

Por eso la barrera es un `if:` a nivel de job y **no** un filtro `paths:` sobre el
workflow: un workflow filtrado no publica sus checks en absoluto, así que el
ruleset espera seis contextos que nunca llegarán y el botón de merge se queda gris
para siempre.

El clasificador está escrito en la dirección tímida: **un job solo se salta cuando
toda ruta modificada le es demostrablemente irrelevante**, de modo que una ruta no
reconocida lo ejecuta todo.

La formulación permisiva de la misma idea dejaría que un directorio nuevo impidiera
en silencio que una suite corriera — lo que no es un build en rojo sino uno en
verde al que le falta una barrera, y este repositorio ya lo ha pagado dos veces
(#143, #165).

Solo existen dos exenciones, ambas comprobadas en vez de supuestas:

- `docs/**`, `mkdocs.yml` y un `*.md` de primer nivel, porque ningún test lee nada de eso;
- la mitad opuesta del árbol, para cada una de las dos suites unitarias.

`e2e` no está exento de ninguna de las dos mitades, y `lint` no se filtra jamás —
porque `make lint-spelling` y `make lint-precommit` leen todos los ficheros
versionados.

La segunda exención se detiene antes de un directorio. `frontend/src/app/api/**`
es el BFF, y `backend/tests/api/test_bff_forwarded_paths.py` comprueba las rutas
`/api/v1/…` que esos handlers llevan escritas a mano contra la propia tabla de
rutas del backend — así que un cambio en un proxy también ejecuta la suite del
backend. Saltársela ahí sería el mismo fallo de verde-sin-barrera de arriba, sobre
el único test escrito para atraparlo.

Dos detalles que la dirección tímida necesita para sostenerse de verdad, y que la
primera versión de esto tuvo mal:

- Cada job filtrado lleva `!cancelled()` junto a la comprobación de la salida. Sin
  eso, un job `changes` que **fallara** — un 502 de la API, un límite de peticiones
  — se saltaría las tres suites sin que sus condiciones llegaran a leerse nunca, y
  como `changes` no es en sí un contexto obligatorio, el botón de merge se pondría
  verde sobre una rama donde no corrió ninguna suite.
- El job le pasa `previous_filename` además de `filename`. Un renombrado informa
  solo de la ruta a la que llegó, así que un módulo sacado de `backend/` sería si no
  una ruta de frontend y se saltaría la suite del backend para un cambio que borró
  un módulo del backend.

Lo que un conjunto de cambios se salta se imprime en el log del job `changes`. En
local no se salta nada: `make check` ejecuta el conjunto entero.

### Una pull request apilada también ejecuta la CI { #a-stacked-pull-request-runs-ci-too }

A dos ramas que editan el mismo fichero se les pide apilarse — la segunda se abre
contra la primera en lugar de contra `main` — así que el disparador `pull_request`
de `ci.yml` **no lleva filtro `branches:`**. Ese filtro compara contra la *base*, y
mientras estuvo ahí una pull request apilada no coincidía con ningún disparador y
no ejecutaba nada en absoluto
([#359](https://github.com/vstorm-co/agenticos/issues/359)).

La mitad peligrosa no era la ejecución ausente, era cómo se leía. Una pull request
sin jobs muestra una lista de checks **vacía**, no una roja: `gh pr checks`
responde "no checks reported" y el resumen sale vacío, lo que parece una ejecución
que aún no ha arrancado. Cuatro pull requests se fusionaron así en un solo día,
verificadas únicamente en un portátil. Nada cerró el hueco hasta que la hija se
reapuntó a `main` tras fusionarse su madre, que es justo el momento en que nadie
espera siete minutos por una ejecución nueva.

Cuesta poco: el job `changes` clasifica a una hija apilada sobre su propio diff —
lee `pulls/{n}/files`, que es la comparación contra la base de esa misma pull
request — y el grupo de concurrencia de más abajo cancela las ejecuciones
superadas de la hija como las de cualquier otra.

Que el disparador no lleve filtro de base se afirma en vez de suponerse, en
`backend/tests/test_ci_workflow.py`. Tiene que ser así: un workflow que no se
dispara no produce prueba alguna de que no lo hizo, así que nada de una ejecución
puede revelar la regresión. El mismo fichero afirma la otra propiedad que ninguna
ejecución puede mostrar — que cada job acota su propio tiempo de ejecución, abajo.

Dos límites que conviene decir con claridad. **Una pull request apilada en verde
se comprobó contra su madre, no contra `main`** — los checks pertenecen a un commit
de cabecera, así que reapuntarla arrastra el resultado antiguo sin cambios; eso es
inherente al apilado y no algo que un disparador pueda arreglar, y es una razón
para mantener las pilas cortas. Y **CodeQL no está configurado aquí**: corre desde
la configuración por defecto de GitHub, cuyos disparadores no están en este
repositorio, así que si lee o no una pull request apilada no nos toca decidirlo.

### Cada job acota su propio tiempo de ejecución { #every-job-bounds-its-own-runtime }

`changes` era el único job de `ci.yml` que llevaba un `timeout-minutes`, así que
los otros siete heredaban el valor por defecto de GitHub, **360 minutos**
([#364](https://github.com/vstorm-co/agenticos/issues/364)), de modo que un job
atascado habría retenido su status check obligatorio durante seis horas sin que
nada en este repositorio lo terminara antes. Aquello se escribió como precaución
frente a algo que nadie había visto. Catorce ejecuciones de `e2e` alcanzaron el
límite en los cuatro días hasta el 18 de agosto
([#879](https://github.com/vstorm-co/agenticos/issues/879)) — y qué aspecto tiene
un job cuando lo hace está más abajo.

| Job | Límite | Observado |
|---|---|---|
| `changes` | 5 | 7s |
| `lint` | 10 | 22s |
| `Security Scan` | 10 | 14s |
| `docs` | 15 | 4m34s |
| `test-frontend` | 20 | 5m08s |
| `docker` | 20 | 2m30s |
| `test` | 25 | 7m43s |
| `e2e` | 25 | 8m01s |

Los tiempos observados vienen de la ejecución 31116003994, una matriz completa
sobre `main`. Cada límite es varias veces su job en vez de quedar justo por
encima: el timeout existe para terminar un atasco, y uno tan ajustado como para
cortar una caché legítimamente fría es un build en rojo por una razón ajena al
diff.

### Una ejecución por rama { #one-run-per-branch }

`ci.yml` lleva un grupo de concurrencia con clave `github.ref`, así que volver a
empujar a una rama cancela su ejecución anterior. Importa porque `CLAUDE.md` pide
un commit y un push por cada pieza terminada: sin nada que cancelara, 75 de las 369
ejecuciones de los primeros seis días de agosto quedaron superadas mientras seguían
en vuelo — unos 1.800 minutos facturados respondiendo preguntas sobre commits que
nadie estaba esperando.

**Un push a `main` está exento, y lo interesante es la manera en que se le exime.**

La ejecución del propio merge es lo que hace que la historia y la insignia
signifiquen algo, así que una ejecución sobre `main` no debe ni cancelarse ni
encolarse.

`cancel-in-progress: false` solo da lo primero. `false` significa *encolar*, y
GitHub cancela cualquier ejecución **pendiente** anterior de un grupo cuando se
encola una más nueva.

Con un solo grupo para `main` — el merge A corriendo, el B pendiente — la llegada
de C cancelaría el B sin más, y el commit de B no recibiría CI alguna. Con catorce
releases en seis días frente a una ejecución de `main` de unos 10 minutos, dos
merges dentro de una misma ventana no es una forma rara.

Por eso el grupo lleva `github.run_id` en un push, que es único por ejecución: cada
merge obtiene un grupo propio y no choca con nada. Las pull requests se resuelven
todas al mismo sufijo y siguen cancelándose entre ellas según `github.ref`.

### Dos cosas informan `cancelled`, y solo una de ellas lo es { #two-things-report-cancelled-and-only-one-of-them-is-that }

La sección de arriba es la cancelación que funciona según lo diseñado, y es la
explicación a la que todo el mundo recurre. **La otra es un job que agotó su
`timeout-minutes`** — GitHub registra como `cancelled`, y no como fallo, un job que
terminó al llegar al límite — y un check obligatorio en `cancelled` *no* se trata
como aprobado, al contrario que uno en `skipped`, así que el merge sigue bloqueado
sobre un diff que está bien.

Distinguirlas cuesta una sola mirada:

| | Superada (#317) | Terminada en su límite (#879) |
|---|---|---|
| Qué más hay en la ejecución | todos los jobs en vuelo cancelados a la vez | **un** job; el resto están en verde |
| La conclusión de la propia ejecución | `cancelled` | `success`, salvo ese job |
| Duración del job cancelado | lo que hubiera alcanzado | su `timeout-minutes`, al segundo |
| Un push más nuevo en la rama | sí — esa es la causa | no |
| La última línea del log | `The operation was canceled.` | la misma línea, que es la trampa |

La duración es la señal. `gh api repos/vstorm-co/agenticos/actions/runs/<id>/attempts/<n>/jobs`
da `started_at`, `completed_at` y las conclusiones por paso — **y tiene que ser la
forma `attempts/<n>`**, porque una reejecución reescribe lo que responde el
endpoint `runs/<id>/jobs` a secas, de modo que un job reejecutado hasta ponerse
verde informa allí `success` y la conclusión original ha desaparecido.

Lo que las catorce tenían en común era un paso: `playwright install --with-deps`
invocando `apt-get`, que se atasca sin límite cuando el espejo de Azure del runner
es inalcanzable. El job e2e ya no instala paquetes del sistema en absoluto, y
`backend/tests/test_ci_workflow.py` rechaza un paso que lo hiciera. La lección
general sobrevive a ese paso, eso sí: **un paso que llega a un tercero es un paso
que puede colgarse sin un límite propio**, y el que lo hace se gasta el
presupuesto entero del job y luego informa como si fuera la cancelación de otro.

## Squash, y por qué importa el título de la pull request { #squash-and-why-the-pull-request-title-matters }

!!! important "La descripción de la pull request *es* el mensaje de commit que sobrevive"

    `main` guarda un commit por pull request, construido a partir del título y del
    cuerpo y no de los commits de la propia rama. `CLAUDE.md` tiene el formato.

Así que `wip`, `fixup` y `try again` nunca llegan ahí — y la descripción no es una
cortesía.

## La escotilla de escape { #the-escape-hatch }

!!! warning "No hay actores con bypass"

    Un owner que necesita fusionar algo ya desactiva el ruleset, fusiona y lo
    vuelve a activar - tres clics y una entrada de auditoría, que es la cantidad
    justa de fricción para algo que debería ser raro.

Es deliberado: un bypass siempre disponible es un bypass que se usa semanalmente, y
un camino de release que nadie sabe describir.

## Actualizaciones de dependencias { #dependency-updates }

El backend corre semanalmente, con los frameworks de agentes agrupados aparte de
todo lo demás — se mueven rápido y este código está pensado para seguirles el
paso. El frontend corre mensualmente, tras un enfriamiento de siete días.

Dependabot propone actualizaciones de las dependencias **directas**. Todo lo que
cuelga de ellas se mueve solo cuando una directa se lo lleva por delante, y por eso
existe `.github/workflows/dependency-freshness.yml`: una vez por semana actualiza
el lock entero — paquetes transitivos incluidos —, ejecuta la suite completa contra
él y abre una issue si eso rompe algo. No se hace commit de nada; la actualización
se tira junto con el runner. `make deps-upgrade-all` es lo mismo en local, y es la
manera de reproducir una issue roja salida de ahí.

Dos cosas al respecto no son obvias, y ambas costaron tiempo antes de entenderse:

- **Un patrón de grupo tiene que llevar un `*` final para casar con una dependencia
  escrita con extras.** `pydantic-ai-slim[openrouter,…]` no casa con
  `pydantic-ai-slim`. Ese silencio costó meses: el grupo `agent-frameworks` no
  abrió ni una sola pull request, y el runtime viajaba en
  `backend-everything-else` con sus versiones mayores. En cambio `fastapi` se
  queda exacto porque está declarado sin extras y no necesita comodín; antes
  necesitaba evitar uno, ya que `fastapi*` también atrapaba a `fastapi-cache2`,
  hasta que esa dependencia se eliminó en #155.
- **Dependabot no puede actualizar `frontend/bun.lock`.** Su ecosistema npm conoce
  `package-lock.json`, `yarn.lock` y `pnpm-lock.yaml`, y no el de bun. Así que una
  subida del frontend llega como `package.json` a secas y `bun install
  --frozen-lockfile` rechaza el desajuste, poniendo `test-frontend` y `e2e` en rojo
  por una razón ajena a la dependencia. **Regenéralo a mano** en la rama de la pull
  request:

  ```bash
  cd frontend && bun install --lockfile-only && git commit -am "build(deps): sync bun.lock"
  ```

  Automatizar eso es más difícil de lo que parece: un workflow sobre
  `pull_request` recibe un token de solo lectura cuando lo disparó Dependabot, diga
  lo que diga su bloque `permissions`, así que no puede empujar el resultado de
  vuelta.

## Reviews { #reviews }

El [revisor automatizado](code-review.md) corre en cada pull request. Nunca es un
check obligatorio, así que no puede hacer fallar un build — pero sus hallazgos son
hilos de review, y el ruleset de arriba exige que estén resueltos. Responder no
basta — alguien tiene que marcar el hilo como resuelto antes de que vuelva el botón
de merge. Véase [code-review.md](code-review.md).

La mitad de calidad de CodeQL abre hilos en los mismos términos, como
`github-code-quality[bot]`. No se puede filtrar por regla ni por ruta — el único
interruptor es apagarlo, para un lenguaje entero, que no es un trueque que merezca
la pena — así que
[code-review.md](code-review.md#codeql-and-the-findings-that-block-a-merge)
enumera en su lugar los hallazgos ya dictaminados, y resolver uno de esos cuesta un
clic en vez de un ensayo.

## Resumen { #recap }

- **Una sola rama de larga vida.** Rama, pull request, squash al hacer merge.
- Un push cancela la ejecución en vuelo, así que volver a empujar es también la
  decisión de dejar de preocuparse por la respuesta anterior.
- La CI ejecuta **menos jobs que `make check`** — un check obligatorio saltado es un
  aprobado, no un problema.
- `main` está exenta de la cancelación, y la manera en que lo está es un grupo de
  concurrencia que lleva `github.run_id` — único por ejecución, así que ninguna
  ejecución de `main` cancela otra.
