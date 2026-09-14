---
source_sha: "097a2caa4c8d"
---

# Licencias y avisos de terceros { #licences-and-third-party-notices }

!!! abstract "Lo que esta página afirma, y lo que no"

    Todo componente que contienen las dos imágenes publicadas está listado con su
    licencia y con la evidencia de esa licencia, y toda obligación que imponen
    esas licencias o bien se cumple de una forma que esta página nombra, o bien
    queda registrada como hallazgo abierto con una issue detrás. No dice "todas
    las licencias cumplen": hay un hallazgo abierto mientras esto se escribe, y
    está listado más abajo en lugar de diluirse en la media. Otros dos se
    revisaron y se zanjaron — el componente AGPL, que tiene una sección propia, y
    la imagen de Redis, que se sustituyó.

AgenticOS en sí es Apache-2.0 (`LICENSE`, `NOTICE`). Lo que un despliegue ejecuta
de verdad es ese código más unos quinientos paquetes de terceros, dos imágenes
basadas en Debian, un puñado de tipografías e iconos, y los servicios y modelos
que ese despliegue conecte. Esta página es la revisión de todo eso: qué entra en
el alcance, cómo se produce el inventario, qué pide cada familia de licencias y
cómo se le responde, y qué hacer cuando cambia una dependencia o un modelo.

## Qué entra en el alcance { #what-is-in-scope }

| Capa | De dónde sale el inventario | ¿La distribuye este proyecto? |
|---|---|---|
| Distribuciones de Python del backend | `backend/uv.lock`, resuelto para Linux con `uv export --no-dev` | Sí, en `agenticos-backend` |
| Paquetes npm del frontend | el cierre de producción de `frontend/package.json`, desde `frontend/bun.lock` | Sí, en `agenticos-frontend` |
| Las imágenes base y los paquetes Debian que instala la imagen del backend | `backend/Dockerfile`, `frontend/Dockerfile` | Sí, como capas de ambas imágenes |
| Tipografías, glifos de marca, archivos de datos incluidos | `frontend/src/app/fonts/`, `NOTICE`, `backend/app/core/catalog/` | Sí |
| Imágenes de servicios que un despliegue ejecuta junto a las dos anteriores | los archivos de compose | No: las descarga el operador |
| Pesos de modelos | se eligen por despliegue en un perfil de modelo | No: nunca se distribuyen |
| Providers y servicios alojados | se configuran por despliegue con una credencial en el vault | No: son un contrato entre el despliegue y el provider |

Las herramientas de desarrollo y de documentación (`uv sync --dev`, el grupo de
dependencias `docs`, `devDependencies`) no están en las imágenes ni en los avisos.
Las herramientas de compilación que se ejecutan en una fase de builder y no están
en la capa final, como `uv`, quedan registradas en `licenses/components.toml` como
no distribuidas.

## El inventario { #the-inventory }

Lo llevan dos archivos, y un script los mantiene honestos.

**[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md)**
se genera y se versiona. Para cada distribución de cualquiera de las dos imágenes
registra el nombre, la versión, la expresión de licencia SPDX, la URL del código
fuente y la evidencia de la que se leyó la licencia: una cabecera
`License-Expression`, un classifier, el texto del propio archivo de licencia, el
índice de paquetes, o un override que registró una persona. También lista primero
los hallazgos abiertos, un recuento de componentes por licencia y los componentes
registrados a mano.

**`licenses/policy.toml`** guarda las decisiones. Una entrada `override` es la
licencia que una persona determinó para un componente cuyos metadatos no la
declaran, con la evidencia que leyó; solo se aplica mientras los metadatos sigan
callados. Una entrada `notices` es el titular del copyright de un paquete que no
distribuye archivo de licencia y no nombra autor. Una entrada `review` es la
decisión sobre un componente bajo una licencia copyleft, share-alike o no abierta:
`accepted`, diciendo cómo se cumple la obligación, u `open`, apuntando a la issue
que se hace cargo de ella. **`licenses/components.toml`** registra lo que ningún
lockfile sabe: las imágenes, los paquetes Debian, las tipografías, los glifos, los
archivos de datos y las imágenes de servicios, cada uno con un estado y su
obligación.

`scripts/license_inventory.py` lee los tres. `make licenses` regenera los avisos;
`make licenses-check`, que ejecutan el job `security` y `make check`, los regenera
en memoria y falla cuando:

- los avisos versionados difieren de lo que ahora resuelven los lockfiles, en
  cualquier componente, versión, licencia o fuente (la celda de evidencia no se
  compara: dos wheels de una misma release pueden llevar metadatos distintos, y
  esa celda registra de dónde leyó la licencia esta máquina);
