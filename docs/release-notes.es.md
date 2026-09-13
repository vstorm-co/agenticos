---
source_sha: 88fd384cb2a0
---

# Notas de versión { #release-notes }

Cada cambio destacable de AgenticOS, el más reciente primero. Esta página *es*
[`CHANGELOG.md`](https://github.com/vstorm-co/agenticos/blob/main/CHANGELOG.md)
del repositorio — se lee en el momento del build en lugar de copiarse, así que
el archivo y la página no pueden separarse. Las entradas en sí se quedan en
inglés, porque son el historial de commits.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y las
versiones siguen [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Hay dos cosas que se versionan aparte de la lista de abajo.

!!! info "`SPEC_VERSION`"

    El formato del spec del agent. Un agent publicado y el YAML exportado de un
    cliente lo llevan los dos, así que solo avanza hacia adelante y solo con una
    migración que mantenga cargables los documentos antiguos. Consulta
    [la referencia del spec](reference/spec.md).

!!! info "La cadena de migraciones"

    `backend/alembic/versions/`, comprimida en un único `0001_baseline`. Los ids
    de revisión que se nombran más abajo describen *cuándo* cambió algo, no un
    archivo que siga existiendo — los cambios de esquema se listan por lo que
    hacen.

<div class="agenticos-release-notes" markdown>

<!-- changelog -->

</div>
