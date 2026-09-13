---
source_sha: 88fd384cb2a0
---

# Versionshinweise { #release-notes }

Jede nennenswerte Änderung an AgenticOS, die neueste zuerst. Diese Seite *ist*
[`CHANGELOG.md`](https://github.com/vstorm-co/agenticos/blob/main/CHANGELOG.md)
aus dem Repository — zur Build-Zeit gelesen statt kopiert, damit Datei und Seite
nicht auseinanderlaufen können. Die Einträge selbst bleiben englisch, denn sie
sind die Commit-Historie.

Das Format folgt [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), die
Versionen folgen [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Zwei Dinge werden getrennt von der Liste unten versioniert.

!!! info "`SPEC_VERSION`"

    Das Format des Agent-Specs. Ein veröffentlichter Agent und das exportierte
    YAML eines Kunden tragen es beide, deshalb bewegt es sich nur vorwärts, und
    nur mit einer Migration, die alte Dokumente weiterhin ladbar hält. Siehe
    [die Spec-Referenz](reference/spec.md).

!!! info "Die Migrationskette"

    `backend/alembic/versions/`, zusammengefasst auf ein einziges
    `0001_baseline`. Unten genannte Revisions-Ids beschreiben, *wann* sich etwas
    geändert hat, nicht eine Datei, die es noch gibt — Schemaänderungen sind
    danach aufgeführt, was sie tun.

<div class="agenticos-release-notes" markdown>

<!-- changelog -->

</div>
