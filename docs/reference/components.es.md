---
source_sha: "1ad52431d0bf"
---

# El inventario de componentes { #the-component-inventory }

De qué está hecho un despliegue de AgenticOS: las partes que escribe este
proyecto, los paquetes de terceros de los que dependen, las imágenes en las que
se ejecutan, los recursos que incluyen y los modelos y servicios que un operador
conecta después. Es la mitad legible del SBOM de la versión y la respuesta a
«qué hay dentro» cuando esa pregunta llega desde una revisión de seguridad y no
desde un sistema de compilación.

!!! abstract "Qué cubre esta página y dónde se detiene"

    Todo hasta *Recursos incluidos* lo entrega este proyecto y está enumerado con
    exactitud, a partir de los ficheros lock y de los Dockerfile. Todo lo que
    viene después — los modelos, los providers, los servidores MCP, las bases de
    datos a las que el operador apunta el despliegue — se elige por despliegue,
    no se entrega aquí y solo puede enumerarlo el despliegue que lo eligió. La
    última sección explica cómo anotar esa mitad; esta página no puede
    escribirla por usted.

El inventario legible por máquina se adjunta a cada versión como
`sbom-api.cdx.json` y `sbom-frontend.cdx.json`, en
[CycloneDX](https://cyclonedx.org/) 1.6 JSON. La evidencia de licencia de cada
componente está en
[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md),
y la revisión de lo que esas licencias obligan está en [Licencias y avisos de
terceros](../licenses.md).

## La versión que describe este inventario { #the-release-this-inventory-describes }

Un inventario sin versión no describe nada. Cada versión lleva la suya: los
documentos SBOM en la release de GitHub de la etiqueta `vX.Y.Z`, generados a
partir de las imágenes publicadas bajo esa etiqueta, y esta página tal como
estaba en el árbol de esa etiqueta. Un despliegue que lea el inventario de la
versión que ejecuta debería leer ambos desde la misma etiqueta y no desde `main`.

| Artefacto | Dónde está | Qué nombra su versión |
|---|---|---|
| `sbom-api.cdx.json` | los recursos de la release de GitHub | la etiqueta `v*` a la que se adjunta |
| `sbom-frontend.cdx.json` | los mismos | lo mismo |
| `ghcr.io/vstorm-co/agenticos-backend` | GHCR | `<version>`, `latest`, `edge`, `sha-<short>` |
| `ghcr.io/vstorm-co/agenticos-frontend` | GHCR | lo mismo |
| `THIRD_PARTY_NOTICES.md` | el repositorio, en esa etiqueta | los ficheros lock en ese commit |

## Componentes que escribe este proyecto { #components-this-project-writes }

Desarrollo propio, Apache-2.0, en este repositorio. Nada de esto es un componente
de terceros y nada aparece en los avisos.

| Componente | Dónde | Qué es | Se entrega en |
|---|---|---|---|
| API y plataforma | `backend/app` | La aplicación FastAPI: routes, services, repositories, el runner de agents, el registro de capabilities | `agenticos-backend` |
| Worker en segundo plano | `backend/app/worker` | El runner de Prefect para ingesta, sincronizaciones, barridos y disparadores programados | `agenticos-backend` |
| Migraciones | `backend/alembic` | La cadena de esquema, aplicada por el servicio de migración antes de que arranque la API | `agenticos-backend` |
| Línea de comandos | `backend/app/commands` | `agenticos cmd …` — bootstrap, doctor, los comandos de RAG | `agenticos-backend` |
| Consola | `frontend/src` | La aplicación Next.js que ven un operador y un usuario | `agenticos-frontend` |
| Shell de escritorio | `desktop/` | Una ventana Tauri alrededor de la consola de un despliegue, compilada por plataforma | no es una imagen; véase [la aplicación de escritorio](../desktop.md) |
| Sitio de documentación | `docs/`, `mkdocs.yml` | Este sitio | no se entrega en ninguna de las dos imágenes |

## Dependencias de terceros { #third-party-dependencies }

Resueltas desde ficheros lock, no desde lo que una máquina tenga instalado. Las
cifras cambian con cada modificación de dependencias, así que la cifra fiable es
la del fichero de avisos de la versión que esté leyendo.

| Conjunto | Fichero lock | Resuelto para | En los avisos |
|---|---|---|---|
| Distribuciones Python del backend | `backend/uv.lock` | Linux, ambas arquitecturas, `--no-dev` | Sí |
| Paquetes npm del frontend | `frontend/bun.lock` | el cierre de producción de `frontend/package.json` | Sí |
| Herramientas de desarrollo y documentación del backend | `backend/uv.lock`, los grupos `dev` y `docs` | la máquina de quien contribuye | No: no están en ninguna imagen |
| `devDependencies` del frontend | `frontend/bun.lock` | la máquina de quien contribuye | No: no están en la imagen |
| Crates de Rust de la shell de escritorio | `desktop/src-tauri/Cargo.lock` | la plataforma para la que se compila la shell | No: no están en ninguna imagen |

Dos auditorías leen estos ficheros lock en cada pull request. `make audit`
resuelve `backend/uv.lock` y lo contrasta con la base de datos de avisos;
`make audit-frontend` ejecuta `bun audit --audit-level=high` sobre
`frontend/bun.lock`. Ambas están en el trabajo `Security Scan` y en `make check`.

## Imágenes de ejecución { #runtime-images }

| Imagen | Base | Contiene | La compila |
|---|---|---|---|
| `agenticos-backend` | una imagen de Python basada en Debian | la API, el worker, las migraciones, la CLI, el cierre de dependencias del backend, los textos de licencia | `backend/Dockerfile` |
| `agenticos-frontend` | una imagen de Node basada en Debian | la compilación standalone de la consola, su cierre de dependencias de producción, las fuentes, los avisos por paquete | `frontend/Dockerfile` |

Ambas se compilan para `amd64` y `arm64`, se publican en GHCR y se escanean con
Trivy después de publicarse. Los paquetes Debian que instala cada imagen están
registrados en `licenses/components.toml` con su posición de licencia y aparecen
en los documentos CycloneDX, porque el generador lee la imagen publicada y no el
árbol de fuentes.

Los servicios que un despliegue ejecuta junto a estas dos — PostgreSQL con
pgvector, Redis, un proxy inverso, un servidor de Prefect — los descarga el
operador de sus propios editores. Están nombrados en los ficheros compose, no se
compilan aquí y no están en el SBOM de este proyecto.

## Recursos incluidos { #bundled-assets }

| Recurso | Dónde | Procedencia |
|---|---|---|
| Fuentes de la interfaz | `frontend/src/app/fonts/` | Inter, Bricolage Grotesque, Geist Mono, todas OFL-1.1 |
| Glifos de marcas y providers | `frontend/src/components/brand/`, `backend/app/core/catalog/icons/` | Font Awesome, Simple Icons y marcas dibujadas a mano; las fuentes las nombra `NOTICE` |
| El catálogo de servidores MCP | `backend/app/core/catalog/` | Datos propios de este proyecto sobre servidores de terceros, no los servidores |
| Valores por defecto de los perfiles de modelo | `backend/app/core/catalog/` | Datos propios de este proyecto; los modelos nunca se entregan |

## Modelos, providers y servicios: la mitad del despliegue { #models-providers-and-services-the-deployments-half }

Nada de lo siguiente forma parte de una versión, y ningún SBOM generado aquí
puede enumerarlo. Cada punto es un componente del sistema en marcha y pertenece
al inventario propio del despliegue.

- **Providers de modelos.** Los de Anthropic, OpenAI, Google, Groq, xAI, Cohere,
  un endpoint compatible con OpenAI o un runtime local que el despliegue
  configure, con los identificadores de modelo que fije. Véase
  [modelos](../models.md).
- **Pesos de los modelos.** Un runtime local los descarga; revisar sus licencias
  corresponde al operador, y [la revisión de licencias](../licenses.md) explica
  por qué.
- **Servidores MCP.** Procesos de terceros o endpoints alojados, conectados por
  organización. El catálogo nombra candidatos; una instalación es un componente.
- **Fuentes de conocimiento y conectores.** Google Drive, S3 y el resto, cada uno
  un servicio de terceros al que se llega con un secreto del vault.
- **Canales.** Los espacios de Slack, Telegram y Mattermost en los que el
  despliegue está registrado.
- **Almacenes de datos e infraestructura.** PostgreSQL, Redis, almacenamiento de
  objetos, el proxy inverso, el host y el endpoint de observabilidad que reciba
  las trazas.

!!! warning "El SBOM de una imagen no es un inventario del sistema"

    Los dos documentos CycloneDX describen dos imágenes. Un despliegue que
    conecta un modelo alojado, tres servidores MCP y un almacenamiento de objetos
    ejecuta componentes que ningún escaneo de esas imágenes puede ver. Tomar el
    SBOM de la versión por el inventario completo es la laguna que esta sección
    existe para nombrar.

## Cómo se produce el inventario y cómo se mantiene al día { #how-the-inventory-is-produced-and-kept-current }

| Artefacto | Lo produce | Cuándo |
|---|---|---|
| `sbom-api.cdx.json`, `sbom-frontend.cdx.json` | el trabajo `sbom` en `.github/workflows/images.yml`, a partir de los manifiestos publicados | en cada publicación; se adjunta a la release con una etiqueta `v*` |
| `THIRD_PARTY_NOTICES.md` | `make licenses` | cuando cambia un fichero lock; `make licenses-check` hace fallar la compilación si está desactualizado |
| Esta página | a mano | cuando un componente se añade, se elimina o pasa de uno de los conjuntos anteriores a otro |

En local, `make sbom` escribe los mismos documentos CycloneDX desde el árbol de
fuentes y no desde una imagen. Necesita [syft](https://github.com/anchore/syft)
instalado, deliberadamente no forma parte de `make check`, y su salida se
diferencia de los documentos de la versión en exactamente un punto que conviene
conocer: no hay capas de la imagen base, porque no hay imagen.

Para ampliar el inventario de un despliegue, tome el SBOM de la versión que
ejecuta, añada los componentes de la sección anterior con la versión y el
proveedor de cada uno, y guárdelo junto a la configuración propia del despliegue.
La [revisión de seguridad](../rollout.md) es donde el revisor de un cliente lo
pide, y [protección de datos](../data-protection.md) es donde están anotados los
datos que toca cada uno de esos componentes.