- los metadatos de un componente no nombran licencia y ningún override registra
  una, o hay un override registrado para un componente cuyos metadatos ahora sí
  nombran una;
- un paquete no distribuye archivo de licencia y además no nombra autor (y ninguna
  entrada `notices` registra al titular), o declara una licencia sin texto bajo
  `frontend/licenses/texts/`;
- un componente está bajo una licencia del conjunto de revisión y no tiene
  decisión;
- la decisión se tomó sobre una licencia distinta de la que el componente lleva
  ahora, porque una actualización la cambió;
- una decisión nombra un componente que los lockfiles ya no resuelven.

Un hallazgo abierto del que se hace seguimiento no hace fallar la comprobación. La
línea del veredicto lo cuenta:
`LICENSES: REVIEWED - 518 components, 1 open finding(s)`.

!!! warning "El «desconocido» de un escáner es una pregunta, no una aprobación"

    El script nunca adivina. Un `BSD` a secas en un campo `License` no se resuelve
    a un número de cláusulas por suposición; decide el archivo de licencia, y si
    ese tampoco es legible la comprobación falla hasta que alguien lo lee y anota
    la respuesta. La columna de evidencia de los avisos es lo que permite a quien
    revisa distinguir una licencia declarada de una inferida.

El inventario es lo que instala un despliegue, no lo que tiene la máquina que
ejecuta el script. Los marcadores de entorno se evalúan para Linux en las dos
arquitecturas para las que se compilan las imágenes, los paquetes npm específicos
de plataforma solo se conservan cuando compilan para Linux glibc en x64 o arm64, y
de un paquete que la máquina no tenga se leen los metadatos de PyPI o del registro
de npm. Una consulta que falla es un fallo de la ejecución.

## Qué piden las licencias, y cómo se les responde { #what-the-licences-ask-and-how-it-is-answered }

Los recuentos de más abajo salen de los avisos en el momento de escribir esto; la
cifra actual es la del propio archivo de avisos.

