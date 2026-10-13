---
source_sha: "2bdccaa6ec15"
---

# Traduce una página { #translate-a-page }

Este sitio se publica en inglés, polaco, alemán y español desde un único árbol
`docs/`. El inglés es la lengua de origen: una página se escribe primero en
inglés, y las otras tres son traducciones de ella que pueden quedarse atrás y de
las que se espera que lo digan cuando ocurre.

## Dónde vive una traducción { #where-a-translation-lives }

Una traducción se guarda junto a la página que traduce, con la locale en el
nombre del archivo.

```text
docs/install.md      the English source
docs/install.pl.md   Polish
docs/install.de.md   German
docs/install.es.md   Spanish
```

[mkdocs-static-i18n](https://github.com/ultrabug/mkdocs-static-i18n) construye un
sitio por locale a partir de ese árbol. El inglés conserva las URL que siempre ha
publicado — `/install/` sigue siendo `/install/` — y cada traducción se añade a su
lado en `/pl/install/`, `/de/install/` y `/es/install/`. El selector de idioma de
la cabecera se mueve entre ellas sin que el lector pierda su sitio.

Nada más cambia. No hay un archivo de navegación aparte, ni un segundo `docs_dir`,
ni una copia de `mkdocs.yml` por locale: la navegación de `mkdocs.yml` es
compartida, y sus títulos de sección los traduce la tabla `nav_translations` que
hay allí bajo cada locale. El título propio de una página en la barra lateral sale
del primer encabezado del archivo traducido, así que traducir el encabezado
traduce la entrada de navegación.

## Cada traducción registra de qué se hizo { #every-translation-records-what-it-was-made-from }

Lo primero en un archivo traducido es su front matter, y la huella que hay en él
es el sentido de todo el montaje:

```markdown
---
source_sha: "4f2b9c1ad07e"
---

# Instalacja
```

Esos son los primeros doce caracteres hexadecimales del SHA-256 de `install.md`
tal como estaba cuando se tradujo la página, tomados del texto con los finales de
línea normalizados, de modo que un checkout en Windows responde lo mismo que CI.
`scripts/docs_i18n.py` la calcula, y dos cosas la vuelven a leer.

`python3 scripts/check_docs_i18n.py` se ejecuta en `make lint` y hace fallar la
build ante una página sin traducción, ante una traducción cuya huella ya no
coincide con su fuente inglesa, y ante una traducción cuya página inglesa ha sido
renombrada o borrada.

La build del sitio lee esa misma huella y pone arriba, en el idioma del lector, un
aviso en cualquier página que esté sin traducir o atrasada. Sin él una locale
parece terminada cuando no lo está: una página que nadie ha traducido responde
igualmente en `/de/...`, en inglés, dentro de una navegación alemana, y nada la
distingue de una página que alguien sí tradujo.

!!! warning "`--update` es el último paso de traducir, no una forma de callar la alarma"

    `python3 scripts/check_docs_i18n.py --update docs/install.pl.md` estampa la
    huella inglesa actual sobre ese archivo. **Nombra los archivos que de verdad
    has vuelto a traducir**, y no se toca nada más — estampar una página que nadie
    ha vuelto a traducir oculta una traducción obsoleta tanto a la puerta como al
    lector, que es justo el único fallo que este diseño existe para evitar.

    Por eso acepta rutas en vez de actualizar todo lo que encuentra. Cambia dos
    páginas inglesas, vuelve a traducir una, y una actualización general marcaría
    las dos como al día: la página intacta conserva su texto viejo, pierde su
    aviso y nadie vuelve a mencionarla.

## Cada encabezado fija su ancla inglesa { #every-heading-pins-its-english-anchor }

Un encabezado traducido lleva el ancla de la página inglesa de forma explícita, en
la forma `attr_list`:

```markdown
## Berechtigungen { #permissions }
### Wer welche Rolle vergeben darf { #who-may-hand-out-which-role }
```

Sin eso, un encabezado traducido al alemán recibe un ancla alemana, y todo enlace
escrito como `../permissions.md#who-may-hand-out-which-role` aterriza al principio
de la página alemana en vez de en la sección. Hay más de cien enlaces entre
páginas en este sitio y muchos llevan un fragmento, así que esto no es un caso
raro — y `mkdocs build --strict` valida la ruta de un enlace pero **no** su
fragmento, de modo que nada más se da cuenta.

Fijarlas significa además que un mismo enlace funciona en los cuatro idiomas sin
reescribirse por locale, y que un enlace permanente que alguien haya compartido
sigue funcionando cuando cambia de idioma.

`scripts/check_docs_i18n.py` compara las dos listas de anclas en el orden del
documento, así que un encabezado que se pierde, se añade, se reordena o se queda
sin fijar hace fallar `make lint` y dice cuál es. Para leer la lista que tienes que
fijar antes de empezar:

```bash
python3 scripts/check_docs_i18n.py --anchors docs/permissions.md
```

No deduzcas el ancla a ojo. El encabezado que dice
`Layer 1: users.is_app_admin - the deployment superadmin` responde a
`layer-1-usersis_app_admin-the-deployment-superadmin`: el punto se cae en vez de
convertirse en un separador, y los guiones bajos sobreviven.

!!! note "Dos anclas de encabezado no te toca fijarlas a ti"

    A un encabezado repetido la extensión `toc` le añade `_1` — `screens.md` tiene
    dos titulados "MCP servers", y el segundo responde a `mcp-servers_1`. Fija el
    mismo texto en ambos y el sufijo se aplica igual a la traducción. Los
    encabezados de símbolo generados en las páginas de `docs/reference/` salen de
    los docstrings y no tienen ningún encabezado en el Markdown que fijar.

## Qué traducir y qué dejar en paz { #what-to-translate-and-what-to-leave-alone }

Traduce la prosa, los encabezados, las cabeceras de tabla y el texto de las celdas
que sea prosa, los títulos de las admoniciones, el texto alternativo de las
imágenes y el texto de los enlaces.

Deja lo siguiente exactamente como está en inglés:

| Nunca se traduce | Por qué |
|---|---|
| Los bloques de código, y todo lo que hay dentro | El lector los teclea al pie de la letra |
| Nombres de comandos, flags, variables de entorno | `make check`, `--strict`, `DATABASE_URL` |
| Rutas de la API, métodos HTTP, códigos de estado | `POST /api/v1/agents` |
| Claves de campo y de configuración | `spec_version`, `budget.monthly_cap` |
| Nombres de permisos | `agents:edit` es una cadena que el producto compara |
| Rutas de archivo y de directorio | `backend/app/core/vault.py` |
| Nombres de clases de error y de excepción | `AuthorizationError` |
| Nombres de producto | Docker Compose, PostgreSQL, Slack, Prefect |
| Bloques Mermaid | Una etiqueta con un corchete o una comilla dentro rompe el grafo, y la build no puede avisarte — Mermaid se renderiza en el navegador |
| Una etiqueta de la consola que el lector tiene que encontrar en pantalla | La interfaz está en inglés, así que `Admin → Response Ratings` es una referencia, no una frase |
| Rutas de imagen | Una captura sirve para las cuatro locales |

Un comentario dentro de un bloque de código es prosa que el lector lee en vez de
teclear, así que se puede traducir — pero solo donde el bloque sea una
ilustración. Nunca traduzcas un comentario de un bloque que alguien va a pegar,
porque al pegarlo se lo lleva.

## Los sustantivos propios del producto se quedan en inglés { #the-products-own-nouns-stay-english }

La consola ya lo hace, y por el mismo motivo: esas palabras nombran cosas que el
lector se encuentra también en la API, en el YAML que un spec exporta a su propio
repositorio, y en cada página inglesa de este sitio. Traducirlas aquí y en ningún
otro sitio le da a un producto dos vocabularios, y un lector polaco que busque la
palabra traducida no encuentra nada.

**agent · spec · capability · skill · embed · budget · run · prompt · provider ·
token · vault · workspace · sandbox · MCP**

Flexiónalos en vez de reemplazarlos, y traduce todo lo que los rodea.

| Inglés | Polaco | Alemán | Español |
|---|---|---|---|
| the agent's spec | spec agenta | der Spec des Agents | el spec del agent |
| publish a version | opublikuj wersję | eine Version veröffentlichen | publica una versión |
| grant a capability | przyznaj capability | eine Capability gewähren | concede una capability |
| the run failed | run zakończył się błędem | der Run ist fehlgeschlagen | el run ha fallado |
| a vault secret | sekret w vault | ein Secret im Vault | un secreto del vault |

Todo lo demás es vocabulario corriente y debe sonar natural: base de conocimiento,
organización, miembro, rol, permiso, aprobación, cap de budget, notificación,
canal, despliegue.

### Un sustantivo conservado necesita un género, y aquí lo recibe { #a-kept-noun-needs-a-gender-and-it-gets-one-here }

Un sustantivo inglés metido en una frase alemana, polaca o española tiene que
tomar un artículo y una terminación, y dejado a criterio de cada página toma uno
distinto. La primera pasada alemana produjo "der Sandbox" en una página y "ein
Sandbox" en otra; el lector se encuentra con las dos. Por eso la decisión se toma
una sola vez, aquí:

| Sustantivo | Alemán | Polaco | Español |
|---|---|---|---|
| agent | der Agent | ten agent, agenta | el agent |
| spec | der Spec | ten spec, speca | el spec |
| capability | die Capability | ta capability (nieodmienne) | la capability |
| skill | der Skill | ten skill, skilla | el skill |
| embed | das Embed | ten embed, embeda | el embed |
| budget | das Budget | ten budżet | el budget |
| run | der Run | ten run, runa | el run |
| prompt | der Prompt | ten prompt, promptu | el prompt |
| provider | der Provider | ten provider, providera | el provider |
| token | das Token | ten token, tokena | el token |
| vault | der Vault | ten vault, vaulcie | el vault |
| workspace | der Workspace | ten workspace, workspace'u | el workspace |
| sandbox | die Sandbox | ten sandbox, sandboksie | la sandbox |
| MCP server | der MCP-Server | ten serwer MCP | el servidor MCP |

El alemán los compone con guion cuando la segunda mitad es alemana — Run-Kosten,
Vault-Eintrag, Sandbox-Session — y conserva la mayúscula propia de la palabra
inglesa.

### Una persona sin nombre es masculina, en los tres idiomas { #a-generic-person-is-masculine-in-all-three-languages }

El inglés dice "the reader", "an operator", "whoever wrote the agent" sin elegir
género, y todos los idiomas de aquí tienen que elegir uno. Dejada a cada página,
la elección sale distinta: la primera pasada alemana produjo "der Betreiber" en
una página y "die Betreiberin" en la siguiente, para la misma persona, y un
lector se encuentra con ambas.

Por eso la forma genérica de un rol es masculina — der Leser, der Betreiber, der
Autor, der Entwickler, der Administrator, der Besitzer, der Kunde; czytelnik,
operator, autor; el lector, el operador, el autor. Esto vale para una persona a
la que nadie ha puesto nombre. Un ejemplo con nombre conserva el género que el
ejemplo le da, y lo mismo una frase sobre una persona concreta.

## Terminología que tiene que ser exacta { #terminology-that-has-to-be-exact }

Las páginas de permisos, governance y seguridad describen negativas, y una
negativa descrita a la ligera es peor que una no descrita. Mantén estas
distinciones en todos los idiomas:

| Inglés | La distinción que hay que preservar |
|---|---|
| permission / grant | Un permiso viene de un rol; un grant va pegado a un recurso y lo amplía |
| role / membership | La autoridad vive en una fila de pertenencia, no en un usuario |
| owner / admin / editor / viewer | Nombres de rol, comparados contra el catálogo — conserva el nombre inglés entre paréntesis en el primer uso |
| budget cap / spend | El límite, y lo que se ha gastado contra él |
| approval / refusal | Una decisión pendiente, y una que es definitiva |
| organization / deployment | Un inquilino, y la instancia instalada entera |
| published / draft | Una versión del spec que los agents ejecutan, y una que todavía no ejecuta nada |

Cuando una frase afirma qué rechaza la plataforma, traduce el rechazo
literalmente. No suavices "is refused" a "puede que no funcione", y no conviertas
una afirmación sobre lo que no puede ocurrir en un consejo sobre lo que no
deberías hacer.

## Los cuatro archivos que renderiza GitHub, no este sitio { #the-four-files-github-renders-not-this-site }

`README.md`, `CONTRIBUTING.md`, `SECURITY.md` y `CODE_OF_CONDUCT.md` se traducen
igual y se registran igual, y `scripts/check_docs_i18n.py` también pregunta por
ellos. Tres cosas cambian, y todas porque esos archivos los renderiza GitHub y
MkDocs no.

**La huella va en un comentario, no en el front matter.** GitHub renderiza un
bloque `---` como una tabla, así que un lector se encontraría `source_sha` antes
que el nombre del proyecto. `--update` escribe en su lugar
`<!-- source_sha: 4f2b9c1ad07e -->` en la primera línea, y la lee de ahí. En una
página del sitio el valor va entrecomillado, porque alrededor de una huella de
cada 281 es toda de dígitos decimales y YAML la leería como un número.

**Los encabezados no pueden fijar un ancla.** `{ #permissions }` es `attr_list`,
que es una extensión de Python-Markdown; GitHub no tiene equivalente e imprime
las llaves. Un encabezado traducido responde por tanto a su propia ancla,
derivada por la regla de GitHub y no por la de la extensión `toc` — parecida,
pero no la misma, porque GitHub conserva una letra que el sitio pliega a ASCII y
convierte cada espacio en su propio guion. Así que **reescribe todos los enlaces
que el archivo se dirige a sí mismo**, y comprueba el resultado:

```bash
python3 scripts/check_docs_i18n.py --anchors README.pl.md
```

La puerta compara la forma de las secciones en vez de las anclas — tantos
encabezados, anidados igual — y falla ante cualquier enlace interno al que no
responda ningún encabezado. Esa segunda mitad es la que atrapa un archivo dejado
a medio traducir: los encabezados sin traducir conservan la forma de aquellos de
los que se copiaron, así que la forma por sí sola no lo ve, pero los enlaces que
están encima siguen apuntando a encabezados que se han movido. Nada más se daría
cuenta, porque GitHub sirve un fragmento muerto como el principio de la página,
en silencio.

**Todos los demás enlaces apuntan al idioma del propio lector.** Un README en
español enlaza a `docs/install.es.md`, no a `docs/install.md` — si no, elegir
idioma dura exactamente un clic. La puerta comprueba cada uno contra el enlace de
la página inglesa en la misma posición, así que un enlace perdido, reordenado o
sin localizar la hace fallar. Una página sin traducción, como `docs/ROADMAP.md`,
se queda en inglés, y la barra de idiomas se deja en paz: apuntar a otros idiomas
es justo para lo que está.

**Cada archivo lleva una barra de idiomas** a sus tres traducciones, y las
traducciones enlazan de vuelta. Actualiza los cuatro cuando se añada un idioma.

`CHANGELOG.md` no se traduce, por la razón por la que `release-notes.md` tampoco:
es el historial de commits.

## Dos cosas que una locale no recibe { #two-things-a-locale-does-not-get }

Las páginas de referencia bajo `docs/reference/` las genera mkdocstrings a partir
de los docstrings de Python. Traducir uno de esos archivos traduce su prosa y sus
encabezados; la documentación de símbolos generada se queda en inglés, porque se
lee del código fuente en el momento de la build. Eso es intencionado — dilo en la
página en vez de parafrasear los docstrings en una segunda copia que se desvía.

`release-notes.md` muestra `CHANGELOG.md`, sustituido en el momento de la build.
Una página de notas de versión traducida traduce el marco propio de la página
alrededor del marcador; las entradas del changelog se quedan en inglés, porque son
el historial de commits.

## Buscar en polaco { #searching-in-polish }

lunr.js, que mueve la búsqueda del sitio, no tiene stemmer polaco, así que la
búsqueda en `/pl/` casa palabras enteras en vez de raíces. El alemán y el español
se lematizan con normalidad. No hay nada que configurar — la build lo dice en su
log — pero conviene saberlo antes de que alguien lo reporte como un fallo.

## El flujo de trabajo { #the-workflow }

1. Copia la página inglesa a `<page>.<locale>.md`.
2. Tradúcela, manteniendo idéntica la estructura de encabezados y fijando el ancla
   inglesa de cada encabezado.
3. Comprueba que cada enlace relativo sigue resolviendo. Un enlace a `../mcp.md`
   desde una página traducida resuelve automáticamente al `mcp.md` traducido; un
   enlace escrito como `../mcp.pl.md` es incorrecto y hace fallar la build.
4. `python3 scripts/check_docs_i18n.py --update <page>.<locale>.md` — el archivo
   que acabas de traducir, y ningún otro.
5. `make docs-build` — se ejecuta con `--strict`, así que un enlace muerto lo hace
   fallar.
6. `python3 scripts/check_docs_paragraphs.py` — el límite de 115 palabras por
   párrafo rige en todos los idiomas, y una traducción que funde dos párrafos
   ingleses en uno suele tropezar con él.

Cambiar una página inglesa es el mismo bucle desde el otro extremo: cámbiala y
luego o vuelves a traducir las tres traducciones en el mismo cambio, o las dejas y
que la puerta las reporte — lo que no puedes hacer es estampar `--update` encima.

## Resumen { #recap }

- Una traducción es `<page>.<locale>.md` junto a la página inglesa; las URL
  inglesas no se mueven.
- Su front matter registra la huella del texto inglés del que se hizo, y cada
  encabezado fija su ancla inglesa.
- `scripts/check_docs_i18n.py` hace fallar `make lint` ante una traducción que
  falta, está obsoleta o ha quedado huérfana y ante encabezados que no cuadran, y
  el sitio marca para el lector una página sin traducir u obsoleta.
- El código, los comandos, las claves, las rutas y los sustantivos propios del
  producto se quedan en inglés; todo lo que los rodea se traduce.
- La redacción sobre permisos y governance es exacta, no aproximada.
