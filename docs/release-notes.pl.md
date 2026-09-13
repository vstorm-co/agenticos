---
source_sha: 88fd384cb2a0
---

# Informacje o wydaniach { #release-notes }

Każda istotna zmiana w AgenticOS, od najnowszej. Ta strona *jest*
plikiem [`CHANGELOG.md`](https://github.com/vstorm-co/agenticos/blob/main/CHANGELOG.md)
z repozytorium — czytanym w czasie budowania, a nie kopiowanym, więc plik i
strona nie mogą się rozjechać. Wpisy pozostają po angielsku, bo są historią
commitów.

Format jest zgodny z [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), a
wersje z [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dwie rzeczy są wersjonowane niezależnie od poniższej listy.

!!! info "`SPEC_VERSION`"

    Format speca agenta. Niesie go zarówno opublikowany agent, jak i wyeksportowany
    przez klienta YAML, więc przesuwa się wyłącznie do przodu i tylko wraz z
    migracją, która pozwala starym dokumentom dalej się wczytywać. Zobacz
    [referencję speca](reference/spec.md).

!!! info "Łańcuch migracji"

    `backend/alembic/versions/`, zgnieciony do pojedynczego `0001_baseline`.
    Identyfikatory rewizji wymienione niżej opisują, *kiedy* coś się zmieniło, a
    nie plik, który nadal istnieje — zmiany schematu są wypisane przez to, co
    robią.

<div class="agenticos-release-notes" markdown>

<!-- changelog -->

</div>