| Familia de licencias | Componentes | Obligación | Cómo se cumple |
|---|---|---|---|
| MIT, ISC, BSD-2-Clause, BSD-3-Clause, 0BSD, MIT-0, MIT-CMU, Unlicense | unos 400 | Conservar el aviso de copyright y el texto de la licencia junto con las copias | El archivo de licencia de cada paquete viaja dentro de la imagen, al lado del código: el `*.dist-info/` de cada wheel en la imagen del backend, y el archivo de licencia de cada paquete bajo `/app/licenses/node_modules/<name>/` en la del frontend. Los avisos los indexan |
| Apache-2.0 | unos 90 | El texto de la licencia, el aviso de los cambios y cualquier archivo `NOTICE` que lleve el paquete | Igual que arriba; no se modifica nada, así que no hay cambios de los que avisar |
| PSF-2.0, CNRI-Python, Zlib, CC0-1.0 | unos pocos | Atribución o nada | Igual que arriba |
| MPL-2.0 (`certifi`, `pathspec`, `tqdm`, parte de `orjson`) | 4 | Copyleft por archivo: los archivos cubiertos siguen bajo MPL y su código fuente está disponible | Se usan sin modificar; el texto de la licencia viaja con ellos; los avisos enlazan el código fuente |
| LGPL-3.0-or-later (`psycopg2-binary`, `@img/sharp-libvips-linux-*`) | 3 | Texto de la licencia, disponibilidad del código fuente y la posibilidad de sustituir la biblioteca | Ambos son binarios instalados por separado y cargados dinámicamente, sin modificar, sustituibles reinstalándolos; el código fuente va enlazado en los avisos. Los paquetes de libvips no publican archivo de licencia, así que la imagen coloca el texto de la LGPL junto a ellos |
| Artistic-1.0-Perl o GPL-2.0-or-later (`text-unidecode`) | 1 | Dual; se toma bajo la Artistic License: aviso y texto | El archivo de licencia del wheel viaja con él |
| CC-BY-4.0 (`caniuse-lite`) | 1 | Atribución y un enlace al código fuente | Aparece nombrado con su fuente en los avisos |
| AGPL-3.0-only (`pymupdf`) | 1 | Copyleft de red: la imagen se transmite bajo los términos de la AGPL-3.0 y un despliegue modificado les debe a sus usuarios el código fuente modificado (art. 13) | Se mantiene deliberadamente y los términos se declaran: [la sección de abajo](#the-agpl-component) y el `COPYING` del wheel dentro de la imagen |
| OFL-1.1 (Inter, Bricolage Grotesque, Geist Mono) | 3 familias | Texto de la licencia y avisos de copyright junto con las tipografías; no vender las tipografías por sí solas; no reutilizar los nombres reservados para tipografías modificadas | `frontend/src/app/fonts/OFL.txt` lleva los tres avisos; las tipografías se sirven sin modificar |
| CC0-1.0, CC-BY-4.0, MIT (glifos de marca) | 3 fuentes | Atribución para los iconos de Font Awesome; las marcas siguen siendo marcas registradas de sus dueños | `NOTICE` nombra las fuentes y la posición sobre las marcas registradas |

**De un paquete que no publica archivo de licencia** no se puede copiar ninguno.
Varios paquetes npm del cierre son así, `@img/sharp-libvips-linux-x64` y su gemelo
de arm64 entre ellos: una biblioteca LGPL sin una copia de la LGPL en el tarball.
También lo son nueve wheels, `tokenizers` y `liteparse` entre ellos. Para cada
paquete npm, `frontend/scripts/collect-licenses.ts` escribe un `NOTICE` que nombra
el paquete, su licencia declarada, su autor y su repositorio, y copia el texto de
cada licencia de su expresión desde `frontend/licenses/texts/`. La imagen del
backend lleva esos mismos textos bajo `/app/licenses/texts/`, y el `METADATA` de
cada wheel ya nombra su licencia y su autor. Una licencia sin texto ahí hace
fallar la construcción de la imagen del frontend, y `make licenses-check` falla
antes, en la pull request, para cualquiera de las dos imágenes. De un paquete que
tampoco nombra autor, `client-only`, el titular del copyright queda registrado en
`licenses/policy.toml` bajo `notices`, con la evidencia, y el archivo de avisos lo
lleva.

Las imágenes base merecen una frase aparte. `python:3.12-slim` y `oven/bun:1` son
Debian, lo que significa cientos de paquetes bajo términos GPL, LGPL, MIT y BSD.
Debian guarda la licencia de cada paquete en
`/usr/share/doc/<package>/copyright` dentro de la imagen y publica el código
fuente correspondiente de cada binario que distribuye, que es en lo que se apoya
la obligación de código fuente de la GPL y la LGPL para una imagen redistribuida.

La imagen del backend añade LibreOffice (MPL-2.0) y Tesseract (Apache-2.0) como
paquetes Debian, usados sin modificar y como procesos separados. El SBOM por
release previsto en
[#1415](https://github.com/vstorm-co/agenticos/issues/1415) registrará el conjunto
exacto de paquetes de cada imagen; hasta que llegue, los Dockerfiles y los digests
de las imágenes base son el inventario de esa capa.

## El componente AGPL { #the-agpl-component }

Un componente de la imagen del backend está bajo un copyleft de red, y es la única
licencia del conjunto que le pide algo a un despliegue y no solo a nosotros.

`pymupdf` tiene licencia dual: AGPL-3.0-only o una licencia comercial de Artifex.
Es el parser de PDF por defecto y el único de los tres que extrae las imágenes
incrustadas para describirlas. La AGPL es compatible en un solo sentido con
Apache-2.0: nuestro código se puede combinar con él, y la imagen resultante pasa
entonces a transmitirse bajo los términos de la AGPL-3.0.

En [#1602](https://github.com/vstorm-co/agenticos/issues/1602) se sopesó
descartarlo en favor de LiteParse (Apache-2.0, ya una dependencia), ponerlo detrás
de una opción que haya que activar, y mantenerlo declarando los términos. **Se
mantiene, y los términos se declaran aquí.** Qué significa eso en la práctica:

- **Ejecutar una release sin modificar.** No se debe nada. AgenticOS es público y
  Apache-2.0, así que el código fuente al que apuntaría una oferta del artículo 13
  ya está publicado.
- **Modificar la plataforma y servirla por red** — el caso al que invita un
  producto autoalojado. El artículo 13 de la AGPL-3.0 obliga a ese despliegue a
  ofrecer a sus usuarios el código fuente modificado del conjunto. Esta es la
  obligación que hay que leer antes de hacer un fork privado, y es por la que
  preguntará una revisión de seguridad.
- **Un despliegue que no pueda aceptar esos términos** tiene tres salidas: comprar
  la licencia comercial de Artifex, poner el parser de PDF de la colección en
  `liteparse` y quitar la dependencia en una build privada, o mantener sus cambios
  sin publicar pero disponibles para sus propios usuarios, que es lo que el
  artículo 13 pide en realidad.

Nada más en ninguna de las dos imágenes lleva un copyleft que alcance más allá de
sus propios archivos.

## Hallazgos abiertos { #open-findings }

Cada uno tiene una issue; cada uno seguirá en esta lista, y a la cabeza de los
avisos, hasta que la issue se cierre y la entrada de la política pase a `accepted`,
o hasta que el componente desaparezca.

Un hallazgo se cerró sustituyendo el componente, no aceptándolo. `redis:7-alpine`
resuelve a Redis 7.4, y desde 7.4.0 Redis está bajo RSALv2 o SSPL-1.0 en lugar de
BSD-3-Clause — ninguna de las dos está aprobada por la OSI. Nada se incumplía por
ello: la imagen la descarga el operador en lugar de redistribuirse aquí, y RSALv2
permite ejecutar Redis dentro de tu propia aplicación, que es lo que hace este
stack. El hallazgo era que un `docker compose up` por defecto arrancaba un
componente no abierto sin decirlo.

[#1603](https://github.com/vstorm-co/agenticos/issues/1603) lo cambió por
`valkey/valkey:8-alpine`, el fork de Redis 7.2 de la Linux Foundation bajo
BSD-3-Clause. Valkey habla el mismo protocolo, así que el nombre del servicio, el
puerto, el esquema de URL `redis://` y todos los ajustes `REDIS_*` no cambian.

**El runtime `workbench` de la sandbox se construye en el despliegue** a partir de
`sandbox_runtimes.json`: Python, Node, LibreOffice, `poppler-utils` (GPL) y una
lista de paquetes de PyPI resueltos al construirlo. Este proyecto no lo publica
nunca, así que no hay nada que redistribuir y las herramientas GPL se ejecutan como
procesos separados. Queda registrado como `deployment-review`: un despliegue que
pase a publicar la imagen construida debe las ofertas de código fuente de esa
imagen.

## Servicios alojados y términos de los providers { #hosted-services-and-provider-terms }

La API de un provider de modelos, Logfire, Tavily, Brave, Exa, LlamaParse, Mem0,
Daytona, Google Drive y S3 no son software que este proyecto distribuya y no tienen
licencia en el sentido de arriba. Cada uno es un acuerdo de servicio entre el
despliegue y el provider, que se contrae cuando un administrador guarda la
credencial de ese provider en el [vault](secrets.md). Los términos que importan
para una revisión son los del provider: qué pasa con los prompts y los documentos
que se le envían, si entrena con ellos, dónde se procesan los datos y cuánto tiempo
se conservan.

Eso es una cuestión de protección de datos y no de licencias, y se responde por
despliegue, no aquí. Los SDK que hablan con esos servicios son paquetes normales de
los avisos: los clientes de Anthropic, OpenAI, Google, Mistral, Cohere, Groq y xAI
son todos MIT o Apache-2.0.

## Pesos de modelos { #model-weights }

Ninguna de las dos imágenes lleva pesos de modelos. Un despliegue elige los modelos
en [perfiles de modelo](models.md); a un modelo cerrado se llega por la API de su
provider y bajo los términos de ese provider, y un modelo de pesos abiertos lo
descarga el despliegue bajo la licencia que le haya puesto quien lo publica. Esas
licencias difieren entre sí más que las de software, y varias no son open source
según la definición de la OSI aunque los pesos se puedan descargar libremente.

| Familia | Licencia, tal como se publica con los pesos | Qué comprobar antes de elegirla |
|---|---|---|
| Qwen 2.5 y 3 (la mayoría de tamaños), Mistral 7B y Nemo, GPT-OSS, DeepSeek V3 y R1, Phi-4 | Apache-2.0 o MIT | Solo atribución. Algunos tamaños grandes de Qwen 2.5 llevan en cambio la licencia de Qwen; lee la model card |
| Llama 3.x | Llama Community License | No es open source: una política de uso aceptable, una atribución "Built with Llama" y una licencia aparte por encima de cierto umbral de usuarios activos mensuales |
| Gemma | Gemma Terms of Use | No es open source: una política de usos prohibidos que se traslada a los derivados |
| Mistral Large y algunas releases de Codestral | Mistral Research License o una licencia comercial | Solo uso de investigación y no comercial, salvo que se licencie |

La tabla es orientación, no evidencia: las licencias de los modelos cambian de una
release a otra y la model card de quien lo publica es el documento que manda. La
página de [elegir un modelo](choosing-models.md#closed-models-or-open-weights)
tiene el lado de ingeniería de esa misma decisión.

!!! tip "Registra la decisión donde se configura el modelo"

    La descripción de un perfil de modelo es un buen sitio para nombrar la
    licencia bajo la que se tomaron los pesos y la fecha en que se comprobó. Viaja
    con el perfil a cada entorno y a cada agent que lo use.

## Componentes propios de cada cliente { #client-specific-components }

El stack propio de un despliegue añadirá componentes que este inventario no puede
ver: el modelo que aloje él mismo, los servidores MCP que conecte, una base de
datos o un Redis gestionados en lugar de los servicios de compose, un proxy
inverso, un proveedor de identidad. Cada uno necesita las mismas tres líneas que
tienen las tablas de arriba — componente, licencia, obligación — antes de que la
revisión de ese despliegue esté completa. Los valores por defecto del camino de
compose están registrados en `licenses/components.toml` bajo `deployment-review` y
`service image`, que es también donde encajan las filas propias de un despliegue,
en su fork o en su repositorio de despliegue.

## Que siga siendo verdad { #keeping-it-true }

La comprobación se ejecuta en cada pull request dentro del job `security` y en
`make check`, así que el flujo de mantenimiento consiste sobre todo en que la
comprobación se niega a pasar.

**Cambia una dependencia.** Dependabot o `make deps-upgrade` mueven un lockfile; el
job `security` falla con `THIRD_PARTY_NOTICES.md is stale`. Ejecuta
`make licenses`, lee el diff, haz commit. Si el diff añade un componente sin
licencia, o uno del conjunto de revisión, la comprobación nombra la entrada de la
política que hay que escribir, y la pull request lleva la decisión al lado de la
actualización que la necesitaba.

**Cambia una licencia.** Un componente revisado bajo una licencia resuelve a otra
después de una actualización; la comprobación dice
`reviewed as X but resolves to Y - review it again`. La decisión antigua no
sobrevive por sí sola.

**Se cierra un hallazgo.** La entrada de la política pasa de `open` a `accepted`
con un `fulfilled_by`, o el componente se elimina y la comprobación pide que la
entrada se vaya. Regenera los avisos; el hallazgo deja de estar al principio del
archivo.

**Cambia un modelo o un servicio.** Nada se mueve en los lockfiles, así que no
falla nada. Lo que hay que actualizar es la tabla de modelos de arriba, la
descripción del perfil de modelo y las filas de componentes propias del despliegue,
y quien lo pide es la lista de comprobación de la release.

**Cambia una imagen.** Una etiqueta base nueva, un paquete Debian añadido, un
servicio de compose nuevo: `licenses/components.toml` se edita en el mismo cambio,
y `scripts/docs_drift.py` lo recuerda cuando se mueve un Dockerfile y esta página
no.

## Lista de comprobación de la release { #release-checklist }

Antes de cortar una release, y como evidencia adjunta a ella:

- [ ] `make licenses-check` pasó en el commit de la release; la línea del veredicto
  está en el resumen del job `security`
- [ ] El `THIRD_PARTY_NOTICES.md` de ese commit son los avisos de la release; ambas
  imágenes llevan sus archivos de licencia (`/app/THIRD_PARTY_NOTICES.md` y
  `.venv/**/*.dist-info/` y `/app/licenses/texts/` en la imagen del backend;
  `/app/licenses/` en la del frontend, con `NOTICE`, `OFL.txt` y un directorio por
  paquete)
- [ ] Los hallazgos abiertos de los avisos son los que lista esta página, cada uno
  con una issue que sigue siendo la correcta
- [ ] `licenses/components.toml` nombra las etiquetas de imagen y los servicios de
  compose que la release usa de verdad
- [ ] Si se añadió una familia de modelos al catálogo o a la tabla de modelos de
  arriba, su licencia se leyó de la model card actual
- [ ] Cuando exista el SBOM por release de #1415: está adjunto a la release y su
  conjunto de componentes coincide con los avisos de las dos imágenes

## Resumen { #recap }

- Las imágenes distribuyen unos quinientos paquetes de terceros, casi todos MIT,
  Apache-2.0 o BSD; el archivo de licencia de cada paquete viaja con él y
  `THIRD_PARTY_NOTICES.md` es el índice generado.
- Las decisiones viven en `licenses/policy.toml` y `licenses/components.toml`; la
  comprobación falla ante cualquier cosa que no tenga una, y ante una decisión
  tomada sobre una licencia que ha cambiado desde entonces.
- Hay un hallazgo abierto y del que se hace seguimiento: el runtime de la sandbox
  construido en el despliegue. Otros dos se zanjaron en lugar de quedarse abiertos
  — la AGPL de PyMuPDF, revisada y mantenida, con una sección propia, y la imagen
  de Redis, sustituida por Valkey.
- Los pesos de modelos y los providers alojados se eligen por despliegue bajo los
  términos de quien los publica o los presta; esta página dice qué comprobar, y el
  despliegue registra qué eligió.
